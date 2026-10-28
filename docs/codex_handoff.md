# SignalShield Codex Implementation Handoff

## Mission

Implement, test, document, and validate the complete SignalShield core specified in the accompanying design documents. The goal is a technically credible, reproducible BPSK communication simulator with reference and sampled-waveform chains, AWGN/gain/tone models, matched filtering, the explicitly offline/noncausal notch comparison, statistically responsible metrics, results, reports, and a local Streamlit demonstration over the same engine.

## Binding design contract

1. Read `README.md` and every file in `docs/` before coding. Inspect the existing repository, working tree, ignored/user files, Python environment, and current tests. Preserve user work; do not overwrite, delete, or rename existing work without a concrete reason and safe migration plan.
2. Build one complete target in dependency order from `implementation_plan.md`; do not create artificial product versions or unrelated features. The final M6 target includes a thin local Streamlit UI; the numerical engine remains reusable without it.
3. Use `b=0 → +1`, `b=1 → −1`, `Eb=1`, `gamma_b=10^(Eb/N0_dB/10)`, real AWGN variance `1/(2 gamma_b)`, and theory `0.5 erfc(sqrt(gamma_b))` for the reference model.
4. For the sampled model, use `L` samples/symbol, finite odd `N=S L+1` RRC taps with `S L` even, explicitly handle singularities, unit-energy taps, causal matched filter, total delay `2*(N−1)/2`, and decision samples at `D_total+kL`. Add iid real sample noise variance `N0/2`; explain this normalized discrete convention and do not claim arbitrary physical continuous-time PSD calibration.
5. Keep gain, AWGN, and tone independently testable. Tone is `A cos(2π f_i n/F_s+φ)`; record actual parameters and defined ISR. M4 may use offline `scipy.signal.iirnotch` with `filtfilt` before matched filtering, but must identify it as noncausal and never claim real-time receiver benefit. A causal design is needed for real-time claims.
6. Never claim improvement from a cleaner waveform. Compare BER, paired errors/uncertainty, wanted-signal loss, tone attenuation, timing/transients and runtime. A valid result may show no benefit.
7. Generate random data only through explicit `numpy.random.Generator` paths. For paired receivers use exactly shared bits, AWGN and tone. Distinguish theory, measurement and prediction in records/plots.
8. Report zero observed errors as an upper confidence bound, not BER=0. Use documented binomial intervals and predeclared sample/stopping policies. Do not relax a correct test to pass faulty code.
9. Implement only modules with real responsibilities. Keep plotting side-effect-free; store true configuration, seeds, versions, counts, outputs. No invented numerical results.
10. Use professional English for identifiers/code/formal docs and clear Arabic for explanations addressed to the user.

## Required implementation deliverables

- Installable `signalshield` package, type hints, validation, docstrings, and focused modules matching `system_design.md`.
- Automated deterministic unit/integration tests and statistical checks described in `validation_and_experiments.md`.
- Reference and sampled waveform simulations, attenuation and tone channel components, baseline and notch receivers.
- Reproducible E1–E5 runners, CSV/JSON results, BER figures with uncertainty and theoretical distinction.
- README/setup/execution instructions, complete mathematical/channel/receiver/validation/decision documentation, limitations, portfolio summary, interview questions.
- Completed task and final validation reports based only on actions/results actually observed.

## Required workflow and evidence

For each task in the work breakdown: inspect relevant files and dependencies; state objective and design choices; implement the smallest coherent slice; run relevant tests; inspect failures rather than masking them; save commands, outputs, measured values, and plots; update documentation/report; then proceed after its exit gate passes. At final handoff run the full test suite and selected experiments from a clean or documented install. Include exact commands and actual outcomes, environment/library versions, known limitations, and reproduction commands.

If an assumption in this contract is mathematically inconsistent with the implementation environment, stop the dependent integration, provide a derivation and concrete alternative, and record its verification consequences. Do not silently substitute a noise formula, change sample indices, add compensation, or change scope.

## Completion definition

The project is complete when all required T00–T10 deliverables exist, all acceptance tests have been run with outcomes reported, reference and waveform chains have reproducible numerical evidence, notch conclusions are supported by fair paired experiments, docs match implementation, and unresolved issues are explicit. Planned work is never described as completed or tested.

