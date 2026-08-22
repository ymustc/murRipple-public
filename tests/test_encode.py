import base64
import subprocess

import numpy as np
import pytest
import soundfile as sf

from murripple.encode import EncodeError, encode_stem, pick_aac_encoder, to_data_uri


@pytest.fixture
def tiny_wav(tmp_path, sr):
    path = tmp_path / "tiny.wav"
    t = np.arange(sr, dtype=np.float32) / sr
    sf.write(path, 0.5 * np.sin(2 * np.pi * 440 * t), sr)
    return path


def test_picks_an_available_encoder():
    assert pick_aac_encoder() in {"aac_at", "aac"}


def test_encode_produces_playable_m4a(tiny_wav, tmp_path):
    out = encode_stem(tiny_wav, tmp_path / "tiny.m4a")
    assert out.exists()
    assert out.stat().st_size > 0

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True,
    )
    assert probe.stdout.strip() == "aac"


def test_data_uri_has_correct_prefix(tiny_wav, tmp_path):
    out = encode_stem(tiny_wav, tmp_path / "tiny.m4a")
    uri = to_data_uri(out)
    assert uri.startswith("data:audio/mp4;base64,")
    assert len(uri) > 100


def test_missing_input_raises(tmp_path):
    with pytest.raises(EncodeError, match="不存在"):
        encode_stem(tmp_path / "nope.wav", tmp_path / "out.m4a")


@pytest.fixture
def three_sec_wav(tmp_path, sr):
    """3 秒。太短的文件里容器开销会盖过码率差异，1 秒不够用。"""
    path = tmp_path / "three.wav"
    t = np.arange(sr * 3, dtype=np.float32) / sr
    # 多个谐波，避免纯正弦被编码器压到接近静音
    y = 0.4 * (np.sin(2 * np.pi * 220 * t)
               + np.sin(2 * np.pi * 660 * t)
               + np.sin(2 * np.pi * 1320 * t))
    sf.write(path, y.astype(np.float32), sr)
    return path


def test_picks_aac_at_when_available(monkeypatch):
    pick_aac_encoder.cache_clear()
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 0, " A....D aac                  AAC\n A..... aac_at               aac\n", ""
        ),
    )
    try:
        assert pick_aac_encoder() == "aac_at"
    finally:
        pick_aac_encoder.cache_clear()


def test_falls_back_to_native_aac_without_audiotoolbox(monkeypatch):
    """没有 AudioToolbox 的机器上必须回退，不能硬编码 aac_at。"""
    pick_aac_encoder.cache_clear()
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 0, " A....D aac                  AAC\n", ""
        ),
    )
    try:
        assert pick_aac_encoder() == "aac"
    finally:
        pick_aac_encoder.cache_clear()


def test_missing_ffmpeg_gives_actionable_error(monkeypatch):
    pick_aac_encoder.cache_clear()

    def boom(*a, **k):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(subprocess, "run", boom)
    try:
        with pytest.raises(EncodeError, match="brew install ffmpeg"):
            pick_aac_encoder()
    finally:
        pick_aac_encoder.cache_clear()


def test_bitrate_actually_reaches_ffmpeg(three_sec_wav, tmp_path):
    """码率是用户拍板的决定（64k 换约 11.5MB 产物）。

    若 `-b:a` 被误删，两次编码都会落到 ffmpeg 的默认码率，产物大小相同，
    本断言失败。这是这条约束唯一的守卫。
    """
    low = encode_stem(three_sec_wav, tmp_path / "low.m4a", bitrate="32k")
    high = encode_stem(three_sec_wav, tmp_path / "high.m4a", bitrate="128k")

    assert high.stat().st_size > low.stat().st_size * 2, (
        f"128k={high.stat().st_size}B 未显著大于 32k={low.stat().st_size}B，"
        f"码率参数很可能没有生效"
    )


def test_data_uri_round_trips_to_original_bytes(tiny_wav, tmp_path):
    """产物要能双击打开，全靠 base64 → ArrayBuffer → decodeAudioData 这条路。

    只验前缀不验内容，等于没验这条路真的通。
    """
    out = encode_stem(tiny_wav, tmp_path / "rt.m4a")
    payload = to_data_uri(out).split(",", 1)[1]
    assert base64.b64decode(payload) == out.read_bytes()
