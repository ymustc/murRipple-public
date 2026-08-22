# `tests/fixtures/whisperx/` 的出处

这两份 `*.transcribe.json` 是 **2026-08-15 一次真跑 WhisperX 的逐字节抄录**，
不是手编的「理想输出」。**任何一份都不许改一个字节**——`tests/test_transcribe.py`
拿它们当真值（草稿的行数、行内容全是从这里推出来的）。

抄不到的不许编：这一整棵目录树里没有第三份 WhisperX 输出，别照着这两份的形状
「再造一份别的歌的」。要新素材就照下面的步骤真跑一次。

## 素材

`songs/05-trempe-moi/`——**于淼自己的歌**：Suno 生成音乐、词他创作，版权归他
本人，也是公开仓带的那首示例歌。`lyrics.txt` 34 行，法语。

| 文件 | 喂进去的音频 | 段数 | 耗时 |
|---|---|---|---|
| `05-source-mix.transcribe.json` | `songs/05-trempe-moi/source.mp3`（整首混音） | 8 | 70.2 秒 |
| `05-vocals.transcribe.json` | `songs/05-trempe-moi/build/stems/htdemucs/source/vocals.wav` | 8 | 60.4 秒 |

两份都留着，因为**它们是「听人声轨还是听混音」这个设计决定的全部证据**
（`murripple/ingest/transcribe.py` 选了混音，理由写在那个模块的 docstring 里）。
删掉其中一份，那个决定就退回成一句没有依据的断言。

## 环境

| 项 | 值 |
|---|---|
| 日期 | 2026-08-15 |
| 机器 | macOS 24.1.0 / arm64 |
| whisperx | `3.3.1`（`uv pip show whisperx`） |
| 模型 | `medium` / `cpu` / `compute_type="int8"` / `language="fr"`（与 `murripple/align.py` 同一组常量） |

## 重新抄一份：完整可执行步骤

```bash
cd <仓库根>
uv sync --extra align

cat > /tmp/capture.py <<'PY'
import json, sys
from pathlib import Path
import whisperx
audio = whisperx.load_audio(sys.argv[1])
model = whisperx.load_model("medium", "cpu", compute_type="int8")
result = model.transcribe(audio, language="fr")
Path(sys.argv[2]).write_text(
    json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
)
PY

uv run python /tmp/capture.py \
  songs/05-trempe-moi/source.mp3 \
  tests/fixtures/whisperx/05-source-mix.transcribe.json

uv run python /tmp/capture.py \
  songs/05-trempe-moi/build/stems/htdemucs/source/vocals.wav \
  tests/fixtures/whisperx/05-vocals.transcribe.json
```

（人声轨那一份要先有 `build/stems/`：`uv run murripple build songs/05-trempe-moi`
会生成，它本身也在 `.gitignore` 里、只活在主检出里。）

## 实测数（照实说，别拿去推一般情况）

- **34 行歌词 → 8 段。** 断句不在机器手里。这是**一首歌**的实测数，
  不是「Whisper 一般切几段」的分布。任何拿它去推「一般情况」的话都没有依据。
- **认错的地方肉眼可见，而且没量过字准率。** 举几处：曲名 `Trempe-moi` 被听成
  `Trompe-moi`／`Trampe-moi`／`Tente-moi`（同一份抄件里三种都有）；
  `Je suis né` → `Je suis née`；`Le fer ne prie pas` → `ne crie pas`／`ne cri pas`；
  `trente regards` → `trente gares`；`une voix` → `une voie`。
  **本仓没有人量过字准率**，所以代码、文档、界面里一个准确率数字都不许出现。
- `model.transcribe()` 的输出里**没有词级时间戳**——那要再跑一次
  `whisperx.align()`。本功能没有用到词级，所以这两份抄件里也没有。
- 抄的是 `transcribe()` 的**原始返回值**，不含 whisperx 打在 stderr 上的那几行
  第三方噪声（`Model was trained with torch 1.10.0+cu102…` 之类）。那一类的抄件
  在 `tests/fixtures/real-build-output.txt` 里（出处见
  `tests/fixtures/README.provenance.md`），已经够 `progress.py` 用了。

---

# ★ 2026-08-16：换掉了哪一对，换掉了什么

在这之前，这个目录里还有 `02-source-mix.transcribe.json` 与
`02-vocals.transcribe.json`，`tests/test_transcribe.py` 用的是那一对。

**它们抄的是别人的作品。** 于淼 2026-08-16 说明五首歌的出处：`01`／`04` 是
朋友创作、`02` 是师姐创作、`03` 是歌手已发行的录音，**只有 `05-trempe-moi`
是他自己的**。此前这份文档里写着「`02` 是于淼自己用 Suno 做的歌，不是商业
录音」——**那句话是错的**，记在这里，不悄悄改掉。

于是那一对抄件里逐字装着的，是师姐那首歌的词。**两份整份删除**，测试改用上面
那对法语抄件。

## 换掉之后，哪一条守卫没人接

**`test_the_draft_comes_back_simplified` 删掉了，接不上。**

它证的是「**真模型真的会在中文歌上吐繁体**，而草稿必须转回简体再交给人」。
那件事只有一份**中文的真跑抄件**证得了：

- 法语抄件里一个繁体字都没有，参数化换过去只会得到一条前提永远塌着的测试；
- 私仓里**没有第二首于淼自己的中文歌**可以真跑重抄——01/02/04 是别人的作品，
  03 是已发行录音，05 是法语。`murripple compose` 摇得出曲子，摇不出人声。
  所以这不是「这一棒没空做」，是**素材层面做不到**。

顶上来的只有半条：`test_the_draft_comes_back_simplified_on_synthetic_input`。
它喂自造语料里那首繁体的歌，**逐句比对手写的简体金样本**（不是拿 opencc 算的，
算出来就成了「opencc 等于 opencc」）。它证「转换本身对」，证不了「真模型真的
会吐繁体」——因为那段繁体是我们自己写的。

`DECISIONS.md` 2026-08-15 记着「公开仓只带得走后一条」；**2026-08-16 起这句话
对私仓也成立了**。这是这次清理付出的最大一笔代价，写在这里，不藏着。

## 换掉之后，哪一条反而变强了

`test_the_punctuation_in_the_transcript_never_becomes_a_line_break`。

原来那条断的是「抄件里一个标点都没有」——中文 Whisper 不打标点，所以那是一条
**关于夹具的**断言：一个「按逗号句号再切一刀」的坏实现，在那份夹具上根本切不动，
一条都不会红。法语抄件里逗号、句号、撇号一大把，于是同一个念头**有东西可切**，
断言也就直接钉在输出上：段数几个，草稿就几行。变异检验的实测数写在那条测试里。
