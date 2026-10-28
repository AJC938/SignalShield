# SignalShield M1 Engineering Report

**Project:** Robust Digital Communication & Signal Recovery Simulator  
**Milestone:** M1 — Project Foundation & Baseline Communication System  
**Execution status:** M1 implementation and verification completed; ready for user review. M2 has not been started.

## A. Executive summary

M1 establishes a reproducible coherent BPSK link over real AWGN. It includes validated configuration, explicit RNG-backed bit generation, the approved `0 → +1` / `1 → −1` map, AWGN calibrated from `Eb/N0`, zero-threshold detection, BER and exact binomial intervals, theoretical BPSK BER, a fixed-budget six-point experiment, CSV/JSON output, and a logarithmic BER plot.

The completed automated suite reports **10 passed**. The six-point experiment ran for 200,000 bits per point with seed `20261027`. For every tested SNR, the observed BER and its two-sided 95% exact interval are recorded. The curve generally decreases as `Eb/N0` increases. At 10 dB the run observed zero errors; the one-sided 95% upper bound is `1.4978549e-5`, so this point does not resolve the much smaller theoretical BER `3.8721082e-6`.

M1 acceptance is **PASS for its implemented scope**. The broader target system is not complete: RRC waveforms, additional channel impairments, notch receiver, and later milestone deliverables remain planned. This report does not claim those features.

## B. Initial environment

- **Project directory:** project root (portable relative paths).
- **OS:** Windows 10, build 22631.
- **Python:** 3.11.5.
- **Git:** Git 2.55.0 is installed, but this project directory is not inside a Git repository. `git status` therefore could not report a worktree status.
- **Initial global packages:** NumPy 2.2.2 and pytest 9.1.1 were importable; SciPy and Matplotlib were absent.
- **Project-local environment after setup:** NumPy 2.4.6, SciPy 1.17.1, Matplotlib 3.11.2, pytest 9.1.1. Exact core/test pins are in `requirements.txt`.
- **Existing project state:** the workspace initially contained the approved README and six design documents; no source package, tests, dependency manifest, or result/report output existed. Those design documents were preserved. The README was updated to reflect actual M1 status.

**Environment setup note:** the first combined install began downloading packages but was interrupted while large wheels were being copied into the OneDrive-hosted virtual environment. The first pytest attempt consequently reported `No module named pytest`. This was an incomplete environment setup, not a test failure. Completing the install with `.venv\Scripts\python.exe -m pip install matplotlib pytest -e .` succeeded; the documented clean setup command `.venv\Scripts\python.exe -m pip install -e '.[dev]'` was then run successfully with all declared dependencies satisfied.

## C. Design and implementation

### Files added or updated

- `pyproject.toml` — installable package metadata, dependencies, pytest configuration, and `signalshield-m1` entry point.
- `requirements.txt` — pinned direct runtime and test dependencies observed in the project environment.
- `.gitignore` — excludes the local virtual environment, Python caches, and build artifacts.
- `src/signalshield/config.py` — immutable `SimulationConfig`; validates bit count, seed, `Eb/N0`, and bit energy.
- `src/signalshield/signals.py` — explicit-RNG bit generation and shared bit/sample validators.
- `src/signalshield/modulation.py` — BPSK mapping/demapping.
- `src/signalshield/channel.py` — dB conversion, noise-variance derivation, and independent AWGN primitive.
- `src/signalshield/receiver.py` — coherent hard-decision detector.
- `src/signalshield/metrics.py` — BER, exact Clopper–Pearson interval, zero-error upper bound, and theoretical BER.
- `src/signalshield/experiments.py` — fixed-budget sweep, deterministic seed derivation, CSV/JSON output, and CLI.
- `src/signalshield/plotting.py` — result-only plotting helper; it does not run simulations.
- `tests/test_baseline.py` — eleven automated test cases spanning M1 behavior.
- `README.md` — M1 model, installation, commands, artifacts, interpretation, and scope status.
- `results/m1/` — captured test output, experiment log, result CSV, configuration/seed JSON, and BER PNG.
- `reports/M1_engineering_report.md` — this report.

Only M1 responsibilities were implemented. There are no placeholder filter, waveform, coding, or advanced-channel modules.

### Main interfaces

- `SimulationConfig(n_bits=200_000, ebn0_db=0.0, seed=20261027, bit_energy=1.0)`
- `generate_bits(n_bits, rng)`
- `bpsk_modulate(bits, bit_energy=1.0)` and `bpsk_demodulate(samples)`
- `noise_variance_from_ebn0_db(ebn0_db, bit_energy=1.0)`
- `add_awgn(samples, variance, rng)`
- `detect_bpsk(received_samples)`
- `ber_estimate(transmitted_bits, received_bits, confidence_level=0.95)`
- `bpsk_awgn_theory(ebn0_db)`
- `run_ber_sweep(...)` and command `python -m signalshield.experiments`

Functions reject malformed dimensions, empty metric inputs, nonbinary bit arrays, nonfinite values, invalid SNR/energy/seed values, mismatched bit lengths, and RNG arguments that are not `numpy.random.Generator` instances. AWGN accepts variance directly, so channel generation stays separate from SNR configuration and symbol mapping. Zero variance is an explicit identity channel for noiseless tests.

## D. Mathematical model implemented

The baseline uses uncoded, real, one-sample-per-bit BPSK. For bit energy `Eb`, mapping is `x=+sqrt(Eb)` for bit 0 and `x=−sqrt(Eb)` for bit 1. The default and experiment value is `Eb=1`.

For `Eb/N0` in dB:

```text
gamma_b = 10**(EbN0_dB / 10)
sigma_squared = Eb / (2 * gamma_b)
sigma = sqrt(sigma_squared)
n ~ Normal(0, sigma_squared)
y = x + n
```

The variance, rather than the standard deviation, is passed into `add_awgn`; that function uses its square root as the Gaussian scale. The detector applies bit 0 when `y >= 0`, bit 1 otherwise; thus an exact zero sample maps to bit 0. BER is integer error count divided by the number of evaluated bits. For coherent uncoded BPSK/AWGN only, theoretical BER is `0.5 * erfc(sqrt(gamma_b))`, evaluated using `scipy.special.erfc`.

Uncertainty uses two-sided exact Clopper–Pearson intervals at 95%. If no errors occur, the reported BER remains `0/N`; a separate exact one-sided 95% upper bound `1−0.05^(1/N)` is saved. No physical continuous-time PSD, pulse shape, oversampling, fading, or other channel is implied by this normalized discrete reference model.

## E. Test results

Successful test command:

```text
.\.venv\Scripts\python.exe -m pytest -q
...........                                                              [100%]
11 passed in 4.33s
```

The captured summary is [results/m1/test_run.txt](../results/m1/test_run.txt). The earlier setup attempt failed before test collection because pytest had not yet been installed into `.venv`; after setup completed, the full suite passed.

All pytest command outcomes during implementation:

| Run | Outcome | Explanation |
|---|---|---|
| Initial run before dependency installation completed | Failed before collection: `No module named pytest` | Environment setup was incomplete; no source tests ran. |
| Baseline suite after installation | 10 passed | Initial M1 behavior passed. |
| First run after adding the results-artifact test and extracting plotting | 1 failed, 10 passed | Artifact metadata referenced a removed module binding; the version lookup was corrected. |
| Next run | 11 passed, 1 warning | A synthetic zero-error fixture had theoretical BER exactly zero, which cannot be drawn on a logarithmic axis; the fixture was changed to a positive theoretical BER case. |
| Final run | 11 passed, no warnings, 4.33 s | Final source and tests pass; summary is captured above. |

| Test coverage | Verification performed | Result |
|---|---|---|
| Configuration | Valid case, zero/boolean bit count, seed bounds, nonfinite/out-of-range SNR, invalid energy | Pass |
| Bits and mapping | Shape/dtype/binary alphabet, fixed-seed repeatability, known map, detector polarity and zero tie | Pass |
| Noiseless chain | Known odd-length sequence and 10,001 seeded random bits through modulator, zero-noise channel, detector and BER | Pass; zero errors |
| Noise model | 500,000 samples at 3 dB; sample mean and variance within six-standard-error limits | Pass |
| Noise reproducibility | Same RNG seed gives identical samples; distinct fixed seeds differ; zero variance preserves input | Pass |
| BER and zero errors | Known count, interval, empty/mismatched/nonbinary inputs, and 100,000-bit zero-error upper bound | Pass |
| Theory | Representative values at 0 and 6 dB, descending trend, 300 dB finite handling, invalid arrays | Pass |
| Integration and statistical check | 200,000-bit point and 500,000-bit 4 dB point; the 99% exact binomial interval contains theoretical BER | Pass |
| Artifact writing | One-point zero-error result through CSV/JSON/PNG writer; files and master-seed metadata checked | Pass |

Tests were not weakened to obtain a pass. Test source: `tests/test_baseline.py`.

## F. Experimental results

### Configuration and reproduction

- SNR sweep: `0, 2, 4, 6, 8, 10 dB`.
- Bits per point: `200,000` (fixed N, no adaptive stopping).
- Master seed: `20261027`.
- Each SNR gets its own `SeedSequence` child and separate bit/noise streams; derived uint32 seeds are saved in CSV/JSON.
- Bit energy: `1.0`.
- Confidence intervals: two-sided 95% exact Clopper–Pearson; zero-error point additionally reports one-sided 95% upper limit.

Reproduction command:

```powershell
.\.venv\Scripts\python.exe -m signalshield.experiments --n-bits 200000 --seed 20261027 --ebn0-db 0 2 4 6 8 10 --output-dir results/m1
```

The command output is saved in [results/m1/experiment_run.txt](../results/m1/experiment_run.txt). Machine-readable configuration and seeds are in [results/m1/m1_experiment_config.json](../results/m1/m1_experiment_config.json); numerical rows are in [results/m1/m1_ber_results.csv](../results/m1/m1_ber_results.csv); the plot is [results/m1/m1_ber_plot.png](../results/m1/m1_ber_plot.png).

| Eb/N0 (dB) | Errors / bits | Simulated BER | Theory BER | 95% exact interval | Note |
|---:|---:|---:|---:|---:|---|
| 0 | 15,692 / 200,000 | 0.078460 | 0.0786496 | [0.0772852, 0.0796471] | Informative; theory is inside interval |
| 2 | 7,449 / 200,000 | 0.037245 | 0.0375061 | [0.0364193, 0.0380841] | Informative; theory is inside interval |
| 4 | 2,418 / 200,000 | 0.012090 | 0.0125008 | [0.0116156, 0.0125786] | Informative; theory is inside interval |
| 6 | 485 / 200,000 | 0.002425 | 0.00238829 | [0.00221418, 0.00265044] | Informative; theory is inside interval |
| 8 | 35 / 200,000 | 0.000175 | 0.000190908 | [0.000121897, 0.000243374] | Wider relative uncertainty; theory is inside interval |
| 10 | 0 / 200,000 | 0 observed | 0.00000387211 | [0, 0.0000184442] | One-sided 95% upper bound: 0.0000149785; insufficient to resolve theory |

BER generally falls as `Eb/N0` increases in this run. Theoretical BER lies inside each displayed per-point 95% interval; the intervals are pointwise, not a familywise simultaneous confidence band. The independent 4 dB statistical test uses a 99% exact interval and also contains theory. The 8 dB estimate is based on only 35 errors and has substantially less relative precision. At 10 dB, zero observed errors do not contradict the theoretical rate: with this bit budget, the experiment cannot estimate that low a BER precisely. The measured outcomes are a consistency check, not proof that all SNR values or all channel models match theory.

Per-point elapsed simulation times are recorded in CSV (roughly 0.008–0.009 s in this environment); these are machine/runtime observations, not correctness criteria. The graph plots theory separately from observations. Its 10 dB symbol and downward arrow indicate an upper confidence bound, not a fabricated positive observed BER.

## G. Failure analysis, deviations, and limitations

- **Initial setup interruption:** the first package install was interrupted before pytest and Matplotlib completed installation. The first test invocation therefore failed at environment setup (`No module named pytest`); after finishing installation, a clean full-suite run passed. Both events are disclosed above.
- **Repository:** Git is installed, but no `.git` repository exists at the project path, so no branch or dirty-worktree state can be reported. No existing project source was present or overwritten.
- **M1 scope limit:** only the reference BPSK/AWGN model is implemented. M2 sampled waveform/RRC, M3 channel extensions, M4 receiver improvements, M5 broader experiments, and M6 final integration are not implemented or tested.
- **Statistics:** 200,000 bits provide useful estimates through 8 dB in this run but not precise evidence at 10 dB. No repeated-peeking stopping rule was used. The test suite has a preselected deterministic statistical comparison at 4 dB.
- **Model assumptions:** uncoded equiprobable bits, coherent threshold detector, ideal timing/phase, real iid discrete AWGN, and fixed known bit energy. It is not a physical RF model or a security/jammer-resilience claim.
- **Design-plan alignment:** the existing project plan uses target tasks T00–T10, while the execution request defines six project milestones and M1 sub-tasks. M1.1–M1.4 were treated as the execution scope, corresponding to project foundation/reference BER experiment work; no conflict in the mathematical conventions was found. The approved design documents remain available and were preserved.
- **No M2 work:** no pulse shaping, filtering, interference, or additional channel module was started.

## H. Reproduction instructions

From the project root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m signalshield.experiments --n-bits 200000 --seed 20261027 --ebn0-db 0 2 4 6 8 10 --output-dir results/m1
```

The exact dependency snapshot used for this run is in `requirements.txt`. The setup and experiment commands were executed in the project environment. Pytest passed after dependency installation; the sweep completed and generated all listed outputs.

## I. M1 acceptance matrix

| Acceptance criterion | Verification | Actual outcome / evidence | Status |
|---|---|---|---|
| Workspace and documents inspected; previous work preserved | Directory inventory; read README and all six specified design documents | Only design docs existed initially; all retained; project is not a Git repository | PASS |
| Python and required dependencies available and documented | Version/import checks; local venv install; pin file | Python 3.11.5; project-local NumPy/SciPy/Matplotlib/pytest versions recorded | PASS |
| Minimal meaningful package structure established | Install editable package; pytest imports public modules | M1 modules only; no empty future-milestone modules | PASS |
| Configuration validates required parameters | `test_config_validates_reference_parameters` | Valid and invalid cases pass | PASS |
| Seeded bit generation and approved BPSK mapping | Bit generation/mapping tests | Shape, alphabet, repeatability and `0→+1`, `1→−1` pass | PASS |
| AWGN dB conversion and variance | Six-standard-error empirical check and analytic assertion | 3 dB, 500,000 samples pass; expected variance `0.250593...` | PASS |
| Noise generation reproducible; zero-noise chain works | Fixed-seed and known/random noiseless end-to-end tests | Identical seeded noise; zero errors through both chains | PASS |
| Detector decisions including zero tie | Known samples | Positive→0, negative→1, zero→0 | PASS |
| BER count, invalid input, and zero-error treatment | BER tests | Counts correct; zero-error upper bound reported separately | PASS |
| Theoretical coherent BPSK BER | Known values, trend, numerical boundary, 99% statistical comparison | Tests pass; theory agrees with 4 dB run within exact 99% interval | PASS |
| Reproducible BER sweep with all requested fields | Run command and CSV/JSON inspection | Six points, 200,000 bits each, seeds/config/variance/counts/intervals saved | PASS |
| BER plot is statistically honest | Visual inspection of PNG and source | Theory separated; nonzero points have 95% intervals; zero-error point marked as upper bound | PASS |
| Tests executed and results captured | `.venv\Scripts\python.exe -m pytest -q` | 11 passed in 4.33 s, no warnings; captured in `results/m1/test_run.txt` | PASS |
| Installed dependencies are consistent and CLI entry point is registered | `.venv\Scripts\python.exe -m pip check`; `signalshield-m1.exe --help` | `No broken requirements found`; CLI usage/options printed successfully | PASS |
| M1 report and README updated | File inspection | Report and M1 instructions present; planned later scope clearly identified | PASS |
| M2 not started | Source/result inventory | No waveform/RRC/filter/channel-extension implementation | PASS |

## J. الشرح الهندسي بالعربية

### ما الذي بُني؟

بنيت أساس M1 لمحاكاة إرسال واستقبال BPSK عبر قناة AWGN. يبدأ المسار بتوليد bits عشوائية باستخدام `NumPy Generator` وبذرة قابلة للتسجيل. يحول المرسل البت `0` إلى الرمز `+1` والبت `1` إلى `−1` عند `Eb=1`، ثم تضيف القناة ضوضاء Gaussian حقيقية مستقلة. يستعيد المستقبل البتات بقرار coherent عند العتبة صفر، وبعد ذلك يحسب البرنامج عدد الأخطاء و`BER`.

### كيف حُسبت الضوضاء؟

تحول قيمة `Eb/N0` من dB إلى قيمة خطية بالمعادلة `gamma_b = 10^(dB/10)`. وبما أن النموذج حقيقي و`Eb=1`، تكون **variance** للضوضاء `sigma² = 1/(2 gamma_b)`، أما قيمة `scale` التي يستخدمها مولد Gaussian فهي **standard deviation** وتساوي `sqrt(sigma²)`. التفريق بين variance وstandard deviation يمنع خطأ شائعًا يغيّر مستوى الضوضاء.

### كيف يستعيد المستقبل البتات ويقيس BER؟

يقرر المستقبل `0` عندما تكون العينة المستقبلة أكبر من أو تساوي الصفر، و`1` عندما تكون سالبة. يقارن `BER analyzer` البتات المستعادة بالبتات المرسلة، ويحسب `errors / n_bits`. وعند عدم وجود أخطاء يعرض `0/N` كقيمة مرصودة، ويعرض حد الثقة الأعلى منفصلًا؛ لا يساوي ذلك إثبات أن معدل الخطأ الحقيقي صفر.

### ماذا أظهرت التجربة؟

شغّلت ست نقاط من `0` إلى `10 dB`، بواقع `200,000` بت لكل نقطة. انخفضت `BER` عمومًا مع ارتفاع `Eb/N0`، وكانت القيم النظرية داخل فواصل الثقة المحسوبة لهذه النقاط. عند `10 dB` لم يظهر خطأ، لذلك لا تستطيع هذه الميزانية تقدير `BER` النظري الصغير بدقة؛ الحد الأعلى أحادي الطرف 95% يساوي تقريبًا `1.50×10⁻⁵`.

### ما الذي لا يمكن استنتاجه؟

لا تثبت التجربة سلوك waveform مأخوذ العينات، أو مرشحات RRC، أو fading، أو تداخلًا جيبيًا، أو تحسن receiver بديل. ولا تمثل قياسات RF فعلية أو حماية أمنية. كل هذه الموضوعات خارج M1، ويجب أن تُبنى وتُختبر في milestones لاحقة.

### مفاهيم يجدر فهمها قبل اعتماد M1

1. الفرق بين `Eb/N0` بوحدة dB ونسبته الخطية.
2. سبب عامل `1/2` في variance عند استخدام AWGN حقيقية وBPSK متماسكة.
3. الفرق بين `variance` و`standard deviation`.
4. لماذا لا تعني نتيجة `0/N` أن BER الحقيقي يساوي صفرًا، وكيف يعبّر confidence bound عن ذلك.
5. حدود افتراض one-sample-per-bit مقارنةً بنموذج pulse-shaped waveform.

## K. جاهزية milestone التالي

M1 جاهز للمراجعة: الحزمة تثبت mapping، تطبيع AWGN، detector، BER، reproducibility، والمرجع النظري مع نتائج قابلة لإعادة التنفيذ. يوفر ذلك أساسًا مناسبًا لبدء M2 بعد مراجعة المستخدم. **لم أبدأ M2**؛ إنشاء RRC waveform وmatched-filter chain ينتظر اعتماد هذا التنفيذ والتقرير والنتائج.

