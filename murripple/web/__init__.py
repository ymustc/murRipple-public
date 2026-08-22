"""本机网页壳子——`murripple serve` 起的那个只跑在本机的服务。

**这个包不 import 分析管线。** 它只用标准库（`http.server`、`subprocess`、
`socket`、`json`），跑歌全靠 `subprocess` 调 `murripple` 命令，管线一行不改。
反过来，`murripple/cli.py` 里那条 `serve` 分支也走**惰性 import**——顶层
import 会让方向反过来，把管线拖进这个包的依赖图里。
"""
