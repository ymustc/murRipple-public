"""CLI 的控制流与降级路径（spec 第 15 节）。

只挡掉 separate/encode 这两个重外部依赖，其余全部走真实代码——
测的是 CLI 自己的决策，不是 mock 的行为。
"""

import json
import sys

import numpy as np
import pytest
import soundfile as sf

from murripple import cli
from murripple.align import AlignmentUnavailable
from murripple.separate import SeparationError


@pytest.fixture
def song_dir(tmp_path, sr):
    d = tmp_path / "demo"
    d.mkdir()
    t = np.arange(sr * 10, dtype=np.float32) / sr
    sf.write(d / "source.wav", (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), sr)
    return d


def _stub_heavy_deps(monkeypatch, song_dir, sr, duration=10.0):
    """挡掉 Demucs 与 ffmpeg，保留 CLI 自身的控制流。

    **注意：这个夹具造的是扁平分轨**（`build/stems/{四条}.wav`），而 M5 之后
    `build()` 见到四条扁平分轨就跳过分离（`murripple/stems.py` 的定案 1）。
    所以用了这个夹具的 5 条测试走的都是"跳过分离"那一支，下面那句
    `monkeypatch.setattr(cli, "separate", ...)` 在它们里面已经是**死代码**
    ——留着是因为夹具本身不该假设调用方走哪一支，删掉反而脆。

    这几条的题目（没有 lyrics.txt 照样 build、WhisperX 缺席降级、音频太短
    中止、超长告警、对不上的行要打出来）全都发生在读分轨**之后**，与
    `stem_paths` 是分离出来的还是现成的无关，所以改道不影响它们要验的东西。
    真正以 separate 为题的 `test_separation_error_returns_exit_code_one`
    没有用这个夹具，仍然走分离那一支。

    Demucs 那一支现在由 `tests/test_compose_cli.py` 里的 `stub_separation`
    接手——它按 Demucs **真实的嵌套布局** `stems/<model>/<源名>/*.wav` 落盘，
    覆盖"普通歌照旧分离""第二次 build 必须再分离一次""坏的 sections.json
    要在分离之前拦下"三条。要改这里之前先去看那三条。

    与 brief 原文的偏离（见 task-8-report.md「修订 A 补丁」）：brief 给的
    版本用纯 220Hz 正弦作四条轨。凡是会走到 build_timeline 的用例都会在
    现有、未改动的 analyze.py 里炸——detect_beats 对无起振变化的纯音会
    退化出 bpm=0.0，被 schema 的 exclusiveMinimum 拒收。加一点方波调幅
    （模拟 120 BPM 的四分音符起振）就够了，不改变任何一条 CLI 测试本身
    要验证的控制流/降级路径。
    """
    n = int(sr * duration)
    t = np.arange(n, dtype=np.float32) / sr
    tremolo = (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 2 * t))).astype(np.float32)
    y = (0.3 * np.sin(2 * np.pi * 220 * t) * tremolo).astype(np.float32)

    stem_dir = song_dir / "build" / "stems"
    stem_dir.mkdir(parents=True, exist_ok=True)
    stems = {}
    for name in ("vocals", "drums", "bass", "other"):
        path = stem_dir / f"{name}.wav"
        sf.write(path, y, sr)
        stems[name] = path

    monkeypatch.setattr(cli, "separate", lambda *a, **k: stems)
    monkeypatch.setattr(cli, "encode_stem", lambda wav, out, bitrate: out)
    return stems


def test_missing_lyrics_file_still_builds(monkeypatch, song_dir, sr, capsys):
    """**没有 lyrics.txt 照样做得出来——但要用户先说出口。**

    2026-08-15 改：原来这条断的是"没有 lyrics.txt 时 `build` 直接降级做完"。
    那一半被判为**沉默降级**——它不问，也不说清用户是不是真想这样，而绝大多数
    情况下"没有 lyrics.txt"是忘了，往下走要烧掉 Demucs 那几分钟到一小时。

    它守的那件事（**一首没有歌词的歌是合法产物**）**没有被放弃**，
    只是改由用户显式说 `--no-lyrics` 来表达——这条测试现在断的就是那条路，
    连同"降级说明照旧打出来"一起。默认拒绝那一半由
    `tests/test_lyrics_gate.py` 接手。

    与它成对的另一条（`test_compose_cli.py::test_run_still_demands_lyrics_*`，
    守「忘了放歌词的人不能白烧一小时」）**一个字节没改，原样通过**。
    """
    _stub_heavy_deps(monkeypatch, song_dir, sr)

    assert cli.build(song_dir, word_level=False, bitrate="64k", no_lyrics=True) == 0
    assert (song_dir / "build" / "timeline.json").exists()
    assert "lyrics.txt" in capsys.readouterr().out


def test_whisperx_unavailable_degrades_without_aborting(monkeypatch, song_dir, sr, capsys):
    """默认环境就没装 WhisperX，这条分支必然走到，绝不能中断整条管线。"""
    _stub_heavy_deps(monkeypatch, song_dir, sr)
    (song_dir / "lyrics.txt").write_text("第一句\n", encoding="utf-8")

    def unavailable(*a, **k):
        raise AlignmentUnavailable("WhisperX 未安装。运行 `uv sync --extra align`")

    monkeypatch.setattr(cli, "align_lyrics", unavailable)

    assert cli.build(song_dir, word_level=False, bitrate="64k") == 0
    doc = json.loads((song_dir / "build" / "timeline.json").read_text("utf-8"))
    assert doc["lyrics"] == []


def test_unmatched_lines_are_printed_for_manual_fixup(monkeypatch, song_dir, sr, capsys):
    """对不上的行必须原样打给用户，不能静默丢弃。"""
    _stub_heavy_deps(monkeypatch, song_dir, sr)
    (song_dir / "lyrics.txt").write_text("对上的\n对不上的\n", encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "align_lyrics",
        lambda *a, **k: (
            [{"t0": 1.0, "t1": 2.0, "text": "对上的", "words": None}],
            ["对不上的"],
        ),
    )

    assert cli.build(song_dir, word_level=False, bitrate="64k") == 0
    assert "对不上的" in capsys.readouterr().out


def test_too_short_audio_aborts_before_writing(monkeypatch, song_dir, sr):
    _stub_heavy_deps(monkeypatch, song_dir, sr, duration=2.0)

    assert cli.build(song_dir, word_level=False, bitrate="64k") == 1
    assert not (song_dir / "build" / "timeline.json").exists()


def test_long_audio_warns_but_continues(monkeypatch, song_dir, sr, capsys):
    _stub_heavy_deps(monkeypatch, song_dir, sr)
    monkeypatch.setattr(cli, "LONG_DURATION_WARNING", 5.0)

    assert cli.build(song_dir, word_level=False, bitrate="64k", no_lyrics=True) == 0
    assert (song_dir / "build" / "timeline.json").exists()
    assert "警告" in capsys.readouterr().err


def test_separation_error_returns_exit_code_one(monkeypatch, song_dir, sr, capsys):
    def unavailable(*a, **k):
        raise SeparationError("Demucs 无法启动。请运行 `uv sync --group dev`")

    monkeypatch.setattr(cli, "separate", unavailable)

    assert cli.build(song_dir, word_level=False, bitrate="64k", no_lyrics=True) == 1
    assert "uv sync" in capsys.readouterr().err


def test_missing_source_audio_names_supported_suffixes(song_dir):
    (song_dir / "source.wav").unlink()

    with pytest.raises(SystemExit) as exc:
        cli.find_source(song_dir)
    assert ".mp3" in str(exc.value)


def _fake_pack_out(tmp_path):
    out = tmp_path / "index.html"
    out.write_bytes(b"x" * 1024)
    return out


def test_cli_pack_passes_title_through(monkeypatch, tmp_path, capsys):
    """--title 必须经 argparse 走到 pack。

    直接调 pack(..., title=...) 的测试测不到这一段：把 cli 里的实参删掉、
    甚至把整个 --title 选项删掉，那种测试照样全绿。
    """
    seen = {}

    def fake_pack(song_dir, renderer, title=None):
        seen["title"] = title
        return _fake_pack_out(tmp_path)

    monkeypatch.setattr(cli, "pack", fake_pack)
    monkeypatch.setattr(
        sys, "argv", ["murripple", "pack", "songs/demo", "--title", "锈色电台"]
    )
    assert cli.main() == 0
    assert seen["title"] == "锈色电台"


def test_cli_pack_title_is_optional(monkeypatch, tmp_path):
    """不给 --title 也要能跑。写成 required=True 会让既有命令行全部报错。"""
    seen = {}

    def fake_pack(song_dir, renderer, title=None):
        seen["title"] = title
        return _fake_pack_out(tmp_path)

    monkeypatch.setattr(cli, "pack", fake_pack)
    monkeypatch.setattr(sys, "argv", ["murripple", "pack", "songs/demo"])
    assert cli.main() == 0
    assert seen["title"] is None, "默认值必须是 None，pack 才能退回 meta.title"
