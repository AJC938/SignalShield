"""Paired baseline-versus-notch receiver experiments for M4."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import time
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import scipy
from scipy.stats import binomtest

from signalshield.channel import ChannelConfig, ChannelOutput, apply_configured_channel, mean_square_power
from signalshield.config import NotchConfig
from signalshield.filters import rrc_taps
from signalshield.metrics import BerEstimate, ber_estimate
from signalshield.modulation import bpsk_modulate
from signalshield.notch import apply_notch, notch_coefficients, notch_frequency_response
from signalshield.receiver import WaveformReceiverOutput, receive_bpsk_waveform
from signalshield.signals import generate_bits
from signalshield.waveform import pulse_shape


def _fit_tone_amplitude(samples: np.ndarray, frequency: float, sps: int, *, edge: int = 200) -> float | None:
    """Least-squares cosine/sine amplitude estimate on an interior sample window."""
    if samples.size <= 2 * edge + 16:
        return None
    start, stop = edge, samples.size - edge
    n = np.arange(start, stop, dtype=np.float64)
    omega_n = 2.0 * np.pi * frequency * n / sps
    design = np.column_stack((np.cos(omega_n), np.sin(omega_n), np.ones(n.size)))
    coeff, _, _, _ = np.linalg.lstsq(design, samples[start:stop], rcond=None)
    return float(np.hypot(coeff[0], coeff[1]))


def _paired_bootstrap_delta(base_errors: np.ndarray, candidate_errors: np.ndarray,
                            *, rng: np.random.Generator, block_length: int = 50,
                            replicates: int = 1000) -> tuple[float, float]:
    """Percentile CI for candidate-minus-baseline BER using paired bit blocks."""
    delta = candidate_errors.astype(np.float64) - base_errors.astype(np.float64)
    n_bits = delta.size
    n_blocks = int(np.ceil(n_bits / block_length))
    padded = np.pad(delta, (0, n_blocks * block_length - n_bits))
    block_sums = padded.reshape(n_blocks, block_length).sum(axis=1)
    selected = rng.integers(0, n_blocks, size=(replicates, n_blocks))
    estimates = block_sums[selected].sum(axis=1) / n_bits
    low, high = np.quantile(estimates, [0.025, 0.975])
    return float(low), float(high)


def compare_receivers(
    received: object,
    transmitted_bits: object,
    taps: object,
    notch_config: NotchConfig,
    *,
    bootstrap_seed: int = 4040,
    block_length: int = 50,
    bootstrap_replicates: int = 1000,
) -> tuple[dict[str, Any], WaveformReceiverOutput, WaveformReceiverOutput, np.ndarray]:
    """Run both receiver paths on the same samples and summarize paired errors.

    The baseline calls the unchanged M2 receiver. The candidate only inserts
    M4's offline notch before that same M2 receiver. ``paired_delta_ci`` is a
    circular-free, contiguous-block bootstrap interval for BER_notch−BER_base.
    McNemar's exact p-value is also recorded, with its bit-independence caveat
    for temporally filtered errors documented in the report.
    """
    bits = np.asarray(transmitted_bits)
    base_start = time.perf_counter()
    base_out = receive_bpsk_waveform(received, taps, n_symbols=int(bits.size),
                                     samples_per_symbol=notch_config.samples_per_symbol)
    base_runtime = time.perf_counter() - base_start
    notch_start = time.perf_counter()
    filtered = apply_notch(received, notch_config)
    notch_out = receive_bpsk_waveform(filtered, taps, n_symbols=int(bits.size),
                                      samples_per_symbol=notch_config.samples_per_symbol)
    notch_runtime = time.perf_counter() - notch_start
    base = ber_estimate(bits, base_out.detected_bits)
    candidate = ber_estimate(bits, notch_out.detected_bits)
    base_err = base_out.detected_bits != bits
    cand_err = notch_out.detected_bits != bits
    corrected = int(np.count_nonzero(base_err & ~cand_err))
    introduced = int(np.count_nonzero(~base_err & cand_err))
    unchanged = int(bits.size - corrected - introduced)
    discordant = corrected + introduced
    mcnemar_raw = float(binomtest(corrected, discordant, p=0.5).pvalue) if discordant else 1.0
    mcnemar_p: float | str = (
        "<2.3e-308 (floating-point underflow)" if mcnemar_raw == 0.0 else mcnemar_raw
    )
    delta_low, delta_high = _paired_bootstrap_delta(
        base_err, cand_err, rng=np.random.default_rng(bootstrap_seed),
        block_length=block_length, replicates=bootstrap_replicates,
    )
    difference = candidate.ber - base.ber
    relative_change = None if base.ber == 0.0 else (candidate.ber - base.ber) / base.ber
    summary: dict[str, Any] = {
        "baseline_errors": base.errors, "baseline_n_bits": base.n_bits, "baseline_ber": base.ber,
        "baseline_ci95_lower": base.confidence_interval[0], "baseline_ci95_upper": base.confidence_interval[1],
        "baseline_zero_error_upper95": base.zero_error_upper_bound_95,
        "notch_errors": candidate.errors, "notch_n_bits": candidate.n_bits, "notch_ber": candidate.ber,
        "notch_ci95_lower": candidate.confidence_interval[0], "notch_ci95_upper": candidate.confidence_interval[1],
        "notch_zero_error_upper95": candidate.zero_error_upper_bound_95,
        "ber_difference_notch_minus_baseline": difference,
        "relative_ber_change": relative_change,
        "paired_errors_corrected_by_notch": corrected,
        "paired_errors_introduced_by_notch": introduced,
        "paired_bits_unchanged": unchanged,
        "mcnemar_exact_two_sided_p": mcnemar_p,
        "paired_delta_block_bootstrap_ci95_lower": delta_low,
        "paired_delta_block_bootstrap_ci95_upper": delta_high,
        "paired_block_length_bits": block_length,
        "paired_bootstrap_replicates": bootstrap_replicates,
        "baseline_receiver_runtime_seconds": base_runtime,
        "notch_receiver_runtime_seconds_including_filter_seconds": notch_runtime,
        "received_length": int(np.asarray(received).size),
    }
    return summary, base_out, notch_out, filtered


def _diagnostics(transmit: np.ndarray, channel: ChannelOutput, filtered_total: np.ndarray,
                 transmit_taps: np.ndarray, n_symbols: int,
                 notch_config: NotchConfig, actual_frequency: float) -> dict[str, float | None]:
    filtered_tone = apply_notch(channel.interference, notch_config) if np.any(channel.interference) else None
    tone_in = _fit_tone_amplitude(channel.interference, actual_frequency, notch_config.samples_per_symbol)
    tone_out = None if filtered_tone is None else _fit_tone_amplitude(
        filtered_tone, actual_frequency, notch_config.samples_per_symbol)
    tone_db = None
    if tone_in is not None and tone_out is not None and tone_in > 0.0 and tone_out > 0.0:
        tone_db = float(20.0 * np.log10(tone_out / tone_in))

    desired = channel.attenuated_signal
    desired_notched = apply_notch(desired, notch_config)
    edge = 200
    sl = slice(edge, -edge)
    desired_rms = float(np.sqrt(np.mean(desired[sl] ** 2)))
    distortion_rms = float(np.sqrt(np.mean((desired_notched[sl] - desired[sl]) ** 2)))
    distortion_fraction = distortion_rms / desired_rms if desired_rms > 0.0 else None
    desired_gain = float(np.sqrt(np.mean(desired_notched[sl] ** 2) / np.mean(desired[sl] ** 2))) if desired_rms > 0 else None

    noise_in_var = float(np.var(channel.noise, ddof=1)) if channel.noise.size > 1 else 0.0
    noise_filtered = apply_notch(channel.noise, notch_config) if np.any(channel.noise) else np.zeros_like(channel.noise)
    noise_out_var = float(np.var(noise_filtered[sl], ddof=1)) if noise_filtered.size > 2 * edge else 0.0
    mf_noise = receive_bpsk_waveform(noise_filtered, transmit_taps,
                                     n_symbols=n_symbols,
                                     samples_per_symbol=notch_config.samples_per_symbol)
    return {
        "interference_amplitude_input_least_squares": tone_in,
        "interference_amplitude_output_least_squares": tone_out,
        "interference_amplitude_attenuation_db": tone_db,
        "desired_signal_record_power_before_notch": mean_square_power(desired),
        "desired_signal_record_power_after_notch": mean_square_power(desired_notched),
        "desired_signal_rms_gain_after_notch_interior": desired_gain,
        "desired_signal_relative_rms_distortion_interior": distortion_fraction,
        "awgn_sample_variance_before_notch": noise_in_var,
        "awgn_sample_variance_after_notch_interior": noise_out_var,
        "total_received_power_before_notch": mean_square_power(channel.received),
        "total_received_power_after_notch": mean_square_power(filtered_total),
        "awgn_decision_sample_variance_after_notch": float(np.var(mf_noise.decision_samples, ddof=1))
        if mf_noise.decision_samples.size > 1 else 0.0,
    }


def _condition_row(name: str, comparison: dict[str, Any], channel_cfg: ChannelConfig,
                   notch_cfg: NotchConfig, *, master_seed: int, bit_seed: int,
                   noise_seed: int, actual_frequency: float | None,
                   diagnostics: dict[str, float | None] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "experiment": name, "master_seed": master_seed, "bit_seed": bit_seed,
        "noise_seed": noise_seed, "n_bits": comparison["baseline_n_bits"],
        "ebn0_db": channel_cfg.ebn0_db, "attenuation_db": channel_cfg.attenuation_db,
        "interference_amplitude_peak": channel_cfg.interference_amplitude,
        "actual_interference_frequency_cycles_per_symbol": actual_frequency,
        "interference_phase_rad": channel_cfg.interference_phase_rad,
        "notch_center_cycles_per_symbol": notch_cfg.center_frequency_cycles_per_symbol,
        "notch_quality_factor": notch_cfg.quality_factor,
        "samples_per_symbol": channel_cfg.samples_per_symbol,
        "rrc_rolloff": 0.35, "rrc_span_symbols": 10,
    }
    row.update(comparison)
    if diagnostics:
        row.update(diagnostics)
    return row


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"no rows available for {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def _ber_plot(rows: list[dict[str, Any]], x_key: str, x_label: str, path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 5.4), constrained_layout=True)
    for prefix, label, marker in (("baseline", "Baseline M2", "o"), ("notch", "Notch + M2", "s")):
        observed = [r for r in rows if float(r[f"{prefix}_ber"]) > 0.0]
        if observed:
            xs = [float(r[x_key]) for r in observed]
            ys = [float(r[f"{prefix}_ber"]) for r in observed]
            lows = [max(0.0, ys[i] - float(observed[i][f"{prefix}_ci95_lower"])) for i in range(len(ys))]
            highs = [max(0.0, float(observed[i][f"{prefix}_ci95_upper"]) - ys[i]) for i in range(len(ys))]
            ax.errorbar(xs, ys, yerr=[lows, highs], marker=marker, capsize=3, label=f"{label} (95% exact CI)")
        zero_rows = [r for r in rows if float(r[f"{prefix}_ber"]) == 0.0
                     and r[f"{prefix}_zero_error_upper95"] is not None]
        if zero_rows:
            ax.scatter([float(r[x_key]) for r in zero_rows],
                       [float(r[f"{prefix}_zero_error_upper95"]) for r in zero_rows],
                       marker="v", label=f"{label}: zero errors, upper 95% bound")
    ax.set_yscale("log")
    ax.set_xlabel(x_label); ax.set_ylabel("Measured bit error rate")
    ax.set_title(title); ax.grid(True, which="both", alpha=.3); ax.legend()
    fig.savefig(path, dpi=160); plt.close(fig)


def _pair_bar(row: dict[str, Any], path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 5), constrained_layout=True)
    values = [float(row["baseline_ber"]), float(row["notch_ber"])]
    lows = [float(row["baseline_ci95_lower"]), float(row["notch_ci95_lower"])]
    highs = [float(row["baseline_ci95_upper"]), float(row["notch_ci95_upper"])]
    x = np.arange(2)
    ax.bar(x, values, color=["tab:blue", "tab:orange"], alpha=.78)
    ax.errorbar(x, values, yerr=[[values[i] - lows[i] for i in range(2)],
                                 [highs[i] - values[i] for i in range(2)]],
                fmt="none", ecolor="black", capsize=4)
    ax.set_xticks(x, ["Baseline M2", "Notch + M2"])
    if any(v > 0 for v in values):
        ax.set_yscale("log")
    ax.set_ylabel("Measured BER (95% exact CI)")
    ax.set_title(title); ax.grid(True, axis="y", which="both", alpha=.3)
    fig.savefig(path, dpi=160); plt.close(fig)


def _save_plots(outdir: Path, response: Any, config: NotchConfig,
                main: dict[str, Any], amplitude_rows: list[dict[str, Any]],
                mismatch_rows: list[dict[str, Any]], awgn: dict[str, Any],
                tx: np.ndarray, channel: ChannelOutput,
                filtered_total: np.ndarray, filtered_tone: np.ndarray,
                filtered_desired: np.ndarray) -> list[Path]:
    paths: list[Path] = []
    f0 = config.center_frequency_cycles_per_symbol
    eps = np.finfo(float).tiny
    single_db = 20.0 * np.log10(np.maximum(response.single_pass_magnitude, eps))
    fb_db = 20.0 * np.log10(np.maximum(response.forward_backward_magnitude, eps))
    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    ax.plot(response.frequency_cycles_per_symbol, single_db, label="Single pass |H(f)|")
    ax.plot(response.frequency_cycles_per_symbol, fb_db, label="Forward-backward effective |H(f)|²")
    ax.axvline(f0, color="black", linestyle="--", label=f"Configured center {f0:g} cycles/symbol")
    ax.set(xlabel="Frequency (cycles/symbol)", ylabel="Magnitude (dB)",
           title=f"IIR notch response: Q={config.quality_factor:g}, sps={config.samples_per_symbol}")
    ax.set_xlim(0, config.samples_per_symbol / 2); ax.set_ylim(-160, 5)
    ax.grid(True, which="both", alpha=.3); ax.legend()
    p = outdir / "m4_notch_frequency_response.png"; fig.savefig(p, dpi=160); plt.close(fig); paths.append(p)

    n = min(320, channel.interference.size)
    t = np.arange(n) / config.samples_per_symbol
    fig, ax = plt.subplots(figsize=(9, 4.7), constrained_layout=True)
    ax.plot(t, channel.interference[:n], label="Tone before notch")
    ax.plot(t, filtered_tone[:n], label="Tone after filtfilt notch")
    ax.set(xlabel="Time (symbol periods)", ylabel="Amplitude", title="Configured tone before and after notch filtering")
    ax.grid(True, alpha=.3); ax.legend()
    p = outdir / "m4_interference_before_after_time.png"; fig.savefig(p, dpi=160); plt.close(fig); paths.append(p)

    nfft = min(8192, channel.received.size)
    start = max(300, channel.received.size // 2 - nfft // 2)
    sl = slice(start, start + nfft)
    window = np.hanning(nfft)
    freq = np.fft.rfftfreq(nfft, d=1.0 / config.samples_per_symbol)
    pre = np.abs(np.fft.rfft(channel.received[sl] * window))
    post = np.abs(np.fft.rfft(filtered_total[sl] * window))
    scale = max(float(pre.max()), eps)
    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    ax.plot(freq, 20*np.log10(np.maximum(pre/scale, eps)), label="Received before notch")
    ax.plot(freq, 20*np.log10(np.maximum(post/scale, eps)), label="Received after notch; same scale")
    ax.axvline(f0, color="black", linestyle="--", label="Configured notch center")
    ax.set(xlabel="Frequency (cycles/symbol)", ylabel="Relative magnitude (dB; common scale)",
           title="Received spectrum before and after notch, interior record")
    ax.set_xlim(0, config.samples_per_symbol/2); ax.set_ylim(-100, 5)
    ax.grid(True, alpha=.3); ax.legend()
    p = outdir / "m4_received_spectrum_before_after.png"; fig.savefig(p, dpi=160); plt.close(fig); paths.append(p)

    n = min(640, tx.size)
    t = np.arange(n) / config.samples_per_symbol
    fig, ax = plt.subplots(figsize=(9, 4.7), constrained_layout=True)
    ax.plot(t, channel.attenuated_signal[:n], label="Desired waveform before notch")
    ax.plot(t, filtered_desired[:n], label="Desired waveform after notch")
    ax.set(xlabel="Time (symbol periods)", ylabel="Amplitude", title="Desired-signal-only distortion diagnostic")
    ax.grid(True, alpha=.3); ax.legend()
    p = outdir / "m4_desired_signal_distortion.png"; fig.savefig(p, dpi=160); plt.close(fig); paths.append(p)

    _pair_bar(main, outdir / "m4_main_baseline_vs_notch_ber.png",
              f"Paired receivers: tone {main['actual_interference_frequency_cycles_per_symbol']} cycles/symbol")
    paths.append(outdir / "m4_main_baseline_vs_notch_ber.png")
    _ber_plot(amplitude_rows, "interference_amplitude_peak", "Interference peak amplitude (normalized units)",
              outdir / "m4_ber_vs_interference_amplitude.png", "Paired BER versus tone amplitude")
    paths.append(outdir / "m4_ber_vs_interference_amplitude.png")
    _ber_plot(mismatch_rows, "actual_interference_frequency_cycles_per_symbol",
              "Actual interference frequency (cycles/symbol)", outdir / "m4_ber_vs_frequency_mismatch.png",
              "Paired BER with fixed notch center and frequency mismatch")
    paths.append(outdir / "m4_ber_vs_frequency_mismatch.png")
    _pair_bar(awgn, outdir / "m4_awgn_only_control.png", "AWGN-only control at 6 dB Eb/N0")
    paths.append(outdir / "m4_awgn_only_control.png")
    return paths


def run_m4_experiments(*, n_bits: int = 30000, master_seed: int = 20261030,
                       output_dir: Path = Path("results/m4"), quality_factor: float = 30.0) -> list[Path]:
    """Execute paired M4 controls, tone sweeps, mismatch sweep and diagnostics."""
    if isinstance(n_bits, bool) or not isinstance(n_bits, int) or n_bits < 1000:
        raise ValueError("n_bits must be an integer of at least 1000")
    if isinstance(master_seed, bool) or not isinstance(master_seed, int) or master_seed < 0:
        raise ValueError("master_seed must be a nonnegative integer")
    output_dir.mkdir(parents=True, exist_ok=True)
    sps, rolloff, span, ebn0 = 8, 0.35, 10, 6.0
    notch_cfg = NotchConfig(center_frequency_cycles_per_symbol=0.35,
                            samples_per_symbol=sps, quality_factor=quality_factor)
    taps = rrc_taps(rolloff, span, sps)
    seed_sequences = np.random.SeedSequence(master_seed).spawn(8)
    seeds = [int(seq.generate_state(1, dtype=np.uint32)[0]) for seq in seed_sequences]
    bit_seed, noise_clean, noise_awgn, noise_main, noise_amp, noise_mismatch, bootstrap_seed, _ = seeds
    bits = generate_bits(n_bits, np.random.default_rng(bit_seed))
    tx = pulse_shape(bpsk_modulate(bits), taps, samples_per_symbol=sps)

    # Controls and primary comparison each use one channel realization for both branches.
    clean_cfg = ChannelConfig(samples_per_symbol=sps)
    awgn_cfg = ChannelConfig(samples_per_symbol=sps, ebn0_db=ebn0)
    main_cfg = ChannelConfig(samples_per_symbol=sps, ebn0_db=ebn0,
                             interference_amplitude=0.22,
                             interference_frequency_cycles_per_symbol=0.35,
                             interference_phase_rad=0.37)
    clean_ch = apply_configured_channel(tx, clean_cfg)
    awgn_ch = apply_configured_channel(tx, awgn_cfg, rng=np.random.default_rng(noise_awgn))
    main_ch = apply_configured_channel(tx, main_cfg, rng=np.random.default_rng(noise_main))

    comparison_rows: list[dict[str, Any]] = []
    clean_cmp = compare_receivers(clean_ch.received, bits, taps, notch_cfg,
                                  bootstrap_seed=bootstrap_seed)
    comparison_rows.append(_condition_row("clean_noiseless", clean_cmp[0], clean_cfg,
                                          notch_cfg, master_seed=master_seed, bit_seed=bit_seed,
                                          noise_seed=noise_clean, actual_frequency=None))
    awgn_cmp = compare_receivers(awgn_ch.received, bits, taps, notch_cfg,
                                 bootstrap_seed=bootstrap_seed + 1)
    awgn_row = _condition_row("awgn_only_control", awgn_cmp[0], awgn_cfg,
                              notch_cfg, master_seed=master_seed, bit_seed=bit_seed,
                              noise_seed=noise_awgn, actual_frequency=None)
    comparison_rows.append(awgn_row)
    main_cmp = compare_receivers(main_ch.received, bits, taps, notch_cfg,
                                 bootstrap_seed=bootstrap_seed + 2)
    main_diag = _diagnostics(tx, main_ch, main_cmp[3], taps, bits.size, notch_cfg, 0.35)
    main_row = _condition_row("matched_frequency_tone", main_cmp[0], main_cfg,
                              notch_cfg, master_seed=master_seed, bit_seed=bit_seed,
                              noise_seed=noise_main, actual_frequency=0.35,
                              diagnostics=main_diag)
    comparison_rows.append(main_row)
    _write_csv(output_dir / "m4_receiver_comparison.csv", comparison_rows)

    amplitude_rows: list[dict[str, Any]] = []
    for index, amplitude in enumerate((0.0, 0.08, 0.16, 0.22, 0.30, 0.42)):
        cfg = ChannelConfig(samples_per_symbol=sps, ebn0_db=ebn0,
                            interference_amplitude=amplitude,
                            interference_frequency_cycles_per_symbol=0.35 if amplitude else None,
                            interference_phase_rad=0.37)
        channel = apply_configured_channel(tx, cfg, rng=np.random.default_rng(noise_amp))
        comparison, _, _, filtered = compare_receivers(
            channel.received, bits, taps, notch_cfg, bootstrap_seed=bootstrap_seed + 10 + index)
        actual_frequency = 0.35 if amplitude else None
        diag = _diagnostics(tx, channel, filtered, taps, bits.size, notch_cfg, 0.35) if amplitude else {
            "interference_amplitude_input_least_squares": None,
            "interference_amplitude_output_least_squares": None,
            "interference_amplitude_attenuation_db": None,
        }
        amplitude_rows.append(_condition_row("interference_amplitude_sweep", comparison, cfg,
                                             notch_cfg, master_seed=master_seed, bit_seed=bit_seed,
                                             noise_seed=noise_amp, actual_frequency=actual_frequency,
                                             diagnostics=diag))
    _write_csv(output_dir / "m4_interference_amplitude_sweep.csv", amplitude_rows)

    mismatch_rows: list[dict[str, Any]] = []
    for index, actual_frequency in enumerate((0.31, 0.33, 0.34, 0.35, 0.36, 0.37, 0.39)):
        cfg = ChannelConfig(samples_per_symbol=sps, ebn0_db=ebn0,
                            interference_amplitude=0.22,
                            interference_frequency_cycles_per_symbol=actual_frequency,
                            interference_phase_rad=0.37)
        channel = apply_configured_channel(tx, cfg, rng=np.random.default_rng(noise_mismatch))
        comparison, _, _, filtered = compare_receivers(
            channel.received, bits, taps, notch_cfg, bootstrap_seed=bootstrap_seed + 30 + index)
        diag = _diagnostics(tx, channel, filtered, taps, bits.size, notch_cfg, actual_frequency)
        mismatch_rows.append(_condition_row("frequency_mismatch_sweep", comparison, cfg,
                                            notch_cfg, master_seed=master_seed, bit_seed=bit_seed,
                                            noise_seed=noise_mismatch, actual_frequency=actual_frequency,
                                            diagnostics=diag))
    _write_csv(output_dir / "m4_frequency_mismatch_sweep.csv", mismatch_rows)

    # Actual single-pass and filtfilt effective magnitude response.
    response = notch_frequency_response(notch_cfg, points=16384)
    response_csv = output_dir / "m4_notch_frequency_response.csv"
    with response_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frequency_cycles_per_symbol", "single_pass_magnitude", "single_pass_db",
                         "forward_backward_effective_magnitude", "forward_backward_effective_db"])
        eps = np.finfo(float).tiny
        for f, single, forward in zip(response.frequency_cycles_per_symbol,
                                      response.single_pass_magnitude,
                                      response.forward_backward_magnitude, strict=True):
            writer.writerow([f, single, 20*np.log10(max(float(single), eps)),
                             forward, 20*np.log10(max(float(forward), eps))])

    # Component, desired-only, noise-only and total waveform diagnostics.
    filtered_total = main_cmp[3]
    filtered_tone = apply_notch(main_ch.interference, notch_cfg)
    filtered_desired = apply_notch(main_ch.attenuated_signal, notch_cfg)
    filtered_noise = apply_notch(main_ch.noise, notch_cfg)
    diag_json = {
        "experiment": "matched_frequency_tone_diagnostics",
        "master_seed": master_seed, "bit_seed": bit_seed, "noise_seed": noise_main,
        "configuration": {"n_bits": n_bits, "ebn0_db": ebn0,
                          "samples_per_symbol": sps, "rrc_rolloff": rolloff,
                          "rrc_span_symbols": span, "tone_amplitude_peak": 0.22,
                          "tone_frequency_cycles_per_symbol": 0.35,
                          "tone_phase_rad": 0.37,
                          "notch_center_cycles_per_symbol": notch_cfg.center_frequency_cycles_per_symbol,
                          "notch_quality_factor": notch_cfg.quality_factor,
                          "filter_mode": "scipy.signal.filtfilt, padtype=odd, padlen=9; offline/noncausal"},
        "measurements": main_diag,
        "notch_coefficients": {"b": notch_coefficients(notch_cfg)[0].tolist(),
                               "a": notch_coefficients(notch_cfg)[1].tolist()},
        "noise_input_variance_configured": main_cfg.noise_variance,
        "noise_output_mean_square_power": mean_square_power(filtered_noise),
        "single_pass_and_forward_backward_responses": "m4_notch_frequency_response.csv",
        "software": {"python": platform.python_version(), "numpy": np.__version__,
                     "scipy": scipy.__version__, "matplotlib": matplotlib.__version__},
        "paired_test": "exact two-sided McNemar binomial test on discordant bit outcomes; p-value assumes independent discordant pairs",
        "paired_interval": "contiguous block bootstrap on candidate-minus-baseline bit error indicators; 50-bit blocks, 1000 replicates",
    }
    diag_path = output_dir / "m4_filter_diagnostics.json"
    diag_path.write_text(json.dumps(diag_json, indent=2), encoding="utf-8")

    diagnostic_csv = output_dir / "m4_filter_diagnostic_waveforms.csv"
    n_diag = min(2048, tx.size)
    with diagnostic_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample_index", "time_symbols", "transmitted", "received_before_notch",
                         "received_after_notch", "tone_before_notch", "tone_after_notch",
                         "desired_before_notch", "desired_after_notch", "awgn_before_notch", "awgn_after_notch"])
        for n in range(n_diag):
            writer.writerow([n, n/sps, tx[n], main_ch.received[n], filtered_total[n],
                             main_ch.interference[n], filtered_tone[n],
                             main_ch.attenuated_signal[n], filtered_desired[n],
                             main_ch.noise[n], filtered_noise[n]])

    plots = _save_plots(output_dir, response, notch_cfg, main_row, amplitude_rows,
                        mismatch_rows, awgn_row, tx, main_ch, filtered_total,
                        filtered_tone, filtered_desired)
    metadata = {
        "milestone": "M4",
        "master_seed": master_seed,
        "seed_strategy": "One fixed bit sequence; each experiment has a fixed noise seed shared across both receiver branches and across its sweep; bootstrap streams are explicit and separate.",
        "primary_configuration": {"n_bits": n_bits, "bit_seed": bit_seed,
                                  "noise_seed_main": noise_main, "ebn0_db": ebn0,
                                  "samples_per_symbol": sps, "rrc_rolloff": rolloff,
                                  "rrc_span_symbols": span, "tone_amplitude_peak": 0.22,
                                  "tone_frequency_cycles_per_symbol": 0.35,
                                  "tone_phase_rad": 0.37,
                                  "notch_center_cycles_per_symbol": notch_cfg.center_frequency_cycles_per_symbol,
                                  "notch_quality_factor": notch_cfg.quality_factor},
        "receiver_paths": {"baseline": "same M2 matched filter + delay-aware sampling + existing BPSK detector",
                           "candidate": "offline filtfilt notch then same M2 receiver",
                           "same_received_waveform": True},
        "filtering": {"design": "scipy.signal.iirnotch second order",
                      "frequency_units": "cycles/symbol; fs=samples_per_symbol",
                      "processing": "scipy.signal.filtfilt, odd padding, explicit padlen=9",
                      "causal": False, "minimum_input_length_samples": 10,
                      "quality_factor_supported_range": [0.5, 1000]},
        "statistical_methods": {"ber_interval": "two-sided 95% Clopper-Pearson",
                                "paired_difference": "candidate minus baseline; contiguous 50-bit block bootstrap, 1000 replicates",
                                "paired_test": "exact two-sided McNemar test; independence assumption noted"},
        "files": ["m4_receiver_comparison.csv", "m4_interference_amplitude_sweep.csv",
                  "m4_frequency_mismatch_sweep.csv", "m4_notch_frequency_response.csv",
                  "m4_filter_diagnostics.json", "m4_filter_diagnostic_waveforms.csv"],
    }
    config_path = output_dir / "m4_experiment_config.json"
    config_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return [*plots, output_dir / "m4_receiver_comparison.csv",
            output_dir / "m4_interference_amplitude_sweep.csv",
            output_dir / "m4_frequency_mismatch_sweep.csv", response_csv,
            diag_path, diagnostic_csv, config_path]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run paired SignalShield M4 notch-receiver experiments.")
    parser.add_argument("--n-bits", type=int, default=30000)
    parser.add_argument("--seed", type=int, default=20261030)
    parser.add_argument("--quality-factor", type=float, default=30.0)
    parser.add_argument("--output-dir", type=Path, default=Path("results/m4"))
    args = parser.parse_args()
    started = time.perf_counter()
    files = run_m4_experiments(n_bits=args.n_bits, master_seed=args.seed,
                               output_dir=args.output_dir, quality_factor=args.quality_factor)
    print(f"M4 experiment runtime: {time.perf_counter()-started:.3f} s")
    for path in files:
        print(f"saved: {path}")
    for filename in ("m4_receiver_comparison.csv", "m4_interference_amplitude_sweep.csv",
                     "m4_frequency_mismatch_sweep.csv"):
        with (args.output_dir / filename).open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                print(f"{row['experiment']}: actual tone={row['actual_interference_frequency_cycles_per_symbol']} "
                      f"amplitude={row['interference_amplitude_peak']}; baseline={row['baseline_errors']}/{row['baseline_n_bits']} "
                      f"BER={float(row['baseline_ber']):.7g}; notch={row['notch_errors']}/{row['notch_n_bits']} "
                      f"BER={float(row['notch_ber']):.7g}; corrected={row['paired_errors_corrected_by_notch']} "
                      f"introduced={row['paired_errors_introduced_by_notch']}; tone attenuation dB="
                      f"{row.get('interference_amplitude_attenuation_db')}")


if __name__ == "__main__":
    main()
