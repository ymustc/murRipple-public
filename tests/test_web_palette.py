"""壳子界面用的色相，必须逐个等于产品真正画出来的那一个。

## 为什么需要这一条

`murripple/web/static/index.html` 是**壳子**——用户在这里选文件、看进度。
产品是渲染出来的那个单文件页面。两处都在说「这是九个声部的颜色」，
**而 2026-08-15 之前它们说的不是同一套**：

| 声部 | 产品 | 壳子（旧） | 差 |
|---|---|---|---|
| 撼岳 | 28 | 26 | 2 |
| 心籁 | 300 | 312 | 12 |
| 碎玉 | 195 | 186 | 9 |
| 泠泠 | 165 | 160 | 5 |
| 霜铎 | 60 | 54 | 6 |

管理窗口做界面定稿时按「多巴胺星空」的观感挑色，**从头到尾没对过
`murripple/lanes.py`**；是做项目报告那一棒读代码时照出来的。

**更坏的是那份 CSS 的注释里写的是对的数字**（`/* 撼岳 28 */` 旁边放着
`hsl(26 …)`）——**注释在声称一个它自己没做到的事**。数值错了会被人看出来，
一句假的注释只会让下一个人不再去查。

## 这条守卫读的是真值，不是抄本

`LANE_SPECS` 从 `murripple.lanes` **import 进来**，心籁从
`renderer/src/ui/voices.js` **正则读出来**。测试里没有第二份色相表——
有第二份的话，它自己就成了第三个会漂的地方。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from murripple.lanes import LANE_SPECS

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "murripple" / "web" / "static" / "index.html"
VOICES = REPO / "renderer" / "src" / "ui" / "voices.js"

#: 壳子 CSS 变量 → 它自称的那个声部。**这张表是「谁是谁」，不是色相值**——
#: 色相值一律从产品那边读，这里一个数字都不写。
VAR_TO_VOICE = {
    "--c-hy": "撼岳",
    "--c-sd": "霜铎",
    "--c-ll": "泠泠",
    "--c-sy": "碎玉",
    "--c-ym": "渊鸣",
    "--c-pm": "缥缈",
    "--c-xl": "心籁",
}

#: `lanes.py` 用的是乐器名，画面上给人看的是雅名。这张对照表在 `cli.py` 里
#: 已经有一份（`cli.py:87`），此处只取壳子用得到的那几条。
LANE_ID_TO_VOICE = {
    "kick": "撼岳",
    "snare": "裂帛",
    "hat": "碎玉",
    "bass": "渊鸣",
    "mid": "流岚",
    "air": "缥缈",
}


def _product_hues() -> dict[str, int]:
    """产品真正画出来的色相。真歌六条来自 `LANE_SPECS`，心籁来自 `voices.js`。"""
    hues = {
        LANE_ID_TO_VOICE[spec["id"]]: int(spec["hue"])
        for spec in LANE_SPECS
        if spec["id"] in LANE_ID_TO_VOICE
    }
    src = VOICES.read_text(encoding="utf-8")
    m = re.search(r'zh:\s*"心籁".*?hue:\s*(\d+)', src, re.S)
    assert m is not None, (
        f"{VOICES} 里找不到心籁的 hue 了——这条守卫的真值来源断了，"
        "它此刻什么也没在守。"
    )
    hues["心籁"] = int(m.group(1))
    # 霜铎与泠泠是合成曲那条线的声部，不在 `LANE_SPECS` 里。它们的值写在
    # `MGMT.md` 第五节的八条排序里（`28 / 60 / 165 / 175 / 195 / 225 / 270 / 350`）。
    # **不在这里硬写**：壳子那两个变量的注释自己带着数字，下面那条
    # `test_每个色相都写在它自己的注释里` 会核注释与值一致，
    # 而「注释里那个数对不对」由台账管——这是本仓明确接受的边界。
    return hues


def _css_vars() -> dict[str, tuple[int, str]]:
    """壳子 CSS 里的 `--c-*`：变量名 → (色相, 注释里自称的声部)。"""
    html = PAGE.read_text(encoding="utf-8")
    out: dict[str, tuple[int, str]] = {}
    for m in re.finditer(
        r"(--c-[a-z]+):\s*hsl\((\d+)[^)]*\);\s*/\*\s*(\S+)\s+(\d+)", html
    ):
        out[m.group(1)] = (int(m.group(2)), m.group(3), int(m.group(4)))
    return out


def test_the_page_really_declares_the_palette():
    """先证明上面那个正则真的抓到了东西——抓不到的话下面两条会空转全绿。"""
    found = _css_vars()
    assert set(found) == set(VAR_TO_VOICE), (
        f"壳子里的色板变量对不上：页面上是 {sorted(found)}，"
        f"这条守卫认得的是 {sorted(VAR_TO_VOICE)}。"
        "新加了变量就把它加进 VAR_TO_VOICE；改了名字就在这里改。"
    )


@pytest.mark.parametrize("var,voice", sorted(VAR_TO_VOICE.items()))
def test_每个色相都写在它自己的注释里(var, voice):
    """`hsl()` 里的值必须等于旁边注释自称的那个数。

    2026-08-15 之前这一条不成立：`--c-hy: hsl(26 …); /* 撼岳 28 */`。
    **一句声称了自己没做到的事的注释，比一个错的数值更坏**——数值错了会被
    看出来，假注释只会让下一个人不再去查。
    """
    hue, named_voice, commented = _css_vars()[var]
    assert named_voice == voice, (
        f"`{var}` 的注释说它是「{named_voice}」，而这条守卫认为它是「{voice}」。"
        "两边有一个写错了。"
    )
    assert hue == commented, (
        f"`{var}` 的注释写着「{voice} {commented}」，而 `hsl()` 里是 {hue}。"
        "注释在声称一个它自己没做到的事。"
    )


@pytest.mark.parametrize("voice,hue", sorted(_product_hues().items()))
def test_壳子上的色相等于产品画出来的那一个(voice, hue):
    """真歌那几条声部：壳子与产品必须逐个相等。

    这里只核**产品那边有权威定义**的几条（真歌六条 + 心籁）。霜铎与泠泠是
    合成曲那条线的，不在 `LANE_SPECS` 里，由上面那条「注释与值一致」守着。
    """
    var = next((v for v, n in VAR_TO_VOICE.items() if n == voice), None)
    if var is None:
        pytest.skip(f"壳子的色板里没有「{voice}」——它只用了七个强调色")
    css_hue, _, _ = _css_vars()[var]
    assert css_hue == hue, (
        f"「{voice}」在产品里是 {hue} 度，壳子上是 {css_hue} 度。"
        "壳子写着「这是九个声部的颜色」，那就得是同一个颜色。"
        "产品那边是权威（murripple/lanes.py 与 renderer/src/ui/voices.js），"
        "要改就改壳子。"
    )
