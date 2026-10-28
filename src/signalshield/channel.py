"""Independent real-AWGN primitives for the reference discrete model."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from signalshield.signals import as_real_samples


@dataclass(frozen=True, slots=True)
class ChannelConfig:
    """Validated settings for the sampled real channel.

    Noise is parameterized by the M2 normalized discrete Eb/N0 convention.
    A zero tone amplitude disables the deterministic tone. Attenuation is
    applied to the wanted waveform only; tone and AWGN are added afterward.
    """

    samples_per_symbol: int = 8
    ebn0_db: float | None = None
    attenuation_db: float = 0.0
    interference_amplitude: float = 0.0
    interference_frequency_cycles_per_symbol: float | None = None
    interference_phase_rad: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.samples_per_symbol, bool) or not isinstance(self.samples_per_symbol, int):
            raise TypeError("samples_per_symbol must be an integer")
        if self.samples_per_symbol < 2:
            raise ValueError("samples_per_symbol must be at least 2")
        for name in ("attenuation_db", "interference_amplitude", "interference_phase_rad"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a real number")
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.attenuation_db < 0.0:
            raise ValueError("attenuation_db must be nonnegative")
        if self.interference_amplitude < 0.0:
            raise ValueError("interference_amplitude must be nonnegative")
        if self.ebn0_db is not None:
            noise_variance_from_ebn0_db(self.ebn0_db)
        if self.interference_frequency_cycles_per_symbol is not None:
            frequency = self.interference_frequency_cycles_per_symbol
            if isinstance(frequency, bool) or not isinstance(frequency, (int, float)):
                raise TypeError("interference_frequency_cycles_per_symbol must be a real number")
            if not math.isfinite(frequency) or not 0.0 < frequency < self.samples_per_symbol / 2.0:
                raise ValueError("interference frequency must satisfy 0 < f_sym < samples_per_symbol/2")
        if self.interference_amplitude > 0.0 and self.interference_frequency_cycles_per_symbol is None:
            raise ValueError("a positive interference amplitude requires a configured frequency")

    @property
    def desired_gain(self) -> float:
        """Linear voltage gain corresponding to the configured attenuation."""
        return 10.0 ** (-float(self.attenuation_db) / 20.0)

    @property
    def noise_variance(self) -> float:
        """Configured real AWGN variance, or zero when AWGN is disabled."""
        return 0.0 if self.ebn0_db is None else noise_variance_from_ebn0_db(self.ebn0_db)


@dataclass(frozen=True, slots=True)
class ChannelOutput:
    """Received samples and same-length component arrays for diagnostics."""

    received: NDArray[np.float64]
    attenuated_signal: NDArray[np.float64]
    interference: NDArray[np.float64]
    noise: NDArray[np.float64]
    applied_gain: float


def attenuation_gain(attenuation_db: float) -> float:
    """Convert nonnegative attenuation in dB to linear voltage gain."""
    if isinstance(attenuation_db, bool) or not isinstance(attenuation_db, (int, float)):
        raise TypeError("attenuation_db must be a real number")
    if not math.isfinite(attenuation_db) or attenuation_db < 0.0:
        raise ValueError("attenuation_db must be finite and nonnegative")
    return 10.0 ** (-float(attenuation_db) / 20.0)


def apply_attenuation(samples: object, attenuation_db: float) -> NDArray[np.float64]:
    """Apply constant nonnegative dB attenuation without changing alignment."""
    checked = as_real_samples(samples)
    return checked * attenuation_gain(attenuation_db)


def generate_sinusoidal_interference(
    n_samples: int,
    *,
    samples_per_symbol: int,
    amplitude_peak: float,
    frequency_cycles_per_symbol: float,
    phase_rad: float = 0.0,
) -> NDArray[np.float64]:
    """Generate ``A*cos(2π f_sym*n/sps + phase)`` in real sample units."""
    if isinstance(n_samples, bool) or not isinstance(n_samples, int):
        raise TypeError("n_samples must be an integer")
    if n_samples <= 0:
        raise ValueError("n_samples must be positive")
    config = ChannelConfig(
        samples_per_symbol=samples_per_symbol,
        interference_amplitude=amplitude_peak,
        interference_frequency_cycles_per_symbol=frequency_cycles_per_symbol,
        interference_phase_rad=phase_rad,
    )
    n = np.arange(n_samples, dtype=np.float64)
    if config.interference_amplitude == 0.0:
        return np.zeros(n_samples, dtype=np.float64)
    return config.interference_amplitude * np.cos(
        2.0 * np.pi * float(config.interference_frequency_cycles_per_symbol) * n / config.samples_per_symbol
        + config.interference_phase_rad
    )


def apply_configured_channel(
    samples: object,
    config: ChannelConfig,
    *,
    rng: np.random.Generator | None = None,
) -> ChannelOutput:
    """Apply gain, sinusoidal interference, then AWGN to a real waveform.

    Components are returned separately and all arrays preserve the input
    length. The attenuation describes the wanted signal only; configured
    interference and receiver-side AWGN are not attenuated.
    """
    source = as_real_samples(samples)
    if not isinstance(config, ChannelConfig):
        raise TypeError("config must be a ChannelConfig")
    gain = config.desired_gain
    wanted = source * gain
    if config.interference_amplitude == 0.0:
        interference = np.zeros_like(source)
    else:
        interference = generate_sinusoidal_interference(
            int(source.size),
            samples_per_symbol=config.samples_per_symbol,
            amplitude_peak=config.interference_amplitude,
            frequency_cycles_per_symbol=float(config.interference_frequency_cycles_per_symbol),
            phase_rad=config.interference_phase_rad,
        )
    if config.noise_variance == 0.0:
        noise = np.zeros_like(source)
    else:
        if not isinstance(rng, np.random.Generator):
            raise TypeError("rng must be a numpy.random.Generator when AWGN is enabled")
        noise = rng.normal(0.0, math.sqrt(config.noise_variance), size=source.size).astype(np.float64)
    received = wanted + interference + noise
    return ChannelOutput(received, wanted, interference, noise, gain)


def mean_square_power(samples: object) -> float:
    """Return mean-square power over the supplied finite waveform record."""
    checked = as_real_samples(samples)
    return float(np.mean(np.square(checked)))


def ebn0_db_to_linear(ebn0_db: float) -> float:
    """Convert an Eb/N0 value from dB to its positive linear ratio."""
    if isinstance(ebn0_db, bool) or not isinstance(ebn0_db, (int, float)):
        raise TypeError("ebn0_db must be a real number")
    if not math.isfinite(ebn0_db):
        raise ValueError("ebn0_db must be finite")
    ratio = 10.0 ** (float(ebn0_db) / 10.0)
    if not math.isfinite(ratio) or ratio <= 0.0:
        raise ValueError("ebn0_db is outside the numerically supported range")
    return ratio


def noise_variance_from_ebn0_db(ebn0_db: float, bit_energy: float = 1.0) -> float:
    """Return real-sample AWGN variance ``Eb / (2 * linear Eb/N0)``."""
    if isinstance(bit_energy, bool) or not isinstance(bit_energy, (int, float)):
        raise TypeError("bit_energy must be a real number")
    if not math.isfinite(bit_energy) or bit_energy <= 0.0:
        raise ValueError("bit_energy must be finite and greater than zero")
    variance = float(bit_energy) / (2.0 * ebn0_db_to_linear(ebn0_db))
    if not math.isfinite(variance) or variance <= 0.0:
        raise ValueError("computed noise variance is outside the numerical range")
    return variance


def add_awgn(
    samples: object,
    variance: float,
    rng: np.random.Generator,
) -> NDArray[np.float64]:
    """Add independent real zero-mean Gaussian noise with given variance."""
    checked = as_real_samples(samples)
    if isinstance(variance, bool) or not isinstance(variance, (int, float)):
        raise TypeError("variance must be a real number")
    if not math.isfinite(variance) or variance < 0.0:
        raise ValueError("variance must be finite and nonnegative")
    if not isinstance(rng, np.random.Generator):
        raise TypeError("rng must be a numpy.random.Generator")
    if variance == 0.0:
        return checked.copy()
    noise = rng.normal(loc=0.0, scale=math.sqrt(variance), size=checked.size)
    return checked + noise

