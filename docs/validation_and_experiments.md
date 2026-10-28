# SignalShield Validation and Experimental Plan

## 1. Acceptance matrix

All tests use deterministic seeds where randomness is involved. Exact equality is required only for deterministic mappings/configured values; stochastic criteria are distribution-based. Thresholds must be set before observing a run and justified in test code/comments. No exact noisy BER is compared to a floating theoretical value.

| ID | Setup | Expected behavior / acceptance | Reason |
|---|---|---|---|
| V01 | Generate bits with fixed `Generator`; test lengths and invalid sizes | Output has requested length and only 0/1; same seed gives same output; invalid length raises | Source invariants and reproducibility |
| V02 | Map `[0,1,0,1]` | Exactly `[+1,-1,+1,-1]`; unit symbol energy | Locks mapping and normalization |
| V03 | Demodulate known positive, negative, and zero samples | Correct convention; zero maps to bit 0 | Detector tie behavior is explicit |
| V04 | End-to-end no-noise reference and waveform | Zero bit errors for valid test sequences, including odd/even bit counts | Integration and edge alignment |
| V05 | Generate large AWGN vector at several `Eb/N0` values | Sample mean near zero and variance within predeclared 6-standard-error bound `sqrt(2/(N−1))*σ²` (plus numerical margin) | Verifies variance without fragile exactness |
| V06 | Repeat complete run using same seed/config | Bitstream, generated noise, counts and result metadata match exactly; plots need not be binary-identical across backends | RNG propagation |
| V07 | Hand-calculated reference/detected bit arrays | BER equals `errors/N`; mismatched lengths or empty input raises | Metric correctness |
| V08 | Several reference AWGN SNR points, fixed total trials | Error counts lie in exact binomial 99% intervals around theory (with rare-event resolution addressed); curve is nonincreasing within a statistical monotonicity rule, not exact pointwise order | Analytical agreement |
| V09 | Gain-only test with known vector | Output equals `g*x` exactly within floating precision; zero/nonfinite/negative gain validation follows contract | Component independence |
| V10 | Tone test over integer-like sample periods | Correct length; estimated sinusoidal frequency/amplitude/phase within FFT/fit resolution; zero amplitude is identity | Structured impairment correctness |
| V11 | RRC parameters over several valid `S,L,α` | Odd expected length `SL+1`; finite coefficients; energy 1; symmetry; group delay `(N−1)/2`; singular cases finite | Filter implementation correctness |
| V12 | Impulse/single-symbol through Tx/Rx filters | Central cascade tap =1 within numerical tolerance; correct delay; symbol samples align; record residual off-symbol taps/ISI | Delay and matched-filter chain |
| V13 | Waveform AWGN through unit-energy matched filter, many independent trials | Decision-sample noise variance matches `N0/2` within confidence bound | Validates discrete convention end-to-end |
| V14 | AWGN waveform BER sweep at an SNR with adequate errors | Consistent with coherent BPSK reference within binomial bounds; explicitly inspect finite-RRC residual ISI at high SNR | Confirms normalization and integration |
| V15 | Notch response, stable filter and tone/no-tone waveform | Pole stability; tone attenuation at configured center; record desired-signal decision gain and boundary transient policy; same output length per API | Prevents unreported boundary/noncausal receiver claims |
| V16 | Paired baseline/notch runs with exact same bits, AWGN and tone | Both metrics reproducible; no assumed improvement; if a claimed benefit is reported, paired error difference/CI supports it and desired signal loss is disclosed | Fair comparison |
| V17 | Clean install/import, run all public examples/CLI if present, tests | No missing module/dependency; results folder generated only by requested experiment | Packaging and integration |
| V18 | Regression suite after each integration task | All prior validated behavior remains unchanged or approved change has updated derivation, tests, and reports | Protects mathematical baseline |

For the filtered waveform high-SNR check, do not demand zero errors when measured truncation ISI creates a floor. Establish its expected scale from the deterministic cascade coefficients and test sampling/model agreement separately. Tests should fail for misalignment, wrong variance, wrong filter energy, and mapping errors; never loosen thresholds to hide those faults.

## 2. Statistical methods and stopping policy

For `N` bits and `E` errors, report `BER_hat=E/N`, `E`, `N`, and a two-sided 95% Clopper–Pearson binomial interval (or another documented exact interval). With zero errors, report the one-sided 95% upper limit `1−0.05^(1/N)` (approximately `3/N` for large `N`), never claim BER is zero. At very low target BER, `N` must grow; report the achieved bound if the run cap is reached.

Default reproducible sweep policy: fixed transmitted bits per point (initial design recommendation `N=200,000`) and a configured maximum (e.g. `2,000,000` bits/point); optionally stop when at least 200 errors are observed or maximum bits reached. A run stopped by maximum has no guaranteed relative precision; the confidence interval states actual uncertainty. Use fixed, distinct seeds derived deterministically from master seed + sweep index, and reuse the same transmitted bits and generated noise for paired receiver comparisons. An optional adaptive stopping policy must have a predeclared rule; ordinary fixed-N binomial intervals are not automatically valid under arbitrary repeated peeking. Avoid adaptive stopping for core acceptance; use fixed N and cap.

Use exact tests/intervals where practical (`scipy.stats.binomtest` / `binom.interval` or an audited implementation). Assert simulated rate is plausible under the theoretical Bernoulli probability using a predeclared interval, not pointwise percentage tolerance. If expected errors are too few to distinguish receivers, increase trials or say evidence is inconclusive.

## 3. Controlled experiment set

### E1 — Reference BPSK over AWGN

- **Question/hypothesis:** does the reference implementation reproduce coherent BPSK theory? BER follows `0.5 erfc(sqrt(γb))` within binomial uncertainty.
- **Baseline/candidate:** reference detector only; theory is analytical comparison, not a second receiver.
- **Fixed/varied:** `Eb=1`, no gain/tone, vary `Eb/N0` over `0,2,...,10 dB` (include higher points only if sample count supports them); fixed N initially 200,000 bits/point, cap 2,000,000.
- **Randomness:** recorded master seed and deterministic per-point streams. For comparisons across implementations, share bit and noise arrays.
- **Measurements/acceptance:** BER, errors, N, theory BER, 95% exact interval, runtime; measured rates compatible with theory at all points using a predeclared familywise procedure or per-point 99% intervals plus transparent multiple-comparison caveat. Curve should trend down qualitatively.
- **Limits:** finite Monte Carlo resolution, especially at high SNR; zero errors only bound BER.

### E2 — Sampled waveform normalization and matched filter

- **Question/hypothesis:** does unit-energy finite RRC Tx/Rx preserve the symbol decision noise convention and sample alignment?
- **Baseline/candidate:** compare sampled waveform to E1 using equal information bits and `Eb/N0`; no tone; valid configurations e.g. `L∈{4,8}`, `α=0.35`, `S=8`.
- **Fixed/varied:** one configuration first, then L; fixed seed and N sufficient to see errors at selected SNR (5 dB is a practical starting point, determine actual outcomes rather than promising them).
- **Measurements/acceptance:** tap energy/delay, central and off-symbol cascade taps, matched-filter noise variance, BER and exact interval. Must align and agree within uncertainty; any high-SNR error floor is explained using residual ISI.
- **Limits:** finite span, burst edges, iid discrete-noise convention is normalized rather than a physical ADC model.

### E3 — Attenuation calibration

- **Question/hypothesis:** does uncorrected gain shift effective SNR predictably by `20log10(g)` dB?
- **Baseline/candidate:** `g=1` vs selected positive gains, no tone, common bits and pre-generated unit-variance noise at the same nominal `N0`.
- **Fixed/varied:** sweep gain, nominal SNR selected for measurable BER.
- **Measurements/acceptance:** received decision mean/variance, BER vs theory at effective `g²Eb/N0`; with optional known-gain correction, separately verify recovery to nominal BER.
- **Limits:** this is deterministic gain, not fading or AGC.

### E4 — Narrowband tone and notch receiver

- **Question/hypothesis:** does a notch improve BER when a sufficiently strong tone lies in a narrow part of the desired spectrum, and where does desired-signal distortion dominate?
- **Baseline/candidate:** matched-filter-only vs the M4 offline `iirnotch`/`filtfilt` notch followed by the matched filter. It is noncausal and must not be represented as a real-time receiver. Compare on exactly the same bits, AWGN samples and tone realization.
- **Fixed/varied:** fixed `L=8, α=.35, S=8`, SNR chosen for measurable uncoded baseline; vary `ISR_dB` from below to above 0 dB (e.g. −20 to +10 dB), tone offset `f_i/R_s` at a few in-band values, and notch Q (e.g. 10, 30) only in a bounded follow-up. Keep `f_i` away from Nyquist and document ratio. Tone frequency and phase are common across paired receivers.
- **Measurements/acceptance:** BER with paired uncertainty, errors/N, tone attenuation, desired-signal transfer/decision gain, transient policy, runtime, saved config. Claim benefit only where paired evidence supports lower BER and report degradation regions. Tone-free run measures notch's cost.
- **Limits/confounders:** tone can overlap desired spectral energy; Q trades rejection and bandwidth; IIR transient and finite packet length matter; “ISR” depends on waveform record/power definition. A sinusoid is a narrowband interferer, not an adversarial or realistic jammer model.

### E5 — Reproduction and artifact check

- **Question/hypothesis:** can a clean environment regenerate the documented results? Re-running a saved experiment configuration yields matching counts and metadata for a fixed deterministic stack and seed.
- **Measurements:** package versions, configuration, run command, output files; compare numeric outputs rather than PNG byte hashes.
- **Limits:** floating-point/library versions may change last-bit values or plot rendering; record versions and tolerance.

## 4. Results and plotting contract

Each run stores JSON configuration/metadata and a row-oriented CSV summary containing model, receiver, seed, `Eb/N0_dB`, gain, tone fields, bit/error counts, BER, theory where valid, confidence bounds, elapsed time, and code/library version. No result file is overwritten without clear intent; filenames include experiment and timestamp or a user-provided run label. Keep raw configuration with derived metrics.

Required figures: (1) BER vs `Eb/N0` on log y-axis, theory visually distinguished from measured points and confidence intervals; (2) BER vs tone ISR for paired receivers with error bars or uncertainty indicators; (3) optional filter magnitude response and representative waveform only as diagnostics. Label sample model, pulse settings, receiver, number of trials and zero-error bounds. Do not use a waveform image as proof of BER improvement.

## 5. M6 final system integration evidence

M6 adds a Streamlit front end and UI-independent UTF-8 payload adapter over the existing M2/M3/M4 engine. The message test path converts UTF-8 bytes to MSB-first bits, invokes existing BPSK/RRC/channel/receiver/BER functions, and strictly decodes the receiver's actual decisions. A paired mode passes the same channel-output array to both receiver paths. The Performance Lab delegates to the M5 experiment runner and result schema.

Current M6 validation commands and recorded evidence:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m streamlit run src\signalshield\streamlit_app.py --server.headless true --server.port 8503 --server.address 127.0.0.1
.\.venv\Scripts\python.exe scripts\run_m6_validation.py --output-dir results/m6/validation --n-bits 50000 --repetitions 2 --seed 20261030
```

The app returned HTTP 200 at `/_stcore/health`, and Streamlit `AppTest` exercised the app's tabs and clean message form without a browser. The M6 validation script saves clean, AWGN-only, matched-tone, mismatch, attenuation-only, and paired same-realization cases; waveform trace arrays and plots; a 50,000-bit × 2-repetition AWGN reference sweep; and an exact non-runtime replay comparison. See `reports/M6_final_validation_report.md` for current test counts, actual measurements, known browser-level limits, and the acceptance matrix. Historical M1–M5 outputs and reports remain unchanged.

