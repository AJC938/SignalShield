"""Streamlit interface for the SignalShield communication laboratory."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st

from signalshield.application import (
    MessageSimulationConfig,
    MessageSimulationResult,
    result_matches_config,
    run_message_simulation,
)
from signalshield.experiment_framework import (
    DEFAULT_EBN0_VALUES,
    DEFAULT_SWEEP_VALUES,
    SUPPORTED_SCENARIOS,
    ExperimentConfig,
)
from signalshield.experiment_runner import run_experiment
from signalshield.audio import load_wav, make_wav
from signalshield.payload_application import PayloadSimulationResult, run_payload_simulation
from signalshield.ui_theme import apply_ui_theme


APP_TITLE = "SignalShield"
APP_SUBTITLE = "Send a text message or a short audio clip through a simulated digital link."
MAX_DISPLAY_SAMPLES = 1800
MAX_PERFORMANCE_BITS = 250_000
MAX_PERFORMANCE_TOTAL_BITS = 1_000_000
PALETTE = {
    "text": "#172B3A", "muted": "#526575", "grid": "#D9E2EA",
    "transmit": "#087E8B", "received": "#263746", "interference": "#D97706",
    "noise": "#B45309", "receiver": "#6D5BD0", "error": "#B42318",
}


def _render_workflow(input_ready: bool, config_ready: bool, result: PayloadSimulationResult | None,
                     result_current: bool) -> None:
    stages = [
        ("01", "Input", "Ready" if input_ready else "Awaiting input"),
        ("02", "Channel", "Configured" if config_ready else "Check settings"),
        ("03", "Receiver", "Configured" if config_ready else "Check settings"),
        ("04", "Recovery", ("Verified" if all(r.crc_valid and r.exact_match for r in result.receivers.values())
                              else "Review result") if result is not None and result_current else "Run required"),
    ]
    cols = st.columns(4)
    for col, (number, name, state) in zip(cols, stages):
        with col, st.container(border=True):
            st.caption(number)
            st.markdown(f"**{name}**")
            st.caption(state)


def _style_plot(ax: Any) -> None:
    ax.set_facecolor("#FFFFFF")
    ax.grid(True, color=PALETTE["grid"], linewidth=0.65, alpha=0.8)
    ax.tick_params(colors=PALETTE["muted"], labelsize=8)
    ax.title.set_color(PALETTE["text"])
    ax.xaxis.label.set_color(PALETTE["muted"])
    ax.yaxis.label.set_color(PALETTE["muted"])
    for spine in ax.spines.values():
        spine.set_color("#D9E2EA")


def _plot_spectrum(ax: Any, signal: np.ndarray, samples_per_symbol: int,
                   title: str, color: str) -> None:
    size = min(len(signal), 8192)
    window = np.hanning(size)
    spectrum = np.fft.rfft(signal[:size] * window)
    frequency = np.fft.rfftfreq(size, d=1.0 / samples_per_symbol)
    ax.plot(frequency, 20*np.log10(np.maximum(np.abs(spectrum), 1e-12)), color=color, linewidth=.8)
    ax.set(title=f"{title} · first {size:,} actual samples", xlabel="Frequency (cycles/symbol)", ylabel="Relative magnitude (dB)")


def _make_message_config() -> MessageSimulationConfig:
    return MessageSimulationConfig(
        message=st.session_state.get("message_text", "SignalShield demo"),
        seed=int(st.session_state.get("message_seed", 20261028)),
        awgn_enabled=bool(st.session_state.get("message_awgn", True)),
        ebn0_db=float(st.session_state.get("message_ebn0", 8.0)),
        interference_enabled=bool(st.session_state.get("message_tone_enabled", False)),
        interference_amplitude_peak=float(st.session_state.get("message_tone_amplitude", 0.22)),
        interference_frequency_cycles_per_symbol=float(st.session_state.get("message_tone_frequency", 0.35)),
        interference_phase_rad=float(st.session_state.get("message_tone_phase", 0.0)),
        attenuation_db=float(st.session_state.get("message_attenuation", 0.0)),
        receiver=st.session_state.get("message_receiver", "Baseline Receiver"),
        notch_center_cycles_per_symbol=float(st.session_state.get("message_notch_center", 0.35)),
        notch_quality_factor=float(st.session_state.get("message_notch_q", 30.0)),
        samples_per_symbol=int(st.session_state.get("message_sps", 8)),
        rolloff=float(st.session_state.get("message_rolloff", 0.35)),
        span_symbols=int(st.session_state.get("message_span", 10)),
    )


def _show_actual_array_plot(result: MessageSimulationResult) -> None:
    tx = result.transmit_waveform
    rx = result.channel.received
    shown = min(MAX_DISPLAY_SAMPLES, tx.size, rx.size)
    symbols_in_view = sum(result.receiver_results[next(iter(result.receiver_results))]
                          .receiver_output.sample_indices < shown)
    st.caption(
        f"Waveform display shows the first {shown:,} samples of {rx.size:,}; "
        f"{symbols_in_view:,} symbol decision instants fall in this view."
    )
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), constrained_layout=True)
    x = np.arange(shown)
    axes[0].plot(x, tx[:shown], color="#1769aa", linewidth=1.0)
    axes[0].set_title("Transmitted pulse-shaped waveform (actual simulation samples)")
    axes[0].set_ylabel("Amplitude")
    axes[0].set_xlabel("Sample index")
    axes[0].grid(alpha=0.25)

    axes[1].plot(x, rx[:shown], label="Received", color="#343a40", linewidth=0.9)
    if np.any(result.channel.interference[:shown]):
        axes[1].plot(x, result.channel.interference[:shown], label="Interference", alpha=0.8)
    if np.any(result.channel.noise[:shown]):
        axes[1].plot(x, result.channel.noise[:shown], label="AWGN component", alpha=0.55)
    axes[1].set_title("Received waveform and enabled channel components")
    axes[1].set_ylabel("Amplitude")
    axes[1].set_xlabel("Sample index")
    axes[1].grid(alpha=0.25)
    axes[1].legend(loc="upper right")

    selected_name = ("Baseline Receiver" if "Baseline Receiver" in result.receiver_results
                     else "Notch-Filtered Receiver")
    output = result.receiver_results[selected_name].receiver_output
    filtered = output.filtered_samples
    show_filtered = min(MAX_DISPLAY_SAMPLES, filtered.size)
    axes[2].plot(np.arange(show_filtered), filtered[:show_filtered],
                 color="#6a1b9a", linewidth=0.9, label="Matched-filter output")
    visible_indices = output.sample_indices[output.sample_indices < show_filtered]
    axes[2].scatter(visible_indices,
                    output.decision_samples[:visible_indices.size],
                    marker="x", color="#d84315", label="Actual symbol decision samples")
    axes[2].set_title(f"{selected_name}: matched-filter output and M2 sampling instants")
    axes[2].set_ylabel("Amplitude")
    axes[2].set_xlabel("Sample index")
    axes[2].grid(alpha=0.25)
    axes[2].legend(loc="upper right")
    st.pyplot(fig, clear_figure=True)
    plt.close(fig)

    if result.channel_config.interference_amplitude > 0.0:
        spectrum_size = min(rx.size, 8192)
        window = np.hanning(spectrum_size)
        spectrum = np.fft.rfft(rx[:spectrum_size] * window)
        frequency = np.fft.rfftfreq(spectrum_size, d=1.0 / result.config.samples_per_symbol)
        magnitude_db = 20.0 * np.log10(np.maximum(np.abs(spectrum), 1e-12))
        spectrum_fig, ax = plt.subplots(figsize=(11, 3.5), constrained_layout=True)
        ax.plot(frequency, magnitude_db, color="#00897b")
        ax.axvline(result.channel_config.interference_frequency_cycles_per_symbol,
                   color="#c62828", linestyle="--", label="Configured tone frequency")
        ax.set_title("Received-record magnitude spectrum (actual samples, Hann window)")
        ax.set_xlabel("Frequency (cycles/symbol)")
        ax.set_ylabel("Magnitude (dB, relative)")
        ax.grid(alpha=0.25)
        ax.legend()
        st.pyplot(spectrum_fig, clear_figure=True)
        plt.close(spectrum_fig)


def _render_message_result(result: MessageSimulationResult) -> None:
    payload = result.payload
    st.success(f"Run completed · configuration `{result.configuration_id}`")
    st.markdown("**Original message**")
    st.code(payload.source_text)
    st.write(f"UTF-8 bytes ({len(payload.payload_bytes)}): `{payload.payload_bytes.hex(' ')}`")
    bit_preview = "".join(str(int(bit)) for bit in payload.bits[:256])
    suffix = " … (display truncated)" if payload.bits.size > 256 else ""
    st.write(f"Encoded bits, MSB first ({payload.bits.size} bits): `{bit_preview}`{suffix}")
    st.write(f"Sampled transmit waveform: {result.transmit_waveform.size:,} samples")

    c1, c2, c3 = st.columns(3)
    c1.metric("Payload bits", f"{payload.bits.size:,}")
    c2.metric("Attenuation gain", f"{result.channel.applied_gain:.5f}")
    c3.metric("Received samples", f"{result.channel.received.size:,}")
    st.json({
        "Eb/N0 dB": result.channel_config.ebn0_db,
        "AWGN enabled": result.channel_config.ebn0_db is not None,
        "AWGN variance": result.channel_config.noise_variance,
        "tone amplitude peak": result.channel_config.interference_amplitude,
        "tone frequency cycles/symbol": result.channel_config.interference_frequency_cycles_per_symbol,
        "tone phase radians": result.channel_config.interference_phase_rad,
        "attenuation dB": result.channel_config.attenuation_db,
        "receiver mode": result.config.receiver,
        "samples/symbol": result.config.samples_per_symbol,
        "RRC rolloff": result.config.rolloff,
        "RRC span symbols": result.config.span_symbols,
        "noise seed": result.config.seed,
    })

    for name, receiver in result.receiver_results.items():
        st.subheader(name)
        a, b, c = st.columns(3)
        a.metric("Recovered bits", f"{receiver.estimate.n_bits:,}")
        b.metric("Bit errors", f"{receiver.estimate.errors:,}")
        c.metric("Payload BER", f"{receiver.estimate.ber:.6g}")
        recovered_preview = "".join(str(int(bit)) for bit in receiver.receiver_output.detected_bits[:256])
        recovered_suffix = " … (display truncated)" if receiver.estimate.n_bits > 256 else ""
        st.write(f"Recovered bits ({receiver.estimate.n_bits:,} total): `{recovered_preview}`{recovered_suffix}")
        if receiver.decode_error:
            st.error(f"Payload could not be decoded: {receiver.decode_error}")
            st.caption("No replacement characters were inserted; the bytes were rejected as invalid UTF-8.")
        else:
            st.markdown("**Recovered message**")
            st.code(receiver.decoded_text or "")
            if receiver.exact_message_recovery:
                st.success("Recovered UTF-8 message matches the original exactly.")
            else:
                st.warning("Recovered text is valid UTF-8 but differs from the original message.")
    st.info("This is the BER of a short message payload, not a long-run statistical BER benchmark.")
    _show_actual_array_plot(result)


def _render_payload_output_card(result: PayloadSimulationResult) -> None:
    """Render the actual decoded receiver output in the flow diagram's output panel."""
    receiver = result.receivers.get("Baseline Receiver", next(iter(result.receivers.values())))
    with st.container(border=True):
        st.markdown("### 03 · Output")
        if all(r.crc_valid and r.exact_match for r in result.receivers.values()):
            st.success("Verified — exact payload match · CRC valid")
        elif receiver.recovered_payload is not None:
            st.warning("Recovered output · verify CRC / match")
        else:
            st.error("Output unavailable")
        if result.payload_type == "text":
            st.caption("Received text")
            if receiver.recovered_text is not None:
                st.code(receiver.recovered_text)
            else:
                st.info(receiver.frame_error or "Text could not be decoded.")
        elif receiver.recovered_audio_wav:
            st.caption("Received audio")
            st.audio(receiver.recovered_audio_wav, format="audio/wav")
        else:
            st.info(receiver.frame_error or "Audio could not be recovered safely.")
        st.metric("CRC", "Valid" if receiver.crc_valid else "Failed / unavailable")


def _render_payload_result(result: PayloadSimulationResult, *, include_summary: bool = True) -> None:
    receiver = result.receivers.get("Baseline Receiver", next(iter(result.receivers.values())))
    if include_summary:
        with st.container(border=True):
            st.markdown("#### Recovery status")
            if all(r.crc_valid and r.exact_match for r in result.receivers.values()):
                st.success("Verified — exact payload match · CRC valid")
            elif any(r.crc_valid and r.exact_match for r in result.receivers.values()):
                st.warning("Receiver outcomes differ — at least one path verified the exact payload. Compare receiver results below.")
            elif receiver.crc_valid:
                st.warning("CRC valid, but payload differs from the source comparison. Review the diagnostic result.")
            elif receiver.recovered_payload is not None:
                st.error("Corruption detected — CRC failed. Recovered output is unverified.")
            else:
                st.error(f"Decoding failed — CRC could not be checked. {receiver.frame_error or ''}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Payload size", f"{len(result.source_payload):,} bytes")
            c2.metric("Coded-bit BER", f"{receiver.coded_ber:.5g}", f"{receiver.coded_errors:,} errors")
            c3.metric("CRC integrity", "Verified" if receiver.crc_valid else "Failed / unavailable")
            st.caption(f"Receiver: {receiver.receiver_name} · transmitted coded bits: {len(result.transmitted_coded_bits):,} · recovered detector bits: {len(receiver.receiver_output.detected_bits):,}")

        st.markdown("#### Payload comparison")
        left, right = st.columns(2)
        if result.payload_type == "text":
            with left, st.container(border=True):
                st.caption("ORIGINAL · UTF-8")
                st.code(result.source_payload.decode("utf-8"))
            with right, st.container(border=True):
                st.caption("RECOVERED · RECEIVER OUTPUT")
                if receiver.recovered_text is not None:
                    st.code(receiver.recovered_text)
                else:
                    st.error(receiver.frame_error or "Received bytes could not be decoded as UTF-8.")
        elif result.audio_metadata:
            st.caption(f"Recovered payload audio format: mono PCM S16LE · {result.audio_metadata['sample_rate']:,} Hz · {result.audio_metadata['frame_count']:,} frames; source: {result.audio_metadata['source_sample_rate']:,} Hz, {result.audio_metadata['source_channels']} channel(s), {result.audio_metadata['source_frame_count']:,} frames.")
            original_wav = make_wav(result.source_payload, result.audio_metadata["sample_rate"])
            with left, st.container(border=True):
                st.caption("ORIGINAL AUDIO · normalized mono 8 kHz PCM")
                st.audio(original_wav, format="audio/wav")
                _plot_audio_waveform(np.frombuffer(result.source_payload, dtype="<i2"), "Original audio waveform")
            with right, st.container(border=True):
                st.caption("RECOVERED AUDIO · actual receiver payload")
                if receiver.recovered_audio_wav and receiver.recovered_payload:
                    if not receiver.crc_valid:
                        st.error("Corrupted / unverified preview")
                    st.audio(receiver.recovered_audio_wav, format="audio/wav")
                    _plot_audio_waveform(np.frombuffer(receiver.recovered_payload, dtype="<i2"), "Recovered audio waveform")
                else:
                    st.error(receiver.frame_error or "No safely parseable audio payload was recovered.")

    if not include_summary:
        analysis_left, analysis_right = st.columns(2)
        analysis_left.metric("Coded-bit BER", f"{receiver.coded_ber:.5g}", f"{receiver.coded_errors:,} errors")
        analysis_right.metric("CRC integrity", "Verified" if receiver.crc_valid else "Failed / unavailable")

    with st.expander("Transmission diagnostics", expanded=False):
        st.caption(f"Payload bits: {len(result.source_payload)*8:,} · frame bits: {len(result.frame_bits):,} · coded bits: {len(result.transmitted_coded_bits):,} · post-FEC frame-bit errors: {receiver.post_fec_frame_errors if receiver.post_fec_frame_errors is not None else 'unavailable'}")
        st.caption(f"FEC: {'Hamming (7,4)' if result.fec_enabled else 'off'} · nonzero-syndrome codewords: {receiver.corrected_codewords} · CRC: {'valid' if receiver.crc_valid else 'failed'}")
        tx_preview = "".join(str(int(b)) for b in result.transmitted_coded_bits[:96])
        rx_preview = "".join(str(int(b)) for b in receiver.receiver_output.detected_bits[:96])
        st.code(f"Tx coded bits: {tx_preview}\nRx decisions:   {rx_preview}", language="text")

    signal_tabs = st.tabs(["Transmit", "Channel", "Receiver", "Recovery"])
    stride = max(1, len(result.transmit_waveform) // MAX_DISPLAY_SAMPLES)
    plot_size = len(result.transmit_waveform[::stride])
    st.caption(f"Signal overview · plotting {plot_size:,} of {len(result.transmit_waveform):,} samples; processing and metrics use every sample.")
    with signal_tabs[0]:
        fig, axes = plt.subplots(1, 2, figsize=(12, 3.8), constrained_layout=True)
        axes[0].plot(result.transmit_waveform[::stride], color="#087E8B", linewidth=.8)
        axes[0].set(title="BPSK/RRC transmitted waveform", xlabel="Sample index", ylabel="Amplitude")
        _plot_spectrum(axes[1], result.transmit_waveform, result.channel_config.samples_per_symbol,
                       "Transmit spectrum", "#087E8B")
        for ax in axes: _style_plot(ax)
        st.pyplot(fig, clear_figure=True); plt.close(fig)
    with signal_tabs[1]:
        fig, axes = plt.subplots(1, 2, figsize=(12, 3.8), constrained_layout=True)
        x = np.arange(0, len(result.channel.received), stride)
        axes[0].plot(x, result.channel.received[::stride], label="Received", color="#263746", linewidth=.8)
        if np.any(result.channel.interference): axes[0].plot(x, result.channel.interference[::stride], label="Interference", color="#D97706", alpha=.9)
        if np.any(result.channel.noise): axes[0].plot(x, result.channel.noise[::stride], label="AWGN", color="#B45309", alpha=.55)
        axes[0].set(title="Received waveform and channel components", xlabel="Sample index", ylabel="Amplitude")
        axes[0].legend(loc="upper right", fontsize=8)
        _plot_spectrum(axes[1], result.channel.received, result.channel_config.samples_per_symbol,
                       "Received spectrum", "#D97706")
        for ax in axes: _style_plot(ax)
        st.pyplot(fig, clear_figure=True); plt.close(fig)
    with signal_tabs[2]:
        output = receiver.receiver_output
        fig, axes = plt.subplots(figsize=(11, 3.8), constrained_layout=True)
        fx = np.arange(0, len(output.filtered_samples), stride)
        axes.plot(fx, output.filtered_samples[::stride], color="#6D5BD0", linewidth=.8, label="Matched-filter output")
        if output.sample_indices.size:
            decision_stride = max(1, len(output.sample_indices) // 200)
            axes.scatter(output.sample_indices[::decision_stride], output.decision_samples[::decision_stride],
                         marker="x", color="#087E8B", s=12, label="Symbol decisions")
        axes.set(title="Matched-filter output and symbol decisions", xlabel="Sample index", ylabel="Amplitude")
        axes.legend(fontsize=8); _style_plot(axes)
        st.pyplot(fig, clear_figure=True); plt.close(fig)
    with signal_tabs[3]:
        nbits = min(128, len(result.transmitted_coded_bits), len(receiver.receiver_output.detected_bits))
        bit_x = np.arange(nbits)
        tx_bits = result.transmitted_coded_bits[:nbits]
        rx_bits = receiver.receiver_output.detected_bits[:nbits]
        fig, ax = plt.subplots(figsize=(11, 3.2), constrained_layout=True)
        ax.step(bit_x, tx_bits, where="mid", label="Tx coded bits", color="#087E8B")
        ax.step(bit_x, rx_bits + 1.15, where="mid", label="Rx detector decisions (offset)", color="#263746")
        errors = np.flatnonzero(tx_bits != rx_bits)
        if errors.size: ax.scatter(errors, tx_bits[errors] + .55, color="#B42318", s=18, label="Detected errors")
        ax.set(title=f"Coded-bit decisions · first {nbits} of {len(result.transmitted_coded_bits):,}", xlabel="Coded-bit index", ylabel="Bit value (offset for comparison)")
        ax.set_yticks([0, 1, 1.15, 2.15], ["Tx 0", "Tx 1", "Rx 0", "Rx 1"])
        ax.legend(fontsize=8); _style_plot(ax)
        st.pyplot(fig, clear_figure=True); plt.close(fig)
    st.info("Short-payload BER is an observation for this message, not a long-run Monte Carlo estimate. CRC-32 detects many accidental errors but is not authentication. Hamming (7,4) corrects one bit per codeword; multiple errors may be miscorrected.")


def _plot_audio_waveform(samples: np.ndarray, title: str) -> None:
    stride = max(1, len(samples) // 2200)
    fig, ax = plt.subplots(figsize=(5.2, 1.7), constrained_layout=True)
    ax.plot(np.arange(0, len(samples), stride) / 8000, samples[::stride], color=PALETTE["transmit"], linewidth=.7)
    ax.set(title=title, xlabel="Time (s)", ylabel="PCM amplitude")
    _style_plot(ax)
    st.pyplot(fig, clear_figure=True); plt.close(fig)


def _render_channel_analysis(result: MessageSimulationResult | None,
                             config: MessageSimulationConfig | None) -> None:
    if result is None or config is None or not result_matches_config(result, config):
        st.info("Run a message transmission first. The comparison uses the current message and channel configuration.")
        return
    if result.comparison is None:
        st.warning("For a fair paired comparison, select “Both (paired comparison)” in Message Transmission and run it.")
        st.markdown(
            "The baseline and notch paths must process the same transmitted bits, waveform, channel configuration, "
            "and realized received samples. The notch center is configured explicitly; it does not estimate an unknown tone."
        )
        return
    comparison = result.comparison
    baseline = result.receiver_results["Baseline Receiver"]
    notch = result.receiver_results["Notch-Filtered Receiver"]
    st.success("Paired run verified: both receivers used the same received waveform.")
    left, right = st.columns(2)
    left.metric("Baseline BER", f"{baseline.estimate.ber:.6g}",
                f"{baseline.estimate.errors}/{baseline.estimate.n_bits} errors")
    right.metric("Notch BER", f"{notch.estimate.ber:.6g}",
                 f"{notch.estimate.errors}/{notch.estimate.n_bits} errors")
    st.metric("Δ BER (notch − baseline)",
              f"{comparison['ber_difference_notch_minus_baseline']:+.6g}")
    a, b, c = st.columns(3)
    a.metric("Corrected errors", str(comparison["corrected_errors"]))
    b.metric("Introduced errors", str(comparison["introduced_errors"]))
    c.metric("Shared errors", str(comparison["shared_errors"]))
    st.caption("A negative Δ BER means fewer measured errors for the notch receiver in this paired payload run.")
    diagnostic_cols = st.columns(3)
    attenuation = comparison["interference_attenuation_db"]
    diagnostic_cols[0].metric(
        "Notch tone attenuation",
        "not applicable" if attenuation is None else f"{attenuation:.2f} dB",
    )
    signal_gain = comparison["desired_signal_rms_gain_after_notch"]
    diagnostic_cols[1].metric(
        "Wanted-signal RMS gain",
        "unavailable" if signal_gain is None else f"{signal_gain:.4f}",
    )
    distortion = comparison["desired_signal_relative_rms_distortion"]
    diagnostic_cols[2].metric(
        "Wanted-signal relative distortion",
        "unavailable" if distortion is None else f"{distortion:.4f}",
    )
    st.warning("A short message is not enough to claim statistical significance or a general receiver advantage.")
    st.info(
        "The notch frequency is configured, not estimated. The current iirnotch + filtfilt path is offline and "
        "noncausal; it must not be interpreted as a real-time receiver. A notch can hurt when no tone is present "
        "or when the actual tone is away from the notch center."
    )
    with st.expander("Recorded M4 experimental context"):
        st.write(
            "M4 reported improvement for a matched tone, a cost under AWGN-only conditions, and sensitivity to "
            "frequency mismatch. Those are outcomes for the recorded M4 configurations, not guaranteed behavior "
            "for every payload or seed. See reports/M4_engineering_report.md."
        )


def _safe_output_directory(scenario: str, seed: int) -> Path:
    root = Path("results/m6/performance").resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = (root / f"{scenario}_seed{seed}_{stamp}").resolve()
    if not target.is_relative_to(root):
        raise ValueError("Generated output directory is outside the application-managed results folder")
    return target


def _performance_workload_bits(n_bits: int, repetitions: int, condition_count: int) -> int:
    """Bound total independent bit trials submitted through the public UI."""
    return n_bits * repetitions * condition_count


def _render_performance_lab() -> None:
    st.subheader("Experiment setup")
    st.caption(
        "Run the established M5 runner. This long-run BER experiment is separate from one-message payload BER. "
        "The public interface caps each run at 250,000 bits and each experiment at 1,000,000 total bit trials."
    )
    scenario = st.selectbox("Experiment scenario", SUPPORTED_SCENARIOS,
                            format_func=lambda item: item.replace("_", " ").title(),
                            key="lab_scenario")
    with st.form("performance_lab_form"):
        c1, c2, c3 = st.columns(3)
        n_bits = int(c1.number_input("Bits per run", min_value=1000, max_value=MAX_PERFORMANCE_BITS,
                                     value=10000, step=1000, key="lab_n_bits"))
        repetitions = int(c2.number_input("Independent repetitions", min_value=1, max_value=4,
                                          value=2, step=1, key="lab_repetitions"))
        seed = int(c3.number_input("Master seed", min_value=0, max_value=2**32-1,
                                   value=20261028, step=1, key="lab_seed"))
        ebn0 = float(st.number_input("Eb/N0 for channel sweeps (dB)", min_value=-20.0,
                                     max_value=40.0, value=6.0, step=1.0, key="lab_ebn0"))
        if scenario in DEFAULT_EBN0_VALUES:
            default_values = DEFAULT_EBN0_VALUES[scenario]
            selected = st.multiselect("Eb/N0 sweep (dB)", default_values,
                                      default=list(default_values), key=f"lab_ebn0_values_{scenario}")
            sweep_values: tuple[float, ...] | None = None
            ebn0_values: tuple[float, ...] | None = tuple(float(v) for v in selected)
        elif scenario in DEFAULT_SWEEP_VALUES:
            default_values = DEFAULT_SWEEP_VALUES[scenario]
            selected = st.multiselect("Sweep values", default_values,
                                      default=list(default_values), key=f"lab_sweep_values_{scenario}")
            sweep_values = tuple(float(v) for v in selected)
            ebn0_values = None
        else:
            st.caption("The receiver comparison uses the configured M5 matched-tone condition.")
            sweep_values = None
            ebn0_values = None
        submitted = st.form_submit_button("Run Performance Experiment", type="primary")

    if submitted:
        try:
            condition_count = len(ebn0_values) if ebn0_values is not None else (
                len(sweep_values) if sweep_values is not None else 1
            )
            workload_bits = _performance_workload_bits(n_bits, repetitions, condition_count)
            if workload_bits > MAX_PERFORMANCE_TOTAL_BITS:
                st.error(
                    f"This selection would run {workload_bits:,} bit trials. "
                    f"Reduce bits, repetitions, or sweep points to stay within "
                    f"{MAX_PERFORMANCE_TOTAL_BITS:,} total bit trials."
                )
                return
            output_dir = _safe_output_directory(scenario, seed)
            config = ExperimentConfig(
                experiment_id=f"m6_ui_{scenario}_seed{seed}_{output_dir.name.rsplit('_', 1)[-1]}",
                scenario=scenario,
                n_bits=n_bits,
                master_seed=seed,
                repetitions=repetitions,
                ebn0_db=ebn0,
                ebn0_values_db=ebn0_values,
                sweep_values=sweep_values,
                output_dir=str(output_dir),
            )
            with st.spinner(f"Running {scenario.replace('_', ' ')}: {n_bits:,} bits × {repetitions} repetitions…"):
                result = run_experiment(config)
            st.session_state["lab_result"] = result
            st.session_state["lab_configuration"] = config.to_dict()
            st.session_state["lab_signature"] = json.dumps({
                "scenario": scenario, "n_bits": n_bits, "repetitions": repetitions,
                "seed": seed, "ebn0": ebn0,
                "ebn0_values": ebn0_values, "sweep_values": sweep_values,
            }, sort_keys=True)
        except Exception as exc:
            st.session_state.pop("lab_result", None)
            st.session_state.pop("lab_configuration", None)
            st.error(f"Experiment could not be completed: {type(exc).__name__}: {exc}")

    result: dict[str, Any] | None = st.session_state.get("lab_result")
    if result is None:
        st.caption("No Performance Lab results are loaded in this session yet.")
        return
    current_signature = json.dumps({
        "scenario": scenario, "n_bits": n_bits, "repetitions": repetitions,
        "seed": seed, "ebn0": ebn0,
        "ebn0_values": ebn0_values, "sweep_values": sweep_values,
    }, sort_keys=True)
    if current_signature != st.session_state.get("lab_signature"):
        st.warning("Performance settings have changed since the saved run. Previous results are hidden until you run the current configuration.")
        return
    if result["overall_status"] != "completed":
        st.error(f"Experiment status: {result['overall_status']}. Inspect the saved manifest and execution log for failed or partial points.")
    else:
        st.success(f"Experiment completed · {result['successful_receiver_rows']} measurement rows · {result['output_dir']}")
    st.subheader("Results and artifacts")
    output = Path(result["output_dir"])
    manifest_path = output / "manifest.json"
    if manifest_path.is_file():
        st.download_button("Download manifest JSON", manifest_path.read_bytes(),
                           file_name="manifest.json", mime="application/json")
    csv_path = output / "results.csv"
    if csv_path.is_file() and csv_path.stat().st_size:
        st.download_button("Download raw results CSV", csv_path.read_bytes(),
                           file_name="results.csv", mime="text/csv")
        import pandas as pd
        rows = pd.read_csv(csv_path)
        st.dataframe(rows, width="stretch", hide_index=True)
    for filename, title in (
        ("ber_by_condition.png", "BER by condition"),
        ("run_variability.png", "Between-run variability"),
        ("paired_ber_difference.png", "Paired BER difference"),
    ):
        path = output / filename
        if path.is_file():
            st.subheader(title)
            st.image(str(path), caption=filename, width="stretch")
    st.caption(f"Configuration: {output / 'resolved_config.json'} · Results: {csv_path}")
    st.caption("Community Cloud storage is temporary. Download the CSV/JSON outputs you want to keep.")


def main() -> None:
    st.set_page_config(page_title="SignalShield Lab", page_icon="📡", layout="wide")
    apply_ui_theme()
    st.markdown(
        "<div class='signalshield-hero'><h1>📡 SignalShield</h1>"
        "<p>Interactive Digital Communications Lab · Transmit · Disturb · Recover · Analyze</p></div>",
        unsafe_allow_html=True,
    )
    st.caption("Explore a reproducible digital link. Educational simulation; not a physical radio or security product.")

    transmission_tab, analysis_tab, lab_tab = st.tabs([
        "Transmit & Analyze", "Channel & Receiver Analysis", "Performance Lab"
    ])
    with transmission_tab:
        st.markdown("<div class='signal-flow'>INPUT &nbsp; → &nbsp; SIGNAL SYSTEM &nbsp; → &nbsp; OUTPUT</div>", unsafe_allow_html=True)
        input_column, system_column, output_column = st.columns([1.05, 1.25, 1.0], gap="medium")
        output_placeholder = output_column.empty()

        with input_column:
            st.markdown("### 01 · Input")
            st.caption("Choose a short text or audio payload.")
            mode = st.radio("Payload type", ["Text Message", "Voice / Audio"], horizontal=True, key="payload_mode")
            source_audio = None
            if mode == "Text Message":
                st.text_area("Your message", value="SignalShield demo", max_chars=512, key="message_text")
                input_payload = st.session_state.get("message_text", "SignalShield demo").encode("utf-8")
                audio_meta = None
            else:
                st.caption("PCM 16-bit WAV · mono/stereo · 8–48 kHz · maximum 1 second and 2 MiB")
                audio_source = st.radio("Audio source", ["Record microphone", "Upload WAV"], horizontal=True, key="audio_source")
                if audio_source == "Record microphone":
                    audio_file = st.audio_input("Record a voice message", key="audio_recording")
                else:
                    audio_file = st.file_uploader("Choose a PCM 16-bit WAV file (mono or stereo)", type=["wav"], key="audio_upload")
                input_payload = b""
                audio_meta = None
                if audio_file is not None:
                    try:
                        source_audio = load_wav(audio_file.getvalue())
                        input_payload = source_audio.pcm_bytes
                        audio_meta = source_audio.metadata
                        st.audio(audio_file.getvalue(), format="audio/wav")
                        fig, ax = plt.subplots(figsize=(10, 2.5), constrained_layout=True)
                        stride = max(1, len(source_audio.samples) // 2500)
                        ax.plot(np.arange(0, len(source_audio.samples), stride) / 8000,
                                source_audio.samples[::stride], linewidth=.7)
                        ax.set(title="Source audio · normalized mono 8 kHz overview", xlabel="Time (s)", ylabel="PCM amplitude")
                        _style_plot(ax); st.pyplot(fig, clear_figure=True); plt.close(fig)
                        st.caption(f"Normalized to mono 8 kHz PCM S16LE · {len(input_payload):,} bytes · source {audio_meta['source_sample_rate']} Hz / {audio_meta['source_channels']} channel(s)")
                    except ValueError as exc:
                        st.error(str(exc))

        with system_column:
            st.markdown("### 02 · Signal system")
            st.markdown("""
                <div class="signal-core">
                  <svg viewBox="0 0 300 132" role="img" aria-label="Three signal paths through a communication system">
                    <g fill="none" stroke-linecap="round" stroke-linejoin="round" stroke-width="3">
                      <path d="M8 32h57l15 0 10 10 10-20 10 20 10-10h30" stroke="#087E8B"/>
                      <path d="M8 66h57l15 0 10 10 10-20 10 20 10-10h30" stroke="#D97706"/>
                      <path d="M8 100h57l15 0 10 10 10-20 10 20 10-10h30" stroke="#6D5BD0"/>
                      <path d="M150 32h20v68h-20M218 32h20v68h-20M238 66h54" stroke="#526575"/>
                    </g>
                    <rect x="170" y="26" width="48" height="80" rx="10" fill="#E8F3F4" stroke="#087E8B" stroke-width="2"/>
                    <circle cx="194" cy="45" r="5" fill="#087E8B"/><circle cx="194" cy="66" r="5" fill="#D97706"/><circle cx="194" cy="87" r="5" fill="#6D5BD0"/>
                    <circle cx="289" cy="66" r="7" fill="#087E8B"/>
                  </svg>
                  <div class="signal-flow">MODULATE · CHANNEL · RECOVER</div>
                </div>
                """, unsafe_allow_html=True)
            with st.expander("Advanced Settings", expanded=False):
                st.markdown("#### Channel")
                channel_left, channel_right = st.columns(2)
                with channel_left:
                    st.checkbox("Add AWGN noise", value=True, key="message_awgn")
                with channel_right:
                    if st.session_state.get("message_awgn", True):
                        st.number_input("Eb/N0 (dB)", min_value=-20.0, max_value=40.0, value=8.0,
                                        step=1.0, key="message_ebn0", help="Higher Eb/N0 means less modeled noise.")
                    else:
                        st.caption("AWGN is off; the channel noise variance is zero.")

                st.divider()
                st.markdown("#### Interference and signal level")
                interference_left, interference_right = st.columns(2)
                with interference_left:
                    st.checkbox("Add narrowband tone", value=False, key="message_tone_enabled")
                with interference_right:
                    st.number_input("Desired-signal attenuation (dB)", min_value=0.0,
                                    max_value=60.0, value=0.0, step=1.0,
                                    key="message_attenuation", help="Scales the wanted signal; channel noise/tone are added after it.")
                if st.session_state.get("message_tone_enabled", False):
                    tone_cols = st.columns(3)
                    tone_cols[0].number_input("Tone amplitude (peak)", min_value=0.0, max_value=2.0,
                                              value=0.22, step=0.02, key="message_tone_amplitude")
                    tone_cols[1].number_input("Tone frequency (cycles/symbol)", min_value=0.01,
                                              max_value=3.99, value=0.35, step=0.01,
                                              key="message_tone_frequency")
                    tone_cols[2].number_input("Tone phase (radians)", min_value=-6.28, max_value=6.28,
                                              value=0.0, step=0.1, key="message_tone_phase")

                st.divider()
                st.markdown("#### Receiver and waveform")
                receiver = st.selectbox("Receiver", [
                    "Baseline Receiver", "Notch-Filtered Receiver", "Both (paired comparison)"
                ], key="message_receiver")
                if receiver != "Baseline Receiver":
                    notch_cols = st.columns(2)
                    notch_cols[0].number_input("Notch center (cycles/symbol)", min_value=0.01,
                                               max_value=3.99, value=0.35, step=0.01,
                                               key="message_notch_center")
                    notch_cols[1].number_input("Notch quality factor Q", min_value=0.5,
                                               max_value=1000.0, value=30.0, step=1.0,
                                               key="message_notch_q")
                    st.caption("The notch center is configured, not automatically estimated.")
                pulse_cols = st.columns(3)
                pulse_cols[0].number_input("Samples per symbol", min_value=2, max_value=32,
                                           value=8, step=2, key="message_sps")
                pulse_cols[1].number_input("RRC roll-off", min_value=0.05, max_value=1.0,
                                           value=0.35, step=0.05, key="message_rolloff")
                pulse_cols[2].number_input("RRC span (symbols)", min_value=2, max_value=20,
                                           value=10, step=2, key="message_span")

                st.divider()
                st.markdown("#### Integrity and repeatability")
                integrity_left, integrity_right = st.columns(2)
                with integrity_left:
                    st.checkbox("Hamming (7,4) error correction", value=True, key="payload_fec")
                    st.caption("Corrects one bit per 7-bit codeword; CRC checks the received frame.")
                with integrity_right:
                    st.number_input("Random seed", min_value=0, max_value=2**32-1, value=20261028,
                                    step=1, key="message_seed", help="Reuse a seed to reproduce the same channel realization.")
            submitted = st.button("Transmit & Analyze", type="primary", key="payload_submit", disabled=(mode == "Voice / Audio" and source_audio is None))

        current_config: MessageSimulationConfig | None = None
        try:
            current_config = _make_message_config()
            if current_config.interference_frequency_cycles_per_symbol >= current_config.samples_per_symbol / 2:
                raise ValueError("Tone frequency must be below half the samples-per-symbol rate.")
            if current_config.notch_center_cycles_per_symbol >= current_config.samples_per_symbol / 2 \
                    and current_config.receiver != "Baseline Receiver":
                raise ValueError("Notch center must be below half the samples-per-symbol rate.")
        except (TypeError, ValueError) as exc:
            st.error(f"Invalid message simulation configuration: {exc}")
            current_config = None

        current_signature = None
        if current_config is not None:
            current_signature = (current_config.configuration_id + ":" + mode + ":" + input_payload.hex()
                                + ":" + json.dumps(audio_meta, sort_keys=True)
                                + ":" + str(bool(st.session_state.get("payload_fec", True))))
        if submitted:
            st.session_state.pop("payload_result", None)
            st.session_state.pop("message_run_error", None)
            if current_config is not None and (mode == "Text Message" or source_audio is not None):
                try:
                    with st.spinner("Transmitting and receiving the payload through SignalShield…"):
                        st.session_state["payload_result"] = run_payload_simulation(
                            current_config, payload_type="text" if mode == "Text Message" else "audio",
                            payload=input_payload if mode != "Text Message" else None,
                            audio_metadata=audio_meta, fec_enabled=bool(st.session_state.get("payload_fec", True)))
                    st.session_state["payload_signature"] = current_signature
                except Exception as exc:
                    st.session_state["message_run_error"] = f"{type(exc).__name__}: {exc}"
            else:
                st.session_state["message_run_error"] = "Correct the invalid configuration and run again."

        if st.session_state.get("message_run_error"):
            st.error(f"Simulation did not complete: {st.session_state['message_run_error']}")
        result: PayloadSimulationResult | None = st.session_state.get("payload_result")
        result_current = result is not None and current_signature == st.session_state.get("payload_signature")
        input_ready = bool(input_payload) and (mode == "Text Message" or source_audio is not None)
        with output_placeholder.container():
            if result is None:
                with st.container(border=True):
                    st.markdown("### 03 · Output")
                    st.info("Run the signal system to see its recovered output here.")
            elif not result_current:
                with st.container(border=True):
                    st.markdown("### 03 · Output")
                    st.warning("The input or settings changed. Run the current setup to refresh this output.")
            else:
                _render_payload_output_card(result)

        st.markdown("<div class='signal-flow'>↓ &nbsp; SIGNAL ANALYSIS &nbsp; ↓</div>", unsafe_allow_html=True)
        _render_workflow(input_ready, current_config is not None, result, result_current)
        if result is not None:
            if not result_current:
                st.warning("The input or settings changed since this run. The previous result is hidden until you run the current configuration.")
            else:
                _render_payload_result(result, include_summary=False)

    current_result: MessageSimulationResult | None = st.session_state.get("message_result")
    current_config: MessageSimulationConfig | None = None
    try:
        current_config = _make_message_config()
    except (TypeError, ValueError):
        pass
    with analysis_tab:
        st.subheader("Paired receiver analysis")
        payload_result: PayloadSimulationResult | None = st.session_state.get("payload_result")
        if payload_result is None:
            st.info("Run a payload first. Select Both (paired comparison) under Advanced Settings to compare the baseline and notch receivers on the same channel realization.")
        elif current_signature != st.session_state.get("payload_signature"):
            st.warning("Current input or settings differ from the saved transmission. Previous receiver results are hidden.")
        elif "Baseline Receiver" not in payload_result.receivers or "Notch-Filtered Receiver" not in payload_result.receivers:
            st.info("For a paired comparison, select Both (paired comparison) under Advanced Settings and transmit again.")
        else:
            base = payload_result.receivers["Baseline Receiver"]
            notch = payload_result.receivers["Notch-Filtered Receiver"]
            st.success("Paired receiver run: both paths used the same transmitted coded bits and received waveform.")
            c1, c2, c3 = st.columns(3)
            c1.metric("Baseline coded BER", f"{base.coded_ber:.6g}", f"{base.coded_errors:,} coded-bit errors")
            c2.metric("Notch coded BER", f"{notch.coded_ber:.6g}", f"{notch.coded_errors:,} coded-bit errors")
            c3.metric("Δ BER (notch − baseline)", f"{notch.coded_ber-base.coded_ber:+.6g}")
            pair = payload_result.comparison or {}
            a, b, c = st.columns(3)
            a.metric("Corrected by notch", str(pair.get("corrected_errors", 0)))
            b.metric("Introduced by notch", str(pair.get("introduced_errors", 0)))
            c.metric("Shared errors", str(pair.get("shared_errors", 0)))
            d, e, f = st.columns(3)
            tone_attenuation = pair.get("interference_attenuation_db")
            d.metric("Interference attenuation", "n/a" if tone_attenuation is None else f"{tone_attenuation:.2f} dB")
            wanted_gain = pair.get("desired_signal_rms_gain_after_notch")
            e.metric("Wanted-signal RMS gain", "n/a" if wanted_gain is None else f"{wanted_gain:.4f}")
            distortion = pair.get("desired_signal_relative_rms_distortion")
            f.metric("Wanted-signal distortion", "n/a" if distortion is None else f"{distortion:.4f}")
            st.table([
                {"Receiver": "Baseline", "CRC": "valid" if base.crc_valid else "failed",
                 "Post-FEC frame errors": base.post_fec_frame_errors, "Exact payload": base.exact_match},
                {"Receiver": "Notch", "CRC": "valid" if notch.crc_valid else "failed",
                 "Post-FEC frame errors": notch.post_fec_frame_errors, "Exact payload": notch.exact_match},
            ])
            st.warning("Paired measurements use the same transmitted bits and channel realization. This one payload is not a statistical superiority claim. The configured notch does not estimate tone frequency and can increase errors when mismatched.")
    with lab_tab:
        _render_performance_lab()


if __name__ == "__main__":
    main()
