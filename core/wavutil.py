# -*- coding: utf-8 -*-
"""RIFF/WAVE inspection.

The engine's PCM path (PcmAudioInfoHybrid) calls FWaveModInfo::ReadWaveInfo and
asserts wFormatTag == 1, so the payload we embed must be a real RIFF/WAVE file.
We never trust ffmpeg's exit code alone: after transcoding we re-parse the
produced file with the code below.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Optional, Tuple

WAVE_FORMAT_PCM = 1
WAVE_FORMAT_IEEE_FLOAT = 3
WAVE_FORMAT_EXTENSIBLE = 0xFFFE

FMT_NAMES = {
    1: "PCM(int)", 2: "ADPCM", 3: "IEEE float", 6: "A-law", 7: "mu-law",
    0x55: "MPEG Layer-3 (MP3)", 0xFFFE: "EXTENSIBLE",
}


def fmt_name(tag: int) -> str:
    return FMT_NAMES.get(tag, "unknown(0x%X)" % tag)


@dataclass
class WavInfo:
    path: str
    size: int
    tag: int
    channels: int
    rate: int
    bits: int
    block_align: int
    byte_rate: int
    data_bytes: int
    sub_format: int = 0        # for EXTENSIBLE

    @property
    def frames(self) -> int:
        if self.block_align <= 0:
            return 0
        return self.data_bytes // self.block_align

    @property
    def duration(self) -> float:
        return (self.frames / float(self.rate)) if self.rate else 0.0

    @property
    def effective_tag(self) -> int:
        return self.sub_format or self.tag

    def describe(self) -> str:
        return ("tag=%d(%s) ch=%d rate=%d bits=%d blockAlign=%d byteRate=%d "
                "dataBytes=%d frames=%d duration=%.3f"
                % (self.effective_tag, fmt_name(self.effective_tag), self.channels,
                   self.rate, self.bits, self.block_align, self.byte_rate,
                   self.data_bytes, self.frames, self.duration))


def is_riff(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(12)
    except OSError:
        return False
    return len(head) >= 12 and head[0:4] == b"RIFF" and head[8:12] == b"WAVE"


def read_wav(path: str) -> Optional[WavInfo]:
    """Return WavInfo, or None when the file is not a parseable RIFF/WAVE."""
    try:
        b = open(path, "rb").read()
    except OSError:
        return None
    if len(b) < 44 or b[0:4] != b"RIFF" or b[8:12] != b"WAVE":
        return None
    q = 12
    fmt = None
    sub_format = 0
    data_bytes = -1
    while q + 8 <= len(b):
        cid = b[q:q + 4]
        sz = struct.unpack_from("<I", b, q + 4)[0]
        body = q + 8
        if cid == b"fmt " and sz >= 16 and body + 16 <= len(b):
            tag, ch, rate, brate, align, bits = struct.unpack_from("<HHIIHH", b, body)
            if tag == WAVE_FORMAT_EXTENSIBLE and sz >= 40 and body + 26 <= len(b):
                sub_format = struct.unpack_from("<H", b, body + 24)[0]
            fmt = (tag, ch, rate, brate, align, bits)
        elif cid == b"data":
            data_bytes = min(sz, len(b) - body)
            break
        q = body + sz + (sz & 1)
    if fmt is None or data_bytes < 0:
        return None
    tag, ch, rate, brate, align, bits = fmt
    return WavInfo(path=path, size=len(b), tag=tag, channels=ch, rate=rate, bits=bits,
                   block_align=align, byte_rate=brate, data_bytes=data_bytes,
                   sub_format=sub_format)


def compliance(info: WavInfo, rate: int, max_ch: int, bits: int) -> Tuple[bool, str]:
    """Can this file be embedded as-is (no re-encode)?"""
    if info.effective_tag != WAVE_FORMAT_PCM:
        return False, "format tag %d (%s) is not PCM" % (info.effective_tag,
                                                         fmt_name(info.effective_tag))
    if info.rate != rate:
        return False, "sample rate %d != %d" % (info.rate, rate)
    if info.bits != bits:
        return False, "%d-bit != %d-bit" % (info.bits, bits)
    if info.channels < 1 or info.channels > max_ch:
        return False, "%d channels not in 1..%d" % (info.channels, max_ch)
    if info.frames <= 0:
        return False, "no audio frames"
    # a WAV with a trailing chunk after data is still fine (engine only reads data)
    return True, "PCM %d Hz / %d-bit / %dch" % (info.rate, info.bits, info.channels)


def verify_identity(a: str, b: str) -> bool:
    """Byte-for-byte equality of two files (used by gate A4)."""
    if os.path.getsize(a) != os.path.getsize(b):
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            x, y = fa.read(1 << 20), fb.read(1 << 20)
            if x != y:
                return False
            if not x:
                return True
