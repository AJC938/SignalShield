import numpy as np
import pytest
from scipy.stats import binomtest

from signalshield.channel import add_awgn, ebn0_db_to_linear, noise_variance_from_ebn0_db
from signalshield.config import SimulationConfig
from signalshield.experiments import derive_sweep_points, simulate_point, write_results
from signalshield.metrics import ber_estimate, bpsk_awgn_theory
from signalshield.modulation import bpsk_demodulate, bpsk_modulate
from signalshield.receiver import detect_bpsk
from signalshield.signals import generate_bits


def test_config_validates_reference_parameters() -> None:
    assert SimulationConfig(n_bits=10, ebn0_db=4.0, seed=9).n_bits == 10
    for kwargs in (
        {"n_bits": 0},
        {"n_bits": True},
        {"seed": -1},
        {"seed": 2**32},
        {"ebn0_db": float("nan")},
        {"ebn0_db": 301.0},
        {"bit_energy": 0.0},
    ):
        with pytest.raises((TypeError, ValueError)):
            SimulationConfig(**kwargs)


def test_bit_generation_shape_values_and_seed_reproducibility() -> None:
    first = generate_bits(128, np.random.default_rng(42))
    second = generate_bits(128, np.random.default_rng(42))
    assert first.shape == (128,)
    assert first.dtype == np.uint8
    assert set(np.unique(first)).issubset({0, 1})
    np.testing.assert_array_equal(first, second)
    assert not np.array_equal(first, generate_bits(128, np.random.default_rng(43)))
    with pytest.raises(ValueError):
        generate_bits(0, np.random.default_rng(42))


def test_bpsk_mapping_demapping_and_zero_tie() -> None:
    bits = np.array([0, 1, 1, 0], dtype=np.uint8)
    np.testing.assert_array_equal(bpsk_modulate(bits), [1.0, -1.0, -1.0, 1.0])
    np.testing.assert_array_equal(bpsk_demodulate([2.0, -2.0, 0.0]), [0, 1, 0])
    np.testing.assert_array_equal(detect_bpsk([1.0, -1.0, 0.0]), [0, 1, 0])
    with pytest.raises(ValueError):
        bpsk_modulate([0, 2])


def test_noiseless_reference_chain_for_known_and_generated_bits() -> None:
    for bits in (
        np.array([0, 1, 1, 0, 1], dtype=np.uint8),
        generate_bits(10_001, np.random.default_rng(7001)),
    ):
        symbols = bpsk_modulate(bits)
        received = add_awgn(symbols, 0.0, np.random.default_rng(10))
        recovered = detect_bpsk(received)
        estimate = ber_estimate(bits, recovered)
        assert recovered.shape == bits.shape
        assert estimate.errors == 0
        assert estimate.ber == 0.0


def test_awgn_variance_matches_model_with_six_standard_error_tolerance() -> None:
    ebn0_db = 3.0
    expected_variance = noise_variance_from_ebn0_db(ebn0_db)
    count = 500_000
    noise = add_awgn(np.zeros(count), expected_variance, np.random.default_rng(54321))
    measured_variance = float(np.var(noise, ddof=1))
    standard_error = expected_variance * np.sqrt(2.0 / (count - 1))
    assert abs(float(np.mean(noise))) <= 6.0 * np.sqrt(expected_variance / count)
    assert abs(measured_variance - expected_variance) <= 6.0 * standard_error
    assert ebn0_db_to_linear(10.0) == pytest.approx(10.0)
    assert expected_variance == pytest.approx(1.0 / (2.0 * 10.0**0.3))


def test_awgn_same_seed_repeats_and_different_seed_changes_noise() -> None:
    samples = np.ones(100, dtype=np.float64)
    noise_a = add_awgn(samples, 0.25, np.random.default_rng(111))
    noise_b = add_awgn(samples, 0.25, np.random.default_rng(111))
    noise_c = add_awgn(samples, 0.25, np.random.default_rng(112))
    np.testing.assert_array_equal(noise_a, noise_b)
    assert not np.array_equal(noise_a, noise_c)
    np.testing.assert_array_equal(add_awgn(samples, 0.0, np.random.default_rng(111)), samples)


def test_ber_counts_validation_and_zero_error_bound() -> None:
    estimate = ber_estimate([0, 1, 0, 1, 1], [0, 0, 0, 1, 0])
    assert estimate.errors == 2
    assert estimate.n_bits == 5
    assert estimate.ber == pytest.approx(0.4)
    assert 0.0 < estimate.confidence_interval[0] < estimate.ber < estimate.confidence_interval[1] < 1.0

    zero = ber_estimate(np.zeros(100_000, dtype=np.uint8), np.zeros(100_000, dtype=np.uint8))
    assert zero.ber == 0.0
    assert zero.errors == 0
    assert zero.zero_error_upper_bound_95 == pytest.approx(1.0 - 0.05 ** (1.0 / 100_000))
    assert zero.confidence_interval[0] == 0.0
    assert zero.confidence_interval[1] > 0.0

    for sent, detected in (([], []), ([0, 1], [0]), ([0, 2], [0, 1])):
        with pytest.raises(ValueError):
            ber_estimate(sent, detected)


def test_theoretical_ber_values_validation_and_trend() -> None:
    assert bpsk_awgn_theory(0.0) == pytest.approx(0.07864960352514257)
    assert bpsk_awgn_theory(6.0) == pytest.approx(0.002388290780932807)
    values = bpsk_awgn_theory(np.array([0.0, 2.0, 4.0, 6.0]))
    assert np.all(np.diff(values) < 0)
    assert bpsk_awgn_theory(300.0) == 0.0
    with pytest.raises(ValueError):
        bpsk_awgn_theory([0.0, float("nan")])
    with pytest.raises(ValueError):
        bpsk_awgn_theory([[0.0, 1.0]])


def test_sweep_seed_derivation_and_single_point_integration() -> None:
    points_a = derive_sweep_points(n_bits=200_000, ebn0_db_values=(0.0, 4.0), master_seed=20261027)
    points_b = derive_sweep_points(n_bits=200_000, ebn0_db_values=(0.0, 4.0), master_seed=20261027)
    assert [(p.bit_seed, p.noise_seed) for p in points_a] == [(p.bit_seed, p.noise_seed) for p in points_b]
    assert points_a[0].bit_seed != points_a[0].noise_seed
    result = simulate_point(points_a[1])
    assert result.n_bits == 200_000
    assert 0 <= result.errors <= result.n_bits
    assert result.ber == result.errors / result.n_bits
    assert result.ci_lower <= result.ber <= result.ci_upper
    assert result.noise_variance == pytest.approx(1.0 / (2.0 * 10.0**0.4))


def test_simulated_ber_is_statistically_consistent_with_theory() -> None:
    point = derive_sweep_points(n_bits=500_000, ebn0_db_values=(4.0,), master_seed=888_321)[0]
    result = simulate_point(point)
    interval = binomtest(result.errors, n=result.n_bits).proportion_ci(
        confidence_level=0.99, method="exact"
    )
    assert interval.low <= result.theoretical_ber <= interval.high


def test_experiment_writer_saves_csv_json_and_plot(tmp_path) -> None:
    point = derive_sweep_points(n_bits=32, ebn0_db_values=(10.0,), master_seed=71)[0]
    result = simulate_point(point)
    assert result.errors == 0
    csv_path, json_path, plot_path = write_results(
        tmp_path,
        points=(point,),
        results=(result,),
        master_seed=71,
    )
    assert csv_path.is_file() and csv_path.stat().st_size > 0
    assert json_path.is_file() and json_path.stat().st_size > 0
    assert plot_path.is_file() and plot_path.stat().st_size > 0
    assert '"master_seed": 71' in json_path.read_text(encoding="utf-8")

