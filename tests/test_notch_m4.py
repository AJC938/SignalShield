import numpy as np
import pytest

from signalshield.channel import ChannelConfig, apply_configured_channel
from signalshield.config import NotchConfig
from signalshield.filters import rrc_taps
from signalshield.m4_experiments import compare_receivers
from signalshield.modulation import bpsk_modulate
from signalshield.notch import (
    apply_notch,
    minimum_notch_input_length,
    notch_coefficients,
    notch_frequency_response,
)
from signalshield.receiver import receive_bpsk_waveform
from signalshield.signals import generate_bits
from signalshield.waveform import pulse_shape


def test_notch_response_center_units_and_stability():
    config = NotchConfig(center_frequency_cycles_per_symbol=0.35,
                         samples_per_symbol=8, quality_factor=30)
    b, a = notch_coefficients(config)
    assert np.all(np.abs(np.roots(a)) < 1.0)
    response = notch_frequency_response(config, points=16384)
    assert response.frequency_cycles_per_symbol.shape == response.single_pass_magnitude.shape
    assert response.single_pass_magnitude.shape == response.forward_backward_magnitude.shape
    index = int(np.argmin(np.abs(response.frequency_cycles_per_symbol - 0.35)))
    assert response.frequency_cycles_per_symbol[index] == pytest.approx(0.35, abs=3e-4)
    assert response.forward_backward_magnitude[index] < 1e-3
    _, exact_center = __import__("scipy.signal", fromlist=["freqz"]).freqz(
        b, a, worN=[0.35], fs=8.0)
    assert abs(exact_center[0]) < 1e-12


@pytest.mark.parametrize("center", [0.0, -0.1, 4.0, float("nan"), float("inf")])
def test_invalid_notch_centers_are_rejected(center):
    with pytest.raises((TypeError, ValueError)):
        NotchConfig(center_frequency_cycles_per_symbol=center, samples_per_symbol=8)


@pytest.mark.parametrize("quality", [0.0, 0.49, float("nan"), float("inf"), 1001])
def test_invalid_notch_quality_is_rejected(quality):
    with pytest.raises((TypeError, ValueError)):
        NotchConfig(center_frequency_cycles_per_symbol=0.35, quality_factor=quality)


def test_filter_is_deterministic_length_preserving_and_non_mutating():
    config = NotchConfig(0.35, 8, 30)
    samples = np.random.default_rng(2).normal(size=1000)
    original = samples.copy()
    first = apply_notch(samples, config)
    second = apply_notch(samples, config)
    assert first.shape == samples.shape
    assert first.dtype == np.float64
    assert np.all(np.isfinite(first))
    np.testing.assert_array_equal(first, second)
    np.testing.assert_array_equal(samples, original)


def test_filter_minimum_input_length_and_bad_input_handling():
    config = NotchConfig(0.35, 8, 30)
    min_len = minimum_notch_input_length(config)
    assert min_len == 10
    with pytest.raises(ValueError, match="more than"):
        apply_notch(np.ones(min_len - 1), config)
    assert apply_notch(np.ones(min_len), config).shape == (min_len,)
    with pytest.raises(ValueError):
        apply_notch(np.array([1.0, np.nan] * 20), config)
    with pytest.raises(TypeError):
        apply_notch(np.ones(20, dtype=complex), config)


def _estimated_amplitude(x, f0=0.35, sps=8):
    n = np.arange(200, x.size-200)
    matrix = np.column_stack((np.cos(2*np.pi*f0*n/sps),
                              np.sin(2*np.pi*f0*n/sps), np.ones(n.size)))
    coeff, *_ = np.linalg.lstsq(matrix, x[200:-200], rcond=None)
    return np.hypot(coeff[0], coeff[1])


def test_notch_suppresses_center_tone_and_is_less_effective_off_center():
    config = NotchConfig(0.35, 8, 30)
    n = np.arange(40000)
    center = np.cos(2*np.pi*0.35*n/8)
    offset = np.cos(2*np.pi*0.37*n/8)
    filtered_center = apply_notch(center, config)
    filtered_offset = apply_notch(offset, config)
    center_attenuation = 20*np.log10(_estimated_amplitude(filtered_center) / _estimated_amplitude(center))
    offset_attenuation = 20*np.log10(_estimated_amplitude(filtered_offset, 0.37) / _estimated_amplitude(offset, 0.37))
    assert center_attenuation < -35.0
    assert offset_attenuation > center_attenuation


def test_same_received_samples_feed_pair_and_clean_data_recovers():
    bits = generate_bits(1200, np.random.default_rng(321))
    taps = rrc_taps(0.35, 10, 8)
    tx = pulse_shape(bpsk_modulate(bits), taps, samples_per_symbol=8)
    received = apply_configured_channel(tx, ChannelConfig(samples_per_symbol=8)).received
    baseline_expected = receive_bpsk_waveform(received, taps, n_symbols=bits.size,
                                              samples_per_symbol=8)
    summary, baseline, notch, filtered = compare_receivers(
        received, bits, taps, NotchConfig(0.35, 8, 30),
        bootstrap_seed=123, bootstrap_replicates=30)
    repeated, _, _, _ = compare_receivers(
        received, bits, taps, NotchConfig(0.35, 8, 30),
        bootstrap_seed=123, bootstrap_replicates=30)
    np.testing.assert_array_equal(baseline.detected_bits, baseline_expected.detected_bits)
    np.testing.assert_array_equal(filtered, apply_notch(received, NotchConfig(0.35, 8, 30)))
    np.testing.assert_array_equal(baseline.detected_bits, bits)
    np.testing.assert_array_equal(notch.detected_bits, bits)
    assert summary["baseline_errors"] == summary["notch_errors"] == 0
    assert summary["paired_bits_unchanged"] == bits.size
    assert summary["paired_delta_block_bootstrap_ci95_lower"] <= 0
    assert summary["paired_delta_block_bootstrap_ci95_upper"] >= 0
    for key in ("baseline_errors", "notch_errors", "paired_errors_corrected_by_notch",
                "paired_errors_introduced_by_notch", "paired_delta_block_bootstrap_ci95_lower",
                "paired_delta_block_bootstrap_ci95_upper"):
        assert summary[key] == repeated[key]

