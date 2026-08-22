"""端到端：**页面自己的 `boot()`** 驱动，替身 CLI 重放真跑抄来的原文。

## 这一份跟 `test_web_page.py` 的分工

`test_web_page.py` 从两头各证一半：那几个纯函数（在 node 里真跑）、六个端点
（用 `http.client` 打真服务）。中间那一层——**`boot()` 有没有把纯函数接到
DOM 上**——两头都够不着。Task 5 的实现者自己发现并报了上来：

> 把 `boot()` 里 `renderMainLog` 那行换成一句死文本，35 条全绿。

本文件补的就是那一段。判据不是「怎么做」，是：**把 `boot()` 里任意一处接线
改坏，必须有测试变红。**

## 怎么补：在 node 里给页面搭一个最小 DOM，让 `boot()` 真跑一遍

`node` 是本仓的**无条件依赖**（`tests/test_decode_parity.py:16,59` 直接调它、
没有 skipif；`renderer/` 那 243 条也全跑在 node 上）。Task 5 已经在把
`<script>` 从 `index.html` 里原样抽出来丢给 node 跑——这里只是在它前面再垫一
段替身 DOM，于是页面脚本末尾那句

    if (typeof document !== "undefined") { document.addEventListener("DOMContentLoaded", boot); }

会真的把 `boot` 挂上去。**替身 DOM 是测试代码，不是新依赖。**

`fetch` **不 mock**：node 24 自带全局 `fetch`，替身只给它拼一个
`http://127.0.0.1:<port>` 的前缀（页面里是同源相对路径，node 解析不了裸的
`/api/job`）。所以这几条是真的端到端——

    页面 boot() → fetch → app.py → runner.py → 替身 CLI → 夹具原文 → 页面 DOM

## 替身 DOM 自己会不会装绿（CONSTRAINTS 第 10 条 · 方向一）

这是本文件最容易翻车的地方。一个「什么都返回、什么都答应」的替身 DOM 会让
接线被删掉之后照样全绿——那正是它要防的错。三条硬规矩：

1. **元素清单从真实 `index.html` 里抽**（`PAGE_ELEMENTS`），不在这里手打。
   认不出的 id 返回 `null`（跟浏览器一致）并记一笔，驱动脚本最后断言「没有
   认不出的 id」。
2. **`hidden` / `disabled` / `href` 的初值也从真实 HTML 里抽。** 四个
   `<section>` 在 HTML 里带着 `hidden`，替身一律给 `hidden=false` 的话，
   「跑完之后成品区显示出来」这类断言就没了对照物。
   **实测（2026-08-14，见 task-6-report.md）**：把抽法改成恒 `false`、页面
   一个字不动，7 条红——**不是悄悄变绿**，因为驱动脚本等待的谓词跟断言看的
   是同一批 `hidden`，撒这个谎会让每一次等待都立刻返回，下游断言成片塌掉。
   `test_the_dom_double_starts_from_the_pages_own_initial_state` 因此是一条
   **诊断**：它把那 7 条红的原因一句话说清，而不是唯一挡着假绿的那道闸。
3. **派发一个没人监听的事件直接抛异常**，不是静默什么也不做——
   `el.start.addEventListener(...)` 被删掉时，测试要以「没人接这个事件」的面
   目红，而不是以「等了 30 秒没跑完」的面目红。

## 替身 CLI 与夹具的同源关系

**不造第三份。** 直接 `import test_web_page` 拿 Task 5 那一份
`FAKE_CLI_SOURCE`（pytest 的 prepend 导入模式把 `tests/` 放进了 `sys.path`），
它的跑通路径是逐行重放 `tests/fixtures/real-build-output.txt`——一次 12 秒
`build` 的真跑抄件（2026-08-16 在示例歌上重抄，1594 字节 / 18 行，出处见
`tests/fixtures/README.provenance.md`）。两级进度那一条
用的是 `test_web_progress.REAL_RUN_STDOUT`，同样是真跑抄来的原文，同样是
**import 过来的，不是在这里重打一遍**。

`E2E_DISPATCH_SOURCE` 那个包装**一个字都不往 stdout 上打**（
`test_the_dispatcher_adds_no_output_of_its_own` 钉着这一条），它只解决一件
事：同一条命令要在 `ingest` 那一步交出 OCR 歌词、在 `run` 那一步交出产物，而
Task 5 那份替身的模式是启动时定死的。

**这是本计划预言的「第九次」的正面**：替身的输出格式一旦跟真 CLI 脱钩，前面
六棒的所有绿就都建立在一份想象的格式上。

## 一个测试都不许碰仓内真实的 `songs/`

全部走 `tmp_path` + `AppState(songs_root=…)`。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

# 同目录的测试模块：pytest 的 prepend 导入模式把 `tests/` 放进了 `sys.path`
# （`tests/conftest.py` 在，且这个目录没有 `__init__.py`）。**故意 import 而
# 不是复制**：替身 CLI 只许有一份，复制一份出来就等于给「第九次」开了门。
import test_web_page as page_tests
import test_web_progress as progress_tests

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = page_tests.PAGE
BUILD_FIXTURE = page_tests.BUILD_FIXTURE
FALLBACK_FIXTURE = page_tests.FALLBACK_FIXTURE
MP3 = page_tests.MP3
MP4 = page_tests.MP4
OCR_LYRICS = page_tests.OCR_LYRICS
PRODUCT_HTML = page_tests.PRODUCT_HTML

#: 驱动脚本等一件事最多等多久。替身是毫秒级的；这个数只是「接线断了」那种实
#: 现的放弃点，不是判据阈值。
FLOW_TIMEOUT_MS = 30_000

#: node 整个跑完的上限（含服务往返）。
NODE_TIMEOUT_S = 120


# ====================================================================== 替身 CLI


#: 包装：按子命令挑模式，然后把活整个交给 Task 5 那份替身。
#:
#: 参数约定：`<Task 5 替身> <夹具> <退出码> <子命令> <歌曲目录> [其余]`。前三
#: 个由 `command=` 在调用现场注进去，后面的由 `runner` 自己拼。
E2E_DISPATCH_SOURCE = '''\
"""按子命令挑一个模式，然后把活整个交给 Task 5 那份替身 CLI。

自己一个字都不往 stdout 上写：输出格式的唯一来源是夹具。
"""
import runpy
import sys

FAKE, FIXTURE, CODE, INGEST_MODE = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
SUB = sys.argv[5]
MODE = INGEST_MODE if SUB == "ingest" else "product"

# Task 5 那份替身的参数约定：<夹具> <退出码> <模式> <子命令> <歌曲目录> …
sys.argv = [FAKE, FIXTURE, CODE, MODE] + sys.argv[5:]
runpy.run_path(FAKE, run_name="__main__")
'''


def _fake_command(
    tmp_path: Path, fixture: Path, code: int = 0, ingest_mode: str = "ocr"
) -> tuple[str, ...]:
    """装一份替身，返回 `AppState(command=…)` 要的那个前缀。

    `ingest_mode="none"` 表示这一次的 `ingest` **一行歌词都没认出来**——
    `cli.py:472` 那条真实分支（「一行都没认出来，请自己写 lyrics.txt」）在页面
    上的落点，见 `…the_page_asks_again_when_ingest_found_no_lyrics`。
    """
    fake = tmp_path / "fake_cli.py"
    fake.write_text(page_tests.FAKE_CLI_SOURCE, encoding="utf-8")
    dispatch = tmp_path / "e2e_dispatch.py"
    dispatch.write_text(E2E_DISPATCH_SOURCE, encoding="utf-8")
    return (
        sys.executable,
        str(dispatch),
        str(fake),
        str(fixture),
        str(code),
        ingest_mode,
    )


# ====================================================================== 替身 DOM

#: 从真实 HTML 里抽标签用的。属性值里的 `>` 由引号那两段吃掉。
_TAG_RE = re.compile(r"<([a-zA-Z][\w-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>")
_ID_RE = re.compile(r'\bid="([^"]+)"')
_HREF_RE = re.compile(r'\bhref="([^"]*)"')


def page_elements() -> dict[str, dict]:
    """真实 `index.html` 上带 id 的元素，连同它们的**初始状态**。

    初始状态（`hidden` / `disabled` / `open` / `href`）必须从页面里抽，不能给默认
    值：给了默认值，替身 DOM 就会在接线被删掉的时候装绿——见模块 docstring 第 2
    条。

    `open` 是收口评审 I4a 补的那一样：`<details id="detailBox">` 加一个 `open`
    属性此前**不会让任何东西变红**，而「`Bad things might happen` 不许出现在用户
    第一眼看到的地方」正是 Task 3.5 整棒的立身之本。抽出来之后，
    `test_clicking_the_why_button…` 里那句 `before["detailOpen"] is False` 才第一次
    有分辨力——在这之前它断的是替身自己写死的 `open: false`。
    """
    html = PAGE.read_text(encoding="utf-8")
    found: dict[str, dict] = {}
    for _tag, attrs in _TAG_RE.findall(html):
        match = _ID_RE.search(attrs)
        if match is None:
            continue
        href = _HREF_RE.search(attrs)
        found[match.group(1)] = {
            "hidden": re.search(r"(?<![\w-])hidden(?![\w-])", attrs) is not None,
            "disabled": re.search(r"(?<![\w-])disabled(?![\w-])", attrs) is not None,
            "open": re.search(r"(?<![\w-])open(?![\w-])", attrs) is not None,
            "href": href.group(1) if href else "",
        }
    return found


#: 替身 DOM + 驱动。**垫在页面脚本前面**，所以页面末尾那句
#: `document.addEventListener("DOMContentLoaded", boot)` 会真的把 boot 挂上。
DOM_DOUBLE_SOURCE = r"""
"use strict";
// ------------------------------------------------------------ 最小 DOM 替身
//
// 只提供页面真正用到的那几样。**不给任何"万能兜底"**：多给一样，就多一种
// 接线被删掉之后照样绿的坏法。

const CONFIG = JSON.parse(process.argv[2]);
const REAL_FETCH = globalThis.fetch;

const missingIds = [];      // boot() 问过、页面上却没有的 id
const openedWindows = [];   // window.open 的实参
const fetchLog = [];        // 页面真正发出去的请求

function makeElement(id, spec) {
  const listeners = Object.create(null);
  return {
    id: id,
    hidden: !!spec.hidden,
    disabled: !!spec.disabled,
    href: spec.href || "",
    open: !!spec.open,
    value: "",
    textContent: "",
    innerHTML: "",
    files: [],
    scrollTop: 0,
    clientHeight: 0,
    scrollHeight: 0,
    addEventListener: function (type, fn) {
      (listeners[type] || (listeners[type] = [])).push(fn);
    },
    scrollIntoView: function () {},
    __dispatch: function (type, event) {
      const fns = listeners[type] || [];
      if (fns.length === 0) {
        throw new Error(
          "派发 " + type + " 到 id=" + id + "，可它上面一个监听器都没有——"
          + "boot() 没把这个事件接上。"
        );
      }
      for (let i = 0; i < fns.length; i++) { fns[i](event || {}); }
    },
  };
}

const ELEMENTS = Object.create(null);
for (const id of Object.keys(CONFIG.elements)) {
  ELEMENTS[id] = makeElement(id, CONFIG.elements[id]);
}

const docListeners = Object.create(null);
globalThis.document = {
  // 浏览器在认不出 id 时给的是 null，这里照办：`boot()` 会当场 TypeError，
  // 而不是拿到一个万能空对象接着跑。
  getElementById: function (id) {
    if (!(id in ELEMENTS)) { missingIds.push(id); return null; }
    return ELEMENTS[id];
  },
  addEventListener: function (type, fn) {
    (docListeners[type] || (docListeners[type] = [])).push(fn);
  },
  __fire: function (type) {
    const fns = docListeners[type] || [];
    if (fns.length === 0) {
      throw new Error("document 上没有挂 " + type + " —— 页面脚本没把 boot 接上。");
    }
    for (let i = 0; i < fns.length; i++) { fns[i]({ type: type }); }
  },
};

globalThis.window = {
  open: function (url, target) { openedWindows.push([url, target]); },
};

// 页面里是同源相对路径（`fetch("/api/job")`），node 解析不了裸的 `/…`，
// 这里补上本机服务的前缀——**顺手把「只许同源相对路径」再断一次**。
globalThis.fetch = function (path, init) {
  if (typeof path !== "string" || path.charAt(0) !== "/") {
    throw new Error("页面往 " + path + " 发请求——本机壳子只许打同源相对路径。");
  }
  fetchLog.push(((init && init.method) || "GET") + " " + path);
  return REAL_FETCH(CONFIG.base + path, init);
};

// 只在走「传一份 lyrics.txt」那条路的驱动里给一个真能读的 FileReader；别的驱动
// 照旧一构造就抛——多给一样，就多一种接线被删掉之后照样绿的坏法。
//
// 自指检查（CONSTRAINTS 第 10 条方向一）：这个替身自己会不会装绿？
// 页面要是不给 `onload` 挂东西（读出来的歌词没有落点），这里**抛**，不是静默地
// 什么也不做——抛在 promise 里，node 以未处理的拒绝退出，`drive_page` 那条
// `returncode == 0` 当场红。
globalThis.FileReader = function () {
  if (!CONFIG.lyricsFile && !CONFIG.lyricsDrop) {
    throw new Error("这份驱动没走「传/拖一份 lyrics.txt」那条路，不该构造 FileReader。");
  }
  const self = this;
  this.onload = null;
  this.result = null;
  this.readAsText = function (file, encoding) {
    if (encoding !== "utf-8") {
      throw new Error(
        "页面读 lyrics.txt 用的编码是 " + encoding + "——不是 utf-8 的话，"
        + "中文歌词读进来就是乱码。"
      );
    }
    file.text().then(function (text) {
      self.result = text;
      if (typeof self.onload !== "function") {
        throw new Error(
          "页面没给 FileReader 挂 onload —— 文件读出来了，却没有任何落点。"
        );
      }
      self.onload({ target: self });
    });
  };
};

function E(id) {
  const el = document.getElementById(id);
  if (!el) { throw new Error("驱动脚本要的 id 不在页面上：" + id); }
  return el;
}

function snapshot() {
  return {
    missingIds: missingIds.slice(),
    opened: openedWindows.slice(),
    fetches: fetchLog.slice(),
    startDisabled: E("start").disabled,
    blocked: E("blocked").textContent,
    lyricsValue: E("lyrics").value,
    outer: E("outer").textContent,
    inner: E("inner").textContent,
    barsHtml: E("bars").innerHTML,
    progressHidden: E("progress").hidden,
    mainLogHtml: E("mainLog").innerHTML,
    omittedHidden: E("omitted").hidden,
    omittedText: E("omitted").textContent,
    detailLog: E("detailLog").textContent,
    detailOpen: E("detailBox").open,
    reviewHidden: E("review").hidden,
    ocrLyrics: E("ocrLyrics").value,
    finishedHidden: E("finished").hidden,
    resultHref: E("resultLink").href,
    failedHidden: E("failed").hidden,
    errorText: E("errorText").textContent,
  };
}

async function waitFor(what, predicate) {
  const deadline = Date.now() + CONFIG.timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) { return; }
    await new Promise(function (r) { setTimeout(r, 20); });
  }
  // **到点不是绿**：把当时的整份快照摆出来再炸。
  throw new Error(
    "等了 " + CONFIG.timeoutMs + " 毫秒还没等到「" + what + "」。此刻页面上是：\n"
    + JSON.stringify(snapshot(), null, 2)
  );
}

/** 点「查看原因 ▾」。只有主日志里**真的渲染出**那个按钮时才算点得着。 */
function whyClickEvent() {
  return {
    target: {
      closest: function (selector) {
        if (selector !== "[data-open-detail]") {
          throw new Error("点击委托用的选择器变成了 " + selector);
        }
        return E("mainLog").innerHTML.indexOf("data-open-detail") >= 0
          ? { __why: true } : null;
      },
    },
  };
}
"""

#: 驱动。接在页面脚本**后面**。
DRIVER_SOURCE = r"""
(async function main() {
  const steps = {};
  const media = new File(
    [Uint8Array.from(CONFIG.media.bytes)], CONFIG.media.name
  );

  document.__fire("DOMContentLoaded");
  steps.atBoot = snapshot();

  E("media").files = [media];
  E("media").__dispatch("change", {});
  steps.afterPick = snapshot();

  if (CONFIG.lyrics) {
    E("lyrics").value = CONFIG.lyrics;
    E("lyrics").__dispatch("input", {});
  }
  if (CONFIG.lyricsFile) {
    // 「传一份 lyrics.txt」：用户一个字都没往框里打，只挑了个文件。
    E("lyricsFile").files = [new File([CONFIG.lyricsFile], "lyrics.txt")];
    E("lyricsFile").__dispatch("change", {});
    await waitFor("「开始」按钮解锁", function () {
      return E("start").disabled === false;
    });
  }
  if (CONFIG.lyricsDrop) {
    // 「把 lyrics.txt 拖进这里」：文本框占位符上写着的那条路。
    // **`preventDefault` 是页面必须做的那一半**——不拦的话浏览器的默认行为是
    // 拿这个文件把整个页面顶掉，用户看到的是「拖进去，页面没了」。这里数一下
    // 页面拦了几次，两个事件各一次。
    let prevented = 0;
    const dropped = {
      preventDefault: function () { prevented++; },
      dataTransfer: { files: [new File([CONFIG.lyricsDrop], "lyrics.txt")] },
    };
    E("lyrics").__dispatch("dragover", dropped);
    E("lyrics").__dispatch("drop", dropped);
    await waitFor("「开始」按钮解锁", function () {
      return E("start").disabled === false;
    });
    steps.afterDrop = snapshot();
    steps.afterDrop.prevented = prevented;
  }
  steps.afterLyrics = snapshot();

  E("start").__dispatch("click", {});

  if (CONFIG.flow === "video" || CONFIG.flow === "video-no-lyrics") {
    await waitFor("核歌词区显示出来", function () {
      return E("review").hidden === false || E("failed").hidden === false;
    });
    steps.afterIngest = snapshot();
    // `video-no-lyrics`：OCR 一行都没认出来，用户什么都没填就点了继续。
    E("ocrLyrics").value = CONFIG.correctedLyrics;
    E("continue").__dispatch("click", {});
  }

  if (CONFIG.flow === "video-no-lyrics") {
    // 这条路走不到成品：服务端会回 `needs-lyrics`，页面该**重新问他要歌词**。
    await waitFor("页面重新开口要歌词", function () {
      return E("blocked").textContent !== "" || E("failed").hidden === false
        || E("finished").hidden === false;
    });
    steps.afterRun = snapshot();
  } else {
    await waitFor("成品区显示出来", function () {
      return E("finished").hidden === false || E("failed").hidden === false;
    });
    steps.afterRun = snapshot();
  }

  if (CONFIG.clickWhy) {
    E("mainLog").__dispatch("click", whyClickEvent());
    steps.afterWhyClick = snapshot();
  }

  console.log(JSON.stringify(steps));
})();
"""


# ====================================================================== 跑一趟


@pytest.fixture
def ffmpeg_on_path(tmp_path, monkeypatch):
    """`PATH` 最前面放一个真的可执行 `ffmpeg`。

    建任务那一步会硬拒没有 ffmpeg 的机器，而这台机器上装没装 ffmpeg 是**机器
    的性质**（CONSTRAINTS 第 9 条）。钉住之后，同一份测试在两种机器上验的是
    同一件事。

    跟 `test_web_page.with_ffmpeg` 的区别：那一份把 `PATH` 整个换掉，这一份只
    **前置**——本文件要在同一段 `PATH` 里找到 `node`。前置一样是钉死的：
    `shutil.which("ffmpeg")` 恒定命中这个假的。
    """
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    fake = bin_dir / "ffmpeg"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    import os

    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir


@pytest.fixture
def make_shell(tmp_path, ffmpeg_on_path):
    """起一个真服务（`songs_root` 在 `tmp_path` 下），返回它的客户端。"""
    made = []

    def factory(fixture: Path, code: int = 0, ingest_mode: str = "ocr"):
        index = len(made)
        songs_root = tmp_path / f"songs-{index}"
        songs_root.mkdir()
        sub = tmp_path / f"fake-{index}"
        sub.mkdir()
        client = page_tests._serve(
            tmp_path, songs_root, _fake_command(sub, fixture, code, ingest_mode)
        )
        made.append(client)
        return client

    yield factory
    for client in made:
        client._httpd.shutdown()
        client._thread.join(timeout=10)
        client._httpd.server_close()


def drive_page(
    tmp_path: Path,
    client,
    *,
    flow: str,
    filename: str,
    content: bytes,
    lyrics: str = "",
    lyrics_file: str = "",
    drop_lyrics_file: str = "",
    corrected_lyrics: str = "",
    click_why: bool = False,
) -> dict:
    """让**页面自己的 `boot()`** 在 node 里跑一趟，返回几个关键时刻的快照。

    `lyrics` 是往文本框里打字那条路；`lyrics_file` 是「传一份 lyrics.txt」那条
    （`#lyricsFile` 那个 input）；`drop_lyrics_file` 是「把 lyrics.txt 拖进
    文本框」那条（文本框占位符上写着的那个说法）。
    """
    config = {
        "base": f"http://127.0.0.1:{client.port}",
        "elements": page_elements(),
        "media": {"name": filename, "bytes": list(content)},
        "lyrics": lyrics,
        "lyricsFile": lyrics_file,
        "lyricsDrop": drop_lyrics_file,
        "correctedLyrics": corrected_lyrics,
        "flow": flow,
        "clickWhy": click_why,
        "timeoutMs": FLOW_TIMEOUT_MS,
    }
    script = tmp_path / f"drive-{flow}-{client.port}.js"
    script.write_text(
        DOM_DOUBLE_SOURCE + "\n" + page_tests._page_script() + "\n" + DRIVER_SOURCE,
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["node", str(script), json.dumps(config, ensure_ascii=False)],
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_S,
    )
    assert proc.returncode == 0, (
        "页面在 node 里没跑通（下面是它自己说的话）：\n"
        f"{proc.stderr}\n--- stdout ---\n{proc.stdout}"
    )
    steps = json.loads(proc.stdout)
    for name, snap in steps.items():
        assert snap["missingIds"] == [], (
            f"boot() 在 {name} 这一刻问了页面上没有的 id：{snap['missingIds']}"
        )
    return steps


def escaped(text: str) -> str:
    """页面 `escapeHtml()` 的对照实现（只用来在这里比对渲染结果）。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ====================================================================== 尺子本身


def test_the_fake_cli_replays_the_fixture_instead_of_a_hand_written_transcript():
    """替身 CLI 的输出**逐行来自夹具文件**，不是谁手打的一份理想格式。

    这是本计划预言的「第九次」正对着的那一条：替身的格式跟真 CLI 一脱钩，前
    面六棒的所有绿就都建立在一份想象的输出上。本文件不自己造替身，直接用
    Task 5 那一份——所以在这里钉一次「那一份仍然是重放夹具的」。
    """
    source = page_tests.FAKE_CLI_SOURCE
    assert 'for line in FIXTURE.read_text(encoding="utf-8").splitlines():' in source, (
        "Task 5 那份替身不再逐行重放夹具了。本文件全部的端到端断言都建立在"
        "「页面上看到的就是真 CLI 打过的那些字」上。"
    )
    assert "    print(line)" in source, "替身不再把夹具原样打出来了。"


def test_the_dispatcher_adds_no_output_of_its_own():
    """包装脚本一个字都不往 stdout 上写。

    它要是自己打一行，那一行就是一份「手打的理想输出」，而页面上的断言分不出
    哪些字来自夹具、哪些来自这里。
    """
    body = "\n".join(
        line
        for line in E2E_DISPATCH_SOURCE.splitlines()
        if not line.startswith('"""') and not line.startswith("自己一个字")
    )
    assert "print(" not in body, f"包装脚本里出现了输出语句：\n{E2E_DISPATCH_SOURCE}"
    assert "sys.stdout" not in body
    assert "sys.stderr" not in body


def test_the_dom_double_starts_from_the_pages_own_initial_state():
    """替身 DOM 的初值是从真实 `index.html` 里抽的，不是一律给「显示、可点」。

    这是 CONSTRAINTS 第 10 条 · 方向一（防护措施自己会不会犯它要防的那个错）
    的落点：替身 DOM 要是把四个 `<section>` 都初始化成显示的，「跑完之后成品
    区显示出来」这类断言就没了对照物。

    **实测过一遍，结论跟直觉不同**（2026-08-14）：把 `page_elements()` 的
    `hidden` 抽法改成恒 `False`、`index.html` 一个字不动，本文件 **7 条红**
    ——撒这个谎不会悄悄变绿，因为驱动脚本的 `waitFor` 谓词跟断言看的是同一批
    `hidden`，谎一撒每一次等待都立刻返回，下游成片塌掉。所以这一条的作用是
    **诊断**：它把那 7 条红一句话归因到「尺子坏了」，而不是让人去查页面。

    「开始」按钮同理：它在 HTML 里是 `disabled` 的，替身给成可点的话，
    「没歌词不让提交」那一条就白断了。
    """
    elements = page_elements()

    for id_ in ("progress", "review", "finished", "failed", "omitted"):
        assert elements[id_]["hidden"] is True, (
            f"`{id_}` 在 index.html 里本该是 hidden 的，抽出来却是 "
            f"{elements[id_]!r}。替身 DOM 会带着一个显示着的它开跑，"
            "于是「它显示出来了」这条断言在接线被删掉时照样绿。"
        )
    assert elements["start"]["disabled"] is True, (
        "「开始」按钮在 index.html 里本该是 disabled 的。"
    )
    assert elements["resultLink"]["href"] == "#", (
        "成品链接的初始 href 变了。它是「resultLink.href 有没有被接上」那条断言"
        "的对照物。"
    )
    assert elements["detailBox"]["open"] is False, (
        "详细区在 index.html 里本该是收起的（收口评审 I4a）。替身 DOM 会带着一个"
        "已经展开的它开跑，于是「点了『查看原因 ▾』才展开」那条断言变成永真。"
    )
    # 认不出 `hidden`／`disabled`／`open` 的抽法会让上面几条一起哑，所以再断一条
    # 反面：不带这几个属性的元素必须抽成 False。
    assert elements["mainLog"] == {
        "hidden": False,
        "disabled": False,
        "open": False,
        "href": "",
    }, (
        f"mainLog 抽出来是 {elements['mainLog']!r}——抽法把属性认宽了，"
        "上面那几条「本该是 hidden」的断言会跟着变成永真。"
    )


def test_the_page_under_test_is_the_file_the_server_hands_out():
    """node 里跑的那段脚本，来自**服务端真正发出去的那个文件**。

    抽出来跑的前提是「抽的是同一份文件」。判据在 `app.PAGE`——`GET /` 读的就
    是它（`app.py:222`），`test_web_page` 另有一条断 `GET /` 逐字节等于该文件。
    把本文件的 `PAGE` 指到一份副本上，这条会红。

    评审 Important 3：这条原先的第二句是
    `page_tests._page_script() in PAGE.read_text(...)`——而 `_page_script()` 正
    是从 `PAGE.read_text()` 里正则捕获出来的，**第一句成立时第二句不可能失败**。
    换成下面这条跟 `app.PAGE` 比的断言，它才有分辨力（变异检验见报告）。
    """
    from murripple.web import app

    assert PAGE == app.PAGE, (
        f"本文件测的是 {PAGE}，而服务端 `GET /` 发出去的是 {app.PAGE}——"
        "两份文件一旦分家，这里全部的页面守卫就都守着一个用户看不到的东西。"
    )


# ====================================================================== 音频全程


def test_the_audio_route_runs_end_to_end_through_the_page(make_shell, tmp_path):
    """判据主线：建任务 → 上传 → 歌词 → start → 轮询到完成 → 取结果。

    **每一步都是页面自己做的**：选文件、贴歌词、点开始、轮询、把成品链接摆出
    来。测试只负责派发用户动作和最后核对。

    末尾那次 `GET` 用的是**页面算出来的那个 href**——「取结果」这一步在页面上
    只是一个 `<a href>`，链接对不对只有从服务那一侧看得见。
    """
    client = make_shell(BUILD_FIXTURE)
    steps = drive_page(
        tmp_path,
        client,
        flow="audio",
        filename="我的 歌.mp3",
        content=MP3,
        lyrics="谁先眨眼就输\n第二句\n",
    )

    # —— 门禁：三个格子（什么都没选 / 选了音频没词 / 词也有了）——
    assert steps["atBoot"]["startDisabled"] is True, (
        "页面一打开「开始」就是可点的。boot() 末尾那次 refreshGate() 没接上。"
    )
    assert steps["afterPick"]["startDisabled"] is True, (
        "选了 mp3、一个字歌词都没有，「开始」却可以点了。"
    )
    assert "歌词" in steps["afterPick"]["blocked"], (
        f"拦住了却没说为什么：{steps['afterPick']['blocked']!r}"
    )
    assert steps["afterLyrics"]["startDisabled"] is False, (
        "歌词贴上了，「开始」还是点不动。"
    )
    assert steps["afterLyrics"]["blocked"] == "", (
        f"放行了却还留着一句拦阻理由：{steps['afterLyrics']['blocked']!r}"
    )

    final = steps["afterRun"]
    assert final["failedHidden"] is True, f"跑出错了：{final['errorText']}"
    assert final["progressHidden"] is False, "「正在做」那一段自始至终没显示出来。"
    assert final["finishedHidden"] is False, "跑完了，成品那一段没显示出来。"

    # —— 六条进度条：接线那一半 ——
    # 「亮几条」怎么算由 `test_web_page.py::test_the_progress_bars_follow_the_real_
    # _progress` 逐档核；这里核的是 `render()` 有没有把它接到 DOM 上。**页面上那
    # 六条的初值是全不亮**（HTML 里静态写着），所以那一行接线一删，这里就是 0。
    bars = final["barsHtml"]
    assert bars.count("<i ") == 6, f"跑完之后进度条不是六条：{bars}"
    assert bars.count(' on"') == 6, (
        f"跑完了，六条进度条没有全亮：{bars}。`render()` 里那行 `el.bars.innerHTML "
        "= renderBars(…)` 没接上的话，这里是页面静态初值（一条都不亮）。"
    )

    # —— 成品链接：页面算出来的那个，真的取得回产物 ——
    href = final["resultHref"]
    assert re.fullmatch(r"/api/job/[0-9a-f]{16}/result", href), (
        f"成品链接是 {href!r}——resultLink.href 没被接上（页面上它的初值是 `#`）。"
    )
    status, body, content_type = client.request("GET", href)
    assert status == 200, f"页面给的成品链接取不回东西：{status} {body!r}"
    assert "text/html" in content_type
    assert body.decode("utf-8") == PRODUCT_HTML
    assert final["opened"] == [[href, "_blank"]], (
        f"产物没有在新标签里自动打开一次：{final['opened']!r}"
    )


#: 「传一份 lyrics.txt」那条路上传的那份文本。**故意跟贴进文本框那条路的用词不
#: 同**，末尾也不带换行——盘上那份要是等于它，就只能是从这个文件里来的。
LYRICS_FILE_TEXT = "第一句从文件里来的\n第二句也是\n第三句没有末尾换行"


def test_a_lyrics_file_unlocks_the_start_button_and_reaches_the_server(
    make_shell, tmp_path
):
    """音频 + **传一份 lyrics.txt**（不是贴进文本框）：门开了，词也真送到了。

    README 与页面 label（`index.html:102/104`）都把「传一份 lyrics.txt」摆成跟
    「贴进文本框」平级的选项，而这条接线（`FileReader` → `el.lyrics.value` →
    `refreshGate()`）此前**一条测试都没有**（收口评审 I5）：替身 DOM 里的
    `FileReader` 是一构造就抛的桩，这条路根本走不进来。

    坏掉的样子很难看：用户传了 lyrics.txt、文本框也填上了内容，**「开始」却仍然
    灰着，旁边写着「需要歌词」**——一个自相矛盾的页面，而且没有任何东西会红。

    三处一起断，缺一处都能被蒙混过去：
    - 文本框真的被填上了（少了它，一个「不读文件、直接放行」的实现也绿）
    - 「开始」真的解锁了（这一条由驱动里的 `waitFor` 先钉住，拦阻理由也清空）
    - **盘上的 `lyrics.txt` 等于文件里那份文本**（少了它，一个只改按钮状态、
      却把空歌词发上去的实现也绿）
    """
    client = make_shell(BUILD_FIXTURE)
    steps = drive_page(
        tmp_path,
        client,
        flow="audio",
        filename="我的歌.mp3",
        content=MP3,
        lyrics="",
        lyrics_file=LYRICS_FILE_TEXT,
    )

    picked = steps["afterPick"]
    assert picked["startDisabled"] is True and "歌词" in picked["blocked"], (
        "选了 mp3、歌词一个字都还没有，「开始」就已经能点了——这条测试后面那半"
        f"（传了文件才解锁）会因此变成永真：{picked['blocked']!r}"
    )

    after = steps["afterLyrics"]
    assert after["lyricsValue"] == LYRICS_FILE_TEXT, (
        f"lyrics.txt 的内容没被填进文本框：{after['lyricsValue']!r}"
    )
    assert after["startDisabled"] is False, (
        "传了 lyrics.txt，「开始」还是灰的。"
    )
    assert after["blocked"] == "", (
        f"歌词已经有了，页面上还留着一句拦阻理由：{after['blocked']!r}"
    )

    final = steps["afterRun"]
    assert final["failedHidden"] is True, f"跑出错了：{final['errorText']}"
    assert final["finishedHidden"] is False, "跑完了，成品那一段没显示出来。"

    song_dirs = list(client.songs_root.iterdir())
    assert len(song_dirs) == 1, f"songs/ 下建出了 {song_dirs}"
    assert (song_dirs[0] / "lyrics.txt").read_text(encoding="utf-8") == (
        LYRICS_FILE_TEXT
    ), (
        "用户传的那份 lyrics.txt 没送到服务端——页面上门开了，管线拿到的却是"
        "另一份（或者空的）。"
    )


#: 拖进文本框那条路上的那份文本。**跟上面两条路的用词都不同**，末尾也不带换行
#: ——盘上那份要是等于它，就只能是拖进来的那个文件里的。
DROPPED_LYRICS_TEXT = "拖进来的第一句\n拖进来的第二句\n拖进来的第三句没有末尾换行"


def test_a_lyrics_file_dropped_on_the_textarea_lands_in_the_box(make_shell, tmp_path):
    """把 lyrics.txt **拖进文本框**：词真的进来了，页面也真的拦住了默认行为。

    这条守的是页面上的一句**承诺**——文本框的占位符写着「也可以把 lyrics.txt
    拖进这里」（定稿的措辞，于淼逐条给的）。浏览器**不会**自己把拖进来的文本
    文件填进 textarea：不接这两个事件的话，默认行为是拿那个文件把整个页面顶掉，
    用户看到的是「拖进去，进度页没了」。**占位符上写着而接线没有，就是页面在
    撒谎**（本仓 17a9cf5「别让页面撒谎」那一条）。

    三处一起断，缺一处都能被蒙混过去：
    - `preventDefault` 真的被调了两次（`dragover` 不拦，`drop` 根本不会来）
    - 文本框真的被填上了，「开始」真的解锁了
    - **盘上的 `lyrics.txt` 等于拖进来那份文本**（少了它，一个只改按钮状态、
      却把空歌词发上去的实现也绿）
    """
    client = make_shell(BUILD_FIXTURE)
    steps = drive_page(
        tmp_path,
        client,
        flow="audio",
        filename="我的歌.mp3",
        content=MP3,
        lyrics="",
        drop_lyrics_file=DROPPED_LYRICS_TEXT,
    )

    picked = steps["afterPick"]
    assert picked["startDisabled"] is True and "歌词" in picked["blocked"], (
        "选了 mp3、歌词一个字都还没有，「开始」就已经能点了——这条测试后面那半"
        f"（拖进来才解锁）会因此变成永真：{picked['blocked']!r}"
    )

    after = steps["afterDrop"]
    assert after["prevented"] == 2, (
        f"页面只拦下了 {after['prevented']} 次默认行为（该是 dragover 与 drop 各"
        "一次）。少拦哪一次，真浏览器里都是同一个结果：文件把页面顶掉。"
    )
    assert after["lyricsValue"] == DROPPED_LYRICS_TEXT, (
        f"拖进来的 lyrics.txt 没被填进文本框：{after['lyricsValue']!r}"
    )
    assert after["startDisabled"] is False, "拖进来了 lyrics.txt，「开始」还是灰的。"
    assert after["blocked"] == "", (
        f"歌词已经有了，页面上还留着一句拦阻理由：{after['blocked']!r}"
    )

    final = steps["afterRun"]
    assert final["failedHidden"] is True, f"跑出错了：{final['errorText']}"
    assert final["finishedHidden"] is False, "跑完了，成品那一段没显示出来。"

    song_dirs = list(client.songs_root.iterdir())
    assert len(song_dirs) == 1, f"songs/ 下建出了 {song_dirs}"
    assert (song_dirs[0] / "lyrics.txt").read_text(encoding="utf-8") == (
        DROPPED_LYRICS_TEXT
    ), (
        "用户拖进来的那份歌词没送到服务端——页面上门开了，管线拿到的却是另一份"
        "（或者空的）。"
    )


def test_every_line_the_cli_printed_is_on_the_page_somewhere(make_shell, tmp_path):
    """18 行真实输出，一行都不能在页面上消失——而且分层要分对。

    分层是**显示位置**，不是过滤器：主日志 + 详细区合起来逐行等于真实输出。
    这一条走的是页面上真实的 DOM 内容（`mainLog.innerHTML` 与
    `detailLog.textContent`），不是服务端的 JSON。
    """
    client = make_shell(BUILD_FIXTURE)
    steps = drive_page(
        tmp_path,
        client,
        flow="audio",
        filename="我的歌.mp3",
        content=MP3,
        lyrics="谁先眨眼就输\n",
    )
    final = steps["afterRun"]
    main_html = final["mainLogHtml"]
    detail = final["detailLog"]

    expected = BUILD_FIXTURE.read_text(encoding="utf-8").splitlines()
    assert len(expected) == 18, f"夹具变成了 {len(expected)} 行，这条测试的前提塌了。"
    missing = [
        line
        for line in expected
        if line.strip() and escaped(line) not in main_html and line not in detail
    ]
    assert not missing, (
        f"真实输出里有 {len(missing)} 行在页面上一个字都看不到：\n" + "\n".join(missing)
    )

    # 分层分对了没有：吓人的那句必须在折叠区里，进度那句必须在主日志上。
    scary = "Model was trained with torch 1.10.0+cu102, yours is 2.2.2."
    assert any(scary in line for line in expected), (
        "夹具里那句 torch 警告不见了——它是「第三方噪声进折叠区」这条断言的对象，"
        f"没有它下面两条会变成永真。夹具此刻是：\n" + "\n".join(expected)
    )
    assert scary in detail, "第三方那句吓人的话没落进折叠区。"
    assert scary not in main_html, (
        "第三方那句「Bad things might happen」跳到主日志上了——普通用户看到它会"
        "以为坏了。"
    )
    assert escaped("[5/5] 组装 timeline") in main_html, (
        f"进度行没进主日志。主日志此刻是：\n{main_html}"
    )

    # 18 行（其中 13 行主日志）没到 20 行的上限，那句「前面那 n 行收在下面的
    # 『详细输出』里」不该出现。
    assert final["omittedHidden"] is True, (
        f"一共才 18 行，页面却说省略了：{final['omittedText']!r}"
    )


def test_the_page_says_so_when_the_main_log_is_truncated(make_shell, tmp_path):
    """主日志超过 20 行时，页面上那句「前面那 n 行…」**真的出现**。

    评审在收口时点出：另外三份夹具是 18 / 12 / 2 行，`main_omitted` 恒为假，
    于是 `test_the_audio_route…` 里那句 `omittedHidden is True` **恰好等于该元
    素在 HTML 里的初值**——把 `boot()` 里 `el.omitted` 那两行整段删掉，一条都
    不会红。这条测试补的就是另一半：**「截尾了、页面说了」与「截尾了、页面没
    说」必须能区分。**

    夹具怎么来的：**`BUILD_LINES + RUN_LINES` 拼起来**，两份都是真跑抄来的原
    文，一行都不是手打的（下面那条断言逐行钉着这件事）。**说清它是什么**——
    这 30 行的**顺序**不是某一次真实运行，它是两次真实运行的首尾相接；这条测
    试只用它的**行数**，不依赖行与行之间的语义。想在这里手打一份「理想的 25
    行输出」正是本计划预言的第九次，所以没有那么做。
    """
    build_lines = BUILD_FIXTURE.read_text(encoding="utf-8").splitlines()
    run_lines = progress_tests.RUN_LINES
    lines = build_lines + run_lines
    pool = set(build_lines) | set(run_lines)
    assert all(line in pool for line in lines), (
        "拼出来的夹具里混进了不属于任何一份真实原文的行。"
    )

    fixture = tmp_path / "two-real-transcripts.txt"
    fixture.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")

    client = make_shell(fixture)
    steps = drive_page(
        tmp_path,
        client,
        flow="audio",
        filename="我的歌.mp3",
        content=MP3,
        lyrics="谁先眨眼就输\n",
    )
    final = steps["afterRun"]
    assert final["failedHidden"] is True, f"跑出错了：{final['errorText']}"

    # 主日志（我们自己打的那些行）确实超过了 20 行——**前提先立住**，
    # 不然下面两条会在「压根没截尾」的情况下变成永真。
    from murripple.web import app, progress

    main_count = sum(
        1 for line in lines if progress.classify(line) == progress.MAIN
    )
    assert main_count > app.LOG_TAIL_LINES, (
        f"拼出来的夹具只有 {main_count} 行主日志，没到 {app.LOG_TAIL_LINES} 行的"
        "上限——这条测试的前提塌了，它什么也证明不了。"
    )
    omitted = main_count - app.LOG_TAIL_LINES

    assert final["omittedHidden"] is False, (
        f"主日志有 {main_count} 行、只显示得下 {app.LOG_TAIL_LINES} 行，页面却"
        "一个字都没说。用户看不到的那 "
        f"{omitted} 行就这么无声无息地没了。"
    )
    assert str(omitted) in final["omittedText"], (
        f"页面说省略了，但没说省略了几行：{final['omittedText']!r}"
    )
    # 留下的确实是**最近**的 20 行：最早那行没了，最后那行在。
    assert escaped(lines[0]) not in final["mainLogHtml"], (
        "最早那行还在——主日志没有截尾，那句「前面那 n 行…」是空口说的。"
    )
    assert escaped(lines[-1]) in final["mainLogHtml"], "最后一行反而不见了。"


def test_an_early_degradation_pushed_out_of_the_window_is_still_on_the_page(
    make_shell, tmp_path
):
    """主日志第 1 行是一句降级、后面又来了 20 行以上 —— 那句降级**仍然读得到**。

    这是收口评审的 I1：滚动区截尾 20 行本身没错（spec 第五节要的就是它），错在
    被挤出去的那些行**当时不在任何一个响应里**——payload 没有 `log` 字段，
    `detail` 只有第三方噪声，页面那句路标当时写的是「前面还有 n 行」，而那 n 行
    谁也捡不回来。

    **这条路真实可达**：`cli.py:384-386` 的「以下 N 行未对上」后面**每一条未对上
    的歌词各占一个主日志行**，一首对得糟的歌 N=20+ 就能把开头的
    `[1/5] 分离音源：跳过（…）` 顶出去——恰恰是用户最需要回看早期降级的那一次。

    夹具是三段真实原文的首尾相接（见 `test_web_page._spliced_overflow_lines`），
    顺序不对应任何一次单独的真实运行；这条只用「第 1 行是降级」和「主日志超过 20
    行」两件事。
    """
    from murripple.web import app, progress

    lines = page_tests._spliced_overflow_lines()
    degraded = lines[0]

    # —— 尺子本身：这份输入真的是"第一行是一句会被挤出窗口的降级" ——
    assert lines.count(degraded) == 1, (
        f"{degraded!r} 在这份输入里出现了 {lines.count(degraded)} 次——"
        "下面那条「页面上找得到」会被后面那一份满足，而第一份丢没丢就看不出来了。"
    )
    assert progress.classify(degraded) == progress.MAIN, (
        f"{degraded!r} 不归主日志，它压根不会走截尾这条路。"
    )
    assert app.is_degraded(degraded), f"{degraded!r} 不算降级行，这条测试测错了东西。"
    main_lines = [ln for ln in lines if progress.classify(ln) == progress.MAIN]
    assert len(main_lines) - app.LOG_TAIL_LINES >= 1 and main_lines[0] == degraded, (
        f"这份输入的主日志是 {len(main_lines)} 行、第一行是 {main_lines[0]!r}——"
        "那句降级没有被挤出窗口，这条测试什么也证明不了。"
    )

    fixture = tmp_path / "spliced-transcripts.txt"
    fixture.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    client = make_shell(fixture)
    steps = drive_page(
        tmp_path,
        client,
        flow="audio",
        filename="我的歌.mp3",
        content=MP3,
        lyrics="谁先眨眼就输\n",
    )
    final = steps["afterRun"]
    assert final["failedHidden"] is True, f"跑出错了：{final['errorText']}"

    assert escaped(degraded) not in final["mainLogHtml"], (
        "那句降级还在滚动区里——主日志压根没截尾，这条测试证明不了「挤出去的行"
        "仍然读得到」。"
    )
    assert degraded in final["detailLog"], (
        f"主日志第 1 行那句降级 {degraded!r} 在页面上一个字都找不到了：滚动区里没有"
        "（被挤出去了），详细区里也没有。页面只说了句「前面那 n 行…」，而那几行"
        f"不在任何一处。详细区此刻是：\n{final['detailLog']}"
    )

    # —— 路标指的那块牌子，得真的叫那个名 ——
    #
    # 页面在同一屏里说两句话：滚动区下面那句「前面那 n 行收在下面的『X』里」，和
    # 折叠区自己的 `<summary>`。**两句话必须指同一个东西**——收口评审的原话是
    # 「别让页面开始撒谎，只是往下挪了一个元素」。断的是页面真的渲染出来的那句
    # 路标（`omittedText`）与真实 HTML 里那块牌子，中间没有第三份副本。
    signpost = re.search(r"「(.+?)」", final["omittedText"])
    assert signpost is not None, (
        f"路标那句话里没有指名任何一块牌子：{final['omittedText']!r}。"
        "用户被告知「前面那几行在别处」，却没被告知在哪儿。"
    )
    summary = re.search(r"<summary>(.*?)</summary>", PAGE.read_text(encoding="utf-8"))
    assert summary is not None, "页面上找不到折叠区的 `<summary>` 了。"
    assert signpost.group(1) in summary.group(1), (
        f"路标说那几行「收在下面的『{signpost.group(1)}』里」，而页面上那块牌子写的是"
        f"「{summary.group(1)}」——用户照着路标找不到东西。"
    )
    assert "通常不用看" not in summary.group(1), (
        f"折叠区还写着「通常不用看」：「{summary.group(1)}」。自从主日志超出滚动区的"
        "行也收进这一区，这句就不成立了——页面一边把用户往这儿指，一边告诉他不用看，"
        "而这一区默认还是收起的。"
    )


def test_the_page_asks_again_when_ingest_found_no_lyrics(make_shell, tmp_path):
    """OCR 一行都没认出来、用户直接点了继续 —— 页面**重新开口要歌词**。

    这是 `render()` 里 `needs-lyrics` 那个分支在页面上的落点，评审点出它此前
    **从未被驱动过**（三条流程都在 start 之前送过歌词，服务端不会回这个状态）。

    这条路是真实可达的：`cli.py:472` 的「一行都没认出来，请自己写 lyrics.txt」
    就是这种 ingest。此时 `sendLyrics("")` 会跳过、`start?stage=run` 拿到的是
    `NEEDS_LYRICS`——页面必须把话说回来让他补歌词，而**不是**报一个错、也不是
    卡在一个永不结束的进度条上。
    """
    client = make_shell(BUILD_FIXTURE, ingest_mode="none")
    steps = drive_page(
        tmp_path,
        client,
        flow="video-no-lyrics",
        filename="录屏.mp4",
        content=MP4,
        corrected_lyrics="",
    )

    mid = steps["afterIngest"]
    assert mid["reviewHidden"] is False, "ingest 跑完了，核歌词那一段没显示出来。"
    assert mid["ocrLyrics"] == "", (
        f"这一次 ingest 一行歌词都没写出来，框里却有东西：{mid['ocrLyrics']!r}"
    )

    final = steps["afterRun"]
    assert final["failedHidden"] is True, (
        f"「还差歌词」被当成错误报出来了：{final['errorText']!r}"
        "——那是一句该重新问的话，不是一次失败。"
    )
    assert final["finishedHidden"] is True, "什么都没做成，却把成品那一段亮出来了。"
    assert "歌词" in final["blocked"], (
        f"页面没有重新开口要歌词，用户对着一个不动的页面：{final['blocked']!r}"
    )
    assert final["startDisabled"] is False, (
        "页面要他补歌词，「开始」却是灰的——他补完了也点不动。"
    )
    assert "murripple ingest" not in final["blocked"], (
        "页面上出现了一句让用户去敲命令行的话。"
    )


def test_both_levels_of_progress_stand_side_by_side_on_the_page(make_shell, tmp_path):
    """两级进度**同时**摆在页面上，内层走完不会被外层顶掉。

    喂的是 `test_web_progress.REAL_RUN_STDOUT`——真跑抄来的一次完整 `run`，
    里面 `[5/5] 组装 timeline` 之后紧跟着 `[2/2] 打包`。**这正是「进度倒退」
    要发生的那一刻**：挤在一个格子里的实现，页面上会从 5 退回 2。

    两条断言必须一起立：只断外层的话，一个把两层写进同一个格子的实现照样绿。
    """
    fixture = tmp_path / "real-run-transcript.txt"
    fixture.write_text(progress_tests.REAL_RUN_STDOUT, encoding="utf-8")
    lines = progress_tests.REAL_RUN_STDOUT.splitlines()
    assert lines.index("[5/5] 组装 timeline") < lines.index("[2/2] 打包"), (
        "这份真实输出里内层收尾不在外层前进之前了，这条测试的前提塌了。"
    )

    client = make_shell(fixture)
    steps = drive_page(
        tmp_path,
        client,
        flow="audio",
        filename="我的歌.mp3",
        content=MP3,
        lyrics="谁先眨眼就输\n",
    )
    final = steps["afterRun"]
    assert final["outer"] == "[2/2] 打包", (
        f"外层那一行是 {final['outer']!r}。"
    )
    assert final["inner"] == "[5/5] 组装 timeline", (
        f"内层那一行是 {final['inner']!r}——外层前进之后内层被顶掉了，"
        "页面上看起来就是进度从 5 退回 2。"
    )


# ====================================================================== 降级


def test_clicking_the_why_button_really_opens_the_detail_region(make_shell, tmp_path):
    """「查看原因 ▾」点下去，折叠区**真的**展开。

    喂的是硬字幕退回那两行真实输出：第一行是原因（白名单认不出，落详细区），
    第二行是那句孤零零的「退回常规对齐。」（主日志，标成降级）。

    `test_web_page` 已经证过 `renderMainLog` 会渲染出那个按钮；**这一条证的是
    页面把点击接上了**——按钮渲染得再对，没人监听也还是点不开。
    """
    client = make_shell(FALLBACK_FIXTURE)
    steps = drive_page(
        tmp_path,
        client,
        flow="audio",
        filename="我的歌.mp3",
        content=MP3,
        lyrics="谁先眨眼就输\n",
        click_why=True,
    )
    reason, degraded = FALLBACK_FIXTURE.read_text(encoding="utf-8").splitlines()

    before = steps["afterRun"]
    assert "data-open-detail" in before["mainLogHtml"], (
        f"降级行旁边没有「查看原因」的入口。主日志此刻是：\n{before['mainLogHtml']}"
    )
    assert escaped(degraded) in before["mainLogHtml"]
    assert before["detailLog"] == reason, (
        f"那句「怎么修」没进详细区，点开是空的。详细区此刻是：{before['detailLog']!r}"
    )
    assert "删掉 lyrics.timing.json" in reason, (
        "夹具变了：这条测试指望第一行是带修复办法的那句。"
    )
    assert before["detailOpen"] is False, (
        "还没点，折叠区就已经是展开的——这条断言下面那一半会变成永真。"
    )

    after = steps["afterWhyClick"]
    assert after["detailOpen"] is True, (
        "点了「查看原因 ▾」，折叠区没展开。按钮渲染得再对也没用——"
        "boot() 里那个点击委托没接上。"
    )


# ====================================================================== 视频


def test_the_video_route_stops_for_a_lyrics_check_then_finishes(make_shell, tmp_path):
    """视频那条路：ingest 完停下来核歌词，改完点继续，跑到出成品。

    这一停是 M4 定的，不是可以优化掉的等待——OCR 会整行整行地漏。

    末尾断盘上的 `lyrics.txt`：**用户在核歌词框里改的那一份真的送到了服务端**。
    少了这一条，一个把 `sendLyrics(el.ocrLyrics.value)` 改成 `sendLyrics("")` 的
    实现会全绿（`lyrics.txt` 在 ingest 那一步已经有了，run 照样跑得完）。
    """
    corrected = "第一句 OCR 出来的\n第二句本来漏了的下半行\n第三句是我自己补的\n"
    client = make_shell(BUILD_FIXTURE)
    steps = drive_page(
        tmp_path,
        client,
        flow="video",
        filename="录屏.mp4",
        content=MP4,
        corrected_lyrics=corrected,
    )

    assert steps["afterPick"]["startDisabled"] is False, (
        "视频 + 空歌词被拦住了——歌词正是 ingest 要 OCR 出来的，"
        "拦了等于把整条路堵死。"
    )

    mid = steps["afterIngest"]
    assert mid["failedHidden"] is True, f"ingest 阶段就出错了：{mid['errorText']}"
    assert mid["reviewHidden"] is False, "ingest 跑完了，核歌词那一段没显示出来。"
    assert mid["ocrLyrics"] == OCR_LYRICS, (
        f"OCR 出来的歌词没被填进核对框，用户没法核行数。框里是：{mid['ocrLyrics']!r}"
    )
    assert mid["finishedHidden"] is True, (
        "还没核歌词就把成品那一段亮出来了——这一停被跳过了。"
    )

    final = steps["afterRun"]
    assert final["failedHidden"] is True, f"run 阶段出错了：{final['errorText']}"
    assert final["reviewHidden"] is True, "点了继续，核歌词那一段还留在页面上。"
    assert final["finishedHidden"] is False, "跑完了，成品那一段没显示出来。"

    song_dirs = list(client.songs_root.iterdir())
    assert len(song_dirs) == 1, f"songs/ 下建出了 {song_dirs}"
    assert (song_dirs[0] / "lyrics.txt").read_text(encoding="utf-8") == corrected, (
        "用户在核歌词框里改的那一份没送到服务端——页面拿着一份没人核过的 OCR "
        "结果就往下跑了。"
    )

    # 两个阶段都由页面自己发起，而且是 ingest 在前、run 在后。
    starts = [
        re.sub(r"[0-9a-f]{16}", "<id>", f)
        for f in final["fetches"]
        if "/start" in f
    ]
    assert starts == [
        "POST /api/job/<id>/start?stage=ingest",
        "POST /api/job/<id>/start?stage=run",
    ], f"页面发出去的两次 start 不是「先 ingest 后 run」：{starts}"


# ====================================================================== 降级白名单
#
# 上面那条走的是「退回常规对齐。」一条真实降级，证的是**那根管子端到端通着**。
# 白名单里另外 11 个词有没有过期，管子是看不出来的——收口的时候查了一遍：
# `DEGRADED_MARKERS` 与 `is_degraded` 此前**一条测试都没有直接引用过**
# （`grep -rn "DEGRADED_MARKERS\|is_degraded" tests/` 一个结果都没有）。
# 判据「每一条降级说明都在页面上看得见」有一半是靠这张表的，所以在这里补上。


def _printable_literals(path: Path) -> list[str]:
    """一个模块里**会被打出来的**字符串字面量。

    用 `ast` 而不是读全文：注释根本不进 AST，docstring 在这里单独剔掉。
    f-string 的固定段是 `JoinedStr` 里的 `Constant`，`ast.walk` 照样走得到。

    **为什么非这么做不可**（评审 Important 2）：`marker in 源码全文` 对多来源
    的词几乎是永真的——`退回` 在 `cli.py` 里有三处，只有 `:436` 是真正的
    `print("  退回常规对齐。")`，另两处是注释（`:161`）和 docstring（`:431`）。
    按全文断的话，**管线把那句 print 改成别的措辞，守卫照样绿**，而页面从此不
    再标那种降级——这条守卫要防的正是这件事。
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))

    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_every_degraded_marker_is_still_something_the_pipeline_really_prints():
    """白名单里每一个词，此刻仍然长在管线**真会打出来的字符串**里。

    `app.DEGRADED_MARKERS` 每条后面都标着 `cli.py` / `scan.py` 的出处。抄来的
    东西会过期：管线哪天把「退回常规对齐。」改成别的措辞，这张表**不会红**，
    它只会开始认一句再也没人打过的话，而真正的降级从此在页面上不再被标出来。

    **只认字符串字面量，不认注释与 docstring**（见 `_printable_literals`）。
    变异检验做的正是评审要求的那一种：把 `cli.py:436` 那句 print 的措辞改掉、
    注释和 docstring 一个字不动，这条必须红。

    条数也钉住：只遍历这张表的话，**删掉一条不会有任何东西变红**（CONSTRAINTS
    怀疑视角第 7 条：参数集由被测数据自己推导出来，删空了照样绿）。要加要减都
    得连着这个数一起改，那就是一次明摆着的决定。

    这个数的历次改动，一次一行：

    - 12 → 13：加 `"听不了："`（`cli.py::transcribe`，WhisperX 装不上／加载不
      了）。听写失败那一行原先**不算降级**——同一块主日志里，「退回常规对齐。」
      是红的、挂着「查看原因 ▾」，而「听不了：…」是白的、什么都不挂。两句话的
      性质完全一样，页面上的待遇却不一样，这是一处有意留下的不一致。
    - 13 → 14：加 `"一个字都没听出来"`（`cli.py::transcribe` 的
      「一个字都没听出来，请自己写 lyrics.txt」，WhisperX 跑起来了却一个字都没
      转出来，同样紧跟着 `return 1`）。它是上一条的兄弟句，同一条路、同一个结
      局，上次只补了前者。注意白名单里那条 `"一行都没认出来"` 是 OCR 那条路
      （`cli.py::ocr`）的话，跟这句**不是同一个字符串**，一个字都对不上——它长
      得像，所以很容易以为已经管住了。
    """
    from murripple.web import app

    literals = _printable_literals(REPO_ROOT / "murripple" / "cli.py") + (
        _printable_literals(REPO_ROOT / "murripple" / "ingest" / "scan.py")
    )
    assert literals, "一个字符串字面量都没抽出来——尺子坏了，下面那圈会全绿。"

    assert len(app.DEGRADED_MARKERS) == 14, (
        f"白名单从 14 条变成了 {len(app.DEGRADED_MARKERS)} 条。"
        "改这张表是在改「哪些行会被标成降级」——请连着这个数一起改，"
        "顺便说清新增/删掉的那条对应 cli.py 的哪一句。"
    )
    for marker in app.DEGRADED_MARKERS:
        assert any(marker in text for text in literals), (
            f"白名单里的 {marker!r} 已经不在 murripple/cli.py 与 ingest/scan.py "
            "任何一句会被打出来的话里了（注释和 docstring 不算数）。它认的那句"
            "话改了措辞——从此那种降级在页面上不再被标出来，而这张表不会红。"
        )


def test_a_real_skip_line_is_degraded_and_a_plain_progress_line_is_not():
    """正反各一条，都取自真跑抄来的原文。

    只断正面的话，一个 `return True` 的实现会把每一行都挂上「查看原因 ▾」——
    页面上满屏都是入口，等于一个都没有。
    """
    from murripple.web import app

    skip_line = next(ln for ln in progress_tests.RUN_LINES if "跳过（" in ln)
    plain_line = next(ln for ln in progress_tests.RUN_LINES if ln == "[2/5] 读取分轨")

    assert app.is_degraded(skip_line), f"这句降级没被认出来：{skip_line!r}"
    assert not app.is_degraded(plain_line), (
        f"一句普通的进度行被标成了降级：{plain_line!r}"
    )


# ====================================================================== 出错


def test_a_failing_run_shows_the_tail_verbatim_on_the_page(make_shell, tmp_path):
    """子进程非零退出：页面上摆出它自己说的话，**一个字不包装**。

    页面那一段的标题是「停在这里了」，正文是 `errorText`。这条走的是真实的
    `boot()` → `fail()` → `errorText.textContent` 这条线。
    """
    client = make_shell(BUILD_FIXTURE, code=3)
    steps = drive_page(
        tmp_path,
        client,
        flow="audio",
        filename="我的歌.mp3",
        content=MP3,
        lyrics="谁先眨眼就输\n",
    )
    final = steps["afterRun"]
    assert final["failedHidden"] is False, "跑挂了，「停在这里了」那一段没显示出来。"
    assert final["finishedHidden"] is True, "跑挂了却把成品那一段亮出来了。"

    last = BUILD_FIXTURE.read_text(encoding="utf-8").splitlines()[-1]
    assert last in final["errorText"], (
        f"尾部原文没透到页面上。页面上是：{final['errorText']!r}"
    )
    assert "处理失败" not in final["errorText"], "原话被包了一层。"
    assert final["opened"] == [], "跑挂了还去开了一个新标签。"
