"""六个 HTTP 端点：把页面、任务目录、子进程编排接成一条线。

spec 第四节那张表的全部落点。**自己不解析进度、不建目录、不起子进程**——那三件
事分别是 `progress.py`、`jobs.py`、`runner.py` 的，本模块只做路由、读写请求体、
和把状态摊成 JSON。

| 方法 | 路径 | 干什么 |
|---|---|---|
| `GET` | `/` | 单页（`static/index.html`，逐字节发出去） |
| `POST` | `/api/job` | 建任务；请求体是**原始字节**，文件名走 `X-Filename` |
| `POST` | `/api/job/<id>/lyrics` | 存歌词（纯文本请求体） |
| `POST` | `/api/job/<id>/start` | 起子进程；`?stage=ingest|run` |
| `GET` | `/api/job/<id>` | 状态：两级进度 + 分层日志 + error |
| `GET` | `/api/job/<id>/result` | 完成后返回 `dist/index.html` |

## 上传不走 multipart

`fetch(url, {method:"POST", body: file})` 直接发原始字节，这里 `read(Content-Length)`
写盘。手写 multipart 解析是个坑，而 `cgi` 模块在 3.13 已被移除——避开整类问题。

**代价说在明处**：请求体是**整份读进内存**再交给 `jobs.create_job(content: bytes)`
的。一个一小时的视频会在建任务的那一瞬间吃掉相应的内存。这是 W1 的已知前提，不是
一条性质：要改成边读边写，得先给 `jobs.create_job` 换一个接口，而那是「管线之外的
既有模块只读」这条约束的另一侧。

中文文件名走**百分号编码**（页面 `encodeURIComponent`，这里 `unquote`）：HTTP 头
是 latin-1 的，`X-Filename: 我的歌.mp3` 原样发出去在浏览器那一侧就编不出来。

## 消毒只有一处，而这一层要证明自己**调了**它

文件名的消毒全在 `jobs.safe_stem()`（那个模块的 docstring 讲了为什么只有一处）。
本模块**不加第二道兜底**——加了的话，删掉任何一处都还有另一处兜着，变异检验会全
绿，于是没人知道哪一处在挡事。

但「消毒函数是安全的」与「端点调了消毒函数」是两件事，中间隔着这一层。守着后者的
是 `tests/test_web_page.py::test_a_hostile_filename_cannot_escape_songs_on_the_*`：
它们发一个 `X-Filename: ../../escaped.mp3`，**断盘上那个绝对路径**，不断状态码。

## 一次跑一个，不做队列

spec 第七节明写不做队列/并发/多任务。任务表是一个进程内的 dict（`AppState.entries`），
服务一关就没了。

**这里要说清它到底成不成立**（2026-08-14 收口评审 I2 订正）。机制没错：断点续跑靠的
是 `songs/` 目录本身还在（`run` 每步先看产物在不在），不是靠我们记的这份账。但**网页
这一层够不到那个目录**——

- `job_id` 是 `secrets.token_hex(8)`，只活在 `AppState.entries` 里；页面只把它存在
  `boot()` 的一个闭包变量上。**没有 localStorage、没有 URL 片段、没有列任务的端点。**
- 所以：刷新页面 → 那个 `job_id` 没了，重选文件会建一个**新时间戳的新目录**，"每步先
  看产物在不在"对它完全不适用，Demucs 从头再跑一小时；重启服务 → 老 `job_id` 查询 404。

**真正成立的是这一条**：目录还在，所以**拿命令行对同一个目录跑 `murripple run`
确实会接着跑**。W1 的网页壳子不支持跨页面刷新／跨进程续跑，README 那句「服务开着的
时候别关浏览器标签——进度都在那一页上」是准确的。

同一个 `job_id` 二次 `start` 不做去重，理由同 `runner.start`。

## 唯一一处 import 到 `murripple/` 里面的东西

`DRAFT_FILENAME`。网页这一层的立身之本是**不依赖分析管线**（跑歌靠 `subprocess` 调
`murripple` 命令，自己只用标准库），而这一条是那条规矩的一个例外，理由要说清楚：

- 拿到的只是一个**文件名常量**，不是任何计算。抄一份字面量进来的话，草稿改个名字，
  网页这边会安静地永远读不到它——两处各写各的，坏起来没有任何提示。
- `murripple.ingest.transcribe` 与它上游的 `murripple.align`、`murripple.ingest`
  的 `__init__` **在 import 阶段只碰标准库**，所以 `murripple serve` 不会因此把
  numpy／librosa／torch 拉起来。

**这是一个前提，不是一条性质**：谁哪天往 `align.py` 或 `transcribe.py` 的顶层加一句
`import numpy`，隔离就没了。守卫是
`tests/test_transcribe.py::test_serving_the_page_still_does_not_drag_the_pipeline_in`。
"""

from __future__ import annotations

import json
import secrets
import shutil
import threading
from dataclasses import dataclass, field
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from murripple.ingest.transcribe import DRAFT_FILENAME
from murripple.web import jobs, progress, runner, server

#: 单页。`GET /` 逐字节发它——**不在 Python 里拼一份**：拼的话
#: `static/index.html` 上那些守卫（零外链、查看原因的入口、歌词必填）全白守了。
PAGE = Path(__file__).resolve().parent / "static" / "index.html"

#: 主日志给页面留几行（spec 第五节「小字滚动区：最近 20 行」）。
LOG_TAIL_LINES = 20

#: 还没点开始。`runner` 那四个状态之外的第五种，只属于这一层。
IDLE = "idle"

#: 主日志里哪些行算「降级」——页面据此在旁边挂「查看原因 ▾」。
#:
#: **按内容认，跟 `progress.classify` 同一个路数**，每条标着 `cli.py` 的出处。
#: 认宽一点没关系（多挂一个入口，点开是紧邻的详细区），认漏了才要命：那正是
#: 「主日志上一句孤零零的『退回常规对齐。』」的由来。
DEGRADED_MARKERS = (
    "跳过",  # cli.py:300 分离音源：跳过（…）／703 分析 跳过（…）
    "降级",  # cli.py:389 降级为无歌词，继续。
    "退回",  # cli.py:436 退回常规对齐。
    "未找到",  # cli.py:368 未找到 lyrics.txt，跳过歌词层。
    "未对上",  # cli.py:384 以下 n 行未对上…
    "警告",  # cli.py:339 / 821（产物超 15 MB 那句）
    "失败",  # cli.py:311 分离失败／487 整理失败／716 打包失败
    "有问题",  # cli.py:409 / 415 overrides.json 有问题：
    "看不明白",  # cli.py:451 素材看不明白：
    "忽略（用不上）",  # scan.py:151
    "一行都没认出来",  # cli.py:472
    "太短",  # cli.py:336
    "听不了：",  # cli.py::transcribe，WhisperX 装不上／加载不了
    "一个字都没听出来",  # cli.py::transcribe，WhisperX 跑了但一个字都没转出来
)


def is_degraded(line: str) -> bool:
    """这一行是不是一句降级／退回／跳过／失败的话。"""
    return any(marker in line for marker in DEGRADED_MARKERS)


@dataclass
class Entry:
    """一个任务此刻的全部：盘上的目录 + （可能还没起的）子进程。"""

    job: jobs.Job
    title: str
    run: runner.Run | None = None
    stage: str | None = None


@dataclass
class AppState:
    """服务的全部可变状态。

    `songs_root` 与 `command` 都是**测试注入点**，写在调用现场——没有环境变量、
    没有全局开关（CONSTRAINTS 第 8 条：逃生口藏进环境变量就等于没人看得见它被
    打开过）。`songs_root` 尤其：写死的话，「恶意文件名逃不出 songs/」那条判据
    根本没法在 `tmp_path` 里测。
    """

    songs_root: Path = jobs.SONGS_ROOT
    command: tuple[str, ...] = runner.MURRIPPLE_COMMAND
    entries: dict[str, Entry] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


def _step(step: progress.Step | None) -> dict | None:
    if step is None:
        return None
    return {"step": step.current, "total": step.total, "name": step.text}


def detail_lines(prog: progress.Progress, main_omitted: int) -> list[str]:
    """详细区里该有哪些行：**第三方噪声 + 被滚动区挤出去的那几行主日志**。

    按 `log` 的原顺序走一遍，所以两块合起来仍然逐行还原得回 `log`——
    `progress.Progress` 那条「分错只是位置不对，不会丢」的结构事实，到这一层才
    真正接上（在这之前，主日志超过 20 行时 payload 里是真的少了几行）。

    `main_omitted` 是**前面**被挤掉的行数，跟 `state_payload` 里那个 `[-20:]`
    是同一件事的两半：留下最近的 20 行，最早的 n 行改到这里来。
    """
    out: list[str] = []
    seen_main = 0
    for line, layer in zip(prog.log, prog.layers):
        if layer != progress.MAIN:
            out.append(line)
            continue
        seen_main += 1
        if seen_main <= main_omitted:
            out.append(line)
    return out


def state_payload(job_id: str, entry: Entry) -> dict:
    """一个任务摊成 JSON。页面轮询拿到的就是它。

    **`main` 截尾 20 条，`detail` 不截。** 「最近 20 行」是滚动区的判据；详细区
    存在的全部理由是「一行都不能丢」，给它截尾等于把刚防住的东西悄悄放回来。

    **被挤出滚动区的那几行主日志也进详细区**（收口评审 I1）。原先它们哪儿都不
    在：payload 没有 `log` 字段，页面只会说一句「前面还有 n 行」，而那 n 行不在
    任何一个响应里——一首对得糟的歌，`cli.py:384-386` 那一串「未对上」的歌词
    每行占一格，开头的 `[1/5] 分离音源：跳过（…）` 就这么无声无息地没了。做防护
    的那个动作（截尾）伤到了它要保护的东西（降级必须大声说）。
    """
    song_dir = entry.job.song_dir
    run = entry.run
    if run is None:
        snapshot = runner.RunState(stage=entry.stage or entry.job.route, status=IDLE)
    else:
        snapshot = run.snapshot()

    main_all = [
        {"text": line, "degraded": is_degraded(line)} for line in snapshot.progress.main
    ]
    main_omitted = max(0, len(main_all) - LOG_TAIL_LINES)
    detail = detail_lines(snapshot.progress, main_omitted)

    # 机器认出来的字只在那一步跑完的那一刻交回去：页面要拿它填进校对框，而别的
    # 时候带上只会在用户正打字时把他的输入盖掉。
    #
    # **两档共用这一个字段、落进同一个校对框**：`ingest` 交的是 OCR 写进
    # `lyrics.txt` 的那份，`transcribe` 交的是 `lyrics.draft.txt`。听写那一步
    # **写不到 `lyrics.txt`**（`murripple/ingest/transcribe.py` 的硬约束），草稿
    # 要变成歌词，只能经过用户在框里点的那一下「改好了，继续」。
    lyrics = None
    if snapshot.status == runner.DONE:
        if snapshot.stage == runner.STAGE_INGEST:
            candidates = [song_dir / "lyrics.txt"]
        elif snapshot.stage == runner.STAGE_TRANSCRIBE:
            # 草稿排在前面；`lyrics.txt` 是兜底：听写那一档走到「已经有
            # lyrics.txt 了，不听写」那条跳过分支时盘上根本没有草稿，这时候把
            # 现成的歌词填进框里，比交一个空框诚实。
            candidates = [song_dir / DRAFT_FILENAME, song_dir / "lyrics.txt"]
        else:
            candidates = []
        for path in candidates:
            if path.exists():
                lyrics = path.read_text(encoding="utf-8", errors="replace")
                break

    return {
        "job_id": job_id,
        "route": entry.job.route,
        "song_dir": str(song_dir),
        "stage": snapshot.stage,
        "status": snapshot.status,
        "outer": _step(snapshot.progress.outer),
        "inner": _step(snapshot.progress.inner),
        # 编号之外的那一段（取回）。页面拿它把大标题从「准备中…」换掉——那几
        # 分钟里它不在准备，它在下工具链和素材。**跟 `outer` 是两件事**，理由
        # 写在 `progress.Progress` 的 docstring 里。
        "phase": snapshot.progress.phase,
        "main": main_all[-LOG_TAIL_LINES:],
        "main_omitted": main_omitted,
        "detail": detail,
        "error": snapshot.error,
        "returncode": snapshot.returncode,
        "result_ready": (song_dir / "dist" / "index.html").exists(),
        "lyrics": lyrics,
    }


class AppHandler(server.ShellHandler):
    """六个端点。认不出来的路径落回骨架那个 404。"""

    # ---------------------------------------------------------------- 应答工具

    @property
    def state(self) -> AppState:
        return self.server.state  # type: ignore[attr-defined]

    def log_request(self, *args, **kwargs) -> None:  # noqa: D102
        # 页面每 700 毫秒轮询一次，逐条打访问日志的话，终端上那行地址几秒钟就被
        # 冲走了——而那行地址是用户唯一需要看见的东西。出错的日志（`log_error`）
        # 照打。
        pass

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body)

    def _fail(self, status: int, message: str) -> None:
        """出错也说人话。**原文照送**，不包一层「处理失败」。"""
        self._json(status, {"error": message})

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length > 0 else b""

    def _entry(self, job_id: str) -> Entry | None:
        with self.state.lock:
            return self.state.entries.get(job_id)

    # ---------------------------------------------------------------- 路由

    def do_GET(self) -> None:  # noqa: N802
        parts = urlparse(self.path)
        path = parts.path
        try:
            if path in ("/", "/index.html"):
                return self._send(
                    200, "text/html; charset=utf-8", PAGE.read_bytes()
                )
            if path.startswith("/api/job/"):
                rest = path[len("/api/job/") :]
                if "/" not in rest:
                    return self._get_state(rest)
                job_id, _, tail = rest.partition("/")
                if tail == "result":
                    return self._get_result(job_id)
            # 认不出来的路径：落回骨架那句「这个地址还没有内容」。
            return super().do_GET()
        except Exception as exc:  # noqa: BLE001
            # 处理器里抛出去的话，用户那一侧只会看到连接断了。
            return self._fail(500, f"服务内部出错：{exc!r}")

    def do_POST(self) -> None:  # noqa: N802
        parts = urlparse(self.path)
        path = parts.path
        query = parse_qs(parts.query)
        try:
            if path == "/api/job":
                return self._create_job()
            # 链接那条路**另开一个端点**，不塞进 `/api/job`：那条路的请求体是
            # 素材的原始字节，靠 `X-Filename` 认路；两件事挤在一个端点上，
            # 「这次到底是上传还是贴链接」就成了要靠猜的东西。
            if path == "/api/job-from-url":
                return self._create_job_from_url()
            if path.startswith("/api/job/"):
                job_id, _, tail = path[len("/api/job/") :].partition("/")
                if tail == "lyrics":
                    return self._put_lyrics(job_id)
                if tail == "start":
                    return self._start(job_id, query.get("stage", [None])[0])
            return self._fail(404, f"没有 {path} 这个端点。")
        except Exception as exc:  # noqa: BLE001
            return self._fail(500, f"服务内部出错：{exc!r}")

    # ---------------------------------------------------------------- 建任务

    def _create_job(self) -> None:
        filename = unquote(self.headers.get("X-Filename") or "")
        content = self._body()

        # **ffmpeg 的硬拒在动盘之前。** Task 1 只做了终端那一半（启动时提醒一句，
        # 不拦启动，好让用户至少打得开页面）；另一半在这里：分离音源与编码音频都
        # 要 ffmpeg，缺了的话跑到第 4 步才炸，前面几分钟全白等。
        hint = server.ffmpeg_missing_message()
        if hint is not None:
            return self._fail(400, hint)

        if not filename.strip():
            return self._fail(
                400, "这次上传没带文件名（X-Filename），认不出该走哪条路。"
            )
        if not content:
            return self._fail(400, f"{filename} 是个空文件，做不成歌。")

        try:
            # **消毒全在 `jobs.create_job` 里面**，这里不加第二道兜底：加了的话
            # 删掉任何一处都还有另一处兜着，变异检验会全绿。
            job = jobs.create_job(filename, content, songs_root=self.state.songs_root)
        except jobs.JobError as exc:
            return self._fail(400, str(exc))
        except OSError as exc:
            return self._fail(500, f"素材写不进去：{exc}")

        job_id = secrets.token_hex(8)
        entry = Entry(job=job, title=jobs.safe_stem(filename))
        with self.state.lock:
            self.state.entries[job_id] = entry
        self._json(
            201,
            {
                "job_id": job_id,
                "route": job.route,
                "title": entry.title,
                "song_dir": str(job.song_dir),
                "needs_lyrics": job.route == jobs.ROUTE_RUN,
            },
        )

    def _create_job_from_url(self) -> None:
        """贴一条链接进来，走到跟传文件同一个地方。

        **这里不取回**。取回是 `murripple ingest --url` 那个子进程干的事——做成
        `ingest` 的一部分而不是这一层的新动作，取回的全部输出（我们的 `[取回]`
        行 + yt-dlp 原文）才顺着已有的进度管子实时到页面。在这里同步取回的话，
        这一个 POST 会挂住几分钟，页面上一个字都没有——而那正是判据里
        「不知情的人不会以为它卡死了」要防的。
        """
        # ffmpeg 的硬拒同样在动盘之前：取回来还是要抽轨、编码。
        hint = server.ffmpeg_missing_message()
        if hint is not None:
            return self._fail(400, hint)

        url = self._body().decode("utf-8", errors="replace").strip()
        try:
            job = jobs.create_job_from_url(url, songs_root=self.state.songs_root)
        except jobs.JobError as exc:
            return self._fail(400, str(exc))
        except OSError as exc:
            return self._fail(500, f"建不了任务目录：{exc}")

        job_id = secrets.token_hex(8)
        # 曲名这会儿还不知道——它在视频的标题里，要等 yt-dlp 把 `%(title)s`
        # 落到 `_in/` 才认得出来（`_start` 里那一段）。**空着比编一个强**。
        entry = Entry(job=job, title="")
        with self.state.lock:
            self.state.entries[job_id] = entry
        self._json(
            201,
            {
                "job_id": job_id,
                "route": job.route,
                "title": entry.title,
                "song_dir": str(job.song_dir),
                "needs_lyrics": False,
            },
        )

    # ---------------------------------------------------------------- 歌词

    def _put_lyrics(self, job_id: str) -> None:
        entry = self._entry(job_id)
        if entry is None:
            return self._fail(404, f"没有 {job_id} 这个任务。")
        text = self._body().decode("utf-8", errors="replace")
        if text.strip() == "":
            # 空白歌词不许落盘：`cli.py::run` 只查 `exists()`，一份全是空格的
            # `lyrics.txt` 骗得过它，然后一路降级到没有歌词层——而用户以为自己
            # 给过了。
            return self._fail(400, "歌词是空的。一行一句地贴进来，或者传一份 lyrics.txt。")
        # 原文一字不改地写下去；浏览器 textarea 发来的 CRLF 由下游的 `align.py`
        # 吃掉（见 `jobs.py` 模块 docstring）。
        (entry.job.song_dir / "lyrics.txt").write_text(text, encoding="utf-8")
        self._json(200, {"ok": True, "lines": len(text.splitlines())})

    # ---------------------------------------------------------------- 起子进程

    def _start(self, job_id: str, stage: str | None) -> None:
        entry = self._entry(job_id)
        if entry is None:
            return self._fail(404, f"没有 {job_id} 这个任务。")

        stage = stage or entry.job.route
        if stage not in runner.STAGES:
            return self._fail(
                400,
                f"不认识的 stage {stage!r}，只有 {'、'.join(runner.STAGES)}。",
            )

        # 链接那条路建任务时还不知道曲名（它在视频标题里）。取回之后 `_in/` 里
        # 那份音频的文件名就是它——调研列的三样价值之一「自动命名编号」落在这
        # 儿。认不出来就仍旧空着，`pack` 退回用 build 时记下的目录名。
        if stage == runner.STAGE_RUN and entry.job.url and not entry.title:
            entry.title = jobs.title_from_in_dir(entry.job.song_dir) or ""

        try:
            run = runner.start(
                entry.job.song_dir,
                stage,
                title=entry.title if stage == runner.STAGE_RUN else None,
                url=entry.job.url,
                command=self.state.command,
            )
        except OSError as exc:
            # `runner.start` 在命令压根起不来时**异常照抛**（它有意留给这一层）。
            # 那时候一行输出都还没有，只能由这里说一句人话。
            return self._fail(
                500,
                f"起不来 murripple 命令：{exc}\n"
                f"  这个网页壳子是靠 `murripple` 命令做歌的。"
                f"确认一下它跟 `murripple serve` 装在同一个环境里。",
            )

        entry.run = run
        entry.stage = stage
        self._json(200, state_payload(job_id, entry))

    # ---------------------------------------------------------------- 查状态

    def _get_state(self, job_id: str) -> None:
        entry = self._entry(job_id)
        if entry is None:
            return self._fail(404, f"没有 {job_id} 这个任务。")
        self._json(200, state_payload(job_id, entry))

    # ---------------------------------------------------------------- 取产物

    def _get_result(self, job_id: str) -> None:
        entry = self._entry(job_id)
        if entry is None:
            return self._fail(404, f"没有 {job_id} 这个任务。")
        product = entry.job.song_dir / "dist" / "index.html"
        if not product.exists():
            return self._fail(
                404,
                f"还没有产物：{product.parent.parent.name}/dist/index.html 不在盘上。"
                f"等这一步跑完再来取。",
            )
        # 产物是自带全部数据的单文件页面（十几 MB），边读边发，不整份读进内存。
        size = product.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with product.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile)


def make_server(
    port: int = server.DEFAULT_PORT, state: AppState | None = None
) -> ThreadingHTTPServer:
    """建一个挂着六个端点的服务（**不** `serve_forever`）。

    端口让路、只绑环回都在 `server.start_server` 里，这里不重做一遍。
    `port=0` 时内核挑一个空闲端口——测试用的就是它，所以并行跑也不会撞。
    """
    httpd = server.start_server(port, AppHandler)
    httpd.state = state if state is not None else AppState()  # type: ignore[attr-defined]
    return httpd


__all__ = [
    "DEGRADED_MARKERS",
    "IDLE",
    "LOG_TAIL_LINES",
    "PAGE",
    "AppHandler",
    "AppState",
    "Entry",
    "detail_lines",
    "is_degraded",
    "make_server",
    "state_payload",
]
