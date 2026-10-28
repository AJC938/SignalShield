"""Focused reproducible experiments for the M3 configurable channel."""

from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import time
from dataclasses import asdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import scipy

from signalshield.channel import (
    ChannelConfig,
    apply_configured_channel,
    mean_square_power,
    noise_variance_from_ebn0_db,
)
from signalshield.filters import rrc_taps
from signalshield.metrics import ber_estimate, bpsk_awgn_theory
from signalshield.modulation import bpsk_modulate
from signalshield.receiver import receive_bpsk_waveform
from signalshield.signals import generate_bits
from signalshield.waveform import pulse_shape


def _row(bits: np.ndarray, detected: np.ndarray, *, config: ChannelConfig, tx: np.ndarray,
         output: object, bit_seed: int, noise_seed: int, experiment: str) -> dict[str, object]:
    estimate = ber_estimate(bits, detected)
    tx_power = mean_square_power(tx)
    wanted_power = mean_square_power(output.attenuated_signal)
    interference_power = mean_square_power(output.interference)
    noise_variance = float(np.var(output.noise, ddof=1)) if output.noise.size > 1 else 0.0
    ratio = interference_power / wanted_power if wanted_power > 0.0 else None
    effective_db = None if config.ebn0_db is None else config.ebn0_db - config.attenuation_db
    theory = None
    if effective_db is not None and config.interference_amplitude == 0.0:
        theory = bpsk_awgn_theory(effective_db)
    return {
        "experiment": experiment,
        "bit_seed": bit_seed,
        "noise_seed": noise_seed,
        "n_bits": estimate.n_bits,
        "errors": estimate.errors,
        "ber": estimate.ber,
        "ci95_lower": estimate.confidence_interval[0],
        "ci95_upper": estimate.confidence_interval[1],
        "zero_error_upper95": estimate.zero_error_upper_bound_95,
        "ebn0_db": config.ebn0_db,
        "effective_ebn0_db": effective_db,
        "theoretical_ber": theory,
        "attenuation_db": config.attenuation_db,
        "gain": config.desired_gain,
        "interference_amplitude_peak": config.interference_amplitude,
        "interference_frequency_cycles_per_symbol": config.interference_frequency_cycles_per_symbol,
        "interference_phase_rad": config.interference_phase_rad,
        "noise_variance_configured": config.noise_variance,
        "noise_variance_measured": noise_variance,
        "tx_record_mean_square_power": tx_power,
        "attenuated_desired_record_power": wanted_power,
        "interference_record_mean_square_power": interference_power,
        "interference_to_attenuated_signal_power_ratio": ratio,
        "received_record_mean_square_power": mean_square_power(output.received),
    }


def _run_case(bits: np.ndarray, tx: np.ndarray, taps: np.ndarray, config: ChannelConfig,
              *, bit_seed: int, noise_seed: int, experiment: str) -> tuple[dict[str, object], object, np.ndarray]:
    output = apply_configured_channel(tx, config, rng=np.random.default_rng(noise_seed))
    rx = receive_bpsk_waveform(output.received, taps, n_symbols=bits.size,
                               samples_per_symbol=config.samples_per_symbol)
    return _row(bits, rx.detected_bits, config=config, tx=tx, output=output,
                bit_seed=bit_seed, noise_seed=noise_seed, experiment=experiment), output, rx.detected_bits


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty experiment")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _plot_sweeps(out: Path, baseline: list[dict[str, object]], amplitude: list[dict[str, object]],
                 frequency: list[dict[str, object]], attenuation: list[dict[str, object]]) -> list[Path]:
    outputs: list[Path] = []

    def plot_ber(rows: list[dict[str, object]], xkey: str, xlabel: str, filename: str,
                 title: str, theories: bool = False) -> None:
        fig, ax = plt.subplots(figsize=(8.3, 5.2), constrained_layout=True)
        valid = [row for row in rows if row["ber"] > 0]
        if valid:
            xs = [float(row[xkey]) for row in valid]
            ys = [float(row["ber"]) for row in valid]
            lows = [max(0.0, ys[i] - float(valid[i]["ci95_lower"])) for i in range(len(valid))]
            highs = [max(0.0, float(valid[i]["ci95_upper"]) - ys[i]) for i in range(len(valid))]
            ax.errorbar(xs, ys, yerr=[lows, highs], fmt="o-", capsize=3, label="Measured BER (95% exact CI)")
        zeros = [row for row in rows if row["ber"] == 0 and row["zero_error_upper95"] is not None]
        for i, row in enumerate(zeros):
            ax.scatter(float(row[xkey]), float(row["zero_error_upper95"]), marker="v", color="tab:red",
                       label="0 errors: 95% upper bound" if i == 0 else None)
        if theories:
            th = [row for row in rows if row["theoretical_ber"] is not None]
            ax.plot([float(row[xkey]) for row in th], [float(row["theoretical_ber"]) for row in th],
                    "k--", label="Coherent BPSK/AWGN theory (effective Eb/N0)")
        ax.set_yscale("log")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("Bit error rate")
        ax.set_title(title)
        ax.grid(True, which="both", alpha=.3)
        ax.legend()
        path = out / filename
        fig.savefig(path, dpi=160)
        plt.close(fig)
        outputs.append(path)

    plot_ber(baseline, "ebn0_db", "Configured Eb/N0 (dB)", "m3_awgn_baseline_ber.png",
             "M3 reference: sampled BPSK with AWGN only", theories=True)
    plot_ber(amplitude, "interference_amplitude_peak", "Interference peak amplitude (normalized units)",
             "m3_ber_vs_interference_amplitude.png", "BER versus sinusoidal interference amplitude")
    plot_ber(frequency, "interference_frequency_cycles_per_symbol", "Interference frequency (cycles/symbol)",
             "m3_ber_vs_interference_frequency.png", "BER versus sinusoidal interference frequency")
    plot_ber(attenuation, "attenuation_db", "Desired-signal attenuation (dB)",
             "m3_ber_vs_attenuation.png", "Attenuation shifts effective Eb/N0 when noise is fixed", theories=True)
    return outputs


def run_m3_experiments(*, n_bits: int = 30000, master_seed: int = 20261029,
                       output_dir: Path = Path("results/m3")) -> list[Path]:
    """Run predefined M3 AWGN, tone, attenuation and combined-channel studies."""
    if isinstance(n_bits, bool) or not isinstance(n_bits, int) or n_bits < 1000:
        raise ValueError("n_bits must be an integer of at least 1000")
    if isinstance(master_seed, bool) or not isinstance(master_seed, int) or master_seed < 0:
        raise ValueError("master_seed must be a nonnegative integer")
    output_dir.mkdir(parents=True, exist_ok=True)
    sps, rolloff, span, eb = 8, 0.35, 10, 6.0
    taps = rrc_taps(rolloff, span, sps)
    seed_children = np.random.SeedSequence(master_seed).spawn(2)
    bit_seed = int(seed_children[0].generate_state(1, dtype=np.uint32)[0])
    noise_root = seed_children[1]
    bits = generate_bits(n_bits, np.random.default_rng(bit_seed))
    tx = pulse_shape(bpsk_modulate(bits), taps, samples_per_symbol=sps)
    noise_seeds = [int(child.generate_state(1, dtype=np.uint32)[0]) for child in noise_root.spawn(32)]
    index = 0

    # Experiment 1: same fixed payload and independently seeded noise per Eb/N0 point.
    baseline: list[dict[str, object]] = []
    for snr in (0.0, 2.0, 4.0, 6.0, 8.0):
        cfg = ChannelConfig(samples_per_symbol=sps, ebn0_db=snr)
        row, _, _ = _run_case(bits, tx, taps, cfg, bit_seed=bit_seed,
                              noise_seed=noise_seeds[index], experiment="awgn_baseline")
        baseline.append(row); index += 1
    _write_csv(output_dir / "m3_awgn_baseline.csv", baseline)

    # Experiments 2 and 3: paired common bits and common noise across each sweep.
    amplitude: list[dict[str, object]] = []
    for value in (0.0, 0.08, 0.16, 0.28, 0.42):
        cfg = ChannelConfig(samples_per_symbol=sps, ebn0_db=eb,
                            interference_amplitude=value,
                            interference_frequency_cycles_per_symbol=0.7 if value else None,
                            interference_phase_rad=0.37)
        row, _, _ = _run_case(bits, tx, taps, cfg, bit_seed=bit_seed,
                              noise_seed=noise_seeds[5], experiment="interference_amplitude")
        amplitude.append(row)
    _write_csv(output_dir / "m3_interference_amplitude.csv", amplitude)

    frequency: list[dict[str, object]] = []
    for value in (0.15, 0.35, 0.7, 1.1, 1.6):
        cfg = ChannelConfig(samples_per_symbol=sps, ebn0_db=eb,
                            interference_amplitude=0.22,
                            interference_frequency_cycles_per_symbol=value,
                            interference_phase_rad=0.37)
        row, _, _ = _run_case(bits, tx, taps, cfg, bit_seed=bit_seed,
                              noise_seed=noise_seeds[6], experiment="interference_frequency")
        frequency.append(row)
    _write_csv(output_dir / "m3_interference_frequency.csv", frequency)

    # Experiment 4: the noise variance is fixed while only the wanted signal is attenuated.
    attenuation: list[dict[str, object]] = []
    for value in (0.0, 2.0, 4.0, 6.0, 8.0):
        cfg = ChannelConfig(samples_per_symbol=sps, ebn0_db=eb, attenuation_db=value)
        row, _, _ = _run_case(bits, tx, taps, cfg, bit_seed=bit_seed,
                              noise_seed=noise_seeds[7], experiment="attenuation")
        attenuation.append(row)
    _write_csv(output_dir / "m3_attenuation.csv", attenuation)

    # Noiseless attenuation separates deterministic scaling from noise-induced errors.
    noiseless_attenuation: list[dict[str, object]] = []
    for value in (0.0, 2.0, 4.0, 8.0):
        cfg = ChannelConfig(samples_per_symbol=sps, attenuation_db=value)
        channel_out = apply_configured_channel(tx, cfg)
        decisions = receive_bpsk_waveform(channel_out.received, taps, n_symbols=bits.size,
                                           samples_per_symbol=sps)
        estimate = ber_estimate(bits, decisions.detected_bits)
        noiseless_attenuation.append({
            "experiment": "noiseless_attenuation", "attenuation_db": value,
            "gain": cfg.desired_gain, "n_bits": n_bits,
            "errors": estimate.errors, "ber": estimate.ber,
            "ci95_lower": estimate.confidence_interval[0],
            "ci95_upper": estimate.confidence_interval[1],
            "noise_enabled": False, "interference_enabled": False,
            "received_waveform_length": int(channel_out.received.size),
        })
    _write_csv(output_dir / "m3_noiseless_attenuation.csv", noiseless_attenuation)

    # A separately seeded controlled combined-channel example.
    combined_cfg = ChannelConfig(samples_per_symbol=sps, ebn0_db=eb, attenuation_db=2.0,
                                 interference_amplitude=0.22,
                                 interference_frequency_cycles_per_symbol=0.7,
                                 interference_phase_rad=0.37)
    combined, combined_output, combined_bits = _run_case(
        bits, tx, taps, combined_cfg, bit_seed=bit_seed, noise_seed=noise_seeds[8],
        experiment="combined_awgn_tone_attenuation")
    combined_path = output_dir / "m3_combined_channel.csv"
    _write_csv(combined_path, [combined])

    # Representative component, time-series and spectrum diagnostics.
    n_diag = min(512, tx.size)
    tone = combined_output.interference
    t = np.arange(n_diag) / sps
    pd = output_dir / "m3_diagnostic_waveforms.csv"
    with pd.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample_index", "time_symbols", "transmitted", "attenuated_desired", "interference", "awgn", "received"])
        for n in range(n_diag):
            writer.writerow([n, t[n], tx[n], combined_output.attenuated_signal[n], tone[n],
                             combined_output.noise[n], combined_output.received[n]])

    figs: list[Path] = _plot_sweeps(output_dir, baseline, amplitude, frequency, attenuation)
    # Time-domain transmitted and received waveforms.
    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    ax.plot(t, tx[:n_diag], label="Transmitted RRC waveform")
    ax.plot(t, combined_output.received[:n_diag], label="Received: gain + tone + AWGN", alpha=.8)
    ax.set(xlabel="Time (symbol periods)", ylabel="Amplitude (normalized units)",
           title="Sampled waveform under combined M3 channel")
    ax.grid(True, alpha=.3); ax.legend()
    path = output_dir / "m3_transmit_receive_time.png"; fig.savefig(path, dpi=160); plt.close(fig); figs.append(path)

    # Tone and one-sided spectrum use a record long enough for readable resolution.
    fig, axes = plt.subplots(2, 1, figsize=(9, 6), constrained_layout=True)
    axes[0].plot(t, tone[:n_diag], label="Configured sinusoidal interference")
    axes[0].set(xlabel="Time (symbol periods)", ylabel="Amplitude", title="Interference: peak amplitude 0.22, 0.7 cycles/symbol")
    axes[0].grid(True, alpha=.3); axes[0].legend()
    spec_n = min(8192, tone.size)
    freq = np.fft.rfftfreq(spec_n, d=1.0 / sps)
    spec = 2.0 * np.abs(np.fft.rfft(tone[:spec_n] * np.hanning(spec_n))) / max(1, spec_n)
    axes[1].plot(freq, spec)
    axes[1].set(xlabel="Frequency (cycles/symbol)", ylabel="Windowed magnitude", title="One-sided interference spectrum")
    axes[1].set_xlim(0, sps / 2); axes[1].grid(True, alpha=.3)
    path = output_dir / "m3_interference_time_spectrum.png"; fig.savefig(path, dpi=160); plt.close(fig); figs.append(path)

    # Transmitted and received spectra for the documented combined channel.
    spec_n = min(8192, tx.size)
    freq = np.fft.rfftfreq(spec_n, d=1.0 / sps)
    win = np.hanning(spec_n)
    txspec = 20*np.log10(np.maximum(np.abs(np.fft.rfft(tx[:spec_n]*win)), 1e-12))
    rxspec = 20*np.log10(np.maximum(np.abs(np.fft.rfft(combined_output.received[:spec_n]*win)), 1e-12))
    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    ax.plot(freq, txspec - np.max(txspec), label="Transmit spectrum (normalized)")
    ax.plot(freq, rxspec - np.max(rxspec), label="Receive spectrum, 2 dB attenuation + 0.22 peak tone + 6 dB AWGN")
    ax.set(xlabel="Frequency (cycles/symbol)", ylabel="Magnitude (dB, each trace normalized)",
           title="Transmitted versus received spectrum")
    ax.set_xlim(0, sps/2); ax.set_ylim(-100, 5); ax.grid(True, alpha=.3); ax.legend()
    path = output_dir / "m3_transmit_receive_spectrum.png"; fig.savefig(path, dpi=160); plt.close(fig); figs.append(path)

    # Explicit AWGN-only vs combined-channel comparison, based on actual BER.
    compare_rows = [amplitude[0], combined]
    fig, ax = plt.subplots(figsize=(7.5, 5), constrained_layout=True)
    x = np.arange(2)
    vals = [float(row["ber"]) for row in compare_rows]
    err = [[vals[i]-float(compare_rows[i]["ci95_lower"]) for i in range(2)],
           [float(compare_rows[i]["ci95_upper"])-vals[i] for i in range(2)]]
    ax.bar(x, vals, color=["tab:blue", "tab:orange"], alpha=.75)
    ax.errorbar(x, vals, yerr=err, fmt="none", ecolor="black", capsize=4)
    ax.set_xticks(x, ["AWGN only", "AWGN + tone + 2 dB attenuation"])
    ax.set_yscale("log"); ax.set_ylabel("Measured BER (95% exact CI)")
    ax.set_title("Measured channel comparison at 6 dB configured Eb/N0")
    ax.grid(True, axis="y", which="both", alpha=.3)
    path = output_dir / "m3_awgn_vs_combined.png"; fig.savefig(path, dpi=160); plt.close(fig); figs.append(path)

    # Save model/seed metadata and actual diagnostic measurements.
    metadata = {
        "milestone": "M3",
        "model": "r[n] = g*s[n] + i[n] + w[n]",
        "operation_order": ["attenuate desired waveform", "add sinusoidal interference", "add real iid AWGN"],
        "modeling_assumption": "attenuation applies only to desired signal; interference and receiver-side AWGN are added afterward",
        "noise_convention": "real iid sample variance Eb/(2*10**(EbN0_dB/10)); unit-energy M2 RRC matched filter; normalized discrete model",
        "interference_convention": "A*cos(2*pi*f_sym*n/sps + phase); f_sym in cycles/symbol; digital cycles/sample=f_sym/sps; A is peak amplitude",
        "attenuation_convention": "g=10**(-attenuation_db/20); effective Eb/N0 dB = configured Eb/N0 dB - attenuation dB only without tone and with fixed noise variance",
        "sweep": {"n_bits": n_bits, "master_seed": master_seed, "bit_seed": bit_seed,
                  "samples_per_symbol": sps, "rrc_rolloff": rolloff, "rrc_span_symbols": span,
                  "symbol_energy": 1.0, "nominal_snr_db": eb,
                  "seed_strategy": "SeedSequence master spawns one fixed payload and distinct AWGN streams; paired conditions reuse exact bits and selected same AWGN stream."},
        "noise_variance_at_nominal_snr": noise_variance_from_ebn0_db(eb),
        "diagnostic_measurements": {
            "tx_record_mean_square_power": mean_square_power(tx),
            "combined_attenuated_desired_power": mean_square_power(combined_output.attenuated_signal),
            "combined_interference_power": mean_square_power(combined_output.interference),
            "combined_noise_sample_variance": float(np.var(combined_output.noise, ddof=1)),
            "combined_received_record_power": mean_square_power(combined_output.received),
            "combined_interference_to_desired_ratio": combined["interference_to_attenuated_signal_power_ratio"],
        },
        "software": {"python": platform.python_version(), "numpy": np.__version__,
                     "scipy": scipy.__version__, "matplotlib": matplotlib.__version__},
        "files": ["m3_awgn_baseline.csv", "m3_interference_amplitude.csv", "m3_interference_frequency.csv",
                  "m3_attenuation.csv", "m3_noiseless_attenuation.csv", "m3_combined_channel.csv", "m3_diagnostic_waveforms.csv"],
    }
    config_path = output_dir / "m3_experiment_config.json"
    config_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    figs.extend([
        output_dir / "m3_awgn_baseline.csv",
        output_dir / "m3_interference_amplitude.csv",
        output_dir / "m3_interference_frequency.csv",
        output_dir / "m3_attenuation.csv",
        output_dir / "m3_noiseless_attenuation.csv",
        combined_path,
        pd,
        config_path,
    ])
    return figs


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SignalShield M3 configurable-channel experiments.")
    parser.add_argument("--n-bits", type=int, default=30000)
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--output-dir", type=Path, default=Path("results/m3"))
    args = parser.parse_args()
    started = time.perf_counter()
    outputs = run_m3_experiments(n_bits=args.n_bits, master_seed=args.seed, output_dir=args.output_dir)
    print(f"M3 experiment runtime: {time.perf_counter()-started:.3f} s")
    for output in outputs:
        print(f"saved: {output}")
    for name in ("m3_awgn_baseline.csv", "m3_interference_amplitude.csv",
                 "m3_interference_frequency.csv", "m3_attenuation.csv",
                 "m3_noiseless_attenuation.csv", "m3_combined_channel.csv"):
        with (args.output_dir / name).open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row["experiment"] == "noiseless_attenuation":
                    print(f"{row['experiment']}: attenuation={row['attenuation_db']} dB "
                          f"errors={row['errors']}/{row['n_bits']} BER={float(row['ber']):.7g}")
                else:
                    print(f"{row['experiment']}: Eb/N0={row['ebn0_db']} dB attenuation={row['attenuation_db']} dB "
                          f"tone={row['interference_amplitude_peak']} peak @{row['interference_frequency_cycles_per_symbol']} cycles/symbol "
                          f"errors={row['errors']}/{row['n_bits']} BER={float(row['ber']):.7g} "
                          f"95% CI=[{float(row['ci95_lower']):.7g},{float(row['ci95_upper']):.7g}]")


if __name__ == "__main__":
    main()
