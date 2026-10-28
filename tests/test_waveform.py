import numpy as np
import pytest

from signalshield.config import WaveformConfig
from signalshield.filters import rrc_taps
from signalshield.waveform import pulse_shape, upsample_symbols


def test_waveform_config_defaults_and_validation() -> None:
    config = WaveformConfig()
    assert config.samples_per_symbol == 8
    assert config.rolloff == 0.35
    assert config.span_symbols == 10
    assert config.tap_count == 81
    assert config.group_delay_samples == 40
    assert config.total_group_delay_samples == 80
    with pytest.raises(ValueError):
        WaveformConfig(rolloff=0.0)
    with pytest.raises(ValueError):
        WaveformConfig(samples_per_symbol=1)
    with pytest.raises(ValueError):
        WaveformConfig(samples_per_symbol=3, span_symbols=1)


def test_upsampling_inserts_zeros_and_preserves_symbol_indices() -> None:
    symbols = np.array([1.0, -1.0, 0.5])
    upsampled = upsample_symbols(symbols, samples_per_symbol=4)
    assert upsampled.size == (symbols.size - 1) * 4 + 1
    np.testing.assert_array_equal(upsampled[::4], symbols)
    np.testing.assert_array_equal(upsampled, [1, 0, 0, 0, -1, 0, 0, 0, 0.5])
    with pytest.raises(ValueError):
        upsample_symbols([], samples_per_symbol=4)
    with pytest.raises(ValueError):
        upsample_symbols([1.0], samples_per_symbol=1)


def test_pulse_shaping_full_convolution_dimensions_and_finiteness() -> None:
    symbols = np.array([1.0, -1.0, 1.0, 1.0])
    taps = rrc_taps()
    shaped = pulse_shape(symbols, taps, samples_per_symbol=8)
    expected_length = (symbols.size - 1) * 8 + taps.size
    assert shaped.shape == (expected_length,)
    assert np.all(np.isfinite(shaped))
    np.testing.assert_allclose(
        shaped,
        np.convolve(upsample_symbols(symbols, 8), taps, mode="full"),
    )

