"""Demucs 音源分离封装。

用子进程而不是 Python API：CLI 接口跨版本稳定得多，而且测试可以完全
mock 掉，不必下载 2GB 模型。用 sys.executable -m demucs 保证跑在同一
个 uv 环境里，绕开 PATH 问题。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from murripple.schema import STEMS

DEFAULT_MODEL = "htdemucs"


class SeparationError(RuntimeError):
    """分离失败。消息里必须带上可执行的修复建议。"""


def separate(
    audio_path: Path, out_dir: Path, model: str = DEFAULT_MODEL
) -> dict[str, Path]:
    """把一个音频文件分离成四轨 WAV，返回 {stem 名: 路径}。"""
    audio_path = Path(audio_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "demucs",
        "-n",
        model,
        # 必须固定为 0。Demucs 默认 --shifts=1，每次跑都做一次**随机**
        # 时间平移再平均，且不接受种子——实测同一首歌两次 build 得到不同
        # 的分轨，歌词对齐从 48 句掉到 33 句，而代码一行没改。分离质量略
        # 有损失，但换来可复现：好结果能重现，退化能追查。
        "--shifts",
        "0",
        "-o",
        str(out_dir),
        str(audio_path),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise SeparationError(
            "无法启动 Demucs。请在仓库根运行 `uv sync --group dev` 安装依赖。"
        ) from exc

    if proc.returncode != 0:
        raise SeparationError(
            f"Demucs 退出码 {proc.returncode}：\n{proc.stderr.strip()}"
        )

    stem_dir = out_dir / model / audio_path.stem
    result: dict[str, Path] = {}
    for stem in STEMS:
        path = stem_dir / f"{stem}.wav"
        if not path.exists():
            raise SeparationError(
                f"未找到分离结果 {path}。Demucs 可能改变了输出布局，"
                f"或分离被中断。"
            )
        result[stem] = path
    return result
