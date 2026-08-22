import json
import subprocess
from pathlib import Path

import pytest

from murripple.pack import PackError, inject, pack


TEMPLATE = (
    "<title>__TITLE__</title>"
    "<script>window.__MR_TIMELINE__ = __TIMELINE__;</script>"
    "<script>window.__MR_AUDIO__ = __AUDIO__;</script>"
    "<script>__BUNDLE__</script>"
)


def test_all_placeholders_are_replaced():
    out = inject(
        TEMPLATE, "var x=1;", '{"meta":{}}', {"vocals": "data:audio/mp4;base64,AA"}, "demo"
    )
    for ph in ("__TITLE__", "__TIMELINE__", "__AUDIO__", "__BUNDLE__"):
        assert ph not in out, f"{ph} 未被替换"


def test_script_close_tag_in_data_is_escaped():
    """JSON 里出现 </script> 会提前闭合脚本标签，产物直接坏掉。

    而 JSON 本身完全合法——任何 JSON 校验都发现不了这个问题。
    """
    evil = json.dumps({"meta": {"title": "</script><script>alert(1)</script>"}})
    out = inject(TEMPLATE, "", evil, {}, "demo")

    body = out.split("window.__MR_TIMELINE__ = ", 1)[1].split(";</script>", 1)[0]
    assert "</script>" not in body, "数据里的 </script> 必须被转义"
    assert "<\\/script>" in out


def test_title_is_escaped():
    out = inject(TEMPLATE, "", "{}", {}, "<img src=x onerror=alert(1)>")
    assert "<img" not in out
    assert "&lt;img" in out


def test_audio_map_becomes_valid_json():
    out = inject(TEMPLATE, "", "{}", {"vocals": "data:audio/mp4;base64,AAAA"}, "demo")
    payload = out.split("window.__MR_AUDIO__ = ", 1)[1].split(";</script>", 1)[0]
    assert json.loads(payload)["vocals"].startswith("data:audio/mp4;base64,")


def test_bundle_is_inserted_verbatim():
    """bundle 是 JS 源码，转义它会直接改坏代码。"""
    out = inject(TEMPLATE, "console.log(1<2);", "{}", {}, "demo")
    assert "console.log(1<2);" in out


# test_stems_list_matches_between_python_and_js 曾经守着"schema.py 的 STEMS
# 与 audio.js 的 STEMS 两份写死的常量不漂移"。M5v2 Task 5 把 audio.js 里那份
# 删掉了——渲染层现在按 timeline.stems（真歌四条、合成曲九条）动态遍历，
# 不再有第二份写死的列表可比。这条测试原本要挡的"两边字面量不一致"这类
# 故障，现在挡不住也不需要挡：`export const STEMS = [...]` 这一行在
# audio.js 里已经不存在，断言必然落空，且这不是回归——是这次改动本身
# 要做的事。真正的一致性现在落在别处：pack.py 按 doc["stems"] 内联音频
# （见 test_pack.py 里 Task 4 的用例），渲染层的解码循环按
# app.timeline.stems 遍历（见 renderer/test/timeline.test.mjs 与
# renderer/test/audio.test.mjs 里 Task 5 新增的用例）。


def test_missing_esbuild_gives_actionable_error(tmp_path, monkeypatch):
    from murripple import pack as pack_mod

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.js").write_text("", encoding="utf-8")

    def boom(*a, **k):
        raise FileNotFoundError("npx")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(PackError, match="npm install"):
        pack_mod.bundle_renderer(tmp_path)


def test_missing_entry_gives_clear_error(tmp_path):
    from murripple import pack as pack_mod

    with pytest.raises(PackError, match="入口"):
        pack_mod.bundle_renderer(tmp_path)


def _minimal_song(tmp_path, title_in_meta="demo", stems=None, audio_bytes=None):
    """够 pack 跑起来的最小歌曲目录 + 渲染器目录。

    stems: timeline 顶层声明的分轨名列表，同时决定 build/audio/ 下放哪些
        同名占位 .m4a 文件。默认 ["vocals"]，保持既有调用点的行为不变。
    audio_bytes: 每条占位 .m4a 文件的字节数。默认 None 时用一个极小的
        M4A 文件头；传数字可以撑大产物体积，用来触发超限守卫。
    """
    stems = list(stems) if stems is not None else ["vocals"]
    song = tmp_path / "songs" / "demo"
    (song / "build" / "audio").mkdir(parents=True)
    (song / "build" / "timeline.json").write_text(
        json.dumps({"meta": {"title": title_in_meta, "duration": 10}, "stems": stems}),
        encoding="utf-8",
    )
    payload = b"\0\0\0\x18ftypM4A " if audio_bytes is None else b"\xab" * audio_bytes
    for stem in stems:
        (song / "build" / "audio" / f"{stem}.m4a").write_bytes(payload)

    renderer = tmp_path / "renderer"
    renderer.mkdir()
    (renderer / "template.html").write_text(TEMPLATE, encoding="utf-8")
    return song, renderer


def test_pack_title_flag_reaches_output(tmp_path, monkeypatch):
    """--title 要真的进到产物里，而不是被参数解析吃掉。"""
    monkeypatch.setattr("murripple.pack.bundle_renderer", lambda _: "")
    song, renderer = _minimal_song(tmp_path)

    # 标题是**随便一个中文串**，跟任何一首真歌无关：这里测的是"--title 有没有
    # 走到产物里"，换成别的字一样成立。刻意不用仓里那四首歌的名字——它们是
    # 别人的作品，不该出现在会被公开的路径上。
    out = pack(song, renderer, title="锈色电台")
    assert "锈色电台" in out.read_text(encoding="utf-8")


def test_pack_title_defaults_to_meta_title(tmp_path, monkeypatch):
    """不给 --title 时退回 build 时记下的目录名，保持既有行为。

    这条不是凑数：--title 一旦写成必填、或者默认值写成空串，产物的标题
    就成了空白，而所有转义测试照样是绿的。
    """
    monkeypatch.setattr("murripple.pack.bundle_renderer", lambda _: "")
    song, renderer = _minimal_song(tmp_path, title_in_meta="夜落长安")

    out = pack(song, renderer).read_text(encoding="utf-8")
    assert "夜落长安" in out
    assert "<title></title>" not in out, "标题为空说明默认值把它吃掉了"


def test_real_template_has_every_injection_point():
    """所有 inject 测试用的都是本文件顶部那个假模板；真模板坏掉没人会知道。

    实测：把 `window.__MR_TITLE__` 那行从真模板里删掉，--title 功能整个
    失效、标题页显示目录名，而 104 条 Python 加 136 条 JS 测试全绿。
    """
    tpl = (
        Path(__file__).resolve().parent.parent / "renderer" / "template.html"
    ).read_text(encoding="utf-8")
    for ph in ("__TITLE__", "__TITLE_JSON__", "__TIMELINE__", "__AUDIO__", "__BUNDLE__"):
        assert ph in tpl, f"真模板缺少 {ph}"
    assert "window.__MR_TITLE__ = __TITLE_JSON__;" in tpl, "曲名不再注入，--title 会静默失效"
    assert 'id="mr-ui"' in tpl, "界面无处挂载"
    assert 'id="cv"' in tpl, "画布没了"


def test_title_in_script_is_json_not_html_escaped():
    """曲名有两个落点，转义方式不同，不能共用一个占位符。

    <title> 里是 HTML 上下文，<script> 里是 JS 字符串。起初两处都用
    html.escape，而 HTML 实体在 script 里不会被解码：曲名「风起 & 陇西」
    会在标题页上原样显示成「风起 &amp; 陇西」。
    """
    tpl = '<title>__TITLE__</title><script>window.__MR_TITLE__ = __TITLE_JSON__;</script>'

    out = inject(tpl, "", "{}", {}, '风起 & <陇西>')
    assert "<title>风起 &amp; &lt;陇西&gt;</title>" in out, "HTML 上下文该转义实体"
    assert 'window.__MR_TITLE__ = "风起 & <陇西>";' in out, (
        "JS 字符串里不该有 HTML 实体——它在 script 中不会被解码，会原样显示"
    )

    # 引号与反斜杠：html.escape 完全不管反斜杠，以它结尾的曲名会让整段
    # script 语法错误、__MR_TITLE__ 未定义，静默退回目录名。
    for evil in ['say "hi"', "It's", "trailing\\", "a\nb"]:
        out = inject(tpl, "", "{}", {}, evil)
        body = out.split("window.__MR_TITLE__ = ", 1)[1].split(";</script>", 1)[0]
        assert json.loads(body) == evil, f"{evil!r} 没能原样还原：{body}"


def test_title_cannot_smuggle_other_placeholders():
    """曲名里写 __BUNDLE__ 不该把整个 bundle 塞进 <title>。

    replace 是顺序执行的，先替换的结果会被后续 replace 命中。
    """
    out = inject(TEMPLATE, "BUNDLE_BODY", "{}", {}, "__BUNDLE__")
    assert out.count("BUNDLE_BODY") == 1, "曲名把 bundle 又插了一遍"


def _audio_map_from_html(html_text):
    """把 __AUDIO__ 占位符对应的那段 JSON 抠出来解析。

    不能只断言 `f'"{stem}"' in html` ——timeline 原文也被原样内联进产物
    （见 inject 的 __TIMELINE__ 占位符），Task 3 之后 timeline 顶层就带
    `"stems": [...]`。分轨名字符串在 html 里出现一次，跟音频有没有被
    内联毫无关系；这条测试要验的是 __AUDIO__ 那段 JSON 的键集合，以及
    每个值确实是 data URI（真的塞进了字节）。
    """
    payload = html_text.split("window.__MR_AUDIO__ = ", 1)[1].split(";</script>", 1)[0]
    return json.loads(payload)


def test_pack_inlines_every_declared_stem(tmp_path, monkeypatch):
    """九条分轨要九段音频。按四条常量遍历的话，后五条会被静默丢掉。"""
    monkeypatch.setattr("murripple.pack.bundle_renderer", lambda _: "")

    nine = ["vocals", "bass", "pad", "pluck", "arp", "bell", "kick", "snare", "hat"]
    song, renderer = _minimal_song(tmp_path, stems=nine)
    out = pack(song, renderer, title="t")
    audio_map = _audio_map_from_html(out.read_text(encoding="utf-8"))

    assert set(audio_map.keys()) == set(nine), (
        f"内联的分轨集合与声明的不一致：内联了 {sorted(audio_map)}，声明的是 {sorted(nine)}"
    )
    for stem, uri in audio_map.items():
        assert uri.startswith("data:audio/"), f"{stem} 的值不是 data URI，音频没被真的内联"

    # 对照：分轨数变少（老四轨路径）时也只应内联那四段，不是"总是全量"。
    four = ["vocals", "bass", "pad", "pluck"]
    song4, renderer4 = _minimal_song(tmp_path / "four-stem", stems=four)
    out4 = pack(song4, renderer4, title="t")
    audio_map4 = _audio_map_from_html(out4.read_text(encoding="utf-8"))
    assert set(audio_map4.keys()) == set(four), (
        f"四轨路径内联的集合不对：{sorted(audio_map4)}"
    )


def test_pack_fails_hard_over_the_size_limit(tmp_path, monkeypatch):
    """余量只剩 1.4 MB。超限必须硬失败，不能只打印警告——
    警告会被当成噪音略过，然后一个超限的产物就发出去了。"""
    monkeypatch.setattr("murripple.pack.bundle_renderer", lambda _: "")

    song, renderer = _minimal_song(tmp_path, stems=["vocals"], audio_bytes=16 * 1024 * 1024)
    with pytest.raises(PackError, match="超过 15 MB 上限"):
        pack(song, renderer, title="t")


def test_pack_preserves_previous_artifact_when_new_build_is_oversized(tmp_path, monkeypatch):
    """超限失败不能牵连 dist/ 下已有的旧产物，也不能留下孤儿临时文件。

    实现里为了不让 out_path.unlink() 波及上一次成功的产物，换成了"先写临时
    文件、量完体积再决定要不要落地"。这个偏离换来的好处如果没有测试钉住，
    以后有人把写盘挪到体积检查之后、或者改回直接写 out_path 再 unlink，
    就会悄悄退回"毁掉旧产物"或"漏下临时文件"，而不会有测试变红。
    """
    monkeypatch.setattr("murripple.pack.bundle_renderer", lambda _: "")
    song, renderer = _minimal_song(tmp_path, stems=["vocals"])

    dist = song / "dist"
    dist.mkdir(parents=True)
    sentinel = "上一次成功产出的哨兵内容 v1，超限重打不该动它"
    (dist / "index.html").write_text(sentinel, encoding="utf-8")

    # 把占位音频撑大到会超限，触发这次构建失败。
    (song / "build" / "audio" / "vocals.m4a").write_bytes(b"\xab" * 16 * 1024 * 1024)

    with pytest.raises(PackError, match="超过 15 MB 上限"):
        pack(song, renderer, title="t")

    assert (dist / "index.html").read_text(encoding="utf-8") == sentinel, (
        "超限失败牵连了上一次成功的旧产物——内容被覆盖或清空了"
    )
    leftover = sorted(p.name for p in dist.iterdir())
    assert leftover == ["index.html"], f"dist/ 下留下了不该在的东西：{leftover}"


def test_pack_fails_when_a_declared_stem_is_missing_its_audio(tmp_path, monkeypatch):
    """声明了 N 条分轨，只有 N-1 条编码成功——半套比一条都没有更危险。

    旧实现只查"至少有一条"，这种"缺一条"的半套会静默通过：main.js 对
    缺的 uri 直接 continue，createMuteState 却仍按 timeline.stems 的全量
    建状态，缺的那条声部行照常渲染、可点、点了没反应，没有任何报错——
    与 murripple/stems.py:26-30 对 find_flat_stems 的"半套比没有更危险"
    是同一个论证，之前只在数据上钉住了（test_regression_real_songs.py），
    没有在 pack 这条代码路径上强制。

    match= 卡在"缺少这些分轨的音频"——这是本文件里唯一一条含这句话的
    PackError，其余几条（15 MB 上限、找不到 timeline、timeline 缺 stems
    字段）都带着各自的"重跑 build"修复建议后缀，如果 match= 卡在"重跑"
    或 "build" 这类词上，会被那几条同类 PackError 一起命中，分辨不出到
    底是哪一种失败（Task 8 已经在 LaneSpecsError 的 fix 后缀上撞过一次）。
    """
    monkeypatch.setattr("murripple.pack.bundle_renderer", lambda _: "")
    nine = ["vocals", "bass", "pad", "pluck", "arp", "bell", "kick", "snare", "hat"]
    song, renderer = _minimal_song(tmp_path, stems=nine)
    (song / "build" / "audio" / "bass.m4a").unlink()

    with pytest.raises(PackError, match="缺少这些分轨的音频") as exc_info:
        pack(song, renderer, title="t")
    assert "bass" in str(exc_info.value), f"消息没点名缺失的分轨：{exc_info.value}"


def test_pack_gives_actionable_error_for_timeline_without_stems(tmp_path, monkeypatch):
    """timeline 早于 Task 3、没有 stems 字段时不能裸 KeyError。

    这不是假设场景：迁移（Task 9）之前，四首真歌本地的 build/timeline.json
    就是没有 stems 键的旧格式，谁在那之前跑一次 pack 都会撞上一个没头没尾
    的 KeyError，看不出跟"timeline 太老"有任何关系。PackError 的类契约
    （pack.py 里 class 的 docstring）要求消息里带可执行的修复建议。
    """
    monkeypatch.setattr("murripple.pack.bundle_renderer", lambda _: "")
    song, renderer = _minimal_song(tmp_path)

    timeline_path = song / "build" / "timeline.json"
    doc = json.loads(timeline_path.read_text(encoding="utf-8"))
    del doc["stems"]
    timeline_path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(PackError, match="早于分轨清单改动"):
        pack(song, renderer, title="t")
