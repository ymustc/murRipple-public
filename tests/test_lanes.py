import numpy as np

from murripple.lanes import LANE_SPECS, bandpass, build_lanes, lanes_from_specs


def test_six_lanes_defined():
    assert len(LANE_SPECS) == 6
    ids = [s["id"] for s in LANE_SPECS]
    assert ids == ["kick", "snare", "hat", "bass", "mid", "air"]
    for spec in LANE_SPECS:
        assert spec["stem"] in {"drums", "bass", "other"}
        assert 0 <= spec["hue"] <= 360


def test_bandpass_keeps_in_band_energy(tone_60hz, sr):
    out = bandpass(tone_60hz, sr, low=None, high=120.0)
    assert np.sqrt(np.mean(out**2)) > 0.5 * np.sqrt(np.mean(tone_60hz**2))


def test_bandpass_rejects_out_of_band_energy(tone_10khz, sr):
    out = bandpass(tone_10khz, sr, low=None, high=120.0)
    assert np.sqrt(np.mean(out**2)) < 0.05 * np.sqrt(np.mean(tone_10khz**2))


def test_kick_lane_lights_up_for_low_tone(tone_60hz, tone_10khz, sr):
    stems = {
        "vocals": np.zeros_like(tone_60hz),
        "drums": tone_60hz,
        "bass": np.zeros_like(tone_60hz),
        "other": np.zeros_like(tone_60hz),
    }
    lanes = {lane["id"]: lane for lane in build_lanes(stems, sr)}
    assert lanes["kick"]["envelope_raw"].max() > 0.1
    assert lanes["hat"]["envelope_raw"].max() < 0.02


def test_hat_lane_lights_up_for_high_tone(tone_10khz, sr):
    stems = {
        "vocals": np.zeros_like(tone_10khz),
        "drums": tone_10khz,
        "bass": np.zeros_like(tone_10khz),
        "other": np.zeros_like(tone_10khz),
    }
    lanes = {lane["id"]: lane for lane in build_lanes(stems, sr)}
    assert lanes["hat"]["envelope_raw"].max() > 0.1
    assert lanes["kick"]["envelope_raw"].max() < 0.02


def test_bass_lane_notes_carry_pitch(click_track_120bpm, sr, tone_60hz):
    # 用 60 Hz 正弦调制的点击轨，保证既有 onset 又有可跟踪的基频
    bass = click_track_120bpm[: len(tone_60hz)] + 0.5 * tone_60hz
    stems = {
        "vocals": np.zeros_like(bass),
        "drums": np.zeros_like(bass),
        "bass": bass.astype(np.float32),
        "other": np.zeros_like(bass),
    }
    lanes = {lane["id"]: lane for lane in build_lanes(stems, sr)}
    notes = lanes["bass"]["notes"]
    assert notes, "bass 轨应至少检出一个音符"

    pitched = [n["pitch"] for n in notes if n["pitch"] is not None]
    assert pitched, "bass 轨应至少有一个音符带音高"
    # 信号里只有 60 Hz 一个基频（≈ MIDI 34.5）。只断言 "不是 None" 挡不住
    # 垃圾值——八度错误会偏 ±12，采样错位会取到静音段，都落在这个窗口外。
    assert all(abs(p - 34.5) < 3.0 for p in pitched), f"音高偏离 60Hz: {pitched}"


def test_every_lane_has_required_fields(click_track_120bpm, sr):
    stems = {k: click_track_120bpm for k in ("vocals", "drums", "bass", "other")}
    for lane in build_lanes(stems, sr):
        assert set(lane) == {
            "id",
            "label",
            "hue",
            "stem",
            "gain",
            "notes",
            "envelope_raw",
        }
        for note in lane["notes"]:
            assert set(note) == {"t", "v", "pitch"}
            assert 0.0 <= note["v"] <= 1.0


def _tone(sr, seconds=2.0, freq=440.0):
    t = np.arange(int(sr * seconds), dtype=np.float32) / sr
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_passthrough_keeps_the_given_notes_verbatim(sr):
    """轨道真值来自乐谱，不许被"优化"。逐条比对，不是比数量。"""
    audio = {"arp": _tone(sr)}
    notes = [{"t": 0.25, "v": 0.6, "pitch": 72},
             {"t": 0.75, "v": 0.9, "pitch": None}]
    lanes = lanes_from_specs(audio, sr, [
        {"id": "arp", "label": "泠泠", "hue": 165.0, "stem": "arp", "notes": notes}
    ])
    assert lanes[0]["notes"] == notes


def test_passthrough_does_not_bandpass(sr, monkeypatch):
    """直通就是不切频段。带通一旦被调用，说明走错了路径。"""
    import murripple.lanes as L

    monkeypatch.setattr(L, "bandpass", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("直通路径不该调 bandpass")))
    lanes_from_specs({"arp": _tone(sr)}, sr, [
        {"id": "arp", "label": "泠泠", "hue": 165.0, "stem": "arp", "notes": []}
    ])


def test_passthrough_does_not_detect_onsets(sr, monkeypatch):
    """音符表是真值，不该再从波形里猜一遍。"""
    import murripple.lanes as L

    monkeypatch.setattr(L, "detect_onsets", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("直通路径不该调 detect_onsets")))
    lanes_from_specs({"arp": _tone(sr)}, sr, [
        {"id": "arp", "label": "泠泠", "hue": 165.0, "stem": "arp", "notes": []}
    ])


def test_passthrough_still_computes_envelope_from_audio(sr):
    """包络是音频属性，必须从波形算——正如段落的 energy。"""
    lanes = lanes_from_specs({"arp": _tone(sr)}, sr, [
        {"id": "arp", "label": "泠泠", "hue": 165.0, "stem": "arp", "notes": []}
    ])
    env = lanes[0]["envelope_raw"]
    assert env.size > 0
    assert float(env.max()) > 0.01


def test_passthrough_envelope_comes_from_its_own_stem_not_another(sr):
    """两条以上 stem 时，每条 lane 的 envelope_raw 必须来自它自己 stem
    指名的那条音频，不是字典里随便一条或永远第一条。

    这条洞是 brief 原有的
    test_passthrough_still_computes_envelope_from_audio 漏掉的：那条测试
    只放了一条 stem（`{"arp": _tone(sr)}`），在只有一条的配置下"从
    spec['stem'] 指定的那条算包络"和"从随便哪条算包络"产出完全一样——
    把实现改成 `next(iter(stem_audio.values()))`，甚至改成永远取字典里
    第一条，那条测试照样绿。这里刻意放两条响度悬殊的 stem，并让
    stem_audio 的字典插入顺序与 specs 的顺序相反（先插 quiet 后插
    loud，但第一条 spec 要的是 loud），专门堵"永远取第一条"这个变异。
    """
    from murripple.envelope import rms_envelope

    n = int(sr * 1.0)
    t = np.arange(n, dtype=np.float32) / sr
    loud = (0.9 * np.sin(2 * np.pi * 220.0 * t)).astype(np.float32)
    quiet = (0.02 * np.sin(2 * np.pi * 220.0 * t)).astype(np.float32)

    stem_audio = {"quiet": quiet, "loud": loud}  # 插入顺序：quiet 先
    specs = [
        {"id": "a", "label": "响", "hue": 10.0, "stem": "loud", "notes": []},
        {"id": "b", "label": "轻", "hue": 20.0, "stem": "quiet", "notes": []},
    ]

    lanes = lanes_from_specs(stem_audio, sr, specs)
    by_id = {lane["id"]: lane for lane in lanes}

    expected_loud = rms_envelope(loud, sr)
    expected_quiet = rms_envelope(quiet, sr)

    # 判据不是"非零"，是逐点数值与它自己源信号算出来的包络一致
    np.testing.assert_array_equal(by_id["a"]["envelope_raw"], expected_loud)
    np.testing.assert_array_equal(by_id["b"]["envelope_raw"], expected_quiet)

    # 双重交叉验证：响的的确比轻的响，防止上面 expected_* 本身算错方向
    assert float(by_id["a"]["envelope_raw"].max()) > float(by_id["b"]["envelope_raw"].max())


def test_passthrough_output_shape_matches_build_lanes(sr):
    """两条路径的产物要能被 build_timeline 无差别消费。"""
    stems = {k: _tone(sr) for k in ("vocals", "drums", "bass", "other")}
    a = set(build_lanes(stems, sr)[0])
    b = set(lanes_from_specs({"arp": _tone(sr)}, sr, [
        {"id": "arp", "label": "泠泠", "hue": 165.0, "stem": "arp", "notes": []}
    ])[0])
    assert a == b


def test_spec_pointing_at_a_missing_stem_says_which(sr):
    import pytest

    with pytest.raises(KeyError, match="ghost"):
        lanes_from_specs({"arp": _tone(sr)}, sr, [
            {"id": "x", "label": "轨", "hue": 1.0, "stem": "ghost", "notes": []}
        ])


# ---- 跨语言：轨道名的真相源在渲染层，Python 这份只是兜底 ------------------


def _renderer_label_table() -> dict[str, str]:
    """从 `renderer/src/ui/voices.js` 里抠出 `LABELS` 那张表。

    Python 读不到 JS，只能正则。**抠空了必须炸**，不能返回空 dict 让下面
    的 `<=` 恒真——一个可能不存在的扫描目标等于一个默认通过的分支
    （CONSTRAINTS 第七轮"守卫只扫版本库里必然存在的东西"）。
    """
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent
           / "renderer" / "src" / "ui" / "voices.js").read_text(encoding="utf-8")
    block = re.search(r"export const LABELS = \{(.*?)\n\};", src, re.S)
    assert block, "voices.js 里找不到 LABELS 那张表了，这条守卫的正则该修了"
    table = dict(re.findall(r"(\w+):\s*\{\s*zh:\s*\"([^\"]+)\"", block.group(1)))
    assert len(table) >= 6, f"只抠出 {len(table)} 条，正则没跟上 voices.js 的写法"
    return table


def test_every_lane_id_python_can_emit_has_a_renderer_label():
    """**声部名的真相源是渲染层那张表，不是 Python 这边。**

    `voices.js` 与 `layers/laneLabels.js` 都是 `LABELS[l.id]?.zh ?? l.label`
    ——已知 id 一律用渲染层那份，timeline 里带的 `label` 只在查不到时兜底。
    所以两份表的**字面值不必相同**，实测也确实不同：真歌那六条
    Python 写的是「底鼓／军鼓／踩镲／低音／中层／气层」，画面上出的是
    「撼岳／裂帛／碎玉／渊鸣／流岚／缥缈」。**拿字符串相等去钉这两张表，
    等于给真歌那一路写一条现在就是假的规矩。**

    真正的不变量是行为层面的：**Python 能产出的每一个 lane id，渲染层都
    得认识**。查不到的那条会掉进兜底，画面上出现一个与其余各条不同风格
    的名字，而且没有任何东西会报警——评审 2026-08-14 在
    `boot-harness-nine.html` 上抓到过一次（九行面板只有五段环外小字）。
    这一条同时管住真歌的六条与合成曲的八条，两条路径同一把尺子。
    """
    from murripple.cli import LANE_LABELS

    known = set(_renderer_label_table())
    emittable = {spec["id"] for spec in LANE_SPECS} | set(LANE_LABELS)
    assert emittable <= known, (
        f"这些 lane id 渲染层不认识，画面与导出的 MP4 上会掉进兜底："
        f"{sorted(emittable - known)}"
    )
