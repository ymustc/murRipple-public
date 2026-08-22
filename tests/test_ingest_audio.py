"""音频抽取与归一。"""

import shutil
import subprocess
import wave

import numpy as np
import pytest

from murripple.ingest.audio import prepare_audio
from murripple.ingest.scan import IngestError

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="需要 ffmpeg/ffprobe",
)


def make_wav(dir_, seconds=2, sr=16000, name="song.wav"):
    """写一段 440 Hz 正弦，不是静音——静音测不出 -vn/-an 写反。"""
    t = np.arange(int(sr * seconds)) / sr
    pcm = (np.sin(2 * np.pi * 440 * t) * 0.5 * 32767).astype("<i2")
    path = dir_ / name
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def make_video_with_tone(dir_, seconds=3, name="录屏.mp4"):
    path = dir_ / name
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=blue:s=160x120:d={seconds}:r=10",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(path)],
        check=True,
    )
    return path


def make_video_without_audio(dir_, seconds=2, name="无声.mp4"):
    path = dir_ / name
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=red:s=160x120:d={seconds}:r=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )
    return path


def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def rms_of(path):
    import librosa

    y, _ = librosa.load(str(path), sr=None, mono=True)
    return float(np.sqrt(np.mean(y**2))) if y.size else 0.0


def test_wav_is_copied_not_transcoded(tmp_path):
    """wav 原样复制。转成 mp3 会白丢一次质量，而管线本来就认 wav。"""
    src = make_wav(tmp_path, seconds=2)
    out = prepare_audio(src, tmp_path)
    assert out.name == "source.wav"
    assert out.read_bytes() == src.read_bytes(), "被转码了"


@pytest.mark.parametrize("suffix", [".wav", ".flac", ".m4a", ".mp3"])
def test_every_supported_suffix_keeps_its_own(suffix, tmp_path):
    """四种扩展名管线都认（cli.find_source），一律不转码。

    只测 wav 的话，"凡不是 mp3 就转成 mp3"这种写法会漏网。
    """
    src = make_wav(tmp_path, seconds=1, name="raw.wav")
    real = tmp_path / f"song{suffix}"
    if suffix == ".wav":
        src.rename(real)
    else:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), str(real)],
                       check=True)
        src.unlink()
    out = prepare_audio(real, tmp_path)
    assert out.name == f"source{suffix}"
    assert out.read_bytes() == real.read_bytes()


def test_video_yields_mp3_with_matching_duration(tmp_path):
    """从视频抽出的音频时长要对得上——差一秒后面全曲错位。"""
    src = make_video_with_tone(tmp_path, seconds=3)
    out = prepare_audio(src, tmp_path)
    assert out.name == "source.mp3"
    assert abs(probe_duration(out) - 3.0) < 0.15


def test_video_audio_is_not_silent(tmp_path):
    """抽出来是静音的话，后面 Demucs 与分析全是空的，而且没有任何报错。

    这条不是凑数：-vn 写成 -an 就会得到一个合法但无声的文件。
    """
    out = prepare_audio(make_video_with_tone(tmp_path, seconds=2), tmp_path)
    assert rms_of(out) > 0.01, "抽出的音频是静音"


def test_video_without_audio_track_fails_loudly(tmp_path):
    with pytest.raises(IngestError, match="没有音频轨"):
        prepare_audio(make_video_without_audio(tmp_path), tmp_path)


def test_video_without_audio_leaves_no_half_written_file(tmp_path):
    """报错之后不能留下一个残缺的 source.mp3——下次跑会被当成"已存在"。"""
    with pytest.raises(IngestError):
        prepare_audio(make_video_without_audio(tmp_path), tmp_path)
    assert not (tmp_path / "source.mp3").exists()


def make_truncated_video(tmp_path, seconds=3):
    """一段被砍掉一半的 mp4。moov 放在文件头，所以时长信息还在。"""
    ok = tmp_path / "ok.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=blue:s=160x120:d={seconds}:r=10",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-movflags", "faststart", "-shortest", str(ok)],
        check=True,
    )
    bad = tmp_path / "残缺.mp4"
    data = ok.read_bytes()
    bad.write_bytes(data[: int(len(data) * 0.45)])
    ok.unlink()
    return bad


def test_truncated_video_is_caught_even_though_ffmpeg_exits_zero(tmp_path):
    """**ffmpeg 对截断文件仍然返回 0**，只在 stderr 留一行 partial file。

    实测：3 秒的视频砍掉一半，抽出 1.09 秒的 mp3，退出码 0。只看退出码的
    话，管线会拿着短了一截的音频一路跑到底——画面与歌词整体错位，而没有
    任何一步报错。所以必须比对时长。
    """
    bad = make_truncated_video(tmp_path, seconds=3)
    with pytest.raises(IngestError, match="残缺|秒"):
        prepare_audio(bad, tmp_path)


def test_truncated_video_leaves_no_half_written_file(tmp_path):
    """这条才真正走到抽轨之后的清理分支。

    没音轨那条在 ffmpeg 之前就拦下了，压根到不了这里。
    """
    bad = make_truncated_video(tmp_path, seconds=3)
    with pytest.raises(IngestError):
        prepare_audio(bad, tmp_path)
    assert not (tmp_path / "source.mp3").exists(), "残件还在，下次跑会被当成已存在"


def test_existing_source_is_not_overwritten_without_force(tmp_path):
    """已经有 source 了就停下——它可能是用户手工换过的更好的一份。"""
    src = make_wav(tmp_path, seconds=2)
    (tmp_path / "source.wav").write_bytes("用户自己放的".encode())
    with pytest.raises(IngestError, match="已存在|--force"):
        prepare_audio(src, tmp_path)
    assert (tmp_path / "source.wav").read_bytes() == "用户自己放的".encode(), "被覆盖了"

    prepare_audio(src, tmp_path, force=True)
    assert (tmp_path / "source.wav").read_bytes() == src.read_bytes()


def test_existing_source_of_a_different_suffix_also_blocks(tmp_path):
    """已有 source.mp3、这次来的是 wav，同样要停下。

    只比对同名文件的话会产出 source.wav + source.mp3 两份，而 find_source
    按固定顺序取第一个——用户以为换了源，其实没换。
    """
    src = make_wav(tmp_path, seconds=1)
    (tmp_path / "source.mp3").write_bytes("先前的".encode())
    with pytest.raises(IngestError, match="已存在|--force"):
        prepare_audio(src, tmp_path)


def test_force_clears_the_other_suffix_too(tmp_path):
    """--force 换源时要把旧的那份删掉，不能两份并存。"""
    src = make_wav(tmp_path, seconds=1)
    (tmp_path / "source.mp3").write_bytes("先前的".encode())
    out = prepare_audio(src, tmp_path, force=True)
    assert out.name == "source.wav"
    assert not (tmp_path / "source.mp3").exists(), "旧的那份还在，find_source 会取错"


def test_source_lands_outside_the_in_dir(tmp_path):
    """`_in/` 只读。产物写在歌曲目录下，不能污染原始素材。"""
    in_dir = tmp_path / "_in"
    in_dir.mkdir()
    src = make_wav(in_dir, seconds=1)
    before = sorted(p.name for p in in_dir.iterdir())
    out = prepare_audio(src, tmp_path)
    assert out == tmp_path / "source.wav"
    assert sorted(p.name for p in in_dir.iterdir()) == before, "动了 _in/"


def test_unsupported_suffix_is_rejected(tmp_path):
    src = tmp_path / "song.ogg"
    src.write_bytes(b"x")
    # 不能只 match "ogg"：把不认识的格式默默当视频抽，报出来的会是
    # 「song.ogg 里没有音频轨」，一样含 "ogg"，测试照过。
    with pytest.raises(IngestError, match="不认识的音源格式"):
        prepare_audio(src, tmp_path)
