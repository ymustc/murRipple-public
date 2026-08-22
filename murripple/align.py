"""歌词强制对齐。

用户提供歌词原文，因此这是"对齐"而非"识别"，精度显著高于纯识别。

关键设计：**不按整句做精确匹配**。Whisper 的分句边界与用户的换行
几乎不可能一致——它会把一行切成两段，也会把相邻两行并成一段，还
可能听错个别字。改为在字符级做序列比对：把词级结果拼成一条归一化
字符流，把用户歌词也拼成一条字符流，用 difflib 求最长公共子序列，
再把每行的字符位置映射回词的时间戳。

默认输出句级：句级差 0.2 秒基本无感，词级差 0.2 秒极其显眼，而歌声
（长音、转音、和声叠唱）的对齐本就比语音困难。词级作为精修手段。
"""

from __future__ import annotations

import difflib
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

DEVICE = "cpu"
# 唱歌比说话难认得多。small 在真实曲目上错得厉害（「陇西」听成「吹息」、
# 「守一纸诺言」听成「手一指抹烟」），导致大量句子对不上。medium 慢
# 三到五倍，但 build 是一次性的、调视觉时不重跑，值这个时间。
MODEL_SIZE = "medium"
#: 「让它自己认」。写成常量而不是裸 `None`，是为了在调用现场读得出意图。
AUTO: str | None = None

#: **默认不写死语言。** 写死 `zh` 曾经让一首法语歌被当中文听——Whisper 会照着
#: 中文音节硬凑出一堆同音字，对齐全线崩；而公开仓面对的是全世界的歌，默认中文
#: 说不过去，也不该逼用户去背 Whisper 的语言码。
#:
#: **但侦测会错，所以这一路上没有一处是沉默的。** 唱歌比说话难认得多（同一个
#: 理由让 `MODEL_SIZE` 选了 medium，见上面那段），认错了不吭声，用户拿到的是
#: 一份垃圾对齐、而且不知道为什么。所以 `decide_language()` 既要认，也要
#: **说出它凭什么**；`--language` 保留，用来推翻它。
#:
#: 这与本仓歌词门那次是同一个判断：**默认走顺手的那条路，但不许沉默降级**
#: （见 `murripple/lyrics_gate.py` 的 docstring）。
LANGUAGE: str | None = AUTO

#: `whisperx.load_audio()` 固定重采样到 16 kHz，下面按样本数切窗口靠这个数。
SAMPLE_RATE = 16000

#: Whisper 认一次语言只看 30 秒（`whisperx/asr.py` 的 `detect_language`：
#: 它把 `audio[:N_SAMPLES]` 送进编码器，N_SAMPLES 就是 30 秒）。这不是我们
#: 挑的参数，是它的性质——下面整套窗口逻辑都是绕着这个 30 秒来的。
WINDOW_SEC = 30

#: 投几个窗口。见 `decide_language` 的 docstring。
VOTE_WINDOWS = 5

#: 低于「最响窗口的这个比例」的窗口一律不参与投票。见 `pick_windows`。
SILENCE_FLOOR = 0.25

# 全曲一个可测字速都没有时的兜底（约合中文演唱的常见语速）。
#
# **只有一个可测速率都没有时才用得上**：真正的速率是 `align_lyrics` 里
# `statistics.median(rates)` 从本曲实测出来的（见那里）。所以换一种语言、
# 换一种字符密度，速率会自己跟上——**这个常量不是多语言的障碍**。
DEFAULT_CHAR_SEC = 0.35


class AlignmentUnavailable(RuntimeError):
    """WhisperX 不可用。消息里必须带上可执行的修复建议。"""


def parse_lyrics(text: str) -> list[str]:
    """按行切分歌词，去掉空行与首尾空白。"""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _make_t2s():
    """繁→简转换器。opencc 属可选的 align extra，装不上就退化为不转换。

    Whisper 在中文歌上会随段落输出繁体——实测转录里有一整段是繁体，
    而歌词是简体。字符级比对里「舊」与「旧」是两个不同的字，那几句必然
    全部落空。（逐字的原文在 `tests/fixtures/whisperx/` 的抄件里；这里
    不引，那几首歌是私产。）
    """
    try:
        import opencc

        return opencc.OpenCC("t2s").convert
    except Exception:  # noqa: BLE001 —— 转换只是增益，缺了不该让管线挂掉
        return lambda s: s


_T2S = _make_t2s()


def _normalize(s: str) -> str:
    """归一化用于匹配：繁转简、去标点与各类空白（含全角空格）、转小写。"""
    return re.sub(r"[\s\W_]+", "", _T2S(s), flags=re.UNICODE).lower()


def _char_stream(units: list[str]) -> tuple[str, list[int]]:
    """把若干文本单元拼成归一化字符流，并记录每个字符属于哪个单元。"""
    chars: list[str] = []
    owners: list[int] = []
    for i, unit in enumerate(units):
        for ch in _normalize(unit):
            chars.append(ch)
            owners.append(i)
    return "".join(chars), owners


def _load_whisperx():
    """惰性导入 WhisperX。

    两类失败要分开说清楚，因为修法完全不同：
      - 没装（ImportError）→ 让用户去装
      - 装了但 ABI 坏（OSError，典型是 torch/torchaudio 版本不配对，
        表现为 dlopen 时 `Symbol not found`）→ 让用户查版本，叫他
        "去安装"只会让他更迷惑，因为包明明已经装着
    两种都必须转成 AlignmentUnavailable，由调用方降级为无歌词继续跑，
    绝不能让整条管线崩在这里（spec 第 15 节）。

    sys.modules 里被置为 None 时 `import` 同样抛 ImportError，因此
    不需要额外判空。
    """
    try:
        import whisperx
    except ImportError as exc:
        raise AlignmentUnavailable(
            "WhisperX 未安装。运行 `uv sync --group dev --extra align` 安装，"
            "或跳过歌词对齐（管线会降级为无歌词）。"
        ) from exc
    except OSError as exc:
        raise AlignmentUnavailable(
            f"WhisperX 已安装但无法加载，通常是 torch 与 torchaudio 版本不匹配："
            f"{exc}。运行 `uv sync --group dev --extra align` 重装，"
            f"或跳过歌词对齐（管线会降级为无歌词）。"
        ) from exc
    return whisperx


# ---------------------------------------------------------------- 这首歌是什么语言


@dataclass(frozen=True)
class Language:
    """这一趟按什么语言听，**以及这个答案凭什么**。

    带着 `votes` 而不是只带一个语言码，是因为判据里最要紧的那条是「拿不准
    的时候不许沉默通过」——而「拿不准」这件事只有把每个窗口各认出什么留下来
    才说得清。调用方据此决定那句话怎么说（见 `murripple/cli.py`）。
    """

    #: Whisper 语言码（`zh` / `fr` / …）。
    code: str
    #: 用户拿 `--language` 指定的（True）还是侦测出来的（False）。
    asked: bool
    #: 侦测时每个窗口各认出了什么，按窗口顺序。指定时为空。
    votes: tuple[str, ...] = ()

    @property
    def agree(self) -> int:
        """有几个窗口认的是 `code`。"""
        return sum(1 for v in self.votes if v == self.code)

    @property
    def unsure(self) -> bool:
        """这个答案站不站得住。**站不住时调用方必须说出来并给出路。**

        指定的永远算数——用户说了就是他说了算，这里没有「我觉得你说错了」
        这种事。侦测的要**过半数**窗口一致才算数：低于半数说明模型在不同
        段落上听出的是不同语言，那不是一个答案，是一堆猜测里最像的一个。

        **这条分支到今天为止没有在任何一首真歌上触发过**（五首歌、两种音源、
        每次都是全票，实测见本轮报告）。也就是说它的正确性只由
        `tests/test_language.py` 里的合成用例担保，不是由真素材担保的。
        """
        if self.asked:
            return False
        return self.agree * 2 <= len(self.votes)


def window_loudness(audio, sample_rate: int = SAMPLE_RATE) -> list[float]:
    """把音频切成 `WINDOW_SEC` 秒一段，逐段算 RMS。

    numpy **在函数体里 import**：这个模块的 import 阶段只碰标准库，
    网页壳子那条「不依赖分析管线」的守卫靠的就是这个前提
    （`tests/test_transcribe.py::test_serving_the_page_still_does_not_drag_the_pipeline_in`）。
    """
    import numpy as np

    a = np.asarray(audio, dtype=np.float32)
    step = WINDOW_SEC * sample_rate
    count = max(1, len(a) // step)
    return [
        float(np.sqrt((a[i * step:(i + 1) * step].astype(np.float64) ** 2).mean()))
        for i in range(count)
    ]


def pick_windows(
    loudness: list[float],
    want: int = VOTE_WINDOWS,
    floor: float = SILENCE_FLOOR,
) -> list[int]:
    """在这些窗口里挑几个去认语言。**按响度挑，不按顺序挑。**

    纯函数，喂一串 RMS、得一串窗口下标（升序）。分成这样是为了让「挑哪几个
    窗口」这个**决定**能脱开 numpy 与模型单独测——守卫在
    `tests/test_language.py`，它拿手写的 RMS 数列就能把下面这个形状钉死。

    ## 为什么不能用开头那 30 秒

    Whisper 只看喂给它的头 30 秒。私仓 `songs/03` 第一句歌词在 **39.50 秒**
    才进来（读自它自己的 `build/timeline.json`），于是：

    | 喂什么 | 认成 |
    |---|---|
    | 人声轨前 30 秒（RMS 0.00094，是次低那首的 1/43） | `en`（0.44） |
    | 混音前 30 秒（RMS 0.12563，**一点都不轻**） | `ru` |
    | 最响的五个窗口投票 | `zh` 5/5 |

    两行失败**不是同一回事**，这一点很要紧：人声轨那次是对着近乎静音硬猜，
    `floor` 挡得住；混音那次前 30 秒是**满编制的器乐前奏**，响度正常，
    `floor` 一点忙都帮不上——挡住它的是「挑最响的几个窗口」这条本身
    （器乐前奏通常不是全曲最响的地方），以及**投票**。

    ## 所以这里做两件事，各挡一种

    1. **`floor`**：低于最响窗口 `floor` 倍的窗口一律不要。挡的是"对着静音硬猜"。
    2. **取最响的 `want` 个**：挡的是"开头恰好没人唱"。

    ## 说清它是个代理指标

    「最响」是「有人在唱」的**代理**，不是它本身——尤其在混音上，最响的窗口
    完全可能是一段器乐高潮。本仓的教训是**代理指标不是证据**，所以这条不靠它
    单独成立：真正兜底的是 `Language.unsure`，投票分裂时会说出来。
    实测到今天为止五首歌两种音源全票通过（见本轮报告），**五首不是一个分布**。
    """
    if not loudness:
        return [0]
    ceiling = max(loudness)
    alive = [i for i, r in enumerate(loudness) if r >= floor * ceiling]
    # `ceiling` 自己一定过得了这道坎，所以 `alive` 不会空——全曲静音时它退化成
    # 「所有窗口都一样响」，照旧往下投票，而不是在这里返回一个空清单让调用方
    # 去猜「没有窗口」是什么意思。
    alive.sort(key=lambda i: loudness[i], reverse=True)
    return sorted(alive[:want])


def decide_language(model, audio, requested: str | None = None) -> Language:
    """**「这首歌是什么语言」全仓只有这一处在决定。**

    `align` 与 `transcribe` 两条路都问它，不各自读常量、更不写在默认参数上——
    默认参数在 `def` 时求值，`language: str = LANGUAGE` 那种写法等于**没有**
    唯一那一处：把 `LANGUAGE` 改掉，`align_lyrics` 那一边纹丝不动。判据要的
    守卫（把唯一那处的答案改掉、看两边跟不跟）因此拿它没辙。
    守卫在 `tests/test_language.py`，路数照 `tests/test_lyrics_gate.py` 那次。

    用户指定了就用他的，一个窗口都不认——那是 `--language` 存在的意义。
    没指定就在 `pick_windows()` 挑出来的窗口上各认一次，**取众数**。

    投票办成两件事，缺一件这个函数就退回成一次猜测：
      · 单个窗口认错（器乐段、和声叠唱、念白）被多数票摊掉；
      · **票型本身就是把握程度**——不必去够 WhisperX 内部那个概率
        （`asr.py` 里 `model.model.detect_language(encoder_output)` 才拿得到），
        也就不必赌它的私有结构不变。
    """
    asked = requested or LANGUAGE
    if asked:
        return Language(code=str(asked), asked=True)

    step = WINDOW_SEC * SAMPLE_RATE
    votes = tuple(
        str(model.detect_language(audio[i * step:]))
        for i in pick_windows(window_loudness(audio))
    )
    # 众数。`Counter.most_common` 在平票时按插入序给第一个，也就是**最响的那个
    # 窗口**认的那一种——平票本来就是 `unsure`，调用方会照实说，这里不假装它
    # 是个有依据的选择。
    code = Counter(votes).most_common(1)[0][0]
    return Language(code=code, asked=False, votes=votes)


def _char_stream_indexed(units: list[str]) -> tuple[str, list[tuple[int, int]]]:
    """字符流 + 每个字符的 (单元下标, 该字符在单元内的序号)。"""
    chars: list[str] = []
    owners: list[tuple[int, int]] = []
    for i, unit in enumerate(units):
        for j, ch in enumerate(_normalize(unit)):
            chars.append(ch)
            owners.append((i, j))
    return "".join(chars), owners


def _match_lines_to_words(
    lines: list[str], words: list[dict]
) -> dict[int, list[tuple[int, int]]]:
    """字符级序列比对。

    返回 {行下标: [(该字在句中的序号, 命中的词下标)]}，按句中序号升序。

    保留"字在句中的序号"是为了在匹配残缺时能反推整句时长——只记录命中
    了哪些词是不够的，见 align_lyrics 里的外推。
    """
    lyric_chars, lyric_owner = _char_stream_indexed(lines)
    word_chars, word_owner = _char_stream([str(w["word"]) for w in words])

    matcher = difflib.SequenceMatcher(
        None, lyric_chars, word_chars, autojunk=False
    )
    hits: dict[int, dict[int, int]] = {}
    for a, b, size in matcher.get_matching_blocks():
        for k in range(size):
            line_i, char_j = lyric_owner[a + k]
            hits.setdefault(line_i, {})[char_j] = word_owner[b + k]
    return {i: sorted(v.items()) for i, v in hits.items()}


def _extrapolate(
    n_chars: int,
    hits: list[tuple[int, int]],
    words: list[dict],
    fallback_rate: float,
) -> tuple[float, float, float | None]:
    """由命中的字反推整句的 (t0, t1)，并返回本句测得的每字时长。

    只取"所有命中词的首尾"在匹配残缺时会给出残缺的窗口——实测 01 里一句
    六个字的歌词只匹配上开头两个字，窗口只有 0.50 秒（每字 0.084s，全曲
    中位数 0.374s），字早早消失而声音还在。

    做法：假设句内字速均匀，用首尾命中字之间的时长除以它们的字距，得到
    每字时长，再按未命中的字数向两端外推。只命中一个字时无从测速，用全
    曲中位数兜底。
    """
    first_j, first_w = hits[0]
    last_j, last_w = hits[-1]
    ts = float(words[first_w]["start"])
    te = float(words[last_w]["end"])

    span = last_j - first_j
    measured = (te - ts) / span if span > 0 else None
    rate = measured if measured else fallback_rate

    t0 = ts - first_j * rate
    t1 = te + (n_chars - 1 - last_j) * rate

    # 外推要封顶。匹配得越差外推越靠猜，没有上限时会被撑到离谱——实测
    # 01 里一句八个字的句读句被推到 11 秒并倒插回上一句里。以锚点为中心
    # 收缩到合理时长即可。
    max_dur = n_chars * rate * MAX_EXTRAPOLATION
    if t1 - t0 > max_dur:
        center = (ts + te) / 2
        t0 = center - max_dur / 2
        t1 = center + max_dur / 2
    return t0, t1, measured


def _char_times(text: str, t0: float, t1: float) -> list[dict]:
    """把一行的字符线性铺在 [t0, t1] 上。

    这是词级的近似实现：真正逐字精确到每个音符需要更强的对齐器，
    而词级本就是按需开启的精修手段，线性分布已足够做卡拉OK高亮。
    """
    chars = [c for c in text if _normalize(c)]
    if not chars:
        return []
    step = (t1 - t0) / len(chars)
    return [
        {"t0": t0 + i * step, "t1": t0 + (i + 1) * step, "c": c}
        for i, c in enumerate(chars)
    ]


MIN_LINE_SEC = 0.35

# 外推后的时长相对「字数 × 字速」的上限倍数。
MAX_EXTRAPOLATION = 1.6


def _enforce_monotonic(lines: list[dict]) -> None:
    """就地消除重叠：重叠区取中点分界，两句各让一半。

    早先的做法是"把后一句起点推到前一句终点"。在引入外推之前那样够用，
    之后就不行了——外推会把句子向两端撑开，相邻句重叠变多，前一句会
    把后一句整个吞掉。实测 01 里相邻的两句因此变成 0.00 秒，比不外推还糟。

    取中点是因为重叠本身说明两句的估计都不确定，没有理由让先来的全赢。
    """
    def clamp_nonneg():
        for line in lines:
            if line["t1"] < line["t0"]:
                line["t1"] = line["t0"]

    # 一：先保证每句自身非负，后面几步都假定这一点
    clamp_nonneg()

    # 二：重叠取中点分界
    for prev, cur in zip(lines, lines[1:]):
        if cur["t0"] < prev["t1"]:
            mid = (prev["t1"] + cur["t0"]) / 2
            prev["t1"] = mid
            cur["t0"] = mid
    clamp_nonneg()

    # 三：太短的补到最短时长，但不越过下一句起点
    for i, line in enumerate(lines):
        limit = lines[i + 1]["t0"] if i + 1 < len(lines) else float("inf")
        want = max(line["t1"], line["t0"] + MIN_LINE_SEC)
        line["t1"] = max(line["t0"], min(want, limit))

    # 四：最后一遍强制不重叠。
    #
    # 这一步不能省。前三步是"尽量公平"的启发式，各自都可能在连环重叠时
    # 留下残余违例——实测补到这一步之前仍有 1 处。不变式必须由一个无条件
    # 的收尾保证，而不是指望前面几步恰好都对。
    for prev, cur in zip(lines, lines[1:]):
        if cur["t0"] < prev["t1"]:
            cur["t0"] = prev["t1"]
        if cur["t1"] < cur["t0"]:
            cur["t1"] = cur["t0"]


def align_lyrics(
    vocals_path: Path,
    lyrics_text: str,
    word_level: bool = False,
    language: str | None = AUTO,
    *,
    on_language=None,
) -> tuple[list[dict], list[str]]:
    """把歌词原文对齐到人声轨。

    返回 (歌词行, 未对上的原文行)。未对上的行由调用方报告给用户，
    供其在 overrides.json 中手工补时间。

    `language` 不给就是 `AUTO`：交给 `decide_language()`，全仓唯一那一处。

    `on_language` 是**这一趟听出来的语言的出口**，收到一个 `Language`。
    调用方拿它去打主日志、去写进 timeline 的 meta（`murripple/cli.py`）。

    **为什么是回调而不是把返回值改成三元组**：`align_lyrics` 的
    `lines, unmatched = …` 解包在 `tests/` 里有十几处，为了多带一个字段去动
    那些既有测试，代价与收益不成比例；而语言是**这一趟的旁注**，不是对齐结果
    的第三个组成部分。不给回调就是没人听，不影响任何行为。
    """
    whisperx = _load_whisperx()
    expected = parse_lyrics(lyrics_text)
    if not expected:
        return [], []

    audio = whisperx.load_audio(str(vocals_path))
    model = whisperx.load_model(MODEL_SIZE, DEVICE, compute_type="int8")
    heard = decide_language(model, audio, language)
    if on_language is not None:
        on_language(heard)
    result = model.transcribe(audio, language=heard.code)

    align_model, meta = whisperx.load_align_model(
        language_code=result.get("language", heard.code), device=DEVICE
    )
    aligned = whisperx.align(
        result["segments"], align_model, meta, audio, DEVICE
    )

    words = [
        w
        for seg in aligned.get("segments", [])
        for w in seg.get("words", [])
        if w.get("start") is not None and w.get("end") is not None
    ]
    words.sort(key=lambda w: float(w["start"]))
    if not words:
        return [], list(expected)

    hits = _match_lines_to_words(expected, words)

    # 两遍：先测出各句的每字时长，取中位数作为兜底，再据此外推。
    # 只命中一个字的句子无从自测字速，只能借全曲的。
    rates: list[float] = []
    for i, text in enumerate(expected):
        h = hits.get(i)
        if not h:
            continue
        _, _, measured = _extrapolate(len(_normalize(text)), h, words, 0.0)
        if measured:
            rates.append(measured)
    fallback_rate = statistics.median(rates) if rates else DEFAULT_CHAR_SEC

    lines: list[dict] = []
    unmatched: list[str] = []
    for i, text in enumerate(expected):
        h = hits.get(i)
        if not h:
            unmatched.append(text)
            continue
        t0, t1, _ = _extrapolate(
            len(_normalize(text)), h, words, fallback_rate
        )
        lines.append({"t0": t0, "t1": t1, "text": text, "words": None})

    # 不按 t0 重排。LCS 保证匹配锚点本身单调递增，歌词顺序是权威的；
    # 外推只影响两端的估计，一旦某句被外推得比下一句起点还晚，重排就会
    # 把歌词顺序打乱——实测 01 的第 4 句被排到了第 5 句后面。
    _enforce_monotonic(lines)

    if word_level:
        for line in lines:
            line["words"] = _char_times(line["text"], line["t0"], line["t1"])

    return lines, unmatched
