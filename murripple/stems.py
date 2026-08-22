"""扁平分轨探测。

`build/stems/*.wav`（扁平，直接躺在 `stems/` 下）= 分轨由外部提供
（`compose` 合成的，或手工放的），跳过 Demucs。**分轨数不再写死**：
真歌走 Demucs 的四条固定名单（`vocals/bass/drums/other`），`compose`
合成的曲子是九条——两条路径产出的分轨数不一样，调用方必须把"合成那
九条也算完整"这件事**当参数传进来**，本模块自己不认识 compose 这一层。

**不从这里 import `murripple.compose.synth`**：评审指出的分层倒置——
`murripple/stems.py` 是核心管线用来判断"要不要起 Demucs"的基础设施，
不该反过来依赖 `compose` 子系统（那会把 arrange/motif/theory/voices +
scipy/soundfile 一并拖进任何 import 这个模块的地方）。今天 `compose/`
下没有东西 import `murripple.stems`，没有环；但 Task 8 就是下一棒，且
明确要动 `cli.py`，`cli.py` 已经同时 import 了 `murripple.stems` 与
`murripple.compose.synth`——一旦 Task 8 让 `compose` 那一侧反过来引用
`find_flat_stems`，两个方向的 import 一凑齐就成环。调用方（`cli.py`）
自己既知道 `schema.STEMS`、也知道 `compose.synth.STEM_NAMES`，让它把
"合成那一套也算完整"作为 `extra_complete_sets` 传进来，本模块永远只
依赖 `schema`。

**不能只判断 `build/stems/` 存不存在**：`separate()`（见 `murripple/separate.py`）
写的是 `stems/<model>/<源文件名>/*.wav`——嵌套布局。任何一次正常 build 之后
`stems/` 目录本身都会存在，照"目录在不在"判断，第二次 build 会误判成
"分轨已由外部提供"、跳过 Demucs，拿上一次的旧分轨假装这次的新结果。这里用
非递归的 `glob("*.wav")`，天然避开嵌套那一层，不需要额外判断。

**"凑不齐一套完整名单"仍然拒绝**：三条不算数，半套分轨比没有更危险——
会静默产出缺一条的曲子。「完整」不是单一固定名单，而是"恰好等于某一套
已知完整名单"；既不属于 `schema.STEMS`、也不属于调用方传入的任何一套
`extra_complete_sets`（包括子集、超集、混搭）一律当作不完整处理。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from murripple.schema import STEMS


def find_flat_stems(
    build_dir: Path,
    extra_complete_sets: Iterable[Iterable[str]] = (),
) -> dict[str, Path] | None:
    """找齐**一整套**扁平分轨就返回 {stem 名: 路径}；凑不出 `schema.STEMS`
    或 `extra_complete_sets` 里任何一套完整名单（含缺一条、多一条、
    跨套混搭）返回 None。

    `extra_complete_sets`：调用方额外认可的完整名单（比如 `compose`
    产出的九条）——本模块只认识 `schema.STEMS` 这一套，别的都靠调用方
    自己传，不在这里 import 别的子系统。
    """
    stems_dir = Path(build_dir) / "stems"
    if not stems_dir.is_dir():
        return None
    found = {path.stem: path for path in stems_dir.glob("*.wav") if path.is_file()}
    complete_sets = (frozenset(STEMS), *(frozenset(s) for s in extra_complete_sets))
    if frozenset(found) in complete_sets:
        return found
    return None
