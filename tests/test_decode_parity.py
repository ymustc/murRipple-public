import subprocess
from pathlib import Path

import numpy as np
import pytest

from murripple.envelope import encode_u8

DECODER = (
    Path(__file__).resolve().parent.parent / "renderer" / "probe_decode.mjs"
)


def _decode_with_node(b64: str) -> np.ndarray:
    proc = subprocess.run(
        ["node", str(DECODER), b64], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    text = proc.stdout.strip()
    if not text:
        return np.array([], dtype=np.uint8)
    return np.array([int(x) for x in text.split(",")], dtype=np.uint8)


@pytest.mark.parametrize(
    "values",
    [
        [0, 1, 127, 254, 255],
        list(range(256)),
        [0] * 100,
        [255] * 100,
    ],
)
def test_js_decoder_matches_python_encoder(values):
    arr = np.array(values, dtype=np.uint8)
    assert np.array_equal(_decode_with_node(encode_u8(arr)), arr)


def test_realistic_envelope_length_survives_roundtrip():
    rng = np.random.default_rng(20260811)
    arr = rng.integers(0, 256, size=60 * 197, dtype=np.uint8)  # 3'17" @60Hz
    assert np.array_equal(_decode_with_node(encode_u8(arr)), arr)


def test_module_does_not_reference_bare_process_at_load_time():
    """浏览器里没有全局 process。probe_decode.mjs 顶层曾直接读
    `process.argv`，一 import 就抛 ReferenceError，导致 probe.html 卡在
    「载入中…」。这里用 `delete globalThis.process` 模拟浏览器环境后动态
    import 该模块 —— 若模块体（不只是 CLI 自检块的执行结果）引用了裸
    `process`，加载阶段就会抛错。
    """
    script = (
        "delete globalThis.process;"
        f"import({str(DECODER.as_uri())!r})"
        ".then(() => { console.log('IMPORT_OK'); })"
        ".catch(e => { console.log('IMPORT_ERR ' + e.constructor.name + ': ' + e.message); });"
    )
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
    )
    assert "IMPORT_OK" in proc.stdout, (
        f"import of probe_decode.mjs failed under a process-less (browser-like) "
        f"global scope.\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
