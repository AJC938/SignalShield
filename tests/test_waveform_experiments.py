from scipy.stats import binomtest

from signalshield.config import WaveformConfig
from signalshield.waveform_experiments import (
    derive_waveform_sweep_points,
    simulate_waveform_point,
    write_waveform_results,
)


def test_waveform_ber_is_consistent_with_bpsk_awgn_reference() -> None:
    point = derive_waveform_sweep_points(
        n_bits=100_000,
        ebn0_db_values=(5.0,),
        master_seed=20261028,
    )[0]
    result = simulate_waveform_point(point)
    interval = binomtest(result.errors, n=result.n_bits).proportion_ci(
        confidence_level=0.99,
        method="exact",
    )
    assert interval.low <= result.theoretical_ber <= interval.high
    assert result.n_bits == 100_000
    assert result.tap_count == 81
    assert result.total_decision_delay_samples == 80


def test_waveform_result_writer_saves_data_config_and_six_plots(tmp_path) -> None:
    waveform = WaveformConfig(samples_per_symbol=4, rolloff=0.35, span_symbols=10)
    points = derive_waveform_sweep_points(
        n_bits=64,
        ebn0_db_values=(10.0,),
        master_seed=58,
        waveform=waveform,
    )
    results = tuple(simulate_waveform_point(point) for point in points)
    outputs = write_waveform_results(
        tmp_path,
        points=points,
        results=results,
        master_seed=58,
    )
    assert len(outputs) == 11
    assert all(output.is_file() and output.stat().st_size > 0 for output in outputs)
    metadata = outputs[1].read_text(encoding="utf-8")
    assert '"samples_per_symbol": 4' in metadata
    assert '"tap_count": 41' in metadata
    assert '"decision_index_rule"' in metadata
