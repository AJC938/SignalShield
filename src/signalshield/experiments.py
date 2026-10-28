"""Reproducible M1 BER sweep, artifact writing, and command-line entry point."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from importlib.metadata import version
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy

from signalshield.channel import add_awgn, noise_variance_from_ebn0_db
from signalshield.config import SimulationConfig
from signalshield.metrics import BerEstimate, ber_estimate, bpsk_awgn_theory
from signalshield.modulation import bpsk_modulate
from signalshield.plotting import save_ber_plot
from signalshield.receiver import detect_bpsk
from signalshield.signals import generate_bits


@dataclass(frozen=True, slots=True)
class SweepPoint:
    """One simulated SNR point and the seeds needed to reproduce it."""

    config: SimulationConfig
    bit_seed: int
    noise_seed: int


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    """Measurements from one actual BPSK/AWGN run."""

    ebn0_db: float
    linear_ebn0: float
    noise_variance: float
    bit_seed: int
    noise_seed: int
    n_bits: int
    errors: int
    ber: float
    theoretical_ber: float
    confidence_level: float
    ci_lower: float
    ci_upper: float
    zero_error_upper_95: float | None
    elapsed_seconds: float


def derive_sweep_points(
    *,
    n_bits: int,
    ebn0_db_values: tuple[float, ...],
    master_seed: int,
    bit_energy: float = 1.0,
) -> tuple[SweepPoint, ...]:
    """Create distinct, deterministic bit/noise seeds per sweep point."""
    if not ebn0_db_values:
        raise ValueError("ebn0_db_values must not be empty")
    if isinstance(master_seed, bool) or not isinstance(master_seed, int):
        raise TypeError("master_seed must be an integer")
    if master_seed < 0 or master_seed >= 2**32:
        raise ValueError("master_seed must be in the range [0, 2**32 - 1]")
    root_sequence = np.random.SeedSequence(master_seed)
    children = root_sequence.spawn(len(ebn0_db_values))
    points: list[SweepPoint] = []
    for ebn0_db, child in zip(ebn0_db_values, children, strict=True):
        bit_sequence, noise_sequence = child.spawn(2)
        bit_seed = int(bit_sequence.generate_state(1, dtype=np.uint32)[0])
        noise_seed = int(noise_sequence.generate_state(1, dtype=np.uint32)[0])
        points.append(
            SweepPoint(
                config=SimulationConfig(n_bits, float(ebn0_db), noise_seed, bit_energy),
                bit_seed=bit_seed,
                noise_seed=noise_seed,
            )
        )
    return tuple(points)


def simulate_point(point: SweepPoint) -> ExperimentResult:
    """Run one reference-model point using distinct explicit RNG streams."""
    started = time.perf_counter()
    bits = generate_bits(point.config.n_bits, np.random.default_rng(point.bit_seed))
    symbols = bpsk_modulate(bits, point.config.bit_energy)
    variance = noise_variance_from_ebn0_db(point.config.ebn0_db, point.config.bit_energy)
    received = add_awgn(symbols, variance, np.random.default_rng(point.noise_seed))
    detected = detect_bpsk(received)
    estimate: BerEstimate = ber_estimate(bits, detected)
    elapsed = time.perf_counter() - started
    return ExperimentResult(
        ebn0_db=float(point.config.ebn0_db),
        linear_ebn0=10.0 ** (float(point.config.ebn0_db) / 10.0),
        noise_variance=variance,
        bit_seed=point.bit_seed,
        noise_seed=point.noise_seed,
        n_bits=estimate.n_bits,
        errors=estimate.errors,
        ber=estimate.ber,
        theoretical_ber=float(bpsk_awgn_theory(point.config.ebn0_db)),
        confidence_level=estimate.confidence_level,
        ci_lower=estimate.confidence_interval[0],
        ci_upper=estimate.confidence_interval[1],
        zero_error_upper_95=estimate.zero_error_upper_bound_95,
        elapsed_seconds=elapsed,
    )


def run_ber_sweep(
    *,
    n_bits: int,
    ebn0_db_values: tuple[float, ...],
    master_seed: int,
    bit_energy: float = 1.0,
) -> tuple[tuple[SweepPoint, ...], tuple[ExperimentResult, ...]]:
    """Run a fixed-size BER sweep with deterministic independent streams."""
    points = derive_sweep_points(
        n_bits=n_bits,
        ebn0_db_values=ebn0_db_values,
        master_seed=master_seed,
        bit_energy=bit_energy,
    )
    return points, tuple(simulate_point(point) for point in points)


def write_results(
    output_dir: Path,
    *,
    points: tuple[SweepPoint, ...],
    results: tuple[ExperimentResult, ...],
    master_seed: int,
) -> tuple[Path, Path, Path]:
    """Write CSV, JSON run metadata, and a BER plot to a result directory."""
    if len(points) != len(results) or not results:
        raise ValueError("points and results must have the same nonzero length")
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "m1_ber_results.csv"
    json_path = output_dir / "m1_experiment_config.json"
    plot_path = output_dir / "m1_ber_plot.png"

    rows = [asdict(result) for result in results]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    metadata = {
        "experiment": "M1 coherent BPSK over real AWGN",
        "model": "one real sample per bit; Eb = configured bit_energy",
        "mapping": {"0": "+sqrt(Eb)", "1": "-sqrt(Eb)"},
        "noise_variance": "Eb / (2 * 10**(EbN0_dB / 10))",
        "master_seed": master_seed,
        "seed_strategy": (
            "NumPy SeedSequence(master_seed) spawns one child per SNR; each child "
            "spawns independent bit and noise streams. Derived uint32 seeds are saved per row."
        ),
        "stopping_rule": "Fixed configured bit count at every SNR; no adaptive stopping.",
        "points": [
            {
                "ebn0_db": point.config.ebn0_db,
                "bit_energy": point.config.bit_energy,
                "n_bits": point.config.n_bits,
                "bit_seed": point.bit_seed,
                "noise_seed": point.noise_seed,
            }
            for point in points
        ],
        "software": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
                "matplotlib": version("matplotlib"),
        },
    }
    json_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    save_ber_plot(results, plot_path)
    return csv_path, json_path, plot_path


def main() -> None:
    """Run the M1 BER sweep from the console."""
    parser = argparse.ArgumentParser(description="Run SignalShield's M1 BPSK/AWGN BER sweep.")
    parser.add_argument("--n-bits", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=20261027)
    parser.add_argument("--bit-energy", type=float, default=1.0)
    parser.add_argument("--ebn0-db", type=float, nargs="+", default=[0, 2, 4, 6, 8, 10])
    parser.add_argument("--output-dir", type=Path, default=Path("results/m1"))
    args = parser.parse_args()

    points, results = run_ber_sweep(
        n_bits=args.n_bits,
        ebn0_db_values=tuple(args.ebn0_db),
        master_seed=args.seed,
        bit_energy=args.bit_energy,
    )
    paths = write_results(args.output_dir, points=points, results=results, master_seed=args.seed)
    for result in results:
        print(
            f"Eb/N0={result.ebn0_db:5.1f} dB  errors={result.errors:6d}/{result.n_bits}  "
            f"BER={result.ber:.8g}  theory={result.theoretical_ber:.8g}  "
            f"95% CI=[{result.ci_lower:.8g}, {result.ci_upper:.8g}]"
        )
    for path in paths:
        print(f"saved: {path}")


if __name__ == "__main__":
    main()

