"""Focused M2 waveform BER experiment and numerical diagnostics."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import platform
import time

import matplotlib
import numpy as np
import scipy

from signalshield.channel import add_awgn, noise_variance_from_ebn0_db
from signalshield.config import SimulationConfig, WaveformConfig
from signalshield.experiments import derive_sweep_points
from signalshield.filters import filter_group_delay_samples, rrc_taps
from signalshield.metrics import ber_estimate, bpsk_awgn_theory
from signalshield.modulation import bpsk_modulate
from signalshield.plotting import save_ber_plot, save_m2_diagnostic_plots
from signalshield.receiver import WaveformReceiverOutput, receive_bpsk_waveform
from signalshield.signals import generate_bits
from signalshield.waveform import pulse_shape


@dataclass(frozen=True, slots=True)
class WaveformSweepPoint:
    """M2 simulation and pulse settings plus independent RNG seeds."""

    simulation: SimulationConfig
    waveform: WaveformConfig
    bit_seed: int
    noise_seed: int


@dataclass(frozen=True, slots=True)
class WaveformExperimentResult:
    """Measured performance and timing for one sampled-waveform point."""

    ebn0_db: float
    linear_ebn0: float
    noise_variance_per_sample: float
    n_bits: int
    errors: int
    ber: float
    theoretical_ber: float
    confidence_level: float
    ci_lower: float
    ci_upper: float
    zero_error_upper_95: float | None
    bit_seed: int
    noise_seed: int
    samples_per_symbol: int
    rolloff: float
    span_symbols: int
    tap_count: int
    tx_group_delay_samples: int
    rx_group_delay_samples: int
    total_decision_delay_samples: int
    max_abs_symbol_spaced_sidelobe: float
    sum_abs_symbol_spaced_sidelobes: float
    elapsed_seconds: float


def combined_symbol_response(
    taps: object,
    samples_per_symbol: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return symbol offsets and Tx/Rx cascade samples around its main tap."""
    pulse = np.asarray(taps, dtype=np.float64)
    if pulse.ndim != 1 or pulse.size == 0 or not np.all(np.isfinite(pulse)):
        raise ValueError("taps must be a nonempty finite one-dimensional array")
    if isinstance(samples_per_symbol, bool) or not isinstance(samples_per_symbol, int):
        raise TypeError("samples_per_symbol must be an integer")
    if samples_per_symbol < 1:
        raise ValueError("samples_per_symbol must be positive")
    cascade = np.convolve(pulse, pulse[::-1], mode="full")
    center = pulse.size - 1
    max_offset = min(center // samples_per_symbol, (cascade.size - 1 - center) // samples_per_symbol)
    offsets = np.arange(-max_offset, max_offset + 1, dtype=np.int64)
    samples = cascade[center + offsets * samples_per_symbol]
    return offsets, samples


def derive_waveform_sweep_points(
    *,
    n_bits: int,
    ebn0_db_values: tuple[float, ...],
    master_seed: int,
    simulation_energy: float = 1.0,
    waveform: WaveformConfig | None = None,
) -> tuple[WaveformSweepPoint, ...]:
    """Derive deterministic per-point seeds using the validated M1 policy."""
    if waveform is not None and not isinstance(waveform, WaveformConfig):
        raise TypeError("waveform must be a WaveformConfig instance")
    waveform_config = waveform if waveform is not None else WaveformConfig()
    baseline_points = derive_sweep_points(
        n_bits=n_bits,
        ebn0_db_values=ebn0_db_values,
        master_seed=master_seed,
        bit_energy=simulation_energy,
    )
    return tuple(
        WaveformSweepPoint(
            simulation=point.config,
            waveform=waveform_config,
            bit_seed=point.bit_seed,
            noise_seed=point.noise_seed,
        )
        for point in baseline_points
    )


def simulate_waveform_point(point: WaveformSweepPoint) -> WaveformExperimentResult:
    """Run pulse-shaped BPSK over iid real waveform-sample AWGN."""
    started = time.perf_counter()
    bits = generate_bits(point.simulation.n_bits, np.random.default_rng(point.bit_seed))
    symbols = bpsk_modulate(bits, point.simulation.bit_energy)
    taps = rrc_taps(
        point.waveform.rolloff,
        point.waveform.span_symbols,
        point.waveform.samples_per_symbol,
    )
    tx_waveform = pulse_shape(
        symbols,
        taps,
        samples_per_symbol=point.waveform.samples_per_symbol,
    )
    variance = noise_variance_from_ebn0_db(
        point.simulation.ebn0_db,
        point.simulation.bit_energy,
    )
    rx_waveform = add_awgn(tx_waveform, variance, np.random.default_rng(point.noise_seed))
    receiver_output = receive_bpsk_waveform(
        rx_waveform,
        taps,
        n_symbols=bits.size,
        samples_per_symbol=point.waveform.samples_per_symbol,
    )
    estimate = ber_estimate(bits, receiver_output.detected_bits)
    offsets, symbol_response = combined_symbol_response(taps, point.waveform.samples_per_symbol)
    sidelobes = np.abs(symbol_response[offsets != 0])
    tx_delay = filter_group_delay_samples(taps)
    rx_delay = filter_group_delay_samples(taps[::-1])
    elapsed = time.perf_counter() - started
    return WaveformExperimentResult(
        ebn0_db=float(point.simulation.ebn0_db),
        linear_ebn0=10.0 ** (float(point.simulation.ebn0_db) / 10.0),
        noise_variance_per_sample=variance,
        n_bits=estimate.n_bits,
        errors=estimate.errors,
        ber=estimate.ber,
        theoretical_ber=float(bpsk_awgn_theory(point.simulation.ebn0_db)),
        confidence_level=estimate.confidence_level,
        ci_lower=estimate.confidence_interval[0],
        ci_upper=estimate.confidence_interval[1],
        zero_error_upper_95=estimate.zero_error_upper_bound_95,
        bit_seed=point.bit_seed,
        noise_seed=point.noise_seed,
        samples_per_symbol=point.waveform.samples_per_symbol,
        rolloff=float(point.waveform.rolloff),
        span_symbols=point.waveform.span_symbols,
        tap_count=taps.size,
        tx_group_delay_samples=tx_delay,
        rx_group_delay_samples=rx_delay,
        total_decision_delay_samples=tx_delay + rx_delay,
        max_abs_symbol_spaced_sidelobe=float(np.max(sidelobes)) if sidelobes.size else 0.0,
        sum_abs_symbol_spaced_sidelobes=float(np.sum(sidelobes)),
        elapsed_seconds=elapsed,
    )


def run_waveform_ber_sweep(
    *,
    n_bits: int,
    ebn0_db_values: tuple[float, ...],
    master_seed: int,
    simulation_energy: float = 1.0,
    waveform: WaveformConfig | None = None,
) -> tuple[tuple[WaveformSweepPoint, ...], tuple[WaveformExperimentResult, ...]]:
    """Run fixed-size M2 points with independent reproducible streams."""
    points = derive_waveform_sweep_points(
        n_bits=n_bits,
        ebn0_db_values=ebn0_db_values,
        master_seed=master_seed,
        simulation_energy=simulation_energy,
        waveform=waveform,
    )
    return points, tuple(simulate_waveform_point(point) for point in points)


def _write_diagnostic_csv(
    path: Path,
    *,
    taps: np.ndarray,
    tx: np.ndarray,
    rx: np.ndarray,
    receiver: WaveformReceiverOutput,
    samples_per_symbol: int,
) -> tuple[Path, Path]:
    tap_path = path / "m2_rrc_taps.csv"
    tap_center = (taps.size - 1) // 2
    with tap_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("tap_index", "time_symbol_periods", "tap_value"))
        for index, value in enumerate(taps):
            writer.writerow((index, (index - tap_center) / samples_per_symbol, value))

    offsets, response = combined_symbol_response(taps, samples_per_symbol)
    response_path = path / "m2_combined_symbol_response.csv"
    with response_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("symbol_offset", "combined_response_sample"))
        writer.writerows(zip(offsets.tolist(), response.tolist(), strict=True))

    waveform_path = path / "m2_diagnostic_waveforms.csv"
    decision_map = {int(sample_index): index for index, sample_index in enumerate(receiver.sample_indices)}
    with waveform_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            (
                "sample_index",
                "time_symbol_periods",
                "tx_sample",
                "awgn_received_sample",
                "matched_filter_sample",
                "payload_decision",
                "decision_symbol_index",
            )
        )
        for index, matched_value in enumerate(receiver.filtered_samples):
            tx_value = tx[index] if index < tx.size else ""
            rx_value = rx[index] if index < rx.size else ""
            symbol_index = decision_map.get(index)
            writer.writerow(
                (
                    index,
                    index / samples_per_symbol,
                    tx_value,
                    rx_value,
                    matched_value,
                    symbol_index is not None,
                    "" if symbol_index is None else symbol_index,
                )
            )
    return tap_path, response_path, waveform_path


def write_waveform_results(
    output_dir: Path,
    *,
    points: tuple[WaveformSweepPoint, ...],
    results: tuple[WaveformExperimentResult, ...],
    master_seed: int,
    diagnostic_ebn0_db: float = 4.0,
    diagnostic_symbols: int = 16,
) -> tuple[Path, ...]:
    """Write M2 BER records, pulse diagnostics, and all requested plots."""
    if not points or len(points) != len(results):
        raise ValueError("points and results must have the same nonzero length")
    if isinstance(diagnostic_symbols, bool) or not isinstance(diagnostic_symbols, int) or diagnostic_symbols <= 0:
        raise ValueError("diagnostic_symbols must be a positive integer")
    if not np.isfinite(diagnostic_ebn0_db):
        raise ValueError("diagnostic_ebn0_db must be finite")
    output_dir.mkdir(parents=True, exist_ok=True)
    first = points[0]
    if any(point.waveform != first.waveform for point in points):
        raise ValueError("a result set must use one common waveform configuration")
    if any(point.simulation.n_bits != first.simulation.n_bits for point in points):
        raise ValueError("a fixed-size sweep must use the same bit count at each point")

    csv_path = output_dir / "m2_ber_results.csv"
    rows = [asdict(result) for result in results]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    taps = rrc_taps(
        first.waveform.rolloff,
        first.waveform.span_symbols,
        first.waveform.samples_per_symbol,
    )
    offsets, combined = combined_symbol_response(taps, first.waveform.samples_per_symbol)
    sidelobes = np.abs(combined[offsets != 0])
    point_children = np.random.SeedSequence(master_seed).spawn(len(points) + 1)
    diagnostic_bit_sequence, diagnostic_noise_sequence = point_children[-1].spawn(2)
    diagnostic_bit_seed = int(diagnostic_bit_sequence.generate_state(1, dtype=np.uint32)[0])
    diagnostic_noise_seed = int(diagnostic_noise_sequence.generate_state(1, dtype=np.uint32)[0])
    diagnostic_rng = np.random.default_rng(diagnostic_bit_seed)
    diagnostic_bits = generate_bits(diagnostic_symbols, diagnostic_rng)
    diagnostic_data = bpsk_modulate(diagnostic_bits, first.simulation.bit_energy)
    tx = pulse_shape(
        diagnostic_data,
        taps,
        samples_per_symbol=first.waveform.samples_per_symbol,
    )
    diagnostic_variance = noise_variance_from_ebn0_db(
        diagnostic_ebn0_db,
        first.simulation.bit_energy,
    )
    rx = add_awgn(tx, diagnostic_variance, np.random.default_rng(diagnostic_noise_seed))
    receiver_output = receive_bpsk_waveform(
        rx,
        taps,
        n_symbols=diagnostic_symbols,
        samples_per_symbol=first.waveform.samples_per_symbol,
    )

    diagnostic_paths = save_m2_diagnostic_plots(
        output_dir=output_dir,
        taps=taps,
        transmit_waveform=tx,
        received_waveform=rx,
        receiver_output=receiver_output,
        samples_per_symbol=first.waveform.samples_per_symbol,
        rolloff=first.waveform.rolloff,
        span_symbols=first.waveform.span_symbols,
        ebn0_db=diagnostic_ebn0_db,
    )
    ber_path = output_dir / "m2_ber_plot.png"
    save_ber_plot(
        results,  # type: ignore[arg-type] -- M2 rows expose the shared BER plot fields.
        ber_path,
        title="SignalShield M2: pulse-shaped BPSK over real AWGN",
    )
    tap_path, response_path, waveform_path = _write_diagnostic_csv(
        output_dir,
        taps=taps,
        tx=tx,
        rx=rx,
        receiver=receiver_output,
        samples_per_symbol=first.waveform.samples_per_symbol,
    )

    config_path = output_dir / "m2_experiment_config.json"
    group_delay = filter_group_delay_samples(taps)
    metadata = {
        "experiment": "M2 pulse-shaped coherent BPSK over real AWGN",
        "bit_mapping": {"0": "+sqrt(Eb)", "1": "-sqrt(Eb)"},
        "sampling": {
            "samples_per_symbol": first.waveform.samples_per_symbol,
            "span_symbols": first.waveform.span_symbols,
            "rolloff": first.waveform.rolloff,
            "tap_count": int(taps.size),
            "tap_energy": float(np.dot(taps, taps)),
            "tx_group_delay_samples": group_delay,
            "rx_group_delay_samples": group_delay,
            "total_decision_delay_samples": 2 * group_delay,
            "decision_index_rule": "2*D + k*samples_per_symbol, k=0,...,n_symbols-1",
            "convolution": "full linear convolution; no circular wrap; preserve FIR tails",
            "upsampled_length": "(n_symbols-1)*samples_per_symbol + 1",
            "transmit_waveform_length": "(n_symbols-1)*samples_per_symbol + tap_count",
        },
        "noise_model": {
            "domain": "real iid discrete waveform samples",
            "variance_per_sample": "Eb / (2 * 10**(EbN0_dB / 10))",
            "matched_filter_variance": "sample_variance * sum(receive_taps**2); equals sample_variance for unit-energy taps",
            "physical_psd_claim": False,
        },
        "ber_reference": "0.5*erfc(sqrt(Eb/N0)); finite RRC truncation adds measured residual ISI",
        "master_seed": master_seed,
        "seed_strategy": "SeedSequence(master_seed) spawns one bit/noise pair per sweep point; additional child pair is reserved for diagnostic waveforms; all derived seeds are saved.",
        "fixed_bit_count_per_snr": first.simulation.n_bits,
        "points": [
            {
                "ebn0_db": point.simulation.ebn0_db,
                "bit_energy": point.simulation.bit_energy,
                "n_bits": point.simulation.n_bits,
                "bit_seed": point.bit_seed,
                "noise_seed": point.noise_seed,
            }
            for point in points
        ],
        "diagnostics": {
            "n_symbols": diagnostic_symbols,
            "ebn0_db": diagnostic_ebn0_db,
            "bit_seed": diagnostic_bit_seed,
            "noise_seed": diagnostic_noise_seed,
            "tx_delay_samples": group_delay,
            "rx_delay_samples": group_delay,
            "total_decision_delay_samples": 2 * group_delay,
            "decision_indices": receiver_output.sample_indices.tolist(),
        },
        "combined_filter": {
            "main_sample": float(combined[offsets == 0][0]),
            "max_abs_symbol_spaced_sidelobe": float(np.max(sidelobes)) if sidelobes.size else 0.0,
            "sum_abs_symbol_spaced_sidelobes": float(np.sum(sidelobes)),
            "symbol_offsets": offsets.tolist(),
            "symbol_spaced_values": combined.tolist(),
        },
        "software": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "matplotlib": matplotlib.__version__,
        },
    }
    config_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return (csv_path, config_path, tap_path, response_path, waveform_path, ber_path, *diagnostic_paths)


def main() -> None:
    """Run the default M2 BER sweep from the command line."""
    parser = argparse.ArgumentParser(description="Run SignalShield's M2 sampled-waveform BER sweep.")
    parser.add_argument("--n-bits", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=20261028)
    parser.add_argument("--bit-energy", type=float, default=1.0)
    parser.add_argument("--ebn0-db", type=float, nargs="+", default=[0, 2, 4, 6, 8])
    parser.add_argument("--samples-per-symbol", type=int, default=8)
    parser.add_argument("--rolloff", type=float, default=0.35)
    parser.add_argument("--span-symbols", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=Path("results/m2"))
    args = parser.parse_args()

    waveform_config = WaveformConfig(
        samples_per_symbol=args.samples_per_symbol,
        rolloff=args.rolloff,
        span_symbols=args.span_symbols,
    )
    points, results = run_waveform_ber_sweep(
        n_bits=args.n_bits,
        ebn0_db_values=tuple(args.ebn0_db),
        master_seed=args.seed,
        simulation_energy=args.bit_energy,
        waveform=waveform_config,
    )
    outputs = write_waveform_results(
        args.output_dir,
        points=points,
        results=results,
        master_seed=args.seed,
    )
    for result in results:
        print(
            f"Eb/N0={result.ebn0_db:5.1f} dB  errors={result.errors:6d}/{result.n_bits}  "
            f"BER={result.ber:.8g}  theory={result.theoretical_ber:.8g}  "
            f"95% CI=[{result.ci_lower:.8g}, {result.ci_upper:.8g}]  "
            f"max_symbol_ISI={result.max_abs_symbol_spaced_sidelobe:.3e}"
        )
    for output in outputs:
        print(f"saved: {output}")


if __name__ == "__main__":
    main()

