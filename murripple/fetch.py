"""从一个视频链接取回素材，落进 `_in/`，交给现有的 `ingest` 决策表。

**版权与伦理（这一段不是装饰，是这个模块存在的前提）**

murRipple 的产物是**内嵌音频的自包含单文件**，设计目的就是"发给朋友、挂 GitHub
Pages"，而且已经有一个**公开**的 demo 仓 `ymustc/murripple-demo`。现在"手上得先
自己弄到一份音频"这道手续是**一层保护**——它恰好是"要不要把这首商业歌曲做成一个
可以直接挂公网的产物"的思考时机。把它压成一条命令，代价就是这个判断。

所以这个模块**刻意不做任何鼓励这件事的设计**：
不猜链接、不批量、不自动往下跑管线，取回时**无条件打印一句版权提醒**。

**规矩：凡是从链接取回来的商业录音，只在本地私有仓里处理，绝不进
`murripple-demo` 或任何公开仓库。** 公开 demo 只放自制素材。

调研见 `docs/research/2026-08-13-url-ingest.md` 第 0 节（那支实测视频的片头版权卡
写着环球音乐 / 华纳盛世，频道简介另有"禁一切"）。

---

**三级降级链**（`DECISIONS.md` 2026-08-13）：

| 顺位 | 路径 | 兜的是什么 |
|---|---|---|
| 1 | 子进程调**运行时拉取的最新** yt-dlp，**不锁版本** | 站点改版——主要失效方式 |
| 2 | 降级到环境里已装的可选 extra | 断网 / 拉不到 PyPI |
| 3 | 打印**可直接粘贴的手动命令** | 前两条都不成，人接手 |

"优先最新而非锁定版"反直觉但是对的：yt-dlp 坏不是因为它自己有 bug，是站点改版；
钉死的旧版比最新版更容易坏（调研当天就撞上 403）。

**降级必须大声说自己走了哪一条、以及为什么。** 悄悄降到旧版再 403，人看到的是个
莫名其妙的报错，根本想不到是降级导致的。与 `ingest` 打印每步决定、
`load_subtitle_timing` 打印退回原因同一路数。

子进程而不是 Python API：与 `separate.py` 调 Demucs 同一路数——CLI 接口跨版本
稳定得多，测试能完全替身掉，而且 yt-dlp **不进 `pyproject.toml`**，
分析链那串 numpy/torch 的版本约束一点碰不到。
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from murripple.ingest.audio import COPY_SUFFIXES

#: 取回来的音频要落在 `COPY_SUFFIXES` 里，`prepare_audio` 才会**原样复制、
#: 不转码**。挑 AAC 免转码是这条路真正的门道（调研第 5.1 节）——落成 opus，
#: `scan` 会把它归进 unknown 打印"忽略（用不上）"，整趟白跑。
AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]"

#: 视频只在要 OCR 硬字幕时才取。音轨同样优先 m4a 里的那条 AAC。
VIDEO_FORMAT = "bv*+ba[ext=m4a]/bv*+ba/b"
VIDEO_CONTAINER = "mkv"

#: 第 1 级要装的东西。`[default]` 是 requests/websockets 那一组，没有它
#: YouTube 会少一部分格式；`[deno]` 是 JS 运行时（36.7 MB 原生二进制），
#: YouTube 现在要它解挑战。**没有版本号是故意的**，见模块 docstring。
YTDLP_REQUIREMENT = "yt-dlp[default,deno]"

#: **我们自己**打的每一行都带这个前缀。yt-dlp 的原文一个字不改、原样透传，
#: 于是"哪些话是这个模块说的"是一条可判定的事实——W1 日志分层同一路数
#: （`MGMT.md` 第七节：缩进不携带任何可靠的结构信息，要分就按内容分）。
LOG_PREFIX = "[取回]"

#: 拿产物路径用的落点。前导点是**承重的**：`ingest.scan` 跳过隐藏文件，
#: 万一没删干净也不会把它当成一份素材。
PATH_SIDECAR = ".murripple-fetch-path"

#: 第 1 级静默多久就说一次"还在忙"。
#:
#: **订正（2026-08-14，冷缓存真跑一次推翻的）**：这里原先写着「第一次拉那
#: 36.7 MB 的 deno 二进制时一行输出都没有」——**不成立**。uv 自己会把每个包
#: 报出来（`Downloading deno (36.7MiB)` / ` Downloaded deno` /
#: `Installed 12 packages in 26ms`，抄件在 `tests/fixtures/yt-dlp/`），而它走
#: stderr、被 `_run` 并进同一个流，所以那段时间**是有输出的**，看门狗根本不
#: 会响。「第一次要下运行时」这件事看得见，靠的是 uv 自己 + stderr 合并。
#:
#: 看门狗因此不是为那一段存在的，它兜的是**真正的静默**：DNS 卡住、连上了不
#: 传数据、yt-dlp 在等一个慢站点。15 秒是个折中：短了会为一件没发生的事道歉，
#: 长了用户已经开始怀疑了。
QUIET_SECONDS = 15.0

#: 静默期说的那句话。**只在真的一行输出都没有时才说**（`_run` 里那个看门狗），
#: 不是开跑前一次性打的免责声明——那种话既盖不住真卡死，也会在跑得快的时候
#: 为一件没发生的事道歉。
#:
#: 措辞只声称"有一阵子没输出了"这个**已经量到的事实**，不声称它在下什么——
#: 它也可能是卡在 DNS 上。原稿那句「还在准备下载工具…」是照着一个没量过的
#: 假设写的，冷缓存真跑一次就推翻了。
QUIET_NOTICE = (
    "这一步有一阵子没有任何输出了。多半是在等网络——第一次还要拉一个约 "
    "36.7 MB 的运行时。不是卡死了，再等等。"
)

#: **面向用户的免责声明，不是写给我们自己看的。**
#:
#: 2026-08-15 于淼指出：上一版的原话是「绝不进 murripple-demo 或任何公开仓库」
#: ——`murripple-demo` 是**我们自己的仓库名**，对拿到这个工具的人毫无意义。
#: 一句提醒如果只有作者看得懂，它就不是提醒。
#:
#: 承重的那一句是「**你对自己处理和分发的素材负责**」——它同时出现在这里和
#: 页面上，`tests/test_web_fetch_wiring.py::test_页面上的版权提醒与取回层是同一句话`
#: 拿它当锚点钉着两处不许各写各的。
COPYRIGHT_NOTICE = (
    "⚠ 你对自己处理和分发的素材负责。从链接取回的录音多半受版权保护；"
    "murRipple 的产物内嵌完整音频，公开分享前请确认你拥有相应权利。"
    "全部处理都在你自己的机器上完成，不上传任何内容。"
)


class FetchError(RuntimeError):
    """取回失败。消息里必须带上可执行的修复建议。

    带结构化字段，测试断这些字段而不是断整条消息——消息里必然有修复建议，
    而修复建议里的词对每一条同类错误都成立（`MGMT.md` 第七节）。
    """

    def __init__(self, message: str, *, attempts=(), manual_command: str | None = None):
        super().__init__(message)
        self.attempts: tuple[Attempt, ...] = tuple(attempts)
        self.manual_command = manual_command


@dataclass(frozen=True)
class Attempt:
    """某一级的结果。`reason` 是**失败原因的原文**，不是"降级了"。"""

    tier: int
    label: str
    argv: tuple[str, ...]
    ok: bool
    returncode: int | None
    reason: str | None = None


class UnusableAudioError(FetchError):
    """取回来了，但落成了 `ingest` 用不上的那一档。

    单独一个类型，测试才断得住"是这个错"而不是"消息里有某个词"——
    消息里必然带修复建议，而修复建议里的词对每一条同类错误都成立
    （`MGMT.md` 第七节：消息里带修复建议 × `match=` 子串断言 = 断言失效）。
    """

    def __init__(self, message: str, *, path: Path, suffix: str, **kwargs):
        super().__init__(message, **kwargs)
        self.path = path
        self.suffix = suffix


class AmbiguousResultError(FetchError):
    """一趟下回来好几份，不知道该拿哪一份当音源。

    照 `ingest.scan` 的老规矩：拿不准就报错、把候选列出来，不猜。
    """

    def __init__(self, message: str, *, paths, **kwargs):
        super().__init__(message, **kwargs)
        self.paths = tuple(paths)


@dataclass(frozen=True)
class FetchResult:
    #: 本次实际用到的**最深**一级（取了视频时是两趟里更深的那个）。
    tier: int
    audio: Path
    video: Path | None
    attempts: tuple[Attempt, ...]


@dataclass(frozen=True)
class _Run:
    """一次子进程的结果。`output` 是 stdout 与 stderr **合并**后的原文。"""

    returncode: int
    output: str


def _run(
    argv: list[str],
    log: Callable[[str], None],
    *,
    quiet_notice: str | None = None,
    quiet_after: float = QUIET_SECONDS,
) -> _Run:
    """跑一个子进程，边跑边把输出交给 `log`，同时收下来备查。

    `quiet_notice` 是**静默看门狗**：只要一行输出都还没来，就每
    `quiet_after` 秒说一次这句话；第一行一到就永久闭嘴。判据是"不知情的人
    不会以为它卡死了"，所以这句话必须挂在**真的没有输出**这件事上——开跑前
    打一句免责声明既盖不住真卡死，也会在跑得快时为一件没发生的事道歉。

    **`stderr` 并进 `stdout`**：yt-dlp 的失败原因全在 stderr，不并的话人只看到
    "失败了"而没有任何原因——与"降级必须大声说"直接冲突（`DECISIONS.md`）。

    **`PYTHONUNBUFFERED=1`**：管道上 Python 的 stdout 是块缓冲的。不塞这个变量，
    "边跑边看"当场变成"跑完一次性刷出来"，而且光靠 `stderr=STDOUT` 连"按到达
    顺序"都做不到（W1 实测，`DECISIONS.md` 2026-08-14）。
    """
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    collected: list[str] = []
    spoke = threading.Event()  # 子进程开口了
    hushed = threading.Event()  # 该收工了（正常结束或出错）

    def nag() -> None:
        # `wait` 返回 True 表示被叫停；超时返回 False，那才是"又静默了一轮"。
        while not hushed.wait(quiet_after):
            if spoke.is_set():
                return
            log(quiet_notice)

    if quiet_notice is not None:
        threading.Thread(target=nag, daemon=True).start()

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            spoke.set()
            line = line.rstrip("\n")
            collected.append(line)
            log(line)
    finally:
        hushed.set()
        # 先关管道再 wait：直接 wait 的话管道一满就双向死锁。
        if proc.stdout is not None:
            proc.stdout.close()
        proc.wait()
    return _Run(returncode=proc.returncode, output="".join(f"{x}\n" for x in collected))


def _ytdlp_args(url: str, out_dir: Path, print_to: Path, *, video: bool) -> list[str]:
    """三级共用的这一段 yt-dlp 参数。"""
    args = ["-f", VIDEO_FORMAT if video else AUDIO_FORMAT]
    if video:
        args += ["--merge-output-format", VIDEO_CONTAINER]
    args += [
        # 产物路径不靠解析 stdout 拿。实测 `--print after_move:filepath` 会把
        # stdout 压成只剩一行路径（进度全没了）；`--print-to-file` 两样都要。
        # 这三个参数是**一体的**，中间插东西会把落点顶成下一个 flag。
        "--print-to-file",
        "after_move:filepath",
        str(print_to),
        "--no-playlist",
        "--newline",
        "-o",
        str(out_dir / "%(title)s.%(ext)s"),
        url,
    ]
    return args


def _tier1_argv(args: list[str]) -> list[str]:
    """uv 的临时环境：不进 `pyproject.toml`、不进 `uv.lock`、不动 `.venv`，
    **每次都是当时的最新版**。"""
    return ["uv", "run", "--with", YTDLP_REQUIREMENT, "--no-project", "--", "yt-dlp", *args]


def _tier2_argv(args: list[str]) -> list[str]:
    """环境里已装的那一份。`sys.executable -m` 保证跑在同一个 uv 环境里。"""
    return [sys.executable, "-m", "yt_dlp", *args]


def fetch_url(
    url: str,
    song_dir: Path,
    *,
    want_video: bool = False,
    force: bool = False,
    log: Callable[[str], None] = print,
) -> FetchResult:
    """把 `url` 的音频（可选：视频）取回 `song_dir/_in/`。"""
    song_dir = Path(song_dir)
    in_dir = song_dir / "_in"
    in_dir.mkdir(parents=True, exist_ok=True)

    _say(log, COPYRIGHT_NOTICE)

    # `_in/` 是用户仅有的原始素材，这一层只往里加、不覆盖。沿用 `prepare_audio`
    # 的规矩：已有东西就停下，`--force` 才继续。**先查再下载**——下完再说
    # "不该下"等于白跑一趟网络，而且新文件已经落在人家目录里了。
    existing = [
        p for p in in_dir.iterdir() if p.is_file() and not p.name.startswith(".")
    ]
    if existing and not force:
        names = "、".join(sorted(p.name for p in existing))
        raise FetchError(
            f"{in_dir} 里已经有素材了：{names}。不覆盖——它可能是你手工放进去的"
            f"更好的一份。确实要从链接重取的话加 --force，"
            f"或者把那些文件先移出 `_in/`。"
        )

    attempts: list[Attempt] = []
    audio, audio_attempts = _download(url, in_dir, log=log, video=False)
    attempts += audio_attempts

    # 落成 `_in/` 里一个 `.mp4`，`scan` 会把它当视频去 OCR；落成 `.opus` 则被
    # 归进 unknown、打印"忽略（用不上）"。两种都是一趟白跑，当场拦住。
    if audio.suffix.lower() not in COPY_SUFFIXES:
        raise UnusableAudioError(
            f"取回来的音频是 {audio.name}，而 `ingest` 只能直接用 "
            f"{'、'.join(COPY_SUFFIXES)}。这多半是这个站点没有 AAC 音频格式。"
            f"两条出路：① 若它其实就是 mp4 容器里的 AAC，改个扩展名即可——"
            f"`mv {shlex.quote(str(audio))} {shlex.quote(str(audio.with_suffix('.m4a')))}`；"
            f"② 先看看有哪些格式：`yt-dlp -F {shlex.quote(url)}`。",
            path=audio,
            suffix=audio.suffix.lower(),
            attempts=attempts,
        )

    video: Path | None = None
    if want_video:
        _say(log, "还要一份视频（硬字幕 OCR 用；只有视频里才有每行的出现时刻）。")
        video, video_attempts = _download(url, in_dir, log=log, video=True)
        attempts += video_attempts

    return FetchResult(
        tier=max(a.tier for a in attempts if a.ok),
        audio=audio,
        video=video,
        attempts=tuple(attempts),
    )


def _say(log, text: str, indent: str = "") -> None:
    """打一段我们自己的话。多行也逐行带前缀——只给第一行带的话，
    后面那些就混进第三方原文里去了。"""
    for line in text.splitlines() or [""]:
        log(f"{LOG_PREFIX} {indent}{line}")


def _sole_result(print_to: Path, attempts) -> Path:
    """读回这一趟的产物路径，必须**正好一份**。

    `--print-to-file` 是**追加**（真跑实测，见夹具的 provenance）：一趟下了
    好几个就是好几行。挑一行用是在猜——照 `scan` 的老规矩，拿不准就把候选
    都列出来交给人。
    """
    paths = [
        Path(line.strip())
        for line in print_to.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(paths) == 1:
        return paths[0]
    names = "、".join(p.name for p in paths)
    raise AmbiguousResultError(
        f"这条链接一趟取回了 {len(paths)} 份：{names}。"
        f"多半是它指向一个播放列表或合集。请换一条**单个视频**的链接；"
        f"确实要整份合集的话，自己挑一首下好放进 `_in/`，`ingest` 会照常接手。",
        paths=paths,
        attempts=attempts,
    )


def _reason(output: str) -> str:
    """从子进程原文里摘出**为什么失败**。

    优先 `ERROR:` 那几行（yt-dlp 的失败原因就在那儿）；uv 自己的失败没有
    `ERROR:`（实测是 `× No solution found …`），退回取末尾几行。
    """
    lines = [line for line in output.splitlines() if line.strip()]
    errors = [line for line in lines if line.lstrip().startswith("ERROR:")]
    if errors:
        return "\n".join(errors)
    return "\n".join(lines[-5:]) if lines else "（子进程没有任何输出）"


#: 三级里前两级是子进程，第 3 级是"交给人"。顺序即优先级。
_TIERS: tuple[tuple[int, str, Callable[[list[str]], list[str]], str], ...] = (
    (
        1,
        "运行时拉取的最新 yt-dlp（uv 临时环境，不进 pyproject/uv.lock，不锁版本）",
        _tier1_argv,
        "站点改版是 yt-dlp 唯一常见的失效方式，所以第一顺位永远取最新的。",
    ),
    (
        2,
        f"环境里已装的 yt-dlp（{Path(sys.executable).name} -m yt_dlp）",
        _tier2_argv,
        "这一级兜的是断网、拉不到 PyPI。它的版本是装的时候那一版，"
        "**站点改版之后比最新版更容易坏**——所以只在第 1 级不成时才用。",
    ),
)


def _download(url: str, in_dir: Path, *, log, video: bool) -> tuple[Path, list[Attempt]]:
    print_to = in_dir / PATH_SIDECAR
    args = _ytdlp_args(url, in_dir, print_to, video=video)
    attempts: list[Attempt] = []

    for index, (tier, label, build, note) in enumerate(_TIERS):
        argv = build(args)
        # 上一级留下的残件必须先清掉，否则这一级失败了也会读到上一级的路径，
        # 报出一个"成功了"。
        print_to.unlink(missing_ok=True)

        _say(log, f"第 {tier} 级：{label}")
        _say(log, f"$ {shlex.join(argv)}", indent="  ")

        returncode: int | None
        try:
            # 静默看门狗只挂第 1 级：那 36.7 MB 的运行时是 uv 临时环境才会拉的
            # 东西，第 2 级跑的是本地已装的模块，那儿说"还在下运行时"是撒谎。
            run = _run(
                argv,
                log,
                quiet_notice=f"{LOG_PREFIX} {QUIET_NOTICE}" if tier == 1 else None,
            )
        except (FileNotFoundError, PermissionError) as exc:
            returncode, reason = None, f"启动不了 {argv[0]}：{exc}"
        else:
            returncode = run.returncode
            if returncode == 0 and not print_to.exists():
                # 退出码 0 却没写出路径：站点改版之后 yt-dlp 有可能"成功地
                # 什么都没下"。当成失败处理，别把一个空目录报成取回成功。
                reason = "yt-dlp 退出码 0，但没有写出任何产物路径。"
            elif returncode == 0:
                reason = None
            else:
                reason = _reason(run.output)

        if reason is None:
            attempts.append(
                Attempt(tier, label, tuple(argv), True, returncode)
            )
            got = _sole_result(print_to, attempts)
            print_to.unlink(missing_ok=True)
            _say(log, f"取回成功（第 {tier} 级）：{got.name}")
            return got, attempts

        attempts.append(Attempt(tier, label, tuple(argv), False, returncode, reason))

        if index + 1 < len(_TIERS):
            nxt = _TIERS[index + 1]
            _say(log, f"⚠ 第 {tier} 级没成，降级到第 {nxt[0]} 级。原因是：")
            _say(log, reason, indent="    ")
            _say(log, nxt[3], indent="  ")

    manual = shlex.join(_tier1_argv(args))
    _say(log, f"⚠ 前 {len(_TIERS)} 级都不成，落到第 {len(_TIERS) + 1} 级：交给人。")
    for attempt in attempts:
        _say(log, f"第 {attempt.tier} 级（{attempt.label}）失败，原因是：")
        _say(log, attempt.reason or "", indent="    ")
    _say(
        log,
        "下面这条就是第 1 级刚才真跑的那条命令，原样贴进终端可以重来一遍"
        "（`--print-to-file` 那三个参数是我们用来拿产物路径的，留着不碍事）：",
    )
    _say(log, manual)
    _say(log, "取回来的文件留在 `_in/` 里，`murripple ingest` 会照常接手。")

    raise FetchError(
        "两级都没能取回来。手动命令已经打在上面了，"
        f"原样贴进终端跑一遍即可；跑通之后文件就在 {in_dir}，"
        "`murripple ingest` 会照常接手。",
        attempts=attempts,
        manual_command=manual,
    )
