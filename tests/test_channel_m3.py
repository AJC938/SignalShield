import numpy as np
import pytest

from signalshield.channel import (
    ChannelConfig,
    add_awgn,
    apply_attenuation,
    apply_configured_channel,
    attenuation_gain,
    generate_sinusoidal_interference,
    noise_variance_from_ebn0_db,
)
from signalshield.filters import rrc_taps
from signalshield.modulation import bpsk_modulate
from signalshield.receiver import receive_bpsk_waveform
from signalshield.waveform import pulse_shape


def test_awgn_configuration_matches_existing_primitive_and_is_reproducible():
    x = np.linspace(-1.0, 1.0, 20000)
    variance = noise_variance_from_ebn0_db(4.0)
    old = add_awgn(x, variance, np.random.default_rng(31))
    out = apply_configured_channel(x, ChannelConfig(samples_per_symbol=8, ebn0_db=4.0),
                                  rng=np.random.default_rng(31))
    np.testing.assert_array_equal(out.received, old)
    assert out.noise.dtype == np.float64
    assert out.noise.shape == x.shape
    assert abs(np.mean(out.noise)) < 6 * np.sqrt(variance / x.size)
    assert abs(np.var(out.noise, ddof=1) - variance) < 6 * variance * np.sqrt(2 / (x.size - 1))


def test_interference_frequency_phase_peak_and_zero_amplitude():
    sps, freq, phase, amplitude = 8, 1.0, np.pi / 2, 0.4
    n = np.arange(4096)
    tone = generate_sinusoidal_interference(n.size, samples_per_symbol=sps,
                                            amplitude_peak=amplitude,
                                            frequency_cycles_per_symbol=freq,
                                            phase_rad=phase)
    assert tone.shape == (n.size,)
    assert tone.dtype == np.float64
    np.testing.assert_allclose(tone, amplitude*np.cos(2*np.pi*freq*n/sps+phase))
    spectrum = np.abs(np.fft.rfft(tone))
    peak_bin = int(np.argmax(spectrum[1:]) + 1)
    assert np.fft.rfftfreq(n.size, d=1/sps)[peak_bin] == pytest.approx(freq)
    assert np.max(np.abs(tone)) == pytest.approx(amplitude, abs=1e-12)
    np.testing.assert_array_equal(generate_sinusoidal_interference(
        16, samples_per_symbol=8, amplitude_peak=0, frequency_cycles_per_symbol=1), np.zeros(16))


@pytest.mark.parametrize("frequency", [0.0, 4.0, -0.1, float("nan")])
def test_invalid_interference_frequencies_are_rejected(frequency):
    with pytest.raises(ValueError):
        ChannelConfig(samples_per_symbol=8, interference_amplitude=0.1,
                      interference_frequency_cycles_per_symbol=frequency)


@pytest.mark.parametrize("kwargs", [
    {"attenuation_db": -1.0}, {"attenuation_db": float("inf")},
    {"interference_amplitude": -0.1}, {"interference_amplitude": float("nan")},
])
def test_invalid_channel_parameters_are_rejected(kwargs):
    with pytest.raises((ValueError, TypeError)):
        ChannelConfig(**kwargs)


def test_attenuation_known_values_and_alignment():
    x = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
    np.testing.assert_array_equal(apply_attenuation(x, 0.0), x)
    np.testing.assert_allclose(apply_attenuation(x, 6.0), x * 10**(-6/20))
    assert attenuation_gain(20.0) == pytest.approx(0.1)
    assert apply_attenuation(x, 6.0).shape == x.shape


def test_channel_composition_follows_documented_equation_and_reproduces():
    tx = np.array([1.0, -2.0, 0.5, 3.0])
    config = ChannelConfig(samples_per_symbol=8, ebn0_db=5.0, attenuation_db=2.0,
                           interference_amplitude=0.3,
                           interference_frequency_cycles_per_symbol=0.5,
                           interference_phase_rad=0.2)
    first = apply_configured_channel(tx, config, rng=np.random.default_rng(7))
    second = apply_configured_channel(tx, config, rng=np.random.default_rng(7))
    np.testing.assert_array_equal(first.received, second.received)
    np.testing.assert_array_equal(first.received, first.attenuated_signal + first.interference + first.noise)
    np.testing.assert_allclose(first.attenuated_signal, tx * 10**(-2/20))
    assert first.received.size == tx.size
    with pytest.raises(TypeError):
        apply_configured_channel(tx, config)


def test_disabled_components_and_noiseless_end_to_end_recovery():
    bits = np.random.default_rng(15).integers(0, 2, size=151, dtype=np.uint8)
    taps = rrc_taps(0.35, 10, 8)
    tx = pulse_shape(bpsk_modulate(bits), taps, samples_per_symbol=8)
    config = ChannelConfig(samples_per_symbol=8)
    output = apply_configured_channel(tx, config)
    np.testing.assert_array_equal(output.received, tx)
    np.testing.assert_array_equal(output.interference, np.zeros_like(tx))
    np.testing.assert_array_equal(output.noise, np.zeros_like(tx))
    rx = receive_bpsk_waveform(output.received, taps, n_symbols=bits.size, samples_per_symbol=8)
    np.testing.assert_array_equal(rx.detected_bits, bits)


def test_tone_only_composition_and_waveform_awgn_reference_integration():
    bits = np.random.default_rng(125).integers(0, 2, size=5000, dtype=np.uint8)
    taps = rrc_taps(0.35, 10, 8)
    tx = pulse_shape(bpsk_modulate(bits), taps, samples_per_symbol=8)
    tone_cfg = ChannelConfig(samples_per_symbol=8, interference_amplitude=0.2,
                             interference_frequency_cycles_per_symbol=0.3,
                             interference_phase_rad=0.6)
    tone_result = apply_configured_channel(tx, tone_cfg)
    np.testing.assert_array_equal(tone_result.received, tx + tone_result.interference)
    np.testing.assert_array_equal(tone_result.interference,
        generate_sinusoidal_interference(tx.size, samples_per_symbol=8, amplitude_peak=0.2,
                                         frequency_cycles_per_symbol=0.3, phase_rad=0.6))

    # With a fixed seed, the configurable AWGN-only route must be sample-for-sample
    # equivalent to the established M2 primitive and receiver path.
    from signalshield.channel import add_awgn
    snr_db, noise_seed = 5.0, 9102
    variance = noise_variance_from_ebn0_db(snr_db)
    legacy = add_awgn(tx, variance, np.random.default_rng(noise_seed))
    configured = apply_configured_channel(tx, ChannelConfig(samples_per_symbol=8, ebn0_db=snr_db),
                                          rng=np.random.default_rng(noise_seed))
    np.testing.assert_array_equal(configured.received, legacy)
    m2_detected = receive_bpsk_waveform(legacy, taps, n_symbols=bits.size, samples_per_symbol=8).detected_bits
    m3_detected = receive_bpsk_waveform(configured.received, taps, n_symbols=bits.size,
                                        samples_per_symbol=8).detected_bits
    np.testing.assert_array_equal(m3_detected, m2_detected)


def test_awgn_requires_explicit_rng_only_when_enabled():
    x = np.ones(4)
    np.testing.assert_array_equal(apply_configured_channel(x, ChannelConfig()).received, x)
    with pytest.raises(ValueError):
        ChannelConfig(samples_per_symbol=1)
    with pytest.raises(ValueError):
        ChannelConfig(samples_per_symbol=8, ebn0_db=4, interference_amplitude=0.2)
