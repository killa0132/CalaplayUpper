# -*- coding: utf-8 -*-
"""cooked Texture2D (.uexp) mip-chain surgery.

Measured layout of an 1920x1080 PF_DXT1 cooked texture (11 mips, 1,383,410 B):
    [header 110 B][mip0][16 B][mip1][16 B]... [mip10][24 B][PACKAGE_FILE_TAG 4 B]
Every inter-mip record is 16 bytes.  We do NOT trust "the payloads are adjacent"
guesses: the mip0 offset is located by its 32-byte head from tex-inspect, then
the +16 rule is *verified* against every remaining head before a single byte is
written.  pak_swap.py used find(head) for every level, which is fragile for the
1x1 mips whose heads are only 8 bytes long.
"""
from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from .common import BuildError, Log

MIP_RE = re.compile(r"byte\[(\d+)\] sha256=([0-9A-F]+) head=([0-9A-F]+)")
INTER_MIP = 16
TRAILER = 28          # 24 B tail + 4 B PACKAGE_FILE_TAG

# ---------------------------------------------------------------------------
# CP-35 route B (user ruling 2026-09-25): "keep 2560x1440, DXT1, whole-file rebuild".
#
# Measured layout of the cooked background shell (1920x1080 PF_DXT1, 1,383,410 B):
#
#   [header 110 B] [mip0][16 B] [mip1][16 B] ... [mip10][16 B] [8 B zero][PACKAGE_FILE_TAG]
#
# with the 16 B record after mip i = u32 SizeX, u32 SizeY, u32 SizeZ(=1), u32 (i+1) - and 0 on the
# last level.  The dimensions follow the engine's *shift* rule (max(1, w >> i)): the shell's mip4 is
# 120x67 and its mip6 is 30x16, not the ceil-half values.  Header fields (all measured):
#   @0 strip flags (04 05) / @2 SizeX / @6 SizeY / @10 16 B key of UNKNOWN semantics / @26 0 /
#   @50 DataSize (= len - 62) / @74 + @78 SizeX + SizeY again / @82 SizeZ=1 / @86 "PF_DXT1" FString /
#   @102 MipCount / @106 0.
# The @10 key is deliberately kept verbatim: eight MD5/SHA1 candidates were tested against it and
# none matched, so re-deriving it is not something this tool can honestly do.
#
# NOTE (counter-example, 2026-09-25; **corrected 2026-09-26**): the game's own 4096x2048 preview
# atlas is NOT rebuilt by this module - not because its layout differs (a refuted first guess said
# "its payloads are adjacent and the records trail"), but because its **header is 115 B** instead of
# this shell's 110 B, so HEADER_LEN must not be applied to it.  Byte-for-byte re-measurement
# (CP-36/CP-37) showed the atlas uses the same [payload][16 B record] framing and the same 28 B tail;
# `core/atlas.py` locates it structurally (file length + record chain) and never uses HEADER_LEN.
# ---------------------------------------------------------------------------
HEADER_LEN = 110
TAG = b"\xc1\x83\x2a\x9e"       # PACKAGE_FILE_TAG
TAIL_ZEROS = 8
BC1_BLOCK = 8                   # bytes per 4x4 block


def mip_table(w: int, h: int) -> List[Tuple[int, int, int, int]]:
    """[(index, bc1_size, size_x, size_y)] for a BC1 chain from w x h down to 1x1."""
    out: List[Tuple[int, int, int, int]] = []
    i, x, y = 0, w, h
    while True:
        out.append((i, ((x + 3) // 4) * ((y + 3) // 4) * BC1_BLOCK, x, y))
        if x == 1 and y == 1:
            return out
        i, x, y = i + 1, max(1, x // 2), max(1, y // 2)


def mip_count(w: int, h: int) -> int:
    return len(mip_table(w, h))


def compose(header: bytes, w: int, h: int, payloads: Sequence[bytes]) -> bytes:
    """Build a whole cooked .uexp in the shell's own layout (nothing written)."""
    table = mip_table(w, h)
    if len(header) < HEADER_LEN:
        raise BuildError("L2", "header is %d B, need at least %d" % (len(header), HEADER_LEN))
    if len(table) != len(payloads):
        raise BuildError("L2", "%dx%d needs %d mip levels, got %d payloads"
                         % (w, h, len(table), len(payloads)))
    out = bytearray(header[:HEADER_LEN])
    struct.pack_into("<I", out, 2, w)
    struct.pack_into("<I", out, 6, h)
    struct.pack_into("<I", out, 74, w)
    struct.pack_into("<I", out, 78, h)
    struct.pack_into("<I", out, 82, 1)
    struct.pack_into("<I", out, 102, len(payloads))
    n = len(payloads)
    for i, (_idx, size, x, y) in enumerate(table):
        p = payloads[i]
        if len(p) != size:
            raise BuildError("L2", "mip%d is %d B but %dx%d needs %d B" % (i, len(p), x, y, size))
        out += p
        out += struct.pack("<IIII", x, y, 1, (i + 1) if (i + 1) < n else 0)
    out += b"\x00" * TAIL_ZEROS + TAG
    struct.pack_into("<I", out, 50, len(out) - 62)   # DataSize, measured relation
    return bytes(out)


def roundtrip_check(uexp_path: str, mips: Sequence[Mip], log: Log, stage: str = "L0") -> None:
    """Prove the byte model on the file itself before it is trusted at another size.

    Rebuilds the package at ITS OWN size from ITS OWN payloads and demands byte equality.  Nothing is
    written.  This is what makes route B safe: the layout is never extrapolated to 2560x1440 until it
    has reproduced a real 1920x1080 file exactly (and the atlas counter-example above is why that
    matters).
    """
    data = open(uexp_path, "rb").read()
    head = data[:HEADER_LEN]
    w = struct.unpack_from("<I", head, 2)[0]
    h = struct.unpack_from("<I", head, 6)[0]
    declared = struct.unpack_from("<I", data, 102)[0]
    table = mip_table(w, h)
    if declared != len(table):
        raise BuildError(stage, "this package does not use the layout this tool can rebuild",
                         "%s: its header declares %d mips, but SizeX/SizeY = %d/%d (which the same "
                         "header carries at @2/@6) implies %d - refusing to rebuild it"
                         % (os.path.basename(uexp_path), declared, w, h, len(table)))
    if len(mips) != declared:
        raise BuildError(stage, "tex-inspect found %d mips, the header declares %d"
                         % (len(mips), declared))
    payloads = [data[m.offset:m.offset + m.size] for m in mips]
    rebuilt = compose(head, w, h, payloads)
    if rebuilt != data:
        n = min(len(rebuilt), len(data))
        first = next((i for i in range(n) if rebuilt[i] != data[i]), n)
        raise BuildError(
            stage, "A0/uexp layout roundtrip FAILED for %s" % os.path.basename(uexp_path),
            "rebuilt %d B vs original %d B, first difference at 0x%X -- refusing to rebuild this "
            "texture at another size" % (len(rebuilt), len(data), first))
    log(stage, "  uexp layout roundtrip OK: %dx%d / %d mips / %d B reproduced byte for byte"
        % (w, h, len(table), len(data)))


def patch_serial_size(uasset_path: str, old_len: int, new_len: int, log: Log,
                      stage: str = "L2") -> None:
    """The uasset's export SerialSize == len(uexp) - 4; it is the ONE size-coupled field."""
    orig = open(uasset_path, "rb").read()
    b = bytearray(orig)
    at = _serial_size_at(orig, old_len, stage)
    struct.pack_into("<q", b, at, new_len - 4)
    outside = [i for i in range(len(b)) if b[i] != orig[i] and not (at <= i < at + 8)]
    if outside:
        raise BuildError(stage, "uasset changed outside the SerialSize field: %s" % outside[:16])
    open(uasset_path, "wb").write(bytes(b))
    log(stage, "  SerialSize @0x%X: %d -> %d" % (at, old_len - 4, new_len - 4))


def _serial_size_at(uasset: bytes, old_len: int, stage: str) -> int:
    needle = struct.pack("<q", old_len - 4)
    hits = [i for i in range(len(uasset) - 8) if bytes(uasset[i:i + 8]) == needle]
    if len(hits) != 1:
        raise BuildError(stage, "SerialSize(%d) hit %d times -- refusing a blind patch"
                         % (old_len - 4, len(hits)))
    return hits[0]


#: Zen BulkDataMap entry, measured on the shell: u64 SerialOffset, i64 CookedIndex(-1),
#: u64 SerialSize, u32 ElementCount(= size), 2 x u32 pad, u32 BulkDataFlags, u32 pad.
#: 0x48 == BULKDATA_SingleUse | BULKDATA_ForceInlinePayload.
BULKMAP_STRIDE = 44
BULKDATA_FLAGS = 0x48


def bulkmap_at(uasset: bytes, mips: Sequence[Mip], stage: str = "L2") -> Tuple[int, List[Tuple[int, int]]]:
    """Locate the trailing per-mip Zen BulkDataMap that `retoc to-legacy` moves into the uasset.

    It must describe exactly the mips tex-inspect sees (same offsets AND same sizes), otherwise the
    reader slices the payload at the wrong place: with a stale map CUE4Parse reports
    `FirstMipToSerialize = -1` and **zero** mips for the rebuilt texture (measured 2026-09-25).
    """
    want = [(m.offset, m.size) for m in mips]
    good: List[Tuple[int, List[Tuple[int, int]]]] = []
    n = len(uasset)
    i = 0
    while i < n - 24:
        recs: List[Tuple[int, int]] = []
        j = i
        while j + BULKMAP_STRIDE <= n:
            off = struct.unpack_from("<q", uasset, j)[0]
            ci = struct.unpack_from("<q", uasset, j + 8)[0]
            size = struct.unpack_from("<q", uasset, j + 16)[0]
            if ci != -1 or off <= 0 or size <= 0:
                break
            recs.append((off, size))
            j += BULKMAP_STRIDE
        if len(recs) == len(want) and recs == want:
            # the map is preceded by its element count (u32 at start-8) - verify it, because a stale
            # count makes the reader walk one entry past the table (measured: the last mip came back
            # with garbage flags and 0 bytes while every byte-level check still passed).
            cnt = struct.unpack_from("<I", uasset, i - 8)[0] if i >= 8 else None
            if cnt != len(recs):
                raise BuildError(stage, "the Zen BulkDataMap at 0x%X holds %d entries but the count "
                                        "field before it says %s" % (i, len(recs), cnt))
            good.append((i, recs))
            i = j
            continue
        i += 1
    if len(good) != 1:
        raise BuildError(stage, "the uasset's Zen BulkDataMap does not describe the shell's %d mips "
                                "(%d candidate map(s) matched)" % (len(want), len(good)),
                         "route B must rewrite that map together with the uexp, so it refuses to "
                         "guess -- expected entries %s" % (want[:3],))
    return good[0]


def rebuild(uexp_path: str, uasset_path: str, src_mips: Sequence[Mip],
            payloads: Sequence[bytes], w: int, h: int, log: Log, stage: str = "L2") -> int:
    """Route B: rebuild a cloned cooked texture as w x h (whole file) + fix every size-coupled
    field of the uasset: the export `SerialSize` and the per-mip Zen `BulkDataMap`.

    The identity (name table / imports / FolderName) is untouched - `da-patch namerepl` already did
    that on the uasset, and the header's @10 key is carried over verbatim.  Returns the new length.
    """
    data = open(uexp_path, "rb").read()
    ua = open(uasset_path, "rb").read()
    roundtrip_check(uexp_path, src_mips, log, stage)
    map_at, map_recs = bulkmap_at(ua, src_mips, stage)
    head = data[:HEADER_LEN]
    sw, sh = struct.unpack_from("<I", head, 2)[0], struct.unpack_from("<I", head, 6)[0]
    built = compose(head, w, h, payloads)

    # where every mip lands inside the file we are about to write
    offs: List[Tuple[int, int]] = []
    o = HEADER_LEN
    for _i, size, _x, _y in mip_table(w, h):
        offs.append((o, size))
        o += size + INTER_MIP
    if o + TAIL_ZEROS + len(TAG) != len(built):
        raise BuildError(stage, "internal mip offsets do not add up to the composed uexp")

    serial_at = _serial_size_at(ua, len(data), stage)
    ua2 = bytearray(ua)
    struct.pack_into("<q", ua2, serial_at, len(built) - 4)
    new_map = bytearray()
    for off, size in offs:
        new_map += struct.pack("<qqq", off, -1, size)
        new_map += struct.pack("<IIIII", size, 0, 0, BULKDATA_FLAGS, 0)
    ua2[map_at:map_at + len(map_recs) * BULKMAP_STRIDE] = new_map
    struct.pack_into("<I", ua2, map_at - 8, len(offs))     # the map's element count

    bad = [i for i in range(map_at) if ua2[i] != ua[i]
           and not (serial_at <= i < serial_at + 8)
           and not (map_at - 8 <= i < map_at)]
    if bad:
        raise BuildError(stage, "uasset changed outside the SerialSize/count fields: %s" % bad[:16])
    tail_old = map_at + len(map_recs) * BULKMAP_STRIDE
    tail_new = map_at + len(new_map)
    if bytes(ua2[tail_new:]) != ua[tail_old:]:
        raise BuildError(stage, "uasset bytes after the bulk map changed")

    open(uexp_path, "wb").write(built)
    open(uasset_path, "wb").write(bytes(ua2))

    # read both back and demand what we just wrote
    chk = open(uexp_path, "rb").read()
    ua3 = open(uasset_path, "rb").read()
    hdr = parse_header(chk)
    if hdr["length"] != len(built) or hdr["mip_count"] != len(payloads) \
            or (hdr["size_x"], hdr["size_y"]) != (w, h) or hdr["size_x2"] != w \
            or hdr["size_y2"] != h:
        raise BuildError(stage, "the rebuilt uexp does not read back as %dx%d / %d mips" % (w, h, len(payloads)))
    if struct.unpack_from("<q", ua3, serial_at)[0] != len(built) - 4:
        raise BuildError(stage, "SerialSize did not stick")
    if struct.unpack_from("<I", ua3, map_at - 8)[0] != len(offs):
        raise BuildError(stage, "the bulk map count did not stick")
    back = [(struct.unpack_from("<q", ua3, map_at + k * BULKMAP_STRIDE)[0],
             struct.unpack_from("<q", ua3, map_at + k * BULKMAP_STRIDE + 16)[0]) for k in range(len(offs))]
    if back != offs:
        raise BuildError(stage, "the rewritten bulk map does not read back", "%s != %s" % (back[:3], offs[:3]))
    log(stage, "  uexp rebuilt %dx%d -> %dx%d: %d B -> %d B (%d mips)"
        % (sw, sh, w, h, len(data), len(built), len(payloads)))
    log(stage, "  uasset: SerialSize @0x%X -> %d, bulk map @0x%X rewritten %d -> %d entries"
        % (serial_at, len(built) - 4, map_at, len(map_recs), len(offs)))
    return len(built)


def parse_header(data: bytes) -> dict:
    """Read back the header fields this tool writes (offline assertion, no CUE4Parse needed)."""
    if len(data) < HEADER_LEN:
        raise BuildError("L4", "texture uexp is only %d B" % len(data))
    flen = struct.unpack_from("<i", data, 86)[0]
    fmt = data[90:90 + flen].decode("ascii", "replace").rstrip("\x00") if 0 < flen < 64 else None
    return {"size_x": struct.unpack_from("<I", data, 2)[0],
            "size_y": struct.unpack_from("<I", data, 6)[0],
            "size_x2": struct.unpack_from("<I", data, 74)[0],
            "size_y2": struct.unpack_from("<I", data, 78)[0],
            "size_z": struct.unpack_from("<I", data, 82)[0],
            "mip_count": struct.unpack_from("<I", data, 102)[0],
            "pixel_format": fmt,
            "watermark": data[10:26].hex(),
            "data_size": struct.unpack_from("<I", data, 50)[0],
            "length": len(data)}


def parse_platform(dump_text: str) -> dict:
    """The platform-level fields of a tex-inspect dump (i.e. before the first mip payload)."""
    head = dump_text.split("BulkData", 1)[0]

    def one(name: str):
        m = re.search(name + r":\s*\n\s*(\S+)", head)
        return m.group(1).strip().strip('"') if m else None

    def as_int(name: str):
        v = one(name)
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    return {"size_x": as_int("SizeX"), "size_y": as_int("SizeY"),
            "pixel_format": one("PixelFormat"), "num_mips_in_tail": as_int("NumMipsInTail"),
            "first_mip": as_int("FirstMipToSerialize"), "mips": len(MIP_RE.findall(dump_text))}



@dataclass
class Mip:
    index: int
    size: int
    sha256: str
    head: bytes
    offset: int = -1


def parse_mips(dump_text: str) -> List[Mip]:
    raw: List[Tuple[int, str, bytes]] = []
    for m in MIP_RE.finditer(dump_text):
        raw.append((int(m.group(1)), m.group(2), bytes.fromhex(m.group(3))))
    if not raw:
        raise BuildError("L0", "0 mip lines parsed from the tex-inspect dump",
                         "refusing to continue (silent-failure guard)")
    chain: List[Tuple[int, str, bytes]] = []
    for size, sha, head in raw:
        if chain and size > chain[-1][0]:
            break
        chain.append((size, sha, head))
    return [Mip(i, s, h, hd) for i, (s, h, hd) in enumerate(chain)]


def locate_mips(uexp_path: str, mips: Sequence[Mip]) -> int:
    """Compute + verify every mip offset inside the .uexp. Returns mip0 offset."""
    data = open(uexp_path, "rb").read()
    n = len(mips)
    # mip0's 32-byte head is unique in practice; verify that before trusting it.
    head0 = mips[0].head
    first = data.find(head0)
    if first < 0:
        raise BuildError("L2", "mip0 head not found in %s" % uexp_path,
                         "head=%s" % head0.hex().upper())
    if data.find(head0, first + 1) >= 0:
        raise BuildError("L2", "mip0 head appears more than once in %s" % uexp_path,
                         "the shell is not the expected single-texture package")
    off = first
    for i, m in enumerate(mips):
        if i > 0:
            off = off + mips[i - 1].size + INTER_MIP
        if off + len(m.head) > len(data):
            raise BuildError("L2", "mip%d offset 0x%X runs past the end of %s"
                             % (i, off, uexp_path))
        got = data[off:off + len(m.head)]
        if got != m.head:
            raise BuildError(
                "L2", "mip%d head mismatch at 0x%X in %s" % (i, off, uexp_path),
                "expected %s got %s -- the cooked layout is not the expected "
                "[header][mip0][16B][mip1]... form" % (m.head.hex().upper(), got.hex().upper()))
        m.offset = off
    end = mips[-1].offset + mips[-1].size
    if end + TRAILER != len(data):
        raise BuildError("L2", "mip chain does not end at uexp_len - %d in %s" % (TRAILER, uexp_path),
                         "chain end=0x%X uexp=%d (delta %d)" % (end, len(data), len(data) - end))
    return first


def replace_mips(uexp_path: str, mips: Sequence[Mip], encodings: Sequence[bytes],
                 log: Log, stage: str = "L2") -> None:
    """In-place, same-length replacement of every mip payload."""
    if len(encodings) != len(mips):
        raise BuildError(stage, "encoding count %d != mip count %d" % (len(encodings), len(mips)))
    data = bytearray(open(uexp_path, "rb").read())
    original_len = len(data)
    locate_mips(uexp_path, mips)
    for i, (m, enc) in enumerate(zip(mips, encodings)):
        if len(enc) != m.size:
            raise BuildError(stage, "mip%d encoded %d B != cooked slot %d B"
                             % (i, len(enc), m.size))
        data[m.offset:m.offset + m.size] = enc
        log(stage, "  mip%2d %7d B @ 0x%X" % (i, m.size, m.offset))
    if len(data) != original_len:
        raise BuildError(stage, "uexp length changed (%d -> %d)" % (original_len, len(data)))
    open(uexp_path, "wb").write(bytes(data))
    log(stage, "  uexp rewritten in place: %d B (length unchanged)" % len(data))
