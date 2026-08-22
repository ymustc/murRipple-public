"""起 `murripple` 子进程、逐行读、实时更新状态。

跨的是**进程边界**，不是 Python API 边界：管线跑一小时、吃满 CPU、可能被
torch 搞崩，跑在子进程里的话崩了只死这一个任务，服务还活着。解析靠
`murripple/web/progress.py`，本模块只管起、读、收尾。

## 三件跟现实对上过的事

**一、stderr 合并进同一个流。** `cli.py:311`（`分离失败：`）、`716`
（`打包失败：`）、`284/388/435`（`  {exc}`）全部走 `sys.stderr`。不合并的话
用户看到的是「失败了」而没有任何原因——与「降级必须大声说」直接冲突。所以
`stderr=STDOUT`，两个流按到达顺序进同一份日志。

代价说在明处：**合并之后就分不出哪一行来自 stderr 了**，spec 第六节那句
「stderr 最后 20 行」在这里落成「**合并流**最后 20 行」（`ERROR_TAIL_LINES`）。
分得开和看得见原因，这一棒选后者。

**二、子进程的 stdout 必须关缓冲。** `cli.py` 的 `print()` 绝大多数不带
`flush`，而 Python 往**管道**上写 stdout 默认是块缓冲的——4 KB 攒不满就一个
字也不出来。一次 `run` 的全部输出加起来也就一两 KB，不关缓冲的话「实时进度」
会变成「跑完一小时之后一次性刷出 17 行」。所以给子进程的环境里塞
`PYTHONUNBUFFERED=1`。

`PYTHONIOENCODING=utf-8` 是同一处顺手加的：输出整段是中文，子进程要是落在
一个 ASCII 的 locale 上，`print()` 自己会 `UnicodeEncodeError`。**这一条没有
测试守着**（造一个 ASCII locale 的子进程环境不在这一棒的范围里），如实记在
这里。

**三、`\\r` 零个的前提是非 tty。** 管理窗口 2026-08-14 真跑一次 12 秒的
`build`（Demucs 全程），1546 字节、17 行、`\\r` **零个**——tqdm 在非 tty 下不
画进度条。`subprocess` 的管道正是非 tty，所以「一行 = 一条记录」这个假设在
W1 里成立。

**这是一个前提，不是一个性质。** 谁要是哪天给子进程接了个伪终端（为了让
Demucs 出进度条），Demucs 会开始往回打 `\\r`，`readline()` 会一直读不到换行
符，页面上的进度会整段卡住直到那一步跑完——而**没有任何测试会红**。

## 歌词门（W1 音频路线歌词必填）

`cli.py::run` 见不到 `lyrics.txt` 就退出 1，打的是「先跑 `murripple ingest
<目录>`」——**一句对网页用户毫无意义的话**：他没有命令行，也不知道 `<目录>`
是什么。管线一行不改，所以这一关拦在**起子进程之前**：没歌词的音频任务根本
走不到 `run` 那一步，状态是 `NEEDS_LYRICS`（一个结构化字段，好让页面重新问
他要歌词，而不是弹一句报错）。

只管 `run`。视频那条路的歌词**正是 `ingest` 要 OCR 出来的**，拿歌词拦
`ingest` 等于把整条路堵死。`transcribe` 同理，而且更直白：那一档存在的全部理由
就是"他没有歌词"，拿歌词去拦它是自相矛盾。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import dataclass, replace
from pathlib import Path

from murripple import lyrics_gate
from murripple.web import progress

#: 前两档 stage，跟 `jobs.ROUTE_RUN` / `ROUTE_INGEST` 是同两个值——页面拿到的是
#: `Job.route`，直接就能交过来。
STAGE_RUN = "run"
STAGE_INGEST = "ingest"

#: 第三档：听写。**不是一条路线，是音频那条路线上的一个前置动作**——所以它
#: 没有对应的 `jobs.ROUTE_*`。`Job.route` 仍然是 `run`，用户在页面上多点了一
#: 个「先听一遍」，于是先跑这一档，跑完落进**同一个**校对框，点「改好了，继续」
#: 再回到 `run`。视频那条路的 OCR 停顿走的正是这个框，这里是复用，不是另起。
STAGE_TRANSCRIBE = "transcribe"

STAGES = (STAGE_RUN, STAGE_INGEST, STAGE_TRANSCRIBE)

#: 子进程还在跑。
RUNNING = "running"
#: 退出码 0。
DONE = "done"
#: 非零退出。`RunState.error` 里是合并流的最后 `ERROR_TAIL_LINES` 行原文。
ERROR = "error"
#: 压根没起子进程——这个音频任务还没有歌词。**不是** `ERROR`：页面该重新问
#: 他要歌词，不是报错。
NEEDS_LYRICS = "needs-lyrics"

#: 出错时原样带上的尾部行数（spec 第六节）。
ERROR_TAIL_LINES = 20

#: 拦下来时说的那句话。**不提 `murripple ingest`，不提「目录」**——页面用户
#: 手上没有命令行。
NEEDS_LYRICS_MESSAGE = (
    "还差歌词。这一步要拿歌词去对时间，没有的话做不成。\n"
    "把这首歌的歌词贴进上面的框里，一行一句，再点开始。"
)


def murripple_command() -> tuple[str, ...]:
    """默认拿哪个 `murripple` 跑。

    先找 `sys.executable` 旁边那个——`serve` 跑在哪个 venv 里，就用哪个 venv
    的命令。这不是讲究：`.venv/bin/murripple serve` 直接起（没 activate、没
    `uv run`）时 `PATH` 里根本没有 `murripple`，照 `PATH` 找会在用户点「开始」
    的那一刻 `FileNotFoundError`。

    **不许 `.resolve()`**（2026-08-16 修）：`.venv/bin/python` 通常是个**指向
    解释器安装目录的符号链接**，`.resolve()` 会跟着它**跳出 venv**。实测这台
    机器上：

        sys.executable  .venv/bin/python
        resolve()       ~/.local/share/uv/python/cpython-3.11.15-…/bin/python3.11
        兄弟 murripple  同上目录 → **不存在**

    于是 `sibling.exists()` 为假、退回 `("murripple",)`，而那条路上 `PATH` 里
    没有它——`.venv/bin/murripple serve` 起的服务，**每个任务点「开始」就炸**。
    我们要的是「`serve` 这个进程所在的那个 bin 目录」，那正是 `.resolve()`
    之前的路径。
    """
    sibling = Path(sys.executable).parent / "murripple"
    if sibling.exists():
        return (str(sibling),)
    return ("murripple",)


MURRIPPLE_COMMAND = murripple_command()


def command_for(
    stage: str,
    song_dir: Path,
    *,
    title: str | None = None,
    url: str | None = None,
    command: tuple[str, ...] = MURRIPPLE_COMMAND,
) -> tuple[str, ...]:
    """拼出要跑的那一串。`command` 是**测试注入点**，写在调用现场。

    **不加 `--force`。** 断点续跑（每一步先看产物在不在）是 M4 定的既有行为。
    加一个 `--force` 就等于每次点开始都从 Demucs 从头再来一小时，而页面上看不
    出任何区别——直到用户等到第二个小时。

    **订正（2026-08-14 收口评审 I2）**：这里一度还写着「也正是『刷新页面、重开
    浏览器、再点一次继续』能接上的原因」——**那半句不成立**，见 `app.py` 模块
    docstring「一次跑一个，不做队列」一节。刷新页面之后网页这一层根本回不到那个
    目录（`job_id` 只活在进程内的 dict 与一个闭包变量里）。**不加 `--force` 的
    理由仍然成立**，它保的是「同一个目录再跑一次不白跑」——而当下够得到这条好处
    的是命令行，以及网页上对同一个 `job_id` 二次 `start` 的那条路。
    """
    if stage not in STAGES:
        raise ValueError(f"不认识的 stage {stage!r}，只有 {'、'.join(STAGES)}")
    argv = [*command, stage, str(song_dir)]
    if stage == STAGE_RUN and title:
        argv += ["--title", title]
    # `--url` 走的是 `ingest` 那一档。取回**故意做成 `ingest` 的一部分**而不是
    # 网页层的一个新动作：这样取回的全部输出（我们的 `[取回]` 行 + yt-dlp 的
    # 原文）顺着已有的这条管子实时到页面，「第一次要下运行时」那句话因此天然
    # 挂在正在下的那一刻上，而不是开跑前一句免责声明。
    if stage == STAGE_INGEST and url:
        argv += ["--url", url]
    return tuple(argv)


def child_env() -> dict[str, str]:
    """子进程的环境。见模块 docstring 第二条。"""
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def lyrics_missing(song_dir: Path) -> bool:
    """这个歌曲目录还缺歌词吗。**空白文件算缺。**

    2026-08-15：函数体搬进 `murripple/lyrics_gate.py`，这里只留一个转发。
    在那之前**同一个判断在仓里有三处**（`cli.run` 的门、`cli.build` 的降级、
    这里），而且互相矛盾——只有这里把"全是空格"算缺。

    `murripple/lyrics_gate.py` **只用标准库**，所以这个 import 不违反
    「网页壳子不依赖分析管线」那条（`test_web_runner.py` 有一条干净子进程
    守卫钉着，`murripple.cli` 仍在它的黑名单里）。

    **共用的是"这首歌有没有能用的歌词"这个事实，不是政策。** 管线那边的政策
    是"默认拦、`--no-lyrics` 放行"（`lyrics_gate.blocked_reason`）；网页这边
    的政策是"音频路线歌词必填"，它是 W1 的**产品决定**、故意跟管线不同——
    页面上没有也不该有 `--no-lyrics`。两条政策各自只有一处。
    """
    # **走模块引用，不用 `from ... import`**：后者在 import 那一刻就把函数绑死，
    # 于是「改掉唯一那一处的答案、看这边跟不跟」根本没法验——而那正是
    # 「只有一处在判」这件事唯一的守卫形式。
    return lyrics_gate.lyrics_missing(song_dir)


@dataclass(frozen=True)
class RunState:
    """某一刻的全部状态。冻的——拿到手里就不会再被读取线程改掉。"""

    #: `STAGE_RUN` 或 `STAGE_INGEST`。
    stage: str

    #: `RUNNING` / `DONE` / `ERROR` / `NEEDS_LYRICS`。
    status: str

    #: 两层进度 + 逐字日志 + 分层，全在这里（`murripple/web/progress.py`）。
    progress: progress.Progress = progress.EMPTY

    #: 子进程的退出码；还在跑、或压根没起，就是 `None`。
    returncode: int | None = None

    #: 出事时给用户看的原文。非零退出时是**合并流的最后 20 行，一个字不加**。
    error: str | None = None


class Run:
    """一次子进程调用。起完就返回，读取在后台线程里进行。"""

    def __init__(self, state: RunState, proc: subprocess.Popen[str] | None = None):
        self._lock = threading.Lock()
        self._state = state
        self._proc = proc
        self._thread: threading.Thread | None = None
        if proc is not None:
            self._thread = threading.Thread(target=self._pump, daemon=True)
            self._thread.start()

    # -------------------------------------------------------------- 对外

    def snapshot(self) -> RunState:
        """此刻的状态。随时可以问，问的时候子进程还在跑也没关系。"""
        with self._lock:
            return self._state

    def is_alive(self) -> bool:
        """子进程还在不在——问的是**操作系统**，不是我们自己记的账。"""
        return self._proc is not None and self._proc.poll() is None

    def wait(self, timeout: float | None = None) -> RunState:
        """等它跑完，返回终态。没起子进程的（歌词门）立刻返回。"""
        if self._thread is not None:
            self._thread.join(timeout)
        return self.snapshot()

    # -------------------------------------------------------------- 内部

    def _pump(self) -> None:
        """逐行读，读一行更一次状态。**不是 `communicate()`。**

        `communicate()` 要等子进程退出才交出全部输出——那意味着一小时里页面
        上一个字也没有，跑完之后一次性刷 17 行。而「跑完才更新」与「实时更
        新」在子进程退出之后**读到的东西一模一样**，所以守着这件事的那条测试
        必须卡在子进程还活着的窗口里（见
        `tests/test_web_runner.py::test_the_middle_of_the_transcript_is_readable_while_the_child_is_alive`）。

        用 `iter(readline, "")` 而不是 `for line in stdout`：两者在 py3 里都
        是 readline 语义，但前者把「一次一行、读到 EOF 为止」写在脸上。

        **`finally` 里一定要收尾。** 这个循环里抛出预料外的异常的话，没有
        `finally` 的版本会：状态**永远停在 `RUNNING`**（页面上一个永不结束的
        进度条），而且异常抛在 `self._proc.wait()` 之前，**子进程连回收都没有**
        ——一个僵尸进程加一个不会结束的页面，而 `Run` 没有 `terminate()`，
        用户没有任何出路。

        目前**找不到可达的触发点**（`progress.advance` / `parse_step` /
        `classify` 对任意字符串都是全函数，读管道用了 `errors="replace"` 所以
        解码不会抛）——所以这是「概率低但后果无出路」。守着它的是故障注入：
        `tests/…::test_a_crash_inside_the_reader_still_reaps_the_child`。
        """
        assert self._proc is not None and self._proc.stdout is not None
        try:
            for line in iter(self._proc.stdout.readline, ""):
                with self._lock:
                    self._state = replace(
                        self._state,
                        progress=progress.advance(self._state.progress, line),
                    )
        finally:
            # **先关这一头再 wait。** 读的人没了，子进程再写就拿到 EPIPE 然后
            # 自己死掉。不关就去 `wait()` 的话，管道一满子进程会永远卡在 write
            # 上，而我们永远卡在 wait 上——比「永不结束的进度条」更糟：那时候
            # 连收尸都收不掉。
            try:
                self._proc.stdout.close()
            except OSError:
                pass
            code = self._proc.wait()
            with self._lock:
                self._finish(code)

    def _finish(self, code: int) -> None:
        """收尾。**调用方持锁。**"""
        if code == 0:
            self._state = replace(self._state, status=DONE, returncode=code)
            return
        tail = self._state.progress.log[-ERROR_TAIL_LINES:]
        self._state = replace(
            self._state,
            status=ERROR,
            returncode=code,
            # 原样。**不加前缀、不加「处理失败」**——包装一层，用户看到的就是
            # 「失败了」而没有任何原因。
            error="\n".join(tail),
        )


def start(
    song_dir: Path,
    stage: str = STAGE_RUN,
    *,
    title: str | None = None,
    url: str | None = None,
    command: tuple[str, ...] = MURRIPPLE_COMMAND,
) -> Run:
    """起一次 `murripple`，立刻返回一个可以随时问状态的 `Run`。

    `command` 是**测试注入点**：没有环境变量、没有全局开关，默认值就是
    `MURRIPPLE_COMMAND`，想换只能写在调用现场。

    二次调用**不做任何去重**：断点续跑是 CLI 自己的既有行为（每一步先看产物
    在不在），让它自己说「跳过（已存在）」，比在这里缓存一份旧结果诚实——
    缓存的话，页面上那份状态没有任何人重新确认过。

    命令压根起不来（`FileNotFoundError` 之类）时**异常照抛给调用方**，不包成
    一个 `ERROR` 状态：那时候一行输出都还没有，`error` 里只能是我们自己编的
    话，而这一棒的规矩正是「不编」。接住它、在页面上说人话，是 Task 5 的事。
    """
    song_dir = Path(song_dir)
    argv = command_for(stage, song_dir, title=title, url=url, command=command)

    if stage == STAGE_RUN and lyrics_missing(song_dir):
        return Run(
            RunState(stage=stage, status=NEEDS_LYRICS, error=NEEDS_LYRICS_MESSAGE)
        )

    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        # **合并**。见模块 docstring 第一条。
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,  # 行缓冲：读的这一头也别攒着
        env=child_env(),
    )
    return Run(RunState(stage=stage, status=RUNNING), proc)


__all__ = [
    "DONE",
    "ERROR",
    "ERROR_TAIL_LINES",
    "MURRIPPLE_COMMAND",
    "NEEDS_LYRICS",
    "NEEDS_LYRICS_MESSAGE",
    "RUNNING",
    "STAGES",
    "STAGE_INGEST",
    "STAGE_RUN",
    "STAGE_TRANSCRIBE",
    "Run",
    "RunState",
    "child_env",
    "command_for",
    "lyrics_missing",
    "murripple_command",
    "start",
]
