import numpy as np

import pytest
from jsonschema import ValidationError

from murripple.envelope import decode_u8
from murripple.lanes import build_lanes
from murripple.schema import SCHEMA_VERSION, validate_timeline
from murripple.timeline import build_timeline


def _stems(y):
    return {
        "vocals": y,
        "drums": y,
        "bass": y,
        "other": y,
    }


def _square_am(n, sr, amp=0.3):
    """方波调幅：给 detect_beats 一个真实起振，不会退化出 bpm=0.0。

    本文件里多条测试各自内联过这段（见 test_global_peak_is_shared_across_lanes
    等处历史注释），这里把它抽成共享 helper，本文件全部用到同一条方波调幅
    表达式的地方（含 Step 1 新增的三条测试）都改调它——纯正弦对
    detect_beats 是退化输入，会被 schema 的 exclusiveMinimum 拒收。
    `amp` 可调：多数调用点用默认的 0.3，也有个别测试要 0.8 或未缩放的
    1.0（自己再乘响度系数），保留参数而不是写死，避免为了复用而扭曲
    各测试本来的信号设计。
    """
    t = np.arange(n, dtype=np.float32) / sr
    tremolo = (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 2 * t))).astype(np.float32)
    return (amp * np.sin(2 * np.pi * 60 * t) * tremolo).astype(np.float32)


def test_build_timeline_passes_schema(click_track_120bpm, sr):
    doc = build_timeline(
        title="demo",
        stem_audio=_stems(click_track_120bpm),
        sr=sr,
        lyrics=[{"t0": 1.0, "t1": 2.0, "text": "第一句", "words": None}],
        bitrate_label="aac-64k",
    )
    validate_timeline(doc)


def test_meta_reflects_inputs(click_track_120bpm, sr):
    doc = build_timeline(
        title="知漪测试",
        stem_audio=_stems(click_track_120bpm),
        sr=sr,
        lyrics=[],
        bitrate_label="aac-64k",
    )
    assert doc["meta"]["title"] == "知漪测试"
    assert doc["meta"]["schemaVersion"] == SCHEMA_VERSION
    assert abs(doc["meta"]["duration"] - 10.0) < 0.05
    assert abs(doc["meta"]["bpm"] - 120.0) < 2.0


def test_six_lanes_with_encoded_envelopes(click_track_120bpm, sr):
    doc = build_timeline(
        title="demo", stem_audio=_stems(click_track_120bpm), sr=sr,
        lyrics=[], bitrate_label="aac-64k",
    )
    assert len(doc["lanes"]) == 6
    expected_len = round(10.0 * 60)
    for lane in doc["lanes"]:
        env = decode_u8(lane["envelope"])
        assert env.dtype == np.uint8
        assert abs(len(env) - expected_len) <= 2


def test_ring_envelope_present(click_track_120bpm, sr):
    doc = build_timeline(
        title="demo", stem_audio=_stems(click_track_120bpm), sr=sr,
        lyrics=[], bitrate_label="aac-64k",
    )
    assert len(decode_u8(doc["ring"]["envelope"])) > 0
    assert len(decode_u8(doc["ring"]["presence"])) > 0


def test_presence_is_binary(click_track_120bpm, sr):
    doc = build_timeline(
        title="demo", stem_audio=_stems(click_track_120bpm), sr=sr,
        lyrics=[], bitrate_label="aac-64k",
    )
    presence = decode_u8(doc["ring"]["presence"])
    assert set(np.unique(presence)).issubset({0, 255})


def test_silent_vocals_yield_zero_presence(click_track_120bpm, sr):
    stems = _stems(click_track_120bpm)
    stems["vocals"] = np.zeros_like(click_track_120bpm)
    doc = build_timeline(
        title="demo", stem_audio=stems, sr=sr, lyrics=[],
        bitrate_label="aac-64k",
    )
    assert decode_u8(doc["ring"]["presence"]).max() == 0


def test_lanes_envelope_raw_stays_unquantized(click_track_120bpm, sr):
    """守住 Task 5 评审提出的边界：quantize/encode_u8 只应发生在
    timeline.py 里，build_lanes 的 envelope_raw 必须原样是未量化的
    float32——不是 build_timeline 的输出，避免误改 tests/test_lanes.py。
    """
    lanes = build_lanes(_stems(click_track_120bpm), sr)
    for lane in lanes:
        env = lane["envelope_raw"]
        assert env.dtype == np.float32
        # 量化后的值会被钳到 [0, 255] 的整数；点击轨的原始 RMS 峰值
        # 远小于 1.0，一旦落进这个范围基本可以断定量化被误挪进了这里。
        assert env.max() < 1.5


def test_presence_marks_both_singing_and_silent(sr):
    """presence 必须真的出现 255。

    原断言只查 presence ⊆ {0,255}，而 {0} 也是子集——恒为 0 时照样通过。
    那意味着判定环全程不亮，是整个产品最显眼的失败模式。
    """
    n = sr * 2
    tone = 0.8 * np.sin(2 * np.pi * 220 * np.arange(n, dtype=np.float32) / sr)
    vocals = np.concatenate([np.zeros(n, dtype=np.float32), tone]).astype(np.float32)
    others = np.zeros(n * 2, dtype=np.float32)

    doc = build_timeline(
        title="demo",
        stem_audio={"vocals": vocals, "drums": others,
                    "bass": others, "other": others},
        sr=sr, lyrics=[], bitrate_label="aac-64k",
    )
    presence = decode_u8(doc["ring"]["presence"])
    assert presence.max() == 255, "人声段必须被标为在唱"
    assert presence.min() == 0, "静音段必须被标为未唱"


def test_global_peak_is_shared_across_lanes(sr):
    """安静的轨必须比响亮的轨暗。

    spec 要求 global_peak 跨全部轨道共享，以保留各轨之间的相对响度。
    若改成各轨自归一，两条轨都会顶到 255，本断言失败——这是这条约束
    唯一的守卫。

    与 brief 原文的偏离（见 task-8-report.md「修订 A 补丁」）：brief 给的
    版本用 2 秒纯 60Hz 正弦，会在本仓库现有、未改动的 analyze.py 上炸出
    两个与本测试意图无关的问题——(1) detect_beats 对无起振变化的纯音
    会退化出 bpm=0.0，被 schema 的 exclusiveMinimum 拒收；(2)
    detect_sections 里 chroma_cqt 的自动调音依赖 librosa.piptrack（默认
    fmin=150Hz），60Hz 纯音在这个搜索频段里完全没有能量，会抛
    "empty frequency set" UserWarning，在 -W error::UserWarning 下变成
    硬错误。两处都是 analyze.py 现有行为在这类合成信号上的边界情况，
    不是 timeline.py/cli.py 的缺陷，因此没有改 analyze.py，只调整了这
    条测试自己的合成信号：把 60Hz 正弦换成方波调幅（给 detect_beats
    喂真实起振），时长从 2s 延到 10s，并给本测试不关心的 vocals 轨垫一点
    极小的宽谱噪声（给 piptrack 的搜索频段内喂一点合法能量）。kick 与
    bass 两条轨的相对响度关系（0.9x vs 0.05x 同一路 wave）未变，断言
    的判定逻辑也未变。
    """
    n = sr * 10
    wave = _square_am(n, sr, amp=1.0)  # 60Hz：kick 与 bass 两条轨都收得到，响度系数交给下面两行
    loud = (0.9 * wave).astype(np.float32)
    quiet = (0.05 * wave).astype(np.float32)               # 比 loud 低约 25 dB
    silence = np.zeros(n, dtype=np.float32)
    rng = np.random.default_rng(0)
    noise_bed = (0.02 * rng.standard_normal(n)).astype(np.float32)

    doc = build_timeline(
        title="demo",
        stem_audio={"vocals": noise_bed, "drums": loud,
                    "bass": quiet, "other": silence},
        sr=sr, lyrics=[], bitrate_label="aac-64k",
    )
    lanes = {lane["id"]: decode_u8(lane["envelope"]).max() for lane in doc["lanes"]}
    assert lanes["kick"] > lanes["bass"] + 60, (
        f"响亮的鼓轨({lanes['kick']})未显著亮于安静的贝斯轨({lanes['bass']})，"
        f"global_peak 很可能没有跨轨共享"
    )


def test_pure_instrumental_ring_falls_back_to_mix_energy(sr):
    """spec 第 15 节：纯器乐、检测不到人声 → 环改由整体能量驱动，不中断。

    人声轨全程静音，presence 因此全曲为 0——这是"检测不到人声"的判定
    信号。此时 ring.envelope 若仍然只取 vocals 的包络（恒为 0），判定环
    会整曲沉睡，是最显眼的失败模式。回退后 ring.envelope 应改用 mix
    （四轨之和）的包络，鼓轨有能量就应该让环亮起来。

    信号设计沿用 test_global_peak_is_shared_across_lanes 的做法：纯 60Hz
    正弦对 detect_beats/detect_sections 是退化输入（无起振变化会让
    beat_track 退化出 bpm=0.0，被 schema 拒收；chroma_cqt 的自动调音
    依赖 piptrack，默认搜索频段 150Hz–4kHz 内没有能量会抛
    "empty frequency set" UserWarning）。所以用方波调幅给出真实起振，
    并在 other 轨（不是 vocals，以保持"人声全静音"的测试前提不被破坏）
    垫一点宽谱噪声，给 piptrack 的搜索频段喂点合法能量。
    """
    n = sr * 10
    drums = _square_am(n, sr, amp=0.8)
    silence = np.zeros(n, dtype=np.float32)
    rng = np.random.default_rng(0)
    noise_bed = (0.02 * rng.standard_normal(n)).astype(np.float32)

    doc = build_timeline(
        title="demo",
        stem_audio={"vocals": silence, "drums": drums, "bass": silence, "other": noise_bed},
        sr=sr, lyrics=[], bitrate_label="aac-64k",
    )
    ring_env = decode_u8(doc["ring"]["envelope"])
    ring_presence = decode_u8(doc["ring"]["presence"])
    assert ring_presence.max() == 0, "人声全静音，presence 应保持全 0（诚实反映没有人声）"
    assert ring_env.max() > 40, (
        f"presence 全 0（纯器乐回退）时 ring.envelope 应改由 mix 驱动，"
        f"不能整曲沉睡（实际 max={ring_env.max()}）"
    )


def test_vocals_present_ring_follows_vocals_not_mix(sr):
    """有人声时，ring.envelope 必须跟着人声的时间包络走，不能被写成
    "回退逻辑生效后就永远用 mix"。

    人声只在前半段唱、后半段不唱；鼓轨则全程等响、不随人声变化。若
    ring 正确跟随人声，后半段应显著暗于前半段；若被误写成恒用 mix，
    前后半段亮度会接近（因为鼓全程等响）。
    """
    n = sr * 4
    t = np.arange(n, dtype=np.float32) / sr
    vocal_gate = (t < 2.0).astype(np.float32)
    vocals = (0.3 * np.sin(2 * np.pi * 220 * t) * vocal_gate).astype(np.float32)
    drums = (0.9 * np.sin(2 * np.pi * 60 * t)).astype(np.float32)  # 全程响，且比人声响得多
    silence = np.zeros(n, dtype=np.float32)

    doc = build_timeline(
        title="demo",
        stem_audio={"vocals": vocals, "drums": drums, "bass": silence, "other": silence},
        sr=sr, lyrics=[], bitrate_label="aac-64k",
    )
    presence = decode_u8(doc["ring"]["presence"])
    assert presence.max() == 255, "前半段有人声，presence 不应全 0（否则本用例没测到目标路径）"

    ring_env = decode_u8(doc["ring"]["envelope"])
    half = len(ring_env) // 2
    first_half_mean = float(ring_env[:half].mean())
    second_half_mean = float(ring_env[half:].mean())
    assert first_half_mean > second_half_mean + 30, (
        f"ring.envelope 应跟随人声的时间包络（前响后静：{first_half_mean:.1f} vs "
        f"{second_half_mean:.1f}），而不是恒响的混音——回退逻辑可能被误写成了"
        f"「presence 有值时也用 mix」"
    )


def test_section_marks_override_detection(sr):
    """有真值就别再猜——与『硬字幕时间戳存在时整个跳过 WhisperX』同一路数。

    鼓轨用方波调幅而不是 brief 里原样的纯 60Hz 正弦：纯正弦对
    detect_beats 是退化输入（无起振变化，beat_track 退化出 bpm=0.0，
    被 schema 的 exclusiveMinimum 拒收），这条坑本文件里
    test_pure_instrumental_ring_falls_back_to_mix_energy 已经踩过一次、
    留了详细注释——这里沿用同一个修法，只换调幅波形，不改测试意图
    （段落名/时间戳/能量范围的断言原样保留）。
    """
    import numpy as np

    from murripple.timeline import build_timeline

    n = sr * 12
    stems = {k: np.zeros(n, dtype=np.float32) for k in ("vocals", "drums", "bass", "other")}
    stems["drums"] = _square_am(n, sr)

    marks = [{"t": 0.0, "name": "起"}, {"t": 6.0, "name": "承"}]
    doc = build_timeline(title="t", stem_audio=stems, sr=sr, lyrics=[],
                         bitrate_label="aac-64k", section_marks=marks)

    assert [s["name"] for s in doc["sections"]] == ["起", "承"]
    assert [s["t"] for s in doc["sections"]] == [0.0, 6.0]
    for section in doc["sections"]:
        assert 0.0 <= section["energy"] <= 1.0


def test_without_marks_detection_still_runs(sr):
    """不给真值时行为一行不变——这条守的是没把老路走坏。

    与上一条同样的理由改用方波调幅（避免 bpm=0.0 被 schema 拒收）；这条
    还会经过 detect_sections 的 chroma_cqt/piptrack，所以额外在 other 轨
    垫一点宽谱噪声，避免"empty frequency set"告警——同样沿用
    test_pure_instrumental_ring_falls_back_to_mix_energy 的做法。
    """
    import numpy as np

    from murripple.timeline import build_timeline

    n = sr * 12
    rng = np.random.default_rng(0)
    noise_bed = (0.02 * rng.standard_normal(n)).astype(np.float32)
    stems = {k: np.zeros(n, dtype=np.float32) for k in ("vocals", "drums", "bass", "other")}
    stems["drums"] = _square_am(n, sr)
    stems["other"] = noise_bed
    doc = build_timeline(title="t", stem_audio=stems, sr=sr, lyrics=[],
                         bitrate_label="aac-64k")
    assert all(s["name"] == "" for s in doc["sections"])


def test_stems_field_lists_the_actual_stems(sr):
    n = sr * 12
    stems = {k: np.zeros(n, dtype=np.float32)
             for k in ("vocals", "drums", "bass", "other")}
    stems["drums"] = _square_am(n, sr)
    doc = build_timeline(title="t", stem_audio=stems, sr=sr, lyrics=[],
                         bitrate_label="aac-64k")
    assert doc["stems"] == ["bass", "drums", "other", "vocals"]


def test_lane_specs_bypass_detection(sr):
    """给了轨道真值就直通——音符表逐条照抄，不从波形猜。"""
    n = sr * 12
    stems = {"vocals": np.zeros(n, dtype=np.float32), "arp": _square_am(n, sr)}
    notes = [{"t": 1.0, "v": 0.5, "pitch": 72}]
    doc = build_timeline(title="t", stem_audio=stems, sr=sr, lyrics=[],
                         bitrate_label="aac-64k",
                         lane_specs=[{"id": "arp", "label": "泠泠", "hue": 165.0,
                                      "stem": "arp", "notes": notes}])
    assert [l["id"] for l in doc["lanes"]] == ["arp"]
    assert doc["lanes"][0]["notes"] == notes
    assert doc["stems"] == ["arp", "vocals"]


def test_without_lane_specs_the_six_lanes_are_unchanged(sr):
    """真歌那一路一行不变——这条是本计划最重要的对照。

    注意射程：这条只断言六条 lane 的 id 顺序，不逐字段核对包络/音符/
    增益——那一路的完整回归是 Task 9 的活（有四首真歌的逐字段基线
    fixture 守着）。这条测试证明的是「不给 lane_specs 时走的还是
    build_lanes 那条老路、产出的仍是那六个 id」，不证明老路的算法本身
    没被动过；一个把六个 id 排对了但包络/音符/增益全算错的实现，能让
    这条测试照样绿。
    """
    n = sr * 12
    stems = {k: np.zeros(n, dtype=np.float32)
             for k in ("vocals", "drums", "bass", "other")}
    stems["drums"] = _square_am(n, sr)
    doc = build_timeline(title="t", stem_audio=stems, sr=sr, lyrics=[],
                         bitrate_label="aac-64k")
    assert [l["id"] for l in doc["lanes"]] == [
        "kick", "snare", "hat", "bass", "mid", "air"]


def test_empty_lane_specs_list_is_rejected_not_silently_ignored(sr):
    """`lane_specs=[]` 必须响亮地失败，不能悄悄落回六条 lane 的检测老路。

    `if lane_specs` 这种真值判断会把空列表和「没给」混为一谈——那样的话
    一首合成曲万一因为某种 bug 拿到一份空的轨道真值，会静默产出一份看
    起来正常、其实完全没用真值的六条 lane，不报任何错。这里用
    `is not None` 钉住相反的行为：空列表被原样交给 `lanes_from_specs`，
    产出空的 `lanes`，随后被 schema 的 `minItems: 1` 当场拒收。

    裸的 `pytest.raises(ValidationError)` 对任何 schema 违规都成立——
    今天确实是 `lanes` 的 `minItems` 触发的，但没有任何东西钉住这一点；
    日后夹具因为别的原因（比如退化的 bpm）挂掉，这条测试会继续绿，而
    它守着的 `is not None` 行为其实已经悄悄坏了。这里额外卡住报错定位
    在 `lanes` 这个字段上，且消息是"非空"这条具体违规，不是随便一个
    ValidationError。"""
    n = sr * 12
    stems = {k: np.zeros(n, dtype=np.float32)
             for k in ("vocals", "drums", "bass", "other")}
    stems["drums"] = _square_am(n, sr)
    with pytest.raises(ValidationError, match="non-empty") as exc_info:
        build_timeline(title="t", stem_audio=stems, sr=sr, lyrics=[],
                       bitrate_label="aac-64k", lane_specs=[])
    assert list(exc_info.value.absolute_path) == ["lanes"], (
        "报错必须定位到 lanes 字段——否则这条测试可能测到的是别的 schema 违规"
    )
