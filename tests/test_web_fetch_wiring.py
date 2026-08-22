"""取回那一层接进网页壳子：分层、命令、建任务、版权提醒。

**这个文件不改既有测试的任何一条。** `tests/test_web_progress.py::OUR_SHAPES`
只钉 `cli.py` 与 `scan.py` 两个源码文件，而 `[取回]` 那些话来自
`murripple/fetch.py`——所以那张表的同款守卫在这里另起一份，钉 `fetch.py`。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from murripple import fetch
from murripple.web import app, jobs, progress, runner

REPO_ROOT = Path(__file__).resolve().parent.parent
FETCH_SOURCE = (REPO_ROOT / "murripple" / "fetch.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# ① 分层：我们的话进主日志，yt-dlp 的原文进详细区
# --------------------------------------------------------------------------

#: (源码里那段字面量, 真跑时长成什么样)。
#:
#: 第二项**照着 `fetch.py` 抄**，不照印象编；第一项逼着这张表跟源码一起变老
#: ——与 `test_web_progress.py::OUR_SHAPES` 同一个路数。
#: 下面这些样例行里的曲名 `锈色电台` 是**自造的**，跟仓里任何一首歌无关
#: （自造语料见 `renderer/test/fixtures/synthetic-lyric-rows.json`）。
#: 2026-08-16 从一首真歌的名字换过来的：那四首是别人的作品，公开仓里出现
#: 「我们处理过那一首」的记录，与本项目一贯的立场相反。**这里要的只是
#: 「一个会出现在 `_in/` 里的中文文件名」，换成什么字断言一个都不变。**
FETCH_SHAPES = [
    ('"⚠ 你对自己处理和分发的素材负责。', "[取回] ⚠ 你对自己处理和分发的素材负责。"),
    ('f"第 {tier} 级：{label}"', "[取回] 第 1 级：运行时拉取的最新 yt-dlp（uv 临时环境，不进 pyproject/uv.lock，不锁版本）"),
    ('f"$ {shlex.join(argv)}"', "[取回]   $ uv run --with 'yt-dlp[default,deno]' --no-project -- yt-dlp -f 'bestaudio[ext=m4a]'"),
    ('f"⚠ 第 {tier} 级没成，降级到第 {nxt[0]} 级。原因是："', "[取回] ⚠ 第 1 级没成，降级到第 2 级。原因是："),
    ('"这一步有一阵子没有任何输出了。多半是在等网络——第一次还要拉一个约 "', "[取回] 这一步有一阵子没有任何输出了。多半是在等网络——第一次还要拉一个约 36.7 MB 的运行时。不是卡死了，再等等。"),
    ('f"取回成功（第 {tier} 级）：{got.name}"', "[取回] 取回成功（第 1 级）：锈色电台.m4a"),
    ('f"⚠ 前 {len(_TIERS)} 级都不成，落到第 {len(_TIERS) + 1} 级：交给人。"', "[取回] ⚠ 前 2 级都不成，落到第 3 级：交给人。"),
    ('f"第 {attempt.tier} 级（{attempt.label}）失败，原因是："', "[取回] 第 2 级（环境里已装的 yt-dlp）失败，原因是："),
    ('"取回来的文件留在 `_in/` 里，`murripple ingest` 会照常接手。"', "[取回] 取回来的文件留在 `_in/` 里，`murripple ingest` 会照常接手。"),
]


def test_夹具表不是空的():
    """参数集由数据推导时 pytest 默认给绿 + 跳过。这是那条独立守卫。"""
    assert len(FETCH_SHAPES) >= 9


@pytest.mark.parametrize("fragment,sample", FETCH_SHAPES)
def test_每一条都是_fetch_此刻真会打的形状(fragment, sample):
    assert fragment in FETCH_SOURCE, (
        f"`murripple/fetch.py` 里已经没有 {fragment!r} 了——这张表停在旧版本上，"
        "它认的那个形状可能已经不是取回那一层打出来的了。重新抄一遍。"
    )


@pytest.mark.parametrize("fragment,sample", FETCH_SHAPES)
def test_取回自己打的每一行都进主日志(fragment, sample):
    """`classify()` **认不出来就归详细区**（那是它刻意选的默认）。

    不给 `[取回]` 立规矩的话，版权提醒、三级报名、降级原因**全部被折叠**——
    正是 W1 那次「日志分层把一条降级埋了」的同一个形状，而这一次被埋的
    是这条路存在的前提。
    """
    assert progress.classify(sample) == progress.MAIN, (
        f"{sample!r} 是取回那一层自己打的（源码：{fragment}），却归了详细区"
    )


#: yt-dlp 自己的原文。这些**该**留在详细区——普通用户不需要看
#: `[download]  32.0% of 46.91KiB`，而分层存在的全部理由就是把这类噪声收起来。
#: 逐字抄自 `tests/fixtures/yt-dlp/`（出处见那个目录的 provenance）。
YTDLP_NOISE = [
    "[generic] Extracting URL: http://127.0.0.1:8931/x.m4a",
    "[generic] 知漪测试音: Downloading webpage",
    "[info] 知漪测试音: Downloading 1 format(s): mp4a-latm",
    "[download]  32.0% of   46.91KiB at  Unknown B/s ETA Unknown",
    "[download] 100% of   46.91KiB in 00:00:00 at 31.11MiB/s",
]


#: uv 第一次跑第 1 级时**自己**打的那几行（走 stderr，被 `_run` 并进来）。
#: 逐字节抄自一次真的冷缓存运行，存档在 `tests/fixtures/yt-dlp/uv-cold-start.stderr`。
UV_COLD_START = (
    (REPO_ROOT / "tests" / "fixtures" / "yt-dlp" / "uv-cold-start.stderr")
    .read_text(encoding="utf-8")
    .splitlines()
)


def test_冷启动抄件不是空的():
    assert len(UV_COLD_START) == 7, f"抄件从 7 行变成了 {len(UV_COLD_START)} 行"


@pytest.mark.parametrize("line", UV_COLD_START)
def test_第一次拉运行时那几行必须进主日志(line):
    """★ 这一条是真跑推翻我自己的假设之后补的。

    原以为第 1 级拉那 36.7 MB 运行时的时候"一行输出都没有"，于是造了个静默
    看门狗去补话。**冷缓存真跑一次才看见：uv 自己会把每一个包报出来**
    （`Downloading deno (36.7MiB)` …），而它走 stderr、被 `_run` 并进了同一
    个流——所以"下运行时这件事看得见"根本不用我们说，它本来就在。

    **但它默认会被折叠。** `classify()` 认不出来就归详细区，于是这几行——
    恰恰是"它没卡死，在下东西"的**唯一证据**——会落进折叠区，而主日志停在
    `$ uv run …` 上一动不动几分钟。那正是 W1「日志分层把该看见的埋了」的同
    一个形状，只是这次埋的是好消息。
    """
    assert progress.classify(line) == progress.MAIN, (
        f"{line!r} 是「第一次要下 36.7 MB 运行时」这件事唯一看得见的证据，"
        "却被折叠进了详细区——主日志会停在 `$ uv run …` 上好几分钟不动"
    )


@pytest.mark.parametrize("line", YTDLP_NOISE)
def test_yt_dlp_的原文留在详细区(line):
    """分层要是把 `[取回]` 认宽成"所有中括号开头的行"，这一条就红。"""
    assert progress.classify(line) == progress.DETAIL, (
        f"{line!r} 是 yt-dlp 的原文，却跳到主日志上去了"
    )


def test_降级那几行会被挂上查看原因的入口():
    """页面靠 `app.is_degraded` 决定哪一行旁边挂「查看原因 ▾」。

    降级说明进了主日志还不够——挂不上入口的话，原因就在紧邻的详细区里
    而没有任何人指过去。
    """
    assert app.is_degraded("[取回] ⚠ 第 1 级没成，降级到第 2 级。原因是：")
    assert app.is_degraded("[取回] 第 2 级（环境里已装的 yt-dlp）失败，原因是：")
    # 顺利跑完那几行不该挂——到处都是入口等于没有入口。
    assert not app.is_degraded("[取回] 取回成功（第 1 级）：锈色电台.m4a")


# --------------------------------------------------------------------------
# ② 命令：网页那一路靠 `murripple ingest <dir> --url <URL>`
# --------------------------------------------------------------------------


def test_带链接时命令里有_url(tmp_path):
    argv = runner.command_for(
        runner.STAGE_INGEST, tmp_path / "歌", url="https://example.invalid/v"
    )
    assert argv[-2:] == ("--url", "https://example.invalid/v")


def test_不带链接时命令一个字节没变(tmp_path):
    """老路不许被这一棒动到。"""
    assert runner.command_for(runner.STAGE_INGEST, tmp_path / "歌") == (
        *runner.MURRIPPLE_COMMAND,
        "ingest",
        str(tmp_path / "歌"),
    )
    assert "--url" not in runner.command_for(runner.STAGE_RUN, tmp_path / "歌")


# --------------------------------------------------------------------------
# ③ 建任务：链接那条路不落素材，`_in/` 是空的等着取回来填
# --------------------------------------------------------------------------


def test_链接建出来的任务走_ingest_那条路(tmp_path):
    job = jobs.create_job_from_url("https://example.invalid/v", songs_root=tmp_path)

    assert job.route == jobs.ROUTE_INGEST
    assert job.url == "https://example.invalid/v"
    assert job.song_dir.parent == tmp_path
    assert job.media_path is None, "链接这条路这会儿还没有素材，不该假装有"
    assert job.song_dir.is_dir()


def test_链接建出来的目录仍然在_songs_底下(tmp_path):
    """链接是用户可控的数据，跟文件名一样。"""
    job = jobs.create_job_from_url(
        "https://evil.invalid/../../../../etc/passwd", songs_root=tmp_path
    )
    assert tmp_path in job.song_dir.parents
    assert job.song_dir.parent == tmp_path


# --------------------------------------------------------------------------
# ④ 取回之后，曲名从 `_in/` 里那份音频认出来
# --------------------------------------------------------------------------


def test_曲名从取回来的音频认出来(tmp_path):
    """调研列的三样价值之一就是"自动命名编号"。

    认不出来的话，产物标题会是 `web-20260814-…-来自链接`——一个用户从没打过
    的字符串，印在成品的标题页上。
    """
    song = tmp_path / "web-20260814-120000-来自链接"
    (song / "_in").mkdir(parents=True)
    (song / "_in" / "锈色电台.m4a").write_bytes(b"x")
    (song / "_in" / "锈色电台.mkv").write_bytes(b"x")

    assert jobs.title_from_in_dir(song) == "锈色电台"


def test_没有音频时不硬编一个曲名(tmp_path):
    song = tmp_path / "空的"
    (song / "_in").mkdir(parents=True)
    assert jobs.title_from_in_dir(song) is None
    assert jobs.title_from_in_dir(tmp_path / "根本不存在") is None


def test_只有视频时也不当成曲名(tmp_path):
    """★ 这一条专挑一个**分得开**的配置。

    上面那条"锈色电台.m4a + 锈色电台.mkv"分不开：`m4a` 字典序在 `mkv` 前面，
    **把按扩展名筛的那一段整个删掉，`sorted()[0]` 拿到的还是同一个文件、
    答案一模一样**。夹具换了档，被观测的那个量没跟着换（`MGMT.md` 第七节）。

    只放一份 `.mkv` 才验得到那段筛选：筛了返回 `None`，不筛返回 `锈色电台`。
    """
    song = tmp_path / "只有视频"
    (song / "_in").mkdir(parents=True)
    (song / "_in" / "锈色电台.mkv").write_bytes(b"x")

    assert jobs.title_from_in_dir(song) is None


def test_两份音频时不猜是哪一首(tmp_path):
    song = tmp_path / "两份"
    (song / "_in").mkdir(parents=True)
    (song / "_in" / "甲.m4a").write_bytes(b"x")
    (song / "_in" / "乙.m4a").write_bytes(b"x")

    assert jobs.title_from_in_dir(song) is None


# --------------------------------------------------------------------------
# ⑤ 版权提醒：页面上那句与 `fetch.py` 里那句不许各写各的
# --------------------------------------------------------------------------


def test_页面上的版权提醒与取回层是同一句话():
    """主日志只留最近 20 行，版权提醒是**第一行**——一次长 ingest 之后它必然
    被挤出可视区。所以页面上另有一句常驻的。

    但两处不许各写各的：这条守卫钉住它们共有的那个特征串，且那个串**此刻仍在
    `fetch.py` 里**。哪天版权措辞变了而页面没跟上，这里会红。
    """
    # 锚点 2026-08-15 从 `murripple-demo` 换成这一句：前者是**我们自己的仓库名**，
    # 对拿到这个工具的人毫无意义（于淼指出）。新锚点是这段话真正承重的那一句，
    # 换掉它就等于换掉了免责声明本身——正是这条守卫该抓的。
    marker = "你对自己处理和分发的素材负责"
    assert marker in fetch.COPYRIGHT_NOTICE
    assert marker in FETCH_SOURCE

    html = app.PAGE.read_text(encoding="utf-8")
    assert marker in html, (
        "页面上没有那句版权提醒。它不能只活在终端里——网页用户看不到终端。"
    )


# --------------------------------------------------------------------------
# ⑥ 端点：贴一条链接进去，跟传文件走到同一个地方
# --------------------------------------------------------------------------

#: 替身 CLI：把自己收到的 argv 原样记下来，再打两行像样的输出。
#: **不 import 管线**——网页那一层的立身之本就是不依赖分析管线。
_RECORDER = """\
import json, sys
record, argv = sys.argv[1], sys.argv[2:]
with open(record, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(argv, ensure_ascii=False) + "\\n")
print("[1/2] 取回")
print("[取回] 取回成功（第 1 级）：锈色电台.m4a")
"""


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """一个真起着的服务 + 一个记录 argv 的替身 CLI。"""
    import http.client
    import json
    import sys
    import threading

    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    ffmpeg = bin_dir / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    ffmpeg.chmod(0o755)
    # 这台机器上装没装 ffmpeg 是机器的性质，钉死它，两种机器上验的才是同一件事。
    monkeypatch.setenv("PATH", str(bin_dir))

    script = tmp_path / "recorder.py"
    script.write_text(_RECORDER, encoding="utf-8")
    record = tmp_path / "argv.jsonl"

    songs_root = tmp_path / "songs"
    songs_root.mkdir()
    state = app.AppState(
        songs_root=songs_root, command=(sys.executable, str(script), str(record))
    )
    httpd = app.make_server(0, state)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    class Wired:
        songs_root = None
        def __init__(self):
            self.songs_root = songs_root

        def post(self, path, body=b"", headers=None):
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
            conn.request("POST", path, body=body, headers=headers or {})
            resp = conn.getresponse()
            payload = json.loads(resp.read().decode("utf-8"))
            conn.close()
            return resp.status, payload

        def argv(self, expected=1, timeout=20.0):
            """等到替身 CLI 真的跑起来并记下第 `expected` 笔为止。

            `runner.start()` 是**立刻返回**的（子进程在后台线程里读），不等
            的话这里读到的是一个还没被写过的文件——而那看起来跟"命令根本没
            带 --url"一模一样。
            """
            import time

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                lines = (
                    record.read_text(encoding="utf-8").splitlines()
                    if record.exists()
                    else []
                )
                if len(lines) >= expected:
                    return [json.loads(ln) for ln in lines]
                time.sleep(0.02)
            raise AssertionError(
                f"{timeout} 秒了替身 CLI 还没记下第 {expected} 笔 argv"
                f"（现在有 {len(lines)} 笔）"
            )

    yield Wired()
    httpd.shutdown()
    thread.join(timeout=10)
    httpd.server_close()


URL = "https://example.invalid/watch?v=abc"


def test_贴一条链接就能建出任务(wired):
    status, payload = wired.post("/api/job-from-url", URL.encode("utf-8"))

    assert status == 201, payload
    assert payload["route"] == "ingest"
    song_dir = Path(payload["song_dir"])
    assert song_dir.is_dir()
    assert (song_dir / "_in").is_dir()
    assert list((song_dir / "_in").iterdir()) == [], "还没取回来呢，`_in/` 不该有东西"


def test_没有_ffmpeg_时链接这条路也在动盘之前就拒(wired, tmp_path, monkeypatch):
    """传文件那条路有这条守卫（`test_web_page.py`），链接这条路是新开的一个
    端点——**不补一条的话，它就是那条守卫覆盖不到的一个口子**。

    取回来了照样要抽轨、编码，缺 ffmpeg 一样跑不完；先建了目录再炸，
    `songs/` 下就留一个空壳。
    """
    empty = tmp_path / "no-ffmpeg"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    before = sorted(p.name for p in wired.songs_root.iterdir())

    status, payload = wired.post("/api/job-from-url", URL.encode("utf-8"))

    assert status == 400
    assert "ffmpeg" in payload["error"]
    assert sorted(p.name for p in wired.songs_root.iterdir()) == before, (
        "拒了，却已经在 songs/ 下留了个空壳"
    )


def test_空链接被挡住(wired):
    status, payload = wired.post("/api/job-from-url", b"   ")
    assert status == 400
    assert "error" in payload


def test_链接任务起子进程时命令里带着那条链接(wired):
    _, created = wired.post("/api/job-from-url", URL.encode("utf-8"))
    status, _ = wired.post(f"/api/job/{created['job_id']}/start?stage=ingest")

    assert status == 200
    argv = wired.argv(1)[0]
    assert argv[0] == "ingest"
    assert argv[-2:] == ["--url", URL]


def test_取回之后那一步用的是认出来的曲名(wired):
    """判据是"一路走到出片"，而出片带的标题不该是 `web-…-来自链接`。"""
    _, created = wired.post("/api/job-from-url", URL.encode("utf-8"))
    song_dir = Path(created["song_dir"])
    # 装成 ingest 已经把素材取回来了。
    (song_dir / "_in" / "锈色电台.m4a").write_bytes(b"x")
    (song_dir / "lyrics.txt").write_text("第一句\n", encoding="utf-8")

    wired.post(f"/api/job/{created['job_id']}/start?stage=run")

    argv = wired.argv(1)[-1]
    assert argv[0] == "run"
    assert "--title" in argv
    assert argv[argv.index("--title") + 1] == "锈色电台"
    assert "--url" not in argv, "`run` 那一步不该再带链接——素材已经在盘上了"


def test_传文件那条老路的命令一个字节没变(wired):
    status, created = wired.post(
        "/api/job", b"fake-audio", {"X-Filename": "%E6%88%91%E7%9A%84%E6%AD%8C.mp3"}
    )
    assert status == 201, created
    song_dir = Path(created["song_dir"])
    (song_dir / "lyrics.txt").write_text("第一句\n", encoding="utf-8")
    wired.post(f"/api/job/{created['job_id']}/start?stage=run")

    argv = wired.argv(1)[-1]
    assert "--url" not in argv
    assert argv[argv.index("--title") + 1] == "我的歌"


# --------------------------------------------------------------------------
# ⑦ 界面：链接输入框，以及它那道闸门
# --------------------------------------------------------------------------


def _page_html() -> str:
    return app.PAGE.read_text(encoding="utf-8")


def _run_page_js(tmp_path: Path, driver: str) -> str:
    """把页面脚本 + 一段驱动丢给 node 跑。

    **不 grep**：判据是「贴了链接就能提交」「文件和链接都给了要拦住」，
    而 `assert "链接" in html` 对一个把字写死在页面上、跟状态毫无关系的实现
    照样绿——这个仓栽过九次的形状。
    """
    import subprocess

    html = _page_html()
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert len(scripts) == 1, f"页面上的内联脚本从 1 段变成了 {len(scripts)} 段"
    path = tmp_path / "page.js"
    path.write_text(scripts[0] + "\n" + driver, encoding="utf-8")
    proc = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"node 跑页面脚本失败：\n{proc.stderr}"
    return proc.stdout


def test_页面上有一个中文的链接输入框():
    """这一个是 `<input type=text>`，**不套 `.sr` + label**——那一套是为了盖住
    原生 file 控件那几个 CSS 改不掉的英文字，套在文本框上等于把输入框藏了。
    沿用的是「中文 + 同一档玻璃卡 + 不引入新配色」。
    """
    html = _page_html()
    tag = re.search(r'<input\b[^>]*id="url"[^>]*>', html)
    assert tag is not None, "页面上没有 `<input id=\"url\">`。"
    assert 'type="text"' in tag.group(0) or 'type="url"' in tag.group(0)
    classes = re.search(r'class="([^"]*)"', tag.group(0))
    assert classes is None or "sr" not in classes.group(1).split(), (
        f"链接框套了 `.sr`——那是无障碍隐藏区，用户根本看不见它：{tag.group(0)}"
    )

    label = re.search(r'<label\b[^>]*\bfor="url"[^>]*>(.*?)</label>', html, re.S)
    assert label is not None, "链接框没有 `<label for=\"url\">`。"
    assert re.search(r"[一-鿿]", label.group(1)), (
        f"链接框的 label 里一个汉字都没有：{label.group(1)!r}"
    )


def test_文件选择器还是两个():
    """加的是文本框，不是第三个 file 控件——`test_web_page.py` 那条
    `len(inputs) == 2` 的守卫不该被这一棒推着改。"""
    assert len(re.findall(r'<input\b[^>]*type="file"[^>]*>', _page_html())) == 2


#: 闸门要分得开的四种情形。`blockedReason(route, lyrics, url, hasFile)`
#: 返回 `null` 表示可以提交。
_GATE = [
    ("只贴链接", [None, "", "https://example.invalid/v", False], True),
    ("只贴链接且没歌词也行", [None, "   ", "https://example.invalid/v", False], True),
    ("只选音频没歌词", ["run", "", "", True], False),
    ("只选音频有歌词", ["run", "第一句", "", True], True),
    ("只选视频没歌词", ["ingest", "", "", True], True),
    ("什么都没给", [None, "", "", False], False),
    ("文件和链接都给了", ["run", "第一句", "https://example.invalid/v", True], False),
]


def test_闸门的这几种情形分得开(tmp_path):
    import json as _json

    cases = [args for _, args, _ in _GATE]
    got = _json.loads(
        _run_page_js(
            tmp_path,
            "console.log(JSON.stringify(%s.map(function (a) "
            "{ return blockedReason(a[0], a[1], a[2], a[3]); })));"
            % _json.dumps(cases, ensure_ascii=False),
        )
    )
    wrong = [
        (name, reason)
        for (name, _, allowed), reason in zip(_GATE, got)
        if (reason is None) != allowed
    ]
    assert not wrong, f"闸门判错了这几种：{wrong}"


def test_文件和链接都给了要说清楚是哪一种冲突(tmp_path):
    """拦住还不够——只说"不能提交"的话，用户不知道该删哪一个。
    照 `scan` 的老规矩：拿不准就报错，并且把候选说出来。"""
    import json as _json

    both, only_file = _json.loads(
        _run_page_js(
            tmp_path,
            'console.log(JSON.stringify(['
            'blockedReason("run", "第一句", "https://x.invalid/v", true),'
            'blockedReason(null, "", "", false)]));',
        )
    )
    assert both is not None
    assert only_file is not None
    assert both != only_file, (
        "「文件和链接都给了」跟「什么都没给」说的是同一句话——"
        "用户看不出自己犯的是哪一个错"
    )


#: 一个够 `boot()` 跑起来的最小 DOM 替身。
#:
#: **为什么值得写这么一段**：闸门那几条验的是纯函数，验不到「点了开始之后到底
#: 打哪个端点」——而那正是链接这条路唯一的接线。只 grep `"/api/job-from-url"`
#: 在页面里出现过是没用的：一段死代码里的字符串照样能让它绿。
_DOM_STUB = """
var __fetches = [];
function __el() {
  return { value: "", files: [], textContent: "", innerHTML: "", hidden: true,
           disabled: false, href: "", open: false, scrollTop: 0, clientHeight: 0,
           scrollHeight: 0, _on: {},
           addEventListener: function (k, f) { this._on[k] = f; },
           scrollIntoView: function () {}, closest: function () { return null; } };
}
var __nodes = {};
global.document = {
  getElementById: function (id) {
    if (!__nodes[id]) { __nodes[id] = __el(); }
    return __nodes[id];
  },
  addEventListener: function () {}
};
global.window = { open: function () {} };
global.setInterval = function () { return 1; };
global.clearInterval = function () {};
global.fetch = function (path, init) {
  __fetches.push({ path: path, method: (init && init.method) || "GET",
                   body: init && init.body });
  return Promise.resolve({
    ok: true,
    json: function () { return Promise.resolve({ job_id: "abc", route: "ingest" }); }
  });
};
"""


def test_贴了链接点开始打的是链接那个端点(tmp_path):
    """页面上写着「粘一条视频链接，自动取回」——**那是一句承诺**。

    真把 `boot()` 跑起来、真点那个按钮，看它打到哪儿去。
    """
    import json as _json

    out = _run_page_js(
        tmp_path,
        _DOM_STUB
        + """
boot();
var el = document.getElementById("url");
el.value = "https://example.invalid/watch?v=abc";
document.getElementById("start")._on.click().then(function () {
  console.log(JSON.stringify(__fetches.map(function (f) { return f.path; })));
});
""",
    )
    paths = _json.loads(out)
    assert paths[0] == "/api/job-from-url", (
        f"贴了链接点开始，打的却是 {paths[0]!r}——页面上那句「粘一条视频链接」是空的"
    )
    assert "/api/job" not in paths[:1]


def test_没贴链接时点开始走的还是上传那条老路(tmp_path):
    """这一条跟上一条是一对：**只验新路会让"永远走新路"也绿**。"""
    import json as _json

    out = _run_page_js(
        tmp_path,
        _DOM_STUB
        + """
boot();
document.getElementById("media").files = [{ name: "我的歌.mp3" }];
document.getElementById("lyrics").value = "第一句";
document.getElementById("start")._on.click().then(function () {
  console.log(JSON.stringify(__fetches.map(function (f) { return f.path; })));
});
""",
    )
    paths = _json.loads(out)
    assert paths[0] == "/api/job", f"没贴链接却打了 {paths[0]!r}"
    assert "/api/job-from-url" not in paths


def test_错误原文限高但一个字节都还够得到():
    """真跑实测：取回落到第 3 级时，那 20 行里有三条带绝对路径的完整命令，
    错误块高 **1385 px**，把下面的东西全推出屏幕。

    限高**必须配 `overflow`**——只限高不给滚动条就是把原文藏起来，那正是
    「降级必须大声说」要防的。两个一起断，缺一条这里就红。
    """
    html = _page_html()
    block = re.search(r"pre\.error\s*\{([^}]*)\}", html)
    assert block is not None, "页面上没有 `pre.error` 这条规则了。"
    body = block.group(1)
    assert "max-height" in body, "错误块没有限高——第 3 级那一屏会把页面撑爆。"
    assert re.search(r"overflow:\s*auto", body), (
        "错误块限了高却没给滚动条——原文被藏起来了，这比撑爆页面更糟。"
    )


def test_版权提醒不是只在日志里一闪而过():
    """断的是"它在页面的静态结构里"，不是"某处出现过这个词"。

    只断 `marker in html` 的话，把它写进一段注释里也照样绿——注释不进渲染。
    """
    html = app.PAGE.read_text(encoding="utf-8")
    stripped = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    assert "你对自己处理和分发的素材负责" in stripped, (
        "那句版权提醒只出现在 HTML 注释里——用户一个字也看不到。"
    )


# --------------------------------------------------------------------------
# ⑧ 取回那几分钟：大标题不许再说「准备中…」
#
# 贴一条链接之后，`fetch` 要下工具链（第一次还有一个 36.7 MB 的运行时）再下
# 素材，**几分钟**。这几分钟里主日志一直在滚（上面 ① 那一节钉的就是这个），
# 而外层那个大标题一直是「准备中…」——因为 `ingest` 的 `[1/2]` 要等取回成功
# 才打。它不在准备，它在下东西。
#
# 修法是给「编号之外的阶段」一个格子（`progress.Progress.phase`），**不动
# `outer` 的分母**：取回不是"第 3 步"，它是 `[1/2]` 之前的一段。
# --------------------------------------------------------------------------


def test_取回层的前缀两处是同一个():
    """`progress.FETCH_PREFIX` 是从 `fetch.LOG_PREFIX` 抄来的三个字。

    抄件会过期：`fetch.py` 哪天把前缀改了，`progress` 这边不会红，它只会从此
    再也认不出取回那一段——主日志重新被折叠、大标题重新变回「准备中…」，而
    **一条测试都不响**。这就是那条守卫。
    """
    assert progress.FETCH_PREFIX == fetch.LOG_PREFIX, (
        f"两处的取回前缀对不上了：progress 抄的是 {progress.FETCH_PREFIX!r}，"
        f"fetch 打出来的是 {fetch.LOG_PREFIX!r}。"
    )


#: 取回一趟走完、再进 `ingest` 的那几行，**顺序照 `cli.ingest_url` 的真实调用
#: 次序**（`fetch_url` 全跑完才轮到 `ingest`）。
#:
#: 头四行取自本文件上面那两张真跑抄件（`FETCH_SHAPES` 与
#: `COLD_START_LINES`），第五行取自 `test_web_progress.py` 那份完整抄件里
#: `ingest` 的第一步——**没有一行是为这条测试新编的**。
_FETCH_THEN_INGEST = [
    "[取回] ⚠ 你对自己处理和分发的素材负责。",
    "[取回] 第 1 级：运行时拉取的最新 yt-dlp（uv 临时环境，不进 pyproject/uv.lock，不锁版本）",
    "Downloading deno (36.7MiB)",
    "[取回] 取回成功（第 1 级）：锈色电台.m4a",
    "[1/2] 准备音频 ← 锈色电台.m4a",
]


def test_取回一开口就有名有姓():
    """第一行落地，`phase` 就说得出这是哪个阶段。

    断的是**第一行**而不是第五行：取回那几分钟的头一句就是版权提醒，
    从那一刻起页面就不该再说「准备中…」。
    """
    state = progress.parse(_FETCH_THEN_INGEST[:1])
    assert state.phase == progress.PHASE_FETCH, (
        f"取回的第一行落地了，phase 却是 {state.phase!r}。"
    )


def test_取回那几分钟外层仍旧是_None_而不是_0_slash_2():
    """**这条守卫没有被放宽。**

    `Progress` 的 docstring 写着 `outer` 为 `None` 表示"这一层一步都还没打印
    过"，跟 `0/2` 不是一回事。给取回加名字很容易顺手写成"外层 0/2"——那就是
    在说"编号那一套已经开始了、走了 0 步"，而实际上它一步都还没打印。
    """
    state = progress.parse(_FETCH_THEN_INGEST[:4])
    assert state.phase == progress.PHASE_FETCH
    assert state.outer is None, (
        f"取回还没完，外层却已经是 {state.outer!r}——`None` 与 `0/2` 是两件事。"
    )
    assert state.inner is None


def test_uv_下运行时那几行不会把阶段丢掉():
    """`Downloading deno (36.7MiB)` **不带** `[取回]` 前缀（那是 uv 自己打的）。

    只在"这一行带前缀"时才认阶段、别的行一律清掉的话，取回中途每来一行 uv 或
    yt-dlp 的原文，大标题就闪回一次「准备中…」。所以阶段是**粘住**的，只由
    `[n/m]` 接手时才交班。
    """
    state = progress.parse(_FETCH_THEN_INGEST[:3])
    assert _FETCH_THEN_INGEST[2].startswith(progress.FETCH_PREFIX) is False, (
        "夹具第三行被改成带前缀的了——它本来就是要考「不带前缀的那种」。"
    )
    assert state.phase == progress.PHASE_FETCH, (
        f"来了一行 uv 的原文，阶段就丢了：phase 变成 {state.phase!r}。"
    )


def test_编号那一套一接手取回就交班():
    """`[1/2]` 一到，`phase` 就清空。

    不清的话，取回结束之后页面上会一直挂着一个早就跑完了的阶段名——那也是一句
    假话，只是方向反过来。**同时断外层真的接上了**：只断"清空了"的话，一个把
    `phase` 永远设成 `None` 的实现照样绿。
    """
    state = progress.parse(_FETCH_THEN_INGEST)
    assert state.phase is None, (
        f"`[1/2]` 都打出来了，phase 还挂着 {state.phase!r}。"
    )
    assert state.outer is not None and state.outer.current == 1, (
        f"外层没接上：{state.outer!r}"
    )
    assert state.outer.total == progress.OUTER_TOTAL == 2, (
        f"外层的分母变成了 {state.outer.total}——取回不是「第 3 步」，"
        "它是 `[1/2]` 之前的一段。分母一变，页面上就成了「有时候 2 步、"
        "有时候 3 步」，那是要读代码才懂的东西。"
    )


def test_没有取回的那条路一个阶段都不冒出来():
    """传文件那条老路上 `phase` 永远是 `None`。

    少了这条，一个"把 `phase` 恒设成 fetch"的实现在上面几条里全绿——而它会让
    传文件的用户也看见「取回素材」，那是一句纯粹的假话。
    """
    state = progress.parse(["[1/2] 准备音频 ← 我的歌.mp3", "[2/2] 歌词    ← 我的歌.txt → lyrics.txt"])
    assert state.phase is None, f"没贴过链接，却冒出来一个阶段 {state.phase!r}。"


def test_取回那一段会进到页面拿得到的_payload_里(tmp_path):
    """`phase` 得真的走到 HTTP 那一侧。

    `state_payload` 漏掉这个字段的话，上面那几条纯函数的守卫**全绿**，而页面
    上一个字都不会变——两头都对、中间断了，是这类改动最容易留下的那道缝。
    """
    songs_root = tmp_path / "songs"
    songs_root.mkdir()
    job = jobs.create_job_from_url("https://example.invalid/v", songs_root=songs_root)
    entry = app.Entry(job=job, title="")
    entry.run = runner.Run(
        runner.RunState(
            stage=runner.STAGE_INGEST,
            status=runner.RUNNING,
            progress=progress.parse(_FETCH_THEN_INGEST[:2]),
        )
    )
    payload = app.state_payload("jobid", entry)
    assert payload["phase"] == progress.PHASE_FETCH, (
        f"payload 里的 phase 是 {payload['phase']!r}——页面拿不到阶段名，"
        "大标题只能退回「准备中…」。"
    )
    assert payload["outer"] is None, "外层不该被顺手填成 0/2。"


def test_阶段名两处对得上():
    """页面那张 `PHASE_NAMES` 的键，跟 `progress.PHASE_FETCH` 是同一个字。

    两处各写各的：`progress.py` 把阶段叫 `fetch`，页面那张表要是写成别的，
    `phaseTitle()` 查不到就**安静地退回「准备中…」**——正是这一整节要修掉的那
    句假话，而没有任何东西会红。
    """
    html = _page_html()
    table = re.search(r"var PHASE_NAMES = \{(.*?)\};", html, re.S)
    assert table is not None, "页面上没有 `PHASE_NAMES` 这张表了。"
    keys = re.findall(r'"([^"]+)"\s*:', table.group(1))
    assert keys == [progress.PHASE_FETCH], (
        f"页面认的阶段键是 {keys}，而 progress 给的是 "
        f"{progress.PHASE_FETCH!r}——对不上就等于没有这张表。"
    )


def test_大标题在三种情形下说的是三件不同的事(tmp_path):
    """`phaseTitle()` 逐档核。**三档一起断，缺一档都能被蒙混过去**：

    - 有 `[n/m]` → 照直念（少了它，一个"永远念取回素材"的实现照样绿）
    - 没有 `[n/m]`、有阶段 → 念阶段名（这一档就是这一棒要修的）
    - 两样都没有 → 才是真的「准备中…」（少了它，一个"再也不说准备中"的
      实现照样绿，而子进程刚起来那一瞬间它确实还什么都没干）
    """
    import json as _json

    out = _run_page_js(
        tmp_path,
        """
        console.log(JSON.stringify({
          numbered: phaseTitle({ outer: { step: 1, total: 2, name: "准备音频" },
                                 phase: null }),
          fetching: phaseTitle({ outer: null, phase: "fetch" }),
          nothing:  phaseTitle({ outer: null, phase: null }),
          numberedWinsOverPhase:
            phaseTitle({ outer: { step: 2, total: 2, name: "歌词" }, phase: "fetch" }),
        }));
        """,
    )
    got = _json.loads(out)
    assert got["numbered"] == "[1/2] 准备音频"
    assert got["fetching"] == "取回素材", (
        f"取回那几分钟大标题念的是 {got['fetching']!r}——它不在准备，它在下东西。"
    )
    assert got["nothing"] == "准备中…", (
        f"一行都还没打出来时念的是 {got['nothing']!r}；那一刻它确实还没开始。"
    )
    assert got["numberedWinsOverPhase"] == "[2/2] 歌词", (
        "编号那一套已经接手了，大标题却还挂着阶段名。"
    )
