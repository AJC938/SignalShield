from pathlib import Path

import numpy as np
import pytest

from signalshield.application import (
    MessageSimulationConfig,
    decode_message,
    encode_message,
    result_matches_config,
    run_message_simulation,
)
from signalshield.experiment_framework import ExperimentConfig
from signalshield.experiment_runner import run_experiment
from signalshield.receiver import receive_bpsk_waveform
from signalshield.streamlit_app import MAX_PERFORMANCE_TOTAL_BITS, _performance_workload_bits


def test_public_performance_lab_workload_budget_counts_sweeps_and_repetitions():
    assert _performance_workload_bits(100_000, 2, 5) == MAX_PERFORMANCE_TOTAL_BITS
    assert _performance_workload_bits(250_000, 1, 5) > MAX_PERFORMANCE_TOTAL_BITS


def test_utf8_msb_first_bit_byte_round_trip_including_arabic_and_emoji():
    text = "SignalShield اتصال 📡"
    payload = encode_message(text)
    assert payload.payload_bytes == text.encode("utf-8")
    assert payload.bits.size == 8 * len(payload.payload_bytes)
    decoded, error = decode_message(payload.bits)
    assert decoded == text
    assert error is None


def test_invalid_utf8_payload_is_reported_without_replacement():
    bits = np.unpackbits(np.frombuffer(b"\xff", dtype=np.uint8), bitorder="big")
    decoded, error = decode_message(bits)
    assert decoded is None
    assert error is not None and "not valid UTF-8" in error


def test_message_configuration_rejects_invalid_input_and_tone_frequency():
    with pytest.raises(ValueError, match="nonempty"):
        MessageSimulationConfig(message="")
    with pytest.raises(ValueError, match="frequency"):
        MessageSimulationConfig(message="x", samples_per_symbol=8,
                                interference_frequency_cycles_per_symbol=4.0)
    with pytest.raises(ValueError, match="nonnegative"):
        MessageSimulationConfig(message="x", attenuation_db=-1.0)


def test_noiseless_end_to_end_message_recovers_exactly_and_preserves_waveform_lengths():
    config = MessageSimulationConfig(
        message="Clean SignalShield link",
        awgn_enabled=False,
        interference_enabled=False,
        attenuation_db=0.0,
        receiver="Baseline Receiver",
        seed=7,
    )
    result = run_message_simulation(config)
    receiver = result.receiver_results["Baseline Receiver"]
    expected_length = (result.payload.bits.size - 1) * config.samples_per_symbol + config.samples_per_symbol * config.span_symbols + 1
    assert result.symbols.size == result.payload.bits.size
    np.testing.assert_array_equal(result.symbols, 1.0 - 2.0 * result.payload.bits)
    assert np.dot(result.taps, result.taps) == pytest.approx(1.0)
    assert result.transmit_waveform.size == expected_length
    assert result.channel.received.shape == result.transmit_waveform.shape
    assert receiver.estimate.errors == 0
    assert receiver.estimate.ber == 0.0
    assert receiver.decoded_text == config.message
    assert receiver.exact_message_recovery
    np.testing.assert_array_equal(
        receiver.receiver_output.sample_indices,
        config.samples_per_symbol * config.span_symbols
        + np.arange(result.payload.bits.size) * config.samples_per_symbol,
    )
    assert receiver.estimate.errors == int(np.count_nonzero(
        result.payload.bits != receiver.receiver_output.detected_bits
    ))
    assert not np.any(result.channel.noise)
    assert not np.any(result.channel.interference)


def test_controls_bind_to_real_channel_components_and_receiver_configuration():
    config = MessageSimulationConfig(
        message="channel controls",
        seed=9321,
        awgn_enabled=True,
        ebn0_db=10.0,
        interference_enabled=True,
        interference_amplitude_peak=0.31,
        interference_frequency_cycles_per_symbol=0.42,
        interference_phase_rad=0.8,
        attenuation_db=3.0,
        receiver="Both (paired comparison)",
        notch_center_cycles_per_symbol=0.40,
        notch_quality_factor=25.0,
    )
    result = run_message_simulation(config)
    assert result.channel_config.ebn0_db == 10.0
    assert result.channel_config.interference_amplitude == 0.31
    assert result.channel_config.interference_frequency_cycles_per_symbol == 0.42
    assert result.channel_config.interference_phase_rad == 0.8
    assert result.channel_config.attenuation_db == 3.0
    assert result.channel.applied_gain == pytest.approx(10 ** (-3.0 / 20.0))
    np.testing.assert_allclose(result.channel.attenuated_signal,
                               result.transmit_waveform * result.channel.applied_gain)
    assert np.any(result.channel.noise)
    assert np.any(result.channel.interference)
    np.testing.assert_allclose(
        result.channel.received,
        result.channel.attenuated_signal + result.channel.interference + result.channel.noise,
    )
    assert set(result.receiver_results) == {"Baseline Receiver", "Notch-Filtered Receiver"}


def test_both_receivers_process_same_received_samples_and_counts_match_decisions():
    config = MessageSimulationConfig(
        message="paired-input check",
        awgn_enabled=False,
        interference_enabled=True,
        interference_amplitude_peak=0.4,
        interference_frequency_cycles_per_symbol=0.35,
        receiver="Both (paired comparison)",
        notch_center_cycles_per_symbol=0.35,
    )
    result = run_message_simulation(config)
    base = receive_bpsk_waveform(result.channel.received, result.taps,
                                 n_symbols=result.payload.bits.size,
                                 samples_per_symbol=config.samples_per_symbol)
    np.testing.assert_array_equal(
        result.receiver_results["Baseline Receiver"].receiver_output.detected_bits,
        base.detected_bits,
    )
    comparison = result.comparison
    assert comparison is not None and comparison["same_received_waveform"] == 1
    assert comparison["same_transmitted_bits"] == 1
    assert comparison["same_transmitted_waveform"] == 1
    assert comparison["same_channel_realization"] == 1
    assert comparison["ber_difference_notch_minus_baseline"] == pytest.approx(
        result.receiver_results["Notch-Filtered Receiver"].estimate.ber
        - result.receiver_results["Baseline Receiver"].estimate.ber
    )
    assert comparison["corrected_errors"] + comparison["shared_errors"] == result.receiver_results["Baseline Receiver"].estimate.errors
    assert comparison["introduced_errors"] + comparison["shared_errors"] == result.receiver_results["Notch-Filtered Receiver"].estimate.errors


def test_stale_message_results_are_not_valid_for_changed_configuration():
    original = MessageSimulationConfig(message="state", seed=1, awgn_enabled=False)
    result = run_message_simulation(original)
    assert result_matches_config(result, original)
    changed = MessageSimulationConfig(message="state", seed=2, awgn_enabled=False)
    assert not result_matches_config(result, changed)
    assert not result_matches_config(None, original)


def test_performance_lab_reuses_m5_runner_and_writes_interpretable_artifacts(tmp_path):
    config = ExperimentConfig(
        experiment_id="m6_ui_integration",
        scenario="receiver_comparison",
        n_bits=300,
        repetitions=1,
        master_seed=323,
        bootstrap_replicates=100,
        output_dir=str(tmp_path / "lab"),
    )
    result = run_experiment(config)
    assert result["overall_status"] == "completed"
    assert (tmp_path / "lab" / "resolved_config.json").is_file()
    assert (tmp_path / "lab" / "results.csv").is_file()
    assert (tmp_path / "lab" / "manifest.json").is_file()


def test_streamlit_app_renders_tabs_and_executes_message_form_without_browser():
    streamlit_testing = pytest.importorskip("streamlit.testing.v1")
    app_path = Path(__file__).resolve().parents[1] / "src" / "signalshield" / "streamlit_app.py"
    app = streamlit_testing.AppTest.from_file(str(app_path), default_timeout=60).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Transmit & Analyze", "Channel & Receiver Analysis", "Performance Lab"
    ]
    app.text_area[0].set_value("M6 application smoke").run()
    app.checkbox[0].uncheck().run()
    app.button[0].click().run()
    assert not app.exception
    assert any(metric.label == "Coded-bit BER" for metric in app.metric)
    assert {"Transmit", "Channel", "Receiver", "Recovery"}.issubset({tab.label for tab in app.tabs})
    assert any("Verified — exact payload match" in item.value for item in app.success)
    app.text_area[0].set_value("changed after the run").run()
    assert any("input or settings changed" in item.value for item in app.warning)
