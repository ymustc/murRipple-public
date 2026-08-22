"""前端单页与它背后的六个 HTTP 端点。

## 页面的 JS 是**跑**出来的，不是 grep 出来的

`murripple/web/static/index.html` 里那段 `<script>` 全部是顶层函数声明，
只有最后一行碰 DOM（`if (typeof document !== "undefined")`）。于是这份测试
可以把整段脚本原样抽出来丢给 `node` 跑，**调的是页面自己那几个函数**，不是
一份抄过来的副本。

为什么非要跑：判据里「音频没歌词不让提交」「降级行旁边有查看原因的入口」这
两条，用 `assert "查看原因" in html` 是断不出来的——**一个把这四个字写死在
页面上、跟任何状态都不挂钩的实现，那条断言照样绿**。这正是本仓栽过九次的形
状（CONSTRAINTS「断言本身没写错，但它跑的那个配置恰好不暴露问题」）。

`node` 是**硬依赖**，不 skip：`tests/test_decode_parity.py` 早就无条件调它
（渲染器那 243 条测试也要它），这台机器上没有 node 的话，本仓的测试本来就跑
不全。skip 是绿色的一种（CONSTRAINTS 怀疑视角第 7 条）。

## 端点走真服务，不走「直接调函数」

全部用 `http.client` 打真实的 `ThreadingHTTPServer`（**端口 0**，让内核挑，
所以并行跑也不会撞——`test_web_server.py` 那几条固定 8731/8732 的用例不在此
列）。理由：路由、`Content-Length` 读法、`X-Filename` 的百分号编码、状态码、
**消毒到底有没有被调用**，这几样只有从网络那一侧才看得见。

## 一个测试都不许碰仓内真实的 `songs/`

同 `test_web_jobs.py` / `test_web_runner.py`：全部走 `tmp_path` +
`AppState(songs_root=…)`。
"""

from __future__ import annotations

import http.client
import json
import re
import subprocess
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
PAGE = REPO_ROOT / "murripple" / "web" / "static" / "index.html"

#: 真跑抄来的两份原文。**不许在这里手打一份「理想输出」**（CONSTRAINTS 预言
#: 的那个「第九次」）。
BUILD_FIXTURE = FIXTURE_DIR / "real-build-output.txt"
FALLBACK_FIXTURE = FIXTURE_DIR / "real-fallback-output.txt"


def _page_html() -> str:
    return PAGE.read_text(encoding="utf-8")


# ================================================================ 零外链守卫
#
# 「零外链」不止 `<script src="https://…">` 一种。下面这张表是这条守卫**认得
# 的全部形式**；认不得的写在 `test_web_page.py` 的报告里（task-5-report.md
# 「零外链守卫覆盖哪些形式、漏哪些」一节），不假装覆盖全集。

#: 任何带 scheme 或协议相对的属性值都算外链。`src`/`href` 之外还列了
#: `srcset`（`<img srcset>` 绕过 `src`）、`data`（`<object data>`）、
#: `action`（`<form action>`）、`poster`（`<video poster>`）。
_URL_ATTRS = "src|href|srcset|data|action|poster|formaction|content"
_ATTR_RE = re.compile(rf'\b(?:{_URL_ATTRS})\s*=\s*"([^"]*)"', re.IGNORECASE)
_SCHEME_RE = re.compile(r"^\s*[a-zA-Z][a-zA-Z0-9+.\-]*:")

#: 会把资源从别处拉过来的标签，一个都不许有（`iframe` 同时也是「不做 iframe
#: 嵌入产物」那条判据的守卫）。
_FORBIDDEN_TAGS = ("<iframe", "<object", "<embed", "<base ", "<base>")

#: 会把请求发到别处的 JS 入口。页面只用 `fetch`，而 `fetch` 的目标另有断言。
_FORBIDDEN_JS = (
    "XMLHttpRequest",
    "WebSocket",
    "EventSource",
    "sendBeacon",
    "importScripts",
    "serviceWorker",
    "import(",
    ".src =",
    ".src=",
)


#: CSS 里的 `url(…)` 目标。抽成函数是为了让「尺子本身」验得着——页面里当下一个
#: `url(` 都没有，这一轮**循环体从未进入**（CONSTRAINTS 怀疑视角第 7 条：一个可能
#: 不存在的扫描目标，等于一个默认通过的分支），而 CSS 外链恰恰只有它在管。
_CSS_URL_RE = re.compile(r"url\(\s*['\"]?([^)'\"]*)")


def _external_css_urls(text: str) -> list[str]:
    """`text` 里指向外部的 `url(…)` 目标。同源相对路径不算。"""
    return [
        target
        for target in _CSS_URL_RE.findall(text)
        if _SCHEME_RE.match(target) is not None or target.startswith("//")
    ]


#: 已知有毒的两份样本，专门喂给上面那把尺子。**不是页面的一部分**——它们证的是
#: 「真出现一个外链 `url(`，这把尺子认得出来」，照 `test_web_server.py:247` 的对照
#: 组、`test_web_progress.py:89` 的夹具自检、`test_web_e2e.py:1020` 的字面量池非空
#: 那三处的写法。
#: （样本, 它里面那个外部地址）。**期望值写死在这里**，不拿被测的那个正则算——
#: 拿它算的话，正则被改坏时这一条会以 `IndexError` 的面目红，而不是以「尺子放过
#: 了一个外链」的面目红，两者的诊断成本差得很远。
_POISONED_CSS = (
    ('body { background: url("https://evil.example/bg.png"); }',
     "https://evil.example/bg.png"),
    ("@font-face { src: url(//evil.example/f.woff2); }",
     "//evil.example/f.woff2"),
)


def test_the_css_url_scan_can_actually_catch_an_external_url():
    """先验尺子：一份有毒的 CSS 喂进去，这把尺子必须认得出来。

    页面里当下**一个 `url(` 都没有**，所以
    `test_the_page_pulls_nothing_from_the_network` 的第 ④ 轮循环体一次都不执行——
    它此刻是一个默认通过的分支（收口评审 I4b）。把那一轮的正则或判据改坏，页面那
    一侧不会有任何反应；这一条会。
    """
    for sample, target in _POISONED_CSS:
        assert _external_css_urls(sample) == [target], (
            f"这把尺子放过了 {sample!r} 里的 {target!r}——`test_the_page_pulls_"
            "nothing_from_the_network` 的第 ④ 轮从此什么也挡不住，而页面里一个 "
            "`url(` 都没有，那边不会有任何征兆。"
        )
    assert not _external_css_urls("background: url(./local.png);"), (
        "同源相对路径也被当成外链了——这把尺子会在正常页面上误报。"
    )


def test_the_page_pulls_nothing_from_the_network():
    """页面零外链：没有 CDN、没有外部字体、没有 fetch 到第三方。

    六种形式各断一条（变异检验逐条做过，见报告）：绝对 URL、协议相对
    `//host`、`@import`、`url(scheme:…)`、带 scheme 的属性值、非 `fetch` 的
    网络入口。**只挡 `<script src="https://` 的守卫在别的五种上是全绿的。**
    """
    html = _page_html()

    # ① 绝对 URL——出现在任何位置都算，包括注释和 JS 字符串。
    for scheme in ("http://", "https://", "ftp://", "ws://", "wss://"):
        assert scheme not in html, (
            f"页面里出现了绝对 URL（{scheme}…）。零外链这条是按「文件里一个"
            f"远程地址都没有」守的，出现即失守。"
        )

    # ② 协议相对：`//cdn.example.com/x.js` 会跟着页面的 scheme 走。
    for value in _ATTR_RE.findall(html):
        assert not value.strip().startswith("//"), (
            f"属性值 {value!r} 是协议相对地址，会去外部主机取东西。"
        )
        # ⑤ 带 scheme 的属性值（`javascript:` 也一并挡掉）。
        assert _SCHEME_RE.match(value) is None, (
            f"属性值 {value!r} 带 scheme。页面上的每一个地址都必须是同源相对路径。"
        )

    # ③ CSS 的 `@import`：不带任何标签，前两条都看不见它。
    assert "@import" not in html, (
        "页面里有 `@import`。它在样式表里拉外部 CSS，`<link>` 那条守卫看不见它。"
    )

    # ④ `url(...)` 里的远程地址（背景图、字体）。**这一轮当下扫不到任何东西**
    # （页面里一个 `url(` 都没有），尺子本身由
    # `test_the_css_url_scan_can_actually_catch_an_external_url` 单独验。
    external = _external_css_urls(html)
    assert not external, f"CSS 的 url({external!r}) 指向外部地址。"

    # ⑥ 其它网络入口 + 会把资源拉进来的标签。
    for needle in _FORBIDDEN_JS:
        assert needle not in html, (
            f"页面里出现了 {needle!r}。这条路子绕得开 `fetch` 那条断言。"
        )
    for tag in _FORBIDDEN_TAGS:
        assert tag not in html.lower(), f"页面里出现了 {tag!r}。"

    # ⑦ `fetch` 的目标必须是同源相对路径。
    targets = re.findall(r"fetch\(\s*([`'\"])([^`'\"]*)", html)
    assert targets, "页面里一个 fetch 都没有——它得跟本机的端点说话。"
    for _quote, target in targets:
        assert target.startswith("/"), (
            f"fetch 的目标 {target!r} 不是以 `/` 开头的同源路径。"
        )


def test_the_result_opens_in_a_new_tab_and_is_never_embedded():
    """跑完直接开浏览器打开产物，不做 iframe 嵌入（spec 第七节）。"""
    html = _page_html()
    assert "<iframe" not in html.lower()
    assert 'target="_blank"' in html, (
        "页面上没有一个 `target=\"_blank\"` 的入口，产物打不开。"
    )
    assert "/result" in html, "页面上没有指向产物端点的地址。"


def test_the_page_says_the_audio_route_needs_lyrics():
    """裁定 D：W1 音频路线歌词必填，页面上要写明两种给法。

    **2026-08-14 订正（换视觉层那一棒）**：这条原先是
    `assert "需要歌词" in html`。任务书预判它会被新措辞（「上传音频需要搭配
    歌词」）打破，**实测没有打破——它照样绿**。原因是 `需要歌词` 在这个文件里
    有**两个来源**：歌词那句 label 是一个，`blockedReason()` 里那句「需要歌词
    （贴文本或传 lyrics.txt）。」是另一个。**把 label 整句删掉，那条断言也不会
    红**（MGMT 第七节「断言命中的字符串来自被测对象里的另一段数据」）。

    换成两条各只有一个来源的：
    - label 上那句原文（只出现在 label 里）
    - 「另一种给法」现在写在文本框的 placeholder 里（原先那行 `<label
      for="lyricsFile">` 已按定稿删掉，`#lyricsFile` 这个 input 仍在）。
      **从 `<textarea>` 那个标签里抠出来断**，不是在整份 HTML 里搜
      `lyrics.txt`——后者在这个文件里有四个来源（placeholder、aria-label、
      `accept=`、`blockedReason`），搜得到证明不了页面上写着它。
    """
    html = _page_html()
    assert "上传音频需要搭配歌词" in html, (
        "歌词那句 label 不再写明「上传音频需要搭配歌词」——音频路线歌词必填这条"
        "从页面上消失了，用户只会在点不动「开始」的时候才发现。"
    )

    tag = re.search(r'<textarea\b[^>]*id="lyrics"[^>]*>', html)
    assert tag is not None, "页面上找不到 `<textarea id=\"lyrics\">` 了。"
    placeholder = re.search(r'placeholder="([^"]*)"', tag.group(0))
    assert placeholder is not None and "lyrics.txt" in placeholder.group(1), (
        f"文本框的占位符里没写「传/拖一份 lyrics.txt」这条给法：{tag.group(0)}。"
        "那行 label 删掉之后，这是页面上唯一还说得出第二种给法的地方。"
    )


def test_the_detail_region_starts_collapsed():
    """详细输出**默认收起**（Task 3.5 整棒的立身之本）。

    那一区里躺着 `Bad things might happen` ×2 —— 普通用户第一眼看见它会以为坏了。
    「不出现在用户第一眼看到的地方」这条判据此前**一条守卫都没有**：给
    `<details id="detailBox">` 加一个 `open` 属性，全仓不会有任何东西变红
    （收口评审 I4a）。

    这里断的是 HTML 上那个属性；**行为那一半**在
    `test_web_e2e.py::test_clicking_the_why_button_really_opens_the_detail_region`
    的 `before["detailOpen"] is False` —— 替身 DOM 的 `open` 初值现在也从这份
    HTML 里抽（`page_elements()`），加了 `open` 那一条也会跟着红。
    """
    tag = re.search(r'<details\b[^>]*id="detailBox"[^>]*>', _page_html())
    assert tag is not None, (
        "页面上找不到 `<details id=\"detailBox\">` 了——详细区换了个形状，"
        "这条守卫会变成永真（`re.search` 找不到就什么也没断）。"
    )
    assert re.search(r"(?<![\w-])open(?![\w-])", tag.group(0)) is None, (
        f"详细区默认是展开的：{tag.group(0)}。"
        "折叠区里那两句 `Bad things might happen` 会直接落在用户第一眼看到的地方。"
    )


def test_the_page_routes_every_suffix_the_server_accepts(tmp_path):
    """页面的 `routeOf()` 与服务端的 `jobs.route_for()` 认同一张表。

    同一张后缀表在这个分支里有**四份**：管线两份（`cli.AUDIO_SUFFIXES` +
    `ingest.scan.VIDEO_SUFFIXES`）、`jobs.py` 一份、页面 JS 两个数组、以及
    `<input accept=…>`。管线↔`jobs.py` 那一对有守卫
    （`test_web_jobs.py::test_the_accepted_suffixes_still_match_the_pipeline`），
    **页面那两份此前一条测试都没有**（收口评审 I3）。

    漂掉的后果：管线加 `.ogg` → 既有守卫逼着 `jobs.py` 跟上 → 服务端此后完全接受
    `.ogg`，而页面 `routeOf()` 返回 `null`、`blockedReason` 回「先选一个音频或视频
    文件。」→ **开始按钮永久灰着，页面对一个服务端明明接受的文件说了句假话**。全绿。

    **断行为不断数组**：两个 JS 数组只是页面认路的原料，判据是「页面认的路跟服务端
    认的路一样」。大小写各喂一份——`routeOf` 与 `route_for` 都该先小写化。
    """
    from murripple.web import jobs

    suffixes = jobs.AUDIO_SUFFIXES + jobs.VIDEO_SUFFIXES
    assert suffixes, (
        "服务端一个后缀都不认了——下面那一圈会一次都不执行，于是默认通过"
        "（CONSTRAINTS 怀疑视角第 7 条）。"
    )
    names = [f"我的歌{suffix}" for suffix in suffixes]
    names += [f"我的歌{suffix.upper()}" for suffix in suffixes]

    got = json.loads(
        _run_page_js(
            tmp_path,
            "console.log(JSON.stringify(%s.map(routeOf)));"
            % json.dumps(names, ensure_ascii=False),
        )
    )
    expected = [jobs.route_for(name) for name in names]
    mismatched = [
        (name, page, server)
        for name, page, server in zip(names, got, expected)
        if page != server
    ]
    assert not mismatched, (
        "页面认的路跟服务端认的路对不上（文件名, 页面, 服务端）："
        f"{mismatched}。页面上那两个 JS 数组跟 `murripple/web/jobs.py` 漂开了——"
        "服务端收得下的文件，页面上「开始」按钮是灰的。"
    )


def test_the_file_picker_offers_every_suffix_the_server_accepts():
    """`<input accept=…>` 那一份也是同一张表。

    它漂掉的后果比 JS 数组更早：文件选择器里**根本挑不出来**那个文件，用户连
    「开始按钮是灰的」都看不到。
    """
    from murripple.web import jobs

    tag = re.search(r'<input\b[^>]*id="media"[^>]*>', _page_html())
    assert tag is not None, "页面上找不到 `<input id=\"media\">` 了。"
    accept = re.search(r'accept="([^"]*)"', tag.group(0))
    assert accept is not None, (
        f"选文件那个框没有 accept 属性了：{tag.group(0)}"
    )
    offered = tuple(part.strip() for part in accept.group(1).split(",") if part.strip())
    assert offered == jobs.AUDIO_SUFFIXES + jobs.VIDEO_SUFFIXES, (
        f"文件选择器给的是 {offered}，服务端收的是 "
        f"{jobs.AUDIO_SUFFIXES + jobs.VIDEO_SUFFIXES}。"
    )


def test_no_file_picker_shows_the_browser_english_button():
    """每个 `<input type=file>` 都被一个中文 `<label for=…>` 顶着。

    原生控件的按钮文案（Chrome 上 `Choose File / No file chosen`）**CSS 改不掉**
    ——`::file-selector-button` 能改样式、改不了那几个字。中文页面上摆两个英文
    控件，于淼 2026-08-14 当场指出来了。

    修法是把原生控件收进 `.sr`、用 `<label for=…>` 顶上去（点 label 开选择器是
    浏览器的原生行为，不用接 JS）。这条守卫钉的是**那个修法还在**，不是文案本身：
    只断「页面上有『选择文件』四个字」是没用的——把 `.sr` 摘掉、原生控件重新
    露出来，那四个字照样在，断言照样绿。所以逐个 input 核三件事。
    """
    html = _page_html()
    inputs = re.findall(r'<input\b[^>]*type="file"[^>]*>', html)
    assert len(inputs) == 2, (
        f"页面上的文件选择器从 2 个变成了 {len(inputs)} 个。新增的那个也要照这条守卫办：\n"
        + "\n".join(inputs)
    )
    for tag in inputs:
        ident = re.search(r'id="([^"]+)"', tag)
        assert ident is not None, f"文件选择器没有 id，label 就没法 `for` 它：{tag}"
        name = ident.group(1)

        classes = re.search(r'class="([^"]*)"', tag)
        assert classes is not None and "sr" in classes.group(1).split(), (
            f"`#{name}` 没有 `.sr`——原生控件露在外面，用户会看到 "
            f"`Choose File / No file chosen`。实际：{tag}"
        )

        # 必须认 `class` 里带 `filepick` 的那一个，**不能只按 `for=` 找**：
        # 每个选择器上面还有一句描述性的 `<label for=…>`，它排在前面、而且天然
        # 带汉字。第一版这里写的是「找到任意一个 `for=` 它的 label」——把顶上去
        # 的按钮整个换成英文，断言照样绿，因为它命中的是那句描述文字。
        # （变异检验当场逮住。这是本仓那条「断言命中的字符串来自被测对象里的
        # 另一段数据」，2026-08-14 一天之内第三次。）
        label = re.search(
            r'<label\b[^>]*\bclass="[^"]*\bfilepick\b[^"]*"[^>]*\bfor="%s"[^>]*>(.*?)</label>'
            % re.escape(name),
            html,
            re.S,
        )
        assert label is not None, (
            f"`#{name}` 被 `.sr` 藏起来了，却没有 `<label class=\"filepick\" for=\"{name}\">` "
            f"顶上去——这个选择器现在既看不见、也点不开。"
        )
        assert re.search(r"[一-鿿]", label.group(1)), (
            f"顶 `#{name}` 的那个 label 里一个汉字都没有，用户看到的还是英文："
            f"{label.group(1)!r}"
        )


def test_the_review_notice_is_about_line_count_not_typos():
    """视频那条路停下来之后，写明要核的是什么（spec 第三节 B）。"""
    assert "要核的是行数与内容，不是只改错字" in _page_html()


# ================================================================ 页面 JS
#
# 抽出 `<script>` 原样丢给 node 跑。**调的是页面自己那几个函数。**

_SCRIPT_RE = re.compile(r"<script>(.*?)</script>", re.DOTALL)


def _page_script() -> str:
    scripts = _SCRIPT_RE.findall(_page_html())
    assert len(scripts) == 1, (
        f"页面里有 {len(scripts)} 段内联脚本，这份测试只会跑第一段——"
        "拆成多段的话有一段会悄悄不被测。"
    )
    return scripts[0]


def _run_page_js(tmp_path: Path, driver: str) -> str:
    """把页面脚本 + 一段驱动代码丢给 node，返回它的 stdout。"""
    path = tmp_path / "page-under-test.js"
    path.write_text(_page_script() + "\n" + driver, encoding="utf-8")
    proc = subprocess.run(
        ["node", str(path)], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, (
        f"node 跑页面脚本失败（页面脚本必须在没有 document 的环境里也能求值）：\n"
        f"{proc.stderr}"
    )
    return proc.stdout


def test_the_page_script_evaluates_without_a_dom(tmp_path):
    """脚本在没有 `document` 的环境里能整段求值。

    这是下面几条 node 用例的**前提**，单独立一条：前提塌了的话，下面那几条会
    以「node 跑失败」的面目红，而不是以「行为不对」的面目红，两者的诊断成本
    差得很远。
    """
    assert _run_page_js(tmp_path, 'console.log("ok");').strip() == "ok"


def test_audio_without_lyrics_cannot_be_submitted(tmp_path):
    """裁定 D 的另一半：没歌词的音频**提交不了**，而且说得出为什么。

    三个格子一起断，缺一个都能被蒙混过去：
    - 音频 + 空歌词 → 拦住，且理由里提到歌词
    - 音频 + 有歌词 → 放行（少了这条，一个「永远拦住」的实现也全绿）
    - 视频 + 空歌词 → 放行（歌词正是 ingest 要 OCR 出来的，拦了就把整条路堵死）
    """
    out = _run_page_js(
        tmp_path,
        """
        console.log(JSON.stringify({
          audioBlank: blockedReason("run", "   \\n  "),
          audioFilled: blockedReason("run", "谁先眨眼就输"),
          videoBlank: blockedReason("ingest", ""),
          nothingPicked: blockedReason(null, ""),
        }));
        """,
    )
    got = json.loads(out)
    assert got["audioBlank"], "音频 + 空歌词竟然放行了。"
    assert "歌词" in got["audioBlank"]
    assert got["audioFilled"] is None, "音频 + 有歌词被拦住了。"
    assert got["videoBlank"] is None, (
        "视频 + 空歌词被拦住了——歌词正是 ingest 要 OCR 出来的，拦了等于把视频"
        "那条路堵死。"
    )
    assert got["nothingPicked"], "什么都没选竟然能提交。"


#: 降级行与它的原因，逐字来自 `tests/fixtures/real-fallback-output.txt`。
FALLBACK_LINES = FALLBACK_FIXTURE.read_text(encoding="utf-8").splitlines()
REASON_LINE = FALLBACK_LINES[0]  # `  lyrics.timing.json 有 1 行…` → 详细区
DEGRADED_LINE = FALLBACK_LINES[1]  # `  退回常规对齐。` → 主日志


def _render(tmp_path: Path, entries: list[dict], detail_count: int) -> str:
    return _run_page_js(
        tmp_path,
        "console.log(renderMainLog(%s, %d));"
        % (json.dumps(entries, ensure_ascii=False), detail_count),
    )


def test_a_degraded_line_offers_a_way_to_open_the_detail_region(tmp_path):
    """「查看原因 ▾」那条的**前一半**：入口在，而且真的挂在降级行上。

    `cli.py:284/388/435` 三处是纯 `print(f"  {exc}")`，白名单认不出来，只能落
    详细区——于是主日志上会出现一句孤零零的「退回常规对齐。」。台账那条是
    「降级必须**大声说**」，说了一半不算说到。
    """
    html = _render(
        tmp_path,
        [
            {"text": "[3/5] 对齐歌词", "degraded": False},
            {"text": DEGRADED_LINE, "degraded": True},
        ],
        detail_count=1,
    )
    assert "查看原因" in html, f"降级行旁边没有入口。渲染出来的是：\n{html}"
    assert "data-open-detail" in html, "入口没挂上「点开即展开详细区」的钩子。"
    # 入口只跟着降级行走，不是每行都挂一个。
    assert html.count("查看原因") == 1, (
        f"两行里挂了 {html.count('查看原因')} 个入口——它没有认降级行，只是每行"
        f"都装了一个。渲染出来的是：\n{html}"
    )


def test_no_entry_is_offered_when_the_detail_region_is_empty(tmp_path):
    """「查看原因 ▾」那条的**后一半**（控制窗口加的防装饰判据）。

    只断「页面上有一个 ▾」是假守卫——它在详细区为空时照样绿。一个点开是空的
    入口比没有入口更糟：用户点了，看见空的，于是以为原因**不存在**。

    自指检查（CONSTRAINTS 第 10 条方向一）：这个防「降级没有原因」的措施，自己
    在没有原因的时候会不会假装有？答案必须是不会。
    """
    html = _render(tmp_path, [{"text": DEGRADED_LINE, "degraded": True}], 0)
    assert "查看原因" not in html, (
        f"详细区一行都没有，页面却照样给了「查看原因」的入口——点开是空的。"
        f"渲染出来的是：\n{html}"
    )
    assert DEGRADED_LINE.strip() in html, "降级行本身也没了。"


def test_the_log_keeps_user_text_as_text(tmp_path):
    """日志里带尖括号的行原样显示，不当成标签。

    `    - <歌词里真有尖括号>` 这种行来自**用户数据**（`cli.py:386` 打的是未对
    上的歌词原文）。不转义的话，用户的歌词能往这个页面里注 DOM。
    """
    html = _render(tmp_path, [{"text": "    - <b>一盏灯</b>", "degraded": False}], 0)
    assert "<b>" not in html, f"歌词里的标签被当成 HTML 了：\n{html}"
    assert "&lt;b&gt;" in html


#: 六条声部色进度条：喂进去的两级进度（外层, 内层, 是否已完成），和该亮的条数。
#:
#: **逐档写死在这里**，因为判据就是「第 3 段亮」与「永远亮 5 段」分得开——只断
#: 「有条亮着」的话，一个恒定亮 5 段的纯装饰照样绿，而那正是这一栏要防的东西。
#: 档位取自真实的两条流程：`run` 是外层 `/2` × 内层 `/5`，`ingest` 只有外层 `/2`
#: （`murripple/web/progress.py` 按分母分层）。
_BAR_CASES = [
    ("还没开跑", None, None, False, 0),
    ("[1/2] 分析 · [1/5] 分离音源", {"step": 1, "total": 2}, {"step": 1, "total": 5}, False, 1),
    ("[1/2] 分析 · [3/5] 对齐歌词", {"step": 1, "total": 2}, {"step": 3, "total": 5}, False, 2),
    ("[1/2] 分析 · [5/5] 组装 timeline", {"step": 1, "total": 2}, {"step": 5, "total": 5}, False, 3),
    ("[2/2] 打包（这一层没有内层细分）", {"step": 2, "total": 2}, None, False, 5),
    ("跑完了", {"step": 2, "total": 2}, None, True, 6),
]


def test_the_progress_bars_follow_the_real_progress(tmp_path):
    """六条进度条跟着实际进度亮，不是画上去的。

    判据（管理窗口下的）：**能区分「第 3 段亮」与「永远亮 5 段」**。所以这里
    不断「有条亮着」，而是把六档进度逐档喂进 `renderBars()`，对一整条亮起来的
    条数序列——一个恒定亮 5 段的实现，第一档就红。

    另外两条一起断，缺一条都能被蒙混过去：
    - **六个格子一个不少**：一个只渲染亮着那几条的实现，视觉上是「进度条变短」
      而不是「后面几段暗着」，看起来像跑完了。
    - **亮的必须是从头连续的一段**：`bar-1..bar-n`。挑着亮的话，颜色跟进度就
      对不上了（第 n 条的颜色是 CSS 按 `.bar-n` 给的）。
    """
    payload = [[outer, inner, done] for _name, outer, inner, done, _lit in _BAR_CASES]
    got = json.loads(
        _run_page_js(
            tmp_path,
            "console.log(JSON.stringify(%s.map(function (c) {"
            " return renderBars(c[0], c[1], c[2]); })));"
            % json.dumps(payload, ensure_ascii=False),
        )
    )

    lit = []
    for html in got:
        bars = re.findall(r'class="bar-(\d+)( on)?"', html)
        assert [int(index) for index, _on in bars] == [1, 2, 3, 4, 5, 6], (
            f"渲染出来的不是六条完整的格子：{html}"
        )
        on = [int(index) for index, is_on in bars if is_on]
        assert on == list(range(1, len(on) + 1)), (
            f"亮着的不是从头连续的一段：{html}"
        )
        lit.append(len(on))

    expected = [count for _name, _outer, _inner, _done, count in _BAR_CASES]
    mismatched = [
        (case[0], case[4], actual)
        for case, actual in zip(_BAR_CASES, lit)
        if case[4] != actual
    ]
    assert not mismatched, (
        f"（这一档, 该亮几条, 实际亮了几条）：{mismatched}。"
        "进度条跟实际进度对不上——常见的坏法是它压根不看进度，永远亮同样多。"
    )


# ================================================================ 端点
#
# 下面全部走真服务。

MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00fake mp3 bytes"
MP4 = b"\x00\x00\x00\x20ftypisom fake mp4 bytes"

#: 替身 CLI 会写进 `dist/index.html` 的东西。
PRODUCT_HTML = "<!doctype html><title>成品</title>涟漪"

#: 替身 `ingest` 会写进 `lyrics.txt` 的「OCR 结果」。
OCR_LYRICS = "第一句 OCR 出来的\n第二句漏了半行\n"

#: 替身 CLI。**跑通那条路上打印的每一行都从夹具里读**，一个字不加。
FAKE_CLI_SOURCE = '''\
"""替身 murripple。输出全部从夹具里逐行重放。"""
import sys
from pathlib import Path

FIXTURE = Path(sys.argv[1])
CODE = int(sys.argv[2])
MODE = sys.argv[3]
ARGV = sys.argv[4:]
SONG_DIR = Path(ARGV[1])

for line in FIXTURE.read_text(encoding="utf-8").splitlines():
    print(line)

if MODE == "ocr":
    (SONG_DIR / "lyrics.txt").write_text(%(ocr)r, encoding="utf-8")
if MODE == "product":
    dist = SONG_DIR / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(%(product)r, encoding="utf-8")

raise SystemExit(CODE)
''' % {"ocr": OCR_LYRICS, "product": PRODUCT_HTML}


@dataclass
class Client:
    """一个连着真服务的客户端 + 它的 `songs/` 根目录。"""

    port: int
    songs_root: Path
    tmp_path: Path

    # ---------------------------------------------------------- 低层
    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes, str]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
        finally:
            conn.close()

    def json(
        self, method: str, path: str, body: bytes | None = None, **headers: str
    ) -> tuple[int, dict]:
        status, payload, _ = self.request(method, path, body, headers)
        return status, json.loads(payload.decode("utf-8"))

    # ---------------------------------------------------------- 高层
    def create(self, filename: str, content: bytes = MP3) -> tuple[int, dict]:
        return self.json(
            "POST", "/api/job", content, **{"X-Filename": quote(filename)}
        )

    def state(self, job_id: str) -> dict:
        status, payload = self.json("GET", f"/api/job/{job_id}")
        assert status == 200, payload
        return payload

    def wait(self, job_id: str, timeout: float = 60.0) -> dict:
        """等到不是 `running` 为止。到点就把最后看到的状态摆出来再红。"""
        deadline = time.monotonic() + timeout
        state = self.state(job_id)
        while state["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.02)
            state = self.state(job_id)
        assert state["status"] != "running", f"{timeout} 秒还没跑完：{state}"
        return state


def _fake_command(tmp_path: Path, fixture: Path, code: int, mode: str) -> tuple:
    script = tmp_path / "fake_cli.py"
    script.write_text(FAKE_CLI_SOURCE, encoding="utf-8")
    return (sys.executable, str(script), str(fixture), str(code), mode)


@pytest.fixture
def with_ffmpeg(tmp_path, monkeypatch):
    """`PATH` 里放一个真的可执行 `ffmpeg`。

    **不是摆设**：建任务那一步会硬拒没有 ffmpeg 的机器，而这台机器上装没装
    ffmpeg 是**机器的性质**（CONSTRAINTS 第 9 条）。不把 PATH 钉死的话，同一
    份测试在装了 ffmpeg 的机器上和没装的机器上验的是两件事。
    """
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    fake = bin_dir / "ffmpeg"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    return bin_dir


def _serve(tmp_path: Path, songs_root: Path, command: tuple) -> Client:
    from murripple.web import app

    state = app.AppState(songs_root=songs_root, command=command)
    httpd = app.make_server(0, state)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    client = Client(httpd.server_port, songs_root, tmp_path)
    client._httpd = httpd  # 关服务用
    client._thread = thread
    return client


@pytest.fixture
def client(tmp_path, with_ffmpeg):
    """默认替身：重放真实 build 输出、退出 0、顺手写出产物。"""
    songs_root = tmp_path / "songs"
    songs_root.mkdir()
    command = _fake_command(tmp_path, BUILD_FIXTURE, 0, "product")
    client = _serve(tmp_path, songs_root, command)
    yield client
    client._httpd.shutdown()
    client._thread.join(timeout=10)
    client._httpd.server_close()


@pytest.fixture
def make_client(tmp_path, with_ffmpeg):
    """自己挑夹具／退出码／模式的客户端工厂。"""
    made = []

    def factory(fixture: Path, code: int = 0, mode: str = "none") -> Client:
        songs_root = tmp_path / f"songs-{len(made)}"
        songs_root.mkdir()
        sub = tmp_path / f"fake-{len(made)}"
        sub.mkdir()
        client = _serve(tmp_path, songs_root, _fake_command(sub, fixture, code, mode))
        made.append(client)
        return client

    yield factory
    for client in made:
        client._httpd.shutdown()
        client._thread.join(timeout=10)
        client._httpd.server_close()


# ---------------------------------------------------------------- GET /


def test_the_root_serves_the_page_itself(client):
    """`GET /` 给的就是那份 `index.html`，逐字节相同。

    断字节相同而不是断某个子串：断子串的话，一个把页面写死在 Python 里的实现
    （于是 `static/index.html` 上的全部守卫都白守了）也能通过。
    """
    status, body, content_type = client.request("GET", "/")
    assert status == 200
    assert "text/html" in content_type and "utf-8" in content_type.lower()
    assert body == PAGE.read_bytes()


def test_an_unknown_path_still_says_it_has_nothing(client):
    status, _body, _ct = client.request("GET", "/__murripple_probe__")
    assert status == 404


# ---------------------------------------------------------------- 建任务


def test_a_chinese_filename_lands_in_songs_as_source_mp3(client):
    """建任务：中文名 + 空格不炸，素材原样落盘。"""
    status, payload = client.create("我的 歌.mp3")
    assert status == 201, payload
    assert payload["route"] == "run"

    dirs = list(client.songs_root.iterdir())
    assert len(dirs) == 1, f"songs/ 下建出了 {len(dirs)} 个目录：{dirs}"
    assert dirs[0].name.endswith("我的 歌"), dirs[0].name
    assert (dirs[0] / "source.mp3").read_bytes() == MP3


def test_a_video_goes_down_the_ingest_route(client):
    status, payload = client.create("录屏.mp4", MP4)
    assert status == 201, payload
    assert payload["route"] == "ingest"
    song_dir = next(iter(client.songs_root.iterdir()))
    assert (song_dir / "_in" / "录屏.mp4").read_bytes() == MP4


# ------------------------------------------------- 路径穿越（**HTTP 边界上的**）
#
# `tests/test_web_jobs.py` 已经证过「调了 `safe_stem()` 就安全」。它**不证明端点
# 真的调了它**——这两件事之间隔着一整层，而那一层归本文件。
#
# 三条设计上的讲究，缺一条这两个用例就会变成假守卫：
#
# 1. **不断状态码。** 一个把 `../../x.mp3` 消毒成 `x.mp3` 的实现不返回 400，一个
#    把它原样写出去的实现**也不返回 400**——`assert status == 400` 在这两者之间
#    没有任何分辨力。让请求真的走完，再看盘上那个绝对路径落在哪儿。
# 2. **光断「绝对路径还在 `songs/` 里」也不够**（`jobs.py` 模块 docstring 里那条
#    实测）：不消毒时 `../../x.mp3` 建出的是 `songs/web-<ts>-../../x/`，而
#    `web-<ts>-` 前缀恰好当了一级挡箭牌，`..` 只往上走了一层——最终**仍在
#    `songs/` 里面**，只是旁边多了个叫 `web-<ts>-..` 的残骸。所以还要断
#    「`songs/` 下正好多出一个东西」。
# 3. **`..` 的个数是挑过的**：两级刚好落在 `tmp_path` 里——逃出去了看得见，又
#    不会在测试机上到处建目录。给四级的话，逃出去的那份落在 `tmp_path` 外面，
#    「songs/ 里正好一份」那条断言照样红，但残骸留在别人家里。


def _copies_of(content: bytes, root: Path) -> list[Path]:
    """`root` 底下所有内容等于 `content` 的文件。"""
    found = []
    for path in root.rglob("*"):
        try:
            if path.is_file() and path.read_bytes() == content:
                found.append(path)
        except OSError:
            continue
    return found


def test_a_hostile_filename_cannot_escape_songs_on_the_audio_route(client):
    """`X-Filename: ../../escaped.mp3` → 素材仍然落在 `songs/` 之内。"""
    client.create("../../escaped.mp3")

    inside = _copies_of(MP3, client.songs_root)
    assert len(inside) == 1, (
        f"素材没有落在 songs/ 里面（找到 {len(inside)} 份）。"
        f"tmp_path 下的其余去处：{_copies_of(MP3, client.tmp_path)}"
    )
    assert inside[0].resolve().is_relative_to(client.songs_root.resolve())

    strays = [
        p for p in _copies_of(MP3, client.tmp_path)
        if not p.resolve().is_relative_to(client.songs_root.resolve())
    ]
    assert not strays, f"素材还写到了 songs/ 外面：{strays}"

    entries = list(client.songs_root.iterdir())
    assert len(entries) == 1, (
        f"songs/ 下多出了 {len(entries)} 个东西：{[e.name for e in entries]}。"
        "多出来的那个多半是 `web-<ts>-..` 那种残骸——它说明文件名原样进了路径，"
        "只是被前缀挡了一级。"
    )
    assert ".." not in entries[0].name


def test_a_hostile_filename_cannot_escape_songs_on_the_video_route(client):
    """视频那条路要多守一处：用户给的串出现在**两个**地方。

    音频只有目录名一处，视频还有 `_in/<原名>` 那一处（`jobs.create_job` 里
    `media_path = song_dir / "_in" / f"{stem}{suffix}"`）。只喂 `.mp3` 的守卫
    看不见后面那一处。
    """
    client.create("../../escaped.mp4", MP4)

    inside = _copies_of(MP4, client.songs_root)
    assert len(inside) == 1, (
        f"素材没有落在 songs/ 里面（找到 {len(inside)} 份）。"
        f"tmp_path 下的其余去处：{_copies_of(MP4, client.tmp_path)}"
    )
    landed = inside[0].resolve()
    assert landed.is_relative_to(client.songs_root.resolve())
    assert landed.parent.name == "_in", f"视频没落在 _in/ 里：{landed}"

    strays = [
        p for p in _copies_of(MP4, client.tmp_path)
        if not p.resolve().is_relative_to(client.songs_root.resolve())
    ]
    assert not strays, f"素材还写到了 songs/ 外面：{strays}"

    entries = list(client.songs_root.iterdir())
    assert len(entries) == 1, (
        f"songs/ 下多出了 {len(entries)} 个东西：{[e.name for e in entries]}"
    )
    assert ".." not in entries[0].name


def test_an_unknown_file_type_is_refused_with_what_to_send_instead(client):
    status, payload = client.create("讲稿.pdf", b"%PDF-1.4")
    assert status == 400
    assert ".mp3" in payload["error"] and ".mp4" in payload["error"], payload
    assert not list(client.songs_root.iterdir()), "被拒的素材还是在盘上留了目录。"


def test_a_job_without_a_filename_is_refused(client):
    status, payload = client.json("POST", "/api/job", MP3)
    assert status == 400
    assert "error" in payload


def test_an_empty_upload_is_refused(client):
    status, payload = client.create("空的.mp3", b"")
    assert status == 400
    assert "error" in payload
    assert not list(client.songs_root.iterdir())


def test_the_job_is_refused_up_front_when_ffmpeg_is_missing(client, monkeypatch, tmp_path):
    """spec 第六节：ffmpeg 不在 PATH，**建任务阶段就硬拒**，并把那条修法送上页面。

    Task 1 只做了终端那一半（启动时提醒一句，不拦启动），留下的另一半在这里：
    用户那时候页面已经在眼前，说得清楚。

    对照组在下一条（`test_the_job_goes_through_when_ffmpeg_is_on_path`）——少了
    它，一个「无论如何都拒」的实现在这条上全绿。
    """
    empty = tmp_path / "no-ffmpeg-here"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    status, payload = client.create("我的歌.mp3")
    assert status == 400, payload
    assert "brew install ffmpeg" in payload["error"], payload
    assert not list(client.songs_root.iterdir()), "拒了还是建了目录。"


def test_the_job_goes_through_when_ffmpeg_is_on_path(client):
    """上一条的对照组。`with_ffmpeg` 已经把 PATH 钉在一个装了 ffmpeg 的目录上。"""
    status, payload = client.create("我的歌.mp3")
    assert status == 201, payload


# ---------------------------------------------------------------- 歌词


def test_lyrics_land_in_lyrics_txt_verbatim(client):
    _status, payload = client.create("我的歌.mp3")
    text = "谁先眨眼就输\n第二句\n"
    status, _ = client.json(
        "POST", f"/api/job/{payload['job_id']}/lyrics", text.encode("utf-8")
    )
    assert status == 200
    song_dir = next(iter(client.songs_root.iterdir()))
    assert (song_dir / "lyrics.txt").read_text(encoding="utf-8") == text


def test_blank_lyrics_are_refused_instead_of_written(client):
    """全是空白的歌词不许落盘。

    `cli.py::run` 只查 `exists()`，一份全是空格的 `lyrics.txt` 骗得过它，然后
    一路降级到没有歌词层——而用户以为自己给过了。
    """
    _status, payload = client.create("我的歌.mp3")
    status, body = client.json(
        "POST", f"/api/job/{payload['job_id']}/lyrics", "  \n \n".encode("utf-8")
    )
    assert status == 400, body
    song_dir = next(iter(client.songs_root.iterdir()))
    assert not (song_dir / "lyrics.txt").exists()


def test_an_unknown_job_id_is_a_404_not_a_crash(client):
    status, payload = client.json("GET", "/api/job/nosuchjob")
    assert status == 404
    assert "error" in payload


# ---------------------------------------------------------------- 起子进程


def test_starting_an_audio_job_without_lyrics_asks_for_lyrics(client):
    """裁定 D 在服务端这一侧：没歌词的音频**根本不起子进程**。"""
    _status, payload = client.create("我的歌.mp3")
    status, state = client.json("POST", f"/api/job/{payload['job_id']}/start")
    assert status == 200, state
    assert state["status"] == "needs-lyrics"
    assert "歌词" in state["error"]
    # `cli.py:695` 那句命令行提示对页面用户毫无意义，不许漏到页面上。
    assert "murripple ingest" not in state["error"], (
        "页面上出现了一句让用户去敲命令行的话。"
    )


def test_a_run_reports_two_levels_of_progress_and_loses_no_line(client):
    """轮询：两级进度分得开，**18 行真实输出一行都不能丢**。

    主日志 + 详细区合起来逐行等于真实输出——分层只是显示位置，不是过滤器。
    """
    _status, payload = client.create("我的歌.mp3")
    job_id = payload["job_id"]
    client.json("POST", f"/api/job/{job_id}/lyrics", "谁先眨眼就输\n".encode())
    client.json("POST", f"/api/job/{job_id}/start")
    state = client.wait(job_id)

    assert state["status"] == "done", state
    assert state["inner"] == {"step": 5, "total": 5, "name": "组装 timeline"}, state

    expected = BUILD_FIXTURE.read_text(encoding="utf-8").splitlines()
    seen = [entry["text"] for entry in state["main"]] + list(state["detail"])
    missing = [line for line in expected if line not in seen]
    assert not missing, (
        f"真实输出里有 {len(missing)} 行在页面上一个字都看不到：\n"
        + "\n".join(missing)
    )


def test_the_main_log_is_capped_at_the_last_twenty_lines(make_client, tmp_path):
    """日志滚动区：最近 20 行（spec 第五节）。"""
    long_fixture = tmp_path / "many-lines.txt"
    long_fixture.write_text(
        "".join(f"完成：第 {i} 行\n" for i in range(1, 31)), encoding="utf-8"
    )
    client = make_client(long_fixture, 0, "none")
    _status, payload = client.create("我的歌.mp3")
    job_id = payload["job_id"]
    client.json("POST", f"/api/job/{job_id}/lyrics", "词\n".encode())
    client.json("POST", f"/api/job/{job_id}/start")
    state = client.wait(job_id)

    texts = [entry["text"] for entry in state["main"]]
    assert len(texts) == 20, f"主日志给了 {len(texts)} 行"
    assert texts[0] == "完成：第 11 行" and texts[-1] == "完成：第 30 行"
    assert state["main_omitted"] == 10


#: 主日志超过 20 行的那一份**拼**出来的原文：一句真实降级 + 真实 `build` 全程 +
#: 真实 `run` 全程。三份都是抄来的，一行都不是手打的。
#:
#: **说清它是什么**（跟 `test_web_e2e.py` 那份 29 行的同一个交代）：这 30 行的
#: **顺序**不对应任何一次单独的真实运行，它是三段真实原文的首尾相接。下面这两条
#: 测试只用它的「主日志行数 > 20」和「第一行是一句降级」，不依赖行与行之间的语义。
def _spliced_overflow_lines() -> list[str]:
    import test_web_progress as progress_tests

    return (
        [DEGRADED_LINE]
        + BUILD_FIXTURE.read_text(encoding="utf-8").splitlines()
        + progress_tests.RUN_LINES
    )


def test_the_lines_pushed_out_of_the_main_window_are_still_in_the_payload(
    make_client, tmp_path
):
    """被 20 行窗口挤出去的主日志行，**一条不少地**收进详细区。

    在这之前它们哪儿都不在：`main` 只剩最后 20 行，`detail` 只有第三方噪声，
    payload 里**没有 `log` 字段**——于是主日志第 1 行一旦被挤出窗口，页面上没有
    任何途径再看到它，页面只会说一句「前面还有 n 行」，而那 n 行不在任何一个响应
    里。「降级必须大声说」栽在自己的滚动区上（CONSTRAINTS 第 10 条方向二：做防护
    的那个动作伤到了它要保护的东西）。

    断的是**结构**：页面上看得见的每一行（`main` + `detail`）与子进程真的打出来
    的那些行**逐行等量**，一行不多一行不少。只断「那句降级在 detail 里」的话，一
    个把整份 log 无脑塞进 detail 的实现也绿，而它会把顺序和重复搅乱。
    """
    lines = _spliced_overflow_lines()
    fixture = tmp_path / "spliced-transcripts.txt"
    fixture.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")

    from murripple.web import app, progress

    main_lines = [ln for ln in lines if progress.classify(ln) == progress.MAIN]
    assert len(main_lines) > app.LOG_TAIL_LINES, (
        f"拼出来的夹具只有 {len(main_lines)} 行主日志，没到 {app.LOG_TAIL_LINES} "
        "行的上限——这条测试的前提塌了，它什么也证明不了。"
    )
    pushed_out = main_lines[: len(main_lines) - app.LOG_TAIL_LINES]

    client = make_client(fixture, 0, "none")
    _status, payload = client.create("我的歌.mp3")
    job_id = payload["job_id"]
    client.json("POST", f"/api/job/{job_id}/lyrics", "词\n".encode())
    client.json("POST", f"/api/job/{job_id}/start")
    state = client.wait(job_id)

    seen = [entry["text"] for entry in state["main"]] + list(state["detail"])
    assert Counter(seen) == Counter(lines), (
        "页面拿得到的行跟子进程真的打出来的行对不上。少掉的："
        f"{sorted((Counter(lines) - Counter(seen)).elements())}；"
        f"多出来的：{sorted((Counter(seen) - Counter(lines)).elements())}"
    )
    assert state["main_omitted"] == len(pushed_out)
    detail_counts = Counter(state["detail"])
    for line in pushed_out:
        assert detail_counts[line] >= 1, (
            f"被挤出窗口的 {line!r} 在整份响应里一个字都没有了。"
        )


def test_a_degradation_reason_that_the_whitelist_missed_is_in_the_detail_region(
    make_client,
):
    """「查看原因 ▾」那条的**后一半**在服务端这一侧。

    真实退回原文两行：第一行是原因（`cli.py:435` 的 `print(f"  {exc}")`，白名单
    认不出来），第二行是那句孤零零的「退回常规对齐。」。

    这条断的是「那句『怎么修』真的进了详细区」——只断「有个入口」的守卫在详细
    区为空时照样绿。
    """
    client = make_client(FALLBACK_FIXTURE, 0, "none")
    _status, payload = client.create("我的歌.mp3")
    job_id = payload["job_id"]
    client.json("POST", f"/api/job/{job_id}/lyrics", "词\n".encode())
    client.json("POST", f"/api/job/{job_id}/start")
    state = client.wait(job_id)

    degraded = [e for e in state["main"] if e["degraded"]]
    assert [e["text"] for e in degraded] == [DEGRADED_LINE], (
        f"降级行没被认出来。主日志：{state['main']}"
    )
    assert REASON_LINE in state["detail"], (
        f"那句「怎么修」不在详细区里，入口点开是空的。详细区：{state['detail']}"
    )
    assert "删掉 lyrics.timing.json" in REASON_LINE, (
        "夹具变了：这条测试指望第一行是带修复办法的那句。"
    )


def test_a_nonzero_exit_shows_the_tail_verbatim_without_wrapping(make_client):
    """spec 第六节：子进程非零退出，把尾部原样显示，**不要包装成「处理失败」**。"""
    client = make_client(BUILD_FIXTURE, 3, "none")
    _status, payload = client.create("我的歌.mp3")
    job_id = payload["job_id"]
    client.json("POST", f"/api/job/{job_id}/lyrics", "词\n".encode())
    client.json("POST", f"/api/job/{job_id}/start")
    state = client.wait(job_id)

    assert state["status"] == "error"
    assert state["returncode"] == 3
    last = BUILD_FIXTURE.read_text(encoding="utf-8").splitlines()[-1]
    assert last in state["error"], f"尾部原文没透出来：{state['error']!r}"
    assert "处理失败" not in state["error"]


def test_the_oversize_warning_reaches_the_main_log(make_client, tmp_path):
    """产物超 15 MB：`pack` 已经硬失败并给了修法，原样透出（spec 第六节）。

    夹具那两行是 `cli.py:818-821` 的 `print` 字面量，下面那条断言钉着它们此刻
    仍在源码里——否则这条测试会停在一个旧版本的输出格式上，而**不会红**。
    """
    source = (REPO_ROOT / "murripple" / "cli.py").read_text(encoding="utf-8")
    assert '  体积 {size_mb:.1f} MB' in source
    assert '警告：产物 {size_mb:.1f} MB 超过 15 MB 上限' in source

    fixture = tmp_path / "oversize.txt"
    fixture.write_text(
        "完成：/x/dist/index.html\n  体积 18.4 MB\n警告：产物 18.4 MB 超过 15 MB 上限\n",
        encoding="utf-8",
    )
    client = make_client(fixture, 0, "none")
    _status, payload = client.create("我的歌.mp3")
    job_id = payload["job_id"]
    client.json("POST", f"/api/job/{job_id}/lyrics", "词\n".encode())
    client.json("POST", f"/api/job/{job_id}/start")
    state = client.wait(job_id)

    texts = [entry["text"] for entry in state["main"]]
    assert "警告：产物 18.4 MB 超过 15 MB 上限" in texts, (
        f"超限那句没进主日志（它要是掉进折叠区，用户默认看不见）：{texts}"
    )


def test_a_command_that_cannot_start_says_so_in_plain_words(make_client, tmp_path):
    """`murripple` 命令压根起不来时，页面上要有一句人话，不是 500 空白。

    `runner.start` 在这种情况下**异常照抛**（那是它有意留给这一棒的）。
    """
    songs_root = tmp_path / "songs-nocmd"
    songs_root.mkdir()
    client = _serve(tmp_path, songs_root, (str(tmp_path / "根本没有这个命令"),))
    try:
        _status, payload = client.create("我的歌.mp3")
        job_id = payload["job_id"]
        client.json("POST", f"/api/job/{job_id}/lyrics", "词\n".encode())
        status, body = client.json("POST", f"/api/job/{job_id}/start")
        assert status == 500, body
        assert "murripple" in body["error"]
    finally:
        client._httpd.shutdown()
        client._thread.join(timeout=10)
        client._httpd.server_close()


# ---------------------------------------------------------------- 视频那条路


def test_ingest_hands_the_ocr_lyrics_back_for_checking(make_client):
    """视频那条路：`ingest` 完停下来，把 OCR 出来的歌词交回页面。

    页面拿它填进文本框让人核行数——这一停是 M4 定的，不是可以优化掉的等待。
    """
    client = make_client(BUILD_FIXTURE, 0, "ocr")
    _status, payload = client.create("录屏.mp4", MP4)
    job_id = payload["job_id"]
    assert payload["route"] == "ingest"

    status, _ = client.json("POST", f"/api/job/{job_id}/start?stage=ingest")
    assert status == 200
    state = client.wait(job_id)
    assert state["status"] == "done", state
    assert state["stage"] == "ingest"
    assert state["lyrics"] == OCR_LYRICS, (
        f"OCR 出来的歌词没交回页面，用户没法核行数。拿到的是：{state['lyrics']!r}"
    )


def test_an_unknown_stage_is_refused(client):
    _status, payload = client.create("我的歌.mp3")
    status, body = client.json(
        "POST", f"/api/job/{payload['job_id']}/start?stage=compose"
    )
    assert status == 400
    assert "compose" in body["error"]


# ---------------------------------------------------------------- 产物


def test_the_result_endpoint_hands_back_the_product(client):
    _status, payload = client.create("我的歌.mp3")
    job_id = payload["job_id"]
    client.json("POST", f"/api/job/{job_id}/lyrics", "词\n".encode())
    client.json("POST", f"/api/job/{job_id}/start")
    state = client.wait(job_id)
    assert state["result_ready"] is True, state

    status, body, content_type = client.request("GET", f"/api/job/{job_id}/result")
    assert status == 200
    assert "text/html" in content_type
    assert body.decode("utf-8") == PRODUCT_HTML


def test_asking_for_a_product_that_is_not_there_says_so(client):
    _status, payload = client.create("我的歌.mp3")
    status, body, _ct = client.request("GET", f"/api/job/{payload['job_id']}/result")
    assert status == 404
    assert "dist/index.html" in body.decode("utf-8")


# ------------------------------------------------------- `murripple serve` 本身
#
# 上面全部用 `app.make_server()` 建服务——那是**测试自己接的线**。产品那条线
# （`cli.py serve` → `server.serve()` → `make_server`）没人走过的话，六个端点可以
# 条条绿着，而用户打开 8731 看见的仍然是骨架那句「这个地址还没有内容」。
#
# 这正是本仓栽过九次的形状：断言没写错，但它跑的那个配置不是用户跑的那个。


def test_serve_really_hands_out_the_page(tmp_path):
    """真跑一次 `murripple serve`，`GET /` 必须是那份 `index.html`。"""
    proc = subprocess.Popen(
        [sys.executable, "-m", "murripple.cli", "serve"],
        cwd=REPO_ROOT,
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
    try:
        # 冷启动要 import 整条分析管线（实测约 1 秒），慢机器留足余量。
        deadline = time.monotonic() + 20.0
        url = None
        while url is None and time.monotonic() < deadline:
            for line in list(lines):
                if "http" in line:
                    url = line
                    break
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        assert url is not None, f"没等到地址那一行。输出：\n{''.join(lines)}"
        port = int(re.search(r":(\d+)", url).group(1))

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        try:
            conn.request("GET", "/")
            resp = conn.getresponse()
            body = resp.read()
        finally:
            conn.close()
        assert resp.status == 200, (
            f"`murripple serve` 起来了，但 GET / 是 {resp.status}——"
            "端点没接进产品那条线，用户打开看见的是骨架那句「这个地址还没有内容」。"
        )
        assert body == PAGE.read_bytes()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        if proc.stdout is not None:
            proc.stdout.close()


# ==================================================================== 听写那几分钟
#
# 听写内部要跑几十秒到几分钟，而 WhisperX **不吐逐段回调**——页面上原先一个字
# 都不动。上一棒没有造一个假的进度条，那个决定是对的，这里把它钉住：诚实的做
# 法是说清「它在做什么、为什么久」，而不是画一个匀速爬的东西。


def _waiting(tmp_path: Path, state: dict) -> str:
    out = _run_page_js(
        tmp_path,
        "console.log(JSON.stringify(transcribeWaiting(%s)));"
        % json.dumps(state, ensure_ascii=False),
    )
    return json.loads(out)


#: 听写真正在跑的那一刻。`[1/2] 听写    ← source.mp3（模型跑在本机，要一会儿）`
#: 抄自 `murripple/cli.py::transcribe`。
_TRANSCRIBING = {
    "stage": "transcribe",
    "status": "running",
    "outer": {"step": 1, "total": 2, "name": "听写    ← source.mp3（模型跑在本机，要一会儿）"},
}


def test_the_transcribe_wait_says_what_it_is_doing(tmp_path):
    """听写在跑的时候，页面得说得出它在干什么、以及为什么不动。

    判据是「一个不知情的人不会以为它卡死了」。屏幕上几分钟一动不动，唯一能挡
    住那个误解的就是**提前说清「停着是正常的」**。
    """
    note = _waiting(tmp_path, _TRANSCRIBING)
    assert note, "听写正在跑，页面却一个字都不说。"
    assert "不是卡住" in note, (
        f"这块话没有正面回答「它是不是死了」——那正是用户唯一想知道的：\n{note}"
    )


def test_the_transcribe_wait_promises_no_progress_it_cannot_know(tmp_path):
    """**不许造假进度。**

    WhisperX 不给逐段回调，所以百分比、还剩几步、预计还需多久，一个都算不出
    来。算不出来还写在页面上就是撒谎——这条是本棒最硬的一条判据的落点。

    `%` 与「还需」「预计」「剩余」一并挡住：只挡百分号的话，一句「预计还需 3
    分钟」照样绿。
    """
    note = _waiting(tmp_path, _TRANSCRIBING)
    for forbidden in ("%", "百分", "还需", "预计", "剩余", "还剩"):
        assert forbidden not in note, (
            f"这块话里出现了 {forbidden!r}——听写这一步没有任何进度可算，"
            f"写出来的都是编的：\n{note}"
        )


#: 不该出现那块话的几种情形。**逐档都要有**：只断正面的话，一个「永远显示」
#: 的实现照样绿，而它会在跳过分支上对着一个瞬间跑完的步骤说「要等一会儿」。
_NOT_WAITING = [
    (
        "跳过分支",
        {
            "stage": "transcribe",
            "status": "running",
            # `lyrics.txt` 已经在盘上，下一行紧接着就来，根本不等人。
            "outer": {"step": 1, "total": 2, "name": "听写    跳过（lyrics.txt 已存在，用不着听）"},
        },
    ),
    (
        "已经在写草稿了",
        {
            "stage": "transcribe",
            "status": "running",
            "outer": {"step": 2, "total": 2, "name": "写草稿"},
        },
    ),
    (
        "听写已经跑完",
        {"stage": "transcribe", "status": "done",
         "outer": {"step": 2, "total": 2, "name": "写草稿"}},
    ),
    (
        "根本不是听写那一档",
        {"stage": "run", "status": "running",
         "outer": {"step": 1, "total": 2, "name": "分析"}},
    ),
    (
        "一行都还没打出来",
        {"stage": "transcribe", "status": "running", "outer": None},
    ),
]


def test_the_waiting_cases_are_not_empty():
    """参数集由数据推导时 pytest 默认给绿 + 跳过。这是那条独立守卫。"""
    assert len(_NOT_WAITING) == 5


@pytest.mark.parametrize("name,state", _NOT_WAITING)
def test_the_transcribe_wait_stays_out_of_the_way_otherwise(tmp_path, name, state):
    assert _waiting(tmp_path, state) is None, (
        f"「{name}」这一档不该出现那块等待的话——它会对着一件没在发生的事说话。"
    )


def test_the_elapsed_clock_only_reports_what_was_measured(tmp_path):
    """已用时念的是**量到的**那个数，一秒不多一秒不少。

    这个数是页面唯一会动的东西，所以它必须绝对老实：喂进去多少毫秒，念出来就
    是多少秒。少了这条，一个「乘以 2 好让它看着快些」的实现没有任何东西挡得住。
    """
    got = json.loads(
        _run_page_js(
            tmp_path,
            "console.log(JSON.stringify([0, 1000, 59000, 60000, 83000, 671000]"
            ".map(elapsedText)));",
        )
    )
    assert got == [
        "0 秒", "1 秒", "59 秒", "1 分 0 秒", "1 分 23 秒", "11 分 11 秒",
    ], f"已用时念错了：{got}"


# ============================================================ 听写失败那一行
#
# 听写失败时打的是 `听不了：…`（`cli.py::transcribe`，WhisperX 装不上／加载不
# 了）。它原先**不算降级**：同一块主日志里，「退回常规对齐。」是红的、挂着
# 「查看原因 ▾」，而「听不了：…」是白的、什么都不挂——两句话的性质一模一样，
# 页面上的待遇却不一样。这是一处有意留下的不一致，这一节把它补上。

#: 两条真消息，逐字抄自 `murripple/ingest/transcribe.py::_load_whisperx`
#: 抛出的 `TranscriptionUnavailable`，前面加上 `cli.py` 打的那四个字。
_CANNOT_HEAR = [
    "听不了：WhisperX 未安装，听不了。运行 `uv sync --extra align` 装上，"
    "或者自己写一份 lyrics.txt 放进歌曲目录。",
    "听不了：WhisperX 已安装但无法加载，通常是 torch 与 torchaudio 版本不匹配："
    "dlopen(...) 。运行 `uv sync --extra align` 重装，"
    "或者自己写一份 lyrics.txt 放进歌曲目录。",
]


@pytest.mark.parametrize("line", _CANNOT_HEAR)
def test_the_cannot_hear_line_counts_as_a_degradation(line):
    """`听不了：…` 跟别的降级行一样被标出来。

    **这两条消息里一个既有的标记词都不带**（没有「失败」「跳过」「退回」…），
    所以在加 `"听不了："` 之前它们是白的——不是靠别的词蒙对的。
    """
    from murripple.web import app

    assert app.is_degraded(line), f"听写失败这一行没被认成降级：{line!r}"


def test_the_cannot_hear_line_gets_the_same_entry_as_its_siblings(tmp_path):
    """认成降级还不够——**得真的挂上「查看原因 ▾」**。

    `is_degraded` 与「页面上那个入口」之间隔着 `renderMainLog`，只断前者的话，
    中间断了也全绿。这里跑的是页面自己那个函数。
    """
    from murripple.web import app

    html = _render(
        tmp_path,
        [{"text": _CANNOT_HEAR[0], "degraded": app.is_degraded(_CANNOT_HEAR[0])}],
        detail_count=1,
    )
    assert "查看原因" in html, f"听写失败那行旁边没有入口：\n{html}"
    assert "ln-degraded" in html, f"听写失败那行没有被标成降级：\n{html}"


# ======================================================== 一个字都没听出来那一行
#
# 上一节的兄弟句。`cli.py::transcribe` 里两句紧挨着：WhisperX 装不上／加载不了
# 打 `听不了：…`，而 WhisperX 跑起来了、却一个字都没转出来时打的是
# 「一个字都没听出来，请自己写 lyrics.txt」，两句都紧跟着 `return 1`。上一节把
# 前者补成了降级，后者当时漏了——同一条路上、同一个结局，页面待遇又不一样了。
#
# 特别提防一个看着像覆盖了的词：白名单里那条 `"一行都没认出来"` 是 OCR 那条路
# （`cli.py::ocr`）的话，跟这里的「一个字都没听出来」**是两个不同的字符串**，
# 一个字都对不上。它长得像，所以很容易以为已经管住了。

#: 逐字抄自 `murripple/cli.py::transcribe`，连前面那六个空格一起——主日志里
#: 它就是这个样子（`progress._OURS` 那条正则也钉着这六个空格）。
_NOT_A_WORD = "      一个字都没听出来，请自己写 lyrics.txt"


def test_the_not_a_word_line_counts_as_a_degradation():
    """`一个字都没听出来…` 跟它的兄弟句一样被标出来。

    **这句话里一个既有的标记词都不带**——尤其不带 `"一行都没认出来"`（那是 OCR
    那条路的话）。所以它不是靠别的词蒙对的：不加新词，这条就是白的。
    """
    from murripple.web import app

    assert app.is_degraded(_NOT_A_WORD), f"这一行没被认成降级：{_NOT_A_WORD!r}"


def test_the_not_a_word_line_gets_the_same_entry_as_its_siblings(tmp_path):
    """认成降级还不够——**得真的挂上「查看原因 ▾」**。

    跟上一节同样的理由：`is_degraded` 与页面上那个入口之间隔着 `renderMainLog`，
    只断前者的话，中间断了也全绿。这里跑的是页面自己那个函数。
    """
    from murripple.web import app

    html = _render(
        tmp_path,
        [{"text": _NOT_A_WORD, "degraded": app.is_degraded(_NOT_A_WORD)}],
        detail_count=1,
    )
    assert "查看原因" in html, f"这一行旁边没有入口：\n{html}"
    assert "ln-degraded" in html, f"这一行没有被标成降级：\n{html}"
