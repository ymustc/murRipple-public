"""ingest 与 run 两个子命令。"""

import json
import sys

import pytest

from murripple import cli


def song_with_in(tmp_path, *names):
    song = tmp_path / "01-某首歌"
    in_dir = song / "_in"
    in_dir.mkdir(parents=True)
    for n in names:
        (in_dir / n).write_bytes(b"x")
    return song


def song_ready(tmp_path, with_timeline=False):
    song = tmp_path / "02-另一首"
    song.mkdir(parents=True)
    (song / "source.wav").write_bytes(b"x")
    (song / "lyrics.txt").write_text("第一句\n", encoding="utf-8")
    if with_timeline:
        (song / "build").mkdir()
        (song / "build" / "timeline.json").write_text("{}", encoding="utf-8")
    return song


@pytest.fixture
def stub_ingest(monkeypatch):
    """把真正干活的三个函数换掉，只看编排。"""
    calls = []

    def prepare_audio(src, song_dir, force=False):
        out = song_dir / f"source{src.suffix.lower()}"
        out.write_bytes(b"audio")
        calls.append(("audio", src.name))
        return out

    def extract_subtitles(video, **kw):
        calls.append(("ocr", video.name))
        return [{"t0": 0.0, "t1": 1.0, "text": "第一句"}], None

    monkeypatch.setattr(cli, "prepare_audio", prepare_audio)
    monkeypatch.setattr(cli, "extract_subtitles", extract_subtitles)
    return calls


@pytest.fixture
def stub_run(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "build", lambda *a, **k: calls.append("build") or 0)
    monkeypatch.setattr(
        cli, "pack",
        lambda song_dir, *a, **k: (calls.append("pack") or _fake_out(song_dir)),
    )
    return calls


def _fake_out(song_dir):
    out = song_dir / "dist" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("<html>", encoding="utf-8")
    return out


def run_cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["murripple", *argv])
    return cli.main()


# --- ingest ---------------------------------------------------------------


def test_ingest_stops_before_build(monkeypatch, tmp_path, stub_ingest, stub_run):
    """ingest 不许直接往下跑——OCR 会错字，必须让人先过一眼歌词。"""
    song = song_with_in(tmp_path, "song.wav")
    assert run_cli(monkeypatch, "ingest", str(song)) == 0
    assert stub_run == [], "ingest 自作主张往下跑了"
    assert (song / "source.wav").exists()


def test_ingest_prints_its_decisions(capsys, monkeypatch, tmp_path, stub_ingest):
    """决策要讲出来。猜错时用户要能一眼看出来，而不是跑完一小时才发现。"""
    song = song_with_in(tmp_path, "录屏.mp4", "song.wav")
    run_cli(monkeypatch, "ingest", str(song))

    out = capsys.readouterr().out
    assert "song.wav" in out and "录屏.mp4" in out, "要列出看到了哪些素材"
    assert "音频" in out and "歌词" in out, "两条路线各自的来源都要说"


def test_ingest_takes_audio_from_wav_and_lyrics_from_video(
    monkeypatch, tmp_path, stub_ingest
):
    """各取所长：音频用 wav，时间戳只能从 mp4 来。"""
    song = song_with_in(tmp_path, "录屏.mp4", "song.wav")
    run_cli(monkeypatch, "ingest", str(song))
    assert ("audio", "song.wav") in stub_ingest
    assert ("ocr", "录屏.mp4") in stub_ingest


def test_ingest_writes_lyrics_and_timing(monkeypatch, tmp_path, stub_ingest):
    """OCR 拿到的时间戳要落盘，否则这一步最值钱的东西就丢了。"""
    from murripple.ingest.subtitle import TIMING_FILENAME

    song = song_with_in(tmp_path, "录屏.mp4")
    run_cli(monkeypatch, "ingest", str(song))
    assert (song / "lyrics.txt").read_text(encoding="utf-8").strip() == "第一句"
    doc = json.loads((song / TIMING_FILENAME).read_text(encoding="utf-8"))
    assert doc == [{"t0": 0.0, "t1": 1.0, "text": "第一句"}]


def test_ingest_copies_existing_lyrics_instead_of_ocr(
    monkeypatch, tmp_path, stub_ingest
):
    """有现成歌词就不 OCR，也不该写时间戳补丁——那份时间戳无从谈起。"""
    song = song_with_in(tmp_path, "录屏.mp4", "词.txt")
    (song / "_in" / "词.txt").write_text("现成的一句\n", encoding="utf-8")
    run_cli(monkeypatch, "ingest", str(song))
    assert (song / "lyrics.txt").read_text(encoding="utf-8") == "现成的一句\n"
    assert not any(c[0] == "ocr" for c in stub_ingest)
    assert not (song / "lyrics.timing.json").exists()


def test_ingest_does_not_touch_the_in_dir(monkeypatch, tmp_path, stub_ingest):
    """`_in/` 是用户仅有的原始素材，只读。"""
    song = song_with_in(tmp_path, "录屏.mp4", "song.wav")
    before = {p.name: p.read_bytes() for p in (song / "_in").iterdir()}
    run_cli(monkeypatch, "ingest", str(song))
    after = {p.name: p.read_bytes() for p in (song / "_in").iterdir()}
    assert before == after


def test_ingest_does_not_overwrite_existing_lyrics(
    monkeypatch, tmp_path, stub_ingest
):
    """已经人工校对过的歌词，重跑 ingest 不能一把冲掉。"""
    song = song_with_in(tmp_path, "录屏.mp4")
    (song / "lyrics.txt").write_text("我改过的\n", encoding="utf-8")
    run_cli(monkeypatch, "ingest", str(song))
    assert (song / "lyrics.txt").read_text(encoding="utf-8") == "我改过的\n"


def test_ingest_reports_a_bad_material_dir_without_traceback(
    capsys, monkeypatch, tmp_path
):
    song = tmp_path / "空的"
    (song / "_in").mkdir(parents=True)
    assert run_cli(monkeypatch, "ingest", str(song)) == 1
    assert "Traceback" not in capsys.readouterr().err


# --- run ------------------------------------------------------------------


def test_run_skips_steps_whose_output_exists(monkeypatch, tmp_path, stub_run):
    """全链一小时。不可断点续跑的话，改一个参数就要从头来。"""
    song = song_ready(tmp_path, with_timeline=True)
    assert run_cli(monkeypatch, "run", str(song)) == 0
    assert "build" not in stub_run, "timeline.json 已存在还是重跑了分析"
    assert "pack" in stub_run, "打包该照跑"


def test_run_builds_when_there_is_no_timeline(monkeypatch, tmp_path, stub_run):
    song = song_ready(tmp_path)
    run_cli(monkeypatch, "run", str(song))
    assert "build" in stub_run


def test_force_reruns_everything(monkeypatch, tmp_path, stub_run):
    song = song_ready(tmp_path, with_timeline=True)
    run_cli(monkeypatch, "run", str(song), "--force")
    assert "build" in stub_run, "--force 下必须重跑"


def test_run_stops_when_build_fails(monkeypatch, tmp_path, stub_run):
    """分析失败还照打包的话，打出来的是上一次的旧产物，看不出问题。"""
    monkeypatch.setattr(cli, "build", lambda *a, **k: 1)
    song = song_ready(tmp_path)
    assert run_cli(monkeypatch, "run", str(song)) == 1
    assert "pack" not in stub_run


def test_run_without_lyrics_says_what_is_missing(capsys, monkeypatch, tmp_path):
    song = tmp_path / "缺歌词"
    song.mkdir()
    (song / "source.wav").write_bytes(b"x")
    assert run_cli(monkeypatch, "run", str(song)) == 1
    err = capsys.readouterr().err
    assert "lyrics.txt" in err
