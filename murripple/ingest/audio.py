"""把扫描定下的音源整理成歌曲目录下的 `source.*`。

**能不转码就不转码。** `cli.find_source` 从 M1 起就认 mp3/wav/m4a/flac 四种，
把用户给的 wav 转成 mp3 只是白丢一次质量。这是这一步最容易顺手做错的地方，
所以四种扩展名各有一条测试。

只有视频要真的动手：`-vn` 丢掉视频轨，抽出 `source.mp3`。

**已有 source 就停下。** 那份可能是用户手工换过的更好的一版；`--force` 才
覆盖，且覆盖时把另一个扩展名的旧 source 一并删掉——两份并存的话
`find_source` 按固定顺序取第一个，用户以为换了源其实没换。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from murripple.ingest.scan import (
    LOSSLESS_SUFFIXES,
    LOSSY_SUFFIXES,
    VIDEO_SUFFIXES,
    IngestError,
)

#: 直接可用、不转码的音频扩展名。与 cli.AUDIO_SUFFIXES 一致。
COPY_SUFFIXES = LOSSLESS_SUFFIXES + LOSSY_SUFFIXES

#: 从视频抽轨时的 LAME 质量档。2 约合 190 kbps VBR，听感上对分离与分析
#: 已经过剩；视频音轨本身就是有损的，再高只是放大前一次压缩的产物。
MP3_QUALITY = "2"

#: 抽出的音频与源声明时长的最大容差（秒）。mp3 帧填充与容器时长取整都在
#: 毫秒量级，1 秒足够宽松；真正的截断动辄差几秒到几十秒。
DURATION_TOLERANCE = 1.0


def _existing_sources(song_dir: Path) -> list[Path]:
    return [p for s in COPY_SUFFIXES if (p := song_dir / f"source{s}").exists()]


def _ffprobe(*args: str) -> str:
    out = subprocess.run(
        ["ffprobe", "-v", "error", *args], capture_output=True, text=True
    )
    return out.stdout.strip()


def _has_audio_track(src: Path) -> bool:
    return bool(
        _ffprobe("-select_streams", "a", "-show_entries", "stream=index",
                 "-of", "csv=p=0", str(src))
    )


def _duration(path: Path) -> float | None:
    """秒。优先问音频轨——视频轨末尾多挂一段无声画面是常事，那不算音频变短。"""
    for args in (
        ("-select_streams", "a:0", "-show_entries", "stream=duration"),
        ("-show_entries", "format=duration"),
    ):
        raw = _ffprobe(*args, "-of", "default=nw=1:nk=1", str(path))
        try:
            value = float(raw)
        except ValueError:
            continue
        if value > 0:
            return value
    return None


def prepare_audio(src: Path, song_dir: Path, force: bool = False) -> Path:
    """把 `src` 整理成 `song_dir/source.*`，返回产物路径。"""
    src = Path(src)
    song_dir = Path(song_dir)
    suffix = src.suffix.lower()

    if suffix in COPY_SUFFIXES:
        out = song_dir / f"source{suffix}"
    elif suffix in VIDEO_SUFFIXES:
        out = song_dir / "source.mp3"
    else:
        raise IngestError(
            f"不认识的音源格式：{src.name}（{suffix}）。"
            f"可直接使用的是 {'、'.join(COPY_SUFFIXES)}，"
            f"视频是 {'、'.join(VIDEO_SUFFIXES)}。"
        )

    existing = _existing_sources(song_dir)
    if existing and not force:
        names = "、".join(p.name for p in existing)
        raise IngestError(
            f"{song_dir} 下已存在 {names}，不覆盖——它可能是你手工换过的更好的"
            f"一份。确实要用 {src.name} 重来的话加 --force。"
        )

    if suffix in COPY_SUFFIXES:
        # 已有产物先清干净：留着另一个扩展名的旧 source，find_source 会取错。
        for p in existing:
            if p != out:
                p.unlink()
        # 源就是目标（用户把 source.wav 直接放在歌曲目录里）时什么都不用做。
        if src.resolve() != out.resolve():
            shutil.copy2(src, out)
        return out

    if not _has_audio_track(src):
        raise IngestError(
            f"{src.name} 里没有音频轨，抽不出东西来。"
            f"请确认这段视频是带声音的，或者单独提供一份音源。"
        )

    for p in existing:
        if p != out:
            p.unlink()

    expected = _duration(src)
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src),
         "-vn", "-acodec", "libmp3lame", "-q:a", MP3_QUALITY, str(out)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        # 失败要把残件删掉：留着的话下次跑会被当成"已存在"而跳过。
        out.unlink(missing_ok=True)
        raise IngestError(f"从 {src.name} 抽音频失败：{proc.stderr.strip()}")

    # 时长比对。**ffmpeg 对截断/损坏的文件仍然返回 0**（实测：3 秒的视频
    # 被截掉一半，抽出 1.09 秒的 mp3，退出码 0，只在 stderr 留一行
    # "partial file"）。只看退出码的话，管线会拿着一份短了一截的音频一路
    # 跑到底——画面与歌词整体错位，而没有任何一步报错。
    got = _duration(out)
    if expected and got and abs(got - expected) > DURATION_TOLERANCE:
        out.unlink(missing_ok=True)
        raise IngestError(
            f"从 {src.name} 抽出的音频只有 {got:.1f} 秒，而源声明是 "
            f"{expected:.1f} 秒——这段视频多半是残缺的（下载中断、截断）。"
            f"请换一份完整的，或者单独提供音源。"
        )
    return out
