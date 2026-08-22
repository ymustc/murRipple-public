"""扫描 _in/ 并判定路线。"""

import pytest

from murripple.ingest.scan import IngestError, scan


def make(dir_, *names):
    dir_.mkdir(parents=True, exist_ok=True)
    for n in names:
        (dir_ / n).write_bytes(b"x")
    return dir_


def test_prefers_standalone_audio_over_video_track(tmp_path):
    """同时有 mp4 和 wav 时，音频取 wav。

    mp4 里的音轨经过一次有损压缩，录屏还常带系统混音；单独给的 wav 是
    用户手上质量最好的那一份。这是于淼明确提出的「各取所长」。
    """
    make(tmp_path, "录屏.mp4", "song.wav")
    plan = scan(tmp_path)
    assert plan.audio_from.name == "song.wav"
    assert any("wav" in n and "mp4" in n for n in plan.notes), "要说明为什么不用 mp4 的音轨"


def test_still_uses_video_for_subtitles_even_when_audio_comes_elsewhere(tmp_path):
    """音频用 wav，字幕仍然要从 mp4 来——时间戳只有它有。"""
    make(tmp_path, "录屏.mp4", "song.wav")
    plan = scan(tmp_path)
    assert plan.lyrics_from == ("ocr", tmp_path / "录屏.mp4")


def test_video_only_extracts_audio_from_it(tmp_path):
    make(tmp_path, "录屏.mp4")
    plan = scan(tmp_path)
    assert plan.audio_from == tmp_path / "录屏.mp4"
    assert plan.lyrics_from == ("ocr", tmp_path / "录屏.mp4")


def test_existing_lyrics_beats_ocr(tmp_path):
    """有现成歌词就不 OCR——OCR 会错字，现成的是权威。"""
    make(tmp_path, "录屏.mp4", "歌词.txt")
    plan = scan(tmp_path)
    assert plan.lyrics_from == tmp_path / "歌词.txt"
    assert any("OCR" in n for n in plan.notes), "要说明为什么跳过 OCR"


def test_audio_only_is_fine(tmp_path):
    make(tmp_path, "song.mp3")
    plan = scan(tmp_path)
    assert plan.audio_from.name == "song.mp3"
    assert plan.lyrics_from is None
    assert any("没有歌词" in n for n in plan.notes), "缺歌词要说出来，不能默默继续"


def test_lossless_beats_lossy(tmp_path):
    """同时给了 wav 和 mp3，取无损那份。

    两个都是「单独给的音源」，优先级不能靠文件名或遍历顺序决定。
    """
    make(tmp_path, "song.mp3", "song.wav")
    assert scan(tmp_path).audio_from.name == "song.wav"


def test_empty_dir_gives_actionable_error(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    with pytest.raises(IngestError, match="_in"):
        scan(tmp_path)


def test_missing_dir_gives_actionable_error(tmp_path):
    with pytest.raises(IngestError, match="_in"):
        scan(tmp_path / "不存在")


def test_no_audio_anywhere_is_an_error(tmp_path):
    """只放了歌词没放音源——说清缺的是什么，别等到 build 才炸。"""
    make(tmp_path, "歌词.txt")
    with pytest.raises(IngestError, match="音频|音源"):
        scan(tmp_path)


def test_multiple_videos_is_an_error_not_a_guess(tmp_path):
    """两个 mp4 时不许猜。猜错要跑一小时才发现。"""
    make(tmp_path, "a.mp4", "b.mp4")
    with pytest.raises(IngestError, match="a.mp4.*b.mp4|b.mp4.*a.mp4"):
        scan(tmp_path)


def test_multiple_lyrics_is_an_error_not_a_guess(tmp_path):
    make(tmp_path, "song.wav", "a.txt", "b.txt")
    with pytest.raises(IngestError, match="a.txt.*b.txt|b.txt.*a.txt"):
        scan(tmp_path)


def test_multiple_audio_of_same_tier_is_an_error(tmp_path):
    """两份同等质量的音源，同样不许猜。

    wav + mp3 有明确的优劣可判（见上），wav + flac 没有。
    """
    make(tmp_path, "a.wav", "b.flac")
    with pytest.raises(IngestError, match="a.wav.*b.flac|b.flac.*a.wav"):
        scan(tmp_path)


@pytest.mark.parametrize(
    "name,kind",
    [("歌.MP4", "video"), ("Song.WAV", "audio"), ("词.TXT", "lyrics")],
)
def test_extension_matching_is_case_insensitive(name, kind, tmp_path):
    """用户从各处拿来的文件大小写不一，别在这上面栽跟头。"""
    make(tmp_path, name, "垫底.mp3" if kind != "audio" else "垫底.txt")
    plan = scan(tmp_path)
    if kind == "video":
        assert plan.lyrics_from == ("ocr", tmp_path / name)
    elif kind == "audio":
        assert plan.audio_from == tmp_path / name
    else:
        assert plan.lyrics_from == tmp_path / name


def test_unknown_files_are_ignored_but_reported(tmp_path):
    """封面图、说明文档之类不该让扫描失败，但要让用户知道我们没用它。"""
    make(tmp_path, "song.wav", "cover.jpg", "readme.pdf")
    plan = scan(tmp_path)
    assert plan.audio_from.name == "song.wav"
    assert any("cover.jpg" in n for n in plan.notes)


def test_hidden_files_are_ignored(tmp_path):
    """.DS_Store 会让「只有一个 txt」变成「两个」，macOS 上必然踩到。"""
    make(tmp_path, "song.wav", ".DS_Store", "._song.wav")
    plan = scan(tmp_path)
    assert plan.audio_from.name == "song.wav"
    assert all(".DS_Store" not in n for n in plan.notes)


def test_subdirectories_are_ignored(tmp_path):
    (tmp_path / "子目录").mkdir(parents=True)
    make(tmp_path, "song.wav")
    assert scan(tmp_path).audio_from.name == "song.wav"


def test_notes_are_human_sentences(tmp_path):
    """notes 是打印给人看的，不是 repr。"""
    make(tmp_path, "录屏.mp4", "song.wav")
    for n in scan(tmp_path).notes:
        assert isinstance(n, str) and n.strip() == n and n
        assert "PosixPath" not in n and "\n" not in n
