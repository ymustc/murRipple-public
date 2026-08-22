# `tests/fixtures/real-build-output.txt` 的出处

一次**真跑 `murripple build` 的逐字节抄录**，不是手编的「理想噪声」。
`tests/test_web_progress.py`、`test_web_page.py`、`test_web_e2e.py`、
`test_web_runner.py` 四份测试拿它当日志分层的真值。

**任何一份都不许改一个字节。** 手改之后它仍然长得像抄件，而它的全部价值就在于
「没有人会手编出这样一份噪声」。

## 为什么 2026-08-16 重抄了一次

原来那一份（2026-08-14 抄的，1546 字节 / 17 行）里第 12 行是那次跑「未对上」的
歌词原文，而那句词来自**私仓 `songs/04`——朋友创作的一首歌**。
于淼 2026-08-16 说明五首歌里只有 `05-trempe-moi` 是他自己的，其余四首都是别人的
作品，所以那一行不能留。

（**这里刻意不把那一句抄出来当例子。** 一份「说明我们删掉了哪句第三方歌词」的
文档，如果自己把那句话写进去，就等于什么都没删——`tools/check_public_residue.py`
2026-08-16 在这份文档的初稿上当场抓到过这一条。）

**没有手改，是真跑重抄。** 改一个字它就不再是抄件。

## 素材

`songs/05-trempe-moi`（**于淼自己的歌**：Suno 生成音乐、词他写的，版权归他本人，
也是公开仓那首示例歌）的**头 12 秒**，切成一个临时歌曲目录：

```bash
mkdir -p /tmp/recap/songs/短片段
ffmpeg -i songs/05-trempe-moi/source.mp3 -t 12 -c:a libmp3lame -q:a 2 \
  /tmp/recap/songs/短片段/source.mp3
printf 'Le fer ne prie pas, il attend son heure,\n' \
  > /tmp/recap/songs/短片段/lyrics.txt
```

`lyrics.txt` 只放**一行**、而且放的是 05 歌词里的一句：头 12 秒是器乐前奏，
对齐必然一句都对不上，于是那一行必然进「以下 1 行未对上」。这就是第 12～13 行
那两格／四格缩进的来源——**它是可复现的，不是碰巧抄到的**。

## 跑法

```bash
cd <仓库根>
uv sync --extra align
PYTHONUNBUFFERED=1 uv run murripple build --language zh /tmp/recap/songs/短片段
```

### ★ `--language zh` 那一处，是这份抄件唯一需要解释的地方

喂进去的是**法语**素材，却指定了 `zh`。理由是这份夹具全部难点所在的那一行：

```
  warnings.warn(
```

它来自 `transformers/configuration_utils.py:312`，而那个 `warnings.warn` 只在
模型 config 里带 `gradient_checkpointing=True` 时才触发——**中文那个
wav2vec2 对齐模型带，法语和英语的不带**。2026-08-16 实测：

| 跑法 | 有没有 `  warnings.warn(` |
|---|---|
| 不指定语言（自动侦测出 `en`） | **没有** |
| `--language fr` | **没有** |
| `--language zh` | **有** |

这份夹具存在的理由就是「第 11 行（第三方）与第 12 行（我们）**都缩两格**，
形状一模一样」——那是「缩进不携带任何可靠的结构信息」这句话的判据形式
（`tests/test_web_progress.py` 的 `BUILD_EXPECTED_LAYERS` 就压在这一对上）。
没有那一行，这份抄件换成任何一次别的真跑都行，也就什么都不证明了。

指定 `zh` 不改变任何一行是不是真跑出来的：整份仍然是这条命令的原样 stdout+stderr，
一个字节没动。**认错的是模型，不是抄件。**

## 环境

| 项 | 值 |
|---|---|
| 日期 | 2026-08-16 |
| 机器 | macOS 24.1.0 / arm64 |
| 检出 | `/Users/miaoyu/Documents/claudeProjects/murRipple`（主检出；第 10 行那条绝对路径由此而来） |
| 检出（2026-08-21 之后） | 仓已迁到 `/Users/miaoyu/Documents/claudeProjects/archived-projects/murRipple/murRipple`。**上面那一行是抄录当时的实况，不改**；要重抄一份，把 `cd` 换成新址即可。抄件 `real-build-output.txt` 里那条绝对路径**更不许动**——`tests/test_web_progress.py:362` 钉着它 1594 字节 |
| whisperx | `3.3.1` |
| transformers | `4.48.3` |
| 抄件 | **1594 字节 / 18 行 / 0 个 `\r`** |

## 这份抄件覆盖不到的（照实说）

- **只有一条成功路径。** 降级、失败、`--force` 重跑一律不在里面。降级那一档另有
  `tests/fixtures/real-fallback-output.txt`（2026-08-14 抄的，209 字节 / 2 行，
  这一次**没有动它**——它里面没有任何第三方内容）。
- **第三方噪声是这台机器这一天的样子。** 换个 torch/pyannote/transformers 版本，
  第 4～7、10～11 行会变。它不是「Whisper 一般打什么」的分布。
- **`0 句歌词`** 是因为这 12 秒里没有人声，不是因为对齐坏了。整首歌跑出来是 34 句
  （`DECISIONS.md` 2026-08-16 管理窗口实跑那一条）。
- **比原来多一行**：`  语言：zh（--language 指定）`。那是多语言那一棒之后
  `cli.py` 新加的产品输出，2026-08-14 抄那一份时还不存在——**换句话说，旧夹具
  已经落后于产品一行了，而没有任何东西会为此变红**。
