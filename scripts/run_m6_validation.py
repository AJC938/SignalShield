"""Run the documented M6 payload and long-run integration validations."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from signalshield.application import MessageSimulationConfig, run_message_simulation  # noqa: E402
from signalshield.experiment_framework import ExperimentConfig  # noqa: E402
from signalshield.experiment_runner import run_experiment  # noqa: E402


MESSAGE = (
    "SignalShield verifies an actual UTF-8 payload through BPSK modulation, "
    "root-raised-cosine pulse shaping, a sampled channel, matched filtering, "
    "and byte reconstruction. This is a digital simulation, not a physical radio."
)


def _receiver_summary(receiver: Any) -> dict[str, Any]:
    return {
        "receiver": receiver.receiver_name,
        "bits_evaluated": receiver.estimate.n_bits,
        "errors": receiver.estimate.errors,
        "payload_ber": receiver.estimate.ber,
        "confidence_interval_95_pointwise": list(receiver.estimate.confidence_interval),
        "zero_error_upper95": receiver.estimate.zero_error_upper_bound_95,
        "decoded_text": receiver.decoded_text,
        "decode_error": receiver.decode_error,
        "exact_message_recovery": receiver.exact_message_recovery,
    }


def run_payload_case(name: str, config: MessageSimulationConfig, out_dir: Path) -> dict[str, Any]:
    result = run_message_simulation(config)
    case_dir = out_dir / name
    case_dir.mkdir(parents=True, exist_ok=True)
    receiver_rows = [_receiver_summary(item) for item in result.receiver_results.values()]
    summary: dict[str, Any] = {
        "case": name,
        "status": "completed",
        "configuration_id": result.configuration_id,
        "config": {
            "message": config.message,
            "utf8_bytes_hex": result.payload.payload_bytes.hex(),
            "payload_bit_count": int(result.payload.bits.size),
            "seed": config.seed,
            "awgn_enabled": config.awgn_enabled,
            "ebn0_db": result.channel_config.ebn0_db,
            "noise_variance": result.channel_config.noise_variance,
            "interference_enabled": config.interference_enabled,
            "interference_amplitude_peak": result.channel_config.interference_amplitude,
            "interference_frequency_cycles_per_symbol": result.channel_config.interference_frequency_cycles_per_symbol,
            "interference_phase_rad": result.channel_config.interference_phase_rad,
            "attenuation_db": result.channel_config.attenuation_db,
            "desired_voltage_gain": result.channel.applied_gain,
            "receiver": config.receiver,
            "notch_center_cycles_per_symbol": config.notch_center_cycles_per_symbol,
            "notch_quality_factor": config.notch_quality_factor,
            "samples_per_symbol": config.samples_per_symbol,
            "rolloff": config.rolloff,
            "span_symbols": config.span_symbols,
            "tx_waveform_samples": int(result.transmit_waveform.size),
            "rx_waveform_samples": int(result.channel.received.size),
        },
        "receivers": receiver_rows,
        "paired_comparison": result.comparison,
    }
    with (case_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)
    arrays: dict[str, np.ndarray] = {
        "transmitted_bits": result.payload.bits,
        "transmitted_symbols": result.symbols,
        "tx_waveform": result.transmit_waveform,
        "received_waveform": result.channel.received,
        "attenuated_signal": result.channel.attenuated_signal,
        "interference": result.channel.interference,
        "noise": result.channel.noise,
    }
    for key, value in result.receiver_results.items():
        slug = "baseline" if key == "Baseline Receiver" else "notch"
        arrays[f"{slug}_matched_filter_output"] = value.receiver_output.filtered_samples
        arrays[f"{slug}_sample_indices"] = value.receiver_output.sample_indices
        arrays[f"{slug}_decision_samples"] = value.receiver_output.decision_samples
        arrays[f"{slug}_recovered_bits"] = value.receiver_output.detected_bits
    np.savez_compressed(case_dir / "trace_arrays.npz", **arrays)

    samples = min(result.transmit_waveform.size, result.channel.received.size, 2200)
    indices = np.arange(samples)
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), constrained_layout=True)
    axes[0].plot(indices, result.transmit_waveform[:samples], label="Tx waveform")
    axes[0].set_title(f"{name}: actual transmitted pulse-shaped samples")
    axes[0].set_ylabel("Amplitude")
    axes[0].set_xlabel("Sample index")
    axes[0].grid(alpha=.25)
    axes[1].plot(indices, result.channel.received[:samples], label="Received waveform")
    if np.any(result.channel.interference[:samples]):
        axes[1].plot(indices, result.channel.interference[:samples], label="Tone component", alpha=.8)
    if np.any(result.channel.noise[:samples]):
        axes[1].plot(indices, result.channel.noise[:samples], label="AWGN component", alpha=.65)
    axes[1].set_title("Actual received waveform and channel components")
    axes[1].set_ylabel("Amplitude")
    axes[1].set_xlabel("Sample index")
    axes[1].grid(alpha=.25)
    axes[1].legend()
    receiver = next(iter(result.receiver_results.values()))
    mf = receiver.receiver_output
    shown_mf = min(mf.filtered_samples.size, samples)
    axes[2].plot(np.arange(shown_mf), mf.filtered_samples[:shown_mf], label="Matched-filter output")
    visible = mf.sample_indices < shown_mf
    axes[2].scatter(mf.sample_indices[visible], mf.decision_samples[visible],
                    marker="x", label="Decision sample")
    axes[2].set_title("Matched filter with actual symbol sampling instants")
    axes[2].set_ylabel("Amplitude")
    axes[2].set_xlabel("Sample index")
    axes[2].grid(alpha=.25)
    axes[2].legend()
    fig.savefig(case_dir / "waveform_diagnostics.png", dpi=150)
    plt.close(fig)

    for row in receiver_rows:
        row.update({"case": name, "configuration_id": result.configuration_id,
                    "seed": config.seed, "awgn_enabled": config.awgn_enabled,
                    "ebn0_db": result.channel_config.ebn0_db,
                    "interference_amplitude_peak": result.channel_config.interference_amplitude,
                    "actual_tone_frequency_cycles_per_symbol": result.channel_config.interference_frequency_cycles_per_symbol,
                    "attenuation_db": config.attenuation_db})
    return {"summary": summary, "csv_rows": receiver_rows}


def _compare_csv_rows(first: Path, second: Path, ignored: set[str]) -> tuple[bool, int]:
    with first.open(newline="", encoding="utf-8") as handle:
        left = list(csv.DictReader(handle))
    with second.open(newline="", encoding="utf-8") as handle:
        right = list(csv.DictReader(handle))
    if len(left) != len(right):
        return False, 0
    compared = 0
    for row_a, row_b in zip(left, right, strict=True):
        if row_a.keys() != row_b.keys():
            return False, compared
        for field in row_a:
            if field in ignored:
                continue
            compared += 1
            if row_a[field] != row_b[field]:
                return False, compared
    return True, compared


def run_long_experiment(out_dir: Path, n_bits: int, repetitions: int, seed: int) -> dict[str, Any]:
    primary = out_dir / "long_run_awgn"
    config = ExperimentConfig(
        experiment_id="m6_final_long_awgn_reference",
        scenario="awgn_reference",
        n_bits=n_bits,
        repetitions=repetitions,
        master_seed=seed,
        ebn0_values_db=(0.0, 4.0, 8.0),
        output_dir=str(primary),
    )
    original = run_experiment(config)
    loaded = ExperimentConfig.load_json(primary / "resolved_config.json")
    replay = ExperimentConfig.from_dict({
        **loaded.to_dict(), "output_dir": str(out_dir / "long_run_reproduction")
    })
    replay_result = run_experiment(replay)
    exact, cells = _compare_csv_rows(
        primary / "results.csv", out_dir / "long_run_reproduction" / "results.csv",
        ignored={"runtime_seconds"},
    )
    summary_exact, summary_cells = _compare_csv_rows(
        primary / "aggregate_summary.csv", out_dir / "long_run_reproduction" / "aggregate_summary.csv",
        ignored=set(),
    )
    report = {
        "scenario": "awgn_reference",
        "primary_configuration_id": original["configuration_id"],
        "replay_configuration_id": replay_result["configuration_id"],
        "primary_status": original["overall_status"],
        "replay_status": replay_result["overall_status"],
        "raw_csv_exact_match_excluding_runtime": exact,
        "raw_csv_fields_compared": cells,
        "aggregate_csv_exact_match": summary_exact,
        "aggregate_csv_fields_compared": summary_cells,
        "plot_files_regenerated": all((out_dir / "long_run_reproduction" / f).is_file()
                                       for f in ("ber_by_condition.png", "run_variability.png")),
        "config_load_and_replay": "PASS" if exact and summary_exact else "FAIL",
    }
    (out_dir / "long_run_reproducibility.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="results/m6/validation")
    parser.add_argument("--n-bits", type=int, default=50000)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261030)
    args = parser.parse_args()
    if args.n_bits < 1000 or args.repetitions < 1 or not 0 <= args.seed < 2**32:
        parser.error("require n-bits >= 1000, repetitions >= 1, and a uint32 seed")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    cases: list[tuple[str, MessageSimulationConfig]] = [
        ("clean_transmission", MessageSimulationConfig(
            message=MESSAGE, seed=101, awgn_enabled=False, interference_enabled=False,
            attenuation_db=0.0, receiver="Baseline Receiver",
        )),
        ("awgn_only_transmission", MessageSimulationConfig(
            message=MESSAGE, seed=2026, awgn_enabled=True, ebn0_db=6.0,
            interference_enabled=False, attenuation_db=0.0,
            receiver="Baseline Receiver",
        )),
        ("matched_frequency_comparison", MessageSimulationConfig(
            message=MESSAGE, seed=303, awgn_enabled=True, ebn0_db=6.0,
            interference_enabled=True, interference_amplitude_peak=0.40,
            interference_frequency_cycles_per_symbol=0.35,
            interference_phase_rad=0.37, receiver="Both (paired comparison)",
            notch_center_cycles_per_symbol=0.35, notch_quality_factor=30.0,
        )),
        ("frequency_mismatch_comparison", MessageSimulationConfig(
            message=MESSAGE, seed=404, awgn_enabled=True, ebn0_db=6.0,
            interference_enabled=True, interference_amplitude_peak=0.40,
            interference_frequency_cycles_per_symbol=0.60,
            interference_phase_rad=0.37, receiver="Both (paired comparison)",
            notch_center_cycles_per_symbol=0.35, notch_quality_factor=30.0,
        )),
        ("attenuation_without_noise", MessageSimulationConfig(
            message=MESSAGE, seed=505, awgn_enabled=False, interference_enabled=False,
            attenuation_db=6.0, receiver="Baseline Receiver",
        )),
        ("baseline_notch_same_realization", MessageSimulationConfig(
            message=MESSAGE, seed=606, awgn_enabled=True, ebn0_db=6.0,
            interference_enabled=True, interference_amplitude_peak=0.32,
            interference_frequency_cycles_per_symbol=0.35,
            interference_phase_rad=1.2, receiver="Both (paired comparison)",
            notch_center_cycles_per_symbol=0.35, notch_quality_factor=30.0,
        )),
    ]
    all_rows: list[dict[str, Any]] = []
    all_summaries = []
    for name, config in cases:
        outcome = run_payload_case(name, config, out_dir / "payload_cases")
        all_summaries.append(outcome["summary"])
        all_rows.extend(outcome["csv_rows"])

    with (out_dir / "payload_validation_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = list(dict.fromkeys(key for row in all_rows for key in row))
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)
    (out_dir / "payload_validation_summary.json").write_text(
        json.dumps(all_summaries, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    long_run = run_long_experiment(out_dir, args.n_bits, args.repetitions, args.seed)
    final = {
        "milestone": "M6",
        "status": "completed" if long_run["config_load_and_replay"] == "PASS" else "partial",
        "payload_scenarios": len(cases),
        "payload_receiver_rows": len(all_rows),
        "long_run": long_run,
        "output_dir": str(out_dir),
    }
    (out_dir / "validation_manifest.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
    print(json.dumps(final, indent=2))
    return 0 if final["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
