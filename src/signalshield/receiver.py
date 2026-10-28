"""Coherent hard-decision BPSK receiver."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from signalshield.filters import filter_group_delay_samples, matched_filter, sample_symbols, symbol_sample_indices
from signalshield.modulation import bpsk_demodulate
from signalshield.signals import as_real_samples


def detect_bpsk(received_samples: object) -> NDArray[np.uint8]:
    """Recover bits using a zero threshold; a zero sample maps to bit 0."""
    return bpsk_demodulate(as_real_samples(received_samples))


@dataclass(frozen=True, slots=True)
class WaveformReceiverOutput:
    """Aligned full matched-filter output and payload decisions."""

    filtered_samples: NDArray[np.float64]
    sample_indices: NDArray[np.int64]
    decision_samples: NDArray[np.float64]
    detected_bits: NDArray[np.uint8]


def receive_bpsk_waveform(
    received_waveform: object,
    transmit_taps: object,
    *,
    n_symbols: int,
    samples_per_symbol: int,
) -> WaveformReceiverOutput:
    """Matched-filter, compensate equal Tx/Rx delays, sample and detect.

    Convolutions use ``full`` mode. The first symbol decision is at
    ``2*D + 0*sps`` and subsequent decisions are one symbol apart.
    """
    checked_waveform = as_real_samples(received_waveform, name="received_waveform")
    checked_taps = as_real_samples(transmit_taps, name="transmit_taps")
    tx_delay = filter_group_delay_samples(checked_taps)
    rx_delay = filter_group_delay_samples(checked_taps[::-1])
    total_delay = tx_delay + rx_delay
    filtered = matched_filter(checked_waveform, checked_taps)
    indices = symbol_sample_indices(
        n_symbols,
        samples_per_symbol,
        total_delay,
        int(filtered.size),
    )
    decisions = sample_symbols(
        filtered,
        n_symbols=n_symbols,
        samples_per_symbol=samples_per_symbol,
        total_delay_samples=total_delay,
    )
    return WaveformReceiverOutput(
        filtered_samples=filtered,
        sample_indices=indices,
        decision_samples=decisions,
        detected_bits=detect_bpsk(decisions),
    )

