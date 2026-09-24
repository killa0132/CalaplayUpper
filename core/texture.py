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
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from .common import BuildError, Log

MIP_RE = re.compile(r"byte\[(\d+)\] sha256=([0-9A-F]+) head=([0-9A-F]+)")
INTER_MIP = 16
TRAILER = 28          # 24 B tail + 4 B PACKAGE_FILE_TAG


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
