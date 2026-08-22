"""murripple 命令行入口。

    murripple build songs/demo

读取 songs/<slug>/source.*（mp3/wav/m4a/flac）与 lyrics.txt，产出
songs/<slug>/build/timeline.json 与 build/audio/*.m4a。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import librosa
import numpy as np

from murripple import align as align_module
from murripple.align import AlignmentUnavailable, align_lyrics
from murripple.encode import DEFAULT_BITRATE, encode_stem
from murripple import overrides
from murripple.fetch import FetchError, fetch_url
from murripple.ingest.audio import prepare_audio
from murripple.ingest.scan import IngestError, scan
from murripple.lyrics_gate import COMPOSE_FILENAME, blocked_reason
from murripple.ingest.subtitle import (
    TIMING_FILENAME,
    extract_subtitles,
    load_timing,
    write_lyrics,
    write_timing,
)
from murripple.ingest.transcribe import (
    DRAFT_FILENAME,
    TranscriptionUnavailable,
    transcribe_audio,
    write_draft,
)
from murripple.pack import PackError, pack
from murripple.separate import SeparationError, separate
from murripple.stems import find_flat_stems
from murripple.timeline import build_timeline

# `murripple.compose` 是**可以整个不在**的：公开仓不带合成器（于淼 2026-08-15
# 定），`tools/make_public_tree.py` 会把 `murripple/compose/` 整个摘掉。摘掉之后
# 这个模块——也就是整条 CLI——必须照样 import 得动、`build`／`run`／`pack`／
# `ingest`／`serve` 必须照样能跑。
#
# 与 `murripple.align` 那一路同构：那边是可选 extra 没装（`AlignmentUnavailable`），
# 这边是子包整个不在。两处都**只在自己那条命令上失效**，不牵连别的。
#
# 写成顶层 try 而不是函数内惰性 import，有一个具体理由：`compose` 子命令的
# **参数表**要用 `compose_theory.SCALES`／`KEYS` 来生成帮助文本，那是在
# `main()` 搭 argparse 的时候，不是在执行的时候。可用与否必须在那之前就知道。
try:
    from murripple.compose import arrange as compose_arrange
    from murripple.compose import score as compose_score
    from murripple.compose import synth as compose_synth
    from murripple.compose import theory as compose_theory

    COMPOSE_AVAILABLE = True
except ImportError:
    compose_arrange = compose_score = compose_synth = compose_theory = None
    COMPOSE_AVAILABLE = False

AUDIO_SUFFIXES = (".mp3", ".wav", ".m4a", ".flac")
MIN_DURATION = 5.0
LONG_DURATION_WARNING = 600.0

# `COMPOSE_FILENAME` 从 `murripple.lyrics_gate` 进来（见上面的 import）：
# 歌词那道门要认它当"用户已经说过这是器乐曲"，两处各写一遍就会漂。
SECTIONS_FILENAME = "sections.json"
LANES_FILENAME = "lanes.json"
DEFAULT_DURATION = 150.0
DEFAULT_SCALE = "宫"
# 缺省 BPM 的取值区间。慢一点的中速最贴仙侠玄幻的气质，也给主奏留出气口。
BPM_RANGE = (72, 97)

# 面板色相。心籁（vocals，判定环）固定 300，其余八条各占一个角度。
#
# pad 取 175、pluck 取 270，与真歌那六条里的 mid、air **故意相同**：
# 它们本来就是同一个位置的两种来源（渲染层 `ui/voices.js` 的 LABELS 表也
# 让 mid/pad 共用「流岚」、air/pluck 共用「缥缈」），而真歌与合成曲的
# lane 永远不会出现在同一份 timeline 里，同色撞不上。
#
# **相隔最近的一对是 arp(165) 与 pad(175)，只差 10 度**——task-8-brief 里
# "相邻两条至少差 30 度"那句注释与它自己给的这张表对不上（实测最小间隔
# 10 度，其次 pad 175 与 hat 195 差 20 度；真歌那六条里 mid 175 与 hat 195
# 也是 20 度，这条规矩在本仓从来没成立过）。数值按 brief 保留（它与
# mid/air 的对应关系是有意的），把那句不实的注释改掉，并已在 task-8 报告
# 里报给管理窗口定夺——要不要把 arp 挪开是视觉判断，得于淼的眼睛说了算。
LANE_HUES: dict[str, float] = {
    "bass": 225.0, "pad": 175.0, "pluck": 270.0, "arp": 165.0,
    "bell": 60.0, "kick": 28.0, "snare": 350.0, "hat": 195.0,
}
# 轨道名。**这份表只是兜底**：渲染层 `ui/voices.js` 的 LABELS 表才是画面上
# 那个名字的真相源（侧栏与环外小字都写 `LABELS[l.id]?.zh ?? l.label`，
# 已知 id 一律走它那份）。两份表的字面值不必相同，真歌那六条实测就不同
# （这里的 `murripple/lanes.py` 写「底鼓」，画面上出的是「撼岳」）。
# 真正要守的是"每个 id 渲染层都认识"，见
# `tests/test_lanes.py::test_every_lane_id_python_can_emit_has_a_renderer_label`。
LANE_LABELS: dict[str, str] = {
    "bass": "渊鸣", "pad": "流岚", "pluck": "缥缈", "arp": "泠泠",
    "bell": "霜铎", "kick": "撼岳", "snare": "裂帛", "hat": "碎玉",
}
# 打击声部在乐谱里写的是 `pitch=0`——那在 MIDI 上是一个**真实的音**（C-1），
# 照搬进 lane 会让画面把每一记鼓都画在最低音的位置。它们本来就没有音高。
UNPITCHED_TRACKS = ("kick", "snare", "hat")


class SectionMarksError(ValueError):
    """`build/sections.json` 有问题。消息里必须点名是哪个文件、哪一条不对。"""


class LaneSpecsError(ValueError):
    """`build/lanes.json` 有问题。消息里必须点名是哪一条、缺什么。

    **`entry`/`field` 两个结构化属性是给测试断言用的**，不是装饰。渲染后的
    整条消息由「问题」+「修复建议」拼成，而修复建议里带着一份示例
    lane（`{"id": "bass", ..., "hue": 225.0, ...}`），**每一个字段名都在那
    段后缀里出现**。于是任何 `match="hue"` 之类的子串断言对**所有**坏数据
    都为真——评审 2026-08-14 实测：顶层不是数组、缺 label、notes 不是数组，
    统统能骗过 `re.search("hue", ...)`。

    规矩（管理窗口 2026-08-14 定）：**`match=` 永远断言在结构化字段或诊断
    段上，绝不断言在渲染后的整条消息上。** jsonschema 那边对应的是断
    `exc.value.message` 而不是 `str(exc.value)`（Task 1 已定）；自定义异常
    这边就是断这两个属性。
    """

    def __init__(
        self,
        message: str,
        *,
        entry: int | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.entry = entry    # 第几条 lane 出的事；整份文件的问题为 None
        self.field = field    # 哪个字段出的事；不针对单个字段的问题为 None


def find_source(song_dir: Path) -> Path:
    for suffix in AUDIO_SUFFIXES:
        candidate = song_dir / f"source{suffix}"
        if candidate.exists():
            return candidate
    raise SystemExit(
        f"在 {song_dir} 下没找到 source 音频。"
        f"支持的扩展名：{', '.join(AUDIO_SUFFIXES)}"
    )


def load_section_marks(build_dir: Path) -> list[dict] | None:
    """读 `build/sections.json`——合成的曲子自带的**段落真值**。

    文件不在就返回 None，下游照旧自己检测：普通歌曲这一路一行不变。

    **按 t 排序**再交出去：`analyze.sections_from_marks` 假设 marks 按 t
    升序（每段的止点取自「下一条」mark），但它自己不校验——乱序进去会
    静默算出错误的段落区间，一句提示都没有。t 就写在每条 mark 上，顺序
    信息一点没丢，排序是唯一正确的解读，不必为此报错。

    真正的坏数据（结构不对、时刻重复）则当场抛错：这个文件读错了只会让
    画面上的段落对不上音乐，而对不上时人只会怀疑是分析算法不准，根本想
    不到是一份 JSON 写坏了。
    """
    path = Path(build_dir) / SECTIONS_FILENAME
    if not path.exists():
        return None

    fix = (
        f"删掉它重新生成（合成的歌跑 `murripple compose <歌曲目录> --from-score`），"
        f'或者手工改成按 t 升序的数组：[{{"t": 0.0, "name": "起"}}, ...]。'
    )

    def bad(problem: str) -> SectionMarksError:
        return SectionMarksError(f"{path} {problem}。{fix}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise bad(f"不是合法的 JSON：{exc}") from exc

    if not isinstance(raw, list):
        raise bad(f"顶层要是一个数组，实际是 {type(raw).__name__}")
    if not raw:
        # 空数组会让 build_timeline 静默退回自相似矩阵去猜——本来有真值却
        # 悄悄改用猜的，正是这个文件最该防的那种失败。
        raise bad("是空的：一条段落边界都没有")

    marks: list[dict] = []
    for i, mark in enumerate(raw):
        if not isinstance(mark, dict):
            raise bad(f"第 {i} 条不是对象，而是 {type(mark).__name__}")
        for field in ("t", "name"):
            if field not in mark:
                raise bad(f"第 {i} 条缺少 {field}")
        if isinstance(mark["t"], bool) or not isinstance(mark["t"], (int, float)):
            raise bad(f"第 {i} 条的 t 不是数字：{mark['t']!r}")
        if mark["t"] < 0:
            raise bad(f"第 {i} 条的 t 是负数：{mark['t']!r}")
        marks.append({"t": float(mark["t"]), "name": str(mark["name"])})

    marks.sort(key=lambda m: m["t"])
    for earlier, later in zip(marks, marks[1:]):
        if earlier["t"] == later["t"]:
            raise bad(
                f"有两条 mark 都落在 t={earlier['t']}"
                f"（{earlier['name']}、{later['name']}），分不出先后"
            )
    return marks


def load_lane_specs(build_dir: Path) -> list[dict] | None:
    """读 `build/lanes.json`——合成的曲子自带的**轨道真值**。

    文件不在就返回 None，下游照旧切频段猜：普通歌曲这一路一行不变。

    与 `load_section_marks` 同一路数，坏数据当场抛错。校验到哪一层不是拍
    脑袋定的，是**照着"不拦的话用户会看到什么"实测**定的（2026-08-14）：

    | 坏法 | 不拦的话下游报什么 | 拦不拦 |
    |---|---|---|
    | 不是 JSON / 顶层不是数组 | `TypeError: 'int' object is not subscriptable` | 拦 |
    | 空数组 | schema 的 minItems，**2174 字符**、把整段 lanes schema 打印出来 | 拦 |
    | 某一条不是对象 | 同上那个没头没尾的 TypeError | 拦 |
    | 缺 hue | `KeyError: 'hue'`，不含文件名、不含第几条 | 拦 |
    | hue 不是数 | `ValueError: could not convert string to float: '蓝'`（38 字符） | 拦 |
    | notes 不是数组 | `TypeError: 'int' object is not iterable`（28 字符） | 拦 |
    | hue 超 0–360、id 不是非空串、note 缺 t/v/pitch | jsonschema **点名了字段与路径**，人读得懂 | **不拦** |

    最后一行是有意留白：schema 已经把这几样拒得很清楚了，在这里再手写一遍
    只是同一条检查的第二份实现——Task 1 删掉 `validate_timeline()` 里那段
    重名检查是同一个道理。这里拦的全是"下游只会甩出一个不含任何线索的
    裸异常"的那几种。

    **这条分界的代价要记明白**（评审 2026-08-14 指出我漏记了）：坏掉的
    `lanes.json` 因此**分成两类结局**——

    - **干净地 `return 1` + 一句人话**：本函数拦下的六种，加上
      `build()` 里那条"stem 指向不存在的分轨"前置检查（见那里的注释）。
    - **未捕获的 `jsonschema.ValidationError` traceback**：有意不拦的那几种
      （`hue: 400`、note 缺 `pitch` 等），从 `murripple/timeline.py` 的
      `validate_timeline()` 逃出来。

    第二类不好看，但消息里点着字段名与路径，人查得下去；要把它也变成
    `return 1`，得在 `build()` 里捕 `ValidationError`，那会把**所有**
    timeline 组装错误（包括真 bug）一并吞成一行提示。分界画在"消息里有没有
    线索"上，不是画在"抛不抛异常"上。
    """
    path = Path(build_dir) / LANES_FILENAME
    if not path.exists():
        return None

    fix = (
        f"删掉它重新生成（`murripple compose <歌曲目录> --from-score`），"
        f'或者手工改成数组：[{{"id": "bass", "label": "渊鸣", "hue": 225.0, '
        f'"stem": "bass", "notes": []}}, ...]。'
    )

    def bad(
        problem: str, *, entry: int | None = None, field: str | None = None
    ) -> LaneSpecsError:
        return LaneSpecsError(f"{path} {problem}。{fix}", entry=entry, field=field)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise bad(f"不是合法的 JSON：{exc}") from exc

    if not isinstance(raw, list):
        raise bad(f"顶层要是一个数组，实际是 {type(raw).__name__}")
    if not raw:
        # 空数组一路走到 schema 的 minItems 才被拒，报的是一段人读不出
        # "是我那份文件空了"的 schema dump。见 `murripple/timeline.py`
        # 里 `lane_specs` 那段 docstring——那边也拒 `[]`，两道都要有：
        # 这边给人话，那边挡住绕开本函数直接传空表的调用方。
        raise bad("是空的：一条视觉轨道都没有")

    for i, spec in enumerate(raw):
        if not isinstance(spec, dict):
            raise bad(f"第 {i} 条不是对象，而是 {type(spec).__name__}", entry=i)
        for field in ("id", "label", "hue", "stem", "notes"):
            if field not in spec:
                raise bad(f"第 {i} 条缺少 {field}", entry=i, field=field)
        if isinstance(spec["hue"], bool) or not isinstance(spec["hue"], (int, float)):
            raise bad(
                f"第 {i} 条的 hue 不是数字：{spec['hue']!r}", entry=i, field="hue"
            )
        if not isinstance(spec["notes"], list):
            raise bad(
                f"第 {i} 条的 notes 不是数组，而是 {type(spec['notes']).__name__}",
                entry=i,
                field="notes",
            )
    return raw


def _language_lines(heard, song_dir: Path) -> str:
    """侦测结果那几句话。**打在主日志上，不许折进详细区。**

    三种情形三种说法，一句都不能省：

    · **指定的**——照实说是他指定的，不要说成"侦测出来的"。
    · **侦测出来且站得住**——说出认的是什么、几个片段一致，并且**顺带给出
      推翻它的办法**。这一句是给"看着对、其实错了"那种情况留的门：认错时
      整首歌的歌词都会错位，而画面上只是"歌词不对"，看不出错在语言这一步。
    · **拿不准**——票型摊开写，再给一条**能照着敲的命令**。

    最后那条命令写成 `uv run murripple build …`（不是 `run --force`）：
    `build` 每次都真的重做分析、没有跳过逻辑，所以它一定有效；而 `run` 在
    `build/timeline.json` 已经在盘上时会跳过分析那一步。这条命令也是**网页
    那条路唯一的出路**——壳子上没有语言入口（那是有意的，见 README/台账），
    所以这句话必须指得出一条网页用户真的走得到的路，而不是只报一个坏消息。
    """
    total = len(heard.votes)
    if heard.asked:
        return f"  语言：{heard.code}（--language 指定）"
    tally = "、".join(
        f"{code}×{n}" for code, n in Counter(heard.votes).most_common()
    )
    if heard.unsure:
        return (
            f"  语言：{heard.code}（自动侦测，**拿不准**："
            f"{total} 个片段认出 {tally}）\n"
            f"  认错的话整首歌的歌词都会错位。指定语言重跑：\n"
            f"  uv run murripple build {song_dir} --language {heard.code}"
        )
    return (
        f"  语言：{heard.code}（自动侦测，{heard.agree}/{total} 个片段一致；"
        f"认错的话加 --language 指定）"
    )


def build(
    song_dir: Path,
    word_level: bool,
    bitrate: str,
    no_lyrics: bool = False,
    language: str | None = None,
) -> int:
    song_dir = song_dir.resolve()
    build_dir = song_dir / "build"
    audio_dir = build_dir / "audio"

    # 合成的曲子自带真实段落边界与轨道真值。有真值就别再猜。
    # **先读再干活**：这两份文件读不动的话，跑完四分钟 Demucs 再报错是白等。
    try:
        section_marks = load_section_marks(build_dir)
        lane_specs = load_lane_specs(build_dir)
    except (SectionMarksError, LaneSpecsError) as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    # **歌词那道门在这里，而且只在这里。**
    #
    # 它原来长在 `run` 里，于是同一个输入在两个入口上得到两个答案：`run` 退出
    # 1 一步不跑，`build` 打一句「跳过歌词层」照样做完。而且它排在 `run` 的
    # 「产物在就跳过分析」**之前**——只需要重新打包时也照拒，那一步跟歌词毫无
    # 关系。搬到这儿两件事一起解决：`run` 跳过分析时根本走不到这儿（③ 修了），
    # 而 `run` 真要分析时必然经过它（判断只剩一处，②）。
    #
    # **拦在动盘之前**：往下是 Demucs 那几分钟到一小时。忘了放歌词的人不该
    # 白烧一小时——这是这道门存在的全部理由，不许被放宽掉。
    #
    # **默认拦、显式放行**：`--no-lyrics`（或 `compose.json`）才继续。原来
    # `build` 那一半是**沉默降级**：它不问，也不说清用户是不是真想这样。
    reason = blocked_reason(song_dir, no_lyrics=no_lyrics)
    if reason is not None:
        print(reason, file=sys.stderr)
        return 1

    # 分轨已由外部提供（compose 合成的，或手工放的扁平布局）就不分离，
    # 也不再要求 source.*——合成的歌根本没有源音频。
    #
    # 判据是 `find_flat_stems`（一整套扁平 wav 都在——真歌四条，或 task-7
    # 之后 compose 产出的九条），**不是 `build/stems/` 目录在不在**：
    # `separate()` 写的是 `stems/<model>/<源名>/*.wav`，任何一次正常
    # build 之后那个目录都在，照"目录在不在"判断会让第二次 build 误跳过
    # 分离、拿旧分轨假装新结果。九条那一套认不认，靠 `extra_complete_sets`
    # 传给 `find_flat_stems`——`murripple/stems.py` 本身不认识 compose。
    #
    # 合成器不在时传空元组：没有 compose 就产不出那九条，认得它反而是认一套
    # 这棵树上不可能出现的分轨。真歌那四条走 `find_flat_stems` 自带的名单，
    # 与合成器在不在无关。
    stem_paths = find_flat_stems(
        build_dir,
        extra_complete_sets=(compose_synth.STEM_NAMES,) if COMPOSE_AVAILABLE else (),
    )
    if stem_paths is not None:
        print(f"[1/5] 分离音源：跳过（build/stems/ 下已有 {len(stem_paths)} 条现成分轨）")
    else:
        # **先问 find_source，再建 build/**：find_source 找不到就直接
        # SystemExit，把 mkdir 放在它前面会让缺 source 的歌白白多出一个空
        # build/ 目录——改动前不会。真歌路径上的可观察差异，一处都不留。
        source = find_source(song_dir)
        build_dir.mkdir(parents=True, exist_ok=True)
        print(f"[1/5] 分离音源：{source.name}")
        try:
            stem_paths = separate(source, build_dir / "stems")
        except SeparationError as exc:
            print(f"分离失败：{exc}", file=sys.stderr)
            return 1

    print("[2/5] 读取分轨")
    stem_audio: dict[str, np.ndarray] = {}
    sr = 44100
    for name, path in stem_paths.items():
        try:
            y, sr = librosa.load(path, sr=None, mono=True)
        except Exception as exc:  # noqa: BLE001
            # `find_flat_stems` 只判文件在不在，不判读不读得动：空文件实测
            # 抛的是一个**连消息都没有的** EOFError，损坏文件抛
            # audioread.NoBackendError——异常类型横跨 soundfile/audioread，
            # 且都不带路径。不接住的话，用户看到的就是一个没头没尾的
            # traceback，压根不知道是哪条分轨坏了。
            print(
                f"读不了分轨 {path.name}（{path}）：{type(exc).__name__}: {exc}\n"
                f"  这个文件是空的或者损坏了。删掉 {path.parent} 重跑一次。",
                file=sys.stderr,
            )
            return 1
        stem_audio[name] = y.astype(np.float32)

    duration = len(next(iter(stem_audio.values()))) / sr
    if duration < MIN_DURATION:
        print(f"音频仅 {duration:.1f} 秒，太短，中止。", file=sys.stderr)
        return 1
    if duration > LONG_DURATION_WARNING:
        print(
            f"警告：音频 {duration / 60:.1f} 分钟，产物体积会很大。",
            file=sys.stderr,
        )

    # `lanes.json` 指着一条不存在的分轨——这是 `load_lane_specs` 拦不到的那
    # 一种（它跑在读音频之前，那时还不知道有哪些分轨），但到这里 stem_audio
    # 已经在手上了，能给出一句人话。
    #
    # 不拦的话 `lanes_from_specs` 抛的 KeyError 消息其实很好，但它是从
    # build() 裸抛出去的 traceback，不是 CLI 错误。也**不能**改成在
    # build_timeline 外面套 except KeyError——那里面还有 stem_audio["vocals"]
    # 等好几处 KeyError 源，套上去是拿"掩盖真 bug"换"错误信息好看"。
    if lane_specs is not None:
        missing = sorted({s["stem"] for s in lane_specs} - set(stem_audio))
        if missing:
            print(
                f"{build_dir / LANES_FILENAME} 要的分轨 {'、'.join(missing)} "
                f"不在 {build_dir / 'stems'} 里；现有：{'、'.join(sorted(stem_audio))}。"
                f"删掉它重新生成（`murripple compose <歌曲目录> --from-score`）。",
                file=sys.stderr,
            )
            return 1

    print("[3/5] 对齐歌词")
    lyrics: list[dict] = []
    #: 这一趟真的按什么语言听的。**只有 WhisperX 真跑过才会有东西**——硬字幕
    #: 那条路、没有 lyrics.txt、`--no-lyrics`、器乐曲，都一次都没听过，那时
    #: 它就该是空的，而不是补一个"大概是 zh"进去。往 meta 里写一个没人听过的
    #: 语言码，正是这一棒禁止的「沉默地猜」。
    heard: list = []
    lyrics_file = song_dir / "lyrics.txt"
    timing = load_subtitle_timing(song_dir)
    if not lyrics_file.exists():
        print("  未找到 lyrics.txt，跳过歌词层。")
    elif timing is not None:
        # 硬字幕的时间戳**就是**对齐结果，不需要再听一遍。
        #
        # WhisperX 听唱歌是会出错的（第一首歌里把「陇西」听成「吹息」、
        # 「守一纸诺言」听成「手一指抹烟」）；而字幕从暗变亮的那一刻是画面
        # 直接给出的演唱时刻。拿它去跑对齐只会把准的换成不准的，还会因为
        # 对不上而丢行——丢了行，按下标写的补丁就整体错位。
        lyrics = timing
        print(f"  用硬字幕的演唱时刻，跳过 WhisperX（{len(lyrics)} 行）")
    else:
        try:
            def _say(h):
                # 侦测结果**当场**打出来，不攒到最后：对齐要跑几分钟，这句话
                # 攒到跑完再说，用户已经等完了才知道它听错了语言。
                heard.append(h)
                print(_language_lines(h, song_dir))

            lyrics, unmatched = align_lyrics(
                stem_paths["vocals"],
                lyrics_file.read_text("utf-8"),
                word_level,
                language,
                on_language=_say,
            )
            if unmatched:
                print(f"  以下 {len(unmatched)} 行未对上，请在 overrides.json 中补时间：")
                for line in unmatched:
                    print(f"    - {line}")
        except AlignmentUnavailable as exc:
            print(f"  {exc}")
            print("  降级为无歌词，继续。")

    print("[4/5] 编码音频")
    for name, path in stem_paths.items():
        encode_stem(path, audio_dir / f"{name}.m4a", bitrate)

    print("[5/5] 组装 timeline")
    doc = build_timeline(
        title=song_dir.name,
        stem_audio=stem_audio,
        sr=sr,
        lyrics=lyrics,
        bitrate_label=f"aac-{bitrate}",
        section_marks=section_marks,
        lane_specs=lane_specs,
        language=heard[0].code if heard else None,
    )
    # 精修层：自动分析不满意的地方改 overrides.json 重跑，不动代码
    try:
        patch = overrides.load(song_dir)
    except overrides.OverrideError as exc:
        print(f"overrides.json 有问题：{exc}", file=sys.stderr)
        return 1
    if patch:
        try:
            doc = overrides.apply(doc, patch)
        except overrides.OverrideError as exc:
            print(f"overrides.json 有问题：{exc}", file=sys.stderr)
            return 1
        print(f"      已应用 {song_dir / overrides.FILENAME}")

    out = build_dir / "timeline.json"
    out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    print(f"\n完成：{out}")
    print(f"  时长 {doc['meta']['duration']:.1f}s · "
          f"{doc['meta']['bpm']:.1f} BPM · "
          f"{len(doc['lanes'])} 条轨道 · "
          f"{len(doc['lyrics'])} 句歌词")
    return 0


def load_subtitle_timing(song_dir: Path) -> list[dict] | None:
    """硬字幕的演唱时刻，对不上就退回常规对齐并说明原因。"""
    try:
        return load_timing(song_dir)
    except (IngestError, ValueError, KeyError) as exc:
        print(f"  {exc}", file=sys.stderr)
        print("  退回常规对齐。")
        return None


def ingest(song_dir: Path, force: bool = False) -> int:
    """`_in/` 里的原始素材 → 标准的 `source.*` + `lyrics.txt`（+ 时间戳补丁）。

    **走到这一步就停。** OCR 会错字，而歌词原文的准确度直接决定强制对齐的
    质量——错的地方会一路错到底，看画面时根本看不出是哪一步错的。所以这里
    只负责把素材整理好，让人过一眼，再自己去跑 `run`。
    """
    song_dir = Path(song_dir).resolve()
    try:
        plan = scan(song_dir / "_in")
    except IngestError as exc:
        print(f"素材看不明白：{exc}", file=sys.stderr)
        return 1

    for note in plan.notes:
        print(f"  {note}")

    try:
        print(f"[1/2] 准备音频 ← {plan.audio_from.name}")
        out = prepare_audio(plan.audio_from, song_dir, force=force)
        print(f"      → {out.name}")

        lyrics_path = song_dir / "lyrics.txt"
        if lyrics_path.exists() and not force:
            # 这一份多半是人工校对过的。重跑 ingest 只为换个音频、或者
            # 参数调错了重来，不该把校对成果一把冲掉。
            print(f"[2/2] 歌词    跳过（{lyrics_path.name} 已存在，用 --force 重来）")
        elif isinstance(plan.lyrics_from, tuple):
            video = plan.lyrics_from[1]
            print(f"[2/2] OCR 硬字幕 ← {video.name}（要一会儿）")
            lines, _ = extract_subtitles(video)
            if not lines:
                print("      一行都没认出来，请自己写 lyrics.txt", file=sys.stderr)
                return 1
            write_lyrics(lines, lyrics_path)
            # 时间戳才是硬字幕相对现成歌词的独有价值：这首歌可以完全跳过
            # WhisperX，而它听唱歌是会出错的。
            write_timing(lines, song_dir)
            print(f"      → lyrics.txt（{len(lines)} 行）、{TIMING_FILENAME}（演唱时刻）")
        elif plan.lyrics_from is not None:
            lyrics_path.write_text(
                plan.lyrics_from.read_text(encoding="utf-8"), encoding="utf-8"
            )
            print(f"[2/2] 歌词    ← {plan.lyrics_from.name} → lyrics.txt")
        else:
            print("[2/2] 歌词    没有。请自己写一份 lyrics.txt 放进歌曲目录。")
    except IngestError as exc:
        print(f"整理失败：{exc}", file=sys.stderr)
        return 1

    print(
        f"\n完成。请先过一眼 {song_dir / 'lyrics.txt'}，确认无误后：\n"
        f"  uv run murripple run {song_dir}"
    )
    return 0


def ingest_url(
    song_dir: Path, url: str, force: bool = False, want_video: bool = True
) -> int:
    """`--url`：先把素材取回 `_in/`，再**原样**交给上面那个 `ingest`。

    取回这一层一个决策都不做——落进 `_in/` 之后，"音频从哪来、歌词从哪来"
    仍旧全部由 `scan` 的决策表说了算。

    **`fetch` 那几个异常的落点就在这里。** `UnusableAudioError`、
    `AmbiguousResultError`、以及"`_in/` 里已经有素材了"都是直接抛的（消息里
    带可执行的修复建议，照 `IngestError`／`SeparationError`／`PackError` 的老
    路数），到这一层才被打成人看得见的一句话。**不接住的话，用户看到的是一
    整段 traceback**——那正是"降级必须大声说"要防的反面。

    **取回失败就不往下跑。** 继续跑 `ingest` 的话，屏幕上会先是取回的原因、
    再来一句"素材看不明白：`_in/` 是空的"——两条错，真正那条被埋在上面。

    默认连视频一起取：没有视频就没有硬字幕可 OCR，`scan` 会说"请自己写一份
    lyrics.txt"，这条路当场断掉。视频比音频大得多，`--no-video` 是那条出路。
    """
    song_dir = Path(song_dir)
    # 人手上只有一条链接，不该先被要求自己去建一层目录。
    song_dir.mkdir(parents=True, exist_ok=True)
    try:
        fetch_url(url, song_dir, want_video=want_video, force=force)
    except FetchError as exc:
        print(f"取回失败：{exc}", file=sys.stderr)
        return 1
    return ingest(song_dir, force)


def _draft_next_steps(song_dir: Path, draft_path: Path) -> int:
    """草稿已经在盘上了，说清它是什么、以及人接下来要干什么。

    **这几句是这个功能的一半。** 另一半（草稿写的是 `lyrics.draft.txt` 而不是
    `lyrics.txt`）挡住了「不看就用」的机器路径，这几句挡的是人的那一边：他得
    知道自己拿到的是什么，才会去核。所以三条一条都不能省——
    「字会错」「断句不是歌词的行」「行数不对比没有更坏」——**没有准确率数字**，
    本仓没有人量过。
    """
    lines = [
        ln for ln in draft_path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    print(
        f"\n完成。这是机器听写的草稿，不是歌词：\n"
        f"  · 字会认错——它听的是唱腔，不是说话。这份草稿一个字都没有人核过。\n"
        f"  · 断句是按停顿切的，不是歌词的行。这份草稿 {len(lines)} 行，"
        f"行数几乎肯定不对。\n"
        f"  · 行数决定对齐质量：一份行数不对的 lyrics.txt 比没有歌词更坏。\n"
        f"  打开 {draft_path} 自己断句、改字，存成 {song_dir / 'lyrics.txt'}，再跑：\n"
        f"  uv run murripple run {song_dir}"
    )
    return 0


def transcribe(
    song_dir: Path, force: bool = False, language: str | None = None
) -> int:
    """`source.*` → `lyrics.draft.txt`。**机器认字，人断句。**

    **这一步绝不写 `lyrics.txt`。** 草稿要变成歌词，只能由人自己断好句、改好
    字、存过去（网页那条路上，"存过去"就是校对框里点「改好了，继续」）。

    **听的是 `source.*` 整首混音，不做音源分离。** 人声轨确实听得更准，但拿它
    就得先跑一遍 Demucs，而那几分钟是纯浪费——`build` 判断"要不要起 Demucs"用
    的是扁平布局，`separate()` 写的是嵌套布局，扫不到，于是 `build` 会原样再分
    离一遍。证据、两份真跑抄件、以及"要改就得动核心管线的判据"这件事，都在
    `murripple/ingest/transcribe.py` 的 docstring 里。
    """
    song_dir = Path(song_dir).resolve()
    draft_path = song_dir / DRAFT_FILENAME
    lyrics_path = song_dir / "lyrics.txt"

    # `lyrics.txt` 在就什么都不做。它是这首歌歌词的真相源（多半是人自己听写或
    # 校对过的），而听写只在「没有歌词」时才有意义。
    if lyrics_path.exists():
        print(f"[1/2] 听写    跳过（{lyrics_path.name} 已存在，用不着听）")
        print(
            f"[2/2] 写草稿  跳过（听写只在没有歌词时才有意义；"
            f"真要重听一遍，先把 {lyrics_path.name} 挪走）"
        )
        return 0

    if draft_path.exists() and not force:
        # 断点续跑，跟 `run` 每步先看产物在不在是同一条规矩：听写要跑几分钟，
        # 页面上二次点开始不该从头再来一遍。
        print(f"[1/2] 听写    跳过（{draft_path.name} 已存在，用 --force 重来）")
        print(f"[2/2] 写草稿  跳过（{draft_path.name} 已存在，用 --force 重来）")
        return _draft_next_steps(song_dir, draft_path)

    source = find_source(song_dir)
    print(f"[1/2] 听写    ← {source.name}（模型跑在本机，要一会儿）")
    try:
        segments = transcribe_audio(
            source,
            language=language,
            on_language=lambda h: print(_language_lines(h, song_dir)),
        )
    except TranscriptionUnavailable as exc:
        print(f"听不了：{exc}", file=sys.stderr)
        return 1
    if not segments:
        print("      一个字都没听出来，请自己写 lyrics.txt", file=sys.stderr)
        return 1

    print("[2/2] 写草稿")
    write_draft(segments, song_dir)
    print(f"      → {draft_path.name}（{len(segments)} 行）")
    return _draft_next_steps(song_dir, draft_path)


def _write_sections(score: compose_score.Score, build_dir: Path) -> None:
    """把**真实**段落边界写成 `build/sections.json`（定案 4）。

    不经 `overrides.json` 的下标：按下标打进一个数量会变的列表，正是 M4
    栽过的那一跤——列表一变长短，补丁就整体错位，而且没有任何提示。
    """
    spans = compose_arrange.section_spans(score)
    marks = [
        {"t": spans[s.name][0], "name": s.name}
        for s in score.sections
    ]
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / SECTIONS_FILENAME).write_text(
        json.dumps(marks, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _write_lane_specs(score: compose_score.Score, build_dir: Path) -> None:
    """把乐谱的音符表导成 `build/lanes.json`——**视觉轨道的真值**。

    **主奏不在内。** 判据不是"名字叫 lead"，而是"它进的是 vocals 那条
    stem"：进 vocals 的声部驱动的是判定环本身，环不占轨道（spec 第 7 节）。
    照 `STEM_OF` 写而不是照名字写，多一条声部并进 vocals 时这里自动跟上。

    `stem` 同样走 `STEM_OF`，不写死恒等：`lanes_from_specs` 要求
    `spec["stem"]` 落在 `stem_audio` 的键里，而那些键正是
    `set(STEM_OF.values())`。照 `STEM_OF` 取是**必然**对得上，照轨道名取
    只是眼下恰好对得上（task-7 的恒等映射）。

    与 `_write_sections` 同一路数：真值落成一份人能改的 JSON，不经
    `overrides.json` 的下标——按下标打进一个数量会变的列表是 M4 栽过的跤。
    """
    stem_of = compose_synth.STEM_OF
    specs = [
        {
            "id": track,
            "label": LANE_LABELS[track],
            "hue": LANE_HUES[track],
            "stem": stem_of[track],
            "notes": [
                {
                    "t": n.t,
                    "v": n.vel,
                    "pitch": None if track in UNPITCHED_TRACKS else n.pitch,
                }
                for n in score.tracks[track]
            ],
        }
        for track in compose_score.TRACKS
        if stem_of[track] != "vocals"
    ]
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / LANES_FILENAME).write_text(
        json.dumps(specs, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _duplicate_section_name(score: compose_score.Score) -> str | None:
    """段落重名会让 `section_spans` 的 name → 区间 映射悄悄折掉一段。

    `compose.json` 是给人改的文件，改段落名是支持的用法（`--from-score`）。
    重名之后 `section_spans` 返回的 dict 里后一段直接盖掉前一段，写出去的
    sections.json 会有两条 mark 指向同一时刻——与其等 build 阶段对着一个
    **生成出来的**文件报错，不如在读用户手改的那份时当场说清楚。
    """
    seen: set[str] = set()
    for section in score.sections:
        if section.name in seen:
            return section.name
        seen.add(section.name)
    return None


def compose(
    song_dir: Path,
    seed: int | None,
    bpm: float | None,
    key: int | None,
    scale: str | None,
    duration: float | None,
    from_score: bool,
) -> int:
    """摇一首曲子出来。**做完就停**，不自动往下跑。

    合成是要试听、要重摇的，不该每次都连着跑四十分钟——与 `ingest` 同理。
    """
    if not COMPOSE_AVAILABLE:
        # 正常情况下走不到这里：合成器不在时 `main()` 压根不注册 `compose`
        # 子命令，argparse 会先一步拒掉。这条留给**直接调用这个函数**的人
        # （测试、别的脚本），让它明确失败而不是在下面某一行抛 AttributeError
        # ——`compose_synth` 那时是 None，报出来的会是一句看不懂的话。
        print(
            "这份检出里没有 murripple/compose/，合成功能不可用。"
            "其余命令（build／pack／run／ingest／transcribe／serve）不受影响。",
            file=sys.stderr,
        )
        return 1
    song_dir = Path(song_dir).resolve()
    song_dir.mkdir(parents=True, exist_ok=True)
    build_dir = song_dir / "build"
    score_path = song_dir / COMPOSE_FILENAME

    if from_score:
        if not score_path.exists():
            print(
                f"{score_path} 不存在。先跑一次**不带** --from-score 的 compose "
                f"摇一首出来：`murripple compose {song_dir}`。",
                file=sys.stderr,
            )
            return 1
        try:
            score = compose_score.load(score_path)
        except (compose_score.ScoreError, KeyError, ValueError, TypeError) as exc:
            print(f"{COMPOSE_FILENAME} 读不动：{exc}", file=sys.stderr)
            return 1
        print(f"[1/2] 读谱     ← {score_path.name}（seed {score.seed}）")
    else:
        scale = scale or DEFAULT_SCALE
        if scale not in compose_theory.SCALES:
            print(
                f"不认识的调式 {scale!r}。可选："
                f"{'、'.join(compose_theory.SCALES)}",
                file=sys.stderr,
            )
            return 1
        # 缺省随机取，但**一定打印出来**：不打印的话这一首就再也摇不回来了。
        if seed is None:
            seed = int(np.random.Generator(np.random.PCG64()).integers(0, 2**31 - 1))
        if bpm is None:
            bpm = float(
                np.random.Generator(np.random.PCG64(seed)).integers(*BPM_RANGE)
            )
        if key is None:
            key = int(np.random.Generator(np.random.PCG64(seed ^ 99)).integers(0, 12))
        duration = duration or DEFAULT_DURATION
        key_name = next(
            (name for name, pc in compose_theory.KEYS.items() if pc == key), str(key)
        )
        print(f"[1/2] 作曲     seed {seed} · {bpm:.0f} BPM · {key_name}{scale}")
        score = compose_arrange.arrange(
            seed=seed, bpm=bpm, key=key, scale=scale, duration=duration
        )
        compose_score.save(score, score_path)

    duplicate = _duplicate_section_name(score)
    if duplicate is not None:
        print(
            f"{score_path} 里有两段都叫 {duplicate!r}。段落名要各不相同"
            f"（它是段落边界的键），改一个再跑。",
            file=sys.stderr,
        )
        return 1

    print("[2/2] 合成分轨")
    stems = compose_synth.render_score(score)
    paths = compose_synth.write_stems(stems, build_dir / "stems")
    _write_sections(score, build_dir)
    _write_lane_specs(score, build_dir)

    # 换个 seed 重摇之后，`build/timeline.json` 描述的还是**上一首**。而
    # `run()` 见到它就跳过分析（断点续跑，那是它该做的），于是直接拿旧
    # timeline 去打包——新音乐、旧画面，还打印一句"完成"。
    #
    # timeline 是可再生的派生物，`run` 本来就把它当缓存。缓存的输入变了就
    # 该失效，这是缓存的正常语义，不是给 compose 开的特例。`compose` 的整个
    # 卖点就是反复重摇，这条路会被高频踩到。
    timeline = build_dir / "timeline.json"
    if timeline.exists():
        timeline.unlink()
        print(f"      已作废 {timeline.name}（描述的是上一首，run 会重新分析）")

    # 报**实际**时长，不是要的时长：每段恒为整数遍动机，秒数会被对齐，
    # 误差上界 4 个小节（`arrange._bars_per_section`）。照着要的数报，用户
    # 会以为 `--duration 150` 就一定是 150 秒。
    seconds = len(next(iter(stems.values()))) / compose_synth.SR
    asked = (
        f"（要的是 {duration:.0f}s，段落按整数遍动机对齐）"
        if duration is not None and abs(seconds - duration) >= 0.05
        else ""
    )
    print(
        f"\n完成：{score_path}\n"
        f"  {seconds:.1f}s{asked} · {len(score.sections)} 段 · "
        f"{sum(len(v) for v in score.tracks.values())} 个音符\n"
        f"  分轨 → {paths['vocals'].parent}\n\n"
        f"先把那 {len(paths)} 条 wav 一起放来听听，不满意就换个 seed 重摇；满意了再：\n"
        f"  uv run murripple run {song_dir}"
    )
    return 0


def run(
    song_dir: Path,
    renderer: Path,
    title: str | None,
    word_level: bool,
    bitrate: str,
    force: bool,
    no_lyrics: bool = False,
    language: str | None = None,
) -> int:
    """标准输入 → 成品。**每一步先看产物在不在，在就跳过。**

    全链耗时：Demucs 约 4 分钟 + Whisper 几分钟 + 导出 33 分钟。不可断点
    续跑的话，改一个打包参数就要从头再来一小时。
    """
    song_dir = Path(song_dir).resolve()
    # **这里不再有歌词门**，它搬进 `build()` 了（见那里的注释）。搬走解决了
    # 两件事：① 只需要重新打包时不再被拦——下面那句「产物在就跳过分析」原来
    # 排在门后面，而重新打包跟歌词毫无关系；② 判断只剩一处，`run` 与 `build`
    # 不会各写一遍等着漂。忘了放歌词的人照样在动 Demucs 之前就被拦下。
    timeline = song_dir / "build" / "timeline.json"
    if timeline.exists() and not force:
        print("[1/2] 分析    跳过（build/timeline.json 已存在，用 --force 重来）")
    else:
        print("[1/2] 分析")
        code = build(song_dir, word_level, bitrate, no_lyrics, language)
        if code != 0:
            # 分析失败还照打包的话，打出来的是上一次的旧产物，看不出问题。
            return code

    print("[2/2] 打包")
    try:
        out = pack(song_dir, renderer, title)
    except PackError as exc:
        print(f"打包失败：{exc}", file=sys.stderr)
        return 1
    print(f"      → {out}（{out.stat().st_size / 1e6:.1f} MB）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="murripple")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="分析一首歌，产出 timeline.json")
    p_build.add_argument("song_dir", type=Path, help="歌曲目录，如 songs/demo")
    p_build.add_argument(
        "--word-level", action="store_true", help="启用词级歌词对齐"
    )
    p_build.add_argument(
        "--language",
        default=None,
        help="歌词与人声的语言（Whisper 语言码，如 zh/fr/en）。不给就自动侦测，侦测结果会打在日志里",
    )
    p_build.add_argument("--bitrate", default=DEFAULT_BITRATE)
    p_build.add_argument(
        "--no-lyrics",
        action="store_true",
        help="这首歌本来就没有歌词，做成没有歌词层的版本",
    )

    p_pack = sub.add_parser("pack", help="把 timeline 与音频打成单文件 index.html")
    p_pack.add_argument("song_dir", type=Path, help="歌曲目录，如 songs/demo")
    p_pack.add_argument(
        "--renderer",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "renderer",
        help="渲染器目录，默认为仓库内的 renderer/",
    )
    p_pack.add_argument(
        "--title",
        default=None,
        help="标题页与浏览器标签显示的曲名。默认取 build 时记下的目录名。",
    )

    default_renderer = Path(__file__).resolve().parent.parent / "renderer"

    p_ingest = sub.add_parser(
        "ingest", help="把 _in/ 里的原始素材整理成 source.* 与 lyrics.txt"
    )
    p_ingest.add_argument("song_dir", type=Path, help="歌曲目录，如 songs/02-某首歌")
    p_ingest.add_argument(
        "--force", action="store_true", help="覆盖已有的 source.* 与 lyrics.txt"
    )
    p_ingest.add_argument(
        "--url",
        default=None,
        help="视频链接。先把音频（和视频）取回 _in/，再照常整理",
    )
    p_ingest.add_argument(
        "--no-video",
        action="store_true",
        help="配合 --url：只取音频。视频只为 OCR 硬字幕而下，比音频大得多",
    )

    p_transcribe = sub.add_parser(
        "transcribe",
        help="没有歌词时，让它在本机听一遍，写一份 lyrics.draft.txt 草稿给你断句",
    )
    p_transcribe.add_argument(
        "song_dir", type=Path, help="歌曲目录，如 songs/02-某首歌"
    )
    p_transcribe.add_argument(
        "--force", action="store_true", help=f"覆盖已有的 {DRAFT_FILENAME}"
    )
    # 听写这条路原来**根本没有这个开关**，而它里面写死着 `align.LANGUAGE`——
    # 于是一首法语歌走这条路，无论怎么传都会被按中文听，用户没有任何办法。
    p_transcribe.add_argument(
        "--language",
        default=None,
        help="听写的语言（Whisper 语言码，如 zh/fr/en）。不给就自动侦测",
    )

    # 合成器不在这份检出里（公开仓）就不注册这条子命令——注册一条跑不了的
    # 命令，比没有这条命令更糟：`--help` 里写着它、打上去却报错。
    if COMPOSE_AVAILABLE:
        p_compose = sub.add_parser(
            "compose", help="不给音频，摇一个 seed 自己写一首器乐曲"
        )
        p_compose.add_argument("song_dir", type=Path, help="歌曲目录，如 songs/03-无名")
        p_compose.add_argument("--seed", type=int, default=None,
                               help="缺省随机取，但一定打印出来，方便复现")
        p_compose.add_argument("--bpm", type=float, default=None,
                               help=f"缺省 {BPM_RANGE[0]}–{BPM_RANGE[1] - 1} 按 seed 取")
        p_compose.add_argument("--key", default=None, help="音名，如 D；缺省按 seed 取")
        p_compose.add_argument("--scale", default=None,
                               help=f"调式，{' 或 '.join(compose_theory.SCALES)}；"
                                    f"缺省 {DEFAULT_SCALE}")
        p_compose.add_argument("--duration", type=float, default=None,
                               help=f"秒，缺省 {DEFAULT_DURATION:.0f}。段落按整数遍动机"
                                    f"对齐，实际时长会略有出入")
        p_compose.add_argument("--from-score", action="store_true",
                               help="不摇了，读 compose.json 重新合成")

    p_run = sub.add_parser("run", help="分析并打包。每步先看产物在不在，在就跳过")
    p_run.add_argument("song_dir", type=Path, help="歌曲目录，如 songs/02-某首歌")
    p_run.add_argument("--renderer", type=Path, default=default_renderer)
    p_run.add_argument("--title", default=None)
    p_run.add_argument("--word-level", action="store_true", help="启用词级歌词对齐")
    p_run.add_argument(
        "--language",
        default=None,
        help="歌词与人声的语言（Whisper 语言码，如 zh/fr/en）。不给就自动侦测，侦测结果会打在日志里",
    )
    p_run.add_argument("--bitrate", default=DEFAULT_BITRATE)
    p_run.add_argument("--force", action="store_true", help="每一步都重跑")
    p_run.add_argument(
        "--no-lyrics",
        action="store_true",
        help="这首歌本来就没有歌词，做成没有歌词层的版本",
    )

    sub.add_parser("serve", help="起一个只跑在本机的网页壳子，用浏览器做歌")

    args = parser.parse_args()
    if args.command == "compose":
        # 命令行给的是音名（D），往下走的是 pitch class（2）。打错音名要当场
        # 说清可选值——`KEYS[args.key]` 直接甩一个 KeyError 的 traceback，
        # 用户看不出该填什么。
        if args.key is None:
            key = None
        elif args.key in compose_theory.KEYS:
            key = compose_theory.KEYS[args.key]
        else:
            print(
                f"不认识的音名 {args.key!r}。可选："
                f"{'、'.join(compose_theory.KEYS)}",
                file=sys.stderr,
            )
            return 1
        return compose(args.song_dir, args.seed, args.bpm, key,
                       args.scale, args.duration, args.from_score)
    # 更具体的那条分支排在前面。**下面那两行一个字节没动**——`--url` 是加了
    # 一条路，不是改了原来那条。
    if args.command == "ingest" and args.url:
        return ingest_url(args.song_dir, args.url, args.force, not args.no_video)
    if args.command == "ingest":
        return ingest(args.song_dir, args.force)
    if args.command == "transcribe":
        return transcribe(args.song_dir, args.force, args.language)
    if args.command == "run":
        return run(
            args.song_dir, args.renderer, args.title,
            args.word_level, args.bitrate, args.force, args.no_lyrics,
            args.language,
        )
    if args.command == "build":
        return build(
            args.song_dir, args.word_level, args.bitrate, args.no_lyrics, args.language
        )
    if args.command == "pack":
        try:
            out = pack(args.song_dir, args.renderer, args.title)
        except PackError as exc:
            print(f"打包失败：{exc}", file=sys.stderr)
            return 1
        size_mb = out.stat().st_size / 1e6
        print(f"完成：{out}\n  体积 {size_mb:.1f} MB")
        if size_mb > 15:
            print(f"警告：产物 {size_mb:.1f} MB 超过 15 MB 上限", file=sys.stderr)
        return 0
    if args.command == "serve":
        # **惰性 import，别提到顶层。** `murripple/web/` 的立身之本是「不依赖
        # 分析管线」——它跑歌靠 `subprocess` 调 `murripple` 命令，自己只用标准
        # 库。顶层 import 会把方向反过来：`murripple.web.server` 成了本模块
        # （它顶上就 import 着 librosa/demucs 那一串）的依赖，隔离守卫也就名存
        # 实亡了。
        from murripple.web.server import serve as serve_web

        return serve_web()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
