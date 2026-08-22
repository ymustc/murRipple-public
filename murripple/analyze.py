"""节拍、小节线、onset、音高与段落分析。

全部是纯函数：输入 numpy 数组，输出普通 Python 数据。无 IO，无外部
进程，因此测试用合成音频即可，跑得很快。
"""

from __future__ import annotations

import librosa
import numpy as np

# bass 轨音高跟踪的搜索范围
FMIN_HZ = 32.70319566257483   # C1
FMAX_HZ = 261.6255653005986   # C4


def detect_beats(y: np.ndarray, sr: int) -> tuple[float, list[float], list[float]]:
    """返回 (bpm, 拍点秒数, 小节线秒数)。

    librosa 不检测小节线。这里按 4/4 假设，从 onset 强度最大的那一拍
    起每四拍取一个作为小节线——绝大多数流行/电子曲目成立，不成立时
    可用 overrides 修正。
    """
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])
    beats = [float(t) for t in librosa.frames_to_time(beat_frames, sr=sr)]

    if not beats:
        return bpm, [], []

    strength = librosa.onset.onset_strength(y=y, sr=sr)
    beat_strength = [
        float(strength[min(f, len(strength) - 1)]) for f in beat_frames
    ]
    phase = int(np.argmax(beat_strength)) % 4
    downbeats = [t for i, t in enumerate(beats) if i % 4 == phase]
    return bpm, beats, downbeats


def detect_onsets(y: np.ndarray, sr: int) -> list[tuple[float, float]]:
    """返回 [(时间, 归一化强度)]，强度按本轨最大值归一到 0–1。"""
    if not np.any(y):
        return []

    strength = librosa.onset.onset_strength(y=y, sr=sr)
    frames = librosa.onset.onset_detect(
        onset_envelope=strength, sr=sr, backtrack=True
    )
    if len(frames) == 0:
        return []

    times = librosa.frames_to_time(frames, sr=sr)
    peak = float(strength.max()) or 1.0
    out: list[tuple[float, float]] = []
    for f, t in zip(frames, times):
        v = float(strength[min(f, len(strength) - 1)]) / peak
        out.append((float(t), float(np.clip(v, 0.0, 1.0))))
    return out


def _yin_frame_length(sr: int) -> int:
    """YIN 要求 frame_length >= 2*sr/fmin 才能分辨出最低音。

    默认的 2048 在 44100 Hz 下不足以覆盖 C1（需要 2698），librosa 会
    告警，而且低频音高会不可靠——恰恰是 bass 轨最需要的那一段。这里
    按采样率算出需求再向上取到 2 的幂。
    """
    need = int(np.ceil(2 * sr / FMIN_HZ))
    return 1 << (need - 1).bit_length()


def track_pitch(
    y: np.ndarray, sr: int, times: list[float]
) -> list[float | None]:
    """在给定时刻取基频并转成 MIDI 音高。用于 bass 轨（单音）。"""
    if not times:
        return []

    frame_length = _yin_frame_length(sr)
    f0 = librosa.yin(
        y,
        fmin=FMIN_HZ,
        fmax=FMAX_HZ,
        sr=sr,
        frame_length=frame_length,
    )
    frame_times = librosa.times_like(f0, sr=sr, hop_length=frame_length // 4)

    out: list[float | None] = []
    for t in times:
        idx = int(np.argmin(np.abs(frame_times - t)))
        hz = float(f0[idx])
        if not np.isfinite(hz) or hz <= 0:
            out.append(None)
        else:
            out.append(float(librosa.hz_to_midi(hz)))
    return out


def detect_sections(y: np.ndarray, sr: int, n: int = 9) -> list[dict]:
    """用自相似矩阵把全曲切成若干段落。

    精度中等，只影响配色，不作为关键视觉依据，可用 overrides 修正。

    段落名一律为空串，由 overrides.json 手写填入——自动分段精度中等，
    打出一个猜的名字比不打更糟。
    """
    duration = len(y) / sr
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    n_eff = max(1, min(n, chroma.shape[1]))
    bounds = librosa.segment.agglomerative(chroma, n_eff)
    times = librosa.frames_to_time(bounds, sr=sr)

    rms = librosa.feature.rms(y=y)[0]
    rms_times = librosa.times_like(rms, sr=sr)
    peak = float(rms.max()) or 1.0

    bounds_t = [t for t in sorted({0.0, *(float(x) for x in times)}) if t < duration]

    sections: list[dict] = []
    for i, t in enumerate(bounds_t):
        end = bounds_t[i + 1] if i + 1 < len(bounds_t) else duration
        mask = (rms_times >= t) & (rms_times < max(end, t + 1e-6))
        energy = float(rms[mask].mean() / peak) if mask.any() else 0.0
        sections.append(
            {
                "t": float(t),
                "name": "",
                "energy": float(np.clip(energy, 0.0, 1.0)),
            }
        )
    return sections or [{"t": 0.0, "name": "", "energy": 0.0}]


def sections_from_marks(y: np.ndarray, sr: int, marks: list[dict]) -> list[dict]:
    """按**给定的**段落边界算能量，不做检测。

    合成的曲子知道自己的段落边界，那是真值；`detect_sections` 是拿自相似
    矩阵猜出来的。有真值就别再猜——与『硬字幕时间戳存在时整个跳过
    WhisperX』是同一条道理。`energy` 仍从音频算，因为它本来就是音频属性。
    """
    duration = len(y) / sr
    rms = librosa.feature.rms(y=y)[0]
    rms_times = librosa.times_like(rms, sr=sr)
    peak = float(rms.max()) or 1.0

    sections: list[dict] = []
    for i, mark in enumerate(marks):
        start = float(mark["t"])
        end = float(marks[i + 1]["t"]) if i + 1 < len(marks) else duration
        mask = (rms_times >= start) & (rms_times < max(end, start + 1e-6))
        energy = float(rms[mask].mean() / peak) if mask.any() else 0.0
        sections.append({
            "t": start,
            "name": str(mark["name"]),
            "energy": float(np.clip(energy, 0.0, 1.0)),
        })
    return sections
