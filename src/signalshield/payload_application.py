"""Framed text/audio payload simulation using the established M2-M4 engine."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json

import numpy as np

from signalshield.application import MessageSimulationConfig
from signalshield.audio import make_wav
from signalshield.channel import ChannelConfig, ChannelOutput, apply_configured_channel
from signalshield.config import NotchConfig, WaveformConfig
from signalshield.fec import decode as hamming_decode, encode as hamming_encode
from signalshield.filters import rrc_taps
from signalshield.modulation import bpsk_modulate
from signalshield.notch import apply_notch
from signalshield.payload_frame import AUDIO, FrameError, bits_to_bytes, build_frame, bytes_to_bits, parse_frame
from signalshield.receiver import WaveformReceiverOutput, receive_bpsk_waveform
from signalshield.waveform import pulse_shape


@dataclass(frozen=True, slots=True)
class PayloadReceiverResult:
    receiver_name: str
    receiver_output: WaveformReceiverOutput
    coded_errors: int
    coded_ber: float
    post_fec_frame_errors: int | None
    corrected_codewords: int
    crc_valid: bool
    exact_match: bool
    recovered_text: str | None
    recovered_audio_wav: bytes | None
    recovered_payload: bytes | None
    frame_error: str | None


@dataclass(frozen=True, slots=True)
class PayloadSimulationResult:
    configuration_id: str
    payload_type: str
    source_payload: bytes
    frame_bits: np.ndarray
    transmitted_coded_bits: np.ndarray
    transmit_waveform: np.ndarray
    channel: ChannelOutput
    channel_config: ChannelConfig
    taps: np.ndarray
    receivers: dict[str, PayloadReceiverResult]
    fec_enabled: bool
    audio_metadata: dict[str, int] | None
    comparison: dict[str, int | float | None] | None


def run_payload_simulation(config: MessageSimulationConfig, *, payload_type: str = "text",
                           payload: bytes | None = None, audio_metadata: dict[str, int] | None = None,
                           fec_enabled: bool = True) -> PayloadSimulationResult:
    if payload_type == "text":
        payload = config.message.encode("utf-8")
    elif payload_type != "audio" or payload is None:
        raise ValueError("audio payload bytes are required")
    if not payload:
        raise ValueError("Payload must not be empty")
    frame = build_frame(payload, payload_type, audio_metadata)
    frame_bits = bytes_to_bits(frame)
    coded = hamming_encode(frame_bits) if fec_enabled else frame_bits.copy()
    symbols = bpsk_modulate(coded)
    wf = WaveformConfig(config.samples_per_symbol, config.rolloff, config.span_symbols)
    taps = rrc_taps(wf.rolloff, wf.span_symbols, wf.samples_per_symbol)
    tx = pulse_shape(symbols, taps, samples_per_symbol=wf.samples_per_symbol)
    chcfg = ChannelConfig(samples_per_symbol=config.samples_per_symbol,
        ebn0_db=config.ebn0_db if config.awgn_enabled else None, attenuation_db=config.attenuation_db,
        interference_amplitude=config.interference_amplitude_peak if config.interference_enabled else 0.0,
        interference_frequency_cycles_per_symbol=config.interference_frequency_cycles_per_symbol if config.interference_enabled else None,
        interference_phase_rad=config.interference_phase_rad)
    channel = apply_configured_channel(tx, chcfg, rng=np.random.default_rng(config.seed))
    names = ("Baseline Receiver", "Notch-Filtered Receiver") if config.receiver == "Both (paired comparison)" else (config.receiver,)
    results = {}
    for name in names:
        samples = channel.received
        if name == "Notch-Filtered Receiver":
            samples = apply_notch(samples, NotchConfig(config.notch_center_cycles_per_symbol,
                config.samples_per_symbol, config.notch_quality_factor))
        rx = receive_bpsk_waveform(samples, taps, n_symbols=len(coded), samples_per_symbol=config.samples_per_symbol)
        got_coded = rx.detected_bits
        coded_errors = int(np.count_nonzero(coded != got_coded))
        if fec_enabled:
            try:
                got_frame_bits, corrected = hamming_decode(got_coded)
            except ValueError:
                got_frame_bits, corrected = np.array([], dtype=np.uint8), 0
        else:
            got_frame_bits, corrected = got_coded, 0
        post_errors = int(np.count_nonzero(frame_bits != got_frame_bits)) if len(got_frame_bits) == len(frame_bits) else None
        valid, recovered, text, wav, err = False, None, None, None, None
        try:
            parsed = parse_frame(bits_to_bytes(got_frame_bits))
            valid, recovered = parsed.crc_valid, parsed.payload
            if parsed.payload_type == "text":
                text = recovered.decode("utf-8", errors="strict")
            elif parsed.payload_type == "audio":
                wav = make_wav(recovered, parsed.metadata["sample_rate"])
        except (FrameError, UnicodeDecodeError, ValueError) as exc:
            err = str(exc)
        results[name] = PayloadReceiverResult(name, rx, coded_errors, coded_errors / max(1, len(coded)),
            post_errors, corrected, valid, valid and recovered == payload, text, wav, recovered, err)
    comparison = None
    if "Baseline Receiver" in results and "Notch-Filtered Receiver" in results:
        base_bits = results["Baseline Receiver"].receiver_output.detected_bits
        notch_bits = results["Notch-Filtered Receiver"].receiver_output.detected_bits
        base_errors, notch_errors = coded != base_bits, coded != notch_bits
        notch_cfg = NotchConfig(config.notch_center_cycles_per_symbol,
                                config.samples_per_symbol, config.notch_quality_factor)
        notch_tone = apply_notch(channel.interference, notch_cfg)
        notch_wanted = apply_notch(channel.attenuated_signal, notch_cfg)
        tone_rms = float(np.sqrt(np.mean(np.square(channel.interference))))
        residual_tone_rms = float(np.sqrt(np.mean(np.square(notch_tone))))
        wanted_rms = float(np.sqrt(np.mean(np.square(channel.attenuated_signal))))
        comparison = {
            "ber_difference_notch_minus_baseline": results["Notch-Filtered Receiver"].coded_ber - results["Baseline Receiver"].coded_ber,
            "corrected_errors": int(np.count_nonzero(base_errors & ~notch_errors)),
            "introduced_errors": int(np.count_nonzero(~base_errors & notch_errors)),
            "shared_errors": int(np.count_nonzero(base_errors & notch_errors)),
            "unchanged_decisions": int(np.count_nonzero(base_bits == notch_bits)),
            "interference_attenuation_db": (float(20 * np.log10(max(residual_tone_rms, 1e-15) / tone_rms)) if tone_rms else None),
            "desired_signal_rms_gain_after_notch": (float(np.sqrt(np.mean(np.square(notch_wanted))) / wanted_rms) if wanted_rms else None),
            "desired_signal_relative_rms_distortion": (float(np.sqrt(np.mean(np.square(notch_wanted-channel.attenuated_signal))) / wanted_rms) if wanted_rms else None),
        }
    digest = hashlib.sha256(frame + json.dumps({"config": config.configuration_id, "fec": fec_enabled}, sort_keys=True).encode()).hexdigest()[:16]
    return PayloadSimulationResult(digest, payload_type, payload, frame_bits, coded, tx, channel, chcfg, taps,
                                   results, fec_enabled, audio_metadata, comparison)
