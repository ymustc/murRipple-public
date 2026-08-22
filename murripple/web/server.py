"""`murripple serve` —— 本机网页壳子的 HTTP 服务骨架。

只做四件事：起服务、绑对地址、端口让路、ffmpeg 前置检查。HTTP 端点、任务
目录、子进程编排、前端页面都不在这里。
"""

from __future__ import annotations

import errno
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# **只绑环回。** 这个服务会拿用户给的路径去 `subprocess` 调命令，绑 0.0.0.0
# 等于把它交给整个局域网。地址写在这里不是为了「可配置」——它没有开关，也
# 不该有。
HOST = "127.0.0.1"

DEFAULT_PORT = 8731

# 8731 被占住时往上找几个。找不到就报错而不是无限往上爬：连着二十个端口都
# 占满，多半是别的地方出了问题，那时候悄悄落在 8751 上比停下来更难查。
PORT_SEARCH_SPAN = 20

# ffmpeg 缺席时终端上的那句话。**这条消息只是提醒，不拦启动**——
# 见 `serve()` 里的注释。
FFMPEG_HINT = (
    "提醒：PATH 里没有 ffmpeg。分离音源与编码音频都要用它，缺了的话做歌会失败。\n"
    "  brew install ffmpeg"
)


def ffmpeg_missing_message() -> str | None:
    """ffmpeg 不在 `PATH` 里就返回那句提醒，在就返回 None。

    返回 None / 非 None 这个**结构**才是判据，不是消息里的某个子串——
    这里只有一条消息，断它的子串等于断一个常量。
    """
    if shutil.which("ffmpeg") is None:
        return FFMPEG_HINT
    return None


class ShellHandler(BaseHTTPRequestHandler):
    """骨架阶段的处理器：任何路径都回 404。

    真正的端点是后面几棒的事。这里留一个会应答的处理器，是因为「端口让路」
    那条判据要的是「换到的新端口**真的能服务请求**」——只断端口号的话，
    一个 bind 了却没挂处理器的实现也能通过。
    """

    server_version = "murRipple"

    def do_GET(self) -> None:  # noqa: N802  （BaseHTTPRequestHandler 的约定）
        body = "murRipple：这个地址还没有内容。\n".encode("utf-8")
        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_server(
    port: int = DEFAULT_PORT,
    handler: type[BaseHTTPRequestHandler] = ShellHandler,
) -> ThreadingHTTPServer:
    """绑一个能用的端口并返回服务对象（**不** `serve_forever`）。

    `handler` 默认还是上面那个骨架（任何路径都回 404）。真正的六个端点在
    `murripple/web/app.py` 里，由 `serve()` 惰性接进来——**本模块不 import 它**，
    否则 `app` → `server` → `app` 转成一个循环。

    从 `port` 往上找：本机壳子是用户随手起的东西，上一次没关干净、或者同时
    开了两个，都不该让它当场崩掉。

    只接 `EADDRINUSE` 一种错。权限不足、地址不存在之类的错照抛——那些换个
    端口也好不了，吞掉只会让人对着一个"莫名其妙起在 8745"的服务发愣。

    用 `ThreadingHTTPServer` 而不是 `HTTPServer`：单线程的话，一个连接没读完
    就会把整个服务堵死，而页面本来就要一边跑任务一边轮询进度。
    """
    last: OSError | None = None
    for candidate in range(port, port + PORT_SEARCH_SPAN):
        try:
            return ThreadingHTTPServer((HOST, candidate), handler)
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
            last = exc
    raise OSError(
        f"{HOST} 上 {port}–{port + PORT_SEARCH_SPAN - 1} 这 {PORT_SEARCH_SPAN} 个"
        f"端口全被占用了。先看看是不是有旧的 murripple serve 没关掉。"
    ) from last


def serve(port: int = DEFAULT_PORT) -> int:
    """起服务，一直跑到 Ctrl-C。

    **ffmpeg 缺席只提醒，不退出。** 启动阶段就 `sys.exit` 的话，用户连页面
    都打不开，那条 `brew install ffmpeg` 的建议他一个字也看不到。真正的硬拒
    在建任务的时候（后面棒的事）——那时候页面已经在他眼前，说得清楚。

    每一句都 `flush=True`：`serve_forever` 之后这个进程就不再退出了，而管道
    里的 stdout 是块缓冲的——不冲的话，`murripple serve | tee log` 或者任何
    把它当子进程跑的地方，在服务停掉之前一个字都看不到，包括最要紧的那行
    地址。
    """
    hint = ffmpeg_missing_message()
    if hint is not None:
        print(hint, flush=True)

    # **惰性 import。** 顶层 import 会让 `app` 与 `server` 互相引用；而且骨架
    # （`start_server` 的默认 handler）本身不该依赖端点那一层。
    from murripple.web.app import make_server

    httpd = make_server(port)
    # 打印**实际**拿到的端口，不是要的那个：让路之后还照着 8731 说，用户会
    # 打开一个没人在听的地址。
    print(f"知漪 murRipple：http://{HOST}:{httpd.server_port}", flush=True)
    print("在浏览器里打开上面这个地址。Ctrl-C 停止。", flush=True)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。", flush=True)
    finally:
        httpd.server_close()
    return 0
