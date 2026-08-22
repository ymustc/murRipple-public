"""把 timeline、音频与渲染器打成一个零依赖的单文件 index.html。

与 build 拆开：分析约 84 秒、打包约 2 秒。调视觉时每改一次都重跑分析
没法忍。
"""

from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path

from murripple.encode import to_data_uri


class PackError(RuntimeError):
    """打包失败。消息里必须带上可执行的修复建议。"""


# 产物体积上限，单位 MB——十进制（1 MB = 1e6 字节），不是二进制 1024**2。
# 拿不准就取严的那一档，别顺手"标准化"成二进制：
#
# 1. 全项目现存的实测数字都是十进制换算的。四首真歌实测字节数
#    01: 12169222B  02: 6826764B  03: 10890651B  04: 13363849B，
#    MGMT.md / DECISIONS.md / spec 里记的 12.2 / 6.8 / 10.9 / 13.4 MB
#    全部对应 /1e6。换成 /1024**2 算出来是 11.61 / 6.51 / 10.39 / 12.74，
#    这四个数字连同"九条 64kbps 约 13.6 MB"这条硬约束依据会同时变错。
# 2. 十进制是更严的一档：15*1e6=15,000,000 字节，15*1024**2=15,728,640
#    字节，相差 4.86%——而九条分轨的实测余量只有约 9%。上限这种东西
#    宁可提前触发降码率，也不要把超限产物放行出去。
MAX_ARTIFACT_MB = 15


def bundle_renderer(renderer_dir: Path) -> str:
    """用 esbuild 把 renderer/src 打成一个 IIFE，返回 JS 源码。"""
    renderer_dir = Path(renderer_dir)
    entry = renderer_dir / "src" / "main.js"
    if not entry.exists():
        raise PackError(f"找不到渲染器入口 {entry}")

    cmd = [
        "npx", "--yes", "esbuild", str(entry),
        "--bundle", "--format=iife", "--global-name=murRippleApp",
        "--minify",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=renderer_dir)
    except FileNotFoundError as exc:
        raise PackError(
            "无法运行 esbuild。在 renderer/ 下执行 `npm install`，"
            "并确认已安装 Node。"
        ) from exc

    if proc.returncode != 0:
        raise PackError(f"esbuild 退出码 {proc.returncode}：\n{proc.stderr.strip()}")
    return proc.stdout


def _js_safe(payload: str) -> str:
    """转义内联到 <script> 里的 JSON。

    数据里若出现 </script>，浏览器会在那里提前闭合脚本标签，产物直接坏
    掉——而 JSON 本身完全合法，任何 JSON 校验都发现不了。
    """
    return payload.replace("</", "<\\/")


def inject(
    template: str, bundle: str, timeline_json: str, audio_map: dict, title: str
) -> str:
    """把四样东西注入模板。bundle 是 JS 源码，原样插入；其余都要转义。

    曲名有两个落点，转义方式**不同**，不能共用一个占位符：

    - ``__TITLE__`` 在 <title> 标签里，是 HTML 上下文 → html.escape
    - ``__TITLE_JSON__`` 在 <script> 的 JS 字符串里 → json.dumps

    起初两处都用 html.escape，而 HTML 实体在 script 里不会被解码：曲名
    「风起 & 陇西」会在标题页上原样显示成「风起 &amp; 陇西」；以反斜杠
    结尾的曲名更会让整段 script 语法错误、__MR_TITLE__ 未定义，静默退回
    目录名。

    必须**一次性**替换，不能链式 replace：链式的话先替换的结果会被后续
    replace 命中——曲名里写 "__BUNDLE__" 就能把整个 bundle 又插一遍。
    """
    values = {
        "__TITLE_JSON__": _js_safe(json.dumps(title, ensure_ascii=False)),
        "__TITLE__": html.escape(title),
        "__TIMELINE__": _js_safe(timeline_json),
        "__AUDIO__": _js_safe(json.dumps(audio_map, ensure_ascii=False)),
        "__BUNDLE__": bundle,
    }
    # __TITLE_JSON__ 必须排在 __TITLE__ 前面，否则前者的 __TITLE 部分先被吃掉
    pattern = re.compile("|".join(sorted(map(re.escape, values), key=len, reverse=True)))
    return pattern.sub(lambda m: values[m.group(0)], template)


def pack(song_dir: Path, renderer_dir: Path, title: str | None = None) -> Path:
    """产出 songs/<slug>/dist/index.html。

    title 为 None 时退回 timeline 里的 meta.title（那是 build 时取的目录名）。
    转义由 inject 负责，见 tests/test_pack.py::test_title_is_escaped。
    """
    song_dir = Path(song_dir).resolve()
    renderer_dir = Path(renderer_dir).resolve()

    timeline_path = song_dir / "build" / "timeline.json"
    if not timeline_path.exists():
        raise PackError(
            f"找不到 {timeline_path}。先跑 `murripple build songs/{song_dir.name}`。"
        )

    template_path = renderer_dir / "template.html"
    if not template_path.exists():
        raise PackError(f"找不到模板 {template_path}")

    timeline_json = timeline_path.read_text(encoding="utf-8")
    doc = json.loads(timeline_json)

    if "stems" not in doc:
        raise PackError(
            f"{timeline_path} 缺少 stems 字段——这份 timeline 早于分轨清单改动。"
            f"重跑 `murripple build songs/{song_dir.name}`，或执行 Task 9 的迁移脚本。"
        )

    audio_dir = song_dir / "build" / "audio"
    audio_map = {}
    # 按 timeline 声明的分轨遍历，不用 schema.STEMS——合成曲有九条，
    # 写死四条常量会把后面的分轨静默丢在产物之外。
    for stem in doc["stems"]:
        p = audio_dir / f"{stem}.m4a"
        if p.exists():
            audio_map[stem] = to_data_uri(p)

    # 必须是"声明的分轨全部到齐"，不能只查"至少有一条"——半套比一条都
    # 没有更危险（murripple/stems.py:26-30 对 find_flat_stems 的同一条
    # 论证）：declared 九条、编码只成功八条这种情况下游完全无感——
    # main.js 对缺的 uri 直接 continue，createMuteState 却仍照 timeline
    # .stems 的全量建状态，于是缺的那条声部行照常渲染、可点、点了没反应，
    # 没有任何报错。这里把"至少一条"升级成"必须等于声明集合"，原来那句
    # "一条都没有"的专门提示因此不再单独保留：它现在只是这条更一般检查
    # 的一个特例（missing == 声明的全集），单独留着不会比"缺了这些分轨"
    # 提供更多信息，反而多一条分支要维护。
    missing = set(doc["stems"]) - set(audio_map)
    if missing:
        raise PackError(
            f"{audio_dir} 下缺少这些分轨的音频：{sorted(missing)}。"
            f"重跑 `murripple build songs/{song_dir.name}` 补齐后再 pack。"
        )

    out_dir = song_dir / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    # 先写临时文件、量完体积再决定要不要落地成 out_path：如果直接写
    # out_path 再在超限时删掉它，会把上一次成功的产物也一并抹掉——即使
    # 这次超限失败，用户手里那个能用的旧产物不该被牵连。
    tmp_out = out_dir / f".{out.name}.tmp"
    tmp_out.write_text(
        inject(
            template_path.read_text(encoding="utf-8"),
            bundle_renderer(renderer_dir),
            timeline_json,
            audio_map,
            title or doc["meta"]["title"],
        ),
        encoding="utf-8",
    )

    size_mb = tmp_out.stat().st_size / 1e6
    if size_mb > MAX_ARTIFACT_MB:
        tmp_out.unlink()
        raise PackError(
            f"产物 {size_mb:.1f} MB 超过 {MAX_ARTIFACT_MB} MB 上限。"
            f"降低 --bitrate 或减少分轨数后重试。"
        )
    tmp_out.replace(out)
    return out
