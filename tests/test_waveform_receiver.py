import numpy as np
import pytest

from signalshield.channel import noise_variance_from_ebn0_db
from signalshield.filters import rrc_taps
from signalshield.metrics import ber_estimate
from signalshield.modulation import bpsk_modulate
from signalshield.receiver import receive_bpsk_waveform
from signalshield.waveform import pulse_shape


def test_combined_rrc_response_main_tap_and_residual_symbol_isi() -> None:
    taps = rrc_taps()
    cascade = np.convolve(taps, taps[::-1], mode="full")
    center = taps.size - 1
    symbol_offsets = np.arange(-10, 11)
    symbol_response = cascade[center + symbol_offsets * 8]
    main = symbol_response[symbol_offsets == 0][0]
    sidelobes = np.abs(symbol_response[symbol_offsets != 0])
    assert main == pytest.approx(1.0, abs=2e-14)
    assert float(np.max(sidelobes)) == pytest.approx(0.005816568303543849, rel=1e-11)
    assert float(np.sum(sidelobes)) == pytest.approx(0.020364309246394197, rel=1e-11)


def test_noiseless_waveform_recovers_payload_at_expected_indices() -> None:
    bits = np.random.default_rng(7712).integers(0, 2, size=1001, dtype=np.uint8)
    symbols = bpsk_modulate(bits)
    taps = rrc_taps()
    tx = pulse_shape(symbols, taps, samples_per_symbol=8)
    output = receive_bpsk_waveform(tx, taps, n_symbols=bits.size, samples_per_symbol=8)
    expected_indices = 80 + np.arange(bits.size) * 8
    np.testing.assert_array_equal(output.sample_indices, expected_indices)
    assert output.filtered_samples.size == tx.size + taps.size - 1
    assert output.decision_samples.size == bits.size
    np.testing.assert_array_equal(output.detected_bits, bits)
    assert ber_estimate(bits, output.detected_bits).errors == 0
    # The bounded decision-sample deviation is explained by the measured
    # sum of all finite-filter symbol-spaced sidelobes.
    assert np.max(np.abs(output.decision_samples - symbols)) <= 0.020364309247


def test_matched_filter_noise_variance_remains_sigma_squared() -> None:
    n_symbols = 20_000
    sps = 8
    taps = rrc_taps()
    variance = noise_variance_from_ebn0_db(4.0)
    tx_length = (n_symbols - 1) * sps + taps.size
    noise = np.random.default_rng(99012).normal(0.0, np.sqrt(variance), size=tx_length)
    output = receive_bpsk_waveform(noise, taps, n_symbols=n_symbols, samples_per_symbol=sps)
    measured_variance = float(np.var(output.decision_samples, ddof=1))
    standard_error = variance * np.sqrt(2.0 / (n_symbols - 1))
    assert abs(float(np.mean(output.decision_samples))) <= 6.0 * np.sqrt(variance / n_symbols)
    assert abs(measured_variance - variance) <= 6.0 * standard_error

