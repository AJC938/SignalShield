"""Shared experiment configuration, result records and run aggregation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import t

from signalshield.config import NotchConfig, WaveformConfig


SUPPORTED_SCENARIOS = (
    "awgn_reference",
    "waveform_awgn",
    "interference_amplitude",
    "interference_frequency",
    "attenuation",
    "receiver_comparison",
    "frequency_mismatch",
)

DEFAULT_EBN0_VALUES = {
    "awgn_reference": (0.0, 2.0, 4.0, 6.0, 8.0),
    "waveform_awgn": (2.0, 4.0, 6.0, 8.0),
}
DEFAULT_SWEEP_VALUES = {
    "interference_amplitude": (0.0, 0.08, 0.16, 0.22, 0.30, 0.42),
    "interference_frequency": (0.15, 0.35, 0.70, 1.10, 1.60),
    "attenuation": (0.0, 2.0, 4.0, 6.0, 8.0),
    "frequency_mismatch": (0.31, 0.33, 0.34, 0.35, 0.36, 0.37, 0.39),
}


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """Validated immutable configuration for a supported SignalShield study."""

    experiment_id: str
    scenario: str
    n_bits: int = 10000
    master_seed: int = 20261031
    repetitions: int = 2
    ebn0_db: float = 6.0
    ebn0_values_db: tuple[float, ...] | None = None
    sweep_values: tuple[float, ...] | None = None
    samples_per_symbol: int = 8
    rolloff: float = 0.35
    span_symbols: int = 10
    attenuation_db: float = 0.0
    interference_amplitude: float = 0.22
    interference_frequency_cycles_per_symbol: float = 0.35
    interference_phase_rad: float = 0.37
    notch_center_cycles_per_symbol: float = 0.35
    notch_quality_factor: float = 30.0
    confidence_level: float = 0.95
    bootstrap_block_length: int = 50
    alternate_block_length: int = 100
    bootstrap_replicates: int = 1000
    save_paired_outcomes: bool = True
    output_dir: str = "results/m5"

    def __post_init__(self) -> None:
        if not isinstance(self.experiment_id, str) or not self.experiment_id.strip():
            raise ValueError("experiment_id must be a nonempty string")
        if self.scenario not in SUPPORTED_SCENARIOS:
            raise ValueError(f"scenario must be one of: {', '.join(SUPPORTED_SCENARIOS)}")
        for name, value in (("n_bits", self.n_bits), ("repetitions", self.repetitions),
                            ("master_seed", self.master_seed), ("samples_per_symbol", self.samples_per_symbol),
                            ("span_symbols", self.span_symbols), ("bootstrap_block_length", self.bootstrap_block_length),
                            ("alternate_block_length", self.alternate_block_length),
                            ("bootstrap_replicates", self.bootstrap_replicates)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
        if self.n_bits <= 0 or self.repetitions <= 0:
            raise ValueError("n_bits and repetitions must be positive")
        if not 0 <= self.master_seed < 2**32:
            raise ValueError("master_seed must be in [0, 2**32-1]")
        if self.bootstrap_block_length <= 0 or self.alternate_block_length <= 0:
            raise ValueError("bootstrap block lengths must be positive")
        if self.bootstrap_block_length == self.alternate_block_length:
            raise ValueError("primary and alternate bootstrap block lengths must differ")
        if self.bootstrap_replicates < 100:
            raise ValueError("bootstrap_replicates must be at least 100")
        if not isinstance(self.save_paired_outcomes, bool):
            raise TypeError("save_paired_outcomes must be a boolean")
        if not isinstance(self.output_dir, str) or not self.output_dir.strip():
            raise ValueError("output_dir must be a nonempty path")
        for name, value in (
            ("ebn0_db", self.ebn0_db), ("rolloff", self.rolloff),
            ("attenuation_db", self.attenuation_db),
            ("interference_amplitude", self.interference_amplitude),
            ("interference_frequency_cycles_per_symbol", self.interference_frequency_cycles_per_symbol),
            ("interference_phase_rad", self.interference_phase_rad),
            ("notch_center_cycles_per_symbol", self.notch_center_cycles_per_symbol),
            ("notch_quality_factor", self.notch_quality_factor),
            ("confidence_level", self.confidence_level),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a real number")
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if not 0.0 < self.confidence_level < 1.0:
            raise ValueError("confidence_level must be strictly between 0 and 1")
        if not -100.0 <= self.ebn0_db <= 300.0:
            raise ValueError("ebn0_db must be in [-100, 300] dB")
        if self.attenuation_db < 0.0 or self.interference_amplitude < 0.0:
            raise ValueError("attenuation_db and interference_amplitude must be nonnegative")
        WaveformConfig(self.samples_per_symbol, self.rolloff, self.span_symbols)
        NotchConfig(self.notch_center_cycles_per_symbol, self.samples_per_symbol,
                    self.notch_quality_factor)
        if self.ebn0_values_db is None:
            values = DEFAULT_EBN0_VALUES.get(self.scenario, (float(self.ebn0_db),))
            object.__setattr__(self, "ebn0_values_db", values)
        elif not isinstance(self.ebn0_values_db, tuple) or not self.ebn0_values_db:
            raise ValueError("ebn0_values_db must be a nonempty tuple when supplied")
        if self.sweep_values is None:
            values = DEFAULT_SWEEP_VALUES.get(self.scenario, ())
            object.__setattr__(self, "sweep_values", values)
        elif not isinstance(self.sweep_values, tuple):
            raise TypeError("sweep_values must be a tuple when supplied")
        elif not self.sweep_values and self.scenario in DEFAULT_SWEEP_VALUES:
            raise ValueError("sweep_values must not be empty for a sweep scenario")
        for name, values in (("ebn0_values_db", self.ebn0_values_db),
                             ("sweep_values", self.sweep_values)):
            for value in values:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"{name} values must be finite real numbers")
        for value in self.ebn0_values_db:
            if not -100.0 <= value <= 300.0:
                raise ValueError("Eb/N0 sweep values must be in [-100, 300] dB")
        if self.scenario == "interference_amplitude" and any(v < 0.0 for v in self.sweep_values):
            raise ValueError("interference amplitude sweep values must be nonnegative")
        if self.scenario in ("interference_frequency", "frequency_mismatch"):
            if any(not 0.0 < v < self.samples_per_symbol / 2.0 for v in self.sweep_values):
                raise ValueError("frequency sweep values must satisfy 0 < f < sps/2 cycles/symbol")
        if self.scenario == "attenuation" and any(v < 0.0 for v in self.sweep_values):
            raise ValueError("attenuation sweep values must be nonnegative")
        if self.scenario == "frequency_mismatch" and any(
            abs(v - self.notch_center_cycles_per_symbol) >= self.samples_per_symbol / 2.0
            for v in self.sweep_values
        ):
            raise ValueError("mismatch frequencies must remain inside the configured Nyquist band")

    @property
    def waveform_config(self) -> WaveformConfig:
        return WaveformConfig(self.samples_per_symbol, self.rolloff, self.span_symbols)

    @property
    def notch_config(self) -> NotchConfig:
        return NotchConfig(self.notch_center_cycles_per_symbol, self.samples_per_symbol,
                           self.notch_quality_factor)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["ebn0_values_db"] = list(self.ebn0_values_db)
        result["sweep_values"] = list(self.sweep_values)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentConfig":
        if not isinstance(data, dict):
            raise TypeError("experiment configuration must be a JSON object")
        allowed = set(cls.__dataclass_fields__)
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"unknown experiment configuration fields: {', '.join(sorted(unknown))}")
        payload = dict(data)
        for name in ("ebn0_values_db", "sweep_values"):
            if name in payload and payload[name] is not None:
                if not isinstance(payload[name], list):
                    raise TypeError(f"{name} in JSON must be an array")
                payload[name] = tuple(payload[name])
        return cls(**payload)

    @classmethod
    def load_json(cls, path: str | Path) -> "ExperimentConfig":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read experiment configuration {path}: {exc}") from exc
        return cls.from_dict(data)

    def save_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @property
    def configuration_id(self) -> str:
        """Stable semantic identifier; output location does not affect the ID."""
        payload = self.to_dict()
        payload.pop("output_dir", None)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class ExperimentRecord:
    """One receiver measurement for one point and repetition."""

    experiment_id: str
    configuration_id: str
    scenario: str
    scenario_point_index: int
    scenario_parameter: str
    scenario_value: float | None
    repetition: int
    receiver_id: str
    master_seed: int
    bit_seed: int | None
    noise_seed: int | None
    bootstrap_seed: int | None
    n_bits: int | None
    errors: int | None
    ber: float | None
    confidence_level: float
    ci_lower: float | None
    ci_upper: float | None
    zero_error_upper95: float | None
    familywise_confidence_level: float
    familywise_ci_lower: float | None
    familywise_ci_upper: float | None
    ebn0_db: float | None
    effective_ebn0_db: float | None
    samples_per_symbol: int
    rolloff: float | None
    span_symbols: int | None
    attenuation_db: float | None
    desired_gain: float | None
    interference_amplitude_peak: float | None
    interference_frequency_cycles_per_symbol: float | None
    interference_phase_rad: float | None
    noise_variance_configured: float | None
    noise_variance_measured: float | None
    transmit_record_mean_square_power: float | None
    interference_record_mean_square_power: float | None
    interference_to_desired_power_ratio: float | None
    received_record_mean_square_power: float | None
    notch_center_cycles_per_symbol: float | None
    notch_quality_factor: float | None
    theoretical_ber: float | None
    theoretical_reference_applicable: bool
    theory_note: str
    paired_ber_difference: float | None
    paired_block_ci_lower: float | None
    paired_block_ci_upper: float | None
    paired_alternate_ci_lower: float | None
    paired_alternate_ci_upper: float | None
    paired_corrected_errors: int | None
    paired_introduced_errors: int | None
    paired_shared_errors: int | None
    paired_unchanged_decisions: int | None
    paired_mcnemar_p_value: float | None
    paired_mcnemar_underflow: bool | None
    runtime_seconds: float | None
    execution_status: str
    failure_note: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def derive_seed(master_seed: int, experiment_id: str, repetition: int,
                role: str, condition_key: str = "shared") -> int:
    """Stable 32-bit seed independent of scenario execution order."""
    identity = f"{master_seed}|{experiment_id}|rep={repetition}|{role}|condition={condition_key}"
    return int.from_bytes(hashlib.sha256(identity.encode("utf-8")).digest()[:4], "big")


def aggregate_run_records(records: list[ExperimentRecord], confidence_level: float) -> list[dict[str, Any]]:
    """Summarize run-to-run BER variability without discarding individual runs."""
    groups: dict[tuple[str, int, str], list[ExperimentRecord]] = {}
    for record in records:
        if record.execution_status != "success" or record.ber is None:
            continue
        groups.setdefault((record.scenario, record.scenario_point_index, record.receiver_id), []).append(record)
    summaries: list[dict[str, Any]] = []
    for (scenario, point_index, receiver), group in sorted(groups.items()):
        rates = np.asarray([r.ber for r in group], dtype=np.float64)
        mean = float(np.mean(rates))
        std = float(np.std(rates, ddof=1)) if rates.size > 1 else None
        if rates.size > 1:
            half = float(t.ppf((1.0 + confidence_level) / 2.0, df=rates.size - 1) * std / math.sqrt(rates.size))
            mean_low, mean_high = max(0.0, mean-half), min(1.0, mean+half)
        else:
            mean_low = mean_high = None
        summaries.append({
            "scenario": scenario,
            "scenario_point_index": point_index,
            "scenario_parameter": group[0].scenario_parameter,
            "scenario_value": group[0].scenario_value,
            "receiver_id": receiver,
            "n_repetitions": int(rates.size),
            "mean_run_ber": mean,
            "between_run_ber_standard_deviation": std,
            "mean_run_ber_t_ci_lower": mean_low,
            "mean_run_ber_t_ci_upper": mean_high,
            "mean_errors_per_run": float(np.mean([r.errors for r in group])),
            "bits_per_run": group[0].n_bits,
            "per_run_binomial_intervals_retained_in_results_csv": True,
        })
    return summaries


def aggregate_paired_records(records: list[ExperimentRecord], confidence_level: float) -> list[dict[str, Any]]:
    """Summarize paired BER differences across independent repetitions."""
    groups: dict[tuple[str, int], list[ExperimentRecord]] = {}
    for r in records:
        if r.execution_status == "success" and r.paired_ber_difference is not None and r.receiver_id == "baseline_m2":
            groups.setdefault((r.scenario, r.scenario_point_index), []).append(r)
    summaries: list[dict[str, Any]] = []
    for (scenario, point_index), group in sorted(groups.items()):
        values = np.asarray([r.paired_ber_difference for r in group], dtype=np.float64)
        mean = float(np.mean(values))
        std = float(np.std(values, ddof=1)) if values.size > 1 else None
        if values.size > 1:
            half = float(t.ppf((1.0 + confidence_level) / 2.0, df=values.size - 1) * std / math.sqrt(values.size))
            low, high = mean-half, mean+half
        else:
            low = high = None
        summaries.append({
            "scenario": scenario,
            "scenario_point_index": point_index,
            "scenario_parameter": group[0].scenario_parameter,
            "scenario_value": group[0].scenario_value,
            "n_repetitions": int(values.size),
            "mean_paired_delta_candidate_minus_baseline": mean,
            "between_run_delta_standard_deviation": std,
            "mean_delta_t_ci_lower": low,
            "mean_delta_t_ci_upper": high,
        })
    return summaries
