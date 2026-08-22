"""看 `_in/` 里有什么，定路线。

于淼的要求是"有啥放啥"：可能是一段录屏 mp4，可能是 wav 加一份歌词 txt，
也可能两样都有。两样都有时**不是二选一，而是各取所长**：

- **音频取质量最好的那一份。** 单独给的 wav/flac 优于 mp4 里的音轨——后者
  经过一次有损压缩，录屏还常带系统混音。
- **歌词优先用现成的 txt。** OCR 会错字，现成的是权威。
- **时间戳只能从 mp4 来。** 所以哪怕音频走了 wav、歌词走了 txt，视频仍然
  值得留着——那是纯音频拿不到的东西。

两条硬规矩：

一、**拿不准就报错，不猜。** 目录里两个 mp4，猜错要跑一小时才发现。报错
    时要把候选文件名都列出来，让人一眼知道该删哪个。

二、**决策要讲出来。** `Plan.notes` 是打印给人看的句子，不是调试输出。猜
    错时用户要能在第一屏就看出来。

与计划稿的一处偏差：`audio_from` 是一个纯 `Path`，没有 `("extract", ...)`
标签。要不要抽轨由扩展名唯一决定（Task 2 的分派表本来就是按扩展名写的），
再挂一个标签只会多出一个可能与扩展名打架的事实。`lyrics_from` 保留标签，
因为那里三种情形（现成文件 / 要 OCR / 没有）确实需要区分。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

#: 无损音源。同时给了无损与有损时取这一档。
LOSSLESS_SUFFIXES = (".wav", ".flac")

#: 有损但可直接用的音源。这两档合起来正好是 cli.find_source 认的四种扩展名，
#: 于是 Task 2 可以原样复制、不必转码。往这里加 .ogg 之类之前，先去改
#: find_source，否则复制出来的 source.ogg 管线根本找不到。
LOSSY_SUFFIXES = (".m4a", ".mp3")

VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm", ".avi")

LYRICS_SUFFIXES = (".txt",)


class IngestError(RuntimeError):
    """素材有问题，或者拿不准该怎么处理。消息里必须说清下一步该做什么。"""


@dataclass
class Plan:
    """扫描结论。"""

    #: 音频的来源文件。是视频的话由 Task 2 抽轨，是音频就原样复制。
    audio_from: Path

    #: 歌词的来源：现成文件、`("ocr", 视频)`、或者根本没有。
    lyrics_from: Path | tuple[str, Path] | None

    #: 给人看的决策说明，每条一句话。
    notes: list[str] = field(default_factory=list)


def _pick(files: list[Path], what: str) -> Path:
    """同一档里有多个候选就报错——这里没有可靠的高下之分，不许猜。"""
    if len(files) > 1:
        names = "、".join(f.name for f in files)
        raise IngestError(
            f"`_in/` 里有多个{what}：{names}。"
            f"不知道该用哪个，请只留一个（其余的移出 `_in/` 即可）。"
        )
    return files[0]


def scan(in_dir: Path) -> Plan:
    """看一眼 `_in/`，决定音频与歌词各从哪来。"""
    in_dir = Path(in_dir)
    # 隐藏文件一律跳过。macOS 的 .DS_Store 和 ._foo 会让"只有一个 txt"
    # 变成"两个"，于是每次都撞上面那条多候选报错。
    entries = sorted(
        p for p in in_dir.iterdir() if p.is_file() and not p.name.startswith(".")
    ) if in_dir.is_dir() else []

    if not entries:
        raise IngestError(
            f"`_in/` 是空的或不存在：{in_dir}。"
            f"请把这首歌的原始素材（录屏 mp4、mp3/wav、歌词 txt，有啥放啥）"
            f"放进去再来。"
        )

    def of(suffixes: tuple[str, ...]) -> list[Path]:
        # 大小写不敏感：用户从各处拿来的文件后缀写法不一。
        return [p for p in entries if p.suffix.lower() in suffixes]

    lossless = of(LOSSLESS_SUFFIXES)
    lossy = of(LOSSY_SUFFIXES)
    videos = of(VIDEO_SUFFIXES)
    lyrics = of(LYRICS_SUFFIXES)
    known = {*lossless, *lossy, *videos, *lyrics}
    unknown = [p for p in entries if p not in known]

    notes: list[str] = []
    seen = "、".join(p.name for p in entries if p in known)
    notes.append(f"扫描 `_in/`：{seen}")

    # 视频哪怕不供音频也要挑出唯一那个——字幕要从它来。
    video = _pick(videos, "视频") if videos else None

    if lossless or lossy:
        standalone = _pick(lossless, "无损音源") if lossless else _pick(lossy, "音源")
        audio_from = standalone
        if lossless and lossy:
            other = "、".join(p.name for p in lossy)
            notes.append(f"音频 ← {standalone.name}（无损，优于 {other}）")
        elif video:
            notes.append(
                f"音频 ← {standalone.name}"
                f"（单独给的音源优于 {video.name} 里的音轨："
                f"视频音轨经过一次有损压缩，录屏还常带系统混音）"
            )
        else:
            notes.append(f"音频 ← {standalone.name}")
    elif video:
        audio_from = video
        notes.append(f"音频 ← 从 {video.name} 抽轨（`_in/` 里没有单独的音源）")
    else:
        raise IngestError(
            "`_in/` 里没有任何音频或视频，做不出东西来。"
            f"请放进一份 {'/'.join(s.lstrip('.') for s in LOSSLESS_SUFFIXES + LOSSY_SUFFIXES)}"
            f" 或一段录屏视频。"
        )

    if lyrics:
        lyrics_from: Path | tuple[str, Path] | None = _pick(lyrics, "歌词文件")
        note = f"歌词 ← {lyrics_from.name}"
        if video:
            note += "（现成歌词是权威，跳过 OCR——OCR 会错字）"
        else:
            note += "（跳过 OCR）"
        notes.append(note)
    elif video:
        lyrics_from = ("ocr", video)
        notes.append(f"歌词 ← {video.name} 的硬字幕（OCR，顺带拿到每行的出现时刻）")
    else:
        lyrics_from = None
        notes.append(
            "歌词 ← 没有歌词文件，也没有视频可 OCR。"
            "请自己写一份 lyrics.txt 放进歌曲目录，"
            "或者跑 `murripple transcribe <歌曲目录>` 在本机听一遍——"
            "拿到的是一份要你自己断句、改字的草稿，不是歌词"
        )

    if unknown:
        notes.append("忽略（用不上）：" + "、".join(p.name for p in unknown))

    return Plan(audio_from=audio_from, lyrics_from=lyrics_from, notes=notes)
