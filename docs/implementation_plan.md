# SignalShield Implementation Work Breakdown

This plan constructs the complete agreed target through engineering tasks, not product versions. Each task produces an inspectable artifact and evidence before dependent work begins. No implementation is claimed complete by this design document.

| Task | Dependencies | Deliverables | Exit / verification gate |
|---|---|---|---|
| T00 Repository and environment reconnaissance | None | Inventory of existing files, Python/package versions, current user changes, target tree proposal; initial Arabic/English design decisions | No existing work overwritten; imports/install commands recorded accurately; dependency and Python minimum fixed |
| T01 Package/configuration foundation | T00 | `pyproject.toml`, validated immutable config, package metadata and public error policy | Install/import succeeds; invalid SNR, bit count, rolloff, L, spans, tone frequencies rejected; config tests |
| T02 Bits and BPSK reference | T01 | RNG-injected bit source, strict bit validation, mapping/demapping, reference AWGN detector flow | V01–V04 pass; exact formula and convention documented |
| T03 Channel primitives and metrics | T02 | gain, additive-noise primitive, tone component, BER/theory/interval utilities | V05–V10/V07 pass; measured noise variance and zero-error bounds verified |
| T04 Reference experiment and result record | T03 | seeded E1 sweep, CSV/JSON writer, BER plot and truthful report | V06, V08, V17 pass; run artifact includes true counts/config/versions |
| T05 RRC and sampled waveform | T02–T03 | RRC formula incl singular limits, finite tap normalization, upsample/convolve, matched filter, delay-aware sampler | V11–V13 pass; demonstrate exact alignment for short known sequences and quantify ISI |
| T06 Integrated waveform baseline | T05 | E2 runner, shared channel interface, theory comparison and waveform result plots | V04, V13, V14 pass within predeclared binomial bounds; no hidden per-packet normalization |
| T07 Notch receiver | T05 | Validated second-order iirnotch with documented offline filtfilt mode, stability/response metadata, boundary handling | V15 passes; noncausal mode disclosed; tone-free desired-signal cost measured |
| T08 Controlled channel/receiver experiments | T06–T07 | E3 attenuation and paired tone-vs-notch experiments; saved experiment configs/results | Paired outputs and block-bootstrap BER difference recorded; includes candidate degradation cases |
| T09 Packaging, documentation and portfolio | T08 | Complete README, install/use commands, block diagram, mathematical/model docs, limitations, concise portfolio summary, interview questions | Clean environment reproduces examples; docs agree with API/results; no unverified claims |
| T10 Final validation and handoff | T09 | Full pytest and experiment run record; validation report; reproducibility instructions and known limitations | V17–V18 complete; all failures/deviations disclosed; repository state summarized |

## Integration checkpoints

1. **Reference gate after T04:** Do not start filter/channel extensions until BPSK/AWGN theory, RNG injection, BER, confidence handling, and saved results are stable.
2. **Waveform gate after T06:** Confirm unit-energy taps, correct total delay, receiver noise variance, finite-pulse ISI and theory comparison. Correct derivation before adding notch.
3. **Receiver-comparison gate after T08:** Confirm paired realizations, explicitly causal or offline filter mode, tone and signal response, error uncertainty, and fair gain/noise normalization.
4. **Release evidence gate after T10:** Run and record actual tests/experiments from a clean or documented environment; update validation report from outputs, never from plans.

## Change control

If an implementation detail differs from this baseline, the implementing agent must document (a) what changes, (b) equations/assumptions affected, (c) API/data consequences, (d) tests that establish equivalence or justify a new behavior, and (e) any experiment impact. Scope changes adding conditional features require updating this plan and acceptance matrix before implementation. Preserve user work and inspect the repository before writing any file.

## Actual milestone status (2026-10-28)

| Milestone | Status | Evidence |
|---|---|---|
| M1 — Foundation and reference link | Implemented before M3; regression retained | `tests/test_baseline.py`, `results/m1/`, and `reports/M1_engineering_report.md` |
| M2 — Sampled waveform and matched filtering | Implemented before M3; regression retained | M2 tests, `results/m2/`, and `reports/M2_engineering_report.md` |
| M3 — Configurable channel simulator | Implemented and verified in this workspace | `src/signalshield/channel.py`, `src/signalshield/m3_experiments.py`, `tests/test_channel_m3.py`, `results/m3/`, and `reports/M3_engineering_report.md` |
| M4 — Receiver improvement and recovery | Implemented and verified in this workspace | `src/signalshield/notch.py`, `src/signalshield/m4_experiments.py`, `tests/test_notch_m4.py`, `results/m4/`, and `reports/M4_engineering_report.md` |
| M5 — Experimental framework and performance analysis | Implemented and verified in this workspace | `src/signalshield/experiment_framework.py`, `src/signalshield/experiment_runner.py`, centralized paired metrics, `tests/test_experiment_framework_m5.py`, seven scenario outputs under `results/m5/`, and `reports/M5_engineering_report.md` |
| M6 — System integration and final validation | Implemented and verified for the defined simulator/UI scope | `src/signalshield/application.py`, `src/signalshield/streamlit_app.py`, `scripts/run_m6_validation.py`, `tests/test_application_m6.py`, `results/m6/validation/`, `docs/user_guide.md`, `docs/system_architecture.md`, and `reports/M6_final_validation_report.md` |

M3 follows the user-approved order `desired-signal attenuation → sinusoidal interference → AWGN`. Earlier wording in the system design listed AWGN before tone; the equation and generated components are additive, so their sum is unchanged for fixed components. The M3 API now uses the requested explicit order and this design document has been reconciled. Attenuation remains signal-only, with interference and AWGN added after it.

M4 uses second-order `iirnotch` coefficients with zero-phase forward-backward `filtfilt` for the offline experiments. Earlier design text described a causal notch as the required comparison. The M4 request explicitly permits `filtfilt` for this offline simulator and prohibits real-time claims; the docs now state that choice. M5 adds standardized execution and analysis without changing the M1–M4 signal models. M6 adds the Streamlit UI and UI-independent message adapter over the same engine, plus current integration tests and final report; it adds no communication algorithms. The final acceptance matrix is in `reports/M6_final_validation_report.md`.

