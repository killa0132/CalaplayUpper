# -*- coding: utf-8 -*-
"""CP-37: append our per-background thumbnails into the game's own preview atlas.

Design + evidence: ``docs/CP37_ATLAS_MI_STRATEGY_ASSESSMENT.md`` (and ``CP36_ATLAS_APPEND_DESIGN.md``).

What this module does -- and the two things it deliberately does NOT do
----------------------------------------------------------------------
* The atlas ``/Game/CalaPlayer/UI/EditorUI/Textures/T_BackgroundPreviews`` is the game's own
  cooked ``Texture2D``.  We replace **only the BC1 blocks that cover "our" cells** (index 165..223,
  the free right/bottom band measured at 4096x2048 / 16x14 grid / 165 occupied) inside **every**
  mip payload.  Same length, same mip count, same format, in place.
* Therefore the uasset is **not touched at all**: no ``SerialSize`` fix, no Zen ``BulkDataMap``
  rewrite, no count field.  (Route B needed all three because it *changed the size*; this does not.)
* The 165 native thumbnails keep their pixels.  ``embed()`` re-verifies that claim block by block
  and pixel by pixel (``verify()``) so "no native pollution" is a measurement, not a promise.

Policy **P1** (user ruling 2026-09-26): a block that straddles our cell keeps the *original decoded*
pixels outside the cell rectangle and gets our content inside it.  Consequence, measured in the
assessment §6: at **mip0** every block we touch holds only our cell + the 2 px black gap, so all 165
native thumbnails stay byte identical; at **mips >= 1** the cell origin is no longer 4-aligned and
16 cells (index 165..175 row 10 + 176..180 row 11 cols 0..4) share a one-block seam with a native
neighbour -- those blocks are re-encoded from the original decoded pixels, so the only difference
there is BC1 re-encode error, which ``verify()`` measures and reports per mip.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .bc1 import bc1_encode, bc1_size, decode_bc1, quality
from .common import BuildError, Log
from .texture import TAG, TAIL_ZEROS, mip_table, parse_mips, locate_mips

CELL_W, CELL_H = 250, 141            # the game's own cell size (measured)
STRIDE_X, STRIDE_Y = 252, 143        # the game's own stride = cell + 2 px gap
COLS, ROWS = 16, 14                  # 4096x2048 with that stride -> 16 x 14 = 224 slots
SLOTS = COLS * ROWS
NATIVE_CELLS = 165                   # occupied by the game: rows 0..9 (160) + row 10 cols 0..4 (5)
MAX_ATLAS_BG = SLOTS - NATIVE_CELLS  # 59 free cells, index 165..223


def cell_origin(index: int) -> Tuple[int, int]:
    """The game's own grid formula (its native MIs use exactly this)."""
    return (index % COLS) * STRIDE_X, (index // COLS) * STRIDE_Y


def thumbnail_of(src, fit_note_prefix: str = "") -> Tuple[np.ndarray, str]:
    """Source image (PIL, RGB) -> the 250x141 preview tile, cover-fitted like the background."""
    from .bc1 import fit_image
    tile, note = fit_image(src, (CELL_W, CELL_H), "cover")
    return np.asarray(tile.convert("RGB"), dtype=np.uint8), fit_note_prefix + note


def tile_from_canvas(canvas) -> np.ndarray:
    """The fitted TARGET_W x TARGET_H canvas -> the tile this background's cell receives.

    Taken from the canvas rather than from the source file so the tile shows exactly the framing the
    background itself shows (the -Fit cover crop or the -Fit contain letterbox included).
    """
    from PIL import Image
    im = canvas.convert("RGB").resize((CELL_W, CELL_H), Image.LANCZOS)
    return np.asarray(im, dtype=np.uint8)


def stage_atlas(base_uexp: str, base_uasset: str,
                cells: Sequence[Tuple[int, np.ndarray]], out_dir: str, log: Log,
                stage: str = "L2b", dump_sizes: Optional[Sequence[int]] = None) -> Dict:
    """Copy the atlas into ``out_dir``, embed every (index, tile), prove it, report.

    Returns ``{"uexp","uasset","bytes","plan","cells":[...],"quality":[...],"a9":{...},"sha256"}``.
    The uasset is copied verbatim (equal-length pixel work never touches it) and that is asserted.
    """
    import hashlib
    import os
    import shutil
    if not cells:
        raise BuildError(stage, "stage_atlas was called with no cells")
    os.makedirs(out_dir, exist_ok=True)
    dst_uexp = os.path.join(out_dir, os.path.basename(base_uexp))
    dst_uasset = os.path.join(out_dir, os.path.basename(base_uasset))
    shutil.copyfile(base_uexp, dst_uexp)
    shutil.copyfile(base_uasset, dst_uasset)
    orig = open(dst_uexp, "rb").read()
    ua_before = open(dst_uasset, "rb").read()
    plan = parse_plan(dst_uexp, log, stage, dump_sizes)
    data = bytearray(orig)
    reps = []
    for index, tile in cells:
        reps.append(embed(data, plan, index, tile, log, stage))
    if len(data) != len(orig):
        raise BuildError(stage, "the atlas changed length (%d -> %d)" % (len(orig), len(data)))
    v = verify(orig, bytes(data), plan, [i for i, _t in cells], log, stage)
    q = [dict(cell_quality(bytes(data), plan, index, tile, log, stage), index=index)
         for index, tile in cells]
    if open(dst_uasset, "rb").read() != ua_before:
        raise BuildError(stage, "the atlas uasset changed (it must not: equal-length pixel work)")
    open(dst_uexp, "wb").write(bytes(data))
    back = open(dst_uexp, "rb").read()
    if len(back) != len(orig):
        raise BuildError(stage, "the written atlas does not read back at %d B" % len(orig))
    if hashlib.sha256(back).digest() == hashlib.sha256(orig).digest():
        raise BuildError(stage, "the atlas is byte identical to the original: nothing was embedded")
    log(stage, "  atlas staged: %s (%d B, %d cell(s), uasset untouched)"
        % (os.path.basename(dst_uexp), len(back), len(cells)))
    return {"uexp": dst_uexp, "uasset": dst_uasset, "bytes": len(back), "plan": plan,
            "cells": reps, "quality": q, "a9": v,
            "sha256": hashlib.sha256(back).hexdigest()}


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------
@dataclass
class AtlasPlan:
    width: int
    height: int
    uexp_len: int
    header_len: int
    mips: List[Tuple[int, int, int, int, int, int]] = field(default_factory=list)
    #                     (index, offset, size, w, h, block_stride)

    def mip_dims(self) -> List[Tuple[int, int]]:
        return [(m[3], m[4]) for m in self.mips]


def parse_plan(uexp_path: str, log: Log, stage: str = "L1",
               dump_sizes: Optional[Sequence[int]] = None) -> AtlasPlan:
    """Read the atlas framing out of the file itself and verify every byte of the model.

    The atlas is *located structurally* rather than by a tex-inspect head signature, because a
    ``-Combined`` build starts from **our own previous atlas**, whose lowest mips (the cell is the
    whole 1x1/2x1/4x2 level) are already rewritten - a head search would refuse those.  Instead we
    scan for the 16 B record that follows mip0 - ``(SizeX, SizeY, 1, 1)`` - and then demand that the
    whole chain (shift rule + one 16 B record per level + 8 zero bytes + PACKAGE_FILE_TAG) accounts
    for the file length **exactly**.  Together with the per-level record check in the loop below that
    is a much stronger statement than "a 32 byte signature was found at offset X".

    ``dump_sizes`` (the mip sizes tex-inspect printed, when the caller has them) is cross-checked so a
    wrong asset cannot be silently accepted.
    """
    data = open(uexp_path, "rb").read()
    mip0, w, h = find_mip0(data, uexp_path, stage)
    table = mip_table(w, h)
    plan = AtlasPlan(width=w, height=h, uexp_len=len(data), header_len=mip0, mips=[])
    off = mip0
    for i, (_idx, size, x, y) in enumerate(table):
        if off + size + 16 > len(data):
            raise BuildError(stage, "mip%d at 0x%X runs past the end of the atlas" % (i, off))
        r = _record(data, off + size, stage)
        nxt = (i + 1) if (i + 1) < len(table) else 0
        if r != (x, y, 1, nxt):
            raise BuildError(stage, "mip%d's trailing record is %s, expected %s"
                             % (i, r, (x, y, 1, nxt)))
        plan.mips.append((i, off, size, x, y, (x + 3) // 4))
        off += size + 16
    if data[off:] != b"\x00" * TAIL_ZEROS + TAG:
        raise BuildError(stage, "the atlas tail is not 8 zero bytes + PACKAGE_FILE_TAG",
                         "%d trailing byte(s): %s" % (len(data) - off, data[off:off + 24].hex()))
    if (COLS - 1) * STRIDE_X + CELL_W > w or (ROWS - 1) * STRIDE_Y + CELL_H > h:
        raise BuildError(stage, "the %dx%d grid does not fit in %dx%d" % (COLS, ROWS, w, h))
    if dump_sizes is not None:
        got = [m[2] for m in plan.mips]
        if list(dump_sizes) != got:
            raise BuildError(stage, "the file's mip chain %s does not match tex-inspect's %s"
                             % (got, list(dump_sizes)))
    if b"PF_DXT1" not in data[:mip0]:
        log(stage, "  WARN: no PF_DXT1 in the atlas header - the structural model still holds")
    log(stage, "  atlas plan: %dx%d / %d mips / header %d B / payload %d B (models verified)"
        % (w, h, len(plan.mips), plan.header_len, sum(m[2] for m in plan.mips)))
    return plan


def _chain_check(data: bytes, head: int, w: int, h: int) -> bool:
    """True when the whole chain from `head` matches the shift rule and ends in the pack file tag."""
    table = mip_table(w, h)
    total = head
    for i, (_idx, size, x, y) in enumerate(table):
        if total + size + 16 > len(data):
            return False
        nxt = (i + 1) if (i + 1) < len(table) else 0
        if struct.unpack_from("<IIII", data, total + size) != (x, y, 1, nxt):
            return False
        total += size + 16
    return data[total:] == b"\x00" * TAIL_ZEROS + TAG


def find_mip0(data: bytes, uexp_path: str, stage: str) -> Tuple[int, int, int]:
    """Locate mip0 from the file length alone: for a WxH chain the header length is forced.

    ``len = header + sum(bc1 sizes) + 16 * mips + 28``  =>  header is a function of (W, H), and the
    record right after mip0 must read ``(W, H, 1, 1)``.  That makes the search a handful of integer
    checks instead of a byte scan, and it works on our own previous atlas too (equal length).
    """
    import os
    n = len(data)

    def try_dims(w: int, h: int):
        table = mip_table(w, h)
        payload = sum(t[1] for t in table)
        head = n - (payload + 16 * len(table) + TAIL_ZEROS + len(TAG))
        if not (0 < head < 8192) or head + table[0][1] + 16 > n:
            return None
        if struct.unpack_from("<IIII", data, head + table[0][1]) != (w, h, 1, 1):
            return None
        return (head, w, h) if _chain_check(data, head, w, h) else None

    cands = []
    pows = (128, 256, 512, 1024, 2048, 4096, 8192, 16384)
    for w in pows:
        for h in pows:
            got = try_dims(w, h)
            if got:
                cands.append(got)
    if not cands:                      # non power-of-two fallback: scan for the record pattern
        for p in range(32, n - 16):
            w = struct.unpack_from("<I", data, p)[0]
            h = struct.unpack_from("<I", data, p + 4)[0]
            if not (16 <= w <= 16384 and 16 <= h <= 16384) or w * h > (1 << 28):
                continue
            if struct.unpack_from("<II", data, p + 8) != (1, 1):
                continue
            head = p - bc1_size(w, h)
            if head > 0 and _chain_check(data, head, w, h):
                cands.append((head, w, h))
                break
    if len(cands) != 1:
        raise BuildError(stage, "could not pin down the atlas' mip0 (%d structural candidate(s))"
                         % len(cands),
                         "%s: %s -- refusing to touch an atlas whose layout this tool cannot "
                         "reproduce" % (os.path.basename(uexp_path), cands[:4]))
    return cands[0]


def _record(data: bytes, at: int, stage: str) -> Tuple[int, int, int, int]:
    if at + 16 > len(data):
        raise BuildError(stage, "record at 0x%X runs past the end of the atlas" % at)
    return struct.unpack_from("<IIII", data, at)


# ---------------------------------------------------------------------------
# embed (policy P1)
# ---------------------------------------------------------------------------
def _region_blocks(plan_mip, x0: int, y0: int, x1: int, y1: int):
    """Block-aligned rectangle covering the pixel rect (block coords, inclusive-exclusive)."""
    _i, _off, _size, _w, _h, bw = plan_mip
    bx0, by0 = x0 // 4, y0 // 4
    bx1, by1 = (x1 + 3) // 4, (y1 + 3) // 4
    return bx0, by0, bx1, by1, bw


def _mip_cell_rect(cell_x: int, cell_y: int, k: int) -> Tuple[int, int, int, int]:
    """The cell's pixel rectangle inside mip k (engine shift rule, same as mip_table)."""
    x0, y0 = cell_x >> k, cell_y >> k
    x1, y1 = (cell_x + CELL_W) >> k, (cell_y + CELL_H) >> k
    return x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)


def embed(data: bytearray, plan: AtlasPlan, index: int, tile: np.ndarray,
          log: Log, stage: str = "L1") -> Dict:
    """Write one 250x141 tile into the atlas' cell ``index`` across every mip.  Returns a report."""
    from PIL import Image
    if tile.shape[0] != CELL_H or tile.shape[1] != CELL_W:
        raise BuildError(stage, "tile is %dx%d, the atlas cell is %dx%d"
                         % (tile.shape[1], tile.shape[0], CELL_W, CELL_H))
    cell_x, cell_y = cell_origin(index)
    rep = {"index": index, "x": cell_x, "y": cell_y, "mips": [], "blocks": 0}
    for (k, off, size, w, h, bw) in plan.mips:
        x0, y0, x1, y1 = _mip_cell_rect(cell_x, cell_y, k)
        if x1 > w or y1 > h:
            raise BuildError(stage, "mip%d cell rect %s runs past %dx%d" % (k, (x0, y0, x1, y1), w, h))
        bx0, by0, bx1, by1, _ = _region_blocks(plan.mips[k], x0, y0, x1, y1)
        rw, rh = bx1 - bx0, by1 - by0
        if rw <= 0 or rh <= 0:
            continue
        # gather the region's blocks (row major, contiguous)
        rows = []
        for by in range(by0, by1):
            a = off + (by * bw + bx0) * 8
            rows.append(bytes(data[a:a + rw * 8]))
        region = b"".join(rows)
        img = decode_bc1(region, rw * 4, rh * 4)                 # P1: keep original decoded pixels
        tile_k = np.asarray(Image.fromarray(tile).resize((max(1, x1 - x0), max(1, y1 - y0)),
                                                         Image.BOX), dtype=np.uint8)
        img[y0 - by0 * 4:y0 - by0 * 4 + (y1 - y0),
            x0 - bx0 * 4:x0 - bx0 * 4 + (x1 - x0)] = tile_k
        enc = bc1_encode(img)
        if len(enc) != rw * rh * 8:
            raise BuildError(stage, "mip%d region encoded %d B, expected %d" % (k, len(enc), rw * rh * 8))
        for j, by in enumerate(range(by0, by1)):
            a = off + (by * bw + bx0) * 8
            data[a:a + rw * 8] = enc[j * rw * 8:(j + 1) * rw * 8]
        rep["mips"].append({"mip": k, "rect": [x0, y0, x1, y1],
                            "blocks": [bx0, by0, bx1, by1], "bytes": rw * rh * 8})
        rep["blocks"] += rw * rh
    log(stage, "  atlas cell %d (col %d, row %d) @ (%d,%d): %d blocks over %d mips"
        % (index, index % COLS, index // COLS, cell_x, cell_y, rep["blocks"], len(rep["mips"])))
    return rep


# ---------------------------------------------------------------------------
# verification (this is what makes "no native pollution" a measurement)
# ---------------------------------------------------------------------------
CELL_BLOCKS = ((CELL_W + 3) // 4) * ((CELL_H + 3) // 4)


def verify(orig: bytes, new: bytes, plan: AtlasPlan, indices: Sequence[int],
           log: Log, stage: str = "L1") -> Dict:
    """A9 + A9b straight off the two byte strings.

    A9 : per mip, {blocks whose 8 bytes differ} must be a subset of the blocks covering our cells
         (allowed to be larger by the block rounding the embed itself did - compared exactly).
    A9b: per mip, decode both versions and measure the difference **inside every native cell's
         sampled rectangle** (index 0..164).  mip0 must be exactly zero; the other mips report the
         count and the max channel delta (the one-block seam described in the module docstring).
    """
    if len(orig) != len(new):
        raise BuildError(stage, "atlas length changed (%d -> %d)" % (len(orig), len(new)))
    allowed: Dict[int, set] = {m[0]: set() for m in plan.mips}
    for index in indices:
        cx, cy = cell_origin(index)
        for (k, _off, _size, _w, _h, _bw) in plan.mips:
            x0, y0, x1, y1 = _mip_cell_rect(cx, cy, k)
            bx0, by0, bx1, by1, _ = _region_blocks(plan.mips[k], x0, y0, x1, y1)
            for by in range(by0, by1):
                for bx in range(bx0, bx1):
                    allowed[k].add((bx, by))
    rep = {"mips": [], "a9_ok": True, "a9b_mip0_zero": None, "blocks_touched": 0,
           "native_pixels_changed": 0, "native_max_delta": 0}
    for (k, off, size, w, h, bw) in plan.mips:
        diff = 0
        outside = []
        for by in range((h + 3) // 4):
            base = off + by * bw * 8
            for bx in range(bw):
                a = base + bx * 8
                if orig[a:a + 8] != new[a:a + 8]:
                    diff += 1
                    if (bx, by) not in allowed[k]:
                        outside.append((bx, by))
        rep["blocks_touched"] += diff
        if outside:
            rep["a9_ok"] = False
        row = {"mip": k, "diff_blocks": diff, "outside_ours": len(outside),
               "example_outside": outside[:4]}
        if k <= 4:      # decoding anything below ~256 px tells us nothing useful
            io = decode_bc1(orig[off:off + size], w, h).astype(np.int16)
            iN = decode_bc1(new[off:off + size], w, h).astype(np.int16)
            d = np.abs(io - iN).max(axis=2)
            nat = np.zeros(d.shape, dtype=bool)
            for i in range(NATIVE_CELLS):
                cx, cy = cell_origin(i)
                x0 = cx >> k
                y0 = cy >> k
                x1 = (cx + CELL_W) >> k
                y1 = (cy + CELL_H) >> k
                nat[y0:y1, x0:x1] = True
            nat = nat[:d.shape[0], :d.shape[1]]
            row["native_px_changed"] = int((d[nat] > 0).sum())
            row["native_max_delta"] = int(d[nat].max()) if nat.any() else 0
            rep["native_pixels_changed"] += row["native_px_changed"]
            rep["native_max_delta"] = max(rep["native_max_delta"], row["native_max_delta"])
            if k == 0:
                rep["a9b_mip0_zero"] = (row["native_px_changed"] == 0)
        rep["mips"].append(row)
    if not rep["a9_ok"]:
        raise BuildError(stage, "A9 failed: some changed BC1 blocks are outside our cells")
    if rep["a9b_mip0_zero"] is not True:
        raise BuildError(stage, "A9b failed: mip0 changed %d native preview pixels"
                         % rep["mips"][0].get("native_px_changed"))
    log(stage, "  A9/A9b: %d blocks changed, all inside our cells; mip0 native pixels changed = 0; "
        "mips>=1 native pixels=%d max delta=%d (one-block seam)"
        % (rep["blocks_touched"], rep["native_pixels_changed"], rep["native_max_delta"]))
    return rep


def read_cell(data: bytes, plan: AtlasPlan, index: int, mip: int = 0) -> np.ndarray:
    """Decode one cell back out of (a copy of) the atlas - used by the A9b/PSNR evidence."""
    (k, off, size, w, h, bw) = plan.mips[mip]
    x0, y0, x1, y1 = _mip_cell_rect(*cell_origin(index), k)
    bx0, by0, bx1, by1, _ = _region_blocks(plan.mips[mip], x0, y0, x1, y1)
    rows = []
    for by in range(by0, by1):
        a = off + (by * bw + bx0) * 8
        rows.append(data[a:a + (bx1 - bx0) * 8])
    img = decode_bc1(b"".join(rows), (bx1 - bx0) * 4, (by1 - by0) * 4)
    return img[y0 - by0 * 4:y0 - by0 * 4 + (y1 - y0), x0 - bx0 * 4:x0 - bx0 * 4 + (x1 - x0)]


def cell_quality(data: bytes, plan: AtlasPlan, index: int, tile: np.ndarray,
                 log: Log, stage: str = "L1") -> Dict:
    """A9b per cell: decode our cell out of mip0 and compare it with the tile we put in."""
    from PIL import Image
    got = read_cell(data, plan, index, 0)
    ref = np.asarray(Image.fromarray(tile).resize((got.shape[1], got.shape[0]), Image.BOX))
    q = quality(got, ref)
    log(stage, "  atlas cell %d QUALITY: PSNR=%s dB MAE=%s sharpness=%s"
        % (index, q["psnr_db"], q["mae_s"], q["sharpness_s"]))
    return q


def load_mips(dump_text: str, uexp_path: str) -> List:
    """tex-inspect dump -> located mip list (shared with the background texture path)."""
    mips = parse_mips(dump_text)
    locate_mips(uexp_path, mips)
    return mips


def native_bytes(data: bytes, plan: AtlasPlan) -> int:
    return sum(m[2] for m in plan.mips)
