"""Bounded payload framing: SSP1, network-order fields, MSB-first bits, IEEE CRC-32."""
from __future__ import annotations

from dataclasses import dataclass
import struct
import zlib

import numpy as np

MAGIC = b"SSP1"
MAX_PAYLOAD_BYTES = 16_384
# magic, type, flags, payload length, canonical rate/channels/format/frames,
# original rate/channels/bits/frames; all integers unsigned big-endian.
HEADER = struct.Struct(">4sBBIIBBIIBBI")
TEXT, AUDIO = 1, 2
PCM_S16LE = 1


class FrameError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PayloadFrame:
    payload_type: str
    payload: bytes
    crc_valid: bool
    metadata: dict[str, int]


def build_frame(payload: bytes, payload_type: str = "text", metadata: dict[str, int] | None = None) -> bytes:
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if not payload or len(payload) > MAX_PAYLOAD_BYTES:
        raise FrameError(f"payload must be 1..{MAX_PAYLOAD_BYTES} bytes")
    metadata = metadata or {}
    if payload_type == "text":
        vals = (0, 0, 0, 0, 0, 0, 0, 0)
        ptype = TEXT
    elif payload_type == "audio":
        vals = tuple(int(metadata.get(k, 0)) for k in (
            "sample_rate", "channels", "format_code", "frame_count",
            "source_sample_rate", "source_channels", "source_bits", "source_frame_count"))
        ptype = AUDIO
        if vals[:3] != (8000, 1, PCM_S16LE) or vals[3] * 2 != len(payload):
            raise FrameError("audio payload metadata must describe mono 8 kHz PCM S16LE")
        if not (8000 <= vals[4] <= 48000 and vals[5] in (1, 2) and vals[6] == 16 and 0 < vals[7] <= 48000):
            raise FrameError("source audio metadata is outside supported limits")
    else:
        raise FrameError("payload type must be text or audio")
    header = HEADER.pack(MAGIC, ptype, 0, len(payload), *vals)
    protected = header + payload
    return protected + struct.pack(">I", zlib.crc32(protected) & 0xffffffff)


def parse_frame(frame: bytes) -> PayloadFrame:
    if len(frame) < HEADER.size + 5:
        raise FrameError("frame is too short")
    fields = HEADER.unpack(frame[:HEADER.size])
    magic, ptype, flags, size, *meta = fields
    if magic != MAGIC or flags != 0 or ptype not in (TEXT, AUDIO):
        raise FrameError("invalid frame identifier, type, or flags")
    if size == 0 or size > MAX_PAYLOAD_BYTES or len(frame) != HEADER.size + size + 4:
        raise FrameError("invalid frame payload length")
    payload = frame[HEADER.size:HEADER.size + size]
    expected = struct.unpack(">I", frame[-4:])[0]
    valid = (zlib.crc32(frame[:-4]) & 0xffffffff) == expected
    metadata = dict(zip(("sample_rate", "channels", "format_code", "frame_count", "source_sample_rate", "source_channels", "source_bits", "source_frame_count"), meta))
    kind = "text" if ptype == TEXT else "audio"
    if kind == "audio":
        source_rate = metadata["source_sample_rate"]
        source_frames = metadata["source_frame_count"]
        if (metadata["sample_rate"] != 8000 or metadata["channels"] != 1
                or metadata["format_code"] != PCM_S16LE or metadata["frame_count"] * 2 != size
                or not 8000 <= source_rate <= 48000 or metadata["source_channels"] not in (1, 2)
                or metadata["source_bits"] != 16 or not 0 < source_frames <= source_rate):
            raise FrameError("invalid audio metadata or length")
    if kind == "text" and any(meta):
        raise FrameError("text frame must not contain audio metadata")
    return PayloadFrame(kind, payload, valid, metadata)


def bytes_to_bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8), bitorder="big")


def bits_to_bytes(bits: object) -> bytes:
    values = np.asarray(bits)
    if values.ndim != 1 or values.size % 8 or not np.all((values == 0) | (values == 1)):
        raise FrameError("frame bits must be binary and byte-aligned")
    return np.packbits(values.astype(np.uint8), bitorder="big").tobytes()
