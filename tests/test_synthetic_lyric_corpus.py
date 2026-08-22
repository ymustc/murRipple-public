"""自造语料的**形状覆盖**守卫。

`renderer/test/fixtures/synthetic-lyric-rows.json` 是手写的四首不存在的歌，
存在的理由是替换掉散在测试与源码里的私有歌词：于淼那四首歌是他的私产，
不进公开仓，而歌词原文此刻会跟着测试一起漏出去。

**换语料这件事本身有一个固有的失败方式：换出来的语料比原语料好听、好看、
更工整，于是分辨力更弱，而没有人会发现。** 真语料能抓 bug 是因为它有
`fake one` 那种别扭的东西——一个中文句子里嵌着一个带空格的英文短语，
四首歌里只有一句撞上，而那一句正是「空格被删」那个 bug 唯一的样本。

所以这一条守的不是"语料在不在"，是**"语料里那几类承重形状还各有几条"**。
它是**数出来的**，不是人眼扫出来的：形状由文本自身判定（有没有全角空格、
有没有拉丁字母、繁不繁体、断完还超不超预算），不看谁给它贴了什么标签。

## 这条守卫自己的失败方式，也写了守卫

空集上「某某不存在」恒真——一份空语料会让所有"至少 N 条"退化成"至少 0 条"
而全绿（本仓刚栽过）。所以下面三层：

1. `test_..._covers_every_load_bearing_shape` —— 真语料真的过。
2. `test_the_guard_goes_red_on_an_empty_corpus` —— **空语料必须红**。
3. `test_every_threshold_is_load_bearing` —— 把任意一类形状的句子抽掉，
   这条守卫必须红。抓的是"某个门槛被别的形状顺手满足了、其实从没起过作用"。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from murripple.align import _T2S

REPO = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO / "renderer" / "test" / "fixtures" / "synthetic-lyric-rows.json"
DOC = json.loads(FIXTURE_PATH.read_text("utf-8"))
CORPUS: dict[str, list[dict]] = DOC["songs"]

#: 一行放得下多少个汉字宽——与 `renderer/src/layers/lyrics.js` 的
#: `MAX_CHARS_PER_LINE` 同一个数。两处各写一遍是刻意的：这份守卫是 Python，
#: 读不到那个模块的导出；而它一旦跟渲染层漂了，下面「断完仍超预算」那一类
#: 会数出 0 条来，当场红——不会静默失效。
MAX_CHARS_PER_LINE = 9

#: 与 `lyrics.js` 的 `WORD_SCRIPT` 同一判据：用空格分词的文字。
WORD_SCRIPT = re.compile(r"[A-Za-zÀ-ʯͰ-ϿЀ-ӿ]")
#: 与 `lyrics.js` 的 `WIDE` 同一判据：占一个汉字宽的字符。
WIDE = re.compile(r"[⺀-〾ぁ-㏿㐀-䶿一-鿿"
                  r"豈-﫿︰-﹏＀-￦]")
SEP = re.compile(r"[\s　]")


def display_width(s: str) -> float:
    return sum(1 if WIDE.match(ch) else 0.5 for ch in s)


def _is_caesura(text: str) -> bool:
    """句读句：整句没有一个拉丁字母，却带着空白。"""
    return not WORD_SCRIPT.search(text) and bool(SEP.search(text))


def _caesura_tail(text: str) -> str:
    m = SEP.search(text)
    return SEP.sub("", text[m.start():]) if m else ""


#: 每一类形状：名字 → (判定函数, 至少要有几条, 为什么这一类是承重的)。
#:
#: **这张表是手编的，而手编清单的固有失败方式就是漏。** 下面每一条都注明
#: 是被哪一处测试逼出来的——认领不到出处的类别就不该在这张表里，反过来，
#: 哪天有测试用到一类这里没有的形状，那是这张表该长一条，不是把测试改软。
SHAPES: dict[str, tuple] = {
    "全角空格句读": (
        lambda t: _is_caesura(t) and "　" in t,
        18,
        "renderer/test/lyricsSyntheticCorpus.test.mjs：断行规则存在的全部理由",
    ),
    "半角空格句读": (
        lambda t: _is_caesura(t) and re.search(r"[ \t]", t) is not None,
        2,
        "renderer/test/lyrics.test.mjs「半角空格同样处理」",
    ),
    "多个分隔符": (
        lambda t: _is_caesura(t) and len([c for c in SEP.split(t) if c]) >= 3,
        2,
        "renderer/test/lyrics.test.mjs「只按第一个断，避免碎成三行以上」",
    ),
    "句读断完仍超预算": (
        lambda t: _is_caesura(t) and display_width(_caesura_tail(t)) > MAX_CHARS_PER_LINE,
        2,
        "renderer/test/lyricsFit.test.mjs：那道装箱被变异检验逼出来时，"
        "四首真歌一条都走不到它——删掉整道装箱 26 条测试全绿",
    ),
    "中英混排且拉丁短语内部有空格": (
        lambda t: WORD_SCRIPT.search(t) is not None
        and WIDE.search(t) is not None
        and re.search(r"[A-Za-z]+[ \t]+[A-Za-z]+", t) is not None,
        4,
        "★「空格被删」那个 bug 在四首真歌里唯一撞上的形状（`fake one`）。"
        "这一类没了，拿旧实现跑新语料就不再红",
    ),
    "无分隔符短句": (
        lambda t: not SEP.search(t) and display_width(t) <= MAX_CHARS_PER_LINE,
        4,
        "renderer/test/lyrics.test.mjs「无分隔符且够短时不断行」",
    ),
    "无分隔符长句": (
        lambda t: not SEP.search(t) and display_width(t) > MAX_CHARS_PER_LINE,
        6,
        "renderer/test/lyrics.test.mjs「无分隔符但过长时从中点断」；"
        "真语料里 03/04 走的就是这一路",
    ),
    "繁体": (
        lambda t: _T2S(t) != t,
        6,
        "tests/test_align.py 的繁→简归一化、"
        "tests/test_transcribe.py::test_the_draft_comes_back_simplified_on_synthetic_input。"
        "数出 0 条时也可能是 opencc（align extra）没装——那同样要红，"
        "「装不上所以没验」跟「验过了没问题」不许长得一样",
    ),
    "行尾中文标点": (
        lambda t: t[-1:] in "。！？，、—",
        3,
        "tests/test_ingest_subtitle.py：剥标点比对，但输出要留着标点",
    ),
    "句中中文标点": (
        lambda t: any(p in t[:-1] for p in "，、。—"),
        3,
        "tests/test_ingest_subtitle.py 的标点抖动；"
        "tests/test_transcribe.py 的人工校对稿",
    ),
    "十字以上的纯中文长句": (
        lambda t: not SEP.search(t) and not WORD_SCRIPT.search(t) and len(t) >= 10,
        3,
        "tests/test_ingest_subtitle.py「同一行多认／少认一个字」——"
        "句子短了，掉一个字就把相似度拉到阈值以下，那条测试会变成测别的东西",
    ),
}


def shape_counts(lines: list[str]) -> dict[str, int]:
    return {name: sum(1 for t in lines if pred(t)) for name, (pred, _, _) in SHAPES.items()}


def check_shape_coverage(corpus: dict[str, list[dict]]) -> None:
    """语料必须覆盖每一类承重形状。**空语料在这里必须炸，不是悄悄通过。**"""
    lines = [entry["text"] for song in corpus.values() for entry in song]
    assert lines, (
        f"{FIXTURE_PATH} 里一句歌词都没有。"
        "空集上「至少 N 条」全部退化成「至少 0 条」——那不是覆盖，那是没检查。"
    )
    counts = shape_counts(lines)
    short = [
        f"  {name}：只有 {counts[name]} 条，要 {need} 条\n    ← {why}"
        for name, (_, need, why) in SHAPES.items()
        if counts[name] < need
    ]
    assert not short, (
        f"自造语料（{len(lines)} 句）漏了这几类承重形状：\n" + "\n".join(short) + "\n"
        "不要把门槛调低——门槛低下去，语料的分辨力就跟着低下去，而没有人会发现。"
    )


def test_the_synthetic_corpus_covers_every_load_bearing_shape():
    check_shape_coverage(CORPUS)


def test_the_guard_goes_red_on_an_empty_corpus():
    """★ 这条守卫自己的守卫。

    「某某形状至少有 N 条」在空集上会退化成恒真——如果 N 是 0 的话；而这里
    N 不是 0，所以空集会在计数那一步就不够。真正危险的是**语料结构变了导致
    一句都读不出来**（比如 `songs` 这一层被改名），那时每一类都是 0、每一条
    都不够，守卫会红——这条断言把这个行为钉住。
    """
    with pytest.raises(AssertionError, match="一句歌词都没有"):
        check_shape_coverage({})
    with pytest.raises(AssertionError, match="一句歌词都没有"):
        check_shape_coverage({"甲": [], "乙": []})


@pytest.mark.parametrize("dropped", sorted(SHAPES))
def test_every_threshold_is_load_bearing(dropped):
    """把某一类形状的句子全抽掉，这条守卫必须红。

    抓的是**顺手满足**：某个门槛其实一直是被别的类别的句子撑着的，它自己
    从没起过作用——那种门槛在语料真的丢了那一类时不会响。
    """
    pred = SHAPES[dropped][0]
    thinned = {
        slug: [e for e in song if not pred(e["text"])] for slug, song in CORPUS.items()
    }
    with pytest.raises(AssertionError, match="漏了这几类承重形状|一句歌词都没有"):
        check_shape_coverage(thinned)


def test_the_fixture_carries_its_own_provenance():
    """一份没有出处的语料，跟一份从哪儿抄来的语料在仓里长得一模一样。"""
    for key in ("note", "provenance", "songs"):
        assert key in DOC, f"{FIXTURE_PATH} 缺 {key}"
    assert "自造" in DOC["note"]
    assert "手写" in DOC["provenance"] and "抄件" in DOC["provenance"]


def test_every_line_is_nonempty_and_single_line():
    """一行就是一行——语料里混进一个带换行的字符串，下游按行配对会整体错位。"""
    for slug, song in CORPUS.items():
        assert song, f"{slug} 一句都没有"
        for i, entry in enumerate(song):
            text = entry["text"]
            assert text.strip(), f"{slug} 第 {i} 句是空的"
            assert "\n" not in text, f"{slug} 第 {i} 句里有换行"
            assert entry["rows"], f"{slug} 第 {i} 句没有金样本 rows"
