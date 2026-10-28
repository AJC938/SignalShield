"""Safe WAV ingestion and canonical mono 8 kHz signed-16-bit audio payloads."""
from __future__ import annotations
from dataclasses import dataclass
from io import BytesIO
import math
import wave

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly

MAX_WAV_BYTES = 2 * 1024 * 1024
MAX_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class AudioPayload:
    pcm_bytes: bytes
    samples: np.ndarray
    metadata: dict[str, int]


def load_wav(data: bytes) -> AudioPayload:
    if not isinstance(data, bytes) or not data or len(data) > MAX_WAV_BYTES:
        raise ValueError("WAV file must be nonempty and at most 2 MiB")
    try:
        rate, raw = wavfile.read(BytesIO(data), mmap=False)
    except Exception as exc:
        raise ValueError(f"Invalid WAV file: {exc}") from exc
    if raw.dtype != np.dtype("int16") or raw.ndim not in (1, 2) or (raw.ndim == 2 and raw.shape[1] not in (1, 2)):
        raise ValueError("Supported format: PCM signed 16-bit WAV, mono or stereo")
    channels = 1 if raw.ndim == 1 else raw.shape[1]
    frames = int(raw.shape[0])
    if not 8000 <= rate <= 48000 or not frames or frames / rate > MAX_SECONDS:
        raise ValueError("Audio must be 8–48 kHz and no longer than 1 second")
    floats = raw.astype(np.float64) / 32768.0
    mono = floats if raw.ndim == 1 else floats.mean(axis=1)
    divisor = math.gcd(int(rate), 8000)
    normalized = resample_poly(mono, 8000 // divisor, int(rate) // divisor)
    wanted = max(1, round(frames * 8000 / rate))
    normalized = normalized[:wanted] if len(normalized) >= wanted else np.pad(normalized, (0, wanted-len(normalized)))
    samples = np.rint(np.clip(normalized, -1, 32767 / 32768) * 32768).astype("<i2")
    meta = {"sample_rate": 8000, "channels": 1, "format_code": 1, "frame_count": int(len(samples)),
            "source_sample_rate": int(rate), "source_channels": channels, "source_bits": 16, "source_frame_count": frames}
    return AudioPayload(samples.tobytes(), samples, meta)


def make_wav(pcm_bytes: bytes, sample_rate: int = 8000) -> bytes:
    samples = np.frombuffer(pcm_bytes, dtype="<i2")
    stream = BytesIO()
    wavfile.write(stream, sample_rate, samples)
    return stream.getvalue()
