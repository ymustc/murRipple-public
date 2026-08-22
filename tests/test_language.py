"""多语言：「这首歌是什么语言」只许有一处在决定，而且它不许沉默。

## 这一份守的是什么

**不是「侦测准不准」。** 那要真跑 medium 模型，而测试不下载模型、不走网络；
准不准是**量**出来的，量法与结果在这一棒的报告里（五首真歌 × 人声轨/混音两种
音源，`model.detect_language()` 各一趟）。**本文件里一个准确率数字都没有**，
也没有任何一条断言立在"它认得准"上——本仓被真实结果推翻过两次，代理指标不是
证据。

守的是三件可判定的事：

1. **只有一处在决定**（`align.decide_language`），`align_lyrics` 与
   `transcribe_audio` 两边都去问它。判别法照 `tests/test_lyrics_gate.py` 那次：
   **把唯一那一处的答案改掉，看两边跟不跟**——不是数源码里出现了几次。
2. **不在"没人在唱"的窗口上做决定**。这一条钉的是私仓 `songs/03` 那个
   形状，但**钉的是形状不是那一首**：任何"前奏长于侦测窗口"的歌都该被它接住。
3. **拿不准时说出来、并给出一条走得通的路**，而且那句话**到得了主日志**——
   折进详细区就等于没说。

## 03 那件事的原始数据（这一份的由来）

`detect_language` 只看喂给它的头 30 秒（`whisperx/asr.py`）。03 第一句歌词在
**39.50 秒**才进来（读自它自己的 `build/timeline.json`）：

| 喂什么 | 认成 |
|---|---|
| 人声轨前 30 秒（RMS 0.00094，是次低那首的 1/43） | `en` |
| 混音前 30 秒（RMS 0.12563，**响度正常的器乐前奏**） | `ru` |
| 最响的五个窗口投票 | `zh`，五票全中 |

**两行失败不是同一回事**，下面 `pick_windows` 那组测试因此分成两组：静音那种
靠 `SILENCE_FLOOR` 挡，器乐前奏那种响度正常、只能靠"挑最响的几个"加投票挡。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

# 同目录的测试模块：pytest 的 prepend 导入模式把 `tests/` 放进了 `sys.path`。
# **故意 import 而不是各写一份替身**——替身只许有一份，两份迟早会漂。
import test_align as align_tests
import test_cli as cli_tests
import test_transcribe as transcribe_tests

from murripple import align, cli
from murripple.ingest.transcribe import transcribe_audio
from murripple.schema import validate_timeline
from murripple.timeline import build_timeline
from murripple.web import progress

REPO_ROOT = Path(__file__).resolve().parents[1]
STEP = align.WINDOW_SEC * align.SAMPLE_RATE


def audio_of(levels: list[float]) -> np.ndarray:
    """一段合成波形：每个元素一个 30 秒窗口，值就是那一窗的振幅（也就是 RMS）。

    常数振幅，所以 RMS 恰好等于振幅——测试里想让第几窗多响就写多少，
    不必再算一遍。
    """
    return np.concatenate(
        [np.full(STEP, lvl, dtype=np.float32) for lvl in levels]
    )


class FakeModel:
    """按"这一窗有多响"决定认出什么——**这正是真实失败的形状**。

    真模型在近乎静音、或满编制的器乐段上会给出一个跟人声无关的语言码
    （实测 03：人声轨静音段 → `en`，混音器乐前奏 → `ru`）。这个替身把那件事
    做成确定的：安静的窗口一律回 `quiet`，够响的回 `loud`。

    **不模拟"响度以外的东西"**：多给一样，被测的那条决定就有可能被替身兜住。
    """

    def __init__(self, quiet: str = "en", loud: str = "zh", cutoff: float = 0.01):
        self.quiet, self.loud, self.cutoff = quiet, loud, cutoff
        self.seen: list[float] = []

    def detect_language(self, audio) -> str:
        head = np.asarray(audio[:STEP], dtype=np.float64)
        rms = float(np.sqrt((head**2).mean())) if head.size else 0.0
        self.seen.append(rms)
        return self.loud if rms >= self.cutoff else self.quiet


# ==========================================================================
# 一、只有一处在决定，两边都去问它
# ==========================================================================


def test_默认不再写死中文():
    """写死 `zh` 曾经让一首法语歌被当中文听。公开仓面对的是全世界的歌。"""
    assert align.LANGUAGE is align.AUTO
    assert align.AUTO is None


def test_对齐那条路问的是唯一那一处(monkeypatch, tmp_path):
    """★ 判据 5 的守卫（对齐这一边）。

    判别法**不是数源码里有几个 `LANGUAGE`**，而是让唯一那一处永远回同一个
    答案，看 `align_lyrics` 认不认。跟不动就说明它自己还留着一份判断——
    而这正是它上一版的毛病：`language: str = LANGUAGE` 写在**默认参数**上，
    默认参数在 `def` 时求值，改掉 `LANGUAGE` 它纹丝不动。
    """
    align_tests._install_fake_whisperx(
        monkeypatch, [align_tests._seg(1.0, 2.0, [("春", 1.0, 1.5), ("风", 1.5, 2.0)])]
    )
    monkeypatch.setattr(
        align, "decide_language",
        lambda model, audio, requested=None: align.Language("xx", asked=True),
    )
    seen = []
    align.align_lyrics(
        tmp_path / "vocals.wav", "春风", on_language=seen.append
    )
    assert [h.code for h in seen] == ["xx"], (
        "改了唯一那一处的答案，对齐没跟着改——它自己还留着一份判断"
    )


def test_听写那条路问的也是同一处(monkeypatch):
    """★ 判据 5 的守卫（听写这一边）。

    这一边原来**根本没在问**：`transcribe.py` 里写死着 `language=align.LANGUAGE`，
    于是 `--language` 对听写等于不存在——一首法语歌走这条路，无论怎么传都会被
    按中文听。
    """
    fake = transcribe_tests.FakeWhisperX(transcribe_tests.raw(transcribe_tests.MIX_FIXTURE))
    monkeypatch.setattr(
        align, "decide_language",
        lambda model, audio, requested=None: align.Language("xx", asked=True),
    )
    transcribe_audio(Path("x.wav"), load=lambda: fake)
    assert ("transcribe", "xx") in fake.calls, (
        f"改了唯一那一处的答案，听写没跟着改：{fake.calls}"
    )


def test_指定的语言一路传得到唯一那一处(monkeypatch):
    """`--language` 得真的走到决定那一处手里，不是半路被谁吃掉。"""
    fake = transcribe_tests.FakeWhisperX(transcribe_tests.raw(transcribe_tests.MIX_FIXTURE))
    asked = []
    real = align.decide_language
    monkeypatch.setattr(
        align, "decide_language",
        lambda model, audio, requested=None: asked.append(requested) or real(
            model, audio, requested
        ),
    )
    transcribe_audio(Path("x.wav"), language="fr", load=lambda: fake)
    assert asked == ["fr"], asked
    assert ("transcribe", "fr") in fake.calls, fake.calls


# ==========================================================================
# 二、挑窗口：不在"没人在唱"的地方做决定
# ==========================================================================


@pytest.mark.parametrize("quiet_windows", [1, 2, 3])
def test_静音的前奏不许参与投票(quiet_windows):
    """★ 判据 3：钉的是**形状**，不是私仓 `songs/03` 那一首。

    前奏几窗静音都一样：只要它明显比唱起来之后轻，就不该有票。写成参数化
    正是为了这句话——一首前奏两分钟的歌跟 03 是同一类，这里也接得住。
    """
    loudness = [0.0009] * quiet_windows + [0.05, 0.06, 0.055, 0.048]
    picked = align.pick_windows(loudness)
    assert all(i >= quiet_windows for i in picked), (
        f"静音的前 {quiet_windows} 窗被选进来投票了：{picked}"
    )


def test_挑的是最响的那几个而不是最靠前的那几个():
    """器乐前奏那种**响度正常**的失败，`SILENCE_FLOOR` 一点忙都帮不上。

    实测 03 的混音前 30 秒 RMS 0.12563，全曲最响窗口 0.29974——远在任何合理
    的静音线之上。挡住它的是"按响度排序取前几个"这条本身。
    """
    loudness = [0.13, 0.10, 0.30, 0.28, 0.26, 0.24, 0.22]
    assert align.pick_windows(loudness, want=3) == [2, 3, 4]


def test_全曲一样响时一个都不排除():
    """没有可依据的差异时不许自作主张——照旧全都拿去投票。"""
    assert align.pick_windows([0.2] * 4, want=10) == [0, 1, 2, 3]


def test_窗口不够也给得出答案():
    """短过一个窗口的音频只有一窗，照样得有个下标可投，不能返回空清单。

    返回空的话调用方要去猜"没有窗口"是什么意思，而那是一条没人测的分支。
    """
    assert align.pick_windows([0.3]) == [0]
    assert align.pick_windows([]) == [0]


def test_全曲静音也不许静默地什么都不做():
    """整首都近乎无声时，`floor` 是相对最响窗口算的，所以谁都不会被排除。

    这条钉的是"退化输入不产生空清单"：真到了这一步，答案会由下面的
    `unsure` 去说它站不住，而不是在这里悄悄消失。
    """
    assert align.pick_windows([0.0, 0.0, 0.0]) == [0, 1, 2]


def test_前奏长于侦测窗口时不许被前奏定调():
    """★ 判据 1 + 3 的**端到端**那一半。

    上面那几条测的是"挑哪几个窗口"这个纯函数；这一条把模型接上，走完整条
    `decide_language`。两层都要有：只测纯函数的话，谁把 `pick_windows` 的结果
    忘了用、直接把整条音频丢给模型，上面全绿而这里红。
    """
    # 前两窗静音（前奏 60 秒），后面五窗有人在唱。
    audio = audio_of([0.0, 0.0, 0.05, 0.06, 0.05, 0.055, 0.05])
    model = FakeModel(quiet="en", loud="zh")

    heard = align.decide_language(model, audio)

    assert heard.code == "zh", (
        f"被静音的前奏定了调：认成 {heard.code}，各窗 RMS={model.seen}"
    )
    assert heard.unsure is False
    assert "en" not in heard.votes, f"静音窗口拿到票了：{heard.votes}"


class SequenceModel:
    """按调用次序把预置的答案一个个交出去。用来造「窗口之间不一致」。"""

    def __init__(self, answers: list[str]):
        self.answers = list(answers)
        self.calls = 0

    def detect_language(self, audio) -> str:
        self.calls += 1
        return self.answers[min(self.calls - 1, len(self.answers) - 1)]


def test_单个窗口认错会被多数票摊掉():
    """★ **这一条是变异检验逼出来的**（2026-08-15）。

    把 `decide_language` 改成只认第一个窗口（`pick_windows(...)[:1]`），
    上面那 40 条**一条都不红**——因为别的用例里每个窗口给的都是同一个答案，
    只认一个也照样对。

    而"只认一个"会**悄悄拆掉整张安全网**：一票必然全票，`unsure` 从此永远
    是 False，判据 2 那条「拿不准要说出来」再也不会触发，而且没有任何东西
    会红。这正是本仓最怕的那种失败——降级了，但没人知道。

    所以这里把「真的问了不止一个窗口，而且少数服从多数」钉死：第一个窗口
    认错，答案仍然得是多数那个。
    """
    audio = audio_of([0.05] * 5)
    model = SequenceModel(["ru", "zh", "zh", "zh", "zh"])

    heard = align.decide_language(model, audio)

    assert model.calls == 5, f"没有真的逐窗去认，只问了 {model.calls} 次"
    assert heard.code == "zh", f"被单个认错的窗口带偏了：{heard.votes}"
    assert heard.votes == ("ru", "zh", "zh", "zh", "zh")
    assert heard.unsure is False


def test_指定了语言就一个窗口都不认(monkeypatch):
    """`--language` 存在的意义就是推翻侦测。指定了还去认，等于没推翻。"""
    model = FakeModel()
    heard = align.decide_language(model, audio_of([0.05] * 4), requested="fr")

    assert heard.code == "fr"
    assert heard.asked is True
    assert heard.unsure is False
    assert model.seen == [], f"指定了语言还是跑了侦测：{model.seen}"


# ==========================================================================
# 三、拿不准的时候不许沉默通过
# ==========================================================================


def test_全票就是站得住():
    heard = align.Language("zh", asked=False, votes=("zh",) * 5)
    assert heard.agree == 5
    assert heard.unsure is False


@pytest.mark.parametrize(
    "votes",
    [
        ("zh", "zh", "en", "en", "fr"),   # 众数只占五分之二
        ("zh", "en"),                      # 平票
        ("zh", "en", "fr", "de"),          # 四窗四种，谁也说了不算
    ],
)
def test_票型分裂就是拿不准(votes):
    """★ 判据 2：过不了半数就不是一个答案，是一堆猜测里最像的一个。

    这条分支**到今天为止没有在任何一首真歌上触发过**（五首歌、两种音源、
    每次都是全票）。也就是说它的正确性只由这里的合成用例担保，不是由真素材
    担保的——这一点写在 `Language.unsure` 的 docstring 里，别把它读成
    "已经在真歌上验过了"。
    """
    heard = align.Language(votes[0], asked=False, votes=votes)
    assert heard.unsure is True, f"{votes} 竟然算站得住"


def test_用户指定的永远算数():
    """指定的不许被判成"拿不准"——那是用户说了算的事，这里没有"我觉得你说错了"。"""
    assert align.Language("fr", asked=True).unsure is False


# ==========================================================================
# 四、那几句话：说得出来，而且到得了主日志
# ==========================================================================

#: `progress._OURS` 里为语言加的那两条，每条配一个**照着 `cli.py` 抄的**样例行。
#: 跟 `test_transcribe.TRANSCRIBE_SHAPES` 同一个路数：白名单最容易烂在
#: 「我照着印象编了一个样例，白名单认得它，而真实那句话其实多了个字」。
LANGUAGE_SHAPES = [
    (
        'return f"  语言：{heard.code}（--language 指定）"',
        "  语言：fr（--language 指定）",
    ),
    (
        'f"  语言：{heard.code}（自动侦测，{heard.agree}/{total} 个片段一致；"',
        "  语言：zh（自动侦测，5/5 个片段一致；认错的话加 --language 指定）",
    ),
    (
        'f"  认错的话整首歌的歌词都会错位。指定语言重跑：\\n"',
        "  认错的话整首歌的歌词都会错位。指定语言重跑：",
    ),
    (
        'f"  uv run murripple build {song_dir} --language {heard.code}"',
        "  uv run murripple build /x/歌 --language zh",
    ),
]

CLI_SOURCE = (REPO_ROOT / "murripple" / "cli.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("source_fragment,sample", LANGUAGE_SHAPES)
def test_每个样例都是_cli_真会打的那一句(source_fragment, sample):
    """样例行照着源码抄，不照着印象编。措辞改了这里要红。"""
    assert source_fragment in CLI_SOURCE, (
        f"源码里已经没有 {source_fragment!r} 了——样例停在旧版本上。"
    )


@pytest.mark.parametrize("source_fragment,sample", LANGUAGE_SHAPES)
def test_每一句都到得了主日志(source_fragment, sample):
    """**折进详细区就等于没说。**

    「详细输出」在页面上默认是折叠的。侦测认错时整首歌的歌词都会错位，而画面
    上只是"歌词不对"——看不出错在语言这一步。这几句话是唯一说得出这件事的
    地方，它们必须在用户一眼就看得见的那一块里。
    """
    assert progress.classify(sample) == progress.MAIN, (
        f"{sample!r} 是我们自己打的（源码：{source_fragment}），却归了详细区"
    )


def test_指定的不许说成是侦测出来的():
    """两者的可信度完全不同，说反了就是在骗人。"""
    line = cli._language_lines(align.Language("fr", asked=True), Path("/x/歌"))
    assert "指定" in line and "自动侦测" not in line, line


def test_站得住的时候也要顺带给出推翻它的办法():
    """全票不等于对。**认错时用户唯一的线索就是这句话里那个语言码。**"""
    line = cli._language_lines(
        align.Language("zh", asked=False, votes=("zh",) * 5), Path("/x/歌")
    )
    assert "zh" in line and "5/5" in line
    assert "--language" in line, f"没给推翻它的办法：{line}"


def test_拿不准那句话把票型摊开并给出一条能敲的命令():
    """★ 判据 2 的后半句：**说出来，还要给出路。**

    只说"拿不准"而不给下一步，等于告诉用户坏消息又不给他办法。命令里点名
    的是**这个歌曲目录**——网页那条路上用户手里只有这一个东西。
    """
    line = cli._language_lines(
        align.Language("zh", asked=False, votes=("zh", "zh", "en", "en", "fr")),
        Path("/x/歌"),
    )
    assert "拿不准" in line, line
    # 票型要摊开：三种各几票都得写出来，否则"拿不准"是一句没有依据的话。
    for piece in ("zh×2", "en×2", "fr×1"):
        assert piece in line, f"票型里缺 {piece}：{line}"
    assert "uv run murripple build /x/歌 --language" in line, line


def test_那条命令里的_flag_真的存在(monkeypatch, tmp_path):
    """★ **当场敲一遍。** 本仓往台账里写过一个不存在的 `--force`，下一任照抄了。

    上面那条测试断言我们会打印 `uv run murripple build … --language …`。
    **打印一条不存在的命令，比不打印更坏**——用户照着敲，撞一脸 argparse 报错，
    然后不再相信这里说的任何一句话。所以这里把真的解析器要来走一遍。

    不跑 `build` 本身（那要 Demucs）：把它换成记账的替身，只看 argparse 认不认
    这个 flag、以及解析出来的值有没有走到它手里。
    """
    seen: list = []
    monkeypatch.setattr(
        cli, "build",
        lambda song_dir, word_level, bitrate, no_lyrics=False, language=None: (
            seen.append(language) or 0
        ),
    )
    monkeypatch.setattr(
        sys, "argv",
        ["murripple", "build", str(tmp_path), "--language", "fr"],
    )
    assert cli.main() == 0
    assert seen == ["fr"], seen


def test_不给_language_也解析得动(monkeypatch, tmp_path):
    """默认那条路：不给就是 `None`，交给侦测。"""
    seen: list = []
    monkeypatch.setattr(
        cli, "build",
        lambda song_dir, word_level, bitrate, no_lyrics=False, language=None: (
            seen.append(language) or 0
        ),
    )
    monkeypatch.setattr(sys, "argv", ["murripple", "build", str(tmp_path)])
    assert cli.main() == 0
    assert seen == [None], seen


# ==========================================================================
# 五、记进 timeline 的 meta，让它可复核
# ==========================================================================


def test_听过之后语言进_meta(click_track_120bpm, sr):
    doc = build_timeline(
        title="demo",
        stem_audio={k: click_track_120bpm for k in ("vocals", "drums", "bass", "other")},
        sr=sr,
        lyrics=[{"t0": 1.0, "t1": 2.0, "text": "une ligne", "words": None}],
        bitrate_label="aac-64k",
        language="fr",
    )
    assert doc["meta"]["language"] == "fr"
    validate_timeline(doc)


def test_没听过就不写这一格(click_track_120bpm, sr):
    """★ 硬字幕、`--no-lyrics`、器乐曲都没跑过 WhisperX。

    往这儿补一个"大概是 zh"正是这一棒禁止的沉默地猜——**缺席本身是一句实话**：
    这首歌的语言没有人问过。所以它是可选字段，而不是带默认值的必填字段。
    """
    doc = build_timeline(
        title="demo",
        stem_audio={k: click_track_120bpm for k in ("vocals", "drums", "bass", "other")},
        sr=sr,
        lyrics=[],
        bitrate_label="aac-64k",
    )
    assert "language" not in doc["meta"], doc["meta"]
    validate_timeline(doc)


#: `test_cli` 的两件家伙什，**import 过来用，不复制一份**：一个造歌曲目录，
#: 一个挡掉 Demucs 与 ffmpeg（`build()` 自身的控制流全部走真代码）。
song_dir = cli_tests.song_dir


def test_build_真的把听到的语言接到了_timeline_上(monkeypatch, song_dir, sr):
    """★ **这一条也是变异检验逼出来的**（2026-08-15）。

    把 `cli.build` 里那句 `language=heard[0].code if heard else None` 改成写死
    `language=None`，上面那 40 多条**一条都不红**：
    `test_听过之后语言进_meta` 测的是 `build_timeline` 这个**零件**，
    而 `cli.build` 里那根**接线**没有任何东西在守——既有的几条 build 测试都
    走 WhisperX 缺席那一支，`heard` 本来就是空的，接不接都一样。

    零件对、接线断，是本仓反复栽过的形状（`transcribe` 那个子命令、页面上
    `render()` 里那半句，都是同一族）。所以这里走一趟**真的 `cli.build`**，
    只把对齐那一处换成会回报语言的替身，然后去盘上把 timeline.json 读出来。
    """
    cli_tests._stub_heavy_deps(monkeypatch, song_dir, sr)
    (song_dir / "lyrics.txt").write_text("une ligne\n", encoding="utf-8")

    def aligned(vocals, text, word_level=False, language=None, *, on_language=None):
        on_language(align.Language("fr", asked=False, votes=("fr",) * 5))
        return [{"t0": 1.0, "t1": 2.0, "text": "une ligne", "words": None}], []

    monkeypatch.setattr(cli, "align_lyrics", aligned)

    assert cli.build(song_dir, word_level=False, bitrate="64k") == 0
    doc = json.loads((song_dir / "build" / "timeline.json").read_text("utf-8"))
    assert doc["meta"]["language"] == "fr", (
        f"听出来的语言没接到 timeline 上：{doc['meta']}"
    )
    validate_timeline(doc)


def test_没听过的那几条路_meta_里就不该有这一格(monkeypatch, song_dir, sr, capsys):
    """WhisperX 缺席时降级为无歌词——那一趟**一个字都没听过**。

    这时 meta 里补一个语言码就是凭空捏造。跟上一条成对：一条守"听了要记"，
    一条守"没听不许编"。
    """
    cli_tests._stub_heavy_deps(monkeypatch, song_dir, sr)
    (song_dir / "lyrics.txt").write_text("第一句\n", encoding="utf-8")

    def unavailable(*a, **k):
        raise align.AlignmentUnavailable("WhisperX 未安装。运行 `uv sync --extra align`")

    monkeypatch.setattr(cli, "align_lyrics", unavailable)

    assert cli.build(song_dir, word_level=False, bitrate="64k") == 0
    doc = json.loads((song_dir / "build" / "timeline.json").read_text("utf-8"))
    assert "language" not in doc["meta"], doc["meta"]


# `test_四首真歌那份没有这一格也照样合法`（要读仓内私仓 `songs/01` 的 `build/`）
# 已于 2026-08-15 搬到 `tests/test_language_real_songs.py`——公开仓不带那四首歌，
# 不拆的话这一整份 29 条会被「读仓内 songs/ 的测试不进公开树」整份排掉。
# 断言逐字未改。


# ==========================================================================
# 六、听写那条子命令
# ==========================================================================


def test_听写子命令认得_language_并且真的传下去(tmp_path, monkeypatch):
    """`murripple transcribe <目录> --language fr` 真的接到了那一路上。

    只测函数的话，argparse 那一段少一行、这条路根本不存在，测试照样全绿。
    """
    song = tmp_path / "05-没有歌词的歌"
    song.mkdir()
    (song / "source.mp3").write_bytes(b"audio")

    got: list = []

    def stub(audio_path, **kw):
        got.append(kw.get("language"))
        on = kw.get("on_language")
        if on is not None:
            on(align.Language("fr", asked=True))
        return [{"t0": 0.0, "t1": 1.0, "text": "une ligne"}]

    monkeypatch.setattr(cli, "transcribe_audio", stub)
    monkeypatch.setattr(
        sys, "argv", ["murripple", "transcribe", str(song), "--language", "fr"]
    )
    assert cli.main() == 0
    assert got == ["fr"], got


def test_听写也会把语言说出来(tmp_path, monkeypatch, capsys):
    """听写那条路同样不许沉默——它跟对齐用的是同一句话。"""
    song = tmp_path / "05-没有歌词的歌"
    song.mkdir()
    (song / "source.mp3").write_bytes(b"audio")

    def stub(audio_path, **kw):
        kw["on_language"](align.Language("fr", asked=False, votes=("fr",) * 5))
        return [{"t0": 0.0, "t1": 1.0, "text": "une ligne"}]

    monkeypatch.setattr(cli, "transcribe_audio", stub)
    assert cli.transcribe(song) == 0
    out = capsys.readouterr().out
    assert "  语言：fr" in out, out
    for forbidden in ("%", "％", "准确率", "字准", "正确率"):
        assert forbidden not in out, (
            f"输出里出现了 {forbidden!r}——本仓没有人量过侦测的准确率。"
        )
