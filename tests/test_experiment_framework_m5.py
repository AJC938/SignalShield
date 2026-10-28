import csv
import json

import numpy as np
import pytest

from signalshield.experiment_framework import (
    ExperimentConfig,
    aggregate_paired_records,
    derive_seed,
)
from signalshield.experiment_runner import run_experiment
from signalshield.metrics import ber_estimate, paired_ber_estimate


def _config(tmp_path, scenario="awgn_reference", **kwargs):
    base = {
        "experiment_id": f"test_{scenario}",
        "scenario": scenario,
        "n_bits": 400,
        "master_seed": 111,
        "repetitions": 1,
        "bootstrap_replicates": 100,
        "output_dir": str(tmp_path / scenario),
    }
    if scenario in ("awgn_reference", "waveform_awgn"):
        base["ebn0_values_db"] = (4.0,)
    if scenario == "interference_amplitude":
        base["sweep_values"] = (0.0, 0.22)
    if scenario == "interference_frequency":
        base["sweep_values"] = (0.35, 0.4)
    if scenario == "attenuation":
        base["sweep_values"] = (0.0, 2.0)
    if scenario == "frequency_mismatch":
        base["sweep_values"] = (0.34, 0.35, 0.36)
    base.update(kwargs)
    return ExperimentConfig(**base)


def test_config_json_roundtrip_and_stable_identity_ignores_output_path(tmp_path):
    config = ExperimentConfig(
        experiment_id="roundtrip", scenario="receiver_comparison",
        n_bits=1234, repetitions=3, output_dir=str(tmp_path / "a"),
    )
    path = tmp_path / "resolved.json"
    config.save_json(path)
    restored = ExperimentConfig.load_json(path)
    assert restored == config
    moved = ExperimentConfig.from_dict({**config.to_dict(), "output_dir": str(tmp_path / "b")})
    assert moved.configuration_id == config.configuration_id
    assert restored.configuration_id == config.configuration_id


def test_config_rejects_missing_unknown_invalid_and_empty_sweep_values(tmp_path):
    with pytest.raises(TypeError):
        ExperimentConfig.from_dict({"scenario": "awgn_reference"})
    with pytest.raises(ValueError, match="unknown"):
        ExperimentConfig.from_dict({"experiment_id": "x", "scenario": "awgn_reference", "extra": 2})
    with pytest.raises(ValueError, match="confidence"):
        ExperimentConfig("bad", "awgn_reference", confidence_level=1.0)
    with pytest.raises(ValueError, match="not be empty"):
        ExperimentConfig("bad", "interference_amplitude", sweep_values=())
    with pytest.raises(ValueError, match="cycles/symbol"):
        ExperimentConfig("bad", "interference_frequency", sweep_values=(4.0,))


def test_seed_derivation_is_order_independent_and_role_specific():
    bit_seed = derive_seed(99, "experiment", 2, "bits")
    noise_seed = derive_seed(99, "experiment", 2, "noise")
    assert bit_seed == derive_seed(99, "experiment", 2, "bits")
    assert bit_seed != noise_seed
    assert bit_seed != derive_seed(99, "experiment", 3, "bits")
    assert bit_seed != derive_seed(99, "other_experiment", 2, "bits")


def test_ber_interval_edge_cases_and_validation():
    zero = ber_estimate(np.zeros(100, dtype=np.uint8), np.zeros(100, dtype=np.uint8))
    assert zero.errors == 0 and zero.ber == 0
    assert zero.zero_error_upper_bound_95 is not None
    assert zero.confidence_interval[1] > zero.zero_error_upper_bound_95
    all_bad = ber_estimate(np.zeros(20, dtype=np.uint8), np.ones(20, dtype=np.uint8))
    assert all_bad.errors == 20 and all_bad.ber == 1.0
    assert all_bad.confidence_interval[1] == 1.0
    with pytest.raises(ValueError):
        ber_estimate(np.zeros(3), np.zeros(2))
    with pytest.raises(ValueError):
        ber_estimate(np.zeros(3), np.zeros(3), confidence_level=1.0)


def test_paired_metrics_counts_intervals_and_reproducibility():
    sent = np.array([0, 0, 1, 1, 0, 1, 0, 1], dtype=np.uint8)
    base = np.array([1, 0, 0, 1, 0, 1, 1, 1], dtype=np.uint8)
    cand = np.array([0, 1, 0, 1, 1, 1, 0, 1], dtype=np.uint8)
    first = paired_ber_estimate(sent, base, cand, block_lengths=(2, 4),
                                bootstrap_replicates=200, bootstrap_seed=78)
    second = paired_ber_estimate(sent, base, cand, block_lengths=(2, 4),
                                 bootstrap_replicates=200, bootstrap_seed=78)
    assert first.baseline.errors == 3
    assert first.candidate.errors == 3
    assert first.corrected_errors == 2
    assert first.introduced_errors == 2
    assert first.shared_errors == 1
    assert first.unchanged_decisions == 4
    assert first.difference_candidate_minus_baseline == 0.0
    assert first.block_confidence_intervals == second.block_confidence_intervals
    assert set(first.block_confidence_intervals) == {2, 4}
    with pytest.raises(ValueError):
        paired_ber_estimate(sent, base, cand, block_lengths=(4, 4))
    with pytest.raises(ValueError):
        paired_ber_estimate(sent, base[:-1], cand)


@pytest.mark.parametrize("scenario", [
    "awgn_reference", "waveform_awgn", "interference_amplitude",
    "interference_frequency", "attenuation", "receiver_comparison", "frequency_mismatch",
])
def test_runner_dispatches_every_supported_scenario_and_writes_schema(tmp_path, scenario):
    config = _config(tmp_path, scenario)
    result = run_experiment(config)
    assert result["overall_status"] == "completed"
    output = tmp_path / scenario
    rows = list(csv.DictReader((output / "results.csv").open(encoding="utf-8")))
    assert rows
    assert {row["execution_status"] for row in rows} == {"success"}
    assert all(int(row["n_bits"]) == config.n_bits for row in rows)
    assert all(int(row["errors"]) >= 0 for row in rows)
    for row in rows:
        assert float(row["ber"]) == int(row["errors"]) / int(row["n_bits"])
        assert row["configuration_id"] == config.configuration_id
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["overall_status"] == "completed"
    assert (output / "aggregate_summary.csv").exists()
    if scenario in ("receiver_comparison", "frequency_mismatch"):
        assert {row["receiver_id"] for row in rows} == {"baseline_m2", "notch_m2"}
        assert rows[0]["paired_ber_difference"] != ""
    if scenario == "receiver_comparison":
        assert (output / "paired_per_bit_outcomes.csv").exists()


def test_runner_reproduction_matches_raw_results_excluding_runtime(tmp_path):
    config_a = _config(tmp_path, "interference_amplitude", experiment_id="replicate")
    result_a = run_experiment(config_a)
    config_b = ExperimentConfig.from_dict({
        **config_a.to_dict(), "output_dir": str(tmp_path / "reproduction")
    })
    result_b = run_experiment(config_b)
    assert result_a["configuration_id"] == result_b["configuration_id"]
    rows_a = list(csv.DictReader((tmp_path / "interference_amplitude" / "results.csv").open()))
    rows_b = list(csv.DictReader((tmp_path / "reproduction" / "results.csv").open()))
    for a, b in zip(rows_a, rows_b, strict=True):
        a.pop("runtime_seconds", None)
        b.pop("runtime_seconds", None)
        assert a == b


def test_runner_records_failures_instead_of_success(monkeypatch, tmp_path):
    import signalshield.experiment_runner as runner

    def fail(*args, **kwargs):
        raise RuntimeError("injected scenario failure")

    monkeypatch.setattr(runner, "_execute_point", fail)
    result = runner.run_experiment(_config(tmp_path, "awgn_reference"))
    assert result["overall_status"] == "failed"
    rows = list(csv.DictReader((tmp_path / "awgn_reference" / "results.csv").open()))
    assert rows[0]["execution_status"] == "failed"
    assert "injected scenario failure" in rows[0]["failure_note"]

