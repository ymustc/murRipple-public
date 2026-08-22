import numpy as np

from murripple.envelope import (
    ENVELOPE_RATE,
    decode_u8,
    encode_u8,
    quantize,
    rms_envelope,
)


def test_envelope_is_60hz(full_scale, sr):
    env = rms_envelope(full_scale, sr)
    # 2 秒 × 60 Hz = 120 帧，允许边界上下 1 帧
    assert abs(len(env) - 2 * ENVELOPE_RATE) <= 1


def test_silence_quantizes_to_zero(silence, sr):
    env = rms_envelope(silence, sr)
    u8 = quantize(env, global_peak=1.0)
    assert u8.dtype == np.uint8
    assert u8.max() == 0


def test_full_scale_quantizes_to_max(full_scale, sr):
    env = rms_envelope(full_scale, sr)
    u8 = quantize(env, global_peak=1.0)
    # 中段（避开首尾不完整的帧）应达到满值
    assert u8[10:-10].min() == 255


def test_minus_30db_lands_mid_range(full_scale, sr):
    quiet = full_scale * (10 ** (-30 / 20))  # -30 dB
    env = rms_envelope(quiet, sr)
    u8 = quantize(env, global_peak=1.0)
    # (-30 + 60) / 60 * 255 = 127.5
    assert 120 <= int(u8[10:-10].mean()) <= 135


def test_base64_roundtrip():
    arr = np.array([0, 1, 127, 254, 255], dtype=np.uint8)
    assert np.array_equal(decode_u8(encode_u8(arr)), arr)
