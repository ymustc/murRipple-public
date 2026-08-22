import importlib.abc
import importlib.util
import sys
import types

from pathlib import Path

import pytest

from murripple.align import AlignmentUnavailable, align_lyrics, parse_lyrics


def _install_fake_whisperx(monkeypatch, segments):
    """装一个假的 whisperx 模块，返回预置的词级对齐结果。"""
    fake = types.ModuleType("whisperx")
    fake.load_audio = lambda path: [0.0]
    fake.load_model = lambda *a, **k: types.SimpleNamespace(
        transcribe=lambda audio, **kw: {"segments": segments, "language": "zh"},
        # 替身**照着真 pipeline 长**：`align_lyrics` 现在先问
        # `align.decide_language()`，那一处会在挑出来的窗口上调
        # `model.detect_language()`。少给这一样，替身就在替真实现兜一件它
        # 其实要做的事。（守卫见 tests/test_language.py）
        detect_language=lambda audio: "zh",
    )
    fake.load_align_model = lambda **k: (object(), {})
    fake.align = lambda segs, m, meta, audio, device, **k: {"segments": segs}
    monkeypatch.setitem(sys.modules, "whisperx", fake)


def _seg(start, end, words):
    """words 为 [(字, 起, 止)]。"""
    return {
        "start": start,
        "end": end,
        "text": "".join(w[0] for w in words),
        "words": [{"word": w[0], "start": w[1], "end": w[2]} for w in words],
    }


def test_parse_lyrics_strips_blanks():
    text = "  第一句  \n\n第二句\n\n\n  \n第三句\n"
    assert parse_lyrics(text) == ["第一句", "第二句", "第三句"]


def test_exact_segmentation_aligns(monkeypatch, tmp_path):
    _install_fake_whisperx(
        monkeypatch,
        [
            _seg(1.0, 2.0, [("春", 1.0, 1.5), ("风", 1.5, 2.0)]),
            _seg(3.0, 4.0, [("秋", 3.0, 3.5), ("月", 3.5, 4.0)]),
        ],
    )
    lines, unmatched = align_lyrics(tmp_path / "vocals.wav", "春风\n秋月")

    assert unmatched == []
    assert [(l["text"], l["t0"], l["t1"]) for l in lines] == [
        ("春风", 1.0, 2.0),
        ("秋月", 3.0, 4.0),
    ]


def test_whisper_splits_one_lyric_line_into_two_segments(monkeypatch, tmp_path):
    """一行歌词被 Whisper 切成两段——整句匹配会失败，字符级比对不会。"""
    _install_fake_whisperx(
        monkeypatch,
        [
            _seg(1.0, 2.0, [("锈", 1.0, 1.5), ("色", 1.5, 2.0)]),
            _seg(2.2, 3.0, [("电", 2.2, 2.6), ("台", 2.6, 3.0)]),
        ],
    )
    lines, unmatched = align_lyrics(tmp_path / "vocals.wav", "锈色电台")

    assert unmatched == []
    assert len(lines) == 1
    assert lines[0]["text"] == "锈色电台"
    assert lines[0]["t0"] == 1.0
    assert lines[0]["t1"] == 3.0


def test_whisper_merges_two_lyric_lines_into_one_segment(monkeypatch, tmp_path):
    """两行歌词被 Whisper 并成一段——两行都要各自拿到时间。"""
    _install_fake_whisperx(
        monkeypatch,
        [
            _seg(
                1.0,
                4.0,
                [("锈", 1.0, 1.5), ("色", 1.5, 2.0),
                 ("电", 3.0, 3.5), ("台", 3.5, 4.0)],
            )
        ],
    )
    lines, unmatched = align_lyrics(tmp_path / "vocals.wav", "锈色\n电台")

    assert unmatched == []
    assert [(l["text"], l["t0"], l["t1"]) for l in lines] == [
        ("锈色", 1.0, 2.0),
        ("电台", 3.0, 4.0),
    ]


def test_full_width_space_is_ignored_in_matching(monkeypatch, tmp_path):
    """歌词里的全角空格 U+3000 不参与匹配。"""
    _install_fake_whisperx(
        monkeypatch,
        [
            _seg(
                1.0,
                4.0,
                [("锈", 1.0, 1.5), ("色", 1.5, 2.0),
                 ("电", 3.0, 3.5), ("台", 3.5, 4.0)],
            )
        ],
    )
    lines, unmatched = align_lyrics(tmp_path / "vocals.wav", "锈色　电台")

    assert unmatched == []
    assert lines[0]["text"] == "锈色　电台"
    assert lines[0]["t0"] == 1.0
    assert lines[0]["t1"] == 4.0


def test_misheard_character_still_matches_line(monkeypatch, tmp_path):
    """Whisper 把「进」听成同音的「近」——整行仍应对上。"""
    _install_fake_whisperx(
        monkeypatch,
        [
            _seg(
                1.0,
                4.0,
                [("潮", 1.0, 2.0), ("气", 2.0, 3.0), ("爬", 3.0, 3.5),
                 ("近", 3.5, 4.0)],
            )
        ],
    )
    lines, unmatched = align_lyrics(tmp_path / "vocals.wav", "潮气爬进")

    assert unmatched == []
    assert lines[0]["t0"] == 1.0
    assert lines[0]["t1"] >= 3.5


def test_repeated_chorus_with_mismatched_segmentation(monkeypatch, tmp_path):
    """副歌整段重复，且分句边界与歌词换行全部对不齐。

    真实情况里这两件事总是一起出现，把它们拆开测等于测了个不会发生的
    场景。这里第一次出现被并成一段，第二次出现在错误的位置被切开——
    三个 segment 的文本分别是「锈色电台」「锈色电」「台」，没有任何一个
    等于某一行歌词，所以任何基于整句相等的匹配都会四行全部落空。
    """
    _install_fake_whisperx(
        monkeypatch,
        [
            # 第一次出现：两行被并成一段
            _seg(1.0, 4.0, [("锈", 1.0, 1.5), ("色", 1.5, 2.0),
                            ("电", 3.0, 3.5), ("台", 3.5, 4.0)]),
            # 第二次出现：在错误的位置切开
            _seg(5.0, 6.2, [("锈", 5.0, 5.5), ("色", 5.5, 6.0),
                            ("电", 6.0, 6.2)]),
            _seg(6.2, 8.0, [("台", 7.5, 8.0)]),
        ],
    )
    lines, unmatched = align_lyrics(
        tmp_path / "vocals.wav", "锈色\n电台\n锈色\n电台"
    )

    assert unmatched == []
    assert [l["text"] for l in lines] == ["锈色", "电台", "锈色", "电台"]
    assert [l["t0"] for l in lines] == [1.0, 3.0, 5.0, 6.0]
    for prev, cur in zip(lines, lines[1:]):
        assert cur["t0"] >= prev["t1"]


def test_line_with_no_audio_match_is_reported(monkeypatch, tmp_path):
    _install_fake_whisperx(
        monkeypatch,
        [_seg(1.0, 2.0, [("春", 1.0, 1.5), ("风", 1.5, 2.0)])],
    )
    lines, unmatched = align_lyrics(tmp_path / "vocals.wav", "春风\n毫不相干")

    assert [l["text"] for l in lines] == ["春风"]
    assert unmatched == ["毫不相干"]


def test_times_are_monotonic(monkeypatch, tmp_path):
    _install_fake_whisperx(
        monkeypatch,
        [
            _seg(1.0, 3.0, [("甲", 1.0, 3.0)]),
            _seg(2.0, 4.0, [("乙", 2.0, 4.0)]),  # 与上一行重叠
        ],
    )
    lines, _ = align_lyrics(tmp_path / "vocals.wav", "甲\n乙")

    for prev, cur in zip(lines, lines[1:]):
        assert cur["t0"] >= prev["t1"]
        assert cur["t1"] > cur["t0"]


def test_word_level_emits_one_entry_per_lyric_character(monkeypatch, tmp_path):
    _install_fake_whisperx(
        monkeypatch,
        [_seg(1.0, 3.0, [("晨", 1.0, 2.0), ("露", 2.0, 3.0)])],
    )
    lines, _ = align_lyrics(tmp_path / "vocals.wav", "晨露", word_level=True)

    words = lines[0]["words"]
    assert [w["c"] for w in words] == ["晨", "露"]
    assert words[0]["t0"] == 1.0
    assert words[-1]["t1"] == 3.0
    for prev, cur in zip(words, words[1:]):
        assert cur["t0"] >= prev["t0"]


def test_sentence_level_leaves_words_none(monkeypatch, tmp_path):
    _install_fake_whisperx(
        monkeypatch,
        [_seg(1.0, 3.0, [("晨", 1.0, 2.0), ("露", 2.0, 3.0)])],
    )
    lines, _ = align_lyrics(tmp_path / "vocals.wav", "晨露")
    assert lines[0]["words"] is None


def test_empty_lyrics_returns_empty(monkeypatch, tmp_path):
    _install_fake_whisperx(monkeypatch, [])
    assert align_lyrics(tmp_path / "vocals.wav", "\n  \n") == ([], [])


def test_missing_whisperx_raises_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "whisperx", None)
    with pytest.raises(AlignmentUnavailable, match="--extra align"):
        align_lyrics(tmp_path / "vocals.wav", "第一句")


def test_broken_install_also_degrades(monkeypatch, tmp_path):
    """装了但 ABI 坏掉时（torch/torchaudio 不配对）同样要降级，不能崩。

    真实故障：OSError: dlopen(..._torchaudio.abi3.so): Symbol not found:
    _aoti_torch_abi_version。只捕 ImportError 会让整条管线崩溃，而 spec
    第 15 节要求 WhisperX 不可用时降级为无歌词并继续。

    没有用 monkeypatch 替换 builtins.__import__ 来伪造这个 OSError——那样
    会拦截测试期间*所有*的 import（包括 pytest/fixture 自身可能触发的
    import），影响面太大、太脆弱。改用一个只认 "whisperx" 这一个模块名
    的 sys.meta_path finder/loader：只有 `import whisperx` 会被它接管，
    其余 import 完全走原路径，互不干扰。
    """

    class _BrokenLoader(importlib.abc.Loader):
        def create_module(self, spec):
            return None  # 交给默认机制创建空模块对象

        def exec_module(self, module):
            raise OSError(
                "dlopen(.../torchaudio/lib/_torchaudio.abi3.so): "
                "Symbol not found: _aoti_torch_abi_version"
            )

    class _BrokenFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name == "whisperx":
                return importlib.util.spec_from_loader(name, _BrokenLoader())
            return None

    monkeypatch.delitem(sys.modules, "whisperx", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_BrokenFinder(), *sys.meta_path])

    with pytest.raises(AlignmentUnavailable, match="版本"):
        align_lyrics(tmp_path / "vocals.wav", "第一句")


def test_partial_match_extrapolates_to_full_line():
    """只匹配上句中一部分字时，必须按字在句中的位置反推整句时长。

    真实故障：一句六个字的歌词只匹配上开头两个字，窗口只有 0.50 秒
    （每字 0.084s，全曲中位数是 0.374s），字早早就消失而声音还在。
    （这里的六字句取自自造语料，真句子是他的私产，见
    `tests/test_no_private_lyrics.py`。）
    原实现取"所有匹配词的首尾"，匹配残缺时窗口就残缺。
    """
    import sys
    import types

    fake = types.ModuleType("whisperx")
    fake.load_audio = lambda path: [0.0]
    fake.load_model = lambda *a, **k: types.SimpleNamespace(
        transcribe=lambda audio, **kw: {"segments": SEGS, "language": "zh"},
        # 替身**照着真 pipeline 长**：`align_lyrics` 现在先问
        # `align.decide_language()`，那一处会在挑出来的窗口上调
        # `model.detect_language()`。少给这一样，替身就在替真实现兜一件它
        # 其实要做的事。（守卫见 tests/test_language.py）
        detect_language=lambda audio: "zh",
    )
    fake.load_align_model = lambda **k: (object(), {})
    fake.align = lambda segs, m, meta, audio, device, **k: {"segments": segs}

    # 六字句，只有前两个字被听对；后四个字 Whisper 听成了别的
    SEGS = [
        {
            "start": 10.0,
            "end": 11.0,
            "text": "谁先",
            "words": [
                {"word": "谁", "start": 10.0, "end": 10.5},
                {"word": "先", "start": 10.5, "end": 11.0},
            ],
        }
    ]
    sys.modules["whisperx"] = fake
    try:
        lines, unmatched = align_lyrics(Path("/tmp/nope.wav"), "谁先眨眼就输")
    finally:
        sys.modules.pop("whisperx", None)

    assert unmatched == []
    line = lines[0]
    # 每字 0.5 秒 × 6 字 = 3.0 秒，而不是只有匹配上那两字的 1.0 秒
    dur = line["t1"] - line["t0"]
    assert dur > 2.4, f"应按字数外推到约 3 秒，实得 {dur:.2f} 秒"
    assert abs(line["t0"] - 10.0) < 0.01, "首字匹配上了，起点不该动"


def test_full_match_window_unchanged():
    """整句都匹配上时，窗口就是匹配词的首尾，不做任何外推。"""
    import sys
    import types

    SEGS = [
        {
            "start": 10.0,
            "end": 12.0,
            "text": "春风",
            "words": [
                {"word": "春", "start": 10.0, "end": 11.0},
                {"word": "风", "start": 11.0, "end": 12.0},
            ],
        }
    ]
    fake = types.ModuleType("whisperx")
    fake.load_audio = lambda path: [0.0]
    fake.load_model = lambda *a, **k: types.SimpleNamespace(
        transcribe=lambda audio, **kw: {"segments": SEGS, "language": "zh"},
        # 替身**照着真 pipeline 长**：`align_lyrics` 现在先问
        # `align.decide_language()`，那一处会在挑出来的窗口上调
        # `model.detect_language()`。少给这一样，替身就在替真实现兜一件它
        # 其实要做的事。（守卫见 tests/test_language.py）
        detect_language=lambda audio: "zh",
    )
    fake.load_align_model = lambda **k: (object(), {})
    fake.align = lambda segs, m, meta, audio, device, **k: {"segments": segs}

    sys.modules["whisperx"] = fake
    try:
        lines, _ = align_lyrics(Path("/tmp/nope.wav"), "春风")
    finally:
        sys.modules.pop("whisperx", None)

    assert abs(lines[0]["t0"] - 10.0) < 1e-6
    assert abs(lines[0]["t1"] - 12.0) < 1e-6


def test_overlap_is_split_at_midpoint_not_swallowed():
    """外推让相邻句重叠时，不能让前一句把后一句整个吞掉。

    真实回归：加入外推后，01 里相邻的两句句读句时长变成 0.00 秒
    ——原实现解决重叠的办法是把后一句起点推到前一句
    终点，前一句被外推撑长后就把后一句吃光了。
    """
    from murripple.align import _enforce_monotonic

    lines = [
        {"t0": 10.0, "t1": 14.0, "text": "甲", "words": None},
        {"t0": 12.0, "t1": 13.0, "text": "乙", "words": None},  # 被前一句覆盖
        {"t0": 16.0, "t1": 18.0, "text": "丙", "words": None},
    ]
    _enforce_monotonic(lines)

    for line in lines:
        dur = line["t1"] - line["t0"]
        assert dur > 0.3, f"「{line['text']}」被压成 {dur:.2f} 秒"
    for prev, cur in zip(lines, lines[1:]):
        assert cur["t0"] >= prev["t1"] - 1e-9, "仍须单调不重叠"


def test_no_overlap_is_left_alone():
    """本来就不重叠的句子不该被动过。"""
    from murripple.align import _enforce_monotonic

    lines = [
        {"t0": 10.0, "t1": 12.0, "text": "甲", "words": None},
        {"t0": 13.0, "t1": 15.0, "text": "乙", "words": None},
    ]
    _enforce_monotonic(lines)
    assert lines[0]["t1"] == 12.0
    assert lines[1]["t0"] == 13.0


def test_lyric_order_is_authoritative_never_reordered():
    """外推可能把某句起点推得比下一句还晚，但绝不能因此重排歌词。

    真实回归：01 的第 4 句被排到了第 5 句后面。
    LCS 保证匹配锚点单调递增，歌词顺序本身是权威
    的，按 t0 重排只会在外推出偏差时把顺序搞乱。
    """
    import sys
    import types

    # 两句：第一句只匹配上最后一个字（锚点靠后），第二句正常
    SEGS = [
        {
            "start": 10.0, "end": 14.0, "text": "四乙丙",
            "words": [
                {"word": "四", "start": 12.8, "end": 13.0},
                {"word": "乙", "start": 13.2, "end": 13.6},
                {"word": "丙", "start": 13.6, "end": 14.0},
            ],
        }
    ]
    fake = types.ModuleType("whisperx")
    fake.load_audio = lambda path: [0.0]
    fake.load_model = lambda *a, **k: types.SimpleNamespace(
        transcribe=lambda audio, **kw: {"segments": SEGS, "language": "zh"},
        # 替身**照着真 pipeline 长**：`align_lyrics` 现在先问
        # `align.decide_language()`，那一处会在挑出来的窗口上调
        # `model.detect_language()`。少给这一样，替身就在替真实现兜一件它
        # 其实要做的事。（守卫见 tests/test_language.py）
        detect_language=lambda audio: "zh",
    )
    fake.load_align_model = lambda **k: (object(), {})
    fake.align = lambda segs, m, meta, audio, device, **k: {"segments": segs}

    sys.modules["whisperx"] = fake
    try:
        lines, _ = align_lyrics(Path("/tmp/nope.wav"), "一二三四\n乙丙")
    finally:
        sys.modules.pop("whisperx", None)

    assert [l["text"] for l in lines] == ["一二三四", "乙丙"], "歌词顺序不得被重排"
    for prev, cur in zip(lines, lines[1:]):
        assert cur["t0"] >= prev["t1"] - 1e-9


def test_no_line_ever_gets_negative_duration():
    """兜底不能算出 t1 < t0。

    真实回归：兜底那行 min(t0 + MIN_LINE_SEC, 下一句 t0) 在下一句起点
    早于本句起点时会给出负时长（实测每字 -0.339 秒）。连环重叠时确实
    会出现这种局面。
    """
    from murripple.align import _enforce_monotonic

    # 刻意构造连环重叠，且后面的句子起点比前面的还早
    lines = [
        {"t0": 10.0, "t1": 20.0, "text": "甲", "words": None},
        {"t0": 11.0, "t1": 11.5, "text": "乙", "words": None},
        {"t0": 10.5, "t1": 12.0, "text": "丙", "words": None},
        {"t0": 30.0, "t1": 32.0, "text": "丁", "words": None},
    ]
    _enforce_monotonic(lines)

    for line in lines:
        assert line["t1"] >= line["t0"], (
            f"「{line['text']}」时长为负：{line['t1'] - line['t0']:.3f}s"
        )
    for prev, cur in zip(lines, lines[1:]):
        assert cur["t0"] >= prev["t1"] - 1e-9, "仍须单调"


def test_traditional_chinese_matches_simplified_lyrics():
    """Whisper 会随段落输出繁体，必须归一化后再比对。

    实测转录里有一整段是繁体，而歌词是简体。字符级比对里「舊」与「旧」
    是两个不同的字，那几句必然全部落空——48 句里有 15 句对不上，这是
    其中一批。（下面的例句取自自造语料 `丁-舊城殘卷`，真句子是他的私产。）
    """
    # `opencc` 在可选的 `align` extra 里。缺了它转换不发生，这条必然红——
    # 而原来的报错只说「舊 != 旧」，一个字都没提缺的是什么。
    #
    # **不跳过。** 本仓已经立过这个判断：`tests/test_synthetic_lyric_corpus.py`
    # 明写「『装不上所以没验』跟『验过了没问题』不许长得一样」，并且它自己在缺
    # extra 时也照样红。2026-08-21 我先改成了 `importorskip`，被那条守卫当场
    # 顶回来——它是对的。所以这里只做一件事：**把红说清楚**，不把红变没。
    try:
        import opencc  # noqa: F401
    except ModuleNotFoundError:
        pytest.fail(
            "繁简转换要 opencc，它在可选的 align extra 里，此刻没装——"
            "所以下面的比对必然落空。这条红是真的少验了，不是代码坏了。"
            "补：uv sync --group dev --extra align"
        )

    from murripple.align import _normalize

    assert _normalize("舊城殘卷") == _normalize("旧城残卷")
    assert _normalize("誰替鐵門") == _normalize("谁替铁门")
    assert _normalize("說謊的人　學會了咳嗽") == _normalize("说谎的人 学会了咳嗽")


def test_simplified_input_is_unchanged():
    """本来就是简体的不该被动过。"""
    from murripple.align import _normalize

    assert _normalize("锈色电台　夜里还醒") == "锈色电台夜里还醒"
