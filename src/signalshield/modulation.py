"""BPSK mapping and demapping conventions."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from signalshield.signals import as_bits, as_real_samples


def bpsk_modulate(bits: object, bit_energy: float = 1.0) -> NDArray[np.float64]:
    """Map bit 0 to ``+sqrt(Eb)`` and bit 1 to ``-sqrt(Eb)``."""
    checked = as_bits(bits)
    if isinstance(bit_energy, bool) or not isinstance(bit_energy, (int, float)):
        raise TypeError("bit_energy must be a real number")
    if not np.isfinite(bit_energy) or bit_energy <= 0:
        raise ValueError("bit_energy must be finite and greater than zero")
    return (1.0 - 2.0 * checked.astype(np.float64)) * np.sqrt(bit_energy)


def bpsk_demodulate(samples: object) -> NDArray[np.uint8]:
    """Hard-decision BPSK demapping; samples at zero map to bit 0."""
    checked = as_real_samples(samples)
    return (checked < 0.0).astype(np.uint8)

