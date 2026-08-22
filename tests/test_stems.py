import numpy as np
import soundfile as sf

from murripple.schema import STEMS
from murripple.stems import find_flat_stems


def write_flat(build_dir, names=STEMS):
    d = build_dir / "stems"
    d.mkdir(parents=True)
    for stem in names:
        sf.write(d / f"{stem}.wav", np.zeros(1000, dtype=np.float32), 44100)
    return d


def test_finds_all_four_flat_stems(tmp_path):
    write_flat(tmp_path)
    found = find_flat_stems(tmp_path)
    assert found is not None
    assert set(found) == set(STEMS)


# 九条那一档（要 `murripple.compose`）已于 2026-08-15 整段搬到
# `tests/test_stems_composed.py`——公开仓不带合成器，不拆的话整份文件都进不去。
# 断言一条没改，只是换了个文件放。


def test_missing_build_dir_returns_none(tmp_path):
    assert find_flat_stems(tmp_path) is None


def test_partial_set_returns_none(tmp_path):
    """三条不算数。半套分轨比没有更危险——会静默产出缺一条的曲子。"""
    d = write_flat(tmp_path)
    (d / "drums.wav").unlink()
    assert find_flat_stems(tmp_path) is None


def test_demucs_nested_layout_is_not_mistaken_for_flat(tmp_path):
    """**这是定案 1 的核心。** Demucs 写的是 stems/<model>/<源名>/*.wav，
    任何一次正常 build 之后 stems/ 都存在——照 spec 原话判断会误跳过分离，
    拿旧分轨假装新结果。"""
    nested = tmp_path / "stems" / "htdemucs" / "source"
    nested.mkdir(parents=True)
    for stem in STEMS:
        sf.write(nested / f"{stem}.wav", np.zeros(1000, dtype=np.float32), 44100)
    assert find_flat_stems(tmp_path) is None


def test_an_extra_unrelated_file_is_rejected_not_ignored(tmp_path):
    """评审 Minor #2：`find_flat_stems` 从"只查四个已知名字在不在"改成
    "目录下的文件集合恰好等于某一套完整名单"之后，行为悄悄变严格了——
    旧写法对"四个正确名字 + 一个不相干的 wav"是**接受**的（`found` 只按
    固定的四个名字去查，压根不知道目录里还有别的文件）；新写法要求
    `frozenset(找到的文件)` 与某套完整名单精确相等，多一个文件就不再
    相等。这个改变是有意的、也写进了 docstring（"含...超集...一律当作
    不完整处理"），对真歌安全（不会误把一份混了杂音频的目录当成合法
    分轨），但此前一直没有测试盯着这处行为变化本身。
    """
    d = write_flat(tmp_path)
    sf.write(d / "mix.wav", np.zeros(1000, dtype=np.float32), 44100)
    assert find_flat_stems(tmp_path) is None
