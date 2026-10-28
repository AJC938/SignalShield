import math

import numpy as np
import pytest

from signalshield.config import WaveformConfig
from signalshield.filters import filter_group_delay_samples, matched_filter, rrc_taps


def test_default_rrc_tap_shape_symmetry_and_unit_energy() -> None:
    config = WaveformConfig()
    taps = rrc_taps()
    assert taps.shape == (81,)
    assert taps.size == config.tap_count
    assert np.all(np.isfinite(taps))
    np.testing.assert_allclose(taps, taps[::-1], rtol=0.0, atol=1e-14)
    assert float(np.dot(taps, taps)) == pytest.approx(1.0, abs=1e-14)
    assert filter_group_delay_samples(taps) == 40
    assert config.total_group_delay_samples == 80


def test_rrc_uses_limits_at_zero_and_rolloff_singularity() -> None:
    beta = 0.25
    sps = 4
    span = 10
    taps = rrc_taps(beta, span, sps)
    times = (np.arange(taps.size) - (taps.size - 1) / 2) / sps
    raw = []
    singular_value = (beta / math.sqrt(2.0)) * (
        (1.0 + 2.0 / math.pi) * math.sin(math.pi / (4.0 * beta))
        + (1.0 - 2.0 / math.pi) * math.cos(math.pi / (4.0 * beta))
    )
    for t in times:
        if abs(t) < 1e-14:
            raw.append(1.0 + beta * (4.0 / math.pi - 1.0))
        elif abs(abs(t) - 1.0 / (4.0 * beta)) < 1e-14:
            raw.append(singular_value)
        else:
            raw.append(
                (
                    math.sin(math.pi * t * (1.0 - beta))
                    + 4.0 * beta * t * math.cos(math.pi * t * (1.0 + beta))
                )
                / (math.pi * t * (1.0 - (4.0 * beta * t) ** 2))
            )
    raw = np.asarray(raw)
    expected = raw / np.linalg.norm(raw)
    np.testing.assert_allclose(taps, expected, rtol=1e-13, atol=1e-14)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rolloff": 0.0},
        {"rolloff": -0.1},
        {"rolloff": 1.1},
        {"span_symbols": 0},
        {"samples_per_symbol": 1},
        {"span_symbols": 1, "samples_per_symbol": 3},
        {"span_symbols": True},
    ],
)
def test_rrc_rejects_invalid_parameters(kwargs) -> None:
    with pytest.raises((TypeError, ValueError)):
        rrc_taps(**kwargs)


def test_matched_filter_is_time_reverse_and_uses_full_convolution() -> None:
    pulse = np.array([1.0, 2.0, 1.0]) / np.sqrt(6.0)
    samples = np.array([1.0, -1.0])
    result = matched_filter(samples, pulse)
    expected = np.convolve(samples, pulse[::-1], mode="full")
    np.testing.assert_array_equal(result, expected)
    assert result.size == samples.size + pulse.size - 1
    np.testing.assert_array_equal(pulse[::-1], pulse)


def test_group_delay_rejects_even_or_nonsymmetric_filter() -> None:
    with pytest.raises(ValueError):
        filter_group_delay_samples([1.0, 0.0])
    with pytest.raises(ValueError):
        filter_group_delay_samples([1.0, 0.0, 0.0])

