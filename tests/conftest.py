"""测试用合成音频。全部程序生成，不依赖任何音频素材文件。"""

import numpy as np
import pytest

SR = 44100


@pytest.fixture
def sr() -> int:
    return SR


@pytest.fixture
def silence() -> np.ndarray:
    """2 秒静音。"""
    return np.zeros(SR * 2, dtype=np.float32)


@pytest.fixture
def full_scale() -> np.ndarray:
    """2 秒满量程方波（RMS = 1.0）。"""
    return np.ones(SR * 2, dtype=np.float32)


@pytest.fixture
def click_track_120bpm() -> np.ndarray:
    """10 秒、精确 120 BPM 的点击轨：每 0.5 秒一个 5ms 脉冲。"""
    y = np.zeros(SR * 10, dtype=np.float32)
    click_len = int(SR * 0.005)
    envelope = np.exp(-np.linspace(0, 8, click_len)).astype(np.float32)
    for i in range(20):  # 10 秒 / 0.5 秒
        start = int(i * 0.5 * SR)
        y[start : start + click_len] = envelope
    return y


@pytest.fixture
def tone_60hz() -> np.ndarray:
    """2 秒 60 Hz 正弦——落在底鼓频段内。"""
    t = np.arange(SR * 2, dtype=np.float32) / SR
    return (0.9 * np.sin(2 * np.pi * 60 * t)).astype(np.float32)


@pytest.fixture
def tone_10khz() -> np.ndarray:
    """2 秒 10 kHz 正弦——落在踩镲频段内。"""
    t = np.arange(SR * 2, dtype=np.float32) / SR
    return (0.9 * np.sin(2 * np.pi * 10000 * t)).astype(np.float32)


@pytest.fixture
def two_tone_step() -> np.ndarray:
    """2 秒，前 1 秒 110 Hz（MIDI 45），后 1 秒 55 Hz（MIDI 33）。

    用于验证音高的时间戳对齐：全程不变的正弦无法暴露恒定时间偏移，
    音高在已知时刻跳变才能。两个频率都落在 YIN 的 [C1, C4] 搜索范围内。
    """
    t = np.arange(SR, dtype=np.float32) / SR
    first = 0.9 * np.sin(2 * np.pi * 110.0 * t)
    second = 0.9 * np.sin(2 * np.pi * 55.0 * t)
    return np.concatenate([first, second]).astype(np.float32)
