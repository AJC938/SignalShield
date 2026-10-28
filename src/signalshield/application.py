"""UI-independent adapters for interactive SignalShield demonstrations.

The functions in this module translate a UTF-8 message to bits and pass those
bits through the established waveform, channel, receiver, and BER APIs. They
do not implement a second copy of the signal-processing algorithms.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from signalshield.channel import ChannelConfig, ChannelOutput, apply_configured_channel
from signalshield.config import NotchConfig, WaveformConfig
from signalshield.filters import rrc_taps
from signalshield.metrics import BerEstimate, ber_estimate
from signalshield.modulation import bpsk_modulate
from signalshield.notch import apply_notch
from signalshield.receiver import WaveformReceiverOutput, receive_bpsk_waveform
from signalshield.waveform import pulse_shape


ReceiverChoice = Literal["Baseline Receiver", "Notch-Filtered Receiver", "Both (paired comparison)"]


@dataclass(frozen=True, slots=True)
class MessageSimulationConfig:
    """Validated payload-demo settings; ``ebn0_db=None`` disables AWGN."""

    message: str
    seed: int = 20261028
    awgn_enabled: bool = True
    ebn0_db: float = 8.0
    interference_enabled: bool = False
    interference_amplitude_peak: float = 0.22
    interference_frequency_cycles_per_symbol: float = 0.35
    interference_phase_rad: float = 0.0
    attenuation_db: float = 0.0
    receiver: ReceiverChoice = "Baseline Receiver"
    notch_center_cycles_per_symbol: float = 0.35
    notch_quality_factor: float = 30.0
    samples_per_symbol: int = 8
    rolloff: float = 0.35
    span_symbols: int = 10

    def __post_init__(self) -> None:
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("Enter a nonempty text message")
        if len(self.message.encode("utf-8")) > 4096:
            raise ValueError("Message must encode to at most 4096 UTF-8 bytes")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TypeError("seed must be an integer")
        if not 0 <= self.seed < 2**32:
            raise ValueError("seed must be in [0, 2**32-1]")
        if not isinstance(self.awgn_enabled, bool) or not isinstance(self.interference_enabled, bool):
            raise TypeError("channel enable controls must be booleans")
        if self.receiver not in ("Baseline Receiver", "Notch-Filtered Receiver", "Both (paired comparison)"):
            raise ValueError("Select a supported receiver mode")
        WaveformConfig(self.samples_per_symbol, self.rolloff, self.span_symbols)
        numeric = (
            ("ebn0_db", self.ebn0_db),
            ("interference_amplitude_peak", self.interference_amplitude_peak),
            ("interference_frequency_cycles_per_symbol", self.interference_frequency_cycles_per_symbol),
            ("interference_phase_rad", self.interference_phase_rad),
            ("attenuation_db", self.attenuation_db),
            ("notch_center_cycles_per_symbol", self.notch_center_cycles_per_symbol),
            ("notch_quality_factor", self.notch_quality_factor),
        )
        for name, value in numeric:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a real number")
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.interference_amplitude_peak < 0:
            raise ValueError("interference amplitude must be nonnegative")
        if self.attenuation_db < 0:
            raise ValueError("attenuation must be nonnegative")
        if not 0 < self.interference_frequency_cycles_per_symbol < self.samples_per_symbol / 2:
            raise ValueError("tone frequency must satisfy 0 < f < sps/2 cycles/symbol")
        needs_notch = self.receiver != "Baseline Receiver"
        if needs_notch:
            NotchConfig(self.notch_center_cycles_per_symbol, self.samples_per_symbol,
                        self.notch_quality_factor)
        if self.awgn_enabled:
            ChannelConfig(samples_per_symbol=self.samples_per_symbol, ebn0_db=self.ebn0_db)

    @property
    def configuration_id(self) -> str:
        serialized = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class MessagePayload:
    """Exact UTF-8 representation used for a message transmission."""

    source_text: str
    payload_bytes: bytes
    bits: NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class ReceiverPayloadResult:
    """Decoded message and bit-level measurement for one receiver output."""

    receiver_name: str
    receiver_output: WaveformReceiverOutput
    estimate: BerEstimate
    decoded_text: str | None
    decode_error: str | None
    exact_message_recovery: bool


@dataclass(frozen=True, slots=True)
class MessageSimulationResult:
    """Actual arrays and outcomes from one complete message simulation."""

    config: MessageSimulationConfig
    configuration_id: str
    payload: MessagePayload
    symbols: NDArray[np.float64]
    transmit_waveform: NDArray[np.float64]
    channel: ChannelOutput
    channel_config: ChannelConfig
    taps: NDArray[np.float64]
    receiver_results: dict[str, ReceiverPayloadResult]
    comparison: dict[str, int | float | None] | None


def encode_message(message: str) -> MessagePayload:
    """Encode text as UTF-8 bytes, then MSB-first bits within each byte."""
    if not isinstance(message, str):
        raise TypeError("message must be text")
    if not message:
        raise ValueError("message must not be empty")
    raw = message.encode("utf-8")
    if len(raw) > 4096:
        raise ValueError("message must encode to at most 4096 UTF-8 bytes")
    byte_array = np.frombuffer(raw, dtype=np.uint8)
    bits = np.unpackbits(byte_array, bitorder="big").astype(np.uint8, copy=False)
    return MessagePayload(message, raw, bits)


def decode_message(bits: object) -> tuple[str | None, str | None]:
    """Decode MSB-first bits strictly; return a useful reason on failure."""
    checked = np.asarray(bits)
    if checked.ndim != 1 or not np.all((checked == 0) | (checked == 1)):
        raise ValueError("bits must be a one-dimensional sequence containing only 0 and 1")
    if checked.size == 0 or checked.size % 8:
        return None, "Recovered payload does not contain a complete sequence of bytes."
    raw = np.packbits(checked.astype(np.uint8), bitorder="big").tobytes()
    try:
        return raw.decode("utf-8", errors="strict"), None
    except UnicodeDecodeError as exc:
        return None, f"Recovered bytes are not valid UTF-8 ({exc.reason} at byte {exc.start})."


def result_matches_config(result: MessageSimulationResult | None,
                          config: MessageSimulationConfig) -> bool:
    """True only when displayed results belong to the currently selected config."""
    return result is not None and result.configuration_id == config.configuration_id


def _receiver_payload(name: str, output: WaveformReceiverOutput,
                      transmitted_bits: NDArray[np.uint8], original_text: str) -> ReceiverPayloadResult:
    estimate = ber_estimate(transmitted_bits, output.detected_bits)
    decoded, decode_error = decode_message(output.detected_bits)
    return ReceiverPayloadResult(
        receiver_name=name,
        receiver_output=output,
        estimate=estimate,
        decoded_text=decoded,
        decode_error=decode_error,
        exact_message_recovery=decode_error is None and decoded == original_text,
    )


def run_message_simulation(config: MessageSimulationConfig) -> MessageSimulationResult:
    """Run a UTF-8 payload through the established M2/M3/M4 signal chain."""
    if not isinstance(config, MessageSimulationConfig):
        raise TypeError("config must be a MessageSimulationConfig")
    payload = encode_message(config.message)
    symbols = bpsk_modulate(payload.bits)
    waveform = WaveformConfig(config.samples_per_symbol, config.rolloff, config.span_symbols)
    taps = rrc_taps(waveform.rolloff, waveform.span_symbols, waveform.samples_per_symbol)
    tx_waveform = pulse_shape(symbols, taps, samples_per_symbol=waveform.samples_per_symbol)
    channel_config = ChannelConfig(
        samples_per_symbol=config.samples_per_symbol,
        ebn0_db=config.ebn0_db if config.awgn_enabled else None,
        attenuation_db=config.attenuation_db,
        interference_amplitude=(config.interference_amplitude_peak if config.interference_enabled else 0.0),
        interference_frequency_cycles_per_symbol=(
            config.interference_frequency_cycles_per_symbol if config.interference_enabled else None
        ),
        interference_phase_rad=config.interference_phase_rad,
    )
    channel = apply_configured_channel(
        tx_waveform, channel_config, rng=np.random.default_rng(config.seed)
    )

    receiver_outputs: dict[str, WaveformReceiverOutput] = {}
    if config.receiver in ("Baseline Receiver", "Both (paired comparison)"):
        receiver_outputs["Baseline Receiver"] = receive_bpsk_waveform(
            channel.received, taps, n_symbols=payload.bits.size,
            samples_per_symbol=config.samples_per_symbol,
        )
    if config.receiver in ("Notch-Filtered Receiver", "Both (paired comparison)"):
        notch_config = NotchConfig(config.notch_center_cycles_per_symbol,
                                   config.samples_per_symbol, config.notch_quality_factor)
        notched_samples = apply_notch(channel.received, notch_config)
        receiver_outputs["Notch-Filtered Receiver"] = receive_bpsk_waveform(
            notched_samples, taps, n_symbols=payload.bits.size,
            samples_per_symbol=config.samples_per_symbol,
        )

    results = {
        name: _receiver_payload(name, output, payload.bits, config.message)
        for name, output in receiver_outputs.items()
    }
    comparison: dict[str, int | float | None] | None = None
    if "Baseline Receiver" in results and "Notch-Filtered Receiver" in results:
        baseline_errors = payload.bits != results["Baseline Receiver"].receiver_output.detected_bits
        notch_errors = payload.bits != results["Notch-Filtered Receiver"].receiver_output.detected_bits
        notch_config = NotchConfig(config.notch_center_cycles_per_symbol,
                                   config.samples_per_symbol, config.notch_quality_factor)
        notched_interference = apply_notch(channel.interference, notch_config)
        notched_desired = apply_notch(channel.attenuated_signal, notch_config)
        interference_rms = float(np.sqrt(np.mean(np.square(channel.interference))))
        residual_interference_rms = float(np.sqrt(np.mean(np.square(notched_interference))))
        desired_rms = float(np.sqrt(np.mean(np.square(channel.attenuated_signal))))
        notched_desired_rms = float(np.sqrt(np.mean(np.square(notched_desired))))
        comparison = {
            "ber_difference_notch_minus_baseline": (
                results["Notch-Filtered Receiver"].estimate.ber
                - results["Baseline Receiver"].estimate.ber
            ),
            "corrected_errors": int(np.count_nonzero(baseline_errors & ~notch_errors)),
            "introduced_errors": int(np.count_nonzero(~baseline_errors & notch_errors)),
            "shared_errors": int(np.count_nonzero(baseline_errors & notch_errors)),
            "unchanged_decisions": int(np.count_nonzero(
                results["Baseline Receiver"].receiver_output.detected_bits
                == results["Notch-Filtered Receiver"].receiver_output.detected_bits
            )),
            "interference_attenuation_db": (
                float(20.0 * np.log10(max(residual_interference_rms, 1e-15) / interference_rms))
                if interference_rms > 0.0 else None
            ),
            "desired_signal_rms_gain_after_notch": (
                notched_desired_rms / desired_rms if desired_rms > 0.0 else None
            ),
            "desired_signal_relative_rms_distortion": (
                float(np.sqrt(np.mean(np.square(notched_desired - channel.attenuated_signal))) / desired_rms)
                if desired_rms > 0.0 else None
            ),
            "same_transmitted_bits": 1,
            "same_transmitted_waveform": 1,
            "same_channel_realization": 1,
            "same_received_waveform": 1,
        }
    return MessageSimulationResult(
        config=config,
        configuration_id=config.configuration_id,
        payload=payload,
        symbols=symbols,
        transmit_waveform=tx_waveform,
        channel=channel,
        channel_config=channel_config,
        taps=taps,
        receiver_results=results,
        comparison=comparison,
    )
