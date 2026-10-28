"""BER estimates, exact binomial intervals, and coherent-BPSK theory."""

from __future__ import annotations

from dataclasses import dataclass
import math
import hashlib

import numpy as np
from numpy.typing import ArrayLike
from scipy.special import erfc
from scipy.stats import beta, binomtest

from signalshield.channel import ebn0_db_to_linear
from signalshield.signals import as_bits


@dataclass(frozen=True, slots=True)
class BerEstimate:
    """Observed bit-error rate and exact binomial uncertainty."""

    errors: int
    n_bits: int
    ber: float
    confidence_level: float
    confidence_interval: tuple[float, float]
    zero_error_upper_bound_95: float | None


@dataclass(frozen=True, slots=True)
class PairedBerEstimate:
    """Paired receiver BER difference and bit-transition counts."""

    baseline: BerEstimate
    candidate: BerEstimate
    difference_candidate_minus_baseline: float
    corrected_errors: int
    introduced_errors: int
    shared_errors: int
    unchanged_decisions: int
    mcnemar_exact_p_value: float
    mcnemar_p_value_underflow: bool
    block_confidence_intervals: dict[int, tuple[float, float]]


def ber_estimate(
    transmitted_bits: object,
    received_bits: object,
    confidence_level: float = 0.95,
) -> BerEstimate:
    """Calculate BER and a two-sided Clopper–Pearson interval.

    For zero errors, ``ber`` remains exactly zero observed errors divided by
    N; ``zero_error_upper_bound_95`` separately reports a one-sided 95% bound.
    """
    sent = as_bits(transmitted_bits, name="transmitted_bits")
    detected = as_bits(received_bits, name="received_bits")
    if sent.size != detected.size:
        raise ValueError("transmitted_bits and received_bits must have equal lengths")
    if isinstance(confidence_level, bool) or not isinstance(confidence_level, (int, float)):
        raise TypeError("confidence_level must be a real number")
    if not math.isfinite(confidence_level) or not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be finite and between 0 and 1")

    n_bits = int(sent.size)
    errors = int(np.count_nonzero(sent != detected))
    alpha = 1.0 - float(confidence_level)
    lower = 0.0 if errors == 0 else float(beta.ppf(alpha / 2.0, errors, n_bits - errors + 1))
    upper = 1.0 if errors == n_bits else float(beta.ppf(1.0 - alpha / 2.0, errors + 1, n_bits - errors))
    zero_upper = 1.0 - 0.05 ** (1.0 / n_bits) if errors == 0 else None
    return BerEstimate(
        errors=errors,
        n_bits=n_bits,
        ber=errors / n_bits,
        confidence_level=float(confidence_level),
        confidence_interval=(lower, upper),
        zero_error_upper_bound_95=zero_upper,
    )


def bpsk_awgn_theory(ebn0_db: ArrayLike) -> float | np.ndarray:
    """Return coherent uncoded BPSK BER ``0.5*erfc(sqrt(Eb/N0))``."""
    values = np.asarray(ebn0_db, dtype=np.float64)
    if values.ndim > 1:
        raise ValueError("ebn0_db must be a scalar or one-dimensional array")
    if values.size == 0 or not np.all(np.isfinite(values)):
        raise ValueError("ebn0_db must contain finite values")
    linear = np.power(10.0, values / 10.0)
    if not np.all(np.isfinite(linear)) or np.any(linear <= 0.0):
        raise ValueError("ebn0_db is outside the numerically supported range")
    result = 0.5 * erfc(np.sqrt(linear))
    return float(result) if result.ndim == 0 else result


def paired_ber_estimate(
    transmitted_bits: object,
    baseline_bits: object,
    candidate_bits: object,
    *,
    confidence_level: float = 0.95,
    block_lengths: tuple[int, ...] = (50, 100),
    bootstrap_replicates: int = 1000,
    bootstrap_seed: int = 4040,
) -> PairedBerEstimate:
    """Compute BERs and paired uncertainty for two decisions on the same bits.

    Difference is candidate BER minus baseline BER. Contiguous block bootstrap
    intervals preserve short-range dependence better than resampling bits
    independently. McNemar's exact test is included for reference and assumes
    independent discordant pairs; filtered communication errors may violate
    that assumption. Each block length receives a stable sub-seed.
    """
    sent = as_bits(transmitted_bits, name="transmitted_bits")
    baseline = as_bits(baseline_bits, name="baseline_bits")
    candidate = as_bits(candidate_bits, name="candidate_bits")
    if baseline.size != sent.size or candidate.size != sent.size:
        raise ValueError("transmitted, baseline, and candidate bit arrays must have equal lengths")
    if not isinstance(block_lengths, tuple) or not block_lengths:
        raise TypeError("block_lengths must be a nonempty tuple of positive integers")
    if len(set(block_lengths)) != len(block_lengths):
        raise ValueError("block_lengths must not contain duplicates")
    for block_length in block_lengths:
        if isinstance(block_length, bool) or not isinstance(block_length, int):
            raise TypeError("each block length must be an integer")
        if block_length <= 0:
            raise ValueError("each block length must be positive")
    if isinstance(bootstrap_replicates, bool) or not isinstance(bootstrap_replicates, int):
        raise TypeError("bootstrap_replicates must be an integer")
    if bootstrap_replicates < 100:
        raise ValueError("bootstrap_replicates must be at least 100")
    if isinstance(bootstrap_seed, bool) or not isinstance(bootstrap_seed, int) or bootstrap_seed < 0:
        raise ValueError("bootstrap_seed must be a nonnegative integer")

    baseline_estimate = ber_estimate(sent, baseline, confidence_level)
    candidate_estimate = ber_estimate(sent, candidate, confidence_level)
    baseline_error = baseline != sent
    candidate_error = candidate != sent
    corrected = int(np.count_nonzero(baseline_error & ~candidate_error))
    introduced = int(np.count_nonzero(~baseline_error & candidate_error))
    shared = int(np.count_nonzero(baseline_error & candidate_error))
    unchanged = int(np.count_nonzero(baseline == candidate))
    discordant = corrected + introduced
    p_value = float(binomtest(corrected, discordant, p=0.5).pvalue) if discordant else 1.0

    delta = candidate_error.astype(np.float64) - baseline_error.astype(np.float64)
    intervals: dict[int, tuple[float, float]] = {}
    for block_length in block_lengths:
        n_blocks = int(np.ceil(delta.size / block_length))
        padded = np.pad(delta, (0, n_blocks * block_length - delta.size))
        block_sums = padded.reshape(n_blocks, block_length).sum(axis=1)
        seed_material = f"{bootstrap_seed}|paired-ber-block|{block_length}".encode()
        child_seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
        rng = np.random.default_rng(child_seed)
        indices = rng.integers(0, n_blocks, size=(bootstrap_replicates, n_blocks))
        estimates = block_sums[indices].sum(axis=1) / delta.size
        tail = (1.0 - float(confidence_level)) / 2.0
        low, high = np.quantile(estimates, [tail, 1.0-tail])
        intervals[block_length] = (float(low), float(high))

    return PairedBerEstimate(
        baseline=baseline_estimate,
        candidate=candidate_estimate,
        difference_candidate_minus_baseline=candidate_estimate.ber-baseline_estimate.ber,
        corrected_errors=corrected,
        introduced_errors=introduced,
        shared_errors=shared,
        unchanged_decisions=unchanged,
        mcnemar_exact_p_value=p_value,
        mcnemar_p_value_underflow=(p_value == 0.0),
        block_confidence_intervals=intervals,
    )

