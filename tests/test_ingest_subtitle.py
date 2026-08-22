"""硬字幕 OCR：亮集合的新增 → 带时间戳的行。"""

import pytest

from murripple.ingest.subtitle import MIN_FRAMES, merge_bright


def texts(lines):
    return [line["text"] for line in lines]


def scroll(*rows):
    """把"每帧的已唱集合"写成一串列表，省得每条测试都手糊。"""
    return list(rows)


def test_a_line_entering_the_sung_set_becomes_one_line():
    frames = [["甲"]] * 6 + [["甲", "乙"]] * 6
    lines = merge_bright(frames, fps=2)
    assert texts(lines) == ["甲", "乙"]
    assert lines[1]["t0"] == pytest.approx(3.0)


def test_a_line_that_stays_sung_does_not_retrigger():
    """一行进了已唱集合会待十几秒。每帧都记一次的话会有几百行重复。"""
    assert len(merge_bright([["甲"]] * 40, fps=2)) == 1


def test_a_line_visible_only_one_frame_at_the_bottom_is_still_captured():
    """**真实素材上漏掉整整一行的那个 bug。**

    先前的做法是"取最下面那条亮行"。真实素材里有一整行只在一帧里当过
    最下面的亮行（t=27.5），随即被闪帧过滤当噪声丢掉。按"谁刚进入已唱
    集合"判就没这问题——它在集合里待了十几帧。
    """
    frames = (
        [["A", "B", "C"]] * 8       # C 是当时最下面的
        + [["A", "B", "C", "D"]]    # D 只当了一帧最下面的
        + [["B", "C", "D", "E"]] * 8
    )
    assert "D" in texts(merge_bright(frames, fps=2))


def test_a_one_frame_ocr_dropout_does_not_duplicate_a_line():
    """OCR 偶尔漏认一帧。只跟上一帧比的话，那一行会被记成"又来了一次"。"""
    frames = [["甲"]] * 5 + [[]] + [["甲"]] * 5
    assert len(merge_bright(frames, fps=2)) == 1


def test_ocr_jitter_does_not_duplicate_a_line():
    """同一行多认／少认一个字，是一行不是两行。"""
    frames = [["他们把这一句念完才算数吗"]] * 5 + [["他们把这一句念完才算数"]] * 5
    assert len(merge_bright(frames, fps=2)) == 1


def test_a_one_frame_blip_is_dropped():
    """只闪一帧的多半是抖动，不是真出现过一行。"""
    frames = [["甲"]] * 6 + [["甲", "雜訊"]] + [["甲"]] * 6
    assert texts(merge_bright(frames, fps=2)) == ["甲"]


def test_min_frames_is_the_persistence_threshold():
    assert MIN_FRAMES >= 2
    base = [["甲"]] * 6
    assert texts(merge_bright(base + [["甲", "乙"]] * (MIN_FRAMES - 1) + base,
                              fps=2)) == ["甲"]
    assert texts(merge_bright(base + [["甲", "乙"]] * MIN_FRAMES + base,
                              fps=2)) == ["甲", "乙"]


def test_t1_is_the_next_lines_t0():
    """一行进了已唱集合会待到滚出画面，那是十几秒后的事。

    拿"离开集合"当结束，每一行都会跟后面好几行重叠。
    """
    frames = [["甲"]] * 6 + [["甲", "乙"]] * 6 + [["甲", "乙", "丙"]] * 6
    lines = merge_bright(frames, fps=2)
    assert lines[0]["t1"] == pytest.approx(lines[1]["t0"])
    assert lines[1]["t1"] == pytest.approx(lines[2]["t0"])


def test_no_line_overlaps_the_next():
    frames = [["甲"]] * 6 + [["甲", "乙"]] * 6 + [["甲", "乙", "丙"]] * 6
    lines = merge_bright(frames, fps=2)
    for a, b in zip(lines, lines[1:]):
        assert a["t1"] <= b["t0"] + 1e-9


def test_lines_come_out_in_time_order():
    frames = [["甲"]] * 4 + [["甲", "乙"]] * 4 + [["甲", "乙", "丙"]] * 4
    lines = merge_bright(frames, fps=2)
    assert texts(lines) == ["甲", "乙", "丙"]
    assert [l["t0"] for l in lines] == sorted(l["t0"] for l in lines)


def test_two_lines_appearing_in_the_same_frame_keep_screen_order():
    """采样间隔里唱过两句时，按画面上下顺序记，不能颠倒。"""
    frames = [["甲"]] * 4 + [["甲", "乙", "丙"]] * 4
    assert texts(merge_bright(frames, fps=2)) == ["甲", "乙", "丙"]


def test_fps_scales_the_timestamps():
    frames = [["甲"]] * 6 + [["甲", "乙"]] * 6
    assert merge_bright(frames, fps=4)[1]["t0"] == pytest.approx(1.5)


def test_a_repeated_lyric_line_later_in_the_song_is_kept_separate():
    """副歌重复的那句要出现两次——去重会把它并成一行、时间戳横跨整首歌。"""
    frames = [["副歌"]] * 6 + [["别的"]] * 6 + [["副歌"]] * 6
    lines = merge_bright(frames, fps=2)
    assert texts(lines) == ["副歌", "别的", "副歌"]
    assert lines[2]["t0"] > lines[0]["t1"]


def test_blank_frames_give_nothing():
    assert merge_bright([[]] * 30, fps=2) == []


def test_empty_input_gives_nothing():
    assert merge_bright([], fps=2) == []


def test_text_is_normalized():
    frames = [["  甲 乙  "]] * 6
    assert merge_bright(frames, fps=2)[0]["text"] == "甲乙"


def test_bad_fps_is_rejected():
    with pytest.raises(ValueError, match="fps"):
        merge_bright([["甲"]] * 4, fps=0)


# --- 画面分区与"哪一行正在唱" -------------------------------------------
#
# 这两处是真跑真实素材时翻车的地方，所以用假 OCR 造出同样的局面来钉住。

import numpy as np

from murripple.ingest.subtitle import (
    BRIGHT_THRESHOLD,
    MIN_DISTINCT_TEXTS,
    IngestError,
    Layout,
    TextBox,
    classify_bands,
    bright_lines,
    norm_text,
)

H = 1000


def box(text, y, score=0.99, x0=100, x1=700):
    return TextBox(text=text, x0=x0, y0=y, x1=x1, y1=y + 30, score=score)


def lyric_frames(n=16):
    """n 帧，每帧歌词带上一句不同的话，外加一个不变的曲名。"""
    return [[box("曲名", 180), box(f"第{i}句", 600)] for i in range(n)]


def test_changing_band_is_the_lyric_band():
    layout = classify_bands(lyric_frames(), H)
    assert layout.band[0] < 0.60 < layout.band[1]
    assert layout.band[0] > 0.20, "曲名那条不该被算进歌词带"


def test_static_text_is_reported_not_treated_as_lyrics():
    layout = classify_bands(lyric_frames(), H)
    assert [t for _, t in layout.static] == ["曲名"]
    assert any(abs(c - 0.195) < 0.02 for c, _ in layout.static)


def test_watermark_read_inconsistently_is_still_static():
    """**实测踩过的坑。**

    OCR 把同一个水印一会儿读成 MADEWITHSUNO、一会儿读成 MADEWITH SUNO。
    按原样比对的话，两种写法就足以让它冒充"会变的文字"——于是水印既混进
    了歌词带，又躲过了静态文字的排除，最后整首歌识别出来的每一行都是
    「MADEWITHSUNO」，一句歌词都没有。
    """
    frames = [
        [box(f"第{i}句", 600),
         box("MADEWITHSUNO" if i % 2 else "MADEWITH SUNO", 745)]
        for i in range(16)
    ]
    layout = classify_bands(frames, H)
    assert any(norm_text(t) == "MADEWITHSUNO" for _, t in layout.static), "水印没被认成静态"
    assert layout.band[1] < 0.745, "水印被算进了歌词带"


def test_a_band_with_only_a_couple_of_variants_is_not_lyrics():
    """两三种写法不算"在变"。歌词带一首歌里要换几十句。"""
    frames = [
        [box(f"第{i}句", 600), box(f"抖动{i % (MIN_DISTINCT_TEXTS - 1)}", 745)]
        for i in range(16)
    ]
    assert classify_bands(frames, H).band[1] < 0.745


def test_no_changing_text_gives_actionable_error():
    frames = [[box("曲名", 180)] for _ in range(16)]
    with pytest.raises(IngestError, match="lyrics.txt"):
        classify_bands(frames, H)


def test_norm_text_folds_ocr_word_splitting():
    assert norm_text("MADEWITH SUNO") == norm_text("MADEWITHSUNO")
    assert norm_text("  甲 乙  ") == "甲乙"


def frame_with_rows(rows):
    """造一张图：rows 是 (y, 亮度) 列表，每行画 30 px 高的一条。"""
    img = np.zeros((900, 800, 3), dtype=np.uint8)
    for y, value in rows:
        img[y:y + 30, 100:700] = value
    return img


def test_bright_lines_are_the_sung_ones_top_to_bottom():
    img = frame_with_rows([(100, 255), (200, 255), (300, 240), (400, 180)])
    boxes = [box("已唱一", 100), box("已唱二", 200),
             box("刚唱到", 300), box("还没唱", 400)]
    assert bright_lines(img, boxes) == ["已唱一", "已唱二", "刚唱到"]


def test_dim_lines_are_never_bright():
    img = frame_with_rows([(400, 180)])
    assert bright_lines(img, [box("还没唱", 400)]) == []


def test_excluded_text_is_dropped_even_when_bright():
    """水印落在歌词带里，会以"新来的一行"的身份白记一行歌词。"""
    img = frame_with_rows([(300, 255), (500, 255)])
    boxes = [box("正在唱", 300), box("MADEWITHSUNO", 500)]
    assert bright_lines(img, boxes, exclude=frozenset({"MADEWITHSUNO"})) == ["正在唱"]


def test_exclusion_compares_normalized_text():
    img = frame_with_rows([(300, 255), (500, 255)])
    boxes = [box("正在唱", 300), box("MADEWITH SUNO", 500)]
    assert bright_lines(img, boxes, exclude=frozenset({"MADEWITHSUNO"})) == ["正在唱"]


def test_threshold_sits_between_the_two_measured_populations():
    """实测：已唱行 p95 是 237–255，未唱行是 176–207。"""
    assert 207 < BRIGHT_THRESHOLD < 237


def test_a_few_bright_pixels_do_not_make_a_line_current():
    """未唱行的**峰值**能到 225（抗锯齿的亮边），p95 才 207。

    用峰值判定的话，这一行会被当成"正在唱"，整首歌的时间戳提前一句。
    实测 f45 那一帧就是这个样子：峰值 225／p95 207。
    """
    img = np.zeros((900, 800, 3), dtype=np.uint8)
    img[400:430, 100:700] = 180          # 主体是暗的
    img[400:430, 100:706:100] = 255      # 零星几个亮像素（约占 1%）
    assert bright_lines(img, [box("还没唱", 400)]) == []


# --- 标点抖动与同帧多行 ---------------------------------------------------

from murripple.ingest.subtitle import compare_key


def test_punctuation_jitter_does_not_split_a_short_line():
    """**实测踩过的坑。**

    真实素材里一行「X——」在相邻帧里被 OCR 读成 X／X-／X—／X一 四种。
    破折号只有一个字符，在三字短句里一变就把相似度拉到 0.67，于是同一行
    被记成了三行歌词。（下面这一行取自自造语料，形状与真那一行相同。）
    """
    frames = (
        [["退潮"]] * 4 + [["退潮-"]] * 4 + [["退潮—"]] * 4 + [["退潮一"]] * 4
    )
    assert len(merge_bright(frames, fps=2)) == 1


def test_compare_key_drops_punctuation_but_output_keeps_it():
    assert compare_key("退潮——") == compare_key("退潮-") == "退潮"
    assert merge_bright([["记下来就够了。"]] * 6, fps=2)[0]["text"] == "记下来就够了。"


def test_two_genuinely_different_short_lines_stay_separate():
    """剥标点不能剥到把不同的句子也并掉。"""
    frames = [["退潮"]] * 6 + [["面板"]] * 6
    assert len(merge_bright(frames, fps=2)) == 2


def test_lines_appearing_in_the_same_frame_get_nonzero_durations():
    """同帧冒出的几行时长全是 0 的话，下游会当成空行整段丢掉。"""
    frames = [["甲"]] * 4 + [["甲", "乙", "丙"]] * 4 + [["甲", "乙", "丙", "丁"]] * 4
    lines = merge_bright(frames, fps=2)
    for line in lines:
        assert line["t1"] > line["t0"], f"{line['text']} 时长为 0"


def test_same_frame_lines_stay_inside_their_sampling_interval():
    """摊开是插值不是测量：只知道这几句都在这半秒里，不能占到下一行为止。"""
    frames = [["甲", "乙"]] * 4 + [["甲", "乙", "丙"]] * 20
    lines = merge_bright(frames, fps=2)
    assert lines[0]["t0"] == pytest.approx(0.0)
    assert lines[1]["t0"] == pytest.approx(0.25), "第二句应当落在同一个采样间隔内"


# --- 产物 -----------------------------------------------------------------

import json

from murripple.ingest.subtitle import (
    TIMING_FILENAME,
    IngestError,
    load_timing,
    write_lyrics,
    write_timing,
)

SAMPLE = [
    {"t0": 0.0, "t1": 2.5, "text": "第一句"},
    {"t0": 2.5, "t1": 5.0, "text": "第二句"},
]


def test_lyrics_txt_is_plain_text_one_line_each(tmp_path):
    p = write_lyrics(SAMPLE, tmp_path / "lyrics.txt")
    assert p.read_text(encoding="utf-8").splitlines() == ["第一句", "第二句"]


def test_timing_is_a_sidecar_not_an_overrides_patch(tmp_path):
    """**实测踩过的坑。**

    最初写进 overrides.json 的 lyrics.lines，那是按下标打进「对齐之后」的
    列表的；而对齐会把没对上的行丢掉——这首歌 32 行进去、30 行出来，下标
    当场整体错位，build 直接报越界。演唱时刻不是对齐结果的补丁，它就是
    对齐结果，该在对齐之前顶掉 WhisperX。
    """
    write_timing(SAMPLE, tmp_path)
    assert (tmp_path / TIMING_FILENAME).exists()
    assert not (tmp_path / "overrides.json").exists()


def test_timing_round_trips(tmp_path):
    write_lyrics(SAMPLE, tmp_path / "lyrics.txt")
    write_timing(SAMPLE, tmp_path)
    assert [(l["t0"], l["t1"], l["text"]) for l in load_timing(tmp_path)] == [
        (0.0, 2.5, "第一句"), (2.5, 5.0, "第二句")
    ]


def test_text_comes_from_lyrics_txt_not_the_timing_file(tmp_path):
    """人过一眼时改的是 lyrics.txt（这首歌就把「臂越」改回了「僭越」）。

    拿时间戳文件里那份 OCR 原文去盖，等于把校对成果整个作废。
    """
    write_timing(SAMPLE, tmp_path)
    (tmp_path / "lyrics.txt").write_text("改过的一句\n第二句\n", encoding="utf-8")
    assert [l["text"] for l in load_timing(tmp_path)] == ["改过的一句", "第二句"]


def test_line_count_mismatch_is_an_error_not_a_silent_misalignment(tmp_path):
    """校对时拆了或并了行，下标就整体错位。宁可报错退回常规对齐。"""
    write_timing(SAMPLE, tmp_path)
    (tmp_path / "lyrics.txt").write_text("只剩一句\n", encoding="utf-8")
    with pytest.raises(IngestError, match="对不上"):
        load_timing(tmp_path)


def test_missing_timing_file_is_not_an_error(tmp_path):
    (tmp_path / "lyrics.txt").write_text("一句\n", encoding="utf-8")
    assert load_timing(tmp_path) is None


def test_blank_lines_in_lyrics_do_not_shift_the_pairing(tmp_path):
    """人校对时常留空行。空行不算歌词，不能把后面的时间戳整体挪一格。"""
    write_timing(SAMPLE, tmp_path)
    (tmp_path / "lyrics.txt").write_text("第一句\n\n第二句\n", encoding="utf-8")
    assert [l["text"] for l in load_timing(tmp_path)] == ["第一句", "第二句"]


def test_loaded_lines_have_the_shape_the_timeline_expects(tmp_path):
    """timeline 里每句歌词都有 words 字段，缺了 schema 过不去。"""
    write_lyrics(SAMPLE, tmp_path / "lyrics.txt")
    write_timing(SAMPLE, tmp_path)
    assert all(set(l) == {"t0", "t1", "text", "words"} for l in load_timing(tmp_path))


def test_a_line_does_not_linger_through_an_instrumental_break():
    """不封顶的话每行都延续到下一行开始，间奏里画面上一直挂着上一句。

    上限 8 秒来自第一首歌的 WhisperX 结果——那量的是真实演唱时长，48 行里
    最长的一行也才 7.42 秒。
    """
    from murripple.ingest.subtitle import MAX_LINE_SEC

    frames = [["甲"]] * 80 + [["甲", "乙"]] * 6      # 甲 之后空了 40 秒
    line = merge_bright(frames, fps=2)[0]
    assert line["t1"] - line["t0"] == pytest.approx(MAX_LINE_SEC)


def test_max_line_sec_is_a_ratchet():
    """把 8.0 钉住——**这是棘轮，不是 8.0 正确的证据**。

    这个上限只有一个样本：第一首歌 48 行，中位 3.54 秒、p90 5.01 秒、最长
    7.42 秒（见 murripple/ingest/subtitle.py 该常量上方的注释）。一首歌说明
    不了它对所有歌都合适。

    这条测试不量任何东西，也不声称量过。它唯一的作用是让这个数改不动：谁
    想调它，必须连这里一起改，于是必须在提交里写下理由。没有它，8.0 可以
    被悄悄调成 6 或 12 而没人察觉。

    真要给它证据，得拿多首歌的 lyrics.timing.json（那正是 WhisperX 量出来
    的真实演唱时长）把分布重算一遍，再按新的最长值重定这个数，并把样本数
    写进注释。那件事还没有人做。
    """
    from murripple.ingest.subtitle import MAX_LINE_SEC

    assert MAX_LINE_SEC == 8.0, (
        "MAX_LINE_SEC 被改动了。这不一定是错的，但它必须是有意的："
        "请在提交说明里写清依据（重算了哪几首歌的演唱时长分布），"
        "并同步更新 subtitle.py 里那段注释记的样本数。"
    )


def test_a_normal_line_is_not_truncated():
    frames = [["甲"]] * 6 + [["甲", "乙"]] * 6
    line = merge_bright(frames, fps=2)[0]
    assert line["t1"] == pytest.approx(3.0), "正常长度的行不该被截"


def test_section_markers_are_stripped_from_lyrics(tmp_path):
    """Suno 的歌词单每段开头挂一个 [Verse 1]，那不是唱的内容。

    不剥的话画面上第一句是「[Verse1]一个人也可以是复数」。
    """
    lines = [{"t0": 0.0, "t1": 1.0, "text": "[Verse 1]一个人也可以是复数"}]
    out = write_lyrics(lines, tmp_path / "lyrics.txt")
    assert out.read_text(encoding="utf-8").strip() == "一个人也可以是复数"


def test_parentheses_are_not_stripped():
    """圆括号在真歌词里是和声与语气词，不能跟方括号一起剥。"""
    from murripple.ingest.subtitle import strip_section_marker

    assert strip_section_marker("（Spoken，不带情绪）") == "（Spoken，不带情绪）"


def test_a_line_that_is_only_a_marker_is_kept(tmp_path):
    """删成空串会让这一行凭空消失，而 lyrics.txt 与时间戳是按行数配对的。"""
    lines = [{"t0": 0.0, "t1": 1.0, "text": "[Chorus]"},
             {"t0": 1.0, "t1": 2.0, "text": "第二句"}]
    out = write_lyrics(lines, tmp_path / "lyrics.txt")
    assert out.read_text(encoding="utf-8").splitlines() == ["[Chorus]", "第二句"]
