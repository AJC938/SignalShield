# SignalShield Portfolio Summary

## Project

SignalShield is an educational digital communications lab that simulates an uncoded real-baseband BPSK link and examines how controlled channel conditions affect bit recovery.

## Engineering challenge

The central challenge was to integrate a mathematically consistent one-sample AWGN reference with an oversampled finite-RRC waveform, a configurable channel, matched-filter timing, a paired offline notch receiver, reproducible experiments, and an interface that shows actual signal arrays and decoded user data.

## Implemented architecture and methods

- Python package separating configuration, bit source, BPSK mapping, waveform/filtering, channel, receivers, metrics, experiments, payload adapter, and Streamlit UI.
- Coherent BPSK, finite unit-energy root-raised-cosine pulse shaping, matched filtering, delay-aware symbol sampling, real AWGN, deterministic signal attenuation, and a sinusoidal tone.
- Configured second-order notch receiver using `iirnotch` and offline zero-phase `filtfilt`; it is explicitly noncausal.
- BER from actual error counts, Clopper–Pearson intervals, BPSK/AWGN theory when applicable, deterministic SHA-256 seed derivation, paired error counts, and contiguous-block bootstrap sensitivity.
- Streamlit payload demo encodes UTF-8 to bits and reconstructs recovered bytes strictly. Performance Lab calls the same M5 experiment runner exposed by the CLI.

## Verification and observed findings

The full final suite passed with **83 tests** (see `reports/M6_final_validation_report.md` for exact command and timing). A Streamlit `AppTest` executed a clean message; a local server health endpoint returned HTTP 200. Six payload scenarios and a 50,000-bit × 2-repetition M1 AWGN reference experiment were run. The long-run measured mean BERs at 0, 4, and 8 dB were 0.07899, 0.01233, and 0.00019, compared with theoretical 0.07865, 0.01250, and 0.000191. In one matched-tone payload comparison, BER decreased from 0.14555 baseline to 0.006279 with the notch; at a 0.60 cycles/symbol tone and 0.35 center, it increased from 0.01142 to 0.01655.

These are finite simulation measurements for documented configurations. They are not universal receiver performance guarantees. Statistical inference from two repetitions remains limited.

## Technologies

Python 3.11, NumPy, SciPy, Matplotlib, pytest, and Streamlit. Results are stored as CSV, JSON, NPZ traces, and PNG plots.

## Limitations and distribution note

The model is normalized discrete time and does not include synchronization, fading, FEC, RF hardware, or real-time DSP. RRC truncation leaves residual ISI. Notch filtering can distort the wanted waveform and is noncausal here. The project has no selected license; the owner must decide one before public redistribution.
