# M2 Sampled-Waveform Model

## Scope and defaults

M2 extends the M1 one-sample-per-bit real BPSK reference with a sampled pulse-shaped waveform and a matched-filter receiver. M1's mapping, detector, AWGN primitive, BER semantics, and regression tests remain intact. M2 does not introduce fading, gain, tone interference, coding, synchronization, or complex baseband.

Default pulse parameters are `samples_per_symbol=s=8`, RRC roll-off `β=0.35`, and filter span `L=10` symbols. Valid configurations require integer `s≥2`, positive integer `L`, `L*s` even, and `0<β≤1`. Zero roll-off is rejected explicitly. The finite tap count is `Nh=L*s+1`, and the sample times in symbol periods are `t_m=(m−(Nh−1)/2)/s`, giving endpoints `−L/2` and `+L/2`.

## RRC coefficients and normalization

Before normalization, calculate the ideal RRC impulse response

`h(t) = [sin(πt(1−β)) + 4βt cos(πt(1+β))] / [πt(1−(4βt)^2)]`.

Evaluate the continuous limits explicitly:

- `h(0) = 1 + β(4/π − 1)`.
- `h(±1/(4β)) = (β/√2)[(1+2/π)sin(π/(4β)) + (1−2/π)cos(π/(4β))]`.

The sampled tap vector is symmetric and normalized as `h ← h / sqrt(sum(h**2))`. Thus the finite discrete-time pulse has unit energy. The filter is a finite truncation of the ideal infinite-duration response; its residual symbol-spaced sidelobes are measured in `results/m2/m2_combined_symbol_response.csv` and summarized in `results/m2/m2_experiment_config.json`.

## Upsampling, convolution, and timing

Given `Nsym` symbols, place each symbol at `u[k*s]=a[k]` and zeros at the other samples. The upsampled vector length is `(Nsym−1)*s+1`. Full linear convolution with `Nh` transmit taps yields a waveform of length `(Nsym−1)*s+Nh` and preserves the transmit-filter transient.

For the real symmetric transmit pulse, the matched receive impulse response is `h_MF[n]=h[Nh−1−n]`. Full linear convolution adds `Nh−1` samples and retains the receive-filter tail. Each odd, symmetric FIR has delay `D=(Nh−1)/2`; the decision-path delay is `Dtx+Drx=2D=Nh−1`. Payload decisions use

`sample_index[k] = 2D + k*s`, for `k=0,...,Nsym−1`.

With the default `Nh=81`, `Dtx=Drx=40` samples and decision indices start at 80 and advance by 8. The implementation computes delays from actual tap lengths; it does not hard-code 80. Sampling validates that the last requested symbol lies within the full-convolution output.

The Tx/Rx cascade is `g[n]=h[n]*h_MF[n]`. Its main sample is at index `Nh−1` and equals `sum(h**2)=1`. Symbol-spaced sidelobes `g[Nh−1+k*s]`, `k≠0`, quantify finite-pulse residual ISI. They are not forced to zero.

## AWGN normalization

For unit-energy BPSK symbols, `Eb=1` by default and `γb=10^(Eb/N0_dB/10)`. Add independent real discrete-time noise to every transmitted waveform sample with

`variance_sample = N0/2 = Eb/(2*γb)`.

The matched filter's output-noise sample is a weighted sum of independent samples, so

`variance_MF = variance_sample * sum(h_MF**2) = variance_sample`,

because the receive taps have unit energy. No additional factor of samples per symbol is applied. This is a normalized discrete-time model, not an absolute continuous-time PSD or ADC claim.

## BER reference and limitations

For an infinite-duration Nyquist pulse pair and the coherent symbol detector, the reference is the uncoded BPSK/AWGN formula `Pb=0.5*erfc(sqrt(Eb/N0))`. A finite RRC truncation introduces measured residual ISI, so agreement is statistical and approximate. Report bit counts, errors, confidence intervals, the measured sidelobes, and high-SNR resolution; do not claim exact zero ISI or infer continuous-time behavior.

