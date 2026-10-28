from io import BytesIO
import struct
import wave

import numpy as np
import pytest

from signalshield.application import MessageSimulationConfig
from signalshield.audio import load_wav, make_wav
from signalshield.fec import decode, encode
from signalshield.payload_application import run_payload_simulation
from signalshield.payload_frame import FrameError, bits_to_bytes, build_frame, bytes_to_bits, parse_frame


def wav_data(values, rate=8000, channels=1):
    buf = BytesIO()
    arr = np.asarray(values, dtype="<i2")
    if channels == 2:
        arr = np.column_stack((arr, arr))
    from scipy.io import wavfile
    wavfile.write(buf, rate, arr)
    return buf.getvalue()


def test_text_frame_crc_and_malformed_lengths():
    frame = build_frame("مرحبا".encode())
    parsed = parse_frame(frame)
    assert parsed.payload == "مرحبا".encode() and parsed.crc_valid
    damaged = bytearray(frame); damaged[-5] ^= 1
    assert not parse_frame(bytes(damaged)).crc_valid
    with pytest.raises(FrameError): parse_frame(frame[:-1])
    damaged_id = b"NOPE" + frame[4:]
    with pytest.raises(FrameError): parse_frame(damaged_id)


def test_hamming_every_single_bit_position():
    source = np.array([1, 0, 1, 1, 0, 1, 0, 0], dtype=np.uint8)
    code = encode(source)
    assert np.array_equal(decode(code)[0], source)
    for i in range(7):
        damaged = code.copy(); damaged[i] ^= 1
        got, count = decode(damaged)
        assert np.array_equal(got, source) and count == 1


def test_hamming_double_flip_is_checked_by_downstream_frame_crc():
    frame = build_frame(b"payload")
    bits = bytes_to_bits(frame)
    coded = encode(bits)
    coded[-1] ^= 1
    coded[-2] ^= 1
    decoded, _ = decode(coded)
    parsed = parse_frame(bits_to_bytes(decoded))
    assert not parsed.crc_valid


def test_audio_normalization_metadata_and_round_trip():
    source = wav_data(np.arange(800, dtype=np.int16), rate=16000)
    payload = load_wav(source)
    assert payload.metadata["sample_rate"] == 8000
    assert payload.metadata["source_sample_rate"] == 16000
    assert len(payload.pcm_bytes) == 800
    wav = make_wav(payload.pcm_bytes)
    recovered = load_wav(wav)
    assert recovered.metadata["frame_count"] == 400
    assert np.array_equal(recovered.samples, payload.samples)


def test_audio_unsupported_or_too_long_rejected():
    with pytest.raises(ValueError, match="8–48 kHz"):
        load_wav(wav_data(np.zeros(8010, dtype=np.int16), rate=8000))
    with pytest.raises(ValueError, match="16-bit"):
        from scipy.io import wavfile
        stream = BytesIO(); wavfile.write(stream, 8000, np.zeros(20, dtype=np.float32))
        load_wav(stream.getvalue())
    with pytest.raises(ValueError, match="Invalid WAV"):
        load_wav(b"bad")


def test_end_to_end_framed_text_and_corruption_status():
    cfg = MessageSimulationConfig(message="CRC test", awgn_enabled=False, seed=22)
    result = run_payload_simulation(cfg, fec_enabled=True)
    assert result.receivers["Baseline Receiver"].crc_valid
    assert result.receivers["Baseline Receiver"].exact_match


def test_end_to_end_clean_audio_payload():
    audio = load_wav(wav_data((np.sin(np.arange(80) / 5) * 10000).astype(np.int16)))
    cfg = MessageSimulationConfig(message="audio placeholder", awgn_enabled=False, seed=18)
    result = run_payload_simulation(cfg, payload_type="audio", payload=audio.pcm_bytes,
                                    audio_metadata=audio.metadata, fec_enabled=True)
    out = result.receivers["Baseline Receiver"]
    assert out.crc_valid and out.exact_match and out.recovered_audio_wav


def test_paired_payload_receivers_share_transmission_and_report_comparison():
    cfg = MessageSimulationConfig(message="paired engineering run", awgn_enabled=False,
        receiver="Both (paired comparison)", interference_enabled=True,
        interference_amplitude_peak=0.25, interference_frequency_cycles_per_symbol=0.35)
    result = run_payload_simulation(cfg, fec_enabled=False)
    assert set(result.receivers) == {"Baseline Receiver", "Notch-Filtered Receiver"}
    assert result.comparison is not None
    baseline = result.receivers["Baseline Receiver"]
    notch = result.receivers["Notch-Filtered Receiver"]
    expected = baseline.coded_ber - notch.coded_ber
    assert result.comparison["ber_difference_notch_minus_baseline"] == pytest.approx(-expected)
    assert result.comparison["corrected_errors"] + result.comparison["shared_errors"] == baseline.coded_errors


def test_severely_noisy_transmission_does_not_claim_success():
    cfg = MessageSimulationConfig(message="noise integrity", awgn_enabled=True,
                                  ebn0_db=-20, seed=7)
    out = run_payload_simulation(cfg, fec_enabled=False).receivers["Baseline Receiver"]
    assert not (out.crc_valid and out.exact_match)
