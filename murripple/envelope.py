"""响度包络：RMS → 60 Hz → dB → uint8 → base64。

一条轨 3 分钟约 10.8 KB，相对总体积可忽略，换来每条弧形轨道随音量
精确发光。
"""

from __future__ import annotations

import base64

import numpy as np

ENVELOPE_RATE = 60
DB_FLOOR = -60.0  # 低于此值一律映射为 0


def rms_envelope(y: np.ndarray, sr: int) -> np.ndarray:
    """按 60 Hz 逐帧计算 RMS。

    hop 直接取 sr/60，帧中心天然落在 60 Hz 网格上，省掉一次重采样。
    """
    hop = max(1, round(sr / ENVELOPE_RATE))
    n_frames = int(np.ceil(len(y) / hop))
    padded = np.pad(y, (0, n_frames * hop - len(y)))
    frames = padded.reshape(n_frames, hop)
    return np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1)).astype(
        np.float32
    )


def quantize(env: np.ndarray, global_peak: float) -> np.ndarray:
    """把 RMS 包络按 dB 映射到 uint8。

    global_peak 取全部 stem 的共同峰值，以保留各轨之间的相对响度——
    否则安静的轨会和响亮的轨一样亮。个别轨太暗可用 overrides 的
    per-lane gain 提起来。
    """
    if global_peak <= 0:
        return np.zeros(len(env), dtype=np.uint8)
    ratio = np.maximum(env / global_peak, 1e-12)
    db = 20.0 * np.log10(ratio)
    scaled = (db - DB_FLOOR) / (-DB_FLOOR) * 255.0
    return np.clip(np.round(scaled), 0, 255).astype(np.uint8)


def encode_u8(arr: np.ndarray) -> str:
    """uint8 数组 → base64 字符串。"""
    return base64.b64encode(np.asarray(arr, dtype=np.uint8).tobytes()).decode("ascii")


def decode_u8(s: str) -> np.ndarray:
    """base64 字符串 → uint8 数组。"""
    return np.frombuffer(base64.b64decode(s), dtype=np.uint8)
