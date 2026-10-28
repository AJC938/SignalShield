# SignalShield User Guide

## Start the application

From the project directory in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,app]"
.\.venv\Scripts\python.exe -m streamlit run src\signalshield\streamlit_app.py
```

Open the local URL printed by Streamlit, usually `http://localhost:8501`.

## Send a text or voice payload

In **Transmit & Analyze**, follow the four on-screen stages: **Input → Channel → Receiver → Recovery**. Select **Text Message** or **Voice / Audio**, provide the content, then press the single **Transmit & Analyze** button. A run happens only when submitted. The communication chain displays a prominent recovery status, compact metrics, original/recovered payload comparison, and plots grouped into **Transmit**, **Channel**, **Receiver**, and **Recovery** views. Input or setting changes hide results from the earlier configuration.

For audio, choose microphone recording or WAV upload. Accepted input is PCM signed 16-bit WAV, mono or stereo, sample rate 8–48 kHz, up to one second and 2 MiB. Unsupported encodings, malformed WAV files, excessive duration, and other channel layouts are rejected. Microphone recording uses the same validation. No speech recognition occurs.

Audio is downmixed to mono when needed, resampled to 8 kHz, clipped and quantized to signed 16-bit little-endian PCM. The frame carries both canonical and source sample metadata, including sample rate, channels, sample format, and frame count. The reconstructed preview is canonical mono 8 kHz audio. Canonical audio is limited to 16,000 bytes; the whole frame is bounded by the 16 KiB payload limit plus its header and CRC.

## Frame, channel, and integrity

UTF-8 text bytes or canonical audio bytes are framed as magic `SSP1`, payload type, flags, payload length, audio metadata, payload bytes, and a 32-bit CRC. Multi-byte fields are unsigned big-endian; bytes are expanded most-significant-bit first. CRC is Python `zlib.crc32`, the standard reflected IEEE CRC-32/ISO-HDLC convention, initialized/finalized as that API specifies, stored big-endian, and calculated over the complete header and payload.

By default the frame bits are encoded with systematic even-parity Hamming (7,4) before BPSK. The advanced settings allow disabling it for comparison. It corrects one bit in each 7-bit codeword. Multiple errors in one codeword may be miscorrected; reported correction count is the number of nonzero syndromes, not proof of the underlying number of physical errors. CRC catches many accidental corruptions after FEC but is not authentication and cannot guarantee detection of every possible corruption.

The existing SignalShield waveform, RRC pulse shaping, configurable AWGN/tone/attenuation channel, matched-filter receiver, and optional notch path process the actual framed bits. Advanced Settings contains Eb/N0, AWGN, tone, attenuation, receiver, notch, waveform, seed, and FEC controls. In a clean/noiseless run, CRC-valid plus exact byte comparison establishes the observed payload match. In an impaired run, CRC failure is shown as unverified/corrupt; any safely parsed audio is explicitly a damaged preview.

## Read the plots and metrics

Plots are built from actual simulation arrays: transmitted BPSK/RRC waveform, received waveform with active noise/tone traces, and matched-filter output. The audio waveform is shown separately from the communication waveform. Long arrays are downsampled only in the plot; transmission and receiver processing use full-resolution data. A bounded coded-bit preview is shown instead of dumping large bit arrays.

The reported coded-bit BER compares detector decisions with transmitted coded bits before FEC. Post-FEC frame-bit error count is a separate measure. CRC and exact payload match are the final integrity outcomes. BER from a short message is a per-payload observation and is not a long-run Monte Carlo estimate. **Channel & Receiver Analysis** and **Performance Lab** retain the deeper receiver and M5 experiment tools. When **Both (paired comparison)** is selected, the receiver tab displays the same-run baseline/notch BER, corrected/introduced/shared coded-bit errors, notch attenuation/distortion diagnostics, CRC results, and exact payload match for each branch.

## Tests and limits

Run the full regression suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

SignalShield is an educational offline simulator, not a physical radio. It does not provide speech transcription, synchronization, cryptographic authentication, RF hardware, or guarantees of payload delivery. Hamming cannot correct arbitrary multi-bit errors, and CRC is an accidental-error check rather than a security primitive. See the [final UI/UX refinement report](../reports/ui_refinement_report.md), [payload interface engineering report](../reports/payload_ui_refinement_report.md), and [M6 historical report](../reports/M6_final_validation_report.md).
