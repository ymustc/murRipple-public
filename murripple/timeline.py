"""把各模块的分析结果组装成 timeline.json。

这里只做组装与校验，不做分析——分析全在 analyze/lanes/align 里。
"""

from __future__ import annotations

import numpy as np

from murripple.analyze import detect_beats, detect_sections, sections_from_marks
from murripple.envelope import encode_u8, quantize, rms_envelope
from murripple.lanes import build_lanes, lanes_from_specs
from murripple.schema import SCHEMA_VERSION, validate_timeline

# 人声 RMS 高于全曲峰值的这个比例才算"在唱"
PRESENCE_THRESHOLD = 0.02


def build_timeline(
    title: str,
    stem_audio: dict[str, np.ndarray],
    sr: int,
    lyrics: list[dict],
    bitrate_label: str,
    section_marks: list[dict] | None = None,
    lane_specs: list[dict] | None = None,
    language: str | None = None,
) -> dict:
    """组装一份通过 schema 校验的 timeline 文档。

    `section_marks` 可选：合成的曲子自带真实段落边界（真值），给了就直接
    用、跳过 `detect_sections` 的自相似矩阵猜测；不给行为与此前一行不变。

    `lane_specs` 可选：合成的曲子自带轨道真值（每条 lane 的 id/label/hue/
    stem/notes 都是已知的），给了就直通 `lanes_from_specs`，跳过
    `build_lanes` 的带通切分 + onset 检测猜测；不给行为与此前一行不变。

    判断用的是 `is not None`，不是真值判断（`if lane_specs`）——两者的
    分歧只在 `lane_specs=[]`（空列表）这一种输入上：真值判断会把它当
    "没给"处理，悄悄落回 `build_lanes` 那条检测老路，产出一份看起来
    正常、其实完全没用轨道真值的六条 lane，不报任何错。`is not None`
    则会把 `[]` 交给 `lanes_from_specs`，原样得到空的 lanes 列表，随后
    `validate_timeline()` 会因为 `doc["lanes"]` 违反 schema 的
    `minItems: 1` 当场炸掉——同一个误用，从"静默出错的产物"变成
    "构建时就失败"。Task 8（尚未落地，见
    `.superpowers/sdd/2026-08-13-m5-v2-stems/task-8-brief.md`）计划让
    `murripple/cli.py` 的 `load_lane_specs()` 在 `lanes.json` 是空数组
    时直接拒收、不把 `[]` 传下来，届时这条分支会在上游再被挡一道；但
    timeline.py 本身不依赖那份未来的保证——就算以后有别的调用方跳过
    `load_lane_specs` 直接传一个空列表，这里也要报错而不是悄悄切回
    老路。见
    `tests/test_timeline.py::test_empty_lane_specs_list_is_rejected_not_silently_ignored`。
    """
    vocals = np.asarray(stem_audio["vocals"], dtype=np.float32)
    mix = sum(np.asarray(stem_audio[k], dtype=np.float32) for k in stem_audio)
    duration = len(mix) / sr

    bpm, beats, downbeats = detect_beats(mix, sr)
    sections = (
        sections_from_marks(mix, sr, section_marks)
        if section_marks
        else detect_sections(mix, sr)
    )

    # 合成的曲子自带轨道真值，直通；真歌没有，照旧切频段。判断用
    # `is not None`，理由见函数 docstring。
    lanes_raw = (
        lanes_from_specs(stem_audio, sr, lane_specs)
        if lane_specs is not None
        else build_lanes(stem_audio, sr)
    )
    vocal_env = rms_envelope(vocals, sr)
    mix_env = rms_envelope(mix, sr)

    # 跨全部轨道共享峰值，保留相对响度。注意：mix_env 的峰值故意不计入
    # 这里——mix 是四轨之和，峰值通常明显高于任何单条 lane 或人声轨，
    # 一旦计入会推高 global_peak，进而按 dB 刻度把六条 lane 一并拉暗
    # （quantize 是跨轨共享同一个 global_peak 的 dB 映射，见
    # test_global_peak_is_shared_across_lanes）。纯器乐回退（见下）只换
    # ring 的数据源，不改变这个归一化基准。
    peaks = [float(lane["envelope_raw"].max()) for lane in lanes_raw]
    peaks.append(float(vocal_env.max()))
    global_peak = max(peaks) or 1.0

    presence = np.where(
        vocal_env > PRESENCE_THRESHOLD * global_peak, 255, 0
    ).astype(np.uint8)

    # spec 第 15 节：纯器乐、检测不到人声 → 环改由整体能量驱动，跳过歌词层，
    # 不中断。presence 已经是逐帧"是否在唱"的二值判断；全曲为 0 就是
    # "检测不到人声"，复用它作判定信号，不必新引入阈值。presence 本身
    # 仍然保持全 0，诚实反映没有人声，供渲染层据此选择不同表现。
    ring_env = mix_env if presence.max() == 0 else vocal_env

    lanes = [
        {
            "id": lane["id"],
            "label": lane["label"],
            "hue": lane["hue"],
            "stem": lane["stem"],
            "gain": lane["gain"],
            "notes": lane["notes"],
            "envelope": encode_u8(quantize(lane["envelope_raw"], global_peak)),
        }
        for lane in lanes_raw
    ]

    doc = {
        "meta": {
            "title": title,
            "duration": float(duration),
            "bpm": float(bpm),
            "codec": bitrate_label,
            "schemaVersion": SCHEMA_VERSION,
            # **只有 WhisperX 真的听过这首歌才有这一格。** 硬字幕那条路、
            # 没有 lyrics.txt、`--no-lyrics`、器乐曲，都一次都没听过——那时
            # 补一个"大概是 zh"进去，正是这一棒禁止的沉默地猜。所以它是
            # 可选字段（schema 里不在 required 里），缺席本身就是一句实话：
            # 这首歌的语言没有人问过。
            **({"language": language} if language else {}),
        },
        "stems": sorted(stem_audio),
        "sections": sections,
        "beats": beats,
        "downbeats": downbeats,
        "ring": {
            "envelope": encode_u8(quantize(ring_env, global_peak)),
            "presence": encode_u8(presence),
        },
        "lanes": lanes,
        "lyrics": lyrics,
    }
    validate_timeline(doc)
    return doc
