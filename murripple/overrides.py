"""手工精修层。

`songs/<slug>/overrides.json` 在 build 的最后一步合并进 timeline。自动分析
不满意的地方改这个文件重跑，不动代码——这是"通用管线打底 + 重点歌精修"
里精修的落点。

三条设计决定：

一、**深合并，不是替换。** 只写了 `gain` 的那条轨道，其余字段必须原样
    保留。浅合并会把整条 lane 换掉、envelope 与 notes 全丢，而产出仍是
    合法 JSON、schema 也过——只有画面会莫名其妙地空掉，最难查。

二、**未知字段当场报错。** 静默忽略是最坏的：用户改了半天没反应，会以为
    是渲染层的问题。报错还要指出是哪个字段。

三、**缺文件不是错误。** 绝大多数歌不需要精修。
"""

from __future__ import annotations

import json
from pathlib import Path

FILENAME = "overrides.json"

TOP_KEYS = {"meta", "sections", "lanes", "lyrics"}
META_KEYS = {"title"}
SECTION_KEYS = {"name", "energy"}
LANE_KEYS = {"gain", "hue", "label"}
LYRICS_KEYS = {"offset", "lines", "insert"}
LINE_KEYS = {"t0", "t1", "text"}

#: 插一行必须三样都给。`lines` 那边是**补丁**（改哪个给哪个），这边是**整行**
#: ——缺 `t1` 的话渲染层不知道它什么时候该暗下去，缺 `text` 就是一行看不见的
#: 歌词占着一段时间，比不插更难查。
INSERT_KEYS = {"t0", "t1", "text"}


class OverrideError(ValueError):
    """overrides.json 有问题。消息里必须指出是哪个字段。"""


def _check_keys(obj: dict, allowed: set[str], where: str) -> None:
    unknown = set(obj) - allowed
    if unknown:
        raise OverrideError(
            f"{where} 里有无法识别的字段：{', '.join(sorted(unknown))}。"
            f"可用的是：{', '.join(sorted(allowed))}"
        )


def load(song_dir: Path) -> dict:
    """读取 overrides.json。文件不存在时返回空字典。"""
    path = Path(song_dir) / FILENAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OverrideError(f"{path} 不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise OverrideError(f"{path} 的顶层应当是一个对象")
    return data


def apply(doc: dict, over: dict) -> dict:
    """把 overrides 合并进 timeline，返回新文档（不改原对象）。"""
    if not over:
        return doc
    _check_keys(over, TOP_KEYS, "overrides.json")

    out = json.loads(json.dumps(doc))  # 深拷贝，调用方的原始文档不受影响

    if "meta" in over:
        _check_keys(over["meta"], META_KEYS, "meta")
        out["meta"].update(over["meta"])

    if "sections" in over:
        _apply_indexed(out["sections"], over["sections"], SECTION_KEYS, "sections")

    if "lanes" in over:
        _apply_by_id(out["lanes"], over["lanes"], LANE_KEYS, "lanes")

    if "lyrics" in over:
        _apply_lyrics(out, over["lyrics"])

    return out


def _apply_indexed(target: list, patch, allowed: set[str], where: str) -> None:
    """按下标打补丁。patch 是 {"0": {...}} 或按序的列表。"""
    items = patch.items() if isinstance(patch, dict) else enumerate(patch)
    for key, val in items:
        try:
            i = int(key)
        except (TypeError, ValueError) as exc:
            raise OverrideError(f"{where} 的下标 {key!r} 不是整数") from exc
        if not 0 <= i < len(target):
            raise OverrideError(
                f"{where} 里的下标 {i} 越界——一共只有 {len(target)} 项"
            )
        if val is None:
            continue
        _check_keys(val, allowed, f"{where}[{i}]")
        target[i].update(val)


def _apply_by_id(target: list, patch: dict, allowed: set[str], where: str) -> None:
    """按 id 打补丁。轨道用 id 而不是下标——下标会随管线改动而变。"""
    known = {item["id"]: item for item in target}
    for lane_id, val in patch.items():
        if lane_id not in known:
            raise OverrideError(
                f"{where} 里没有叫 {lane_id!r} 的轨道。"
                f"现有的是：{', '.join(known)}"
            )
        _check_keys(val, allowed, f"{where}.{lane_id}")
        known[lane_id].update(val)


def _insert_lines(lyrics: list, patch, where: str = "lyrics.insert") -> None:
    """把补录的整行插进去。**位置由 `t0` 决定，不由下标决定。**

    对齐会整句整句地丢（私仓 `songs/04` 丢了三行），而 `lines` 只能改
    已有句子。没有这一条，那首歌重跑 `build` 会在 `lyrics.lines 里的下标 61
    越界` 上当场失败——一个 timeline 都产不出来。

    **为什么不给下标**：`lines` 的下标打进一个数量会变的列表已经是 M4 栽过的
    那一跤，而插入**本身就在改变数量**，再按下标定位是同一个错的加强版。
    自带绝对时刻、按 `t0` 归位，与「段落名走真值不走下标」同源。

    并列（`t0` 与已有行相同）时**排在已有行之后**：并列也得有个定死的答案，
    不能看谁先谁后碰运气。
    """
    if not isinstance(patch, list):
        raise OverrideError(
            f"{where} 应当是一个数组，每项是一整行 "
            f"{{\"text\": …, \"t0\": …, \"t1\": …}}，实得 {type(patch).__name__}"
        )
    for i, item in enumerate(patch):
        if not isinstance(item, dict):
            raise OverrideError(
                f"{where}[{i}] 应当是一个对象，实得 {type(item).__name__}"
            )
        _check_keys(item, INSERT_KEYS, f"{where}[{i}]")
        missing = sorted(INSERT_KEYS - set(item))
        if missing:
            # 只点名缺的那几个：把三个字段全列出来的话，三种缺法给的是同一
            # 句话，读的人还得自己去比对。
            raise OverrideError(f"{where}[{i}] 缺少：{'、'.join(missing)}")
        for key in ("t0", "t1"):
            if not isinstance(item[key], (int, float)) or isinstance(item[key], bool):
                raise OverrideError(
                    f"{where}[{i}].{key} 应为数字，实得 {item[key]!r}"
                )
        if not isinstance(item["text"], str) or not item["text"].strip():
            raise OverrideError(
                f"{where}[{i}].text 是空的——插一行看不见的歌词占着一段时间，"
                f"比不插更难查"
            )
        if item["t1"] < item["t0"]:
            raise OverrideError(
                f"{where}[{i}] 的 t1 {item['t1']:.2f} 早于 t0 "
                f"{item['t0']:.2f}——时间倒挂"
            )

    # 落点是**绝对的**（"排在第一条 t0 比我大的行前面"），所以每一条插进来都
    # 与其它条互不影响，**给的顺序不影响结果**——`insert` 是一组补录，不是一份
    # 要按顺序执行的剧本。
    #
    # 这里原本先 `sorted(patch, key=t0)` 再插。**变异检验 Y5 把那一行整个删掉，
    # 36 条测试全绿**——因为绝对落点本来就与顺序无关，排序改变不了任何结果。
    # 照台账那条规矩（手写的、删掉照样绿的就是死代码），删掉；顺序语义改由
    # `test_两条同一时刻的补录按给的顺序排` 钉住。
    for item in patch:
        at = len(lyrics)
        for i, line in enumerate(lyrics):
            if line["t0"] > item["t0"]:
                at = i
                break
        lyrics.insert(at, {"t0": item["t0"], "t1": item["t1"], "text": item["text"]})


def _apply_lyrics(out: dict, patch: dict) -> None:
    """歌词：整体偏移 + 补录整行 + 单句覆盖。三样的先后是承重的。"""
    _check_keys(patch, LYRICS_KEYS, "lyrics")

    offset = patch.get("offset", 0)
    if not isinstance(offset, (int, float)):
        raise OverrideError(f"lyrics.offset 应为数字，实得 {offset!r}")
    if offset:
        for line in out["lyrics"]:
            line["t0"] += offset
            line["t1"] += offset

    # 补录排在整体偏移**之后**：补录的时刻是人对着画面量出来的绝对时刻，
    # 跟 `lines` 的单句覆盖同一个道理，不该再被整体偏移推一次。
    if "insert" in patch:
        _insert_lines(out["lyrics"], patch["insert"])

    # 单句覆盖排在整体偏移之后：用户为个别句子手工补的时间是绝对时刻，
    # 不该再被整体偏移推一次。
    #
    # 也排在**补录之后**：下标打的是补齐之后的那份列表。反过来的话，
    # 私仓 `songs/04` 那 64 个下标会整体错位——而它们本来就是照着
    # 补齐后的 64 行写的。
    if "lines" in patch:
        _apply_indexed(out["lyrics"], patch["lines"], LINE_KEYS, "lyrics.lines")

    for i, line in enumerate(out["lyrics"]):
        if line["t1"] < line["t0"]:
            raise OverrideError(
                f"lyrics.lines[{i}] 的 t1 {line['t1']:.2f} 早于 t0 "
                f"{line['t0']:.2f}——时间倒挂"
            )
