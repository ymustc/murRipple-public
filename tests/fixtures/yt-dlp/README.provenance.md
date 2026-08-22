# `tests/fixtures/yt-dlp/` 的出处

这一目录下的 `*.stdout` / `*.stderr` 是 **2026-08-14 一次真跑 yt-dlp 的逐字节抄录**，
不是手打的"理想格式"。**任何一份都不许在文件里加注释、加标题、改空白**——
`test_fetch.py` 有一条恒等式测试拿它们当真值（见文末）。要记东西就记在这份 sidecar 里。

## 为什么不是从 YouTube 抄的

从 YouTube 抄要下载一份商业录音（见 `docs/research/2026-08-13-url-ingest.md` 第 0 节）。
改成**本机起一个 HTTP 服务喂自制媒体**，走 yt-dlp 的 generic 抽取器——
拿到的是同一个 yt-dlp 的同一套输出形状，且不碰任何版权素材。

**这一份抄件覆盖不到的**（照实说）：YouTube 专有的那部分文案，例如
`WARNING: [youtube] No supported JavaScript runtime could be found`、
`[youtube] xxxxx: Downloading player`。本仓没有这些的抄件。
调研文档里那条真实的 YouTube 403 原文是
`ERROR: unable to download video data: HTTP Error 403: Forbidden`
（`docs/research/2026-08-13-url-ingest.md` 第 4.3 节，2026-08-13 真跑），
与本目录 `http-403.stderr` 是**不同措辞的同一类错误**——前者在下载阶段，
后者在抓网页阶段。两条都不要手改成对方的样子。

## 环境

| 项 | 值 |
|---|---|
| 日期 | 2026-08-14 |
| yt-dlp | `2026.07.04`（`uv run --with 'yt-dlp' --no-project -- yt-dlp --version`） |
| 机器 | macOS 24.1.0 / arm64 |
| 抄录目录 | `$SP = <本次会话 scratchpad>/capture` |

## 重新抄一份：完整可执行步骤

```bash
SP=/tmp/ytdlp-capture          # 换成任何一个空目录
mkdir -p "$SP/www" && cd "$SP"

# 1) 自制媒体（不碰任何版权素材）
ffmpeg -v error -y -f lavfi -i "sine=frequency=440:duration=3" \
  -c:a aac -b:a 128k "www/知漪测试音.m4a"
ffmpeg -v error -y -f lavfi -i "testsrc=size=320x240:rate=10:duration=3" \
  -f lavfi -i "sine=frequency=440:duration=3" \
  -c:v libx264 -c:a aac -shortest "www/知漪测试片.mp4"

# 2) 本机 HTTP 服务：/ 下发媒体，/forbidden/* 一律 403
cat > serve.py <<'PY'
import http.server, os
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "www"))
class H(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/forbidden"):
            self.send_response(403); self.send_header("Content-Length","0"); self.end_headers(); return
        return super().do_GET()
    do_HEAD = do_GET
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(("127.0.0.1", 8931), H).serve_forever()
PY
python3 serve.py &

A="http://127.0.0.1:8931/%E7%9F%A5%E6%BC%AA%E6%B5%8B%E8%AF%95%E9%9F%B3.m4a"   # 知漪测试音.m4a
V="http://127.0.0.1:8931/%E7%9F%A5%E6%BC%AA%E6%B5%8B%E8%AF%95%E7%89%87.mp4"   # 知漪测试片.mp4

# 3) audio-success.stdout（成功取音频）
mkdir -p outB
uv run --with 'yt-dlp' --no-project -- yt-dlp \
  -f 'bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]' --newline --no-playlist \
  --print-to-file after_move:filepath "$SP/outB.path" \
  -o "$SP/outB/%(title)s.%(ext)s" "$A" > audio-success.stdout 2> /dev/null

# 4) video-success.stdout（成功取视频）
mkdir -p outE
uv run --with 'yt-dlp' --no-project -- yt-dlp \
  -f 'bv*+ba[ext=m4a]/bv*+ba/b' --merge-output-format mkv --newline --no-playlist \
  --print-to-file after_move:filepath "$SP/outE.path" \
  -o "$SP/outE/%(title)s.%(ext)s" "$V" > video-success.stdout 2> /dev/null

# 5) http-403.{stdout,stderr}
mkdir -p outC
uv run --with 'yt-dlp' --no-project -- yt-dlp \
  -f 'bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]' --newline --no-playlist \
  --print-to-file after_move:filepath "$SP/outC.path" \
  -o "$SP/outC/%(title)s.%(ext)s" \
  "http://127.0.0.1:8931/forbidden/x.m4a" > http-403.stdout 2> http-403.stderr

# 6) no-format.{stdout,stderr}（拿音频选择器去要一个只有合并格式的 mp4）
mkdir -p outD
uv run --with 'yt-dlp' --no-project -- yt-dlp \
  -f 'bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]' --newline --no-playlist \
  --print-to-file after_move:filepath "$SP/outD.path" \
  -o "$SP/outD/%(title)s.%(ext)s" "$V" > no-format.stdout 2> no-format.stderr

# 7) no-module.stderr（第 2 级：环境里没装 yt-dlp）
python3 -m yt_dlp --version > /dev/null 2> no-module.stderr

# 8) uv-unresolvable.stderr（第 1 级：uv 拉不到）
uv run --with 'yt-dlp==99.99.99' --no-project -- yt-dlp --version > /dev/null 2> uv-unresolvable.stderr
```

抄回来的文件里带的是**上面那个 `$SP` 的绝对路径**。测试**不改这些文件**——
`test_fetch.py` 里的替身用的是一份带占位符的模板，另有一条测试拿抄件当时的实际值
填回模板、要求**逐字节还原抄件**（`test_替身模板能逐字节还原真实抄件`）。
手把模板改成"理想格式"，那条会红。

## 各文件是什么

| 文件 | 退出码 | 是什么 |
|---|---|---|
| `audio-success.stdout` | 0 | 取音频成功。注意 `--print-to-file` 那行 `[info] Writing '%(filepath)s' to:` |
| `video-success.stdout` | 0 | 取视频成功（本例只有一个合并格式，没走到 merge） |
| `http-403.stdout` + `.stderr` | 1 | 站点回 403。**`ERROR:` 在 stderr**——不合并 stderr 就只剩"失败了" |
| `no-format.stdout` + `.stderr` | 1 | 没有可用的 AAC 音频格式 |
| `no-module.stderr` | 1 | 第 2 级不可用：`No module named yt_dlp` |
| `uv-unresolvable.stderr` | 1 | 第 1 级不可用：uv 解析不出来（断网时形状同类） |

---

## 追记（2026-08-14，接线那一棒）：`uv-cold-start.stderr`

**这一份不是 yt-dlp 的输出，是 `uv` 自己的**，走 stderr（被 `fetch._run` 的
`stderr=STDOUT` 并进同一个流）。它推翻了上一棒写在 `fetch.py` 里的一个假设：
「第 1 级第一次拉那 36.7 MB 的 deno 二进制时一行输出都没有」——**不成立**。

重抄：

```bash
COLD=$(mktemp -d)
UV_CACHE_DIR="$COLD" uv run --with 'yt-dlp[default,deno]' --no-project -- \
  yt-dlp --version > /dev/null 2> uv-cold-start.stderr
rm -rf "$COLD"
```

（`UV_CACHE_DIR` 指到一个空目录，逼 uv 真的重下一遍；抄完删掉那个目录，
上次实测它涨到 226 MB。）

消费它的是 `tests/test_web_fetch_wiring.py::test_第一次拉运行时那几行必须进主日志`
——这三种形状**必须归主日志**，因为那几分钟里它们是「没卡死、正在下东西」的
唯一证据。
