"""`overrides.json` 的 `lyrics.insert`：补回对齐时整句丢掉的词。

## 这个能力为什么必须存在

私仓 `songs/04` 里有三行是 WhisperX **整句对不上**、当时手工补进
`build/timeline.json` 的（是哪三行见 `tests/fixtures/04-align-unmatched.json`
那份真跑抄件；这里不照抄，**那几句是别人的作品**——那份抄件也因此不进公开树，
见 `tools/make_public_tree.py` 的 `orphan-fixture` 规则）。`overrides` 只能改已有句子、
没法插入，于是**对这首歌重跑 `build` 会当场硬失败**（真跑量到的原文）：

    以下 3 行未对上，请在 overrides.json 中补时间：
        - <第一句>
        - <第二句>
        - <第三句>
    overrides.json 有问题：lyrics.lines 里的下标 61 越界——一共只有 61 项

## 位置由 t0 定，不由下标定

插入用下标是 M4 栽过的那一跤的加强版：`lines` 的下标打进一个**数量会变**的
列表已经很险，而插入**本身就在改变数量**。所以插入的行自带绝对时刻，位置由
`t0` 归位——与「段落名走真值不走下标」（`DECISIONS.md` 定案 4）同源。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from murripple import overrides


def _doc(*lines: tuple[float, float, str]) -> dict:
    return {
        "meta": {"title": "某首歌"},
        "sections": [],
        "lanes": [],
        "lyrics": [{"t0": t0, "t1": t1, "text": text} for t0, t1, text in lines],
    }


def _texts(doc: dict) -> list[str]:
    return [line["text"] for line in doc["lyrics"]]


def _times(doc: dict) -> list[tuple[float, float]]:
    return [(line["t0"], line["t1"]) for line in doc["lyrics"]]


# --------------------------------------------------------------------------
# 插进去，落在对的位置
# --------------------------------------------------------------------------


def test_插进去的行按_t0_归位而不是追加到末尾():
    doc = _doc((10.0, 12.0, "第一句"), (20.0, 22.0, "第三句"))
    out = overrides.apply(doc, {"lyrics": {"insert": [
        {"text": "第二句", "t0": 15.0, "t1": 17.0},
    ]}})

    assert _texts(out) == ["第一句", "第二句", "第三句"]
    assert _times(out) == [(10.0, 12.0), (15.0, 17.0), (20.0, 22.0)]


def test_插在最前面和最后面都行():
    doc = _doc((10.0, 12.0, "中间"))
    out = overrides.apply(doc, {"lyrics": {"insert": [
        {"text": "末尾", "t0": 30.0, "t1": 32.0},
        {"text": "开头", "t0": 1.0, "t1": 3.0},
    ]}})

    assert _texts(out) == ["开头", "中间", "末尾"]


def test_给的顺序不影响结果():
    """`insert` 是一个集合，不是一份剧本——乱序给必须归到同一个位置。"""
    doc = _doc((10.0, 12.0, "甲"), (40.0, 42.0, "丁"))
    a = overrides.apply(doc, {"lyrics": {"insert": [
        {"text": "乙", "t0": 20.0, "t1": 22.0},
        {"text": "丙", "t0": 30.0, "t1": 32.0},
    ]}})
    b = overrides.apply(doc, {"lyrics": {"insert": [
        {"text": "丙", "t0": 30.0, "t1": 32.0},
        {"text": "乙", "t0": 20.0, "t1": 22.0},
    ]}})

    assert _texts(a) == _texts(b) == ["甲", "乙", "丙", "丁"]


def test_t0_与已有行相同时排在它后面():
    """并列时也得有个**定死**的答案，不能看字典序或者哈希顺序。"""
    doc = _doc((10.0, 12.0, "原本就在的"))
    out = overrides.apply(doc, {"lyrics": {"insert": [
        {"text": "同一时刻插的", "t0": 10.0, "t1": 11.0},
    ]}})

    assert _texts(out) == ["原本就在的", "同一时刻插的"]


def test_文本一样也能各插各的():
    """`锈色电台` 这种在一首歌里出现好几次的词——插入靠的是自带的时刻，
    不靠去已有列表里找同名的那一行，所以重名根本不构成问题。"""
    doc = _doc((10.0, 12.0, "锈色电台"))
    out = overrides.apply(doc, {"lyrics": {"insert": [
        {"text": "锈色电台", "t0": 50.0, "t1": 52.0},
    ]}})

    assert _texts(out) == ["锈色电台", "锈色电台"]
    assert _times(out) == [(10.0, 12.0), (50.0, 52.0)]


# --------------------------------------------------------------------------
# 与另外两样的先后
# --------------------------------------------------------------------------


def test_插进去的行不吃整体偏移():
    """跟既有那条注释同一个理由：手工补的时刻是**绝对**的，
    不该再被 `offset` 推一次。02 那首歌的 `offset: -0.6` 就是活的先例。"""
    doc = _doc((10.0, 12.0, "自动对上的"))
    out = overrides.apply(doc, {"lyrics": {
        "offset": -0.6,
        "insert": [{"text": "手工补的", "t0": 5.0, "t1": 7.0}],
    }})

    assert _times(out) == [(5.0, 7.0), (9.4, 11.4)]


def test_下标补丁打在合并之后的列表上():
    """04 那 64 个下标是照着**补齐之后**的 64 行写的。
    `insert` 排在 `lines` 后面的话，那 64 个下标会整体错位。"""
    doc = _doc((10.0, 12.0, "甲"), (30.0, 32.0, "丙"))
    out = overrides.apply(doc, {"lyrics": {
        "insert": [{"text": "乙", "t0": 20.0, "t1": 22.0}],
        # 下标 1 指的是**插入之后**的「乙」。
        "lines": {"1": {"t1": 25.0}},
    }})

    assert _texts(out) == ["甲", "乙", "丙"]
    assert _times(out) == [(10.0, 12.0), (20.0, 25.0), (30.0, 32.0)]


def test_插入之后下标才够得着最后那一行():
    """这条是 04 现场的最小复现：61 项的列表配一个下标 61 会越界，
    补进来一行之后正好够得着。"""
    doc = _doc((10.0, 12.0, "甲"))
    patch = {"lyrics": {"lines": {"1": {"t1": 99.0}}}}

    with pytest.raises(overrides.OverrideError) as exc:
        overrides.apply(doc, patch)
    assert "越界" in str(exc.value)

    patch["lyrics"]["insert"] = [{"text": "乙", "t0": 20.0, "t1": 22.0}]
    out = overrides.apply(doc, patch)
    assert _times(out)[1] == (20.0, 99.0)


# --------------------------------------------------------------------------
# 说不清楚就报错，不猜
# --------------------------------------------------------------------------


def test_没有_insert_时行为一个字节没变():
    doc = _doc((10.0, 12.0, "甲"))
    assert overrides.apply(doc, {"lyrics": {"offset": 1.0}}) == _doc((11.0, 13.0, "甲"))


def test_空的_insert_不算错也不改变什么():
    doc = _doc((10.0, 12.0, "甲"))
    assert overrides.apply(doc, {"lyrics": {"insert": []}}) == doc


@pytest.mark.parametrize(
    "bad,missing",
    [
        ({"t0": 1.0, "t1": 2.0}, "text"),
        ({"text": "甲", "t1": 2.0}, "t0"),
        ({"text": "甲", "t0": 1.0}, "t1"),
    ],
)
def test_三个字段缺一个就报错并点名(bad, missing):
    """插一行没有"部分"可言——缺 `t1` 的话渲染层拿什么决定它什么时候暗下去？

    **点名缺的是哪一个**：三种输入互相排斥地断，只说"字段不全"会让三条同时红。
    """
    with pytest.raises(overrides.OverrideError) as exc:
        overrides.apply(_doc(), {"lyrics": {"insert": [bad]}})

    message = str(exc.value)
    assert missing in message
    for other in ("text", "t0", "t1"):
        if other != missing:
            assert other not in message.split("：")[-1], (
                f"缺的是 {missing}，消息里却也点了 {other}：{message}"
            )


def test_多出来的字段当场报错():
    with pytest.raises(overrides.OverrideError) as exc:
        overrides.apply(_doc(), {"lyrics": {"insert": [
            {"text": "甲", "t0": 1.0, "t1": 2.0, "hue": 225.0},
        ]}})
    assert "hue" in str(exc.value)


def test_insert_不是列表就报错():
    """★ 断的是"它说了这是**数组**的问题"，不是"消息里有 insert 三个字母"。

    第一版就断了 `"insert" in message`——**变异检验 Y11 全绿**：`where` 前缀
    (`lyrics.insert[0]`) 让**每一条**同类消息都含这三个字母，而 dict 进来时
    `enumerate` 迭代的是键（字符串），下面那条"不是对象"的检查会先抓住它。
    「断言命中的字符串在被测产物里有几个来源」，`MGMT.md` 第七节。
    """
    with pytest.raises(overrides.OverrideError) as exc:
        overrides.apply(_doc(), {"lyrics": {"insert": {"0": {"text": "甲"}}}})
    assert "数组" in str(exc.value)


def test_插进来的一条里_t1_早于_t0_要报错():
    """★ 断言必须点名是 `insert` 那一条倒挂。

    只断"倒挂"两个字的话**变异检验 Y8 全绿**：`_apply_lyrics` 末尾那道总检查
    会兜住同一个输入，但它报的是 `lyrics.lines[i]`——**指着一个用户根本没写
    的补丁**。这一条自己那道检查存在的全部理由就是把手指头指对地方。
    """
    with pytest.raises(overrides.OverrideError) as exc:
        overrides.apply(_doc(), {"lyrics": {"insert": [
            {"text": "倒挂的", "t0": 9.0, "t1": 3.0},
        ]}})
    message = str(exc.value)
    assert "倒挂" in message
    assert "lyrics.insert" in message, f"指错了地方：{message}"
    assert "lyrics.lines" not in message


def test_两条同一时刻的补录按给的顺序排():
    """落点是绝对的，所以顺序只在**并列**时才看得出来。

    这一条钉的就是那唯一一处顺序语义——`_insert_lines` 里那句 `sorted` 删掉
    之后（它是死代码，见那里的注释），这条仍然是绿的、而且仍然在守着东西。
    """
    doc = _doc((10.0, 12.0, "已有的"))
    out = overrides.apply(doc, {"lyrics": {"insert": [
        {"text": "先给的", "t0": 20.0, "t1": 21.0},
        {"text": "后给的", "t0": 20.0, "t1": 21.0},
    ]}})

    assert _texts(out) == ["已有的", "先给的", "后给的"]


@pytest.mark.parametrize("bad_time", ["9.0", None, [9.0]])
def test_时刻不是数字就报错(bad_time):
    with pytest.raises(overrides.OverrideError) as exc:
        overrides.apply(_doc(), {"lyrics": {"insert": [
            {"text": "甲", "t0": bad_time, "t1": 12.0},
        ]}})
    assert "t0" in str(exc.value)


def test_文本是空的就报错():
    """空文本插进去，画面上是一行看不见的歌词占着一段时间——
    比不插更难查。"""
    with pytest.raises(overrides.OverrideError) as exc:
        overrides.apply(_doc(), {"lyrics": {"insert": [
            {"text": "   ", "t0": 1.0, "t1": 2.0},
        ]}})
    assert "text" in str(exc.value)


def test_一条不是对象也报错():
    """同 `test_insert_不是列表就报错` 的理由：断"它说了这是**对象**的问题"。

    只断 `"insert"` 的话**变异检验 Y12 全绿**——把这条检查删掉，
    `_check_keys` 会拿字符串去做集合减法，报出来的是一串汉字当"无法识别的
    字段"，而那条消息里照样有 `lyrics.insert[0]` 这个前缀。
    """
    with pytest.raises(overrides.OverrideError) as exc:
        overrides.apply(_doc(), {"lyrics": {"insert": ["锈色电台"]}})
    assert "对象" in str(exc.value)

# 「仓里那几份 overrides.json 自己也要立得住」那三条（读真实的
# `songs/*/overrides.json` 与 `lyrics.txt`）已于 2026-08-15 整段搬到
# `tests/test_overrides_insert_real_songs.py`——公开仓不带素材，不拆的话
# 整份文件都进不去。断言一条没改，只是换了个文件放。
