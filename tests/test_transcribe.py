"""听写：机器认字，人断句。

## 这一份守的是什么

**不是"听得准不准"**——本仓没有人量过字准率，也就没有任何一条断言可以立在那上面
（代理指标不是证据，这个仓已经被真实结果推翻过两次）。这一份守的是**诚实**与
**复用**这两件可判定的事：

1. 草稿**落不到 `lyrics.txt` 上**。管线一个字都不读它，人不动手它就不存在。
2. 草稿**不替人断句**——一段一行，多切一刀都是造出来的行边界。
3. 「这是机器听的、字会错、行数几乎肯定不对」这几句**真的到得了用户眼前**
   （CLI 的主日志、网页的校对框），而且**一个准确率数字都没有**。
4. 网页上停下来核那一下，走的是**视频那条路已经有的那个校对框**，不是另起一套。

## 真跑抄件

`tests/fixtures/whisperx/` 下那两份是 2026-08-15 一次真跑 WhisperX 的逐字节抄录
（出处、环境、重抄步骤全在同目录的 `README.provenance.md` 里）。**本文件不手编
任何一份 WhisperX 输出**：手编的话，没有人会想到「34 行的歌只切回 8 段」，也没有
人会想到同一份抄件里把曲名听成三种不同的拼法——而那两样正是这个功能的全部难点。

**2026-08-16 换过一次素材。** 原来用的是 `02-*` 那一对抄件，而那首歌是**别人的
作品**（于淼 2026-08-16 说明），抄件里逐字装着它的歌词。现在用的是示例歌
`05-trempe-moi`（于淼自己的歌）的那一对。**换掉了什么、没换掉什么，逐条写在
`tests/fixtures/whisperx/README.provenance.md` 的末尾**——最要紧的一条：
繁简那条守卫是中文特有的，法语抄件替代不了，它现在只剩自造语料那个双胞胎。

测试因此**不下载模型、不走网络**：`transcribe_audio(…, load=…)` 是写在调用现场的
注入点，喂进去的就是那份抄件。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

# 同目录的测试模块：pytest 的 prepend 导入模式把 `tests/` 放进了 `sys.path`。
# **故意 import 而不是复制**——替身 CLI 与替身 DOM 各只许有一份。
import test_web_e2e as e2e_tests
import test_web_page as page_tests

from murripple import cli
from murripple.align import _T2S
from murripple.ingest import transcribe as transcribe_mod
from murripple.ingest.transcribe import (
    DRAFT_FILENAME,
    TranscriptionUnavailable,
    draft_lines,
    transcribe_audio,
    write_draft,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
WHISPER_DIR = TESTS_DIR / "fixtures" / "whisperx"
VOCALS_FIXTURE = WHISPER_DIR / "05-vocals.transcribe.json"
MIX_FIXTURE = WHISPER_DIR / "05-source-mix.transcribe.json"



def raw(fixture: Path) -> dict:
    return json.loads(fixture.read_text(encoding="utf-8"))


class FakeWhisperX:
    """替身 whisperx 模块。**只重放抄件，不做任何决定。**

    刻意做得很笨：`load_model` 把自己交回去。多给一样（比如自己按标点切一刀），
    `transcribe_audio` 那一层的行为就有可能被替身兜住而不被测。

    **2026-08-15 改了两处，都是「替身跟上真实现」**：

    · `load_audio` 原来把**路径字符串**原样交回去。真 `whisperx.load_audio`
      交回的是一条 16 kHz 的 float32 波形，而 `align.decide_language()` 现在
      要按 30 秒切窗口、逐窗口算 RMS——喂给它一个字符串会当场 ValueError。
      替身在那一点上说的是假话，现在改成交回一条真的（很短的）波形，路径仍然
      记进 `calls`，断言拿得到。
    · 多了 `detect_language`：真 pipeline 有这个方法，`decide_language` 会在
      挑出来的窗口上逐个调它。少给这一样，替身就在替真实现兜一件它其实要做
      的事。（守卫见 tests/test_language.py）
    """

    def __init__(self, doc: dict, language: str = "zh"):
        self.doc = doc
        self.language = language
        self.calls: list[tuple] = []

    def load_audio(self, path):
        self.calls.append(("load_audio", str(path)))
        # 一秒静音就够：窗口切分与 RMS 都算得下去，而这个替身不做任何
        # 依赖波形内容的判断（语言由下面的 detect_language 直接给）。
        return [0.0] * 16000

    def load_model(self, size, device, compute_type):
        self.calls.append(("load_model", size, device, compute_type))
        return self

    def detect_language(self, audio):
        self.calls.append(("detect_language", len(audio)))
        return self.language

    def transcribe(self, audio, language):
        self.calls.append(("transcribe", language))
        return self.doc


def replay(fixture: Path = MIX_FIXTURE):
    """`transcribe_audio(…, load=replay())` —— 喂真跑抄件，不碰网络。

    默认用**混音**那一份：真实路径上听的就是 `source.*`（为什么不是人声轨，见
    `murripple/ingest/transcribe.py` 的 docstring）。

    语言**从抄件自己的 `language` 字段取**，不写死。2026-08-16 换素材时改的：
    写死 `"zh"` 而喂一份法语抄件，替身就在这一点上说假话，而没有任何东西会红。
    """
    doc = raw(fixture)
    fake = FakeWhisperX(doc, language=doc.get("language", "zh"))
    return lambda: fake


# ==========================================================================
# 一、抄件本身：这个功能的全部前提都在这两份文件里
# ==========================================================================


def test_the_fixture_is_a_real_capture_with_its_provenance_written_down():
    """抄件旁边必须有出处，而且出处里得说清怎么重抄一份。

    一份没有出处的"真跑抄件"跟一份手编的理想输出，在仓里长得一模一样。
    """
    sidecar = (WHISPER_DIR / "README.provenance.md").read_text(encoding="utf-8")
    for needed in ("05-vocals.transcribe.json", "05-source-mix.transcribe.json"):
        assert needed in sidecar, f"出处里没提 {needed}，那份抄件等于没有来历。"
    assert "uv run python" in sidecar, "出处里没有可执行的重抄步骤。"
    assert "没有量" in sidecar or "没量过" in sidecar, (
        "出处里没有照实说「字准率没有人量过」——那正是这份抄件最容易被拿去乱推的地方。"
    )


# `test_whisper_does_not_hand_back_lyric_lines`（要读仓内那首歌的 `lyrics.txt`）
# 已于 2026-08-15 搬到 `tests/test_transcribe_real_lyrics.py`——公开仓不带素材，
# 不拆的话整份文件都进不去。断言逐字未改（2026-08-16 只把素材从 02 换成了 05）。


def test_the_punctuation_in_the_transcript_never_becomes_a_line_break():
    """★ 抄件里**有**标点，而草稿仍然一段一行——「按标点断句」那条路走不通。

    这一条是**为了挡住一次未来的好心改动**：看见 8 行长句，下一个人很容易想到
    「按逗号句号切开就好了」。

    **2026-08-16 换素材时，这条从「查缺席」变成了「查在场」，而且真的变强了。**
    原来用的是中文抄件，那一份里一个标点都没有（Whisper 在中文歌上不打标点），
    所以原断言是「抄件里一个标点都没有」——那是一条**关于夹具的**断言，
    实现按标点切一刀在那份夹具上根本切不动，一条也不会红。
    法语抄件里逗号、句号、撇号一大把，于是同一个念头在这里**有东西可切**，
    而这条断言直接钉在**输出**上：段数几个，草稿就几行。

    变异检验（2026-08-16 实跑，M-punct）：给 `draft_lines` 加一句按 `,` `.` 再切
    一刀——**同一个变异，两份夹具下的结果是**：

    | 抄件 | 段数 | 变异下的草稿行数 | 这条会不会红 |
    |---|---|---|---|
    | 旧的中文那一份（`02-*`，已删） | 6 | **6** | **不会** |
    | 现在这份法语的（`05-source-mix`） | 8 | **25** | 会 |

    中文 Whisper 不打标点，所以那个坏实现在旧夹具上根本切不动，**一条都不红**。
    """
    segments = raw(MIX_FIXTURE)["segments"]
    text = "".join(seg["text"] for seg in segments)
    punct = [ch for ch in ",.!?;，。！？；、" if ch in text]
    assert punct, (
        f"抄件里一个标点都没有——这条测试此刻什么也切不动，它变回了永真：{text!r}"
    )
    lines = draft_lines(transcribe_audio(Path("x.wav"), load=replay()))
    assert len(lines) == len(segments), (
        f"抄件 {len(segments)} 段、里面有 {punct} 这些标点，草稿却是 {len(lines)} 行"
        "——这一层自己按标点又切了一刀，而那是机器并不知道的行边界。"
    )


# ==========================================================================
# 二、听写这一层：诚实是一条结构事实，不是一句注释
# ==========================================================================


def test_the_draft_is_one_line_per_segment_and_nothing_is_invented():
    """一段一行。**不替人断句**——多切一刀就是造一个机器并不知道的行边界。"""
    segments = transcribe_audio(Path("不存在.wav"), load=replay())
    lines = draft_lines(segments)
    assert len(lines) == len(raw(MIX_FIXTURE)["segments"]), (
        f"抄件 {len(raw(MIX_FIXTURE)['segments'])} 段，草稿 {len(lines)} 行——"
        "对不上就说明这一层自己动手切了（或并了）行。"
    )
    # **不写死那一句**：抄件的内容是于淼那首歌的词，不进公开仓
    # （守卫见 tests/test_no_private_lyrics.py）。判据从抄件自己推出来——
    # 与写死一模一样强，而且抄件换一份时它跟着换，不会指着一句不存在的话。
    head = _T2S(raw(MIX_FIXTURE)["segments"][0]["text"]).strip()
    assert lines[0] == head, (lines[0], head)


# ==========================================================================
# ★ 2026-08-16 删掉的一条，与它留下的洞
# ==========================================================================
#
# `test_the_draft_comes_back_simplified`（参数化两份真跑抄件）**没了**。
#
# 它证的是：**真模型真的会在中文歌上吐繁体**，而草稿必须转回简体再交给人。
# 那件事只有一份**中文的真跑抄件**证得了，而唯一存在过的那一对（`02-*`）抄的是
# **别人的作品**，2026-08-16 已按于淼的判据整份删除。
#
# **接不了。照实写在这里：**
#
# · 现存那一对法语抄件（`05-*`）里没有一个繁体字，参数化换过去只会得到一条
#   前提永远塌着的测试——「抄件第 N 段不再是繁体了」当场红。
# · 私仓里没有第二首**于淼自己的中文歌**可以真跑重抄：01/02/04 是朋友与师姐的
#   作品，03 是已发行录音，05 是法语。`murripple compose` 摇得出曲子，摇不出人声。
#   所以这不是「这一棒没空做」，是**素材层面做不到**。
# · 顶上来的只有半条：`test_the_draft_comes_back_simplified_on_synthetic_input`
#   （下面那一条）。它证「转换本身对」——简体那一列是**手写金样本**，
#   opencc 整个换掉也逃不掉；但它证不了「真模型真的会吐繁体」，因为喂进去的
#   繁体是我们自己写的。
#
# 也就是说：`DECISIONS.md` 2026-08-15 记的那条「公开仓只带得走后一条」，
# 2026-08-16 起**对私仓也成立了**。这是这次清理付出的最大一笔代价。


#: 自造语料里那首繁体的歌，连同它逐句的简体形态。
#: **简体那一列是手写的金样本，不是拿 opencc 算出来的**——算出来的话这条
#: 断言就成了「opencc 等于 opencc」，转换器整个换掉也不会红。
SYNTHETIC_TRADITIONAL = [
    ("舊城殘卷　字跡發燙", "旧城残卷　字迹发烫"),
    ("誰替鐵門　換了顏色", "谁替铁门　换了颜色"),
    ("說謊的人　學會了咳嗽", "说谎的人　学会了咳嗽"),
    ("把發黃的信　摺成一隻船", "把发黄的信　折成一只船"),
    ("這條巷子　沒有第二個出口", "这条巷子　没有第二个出口"),
    ("舊城殘卷　風把它翻到最後一頁", "旧城残卷　风把它翻到最后一页"),
    ("沒有人認領這串鑰匙", "没有人认领这串钥匙"),
]


def test_the_draft_comes_back_simplified_on_synthetic_input():
    """★ 上面那条的**自造语料双胞胎**。

    上面那条的被测数据是两份真跑抄件，而抄件里是于淼那首歌的词——它们不进
    公开仓（`tests/test_no_private_lyrics.py` 把它们整份豁免了，公开树那边
    由生成器摘掉）。摘掉之后「草稿要转成简体」这条性质在公开仓里就没人守了。

    这一条补那个洞：喂进去的是自造语料里那首繁体的歌，**逐句比对手写的简体
    金样本**。它证不了「真模型真的会吐繁体」——那件事只有抄件证得了，所以
    两条并存、各管一段。
    """
    # `opencc` 在可选的 `align` extra 里。缺了它转换不发生，这条必然红——
    # 而原来的报错只说「舊 != 旧」，一个字都没提缺的是什么。
    #
    # **不跳过。** 本仓已经立过这个判断：`tests/test_synthetic_lyric_corpus.py`
    # 明写「『装不上所以没验』跟『验过了没问题』不许长得一样」，并且它自己在缺
    # extra 时也照样红。2026-08-21 我先改成了 `importorskip`，被那条守卫当场
    # 顶回来——它是对的。所以这里只做一件事：**把红说清楚**，不把红变没。
    try:
        import opencc  # noqa: F401
    except ModuleNotFoundError:
        pytest.fail(
            "繁简转换要 opencc，它在可选的 align extra 里，此刻没装——"
            "所以下面的比对必然落空。这条红是真的少验了，不是代码坏了。"
            "补：uv sync --group dev --extra align"
        )

    fake = FakeWhisperX(
        {"segments": [
            {"text": trad, "start": float(i), "end": float(i) + 1.0}
            for i, (trad, _) in enumerate(SYNTHETIC_TRADITIONAL)
        ]}
    )
    lines = draft_lines(transcribe_audio(Path("x.wav"), load=lambda: fake))
    assert lines == [simp for _, simp in SYNTHETIC_TRADITIONAL]


def test_the_synthetic_traditional_sample_is_actually_traditional():
    """前提：上面那份样本真的是繁体，而且两列真的不一样。

    少了这一条，有人把 `SYNTHETIC_TRADITIONAL` 两列改成一模一样的简体，
    上面那条照样全绿——而它此刻测的是「不转换也对」。
    """
    corpus = json.loads(
        (REPO_ROOT / "renderer" / "test" / "fixtures" / "synthetic-lyric-rows.json")
        .read_text(encoding="utf-8")
    )["songs"]["丁-舊城殘卷"]
    in_corpus = {entry["text"] for entry in corpus}
    for trad, simp in SYNTHETIC_TRADITIONAL:
        assert trad != simp, f"{trad!r} 两列一样，这条样本没有繁体可转"
        assert trad in in_corpus, (
            f"{trad!r} 不在自造语料里——样本要从那一份来，别在这里另开一批"
        )


def test_blank_segments_are_dropped_instead_of_becoming_blank_lines():
    """空段不许变成空行：`lyrics.txt` 是按行配对的，多一个空行就整体错位。"""
    fake = FakeWhisperX(
        {"segments": [
            {"text": "  ", "start": 0.0, "end": 1.0},
            {"text": " 有字 ", "start": 1.0, "end": 2.0},
        ]}
    )
    lines = draft_lines(transcribe_audio(Path("x.wav"), load=lambda: fake))
    assert lines == ["有字"], lines


def test_segments_come_back_in_time_order():
    fake = FakeWhisperX(
        {"segments": [
            {"text": "后", "start": 9.0, "end": 10.0},
            {"text": "先", "start": 1.0, "end": 2.0},
        ]}
    )
    assert [s["text"] for s in transcribe_audio(Path("x.wav"), load=lambda: fake)] == [
        "先",
        "后",
    ]


def test_nothing_in_this_layer_can_write_lyrics_txt(tmp_path):
    """**草稿落不到 `lyrics.txt` 上。**

    `lyrics.txt` 是这首歌歌词的真相源（多半是人自己听写、校对过的）。这一层
    没有任何一条路径写得到它——写进去一个字节，「必须过人的确认」就只剩一句
    注释里的承诺了。
    """
    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text("人自己写的那一份\n", encoding="utf-8")
    before = lyrics.read_bytes()

    segments = transcribe_audio(Path("x.wav"), load=replay())
    path = write_draft(segments, tmp_path)

    assert path.name == DRAFT_FILENAME
    assert path.name != "lyrics.txt"
    assert lyrics.read_bytes() == before, "听写把 lyrics.txt 改了。"


def test_the_draft_file_is_only_the_words(tmp_path):
    """草稿里**只有听出来的字**，没有表头、没有注释。

    加一行「# 这是机器听写的」看着更诚实，实际更危险：用户把这份文件改个名
    存成 `lyrics.txt` 的时候，那一行会变成歌词的第一句，而且下游一个字都不会说。
    说明的落点是 CLI 的输出与页面上的提醒，不是这个文件本身。
    """
    write_draft(transcribe_audio(Path("x.wav"), load=replay()), tmp_path)
    text = (tmp_path / DRAFT_FILENAME).read_text(encoding="utf-8")
    assert not text.startswith("#")
    assert "机器" not in text and "草稿" not in text
    assert text.endswith("\n")


def test_the_model_is_the_same_one_alignment_uses():
    """听写与对齐用同一个模型。

    两处各挑各的，"听写出来的字"和"对齐时听到的字"就会对不上——而对齐正是拿
    前者去做的。
    """
    from murripple import align

    fake = FakeWhisperX(raw(MIX_FIXTURE))
    transcribe_audio(Path("x.wav"), load=lambda: fake)
    assert ("load_model", align.MODEL_SIZE, align.DEVICE, "int8") in fake.calls, (
        f"听写用的不是 align 那一组常量：{fake.calls}"
    )
    # 语言**不再是一个常量**了：它由 `align.decide_language()` 决定，这里断的是
    # 「听写把那一处给的答案原样用上了」。原来这一行断的是
    # `("transcribe", "x.wav", align.LANGUAGE)`——那时 `transcribe.py` 里写死着
    # `language=align.LANGUAGE`，而那正是这一棒要拆掉的东西。
    # 「只有一处在决定、两边都跟」的守卫在 tests/test_language.py。
    assert ("transcribe", fake.language) in fake.calls, fake.calls
    assert any(c[0] == "detect_language" for c in fake.calls), (
        f"听写没有问过语言，直接就听了：{fake.calls}"
    )


def test_a_missing_whisperx_says_how_to_fix_it_and_never_mentions_a_fallback(
    monkeypatch,
):
    """没装 WhisperX 要说清怎么装。

    **且不许说「会降级为无歌词」**——那是 `align.py` 那边的出路，听写这条路没有
    降级出口（用户点这个命令就是为了拿到字）。照抄过去等于给他指一条不存在的路。
    """
    monkeypatch.setitem(sys.modules, "whisperx", None)
    with pytest.raises(TranscriptionUnavailable) as exc:
        transcribe_audio(Path("x.wav"))
    assert "uv sync --extra align" in str(exc.value)
    assert "降级" not in str(exc.value), str(exc.value)


def test_the_listening_never_opens_a_socket(monkeypatch, tmp_path):
    """**零外部 API。** 整条路上一次网络连接都没有。

    把 `socket.socket` 换成一个一构造就炸的东西，再跑一遍完整的听写＋落盘。
    真有人往这一层塞一个联网的转写服务，这里当场红。
    """
    import socket

    class NoNetwork(socket.socket):
        def __init__(self, *a, **kw):
            raise AssertionError("听写这一层开了一个 socket——本仓的 ML 全部跑在本机。")

    monkeypatch.setattr(socket, "socket", NoNetwork)
    write_draft(transcribe_audio(Path("x.wav"), load=replay()), tmp_path)
    assert (tmp_path / DRAFT_FILENAME).exists()


# ==========================================================================
# 三、CLI：`murripple transcribe`
# ==========================================================================


@pytest.fixture
def stub_transcribe(monkeypatch):
    """把真跑要几分钟的那一处 I/O 换掉，只看编排。

    换掉的**只有模型推理**：换进去的替身仍然调真的 `transcribe_audio`，只是把
    whisperx 换成重放抄件的替身——所以段落归一化、繁简、丢空段那几步走的都是
    真代码。跟 `test_ingest_cli.stub_ingest` 同路数。
    """
    calls: list[tuple] = []

    def transcribe_audio_stub(audio_path, **kw):
        calls.append(("transcribe", Path(audio_path).name))
        return transcribe_audio(audio_path, load=replay())

    monkeypatch.setattr(cli, "transcribe_audio", transcribe_audio_stub)
    return calls


def song_with_source(tmp_path, name: str = "source.mp3") -> Path:
    song = tmp_path / "05-没有歌词的歌"
    song.mkdir(parents=True)
    (song / name).write_bytes(b"audio")
    return song


def test_transcribe_writes_a_draft_and_never_lyrics_txt(tmp_path, stub_transcribe):
    song = song_with_source(tmp_path)
    assert cli.transcribe(song) == 0
    assert (song / DRAFT_FILENAME).exists()
    assert not (song / "lyrics.txt").exists(), (
        "听写把 lyrics.txt 写出来了——那样 `run` 立刻就能拿它去做歌，"
        "而没有任何人看过它一眼。"
    )


def test_the_pipeline_does_not_read_the_draft(tmp_path, stub_transcribe, capsys):
    """**只有草稿在盘上时，`run` 仍然说「没有 lyrics.txt」。**

    这一条是「必须过人的确认」的结构证据：草稿改不了任何下游行为，人不把它存成
    `lyrics.txt`，管线就当没有歌词。
    """
    song = song_with_source(tmp_path, "source.wav")
    assert cli.transcribe(song) == 0
    capsys.readouterr()

    code = cli.run(song, REPO_ROOT / "renderer", None, False, "128k", False)
    out = capsys.readouterr()
    assert code == 1
    assert "下没有 lyrics.txt" in out.err, out.err
    assert "murripple transcribe" in out.err, (
        "缺歌词时没说出听写这条路——用户走到这一步正是最需要它的时候。"
    )


def test_transcribe_says_what_the_draft_is_and_gives_no_accuracy_number(
    tmp_path, stub_transcribe, capsys
):
    """三句话一句都不能少，**一个准确率数字都不许有**。

    用户拿到手要知道自己在校对什么。三条各挡一种误解：
    以为字是准的 / 以为断句是歌词的行 / 以为行数不对无所谓。
    """
    song = song_with_source(tmp_path)
    cli.transcribe(song)
    out = capsys.readouterr().out

    assert "草稿" in out and "不是歌词" in out
    assert "字会认错" in out, "没说字会错——用户会以为这是准的。"
    assert "断句是按停顿切的" in out, "没说断句不是歌词的行。"
    assert "比没有歌词更坏" in out, "没说行数不对的代价。"
    assert str(song / "lyrics.txt") in out, "没说清改好了要存到哪儿去。"

    for forbidden in ("%", "％", "准确率", "字准", "正确率"):
        assert forbidden not in out, (
            f"输出里出现了 {forbidden!r}——本仓没有人量过听写的准确率，"
            "任何一个这样的数字都是编的。"
        )


def test_transcribe_refuses_to_touch_a_song_that_already_has_lyrics(
    tmp_path, stub_transcribe, capsys
):
    """`lyrics.txt` 在就什么都不做，**连模型都不加载**。"""
    song = song_with_source(tmp_path)
    (song / "lyrics.txt").write_text("于淼自己听写的\n", encoding="utf-8")
    before = (song / "lyrics.txt").read_bytes()

    assert cli.transcribe(song) == 0
    out = capsys.readouterr().out

    assert (song / "lyrics.txt").read_bytes() == before
    assert not (song / DRAFT_FILENAME).exists()
    assert stub_transcribe == [], f"歌词已经在了，却还是跑了一遍：{stub_transcribe}"
    assert "跳过" in out


def test_the_draft_is_not_redone_unless_forced(tmp_path, stub_transcribe, capsys):
    """断点续跑：听写要几分钟，二次点开始不该从头再来。`--force` 是那条出路。"""
    song = song_with_source(tmp_path)
    cli.transcribe(song)
    first = list(stub_transcribe)
    (song / DRAFT_FILENAME).write_text("我自己改过的草稿\n", encoding="utf-8")

    assert cli.transcribe(song) == 0
    assert stub_transcribe == first, "草稿已经在了，却又听了一遍。"
    assert (song / DRAFT_FILENAME).read_text(encoding="utf-8") == "我自己改过的草稿\n"

    capsys.readouterr()
    assert cli.transcribe(song, force=True) == 0
    assert len(stub_transcribe) > len(first), "--force 没有让它重听。"
    assert (song / DRAFT_FILENAME).read_text(encoding="utf-8") != "我自己改过的草稿\n"


def test_transcribe_listens_to_the_source_and_separates_nothing(
    tmp_path, monkeypatch, stub_transcribe
):
    """听的是 `source.*` 整首混音，**一次 Demucs 都不起**。

    人声轨确实听得更准（两份真跑抄件就在 `tests/fixtures/whisperx/`），但
    `build` 判断"要不要起 Demucs"看的是**扁平**布局、而 `separate()` 写的是嵌套
    布局——在这儿分离一遍，`build` 还会原样再分离一遍，那几分钟是纯浪费。理由
    与证据写在 `murripple/ingest/transcribe.py` 的 docstring 里。

    这条断言钉的是**代价**那一半：谁把人声轨接回来，得连着这个决定一起改。
    """
    def never(*a, **kw):
        raise AssertionError(
            "听写起了一次 Demucs——那几分钟 `build` 还会再花一遍，是纯浪费。"
        )

    monkeypatch.setattr(cli, "separate", never)
    song = song_with_source(tmp_path)
    assert cli.transcribe(song) == 0
    assert ("transcribe", "source.mp3") in stub_transcribe, stub_transcribe
    assert not (song / "build").exists(), (
        "听写留下了一个 build/ 目录——它一条分轨都没产出，那个目录只会误导下一步。"
    )


def test_transcribe_reports_an_unusable_whisperx_without_a_traceback(
    tmp_path, monkeypatch, capsys, stub_transcribe
):
    def boom(audio_path, **kw):
        raise TranscriptionUnavailable("WhisperX 未安装，听不了。运行 `uv sync --extra align`")

    monkeypatch.setattr(cli, "transcribe_audio", boom)
    song = song_with_source(tmp_path)
    assert cli.transcribe(song) == 1
    err = capsys.readouterr().err
    assert err.startswith("听不了："), err
    assert "Traceback" not in err


def test_transcribe_says_so_when_it_heard_nothing(
    tmp_path, monkeypatch, capsys, stub_transcribe
):
    monkeypatch.setattr(cli, "transcribe_audio", lambda *a, **k: [])
    song = song_with_source(tmp_path)
    assert cli.transcribe(song) == 1
    assert "一个字都没听出来" in capsys.readouterr().err
    assert not (song / DRAFT_FILENAME).exists()


def test_the_subcommand_is_reachable_from_the_command_line(
    tmp_path, monkeypatch, stub_transcribe
):
    """`murripple transcribe <目录>` 真的接到了上面那个函数上。

    只测函数的话，argparse 那一段少一行、整条命令根本不存在，测试照样全绿。
    """
    song = song_with_source(tmp_path)
    monkeypatch.setattr(sys, "argv", ["murripple", "transcribe", str(song)])
    assert cli.main() == 0
    assert (song / DRAFT_FILENAME).exists()


def test_the_dead_end_now_points_at_the_way_out(tmp_path):
    """`_in/` 里只有音频、没有歌词时，`scan` 那句话要说得出下一步。

    这句话原先写的是「不做语音转录」——现在做了，留着它就是仓自己在骗人。
    """
    from murripple.ingest.scan import scan

    in_dir = tmp_path / "_in"
    in_dir.mkdir()
    (in_dir / "song.mp3").write_bytes(b"x")
    notes = scan(in_dir).notes
    assert any("murripple transcribe" in n for n in notes), notes
    assert any("草稿" in n for n in notes), (
        f"提到了 transcribe 却没说它给的是草稿——那会让人以为它直接产出歌词：{notes}"
    )


# ==========================================================================
# 四、这几句话到得了网页用户眼前吗
# ==========================================================================

#: `progress._OURS` 里为听写加的那几条，每条配一个**照着 `cli.py` 抄的**样例行。
#: 跟 `test_web_progress.OUR_SHAPES` 同一个路数：白名单最容易烂在「我照着印象编了
#: 一个样例，白名单认得它，而真实那句话其实多了个字」。
TRANSCRIBE_SHAPES = [
    (
        'f"  · 字会认错——它听的是唱腔，不是说话。这份草稿一个字都没有人核过。\\n"',
        "  · 字会认错——它听的是唱腔，不是说话。这份草稿一个字都没有人核过。",
    ),
    (
        'f"  打开 {draft_path} 自己断句、改字，存成 {song_dir / \'lyrics.txt\'}，再跑：\\n"',
        "  打开 /x/lyrics.draft.txt 自己断句、改字，存成 /x/lyrics.txt，再跑：",
    ),
    (
        'print(f"听不了：{exc}", file=sys.stderr)',
        "听不了：WhisperX 未安装，听不了。运行 `uv sync --extra align`",
    ),
    (
        'print("      一个字都没听出来，请自己写 lyrics.txt", file=sys.stderr)',
        "      一个字都没听出来，请自己写 lyrics.txt",
    ),
    (
        'f"  实在没有歌词可抄，`murripple transcribe {song_dir}` 会在本机听一遍，"',
        "  实在没有歌词可抄，`murripple transcribe /x/歌` 会在本机听一遍，"
        "给你一份要你自己断句、改字的草稿（它不会写 lyrics.txt）。",
    ),
]

#: 这几句话住在哪几个文件里。**不是只读 `cli.py`**：2026-08-15 合并时，
#: 「实在没有歌词可抄」那一句从 `cli.run` 的旧门后面搬进了
#: `murripple/lyrics_gate.py`（那道门当天早些时候收成了全仓唯一一处）。
#: 只读 `cli.py` 的话这条钉子会红在一个**搬家**上，而不是红在措辞漂了上。
CLI_SOURCE = "\n".join(
    (REPO_ROOT / "murripple" / name).read_text(encoding="utf-8")
    for name in ("cli.py", "lyrics_gate.py")
)


@pytest.mark.parametrize("source_fragment,sample", TRANSCRIBE_SHAPES)
def test_each_new_shape_is_one_the_cli_really_prints(source_fragment, sample):
    """样例行照着源码抄，不照着印象编。措辞改了这里要红。"""
    assert source_fragment in CLI_SOURCE, (
        f"源码里已经没有 {source_fragment!r} 了——白名单的这一条停在旧版本上。"
    )


@pytest.mark.parametrize("source_fragment,sample", TRANSCRIBE_SHAPES)
def test_every_word_about_the_draft_reaches_the_main_log(source_fragment, sample):
    """**这几句折进详细区就等于没说。**

    这个功能的全部安全性建立在「用户知道自己在校对什么」上，而「详细输出」是
    默认折叠的。
    """
    from murripple.web import progress

    assert progress.classify(sample) == progress.MAIN, (
        f"{sample!r} 是我们自己打的（源码：{source_fragment}），却归了详细区"
    )


def test_the_progress_lines_of_the_transcribe_flow_are_ours():
    from murripple.web import progress

    for line in (
        "[1/2] 分离音源：source.mp3",
        "[2/2] 听写    ← vocals.wav（模型跑在本机，要一会儿）",
        "      → lyrics.draft.txt（6 行）",
    ):
        assert progress.classify(line) == progress.MAIN, f"{line!r} 没归主日志"


def test_the_transcribe_stage_is_one_the_shell_can_ask_for():
    """`transcribe` 是网页起得动的一档，而且拼出来的命令就是那条子命令。"""
    from murripple.web import runner

    assert runner.STAGE_TRANSCRIBE in runner.STAGES
    argv = runner.command_for(
        runner.STAGE_TRANSCRIBE, Path("/x/歌"), command=("murripple",)
    )
    assert argv == ("murripple", "transcribe", "/x/歌")


def test_the_lyrics_gate_does_not_block_the_transcribe_stage(tmp_path):
    """歌词门只拦 `run`。拿歌词去拦听写是自相矛盾——那一档存在的理由就是没有歌词。"""
    from murripple.web import runner

    song = tmp_path / "歌"
    song.mkdir()
    assert runner.lyrics_missing(song)
    gated = runner.start(song, runner.STAGE_RUN, command=("true",))
    assert gated.snapshot().status == runner.NEEDS_LYRICS

    run = runner.start(song, runner.STAGE_TRANSCRIBE, command=("true",))
    assert run.snapshot().status != runner.NEEDS_LYRICS


def test_the_draft_is_what_comes_back_for_checking(tmp_path):
    """听写跑完那一刻，交回页面的是**草稿**，不是 `lyrics.txt`。"""
    from murripple.web import app, jobs, runner

    song = tmp_path / "歌"
    song.mkdir()
    (song / DRAFT_FILENAME).write_text("机器听出来的一大段\n", encoding="utf-8")

    entry = app.Entry(
        job=jobs.Job(song_dir=song, route=jobs.ROUTE_RUN, media_path=None,
                     lyrics_path=None),
        title="歌",
        run=runner.Run(
            runner.RunState(stage=runner.STAGE_TRANSCRIBE, status=runner.DONE)
        ),
        stage=runner.STAGE_TRANSCRIBE,
    )
    payload = app.state_payload("j1", entry)
    assert payload["lyrics"] == "机器听出来的一大段\n"

    # 还在跑的时候不许交——用户可能正在框里打字，交回去会把他的输入盖掉。
    running = app.Entry(
        job=entry.job,
        title="歌",
        run=runner.Run(
            runner.RunState(stage=runner.STAGE_TRANSCRIBE, status=runner.RUNNING)
        ),
        stage=runner.STAGE_TRANSCRIBE,
    )
    assert app.state_payload("j2", running)["lyrics"] is None


def test_serving_the_page_still_does_not_drag_the_pipeline_in():
    """`murripple/web/` 只用标准库这条规矩，到今天为止仍然成立。

    `app.py` 为了拿 `DRAFT_FILENAME` 破了一次「不 import 管线」的例（理由写在
    那个模块的 docstring 里），而那一例安全的**前提**是上游几个模块在 import
    阶段只碰标准库。这里把那个前提变成一条会红的断言：谁往 `align.py` 或
    `transcribe.py` 顶上加一句 `import numpy`，网页壳子当场背上整条分析链。
    """
    #: 点名不许出现的东西。**两类都要断**：
    #: · 管线模块——`murripple.align` 是这一棒真正的风险点（听写那一层复用它的
    #:   模型常量与繁简转换器），所以它必须在名单里。第一版这里只断了重家伙，
    #:   而 `align.py` 顶层只 import 标准库，于是"壳子把管线拉进来了"这件事
    #:   **不会有任何东西变红**——它是靠 `transcribe.py` 里那个惰性 `_align()`
    #:   挡住的，而挡它的东西得有人守。
    #: · 管线拖着的重家伙。
    #: 名单里每一条都对着一个真实存在的东西，否则就是一条永真的断言。
    banned = (
        "murripple.align", "murripple.analyze", "murripple.separate",
        "murripple.pack", "murripple.timeline", "murripple.cli",
        "numpy", "librosa", "torch", "demucs", "whisperx", "scipy",
    )
    for name in banned:
        if name.startswith("murripple."):
            path = REPO_ROOT / "murripple" / (name.split(".", 1)[1] + ".py")
            assert path.exists(), (
                f"{name} 对不上任何文件（{path} 不存在）——名单里躺着一个不存在的"
                "模块名，就等于躺着一条永真的断言。"
            )

    probe = (
        "import sys, json, murripple.web.app;"
        f"print(json.dumps([m for m in {banned!r} if m in sys.modules]))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=120,
    )
    assert out.returncode == 0, out.stderr
    pulled = json.loads(out.stdout)
    assert pulled == [], (
        f"import murripple.web.app 把 {pulled} 一起拉起来了——"
        "网页那一层的立身之本是不依赖分析管线。"
    )

    # **探针没哑**：这一句必须在里面，否则上面那圈是对着一个空 `sys.modules`
    # 在断言（import 写错名字、模块被删掉，都会得到"什么都没拉进来"）。
    sanity = subprocess.run(
        [sys.executable, "-c",
         "import sys, murripple.web.app;"
         "print('murripple.web.app' in sys.modules and"
         " 'murripple.ingest.transcribe' in sys.modules)"],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=120,
    )
    assert sanity.stdout.strip() == "True", (
        f"探针没真的 import 到那两个模块，上面那圈什么也没在守：{sanity.stdout!r}"
    )


# ==========================================================================
# 五、页面上那几个纯函数
# ==========================================================================


def test_the_box_is_the_only_thing_that_lets_audio_through_without_lyrics(tmp_path):
    """裁定 D 那道门还在，只是多了一个**用户自己按下去的**出口。

    四个格子一起断，缺一个都能被蒙混过去：没勾要拦、勾了放行、视频那条路不受
    影响（勾不勾都放行）、什么都没选照旧拦。
    """
    out = page_tests._run_page_js(
        tmp_path,
        """
        console.log(JSON.stringify({
          audioBlankUnchecked: blockedReason("run", "  \\n ", "", true, false),
          audioBlankChecked: blockedReason("run", "  \\n ", "", true, true),
          videoChecked: blockedReason("ingest", "", "", true, true),
          nothingPicked: blockedReason(null, "", "", false, true),
        }));
        """,
    )
    got = json.loads(out)
    assert got["audioBlankUnchecked"], "没勾「先听一遍」，音频＋空歌词竟然放行了。"
    assert "歌词" in got["audioBlankUnchecked"]
    assert got["audioBlankChecked"] is None, (
        "勾了「先听一遍」还拦着——那个钩子就是页面在撒谎。"
    )
    assert got["videoChecked"] is None
    assert got["nothingPicked"], "什么都没选竟然能提交。"


def test_the_transcribe_stage_is_only_for_audio_with_the_box_ticked(tmp_path):
    out = page_tests._run_page_js(
        tmp_path,
        """
        console.log(JSON.stringify({
          audioTicked: stageFor("run", true),
          audioPlain: stageFor("run", false),
          videoTicked: stageFor("ingest", true),
        }));
        """,
    )
    got = json.loads(out)
    assert got["audioTicked"] == "transcribe"
    assert got["audioPlain"] == "run"
    assert got["videoTicked"] == "ingest", (
        "视频那条路被改道去听写了——硬字幕给的是画面直接写出来的字，"
        "换成听写是拿更准的换更差的。"
    )


def test_the_review_note_tells_the_truth_about_each_route(tmp_path):
    """两条路认错的方式不一样，提醒也就不能是同一句。"""
    out = page_tests._run_page_js(
        tmp_path,
        """
        console.log(JSON.stringify({
          ocr: reviewNote("ingest"),
          transcribe: reviewNote("transcribe"),
        }));
        """,
    )
    got = json.loads(out)
    assert "硬字幕" in got["ocr"] and "整行整行地漏" in got["ocr"]
    assert got["transcribe"] != got["ocr"], (
        "听写那条路复用了硬字幕那句提醒——页面在对着听写稿说 OCR 的毛病。"
    )
    assert "机器" in got["transcribe"] and "字会错" in got["transcribe"], got["transcribe"]
    assert "断句" in got["transcribe"] and "行数" in got["transcribe"], got["transcribe"]
    for forbidden in ("%", "％", "准确率", "字准"):
        assert forbidden not in got["transcribe"], (
            f"提醒里出现了 {forbidden!r}——本仓没有人量过听写的准确率。"
        )


def test_the_hook_starts_disabled_in_the_html_itself():
    """`#transcribe` 的 `disabled` 与那句「为什么用不上」得写在 HTML 上。

    **契约 2026-08-15 变过一次**（于淼要求）：这一行原来是「只在选了音频时才
    出现」，`#transcribeRow` 带着 `hidden`。代价是**上面那句提示先提到了它、
    而它还不在**，刚打开界面的人会当成 bug。现在改成一直露着、用不上时禁用。

    **守的担心一个字没变**：HTML 先渲染、脚本后跑。原来防的是「这一行闪一下
    才消失」，现在防的是「勾选框在脚本跑起来前是可勾的、而且没有任何说明」。
    页面上四个 `<section>` 带着 `hidden` 是同一个理由。

    **这一条仍是变异检验逼出来的那一条**：把这两样从标签上摘掉、只留 `boot()`
    里那两行，端到端那 40 多条一条都不红——因为快照是在 `DOMContentLoaded`
    **之后**取的。
    """
    html = page_tests._page_html()
    tag = re.search(r'<input\b[^>]*id="transcribe"[^>]*>', html)
    assert tag is not None, "页面上找不到 `#transcribe` 了。"
    assert re.search(r"(?<![\w-])disabled(?![\w-])", tag.group(0)), (
        f"`#transcribe` 没带 `disabled`，页面一加载它就是可勾的，直到脚本跑起来"
        f"才禁用——那一瞬间用户可以勾一个此刻没有意义的钩子：{tag.group(0)}"
    )
    why = re.search(r'<i\b[^>]*id="transcribeWhy"[^>]*>([^<]*)</i>', html)
    assert why is not None and why.group(1).strip(), (
        "`#transcribeWhy` 在 HTML 里是空的——那么页面刚打开时，用户看到一个"
        "灰掉的钩子却没有任何一句话说明为什么。"
    )


def test_the_ocr_route_gets_its_half_sentence_too(tmp_path, make_shell):
    """视频那条路的后半句也得由 `render()` 填上。

    后半句从 HTML 挪进了 JS，**两条路都得接**——只接听写那一条的话，OCR 停下来
    时提醒就只剩前半句「要核的是行数与内容」，而"整行整行地漏"那句从此没人说，
    而上面那条纯函数测试（`reviewNote("ingest")` 返回什么）照样绿。
    """
    client = make_shell(page_tests.BUILD_FIXTURE, 0, "ocr")
    why = _review_why(tmp_path, client)
    assert "硬字幕" in why and "整行整行地漏" in why, (
        f"OCR 停下来那一刻，提醒的后半句是 {why!r}——那条路的毛病没人说了。"
    )


def _review_why(tmp_path: Path, client) -> str:
    """把视频那条路停下来那一刻的 `#reviewWhy` 取出来。

    `e2e_tests.DRIVER_SOURCE` 的快照里没有这一格（它比这一棒早），所以这里另跑
    一小段驱动，**用的仍然是同一份替身 DOM 与同一份页面脚本**。
    """
    driver = r"""
    (async function main() {
      document.__fire("DOMContentLoaded");
      E("media").files = [
        new File([Uint8Array.from(CONFIG.media.bytes)], CONFIG.media.name)
      ];
      E("media").__dispatch("change", {});
      E("start").__dispatch("click", {});
      await waitFor("校对框显示出来", function () {
        return E("review").hidden === false || E("failed").hidden === false
          || E("finished").hidden === false;
      });
      console.log(JSON.stringify({ why: E("reviewWhy").textContent }));
    })();
    """
    config = {
        "base": f"http://127.0.0.1:{client.port}",
        "elements": e2e_tests.page_elements(),
        "media": {"name": "录屏.mp4", "bytes": list(page_tests.MP4)},
        "lyrics": "", "lyricsFile": "", "lyricsDrop": "", "correctedLyrics": "",
        "flow": "video", "clickWhy": False, "timeoutMs": e2e_tests.FLOW_TIMEOUT_MS,
    }
    script = tmp_path / "drive-ocr-why.js"
    script.write_text(
        e2e_tests.DOM_DOUBLE_SOURCE + "\n" + page_tests._page_script() + "\n" + driver,
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["node", str(script), json.dumps(config, ensure_ascii=False)],
        capture_output=True, text=True, timeout=e2e_tests.NODE_TIMEOUT_S,
    )
    assert proc.returncode == 0, f"{proc.stderr}\n--- stdout ---\n{proc.stdout}"
    return json.loads(proc.stdout)["why"]


def test_the_shared_headline_of_the_review_notice_is_still_on_the_page():
    """两条路共用的那半句仍然写在 HTML 里，后半句才是 JS 填的。"""
    html = page_tests._page_html()
    assert "要核的是行数与内容，不是只改错字" in html
    assert 'id="reviewWhy"' in html, (
        "后半句没有落点——`reviewNote()` 算出来的话没有任何地方显示得出来。"
    )


# ==========================================================================
# 六、端到端：页面自己的 `boot()` 跑一趟，替身 CLI 跑**真的** transcribe
#
# 上面那几条纯函数测试够不着中间那一层——`boot()` 有没有把它们接到 DOM 上。
# 实测过的坏法（test_web_e2e 模块 docstring 记着同一个形状）：把 `render()` 里
# 「听写跑完也停下来核一遍」那半句删掉，上面 40 条一条都不红，而用户会眼睁睁
# 看着一份没人看过的机器听写稿直接做成歌。
# ==========================================================================

#: 替身 murripple：`transcribe` 那一档跑**真的** `cli.transcribe`，只把模型推理
#: 换成重放抄件；别的子命令交给 `test_web_page` 那一份替身。
#:
#: **不另写一份"理想的 transcribe 输出"**：那一档的输出格式唯一来源是
#: `murripple/cli.py` 自己。手打一份的话，进度分层、日志白名单、页面上那几句话
#: 全都建立在一份想象的格式上——那正是 `test_web_e2e` 模块 docstring 里「第九次」
#: 说的那件事。
TRANSCRIBE_DISPATCH_SOURCE = '''\
"""按子命令挑：transcribe 跑真的 cli.transcribe，其余交给 Task 5 那份替身。"""
import json
import runpy
import sys
from pathlib import Path

FAKE, FIXTURE, CODE, WHISPER_FIXTURE = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
SUB = sys.argv[5]

if SUB != "transcribe":
    sys.argv = [FAKE, FIXTURE, CODE, "product"] + sys.argv[5:]
    runpy.run_path(FAKE, run_name="__main__")
    raise SystemExit(0)

from murripple import cli
from murripple.ingest.transcribe import transcribe_audio


class FakeWhisperX:
    """跟上面那份同一个道理：波形要像波形，还要有 detect_language。"""

    def __init__(self, doc):
        self.doc = doc

    def load_audio(self, path):
        return [0.0] * 16000

    def load_model(self, size, device, compute_type):
        return self

    def detect_language(self, audio):
        return "zh"

    def transcribe(self, audio, language):
        return self.doc


DOC = json.loads(Path(WHISPER_FIXTURE).read_text(encoding="utf-8"))
cli.transcribe_audio = lambda path, **kw: transcribe_audio(
    path, load=lambda: FakeWhisperX(DOC)
)

sys.argv = ["murripple"] + sys.argv[5:]
raise SystemExit(cli.main())
'''

#: 驱动。接在 `DOM_DOUBLE_SOURCE` + 页面脚本**后面**。
TRANSCRIBE_DRIVER_SOURCE = r"""
(async function main() {
  const steps = {};

  function snap() {
    const s = snapshot();
    s.rowHidden = E("transcribeRow").hidden;
    s.tickDisabled = E("transcribe").disabled;
    s.why = E("transcribeWhy").textContent;
    s.reviewWhy = E("reviewWhy").textContent;
    return s;
  }

  document.__fire("DOMContentLoaded");
  steps.atBoot = snap();

  // 先选一个**视频**：那条路的歌词是 ingest 自己 OCR 出来的，「先听一遍」这个
  // 钩子在那儿勾了什么也不会发生——所以它根本不该露面。
  E("media").files = [new File([Uint8Array.from(CONFIG.media.bytes)], "录屏.mp4")];
  E("media").__dispatch("change", {});
  steps.afterVideo = snap();

  E("media").files = [
    new File([Uint8Array.from(CONFIG.media.bytes)], CONFIG.media.name)
  ];
  E("media").__dispatch("change", {});
  steps.afterAudio = snap();

  E("transcribe").checked = true;
  E("transcribe").__dispatch("change", {});
  steps.afterTick = snap();

  E("start").__dispatch("click", {});
  // **「成品区出来了」也算等到了。** 少了这一半，"听写跑完直接往下做成歌"那种
  // 坏法会以「等了 30 秒」的面目红——诊断成本差得很远，而那正是这条测试最要紧
  // 的一种坏法（`test_web_e2e` 模块 docstring 第 3 条同一个道理）。
  // 「页面重新开口要歌词」也算等到了：起错了档（直接起 run）的话，服务端的歌词门
  // 会回 needs-lyrics，那时上面三样一个都不会变。
  await waitFor("校对框显示出来", function () {
    return E("review").hidden === false || E("failed").hidden === false
      || E("finished").hidden === false || E("blocked").textContent !== "";
  });
  steps.afterTranscribe = snap();

  E("ocrLyrics").value = CONFIG.correctedLyrics;
  E("continue").__dispatch("click", {});
  await waitFor("成品区显示出来", function () {
    return E("finished").hidden === false || E("failed").hidden === false;
  });
  steps.afterRun = snap();

  console.log(JSON.stringify(steps));
})();
"""

#: 用户在校对框里断好句、改好字之后的那一份。**行数跟草稿不一样**——这正是
#: 「人负责断句」这件事在这条测试里留下的痕迹。
#: 三句取自自造语料（`renderer/test/fixtures/synthetic-lyric-rows.json`）——
#: 这里要的只是"人改过的一份，行数跟草稿不一样"，用真歌词没有任何增益，
#: 而真歌词会跟着这份测试进公开仓。
CORRECTED = "我把 halo 拆成两半\n面板，冷的\n换气、停顿、然后继续\n"


@pytest.fixture
def transcribe_shell(tmp_path, ffmpeg_on_path):
    """一个真起着的服务，替身 CLI 会跑真的 `murripple transcribe`。"""
    fake = tmp_path / "fake_cli.py"
    fake.write_text(page_tests.FAKE_CLI_SOURCE, encoding="utf-8")
    dispatch = tmp_path / "transcribe_dispatch.py"
    dispatch.write_text(TRANSCRIBE_DISPATCH_SOURCE, encoding="utf-8")

    songs_root = tmp_path / "songs"
    songs_root.mkdir()
    command = (
        sys.executable,
        str(dispatch),
        str(fake),
        str(page_tests.BUILD_FIXTURE),
        "0",
        str(MIX_FIXTURE),
    )
    client = page_tests._serve(tmp_path, songs_root, command)
    yield client
    client._httpd.shutdown()
    client._thread.join(timeout=10)
    client._httpd.server_close()


#: `test_web_e2e` 那两个夹具，**import 过来用，不复制一份**：一个把真 `ffmpeg`
#: 前置进 PATH（这台机器上装没装 ffmpeg 是机器的性质，要钉死），一个起服务。
ffmpeg_on_path = e2e_tests.ffmpeg_on_path
make_shell = e2e_tests.make_shell


def test_the_page_stops_for_a_check_after_transcribing_then_finishes(
    tmp_path, transcribe_shell
):
    """一整趟：选音频 → 勾「先听一遍」→ 停下来核 → 改完继续 → 出成品。

    每一处接线都断在**页面自己的状态**上，不是断在 HTML 的字面量上：
    钩子露不露面、勾了能不能提交、起的是不是 `transcribe` 那一档、草稿有没有
    填进框里、提醒说的是不是听写那一套、改完之后往下走的是不是 `run`。
    """
    config = {
        "base": f"http://127.0.0.1:{transcribe_shell.port}",
        "elements": e2e_tests.page_elements(),
        "media": {"name": "没有歌词的歌.mp3", "bytes": list(page_tests.MP3)},
        "lyrics": "",
        "lyricsFile": "",
        "lyricsDrop": "",
        "correctedLyrics": CORRECTED,
        "flow": "transcribe",
        "clickWhy": False,
        "timeoutMs": e2e_tests.FLOW_TIMEOUT_MS,
    }
    script = tmp_path / "drive-transcribe.js"
    script.write_text(
        e2e_tests.DOM_DOUBLE_SOURCE
        + "\n"
        + page_tests._page_script()
        + "\n"
        + TRANSCRIBE_DRIVER_SOURCE,
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["node", str(script), json.dumps(config, ensure_ascii=False)],
        capture_output=True,
        text=True,
        timeout=e2e_tests.NODE_TIMEOUT_S,
    )
    assert proc.returncode == 0, (
        f"页面在 node 里没跑通：\n{proc.stderr}\n--- stdout ---\n{proc.stdout}"
    )
    steps = json.loads(proc.stdout)
    for name, snap in steps.items():
        assert snap["missingIds"] == [], (
            f"boot() 在 {name} 这一刻问了页面上没有的 id：{snap['missingIds']}"
        )

    # ① 钩子一直露着，但只在音频那条路上可勾
    #
    # 契约 2026-08-15 变过（于淼要求，见 test_the_hook_starts_disabled_…）：
    # 原来是「只在音频那条路上露面」，断的是 `rowHidden`。**要守的东西没变**
    # ——「勾了什么也不会发生」仍然是页面在撒谎，只是现在由 `disabled` 挡着
    # 而不是由藏起来挡着，并且多守一条：**用不上的时候必须说出为什么**。
    assert steps["atBoot"]["rowHidden"] is False, (
        "什么都没选，「先在本机提取」就藏起来了——而上面那句提示正提到它，"
        "刚打开界面的人会以为是 bug。"
    )
    assert steps["atBoot"]["tickDisabled"] is True, "什么都没选，那个钩子却是可勾的。"
    assert steps["atBoot"]["why"], "钩子灰着，却没说为什么。"
    assert steps["afterVideo"]["tickDisabled"] is True, (
        "选了视频，「先在本机提取」还能勾——那条路勾了什么也不会发生，是页面在撒谎。"
    )
    assert steps["afterVideo"]["why"], "视频那条路上钩子灰着，却没说为什么。"
    assert steps["afterAudio"]["tickDisabled"] is False, (
        "选了音频，那个钩子还灰着——那条出路用户根本用不了。"
    )
    assert steps["afterAudio"]["why"] == "", (
        "选了音频、钩子已经可用，却还挂着一句「为什么用不上」。"
    )

    # ② 没勾之前拦着，勾了才放行（勾选真的接到了 refreshGate 上）
    assert steps["afterAudio"]["startDisabled"] is True
    assert "歌词" in steps["afterAudio"]["blocked"]
    assert steps["afterTick"]["startDisabled"] is False, (
        "勾了「先听一遍」，「开始」还是灰的——那个钩子没接到闸门上。"
    )

    # ③ 起的是 transcribe 那一档
    assert any(
        "/start?stage=transcribe" in f for f in steps["afterTranscribe"]["fetches"]
    ), steps["afterTranscribe"]["fetches"]

    # ④ 停下来核，草稿真的填进了那个框，提醒说的是听写那一套
    assert steps["afterTranscribe"]["reviewHidden"] is False, (
        "听写跑完直接往下走了——没人看过那份稿子一眼。"
    )
    # 同 ① 的理由：判据从抄件自己推，不在源码里抄那一句歌词。
    head = draft_lines(transcribe_audio(Path("x.wav"), load=replay()))[0]
    assert head in steps["afterTranscribe"]["ocrLyrics"], (
        f"草稿没填进校对框：{steps['afterTranscribe']['ocrLyrics']!r}"
    )
    why = steps["afterTranscribe"]["reviewWhy"]
    assert "机器" in why and "断句" in why, why
    assert "硬字幕" not in why, f"页面对着听写稿说了硬字幕的毛病：{why!r}"

    # ⑤ 「这是机器听写的草稿」那几句真的到了主日志上，不在折叠区里
    main_log = steps["afterTranscribe"]["mainLogHtml"]
    assert "字会认错" in main_log, "「字会认错」被折进详细区了。"
    assert "比没有歌词更坏" in main_log

    # ⑥ 改完点继续 → 走 run → 出成品
    assert any("/start?stage=run" in f for f in steps["afterRun"]["fetches"]), (
        steps["afterRun"]["fetches"]
    )
    assert steps["afterRun"]["finishedHidden"] is False, steps["afterRun"]["errorText"]

    # ⑦ 落盘的是**人改过的那一份**，不是草稿
    song_dir = next(transcribe_shell.songs_root.iterdir())
    assert (song_dir / "lyrics.txt").read_text(encoding="utf-8") == CORRECTED
    draft = (song_dir / DRAFT_FILENAME).read_text(encoding="utf-8")
    assert draft != CORRECTED and len(draft.splitlines()) != len(CORRECTED.splitlines())
