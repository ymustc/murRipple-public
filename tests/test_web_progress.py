"""进度解析：把 `murripple` 的 stdout 一行一行读成「外层 / 内层 / 日志」。

**这里的夹具是 2026-08-14 从真实运行里抄下来的原文，一个字符都没有动过**
（含空行、含缩进、含全角的 `：`／`（）`）。逐行核对过 `murripple/cli.py` 的
`print()`：

| 夹具那一行 | 出处 |
|---|---|
| `[1/2] 分析` | `cli.py:706` |
| `[1/5] 分离音源：跳过（…9 条现成分轨）` | `cli.py:300` |
| `[2/5] 读取分轨` / `[3/5] 对齐歌词` | `cli.py:314` / `cli.py:363` |
| `  未找到 lyrics.txt，跳过歌词层。` | `cli.py:368`，**缩两格** |
| `[4/5] 编码音频` / `[5/5] 组装 timeline` | `cli.py:391` / `cli.py:395` |
| 空行 + `完成：…` | `cli.py:422` 是 `print(f"\\n完成：{out}")`，空行来自 `\\n` |
| `  时长 141.5s · …` | `cli.py:423-426` |
| `[2/2] 打包` | `cli.py:712` |
| `      → …（14.2 MB）` | `cli.py:718`，**缩六格** |
| `[1/2] 分析    跳过（…用 --force 重来）` | `cli.py:704`，`分析` 后四个空格 |

**为什么这份夹具的形状本身就是判据**：spec 原先写「按缩进区分内外层」，抓到
真实输出才发现 `[1/5]` 这些内层行**也在第 0 列，一个空格都没有**——真正的
判别是**分母**（`/2` 外层、`/5` 内层，`run`、`ingest`、`compose` 三条流程
同形）。缩进标记的是**子消息**（降级说明、结果摘要），不是层级。

所以：**任何用缩进推层级的实现，必须在这份夹具下红。** 如果哪天有人「整理」
了这份夹具、给内层行补上缩进，这条守卫会立刻变成永真——那正是本仓栽过八次
的形状。改夹具之前先重跑一次真实 `murripple run`。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from murripple.web import progress

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

# 两份真跑输出的**原件**在 `.superpowers/sdd/2026-08-14-w1-local-shell/` 下，
# 而那整个目录被 `.superpowers/sdd/.gitignore` 的 `*` 挡在版本库外面。测试不
# 能读版本库外的文件——换台机器、新克隆一份，这个文件会在 import 期就
# FileNotFoundError（连红都算不上，是 collection error）。所以夹具**逐字节复
# 制**进了 `tests/fixtures/`，下面 `…_are_still_the_bytes_they_were_copied_as`
# 那条守卫在原件还在的时候顺手比一次两边是否一致。
SDD_DIR = REPO_ROOT / ".superpowers" / "sdd" / "2026-08-14-w1-local-shell"

# ------------------------------------------------------------------ 真实夹具

# 一次完整的 `murripple run`（stems 已存在、没有 lyrics.txt）。
REAL_RUN_STDOUT = """\
[1/2] 分析
[1/5] 分离音源：跳过（build/stems/ 下已有 9 条现成分轨）
[2/5] 读取分轨
[3/5] 对齐歌词
  未找到 lyrics.txt，跳过歌词层。
[4/5] 编码音频
[5/5] 组装 timeline

完成：/…/build/timeline.json
  时长 141.5s · 95.7 BPM · 8 条轨道 · 0 句歌词
[2/2] 打包
      → /…/dist/index.html（14.2 MB）
"""

# 另一次，走 timeline 已存在的跳过路径（内层一步都不会打印）。
REAL_SKIP_STDOUT = """\
[1/2] 分析    跳过（build/timeline.json 已存在，用 --force 重来）
[2/2] 打包
      → /…/dist/index.html（12.2 MB）
"""

# `splitlines()` 而不是 `split("\n")`：前者保住中间那个空行、又不会在末尾多出
# 一个由收尾换行制造的空串。那个空行是 `cli.py:422` 的 `\n` 打出来的真实输出，
# 不是排版。
RUN_LINES = REAL_RUN_STDOUT.splitlines()
SKIP_LINES = REAL_SKIP_STDOUT.splitlines()


def _pair(step: progress.Step | None) -> tuple[int, int] | None:
    """把一层的状态压成 `(当前, 总数)`，`None` 表示这一层还没开始。"""
    return None if step is None else (step.current, step.total)


# ------------------------------------------------------------------ 数目自检


def test_the_fixtures_are_the_shape_the_rest_of_this_file_assumes():
    """夹具本身没被人「整理」过。

    下面每一条守卫都建立在两个事实上：夹具有 12 行 / 3 行，且**内层行在第 0
    列**。这两件事一旦被悄悄改掉（补缩进、删空行、合并行），别的用例不会红，
    它们只会变得什么也证明不了——本仓栽过八次的正是这个形状。所以在这里为
    「尺子本身」立一条独立的断言。
    """
    assert len(RUN_LINES) == 12, f"完整夹具应当是 12 行，实际 {len(RUN_LINES)}"
    assert len(SKIP_LINES) == 3, f"跳过夹具应当是 3 行，实际 {len(SKIP_LINES)}"

    inner_lines = [ln for ln in RUN_LINES if "/5]" in ln]
    assert len(inner_lines) == 5, f"完整夹具里应当有 5 行内层，实际 {len(inner_lines)}"
    for line in inner_lines:
        assert line.startswith("["), (
            f"内层行 {line!r} 被加上了缩进。真实输出里内层在第 0 列——"
            "一旦补了缩进，「按缩进判层级」的实现在这份夹具下也会全绿，"
            "本文件所有变异检验就一起哑了。"
        )

    assert "" in RUN_LINES, (
        "完整夹具里那个空行不见了。它是 cli.py:422 `print(f\"\\n完成：…\")` "
        "打出来的真实输出，不是排版。"
    )


# ------------------------------------------------------------------ 两层解析


def test_the_full_run_transcript_ends_with_both_layers_where_they_really_are():
    """喂完整段真实输出：外层停在 `2/2 打包`，内层停在 `5/5 组装 timeline`。

    两层各断各的。只断一个「当前进度」的话，`5/5` 与 `2/2` 会挤在同一个格子
    里，「内层走完之后外层前进」和「进度条倒退」就没法区分了——那正是判据
    点名要能区分的两种状态。
    """
    state = progress.parse(RUN_LINES)

    assert state.outer == progress.Step(2, 2, "打包"), (
        f"外层应当停在 [2/2] 打包，实际是 {state.outer!r}"
    )
    assert state.inner == progress.Step(5, 5, "组装 timeline"), (
        f"内层应当停在 [5/5] 组装 timeline，实际是 {state.inner!r}"
    )


def test_the_skip_path_transcript_never_opens_an_inner_layer():
    """跳过路径：外层走完两步，内层**一次都没开始**（`None`，不是 `0/5`）。

    这一条是上一条的另一半。少了它，一个「内层写死成 5/5」的实现也能让上一
    条全绿。而 `None` 与 `0/5` 的区别是要给人看的：页面上该显示「没有内层」，
    不是一根停在 0 的进度条。

    外层那句话要**逐字**带着降级说明——`跳过（build/timeline.json 已存在，
    用 --force 重来）` 就长在 `[1/2] 分析` 这一行里。把 `[n/m]` 之后的原文
    丢掉的实现，会把这句话一起丢掉。
    """
    state = progress.parse(SKIP_LINES)

    assert state.outer == progress.Step(2, 2, "打包")
    assert state.inner is None, (
        f"这条流程一行 `[n/5]` 都没打印，内层应当是 None，实际是 {state.inner!r}"
    )

    first = progress.parse(SKIP_LINES[:1])
    assert first.outer == progress.Step(
        1, 2, "分析    跳过（build/timeline.json 已存在，用 --force 重来）"
    ), f"外层第一步的原文没保全：{first.outer!r}"


def test_neither_layer_ever_moves_backwards_while_the_transcript_plays():
    """逐行喂，把每一行之后的两层状态摆开对。

    这张表就是「内层走到 5/5 之后外层跳到 2/2」与「进度条从 5/5 倒退回 2/2」
    的分界：第 11 行之后外层是 `2/2` **而内层仍是 `5/5`**，两个数各自单调
    不减。把两层挤进一个字段的实现，会在这里给出 5 → 2 的倒退。
    """
    expected = [
        ((1, 2), None),  # [1/2] 分析
        ((1, 2), (1, 5)),  # [1/5] 分离音源：跳过（…）
        ((1, 2), (2, 5)),  # [2/5] 读取分轨
        ((1, 2), (3, 5)),  # [3/5] 对齐歌词
        ((1, 2), (3, 5)),  # 　未找到 lyrics.txt…（子消息，不动进度）
        ((1, 2), (4, 5)),  # [4/5] 编码音频
        ((1, 2), (5, 5)),  # [5/5] 组装 timeline
        ((1, 2), (5, 5)),  # 空行
        ((1, 2), (5, 5)),  # 完成：…
        ((1, 2), (5, 5)),  # 　时长 …
        ((2, 2), (5, 5)),  # [2/2] 打包 ← 外层前进，内层原地
        ((2, 2), (5, 5)),  # 　　　→ …（14.2 MB）
    ]
    assert len(expected) == len(RUN_LINES)

    state = progress.EMPTY
    actual: list[tuple[tuple[int, int] | None, tuple[int, int] | None]] = []
    for line in RUN_LINES:
        state = progress.advance(state, line)
        actual.append((_pair(state.outer), _pair(state.inner)))

    for index, (line, want, got) in enumerate(zip(RUN_LINES, expected, actual), 1):
        assert got == want, (
            f"第 {index} 行 {line!r} 之后：外层/内层应当是 {want}，实际 {got}"
        )

    for layer, index in (("外层", 0), ("内层", 1)):
        seen = [pair[index] for pair in actual if pair[index] is not None]
        numbers = [current for current, _ in seen]
        assert numbers == sorted(numbers), (
            f"{layer}的进度倒退了：{numbers}。这说明两层被挤进了同一个字段——"
            "内层走到 5 之后外层的 2 把它盖掉了。"
        )
        totals = {total for _, total in seen}
        assert len(totals) == 1, (
            f"{layer}途中换了分母：{totals}。同一层的分母在一条流程里是固定的，"
            "变了就说明另一层的行被收进了这一层。"
        )


# ------------------------------------------------------------------ 日志缓冲


def test_every_single_line_reaches_the_log_verbatim_and_in_order():
    """日志缓冲是**整份逐字实录**：一行不丢、一个字符不改、顺序不变。

    为什么 `[n/m]` 行也留在日志里：`[1/5] 分离音源：跳过（…）` 既是进度行
    **又是**降级说明。日志要是只收「不带 `[n/m]` 的行」，这句「跳过」就没了；
    只收「带 `[n/m]` 的行」，`  未找到 lyrics.txt，跳过歌词层。` 就没了。
    台账的规矩是降级必须大声说，两个方向都不许丢。

    这条断言是整份相等而不是「包含某几行」：`strip()` 掉缩进、吞掉空行、
    「整理格式」，都会在这里红。
    """
    state = progress.parse(RUN_LINES)
    assert list(state.log) == RUN_LINES, (
        "日志不是逐字实录。实际收到：\n"
        + "\n".join(repr(ln) for ln in state.log)
        + "\n应当是：\n"
        + "\n".join(repr(ln) for ln in RUN_LINES)
    )

    skip_state = progress.parse(SKIP_LINES)
    assert list(skip_state.log) == SKIP_LINES


@pytest.mark.parametrize(
    "notice",
    [
        "[1/5] 分离音源：跳过（build/stems/ 下已有 9 条现成分轨）",
        "  未找到 lyrics.txt，跳过歌词层。",
    ],
)
def test_the_degradation_notices_can_be_found_word_for_word_in_the_log(notice):
    """两条降级说明必须能在日志里**逐字**找到。

    特意各取一条：一条长在 `[n/m]` 行上（第 0 列），一条是缩两格的子消息。
    任何一边的过滤——只留 `[n/m]` 行、或只留不带 `[n/m]` 的行——都会让这两条
    里的某一条红。降级被静悄悄咽掉，比没做降级更糟。
    """
    state = progress.parse(RUN_LINES)
    assert notice in state.log, (
        f"降级说明 {notice!r} 没能在日志里逐字找到。日志：\n"
        + "\n".join(repr(ln) for ln in state.log)
    )


def test_only_the_line_terminator_is_stripped_not_the_indentation():
    """真实调用是从 `subprocess` 的 stdout 逐行读的，每行都带着 `\\n`。

    收尾的 `\\n` / `\\r\\n` 要去掉（否则日志里每行多一个换行），但**缩进一格
    都不许动**——`  未找到…` 缩两格、`      → …` 缩六格，都是 `cli.py` 打出
    来的原文。一个顺手写 `.strip()` 的实现在这里红。
    """
    raw = ["  未找到 lyrics.txt，跳过歌词层。\n", "      → /…/dist/index.html（14.2 MB）\r\n"]
    state = progress.parse(raw)
    assert list(state.log) == [
        "  未找到 lyrics.txt，跳过歌词层。",
        "      → /…/dist/index.html（14.2 MB）",
    ], f"实际：{[repr(ln) for ln in state.log]}"


# ------------------------------------------------------------------ 陌生分母


def test_an_unfamiliar_denominator_lands_in_the_log_but_in_neither_layer():
    """分母既不是 2 也不是 5 的行：进日志，但不冒充任何一层。

    判别的依据是分母，那么陌生的分母就是「不知道这是哪一层」，只能照实说
    不知道。悄悄归进外层的话，将来某条流程多出一个 `[1/3]`，页面上的外层
    进度会被它顶掉，而日志里看不出发生过什么。
    """
    state = progress.parse(["[1/2] 分析", "[1/3] 某个将来的步骤", "[1/5] 分离音源"])
    assert state.outer == progress.Step(1, 2, "分析")
    assert state.inner == progress.Step(1, 5, "分离音源")
    assert "[1/3] 某个将来的步骤" in state.log


# ============================================================ 日志分层（Task 3.5）
#
# 下面这两份夹具**从磁盘上的文件里读**，不在这个文件里手打一份。它们是管理
# 窗口／控制窗口真跑抄下来的原文，连 `  warnings.warn(` 这种「缩两格的第三方
# 行」都在里面——手写一份「理想的第三方噪声」，没人会想到往里塞这一行。
#
# 分层的判据是**内容白名单**，不是缩进：这份夹具里第 11 行（第三方）与第 12
# 行（我们）都缩两格，形状一模一样。
#
# **2026-08-16 重抄过一次**（出处、跑法、环境在 `tests/fixtures/README.provenance.md`）：
# 旧那一份里未对上的那句歌词是第三方作品的词。新那一份跑在示例歌
# `songs/05-trempe-moi` 的头 12 秒上，1594 字节 / 18 行。

BUILD_FIXTURE = FIXTURE_DIR / "real-build-output.txt"
FALLBACK_FIXTURE = FIXTURE_DIR / "real-fallback-output.txt"

BUILD_LINES = BUILD_FIXTURE.read_text(encoding="utf-8").splitlines()
FALLBACK_LINES = FALLBACK_FIXTURE.read_text(encoding="utf-8").splitlines()

M = progress.MAIN
D = progress.DETAIL

# 「归属」表，一行一格，顺序与文件一致。
# 注意第 11 行与第 12 行**都缩两格**，一个 DETAIL 一个 MAIN——这一列就是
# 「缩进不携带任何可靠的结构信息」这句话的判据形式。
#
# 2026-08-16 重抄后**顺序变了**：第三方那几行现在落在 `[3/5] 对齐歌词` 之后，
# 而不是整条命令的最前面。旧那一份是 2026-08-14 抄的，那时对齐还没有语言侦测
# 这一步。**顺序不是判据**，判据是每一行落进哪一块。
BUILD_EXPECTED_LAYERS = [
    M,  #  1 [1/5] 分离音源：source.mp3
    M,  #  2 [2/5] 读取分轨
    M,  #  3 [3/5] 对齐歌词
    D,  #  4 No language specified …                       第三方，第 0 列
    D,  #  5 Lightning automatically upgraded …            第三方，第 0 列
    D,  #  6 Model was trained with pyannote.audio … Bad things might happen …
    D,  #  7 Model was trained with torch … Bad things might happen …
    M,  #  8 `  语言：zh（--language 指定）`  我们，**缩两格**
    #      多语言那一棒之后 `cli.py` 新加的产品输出。旧夹具里没有它——
    #      也就是说旧夹具已经落后于产品一行，而没有任何东西会为此变红。
    D,  #  9 No active speech found in audio                第三方
    D,  # 10 /…/configuration_utils.py:312: UserWarning …  第三方，第 0 列
    D,  # 11 `  warnings.warn(`                            第三方，**缩两格**
    M,  # 12 `  以下 1 行未对上，请在 overrides.json 中补时间：`  我们，**缩两格**
    M,  # 13 `    - <一句没对上的歌词>`                   我们（用户数据），缩四格
    #      抄件里那一句取自示例歌 `songs/05-trempe-moi`（于淼自己的歌）。
    #      这张表是**我们写的注释**，没有理由跟着抄一遍。
    M,  # 14 [4/5] 编码音频
    M,  # 15 [5/5] 组装 timeline
    M,  # 16 空行（cli.py 收尾那个 `\n`）
    M,  # 17 完成：/…/build/timeline.json
    M,  # 18 `  时长 12.0s · 136.0 BPM · 6 条轨道 · 0 句歌词`
]

# 夹具 D 两行的归属。第二行是降级说明，必须进主日志（台账规矩：降级必须大声
# 说）。**第一行认不出来**——它是 `print(f"  {exc}")`，`exc` 是
# IngestError／ValueError／KeyError 中任意一个，一个 KeyError 打出来就是
# `  't0'`，跟第三方噪声长得一模一样。这里按现实记账：它落进详细区。改这一格
# 之前先想清楚白名单认它靠的是什么。
FALLBACK_EXPECTED_LAYERS = [
    D,  # 1 `  lyrics.timing.json 有 1 行，…`  我们的输出，但白名单认不出来
    M,  # 2 `  退回常规对齐。`                  cli.py:436
]


# ------------------------------------------------------------ 尺子本身


def test_the_two_real_fixtures_are_still_the_bytes_they_were_copied_as():
    """两份夹具的字节数／行数／`\\r` 数，一个都不许变。

    下面每一条守卫都建立在「这两个文件是真跑抄来的原文」上。谁要是顺手
    「整理」了它们——把 `  warnings.warn(` 的缩进去掉、把两行第三方噪声删掉、
    从 LF 改成 CRLF——别的用例不会红，它们只会变得什么也证明不了。所以在这里
    为尺子本身立一条独立的断言。
    """
    build = BUILD_FIXTURE.read_bytes()
    assert len(build) == 1594, f"real-build-output.txt 应当是 1594 字节，实际 {len(build)}"
    assert len(BUILD_LINES) == 18, f"应当是 18 行，实际 {len(BUILD_LINES)}"
    assert build.count(b"\r") == 0, "这份夹具里一个 \\r 都没有，出现了就说明被改过"

    fallback = FALLBACK_FIXTURE.read_bytes()
    assert len(fallback) == 209, (
        f"real-fallback-output.txt 应当是 209 字节，实际 {len(fallback)}"
    )
    assert len(FALLBACK_LINES) == 2, f"应当是 2 行，实际 {len(FALLBACK_LINES)}"
    assert fallback.count(b"\r") == 0

    # 降级那一份仍然是 2026-08-14 的原件，`.superpowers/sdd/` 下那一份
    # （被 gitignore 挡着，不是每台机器上都有）在的时候顺手比一次。
    #
    # **`real-build-output.txt` 不再比**：它 2026-08-16 重抄过（旧那一份里
    # 未对上的那句是第三方作品的歌词），出处、跑法、环境写在
    # `tests/fixtures/README.provenance.md` 里，`.superpowers/sdd/` 下那一份
    # 是被替换掉的旧原件，按它比会永远红。
    original = SDD_DIR / "real-fallback-output.txt"
    if original.exists():
        assert FALLBACK_FIXTURE.read_bytes() == original.read_bytes(), (
            f"{FALLBACK_FIXTURE} 跟原件 {original} 不是同一份了。夹具的全部价值就是"
            "「真跑抄下来的原文」，两边一分家就说明有人手改过其中一份。"
        )

    # 分层这件事的全部难点都压在这一条上：两行缩两格，一个第三方一个我们。
    assert BUILD_LINES[10] == "  warnings.warn(", (
        f"第 11 行应当是缩两格的第三方 `  warnings.warn(`，实际 {BUILD_LINES[10]!r}"
    )
    assert BUILD_LINES[11].startswith("  以下 "), (
        f"第 12 行应当是缩两格的、我们自己的「以下 N 行未对上」，实际 {BUILD_LINES[11]!r}"
    )


def test_the_recaptured_build_fixture_has_its_provenance_written_down():
    """★ 重抄的那一份**必须带着出处**。

    2026-08-16 这一份是重抄的，而「真跑抄件」与「照着旧那份改了一句的假抄件」
    在仓里长得一模一样——分辨它们的唯一东西就是旁边那份出处，以及出处里那段
    任何人都能重跑一遍的命令。

    顺带：这条断言让 `README.provenance.md` 在
    `tools/make_public_tree.py` 的 `orphan-fixture` 规则眼里**有了一个真消费者**
    ——否则一份没有任何代码提到的出处文档会被当成孤儿摘掉，抄件进了公开树、
    它的来历没进。
    """
    sidecar = (FIXTURE_DIR / "README.provenance.md").read_text(encoding="utf-8")
    assert "real-build-output.txt" in sidecar, "出处里没提这份抄件，它等于没有来历。"
    assert "uv run murripple build" in sidecar, "出处里没有可执行的重抄步骤。"
    assert "--language zh" in sidecar, (
        "出处里没写 `--language zh`——那是这份抄件唯一需要解释的地方："
        "喂进去的是法语素材，而 `  warnings.warn(` 那一行只有中文对齐模型才触发。"
    )
    assert str(len(BUILD_FIXTURE.read_bytes())) in sidecar, (
        "出处里记的字节数跟盘上这一份对不上——两边一分家，出处就开始说谎了。"
    )


# ------------------------------------------------------------ 判据 ①：一行都不丢


def test_every_one_of_the_eighteen_real_lines_survives_in_the_full_log():
    """判据 ①：夹具 C 那 18 行**全部**在完整日志里，逐字，顺序不变。

    分层是「摆到哪一块」，不是「留不留」。一行都不丢是这一棒的前提——过滤掉
    第三方噪声的实现在这里红。
    """
    state = progress.parse(BUILD_LINES)
    assert list(state.log) == BUILD_LINES, (
        "完整日志不是逐字实录。实际收到：\n"
        + "\n".join(repr(ln) for ln in state.log)
    )


def test_the_two_stacks_put_back_together_are_exactly_the_full_log():
    """主日志 + 详细区 = 完整日志，顺序不变，一行不多一行不少。

    这一条是「分错只是位置不对，不会丢」的结构形式：`layers` 与 `log` 一一
    对应，所以任何一行都能且只能落进一块。少了它，一个「认不出来就扔掉」的
    实现可以让判据 ②（主日志里没有噪声）全绿。
    """
    state = progress.parse(BUILD_LINES)
    assert len(state.layers) == len(state.log), (
        f"layers {len(state.layers)} 条、log {len(state.log)} 条，对不上"
    )
    assert set(state.layers) <= {progress.MAIN, progress.DETAIL}, (
        f"出现了第三种归属：{set(state.layers)}"
    )

    merged = [
        line
        for line, layer in zip(state.log, state.layers)
        if layer in (progress.MAIN, progress.DETAIL)
    ]
    assert merged == BUILD_LINES
    assert len(state.main) + len(state.detail) == len(BUILD_LINES)
    # 各自内部的顺序也不许乱
    assert list(state.main) == [
        ln for ln, layer in zip(BUILD_LINES, state.layers) if layer == progress.MAIN
    ]


# ------------------------------------------------- 判据 ②③ + 那张归属表


def test_all_eighteen_real_lines_land_where_the_layer_table_says_they_land():
    """整张归属表，一行一格。

    **这是「按缩进」那条变异检验的靶子。** 判据 ② 断的是「主日志里没有
    `Bad things might happen` 那两行」，而那两行本来就在第 0 列——按缩进分类
    根本不影响它们。真正会红的是第 11 行 `  warnings.warn(`：它缩两格，任何
    按缩进分类的实现都会把它当成「我们的子消息」放进主日志。
    """
    state = progress.parse(BUILD_LINES)
    assert len(BUILD_EXPECTED_LAYERS) == len(BUILD_LINES)

    for index, (line, want, got) in enumerate(
        zip(BUILD_LINES, BUILD_EXPECTED_LAYERS, state.layers), 1
    ):
        assert got == want, (
            f"第 {index} 行 {line!r} 应当归 {want}，实际归了 {got}。"
            "（分类只看内容白名单：这份输出里缩进不携带任何可靠的结构信息，"
            "第 11 行第三方与第 12 行我们的行都缩两格。）"
        )


def test_the_scary_third_party_lines_are_not_in_the_main_log_as_whole_lines():
    """判据 ②：`Bad things might happen` 那两行不在主日志里。

    断的是**整行精确相等**，不是子串：`state.main` 是一个字符串元组，`not
    in` 比的是元素相等。用子串断言的话，用户歌词里出现同样的字就会误判——
    而 `    - <歌词原文>` 那一行是会进主日志的，歌词是**用户数据**。
    """
    scary = [ln for ln in BUILD_LINES if "Bad things might happen" in ln]
    assert len(scary) == 2, (
        f"夹具里应当有两行 `Bad things might happen`，实际 {len(scary)} 行——"
        "夹具被改过，这条守卫已经什么都不证明了"
    )

    state = progress.parse(BUILD_LINES)
    for line in scary:
        assert line not in state.main, (
            f"这一行吓人的第三方噪声跑进了主日志：{line!r}"
        )
        assert line in state.detail, (
            f"这一行既不在主日志、也不在详细区，它被丢掉了：{line!r}"
        )


def test_the_unmatched_lyrics_notice_and_the_lyrics_themselves_are_in_the_main_log():
    """判据 ③：「以下 1 行未对上」必须在主日志里，跟着它的歌词原文也是。

    它缩两格，跟第 11 行 `  warnings.warn(` 形状一模一样——一个进主日志，一个
    进详细区。歌词那一行是**用户数据**，白名单认的是 `    - ` 这个形状，不是
    内容。
    """
    state = progress.parse(BUILD_LINES)
    assert BUILD_LINES[11] in state.main, (
        f"「以下 N 行未对上」没进主日志：{BUILD_LINES[11]!r}。主日志：\n"
        + "\n".join(repr(ln) for ln in state.main)
    )
    assert BUILD_LINES[12] in state.main, (
        f"未对上的歌词原文没进主日志：{BUILD_LINES[12]!r}"
    )


# ------------------------------------------------------------ 判据 ④：认不出来也不丢


@pytest.mark.parametrize(
    "line",
    [
        "谁也不认识的一行",
        "  缩两格的、谁也不认识的一行",
        "Some future third-party chatter nobody has seen yet",
        "",
    ],
)
def test_a_line_nobody_recognises_still_shows_up_in_the_full_log(line):
    """「分错只是位置不对，不会丢」——这句话得有人守着。

    只写在注释里的话，它就是一句没人守的承诺。喂一行谁都不认识的输入：归哪
    一层随实现去判，但**完整日志里必须找得到它**。
    """
    state = progress.advance(progress.EMPTY, line)
    assert list(state.log) == [line], (
        f"认不出来的行被丢掉了：{line!r}，日志是 {list(state.log)!r}"
    )
    assert len(state.layers) == 1
    assert line in state.main or line in state.detail, (
        f"{line!r} 既不在主日志也不在详细区"
    )


def test_an_unrecognised_line_lands_in_the_detail_pane_not_the_main_log():
    """认不出来的行往**详细区**落——这是刻意选的失败方向。

    白名单认不出来的东西默认当噪声，宁可让我们自己的某一行掉进折叠区（用户
    展开就看得见），也不让第三方的吓人话跳到主日志上。
    """
    state = progress.advance(progress.EMPTY, "谁也不认识的一行")
    assert state.layers == (progress.DETAIL,)
    assert state.detail == ("谁也不认识的一行",)
    assert state.main == ()


# ------------------------------------------------------------ 判据 ⑤：夹具 D


def test_the_fallback_notice_is_loud_and_its_dynamic_neighbour_is_recorded():
    """判据 ⑤：`  退回常规对齐。` 必须在主日志里（降级必须大声说）。

    它的上一行是 `print(f"  {exc}")`——动态文本，`exc` 换一个类型就换一副
    长相（`KeyError` 打出来是 `  't0'`），**任何白名单都认不出来**。这里不
    硬凑：那一行落进详细区，但一定在完整日志里。
    """
    state = progress.parse(FALLBACK_LINES)

    assert list(state.log) == FALLBACK_LINES
    assert list(state.layers) == FALLBACK_EXPECTED_LAYERS, (
        "夹具 D 的归属变了。实际：\n"
        + "\n".join(
            f"{layer} | {line!r}" for line, layer in zip(FALLBACK_LINES, state.layers)
        )
    )
    assert "  退回常规对齐。" in state.main, (
        "降级说明没进主日志。台账规矩：降级必须大声说。主日志：\n"
        + "\n".join(repr(ln) for ln in state.main)
    )


# ------------------------------------------- 白名单是照着 cli.py 抄的，不是编的


# 左边是 `murripple/cli.py` 源码里那一段**字面量**，右边是它打出来的一行的
# 样子。左边这一列的意义：样例行是照着源码写的，不是我凭印象编的——源码里
# 那句话改了字，这张表当场红，而不是等到用户在页面上看见错位。
#
# 管理窗口手上的清单只有 9 条（`[n/m]`、未找到 lyrics.txt、用硬字幕、以下 N
# 行未对上、`    - 歌词`、完成、时长、`      → 路径`、退回常规对齐）。下面
# 带 ★ 的是**清单外**、我在 cli.py 里翻出来的，照现实补进去的。
OUR_SHAPES = [
    # —— build()（run 这条流程，网页壳子最常跑到的）——
    ('print(f"分离失败：{exc}", file=sys.stderr)', "分离失败：demucs 没装"),  # ★
    ('f"读不了分轨 {path.name}（{path}）：', "读不了分轨 vocals.wav（/x/vocals.wav）：EOFError: "),  # ★
    ('f"  这个文件是空的或者损坏了。删掉 {path.parent} 重跑一次。"', "  这个文件是空的或者损坏了。删掉 /x/stems 重跑一次。"),  # ★
    ('print(f"音频仅 {duration:.1f} 秒，太短，中止。", file=sys.stderr)', "音频仅 3.0 秒，太短，中止。"),  # ★
    ('f"警告：音频 {duration / 60:.1f} 分钟，产物体积会很大。"', "警告：音频 12.5 分钟，产物体积会很大。"),  # ★
    ('要的分轨 ', "/x/build/lanes.json 要的分轨 pad 不在 /x/build/stems 里；现有：bass、drums。"),  # ★
    ('print("  未找到 lyrics.txt，跳过歌词层。")', "  未找到 lyrics.txt，跳过歌词层。"),
    ('f"  用硬字幕的演唱时刻，跳过 WhisperX（{len(lyrics)} 行）"', "  用硬字幕的演唱时刻，跳过 WhisperX（12 行）"),
    ('f"  以下 {len(unmatched)} 行未对上，请在 overrides.json 中补时间："', "  以下 3 行未对上，请在 overrides.json 中补时间："),
    ('print(f"    - {line}")', "    - 谁先眨眼就输"),
    ('print("  降级为无歌词，继续。")', "  降级为无歌词，继续。"),  # ★ 降级，必须大声说
    ('print(f"overrides.json 有问题：{exc}", file=sys.stderr)', "overrides.json 有问题：t0 不是数字"),  # ★
    ('print(f"      已应用 {song_dir / overrides.FILENAME}")', "      已应用 /x/overrides.json"),  # ★
    ('print(f"\\n完成：{out}")', "完成：/x/build/timeline.json"),
    ('print(f"  时长 {doc[\'meta\'][\'duration\']:.1f}s · "', "  时长 141.5s · 95.7 BPM · 8 条轨道 · 0 句歌词"),
    # —— load_subtitle_timing ——
    ('print("  退回常规对齐。")', "  退回常规对齐。"),
    # —— ingest()（含 scan 的 notes）——
    ('print(f"素材看不明白：{exc}", file=sys.stderr)', "素材看不明白：`_in/` 里没有任何音频或视频"),  # ★
    ('f"扫描 `_in/`：{seen}"', "  扫描 `_in/`：a.wav、b.mp4"),  # ★ scan.py:102，经 cli.py:455 缩两格
    ('f"音频 ← {standalone.name}"', "  音频 ← a.wav"),  # ★ scan.py:112/120/123
    ('f"歌词 ← {video.name} 的硬字幕（OCR，顺带拿到每行的出现时刻）"', "  歌词 ← b.mp4 的硬字幕（OCR，顺带拿到每行的出现时刻）"),  # ★
    ('"忽略（用不上）："', "  忽略（用不上）：readme.md"),  # ★
    ('print(f"      → {out.name}")', "      → source.wav"),
    ('print("      一行都没认出来，请自己写 lyrics.txt", file=sys.stderr)', "      一行都没认出来，请自己写 lyrics.txt"),  # ★
    ('print(f"整理失败：{exc}", file=sys.stderr)', "整理失败：抽轨失败"),  # ★
    ('f"  uv run murripple run {song_dir}"', "  uv run murripple run /x/songs/一首歌"),  # ★
    ('f"\\n完成。请先过一眼 {song_dir / \'lyrics.txt\'}，确认无误后：\\n"', "完成。请先过一眼 /x/lyrics.txt，确认无误后："),  # ★
    # —— compose() ——
    ('不存在。先跑一次', "/x/compose.json 不存在。先跑一次**不带** --from-score 的 compose 摇一首出来：`murripple compose /x`。"),  # ★
    ('读不动：{exc}', "compose.json 读不动：seed 不是整数"),  # ★
    ('f"不认识的调式 {scale!r}。可选："', "不认识的调式 'blues'。可选：major、minor"),  # ★
    ('里有两段都叫', "/x/compose.json 里有两段都叫 'verse'。段落名要各不相同"),  # ★
    ('print(f"      已作废 {timeline.name}（描述的是上一首，run 会重新分析）")', "      已作废 timeline.json（描述的是上一首，run 会重新分析）"),  # ★
    ('f"  分轨 → {paths[\'vocals\'].parent}\\n\\n"', "  分轨 → /x/build/stems"),  # ★
    ('段 · ', "  150.0s · 5 段 · 420 个音符"),  # ★
    ('f"先把那 {len(paths)} 条 wav 一起放来听听', "先把那 9 条 wav 一起放来听听，不满意就换个 seed 重摇；满意了再："),  # ★
    # —— run() / pack ——
    ('下没有 lyrics.txt。先跑', "/x/songs/一首歌 下没有 lyrics.txt。先跑 `murripple ingest /x/songs/一首歌`，或者自己写一份。"),  # ★
    ('print(f"打包失败：{exc}", file=sys.stderr)', "打包失败：renderer 没 build"),  # ★
    ('print(f"      → {out}（{out.stat().st_size / 1e6:.1f} MB）")', "      → /x/dist/index.html（14.2 MB）"),
    ('  体积 {size_mb:.1f} MB', "  体积 12.3 MB"),  # ★
    ('f"警告：产物 {size_mb:.1f} MB 超过 15 MB 上限"', "警告：产物 16.1 MB 超过 15 MB 上限"),  # ★
    ('f"不认识的音名 {args.key!r}。可选："', "不认识的音名 'H'。可选：C、D"),  # ★
]

CLI_SOURCE = (REPO_ROOT / "murripple" / "cli.py").read_text(encoding="utf-8")
SCAN_SOURCE = (REPO_ROOT / "murripple" / "ingest" / "scan.py").read_text(encoding="utf-8")
# 「这首歌要不要歌词」那句话 2026-08-15 搬进了 `murripple/lyrics_gate.py`——
# 全仓唯一那一处判断。**钉子跟着字符串走**：它守的是"这条白名单还认得住
# 管线真会打的话"，不是"那句话必须长在 cli.py 里"。
GATE_SOURCE = (REPO_ROOT / "murripple" / "lyrics_gate.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("source_fragment,sample", OUR_SHAPES)
def test_each_shape_in_the_whitelist_is_a_shape_the_pipeline_really_prints(
    source_fragment, sample
):
    """样例行是**照着源码抄的**，不是照着印象编的。

    这一条守的是白名单最容易烂掉的地方：我照着 `cli.py` 写下一个样例，白名单
    认得它，测试全绿——而真实那句话其实多了个字，用户在页面上看到的还是错位
    的。所以每一条都要求那段字面量**此刻仍在源码里**。

    管线是只读的，这条断言不会拦住谁；它只保证这张表跟源码一起变老。
    """
    assert (
        source_fragment in CLI_SOURCE
        or source_fragment in SCAN_SOURCE
        or source_fragment in GATE_SOURCE
    ), (
        f"源码里已经没有 {source_fragment!r} 了——白名单的这一条停在旧版本上，"
        "它认的那个形状可能已经不是管线打出来的了。重新抄一遍。"
    )


@pytest.mark.parametrize("source_fragment,sample", OUR_SHAPES)
def test_every_line_we_print_ourselves_reaches_the_main_log(source_fragment, sample):
    """我们自己打的每一种形状都归主日志。

    判据 ③ 只钉住了「以下 N 行未对上」一条。管线打出来的形状远不止这一条，
    每一条掉进折叠区，都是一句用户看不见的话。
    """
    assert progress.classify(sample) == progress.MAIN, (
        f"{sample!r} 是我们自己打的（源码：{source_fragment}），却归了详细区"
    )


def test_the_progress_lines_of_all_three_flows_are_ours():
    """`run`／`ingest`／`compose` 三条流程的进度行都归主日志。

    分母不一样（`/2`、`/5`），文案也不一样，但形状是同一个。
    """
    for line in (
        "[1/2] 分析",
        "[1/5] 分离音源：source.mp3",
        "[1/2] 准备音频 ← a.wav",
        "[2/2] 歌词    跳过（lyrics.txt 已存在，用 --force 重来）",
        "[1/2] 读谱     ← compose.json（seed 7）",
        "[1/2] 作曲     seed 7 · 96 BPM · Cmajor",
        "[2/2] 合成分轨",
    ):
        assert progress.classify(line) == progress.MAIN, f"{line!r} 没归主日志"


def test_classify_takes_a_raw_line_off_the_pipe_terminator_and_all():
    """真实调用是从 `subprocess` 的 stdout 逐行读的，行尾带着换行符。

    分类要跟日志实录看同一个东西：`  退回常规对齐。\\n` 与 `  退回常规对齐。`
    必须是同一个归属，否则 Task 4 的 runner 会因为「有没有剥换行符」而得到两
    个不同的答案。
    """
    assert progress.classify("  退回常规对齐。\n") == progress.MAIN
    assert progress.classify("  退回常规对齐。\r\n") == progress.MAIN
    assert progress.classify("  warnings.warn(\n") == progress.DETAIL
