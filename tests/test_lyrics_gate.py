"""「这首歌要不要歌词」——全仓唯一那一处判断。

## 原来是三处，而且互相矛盾

| 处 | 行为 |
|---|---|
| `cli.run` | 见不到 `lyrics.txt` 就退出 1（**排在"产物在就跳过分析"之前**） |
| `cli.build` | 见不到就打一句"跳过歌词层"，**照样做完** |
| `web/runner.lyrics_missing` | 见不到**或全是空白**就 `NEEDS_LYRICS` |

三次真跑摆过：同一个目录，`run` rc=1 一步不跑，`build` rc=0 跑完；
`build/timeline.json` 已经在盘上、只需要重新打包时 `run` **照样拒**——
那一步跟歌词毫无关系。

## 两条都是真的，所以不做二选一

- `run` 那道门守的是「**你多半是忘了，而这会花你一小时**」。
- `build` 的降级守的是「**一首没有歌词的歌是合法产物**」（`compose` 整条线就是）。

统一到任何一边都要毁掉另一条。修法是**让它们同时成立**：默认拦住，
**用户显式说 `--no-lyrics` 才放行**——不靠猜、不靠沉默降级。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from murripple import lyrics_gate


@pytest.fixture
def song(tmp_path):
    d = tmp_path / "某首歌"
    d.mkdir()
    return d


# --------------------------------------------------------------------------
# 事实那一半：这首歌有没有能用的歌词
# --------------------------------------------------------------------------


def test_没有文件就是缺(song):
    assert lyrics_gate.lyrics_missing(song) is True


def test_有内容就不缺(song):
    (song / "lyrics.txt").write_text("第一句\n", encoding="utf-8")
    assert lyrics_gate.lyrics_missing(song) is False


@pytest.mark.parametrize("blank", ["", "   ", "\n\n", " \t \n "])
def test_全是空白也算缺(song, blank):
    """`cli.build` 原来只查 `exists()`——一份全是空格的 `lyrics.txt` 骗得过它，
    然后一路降级到没有歌词层，**而用户以为自己给过了**。
    网页那一层早就把空白算缺了；这是两处原本就不一致的地方之一。
    """
    (song / "lyrics.txt").write_text(blank, encoding="utf-8")
    assert lyrics_gate.lyrics_missing(song) is True


# --------------------------------------------------------------------------
# 政策那一半：管线能不能往下做
# --------------------------------------------------------------------------


def test_有歌词就放行(song):
    (song / "lyrics.txt").write_text("第一句\n", encoding="utf-8")
    assert lyrics_gate.blocked_reason(song) is None


def test_没歌词默认拦住并说清三条出路(song):
    """判据 3：忘了放歌词的人不能白烧一小时。所以默认是拦，不是降级。"""
    reason = lyrics_gate.blocked_reason(song)

    assert reason is not None
    # 三条出路缺一不可：跑 ingest / 自己写一份 / 明说这首歌就没有歌词。
    assert "murripple ingest" in reason
    assert "自己写" in reason
    assert lyrics_gate.NO_LYRICS_FLAG in reason


def test_显式说了就是没有歌词才放行(song):
    """判据 4：这条路必须是用户**说出来**的，不能靠猜、不能靠沉默降级。"""
    assert lyrics_gate.blocked_reason(song, no_lyrics=True) is None


def test_合成的曲子本来就没有人声(song):
    """`compose.json` 在，就是用户已经说过"这是一首器乐曲"了——
    它和 `--no-lyrics` 是同一件事的两种说法，不是两条策略。"""
    (song / "compose.json").write_text("{}", encoding="utf-8")
    assert lyrics_gate.blocked_reason(song) is None


def test_有歌词时_no_lyrics_也不会把歌词扔掉(song):
    """`--no-lyrics` 是"我没有歌词"，不是"别用我给的歌词"。

    真扔掉的话，用户随手加了个 flag 就会毁掉一份对好的歌词层，而画面上
    只是"歌词没了"，看不出是哪个 flag 干的。
    """
    (song / "lyrics.txt").write_text("第一句\n", encoding="utf-8")
    assert lyrics_gate.blocked_reason(song, no_lyrics=True) is None
    assert lyrics_gate.lyrics_missing(song) is False


def test_拦住时那句话点名了是哪个目录(song):
    reason = lyrics_gate.blocked_reason(song)
    assert str(song) in reason


# --------------------------------------------------------------------------
# 接进 CLI：run 与 build 必须给同一个答案，而且只有一处在判
# --------------------------------------------------------------------------


@pytest.fixture
def packaged(tmp_path, monkeypatch):
    """一个有 timeline、没有 lyrics.txt 的歌曲目录 + 一个假的 pack。

    带 timeline 是为了让 `run` 走"断点续跑"那一支：**这一步只需要重新打包，
    跟歌词毫无关系**——原来那道门连它都拦（真跑 ③）。
    """
    from murripple import cli

    song = tmp_path / "无歌词的歌"
    (song / "build").mkdir(parents=True)
    (song / "build" / "timeline.json").write_text("{}", encoding="utf-8")

    def fake_pack(song_dir, renderer, title):
        out = Path(song_dir) / "dist" / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("<html></html>", encoding="utf-8")
        return out

    monkeypatch.setattr(cli, "pack", fake_pack)
    return song


def test_只需要重新打包时歌词门不许拦(packaged):
    """★ 判据 1（③ 那个纯 bug）。

    门原来在 `cli.py:726`，**排在 `:734` 那句「timeline 已存在就跳过分析」
    前面**。于是分析产物已经在盘上、只差重新打包时它照样退出 1——
    这在任何方向上都说不通，跟统一到哪边无关。
    """
    from murripple import cli

    assert cli.run(
        packaged, renderer=packaged, title=None,
        word_level=False, bitrate="64k", force=False,
    ) == 0


def test_要重新分析时歌词门照样拦在动_demucs_之前(packaged, monkeypatch, capsys):
    """判据 3：忘了放歌词的人不能白烧一小时。

    断的是**分离一次都没被调用**——只断退出码的话，"跑完 Demucs 才发现没歌词"
    的实现照样退出 1，那一小时照烧不误。
    """
    from murripple import cli

    (packaged / "build" / "timeline.json").unlink()
    separated = []
    monkeypatch.setattr(cli, "separate", lambda *a, **k: separated.append(1))

    code = cli.run(
        packaged, renderer=packaged, title=None,
        word_level=False, bitrate="64k", force=False,
    )

    assert code == 1
    assert separated == [], "已经开始分离了才发现没歌词——那一小时白烧了"
    assert "lyrics.txt" in capsys.readouterr().err


def test_歌词这件事只有一处在判(packaged, monkeypatch):
    """★ 判据 2 的守卫：**把那一处的答案改掉，`run` 必须跟着改。**

    判别法不是数源码里有几个 `lyrics.txt`（`ingest` 那边也有，与这件事无关），
    而是让唯一那一处永远说"不行"，看 `run` 认不认。跟不动就说明 `run` 自己
    还留着一份判断。
    """
    from murripple import cli

    monkeypatch.setattr(
        cli, "blocked_reason", lambda song_dir, **kw: "唯一那一处说不行"
    )
    (packaged / "build" / "timeline.json").unlink()

    assert cli.run(
        packaged, renderer=packaged, title=None,
        word_level=False, bitrate="64k", force=False,
    ) == 1


def test_显式说了没有歌词_run_就一路做到底(packaged, monkeypatch):
    """判据 4：那条路仍然走得通，但要用户说出口。"""
    from murripple import cli

    (packaged / "build" / "timeline.json").unlink()
    built = []
    # 替身的签名**照抄 `cli.build` 的真签名**，不用 `**kw` 兜住。
    #
    # 2026-08-15：`build` 长出 `language` 参数时这条当场 TypeError 红了——
    # **那是替身在报告它跟真实现漂了**，正是本仓「用替身测编排，而替身的输出
    # 跟真 CLI 不一样，于是测的是一个不存在的东西」那条教训想抓的东西。
    # 写成 `**kw` 会让它从此不再报告，红一次好过从此闭嘴。
    monkeypatch.setattr(
        cli, "build",
        lambda song_dir, word_level, bitrate, no_lyrics=False, language="zh": (
            built.append(no_lyrics) or 0
        ),
    )

    code = cli.run(
        packaged, renderer=packaged, title=None,
        word_level=False, bitrate="64k", force=False, no_lyrics=True,
    )

    assert code == 0
    assert built == [True], "`--no-lyrics` 没传到唯一那一处判断手里"


def test_网页壳子问的是同一处(tmp_path, monkeypatch):
    """★ 判据 6：那道「需要歌词」的闸门原来是第三处写着同一个判断的地方。

    判别法与 CLI 那条一样：**把唯一那一处的答案改掉，壳子必须跟着改。**
    跟不动就说明它自己还留着一份实现。

    （壳子的**政策**仍旧与管线不同——它没有也不该有 `--no-lyrics`。
    共用的是"这首歌有没有能用的歌词"这个**事实**。）
    """
    from murripple.web import runner

    song = tmp_path / "有歌词的歌"
    song.mkdir()
    (song / "lyrics.txt").write_text("第一句\n", encoding="utf-8")
    assert runner.lyrics_missing(song) is False

    monkeypatch.setattr(lyrics_gate, "lyrics_missing", lambda song_dir: True)
    assert runner.lyrics_missing(song) is True, (
        "改了唯一那一处的答案，壳子没跟着改——它自己还留着一份实现"
    )
