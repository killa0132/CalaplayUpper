# -*- coding: utf-8 -*-
"""BC3(DXT5) / BC4 / BC5 编码器 + 角色贴图 ubulk 生成。

为什么单独一个文件：`core/bc1.py` 是背景管线的一部分（它开头的注释明说不要
"简化"回去），角色皮肤需要的是另外三种块格式，而且目标不是 1920x1080 的背景
壳，而是**与源 `.ubulk` 精确同尺寸**的 mip 链（多一级或少一级都会让游戏按错
的偏移取样）。

实测数据（Aika S001 贴图，2026-10-11 复核）：
    T_Aika_body_1_D.ubulk = 2,793,472 B = DXT1 五级链 (2048→128)
    T_Aika_body_2_D.ubulk = 5,586,944 B = 16 B/块 五级链 (BC7 原版 / DXT5 替换)
    T_Aika_Body_1_N.ubulk = 5,586,944 B = BC5（法线）
`.ubulk` 里 mip0 从偏移 0 开始、各级首尾相接（没有 16 B 间隔 —— 那是内联在
`.uexp` 里的贴图才有的布局，见 `core/texture.py`）。小 mip（64 及以下）内联在
`.uexp` 里，本模块只替换 ubulk 里的大 mip（与 repaint2.ps1 的既定做法一致）。

格式与编码器对照：
    PF_DXT1 -> bc1.bc1_encode（复用背景管线同一套编码器）
    PF_DXT5 -> BC3：每块 8 B alpha + 8 B BC1 颜色
    PF_BC5  -> BC5：两个 BC4 通道块（法线；原版是 BC5，替换必须也是 BC5）
    PF_BC7  -> 不能用 DXT 编码器重编（数据/声明不一致会渲染错乱，见
               《皮肤贴图正确显示_修复记录》阶段①）——调用方要么跳过，
               要么把声明改成 PF_DXT5 后按 BC3 编码。
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np

from .bc1 import bc1_encode, fix_swap, fit_indices, refine, to565

BLOCK16 = 16          # BC3 / BC5 / BC7
BLOCK8 = 8            # BC1 / BC4

#: 像素格式 → 每 4x4 块的字节数
BLOCK_BYTES = {
    "PF_DXT1": BLOCK8,
    "PF_DXT5": BLOCK16,
    "PF_BC5": BLOCK16,
    "PF_BC7": BLOCK16,
    "PF_BC4": BLOCK8,
}


def ubulk_mip_levels(w: int, h: int, pf: str, total: int) -> Optional[List[Tuple[int, int, int]]]:
    """从 ubulk 总长反推 mip 链：[(w, h, size)]，和必须精确等于 total。

    不符返回 None（调用方负责报错——绝不猜一个链路长度写下去）。
    """
    bb = BLOCK_BYTES.get(pf)
    if not bb:
        return None
    levels: List[Tuple[int, int, int]] = []
    x, y, acc = w, h, 0
    while True:
        size = ((x + 3) // 4) * ((y + 3) // 4) * bb
        if acc + size > total:
            return None
        levels.append((x, y, size))
        acc += size
        if acc == total:
            return levels
        if x == 1 and y == 1:
            return None
        x, y = max(1, x // 2), max(1, y // 2)


# --------------------------------------------------------------------------
# 块化 / 反块化
# --------------------------------------------------------------------------
def _to_blocks(img: np.ndarray) -> np.ndarray:
    """(h, w, c) uint8 -> (n, 16, c) int32（不足 4 的倍数的边按 edge 补齐）。"""
    h, w = img.shape[0], img.shape[1]
    ph, pw = (4 - h % 4) % 4, (4 - w % 4) % 4
    if ph or pw:
        pad = [(0, ph), (0, pw)] + [(0, 0)] * (img.ndim - 2)
        img = np.pad(img, pad, mode="edge")
    H, W = img.shape[0], img.shape[1]
    c = img.shape[2]
    return (img.reshape(H // 4, 4, W // 4, 4, c)
            .transpose(0, 2, 1, 3, 4).reshape(-1, 16, c).astype(np.int32))


def _pack_bits(idx: np.ndarray, nbits: int) -> np.ndarray:
    """(n, 16) 索引 -> (n, 6) 小端位流（每像素 nbits 位）。"""
    n = idx.shape[0]
    bits = np.zeros((n,), dtype=np.uint64)
    for i in range(16):
        bits |= (idx[:, i].astype(np.uint64) & ((1 << nbits) - 1)) << (nbits * i)
    out = np.empty((n, 6), dtype=np.uint8)
    for k in range(6):
        out[:, k] = ((bits >> (8 * k)) & 0xFF).astype(np.uint8)
    return out


def _color_blocks(blocks: np.ndarray, refine_rounds: int = 2) -> np.ndarray:
    """(n, 16, 3) -> (n, 8) BC1 颜色块（与 bc1.py 同一套端点逻辑）。"""
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
    return out


def bc4_encode(chan: np.ndarray, refine_rounds: int = 2) -> bytes:
    """单通道 (h, w) uint8 图 -> BC4 块（8 B/块）。

    单通道块：a0 = 块内最大值，a1 = 最小值（a0 > a1 走 8 值插值模式），
    再做若干轮"按索引分组取均值"的端点精修（与 BC1 的 Lloyd 精修同思路）。
    """
    blocks = _to_blocks(chan.reshape(chan.shape[0], chan.shape[1], 1))[:, :, 0]
    return _alpha_blocks(blocks, refine_rounds).tobytes()


def _alpha_palette(a0: np.ndarray, a1: np.ndarray) -> np.ndarray:
    """a0 > a1 的 8 值调色板：(n, 8) int32（BC4/BC3 alpha 通用）。"""
    d = (a0 - a1).astype(np.int32)
    cols = [a0.astype(np.int32), a1.astype(np.int32)]
    for i in range(1, 7):
        cols.append(((a0.astype(np.int32) * (7 - i) + a1.astype(np.int32) * i + 3) // 7))
    return np.stack(cols, axis=1)


def bc3_encode(rgba: np.ndarray, refine_rounds: int = 2) -> bytes:
    """RGBA (h, w, 4) uint8 -> BC3/DXT5 块（16 B/块：8 B alpha + 8 B 颜色）。"""
    blocks = _to_blocks(rgba)
    alpha_blocks = _alpha_blocks(blocks[:, :, 3], refine_rounds)
    color_blocks = _color_blocks(blocks[:, :, :3], refine_rounds)
    n = blocks.shape[0]
    out = np.empty((n, 16), dtype=np.uint8)
    out[:, 0:8] = alpha_blocks
    out[:, 8:16] = color_blocks
    return out.tobytes()


def _alpha_blocks(chans: np.ndarray, refine_rounds: int = 2) -> np.ndarray:
    """(n, 16) uint8 通道值 -> (n, 8) alpha/BC4 块。"""
    n = chans.shape[0]
    out = np.empty((n, 8), dtype=np.uint8)
    step = 20000
    for s in range(0, n, step):
        b = chans[s:s + step].astype(np.int32)
        a0 = b.max(axis=1)
        a1 = b.min(axis=1)
        hi = np.maximum(a0, a1)
        lo = np.minimum(a0, a1)
        lo = np.where(hi == lo, np.maximum(hi - 1, 0), lo)
        a0, a1 = hi, lo
        for _ in range(refine_rounds):
            pal = _alpha_palette(a0, a1)
            idx = np.abs(b[:, :, None] - pal[:, None, :]).argmin(axis=2).astype(np.int32)
            for which in (0, 1):
                m = (idx == which)
                k = m.sum(axis=1)
                sums = (b * m).sum(axis=1)
                mean = np.where(k > 0, (sums + k // 2) // np.maximum(k, 1),
                                np.where(which == 0, a0, a1))
                v = np.clip(mean, 0, 255).astype(np.int32)
                if which == 0:
                    a0 = np.maximum(v, a1 + 1)
                else:
                    a1 = np.minimum(v, a0 - 1)
                a0 = np.clip(a0, 1, 255)
                a1 = np.clip(a1, 0, 254)
        pal = _alpha_palette(a0, a1)
        idx = np.abs(b[:, :, None] - pal[:, None, :]).argmin(axis=2)
        out[s:s + step, 0] = a0.astype(np.uint8)
        out[s:s + step, 1] = a1.astype(np.uint8)
        out[s:s + step, 2:] = _pack_bits(idx, 3)
    return out


def bc5_encode(rgba: np.ndarray, refine_rounds: int = 2) -> bytes:
    """RGBA (h, w, 4) uint8 -> BC5 块（16 B：BC4 红 + BC4 绿；法线贴图）。"""
    blocks = _to_blocks(rgba)
    r = _alpha_blocks(blocks[:, :, 0], refine_rounds)
    g = _alpha_blocks(blocks[:, :, 1], refine_rounds)
    n = blocks.shape[0]
    out = np.empty((n, 16), dtype=np.uint8)
    out[:, 0:8] = r
    out[:, 8:16] = g
    return out.tobytes()


# --------------------------------------------------------------------------
# mip 链 + ubulk
# --------------------------------------------------------------------------
def _resize_box(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """整数倍率 BOX 缩放（cooked mip 链逐级减半的既有做法）。"""
    from PIL import Image
    im = Image.fromarray(img)
    return np.asarray(im.resize((w, h), Image.BOX))


def encode_ubulk(rgba: np.ndarray, pf: str, levels: Sequence[Tuple[int, int, int]],
                 log=None, stage: str = "C3",
                 refine_rounds: int = 2) -> bytes:
    """把一张 RGBA 图编码成与 `levels` 精确同尺寸的 ubulk。

    `pf` 只接受可编码的 DXT1/DXT5/BC5（BC7 由调用方转声明后按 DXT5 处理）。
    levels 由 `ubulk_mip_levels()` 从源 ubulk 反推而来，逐级校验尺寸。
    """
    enc = {"PF_DXT1": "bc1", "PF_DXT5": "bc3", "PF_BC5": "bc5"}.get(pf)
    if not enc:
        raise ValueError("不可编码的像素格式: %s" % pf)
    m0w, m0h = levels[0][0], levels[0][1]
    if rgba.shape[0] != m0h or rgba.shape[1] != m0w:
        rgba = _resize_box(rgba, m0w, m0h)
    cur = rgba
    out = bytearray()
    for i, (w, h, size) in enumerate(levels):
        if i > 0:
            cur = _resize_box(cur, w, h)
        if enc == "bc1":
            payload = bc1_encode(np.ascontiguousarray(cur[:, :, :3]), refine_rounds)
        elif enc == "bc3":
            a = cur[:, :, 3] if cur.shape[2] == 4 else np.full(cur.shape[:2], 255, np.uint8)
            payload = bc3_encode(np.dstack([cur[:, :, :3], a]), refine_rounds)
        else:
            payload = bc5_encode(cur, refine_rounds)
        if len(payload) != size:
            raise ValueError("mip%d 编码 %d B != 源槽位 %d B" % (i, len(payload), size))
        out += payload
        if log:
            log(stage, "  mip%-2d %4dx%-5d %8d B" % (i, w, h, size))
    return bytes(out)


def fmt_encodable(pf: str) -> bool:
    return pf in ("PF_DXT1", "PF_DXT5", "PF_BC5")
