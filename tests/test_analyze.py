import warnings

import numpy as np

from murripple.analyze import (
    detect_beats,
    detect_onsets,
    detect_sections,
    track_pitch,
)


def test_bpm_of_120_click_track(click_track_120bpm, sr):
    bpm, beats, downbeats = detect_beats(click_track_120bpm, sr)
    assert abs(bpm - 120.0) < 2.0
    # 10 秒 120 BPM = 20 拍，检测边界允许少量出入
    assert 17 <= len(beats) <= 22
    # 4/4 假设下，小节线约为拍数的四分之一
    assert 3 <= len(downbeats) <= 7


def test_beats_land_on_half_second_grid(click_track_120bpm, sr):
    _, beats, _ = detect_beats(click_track_120bpm, sr)
    for t in beats:
        offset = abs(t - round(t / 0.5) * 0.5)
        assert offset < 0.06, f"拍点 {t} 偏离 0.5 秒网格 {offset}"


def test_onsets_match_click_positions(click_track_120bpm, sr):
    onsets = detect_onsets(click_track_120bpm, sr)
    assert 17 <= len(onsets) <= 22
    for t, v in onsets:
        assert 0.0 <= v <= 1.0
        offset = abs(t - round(t / 0.5) * 0.5)
        assert offset < 0.06


def test_silence_yields_no_onsets(silence, sr):
    assert detect_onsets(silence, sr) == []


def test_track_pitch_on_60hz_tone(tone_60hz, sr):
    # 60 Hz ≈ MIDI 34.5（B1 附近）
    pitches = track_pitch(tone_60hz, sr, times=[0.5, 1.0, 1.5])
    assert len(pitches) == 3
    for p in pitches:
        assert p is not None
        assert abs(p - 34.5) < 1.5


def test_track_pitch_emits_no_warnings(tone_60hz, sr):
    """帧长不足以覆盖 fmin 时 librosa 会告警，且低频音高不可靠。"""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        pitches = track_pitch(tone_60hz, sr, times=[1.0])
    assert pitches[0] is not None


def test_track_pitch_timestamps_are_frame_aligned(two_tone_step, sr):
    """t=0.75s 必须落在前段（110Hz / MIDI 45）。

    这是 hop_length 的回归守卫：yin 的 hop 是 frame_length//4（44100Hz
    下为 1024），而 times_like 的默认 hop 是 512。若不同步，报出的时刻
    只有真实时刻的一半，查询 0.75s 实际会取到 1.5s 那一帧——落进后段，
    音高变成 MIDI 33，断言失败。
    """
    early, late = track_pitch(two_tone_step, sr, times=[0.75, 1.75])

    assert early is not None and late is not None
    assert abs(early - 45.0) < 1.5, f"t=0.75s 应为 MIDI 45，实得 {early}"
    assert abs(late - 33.0) < 1.5, f"t=1.75s 应为 MIDI 33，实得 {late}"


def test_sections_are_ordered_and_bounded(click_track_120bpm, sr):
    sections = detect_sections(click_track_120bpm, sr, n=4)
    assert len(sections) >= 1
    assert sections[0]["t"] == 0.0
    times = [s["t"] for s in sections]
    assert times == sorted(times)
    for s in sections:
        assert 0.0 <= s["energy"] <= 1.0
        assert s["name"] == "", "段落名应为空串，留给 overrides 手写"


def test_no_borrowed_section_names(click_track_120bpm, sr):
    """段落名不得含任何硬编码的中文名。

    原实现直接复制了 light-loom 的九个乐章名，既越界又与本项目的曲目
    无关。这条测试守住"不再引入硬编码段落名"。
    """
    import murripple.analyze as analyze

    assert not hasattr(analyze, "SECTION_NAMES"), "SECTION_NAMES 应已移除"
    for s in detect_sections(click_track_120bpm, sr, n=4):
        assert s["name"] == ""
