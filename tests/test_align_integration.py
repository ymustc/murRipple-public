"""align extra 的集成冒烟测试。

只在真正装了 align extra 的机器上运行（否则跳过）。它守的不是
「pyproject 里有没有那几行」——那是同义反复；它守的是那几个钉版
合起来到底能不能让 WhisperX 真的跑起来。

三层依赖冲突的来龙去脉见 pyproject.toml 里 align extra 的注释。
"""

import pytest


def test_whisperx_stack_is_importable_and_sees_torch():
    pytest.importorskip("whisperx", reason="未安装 align extra")

    import torch
    import torchaudio
    from transformers.utils import is_torch_available

    assert torchaudio.__version__.split("+")[0] == torch.__version__.split("+")[0], (
        f"torchaudio {torchaudio.__version__} 与 torch {torch.__version__} 版本不一致，"
        f"ABI 不兼容会让 import 时 dlopen 失败"
    )
    assert is_torch_available(), (
        "transformers 没认出 torch —— 通常是 transformers 版本要求的 torch 高于"
        "实际安装的版本，会让 whisperx 内部抛 NameError: name 'torch' is not defined"
    )
