"""Information source and shared array validation helpers."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def generate_bits(n_bits: int, rng: np.random.Generator) -> NDArray[np.uint8]:
    """Generate ``n_bits`` reproducible 0/1 bits using an explicit RNG."""
    if isinstance(n_bits, bool) or not isinstance(n_bits, int):
        raise TypeError("n_bits must be an integer")
    if n_bits <= 0:
        raise ValueError("n_bits must be greater than zero")
    if not isinstance(rng, np.random.Generator):
        raise TypeError("rng must be a numpy.random.Generator")
    return rng.integers(0, 2, size=n_bits, dtype=np.uint8)


def as_bits(values: object, *, name: str = "bits", allow_empty: bool = False) -> NDArray[np.uint8]:
    """Validate a one-dimensional binary array and return uint8 values."""
    array = np.asarray(values)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if not allow_empty and array.size == 0:
        raise ValueError(f"{name} must not be empty")
    if array.dtype.kind not in "biuf":
        raise TypeError(f"{name} must contain numeric binary values")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    if not np.all((array == 0) | (array == 1)):
        raise ValueError(f"{name} must contain only 0 and 1")
    return array.astype(np.uint8, copy=False)


def as_real_samples(values: object, *, name: str = "samples", allow_empty: bool = False) -> NDArray[np.float64]:
    """Validate a one-dimensional finite real sample array."""
    array = np.asarray(values)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if not allow_empty and array.size == 0:
        raise ValueError(f"{name} must not be empty")
    if array.dtype.kind not in "biuf":
        raise TypeError(f"{name} must contain real numeric values")
    result = array.astype(np.float64, copy=False)
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must contain only finite values")
    return result

