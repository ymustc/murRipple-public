"""「这首歌要不要歌词」——全仓唯一那一处判断。

## 原来是三处，而且互相矛盾

| 处 | 行为 |
|---|---|
| `cli.run` | 见不到 `lyrics.txt` 就退出 1 |
| `cli.build` | 见不到就打一句「跳过歌词层」，**照样做完** |
| `web/runner.lyrics_missing` | 见不到**或全是空白**就 `NEEDS_LYRICS` |

三次真跑（2026-08-14，同一个目录、同一份 12 秒 source.wav、没有 lyrics.txt）：

| # | 命令 | 结果 |
|---|---|---|
| ① | `murripple run <dir>` | rc=1，一步没跑 |
| ② | `murripple build <dir>` | rc=0，跑完，`0 句歌词` |
| ③ | `murripple run <dir>`（`build/timeline.json` **已在盘上**） | 仍然 rc=1 |

③ 是纯 bug：那一步只需要重新打包，跟歌词毫无关系。

## 两条都是真的，所以不做二选一

- `run` 那道门守的是「**你多半是忘了，而这会花你一小时**」。
- `build` 的降级守的是「**一首没有歌词的歌是合法产物**」——`compose` 整条线
  就是器乐曲，那道门当年还得为 `compose.json` 单开豁免才不至于把它堵死。

统一到任何一边都要毁掉另一条。所以这里不统一到哪一边，而是**让它们同时成立**：
**默认拦住；用户显式说 `--no-lyrics` 才放行。** 不靠猜，也不靠沉默降级——
沉默降级正是 `build` 那一半原来的毛病：它不问，也不说清用户是不是真想这样。

## 为什么单独成一个模块

`murripple/web/` 的立身之本是**不依赖分析管线**（`tests/test_web_runner.py` 有
一条干净子进程守卫钉着），所以它不能 `import murripple.cli`。而"这首歌有没有
能用的歌词"这个**事实**，管线和网页壳子问的是同一件事——同一件事只许有一份
实现。于是它落在这个只用标准库的叶子模块里，两边都 import 得起。

**事实与政策分开**：`lyrics_missing()` 是事实，两边共用；`blocked_reason()` 是
**管线的**政策（默认拦、`--no-lyrics` 放行）。网页壳子那条「音频路线歌词必填」
是**产品**决定、故意跟管线不同（它没有也不该有 `--no-lyrics`），所以它只用事实
那一半。两条政策各自只有一处，共用的那个事实也只有一处。
"""

from __future__ import annotations

from pathlib import Path

LYRICS_FILENAME = "lyrics.txt"

#: 合成的曲子自带这份乐谱。它在，就是用户已经说过"这是一首器乐曲"了——
#: 与 `--no-lyrics` 是同一件事的两种说法，不是两条策略。
COMPOSE_FILENAME = "compose.json"

#: 显式说"这首歌本来就没有歌词"的那个 flag。写成常量是为了让提示语与
#: `argparse` 那边永远是同一个字符串——两处各写一遍，改了一处就开始骗人。
NO_LYRICS_FLAG = "--no-lyrics"


def lyrics_missing(song_dir: Path) -> bool:
    """这首歌缺歌词吗。**空白算缺。**

    只查 `exists()` 的话，一份全是空格的 `lyrics.txt` 骗得过它，然后一路
    降级到没有歌词层——而用户以为自己给过了。网页那一层早就这么判了，
    管线那一半原来没有；这是两处原本就不一致的地方之一。
    """
    path = Path(song_dir) / LYRICS_FILENAME
    if not path.exists():
        return True
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip() == ""
    except OSError:
        return True


def blocked_reason(song_dir: Path, *, no_lyrics: bool = False) -> str | None:
    """管线能不能往下做这首歌。能就 `None`，不能就一句给人看的话。

    **默认拦住**：绝大多数情况下"没有 lyrics.txt"是忘了，而往下走要烧掉
    Demucs 那几分钟到一小时。拦得早，人不白等。

    **四条出路都写在消息里**：跑 `ingest`、自己写一份、让它在本机听一遍
    （`transcribe`，给的是要你自己断句改字的**草稿**，写不到 `lyrics.txt`）、
    或者明说这首歌本来就没有歌词。少写一条，那条路对用户就等于不存在。

    > 第四条是 2026-08-15 合并听写那一棒时补进来的。它原来长在 `cli.run` 的
    > 旧门后面（**另起一句 print，旧门那两行一个字节没动**——那一棒做得对），
    > 而旧门在同一天早些时候已经搬进 `build()` 并收成这一处了。
    > **两棒并行、各自基于不同的 `main`，合并时才撞上。** 不是谁写错了，
    > 是并行的固有代价；它没有自己合、报上来让管理窗口合，也做对了。
    """
    song_dir = Path(song_dir)
    if not lyrics_missing(song_dir):
        return None
    if no_lyrics:
        return None
    if (song_dir / COMPOSE_FILENAME).exists():
        return None
    # 第四条出路**另起一行、带两格缩进**，不揉进上面那句。两个理由：
    # ① 四条出路挤成一句话，人读到第三个分号就不读了；
    # ② `murripple/web/progress.py` 的分层按行首形状认「这是我们自己打的话」，
    #    揉进去会让它跟着第一行走——而这一行正是听写那条路的**唯一入口提示**，
    #    折进详细区就等于不存在。`tests/test_transcribe.py::TRANSCRIBE_SHAPES`
    #    两头都钉着（源码里有这一句 + 它归主日志）。
    return (
        f"{song_dir} 下没有 lyrics.txt。先跑 `murripple ingest {song_dir}`，"
        f"或者自己写一份；这首歌本来就没有歌词的话，加 {NO_LYRICS_FLAG}。\n"
        f"  实在没有歌词可抄，`murripple transcribe {song_dir}` 会在本机听一遍，"
        f"给你一份要你自己断句、改字的草稿（它不会写 lyrics.txt）。"
    )


__all__ = [
    "COMPOSE_FILENAME",
    "LYRICS_FILENAME",
    "NO_LYRICS_FLAG",
    "blocked_reason",
    "lyrics_missing",
]
