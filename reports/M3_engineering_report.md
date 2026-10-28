# SignalShield M3 — Configurable Communication Channel Simulator

## Status

- **Implementation:** M3 channel components and focused experiments are implemented.
- **Verification:** full automated suite passes: 45 passed; no failures or skips.
- **Acceptance:** M3 is ready for review against the scope in the M3 request. M4 and later work was not started.

## A. Executive summary

M3 extends the M2 sampled-waveform BPSK chain with a reproducible channel interface for real AWGN, a deterministic narrowband sinusoid, and constant desired-signal attenuation. The channel retains same-length, separately inspectable wanted-signal, tone, noise, and received arrays. AWGN uses the M2 normalized discrete variance; no samples-per-symbol multiplier was introduced. The channel applies attenuation to the wanted waveform, then adds the configured tone, then receiver-side AWGN.

The full M1/M2/M3 test suite passed. Controlled experiments were run for an AWGN baseline, tone-amplitude sweep, tone-frequency sweep, attenuation sweep, noiseless attenuation, and one combined case. Eight plots and the CSV/JSON/run-log evidence are saved under `results/m3/`. The baseline mostly follows BPSK/AWGN theory; the 4 dB point is an observed 95% interval excursion and is called out below. Attenuation lowers the effective signal-to-noise ratio as predicted. Tone impact depends strongly on its location relative to the pulse-shaped signal spectrum.

## B. Repository and environment

- Workspace: project root (portable relative paths).
- Runtime used: project-local `.venv`, Python 3.11.5, NumPy 2.4.6, SciPy 1.17.1, Matplotlib 3.11.2, pytest 9.1.1.
- The package is installed in the local environment and the M2 source, tests, reports, and result files were inspected before editing.
- This workspace does not contain a `.git` repository (`git status` reported “not a git repository”), so a Git diff/status could not be used as a preservation check. Existing M1/M2 files and result directories were retained; M3 outputs were placed in the new `results/m3/` directory.
- No new runtime dependency was added.
- A first attempt to redirect the experiment console output failed because PowerShell creates the redirection target before the program can create its output directory. After creating `results/m3/`, the experiment was rerun successfully and the complete output was captured. This was an invocation setup issue, not a simulator failure.

## C. Channel architecture

```mermaid
flowchart LR
  A[Pulse-shaped M2 waveform s[n]] --> G[Desired-signal gain g]
  G --> S[Attenuated desired waveform]
  I[Configured sinusoid i[n]] --> T[Add tone]
  S --> T
  T --> W[Add real AWGN w[n]]
  N[Explicit NumPy Generator] --> W
  W --> R[Received waveform r[n]]
  R --> MF[Existing M2 matched filter and sampler]
  MF --> B[Recovered bits and BER]
  S --> D[Component/power diagnostics]
  I --> D
  N --> D
  R --> D
```

`ChannelConfig` is immutable and validates samples per symbol, SNR, attenuation, tone peak amplitude, tone frequency, and phase. `apply_configured_channel(samples, config, rng=...)` returns `ChannelOutput` containing `received`, `attenuated_signal`, `interference`, `noise`, and `applied_gain`. Disabled tone/noise components are zero arrays; zero attenuation is unity gain. The channel does not alter sample count, filter, normalize, detect, or compensate delay. The existing M2 receiver consumes the received samples unchanged.

### Specification reconciliation

The M3 request explicitly orders channel operations as gain, tone, then AWGN. Older wording in `docs/system_design.md` listed gain, AWGN, then tone. I reconciled the design text with the current M3 request and used the requested order. Since tone and noise are additive, their sum is identical for the same already-generated component arrays; the stated order defines the API and the signal-only attenuation assumption, not a different mathematical sum.

## D. Mathematical model and assumptions

The implemented finite-record model is

\[
r[n] = g\,s[n] + i[n] + w[n].
\]

For attenuation $A_{dB}\ge0$, the gain is $g=10^{-A_{dB}/20}$. It applies only to the desired waveform. Tone and receiver-side AWGN are added after attenuation and are not attenuated. This is an explicit modeling choice and is not asserted to describe every physical channel.

For the M2 normalized sampled model, configured $E_b/N_0$ gives

\[
\gamma_b=10^{(E_b/N_0)_{dB}/10},\qquad
\sigma_w^2=\frac{E_b}{2\gamma_b}.
\]

The real noise standard deviation is $\sqrt{\sigma_w^2}$. Unit-energy RRC transmit/receive pulses use the established M2 discrete convention, so no additional samples-per-symbol multiplier is applied. This is normalized discrete-time AWGN; it is not a physical continuous-time noise PSD or ADC model. AWGN-only calls reproduce `add_awgn` sample-for-sample when given the same waveform, variance, and seeded generator.

The interference is

\[
i[n]=A_i\cos\left(2\pi f_{sym}\frac{n}{s}+\phi\right),
\]

where $A_i$ is peak sample amplitude, $f_{sym}$ is cycles per symbol, $s$ is samples per symbol, and $\phi$ is radians. Therefore the digital frequency is $f_{sym}/s$ cycles/sample. Valid tone frequency is strictly $0<f_{sym}<s/2$. For an ideal sinusoid over a whole number of periods, mean-square power is $A_i^2/2$; saved diagnostics instead compute the actual finite-record mean square. Tone-to-signal ratio in the CSV is actual interference record power divided by the attenuated desired-signal record power. It is undefined if that desired-signal record power is zero.

With no tone and fixed post-attenuation noise, the effective reference is

\[
(E_b/N_0)_{effective,dB}=(E_b/N_0)_{configured,dB}-A_{dB}.
\]

Theory $P_b=0.5\,\mathrm{erfc}(\sqrt{\gamma_b})$ is therefore used only for AWGN-only cases, with the effective value in attenuation experiments. It is not used as an exact prediction for tone-contaminated runs. The finite RRC is truncated, so the existing M2 residual ISI and finite Monte Carlo uncertainty remain relevant.

## E. Implementation details

- `src/signalshield/channel.py` — retains M1/M2 AWGN functions and adds `ChannelConfig`, `ChannelOutput`, `attenuation_gain`, `apply_attenuation`, `generate_sinusoidal_interference`, `apply_configured_channel`, and finite-record mean-square power.
- `src/signalshield/m3_experiments.py` — executes reproducible baseline and channel sweeps, writes CSV/JSON, exports diagnostics and creates plots. It calls the existing pulse shaper, matched-filter receiver, BER estimator, and theory function rather than duplicating those components.
- `tests/test_channel_m3.py` — validates AWGN reuse/statistics and RNG behavior, tone frequency/phase/peak, parameter rejection, gain, composition equation, zero/noiseless cases, and end-to-end M2 equivalence.
- `pyproject.toml` — adds the `signalshield-m3` console command.
- `README.md`, `docs/implementation_plan.md`, `docs/system_design.md` — document M3, its execution, actual status, and reconciled operation order.
- `results/m3/` — contains experimental records, configuration/seed metadata, diagnostics, test/experiment logs, and eight generated PNG plots.

M3 has not added fading, multipath, timing recovery, interference cancellation, a new receiver, or a GUI.

## F. Validation results

Command executed:

```text
.\.venv\Scripts\python.exe -m pytest -q
45 passed in 3.02s
```

The captured output is `results/m3/test_run.txt`. This total comprises the original 30 M1/M2 tests plus 15 M3 channel tests. New tests verify that:

- A same-seed M3 AWGN-only waveform equals the established M2 `add_awgn` output exactly; noise mean and sample variance fall within six-standard-error tolerances over 20,000 samples.
- A 4,096-sample tone matches its analytical samples, phase and peak and has the configured FFT frequency; zero amplitude returns zeros.
- Invalid tone frequencies, attenuation, amplitude, and samples-per-symbol are rejected.
- Known attenuation values produce the expected linear gain with unchanged length.
- Combined output reconstructs exactly as `attenuated_signal + interference + noise`, and identical seeds reproduce identical output.
- A noiseless, zero-impairment waveform recovers the full payload; tone-only composition equals the analytical tone sum.
- A seeded AWGN-only M3 waveform and detected bits equal the M2 reference exactly.

## G. Experiment results

Reproduction command and saved console output:

```text
.\.venv\Scripts\python.exe -m signalshield.m3_experiments --n-bits 30000 --seed 20261029 --output-dir results/m3
```

The final run completed in 1.924 seconds on this environment. It used 30,000 bits at each point; `sps=8`, RRC rolloff 0.35, span 10 symbols, $E_b=1$, nominal sweep SNR 6 dB except the explicit baseline sweep. A fixed bit sequence was reused. Paired conditions reused the exact AWGN realization for each respective sweep. Seeds are derived using `SeedSequence` and recorded in the CSV/JSON. Exact two-sided 95% Clopper–Pearson intervals are saved; zero-error points are represented as zero observed errors with the separate upper bound (no zero-error observation occurred in the stochastic sweeps).

### AWGN-only baseline

| Configured Eb/N0 | Errors / bits | Measured BER | 95% exact interval | BPSK theory |
|---:|---:|---:|---:|---:|
| 0 dB | 2287 / 30000 | 0.076233 | [0.073255, 0.079294] | 0.078650 |
| 2 dB | 1098 / 30000 | 0.036600 | [0.034503, 0.038787] | 0.037506 |
| 4 dB | 425 / 30000 | 0.014167 | [0.012860, 0.015569] | 0.012501 |
| 6 dB | 80 / 30000 | 0.002667 | [0.002115, 0.003318] | 0.002388 |
| 8 dB | 5 / 30000 | 0.000167 | [0.000054, 0.000389] | 0.000191 |

The theoretical value lies within the pointwise 95% interval at 0, 2, 6, and 8 dB. At 4 dB, the measured interval does not include theory. This is one observed Monte Carlo excursion and is not hidden or “fixed”; a single pointwise 95% interval exclusion can occur under repeated testing. The 8 dB estimate is based on only five errors and has visibly limited precision.

### Tone amplitude sweep

At 6 dB, (f_{sym}=0.7) cycles/symbol and phase 0.37 rad, with common bits and noise:

| Peak amplitude | Tone / attenuated signal power ratio | Errors / bits | BER (95% exact interval) |
|---:|---:|---:|---:|
| 0.00 | 0.000 | 84 / 30000 | 0.002800 [0.002234, 0.003465] |
| 0.08 | 0.026 | 86 / 30000 | 0.002867 [0.002294, 0.003539] |
| 0.16 | 0.102 | 86 / 30000 | 0.002867 [0.002294, 0.003539] |
| 0.28 | 0.314 | 87 / 30000 | 0.002900 [0.002323, 0.003576] |
| 0.42 | 0.706 | 86 / 30000 | 0.002867 [0.002294, 0.003539] |

The measured BER barely changes in this particular sweep. This is consistent with the selected tone lying just beyond the nominal RRC one-sided passband edge ((1+0.35)/2=0.675) cycles/symbol and being attenuated by the matched-filter path. It is not evidence that every tone is harmless or that the channel performs general interference cancellation.

### Tone frequency sweep

At 6 dB with fixed peak amplitude 0.22, phase 0.37 rad, bits and noise:

| Frequency (cycles/symbol) | Errors / bits | BER (95% exact interval) |
|---:|---:|---:|
| 0.15 | 1024 / 30000 | 0.034133 [0.032107, 0.036250] |
| 0.35 | 919 / 30000 | 0.030633 [0.028712, 0.032646] |
| 0.70 | 58 / 30000 | 0.001933 [0.001468, 0.002499] |
| 1.10 | 59 / 30000 | 0.001967 [0.001497, 0.002536] |
| 1.60 | 59 / 30000 | 0.001967 [0.001497, 0.002536] |

The 0.15 and 0.35 cycles/symbol tones fall within the wanted pulse spectrum and produce substantially more errors. The results at and above 0.70 are near the AWGN-only result. This measured pattern is consistent with pulse shaping and matched-filter frequency response, plus symbol timing/phase interaction. It does not imply that BER is monotonic in frequency or amplitude in general.

### Attenuation sweep and noiseless check

At configured 6 dB with fixed AWGN variance and no tone:

| Attenuation | Gain | Effective Eb/N0 | Errors / bits | BER (95% exact interval) | Theory at effective value |
|---:|---:|---:|---:|---:|---:|
| 0 dB | 1.0000 | 6 dB | 60 / 30000 | 0.002000 [0.001527, 0.002574] | 0.002388 |
| 2 dB | 0.7943 | 4 dB | 357 / 30000 | 0.011900 [0.010704, 0.013192] | 0.012501 |
| 4 dB | 0.6310 | 2 dB | 1160 / 30000 | 0.038667 [0.036513, 0.040910] | 0.037506 |
| 6 dB | 0.5012 | 0 dB | 2370 / 30000 | 0.079000 [0.075972, 0.082110] | 0.078650 |
| 8 dB | 0.3981 | −2 dB | 3900 / 30000 | 0.130000 [0.126214, 0.133858] | 0.130644 |

The theory values fall within all five pointwise intervals. A separate no-noise run records 0 errors out of 30,000 bits at 0, 2, 4, and 8 dB attenuation, confirming that gain scaling alone does not flip ideal coherent decisions for these test data. Its CSV keeps the exact upper confidence limit separate from the measured BER of 0/30000.

### Combined-channel run

At 6 dB configured Eb/N0, 2 dB attenuation, 0.22 tone peak, 0.7 cycles/symbol, and 0.37 rad phase, the result was **385/30000 errors**, BER **0.012833**, 95% interval **[0.011590, 0.014172]**. The effective AWGN-only Eb/N0 would be 4 dB under the attenuation assumption, but no exact AWGN theory is assigned because this case also contains a tone. This case combines attenuation and interference; it is intentionally not presented as an isolated estimate of either component.

### Saved numeric artifacts

- `results/m3/m3_awgn_baseline.csv`
- `results/m3/m3_interference_amplitude.csv`
- `results/m3/m3_interference_frequency.csv`
- `results/m3/m3_attenuation.csv`
- `results/m3/m3_noiseless_attenuation.csv`
- `results/m3/m3_combined_channel.csv`
- `results/m3/m3_diagnostic_waveforms.csv` — first 512 samples of transmitted, attenuated, interference, noise and received traces with time axis.
- `results/m3/m3_experiment_config.json` — model equations, order, normalization, seeds, configuration, measured channel powers and versions.
- `results/m3/experiment_run.txt` and `results/m3/test_run.txt` — actual command output.

The combined diagnostic record measured transmitted waveform mean-square power 0.124956, attenuated desired power 0.078842, tone power 0.0241999, sample noise variance 0.125915 (configured 0.125594), received record mean-square power 0.227722, and tone-to-attenuated-signal power ratio 0.30694. These are finite-record measurements, not infinite-record identities.

## H. Plot interpretation

Eight files are generated from the actual run:

1. `m3_awgn_baseline_ber.png` — simulated AWGN BER with exact intervals and the coherent theory curve; the 4 dB deviation and sparse 8 dB errors remain visible.
2. `m3_ber_vs_interference_amplitude.png` — paired amplitude sweep; near-flat BER at 0.7 cycles/symbol illustrates that tone frequency and receiver filtering matter.
3. `m3_ber_vs_interference_frequency.png` — paired frequency sweep; in-band tones at 0.15/0.35 have markedly higher measured BER than higher tones.
4. `m3_ber_vs_attenuation.png` — increasing attenuation shifts effective SNR downward; the overlaid theoretical reference uses configured Eb/N0 minus attenuation.
5. `m3_transmit_receive_time.png` — actual first 512 samples under the combined channel. It demonstrates component addition and distortion, not BER by itself.
6. `m3_interference_time_spectrum.png` — configured tone in time and its windowed one-sided spectrum; finite record/windowing affects spectral leakage.
7. `m3_transmit_receive_spectrum.png` — transmit versus received spectrum for 2 dB attenuation, 0.22 peak tone at 0.7 cycles/symbol, and 6 dB AWGN. Each trace is normalized to its own maximum, so the plot compares spectral shape and location, not absolute power.
8. `m3_awgn_vs_combined.png` — measured AWGN-only versus AWGN + tone + 2 dB attenuation BER at 6 dB, with exact intervals. Because the second case also includes attenuation, the plot compares the two named channel configurations and does not isolate the tone effect.

## I. Failure analysis, limitations, and unverified items

- One baseline point at 4 dB has a 95% interval that excludes theory. It is retained and explicitly reported. The other four baseline points include theory. The run used 30,000 bits per point, so estimates—especially the 8 dB point with five errors—have finite statistical precision.
- Tone results cover only the configured frequencies, phase, and amplitudes. A deterministic single tone is not a general jammer, colored-noise, multi-tone, or propagation model.
- The finite waveform uses the existing truncated M2 RRC and known timing. This work does not assess timing offset, phase recovery, fading, multipath, or receiver mitigation.
- The noise model is a normalized discrete model, not a physical bandwidth/PSD calibrated channel.
- No Git metadata was available in this workspace, so branch/diff evidence is NOT VERIFIED. This did not prevent execution or file-based tests.
- No M3 acceptance requirement remains unverified within the stated software/model scope. Physical channel realism and broader parameter coverage are outside the approved M3 model and remain unverified by design.

## J. Reproduction instructions

From the SignalShield workspace, using the already-installed project environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m signalshield.m3_experiments --n-bits 30000 --seed 20261029 --output-dir results/m3
```

The experiment’s default is the same bit budget and seed. The master seed deterministically derives the payload seed and distinct noise streams; paired conditions intentionally reuse fixed streams. Python/NumPy/SciPy/Matplotlib versions are embedded in `m3_experiment_config.json`.

## K. M3 acceptance matrix

| Criterion | Verification and observed result | Evidence | Status |
|---|---|---|---|
| Channel architecture and operation order explicit | Gain on wanted samples, then tone, then AWGN; additive equation preserved | `channel.py`, M3 config JSON, this report | PASS |
| Existing AWGN normalization retained | Same-seed M3 output equals M2 `add_awgn`; 20k-sample mean/variance checks pass | `tests/test_channel_m3.py`, full test log | PASS |
| Tone independently configurable and validated | Frequency, phase, peak, zero amplitude, invalid Nyquist/DC cases and FFT peak tested | `tests/test_channel_m3.py` | PASS |
| Attenuation independently configurable | Known gains, unity gain and invalid attenuation tested | `tests/test_channel_m3.py` | PASS |
| Components combine without shape/alignment changes | Reconstructed output equals returned component sum; waveform length preserved | `tests/test_channel_m3.py`, diagnostic CSV | PASS |
| Explicit RNG and reproducible outcomes | Same seed yields identical channel samples; paired sweeps reuse streams | Tests, CSV seed columns, configuration JSON | PASS |
| End-to-end M2 integration | Noiseless recovery, tone-only composition and exact AWGN M2 parity pass | `tests/test_channel_m3.py` | PASS |
| M1/M2 regression suite preserved | Complete test run reports 45 passing (30 prior tests + 15 new) | `results/m3/test_run.txt` | PASS |
| AWGN baseline experiment actually executed | Five SNR values, actual errors/BER/95% intervals/theory saved; 4 dB excursion disclosed | `m3_awgn_baseline.csv`, run log, baseline plot | PASS |
| Full tone amplitude sweep executed | Five predefined amplitudes and diagnostics saved | `m3_interference_amplitude.csv`, plot | PASS |
| Tone frequency analysis executed | Five valid frequencies with shared bits/noise and measured BER | `m3_interference_frequency.csv`, plot | PASS |
| Attenuation and effective Eb/N0 verified | Five attenuations compared with adjusted theory; separate noiseless attenuation confirms zero observed errors | `m3_attenuation.csv`, `m3_noiseless_attenuation.csv`, plot | PASS |
| Combined channel experiment executed | AWGN + tone + attenuation; exact BER interval and powers recorded, no unsupported theory claim | `m3_combined_channel.csv`, metadata, plot | PASS |
| Required plots and numeric/config outputs saved | Four BER plots and four waveform/spectrum/comparison plots; CSV/JSON/log evidence exists | `results/m3/` | PASS |
| M3 report and documentation complete | README, system design order, implementation status and this report updated | Documentation files | PASS |
| M4/later scope not started | No receiver improvement or later milestone implementation | Source tree and scope record | PASS |

## L. شرح هندسي بالعربية

### كيف تعمل القناة

تستقبل القناة موجة M2 بعد تشكيل النبضات، وتحسب نسخة الإشارة المطلوبة بعد التوهين، ثم تولّد موجة جيبية اختيارية، وبعد ذلك تضيف ضوضاء AWGN اختيارية. الناتج هو (r[n]=g s[n]+i[n]+w[n]). ترجع الدالة الإشارة النهائية وكل مكوّن على حدة، لذلك يمكن التحقق رقميًا من أن مجموع الإشارة المخفّضة والنغمة والضوضاء يساوي عينات الاستقبال. لا تغيّر القناة عدد العينات ولا تنفذ أي معالجة من المستقبل.

### الفرق بين AWGN والتداخل الجيبي

ضوضاء AWGN عشوائية، صفرية المتوسط، وعيناتها مستقلة وفق توزيع Gaussian بالتباين الذي يحدده (E_b/N_0). أما التداخل الجيبي فموجة منظمة ومتكررة لها سعة قمة وتردد وطور ابتدائي محدد. لذلك قد تتغير أخطاء البتات كثيرًا عند تغيير تردد النغمة حتى لو بقيت سعتها ثابتة: التردد القريب من نطاق إشارة RRC يمر عبر المرشح المطابق بدرجة أكبر، بينما التردد خارج هذا النطاق يضعف في مسار الاستقبال. أظهرت التجربة عند 6 dB أن BER بلغ 3.41% عند 0.15 cycles/symbol و3.06% عند 0.35، مقابل قرابة 0.19% حول 0.7 إلى 1.6 في الإعدادات المختبرة. هذه نتائج هذه الموجة والطور والتوقيت، وليست قاعدة لكل قناة.

### نموذج التوهين

يحوّل التوهين (A_{dB}) إلى كسب جهد (g=10^{-A_{dB}/20}). التوهين 2 dB مثلًا يعطي كسبًا يقارب 0.794. في هذا النموذج تنخفض سعة الإشارة المطلوبة فقط، بينما تظل قدرة AWGN كما ضبطت، ويضاف التداخل بعد التوهين. لذلك ينخفض (E_b/N_0) الفعال بمقدار dB التوهين عندما لا يوجد تداخل. سجلت تجربة 6 dB أن BER ارتفع من 0.002 عند توهين 0 dB إلى 0.13 عند توهين 8 dB. أما في غياب الضوضاء والتداخل، فالتوهين يضرب القيم الموجبة والسالبة بعامل موجب، ولذلك لم تظهر أخطاء في 30,000 بت عند القيم المختبرة.

### كيف أُجريت تجارب BER

ولّدت التجارب 30,000 بت مرة واحدة، ومررتها عبر BPSK وتشكيل RRC الحالي. استخدمت كل نقطة bits ثابتة، وأنشأت مولدات عشوائية صريحة ببذور مشتقة من seed رئيسي محفوظ. وفي مقارنات سعة التداخل وتردده والتوهين، استُخدم realization الضوضاء نفسه لكل الحالات المقارنة. بعد تطبيق القناة، استُخدم مستقبل M2 نفسه دون تعديل، ثم حُسب عدد الأخطاء وBER وفاصل Clopper–Pearson الدقيق 95%. تسجل ملفات CSV الإعدادات والقدرة والضوضاء المقاسة والنتائج؛ ويحفظ ملف JSON قواعد التطبيع والبذور وإصدارات المكتبات.

### ما الذي تثبته النتائج وما حدودها

تثبت الاختبارات أن معاملات التوهين والتداخل والضوضاء تطبق كما عُرّفت، وأن القناة قابلة لإعادة الإنتاج، وأن AWGN-only بقي مطابقًا لتطبيق M2 عند تثبيت seed. التجارب توضح أثر التردد والسعة والتوهين في هذا النظام المحدد. لا تثبت النتائج أن كل نغمة تزيد BER، ولا أن النظام يزيل التداخل عمومًا. إحدى نقاط AWGN عند 4 dB وقعت خارج فاصلها 95% مقارنة بالنظرية، وقد تم الإبلاغ عنها صراحة. حجم 30 ألف بت يعطي دقة محدودة، خصوصًا عند 8 dB حيث رُصدت خمسة أخطاء فقط. النموذج لا يشمل واقع RF أو PSD مستمر، ولا التزامن أو التلاشي أو المسارات المتعددة أو تحسين المستقبل.

## M. جاهزية M4

يوفر M3 أساسًا واضحًا لاختبار مستقبل لاحق: توجد طريقة مستقلة قابلة للضبط لإضافة AWGN ونغمة وتوهين، وتُعاد الحالات ببذور وبيانات معروفة، كما تتوفر موجات المكونات والقياسات المطلوبة لمقارنة BER. لا تتضمن هذه المرحلة أي مرشح notch أو استعادة أو إلغاء تداخل أو تحسين للمستقبل. لذلك فهي **تهيئ المدخلات والتجارب** لتقييم M4 مستقبلًا، لكنها لا تدّعي أن تحسينًا قد صُمّم أو جرى اختباره.
