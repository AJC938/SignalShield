"""Unified, reproducible experiment runner for SignalShield M1–M5."""

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

from signalshield.channel import (
    ChannelConfig,
    ChannelOutput,
    add_awgn,
    apply_configured_channel,
    mean_square_power,
    noise_variance_from_ebn0_db,
)
from signalshield.experiment_framework import (
    DEFAULT_EBN0_VALUES,
    DEFAULT_SWEEP_VALUES,
    SUPPORTED_SCENARIOS,
    ExperimentConfig,
    ExperimentRecord,
    aggregate_paired_records,
    aggregate_run_records,
    derive_seed,
)
from signalshield.filters import rrc_taps
from signalshield.metrics import ber_estimate, bpsk_awgn_theory, paired_ber_estimate
from signalshield.m4_experiments import compare_receivers
from signalshield.modulation import bpsk_modulate
from signalshield.notch import apply_notch, notch_frequency_response
from signalshield.receiver import detect_bpsk, receive_bpsk_waveform
from signalshield.signals import generate_bits
from signalshield.waveform import pulse_shape


def _csv_write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _points(config: ExperimentConfig) -> list[tuple[int, str, float | None, float | None]]:
    """Return stable condition index, x-axis meaning/value, and SNR."""
    if config.scenario in ("awgn_reference", "waveform_awgn"):
        return [(i, "ebn0_db", float(value), float(value))
                for i, value in enumerate(config.ebn0_values_db)]
    if config.scenario == "interference_amplitude":
        return [(i, "interference_amplitude_peak", float(v), config.ebn0_db)
                for i, v in enumerate(config.sweep_values)]
    if config.scenario == "interference_frequency":
        return [(i, "interference_frequency_cycles_per_symbol", float(v), config.ebn0_db)
                for i, v in enumerate(config.sweep_values)]
    if config.scenario == "attenuation":
        return [(i, "attenuation_db", float(v), config.ebn0_db)
                for i, v in enumerate(config.sweep_values)]
    if config.scenario == "frequency_mismatch":
        return [(i, "actual_interference_frequency_cycles_per_symbol", float(v), config.ebn0_db)
                for i, v in enumerate(config.sweep_values)]
    if config.scenario == "receiver_comparison":
        return [(0, "interference_frequency_cycles_per_symbol",
                 float(config.interference_frequency_cycles_per_symbol), config.ebn0_db)]
    raise ValueError(f"unsupported scenario: {config.scenario}")


def _scenario_channel(config: ExperimentConfig, point_parameter: str, point_value: float | None,
                      ebn0_db: float) -> ChannelConfig:
    amplitude = 0.0
    frequency: float | None = None
    attenuation = 0.0
    if config.scenario == "interference_amplitude":
        amplitude = float(point_value)
        frequency = config.interference_frequency_cycles_per_symbol if amplitude > 0 else None
        attenuation = config.attenuation_db
    elif config.scenario == "interference_frequency":
        amplitude = config.interference_amplitude
        frequency = float(point_value)
        attenuation = config.attenuation_db
    elif config.scenario == "attenuation":
        attenuation = float(point_value)
    elif config.scenario == "receiver_comparison":
        amplitude = config.interference_amplitude
        frequency = config.interference_frequency_cycles_per_symbol
        attenuation = config.attenuation_db
    elif config.scenario == "frequency_mismatch":
        amplitude = config.interference_amplitude
        frequency = float(point_value)
        attenuation = config.attenuation_db
    return ChannelConfig(
        samples_per_symbol=config.samples_per_symbol,
        ebn0_db=ebn0_db,
        attenuation_db=attenuation,
        interference_amplitude=amplitude,
        interference_frequency_cycles_per_symbol=frequency,
        interference_phase_rad=config.interference_phase_rad,
    )


def _seed_for_point(config: ExperimentConfig, repetition: int, point_index: int,
                    scenario: str, role: str, parameter: str, value: float | None) -> int:
    # SNR sweeps use independent noise per SNR; paired channel sweeps deliberately share it.
    if scenario in ("awgn_reference", "waveform_awgn"):
        condition = f"{parameter}={value:.12g}"
    else:
        condition = "shared_channel_across_sweep"
    return derive_seed(config.master_seed, config.experiment_id, repetition,
                       f"{scenario}:{role}", condition)


def _theory(scenario: str, ebn0_db: float, channel: ChannelConfig,
            amplitude: float) -> tuple[float | None, bool, str]:
    if scenario in ("awgn_reference", "waveform_awgn"):
        applicable = channel.interference_amplitude == 0.0 and channel.attenuation_db == 0.0
        if applicable:
            return float(bpsk_awgn_theory(ebn0_db)), True, "Coherent uncoded BPSK/AWGN reference."
    elif channel.interference_amplitude == 0.0:
        effective = ebn0_db - channel.attenuation_db
        return float(bpsk_awgn_theory(effective)), True, "AWGN-only reference at configured Eb/N0 minus signal attenuation."
    return None, False, "No exact AWGN-only theory assigned because channel or receiver assumptions differ."


def _channel_measurements(tx: np.ndarray, received: np.ndarray, channel: ChannelOutput | None,
                          noise_array: np.ndarray | None, configured_noise: float | None) -> dict[str, float | None]:
    if channel is not None:
        noise = channel.noise
        interference = channel.interference
        desired = channel.attenuated_signal
    else:
        noise = noise_array
        interference = np.zeros_like(tx)
        desired = tx
    noise_var = float(np.var(noise, ddof=1)) if noise is not None and noise.size > 1 else None
    tone_power = mean_square_power(interference) if interference.size else 0.0
    desired_power = mean_square_power(desired) if desired.size else 0.0
    ratio = tone_power / desired_power if desired_power > 0.0 else None
    return {
        "noise_variance_configured": configured_noise,
        "noise_variance_measured": noise_var,
        "transmit_record_mean_square_power": mean_square_power(tx),
        "interference_record_mean_square_power": tone_power,
        "interference_to_desired_power_ratio": ratio,
        "received_record_mean_square_power": mean_square_power(received),
    }


def _record(
    config: ExperimentConfig,
    *,
    point_index: int,
    point_parameter: str,
    point_value: float | None,
    repetition: int,
    receiver_id: str,
    bit_seed: int,
    noise_seed: int,
    bootstrap_seed: int | None,
    bits: np.ndarray,
    decisions: np.ndarray,
    ebn0_db: float | None,
    channel_config: ChannelConfig | None,
    measurements: dict[str, float | None],
    theory_ber: float | None,
    theory_applicable: bool,
    theory_note: str,
    runtime_seconds: float,
    familywise_confidence: float,
    paired: dict[str, Any] | None = None,
) -> ExperimentRecord:
    estimate = ber_estimate(bits, decisions, config.confidence_level)
    familywise_estimate = ber_estimate(bits, decisions, familywise_confidence)
    channel = channel_config
    paired = paired or {}
    gain = None if channel is None else channel.desired_gain
    attenuation = None if channel is None else channel.attenuation_db
    effective = None if ebn0_db is None or channel is None else ebn0_db - channel.attenuation_db
    return ExperimentRecord(
        experiment_id=config.experiment_id,
        configuration_id=config.configuration_id,
        scenario=config.scenario,
        scenario_point_index=point_index,
        scenario_parameter=point_parameter,
        scenario_value=point_value,
        repetition=repetition,
        receiver_id=receiver_id,
        master_seed=config.master_seed,
        bit_seed=bit_seed,
        noise_seed=noise_seed,
        bootstrap_seed=bootstrap_seed,
        n_bits=estimate.n_bits,
        errors=estimate.errors,
        ber=estimate.ber,
        confidence_level=config.confidence_level,
        ci_lower=estimate.confidence_interval[0],
        ci_upper=estimate.confidence_interval[1],
        zero_error_upper95=estimate.zero_error_upper_bound_95,
        familywise_confidence_level=familywise_confidence,
        familywise_ci_lower=familywise_estimate.confidence_interval[0],
        familywise_ci_upper=familywise_estimate.confidence_interval[1],
        ebn0_db=ebn0_db,
        effective_ebn0_db=effective,
        samples_per_symbol=(1 if config.scenario == "awgn_reference" else config.samples_per_symbol),
        rolloff=(None if config.scenario == "awgn_reference" else config.rolloff),
        span_symbols=(None if config.scenario == "awgn_reference" else config.span_symbols),
        attenuation_db=attenuation,
        desired_gain=gain,
        interference_amplitude_peak=None if channel is None else channel.interference_amplitude,
        interference_frequency_cycles_per_symbol=None if channel is None else channel.interference_frequency_cycles_per_symbol,
        interference_phase_rad=None if channel is None else channel.interference_phase_rad,
        noise_variance_configured=measurements["noise_variance_configured"],
        noise_variance_measured=measurements["noise_variance_measured"],
        transmit_record_mean_square_power=measurements["transmit_record_mean_square_power"],
        interference_record_mean_square_power=measurements["interference_record_mean_square_power"],
        interference_to_desired_power_ratio=measurements["interference_to_desired_power_ratio"],
        received_record_mean_square_power=measurements["received_record_mean_square_power"],
        notch_center_cycles_per_symbol=(config.notch_center_cycles_per_symbol
                                        if receiver_id == "notch_m2" else None),
        notch_quality_factor=(config.notch_quality_factor if receiver_id == "notch_m2" else None),
        theoretical_ber=theory_ber if theory_applicable and receiver_id != "notch_m2" else None,
        theoretical_reference_applicable=bool(theory_applicable and receiver_id != "notch_m2"),
        theory_note=(theory_note if receiver_id != "notch_m2"
                     else "Notch changes the signal and noise response; AWGN-only theory is not assigned."),
        paired_ber_difference=paired.get("difference_candidate_minus_baseline"),
        paired_block_ci_lower=paired.get("primary_ci_lower"),
        paired_block_ci_upper=paired.get("primary_ci_upper"),
        paired_alternate_ci_lower=paired.get("alternate_ci_lower"),
        paired_alternate_ci_upper=paired.get("alternate_ci_upper"),
        paired_corrected_errors=paired.get("corrected_errors"),
        paired_introduced_errors=paired.get("introduced_errors"),
        paired_shared_errors=paired.get("shared_errors"),
        paired_unchanged_decisions=paired.get("unchanged_decisions"),
        paired_mcnemar_p_value=paired.get("mcnemar_p_value"),
        paired_mcnemar_underflow=paired.get("mcnemar_underflow"),
        runtime_seconds=runtime_seconds,
        execution_status="success",
        failure_note=None,
    )


def _failure_record(config: ExperimentConfig, point_index: int, point_parameter: str,
                    point_value: float | None, repetition: int, note: str) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=config.experiment_id, configuration_id=config.configuration_id,
        scenario=config.scenario, scenario_point_index=point_index,
        scenario_parameter=point_parameter, scenario_value=point_value,
        repetition=repetition, receiver_id="scenario_execution",
        master_seed=config.master_seed, bit_seed=None, noise_seed=None, bootstrap_seed=None,
        n_bits=None, errors=None, ber=None, confidence_level=config.confidence_level,
        ci_lower=None, ci_upper=None, zero_error_upper95=None,
        familywise_confidence_level=config.confidence_level,
        familywise_ci_lower=None, familywise_ci_upper=None, ebn0_db=None,
        effective_ebn0_db=None, samples_per_symbol=config.samples_per_symbol,
        rolloff=config.rolloff, span_symbols=config.span_symbols,
        attenuation_db=None, desired_gain=None, interference_amplitude_peak=None,
        interference_frequency_cycles_per_symbol=None, interference_phase_rad=None,
        noise_variance_configured=None, noise_variance_measured=None,
        transmit_record_mean_square_power=None, interference_record_mean_square_power=None,
        interference_to_desired_power_ratio=None, received_record_mean_square_power=None,
        notch_center_cycles_per_symbol=None, notch_quality_factor=None,
        theoretical_ber=None, theoretical_reference_applicable=False,
        theory_note="Scenario failed before a metric could be computed.",
        paired_ber_difference=None, paired_block_ci_lower=None, paired_block_ci_upper=None,
        paired_alternate_ci_lower=None, paired_alternate_ci_upper=None,
        paired_corrected_errors=None, paired_introduced_errors=None,
        paired_shared_errors=None, paired_unchanged_decisions=None,
        paired_mcnemar_p_value=None, paired_mcnemar_underflow=None,
        runtime_seconds=None, execution_status="failed", failure_note=note,
    )


def _paired_metadata(stats: Any, config: ExperimentConfig) -> dict[str, Any]:
    primary = stats.block_confidence_intervals[config.bootstrap_block_length]
    alternate = stats.block_confidence_intervals[config.alternate_block_length]
    p_underflow = stats.mcnemar_p_value_underflow
    return {
        "difference_candidate_minus_baseline": stats.difference_candidate_minus_baseline,
        "primary_ci_lower": primary[0], "primary_ci_upper": primary[1],
        "alternate_ci_lower": alternate[0], "alternate_ci_upper": alternate[1],
        "corrected_errors": stats.corrected_errors,
        "introduced_errors": stats.introduced_errors,
        "shared_errors": stats.shared_errors,
        "unchanged_decisions": stats.unchanged_decisions,
        "mcnemar_p_value": None if p_underflow else stats.mcnemar_exact_p_value,
        "mcnemar_underflow": p_underflow,
    }


def _error_outcome_rows(repetition: int, bits: np.ndarray, baseline: np.ndarray,
                        candidate: np.ndarray, point_index: int) -> list[dict[str, Any]]:
    base_error = baseline != bits
    cand_error = candidate != bits
    rows = []
    for index in range(bits.size):
        rows.append({
            "scenario_point_index": point_index,
            "repetition": repetition,
            "bit_index": index,
            "transmitted_bit": int(bits[index]),
            "baseline_decision": int(baseline[index]),
            "notch_decision": int(candidate[index]),
            "baseline_error": bool(base_error[index]),
            "notch_error": bool(cand_error[index]),
            "corrected_by_notch": bool(base_error[index] and not cand_error[index]),
            "introduced_by_notch": bool(not base_error[index] and cand_error[index]),
            "error_shared_by_both": bool(base_error[index] and cand_error[index]),
        })
    return rows


def _execute_point(config: ExperimentConfig, point: tuple[int, str, float | None, float | None],
                   repetition: int, bits: np.ndarray, tx_symbols: np.ndarray,
                   tx_waveform: np.ndarray, taps: np.ndarray) -> tuple[list[ExperimentRecord], list[dict[str, Any]]]:
    point_index, point_parameter, point_value, ebn0 = point
    assert ebn0 is not None
    bit_seed = derive_seed(config.master_seed, config.experiment_id, repetition, "transmitted_bits")
    noise_seed = _seed_for_point(config, repetition, point_index, config.scenario,
                                 "awgn", point_parameter, point_value)
    bootstrap_seed = derive_seed(config.master_seed, config.experiment_id, repetition,
                                 "paired_bootstrap", f"point={point_index}")
    started = time.perf_counter()
    channel_cfg: ChannelConfig | None = None
    channel_output: ChannelOutput | None = None
    noise_array: np.ndarray | None = None
    received: np.ndarray
    decision_rows: list[dict[str, Any]] = []
    receivers: list[tuple[str, np.ndarray, float]] = []

    if config.scenario == "awgn_reference":
        variance = noise_variance_from_ebn0_db(ebn0)
        received = add_awgn(tx_symbols, variance, np.random.default_rng(noise_seed))
        noise_array = received - tx_symbols
        decisions = detect_bpsk(received)
        channel_cfg = ChannelConfig(samples_per_symbol=config.samples_per_symbol, ebn0_db=ebn0)
        theoretical, applicable, theory_note = _theory(config.scenario, ebn0, channel_cfg, 0.0)
        measurements = _channel_measurements(tx_symbols, received, None, noise_array, variance)
        receivers.append(("baseline_m1", decisions, time.perf_counter() - started))

    elif config.scenario == "waveform_awgn":
        channel_cfg = ChannelConfig(samples_per_symbol=config.samples_per_symbol, ebn0_db=ebn0)
        channel_output = apply_configured_channel(tx_waveform, channel_cfg,
                                                 rng=np.random.default_rng(noise_seed))
        received = channel_output.received
        output = receive_bpsk_waveform(received, taps, n_symbols=bits.size,
                                      samples_per_symbol=config.samples_per_symbol)
        theoretical, applicable, theory_note = _theory(config.scenario, ebn0, channel_cfg, 0.0)
        measurements = _channel_measurements(tx_waveform, received, channel_output, None,
                                             channel_cfg.noise_variance)
        receivers.append(("baseline_m2", output.detected_bits, time.perf_counter() - started))

    else:
        channel_cfg = _scenario_channel(config, point_parameter, point_value, ebn0)
        channel_output = apply_configured_channel(tx_waveform, channel_cfg,
                                                 rng=np.random.default_rng(noise_seed))
        received = channel_output.received
        measurements = _channel_measurements(tx_waveform, received, channel_output, None,
                                             channel_cfg.noise_variance)
        theoretical, applicable, theory_note = _theory(config.scenario, ebn0, channel_cfg,
                                                       channel_cfg.interference_amplitude)
        paired_scenario = config.scenario in ("receiver_comparison", "frequency_mismatch")
        if paired_scenario:
            _compare_summary, baseline_out, candidate_out, _ = compare_receivers(
                received, bits, taps, config.notch_config,
                bootstrap_seed=bootstrap_seed,
                block_length=config.bootstrap_block_length,
                bootstrap_replicates=config.bootstrap_replicates,
            )
            paired_stats = paired_ber_estimate(
                bits, baseline_out.detected_bits, candidate_out.detected_bits,
                confidence_level=config.confidence_level,
                block_lengths=(config.bootstrap_block_length, config.alternate_block_length),
                bootstrap_replicates=config.bootstrap_replicates,
                bootstrap_seed=bootstrap_seed,
            )
            paired_meta = _paired_metadata(paired_stats, config)
            baseline_elapsed = float(_compare_summary["baseline_receiver_runtime_seconds"])
            notch_elapsed = float(_compare_summary["notch_receiver_runtime_seconds_including_filter_seconds"])
            receivers.append(("baseline_m2", baseline_out.detected_bits, baseline_elapsed, paired_meta))
            receivers.append(("notch_m2", candidate_out.detected_bits, notch_elapsed, paired_meta))
            if config.scenario == "receiver_comparison" and config.save_paired_outcomes:
                decision_rows = _error_outcome_rows(repetition, bits,
                                                    baseline_out.detected_bits,
                                                    candidate_out.detected_bits,
                                                    point_index)
        else:
            output = receive_bpsk_waveform(received, taps, n_symbols=bits.size,
                                          samples_per_symbol=config.samples_per_symbol)
            receivers.append(("baseline_m2", output.detected_bits, time.perf_counter() - started))

    if channel_cfg is None:
        raise RuntimeError("scenario did not produce a channel configuration")
    family_size = max(1, len(_points(config)) * config.repetitions * len(receivers))
    family_confidence = 1.0 - (1.0 - config.confidence_level) / family_size
    records: list[ExperimentRecord] = []
    for receiver_item in receivers:
        receiver_id, decisions, runtime = receiver_item[:3]
        paired = receiver_item[3] if len(receiver_item) == 4 else None
        records.append(_record(
            config, point_index=point_index, point_parameter=point_parameter,
            point_value=point_value, repetition=repetition, receiver_id=receiver_id,
            bit_seed=bit_seed, noise_seed=noise_seed,
            bootstrap_seed=bootstrap_seed if paired else None,
            bits=bits, decisions=decisions, ebn0_db=ebn0,
            channel_config=channel_cfg, measurements=measurements,
            theory_ber=theoretical, theory_applicable=applicable,
            theory_note=theory_note, runtime_seconds=runtime,
            familywise_confidence=family_confidence, paired=paired,
        ))
    return records, decision_rows


def _plot_results(config: ExperimentConfig, records: list[ExperimentRecord],
                  summaries: list[dict[str, Any]], paired_summaries: list[dict[str, Any]],
                  output_dir: Path) -> list[Path]:
    successful = [r for r in records if r.execution_status == "success" and r.ber is not None]
    if not successful:
        return []
    paths: list[Path] = []
    receiver_ids = sorted({r.receiver_id for r in successful})
    summary_by_key = {(s["scenario_point_index"], s["receiver_id"]): s for s in summaries}
    xvalues = sorted({r.scenario_value for r in successful if r.scenario_value is not None})
    if not xvalues:
        xvalues = [0.0]

    # Shared scenario-vs-BER plot with repeat-mean confidence and individual runs.
    fig, ax = plt.subplots(figsize=(8.5, 5.5), constrained_layout=True)
    for receiver in receiver_ids:
        group_summaries = [s for s in summaries if s["receiver_id"] == receiver]
        group_summaries.sort(key=lambda s: s["scenario_point_index"])
        positive = [s for s in group_summaries if s["mean_run_ber"] > 0.0]
        if positive:
            xs = [float(s["scenario_value"] if s["scenario_value"] is not None else 0.0) for s in positive]
            ys = [float(s["mean_run_ber"]) for s in positive]
            lows = [max(0.0, ys[i] - float(positive[i]["mean_run_ber_t_ci_lower"] or 0.0))
                    for i in range(len(positive))]
            highs = [max(0.0, float(positive[i]["mean_run_ber_t_ci_upper"] or ys[i]) - ys[i])
                     for i in range(len(positive))]
            ax.errorbar(xs, ys, yerr=[lows, highs], marker="o", capsize=3,
                        label=f"{receiver}: mean across runs (t interval)")
        zero_groups = [s for s in group_summaries if s["mean_run_ber"] == 0.0]
        for i, s in enumerate(zero_groups):
            row = next(r for r in successful if r.scenario_point_index == s["scenario_point_index"]
                       and r.receiver_id == receiver)
            if row.zero_error_upper95 is not None:
                x = float(s["scenario_value"] if s["scenario_value"] is not None else 0.0)
                ax.scatter([x], [row.zero_error_upper95], marker="v", color="tab:red",
                           label=f"{receiver}: zero errors, 95% upper bound" if i == 0 else None)
        if config.scenario in ("awgn_reference", "waveform_awgn") and receiver != "notch_m2":
            theory_rows = [r for r in successful if r.receiver_id == receiver and r.theoretical_ber is not None]
            theory_rows.sort(key=lambda r: float(r.scenario_value or 0.0))
            if theory_rows:
                ax.plot([r.scenario_value for r in theory_rows],
                        [r.theoretical_ber for r in theory_rows], "k--", label="Coherent BPSK/AWGN theory")
    first = successful[0]
    ax.set_xlabel(first.scenario_parameter.replace("_", " "))
    ax.set_ylabel("BER")
    ax.set_yscale("log")
    ax.set_title(f"{config.scenario}: {config.repetitions} seeded runs, {config.n_bits} bits/run")
    ax.grid(True, which="both", alpha=.3); ax.legend()
    path = output_dir / "ber_by_condition.png"; fig.savefig(path, dpi=160); plt.close(fig); paths.append(path)

    # Show individual repetition variability separately from per-run binomial intervals.
    fig, ax = plt.subplots(figsize=(8.5, 5.5), constrained_layout=True)
    receiver_position = {name: i for i, name in enumerate(receiver_ids)}
    rng = np.random.default_rng(1701)
    for receiver in receiver_ids:
        group = [r for r in successful if r.receiver_id == receiver]
        normal = [r for r in group if r.ber is not None and r.ber > 0.0]
        zeros = [r for r in group if r.ber == 0.0 and r.zero_error_upper95 is not None]
        xs = [float(r.scenario_value if r.scenario_value is not None else 0.0)
              + (receiver_position[receiver] - (len(receiver_ids)-1)/2)*0.012
              + float(rng.uniform(-0.003, 0.003)) for r in normal]
        ys = [float(r.ber) for r in normal]
        if ys:
            ax.scatter(xs, ys, label=f"{receiver} per-run measured BER")
        zero_x = [float(r.scenario_value if r.scenario_value is not None else 0.0)
                  + (receiver_position[receiver] - (len(receiver_ids)-1)/2)*0.012
                  + float(rng.uniform(-0.003, 0.003)) for r in zeros]
        if zero_x:
            ax.scatter(zero_x, [float(r.zero_error_upper95) for r in zeros], marker="v",
                       label=f"{receiver}: zero errors, upper 95% bound")
    ax.set_yscale("log"); ax.set_xlabel(first.scenario_parameter.replace("_", " "))
    ax.set_ylabel("Run BER; zero-error runs shown at separate upper bound")
    ax.set_title("Between-run variability (points); per-run exact intervals remain in CSV")
    ax.grid(True, which="both", alpha=.3); ax.legend()
    path = output_dir / "run_variability.png"; fig.savefig(path, dpi=160); plt.close(fig); paths.append(path)

    if paired_summaries:
        fig, ax = plt.subplots(figsize=(8.2, 5.2), constrained_layout=True)
        paired_summaries.sort(key=lambda s: s["scenario_point_index"])
        xs = [float(s["scenario_value"] if s["scenario_value"] is not None else 0.0) for s in paired_summaries]
        ys = [float(s["mean_paired_delta_candidate_minus_baseline"]) for s in paired_summaries]
        lows, highs = [], []
        for s, y in zip(paired_summaries, ys, strict=True):
            lo, hi = s["mean_delta_t_ci_lower"], s["mean_delta_t_ci_upper"]
            if lo is None or hi is None:
                row = next(r for r in successful if r.receiver_id == "baseline_m2"
                           and r.scenario_point_index == s["scenario_point_index"])
                lo, hi = row.paired_block_ci_lower, row.paired_block_ci_upper
            lows.append(max(0.0, y-float(lo)))
            highs.append(max(0.0, float(hi)-y))
        ax.errorbar(xs, ys, yerr=[lows, highs], marker="o", capsize=4)
        ax.axhline(0.0, color="black", linestyle="--", label="No paired BER change")
        ax.set_xlabel(first.scenario_parameter.replace("_", " "))
        ax.set_ylabel("Candidate BER − baseline BER")
        ax.set_title("Paired receiver BER difference; negative favors candidate")
        ax.grid(True, alpha=.3); ax.legend()
        path = output_dir / "paired_ber_difference.png"; fig.savefig(path, dpi=160); plt.close(fig); paths.append(path)
    return paths


def run_experiment(config: ExperimentConfig) -> dict[str, Any]:
    """Execute one configured experiment and save coherent M5 artifacts."""
    if not isinstance(config, ExperimentConfig):
        raise TypeError("config must be an ExperimentConfig")
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / "resolved_config.json"
    config.save_json(config_path)
    points = _points(config)
    records: list[ExperimentRecord] = []
    outcome_rows: list[dict[str, Any]] = []
    log_lines = [f"experiment_id={config.experiment_id}", f"scenario={config.scenario}",
                 f"configuration_id={config.configuration_id}",
                 f"master_seed={config.master_seed}; repetitions={config.repetitions}; n_bits={config.n_bits}"]
    waveform = config.waveform_config
    taps = rrc_taps(waveform.rolloff, waveform.span_symbols, waveform.samples_per_symbol)
    failures = 0

    for repetition in range(config.repetitions):
        bit_seed = derive_seed(config.master_seed, config.experiment_id, repetition, "transmitted_bits")
        bits = generate_bits(config.n_bits, np.random.default_rng(bit_seed))
        symbols = bpsk_modulate(bits)
        tx_waveform = pulse_shape(symbols, taps, samples_per_symbol=config.samples_per_symbol)
        for point in points:
            point_index, point_parameter, point_value, _ = point
            try:
                rows, pair_outcomes = _execute_point(config, point, repetition, bits,
                                                      symbols, tx_waveform, taps)
                records.extend(rows)
                if pair_outcomes:
                    outcome_rows.extend(pair_outcomes)
                for row in rows:
                    log_lines.append(
                        f"status=success scenario={config.scenario} repetition={repetition} "
                        f"point={point_index}:{point_parameter}={point_value} receiver={row.receiver_id} "
                        f"errors={row.errors}/{row.n_bits} BER={row.ber:.12g} seed_bit={row.bit_seed} "
                        f"seed_noise={row.noise_seed}"
                    )
            except Exception as exc:  # Record failure and continue independent points.
                failures += 1
                note = f"{type(exc).__name__}: {exc}"
                records.append(_failure_record(config, point_index, point_parameter,
                                              point_value, repetition, note))
                log_lines.append(f"status=failed repetition={repetition} point={point_index} {note}")

    result_rows = [r.to_dict() for r in records]
    result_path = output_dir / "results.csv"
    _csv_write(result_path, result_rows)
    summaries = aggregate_run_records(records, config.confidence_level)
    summary_path = output_dir / "aggregate_summary.csv"
    _csv_write(summary_path, summaries)
    paired_summaries = aggregate_paired_records(records, config.confidence_level)
    paired_path = output_dir / "paired_summary.csv"
    _csv_write(paired_path, paired_summaries)
    outcome_path: Path | None = None
    if outcome_rows:
        outcome_path = output_dir / "paired_per_bit_outcomes.csv"
        _csv_write(outcome_path, outcome_rows)

    plots = _plot_results(config, records, summaries, paired_summaries, output_dir)
    status = "completed" if failures == 0 else ("failed" if failures == len(points)*config.repetitions else "partial")
    artifacts = [str(config_path), str(result_path), str(summary_path), str(paired_path)]
    if outcome_path:
        artifacts.append(str(outcome_path))
    artifacts.extend(str(p) for p in plots)
    manifest = {
        "experiment_id": config.experiment_id,
        "configuration_id": config.configuration_id,
        "scenario": config.scenario,
        "overall_status": status,
        "successful_receiver_rows": sum(r.execution_status == "success" for r in records),
        "failed_points": failures,
        "record_count": len(records),
        "artifacts": artifacts,
        "software": {"python": platform.python_version(), "numpy": np.__version__,
                     "scipy": scipy.__version__, "matplotlib": matplotlib.__version__},
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    artifacts.append(str(manifest_path))
    log_lines.append(f"overall_status={status}; failed_points={failures}")
    log_lines.extend(f"saved={p}" for p in artifacts)
    (output_dir / "execution_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return {**manifest, "artifacts": artifacts, "output_dir": str(output_dir)}


def run_default_suite(*, n_bits: int = 10000, repetitions: int = 2,
                      master_seed: int = 20261031,
                      output_dir: str | Path = "results/m5") -> dict[str, Any]:
    """Run one modest representative configuration for every supported scenario."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    suite_results = []
    for scenario in SUPPORTED_SCENARIOS:
        config = ExperimentConfig(
            experiment_id=f"m5_{scenario}", scenario=scenario,
            n_bits=n_bits, master_seed=master_seed, repetitions=repetitions,
            output_dir=str(root / scenario),
        )
        suite_results.append(run_experiment(config))
    suite = {
        "milestone": "M5",
        "master_seed": master_seed,
        "n_bits_per_run": n_bits,
        "repetitions": repetitions,
        "overall_status": "completed" if all(r["overall_status"] == "completed" for r in suite_results) else "partial",
        "scenarios": suite_results,
    }
    (root / "suite_manifest.json").write_text(json.dumps(suite, indent=2), encoding="utf-8")
    return suite


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Unified SignalShield experiment runner (M5).")
    parser.add_argument("--config", type=Path, help="Load a previously saved resolved JSON configuration.")
    parser.add_argument("--scenario", choices=(*SUPPORTED_SCENARIOS, "all"))
    parser.add_argument("--experiment-id")
    parser.add_argument("--n-bits", type=int)
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--ebn0-values", type=float, nargs="+")
    parser.add_argument("--values", type=float, nargs="+")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--confidence-level", type=float)
    args = parser.parse_args()

    if args.config:
        config = ExperimentConfig.load_json(args.config)
        if (args.scenario or args.experiment_id or args.n_bits is not None or args.repetitions is not None
                or args.seed is not None or args.values or args.ebn0_values
                or args.confidence_level is not None):
            parser.error("when --config is used, do not pass scenario or experiment-setting overrides")
        if args.output_dir:
            config = ExperimentConfig.from_dict({**config.to_dict(), "output_dir": str(args.output_dir)})
        result = run_experiment(config)
        print(json.dumps(result, indent=2))
        return 0 if result["overall_status"] == "completed" else 1

    if args.scenario is None:
        parser.error("select --scenario or provide --config")
    n_bits = args.n_bits if args.n_bits is not None else 10000
    repetitions = args.repetitions if args.repetitions is not None else 2
    seed = args.seed if args.seed is not None else 20261031
    outdir = args.output_dir or Path("results/m5")
    if args.scenario == "all":
        if args.values or args.ebn0_values or args.experiment_id or args.confidence_level:
            parser.error("--scenario all uses documented scenario presets; use a scenario config for custom sweeps")
        result = run_default_suite(n_bits=n_bits, repetitions=repetitions,
                                   master_seed=seed, output_dir=outdir)
        print(json.dumps(result, indent=2))
        return 0 if result["overall_status"] == "completed" else 1

    values = tuple(args.values) if args.values is not None else None
    snrs = tuple(args.ebn0_values) if args.ebn0_values is not None else None
    if values is not None and args.scenario not in DEFAULT_SWEEP_VALUES:
        parser.error("--values is only valid for interference/attenuation/frequency sweep scenarios")
    if snrs is not None and args.scenario not in DEFAULT_EBN0_VALUES:
        parser.error("--ebn0-values is only valid for AWGN reference and waveform AWGN scenarios")
    config = ExperimentConfig(
        experiment_id=args.experiment_id or f"m5_{args.scenario}_seed{seed}",
        scenario=args.scenario,
        n_bits=n_bits, master_seed=seed, repetitions=repetitions,
        ebn0_values_db=snrs, sweep_values=values,
        confidence_level=args.confidence_level if args.confidence_level is not None else 0.95,
        output_dir=str(outdir / args.scenario),
    )
    result = run_experiment(config)
    print(json.dumps(result, indent=2))
    return 0 if result["overall_status"] == "completed" else 1


def main() -> None:
    raise SystemExit(_cli())


if __name__ == "__main__":
    main()
