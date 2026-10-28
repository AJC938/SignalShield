# SignalShield Payload UI Refinement Report

**Date:** 2026-10-28  
**Scope:** Simpler text/audio transmission workflow, bounded WAV support, frame integrity, optional FEC, plots, documentation, and regression checks. M1–M6 simulation algorithms and historical outputs were retained.

## Implemented

- Reworked the primary Streamlit tab into **Transmit & Analyze** with Text Message / Voice-Audio selection, an explicit run button, collapsed Advanced Settings, and stale-result suppression keyed to payload and configuration. Channel & Receiver Analysis and Performance Lab remain separate tabs.
- Added microphone recording (`st.audio_input`) and WAV upload. Input accepts PCM signed 16-bit WAV, mono/stereo, 8–48 kHz, up to 1 second and 2 MiB. Audio is downmixed to mono when needed, resampled to 8 kHz, clipped and quantized to signed PCM16 little-endian. No ASR is performed.
- Added a bounded `SSP1` frame: magic, type, flags, payload byte length, canonical and source audio metadata, payload, and CRC. Integer fields are unsigned big-endian; frame bytes become MSB-first bits. CRC uses Python `zlib.crc32` (IEEE CRC-32/ISO-HDLC convention) over the header and payload, then is stored big-endian. Frame payloads are limited to 16,384 bytes; audio payloads are at most 16,000 canonical bytes.
- Added systematic even-parity Hamming(7,4), enabled by default in the UI and switchable off. It operates on framed bits before BPSK modulation. The receiver counts nonzero syndromes; that count is not guaranteed to equal actual corrected physical errors when multiple bits flip in one word.
- Added receive-side decode, framing and CRC checks. The source bytes are used only for post-reception diagnostics/exact-match comparison; they do not repair received data. A CRC failure is reported as unverified/corrupt. Safely parseable damaged audio may be previewed but is labeled corrupted.
- Reused the existing BPSK, RRC, channel, matched-filter, and optional notch implementations. Plots display the transmitted/received communication waveforms, available tone/noise components, matched-filter output, coded-bit preview, and audio waveform separately. Display sampling is reduced for visualization only; the signal path processes full arrays.
- Updated `README.md` and `docs/user_guide.md`; added focused framing, audio, Hamming, end-to-end, and noisy-integrity tests. The M6 report and prior M1–M6 results were left intact.

## Verification performed

Command run from the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

**Actual result:** `91 passed in 9.60s`. Coverage includes UTF-8 framing/CRC, invalid frame ID and length, CRC failure after controlled corruption and a two-bit Hamming error, all seven single-bit Hamming positions, WAV normalization and reconstruction, invalid/unsupported/over-duration WAV, clean text/audio end-to-end recovery, and a severe-noise case that is not reported as an exact verified recovery. Existing M1–M6 tests remain in the run. The M6 AppTest now also checks that changing the text after a run hides the old result.

Streamlit startup was checked using:

```powershell
.\.venv\Scripts\python.exe -m streamlit run src\signalshield\streamlit_app.py --server.headless true --server.port 8517 --server.address 127.0.0.1 --browser.gatherUsageStats false
```

The final live server returned HTTP 200 for both `/` and `/_stcore/health`; health response was `ok`. It was stopped after the check. The pytest AppTest exercises the UI without a browser. **No browser screenshot or human visual review was performed.**

## Files changed or added

- `src/signalshield/streamlit_app.py` — simplified primary UI, audio input, advanced controls, output status and plots; paired payload analysis stays linked to the active configuration.
- `src/signalshield/payload_frame.py` — bounded SSP1 frame, parsing, CRC, bit-order helpers.
- `src/signalshield/fec.py` — Hamming(7,4) encode/decode.
- `src/signalshield/audio.py` — WAV validation, normalization, and WAV reconstruction.
- `src/signalshield/payload_application.py` — frame/FEC adapters around the existing waveform/channel/receiver engine.
- `tests/test_payload_features.py` — focused feature and end-to-end checks.
- `tests/test_application_m6.py` — updated Streamlit UI expectations and stale-result assertion; existing engine assertions retained.
- `README.md`, `docs/user_guide.md` — workflow and limits.

No new benchmark outputs were created or substituted for historical M1–M6 results. No Git repository, commit, or remote was created or changed.

## Limits and remaining verification

- Only PCM signed 16-bit WAV is accepted. Other sample formats/encodings are rejected with a message. Maximum source duration is one second; microphone recordings that exceed the same cap are rejected after capture.
- CRC-32 is an accidental-corruption check, not a cryptographic integrity or authenticity mechanism; a CRC collision is possible.
- Hamming corrects a single flipped bit per 7-bit word. Multiple flips may be miscorrected; CRC does not promise detection of every possible resulting frame.
- BER is measured on the transmitted coded frame bits before FEC; post-FEC frame-bit errors and final CRC/exact-byte outcome are separate. A short message's BER is not a Monte Carlo estimate.
- Streamlit startup and browserless AppTest passed; browser-level visual behavior remains unverified. Existing M1–M6 reports describe historical pre-payload-FEC behavior and were intentionally not rewritten.
