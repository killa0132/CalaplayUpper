# -*- coding: utf-8 -*-
"""BC1/DXT1 encoder + background fitting + quality metrics.

This is the *fixed* encoder (2026-09-22 A1).  The original bug was
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c1, c0)
where both right-hand sides were the same expression, collapsing every 4x4
block to a near single colour ("画质被压缩成了屎").  Do not "simplify" it back.

Every image change must print a QUALITY line (PSNR / MAE / sharpness ratio):
content-correct is NOT the same as quality-correct.
"""
from __future__ import annotations

import struct
import zlib
from typing import List, Tuple

import numpy as np

from .common import BuildError

LETTERBOX_RGB = (18, 18, 22)


# --------------------------------------------------------------------------
# BC1 codec
# --------------------------------------------------------------------------
def to565(c):
    r = (c[:, 0] * 31 + 127) // 255
    g = (c[:, 1] * 63 + 127) // 255
    b = (c[:, 2] * 31 + 127) // 255
    return (r << 11) | (g << 5) | b


def to888(c):
    r = ((c >> 11) & 0x1F) * 255 // 31
    g = ((c >> 5) & 0x3F) * 255 // 63
    b = (c & 0x1F) * 255 // 31
    return np.stack([r, g, b], axis=-1).astype(np.int32)


def fit_indices(b, c0, c1):
    p0, p1 = to888(c0), to888(c1)
    pal = np.stack([p0, p1, (2 * p0 + p1) // 3, (p0 + 2 * p1) // 3], axis=1)
    d = ((b[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(axis=3)
    return d.argmin(axis=2).astype(np.uint32), d.min(axis=2).sum(axis=1)


def fix_swap(a, b):
    """4-colour opaque mode requires c0 > c1."""
    swap = a < b
    hi = np.where(swap, b, a)
    lo = np.where(swap, a, b)
    eq = hi == lo
    lo = np.where(eq, np.maximum(hi.astype(np.int64) - 1, 0), lo)
    return hi.astype(np.uint32), lo.astype(np.uint32)


def refine(b, c0, c1, rounds):
    """Lloyd-style endpoint refinement (default 2 rounds, +1..1.6 dB measured)."""
    for _ in range(rounds):
        idx, _ = fit_indices(b, c0, c1)
        for which in (0, 1):
            m = (idx == which)
            k = m.sum(axis=1)
            sums = (b * m[:, :, None]).sum(axis=1)
            mean = sums / np.maximum(k[:, None], 1)
            q = to565(mean.astype(np.int32)).astype(np.uint32)
            if which == 0:
                c0 = np.where(k > 0, q, c0)
            else:
                c1 = np.where(k > 0, q, c1)
        c0, c1 = fix_swap(c0, c1)
    return c0, c1


def bc1_encode(img: np.ndarray, refine_rounds: int = 2) -> bytes:
    """img (h,w,3) uint8 -> BC1 bytes; pads to a multiple of 4 with edge pixels."""
    h, w, _ = img.shape
    ph, pw = (4 - h % 4) % 4, (4 - w % 4) % 4
    if ph or pw:
        img = np.pad(img, ((0, ph), (0, pw), (0, 0)), mode="edge")
    H, W, _ = img.shape
    bh, bw = H // 4, W // 4
    blocks = (img.reshape(bh, 4, bw, 4, 3)
              .transpose(0, 2, 1, 3, 4).reshape(bh * bw, 16, 3).astype(np.int32))
    n = blocks.shape[0]
    out = np.empty((n, 8), dtype=np.uint8)
    step = 20000
    for s in range(0, n, step):
        b = blocks[s:s + step]
        c0, c1 = fix_swap(to565(b.max(axis=1)).astype(np.uint32),
                          to565(b.min(axis=1)).astype(np.uint32))
        if refine_rounds > 0:
            c0, c1 = refine(b, c0, c1, refine_rounds)
        idx, _ = fit_indices(b, c0, c1)
        bits = (idx << (2 * np.arange(16, dtype=np.uint32))[None, :]).sum(axis=1)
        res = np.empty((b.shape[0], 8), dtype=np.uint8)
        res[:, 0] = c0 & 0xFF
        res[:, 1] = (c0 >> 8) & 0xFF
        res[:, 2] = c1 & 0xFF
        res[:, 3] = (c1 >> 8) & 0xFF
        res[:, 4] = bits & 0xFF
        res[:, 5] = (bits >> 8) & 0xFF
        res[:, 6] = (bits >> 16) & 0xFF
        res[:, 7] = (bits >> 24) & 0xFF
        out[s:s + step] = res
    return out.tobytes()


def bc1_size(w: int, h: int) -> int:
    return ((w + 3) // 4) * ((h + 3) // 4) * 8


def decode_bc1(data: bytes, w: int, h: int) -> np.ndarray:
    bw, bh = (w + 3) // 4, (h + 3) // 4
    a = (np.frombuffer(data[:bw * bh * 8], dtype=np.uint8)
         .reshape(bh * bw, 8).astype(np.int32))
    c0, c1 = a[:, 0] | (a[:, 1] << 8), a[:, 2] | (a[:, 3] << 8)
    bits = (a[:, 4].astype(np.uint32) | (a[:, 5].astype(np.uint32) << 8)
            | (a[:, 6].astype(np.uint32) << 16) | (a[:, 7].astype(np.uint32) << 24))
    p0, p1 = to888(c0), to888(c1)
    pal = np.stack([p0, p1, (2 * p0 + p1) // 3, (p0 + 2 * p1) // 3], axis=1)
    idx = np.stack([(bits >> (2 * i)) & 3 for i in range(16)], axis=1)
    px = np.take_along_axis(pal, idx[:, :, None], axis=1)
    return (px.reshape(bh, bw, 4, 4, 3).transpose(0, 2, 1, 3, 4)
            .reshape(bh * 4, bw * 4, 3)[:h, :w].astype(np.uint8))


# --------------------------------------------------------------------------
# metrics + png
# --------------------------------------------------------------------------
def lap_var(rgb) -> float:
    from numpy.lib.stride_tricks import sliding_window_view
    g = np.asarray(rgb).astype(np.float64)
    if g.ndim == 3:
        g = g.mean(axis=2)
    k = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)
    return (sliding_window_view(g, (3, 3)) * k).sum(axis=(2, 3)).var()


def quality(decoded: np.ndarray, ref: np.ndarray) -> dict:
    dec = decoded.astype(np.float64)
    r = ref.astype(np.float64)
    d = np.abs(dec - r)
    mse = ((dec - r) ** 2).mean()
    psnr = 10.0 * np.log10(255.0 ** 2 / max(mse, 1e-9))
    lv_d, lv_r = lap_var(decoded), lap_var(ref)
    return {"psnr": float(psnr), "mae": float(d.mean()),
            "sharpness": float(lv_d / max(lv_r, 1e-9)),
            "psnr_db": "%.2f" % psnr, "mae_s": "%.3f" % d.mean(),
            "sharpness_s": "%.3f" % (lv_d / max(lv_r, 1e-9))}


def write_png(path: str, rgb: np.ndarray) -> None:
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(t, d):
        return (struct.pack(">I", len(d)) + t + d
                + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF))
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    open(path, "wb").write(png)


# --------------------------------------------------------------------------
# fitting
# --------------------------------------------------------------------------
FIT_MODES = ("cover", "contain")


def fit_image(src, target: Tuple[int, int], mode: str):
    """Return (fitted_image, note).  src is a PIL Image in RGB.

    cover   : scale to fill, centre crop (no black bars; trims a little)
    contain : scale to fit, centre on a canvas filled with (18,18,22)
    """
    from PIL import Image
    tw, th = target
    sw, sh = src.size
    if mode not in FIT_MODES:
        raise BuildError("L1", "unknown fit mode '%s'" % mode, "valid: %s" % ", ".join(FIT_MODES))
    if (sw, sh) == (tw, th):
        return src, "already %dx%d -> no resample" % (tw, th)
    scale = max(tw / sw, th / sh) if mode == "cover" else min(tw / sw, th / sh)
    nw, nh = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
    scaled = src.resize((nw, nh), Image.LANCZOS)
    if mode == "cover":
        x, y = (nw - tw) // 2, (nh - th) // 2
        out = scaled.crop((x, y, x + tw, y + th))
        note = ("cover: %dx%d -> x%.4f -> %dx%d -> centre-crop (crop %d,%d)"
                % (sw, sh, scale, nw, nh, x, y))
        return out, note
    canvas = Image.new("RGB", (tw, th), LETTERBOX_RGB)
    x, y = (tw - nw) // 2, (th - nh) // 2
    canvas.paste(scaled, (x, y))
    note = ("contain: %dx%d -> x%.4f -> %dx%d -> pasted at (%d,%d), borders %s"
            % (sw, sh, scale, nw, nh, x, y, LETTERBOX_RGB))
    return canvas, note


def mip_chain(base) -> List:
    """11-level chain matching the cooked shell (1920x1080 -> 1x1)."""
    from PIL import Image
    levels = [base]
    w, h = base.size
    while w > 1 or h > 1:
        w, h = max(1, w // 2), max(1, h // 2)
        levels.append(levels[-1].resize((w, h), Image.BOX))
    return levels


def encode_chain(levels, refine_rounds: int = 2) -> List[bytes]:
    return [bc1_encode(np.asarray(lv), refine_rounds) for lv in levels]
