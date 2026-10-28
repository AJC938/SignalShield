"""Validated configuration for the M1 reference BPSK simulation."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """Parameters for one uncoded, one-sample-per-bit BPSK/AWGN run.

    ``ebn0_db`` is restricted to [-100, 300] dB to avoid meaningless or
    numerically unrepresentable noise powers. M1 assumes real symbols and
    ``bit_energy=1`` by default.
    """

    n_bits: int = 200_000
    ebn0_db: float = 0.0
    seed: int = 20261027
    bit_energy: float = 1.0

    def __post_init__(self) -> None:
        if isinstance(self.n_bits, bool) or not isinstance(self.n_bits, int):
            raise TypeError("n_bits must be an integer")
        if self.n_bits <= 0:
            raise ValueError("n_bits must be greater than zero")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TypeError("seed must be an integer")
        if self.seed < 0 or self.seed >= 2**32:
            raise ValueError("seed must be in the range [0, 2**32 - 1]")
        if isinstance(self.ebn0_db, bool) or not isinstance(self.ebn0_db, (int, float)):
            raise TypeError("ebn0_db must be a real number")
        if not math.isfinite(self.ebn0_db) or not -100.0 <= self.ebn0_db <= 300.0:
            raise ValueError("ebn0_db must be finite and in the range [-100, 300] dB")
        if isinstance(self.bit_energy, bool) or not isinstance(self.bit_energy, (int, float)):
            raise TypeError("bit_energy must be a real number")
        if not math.isfinite(self.bit_energy) or self.bit_energy <= 0.0:
            raise ValueError("bit_energy must be finite and greater than zero")


@dataclass(frozen=True, slots=True)
class WaveformConfig:
    """Finite real RRC waveform settings, separate from the M1 link config.

    The default pulse spans 10 symbols and uses 8 samples per symbol with
    roll-off 0.35. Zero roll-off is intentionally unsupported in M2.
    """

    samples_per_symbol: int = 8
    rolloff: float = 0.35
    span_symbols: int = 10

    def __post_init__(self) -> None:
        if isinstance(self.samples_per_symbol, bool) or not isinstance(self.samples_per_symbol, int):
            raise TypeError("samples_per_symbol must be an integer")
        if self.samples_per_symbol < 2:
            raise ValueError("samples_per_symbol must be at least 2 for the sampled waveform model")
        if isinstance(self.span_symbols, bool) or not isinstance(self.span_symbols, int):
            raise TypeError("span_symbols must be an integer")
        if self.span_symbols <= 0:
            raise ValueError("span_symbols must be greater than zero")
        if (self.span_symbols * self.samples_per_symbol) % 2 != 0:
            raise ValueError("span_symbols * samples_per_symbol must be even for an integer-centered FIR")
        if isinstance(self.rolloff, bool) or not isinstance(self.rolloff, (int, float)):
            raise TypeError("rolloff must be a real number")
        if not math.isfinite(self.rolloff) or not 0.0 < self.rolloff <= 1.0:
            raise ValueError("rolloff must be finite and in the range (0, 1]")

    @property
    def tap_count(self) -> int:
        """Return the odd tap count ``span_symbols*samples_per_symbol+1``."""
        return self.span_symbols * self.samples_per_symbol + 1

    @property
    def group_delay_samples(self) -> int:
        """Return the integer linear-phase group delay in samples."""
        return (self.tap_count - 1) // 2

    @property
    def total_group_delay_samples(self) -> int:
        """Return equal Tx/Rx filter delay through the decision path."""
        return 2 * self.group_delay_samples


@dataclass(frozen=True, slots=True)
class NotchConfig:
    """Offline IIR notch settings; frequency is expressed in cycles/symbol.

    The supported range ``0.5 <= Q <= 1000`` spans broad educational notches
    through narrow, numerically practical notches. Filtering uses zero-phase
    forward-backward processing and is therefore not a real-time receiver.
    """

    center_frequency_cycles_per_symbol: float
    samples_per_symbol: int = 8
    quality_factor: float = 30.0

    def __post_init__(self) -> None:
        if isinstance(self.samples_per_symbol, bool) or not isinstance(self.samples_per_symbol, int):
            raise TypeError("samples_per_symbol must be an integer")
        if self.samples_per_symbol < 2:
            raise ValueError("samples_per_symbol must be at least 2")
        if (isinstance(self.center_frequency_cycles_per_symbol, bool)
                or not isinstance(self.center_frequency_cycles_per_symbol, (int, float))):
            raise TypeError("center_frequency_cycles_per_symbol must be a real number")
        center = float(self.center_frequency_cycles_per_symbol)
        if not math.isfinite(center) or not 0.0 < center < self.samples_per_symbol / 2.0:
            raise ValueError("notch center must satisfy 0 < f0 < samples_per_symbol/2 cycles/symbol")
        if isinstance(self.quality_factor, bool) or not isinstance(self.quality_factor, (int, float)):
            raise TypeError("quality_factor must be a real number")
        q = float(self.quality_factor)
        if not math.isfinite(q) or not 0.5 <= q <= 1000.0:
            raise ValueError("quality_factor must be finite and within the supported range [0.5, 1000]")

