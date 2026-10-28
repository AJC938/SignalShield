"""Pure plotting helpers for saved experiment results."""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from signalshield.experiments import ExperimentResult


def save_ber_plot(
    results: Sequence["ExperimentResult"],
    path: Path,
    *,
    title: str = "SignalShield M1: coherent BPSK over real AWGN",
) -> None:
    """Save BER theory and measured intervals without simulating data.

    Nonzero estimates appear with two-sided exact intervals. If zero errors
    occurred, the marker denotes the one-sided 95% upper bound; zero is never
    moved to an arbitrary positive value and presented as an observation.
    """
    if not results:
        raise ValueError("results must not be empty")

    fig, axis = plt.subplots(figsize=(8.5, 5.5), constrained_layout=True)
    ebn0_values = [result.ebn0_db for result in results]
    theory_values = [result.theoretical_ber for result in results]
    axis.semilogy(ebn0_values, theory_values, "k-", label="Theory: coherent BPSK/AWGN")

    nonzero = [result for result in results if result.errors > 0]
    if nonzero:
        x = [result.ebn0_db for result in nonzero]
        y = [result.ber for result in nonzero]
        low = [result.ci_lower for result in nonzero]
        high = [result.ci_upper for result in nonzero]
        axis.errorbar(
            x,
            y,
            yerr=[[estimate - bound for estimate, bound in zip(y, low, strict=True)],
                  [bound - estimate for estimate, bound in zip(y, high, strict=True)]],
            fmt="o",
            capsize=3,
            label="Simulation (95% exact CI)",
        )

    zero = [result for result in results if result.errors == 0]
    for index, result in enumerate(zero):
        if result.zero_error_upper_95 is None:
            raise ValueError("zero-error result is missing its one-sided 95% upper bound")
        bound = result.zero_error_upper_95
        axis.scatter(
            result.ebn0_db,
            bound,
            marker="v",
            color="tab:red",
            zorder=4,
            label="0 errors: one-sided 95% upper bound" if index == 0 else None,
        )
        axis.annotate(
            "",
            xy=(result.ebn0_db, bound * 0.6),
            xytext=(result.ebn0_db, bound),
            arrowprops={"arrowstyle": "->", "color": "tab:red", "lw": 1.2},
        )
        axis.annotate(
            f"0/{result.n_bits} errors\nupper 95% bound",
            (result.ebn0_db, bound),
            xytext=(6, 8),
            textcoords="offset points",
            fontsize=8,
        )

    axis.set_xlabel(r"$E_b/N_0$ (dB)")
    axis.set_ylabel("Bit error rate")
    axis.set_title(title)
    axis.grid(True, which="both", alpha=0.3)
    axis.legend()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def save_m2_diagnostic_plots(
    *,
    output_dir: Path,
    taps: object,
    transmit_waveform: object,
    received_waveform: object,
    receiver_output: object,
    samples_per_symbol: int,
    rolloff: float,
    span_symbols: int,
    ebn0_db: float,
    n_symbols_to_plot: int = 14,
) -> tuple[Path, Path, Path, Path, Path]:
    """Save impulse, frequency, Tx, noisy Rx, and matched-filter plots."""
    import numpy as np
    from scipy.signal import freqz

    pulse = np.asarray(taps, dtype=np.float64)
    tx = np.asarray(transmit_waveform, dtype=np.float64)
    rx = np.asarray(received_waveform, dtype=np.float64)
    filtered = np.asarray(receiver_output.filtered_samples, dtype=np.float64)
    decision_indices = np.asarray(receiver_output.sample_indices, dtype=np.int64)
    if pulse.ndim != 1 or pulse.size == 0 or not np.all(np.isfinite(pulse)):
        raise ValueError("taps must be a nonempty finite one-dimensional array")
    if tx.ndim != 1 or rx.shape != tx.shape:
        raise ValueError("transmit and received waveforms must be one-dimensional and same length")
    if filtered.ndim != 1 or decision_indices.ndim != 1:
        raise ValueError("receiver output arrays must be one-dimensional")
    if samples_per_symbol <= 0 or n_symbols_to_plot <= 0:
        raise ValueError("plot sample rate and symbol count must be positive")

    output_dir.mkdir(parents=True, exist_ok=True)
    impulse_path = output_dir / "m2_rrc_impulse.png"
    frequency_path = output_dir / "m2_rrc_frequency.png"
    tx_path = output_dir / "m2_tx_waveform.png"
    rx_path = output_dir / "m2_awgn_received_waveform.png"
    matched_path = output_dir / "m2_matched_filter_decisions.png"

    center = (pulse.size - 1) / 2.0
    pulse_time = (np.arange(pulse.size) - center) / samples_per_symbol
    fig, axis = plt.subplots(figsize=(8.5, 4.8), constrained_layout=True)
    axis.stem(pulse_time, pulse, basefmt=" ")
    axis.set_xlabel("Time (symbol periods)")
    axis.set_ylabel("Amplitude (unit-energy taps)")
    axis.set_title(f"RRC impulse response: span={span_symbols}, sps={samples_per_symbol}, β={rolloff:g}")
    axis.grid(True, alpha=0.3)
    fig.savefig(impulse_path, dpi=160)
    plt.close(fig)

    frequency, response = freqz(pulse, worN=8192, fs=float(samples_per_symbol))
    response_db = 20.0 * np.log10(np.maximum(np.abs(response), np.finfo(float).tiny) / np.max(np.abs(response)))
    fig, axis = plt.subplots(figsize=(8.5, 4.8), constrained_layout=True)
    axis.plot(frequency, response_db)
    axis.set_xlim(0.0, 1.5)
    axis.set_ylim(-100, 5)
    axis.set_xlabel("Frequency (cycles per symbol, one-sided)")
    axis.set_ylabel("Magnitude (dB, normalized)")
    axis.set_title(f"RRC frequency response: span={span_symbols}, sps={samples_per_symbol}, β={rolloff:g}")
    axis.grid(True, which="both", alpha=0.3)
    fig.savefig(frequency_path, dpi=160)
    plt.close(fig)

    plot_end = min(tx.size, n_symbols_to_plot * samples_per_symbol)
    time_tx = np.arange(plot_end) / samples_per_symbol
    fig, axis = plt.subplots(figsize=(9, 4.8), constrained_layout=True)
    axis.plot(time_tx, tx[:plot_end], label="Pulse-shaped transmit waveform")
    axis.set_xlabel("Time from burst start (symbol periods)")
    axis.set_ylabel("Amplitude")
    axis.set_title("Actual RRC-shaped transmit burst")
    axis.legend()
    axis.grid(True, alpha=0.3)
    fig.savefig(tx_path, dpi=160)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(9, 4.8), constrained_layout=True)
    axis.plot(time_tx, rx[:plot_end], label=f"Received waveform ({ebn0_db:g} dB, real AWGN)")
    axis.set_xlabel("Time from burst start (symbol periods)")
    axis.set_ylabel("Amplitude")
    axis.set_title("Actual pulse-shaped waveform plus discrete AWGN")
    axis.legend()
    axis.grid(True, alpha=0.3)
    fig.savefig(rx_path, dpi=160)
    plt.close(fig)

    matched_end = min(filtered.size, (n_symbols_to_plot - 1) * samples_per_symbol + pulse.size * 2)
    time_mf = np.arange(matched_end) / samples_per_symbol
    visible_decisions = decision_indices[decision_indices < matched_end]
    fig, axis = plt.subplots(figsize=(9, 4.8), constrained_layout=True)
    axis.plot(time_mf, filtered[:matched_end], label="Matched-filter output")
    axis.scatter(
        visible_decisions / samples_per_symbol,
        filtered[visible_decisions],
        marker="x",
        color="tab:red",
        label="Payload decision instants",
        zorder=3,
    )
    axis.set_xlabel("Time from burst start (symbol periods)")
    axis.set_ylabel("Matched-filter sample amplitude")
    axis.set_title("Matched-filter output with delay-compensated symbol samples")
    axis.legend()
    axis.grid(True, alpha=0.3)
    fig.savefig(matched_path, dpi=160)
    plt.close(fig)
    return impulse_path, frequency_path, tx_path, rx_path, matched_path
