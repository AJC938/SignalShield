"""Validated offline narrowband notch filtering for real waveforms."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.signal import freqz, iirnotch, filtfilt

from signalshield.config import NotchConfig
from signalshield.signals import as_real_samples


@dataclass(frozen=True, slots=True)
class NotchResponse:
    """Digital frequency samples and single-/forward-backward magnitudes."""

    frequency_cycles_per_symbol: NDArray[np.float64]
    single_pass_magnitude: NDArray[np.float64]
    forward_backward_magnitude: NDArray[np.float64]


def notch_coefficients(config: NotchConfig) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Design a stable second-order IIR notch using compatible symbol units.

    ``fs=samples_per_symbol`` and ``w0=cycles_per_symbol`` make SciPy's
    frequency units explicit. The returned vectors are numerator ``b`` and
    denominator ``a`` coefficients for direct use by ``filtfilt``/``freqz``.
    """
    if not isinstance(config, NotchConfig):
        raise TypeError("config must be a NotchConfig")
    b, a = iirnotch(
        w0=float(config.center_frequency_cycles_per_symbol),
        Q=float(config.quality_factor),
        fs=float(config.samples_per_symbol),
    )
    poles = np.roots(a)
    if not np.all(np.isfinite(b)) or not np.all(np.isfinite(a)):
        raise ValueError("notch design produced non-finite coefficients")
    if np.any(np.abs(poles) >= 1.0):
        raise ValueError("notch design is not numerically stable")
    return np.asarray(b, dtype=np.float64), np.asarray(a, dtype=np.float64)


def minimum_notch_input_length(config: NotchConfig) -> int:
    """Return the shortest record accepted by the documented filtfilt padding."""
    b, a = notch_coefficients(config)
    padlen = 3 * max(len(a), len(b))
    return padlen + 1


def apply_notch(samples: object, config: NotchConfig) -> NDArray[np.float64]:
    """Apply zero-phase forward-backward notch filtering to a finite record.

    Uses explicit odd padding with ``padlen=3*max(len(a),len(b))``. The
    operation is offline and noncausal, keeps the input length, does not
    modify the input, and can exhibit finite-record boundary transients.
    """
    checked = as_real_samples(samples, name="samples")
    b, a = notch_coefficients(config)
    padlen = 3 * max(len(a), len(b))
    if checked.size <= padlen:
        raise ValueError(f"samples must contain more than {padlen} values for filtfilt padding")
    output = np.asarray(filtfilt(b, a, checked, padtype="odd", padlen=padlen), dtype=np.float64)
    if output.shape != checked.shape:
        raise RuntimeError("notch filter did not preserve waveform length")
    if not np.all(np.isfinite(output)):
        raise ValueError("notch filtering produced non-finite samples")
    return output


def notch_frequency_response(config: NotchConfig, *, points: int = 16384) -> NotchResponse:
    """Return one-sided single-pass and effective ``filtfilt`` magnitudes."""
    if isinstance(points, bool) or not isinstance(points, int):
        raise TypeError("points must be an integer")
    if points < 16:
        raise ValueError("points must be at least 16")
    b, a = notch_coefficients(config)
    frequency, response = freqz(b, a, worN=points, fs=float(config.samples_per_symbol))
    single = np.abs(response).astype(np.float64)
    return NotchResponse(
        frequency_cycles_per_symbol=np.asarray(frequency, dtype=np.float64),
        single_pass_magnitude=single,
        forward_backward_magnitude=np.square(single),
    )
