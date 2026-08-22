"""子进程编排：起 `murripple`、逐行读、实时更新状态。

## 替身 CLI 打印的每一行都是抄来的原文

本文件里的替身（`FAKE_CLI_SOURCE`）**不自己编造输出格式**：跑通的那条路上，
它逐行重放 `tests/fixtures/real-build-output.txt`——管理窗口 2026-08-14 真跑
一次 12 秒 `build`（Demucs 全程）抓下来的原文（2026-08-16 在示例歌上重抄，
1594 字节 / 18 行）。另外三段（断点
续跑的「跳过」、歌词门、`分离失败：`）在 `cli.py` 里是 `print()` 的字面量，
`test_the_fake_cli_still_says_what_the_real_one_says` 逐条钉着「这段话此刻仍
在 `murripple/cli.py` 里」。

**这是本计划预言的「第九次」的落点**：用替身测子进程编排，而替身的输出格式
跟真 CLI 不一样，于是测试测的是一个不存在的东西。

## `\\r` 零个，前提是非 tty

那次真跑的 18 行里 **`\\r` 一个都没有**——tqdm／Demucs 在非 tty 下不画进度条。
`subprocess` 的管道正是非 tty，所以 W1 里「一行 = 一条记录」这个假设成立。

**这是一个前提，不是一个性质。** 谁要是哪天给子进程接了个伪终端（pty），
Demucs 的进度条会立刻变成一行里塞满 `\\r` 的巨型字符串，本文件全部关于
「第 n 行」的断言会在**不红**的情况下失去意义。

## 实时性怎么做到不赌时序

替身在打完第 3 行之后**停下来等一个闸门文件**（最多等 60 秒，防止跑飞的测试
把整个套件挂死）。于是「子进程还活着」这个窗口是**测试自己开着的**，不是靠
`sleep` 撞运气：

- 断言落在窗口里 —— 闸门没开，子进程**不可能**退出（并且断言里连着验
  `run.is_alive()` 与「闸门文件还不存在」两件事）
- 一个 `communicate()` 跑完再解析的实现，在这里会**等不到**中间状态：它要等
  子进程退出，而子进程在等闸门。`_wait_for` 到点抛 AssertionError（红），
  不会挂死；`finally` 里照样开闸门收尸

## 一个测试都不许碰仓内真实的 `songs/`

同 `test_web_jobs.py`：全部走 `tmp_path` + `jobs.create_job(songs_root=…)`。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from murripple.web import jobs, progress, runner

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

#: 真跑抄来的那 18 行。替身在「跑通」那条路上逐行重放它。
BUILD_FIXTURE = FIXTURE_DIR / "real-build-output.txt"
BUILD_LINES = BUILD_FIXTURE.read_text(encoding="utf-8").splitlines()

#: 替身打到第几行停下来等闸门。第 3 行是 `[3/5] 对齐歌词`——**内层的第三步**，
#: 后面还有 15 行。停在这里，中间状态既不是「什么都没有」也不是「已经全部」。
#:
#: **这个数跟下面那条实时性守卫的等待条件是绑死的**：它等的是
#: `inner == Step(3, 5, "对齐歌词")`，而闸门必须正好架在那一行之后——架早了
#: 等不到，架晚了中间状态就不是「刚好前 GATE_AFTER 行」。2026-08-16 夹具重抄
#: 之后第三方噪声挪到了 `[3/5]` 后面，这个数从 6 改成 3，就是为了跟住它。
GATE_AFTER = 3

#: 轮询中间状态的上限。跑通的实现在毫秒级就到位（替身打完 3 行立刻阻塞）；
#: 这个数只是「跑完才更新」那种实现的**放弃点**，不是判据阈值。
WAIT_TIMEOUT = 15.0

#: 等子进程收尾的上限。
JOIN_TIMEOUT = 60.0

MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00fake mp3 bytes"
MP4 = b"\x00\x00\x00\x20ftypisom fake mp4 bytes"


# ------------------------------------------------------------------ 替身 CLI
#
# 参数约定：`<夹具> <闸门|-> <流水账> <子命令> <歌曲目录> [其余]`。前三个由
# `command=` 在**调用现场**注进去，后面的由 `runner` 自己拼——所以流水账里记
# 下的就是 runner 真正拼出来的那串参数。

FAKE_CLI_SOURCE = '''\
"""替身 murripple。跑通那条路上打印的每一行都从真实夹具里读，一个字符不加。"""
import sys
import time
from pathlib import Path

FIXTURE, GATE, LEDGER = (Path(a) for a in sys.argv[1:4])
ARGV = sys.argv[4:]
SUB = ARGV[0]
SONG_DIR = Path(ARGV[1])

# 调用流水账：起没起子进程、起了几次、拿到的是哪几个参数，全在这个文件里。
with LEDGER.open("a", encoding="utf-8") as fh:
    fh.write("\\t".join(ARGV) + "\\n")

# cli.py:694-700 的歌词门，逐字照抄。**这几行是「没拦住」时用户会吃到的那句
# 命令行提示**——他没有命令行，也不知道 `<目录>` 是什么。
if SUB == "run" and not (SONG_DIR / "lyrics.txt").exists():
    print(
        f"{SONG_DIR} 下没有 lyrics.txt。先跑 `murripple ingest {SONG_DIR}`，"
        f"或者自己写一份。",
        file=sys.stderr,
    )
    raise SystemExit(1)

TIMELINE = SONG_DIR / "build" / "timeline.json"

# cli.py:703-704 的断点续跑分支：产物在就跳过，不重跑。
if SUB == "run" and TIMELINE.exists():
    print("[1/2] 分析    跳过（build/timeline.json 已存在，用 --force 重来）")
    print("[2/2] 打包")
    print(f"      → {SONG_DIR / 'dist' / 'index.html'}（12.2 MB）")
    raise SystemExit(0)

for index, line in enumerate(FIXTURE.read_text(encoding="utf-8").splitlines(), 1):
    # **跟 cli.py 一样，不 flush。** 管道上的 stdout 是块缓冲的，冲不冲由
    # 子进程的启动参数决定，而那是 runner 的职责。
    print(line)
    if index == GATE_AFTER and str(GATE) != "-":
        # 等闸门。60 秒是**跑飞的测试的保险丝**，不是判据的一部分：正常路径
        # 上测试断完就开闸门，等待是毫秒级的。
        deadline = time.time() + 60
        while not GATE.exists() and time.time() < deadline:
            time.sleep(0.02)

TIMELINE.parent.mkdir(parents=True, exist_ok=True)
TIMELINE.write_text("{}", encoding="utf-8")
raise SystemExit(0)
'''

#: 非零退出那条路：先打一批「早期的行」把尾部挤出去，再重放夹具，中途往
#: **stderr** 打一句 `分离失败：`（cli.py:311 就是走 stderr 的），最后退 3。
FAILING_CLI_SOURCE = '''\
"""替身 murripple，注定失败的那一个。"""
import sys
from pathlib import Path

FIXTURE = Path(sys.argv[1])

for i in range(1, EARLY_LINES + 1):
    print(f"早期的第 {i} 行")

for index, line in enumerate(FIXTURE.read_text(encoding="utf-8").splitlines(), 1):
    print(line)
    if index == STDERR_AFTER:
        # cli.py:311 的原文形状：`print(f"分离失败：{exc}", file=sys.stderr)`。
        # **不 flush**，跟真 CLI 一样。
        print("分离失败：ffmpeg 不在 PATH 里", file=sys.stderr)

raise SystemExit(3)
'''

#: 失败替身在夹具前面先打几行。这几行要被 20 行的尾部挤掉。
EARLY_LINES = 12

#: 失败替身在夹具第几行之后插那句 stderr。
STDERR_AFTER = 6

#: 那句 stderr 的原文。
STDERR_LINE = "分离失败：ffmpeg 不在 PATH 里"


@dataclass
class Fake:
    """一个装好的替身：命令前缀 + 闸门 + 流水账。"""

    command: tuple[str, ...]
    gate: Path
    ledger: Path

    def open_gate(self) -> None:
        self.gate.write_text("go", encoding="utf-8")

    def invocations(self) -> list[list[str]]:
        """流水账里每一次调用拿到的参数。没起过子进程就是空表。"""
        if not self.ledger.exists():
            return []
        return [
            line.split("\t")
            for line in self.ledger.read_text(encoding="utf-8").splitlines()
        ]


def _write_fake(tmp_path: Path, source: str, name: str) -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


@pytest.fixture
def no_ambient_unbuffering(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 `PYTHONUNBUFFERED` 从**本进程的**环境里摘掉。

    `runner.child_env()` 是从 `dict(os.environ)` 起手的，所以子进程会**继承**
    这台机器上已经导出的 `PYTHONUNBUFFERED`。不摘的话，实时性、合并顺序、
    尾 20 行这三条守卫在**任何一台全局导出了它的机器或 CI 上**，都会在
    `runner.py` 那一行被删掉之后照样全绿——守卫停止守卫，而没人会发现。

    这是 CONSTRAINTS 第 8 条视角的字面复现：**环境变量不出现在命令和输出里，
    误设即静默全绿**。摘掉之后，那三条守卫只依赖 `runner.child_env()` 里那一
    行赋值，跟跑它的人有没有设这个变量无关。

    实测过两遍（2026-08-14）：`runner.py` 删掉那行赋值之后，`PYTHONUNBUFFERED`
    未设时三条红、**已设时 13 条全绿**——后者正是这个 fixture 挡的东西。
    """
    monkeypatch.delenv("PYTHONUNBUFFERED", raising=False)
    assert "PYTHONUNBUFFERED" not in os.environ, (
        "环境里还留着 PYTHONUNBUFFERED。下面三条守卫会连着这个变量一起失效，"
        "而它们不会红——只会变得什么也不守。"
    )


@pytest.fixture
def fake(tmp_path: Path, no_ambient_unbuffering: None) -> Fake:
    """跑得通的那个替身，闸门开着（默认要等）。"""
    script = _write_fake(
        tmp_path, f"GATE_AFTER = {GATE_AFTER}\n" + FAKE_CLI_SOURCE, "fake_cli.py"
    )
    gate = tmp_path / "gate"
    ledger = tmp_path / "ledger.txt"
    return Fake(
        command=(sys.executable, str(script), str(BUILD_FIXTURE), str(gate), str(ledger)),
        gate=gate,
        ledger=ledger,
    )


@pytest.fixture
def ungated_fake(tmp_path: Path, no_ambient_unbuffering: None) -> Fake:
    """同一个替身，不设闸门——用在跟实时性无关的用例上。"""
    script = _write_fake(
        tmp_path, f"GATE_AFTER = {GATE_AFTER}\n" + FAKE_CLI_SOURCE, "fake_cli.py"
    )
    ledger = tmp_path / "ledger.txt"
    return Fake(
        command=(sys.executable, str(script), str(BUILD_FIXTURE), "-", str(ledger)),
        gate=tmp_path / "gate-unused",
        ledger=ledger,
    )


@pytest.fixture
def failing_fake(tmp_path: Path, no_ambient_unbuffering: None) -> Fake:
    script = _write_fake(
        tmp_path,
        f"EARLY_LINES = {EARLY_LINES}\nSTDERR_AFTER = {STDERR_AFTER}\n"
        + FAILING_CLI_SOURCE,
        "failing_cli.py",
    )
    return Fake(
        command=(sys.executable, str(script), str(BUILD_FIXTURE)),
        gate=tmp_path / "gate-unused",
        ledger=tmp_path / "ledger-unused.txt",
    )


# ------------------------------------------------------------------ 小工具


def _song(tmp_path: Path, lyrics: str | None = "谁先眨眼就输\n") -> Path:
    """用真的 `jobs.create_job` 建一个音频任务目录，落在 `tmp_path` 下。"""
    job = jobs.create_job(
        "我的歌.mp3", MP3, lyrics, songs_root=tmp_path / "songs"
    )
    return job.song_dir


def _wait_for(run, predicate, what: str, timeout: float = WAIT_TIMEOUT):
    """轮询到 `predicate` 成立为止；到点就红，**不挂死**。

    「跑完一次性灌进去」的实现在这里等不到——它要等子进程退出，而子进程正
    等着闸门。到点抛 AssertionError，调用方的 `finally` 再去开闸门收尸。
    """
    deadline = time.monotonic() + timeout
    while True:
        state = run.snapshot()
        if predicate(state):
            return state
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"等了 {timeout} 秒还没等到{what}。"
                f"当前 status={state.status!r}、outer={state.progress.outer!r}、"
                f"inner={state.progress.inner!r}、"
                f"已读到 {len(state.progress.log)} 行：{list(state.progress.log)!r}\n"
                "——一个跑完才更新状态的实现正是这个样子：子进程还没退出，"
                "状态里就什么都没有。"
            )
        time.sleep(0.01)


# ------------------------------------------------------------------ 尺子本身


def test_the_build_fixture_is_still_the_shape_this_file_assumes():
    """替身重放的那份夹具没被人「整理」过。

    本文件所有「第 n 行」的断言都建立在这 18 行上；第 3 行是内层的第三步，
    实时性那条守卫就卡在它身上。夹具一被改，别的用例不会红，它们只会变得
    什么也证明不了。

    2026-08-16 重抄过一次（旧那一份里未对上的那句是第三方作品的歌词），
    出处在 `tests/fixtures/README.provenance.md`。
    """
    raw = BUILD_FIXTURE.read_bytes()
    assert len(raw) == 1594, f"夹具应当是 1594 字节，实际 {len(raw)}"
    assert len(BUILD_LINES) == 18, f"夹具应当是 18 行，实际 {len(BUILD_LINES)}"
    assert raw.count(b"\r") == 0, (
        "夹具里出现了 \\r。真跑抄来的原文一个都没有——非 tty 下 tqdm 不画进度条，"
        "而这正是本文件「一行 = 一条记录」的前提。"
    )
    assert BUILD_LINES[GATE_AFTER - 1] == "[3/5] 对齐歌词", (
        f"第 {GATE_AFTER} 行应当是 `[3/5] 对齐歌词`，实际 "
        f"{BUILD_LINES[GATE_AFTER - 1]!r}——闸门就架在这一行后面。"
    )


def test_the_fake_cli_still_says_what_the_real_one_says():
    """替身自己编的那三段话，逐条钉在 `murripple/cli.py` 上。

    夹具管住了「跑通」那条路，管不住另外三条分支（歌词门、断点续跑、
    `分离失败：`）——那三段是替身照着 `cli.py` 的 `print()` 抄的。抄来的话
    会过期：管线哪天改了措辞，本文件那几条守卫就在**不红**的情况下开始守一
    个不存在的东西。所以在这里钉一次。
    """
    # 歌词门 2026-08-15 搬进 `murripple/lyrics_gate.py`（全仓唯一那一处判断），
    # 所以这里连它一起读。**钉子跟着字符串走**——它守的是"替身抄的那几句话
    # 管线现在还在打"，不是"它们必须长在 cli.py 里"。
    source = "\n".join(
        (REPO_ROOT / "murripple" / name).read_text(encoding="utf-8")
        for name in ("cli.py", "lyrics_gate.py")
    )
    for fragment, why in (
        ("下没有 lyrics.txt。先跑 `murripple ingest ", "歌词门（lyrics_gate.py）"),
        (
            "[1/2] 分析    跳过（build/timeline.json 已存在，用 --force 重来）",
            "断点续跑的跳过行（cli.py:704）",
        ),
        ('print(f"分离失败：{exc}", file=sys.stderr)', "分离失败走 stderr（cli.py:311）"),
    ):
        assert fragment in source, (
            f"`murripple/cli.py` 里找不到 {fragment!r}（{why}）。"
            "替身照着它抄的那段已经过期了。"
        )


def test_the_two_stages_are_the_two_routes_jobs_hands_over():
    """`runner` 的两档 stage 就是 `jobs` 的两条 route，一个字不差。

    页面拿到的是 `Job.route`，交给 `runner.start` 的是 `stage`。两边各写各的
    字面量的话，改一边不会有任何东西变红——直到用户点开始，才发现认不出。
    """
    assert runner.STAGE_RUN == jobs.ROUTE_RUN
    assert runner.STAGE_INGEST == jobs.ROUTE_INGEST


def test_the_default_command_points_at_a_murripple_that_really_exists():
    """默认命令是**这个环境里真的能跑起来的** `murripple`。

    `murripple/web/` 的立身之本是「靠 `subprocess` 调命令」，命令找不到的话
    整条路是断的，而断在用户点「开始」的那一刻——页面上只有一个 500。

    ★★ **这条守卫 2026-08-16 之前是永远绿的。**

    它原来只有 `shutil.which(...)` 一句。而**测试永远跑在 `uv run` 下**，那时
    `PATH` 里必然有 `.venv/bin`——所以哪怕 `murripple_command()` 完全失灵、
    退回了裸的 `("murripple",)`，`which` 也照样找得到。**它守的那件事
    （「`.venv/bin/murripple serve` 直接起也能跑」）恰恰是它测不到的那一种。**

    真实后果：`sys.executable` 上那句 `.resolve()` 跟着符号链接跳出了 venv，
    于是 `sibling` 落在解释器安装目录、不存在、退回裸命令——`PATH` 兜住了
    `uv run`，兜不住 `.venv/bin/murripple serve`。**是做「等待体验」那一棒的
    窗口顺手撞见的，不是这条守卫抓到的。**

    现在断两件事：①这个命令在**当前环境**里找得到（原来那半）；②它**指着
    `serve` 自己所在的那个 bin 目录**——后者才是它一直想守、却从来没守住的。
    """
    import shutil

    resolved = shutil.which(runner.MURRIPPLE_COMMAND[0])
    assert resolved is not None, (
        f"默认命令 {runner.MURRIPPLE_COMMAND!r} 的第一个元素既不是 PATH 里的"
        "可执行文件，也不是一个存在的绝对路径。"
    )

    own_bin = Path(sys.executable).parent
    if (own_bin / "murripple").exists():
        assert runner.MURRIPPLE_COMMAND == (str(own_bin / "murripple"),), (
            f"`{own_bin / 'murripple'}` 真的在那儿，而默认命令是 "
            f"{runner.MURRIPPLE_COMMAND!r}——没指着自己那个 venv。\n"
            "**`PATH` 会在 `uv run` 下把这件事盖住**，而 "
            "`.venv/bin/murripple serve` 直接起时没有 `PATH` 兜底："
            "每个任务点「开始」就 FileNotFoundError。"
        )


# ------------------------------------------------------------------ 命令怎么拼


def test_the_command_line_is_the_subcommand_plus_the_song_dir(tmp_path: Path):
    """`run` / `ingest` 各拼各的，`--title` 跟在后面。

    **不许出现 `--force`。** 断点续跑（每步先看产物在不在）是 M4 定的既有行
    为，加一个 `--force` 就等于每次点开始都从 Demucs 从头再来一小时，而页面
    上看不出任何区别——直到用户等到第二个小时。
    """
    song_dir = tmp_path / "songs" / "web-20260814-153012-我的歌"
    base = ("/somewhere/murripple",)

    run_cmd = runner.command_for(
        runner.STAGE_RUN, song_dir, title="我的歌", command=base
    )
    ingest_cmd = runner.command_for(runner.STAGE_INGEST, song_dir, command=base)

    # `--force` 先断，再断整串相等：反过来的话等式会把这一种坏法一起抓走，
    # 而失败信息里看不出「问题出在 --force」。
    for cmd in (run_cmd, ingest_cmd):
        assert "--force" not in cmd, (
            f"{cmd!r} 里出现了 --force。断点续跑会被它废掉——每次点开始都从"
            "Demucs 从头再来一小时，而页面上看不出任何区别。"
        )

    assert run_cmd == (
        "/somewhere/murripple", "run", str(song_dir), "--title", "我的歌",
    ), f"实际拼出来的是 {run_cmd!r}"
    assert ingest_cmd == ("/somewhere/murripple", "ingest", str(song_dir)), (
        f"实际拼出来的是 {ingest_cmd!r}"
    )


def test_an_unknown_stage_is_refused_before_anything_starts(tmp_path: Path):
    """认不出的 stage 当场拒掉，不去 `subprocess` 里碰运气。"""
    with pytest.raises(ValueError):
        runner.command_for("compose", tmp_path / "x")


# --------------------------------------------------------------- ★ 实时逐行


def test_the_middle_of_the_transcript_is_readable_while_the_child_is_alive(
    tmp_path: Path, fake: Fake
):
    """★ 判据「实时逐行更新」：**断言落在子进程还没退出的那个窗口里**。

    窗口是测试自己开的：替身打完第 3 行就停下来等闸门文件，闸门在断言做完之
    后才写。所以下面三件事同时成立——
    `run.is_alive()` 为真、闸门文件还不存在、状态里已经有了前 3 行。

    一个 `communicate()` 跑完再解析的实现在这里**等不到**中间状态：它要等子
    进程退出，而子进程在等闸门。`_wait_for` 到点抛 AssertionError。

    顺带钉住的第二件事：子进程的 stdout 必须是**不缓冲**的。替身跟 `cli.py`
    一样用不带 `flush` 的 `print()`，而管道上的 stdout 默认是块缓冲的——4 KB
    攒不满就一个字也不出来。这 3 行加起来才 60 来字节，冲不冲全看 runner 给
    子进程的启动参数。
    """
    song_dir = _song(tmp_path)
    run = runner.start(song_dir, runner.STAGE_RUN, command=fake.command)
    try:
        mid = _wait_for(
            run,
            lambda s: s.progress.inner == progress.Step(3, 5, "对齐歌词"),
            "内层走到 [3/5] 对齐歌词",
        )

        assert not fake.gate.exists(), "闸门被谁提前开了，这个窗口就不成立了。"
        assert run.is_alive(), (
            "子进程已经退出了——那这条断言读到的是「跑完之后的状态」，"
            "跟一个跑完才灌数据的实现完全区分不开。"
            "（`is_alive()` 问的是操作系统，不是我们自己记的账。）"
        )
        assert mid.status == runner.RUNNING, f"实际 status={mid.status!r}"
        assert mid.returncode is None
        assert list(mid.progress.log) == BUILD_LINES[:GATE_AFTER], (
            "子进程还卡在第 3 行，状态里却不是前 3 行。实际：\n"
            + "\n".join(repr(ln) for ln in mid.progress.log)
        )
    finally:
        fake.open_gate()

    final = run.wait(timeout=JOIN_TIMEOUT)
    assert final.status == runner.DONE, f"实际 {final.status!r} / {final.error!r}"
    assert final.returncode == 0
    assert list(final.progress.log) == BUILD_LINES, (
        "收尾之后日志不是那 18 行逐字实录。实际：\n"
        + "\n".join(repr(ln) for ln in final.progress.log)
    )
    assert final.progress.inner == progress.Step(5, 5, "组装 timeline")


# ------------------------------------------------------------- 非零退出


def _merged_transcript() -> list[str]:
    """失败替身按**发出的顺序**应当产生的整份合并流。"""
    lines = [f"早期的第 {i} 行" for i in range(1, EARLY_LINES + 1)]
    lines += BUILD_LINES[:STDERR_AFTER]
    lines.append(STDERR_LINE)
    lines += BUILD_LINES[STDERR_AFTER:]
    return lines


def test_a_non_zero_exit_carries_the_last_twenty_lines_verbatim(
    tmp_path: Path, failing_fake: Fake
):
    """判据：非零退出 → `error`，**尾部 20 行原样**，不包装成「处理失败」。

    断的是整份相等，不是「包含某几个字」：任何前缀（「处理失败：」）、任何
    截断、任何行数不对，都在这里红。

    尾部的**行数**也得断——不切片的实现（把 30 行全塞进去）跟切片的实现，
    只看「最后一行对不对」是分不开的。
    """
    song_dir = _song(tmp_path)
    run = runner.start(song_dir, runner.STAGE_RUN, command=failing_fake.command)
    state = run.wait(timeout=JOIN_TIMEOUT)

    assert state.status == runner.ERROR, f"实际 status={state.status!r}"
    assert state.returncode == 3, (
        f"退出码应当原样带上（替身退的是 3），实际 {state.returncode!r}"
    )

    expected_tail = _merged_transcript()[-runner.ERROR_TAIL_LINES :]
    assert len(expected_tail) == 20
    assert state.error is not None

    # 三条断言按「由粗到细」排，好让每一种坏法都在**它自己那条**上先红：
    # 包装 → 第一条；不切尾 → 第二条；错行、改字、顺序不对 → 第三条。
    # 倒过来排的话最后那条等式会先抓住全部三种，另外两条永远轮不到说话。
    assert "处理失败" not in state.error, (
        f"错误被包装了：{state.error!r}。判据点名要的是原样透出——包装一层，"
        "用户看到的是「失败了」而没有任何原因。"
    )
    actual_lines = state.error.split("\n")
    assert len(actual_lines) == runner.ERROR_TAIL_LINES, (
        f"错误正文是 {len(actual_lines)} 行，应当是 {runner.ERROR_TAIL_LINES} 行。"
        f"（子进程一共打了 {len(_merged_transcript())} 行，"
        "行数不对就说明尾部没切、或者切错了长度。）"
    )
    assert actual_lines == expected_tail, (
        "错误正文不是合并流的最后 20 行原文。实际：\n"
        + "\n".join(repr(ln) for ln in actual_lines)
        + "\n应当是：\n"
        + "\n".join(repr(ln) for ln in expected_tail)
    )


def test_the_stderr_line_lands_in_the_log_where_it_was_emitted(
    tmp_path: Path, failing_fake: Fake
):
    """裁定 B：stderr 合并进同一个流，**按到达顺序**进日志。

    `cli.py:311`（`分离失败：`）、`716`（`打包失败：`）、`284/388/435`
    （`  {exc}`）全部走 stderr。不合并的话用户看到的是「失败了」而没有任何
    原因——与「降级必须大声说」直接冲突。

    位置也要断，不能只断「在不在」：Python 的 stderr 是不带缓冲的，stdout 到
    管道上默认块缓冲——不给子进程关缓冲的话，stderr 那一行会**整整齐齐地跑
    到所有 stdout 前面**，而「在不在」那半条断言照样绿。
    """
    song_dir = _song(tmp_path)
    run = runner.start(song_dir, runner.STAGE_RUN, command=failing_fake.command)
    state = run.wait(timeout=JOIN_TIMEOUT)

    log = list(state.progress.log)
    assert STDERR_LINE in log, (
        f"stderr 那一行 {STDERR_LINE!r} 根本没进日志——两个流没合并。日志：\n"
        + "\n".join(repr(ln) for ln in log)
    )
    assert log == _merged_transcript(), (
        "合并流的顺序不对。实际：\n"
        + "\n".join(f"{i:>3} {ln!r}" for i, ln in enumerate(log))
        + "\n应当是：\n"
        + "\n".join(f"{i:>3} {ln!r}" for i, ln in enumerate(_merged_transcript()))
    )

    position = log.index(STDERR_LINE)
    assert position == EARLY_LINES + STDERR_AFTER, (
        f"stderr 那一行落在第 {position} 位，应当在第 "
        f"{EARLY_LINES + STDERR_AFTER} 位（紧跟着 {BUILD_LINES[STDERR_AFTER - 1]!r}）。"
    )
    assert log[position - 1] == BUILD_LINES[STDERR_AFTER - 1]
    assert log[position + 1] == BUILD_LINES[STDERR_AFTER]


@pytest.mark.filterwarnings(
    # 读取线程里的异常会被 pytest 的 threadexception 插件转成一条警告。这条
    # 测试**故意**让它抛，警告是预期的一部分；不消掉的话套件里会永远多一条
    # 来路不明的警告。消的是这一条测试的，不是全局的。
    "ignore::pytest.PytestUnhandledThreadExceptionWarning"
)
def test_a_crash_inside_the_reader_still_reaps_the_child(
    tmp_path: Path, ungated_fake: Fake, monkeypatch: pytest.MonkeyPatch
):
    """读取线程里炸了，状态也必须离开 `RUNNING`，子进程也必须被收掉。

    没有 `finally` 的话：状态**永远停在 `RUNNING`**——页面上一个永不结束的
    进度条；而且异常抛在 `self._proc.wait()` 之前，**子进程连回收都没有**。
    `Run` 又没有 `terminate()`，所以用户没有任何出路：既不会成功，也不会失败，
    也停不掉。

    **目前没有可达的触发点**（`progress.advance` / `parse_step` / `classify`
    对任意字符串都是全函数，读管道用了 `errors="replace"`），所以这里用故障
    注入把那条路径打开。这一条守的不是「某个已知的 bug」，是「兜底那段代码
    还在」——把 `try/finally` 拆掉，它必须红。

    `status` 收成 `DONE` 还是 `ERROR` **由时序决定**（子进程可能已经打完退出、
    也可能在我们关掉管道之后拿到 EPIPE 死掉），两种都算收住了。断言因此断的
    是「离开了 `RUNNING`」这件事本身，不去赌是哪一种——赌哪一种才是靠时序。
    """
    song_dir = _song(tmp_path)
    monkeypatch.setattr(
        runner.progress, "advance", lambda *args, **kwargs: 1 / 0
    )

    run = runner.start(song_dir, runner.STAGE_RUN, command=ungated_fake.command)
    state = run.wait(timeout=JOIN_TIMEOUT)

    assert state.status in (runner.DONE, runner.ERROR), (
        f"读取线程炸了之后 status 停在 {state.status!r}。"
        "页面上这就是一个永不结束的进度条，而 Run 没有 terminate()——"
        "用户既等不到成功、也等不到失败、也停不掉。"
    )
    assert state.returncode is not None, (
        "returncode 还是 None，说明 `self._proc.wait()` 压根没被调到——"
        "子进程没有被回收。"
    )
    assert not run.is_alive()


# ------------------------------------------------------------- 二次 start


def test_a_second_start_lets_the_cli_say_it_is_skipping(
    tmp_path: Path, ungated_fake: Fake
):
    """判据：同一个 job 二次 `start` **不重跑**，CLI 打「跳过（已存在）」。

    断点续跑是 M4 定的既有行为（`run` 每步先看产物在不在）。这一棒只验它确实
    透出来了——所以：

    1. 第二次**确实又起了一次子进程**（流水账两行）。runner 自己缓存一份旧结
       果、第二次直接返回的话，页面上看到的是一份没人重新确认过的状态
    2. 第二次的日志里**逐字**有那句「跳过（build/timeline.json 已存在…）」
    3. 两次拿到的参数一模一样，都没有 `--force`
    """
    song_dir = _song(tmp_path)

    first = runner.start(song_dir, runner.STAGE_RUN, command=ungated_fake.command)
    first_state = first.wait(timeout=JOIN_TIMEOUT)
    assert first_state.status == runner.DONE, f"第一次就没跑通：{first_state!r}"
    assert (song_dir / "build" / "timeline.json").exists()

    second = runner.start(song_dir, runner.STAGE_RUN, command=ungated_fake.command)
    second_state = second.wait(timeout=JOIN_TIMEOUT)
    assert second_state.status == runner.DONE

    calls = ungated_fake.invocations()
    assert len(calls) == 2, (
        f"替身被调用了 {len(calls)} 次，应当是 2 次。"
        "第二次 start 要真的再起一次子进程——让 CLI 自己说它跳过了，"
        "而不是 runner 端偷偷返回上一次的结果。"
    )
    assert calls[0] == calls[1] == ["run", str(song_dir)], f"实际 {calls!r}"

    skip_line = "[1/2] 分析    跳过（build/timeline.json 已存在，用 --force 重来）"
    assert skip_line in second_state.progress.log, (
        f"第二次的日志里找不到逐字的 {skip_line!r}。实际：\n"
        + "\n".join(repr(ln) for ln in second_state.progress.log)
    )
    assert "[1/5] 分离音源：source.mp3" not in second_state.progress.log, (
        "第二次又去分离音源了——这不是跳过，是重跑。"
    )


# --------------------------------------------------- 裁定 D：歌词必填


def test_an_audio_job_without_lyrics_never_reaches_the_cli(
    tmp_path: Path, ungated_fake: Fake
):
    """裁定 D：W1 音频路线**歌词必填**，而且拦在起子进程之前。

    没拦住的话，用户吃到的是 `cli.py:696` 那句「先跑 `murripple ingest
    <目录>`」——**一句对网页用户毫无意义的话**：他没有命令行，也不知道
    `<目录>` 是什么。

    「拦住了」和「没拦住」这两种状态靠三件事区分，一件都不能少：

    1. `status` 是 `NEEDS_LYRICS`，不是 `ERROR`（页面要重新问他要歌词，
       不是报错。断的是**结构化字段**，不是渲染出来的那句话）
    2. 流水账是**空的**——子进程一次都没起
    3. 透出去的话里**没有** `murripple ingest`
    """
    song_dir = _song(tmp_path, lyrics=None)
    assert not (song_dir / "lyrics.txt").exists(), "前提没成立：这个任务不该有歌词"

    run = runner.start(song_dir, runner.STAGE_RUN, command=ungated_fake.command)
    state = run.wait(timeout=JOIN_TIMEOUT)

    assert state.status == runner.NEEDS_LYRICS, (
        f"实际 status={state.status!r}、error={state.error!r}"
    )
    assert ungated_fake.invocations() == [], (
        f"子进程被起来了：{ungated_fake.invocations()!r}。"
        "歌词门必须拦在起子进程之前——走到 `run` 那一步就晚了。"
    )
    assert not run.is_alive()

    said = (state.error or "") + "\n".join(state.progress.log)
    assert "murripple ingest" not in said, (
        f"命令行提示漏到用户眼前了：{said!r}"
    )
    assert "歌词" in said, f"总得说清缺的是歌词。实际：{said!r}"


def test_the_ingest_stage_is_not_held_back_by_the_lyrics_gate(
    tmp_path: Path, ungated_fake: Fake
):
    """歌词门只管 `run`。视频那条路的歌词**正是 `ingest` 要 OCR 出来的**。

    少了这一条，一个「凡是没有 lyrics.txt 就拦」的实现会把视频路线整条堵死，
    而上面那条守卫照样全绿。
    """
    job = jobs.create_job("录屏.mp4", MP4, None, songs_root=tmp_path / "songs")
    run = runner.start(job.song_dir, runner.STAGE_INGEST, command=ungated_fake.command)
    state = run.wait(timeout=JOIN_TIMEOUT)

    assert state.status != runner.NEEDS_LYRICS, "ingest 被歌词门拦下了"
    assert ungated_fake.invocations() == [["ingest", str(job.song_dir)]], (
        f"实际 {ungated_fake.invocations()!r}"
    )


# ------------------------------------------------- ★ 不 import 分析管线

#: 干净子进程里只 import `murripple.web.*`，然后把 `sys.modules` 全交出来。
_ISOLATION_PROBE = """
import json
import sys

import murripple.web.jobs
import murripple.web.progress
import murripple.web.runner
import murripple.web.server

print(json.dumps(sorted(sys.modules)))
"""

#: 点名不许出现的管线模块。每一条都对着 `murripple/` 下一个真实文件——
#: 下面那条守卫会核对，免得列表里躺着一个拼错的名字（一个不存在的模块名
#: 永远「不在 sys.modules 里」，那是一条永真的断言）。
PIPELINE_MODULES = (
    "murripple.analyze",
    "murripple.separate",
    "murripple.align",
    "murripple.pack",
    "murripple.lanes",
    "murripple.timeline",
    "murripple.cli",
)

#: 管线拖着的重家伙。
HEAVY_THIRD_PARTY = ("torch", "librosa", "demucs", "whisperx", "numpy")

#: **唯一的例外**：管线与壳子共用的那几个"只用标准库的叶子模块"。
#:
#: 2026-08-15 加的第一条 `murripple.lyrics_gate`——「这首歌有没有能用的歌词」
#: 这个**事实**，管线和壳子问的是同一件事，而同一件事只许有一份实现（在那
#: 之前仓里有三处，且互相矛盾：只有壳子把"全是空格"算缺）。
#:
#: **这条例外是被下面 `test_the_shared_leaf_modules_really_are_leaves` 兜住的**：
#: 名单里的模块必须真的只 import 标准库。否则今天放进来一个叶子，明天它长出
#: 一条对 librosa 的依赖，这个口子就成了绕开整条守卫的后门——
#: 「防护措施自己会不会犯它要防的那个错」，`MGMT.md` 第七节。
#: 第二条 `murripple.ingest.transcribe` 2026-08-15 同日加：`app.py` 只为拿一个
#: 常量（`DRAFT_FILENAME`）import 它——草稿文件叫什么，管线和壳子必须是同一个
#: 名字。它对 `whisperx` 的 import 是**惰性**的（在函数里，不在模块顶层），所以
#: 它作为叶子成立；下面那条守卫正是在量这件事，`whisperx` 哪天被提到顶层，
#: 这里当场红。
#:
#: > 这一条本该由听写那一棒自己加，但这张名单当时还不在它的 `main` 上——
#: > 它把这件事写进报告让管理窗口合并时补。**没被分配的工作不会举手，
#: > 而这次它举了。**
SHARED_LEAF_MODULES = ("murripple.lyrics_gate", "murripple.ingest.transcribe")


def test_the_shared_leaf_modules_really_are_leaves():
    """★ 上面那条例外的边界：名单里的模块**一个非标准库的东西都不许多拖进来**。

    没有这一条，`SHARED_LEAF_MODULES` 就是一个可以无限放大的口子——
    往里加一个模块，它 import 什么都不再有人管。

    **断的是"比裸解释器多出了什么"，不是"`sys.modules` 里有什么"。**
    第一版断的是后者，当场红在 `pyannote` 上——那是 site-packages 里五个
    `*-nspkg.pth` 在**每一个**解释器启动时注入的，跟被测模块毫无关系
    （实测：`python -c "import sys"` 里就有它）。拿裸解释器当基线，这条
    守卫才是在量这个模块自己拖进来的东西。
    """
    assert SHARED_LEAF_MODULES, (
        "名单是空的——下面那一圈一次都不执行，于是默认通过"
    )

    def _modules(source: str) -> set[str]:
        proc = subprocess.run(
            [sys.executable, "-c",
             "import json, sys\n" + source + "\nprint(json.dumps(sorted(sys.modules)))"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert proc.returncode == 0, f"探针没跑通：\n{proc.stderr}"
        return set(json.loads(proc.stdout))

    baseline = _modules("")
    assert baseline, "基线是空的，这条守卫此刻什么也没在守"

    for name in SHARED_LEAF_MODULES:
        # `split(".", 1)[1]` 换成整条点号路径：第一个**嵌套包**里的模块
        # （`murripple.ingest.transcribe`）会被拼成 `murripple/ingest.transcribe.py`
        # 而找不着。它红得很清楚、没有装绿，但这条守卫本身只会拼一层。
        path = REPO_ROOT.joinpath(*name.split(".")).with_suffix(".py")
        assert path.exists(), f"{name} 对不上任何文件（{path} 不存在）"

        added = _modules(f"import {name}") - baseline
        assert name in added, (
            f"探针没真的 import 到 {name}——这条断言此刻什么也没在守"
        )
        pulled = sorted(
            m for m in added
            if m.split(".")[0] not in sys.stdlib_module_names
            and m.split(".")[0] != "murripple"
        )
        assert pulled == [], (
            f"{name} 不是叶子，它比裸解释器多拖进了：{pulled}。"
            "共用叶子模块只许 import 标准库——否则这条例外就成了绕开"
            "「壳子不依赖管线」的后门。"
        )


def test_importing_the_web_package_does_not_drag_in_the_pipeline():
    """★ 只 import `murripple.web.*` 时，`sys.modules` 里没有分析管线。

    **它证明什么、不证明什么**（管理窗口点名要求原样写在这里）：

    > 它证明 `murripple/web/` 自己没长出对管线的依赖（改动管线不会连累壳子、
    > 壳子不会把 torch 拖进请求处理路径）。它**不**证明「serve 进程里没有
    > torch」——那件事因为 `cli.py` 的顶层 import 本来就不成立。spec 第一节
    > 真正想要的「崩了只死一个任务」是**靠子进程保证的，不是靠 import 图**。

    **为什么必须在干净子进程里跑**：`murripple serve` 是 `cli.py` 的子命令，
    而 `cli.py` 顶层就 import 着 librosa／demucs 那一串；pytest 这个进程里，
    别的测试也早就把管线拉进 `sys.modules` 了。在主进程里查 `sys.modules`
    的话，这条断言**永远失败**——除非有人为了让它过而把它放宽成「查源码里
    有没有 import 字样」，那就退化成一条 `import 了但没用` 也能过的假守卫。
    """
    for name in PIPELINE_MODULES:
        # `split(".", 1)[1]` 换成整条点号路径：第一个**嵌套包**里的模块
        # （`murripple.ingest.transcribe`）会被拼成 `murripple/ingest.transcribe.py`
        # 而找不着。它红得很清楚、没有装绿，但这条守卫本身只会拼一层。
        path = REPO_ROOT.joinpath(*name.split(".")).with_suffix(".py")
        assert path.exists(), (
            f"{name} 对不上任何文件（{path} 不存在）。名单里躺着一个不存在的"
            "模块名，就等于躺着一条永真的断言。"
        )

    proc = subprocess.run(
        [sys.executable, "-c", _ISOLATION_PROBE],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"探针子进程没跑通（returncode={proc.returncode}）：\n{proc.stderr}"
    )
    modules = set(json.loads(proc.stdout))

    # 探针本身没哑：这四个模块**必须**在里面。空集合让下面每一条断言都免费
    # 通过，而 import 写错名字、探针被谁改成什么都不 import，都会得到空集合。
    for name in (
        "murripple.web.runner",
        "murripple.web.server",
        "murripple.web.jobs",
        "murripple.web.progress",
    ):
        assert name in modules, (
            f"探针里连 {name} 都没有。这条守卫此刻什么也没在守。"
        )

    leaked = sorted(
        name
        for name in modules
        if name.split(".")[0] == "murripple"
        and name != "murripple"
        and not name.startswith("murripple.web")
        and name not in SHARED_LEAF_MODULES
    )
    assert leaked == [], (
        f"`murripple/web/` 把管线拖进来了：{leaked}。"
        "壳子跑歌靠 `subprocess` 调命令，不靠 import。"
    )

    for name in PIPELINE_MODULES:
        assert name not in modules, f"{name} 被 import 进来了"

    heavy = sorted(name for name in HEAVY_THIRD_PARTY if name in modules)
    assert heavy == [], f"重家伙被拖进来了：{heavy}"
