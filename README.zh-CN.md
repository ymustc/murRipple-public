# 知漪 · murRipple

把一首歌织成看得见的涟漪。

给它一份音频加一份歌词，它产出一个**零依赖的单文件 `index.html`**（双击即开、
可发给任何人、可挂 GitHub Pages），以及一份 **1080p60 的 MP4**。

[English](README.md) · **中文** · [Français](README.fr.md)

<p align="center">
  <img src="assets/shell.png" alt="本机壳子：选一个文件或粘一条链接、把歌词贴进来、点开始" width="720">
  <br><sub>界面就这一屏。它跑在你自己的机器上，只绑环回地址。它做出来的东西<a href="https://ymustc.github.io/murripple-demo/">可以在线播放</a>——那就是仓里带的这首示例歌。</sub>
</p>

## 整条链路

<p align="center">
  <img src="assets/pipeline.svg" alt="murRipple 的四步链路" width="760">
</p>

上面那张图从左到右四步：**分析**（Demucs 分轨 + 节拍、音高、能量）→
**对齐**（WhisperX 把歌词对到时间上，可选，降级会大声说）→
**时间线**（`build/timeline.json`，一份文件装下全部真相）→
**打包**（音频、渲染器、时间线全部内联）。产出两样：`dist/index.html`
（拔掉网线也能开）和 `dist/<歌名>.mp4`。**每一步先看产物在不在，在就跳过。**

## 算力全在你自己的机器上

- **不接任何大模型 API，不用 API key，不用注册。** 这个项目里没有任何一处调用
  模型厂商的接口。
- **音频分析在本地跑。** 音源分离（Demucs）、节拍与音高分析（librosa）、歌词
  对齐（WhisperX，可选）全部用你自己的 CPU／GPU，音频不会被上传。
- **它产出的那个文件一次网络请求都不发。** `dist/index.html` 把音频、时间线、
  渲染器全部内联进去了；拔掉网线双击打开，照样跑。
- 工具链只有两处会碰网络，而且都是你主动要的：分离／对齐的模型第一次跑时要
  下载权重；`murripple ingest --url <链接>` 本来就是去取你指定的那个视频。

> ⚠ **你对自己处理和分发的素材负责。** 从链接取回的录音多半受版权保护；
> murRipple 的产物内嵌完整音频，公开分享前请确认你拥有相应权利。
> 全部处理都在你自己的机器上完成，不上传任何内容。

## 前置条件

- **Python 3.11** —— 是锁定，不是建议。Demucs 在 Python 3.13 上不工作，所以本
  项目用 [uv](https://docs.astral.sh/uv/) 隔离出一个 3.11 环境。
- **ffmpeg** —— `brew install ffmpeg`（或你平台上的包管理器）。
- **Node.js** —— 只有要构建渲染层 bundle 或者导出 MP4 时才需要。

## 安装

```bash
uv sync --group dev
uv sync --group dev --extra align   # 歌词对齐（WhisperX），可选
uv sync --group dev --extra ocr     # 认录屏里烧死在画面上的硬字幕，可选
```

不装 `align` 也能跑，管线会自动降级为「无歌词层」并且说出来。

## 先跑仓里那首示例歌

仓里带了一首完整的歌，你不用先去找素材就能做出一个真东西。
**[《Trempe-moi》](songs/05-trempe-moi/) 是作者自己的歌**——音乐用 Suno 生成、
词他创作，版权归他本人。

```bash
uv run murripple run songs/05-trempe-moi
open songs/05-trempe-moi/dist/index.html

cd renderer && npm install
node video/render.mjs ../songs/05-trempe-moi --size 1920x1080
```

## 做你自己的

```bash
mkdir -p songs/my-song
cp /path/to/song.mp3 songs/my-song/source.mp3
$EDITOR songs/my-song/lyrics.txt      # 一行一句

uv run murripple run songs/my-song
```

改一个参数重跑不会把贵的那几步再来一遍；要全部重来加 `--force`。

### 或者用网页跑

```bash
uv run murripple serve
```


它起的壳子**只绑环回地址**，同一个局域网里的别的机器连不上。选一个文件、贴
歌词、点开始。给它视频而不是音频，它会先抽音轨、试着认硬字幕，然后**停下来**
把认出来的歌词交回给你过一眼，改完才往下跑。

## 渲染层画的是什么

主奏驱动的判定环、带彗尾的下落音符、命中光屑、歌词化作的光核、辐射谱线、星云
背景、小节涟漪、刻度环、走带条、可单独静音／独奏的声部面板，以及标题页。

「网页看到的就是导出视频里的」不是口号：整套渲染是 `t` 的确定性函数，有一条
测试把同一时刻渲两遍、逐帧比哈希（`renderer/test/export-determinism.test.mjs`）。

## 跑测试

```bash
uv run pytest -q            # Python
cd renderer && npm test     # 渲染层
```

## 这里没有什么

参数化合成子系统 **compose**（不给音频、摇一个 seed 自己写一首器乐曲的那一路）
不在这个仓库里。

## 许可

**[PolyForm Noncommercial License 1.0.0](LICENSE)** —— `Copyright (c) 2026 YU Miao`。

> **它不是开源许可证。** 它不符合 Open Source Initiative 的定义，因为它限制了
> 使用领域。请不要把 murRipple 称作「开源」；准确的说法是「源码可得、禁止商用」。

- **可以**：使用、研究、修改、分发，也可以在它之上做新东西——只要是**非商业**
  用途。个人项目、研究、教学、公益组织、公共机构都可以。
- **不可以**：任何商业用途。不能卖，不能打包进付费产品或服务，不能在经营活动
  中使用。
- **想商用？** 来谈。许可证只是默认不授予，这是一次对话，不是一句拒绝。

以 `LICENSE` 全文为准，上面三条只是人话摘要，本身没有法律效力。

---
---
