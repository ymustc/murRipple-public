"""把「`songs/<歌名>/source.mp3` + `lyrics.txt`」这套目录约定藏起来。

那套约定是给管线自己用的：`cli.find_source` 认 `source.*`，`cli.run` 认
`lyrics.txt`，`ingest.scan` 认 `_in/`。对着命令行做歌的人得自己建目录、把
音频改名、把歌词存成文件——三件事没有一件是关于音乐的。**这个模块就是那三
件事的全部落点。** 用户在页面上只挑一个文件、（可选）贴一段歌词。

只做目录与落盘。起子进程是 `murripple/web/runner.py` 的事，HTTP 是
`server.py` 的事。

## 两条路线由扩展名唯一决定

- 音频（`AUDIO_SUFFIXES`）→ 写成 `source.<小写后缀>`，`murripple run` 拿了就跑。
- 视频（`VIDEO_SUFFIXES`）→ 写进 `_in/<消毒后的 stem><小写后缀>`，先走
  `murripple ingest`：要抽轨，可能还要 OCR 硬字幕。**不能改叫 `source.mp4`**
  ——`find_source` 只认那四种音频后缀，`ingest.scan` 也是按扩展名分档的。

  写的**不是原名**：stem 过了 `safe_stem()`（去目录、抹控制字符、剥扩展名、
  截字节），后缀由 `route_for` 一路 `.lower()` 下来。`我的歌.MP4` 落成
  `_in/我的歌.mp4`；`../../x.mp4` 落成 `_in/x.mp4`。

歌词两条路线都写 `song_dir/lyrics.txt`（不写进 `_in/`）：`cli.ingest` 见到
它已存在就跳过 OCR，而这正是想要的——用户自己给的歌词是权威，OCR 会错字。
歌词原文一字不改地写下去；浏览器 textarea 发来的 CRLF 由下游的
`align.py:39`（`splitlines()` + `strip()`）吃掉。

## 文件名消毒只有一处

用户给的文件名被切成两半，各由一处管，**两处都不许有第二道兜底**：

- **名字那一半**归 `safe_stem()`——目录名和 `_in/` 里的文件名都用它，
  `create_job` 里没有别的地方碰它。
- **扩展名那一半**归 `route_for()` 的白名单：不在 `AUDIO_SUFFIXES` /
  `VIDEO_SUFFIXES` 里的一律 `JobError`，落盘用的是它 `.lower()` 过的那份。
  所以 `safe_stem` 剥掉扩展名不算漏，扩展名根本不经它的手。

只有一处的理由：消毒散开的话，删掉一处还有另一处兜着，变异检验会全绿，于是
没人知道哪一处才是真正在挡事的。要验这条守卫，就把 `safe_stem` 的函数体换成
`return filename.rsplit(".", 1)[0]`，
`tests/test_web_jobs.py::test_hostile_names_land_inside_songs` 必须红。

**「消毒后还在 `songs/` 里」这一条本身挡不住全部**（2026-08-14 实测）：
不消毒时 `../../x.mp3` 建出的是 `songs/web-<ts>-../../x/`，而 `web-<ts>-`
前缀恰好当了一级挡箭牌，`..` 只往上走了一层——最终落在 `songs/x/`，
**仍在 `songs/` 里面**，只是旁边多了个叫 `web-<ts>-..` 的残骸。测试因此
还要断「深度」和「`songs/` 下只多出一个目录」。
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

#: 仓内的 `songs/`。`create_job(songs_root=…)` 只是**测试注入点**——没有环
#: 境变量、没有全局开关，想改只能写在调用现场（见 CONSTRAINTS 第 8 条：逃生
#: 口藏进环境变量就等于没人看得见它被打开过）。
SONGS_ROOT = Path(__file__).resolve().parent.parent.parent / "songs"

#: 与 `cli.AUDIO_SUFFIXES` 一致——`find_source` 只认这四种。
AUDIO_SUFFIXES = (".mp3", ".wav", ".m4a", ".flac")

#: 与 `ingest.scan.VIDEO_SUFFIXES` 一致。比 brief 点名的 mp4/mov/mkv 多两
#: 种：`scan` 认得它们，这里拦下来只会让一个本来做得成的素材做不成。
VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm", ".avi")

ROUTE_RUN = "run"
ROUTE_INGEST = "ingest"

#: 消毒之后一个字符都不剩时用它（`...mp3`、`../.mp3` 这种）。
FALLBACK_STEM = "未命名"

#: 链接那条路的临时目录名。**不拿链接去拼**——那是用户可控的数据，而且这会儿
#: 还不知道曲名。取回之后由 `title_from_in_dir()` 认出真正的曲名。
URL_STEM = "来自链接"

#: 目录名里留给原文件名的字节数。
#:
#: 两个实测数（2026-08-14）：本机 macOS 15 / APFS 的单段上限是 **255 个字
#: 符**（第 256 个字符起 `OSError errno 63`，中文与 ASCII 同样在 255 处翻
#: 车，也就是它数的是字符）；而 ext4 数的是 **255 字节**，255 字节只装得下
#: 85 个汉字。按字节截断两边都活。96 字节 = 32 个汉字，前缀 20 字节，加上
#: 撞名时的 `-2` 后缀，离两个上限都还很远。
MAX_STEM_BYTES = 96

#: 控制字符（含 NUL）。NUL 不拦的话 `open()` 直接
#: `ValueError: embedded null byte`——"不能炸"这条会当场失守。
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

#: 同一秒里同名上传最多让到第几个。到顶了宁可报错，也不无限试下去。
_MAX_COLLISIONS = 1000


class JobError(ValueError):
    """素材做不成歌。消息要说清用户下一步该传什么。"""


@dataclass(frozen=True)
class Job:
    """一个刚建好的任务目录。盘上的东西已经写完了。"""

    #: `songs/web-<时间戳>-<原名>/`。
    song_dir: Path

    #: `ROUTE_RUN` 或 `ROUTE_INGEST`——下一步该跑哪条命令。
    route: str

    #: 音频落在 `source.<小写后缀>`，视频落在
    #: `_in/<消毒后的 stem><小写后缀>`（**不是原名**，见模块 docstring）。
    #:
    #: **链接那条路是 `None`**：这会儿盘上还什么都没有，素材要等
    #: `murripple ingest --url` 那个子进程去取。填一个不存在的路径进来，
    #: 下游只会拿着它去 `exists()` 然后得到一个说不出所以然的假。
    media_path: Path | None

    #: 没贴歌词就是 `None`（**不是**一个空的 `lyrics.txt`：空文件会骗过
    #: `cli.run` 的存在性检查，把"没有歌词"变成"有一份空歌词"）。
    lyrics_path: Path | None

    #: 链接那条路才有。`runner.command_for` 据此拼出 `--url`。
    url: str | None = None


def safe_stem(filename: str) -> str:
    """用户可控的文件名 → 一个安全的目录名片段。

    **名字这一半唯一的消毒点**（扩展名那一半归 `route_for` 的白名单，见模块
    docstring）。顺序有讲究：先取最后一段（把目录、绝对路径前缀、
    Windows 的 `\\` 一起丢掉），再抹控制字符，最后才剥扩展名——反过来的话
    `a\\nb.mp3` 的换行会留在片段里。

    首尾的点和空格一律去掉：`..` 只剩空串（走 `FALLBACK_STEM`），`.隐藏`
    变成 `隐藏`。中间的空格照留，那是人给歌起的名字。
    """
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL.sub("-", name)
    name = PurePosixPath(name).stem
    name = name.strip().strip(". ").strip()
    # 按字节截断，再把截出来的半个字符丢掉。
    name = name.encode("utf-8")[:MAX_STEM_BYTES].decode("utf-8", "ignore")
    return name.strip(". ").strip() or FALLBACK_STEM


def route_for(filename: str) -> str:
    """按扩展名定路线；认不出就 `JobError`。"""
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if suffix in AUDIO_SUFFIXES:
        return ROUTE_RUN
    if suffix in VIDEO_SUFFIXES:
        return ROUTE_INGEST
    raise JobError(
        f"认不出 {suffix or filename!r} 这种文件，做不成歌。\n"
        f"  音频：{'、'.join(AUDIO_SUFFIXES)}\n"
        f"  视频：{'、'.join(VIDEO_SUFFIXES)}"
    )


def _make_song_dir(songs_root: Path, base: str) -> Path:
    """建一个还没被占用的 `songs/<base>/`，返回它。

    目录名只精确到秒，页面上连点两下就会撞。用 `mkdir()` 不带 `exist_ok` 去认
    这件事，而不是先 `exists()` 再建：前者是一次原子的系统调用，后者在两个请求
    同时进来时会双双认为"不存在"，然后第二份 source.mp3 把第一份盖掉——而覆盖
    是**静默的**，用户只会发现歌变成了另一首。

    macOS 默认的 APFS 大小写不敏感（实测：建了 `Abc/` 之后 `abc` 也算存在），
    所以 `Song.mp3` 与 `song.mp3` 在这里同样会走到让名字这一步。
    """
    for attempt in range(1, _MAX_COLLISIONS + 1):
        song_dir = songs_root / (base if attempt == 1 else f"{base}-{attempt}")
        try:
            song_dir.mkdir(parents=True)
            return song_dir
        except FileExistsError:
            continue
    raise JobError(f"{songs_root} 下已经有 {_MAX_COLLISIONS} 个 {base} 了。")


def create_job_from_url(
    url: str,
    *,
    songs_root: Path = SONGS_ROOT,
    now: dt.datetime | None = None,
) -> Job:
    """链接那条路：只建目录，**素材一个字节都还没有**。

    取回是 `murripple ingest --url` 那个子进程干的事——做成 `ingest` 的一部分
    而不是网页层的新动作，取回的输出才顺着已有的进度管子实时到页面。

    **目录名不拿链接去拼。** 链接是用户可控的数据（`safe_stem` 那一整段说的
    就是这类东西），而且这会儿还不知道曲名——曲名要等 yt-dlp 把
    `%(title)s` 落下来，之后由 `title_from_in_dir()` 认。所以先叫
    `来自链接`，认出来了再说。
    """
    if not str(url).strip():
        raise JobError("链接是空的。把视频页面的地址整条粘贴进来。")

    stamp = (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    song_dir = _make_song_dir(Path(songs_root), f"web-{stamp}-{URL_STEM}")
    # `_in/` 先建好：`fetch` 会往里落，`scan` 也从这儿读。
    (song_dir / "_in").mkdir()

    return Job(
        song_dir=song_dir,
        route=ROUTE_INGEST,
        media_path=None,
        lyrics_path=None,
        url=str(url).strip(),
    )


def title_from_in_dir(song_dir: Path) -> str | None:
    """取回之后，从 `_in/` 里那份音频认出曲名。

    调研列的三样价值之一就是"自动命名编号"。认不出来的话，产物标题页上印的
    会是 `web-20260814-120000-来自链接`——一个用户从没打过的字符串。

    **认不出就返回 `None`，不编。** 下游拿 `None` 就退回既有行为（`pack` 用
    build 时记下的目录名）；硬编一个反而把"不知道"藏起来了。
    """
    in_dir = Path(song_dir) / "_in"
    if not in_dir.is_dir():
        return None
    audio = [
        p
        for p in sorted(in_dir.iterdir())
        if p.is_file()
        and not p.name.startswith(".")
        and p.suffix.lower() in AUDIO_SUFFIXES
    ]
    # 多份的话不猜——`ingest.scan` 在同一个位置也是报错不猜。
    if len(audio) != 1:
        return None
    return safe_stem(audio[0].name)


def create_job(
    filename: str,
    content: bytes,
    lyrics: str | None = None,
    *,
    songs_root: Path = SONGS_ROOT,
    now: dt.datetime | None = None,
) -> Job:
    """建任务目录、把素材落盘，返回下一步要用的路径。

    `songs_root` 与 `now` 都是**测试注入点**：不传就是仓内的 `songs/` 和此
    刻。产品路径上没有第二个调用方式。

    认不出的文件在**动盘之前**就拒掉——先建目录再校验的话，用户传错一次就
    在 `songs/` 下留一个空壳，而他在页面上看到的只是"失败了"。
    """
    route = route_for(filename)
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    stem = safe_stem(filename)

    stamp = (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    base = f"web-{stamp}-{stem}"

    # 目录名只精确到秒，页面上连点两下就会撞。用 `mkdir()` 不带 `exist_ok`
    # 去认这件事，而不是先 `exists()` 再建：前者是一次原子的系统调用，后者
    # 在两个请求同时进来时会双双认为"不存在"，然后第二份 source.mp3 把第一
    # 份盖掉——而覆盖是**静默的**，用户只会发现歌变成了另一首。
    #
    # macOS 默认的 APFS 大小写不敏感（实测：建了 `Abc/` 之后 `abc` 也算存
    # 在），所以 `Song.mp3` 与 `song.mp3` 在这里同样会走到让名字这一步。
    song_dir = _make_song_dir(Path(songs_root), base)

    if route == ROUTE_RUN:
        media_path = song_dir / f"source{suffix}"
    else:
        media_path = song_dir / "_in" / f"{stem}{suffix}"
        media_path.parent.mkdir()
    media_path.write_bytes(content)

    lyrics_path: Path | None = None
    if lyrics is not None and lyrics.strip():
        lyrics_path = song_dir / "lyrics.txt"
        lyrics_path.write_text(lyrics, encoding="utf-8")

    return Job(
        song_dir=song_dir,
        route=route,
        media_path=media_path,
        lyrics_path=lyrics_path,
    )
