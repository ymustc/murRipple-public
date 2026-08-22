"""本机听写。**机器认字，人断句。**

这一步的产出**不是歌词**，是一份草稿。名字也叫草稿：`lyrics.draft.txt`，
不是 `lyrics.txt`。管线一个字都不读它——`build` 只认 `lyrics.txt`，而那份
文件只能由人自己存出来。**「必须过人的确认」在这里是一条结构事实，不是一句
注释里的承诺。**

## 为什么不让它直接写 lyrics.txt

本仓最贵的那条教训：**歌词的行数决定对齐质量。** `align.py` 是按行把字符流
映射回时间戳的，一份行数不对的 `lyrics.txt` 会让整首歌的每一句都错位，而且
看画面时根本看不出错在哪一步——比没有 `lyrics.txt` 更坏（没有的话管线会大声
说「未找到 lyrics.txt，跳过歌词层」）。

而 Whisper **不产生歌词的断句**。实测（抄件在 `tests/fixtures/whisperx/`）：

| 素材 | `lyrics.txt` | `model.transcribe()` 吐回 |
|---|---|---|
| 私仓 `songs/02`（中文，2026-08-15，抄件已删，见下） | 36 行 | **6 段** |
| `songs/05-trempe-moi`（法语，2026-08-15） | 34 行 | **8 段** |

一段能横跨八九句歌词。它切的是停顿，不是歌词的行。**两首歌同向，但那是两个
实测数，不是「Whisper 一般切几段」的分布**——别拿它去推一般情况。

（中文那一对抄件 2026-08-16 已整份删除：那首歌是**别人的作品**。理由与它带走的
那条守卫写在 `tests/fixtures/whisperx/README.provenance.md` 末尾。上表里 36→6
这个数是当时真跑量到的，留着它是因为**数还在，只是抄件不在了**。）

所以分工是：**机器把「有哪些字」这件苦力做掉，断句留给人。** 这个模块因此
**不替人猜断句**——一段一行，原样交出去。多切一刀都是凭空造出来的行边界，
而造出来的行边界看起来跟真的一模一样，人反而不会去核。

## 听的是整首混音，不是人声轨——**而人声轨确实更好听得出字**

2026-08-15 在同一首歌上跑了两遍（两份抄件都留在 `tests/fixtures/whisperx/` 里，
正是为了让这一节有据可查）：

| | 混音 | Demucs 分出来的人声轨 |
|---|---|---|
| 曲名那一句 | 五个字错了三个（曲名整个听成别的词） | 五个字只错一个 |
| 最后一段 | 只吐回三个字 | 整句十四个字都在 |
| 某一句的动词短语 | 两个字听成同音的别字 | 两个字都对 |

（上表量的是**私仓那首中文歌**（`songs/02`），2026-08-15。**逐字的原文不在
这里，而且现在也不在仓里任何地方**——那首歌是别人的作品，两份抄件 2026-08-16
已删除。这张表留着，因为它记的是一次真跑量到的差距，而那个差距正是下面这个
决定的全部依据；示例歌那一对抄件（`05-*`，法语）在
`tests/fixtures/whisperx/README.provenance.md` 里，认错的地方逐条列着。）

**人声轨明显更准，这一版还是没有用它。** 理由是一个实测出来的挡路石，写在这里
好让下一个人不必重新发现：

- 要拿人声轨就得先跑一次 Demucs（几分钟），而**那几分钟是纯浪费**：
  `murripple build` 判断"要不要起 Demucs"用的是 `stems.find_flat_stems`，它只认
  **扁平**的 `build/stems/*.wav`（那是 `compose` 合成的那一套）；`separate()` 写
  的是嵌套的 `stems/<model>/<源名>/*.wav`，`glob("*.wav")` 一条都扫不到。也就是
  说听写这里分离一遍，`build` 还会**原样再分离一遍**。
  （这不是猜的：`murripple/stems.py` 的 docstring 明写"不能只判断 `build/stems/`
  存不存在"，第一版实现按"分轨不白跑"写，测试当场逮住。）
- 让 `build` 认得嵌套布局，等于改动核心管线"要不要起 Demucs"的判据——那是一条
  会影响四首既有歌的规矩，`stems.py` 那段 docstring 逐字论证过它为什么长这样。
  **不在这一棒里顺手改**，报给管理窗口定夺。

所以这一版：听混音，一次分离都不做。**这不是"混音够好"，是"更好的那条路眼下要
多花一遍 Demucs"。** 上表原样留着，将来真要换，证据在这儿。

**没量过字准率，所以这里、CLI、网页上都不许出现任何准确率数字。** 上表是三处
肉眼可见的差异，不是一个测量。

## 繁简

Whisper 在中文歌上会随段落输出繁体（上表第一行就是），而本仓四首歌的
`lyrics.txt` 都是简体。草稿是给人拿去改成 `lyrics.txt` 的，所以在这里就转成
简体——转换器直接复用 `align.py` 那一个（那边为了字符级比对同样需要它），
不另起一份：两份转换表迟早会漂。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

#: 草稿文件名。**故意不叫 `lyrics.txt`**：管线只认后者，人不动手它就不存在。
DRAFT_FILENAME = "lyrics.draft.txt"


def _align():
    """`murripple.align`，**惰性拿**。

    这里要的是 align 那一组常量（模型尺寸／设备）、**那一处决定语言的函数**
    （`decide_language`）和那一个繁简转换器：
    **复用，不另写一份**——两处各挑各的模型，只会让「听写出来的字」和「对齐时
    听到的字」对不上；两份简繁转换表迟早会漂。模型选 medium 的理由（small 在
    唱歌上错得厉害）写在 `align.py` 里，这边跟着它走。

    **写成惰性，是为了这个模块在 import 阶段只碰标准库。** 网页壳子那一层
    （`murripple/web/app.py`）要拿上面那个 `DRAFT_FILENAME`，而它的立身之本是
    「不依赖分析管线」，`murripple.align` 正在那条守卫点名的名单里。顶层 import
    的话，`import murripple.web.app` 会把 align 一起拉进 `sys.modules`——
    **实测过**：改回顶层 import，
    `tests/test_transcribe.py::test_serving_the_page_still_does_not_drag_the_pipeline_in`
    当场红在 `['murripple.align']` 上。

    代价是两个函数各自在用的时候多一次已缓存的 import。
    """
    from murripple import align

    return align


class TranscriptionUnavailable(RuntimeError):
    """WhisperX 不可用，听不了。消息里必须带上可执行的修复建议。"""


def _load_whisperx():
    """惰性导入 WhisperX。

    两类失败分开说，跟 `align._load_whisperx` 同一个路数（没装 → 去装；装了但
    ABI 坏 → 去查版本，叫他"去安装"只会更迷惑，因为包明明已经装着）。

    **不复用 `align._load_whisperx`**：那边的每一句都以「跳过歌词对齐（管线会
    降级为无歌词）」收尾，而听写这条路**没有降级出口**——用户点这个命令就是为了
    拿到字，降不了级。照抄过来等于给他指一条这里不存在的路。
    """
    try:
        import whisperx
    except ImportError as exc:
        raise TranscriptionUnavailable(
            "WhisperX 未安装，听不了。运行 `uv sync --extra align` 装上，"
            "或者自己写一份 lyrics.txt 放进歌曲目录。"
        ) from exc
    except OSError as exc:
        raise TranscriptionUnavailable(
            f"WhisperX 已安装但无法加载，通常是 torch 与 torchaudio 版本不匹配："
            f"{exc}。运行 `uv sync --extra align` 重装，"
            f"或者自己写一份 lyrics.txt 放进歌曲目录。"
        ) from exc
    return whisperx


def transcribe_audio(
    audio_path: Path,
    *,
    language: str | None = None,
    on_language: Callable[[Any], None] | None = None,
    load: Callable[[], Any] | None = None,
) -> list[dict]:
    """听一遍，返回 `[{"t0":…, "t1":…, "text":…}]`，按时间升序。

    **全部在本机跑**：模型是 `align.py` 用的那一个，`whisperx` 从本地缓存加载，
    这一路一次外部 API 调用都没有。

    **语言问的是 `align.decide_language()`，不自己拿主意。** 这里原来写着
    `language=align.LANGUAGE`——一个写死的常量，于是 `--language` 这条路对听写
    **根本不存在**：一首法语歌走这条路，无论怎么传都会被按中文听。语言这件事
    全仓只许有一处在决定，两条路都去问它。

    **注意这条路喂的是整首混音，不是人声轨**（为什么，见模块 docstring）。
    `pick_windows()` 的「最响」在混音上是「有人在唱」的代理，而代理会失效——
    实测私仓 `songs/03` 的混音**前 30 秒是满编制的器乐前奏**，响度一点都
    不轻（RMS 0.12563，全曲最响窗口 0.29974），单看它认成 `ru`。挡住这一类的
    是投票，不是响度本身。

    `load` 是**测试注入点**，写在调用现场——没有环境变量、没有全局开关。真实
    路径上它是 `None`，走 `_load_whisperx()`。测试拿它喂
    `tests/fixtures/whisperx/` 里那份真跑抄件，所以测试不下载模型、不走网络。
    """
    whisperx = (load or _load_whisperx)()
    align = _align()

    audio = whisperx.load_audio(str(audio_path))
    model = whisperx.load_model(align.MODEL_SIZE, align.DEVICE, compute_type="int8")
    heard = align.decide_language(model, audio, language)
    if on_language is not None:
        on_language(heard)
    result = model.transcribe(audio, language=heard.code)

    segments = []
    for seg in result.get("segments", []):
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        segments.append(
            {
                "t0": float(seg.get("start", 0.0)),
                "t1": float(seg.get("end", 0.0)),
                "text": text,
            }
        )
    segments.sort(key=lambda s: s["t0"])
    return segments


def draft_lines(segments: list[dict]) -> list[str]:
    """段 → 草稿的行。**一段一行，不替人断句。**

    这个函数短得像没干活，而它没干的那件事正是重点：**不按字数切、不按时长切、
    不按标点切**（实测那份抄件里一个标点都没有，想切也无从切起）。多切一刀就是
    造一个机器并不知道的行边界，而造出来的边界跟真的长得一模一样——人会以为
    那是听出来的，于是不去核。行数是这份草稿里**唯一必须由人定**的东西。

    只做两件确定无疑的事：去掉首尾空白（`  spare part ` 那种）、繁转简。
    """
    t2s = _align()._T2S
    lines = []
    for seg in segments:
        text = t2s(str(seg.get("text", ""))).strip()
        if text:
            lines.append(text)
    return lines


def write_draft(segments: list[dict], song_dir: Path) -> Path:
    """草稿落盘。**只写 `lyrics.draft.txt`，绝不碰 `lyrics.txt`。**

    `lyrics.txt` 是于淼的听写成果、是一首歌歌词的真相源；这个模块没有任何一条
    路径写得到它。想让草稿变成歌词，只能由人自己断好句、改好字、存过去。
    """
    path = Path(song_dir) / DRAFT_FILENAME
    path.write_text("\n".join(draft_lines(segments)) + "\n", encoding="utf-8")
    return path


__all__ = [
    "DRAFT_FILENAME",
    "TranscriptionUnavailable",
    "draft_lines",
    "transcribe_audio",
    "write_draft",
]
