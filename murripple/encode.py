"""四轨音频编码为 AAC，并可转成 data URI 内嵌。

选 AAC 不选 Opus：Opus 体积更小，但 Safari 对 Opus 支持历来不稳，而
本项目的核心场景是"发个链接谁都能开"。macOS 上优先用 AudioToolbox
的 aac_at，音质好于 ffmpeg 原生 aac。
"""

from __future__ import annotations

import base64
import functools
import subprocess
from pathlib import Path

DEFAULT_BITRATE = "64k"


class EncodeError(RuntimeError):
    """编码失败。"""


@functools.lru_cache(maxsize=1)
def pick_aac_encoder() -> str:
    """优先 aac_at（macOS AudioToolbox），不可用时回退原生 aac。"""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True,
        )
    except FileNotFoundError as exc:
        raise EncodeError(
            "未找到 ffmpeg。用 `brew install ffmpeg` 安装。"
        ) from exc
    return "aac_at" if " aac_at " in proc.stdout else "aac"


def encode_stem(
    wav_path: Path, out_path: Path, bitrate: str = DEFAULT_BITRATE
) -> Path:
    """把一条 WAV 编码成 m4a。"""
    wav_path, out_path = Path(wav_path), Path(out_path)
    if not wav_path.exists():
        raise EncodeError(f"输入文件不存在：{wav_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(wav_path),
        "-c:a", pick_aac_encoder(),
        "-b:a", bitrate,
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise EncodeError(
            f"ffmpeg 退出码 {proc.returncode}：\n{proc.stderr.strip()}"
        )
    return out_path


def to_data_uri(path: Path) -> str:
    """把 m4a 转成可直接内嵌进 HTML 的 data URI。

    产物必须走 data URI 而非独立文件：file:// 下 fetch 会被 CORS 拦，
    createMediaElementSource 会因跨域污染而静音，只有
    base64 → ArrayBuffer → decodeAudioData 这条路走得通。
    """
    payload = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:audio/mp4;base64,{payload}"
