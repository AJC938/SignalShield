# SignalShield M2 Engineering Report

**Project:** Robust Digital Communication & Signal Recovery Simulator  
**Milestone:** M2 — Sampled Waveform & Matched Filtering  
**Status:** M2 implementation, automated verification, controlled BER sweep, diagnostics, and plots are complete. M2 is ready for review. M3 has not been started.

## A. Executive summary

M2 extends the accepted M1 reference link into a real, oversampled BPSK waveform chain. It adds a readable finite RRC coefficient generator with singularity limits and unit-energy normalization, zero-insertion upsampling, full linear transmit pulse shaping, a time-reversed matched filter, computed filter delays, validated symbol-rate sample indices, and a waveform receiver. Existing M1 behavior and tests remain usable.

The default M2 profile is `sps=8`, roll-off `β=0.35`, and span `10` symbols. This produces 81 taps; each filter delay is 40 samples, the total delay is 80 samples, and payload decisions occur at `80 + 8k`. The transmit/receive cascade has a unit main sample and measured finite-filter symbol-spaced sidelobes: maximum absolute sidelobe `0.00581657`, sum of absolute sidelobes `0.02036431`.

The final full test suite reports **30 passed in 2.78 s**, including M1 regressions. The five-point, 100,000-bit-per-point waveform sweep decreases overall with `Eb/N0`. Four of the five displayed pointwise 95% intervals contain theory; the 4 dB point is slightly above theory and its unadjusted 95% interval does not contain it. All five points contain theory in exact 99% intervals, a conservative Bonferroni check giving at least 95% family-wise coverage for this five-point sweep. That statistical qualification and two exploratory 4 dB follow-ups are documented below.

## B. Initial repository and environment

- **Project path:** project root (portable relative paths).
- **OS/Python:** Windows 10 build 22631; Python 3.11.5.
- **Project-local packages:** NumPy 2.4.6, SciPy 1.17.1, Matplotlib 3.11.2, pytest 9.1.1.
- **Git:** Git is installed, but this workspace is not a Git repository; no branch or worktree status is available.
- **Starting state:** M1 source, tests, README, design documents, and M1 report/results existed. They were inspected and preserved. Existing M1 test file and M1 result artifacts were not removed or weakened.
- **Dependencies:** M2 uses only the existing NumPy, SciPy, Matplotlib, and pytest dependencies. The M2 CLI entry point was registered in the existing `pyproject.toml`; no new external dependency was added.

The six approved design documents were read. The approved sampled-waveform convention matches the implementation request: real BPSK, RRC transmit/receive filters, unit-energy taps, full convolution, and discrete sample noise variance `Eb/(2γb)`. The prompt permits choosing documented defaults; M2 uses its suggested `sps=8`, `β=0.35`, and span 10. Zero roll-off is explicitly rejected as allowed by the specification. No mathematical conflict with M1 was found.

## C. Architecture and implementation

### Files added or changed

- `src/signalshield/config.py` — added validated `WaveformConfig` with defaults, tap-count property, individual delay, and total equal-filter delay; existing `SimulationConfig` remains unchanged.
- `src/signalshield/filters.py` — analytic RRC taps, group-delay validation, full matched filtering, sample-index validation, and symbol sampling.
- `src/signalshield/waveform.py` — zero-insertion upsampling and full-convolution transmit pulse shaping.
- `src/signalshield/receiver.py` — added `WaveformReceiverOutput` and matched-filter/delay/sample/detect pipeline; M1 `detect_bpsk` behavior is unchanged.
- `src/signalshield/__init__.py` — exports M2 interfaces while retaining M1 exports.
- `src/signalshield/plotting.py` — added actual M2 pulse/time/frequency/matched-filter diagnostic plots; existing M1 plot API remains compatible.
- `src/signalshield/waveform_experiments.py` — fixed-seed M2 sweep, residual-ISI measurements, diagnostic data output, M2 artifact writer, and CLI.
- `pyproject.toml` — registered `signalshield-m2` console entry point.
- `tests/test_filters.py`, `tests/test_waveform.py`, `tests/test_waveform_receiver.py`, `tests/test_waveform_experiments.py` — M2 coverage. Existing `tests/test_baseline.py` was preserved.
- `README.md` — added M2 model, usage, artifacts, and scope status.
- `docs/m2_waveform_model.md` — implementation-specific mathematical conventions and indexing.
- `reports/M2_engineering_report.md` — this report.
- `results/m2/` — BER results, seeds/configuration, raw taps/combined response/waveform diagnostics, six plots, test log, main experiment log, and two follow-up logs/artifact sets.

### M2 interfaces

- `WaveformConfig(samples_per_symbol=8, rolloff=0.35, span_symbols=10)`
- `rrc_taps(rolloff, span_symbols, samples_per_symbol)`
- `upsample_symbols(symbols, samples_per_symbol)`
- `pulse_shape(symbols, taps=None, *, samples_per_symbol, rolloff, span_symbols)`
- `matched_filter(samples, transmit_taps)`
- `filter_group_delay_samples(taps)`
- `symbol_sample_indices(n_symbols, samples_per_symbol, total_delay_samples, filtered_length)`
- `sample_symbols(filtered_samples, *, n_symbols, samples_per_symbol, total_delay_samples)`
- `receive_bpsk_waveform(received_waveform, transmit_taps, *, n_symbols, samples_per_symbol)`
- `run_waveform_ber_sweep(...)`, `write_waveform_results(...)`, and `signalshield-m2`

The waveform receiver returns the full matched-filter output, actual sample indices, sampled decisions, and detected bits. Processing modules validate dimensions, finite real values, RRC parameters, group-delay assumptions, and output bounds.

## D. Mathematical model and conventions

### RRC coefficients

For normalized symbol time `t` and `β∈(0,1]`, the implementation evaluates

`h(t) = [sin(πt(1−β)) + 4βt cos(πt(1+β))] / [πt(1−(4βt)^2)]`.

The singular values are handled explicitly:

- At `t=0`: `h(0)=1+β(4/π−1)`.
- At `t=±1/(4β)`: `(β/√2)[(1+2/π)sin(π/(4β))+(1−2/π)cos(π/(4β))]`.

For span `L` and samples/symbol `s`, `Nh=L*s+1`. Samples cover `[-L/2,+L/2]` in steps of `1/s` symbol periods. The implementation requires `L*s` even, producing an odd tap count and integer-centered group delay. The finite tap vector is normalized by `h ← h/sqrt(sum(h**2))`. The response is symmetric, finite, and has unit discrete-time energy. It is a truncated approximation to an ideal infinite-duration RRC response, not a mathematically exact infinite pulse.

### Upsampling, convolution, and delay

For `Nsym` symbols, zero insertion places symbol `a[k]` at sample `k*s`. The upsampled length is `(Nsym−1)*s+1`; it does not repeat symbols. Transmit pulse shaping uses full linear convolution, so the output length is `(Nsym−1)*s+Nh`.

The matched receive impulse response is `h_MF[n]=h[Nh−1−n]`. It also uses full linear convolution. For the default `Nh=81`:

```text
Tx delay Dtx = (81−1)/2 = 40 samples
Rx delay Drx = (81−1)/2 = 40 samples
Total decision delay = Dtx + Drx = 80 samples
Payload sample index k = 80 + 8k
```

The implementation derives this from the actual filter lengths and verifies that the final requested sample index is inside the filtered output. No circular convolution, wraparound, or implicit edge trimming is used.

### Noise normalization

For unit-energy BPSK, `Eb=1`, `γb=10^(EbN0_dB/10)`, and the real waveform sample noise variance is

`σ²_sample = Eb/(2γb)`.

The channel reuses M1 `add_awgn` with this variance and an explicit NumPy `Generator`. The matched-filter output-noise variance is

`σ²_MF = σ²_sample * sum(h_MF[n]²) = σ²_sample`,

because the matched filter has the same unit-energy taps. No factor of `sps` is added. This is the approved normalized discrete-time baseband convention; it is not an absolute continuous-time PSD, anti-alias filter, or ADC noise claim.

### Finite-filter residual ISI

The combined response is the convolution of `h` with its time reverse. Its main sample is exactly `1.0` to numerical precision. For the default taps, symbol-spaced offsets `−10..+10` produce a maximum absolute sidelobe of `0.0058165683` and sum of absolute sidelobes `0.0203643092`. Those values are stored in the JSON metadata and raw response CSV. This is small residual ISI, not exact zero ISI. The seeded 1,001-symbol noiseless integration test recovers every bit; its sampled decisions differ from the isolated-symbol values by no more than the measured aggregate sidelobe bound.

## E. Tests and regression outcomes

Final command:

```text
.\.venv\Scripts\python.exe -m pytest -q
..............................                                           [100%]
30 passed in 2.78s
```

The final output is saved at [results/m2/test_run.txt](../results/m2/test_run.txt). This command includes the 11 existing M1 tests plus M2 tests; all pass. The M1 source and test implementation were not modified. The test suite covers:

- RRC tap count, symmetry, finiteness, unit energy, delay, `t=0` and nonzero singular limits, and invalid configuration.
- Zero-insertion values, symbol indices, length, invalid values, and full-convolution pulse-shaping dimensions.
- Matched-filter coefficients, full convolution, cascade main amplitude and measured residual symbol-spaced sidelobes.
- Default sample indices, full filtered output length, payload count, and zero-noise recovery for a deterministic 1,001-bit sequence.
- Matched-filter noise mean/variance for 20,000 symbol decisions using a six-standard-error acceptance band.
- A 100,000-bit waveform BER comparison at 5 dB using a 99% exact binomial interval.
- CSV/JSON and all six plots produced by the M2 writer.
- All original M1 configuration, mapping, AWGN, detector, BER, theory, reproducibility, and statistical tests.

The captured matched-noise diagnostic used seed `99012`, 20,000 symbols, and `Eb/N0=4 dB`. It measured output mean `−0.00086352` and output variance `0.20202755`, against configured variance `0.19905359`; the difference is within the test's six-standard-error tolerance. The sample diagnostic and tap calculations are saved in [m2_model_diagnostics.json](../results/m2/m2_model_diagnostics.json).

The M2-specific 5 dB statistical test uses a separate deterministic stream and passed: the 99% Clopper–Pearson interval from the observed waveform errors contains the theoretical BPSK/AWGN probability. The exact count is reproducible by the test in `tests/test_waveform_experiments.py`.

## F. Controlled waveform BER experiment

### Settings

- `sps=8`, `β=0.35`, span `10`, `Nh=81`.
- `Eb=1`, fixed `100,000` bits at each point.
- Sweep `Eb/N0={0,2,4,6,8} dB`.
- Master seed `20261028`; `SeedSequence` derives independent bit/noise seeds per point and a separate diagnostic waveform pair. Seeds are saved in JSON/CSV.
- No adaptive stopping.
- CSV reports pointwise 95% exact Clopper–Pearson intervals. Zero-error output, if any, would retain `0/N` and separately report a one-sided bound.

Reproduction command:

```powershell
.\.venv\Scripts\python.exe -m signalshield.waveform_experiments --n-bits 100000 --seed 20261028 --ebn0-db 0 2 4 6 8 --samples-per-symbol 8 --rolloff 0.35 --span-symbols 10 --output-dir results/m2
```

### Main sweep results

| Eb/N0 (dB) | Errors / bits | Simulated BER | Theory BER | Pointwise exact 95% interval | Theory in 95% interval? |
|---:|---:|---:|---:|---:|---|
| 0 | 7,730 / 100,000 | 0.07730 | 0.0786496 | [0.0756520, 0.0789726] | Yes |
| 2 | 3,835 / 100,000 | 0.03835 | 0.0375061 | [0.0371682, 0.0395587] | Yes |
| 4 | 1,334 / 100,000 | 0.01334 | 0.0125008 | [0.0126381, 0.0140704] | No; measured BER is higher |
| 6 | 234 / 100,000 | 0.00234 | 0.00238829 | [0.00205005, 0.00265939] | Yes |
| 8 | 18 / 100,000 | 0.00018 | 0.000190908 | [0.000106683, 0.000284463] | Yes; relative uncertainty is large |

Because this is a five-point sweep, I also checked exact 99% pointwise binomial intervals. These give at least 95% family-wise coverage by a Bonferroni bound (`α=0.01` per point); theoretical BER is inside all five. The computed intervals and containment flags are saved in [m2_ber_99pct_sweep_check.csv](../results/m2/m2_ber_99pct_sweep_check.csv). The 4 dB point is therefore not a failure under that conservative sweep-level check, but its exclusion from the ordinary pointwise 95% interval remains a real observation and is not hidden in the plot or CSV.

The main curve decreases overall as `Eb/N0` increases. It is not strictly monotone at every finite-sample point relative to theory. At 8 dB only 18 errors were observed, so relative uncertainty is high. Theoretical BER assumes an ideal Nyquist pulse pair; this implementation uses a finite RRC and has measured residual ISI. The observed 4 dB excursion prompted additional fixed-seed diagnostic runs:

| Diagnostic run | Bits | Errors | BER | Pointwise 95% interval | Theory in interval? |
|---|---:|---:|---:|---:|---|
| Master seed 424242, 4 dB | 1,000,000 | 12,791 | 0.012791 | [0.0125717, 0.0130132] | No |
| Master seed 777001, 4 dB | 1,000,000 | 12,660 | 0.012660 | [0.0124418, 0.0128810] | Yes |

These follow-ups are exploratory because they were initiated after noticing the original 4 dB excursion; I do not pool them post hoc or treat them as a predeclared acceptance experiment. They show that individual finite runs can vary around this low BER and that the discrepancy deserves caution. Mathematical checks independently confirm the configured noise variance, matched-filter output variance tolerance, unit main-lobe gain, correct timing, and zero-noise recovery. The final report does not claim that every pointwise 95% comparison passed.

## G. Results, plots, and artifact locations

Main experiment data/configuration:

- [BER rows and confidence intervals](../results/m2/m2_ber_results.csv)
- [99% exact intervals for the conservative sweep-level comparison](../results/m2/m2_ber_99pct_sweep_check.csv)
- [Configuration, derived seeds, timing, response and software versions](../results/m2/m2_experiment_config.json)
- [Measured sample-noise and filter diagnostics](../results/m2/m2_model_diagnostics.json)
- [Tap coefficients](../results/m2/m2_rrc_taps.csv)
- [Combined symbol-spaced response](../results/m2/m2_combined_symbol_response.csv)
- [Diagnostic Tx/Rx/matched-filter samples and decision flags](../results/m2/m2_diagnostic_waveforms.csv)
- [Main sweep console output](../results/m2/experiment_run.txt)
- [Final full-suite output](../results/m2/test_run.txt)
- [4 dB follow-up seed 424242 output and data](../results/m2/followup_4db_run.txt), [files](../results/m2/followup_4db)
- [4 dB follow-up seed 777001 output and data](../results/m2/followup_4db_seed777001_run.txt), [files](../results/m2/followup_4db_seed777001)

Six actual plots are saved:

1. [RRC impulse response](../results/m2/m2_rrc_impulse.png)
2. [RRC one-sided frequency response](../results/m2/m2_rrc_frequency.png)
3. [Pulse-shaped transmit waveform](../results/m2/m2_tx_waveform.png)
4. [Received waveform at 4 dB with AWGN](../results/m2/m2_awgn_received_waveform.png)
5. [Matched-filter output with payload sample instants](../results/m2/m2_matched_filter_decisions.png)
6. [M2 simulated BER and theoretical reference](../results/m2/m2_ber_plot.png)

The diagnostic time plots use the seeded 16-symbol waveform recorded in the JSON metadata and raw diagnostic CSV. The BER plot uses the five actual sweep outcomes; it does not smooth, replace, or invent measured data.

## H. Failures, limitations, and deviations

- **4 dB pointwise interval:** the main sweep's 4 dB estimate is above theory and outside its unadjusted pointwise 95% interval. It is inside the sweep-wide Bonferroni 95% check based on 99% per-point intervals. Two exploratory 1,000,000-bit reruns gave mixed pointwise 95% outcomes. This is fully reported; the measured result is not passed off as an exact theory match.
- **Finite pulse:** span-10 truncation leaves measured symbol-spaced sidelobes. No claim of exact zero ISI is made.
- **High-SNR precision:** at 8 dB the main sweep observed 18 errors; a larger bit budget would be needed for a narrower relative uncertainty. No zero-error case occurred in the main M2 sweep.
- **Noise diagnostic:** a 20,000-decision sample variance fluctuates by about 1.5% from its configured value, within its declared six-standard-error bound. Noise variance derivation is also verified analytically from unit receive-filter energy.
- **Physical interpretation:** the noise model is normalized discrete-time real baseband, not a continuous-time PSD/ADC model.
- **Future scope:** no M3 attenuation/tone/fading channel components, M4 notch receiver, complex modulation, timing recovery, FEC, or M5 experiment framework is implemented.
- **Git metadata:** the workspace is not a Git repository, so branch/commit status cannot be reported.
- **Deviations:** M2 follows the approved architecture and prompt defaults. A dedicated `docs/m2_waveform_model.md` was added to record the realized conventions. No M1 mathematical or interface behavior was intentionally changed.

## I. Reproduction instructions

From the project root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m signalshield.waveform_experiments --n-bits 100000 --seed 20261028 --ebn0-db 0 2 4 6 8 --samples-per-symbol 8 --rolloff 0.35 --span-symbols 10 --output-dir results/m2
```

The installed CLI alternative is `signalshield-m2` with the same options. I executed the M2 module command, installed the editable package and entry point, checked dependencies with `pip check`, smoke-tested `signalshield-m2 --help`, ran the full pytest suite, ran the main sweep and both follow-ups, and inspected the generated plots. Python/package versions are in the experiment JSON.

## J. M2 acceptance matrix

| Criterion | Verification | Actual outcome | Status |
|---|---|---|---|
| M1 source and conventions inspected; approved documents read | Workspace/source/document inventory | M1 interfaces and design preserved; no mathematical conflict found | PASS |
| M1 public behavior remains usable | Full `pytest -q` including original tests | Existing M1 tests pass as part of 30-test suite | PASS |
| RRC formula and singularities implemented | Formula test for `t=0` and `t=±1/(4β)` at `β=0.25`; finite/symmetry tests | Correct normalized coefficients; zero roll-off and invalid settings rejected | PASS |
| Tap length, symmetry, energy and delay | Default configuration and filter tests | 81 taps, symmetric, energy 1.0, per-filter delay 40 | PASS |
| Upsampling locations and length | Exact zero-insertion test | Symbols at `0,s,2s,...`; length `(Nsym−1)s+1` | PASS |
| Pulse-shaped Tx dimensions and convolution | Full-convolution test | Length `(Nsym−1)s+Nh`; all finite | PASS |
| Matched-filter coefficients and full convolution | Independent filter test | Uses reversed taps and preserves tails | PASS |
| Total delay and payload sample indices | 1,001-symbol noiseless integration | Delay 80; indices `80+8k`; all 1,001 bits recovered | PASS |
| Main lobe and finite residual ISI measured | Cascade response test and saved CSV/JSON | Main 1.0; max sidelobe 0.00581657; absolute sidelobe sum 0.02036431 | PASS |
| AWGN variance and matched-filter variance | Analytic derivation, seeded 20,000-symbol statistical test and saved diagnostic | Configured sample variance 0.19905359 at 4 dB; measured filtered variance 0.20202755 within 6-SE acceptance | PASS |
| Waveform BER experiment executed and compared with theory | Five-point sweep; exact intervals; 99% sweep-level check | BER trends down; all 5 theories inside conservative 99% pointwise intervals; one 4 dB point outside ordinary 95% CI and disclosed | PASS WITH STATISTICAL CAVEAT |
| Required six plots and numerical data saved | Result directory inventory and visual inspection | All six plots, BER/config, raw taps/ISI and diagnostic waveform data exist | PASS |
| Full test suite run and recorded | `.venv\Scripts\python.exe -m pytest -q` | 30 passed in 2.78 s, no warnings | PASS |
| M2 CLI and dependencies | Editable install, `pip check`, `signalshield-m2 --help` | No broken requirements; CLI displays correct options | PASS |
| No M3 or later scope started | Source tree and README/report inspection | No gain/tone/fading or notch receiver work added | PASS |

## K. الشرح الهندسي بالعربية

### ما الذي أُضيف؟

وسّعت المسار من عينة واحدة لكل bit إلى `sampled waveform`. يبدأ النظام بتوليد bits ثم تحويلها إلى رموز BPSK. يضع `upsampler` كل رمز عند عينة تفصلها `8` عينات عن الرمز التالي، ويضع أصفارًا في العينات الواقعة بين الرموز؛ لا يكرر الرمز ثماني مرات. بعد ذلك يمرر الإشارة عبر مرشح `RRC` قصير ومتماثل، ثم يضيف AWGN حقيقية، ويمرر الإشارة المستقبلة عبر `matched filter`. يعوض المستقبل تأخير المرشحين ويأخذ عينة واحدة عند كل زمن رمز، ثم يستخدم قرار BPSK نفسه من M1.

### المرشح والتوقيت

لأن span يساوي `10` رموز و`sps=8`، يبلغ عدد tap `10×8+1=81`. طاقة tap بعد التطبيع تساوي `1`. تأخير كل FIR متماثل يساوي `(81−1)/2=40` عينة، فيكون التأخير الكلي `80` عينة. لذلك موقع قرار الرمز `k` هو `80+8k`. نستخدم `full linear convolution` لنحتفظ ببدايات ونهايات المرشح ولا نخفي مشكلة توقيت بحذف العينات.

### التطبيع والضوضاء

تطبيع `RRC` إلى طاقة `1` يجعل سعة العينة الرئيسية بعد مرشح الإرسال والاستقبال `1`. إذا كانت `gamma_b=10^(Eb/N0_dB/10)`, فإن variance ضوضاء كل عينة حقيقية هو `Eb/(2 gamma_b)`. يضرب مرشح الاستقبال الضوضاء بعينة tap متجهة، لذا تصبح variance عند خرج المرشح `sigma² × sum(h_MF²)`. وبما أن طاقة المرشح `1`، تبقى variance كما هي؛ لا نضرب أو نقسم على `sps`.

### الالتباس بين ideal filter والمرشح المحدود

مرشح `RRC` المثالي غير محدود المدة. المرشح البرمجي يقتطع استجابته إلى 81 tap، لذلك لا تكون sidelobes عند أزمنة الرموز صفرًا تمامًا. بلغ أكبر مقدار جانبي مقاس `0.0058166`، ومجموع المقادير الجانبية `0.0203643` مقابل عينة رئيسية `1.0`. سلسلة الاختبار بلا ضوضاء استعادت 1,001 bit بلا أخطاء، لكن ذلك لا يعني أن `ISI` يساوي صفرًا رياضيًا.

### ماذا تقول نتائج BER؟

نفذت خمس نقاط `Eb/N0`، كل نقطة 100,000 bit. ينخفض معدل الخطأ عمومًا مع ارتفاع `Eb/N0`. عند `4 dB` كانت النسبة المقاسة `0.01334`، أعلى من النظرية `0.0125008` وخارج فاصلها النقطي 95%. لم أخفِ ذلك؛ فحصت أيضًا فواصل exact 99% لجميع نقاط sweep، وكانت النظرية ضمن كل منها، كما نفذت نقطتي متابعة عند 4 dB بميزانية مليون bit لكل منهما. اختلفت نتيجة 95% بين المتابعتين، لذلك أتعامل معها كدليل على تفاوت القياس وحاجته للحذر، لا كإثبات تحسين أو تطابق كامل. الميزانية عند `8 dB` أعطت 18 خطأ فقط، لذا عدم اليقين النسبي أكبر.

### ما الذي لم يُنفذ؟

لم أضف بعد gain أو fading أو tone interference أو مرشح notch؛ هذه وظائف M3/M4. كما أن هذا النموذج لا يحاكي PSD فيزيائية أو ADC أو مزامنة توقيت. الخطوة التالية بعد مراجعة M2 هي M3، وليس جزءًا من هذا التنفيذ.

## L. Readiness for M3

M2 is ready for review. The sampled waveform, transmit shaping, matched filtering, computed delay and symbol sampling, unit-energy noise normalization, residual-ISI measurements, M1 regressions, controlled BER sweep, numerical data, and required plots are implemented and tested. The 4 dB pointwise 95% excursion is disclosed and does not pass as an ordinary 95% pointwise theory match; the conservative sweep-level 99% check passes, and follow-ups are recorded as exploratory. After reviewing that evidence and caveat, the waveform interface provides a sound base for M3 channel components. **M3 has not been started.**

