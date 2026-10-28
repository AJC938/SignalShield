"""SignalShield M1: reproducible coherent BPSK over real AWGN."""

from signalshield.channel import add_awgn, noise_variance_from_ebn0_db
from signalshield.config import SimulationConfig
from signalshield.config import WaveformConfig
from signalshield.filters import matched_filter, rrc_taps, sample_symbols, symbol_sample_indices
from signalshield.metrics import BerEstimate, ber_estimate, bpsk_awgn_theory
from signalshield.modulation import bpsk_demodulate, bpsk_modulate
from signalshield.receiver import detect_bpsk, receive_bpsk_waveform
from signalshield.signals import generate_bits
from signalshield.waveform import pulse_shape, upsample_symbols

__all__ = [
    "BerEstimate",
    "SimulationConfig",
    "WaveformConfig",
    "add_awgn",
    "ber_estimate",
    "bpsk_awgn_theory",
    "bpsk_demodulate",
    "bpsk_modulate",
    "detect_bpsk",
    "generate_bits",
    "matched_filter",
    "noise_variance_from_ebn0_db",
    "pulse_shape",
    "receive_bpsk_waveform",
    "rrc_taps",
    "sample_symbols",
    "symbol_sample_indices",
    "upsample_symbols",
]

