"""把 `murripple` 的 stdout 读成「外层进度 / 内层进度 / 日志实录」。

纯函数，不碰 HTTP、不碰 `subprocess`、不存状态：喂一行、得一个新状态。
真正逐行读子进程的是别处。

## 判别靠分母，不靠缩进

真实输出长这样（2026-08-14 抄自一次真实 `murripple run`）：

    [1/2] 分析
    [1/5] 分离音源：跳过（build/stems/ 下已有 9 条现成分轨）
    [2/5] 读取分轨
    [3/5] 对齐歌词
      未找到 lyrics.txt，跳过歌词层。
    ...
    [2/2] 打包
          → /…/dist/index.html（14.2 MB）

**内层的 `[1/5]` 和外层的 `[1/2]` 都在第 0 列，一个空格都不缩。** 缩进在这
份输出里标的是**子消息**（降级说明、结果摘要、产物路径），跟层级无关。所以
分层只看分母：`/2` 是外层，`/5` 是内层。这个判别对 `run`、`ingest`
（`cli.py:458/466/469/483/485`）、`compose`（`cli.py:601/624/639`）三条流程都
成立，解析器因此不需要知道自己在解析哪一条。

## 两层各占一个格子

外层和内层是两个独立字段，不是一个「当前进度」。挤成一个的话，`[5/5] 组装
timeline` 之后来一行 `[2/2] 打包`，页面上就是进度条从 5 倒退回 2——而实际发
生的是「内层走完了，外层往前了一步」。这两种状态必须分得开。

外层前进时**不清空内层**：内层确实走完了 5 步，这是事实，清掉只会让页面在
打包阶段少一段已经发生过的历史。

## 日志是整份逐字实录

每一行都进 `log`，包括带 `[n/m]` 的行，也包括空行，缩进一格不动（只去掉行尾
的换行符）。

因为降级说明**两种位置都有**：`[1/5] 分离音源：跳过（…）` 长在进度行上，
`  未找到 lyrics.txt，跳过歌词层。` 是缩两格的子消息。只留 `[n/m]` 行会丢掉
后者，只留不带 `[n/m]` 的行会丢掉前者。降级必须大声说，两个方向都不许丢。

## 一行都不丢，但分层

真跑一次 12 秒的 `build`（Demucs 全程），17 行里有 7 行是第三方库的噪声，
而且吓人：

    Model was trained with torch 1.10.0+cu102, yours is 2.2.2. Bad things
    might happen unless you revert torch to 1.x.

普通用户看到这句会以为坏了。所以每一行除了进 `log`，还在 `layers` 里占一格：
`MAIN`（我们自己打的话）或 `DETAIL`（其余全部，页面上收进折叠区）。两块合起
来**逐行等于 `log`**——分错只是显示位置不对，不会丢，这是刻意选的失败方向。

**分类按内容白名单，不按缩进。** 那次真跑的第 3 行是 `  warnings.warn(`——
缩两格的**第三方**行，跟第 11 行 `  以下 1 行未对上…`（缩两格的**我们的**行）
形状完全一样；而第 2、8、9 行的第三方噪声又都在第 0 列。**在这个项目的 CLI
输出里，缩进不携带任何可靠的结构信息**——这是同一个形状栽的第二次（第一次是
spec 写「按缩进区分内外层」，实测 `[1/5]` 也在第 0 列）。

## 夹具的出处

**这三份夹具是从真实运行里抄下来的原文，不许任何人手打一份「理想格式」。**
到这一棒为止一共四份：本模块 docstring 上面引的那两段（`run` 完整路径、跳过
路径）在 `tests/test_web_progress.py` 里，`build` 全程与硬字幕退回那两份在
`.superpowers/sdd/2026-08-14-w1-local-shell/real-{build,fallback}-output.txt`
——测试**从文件里读**，不在测试里手打一份。手写一份「理想的第三方噪声」，
没人会想到往里塞一条缩两格的 `  warnings.warn(`，而那一行正是分层的全部难点。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable

# 外层／内层的分母。**这两个数就是判别规则本身**，不是可调参数。
OUTER_TOTAL = 2
INNER_TOTAL = 5

# 取回那一层自己打的每一行都带这个前缀（`fetch.LOG_PREFIX`）。抄一份字面量进
# 来而不是 `from murripple.fetch import LOG_PREFIX`：本模块是**纯函数**，
# `fetch.py` 顶层要 `import sys/shlex/subprocess` 之外还牵着一串东西，而这里只
# 需要三个字。守卫在 `tests/test_web_fetch_wiring.py`，它拿 `fetch.LOG_PREFIX`
# 跟这个常量对着断——抄件过期会红，不会安静地失效。
FETCH_PREFIX = "[取回]"

#: 「取回」这一段：`ingest --url` 里 **`[1/2]` 之前**的那几分钟。
#:
#: 它**不是外层的第三步**。外层的分母永远是 `OUTER_TOTAL`，一次都不会变成 3
#: ——「有时候 2 步、有时候 3 步」是要读代码才懂的东西，而进度条正是给不读代码
#: 的人看的。取回是编号之外的一段：`phase` 说的是「此刻在一个没有编号的阶段
#: 里」，`outer`／`inner` 仍旧**只表示 `[n/m]` 那一套**，语义一套没变。
PHASE_FETCH = "fetch"

# `[n/m] 剩下的原文`。开头允许空白只是为了宽容——**缩进不参与分层**，认出来
# 之后照样按分母归层。`] ` 后面的东西一字不改地留在 `text` 里：`[1/2] 分析
# 　　跳过（build/timeline.json 已存在，用 --force 重来）` 的那句降级说明，
# 以及 `分析` 后面那四个空格，都长在这一段里。
_STEP_RE = re.compile(r"^[ \t]*\[(\d+)/(\d+)\] ?(.*)$")


@dataclass(frozen=True)
class Step:
    """一层进度的当前状态：`[current/total] text`。"""

    current: int
    total: int
    text: str


# ------------------------------------------------------------------ 日志分层

# 每一行归两块中的一块。**两块都留着整行原文，一行都不丢**——分错只是位置不
# 对，不会丢，这是刻意选的失败方向。
MAIN = "main"  # 主日志：我们自己打的话
DETAIL = "detail"  # 「详细输出」折叠区：其余全部（第三方库的噪声）

# 我们自己打的话，长什么样。**按内容认，不按缩进认。**
#
# 每一条后面标着 `murripple/cli.py`（个别是 `murripple/ingest/scan.py`）里的
# 出处；`tests/test_web_progress.py::OUR_SHAPES` 逐条钉着「这段字面量此刻仍在
# 源码里」，所以这张表跟着管线一起变老，不会停在某个旧版本上。
#
# 用 `re.match`（钉在行首）。少数几条以动态路径开头，只能拿 `.*` 起头——它们
# 认的是句中那截固定的中文，第三方库不会打出那种话。
_OURS = tuple(
    re.compile(pattern)
    for pattern in (
        # —— build()：网页壳子最常跑到的一条 ——
        r"分离失败：",  # cli.py:311
        r"读不了分轨 ",  # cli.py:326 第一行
        r"  这个文件是空的或者损坏了。删掉 ",  # cli.py:326 第二行
        r"音频仅 .* 秒，太短，中止。$",  # cli.py:336
        r"警告：",  # cli.py:339 / 821
        r".* 要的分轨 .* 不在 .* 里；现有：",  # cli.py:355
        r"  未找到 lyrics\.txt，跳过歌词层。$",  # cli.py:368
        r"  用硬字幕的演唱时刻，跳过 WhisperX（",  # cli.py:377
        # —— 语言：侦测结果**必须到得了主日志** ——
        #
        # 折进详细区就等于没说，而这一句正是「不许沉默地猜」的全部落点：
        # 认错了整首歌的歌词都会错位，而画面上只是"歌词不对"，看不出错在
        # 语言这一步。第二条是拿不准时那一行（后面还跟一行照着敲的命令，
        # 那一行归已有的 `  uv run murripple ` 那条管）。
        # 两条都钉在 `tests/test_language.py::LANGUAGE_SHAPES` 上（源码里
        # 有这一句 + 它归主日志），路数照 `test_transcribe.TRANSCRIBE_SHAPES`。
        r"  语言：",  # cli.py::_language_lines
        r"  认错的话整首歌的歌词都会错位。",  # cli.py::_language_lines
        r"  以下 \d+ 行未对上，请在 overrides\.json 中补时间：$",  # cli.py:384
        r"    - ",  # cli.py:386 未对上的歌词原文（**用户数据**）
        r"  降级为无歌词，继续。$",  # cli.py:389
        r"overrides\.json 有问题：",  # cli.py:409 / 415
        r"      已应用 ",  # cli.py:417
        r"完成[：。]",  # cli.py:422 / 490 / 666 / 819
        r"  时长 ",  # cli.py:423
        # —— load_subtitle_timing()：降级必须大声说 ——
        r"  退回常规对齐。$",  # cli.py:436
        # —— ingest()（`  {note}` 那几种来自 scan.py，经 cli.py:455 缩两格）——
        r"素材看不明白：",  # cli.py:451
        r"  扫描 `_in/`：",  # scan.py:102
        r"  音频 ← ",  # scan.py:112 / 114 / 120 / 123
        r"  歌词 ← ",  # scan.py:136 / 141 / 145
        r"  忽略（用不上）：",  # scan.py:151
        r"      → ",  # cli.py:460 / 478 / 718
        r"      一行都没认出来，请自己写 lyrics\.txt$",  # cli.py:472
        r"整理失败：",  # cli.py:487
        r"  uv run murripple ",  # cli.py:490 / 666
        # —— transcribe()：听写那条路 ——
        #
        # 前两条认的是**「这份草稿是什么」那段话**。它跟别的降级说明不一样：折进
        # 详细区的话，用户拿到的就是一份没有任何说明的歌词稿——而这个功能的全部
        # 安全性正建立在「他知道自己在校对什么」上。
        r"  · ",  # cli.py::_draft_next_steps 的三条
        r"  打开 ",  # cli.py::_draft_next_steps 最后一句
        r"听不了：",  # cli.py::transcribe，WhisperX 装不上／加载不了
        r"      一个字都没听出来，请自己写 lyrics\.txt$",  # cli.py::transcribe
        r"  实在没有歌词可抄，",  # cli.py::run 缺歌词时指出的第三条路
        # —— compose() ——
        r".* 不存在。先跑一次",  # cli.py:590
        r".* 读不动：",  # cli.py:599
        r"不认识的调式 ",  # cli.py:605
        r".* 里有两段都叫 ",  # cli.py:632
        r"      已作废 ",  # cli.py:655
        r"  分轨 → ",  # cli.py:666
        r"  [\d.]+s.* · \d+ 段 · \d+ 个音符$",  # cli.py:666
        r"先把那 \d+ 条 wav ",  # cli.py:666
        # —— fetch()：`murripple ingest --url` 那条路 ——
        #
        # 取回那一层**自己打的每一行都带这个前缀**（`fetch.LOG_PREFIX`），
        # yt-dlp 的原文一个字不改地原样透传、不带前缀。所以这一条规则同时办
        # 成两件事：版权提醒／三级报名／降级原因进主日志，
        # `[generic] …`、`[download] 32.0% of …` 留在详细区。
        #
        # **不给它立规矩的话，上面那几样全部被折叠**——`classify` 认不出来就
        # 归详细区，而被折叠的恰好是这条路存在的前提（版权）和它最要紧的那句
        # 话（走了哪一级、为什么降级）。W1 那次「日志分层把一条降级埋了」，
        # 就是同一个形状。守卫在 `tests/test_web_fetch_wiring.py`。
        re.escape(FETCH_PREFIX),  # fetch.py:LOG_PREFIX
        # uv **自己**打的那三种（走 stderr，被 `fetch._run` 并进同一个流）。
        # 逐字节抄件在 `tests/fixtures/yt-dlp/uv-cold-start.stderr`。
        #
        # 这三条是**第三方的输出，却归主日志**——本表唯一的例外，理由要说清楚：
        # 第 1 级第一次跑要拉 11 个包 + 一个 36.7 MB 的 deno 二进制，这几分钟里
        # **这几行是"它没卡死、正在下东西"的唯一证据**。折进详细区的话，主日志
        # 会停在 `$ uv run …` 上一动不动几分钟——正是 W1「分层把该看见的埋了」
        # 那个形状，只是这次埋的是好消息。
        #
        # 认得很窄，不会误伤 yt-dlp：它那几句是 `[generic] …: Downloading
        # webpage` 形，`re.match` 钉在行首、且这里还要求括号里跟着数字。
        r"Downloading \S+ \(\d",  # uv：Downloading deno (36.7MiB)
        r" Downloaded \S+$",  # uv：` Downloaded deno`
        r"Installed \d+ packages? in ",  # uv：Installed 12 packages in 26ms
        # —— run() / pack / main() ——
        r".* 下没有 lyrics\.txt。",  # cli.py:695
        r"打包失败：",  # cli.py:716 / 816
        r"  体积 [\d.]+ MB$",  # cli.py:819
        r"不认识的音名 ",  # cli.py:795
    )
)


def classify(line: str) -> str:
    """这一行归主日志还是归详细区。纯函数，只看这一行的内容。

    收尾的换行符先剥掉，跟 `advance()` 记进 `log` 的是同一个东西：Task 4 的
    runner 从管道上逐行读，剥不剥换行符不该改变归属。

    **认不出来就归详细区。** 白名单必然有漏（`print(f"  {exc}")` 那几处是动
    态文本，一个 `KeyError` 打出来就是 `  't0'`，跟第三方噪声长得一模一样），
    漏掉的那些落进折叠区——用户展开就看得见，不会丢。反过来放宽默认值的代价
    是 `Bad things might happen` 这种话跳到主日志上，那正是这一棒要挡的。
    """
    text = line.rstrip("\r\n")
    # 空行是 `cli.py:422`／`490`／`666` 那几个 `\n` 打出来的，是我们排版的一
    # 部分（`完成：…` 前面那口气）。
    if text.strip() == "":
        return MAIN
    # `[n/m] …`：`run`／`ingest`／`compose` 三条流程同形，分母是几都算我们的。
    if parse_step(text) is not None:
        return MAIN
    for pattern in _OURS:
        if pattern.match(text):
            return MAIN
    return DETAIL


@dataclass(frozen=True)
class Progress:
    """喂到某一行为止的全部状态。

    `outer` / `inner` 为 `None` 表示这一层**一步都还没打印过**——跟 `0/2`
    不是一回事：跳过路径下内层永远是 `None`，页面该显示「没有内层」，不是一
    根停在 0 的进度条。

    `layers` 与 `log` **一一对应**：第 i 行归 `layers[i]`。存的是「每行归哪
    一块」而不是两份切好的文本，因为这样两块合起来永远还原得回 `log`——
    「分错只是位置不对，不会丢」这句话就成了一条结构事实，而不是一句注释里
    的承诺。

    `phase` 是**编号之外**的阶段（此刻只有 `PHASE_FETCH` 一种），`None` 表示
    没有这样的阶段在跑。它跟 `outer` 是两件事，不是一件事的两种写法：

    - `outer` 只表示 `[n/m]`。取回这一段一个 `[n/m]` 都不打，所以那几分钟里
      `outer` 照旧是 `None`——**这条守卫没有被放宽**：`None` 仍然是「这一层
      一步都还没打印过」，跟 `0/2` 仍然是两件事。
    - `phase` 只表示「正在跑一个不打 `[n/m]` 的阶段」。页面据此把大标题从
      「准备中…」换成那个阶段的名字——因为**那几分钟里它并不是在准备，它在
      下东西**，而说「准备中」就是在撒谎。

    进了 `[1/2]` 就清空：编号那一套接手了，`phase` 的话说完了。
    """

    outer: Step | None = None
    inner: Step | None = None
    phase: str | None = None
    log: tuple[str, ...] = ()
    layers: tuple[str, ...] = ()

    @property
    def main(self) -> tuple[str, ...]:
        """主日志：我们自己打的那些行，原文，顺序不变。"""
        return tuple(ln for ln, layer in zip(self.log, self.layers) if layer == MAIN)

    @property
    def detail(self) -> tuple[str, ...]:
        """「详细输出」折叠区：其余全部，原文，顺序不变。"""
        return tuple(ln for ln, layer in zip(self.log, self.layers) if layer == DETAIL)


EMPTY = Progress()


def parse_step(line: str) -> Step | None:
    """认出一行进度行；不是进度行就返回 `None`。"""
    match = _STEP_RE.match(line)
    if match is None:
        return None
    return Step(int(match.group(1)), int(match.group(2)), match.group(3))


def advance(state: Progress, line: str) -> Progress:
    """喂一行，返回新状态（旧状态不变）。

    只剥行尾的换行符。`strip()` 会把 `  未找到…` 的两格和 `      → …` 的六格
    一起吃掉，而那是 `cli.py` 打出来的原文。
    """
    text = line.rstrip("\r\n")
    log = state.log + (text,)
    layers = state.layers + (classify(text),)
    state = replace(state, layers=layers)

    step = parse_step(text)
    if step is None:
        # 取回那一段：`[1/2]` 还要过几分钟才打，而这几分钟里页面上那句「准备
        # 中…」是错的——它不在准备，它在下工具链和素材。**认的是每一行**（不
        # 是只认第一行）：`_run` 那条静默看门狗打的提醒也带这个前缀，中途接手
        # 一份状态（`parse(lines, state)`）时不至于漏掉阶段。
        if text.startswith(FETCH_PREFIX):
            return replace(state, phase=PHASE_FETCH, log=log)
        return replace(state, log=log)
    if step.total == INNER_TOTAL:
        return replace(state, inner=step, log=log)
    if step.total == OUTER_TOTAL:
        # 编号那一套开跑了，`phase` 说完了。不清的话，取回完成之后页面上会一直
        # 挂着一个早就结束了的阶段名——那也是一句假话，只是方向反过来。
        return replace(state, outer=step, phase=None, log=log)
    # 分母既不是 2 也不是 5：不知道这是哪一层，就照实说不知道。悄悄归进外层
    # 的话，将来多出来的一条 `[1/3]` 会顶掉页面上的外层进度，而日志里看不出
    # 发生过什么。行本身已经进了 log。
    return replace(state, log=log)


def parse(lines: Iterable[str], state: Progress = EMPTY) -> Progress:
    """把一串行折进状态里。`state` 可以接着上一次的往下喂。"""
    for line in lines:
        state = advance(state, line)
    return state
