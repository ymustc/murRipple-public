"""手工精修层。"""

import json

import pytest

from murripple.overrides import OverrideError, apply, load


def base_doc():
    return {
        "meta": {"title": "demo", "duration": 10.0, "bpm": 120.0},
        "sections": [
            {"t": 0.0, "name": "", "energy": 0.2},
            {"t": 5.0, "name": "", "energy": 0.8},
        ],
        "lanes": [
            {"id": "kick", "label": "kick", "hue": 28, "gain": 1.0,
             "envelope": "AAAA", "notes": [{"t": 1.0, "v": 0.5, "pitch": None}]},
            {"id": "bass", "label": "bass", "hue": 225, "gain": 1.0,
             "envelope": "BBBB", "notes": []},
        ],
        "lyrics": [
            {"t0": 1.0, "t1": 2.0, "text": "第一句", "words": None},
            {"t0": 3.0, "t1": 4.0, "text": "第二句", "words": None},
        ],
    }


def test_missing_file_is_not_an_error(tmp_path):
    """绝大多数歌不需要精修，缺文件必须照常跑通。"""
    assert load(tmp_path) == {}


def test_empty_overrides_returns_doc_unchanged():
    doc = base_doc()
    assert apply(doc, {}) == doc


def test_deep_merges_lane_not_replaces():
    """只写 gain 的那条轨道，其余字段必须原样保留。

    浅合并会把整条 lane 换掉、envelope 与 notes 全丢，而产出仍是合法 JSON、
    schema 也过——只有画面会莫名其妙地空掉，是最难查的那种。
    """
    out = apply(base_doc(), {"lanes": {"kick": {"gain": 1.8}}})
    kick = out["lanes"][0]
    assert kick["gain"] == 1.8
    assert kick["envelope"] == "AAAA", "包络被替换掉了——这是浅合并"
    assert len(kick["notes"]) == 1, "音符被替换掉了"
    assert kick["hue"] == 28, "没写的字段不该变"
    assert out["lanes"][1]["gain"] == 1.0, "没点名的轨道不该受影响"


def test_does_not_mutate_the_input():
    doc = base_doc()
    apply(doc, {"lanes": {"kick": {"gain": 9.0}}})
    assert doc["lanes"][0]["gain"] == 1.0, "原文档被就地改了"


def test_section_names_land():
    """段落大字要靠它——sections[].name 默认恒为空串。"""
    out = apply(base_doc(), {"sections": {"1": {"name": "高潮"}}})
    assert out["sections"][1]["name"] == "高潮"
    assert out["sections"][0]["name"] == "", "没点名的段落不该变"
    assert out["sections"][1]["energy"] == 0.8, "energy 不该被抹掉"


def test_lyric_offset_shifts_every_line():
    """整体偏移作用到每一句，且 t0/t1 同步移动。"""
    out = apply(base_doc(), {"lyrics": {"offset": -0.4}})
    assert out["lyrics"][0]["t0"] == pytest.approx(0.6)
    assert out["lyrics"][0]["t1"] == pytest.approx(1.6)
    assert out["lyrics"][1]["t0"] == pytest.approx(2.6)


def test_single_line_override_is_absolute_not_shifted_again():
    """单句覆盖是绝对时刻，不该再被整体偏移推一次。

    否则用户为某句手工补的时间会莫名其妙地偏掉——而他正是因为自动对齐
    不准才来手工补的。
    """
    out = apply(
        base_doc(),
        {"lyrics": {"offset": -0.4, "lines": {"1": {"t0": 3.5, "t1": 4.5}}}},
    )
    assert out["lyrics"][0]["t0"] == pytest.approx(0.6), "没覆盖的句子照常偏移"
    assert out["lyrics"][1]["t0"] == pytest.approx(3.5), "覆盖的句子取绝对值"
    assert out["lyrics"][1]["t1"] == pytest.approx(4.5)


def test_inverted_lyric_time_is_rejected():
    """t1 早于 t0 会让那句歌词永不显示，且没有任何报错——必须当场拦下。"""
    with pytest.raises(OverrideError, match="倒挂"):
        apply(base_doc(), {"lyrics": {"lines": {"0": {"t1": 0.5}}}})


@pytest.mark.parametrize(
    "over, needle",
    [
        ({"lanez": {}}, "lanez"),
        ({"lanes": {"kick": {"gian": 2}}}, "gian"),
        ({"lanes": {"kik": {"gain": 2}}}, "kik"),
        ({"sections": {"9": {"name": "x"}}}, "越界"),
        ({"lyrics": {"offset": "早一点"}}, "offset"),
    ],
)
def test_typos_are_rejected_with_a_useful_message(over, needle):
    """静默忽略是最坏的：用户改了半天没反应，会以为是渲染层的问题。"""
    with pytest.raises(OverrideError) as e:
        apply(base_doc(), over)
    assert needle in str(e.value), f"报错没指出问题在 {needle}：{e.value}"


def test_bad_json_says_which_file(tmp_path):
    (tmp_path / "overrides.json").write_text("{ 不是 JSON", encoding="utf-8")
    with pytest.raises(OverrideError, match="合法 JSON"):
        load(tmp_path)


def test_lane_patch_keyed_by_id_not_index():
    """轨道按 id 而不是下标——下标会随管线改动而变，写死了就会错位。"""
    out = apply(base_doc(), {"lanes": {"bass": {"gain": 2.5}}})
    assert out["lanes"][1]["gain"] == 2.5
    assert out["lanes"][0]["gain"] == 1.0
