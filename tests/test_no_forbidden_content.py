"""禁用内容扫描守卫。

murRipple 的视觉标杆是 sgaofen/light-loom。于淼立过一条边界：参数、技法、数值、
架构可以借鉴，但那首曲子本身的创作内容不得使用——具体是九个声部名（织梭／云幕／
星屑／潜流／纺线／拍掌／银链／鼓心／夜空）、曲名「织光」、标语。这条约束保护的
是「这个项目能公开」（主仓现在是 private，转公开是于淼要单独下令的事）。

本守卫扫描会被公开/发布的路径，确认这十个词不出现在其中——管理台文档
（MGMT.md / DECISIONS.md / BOOT.md / docs/）和 songs/ 不在扫描范围里，前者
列出这些词正是为了禁止它们，后者是于淼的真实创作素材，歌词里出现任何词都合法。
"""

import subprocess

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 十个禁用词：九个声部名 + 曲名。
FORBIDDEN = [
    "织梭", "云幕", "星屑", "潜流", "纺线", "拍掌", "银链", "鼓心", "夜空", "织光",
]

# 会被公开/发布的路径。renderer/template.html 单独列出：它会被 pack.inject()
# 原样内联进每一份 dist/index.html（逐字进入产物），却既不在 renderer/src/ 下、
# 也不进 bundle——是唯一一个「会发出去又不被其它范围覆盖」的文件。
# README.md 同理单独列出：它是这个仓最直接会被公开的文件——转公开时它就是
# 展示页/公开 demo 的说明来源，比 renderer/src/ 里任何一个模块都更贴近
# "会被人看到"。（renderer/index.html 不存在——渲染器没有独立于 src/ 之外
# 的 HTML 入口，template.html 已经覆盖了唯一的骨架文件。）
#
# 不含 renderer/dist/：它是 gitignored 的构建产物，在干净检出/别人的工作树/CI
# 上可能根本不存在，扫到空目录就绿——一个可能不存在的扫描目标，等于一个默认
# 通过的分支。也不必扫它：bundle 由 renderer/src/ 派生，源里没有的词 bundle
# 里不可能有。
#
# 不含 songs/：于淼的真实素材，不得改，歌词里出现任何词都是合法的。
# 不含 MGMT.md / DECISIONS.md / BOOT.md / docs/ 的其余部分：管理台文档，列出
# 这些词正是为了禁止它们——扫描它们会把「记录边界」本身当成违规。
#
# **但 docs/site/ 是例外，它必须扫**（2026-08-15 加）：那不是管理台文档，是
# 要挂到 murripple.miao-yu.com 的**网站**。这份守卫的判据一直是「会被公开/
# 发布的路径」，而这棵目录是全仓最字面意义上会被发布的东西——比 README.md
# 还直接。docs/ 整体被排除的理由（管理台文档）**对它不成立**，照目录前缀
# 一刀切会把这个站漏掉，而**漏掉不会有任何声音**。
SCAN_TARGETS = [
    REPO / "murripple",
    REPO / "renderer" / "src",
    REPO / "renderer" / "test",
    REPO / "renderer" / "video",
    REPO / "tests",
    REPO / "renderer" / "template.html",
    REPO / "README.md",
]

# ---- 私仓专属的那一项：`docs/site/` -----------------------------------------
#
# 2026-08-16 加。上面那八项在**两棵树里都必然存在**；这一项只在私仓存在——
# `tools/make_public_tree.py` 把整棵 `docs/` 排掉了（介绍站不进公开仓，理由见
# 那个脚本的 `reads-mgmt-docs` 一节）。而这份守卫**必须**进公开树：它是那棵树
# 最核心的守卫之一，也是 `tools/test_public_tree.py` 的锚点之一。
#
# 「目录不在就跳过」是本仓第七节明令禁止的形状（「跳过是绿色的一种」）：那样
# 一来，哪天有人在私仓里把 `docs/site/` 搬走，这份守卫会安安静静地少扫一整个
# 站，而输出跟"扫过了、干净"一模一样。
#
# 所以判据不是「目录在不在」，是「**这份检出是不是私仓**」——私仓必然有
# `MGMT.md`（`make_public_tree.py` 的 `MGMT_FILES` 把它写死排除，
# `tools/test_public_tree.py::test_the_management_console_source_files_really_exist_here`
# 钉着它在私仓里真的存在），公开树里必然没有它（同一份守卫的下一条钉着）。
# 于是：**私仓里 docs/site/ 缺席 = 报错；公开树里它缺席 = 本来就不该有。**
#
# 路径故意写成一段式的 `"docs/site"`，不是 `/ "docs" / "site"`：生成器那条
# `_REPO_DOCS` 谓词按后一种写法判「这份测试读 docs/，公开树里必然红」，
# 写成后一种会把这份守卫自己排出公开树。这处分工两边都写了注释。
_IS_PRIVATE_REPO = (REPO / "MGMT.md").is_file()
if _IS_PRIVATE_REPO:
    _SITE = REPO / "docs/site"
    assert _SITE.is_dir(), (
        f"这是私仓检出（{REPO / 'MGMT.md'} 在），却没有 {_SITE}。\n"
        "子域名介绍站是全仓最字面意义上会被发布的东西，它必须被扫。"
        "目录搬走了要人工确认扫描范围跟着改，不是可以悄悄少扫一个站。"
    )
    SCAN_TARGETS.append(_SITE)

# 扫描时跳过的目录名（编译产物/依赖目录，不是源）。
_SKIP_DIR_NAMES = {"__pycache__", "node_modules", ".git"}

# 本文件自己——它必须带着这份禁用清单，否则扫到自己就会命中全部十个词。
# 用 Path(__file__).resolve() 做「身份」排除，而不是按文件名字符串排除：
# 后者一旦这份文件被改名，排除规则就会跟着失效（新名字不再匹配旧字符串），
# 于是守卫会开始把自己当成违规文件报出来。用路径身份排除，改名后
# __file__ 自动解析成新路径，排除规则不需要跟着改。
GUARD_FILE = Path(__file__).resolve()

# 豁免：按 (相对仓库根的路径, 词) 对，绝不按行号——行号会漂，一个会随时间
# 腐烂的豁免清单比没有更危险。
#
# 「夜空」是普通词，background.js/sky.test.mjs 画的就是星空本身，与
# light-loom 的声部命名无关。豁免的是「这个文件里的这个词」，不是
# 「某几行」。
# 残余风险：如果哪天「夜空」在这两个文件里被当成声部名用（比如加一层
# 叫「夜空」的声部），这条豁免会放它过去而不会报警——豁免只保证「这个
# 词在这个文件里出现过是被审阅过的」，不保证「以后怎么用都安全」。
EXEMPT = {
    ("renderer/src/layers/background.js", "夜空"),
    ("renderer/test/sky.test.mjs", "夜空"),
}


def _iter_scan_files():
    """产出所有待扫描文件的绝对路径 —— **只取版本库跟踪的文件**。

    2026-08-14 订正：原先扫的是文件系统（`rglob`），在干净的 worktree 里
    一直是绿的，第一次在真实工作目录里跑就红了——`renderer/video/probe-out.mp4`
    是 `.gitignore:42` 明写的测试产物，守卫却把它当源码去 UTF-8 解码。
    改成 `git ls-files`：守卫的目的是「违禁内容不得进入会被公开/发布的
    路径」，而被发布的就是版本库里的东西。构建产物、缓存、临时文件本来
    就不会发布，也就不该扫。这是「守卫只扫版本库里必然存在的东西」那条
    规矩的另一半——当初只想到别扫可能不存在的，没想到别扫不该扫的。


    `SCAN_TARGETS` 里每一项今天都在版本库里、必然存在（私仓八项，公开树七项
    ——`docs/site/` 那一项只在私仓追加，理由与它自己的存在性检查写在
    `SCAN_TARGETS` 上方）。如果某一天有人删掉了其中一项（比如整个
    renderer/video/ 目录被移走），这里选择报错而不是静默跳过：跳过等于给这一项
    开了一个默认通过的分支——文件不存在时，"扫到 0 处命中"和"这里根本没扫"在
    守卫的输出里长得一模一样，前者是真的干净，后者是没检查。renderer/dist/
    因为同样的理由被排除在 SCAN_TARGETS 之外（见上面的注释），但
    SCAN_TARGETS 里列出的那几项，则是版本库里应当稳定存在的源码位置，
    缺失本身就是需要人工确认的异常，不是可以悄悄跳过的正常状态。
    """
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True
    ).stdout.decode("utf-8").split("\0")
    tracked_paths = [REPO / t for t in tracked if t]

    # ★ 锚点（2026-08-16 加）：**`git ls-files` 返回空时，这条守卫会在什么都
    # 没扫的情况下全绿。**
    #
    # 下面那圈「扫描目标存在吗」查的是**路径在不在磁盘上**，一棵刚 `git init`
    # 还没提交的树上它们全都在——于是目标齐全、`tracked_paths` 为空、内层循环
    # 一次都不进、一个词都没查，而测试是绿的。
    #
    # 实测撞到过：生成出来的公开树 `git init` 之后还没 commit，`git ls-files`
    # 返回 0 份。**唯一让它露馅的是「豁免条目变成死条目」那条副作用检查**——
    # 那是碰巧，不是设计：豁免表要是空的，这条守卫会安静地什么也不守。
    #
    # 这是本仓「空集上『某某不存在』的断言恒真」那一族，而它长在**保护发布**
    # 的那条守卫上，所以单立一个锚点。
    assert tracked_paths, (
        f"`git ls-files` 在 {REPO} 里一个文件都没返回。\n"
        "**这条守卫此刻什么也没扫，而它本来会是绿的。**\n"
        "最常见的原因是这棵树刚 `git init`、还没有任何提交（生成出来的公开树"
        "就是这个状态）。先提交，或者在一棵有提交的树上跑。"
    )

    for target in SCAN_TARGETS:
        if not target.exists():
            raise AssertionError(
                f"扫描目标不存在：{target}\n"
                "这条路径在 SCAN_TARGETS 里被列为必须扫描的源码位置。"
                "它消失可能意味着代码被移动了（守卫需要跟着改扫描范围），"
                "也可能是误删——两种情况都需要人工确认，所以这里选择报错，"
                "而不是当作「没有可扫的东西」悄悄跳过。"
            )

    for path in tracked_paths:
        for target in SCAN_TARGETS:
            if path == target or target in path.parents:
                yield path
                break


def _scan():
    """扫一遍所有目标文件，返回 (违规列表, 用到的豁免条目集合)。"""
    used_exemptions = set()
    violations = []

    for path in _iter_scan_files():
        if path == GUARD_FILE:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            # 不 continue：跟 _iter_scan_files 里"扫描目标不存在就报错"是
            # 同一条论证——文件存在但解不出码时，"扫到 0 处命中"和
            # "这个文件根本没被检查过"在守卫的输出里长得一模一样。这里
            # 不留"非文本文件，跳过"这条静默分支的理由是：SCAN_TARGETS
            # 那几项（murripple/、renderer/src|test|video、tests/、
            # template.html、README.md，私仓再加 docs/site/）全是源码/
            # 文档目录，不是资产目录
            # ——没有任何一份是本项目会合法放二进制文件的地方（图片、
            # 音频等产物一律在 songs/**/build 或 renderer/dist 下，两者
            # 都不在扫描范围内）。也就是说这里目前**没有"binary assets，
            # 预期会解码失败"这种已知的合法例外要写下来；如果哪天真的
            # 有人往这些目录里放了一个非 UTF-8 文件，那本身就是需要人工
            # 确认的异常情况，应该被看见，不该被这条 except 悄悄吃掉。
            raise AssertionError(
                f"{path.relative_to(REPO)} 不是合法的 UTF-8 文本，无法扫描。\n"
                "这条路径在 SCAN_TARGETS 覆盖范围内，理应是源码/文档，不是二进制"
                "资产——本项目目前没有向这些目录放二进制文件的合法用例。如果这是"
                "误放的产物，删掉或移到 songs/**/build、renderer/dist 之类已被"
                "排除的目录；如果确实需要在这里放一个非文本文件，把它加进一条"
                "带理由的例外，而不是让扫描静默跳过它。"
            ) from exc

        rel = path.relative_to(REPO).as_posix()
        for word in FORBIDDEN:
            if word not in text:
                continue
            key = (rel, word)
            if key in EXEMPT:
                used_exemptions.add(key)
                continue
            count = text.count(word)
            violations.append(f"  {rel}: 「{word}」× {count}")

    return violations, used_exemptions


def test_forbidden_song_content_does_not_appear_in_shippable_paths():
    """light-loom 的九个声部名、曲名「织光」不得出现在会被公开/发布的路径里。"""
    violations, _ = _scan()
    assert not violations, (
        "发现 light-loom 的创作内容词汇出现在会被公开/发布的路径里，"
        "这条边界保护的是「这个项目能公开」：\n" + "\n".join(violations)
    )


def test_exemptions_are_all_still_used():
    """豁免清单里的每一条都必须真的命中过，否则清理它。

    一条不再需要的豁免不会主动报错——它只会安静地留在源码里，直到有人
    手工发现并删掉。这条断言把"发现"这一步自动化：如果 background.js 或
    sky.test.mjs 里的「夜空」被改写掉了，EXEMPT 里对应的条目就变成了
    死条目，下一次跑测试就会被这里点名，而不是永远留着等人手工审查。
    """
    _, used_exemptions = _scan()
    stale = EXEMPT - used_exemptions
    assert not stale, (
        "以下豁免条目已经不再命中任何词，是死条目，请从 EXEMPT 里删掉：\n"
        + "\n".join(f"  {rel}: 「{word}」" for rel, word in sorted(stale))
    )
