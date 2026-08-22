"""`murripple.fetch` 的三级降级链。

**这里一个字节都不走网络。** 三级路径全部靠替身跑到，而替身的输出形状
**逐字抄自 2026-08-14 一次真跑 yt-dlp 2026.07.04**（出处与重抄步骤见
`tests/fixtures/yt-dlp/README.provenance.md`）。`_TEMPLATES` 里那几段模板配了
一条恒等式测试：拿抄件当时的实际值填回去，必须**逐字节还原抄件**。
"""

from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from murripple import fetch
from murripple.ingest.audio import COPY_SUFFIXES
from murripple.ingest.scan import VIDEO_SUFFIXES

FIXTURES = Path(__file__).parent / "fixtures" / "yt-dlp"

#: 替身用的标题。故意带中文与空格——真实素材的标题就是这样，
#: 顺带让"路径拼接把标题当模板了吗"这类错误露出来。
FAKE_TITLE = "知漪 测试曲"


# --------------------------------------------------------------------------
# 抄件 → 模板
#
# 模板是**手抄**的，不是从抄件里 replace 出来的——从抄件 replace 出来的模板
# 与抄件的恒等式是同义反复，验不出"我抄错了"。手抄 + 恒等式回填才验得出。
# --------------------------------------------------------------------------

_AUDIO_SUCCESS_TEMPLATE = (
    "[generic] Extracting URL: {url}\n"
    "[generic] {title}: Downloading webpage\n"
    "[info] {title}: Downloading 1 format(s): {fmt}\n"
    "[download] Destination: {dest}\n"
    "[download]   {p0}% of   {size} at  Unknown B/s ETA Unknown\n"
    "[download]   {p1}% of   {size} at  Unknown B/s ETA Unknown\n"
    "[download]  {p2}% of   {size} at  Unknown B/s ETA Unknown\n"
    "[download]  {p3}% of   {size} at  Unknown B/s ETA Unknown\n"
    "[download]  {p4}% of   {size} at  Unknown B/s ETA Unknown\n"
    "[download] 100.0% of   {size} at  Unknown B/s ETA Unknown\n"
    "[download] 100% of   {size} in 00:00:00 at {speed}\n"
    "[info] Writing '%(filepath)s' to: {printfile}\n"
)

_HTTP_403_TEMPLATE = (
    "[generic] Extracting URL: {url}\n"
    "[generic] {title}: Downloading webpage\n"
    "ERROR: [generic] {title}: Unable to download webpage: "
    "HTTP Error 403: Forbidden (caused by <HTTPError 403: Forbidden>)\n"
)

_NO_FORMAT_TEMPLATE = (
    "[generic] Extracting URL: {url}\n"
    "[generic] {title}: Downloading webpage\n"
    "ERROR: [generic] {title}: Requested format is not available. "
    "Use --list-formats for a list of available formats\n"
)

#: 抄件当时的实际值。恒等式测试拿它把模板填回去，比对抄件的字节。
_CAPTURED = {
    "audio-success.stdout": (
        _AUDIO_SUCCESS_TEMPLATE,
        {
            "url": "http://127.0.0.1:8931/%E7%9F%A5%E6%BC%AA%E6%B5%8B%E8%AF%95%E9%9F%B3.m4a",
            "title": "知漪测试音",
            "fmt": "mp4a-latm",
            "dest": "/private/tmp/claude-501/-Users-miaoyu-Documents-claudeProjects-murRipple--claude-worktrees-nostalgic-gould-ad0822/15312c2f-db01-4d4c-a0a8-522ac12e15b5/scratchpad/capture/outB/知漪测试音.m4a",
            "printfile": "/private/tmp/claude-501/-Users-miaoyu-Documents-claudeProjects-murRipple--claude-worktrees-nostalgic-gould-ad0822/15312c2f-db01-4d4c-a0a8-522ac12e15b5/scratchpad/capture/outB.path",
            "size": "46.91KiB",
            "speed": "31.11MiB/s",
            "p0": "2.1",
            "p1": "6.4",
            "p2": "14.9",
            "p3": "32.0",
            "p4": "66.1",
        },
    ),
    "video-success.stdout": (
        _AUDIO_SUCCESS_TEMPLATE,
        {
            "url": "http://127.0.0.1:8931/%E7%9F%A5%E6%BC%AA%E6%B5%8B%E8%AF%95%E7%89%87.mp4",
            "title": "知漪测试片",
            "fmt": "mp4",
            "dest": "/private/tmp/claude-501/-Users-miaoyu-Documents-claudeProjects-murRipple--claude-worktrees-nostalgic-gould-ad0822/15312c2f-db01-4d4c-a0a8-522ac12e15b5/scratchpad/capture/outE/知漪测试片.mp4",
            "printfile": "/private/tmp/claude-501/-Users-miaoyu-Documents-claudeProjects-murRipple--claude-worktrees-nostalgic-gould-ad0822/15312c2f-db01-4d4c-a0a8-522ac12e15b5/scratchpad/capture/outE.path",
            "size": "41.75KiB",
            "speed": "24.45MiB/s",
            "p0": "2.4",
            "p1": "7.2",
            "p2": "16.8",
            "p3": "35.9",
            "p4": "74.2",
        },
    ),
    "http-403": (
        _HTTP_403_TEMPLATE,
        {"url": "http://127.0.0.1:8931/forbidden/x.m4a", "title": "x"},
    ),
    "no-format": (
        _NO_FORMAT_TEMPLATE,
        {
            "url": "http://127.0.0.1:8931/%E7%9F%A5%E6%BC%AA%E6%B5%8B%E8%AF%95%E7%89%87.mp4",
            "title": "知漪测试片",
        },
    ),
}


def _captured_merged(name: str) -> str:
    """抄件的 stdout 与 stderr 合起来——这正是 `_run` 交给我们的东西。"""
    text = (FIXTURES / f"{name}.stdout").read_text(encoding="utf-8")
    stderr = FIXTURES / f"{name}.stderr"
    if stderr.exists():
        text += stderr.read_text(encoding="utf-8")
    return text


# --------------------------------------------------------------------------
# 替身
# --------------------------------------------------------------------------


@dataclass
class _Step:
    """替身对某一次子进程调用的处置。"""

    kind: str
    #: `ok` 时产物的扩展名。默认 m4a；`--merge-output-format` 会覆盖它。
    ext: str | None = None
    #: 这一趟额外吐出几条产物路径（`--no-playlist` 没拦住的站点会这样）。
    extra_entries: int = 0


class FakeYtDlp:
    """顶掉 `fetch._run` 的替身。

    它**认我们真发出去的那份 argv**：`-o` 模板、`--print-to-file` 的落点、
    `--merge-output-format` 都是从 argv 里读出来的。命令拼错了，替身会当场
    KeyError／IndexError，而不是默默给一个好结果——**替身不该比被测代码宽容**。
    """

    def __init__(self, *steps: _Step | str):
        self.steps = [_Step(s) if isinstance(s, str) else s for s in steps]
        self.calls: list[tuple[str, ...]] = []
        #: 每一次调用拿到的 `quiet_notice`（没有就是 None）。
        self.notices: list[str | None] = []

    @staticmethod
    def _opt(argv: list[str], name: str) -> str | None:
        return argv[argv.index(name) + 1] if name in argv else None

    def __call__(self, argv, log, *, quiet_notice=None, **kwargs):
        argv = list(argv)
        self.calls.append(tuple(argv))
        self.notices.append(quiet_notice)
        if not self.steps:
            raise AssertionError(f"替身没有为第 {len(self.calls)} 次调用准备处置：{argv}")
        step = self.steps.pop(0)
        tier = 1 if Path(argv[0]).name == "uv" else 2
        url = argv[-1]

        if step.kind == "missing-binary":
            # uv 不在 PATH 上：`subprocess` 抛的就是这个。
            raise FileNotFoundError(2, "No such file or directory", argv[0])

        if step.kind == "uv-unresolvable":
            text = (FIXTURES / "uv-unresolvable.stderr").read_text(encoding="utf-8")
            for line in text.splitlines():
                log(line)
            return fetch._Run(returncode=1, output=text)

        if step.kind == "no-module":
            text = (FIXTURES / "no-module.stderr").read_text(encoding="utf-8")
            for line in text.splitlines():
                log(line)
            return fetch._Run(returncode=1, output=text)

        if step.kind in ("http-403", "no-format"):
            template, _ = _CAPTURED[step.kind]
            text = template.format(url=url, title=FAKE_TITLE)
            for line in text.splitlines():
                log(line)
            return fetch._Run(returncode=1, output=text)

        if step.kind == "silent-success":
            # 退出码 0，可什么都没下。站点改版之后 yt-dlp 真会这样，
            # 而"成功地什么都没下"比报错更难查。
            return fetch._Run(returncode=0, output="")

        if step.kind == "ok":
            out_template = self._opt(argv, "-o")
            # `--print-to-file` 吃两个参数：模板、落点。取错一个就会拿到
            # `after_move:filepath` 当路径——所以这里顺带断一下模板本身。
            i = argv.index("--print-to-file")
            assert argv[i + 1] == "after_move:filepath", (
                f"`--print-to-file` 的模板不对：{argv[i + 1]}"
            )
            printfile = Path(argv[i + 2])
            ext = step.ext or self._opt(argv, "--merge-output-format") or "m4a"
            out_dir = Path(out_template).parent
            assert Path(out_template).name == "%(title)s.%(ext)s", (
                f"`-o` 模板不是按标题命名的：{out_template}"
            )
            dest = out_dir / f"{FAKE_TITLE}.{ext}"
            out_dir.mkdir(parents=True, exist_ok=True)
            # 每一级写不同的字节：这样"产物是哪一级产的"是一条可断言的事实，
            # 不是从调用记录推出来的。
            dest.write_bytes(f"TIER{tier}".encode())
            printfile.parent.mkdir(parents=True, exist_ok=True)
            # **追加，不是覆盖**——实测 yt-dlp 的 `--print-to-file` 就是追加
            # （出处见 README.provenance.md）。替身照抄这个行为，否则
            # "落点没清干净"这一类错误在测试里根本不会发生。
            with printfile.open("a", encoding="utf-8") as fh:
                if step.extra_entries:
                    for n in range(step.extra_entries):
                        fh.write(f"{out_dir / f'另一首-{n}.{ext}'}\n")
                fh.write(f"{dest}\n")
            text = _AUDIO_SUCCESS_TEMPLATE.format(
                url=url,
                title=FAKE_TITLE,
                fmt="mp4a-latm",
                dest=str(dest),
                printfile=str(printfile),
                size="46.91KiB",
                speed="31.11MiB/s",
                p0="2.1",
                p1="6.4",
                p2="14.9",
                p3="32.0",
                p4="66.1",
            )
            for line in text.splitlines():
                log(line)
            return fetch._Run(returncode=0, output=text)

        raise AssertionError(f"替身不认识的处置：{step.kind}")


@pytest.fixture
def song_dir(tmp_path: Path) -> Path:
    d = tmp_path / "songs" / "07-测试曲"
    d.mkdir(parents=True)
    return d


#: 故意用 `.invalid`（RFC 2606 保留）：万一哪天替身没顶上，测试会立刻
#: 解析失败，而不是真的去某个站点上敲一下。
URL = "https://example.invalid/watch?v=abc"


def _run_fetch(monkeypatch, fake, song_dir, sink, **kwargs):
    monkeypatch.setattr(fetch, "_run", fake)
    return fetch.fetch_url(URL, song_dir, log=sink.append, **kwargs)


# --------------------------------------------------------------------------
# 第 1 级
# --------------------------------------------------------------------------


def test_第一级用的是运行时拉取的_yt_dlp(monkeypatch, song_dir):
    fake = FakeYtDlp("ok")
    sink: list[str] = []
    result = _run_fetch(monkeypatch, fake, song_dir, sink)

    assert result.tier == 1
    argv = fake.calls[0]
    assert Path(argv[0]).name == "uv"
    assert "--no-project" in argv
    # 产物就是第 1 级那个替身写的那串字节。
    assert result.audio.read_bytes() == b"TIER1"
    assert result.audio.parent == song_dir / "_in"


def test_第一级不锁版本(monkeypatch, song_dir):
    """`yt-dlp` 坏不是因为它自己有 bug，是站点改版——钉死的旧版更容易坏。"""
    fake = FakeYtDlp("ok")
    sink: list[str] = []
    _run_fetch(monkeypatch, fake, song_dir, sink)

    spec = [a for a in fake.calls[0] if a.startswith("yt-dlp")]
    assert spec, f"第 1 级的 argv 里没有 yt-dlp 需求串：{fake.calls[0]}"
    for s in spec:
        for pin in ("==", "<=", "~=", "<"):
            assert pin not in s, f"第 1 级把 yt-dlp 钉在了版本上：{s}"


def test_音频格式选择器优先_aac_免转码(monkeypatch, song_dir):
    """挑 AAC 是这条路的门道：`.m4a` 命中 `COPY_SUFFIXES`，`prepare_audio` 原样复制。"""
    fake = FakeYtDlp("ok")
    sink: list[str] = []
    result = _run_fetch(monkeypatch, fake, song_dir, sink)

    selector = fake.calls[0][fake.calls[0].index("-f") + 1]
    assert selector.split("/")[0] == "bestaudio[ext=m4a]"
    assert result.audio.suffix in COPY_SUFFIXES


def _ours(sink: list[str]) -> str:
    """只留**我们自己**打的那些行。

    不这么做的话，下面几条断言会命中替身照抄真实 yt-dlp 打出来的那段原文——
    "断言命中的字符串来自被测对象里的另一段数据"，`MGMT.md` 第七节记过。
    """
    return "\n".join(line for line in sink if line.startswith(fetch.LOG_PREFIX))


# --------------------------------------------------------------------------
# 降级
# --------------------------------------------------------------------------


@pytest.mark.parametrize("first", ["uv-unresolvable", "missing-binary", "http-403"])
def test_第一级失败后真的降到第二级(monkeypatch, song_dir, first):
    fake = FakeYtDlp(first, "ok")
    sink: list[str] = []
    result = _run_fetch(monkeypatch, fake, song_dir, sink)

    assert len(fake.calls) == 2, "第 1 级失败后没有第二次调用——它直接抛了"
    assert Path(fake.calls[0][0]).name == "uv"
    assert fake.calls[1][0] == sys.executable
    assert fake.calls[1][1:3] == ("-m", "yt_dlp")
    assert result.tier == 2
    # 产物是**第 2 级的替身**写的那串字节：不是从调用记录推出来的。
    assert result.audio.read_bytes() == b"TIER2"


_MARKERS = {
    "http-403": "HTTP Error 403: Forbidden",
    "no-format": "Requested format is not available",
    "uv-unresolvable": "No solution found",
}


@pytest.mark.parametrize("kind", sorted(_MARKERS))
def test_降级消息里说了为什么降级(monkeypatch, song_dir, kind):
    """只说"降级了"不算数——两种不同的失败必须给出两份互相排斥的说明。"""
    fake = FakeYtDlp(kind, "ok")
    sink: list[str] = []
    result = _run_fetch(monkeypatch, fake, song_dir, sink)

    ours = _ours(sink)
    assert _MARKERS[kind] in ours, f"我们自己的输出里没说第 1 级为什么失败：\n{ours}"
    for other, marker in _MARKERS.items():
        if other != kind:
            assert marker not in ours, f"说的原因不对：{kind} 的日志里出现了 {other} 的特征"
    # 同一份原因也要能被机器读到，不只是印在屏幕上。
    assert _MARKERS[kind] in result.attempts[0].reason
    assert result.attempts[0].ok is False
    # **每一行**都要带上我们的前缀。只给第一行带的话，多行原因（uv 那份是
    # 四行）后面几行就混进第三方原文里去了——正是 W1 日志分层要防的形状。
    for line in result.attempts[0].reason.splitlines():
        if line.strip():
            assert line in ours, f"原因的这一行没进我们自己的输出：{line!r}"


def test_退出码零但什么都没下也算失败(monkeypatch, song_dir):
    """只看退出码的话，"成功地什么都没下"会被报成取回成功，
    然后 `ingest` 面对一个空 `_in/` 说"素材看不明白"——错在哪根本看不出来。"""
    fake = FakeYtDlp("silent-success", "ok")
    sink: list[str] = []
    result = _run_fetch(monkeypatch, fake, song_dir, sink)

    assert result.tier == 2
    assert result.attempts[0].ok is False
    assert result.attempts[0].returncode == 0, "这一级的退出码就是 0，别改成假的非零"
    assert "没有写出任何产物路径" in _ours(sink)


def test_落点里残留着上一次的路径也不会读串(monkeypatch, song_dir):
    """`--print-to-file` 是**追加**（真跑实测）。上一趟留下的残件不清掉，
    这一趟读回来就是两行拼成的一个假路径——而且它看起来像成功。"""
    in_dir = song_dir / "_in"
    in_dir.mkdir()
    (in_dir / fetch.PATH_SIDECAR).write_text("/上一趟留下的/假路径.m4a\n", encoding="utf-8")

    fake = FakeYtDlp("ok")
    sink: list[str] = []
    result = _run_fetch(monkeypatch, fake, song_dir, sink)

    assert result.audio.parent == in_dir
    assert result.audio.read_bytes() == b"TIER1"


def test_一条链接吐出多份产物时不猜是哪一份(monkeypatch, song_dir):
    """`--no-playlist` 没拦住的站点会一趟下好几个。挑一个用是在猜——
    照 `scan` 的老规矩：拿不准就报错，把候选都列出来。"""
    fake = FakeYtDlp(_Step("ok", extra_entries=2))
    sink: list[str] = []
    with pytest.raises(fetch.AmbiguousResultError) as exc:
        _run_fetch(monkeypatch, fake, song_dir, sink)

    assert len(exc.value.paths) == 3


def test_只走第一级时日志里不出现第二级(monkeypatch, song_dir):
    fake = FakeYtDlp("ok")
    sink: list[str] = []
    _run_fetch(monkeypatch, fake, song_dir, sink)

    ours = _ours(sink)
    assert "第 1 级" in ours
    assert "第 2 级" not in ours


def test_降到第二级时两级都在日志里报了名(monkeypatch, song_dir):
    fake = FakeYtDlp("uv-unresolvable", "ok")
    sink: list[str] = []
    _run_fetch(monkeypatch, fake, song_dir, sink)

    ours = _ours(sink)
    assert "第 1 级" in ours
    assert "第 2 级" in ours
    assert "第 3 级" not in ours


# --------------------------------------------------------------------------
# 第 3 级
# --------------------------------------------------------------------------


def test_两级都不成时落到第三级(monkeypatch, song_dir):
    fake = FakeYtDlp("uv-unresolvable", "no-module")
    sink: list[str] = []
    with pytest.raises(fetch.FetchError) as exc:
        _run_fetch(monkeypatch, fake, song_dir, sink)

    err = exc.value
    assert [a.tier for a in err.attempts] == [1, 2]
    assert all(a.ok is False for a in err.attempts)
    assert "第 3 级" in _ours(sink)


def test_第三级的手动命令就是第一级真跑过的那条(monkeypatch, song_dir):
    """判据是"可直接粘贴执行"，所以断的不是"有个字符串"，是**它逐项等于我们
    真发给子进程的那份 argv**——占位串、伪代码、少个引号都过不了 shlex 这关。"""
    fake = FakeYtDlp("uv-unresolvable", "no-module")
    sink: list[str] = []
    with pytest.raises(fetch.FetchError) as exc:
        _run_fetch(monkeypatch, fake, song_dir, sink)

    manual = exc.value.manual_command
    assert shlex.split(manual) == list(fake.calls[0])
    # 手动命令也要出现在给人看的输出里，不能只挂在异常对象上。
    assert manual in _ours(sink)


def test_第三级把两级的原因都带上(monkeypatch, song_dir):
    fake = FakeYtDlp("uv-unresolvable", "no-module")
    sink: list[str] = []
    with pytest.raises(fetch.FetchError) as exc:
        _run_fetch(monkeypatch, fake, song_dir, sink)

    ours = _ours(sink)
    assert "No solution found" in ours
    assert "No module named yt_dlp" in ours


# --------------------------------------------------------------------------
# 落地形态：产物必须是 ingest 认得的那一档
# --------------------------------------------------------------------------


def test_取回视频走另一趟且落成容器视频(monkeypatch, song_dir):
    fake = FakeYtDlp("ok", "ok")
    sink: list[str] = []
    result = _run_fetch(monkeypatch, fake, song_dir, sink, want_video=True)

    assert len(fake.calls) == 2
    audio_argv, video_argv = fake.calls
    assert "--merge-output-format" not in audio_argv
    assert video_argv[video_argv.index("--merge-output-format") + 1] == "mkv"
    assert result.audio.suffix in COPY_SUFFIXES
    assert result.video is not None
    assert result.video.suffix in VIDEO_SUFFIXES


def test_取回的音频落成_ingest_不认的扩展名时报错(monkeypatch, song_dir):
    """挑 AAC 免转码是这条路的全部门道。落成 `_in/` 里一个 `.mp4`，
    `scan` 会把它当成**视频**去 OCR；落成 `.opus` 则直接"忽略（用不上）"。
    两种都是一趟白跑，所以这里当场拦住、说清楚怎么办。"""
    fake = FakeYtDlp(_Step("ok", ext="mp4"))
    sink: list[str] = []
    with pytest.raises(fetch.UnusableAudioError) as exc:
        _run_fetch(monkeypatch, fake, song_dir, sink)

    assert exc.value.suffix == ".mp4"
    assert exc.value.path.exists()


def test_in_里已经有东西时不动手(monkeypatch, song_dir):
    (song_dir / "_in").mkdir()
    (song_dir / "_in" / "已经放好的.wav").write_bytes(b"x")
    fake = FakeYtDlp()
    sink: list[str] = []
    with pytest.raises(fetch.FetchError):
        _run_fetch(monkeypatch, fake, song_dir, sink)

    assert fake.calls == [], "`_in/` 里有东西却还是去下载了"


def test_加了_force_就照下(monkeypatch, song_dir):
    (song_dir / "_in").mkdir()
    (song_dir / "_in" / "已经放好的.wav").write_bytes(b"x")
    fake = FakeYtDlp("ok")
    sink: list[str] = []
    result = _run_fetch(monkeypatch, fake, song_dir, sink, force=True)

    assert result.tier == 1


# --------------------------------------------------------------------------
# 版权
# --------------------------------------------------------------------------


def test_版权提醒无条件打印(monkeypatch, song_dir):
    """成功要打，全砸了也要打——它是这条路存在的前提，不是成功回执。"""
    fake = FakeYtDlp("uv-unresolvable", "no-module")
    sink: list[str] = []
    with pytest.raises(fetch.FetchError):
        _run_fetch(monkeypatch, fake, song_dir, sink)
    assert "你对自己处理和分发的素材负责" in _ours(sink)

    fake2 = FakeYtDlp("ok")
    sink2: list[str] = []
    _run_fetch(monkeypatch, fake2, song_dir, sink2, force=True)
    assert "你对自己处理和分发的素材负责" in _ours(sink2)


# --------------------------------------------------------------------------
# 替身的输出是抄来的，不是手打的
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(_CAPTURED))
def test_替身模板能逐字节还原真实抄件(name):
    """替身照着这几段模板说话。拿抄件当时的实际值填回模板，必须**逐字节**
    还原 `tests/fixtures/yt-dlp/` 里那份真跑抄件。

    有人把模板顺手改成"理想格式"（补个空格、把两个空格改成一个、把
    `%(filepath)s` 当成占位符填掉），这一条就红。
    """
    template, values = _CAPTURED[name]
    expected = _captured_merged(name.removesuffix(".stdout"))
    assert template.format(**values) == expected


def test_抄件目录不是空的():
    """参数集由数据推导时，pytest 对空参数集的默认处置是绿 + 跳过
    （`MGMT.md` 第七节）。这一条是那份非参数化的独立守卫。"""
    assert sorted(p.name for p in FIXTURES.glob("*.std*")) == [
        "audio-success.stdout",
        "http-403.stderr",
        "http-403.stdout",
        "no-format.stderr",
        "no-format.stdout",
        "no-module.stderr",
        # uv 冷缓存那一份是 2026-08-14 接线那一棒加的：它不是 yt-dlp 的输出，
        # 是 uv 自己的，消费它的是 `tests/test_web_fetch_wiring.py`。
        # 加进来时这条守卫红了一次——**那正是它该有的样子**，
        # 刷新清单是显式动作。
        "uv-cold-start.stderr",
        "uv-unresolvable.stderr",
        "video-success.stdout",
    ]


# --------------------------------------------------------------------------
# `_run` 本身：这一段用**真子进程**，不用替身
# --------------------------------------------------------------------------


def test_run_把子进程的_stderr_并进来且不乱序():
    """两件事一起验：

    ① `stderr` 必须并进 `stdout`——不并的话用户只看到"失败了"、没有原因，
       与"降级必须大声说"直接冲突（`DECISIONS.md` 2026-08-14）。
    ② 子进程必须**无缓冲**。管道上 Python 的 stdout 是块缓冲的，而 stderr
       是行缓冲的：不塞 `PYTHONUNBUFFERED=1`，`out-1` 会攒到退出才刷出来，
       顺序变成 err-1 / out-1 / out-2（`DECISIONS.md` 2026-08-14 W1 承重条件）。
    """
    script = (
        "import sys\n"
        "print('out-1')\n"
        "sys.stderr.write('err-1\\n'); sys.stderr.flush()\n"
        "print('out-2')\n"
    )
    lines: list[str] = []
    run = fetch._run([sys.executable, "-c", script], lines.append)

    assert run.returncode == 0
    assert lines == ["out-1", "err-1", "out-2"]
    assert run.output == "out-1\nerr-1\nout-2\n"


def test_run_带回退出码():
    run = fetch._run([sys.executable, "-c", "import sys; sys.exit(3)"], lambda _: None)
    assert run.returncode == 3


# --------------------------------------------------------------------------
# 静默期：第一次要下一个 36.7 MB 的运行时，那段时间一行输出都没有
# --------------------------------------------------------------------------


def test_一直没输出时会反复说自己还在忙():
    """判据是「不知情的人不会以为它卡死了」。

    所以这句话**挂在静默这件事本身上**，不是开跑前一次性打的免责声明——
    真的没输出才说，而且一直没输出就一直说。
    """
    lines: list[str] = []
    run = fetch._run(
        [sys.executable, "-c", "import time; time.sleep(0.8)"],
        lines.append,
        quiet_notice="还在忙",
        quiet_after=0.15,
    )

    assert run.returncode == 0
    assert lines.count("还在忙") >= 2, f"静默了 0.8 秒却只说了 {lines.count('还在忙')} 次"


def test_一有输出就不再说了():
    """跑得快的时候一次都不该说——说了就是在为一件没发生的事道歉。"""
    lines: list[str] = []
    fetch._run(
        [sys.executable, "-c", "import time; print('第一行'); time.sleep(0.9)"],
        lines.append,
        quiet_notice="还在忙",
        quiet_after=0.2,
    )

    assert lines[0] == "第一行"
    assert lines.count("还在忙") == 0


def test_只有第一级挂这句话(monkeypatch, song_dir):
    """36.7 MB 的运行时是第 1 级（uv 临时环境）才会下的东西。
    第 2 级跑的是本地已装的模块，没有那一步——那儿说"还在下运行时"是撒谎。"""
    fake = FakeYtDlp("uv-unresolvable", "ok")
    sink: list[str] = []
    _run_fetch(monkeypatch, fake, song_dir, sink)

    assert fake.notices[0] is not None
    assert fetch.QUIET_NOTICE in fake.notices[0]
    assert fake.notices[1] is None
