"""`murripple serve` 的骨架：绑定地址、端口让路、ffmpeg 前置检查。

这三条判据的共同点是**只能从外部行为看出来**：

- 「绑了 `127.0.0.1`」与「绑了 `0.0.0.0`」在源码里只差一个字符串。断言
  `server.server_address[0] == "127.0.0.1"` 是把自己写进去的常量读回来，
  什么也没证明——把实现改成 `0.0.0.0` 之后那条断言照样绿。这里的判据是
  **从一台机器上的非环回地址连过去连不连得上**，见
  `test_the_serving_socket_is_unreachable_from_a_non_loopback_address`
  里那段对照组。
- 「端口被占用时换了端口」与「崩了」：真占住 8731 再起服务，断言它落在
  8732 **并且真的应答 HTTP 请求**——只断端口号的话，一个绑上了却不 listen
  的实现也能骗过去。
- 「ffmpeg 不在 PATH 时报了」与「没报」：两边都跑一遍真的 `serve` 子进程，
  一次 PATH 里放一个假 ffmpeg、一次 PATH 是空目录，比对终端输出。

`serve` 会一直跑下去，所以那几条端到端的用例走真实子进程
（`python -m murripple.cli serve`）——顺带把「子命令确实接上了 CLI」和
「打印出来的是**实际**端口」一并验了，这两件事在进程内没法验。
"""

from __future__ import annotations

import contextlib
import http.client
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from murripple.web import server

REPO = Path(__file__).resolve().parent.parent

# 服务起来之后等它打印那行地址的上限。冷启动要 import 整条分析管线
# （实测约 1 秒），慢机器留足二十倍余量。
SERVE_STARTUP_TIMEOUT = 20.0

# 那行地址长什么样。**特意不写死主机名**：绑定地址是不是 127.0.0.1，由
# `test_the_serving_socket_is_unreachable_from_a_non_loopback_address` 一条
# 用行为去证；这几条子进程用例只关心端口与 ffmpeg，不该跟着一起红。
# （实测：写死 `http://127.0.0.1:` 的话，把实现改成 0.0.0.0 会让这三条各自
# 空等满一个 timeout 才失败，一次变异检验要跑三分钟，还看不出是哪条守卫在
# 起作用。）
URL_RE = re.compile(r"http://[\d.]+:(\d+)")
URL_NEEDLE = "http://"

# 骨架阶段任何路径都回 404（真正的端点是后面几棒的事）。探测路径特意取一个
# 不会被将来任何端点占用的名字，这样这几条用例在端点长出来之后仍然成立：
# 它们要的只是「拿到了 HTTP 应答」，不是某个具体状态码的语义。
PROBE_PATH = "/__murripple_probe__"


# ---------------------------------------------------------------- 套接字工具


@contextlib.contextmanager
def _listening(host: str, port: int = 0):
    """占住一个地址:端口，直到退出上下文。

    端口已经被别人占着时，`bind` 抛的是 `OSError: [Errno 48] Address already
    in use`——那句话既不说是哪个端口、也不说该怎么办。而**最可能占着 8731 的
    就是产品自己**（`murripple serve` 的默认端口正是 8731）：一边开着壳子一边
    跑测试套，这里必炸，报错却完全指不到原因。所以自己接住，说人话。

    不 `skip`：跳过是绿色的一种（`MGMT.md` 第七节），而这两条端口测试是真的
    没跑。照 `test_regression_real_songs.py` 那条守卫的路数——**红，且报错原文
    里就写着修法**。
    """
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError as exc:
        sock.close()
        raise AssertionError(
            f"占不住 {host}:{port} —— {exc}。\n"
            f"这条测试要自己占住 {port} 来模拟「端口被占」，占不住就什么都测不了。\n"
            "最常见的原因是**你自己的壳子还开着**（`murripple serve` 默认就绑 8731）。\n"
            "先查是谁：  lsof -nP -iTCP:8731 -iTCP:8732 -sTCP:LISTEN\n"
            "再关掉：    pkill -f 'murripple serve'"
        ) from exc
    sock.listen(8)
    try:
        yield sock
    finally:
        sock.close()


def _can_connect(host: str, port: int, timeout: float = 2.0) -> bool:
    client = socket.socket()
    client.settimeout(timeout)
    try:
        client.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        client.close()


def _bindable_non_loopback_ipv4() -> str | None:
    """本机上一个**非环回**的 IPv4 地址，没有就返回 None。

    两个来源都试：一是让内核按默认路由挑一个源地址（UDP `connect` 不发包），
    二是解析主机名。拿到之后**再 `bind` 一次确认它真的属于本机**——解析出来
    的地址不一定还配在网卡上（换了网络之后 mDNS 缓存尤其容易过期），拿一个
    绑不上的地址去连，连不上的原因就成了「地址不存在」而不是「服务没绑它」，
    那条断言就变成永真的了。
    """
    candidates: list[str] = []

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        candidates.append(probe.getsockname()[0])
    except OSError:
        pass
    finally:
        probe.close()

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.append(info[4][0])
    except OSError:
        pass

    for addr in candidates:
        if addr.startswith("127.") or addr == "0.0.0.0":
            continue
        test_sock = socket.socket()
        try:
            test_sock.bind((addr, 0))
        except OSError:
            continue
        finally:
            test_sock.close()
        return addr
    return None


def _http_status(port: int, path: str = PROBE_PATH, timeout: float = 5.0) -> int:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path)
        return conn.getresponse().status
    finally:
        conn.close()


# ---------------------------------------------------------------- 子进程工具


def _spawn_serve(path_dir: Path) -> tuple[subprocess.Popen, list[str]]:
    """真跑一次 `murripple serve`，`PATH` 换成 `path_dir` 一个目录。

    stderr 并进 stdout：判据说的是「在**终端**打印」，不区分是哪一股。
    **不加 `-u`**——输出能不能实时读到，本身就是被测行为的一部分
    （`serve` 里那几个 `flush=True`）。用 `-u` 会把它盖掉。
    """
    env = dict(os.environ)
    env["PATH"] = str(path_dir)
    env.pop("PYTHONUNBUFFERED", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "murripple.cli", "serve"],
        cwd=REPO,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    lines: list[str] = []
    reader = threading.Thread(
        target=lambda: lines.extend(iter(proc.stdout.readline, "")), daemon=True
    )
    reader.start()
    return proc, lines


def _wait_for(
    proc: subprocess.Popen, lines: list[str], needle: str, timeout: float
) -> str | None:
    """等某一行出现。**子进程一死就立刻返回**，不空等满 timeout。

    死等的话，「serve 启动就退出」这种失败要等满一分钟才报出来，而那正是
    最该被快速看见的一种（判据里「服务照常起来」的反面）。
    """
    deadline = time.monotonic() + timeout
    while True:
        for line in list(lines):
            if needle in line:
                return line
        if proc.poll() is not None:
            # 进程已退出：再收一次尾巴（读取线程可能还没把最后几行 append 完）
            time.sleep(0.2)
            for line in list(lines):
                if needle in line:
                    return line
            return None
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.05)


def _stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
    if proc.stdout is not None:
        proc.stdout.close()


def _fake_ffmpeg_dir(tmp_path: Path) -> Path:
    """一个只装着可执行 `ffmpeg` 的目录，用来当 `PATH`。"""
    bin_dir = tmp_path / "with-ffmpeg"
    bin_dir.mkdir()
    fake = bin_dir / "ffmpeg"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    return bin_dir


def _empty_path_dir(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "without-ffmpeg"
    bin_dir.mkdir()
    return bin_dir


# ---------------------------------------------------------------- 绑定地址


def test_the_serving_socket_is_unreachable_from_a_non_loopback_address():
    """只绑环回：从本机的局域网地址连过去必须连不上。

    对照组不是可有可无的。这条断言想证的是「服务没绑那个地址」，但
    「连不上」还有别的成因（防火墙拦入站、地址根本不在本机上）。任何一种
    成因成立，这条断言就变成永真——把实现改成 `0.0.0.0` 它也照样绿，
    也就是本仓栽过八次的那个形状：断言没写错，但它看不见差别。

    所以先在同一台机器上起一个绑 `0.0.0.0` 的对照服务，要求从那个地址
    **连得上**。这一步是 `assert` 不是 `skip`：连不上说明这台机器上
    「绑 0.0.0.0」与「绑 127.0.0.1」在外部看来没有区别，此时这条守卫
    什么也证明不了，应该红着让人看见，而不是绿着混过去。

    唯一的 `skip` 分支是「本机一个非环回 IPv4 都没有」（网卡全下线）。
    那种机器上两种绑法在行为上确实完全相同，没有可测的差别存在。
    """
    addr = _bindable_non_loopback_ipv4()
    if addr is None:
        pytest.skip(
            "本机没有可绑定的非环回 IPv4（网卡全下线？）。"
            "这种机器上绑 0.0.0.0 与绑 127.0.0.1 在外部看来没有任何差别，"
            "没有可测的东西——不是守卫失效，是差别本身不存在。"
        )

    with _listening("0.0.0.0") as control:
        control_port = control.getsockname()[1]
        assert _can_connect(addr, control_port), (
            f"对照组失败：一个绑 0.0.0.0 的服务，从 {addr}:{control_port} 都连不上。"
            "说明这台机器上'能不能从非环回地址连过来'这把尺子本身是坏的"
            "（多半是防火墙拦了入站），下面那条断言在这里证明不了任何事。"
        )

    httpd = server.start_server()
    try:
        port = httpd.server_port
        assert _can_connect("127.0.0.1", port), (
            f"服务在 127.0.0.1:{port} 上就连不上——它根本没在 listen，"
            "下面那条'非环回连不上'的断言会因此永真。"
        )
        assert not _can_connect(addr, port), (
            f"服务在非环回地址 {addr}:{port} 上也能连上：它绑的不是 127.0.0.1。"
            "本机壳子会因此暴露给整个局域网——同网段的任何人都能拿它跑命令、"
            "读文件路径。"
        )
    finally:
        httpd.server_close()


# ---------------------------------------------------------------- 端口让路


def test_the_port_steps_up_when_8731_is_taken_and_the_new_one_really_serves():
    """8731 被占住时落到 8732，而且那个端口真的应答请求。

    端口号写死不走 `server.DEFAULT_PORT`：判据里 8731 是一个**产品承诺**，
    引用常量的话，把默认值改成别的数这条测试还是绿的。

    「真的应答」那一半也不能省——只断端口号的话，一个 bind 了却没 listen、
    或者压根没挂处理器的实现也能通过。
    """
    with _listening("127.0.0.1", 8731):
        httpd = server.start_server()
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            assert httpd.server_port == 8732, (
                f"8731 被占住时应当往上找到 8732，实际落在 {httpd.server_port}"
            )
            assert _http_status(httpd.server_port) == 404
        finally:
            httpd.shutdown()
            thread.join(timeout=10)
            httpd.server_close()


def test_serve_prints_the_port_it_actually_got_not_the_one_it_asked_for(tmp_path):
    """8731 被占住时，终端上那行地址写的必须是 8732。

    打印要的端口而不是拿到的端口，是这一条最容易写砸的地方：用户照着
    打印出来的地址打开浏览器，落在一个没人 listen 的端口上。
    """
    with _listening("127.0.0.1", 8731):
        proc, lines = _spawn_serve(_fake_ffmpeg_dir(tmp_path))
        try:
            line = _wait_for(proc, lines, URL_NEEDLE, SERVE_STARTUP_TIMEOUT)
            assert line is not None, f"没等到地址那一行。输出：\n{''.join(lines)}"
            match = URL_RE.search(line)
            assert match is not None
            printed = int(match.group(1))
            assert printed == 8732, (
                f"8731 被占住，终端打印的却是 {printed}。输出：\n{''.join(lines)}"
            )
            assert _http_status(printed) == 404, (
                f"打印出来的 {printed} 端口上没有服务在应答"
            )
        finally:
            _stop(proc)


# ---------------------------------------------------------------- ffmpeg


def test_serve_reports_missing_ffmpeg_yet_keeps_serving(tmp_path):
    """ffmpeg 不在 PATH：终端上要出现带 `brew install ffmpeg` 的那条消息，
    **而服务照常起来**。

    后一半是这条用例的重点。启动阶段直接 `sys.exit` 的话，用户连页面都
    打不开，那条修复建议他一个字也看不到——建任务阶段的硬拒是后面棒的事，
    这里只负责说一声。
    """
    proc, lines = _spawn_serve(_empty_path_dir(tmp_path))
    try:
        line = _wait_for(proc, lines, URL_NEEDLE, SERVE_STARTUP_TIMEOUT)
        assert line is not None, (
            f"ffmpeg 缺席时服务没起来（没等到地址那一行）。输出：\n{''.join(lines)}"
        )
        port = int(URL_RE.search(line).group(1))
        assert _http_status(port) == 404, "服务起来了却不应答请求"

        assert any("brew install ffmpeg" in ln for ln in lines), (
            "ffmpeg 不在 PATH 里，终端却没有出现带 `brew install ffmpeg` 的提示。"
            f"输出：\n{''.join(lines)}"
        )
    finally:
        _stop(proc)


def test_serve_says_nothing_about_ffmpeg_when_it_is_on_path(tmp_path):
    """ffmpeg 在 PATH：一个字都不该提它。

    这是上一条的另一半。少了这一条，一个「无论如何都打印那段提示」的实现
    也能让上一条全绿——那样的话「报了」与「没报」这两种状态测试根本分不出来。
    """
    proc, lines = _spawn_serve(_fake_ffmpeg_dir(tmp_path))
    try:
        line = _wait_for(proc, lines, URL_NEEDLE, SERVE_STARTUP_TIMEOUT)
        assert line is not None, f"没等到地址那一行。输出：\n{''.join(lines)}"
        # 先取快照再发请求：发过请求之后 stderr 会混进 http.server 的访问日志。
        startup = list(lines)
        port = int(URL_RE.search(line).group(1))
        assert _http_status(port) == 404

        offending = [ln for ln in startup if "ffmpeg" in ln]
        assert not offending, (
            "ffmpeg 就在 PATH 里，启动输出却提到了它：\n" + "".join(offending)
        )
    finally:
        _stop(proc)
