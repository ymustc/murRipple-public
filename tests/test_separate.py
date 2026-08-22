import subprocess
import sys
from pathlib import Path

import pytest

from murripple.separate import SeparationError, separate


def _make_stub_outputs(out_dir: Path, model: str, name: str) -> None:
    d = out_dir / model / name
    d.mkdir(parents=True, exist_ok=True)
    for stem in ("vocals", "drums", "bass", "other"):
        (d / f"{stem}.wav").write_bytes(b"RIFF")


def test_builds_expected_command(tmp_path, monkeypatch):
    src = tmp_path / "song.mp3"
    src.write_bytes(b"fake")
    out = tmp_path / "stems"
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        _make_stub_outputs(out, "htdemucs", "song")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    separate(src, out)

    cmd = captured["cmd"]
    assert cmd[:3] == [sys.executable, "-m", "demucs"]
    assert "-n" in cmd and "htdemucs" in cmd
    assert str(src) in cmd


def test_returns_all_four_stem_paths(tmp_path, monkeypatch):
    src = tmp_path / "song.mp3"
    src.write_bytes(b"fake")
    out = tmp_path / "stems"

    def fake_run(cmd, **kwargs):
        _make_stub_outputs(out, "htdemucs", "song")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    stems = separate(src, out)

    assert set(stems) == {"vocals", "drums", "bass", "other"}
    for path in stems.values():
        assert path.exists()


def test_nonzero_exit_raises_with_stderr(tmp_path, monkeypatch):
    src = tmp_path / "song.mp3"
    src.write_bytes(b"fake")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "CUDA out of memory")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SeparationError, match="CUDA out of memory"):
        separate(src, tmp_path / "stems")


def test_missing_output_raises(tmp_path, monkeypatch):
    src = tmp_path / "song.mp3"
    src.write_bytes(b"fake")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SeparationError, match="未找到分离结果"):
        separate(src, tmp_path / "stems")


def test_demucs_not_installed_gives_actionable_error(tmp_path, monkeypatch):
    src = tmp_path / "song.mp3"
    src.write_bytes(b"fake")

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(sys.executable)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SeparationError, match="uv sync"):
        separate(src, tmp_path / "stems")


def test_shifts_is_pinned_to_zero_for_reproducibility(tmp_path, monkeypatch):
    """必须显式传 --shifts 0，否则管线不可复现。

    Demucs 的 --shifts 默认是 1：每次跑都做一次**随机**时间平移再平均
    （"random shifts for equivariant stabilization"），且不接受种子。
    实测同一首歌两次 build 得到不同的分轨，歌词对齐从 48 句掉到 33 句
    ——30% 的落差，而代码一行没改。

    分离质量略有损失，但换来可复现：好结果能重现，退化能追查。
    """
    src = tmp_path / "song.mp3"
    src.write_bytes(b"fake")
    out = tmp_path / "stems"
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        d = out / "htdemucs" / "song"
        d.mkdir(parents=True, exist_ok=True)
        for stem in ("vocals", "drums", "bass", "other"):
            (d / f"{stem}.wav").write_bytes(b"RIFF")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    separate(src, out)

    cmd = captured["cmd"]
    assert "--shifts" in cmd, "未固定 --shifts，管线不可复现"
    assert cmd[cmd.index("--shifts") + 1] == "0"
