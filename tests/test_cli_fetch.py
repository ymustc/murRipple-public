"""`murripple ingest --url <链接>`：取回 → 原样交给既有的 `ingest`。

**这里一个字节都不走网络。** `cli.fetch_url` 被顶掉，验的是编排：
取回之后有没有真的往下跑、失败的话那句原因有没有真的到终端上。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from murripple import cli, fetch

URL = "https://example.invalid/watch?v=abc"


def _argv(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["murripple", *args])


@pytest.fixture
def stub_fetch(monkeypatch):
    """替身：真的往 `_in/` 里落一份素材，然后记一笔。

    **落真文件**是要害——既有的 `ingest` 接着就要 `scan(_in/)`，替身不落盘的话
    「取回之后真的往下跑了」这条根本走不到，测试会在一个假的成功上变绿。
    """
    calls = []

    def fake_fetch_url(url, song_dir, *, want_video=False, force=False, log=print):
        # **先记下进来时目录在不在，再动手建。** 顺序反了的话，替身自己就把
        # 目录建好了，`ingest_url` 里那句 mkdir 删掉照样全绿——替身替产品代码
        # 干了活（变异检验 W5 逮到的就是这个）。
        existed = Path(song_dir).is_dir()
        in_dir = Path(song_dir) / "_in"
        in_dir.mkdir(parents=True, exist_ok=True)
        (in_dir / "取回来的.m4a").write_bytes(b"audio")
        if want_video:
            (in_dir / "取回来的.mkv").write_bytes(b"video")
        calls.append({"url": url, "song_dir": Path(song_dir), "existed": existed,
                      "want_video": want_video, "force": force})
        log(f"{fetch.LOG_PREFIX} 取回成功（第 1 级）：取回来的.m4a")
        return "假的 FetchResult"

    monkeypatch.setattr(cli, "fetch_url", fake_fetch_url)
    return calls


@pytest.fixture
def stub_ingest_work(monkeypatch):
    """`ingest` 真正干活的两步换掉，只看编排走没走到。"""
    done = []

    def prepare_audio(src, song_dir, force=False):
        out = Path(song_dir) / f"source{src.suffix.lower()}"
        out.write_bytes(b"audio")
        done.append(("audio", src.name))
        return out

    def extract_subtitles(video, **kw):
        done.append(("ocr", video.name))
        return [{"t0": 0.0, "t1": 1.0, "text": "第一句"}], None

    monkeypatch.setattr(cli, "prepare_audio", prepare_audio)
    monkeypatch.setattr(cli, "extract_subtitles", extract_subtitles)
    return done


# --------------------------------------------------------------------------
# 一路走到底
# --------------------------------------------------------------------------


def test_给一条链接就一路走到_ingest_跑完(
    monkeypatch, tmp_path, stub_fetch, stub_ingest_work, capsys
):
    """判据：中途不需要人手动搬文件。"""
    song = tmp_path / "songs" / "09-来自链接"
    _argv(monkeypatch, "ingest", str(song), "--url", URL)

    assert cli.main() == 0

    assert [c["url"] for c in stub_fetch] == [URL]
    # 取回之后**真的**接着跑了 ingest：素材被整理成了 source.*，OCR 也走到了。
    assert ("audio", "取回来的.m4a") in stub_ingest_work
    assert ("ocr", "取回来的.mkv") in stub_ingest_work
    assert (song / "source.m4a").exists()
    assert (song / "lyrics.txt").exists()


def test_目录不存在也不用先建(monkeypatch, tmp_path, stub_fetch, stub_ingest_work):
    """人手上只有一条链接，不该先被要求自己去 mkdir 一层。

    断的是**取回被调用的那一刻目录已经在了**，不是"跑完之后目录在"——
    后者是替身自己建的，产品代码那句 mkdir 删掉照样绿（变异检验 W5）。
    """
    song = tmp_path / "songs" / "还没建过的目录"
    assert not song.exists()
    _argv(monkeypatch, "ingest", str(song), "--url", URL)

    assert cli.main() == 0
    assert stub_fetch[0]["existed"] is True, (
        "`fetch_url` 被调用时歌曲目录还不存在——建目录这件事没人做"
    )


def test_默认连视频一起取(monkeypatch, tmp_path, stub_fetch, stub_ingest_work):
    """没有视频就没有硬字幕可 OCR，`scan` 当场说"请自己写一份 lyrics.txt"，
    这条路就断在那儿了。"""
    _argv(monkeypatch, "ingest", str(tmp_path / "a"), "--url", URL)
    cli.main()
    assert stub_fetch[0]["want_video"] is True


def test_no_video_只取音频(monkeypatch, tmp_path, stub_fetch, stub_ingest_work):
    _argv(monkeypatch, "ingest", str(tmp_path / "a"), "--url", URL, "--no-video")
    cli.main()
    assert stub_fetch[0]["want_video"] is False


def test_force_一路带到取回那一层(monkeypatch, tmp_path, stub_fetch, stub_ingest_work):
    """`_in/` 里已有素材时 `fetch` 会拒绝——`--force` 传不下去的话，
    用户加了 `--force` 还是过不去，而错误消息让他加的正是 `--force`。"""
    _argv(monkeypatch, "ingest", str(tmp_path / "a"), "--url", URL, "--force")
    cli.main()
    assert stub_fetch[0]["force"] is True


# --------------------------------------------------------------------------
# ★ 三个直接抛、不走日志层的异常，必须在终端上被打出来
# --------------------------------------------------------------------------

#: 三种失败各带一句只属于自己的话。**互相排斥地断**——只印一句"取回失败"
#: 的实现会让三条同时红。
_FAILURES = {
    "unusable": (
        lambda song: fetch.UnusableAudioError(
            "取回来的音频是 x.mp4，改个扩展名即可",
            path=song / "_in" / "x.mp4",
            suffix=".mp4",
        ),
        "改个扩展名即可",
    ),
    "ambiguous": (
        lambda song: fetch.AmbiguousResultError(
            "这条链接一趟取回了 3 份，多半是它指向一个播放列表",
            paths=[song / "a.m4a"],
        ),
        "指向一个播放列表",
    ),
    "occupied": (
        lambda song: fetch.FetchError(
            f"{song}/_in 里已经有素材了：旧的.wav。不覆盖"
        ),
        "里已经有素材了",
    ),
}


@pytest.mark.parametrize("kind", sorted(_FAILURES))
def test_取回失败的原因原样到终端上(monkeypatch, tmp_path, capsys, kind):
    make, marker = _FAILURES[kind]
    song = tmp_path / "songs" / "09-来自链接"

    def boom(url, song_dir, **kw):
        raise make(Path(song_dir))

    monkeypatch.setattr(cli, "fetch_url", boom)
    _argv(monkeypatch, "ingest", str(song), "--url", URL)

    assert cli.main() == 1

    err = capsys.readouterr().err
    assert marker in err, f"{kind} 的原因没到终端上：\n{err}"
    for other, (_, other_marker) in _FAILURES.items():
        if other != kind:
            assert other_marker not in err, f"{kind} 打出来的却是 {other} 的话"


def test_取回失败就不往下跑(monkeypatch, tmp_path, stub_ingest_work):
    """取回失败还继续跑 `ingest` 的话，用户会先看到取回的原因、
    再看到一句"素材看不明白"——两条错，真正的那条被埋在上面。

    ★ **这条测试第一版是假绿的**（变异检验 W3 逮到）。第一版的替身抛错时
    `_in/` 是空的，于是"往下跑"也走不动——`scan` 当场 `IngestError`，
    `prepare_audio` 一次都没被调，退出码照样是 1。**断言没写错，是它跑的那个
    配置恰好不暴露问题**（`MGMT.md` 第七节那个最高频形状）。

    改法：让替身**先把素材落下去再抛**——这正是 `UnusableAudioError` /
    `AmbiguousResultError` 的真实形状（东西下回来了，只是不能用）。这样"往下
    跑"就真的跑得动，掉进去才会被抓住。
    """

    def boom(url, song_dir, **kw):
        in_dir = Path(song_dir) / "_in"
        in_dir.mkdir(parents=True, exist_ok=True)
        # 落一份**能用**的素材：不这样的话 `scan` 会先炸，掩护住这条断言。
        (in_dir / "取回来的.m4a").write_bytes(b"audio")
        raise fetch.AmbiguousResultError("一趟取回了 3 份", paths=[in_dir / "甲.m4a"])

    monkeypatch.setattr(cli, "fetch_url", boom)
    _argv(monkeypatch, "ingest", str(tmp_path / "a"), "--url", URL)

    assert cli.main() == 1
    assert stub_ingest_work == [], "取回都失败了，还是往下跑了 ingest"


# --------------------------------------------------------------------------
# 不给 --url 的那条老路一个字节没变
# --------------------------------------------------------------------------


def test_不给链接时走的还是原来那条路(monkeypatch, tmp_path, stub_ingest_work):
    song = tmp_path / "songs" / "10-手工放的"
    (song / "_in").mkdir(parents=True)
    (song / "_in" / "手工放的.wav").write_bytes(b"x")

    called = []
    monkeypatch.setattr(
        cli, "fetch_url", lambda *a, **k: called.append(1)
    )
    _argv(monkeypatch, "ingest", str(song))

    assert cli.main() == 0
    assert called == [], "没给 --url，却还是去取回了"
    assert ("audio", "手工放的.wav") in stub_ingest_work
