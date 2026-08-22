"""把 Demucs 的 4 条 stem 细分成 6 条视觉轨道。

人声不占轨道——它驱动判定环本身（见 spec 第 7 节）。剩下三条 stem
按频段拆成六条，让画面密度接近原作的八条。

注意：底鼓/军鼓/踩镲是从同一条鼓轨滤出来的，能分开画，不能分开
静音。静音粒度仍是 4（由 lane 的 stem 字段归组）。
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfiltfilt

from murripple.analyze import detect_onsets, track_pitch
from murripple.envelope import rms_envelope

LANE_SPECS: list[dict] = [
    {"id": "kick",  "label": "底鼓", "hue": 28,  "stem": "drums", "band": (None, 120.0)},
    {"id": "snare", "label": "军鼓", "hue": 350, "stem": "drums", "band": (200.0, 800.0)},
    {"id": "hat",   "label": "踩镲", "hue": 195, "stem": "drums", "band": (6000.0, None)},
    {"id": "bass",  "label": "低音", "hue": 225, "stem": "bass",  "band": (None, None)},
    {"id": "mid",   "label": "中层", "hue": 175, "stem": "other", "band": (200.0, 4000.0)},
    {"id": "air",   "label": "气层", "hue": 270, "stem": "other", "band": (4000.0, None)},
]


def bandpass(
    y: np.ndarray, sr: int, low: float | None, high: float | None
) -> np.ndarray:
    """四阶巴特沃斯带通/高通/低通。low 与 high 都为 None 时原样返回。"""
    nyq = sr / 2.0
    if low is None and high is None:
        return y
    if low is None:
        sos = butter(4, min(high, nyq * 0.99) / nyq, btype="lowpass", output="sos")
    elif high is None:
        sos = butter(4, min(low, nyq * 0.99) / nyq, btype="highpass", output="sos")
    else:
        sos = butter(
            4,
            [min(low, nyq * 0.98) / nyq, min(high, nyq * 0.99) / nyq],
            btype="bandpass",
            output="sos",
        )
    # padtype="constant"：sosfiltfilt 默认的 "odd" 端点外推对本项目里
    # 突然起振的信号（如测试用的纯音）会在起点附近反射出低频伪影，
    # 足以让理应被带外拒绝的能量在包络的第一帧冒出头。"constant" 把
    # 边界当作恒定延伸（对以 0 起振的信号等价于"起点前是静音"），
    # 更符合音频缓冲区的物理假设，也彻底压掉了这个伪影。
    return sosfiltfilt(sos, y, padtype="constant").astype(np.float32)


def build_lanes(stem_audio: dict[str, np.ndarray], sr: int) -> list[dict]:
    """由四轨 stem 生成六条视觉轨道的原始数据（包络尚未量化）。"""
    lanes: list[dict] = []
    for spec in LANE_SPECS:
        source = stem_audio[spec["stem"]]
        low, high = spec["band"]
        filtered = bandpass(np.asarray(source, dtype=np.float32), sr, low, high)

        onsets = detect_onsets(filtered, sr)
        times = [t for t, _ in onsets]
        pitches = (
            track_pitch(filtered, sr, times)
            if spec["id"] == "bass" and times
            else [None] * len(times)
        )

        notes = [
            {"t": float(t), "v": float(v), "pitch": p}
            for (t, v), p in zip(onsets, pitches)
        ]

        lanes.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "hue": float(spec["hue"]),
                "stem": spec["stem"],
                "gain": 1.0,
                "notes": notes,
                "envelope_raw": rms_envelope(filtered, sr),
            }
        )
    return lanes


def lanes_from_specs(
    stem_audio: dict[str, np.ndarray], sr: int, specs: list[dict]
) -> list[dict]:
    """一条 stem 就是一条视觉轨道——**直通，不切频段、不猜音符**。

    合成的曲子每个音符属于哪个声部是我们自己写的。带通切分与 onset 检测
    是为「只有四条 stem」的真歌准备的补救手段；对着自己刚写完的乐谱再猜
    一遍，是把已知信息丢掉再找回来。

    与 `sections_from_marks` 同一路数：**名字、色相、音符表来自真值，
    包络仍从音频算**——包络本来就是音频属性。
    """
    lanes: list[dict] = []
    for spec in specs:
        if spec["stem"] not in stem_audio:
            raise KeyError(
                f"轨道 {spec['id']!r} 要的分轨 {spec['stem']!r} 不在音频里；"
                f"现有：{'、'.join(sorted(stem_audio))}"
            )
        source = np.asarray(stem_audio[spec["stem"]], dtype=np.float32)
        lanes.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "hue": float(spec["hue"]),
                "stem": spec["stem"],
                "gain": 1.0,
                "notes": list(spec["notes"]),
                "envelope_raw": rms_envelope(source, sr),
            }
        )
    return lanes
