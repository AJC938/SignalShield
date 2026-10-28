# SignalShield Learning and Review Guide

Use this guide alongside the implementation milestones. For each topic, explain the idea in your own words, derive the relevant equation, and predict how a deliberate fault would change output before looking at the test.

| Milestone | Concepts to understand | Likely failure modes | Questions to answer independently |
|---|---|---|---|
| T01–T02: bits, mapping, reference | Bernoulli bits, BPSK antipodal mapping, energy per bit, coherent threshold detection | Bit convention inverted, integer/float confusion, wrong threshold tie, hidden RNG | Why does `0→+1` make zero-threshold detection work? What is `Eb` for unit BPSK? |
| T03–T04: AWGN and BER | dB vs linear ratio, real Gaussian variance, `Q`/`erfc`, binomial trials and confidence | Using `1/γ` instead of `1/(2γ)`, dB used as linear, resetting RNG, claiming zero BER | Derive `σ²=N0/2`; why does a finite run not prove BER is zero? |
| T05–T06: RRC waveform | Upsampling, convolution, pulse energy, matched filter, group delay, Nyquist criterion, residual truncation ISI | Tap normalization by peak/sum, off-by-one delay, dropping convolution tails, scaling noise with L incorrectly | Why does unit-energy receive filtering preserve noise variance? Which sample index is the first decision? |
| T07–T08: tone and notch | Narrowband interference, frequency response, Q, causal filtering, transients, paired experiments | Filtering after decisions, `filtfilt`, ignoring signal spectrum, different random draws, frequency units mismatch | Under what condition can a notch lower BER? How can it worsen BER while reducing tone amplitude? |
| T09–T10: reproducibility and validation | Exact vs statistical tests, uncertainty, metadata, clean install, measured vs theoretical results | Undocumented configuration, overwritten results, unstable tests, plot mistaken for evidence | What does the confidence interval say when errors are zero? How would another person reproduce this exact point? |

## Final technical review questions

1. Derive coherent BPSK BER from the decision statistic and Gaussian tail probability.
2. Explain why `Eb/N0` is converted from dB using `10^(dB/10)` and why the real noise variance has a factor of two.
3. Distinguish sample power, pulse energy, symbol energy, and continuous-time PSD.
4. Derive the noise variance after a matched filter for arbitrary tap energy, then specialize to unit-energy taps.
5. Show how transmit and receive FIR delays determine the sampler indices.
6. Explain why a finite RRC pulse can leave residual ISI even with a mathematically Nyquist pulse shape.
7. Explain how attenuation affects effective `Eb/N0` when the receiver does not know or compensate for gain.
8. Explain how to make a baseline/notch comparison paired and why pairing improves the comparison.
9. Identify the notch's wanted-signal and delay costs and describe an experiment that could falsify its usefulness.
10. State the system's security and realism boundaries without describing this simulation as a production jammer defense.

