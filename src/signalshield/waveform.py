"""Upsampling and finite pulse-shaped transmit-waveform construction."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from signalshield.filters import rrc_taps
from signalshield.signals import as_real_samples


def upsample_symbols(symbols: object, samples_per_symbol: int) -> NDArray[np.float64]:
    """Insert ``samples_per_symbol-1`` zeros between symbols.

    The output length is ``(n_symbols-1)*samples_per_symbol+1`` and the
    original symbols occupy indices ``0, sps, 2*sps, ...``.
    """
    checked = as_real_samples(symbols, name="symbols")
    if isinstance(samples_per_symbol, bool) or not isinstance(samples_per_symbol, int):
        raise TypeError("samples_per_symbol must be an integer")
    if samples_per_symbol < 2:
        raise ValueError("samples_per_symbol must be at least 2")
    output = np.zeros((checked.size - 1) * samples_per_symbol + 1, dtype=np.float64)
    output[::samples_per_symbol] = checked
    return output


def pulse_shape(
    symbols: object,
    taps: object | None = None,
    *,
    samples_per_symbol: int = 8,
    rolloff: float = 0.35,
    span_symbols: int = 10,
) -> NDArray[np.float64]:
    """Upsample symbols and apply an RRC FIR using full linear convolution.

    If ``taps`` is omitted, the unit-energy taps are designed from the
    supplied RRC parameters. The output length is ``(Nsym-1)*sps + Nh``;
    the causal transmit-filter transient and group delay remain in the array.
    """
    checked_symbols = as_real_samples(symbols, name="symbols")
    pulse = (
        rrc_taps(rolloff, span_symbols, samples_per_symbol)
        if taps is None
        else as_real_samples(taps, name="taps")
    )
    impulse_train = upsample_symbols(checked_symbols, samples_per_symbol)
    return np.convolve(impulse_train, pulse, mode="full")
