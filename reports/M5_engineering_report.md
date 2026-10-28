# SignalShield M5 Engineering Report

**Milestone:** M5 — Experimental Framework & Performance Analysis  
**Status:** Implemented; tested; all seven configured scenarios completed  
**Scope boundary:** M6 has not been started  
**Report date:** 2026-10-28

## 1. Executive summary

M5 adds a common, reproducible experiment layer to the existing SignalShield M1–M4 simulation code. It defines a validated configuration and measurement record, deterministic seed derivation, a reusable runner and CLI, exact binomial BER intervals, paired receiver statistics, repeat-run summaries, CSV/JSON outputs, manifests, execution logs, and standard plots. It integrates the existing M1 reference chain, M2 waveform chain, M3 channel conditions, and M4 baseline/notch receiver paths; it does not introduce channel impairments or receiver algorithms.

The configured suite ran seven scenarios with 10,000 bits per run, two repetitions, and master seed `20261031`. All points completed: 82 successful receiver measurement rows and zero failed points. A separate replay of the saved receiver comparison configuration reproduced all non-runtime numerical output exactly, including per-bit outcomes and paired summaries. The complete current test suite passed: **74 passed**.

The results show the expected qualitative patterns for this finite run: AWGN BER fell as Eb/N0 increased; baseline BER rose with tone amplitude; attenuation increased BER; and the notch receiver substantially reduced BER for the matched 0.35 cycles/symbol tone. Frequency mismatch was consequential: the notch helped near its configured center and hurt at some offsets. The mismatch sweep is exploratory and does not establish a simultaneous, familywise claim. Two repetitions are too few for reliable estimation of run-to-run variability; aggregate t-intervals are shown for transparency and are not treated as strong evidence.

## 2. Repository and environment inspection

The existing project was inspected before M5 changes. The implementation reuses:

- `signals.py`, `modulation.py`, and the M1 AWGN experiment for bit generation, BPSK mapping, detection, and theory;
- `waveform.py`, `filters.py`, and `receiver.py` for the M2 sampled waveform, RRC filtering, matched filtering, and delay-aware decisions;
- `channel.py` for M3 AWGN, tone, and signal-only attenuation;
- `notch.py` and `m4_experiments.py` for the M4 notch and paired receiver processing;
- existing `metrics.py` functions, extended with a common paired-BER estimate.

The approved design, validation, implementation, handoff, learning, and report-template documents were read, along with the M1–M4 reports, code, tests, and saved outputs. No prior M1–M4 results were overwritten. This workspace is not a Git repository, so there is no Git diff/history to report.

Recorded environment from the suite manifest:

| Component | Version |
|---|---:|
| Python | 3.11.5 |
| NumPy | 2.4.6 |
| SciPy | 1.17.1 |
| Matplotlib | 3.11.2 |
| pytest | 9.1.1 |

## 3. Existing experiment capability audit

Before M5, M1 through M4 each had their own experiment scripts and result conventions. M1 measured BPSK/AWGN against coherent theory; M2 ran an oversampled pulse-shaped waveform; M3 varied tone amplitude, tone frequency, and attenuation; M4 compared baseline and offline notch receivers and already included paired comparisons and block resampling. Their shared responsibilities—configuration, seeds, BER records, uncertainty, plotting, and outputs—were not represented by one common runner.

M5 leaves those established scripts available for backward-compatible use. The new runner calls their existing algorithms and configuration types rather than duplicating signal-generation, channel, filter, receiver, or theory implementations. The M4 comparison routine continues to deliver both receivers the same realized received waveform. The M5 record layer adds a uniform representation around these paths.

## 4. Configuration, result schema, and persistence

### Configuration

`ExperimentConfig` is an immutable validated dataclass in `src/signalshield/experiment_framework.py`. It includes experiment identity and scenario; bit count; master seed; repetition count; fixed Eb/N0 or sweep values; samples/symbol, RRC rolloff and span; attenuation and tone parameters; notch center and Q; confidence level; primary and alternate bootstrap block lengths; bootstrap replicate count; per-bit output selection; and output directory. It uses the existing `WaveformConfig` and `NotchConfig` validators.

Configuration JSON uses lists for sweep fields and round-trips through `from_dict`/`load_json`. Unknown keys, missing required identity fields, invalid ranges, malformed sweep definitions, unsupported scenarios, and invalid waveform/notch settings are rejected with explicit errors. The semantic `configuration_id` is the first 16 hex characters of SHA-256 over canonical JSON, excluding only `output_dir`; moving an experiment's destination therefore does not change its semantic identifier.

### Result records

Each `ExperimentRecord` corresponds to one receiver at one sweep point and repetition. The CSV preserves raw `n_bits` and `errors` as well as BER, point index/value/parameter, receiver and scenario names, config ID, master/derived seeds, nominal/effective Eb/N0, waveform and channel parameters, configured and measured noise variance, power diagnostics, theory applicability/note, exact confidence bounds, zero-error upper bound, familywise-adjusted bounds, paired metrics, runtime, execution status, and failure note.

Unavailable quantities are saved as empty CSV fields / JSON null-like values; failure rows carry no fabricated BER or count. Per-run records are never replaced by a merged count. The runner also writes `aggregate_summary.csv`, `paired_summary.csv`, `execution_log.txt`, a `manifest.json`, and applicable plots. Fixed receiver comparisons additionally save `paired_per_bit_outcomes.csv` when enabled. The top-level suite writes `suite_manifest.json` and captures stdout in `suite_run.txt`.

## 5. Seed and reproducibility strategy

`derive_seed` computes a stable 32-bit seed from the text tuple `(master seed, experiment ID, repetition, role, condition key)` using SHA-256. Separate roles distinguish the transmitted bits, AWGN, and paired bootstrap. This mapping is independent of experiment execution order and does not use NumPy global random state. Each generator is an explicit `numpy.random.default_rng(derived_seed)`.

All points in a repetition share the generated bit sequence. For AWGN Eb/N0 sweeps, the noise seed is condition-specific, so each SNR receives its own noise realization. For channel sweeps, the same noise stream is used across sweep points in a repetition to support controlled comparisons. In receiver-comparison scenarios, baseline and notch process the same received array generated from that repetition's bits, noise, and tone. Bootstrap block lengths derive stable child streams from the recorded bootstrap seed.

Reproduction was verified by loading `results/m5/receiver_comparison/resolved_config.json`, directing output to `results/m5/reproduction_check`, and comparing CSV rows. `results.csv` matched in every field except `runtime_seconds`; `aggregate_summary.csv`, `paired_summary.csv`, and `paired_per_bit_outcomes.csv` matched exactly. Both run manifests used configuration ID `1ae6d6f0901dd215`. Runtime is expected to vary with machine load and is not a simulated outcome.

## 6. Runner architecture and commands

`src/signalshield/experiment_runner.py` owns scenario dispatch, seed injection, per-run records, aggregation, artifact writing, and plotting. `run_experiment(ExperimentConfig)` is the Python API. `run_default_suite` dispatches the full named suite. The CLI accepts scenario selection, bit count, repetitions, master seed, output directory, or a saved config. Config replay rejects conflicting parameter overrides rather than quietly changing the resolved experiment. `signalshield-m5` was added as the installed console entry point.

Full suite command used:

```powershell
.\.venv\Scripts\python.exe -m signalshield.experiment_runner --scenario all --n-bits 10000 --repetitions 2 --seed 20261031 --output-dir results/m5
```

Saved-config replay command used:

```powershell
.\.venv\Scripts\python.exe -m signalshield.experiment_runner --config results/m5/receiver_comparison/resolved_config.json --output-dir results/m5/reproduction_check
```

For one scenario, replace `all` with one of the supported names. `--help` lists the actual CLI flags. The moderate suite workload is explicit; larger bit counts and repetition counts can be requested through the same interface.

## 7. Supported scenarios

| Scenario | Reused path | Main sweep or condition | Theory handling |
|---|---|---|---|
| `awgn_reference` | M1 BPSK/AWGN | Eb/N0 = 0, 2, 4, 6, 8 dB | Coherent uncoded BPSK/AWGN reference |
| `waveform_awgn` | M2 RRC waveform and matched filter | Eb/N0 = 2, 4, 6, 8 dB | AWGN reference; finite RRC and burst effects remain model limits |
| `interference_amplitude` | M3 tone channel and M2 baseline receiver | Peak amplitude = 0, .08, .16, .22, .30, .42 | No AWGN-only theory while tone is present |
| `interference_frequency` | M3 tone channel and M2 baseline receiver | 0.15, .35, .70, 1.10, 1.60 cycles/symbol | No AWGN-only theory while tone is present |
| `attenuation` | M3 signal-only attenuation and M2 receiver | 0, 2, 4, 6, 8 dB | AWGN theory at configured Eb/N0 minus attenuation |
| `receiver_comparison` | M4 paired baseline/notch paths | Matched tone at .35 cycles/symbol; Q=30 | No exact theory assigned to altered receiver response |
| `frequency_mismatch` | M4 paired paths with tone sweep | Actual tone .31, .33, .34, .35, .36, .37, .39 cycles/symbol; notch center .35 | No exact AWGN-only theory while tone is present |

No scenario or algorithm outside the existing M1–M4 functionality was added. The original standalone M1–M4 command lines remain available.

## 8. BER, confidence bounds, and theory

For each receiver, the runner stores `errors`, `n_bits`, and `BER=errors/n_bits`. `ber_estimate` computes the two-sided Clopper–Pearson exact binomial confidence interval using beta quantiles. The interval assumes independent Bernoulli trials with a constant error probability within the run; pulse shaping and filtering can introduce dependence, so its nominal coverage is most straightforward for the M1 memoryless link. It remains a standard per-run descriptive interval for the other models and should be read with that caveat.

Zero errors remain exactly `0/N`; they are not changed to an arbitrary plotting value. A separate one-sided 95% zero-error upper bound, `1 - 0.05**(1/N)`, is recorded. All-error runs, low error counts, malformed input lengths, and invalid confidence levels are handled explicitly by tests. Plots mark zero-error observations at their separate upper bound.

The coherent BPSK reference `0.5*erfc(sqrt(10**(EbN0_dB/10)))` is included only for the applicable uncoded BPSK/AWGN receiver. For attenuation-only scenarios, effective Eb/N0 is nominal Eb/N0 less signal attenuation in dB. Interference-bearing runs do not receive an AWGN-only curve, and the notch receiver is not given an exact AWGN theory because its signal/noise response differs.

For an experiment's displayed exact intervals, the runner also uses a Bonferroni allocation across `number of sweep points × repetitions × receiver rows`, recording `familywise_confidence_level` and corresponding bounds. This is a conservative per-experiment simultaneous coverage adjustment for that defined family; it does not correct the paired bootstrap intervals or create a preplanned hypothesis test.

## 9. Paired comparison and uncertainty

The M5 paired utility receives transmitted bits plus each receiver's decision array. It stores candidate-minus-baseline BER difference, corrected errors (baseline wrong/candidate right), introduced errors (baseline right/candidate wrong), shared errors, and unchanged decisions. The paired bootstrap resamples contiguous blocks of the per-bit error-indicator difference. The primary block length is 50; an alternate length of 100 is also calculated using 1,000 replicates. This retains short-range dependence better than independently resampling bits, although no finite block length guarantees coverage for every dependence structure. The saved seed makes the bootstrap reproducible.

An exact McNemar test is retained as a reference statistic, but its independence assumption for discordant bit pairs can be weakened by pulse shaping and filtering. It is therefore not used alone to establish receiver superiority. The two block-length intervals and per-run difference remain visible. For the main matched-tone run, primary 50-bit bootstrap intervals were [-0.030105, -0.023700] and [-0.030200, -0.022600] across the two repetitions; 100-bit intervals were [-0.030100, -0.023800] and [-0.030703, -0.022500]. These are consistent in this run with a substantial negative paired difference.

Run-to-run summaries are different: `aggregate_summary.csv` gives the mean and sample standard deviation of per-run BER, with a t interval over independent repetitions. `paired_summary.csv` similarly summarizes paired deltas over repetitions. These intervals do not replace the per-run binomial or block-bootstrap intervals. With only two repetitions, the t interval has one degree of freedom, is highly sensitive to the individual runs, and cannot support strong population-level inference. Identical deltas can yield a degenerate interval; this is not proof of zero run variability.

## 10. Multiple comparisons and analysis status

The suite sweeps multiple SNRs, amplitudes, frequencies, and attenuations. Bonferroni-adjusted exact BER bounds are available for the declared family above; they are conservative. Paired-bootstrap intervals are pointwise and not multiplicity-adjusted. In particular, the mismatch sweep was exploratory, and conclusions seen after inspecting it are not framed as preplanned tests or as familywise significance claims. Two independent repeats are not sufficient to characterize the run-seed distribution. A larger planned study should increase both bits and repetitions before making inferential claims.

## 11. Actual experiments and numerical results

Command parameters: 10,000 bits per run, two repetitions, master seed `20261031`, nominal Eb/N0 6 dB for channel sweeps, 8 samples/symbol, RRC rolloff .35/span 10, 0.22 peak tone, phase 0.37 rad, notch center .35 cycles/symbol, Q=30, 95% confidence, block lengths 50/100, 1,000 bootstrap replicates. All scenarios completed without failed points. There were 82 successful measurement rows across the suite: 10 M1, 8 M2, 12 amplitude, 10 frequency, 10 attenuation, 4 receiver-comparison, and 28 mismatch rows.

### Representative mean BER across the two repetitions

| Scenario | Condition | Mean BER | Interpretation |
|---|---:|---:|---|
| M1 AWGN | 0 dB | 0.07665 | BER falls with increasing SNR |
| M1 AWGN | 4 dB | 0.01200 | Finite-run Monte Carlo estimate |
| M1 AWGN | 8 dB | 0.00015 | Mean of 1 and 2 errors in the two runs |
| M2 waveform AWGN | 2 dB | 0.03905 | Pulse-shaped receiver path |
| M2 waveform AWGN | 8 dB | 0.00030 | Three errors total across the two runs |
| Tone amplitude | 0.00 | 0.00280 | AWGN-only control |
| Tone amplitude | 0.22 | 0.03215 | Baseline BER increases with this configured tone |
| Tone amplitude | 0.42 | 0.16860 | Strong tone significantly raises observed errors |
| Tone frequency | 0.35 cycles/symbol | 0.03150 | Tone near notch center also stresses baseline |
| Tone frequency | 0.70 cycles/symbol | 0.00220 | Frequency response matters; not monotonic |
| Attenuation | 0 dB | 0.00150 | Control at nominal 6 dB Eb/N0 |
| Attenuation | 4 dB | 0.03550 | Effective Eb/N0 is 2 dB |
| Attenuation | 8 dB | 0.12640 | Effective Eb/N0 is -2 dB |

### Paired receiver comparison

At the matched 0.35 cycles/symbol tone, baseline mean BER was 0.03095 and notch mean BER was 0.00430. Mean paired delta (notch minus baseline) was **-0.02665** across the two repetitions. Per-run deltas were -0.0269 and -0.0264. At the first repetition, the candidate corrected 289 baseline errors, introduced 20, and shared 14; at the second it corrected 293, introduced 29, and shared 23. The block-50 and block-100 intervals were similar in each repetition (shown above). This is evidence for this configured finite simulation, not a universal property of the receiver or an M6 qualification.

### Frequency mismatch

Mean paired deltas by actual tone frequency were:

| Tone frequency (cycles/symbol) | Mean notch-minus-baseline BER difference | Two-run t interval |
|---:|---:|---:|
| .31 | +.00780 | [-.00872, .02432] |
| .33 | +.00475 | [-.00605, .01555] |
| .34 | -.00810 | [-.01445, -.00175] |
| .35 | -.02755 | [-.04216, -.01294] |
| .36 | -.00890 | [-.02161, .00381] |
| .37 | +.00305 | [-.01156, .01766] |
| .39 | +.00620 | [.00620, .00620] * |

Positive differences mean the notch had higher BER in those paired runs. The per-run block bootstrap also showed an increase at .31, .33, and .39 and a reduction near .34–.36, with block-50 and block-100 intervals generally similar. `*` At .39, both repeated deltas happened to be identical, so the computed t interval collapses to one value; with two repetitions this is an artifact of the tiny sample, not evidence of no uncertainty. The exploratory sweep and pointwise methods do not provide a simultaneous familywise claim.

The complete raw measurements and confidence bounds are in each scenario's `results.csv`; the aggregate tables preserve run-level variability. These are actual simulation outcomes, not fixed expected values in the runner.

## 12. Plots and artifact locations

Each scenario folder contains `ber_by_condition.png` and `run_variability.png`. Paired scenarios also include `paired_ber_difference.png`. For example:

- M1: `results/m5/awgn_reference/ber_by_condition.png` — simulated/theoretical BER versus Eb/N0;
- M2: `results/m5/waveform_awgn/ber_by_condition.png` — pulse-shaped AWGN behavior;
- tone amplitude: `results/m5/interference_amplitude/ber_by_condition.png`;
- tone frequency: `results/m5/interference_frequency/ber_by_condition.png`;
- attenuation: `results/m5/attenuation/ber_by_condition.png`;
- paired matched tone: `results/m5/receiver_comparison/paired_ber_difference.png`;
- mismatch: `results/m5/frequency_mismatch/paired_ber_difference.png`.

The log BER plots distinguish theory from measured data where valid and use a separate marker for zero-error upper bounds. Repeated-run variability is represented from the actual run records. The two-repeat t error bars should be interpreted with the limitations described above. The suite manifest lists artifact paths, status, configuration IDs, counts, and library versions. The captured full suite output is `results/m5/suite_run.txt`.

## 13. Automated tests and M1–M4 regression

Complete command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Actual result: **74 passed in 6.04 seconds** (captured at `results/m5/test_run.txt`). This includes all pre-existing M1–M4 tests and 14 M5 tests covering config validation and JSON identity, deterministic seed derivation, BER edge conditions, paired counts and bootstrap repeatability, dispatch across all seven scenarios, output metadata and BER/count consistency, per-bit comparison output, saved-config reproduction, and failure recording. No earlier test was removed or weakened.

The CLI run also exercised all seven scenarios end-to-end and saved the expected artifacts. Injected runner failure tests confirm that a failed point has `execution_status=failed`, a failure note, and no fabricated measurement.

## 14. Reproducibility check

The saved receiver-comparison config was replayed using the command in §6 into `results/m5/reproduction_check`. Comparison result: **PASS**. The main results CSV matched exactly in all non-runtime fields. Aggregate summary, paired summary, and saved per-bit outcomes matched exactly. Runtime is excluded because it is inherently machine/load dependent. Bootstrap streams and configuration identity matched. The second execution completed all four receiver rows with zero failed points.

## 15. Limitations and deviations

- The suite used 10,000 bits and only two repetitions to keep execution modest. High-SNR estimates and repeat-level summaries therefore have limited precision; further repetitions and larger bit budgets are required for strong characterization.
- The Student t summary with `n=2` has one degree of freedom; a zero sample standard deviation creates a degenerate interval. Treat these summaries as descriptive only.
- Per-run Clopper–Pearson intervals assume independent, identically distributed bit errors. Filtering and finite-pulse effects may introduce dependence. Paired block bootstrap is used for receiver deltas, but block lengths 50 and 100 do not prove coverage under all dependence structures.
- McNemar's exact test assumes independent discordant pairs; filtered bit errors may violate that condition. Its p-value is recorded as a diagnostic rather than sole evidence.
- Paired bootstrap intervals are pointwise and not adjusted over the mismatch or other sweeps. The exact BER intervals have a Bonferroni adjustment for the documented per-experiment family.
- M5 retains historical scripts and outputs rather than migrating or rewriting M1–M4 files. This preserves validated work and means those historical outputs do not retroactively acquire M5's row schema.
- M1 reference rows explicitly record one sample per symbol. The shared config still contains the waveform defaults used by the other scenarios; the record prevents misreading M1 as an oversampled model.
- Plots show repeat-mean t intervals for run variability, not the per-run exact interval. Exact and familywise intervals remain in CSV. A zero-error observation can be shown at its upper bound to make the logarithmic plot readable; that marker is not a measured positive BER.
- This remains a normalized simulation; it is not a hardware receiver, physical channel calibration, security product, or real-time notch implementation.
- No M5 acceptance blocker remains. M6 packaging, final integration, delivery, and any GUI work were intentionally not started.

No substantive algorithm or channel model changes were made. The M5-specific extensions are limited to experiment orchestration, records, metrics, plots, persistence, tests, and documentation.

## 16. Exact reproduction instructions

From the project root in Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m signalshield.experiment_runner --scenario all --n-bits 10000 --repetitions 2 --seed 20261031 --output-dir results/m5
.\.venv\Scripts\python.exe -m signalshield.experiment_runner --config results/m5/receiver_comparison/resolved_config.json --output-dir results/m5/reproduction_check
.\.venv\Scripts\python.exe -m pytest -q
```

The first command writes the seven scenario result folders. The second replays the saved receiver-comparison experiment with the same semantic configuration; its output directory does not affect the configuration ID. The third reruns the tests. The environment versions are in `results/m5/suite_manifest.json`.

## 17. M5 acceptance matrix

| Acceptance criterion | Status | Evidence |
|---|---|---|
| Existing M1–M4 experiment functionality assessed and reused | PASS | Source audit; legacy CLIs preserved; runner imports existing channel, waveform, receiver, notch, and M4 comparison paths |
| Unified validated configuration and result model | PASS | `experiment_framework.py`; round-trip/validation tests; resolved JSON and uniform CSV |
| Supported experiments run through documented interfaces | PASS | Seven scenario suite command; all scenario manifests completed |
| Explicit deterministic seed handling | PASS | SHA-256 role/condition derivation and recorded bit/noise/bootstrap seeds |
| Raw counts, BER, uncertainty, and configuration metadata preserved | PASS | `results.csv`; BER/count identity integration assertions |
| Theory only used for valid channel/receiver assumptions | PASS | Applicability flags and theory notes; attenuation-adjusted Eb/N0 |
| Paired receivers use identical realized inputs | PASS | M4 paired call uses one generated `received` waveform; same-repetition seeds/bit stream |
| Run variability distinguished from per-run and paired uncertainty | PASS | Per-run exact intervals in raw CSV; separate between-run and paired summaries |
| Multiple-comparison limitations documented | PASS | Bonferroni BER family metadata; pointwise bootstrap and exploratory mismatch caveats |
| Numerical/visual outputs saved | PASS | Seven scenario folders, plots, CSV, JSON, logs, manifests |
| Reproducibility check actually performed | PASS | Exact CSV comparison, excluding runtime; reproduction directory and run log |
| Complete M1–M4 regression suite passes | PASS | `pytest -q`: 74 passed, including prior tests |
| New tests pass or failures explicitly reported | PASS | 14 M5 tests included in the 74-pass full suite |
| M5 report reflects actual implementation and results | PASS | This report cites actual saved outputs and measured results |
| M6 has not been started | PASS | Scope boundary preserved; implementation plan marks M6 not started |

## 18. شرح هندسي تفصيلي بالعربية

### لماذا أُضيف إطار M5؟

قبل M5 كانت كل مرحلة تجري تجاربها بطريقتها: ملف إعدادات مختلف، وتسمية أعمدة مختلفة، وطريقة خاصة لحفظ البذور والرسوم. هذا مناسب لتطوير كل مرحلة على حدة، لكنه يصعّب مقارنة AWGN مع موجة RRC أو مقارنة المستقبلين تحت القناة نفسها. لذلك أضفت طبقة تنسيق مشتركة تحيط بالدوال الموجودة. الطبقة الجديدة لا تعيد كتابة المضمّن BPSK أو مرشح RRC أو القناة أو كاشف الإشارة؛ بل تنشئ الإعدادات، تمرر المولدات العشوائية، تستدعي المكونات الحالية، ثم تحفظ نتيجة كل تشغيل بصيغة واحدة.

### كيف تعمل البذور؟

لا يعتمد التشغيل على مولد عشوائي عام مخفي. تُشتق بذرة مستقلة للبتات وأخرى للضوضاء وأخرى لإعادة أخذ عينات bootstrap. الاشتقاق يأخذ البذرة الرئيسية ومعرّف التجربة والتكرار والدور وشرط القياس، ثم يمررها عبر SHA-256. وبذلك لا تتغير بذرة تجربة لمجرد أن تجربة أخرى نُفذت قبلها. في مقارنة المستقبلين تتشارك القناتان البتات نفسها والإشارة المستقبلة نفسها؛ أي إن الفرق المقاس يرجع لقرارات المستقبل لا لاختلاف عينة الضوضاء.

### كيف تُقرأ BER وفواصل الثقة؟

يحفظ الإطار عدد الأخطاء `E` وعدد البتات `N` ثم يحسب `BER=E/N`. فاصل Clopper–Pearson يصف عدم اليقين الثنائي داخل تشغيل واحد. إذا لم يظهر أي خطأ، تظل BER المقاسة صفرًا لأنها `0/N`، لكن ذلك لا يعني أن الاحتمال الحقيقي صفر؛ لهذا يُحفظ حد أعلى منفصل عند 95%. عند وجود نقاط مسح كثيرة، يحفظ النظام أيضًا فواصل محافظة بتصحيح Bonferroni للعائلة المحددة، حتى لا تُفسر فواصل كل نقطة كما لو لم تكن هناك مقارنات متعددة.

هناك نوع آخر من عدم اليقين: اختلاف النتائج بين البذور المستقلة. لذلك لا تجمع النتائج في عدد أخطاء واحد ثم تفقد أثر التكرار؛ بل يحتفظ النظام بكل تشغيل ويحسب متوسط BER والانحراف بين التكرارات في ملف مستقل. التكراران المستخدمان هنا يصلحان لإظهار سير العمل والفروق الواضحة، لكنهما لا يكفيان لتقدير توزيع النتائج بدقة. ولهذا فواصل t عبر التكرارات وصفية، خصوصًا إذا كان عدد التكرارات اثنين فقط.

### ماذا أظهرت التجارب الفعلية؟

في تشغيل AWGN المرجعي، انخفض متوسط BER من `0.07665` عند 0 dB إلى `0.00015` عند 8 dB. وفي قناة التداخل ارتفع متوسط BER للمستقبل الأساسي من `0.0028` دون نغمة إلى `0.1686` عند سعة قمة `0.42`. كما زاد التوهين BER: من `0.0015` دون توهين إلى `0.1264` عند 8 dB؛ لأن Eb/N0 الفعال ينخفض بمقدار التوهين.

في المقارنة عند نغمة مطابقة لتردد notch، كان متوسط BER للمستقبل الأساسي `0.03095` وللمرشح `0.00430`، وكان فرق BER المقترن المتوسط `-0.02665`. السالب يعني أن المرشح سجل أخطاء أقل في هذين التشغيلين تحديدًا. لكن عند تغيير تردد النغمة لم تبق الفائدة ثابتة: تحسن المرشح قرب `0.34–0.36` cycles/symbol، بينما زادت الأخطاء عند بعض الإزاحات مثل `.31` و`.33` و`.39`. هذه نتيجة حساسية مهمة، لكنها مسح استكشافي صغير وليست ضمانًا لأداء مستقبلي عام.

استُخدم bootstrap كتلي على فرق مؤشرات الخطأ، مع كتل بطول 50 ثم فحص الحساسية بطول 100. تشابه الفواصل بين الطولين في هذه النتائج يبيّن أن الاستنتاج لم يتغير كثيرًا عند هذا التعديل المحدد، لكنه لا يثبت صلاحية كل أطوال الكتل أو كل قنوات الاعتماد. كذلك اختبار McNemar يعامل أزواج الأخطاء المتخالفة كأنها مستقلة؛ الترشيح والنبضات قد يضعفان هذا الافتراض، لذا لا أستخدم قيمة الاختبار وحدها لإعلان تفوق المستقبل.

### كيف يعيد المهندس التجربة؟

يُعاد التشغيل من ملف `resolved_config.json` نفسه؛ الملف يتضمن قيم الموجة والقناة والتكرار والبذرة، بينما تحفظ CSV الأعداد الخام والبذور المشتقة والنتائج وفواصل الثقة. وقد نُفذ ذلك فعلًا: تطابقت ملفات النتائج والملخصات والقرارات لكل بت بين التشغيل الأول والإعادة، مع استثناء `runtime_seconds` لأنه يتأثر بحمل الجهاز. كما اجتاز كامل الاختبار الآلي 74 اختبارًا، منها اختبارات الرجوع لمراحل M1–M4.

### حدود الجاهزية

M5 مكتمل بحسب بوابة القبول الواردة في هذا التقرير. يظل هذا نموذجًا رقميًا عائمًا بزمن متقطع واتفاقية ضوضاء موثقة، وليس معايرة جهاز أو مستقبلًا آنيًا. مرشح M4/M5 يستخدم `filtfilt` غير السببي، لذلك لا يجوز تقديم نتائجه كميزة مستقبل آني. الخطوة التالية من حيث خطة المشروع هي مراجعة المستخدم لتقرير M5 ومخرجاته؛ لم أبدأ M6.

## 19. Readiness assessment for M6

M5 is ready for review. The common runner, results, plots, regression evidence, reproducibility check, and acceptance matrix are complete for the defined scope. M6 may begin only after the user reviews these results and explicitly proceeds. No M6 integration, final packaging, GUI, or delivery tasks were performed in this milestone.
