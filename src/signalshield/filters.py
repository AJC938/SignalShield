"""Finite RRC pulse design, matched filtering, and symbol-rate sampling."""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from signalshield.config import WaveformConfig
from signalshield.signals import as_real_samples


def rrc_taps(
    rolloff: float = 0.35,
    span_symbols: int = 10,
    samples_per_symbol: int = 8,
) -> NDArray[np.float64]:
    """Create unit-energy, symmetric finite RRC taps from the analytic formula.

    The time axis spans ``[-span_symbols/2, +span_symbols/2]`` in symbol
    periods with spacing ``1/samples_per_symbol``. Zero roll-off is rejected.
    """
    config = WaveformConfig(samples_per_symbol, rolloff, span_symbols)
    tap_count = config.tap_count
    center = (tap_count - 1) // 2
    time = (np.arange(tap_count, dtype=np.float64) - center) / config.samples_per_symbol
    beta = float(config.rolloff)
    taps = np.empty(tap_count, dtype=np.float64)
    singular_time = 1.0 / (4.0 * beta)
    tolerance = 16.0 * np.finfo(np.float64).eps * max(1.0, singular_time)

    for index, t in enumerate(time):
        if abs(t) <= tolerance:
            value = 1.0 + beta * (4.0 / math.pi - 1.0)
        elif abs(abs(t) - singular_time) <= tolerance:
            value = (beta / math.sqrt(2.0)) * (
                (1.0 + 2.0 / math.pi) * math.sin(math.pi / (4.0 * beta))
                + (1.0 - 2.0 / math.pi) * math.cos(math.pi / (4.0 * beta))
            )
        else:
            numerator = math.sin(math.pi * t * (1.0 - beta)) + (
                4.0 * beta * t * math.cos(math.pi * t * (1.0 + beta))
            )
            denominator = math.pi * t * (1.0 - (4.0 * beta * t) ** 2)
            value = numerator / denominator
        taps[index] = value

    energy = float(np.dot(taps, taps))
    if not math.isfinite(energy) or energy <= 0.0:
        raise ValueError("RRC tap energy is invalid for the requested parameters")
    taps /= math.sqrt(energy)
    return taps


def filter_group_delay_samples(taps: object) -> int:
    """Return group delay for an odd-length symmetric linear-phase FIR."""
    checked = as_real_samples(taps, name="taps")
    if checked.size % 2 != 1:
        raise ValueError("taps must have odd length for an integer group delay")
    if not np.allclose(checked, checked[::-1], rtol=1e-12, atol=1e-14):
        raise ValueError("taps must be symmetric to use this linear-phase delay")
    return (checked.size - 1) // 2


def matched_filter(samples: object, transmit_taps: object) -> NDArray[np.float64]:
    """Apply the real matched filter with full linear convolution.

    For the real M2 pulse, the matched impulse response is the time reverse
    of the transmit pulse. Full convolution preserves all filter tails.
    """
    checked_samples = as_real_samples(samples, name="samples")
    checked_taps = as_real_samples(transmit_taps, name="transmit_taps")
    return np.convolve(checked_samples, checked_taps[::-1], mode="full")


def symbol_sample_indices(
    n_symbols: int,
    samples_per_symbol: int,
    total_delay_samples: int,
    filtered_length: int,
) -> NDArray[np.int64]:
    """Return validated payload sample indices for full-convolution output."""
    for name, value in (
        ("n_symbols", n_symbols),
        ("samples_per_symbol", samples_per_symbol),
        ("total_delay_samples", total_delay_samples),
        ("filtered_length", filtered_length),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
    if n_symbols <= 0 or samples_per_symbol <= 0 or filtered_length <= 0:
        raise ValueError("symbol count, samples per symbol, and filtered length must be positive")
    if total_delay_samples < 0:
        raise ValueError("total_delay_samples must be nonnegative")
    indices = total_delay_samples + np.arange(n_symbols, dtype=np.int64) * samples_per_symbol
    if indices[-1] >= filtered_length:
        raise ValueError("the requested symbol decisions exceed the filtered output")
    return indices


def sample_symbols(
    filtered_samples: object,
    *,
    n_symbols: int,
    samples_per_symbol: int,
    total_delay_samples: int,
) -> NDArray[np.float64]:
    """Sample full-convolution output at ``total_delay + k*sps``."""
    checked = as_real_samples(filtered_samples, name="filtered_samples")
    indices = symbol_sample_indices(
        n_symbols,
        samples_per_symbol,
        total_delay_samples,
        int(checked.size),
    )
    return checked[indices]
