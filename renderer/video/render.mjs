/**
 * 逐帧离线渲染 → MP4。
 *
 * 用法：
 *   node video/render.mjs ../songs/demo [--fps 60] [--size 1920x1080]
 *                                       [--from 0] [--to 30] [--crf 17]
 *
 * 四条设计决定，每条都有原因：
 *
 * 一、**加载产物 index.html 本身**，不另建渲染路径。整个 M2 的确定性铁则
 *     （固定步长时钟、禁 shadowBlur、把累积状态改写成 t 的闭式解）都是为
 *     这一步立的；另起一条路等于把它们全作废，"网页看到的 = 导出视频"也
 *     就无从谈起。
 *
 * 二、**不点标题页的开始按钮**。那会启动实时播放循环，与逐帧推进打架
 *     ——循环每帧按音频时钟重画，会把我们手动渲的那一帧覆盖掉。改为直接
 *     造一个 mode:"offline" 的实例。
 *
 * 三、**用 OfflineAudioContext 解码**。频谱与波形两层都要真实采样，而无头
 *     环境没有音频设备，AudioContext 会被挂起。实测 OfflineAudioContext
 *     解 270 秒的轨只要 156 ms。
 *
 * 四、**抓 canvas 而不是整页**。界面是 DOM 覆盖层，抓整页会把走带条和声部
 *     面板烤进视频。也不用 locator.screenshot——实测 346 ms/帧，比读
 *     canvas 的 89 ms 慢近四倍（它要做裁剪与合成）。
 */

import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync, mkdirSync, statSync } from "node:fs";
import { basename, resolve, join } from "node:path";

const AUDIO_SUFFIXES = [".mp3", ".wav", ".m4a", ".flac"];

function parseArgs(argv) {
  const songDir = argv[0];
  if (!songDir || songDir.startsWith("--")) {
    throw new Error(
      "用法：node video/render.mjs <歌曲目录> [--fps 60] [--size 1920x1080] " +
        "[--from 0] [--to 30] [--crf 17]",
    );
  }
  const opt = {
    fps: 60,
    width: 1920,
    height: 1080,
    from: 0,
    to: null,
    crf: 17,
  };
  for (let i = 1; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, "");
    const val = argv[i + 1];
    if (key === "size") {
      const [w, h] = val.split("x").map(Number);
      if (!w || !h) throw new Error(`--size 应形如 1920x1080，实得 ${val}`);
      opt.width = w;
      opt.height = h;
    } else if (key in opt) {
      opt[key] = Number(val);
      if (!Number.isFinite(opt[key])) {
        throw new Error(`--${key} 应为数字，实得 ${val}`);
      }
    } else {
      throw new Error(`未知参数 --${key}`);
    }
  }
  return { songDir: resolve(songDir), opt };
}

/** 找出原始音频。导出用它直接封装，零损耗——产物里那份 64k AAC 是为了体积。 */
function findSource(songDir) {
  for (const ext of AUDIO_SUFFIXES) {
    const p = join(songDir, `source${ext}`);
    if (existsSync(p)) return p;
  }
  throw new Error(`在 ${songDir} 下没找到 source 音频`);
}

function fmtDuration(sec) {
  const s = Math.round(sec);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** 在页面里造一个离线实例并喂上音频。返回时长。 */
async function prepare(page, width, height) {
  return page.evaluate(
    async ({ width, height }) => {
      // 标题页与界面全部移除：它们是 DOM 覆盖层，虽然抓 canvas 抓不到，
      // 但留着会让 boot 的实时循环有机会启动。
      document.getElementById("mr-title")?.remove();
      document.getElementById("mr-ui")?.remove();

      const cv = document.getElementById("cv");
      cv.style.width = `${width}px`;
      cv.style.height = `${height}px`;

      const app = murRippleApp.createApp({
        doc: document,
        canvas: cv,
        timelineDoc: window.__MR_TIMELINE__,
        mode: "offline",
      });
      app.resize();

      const decodeOne = async (uri) => {
        const bin = atob(uri.slice(uri.indexOf(",") + 1));
        const buf = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
        // OfflineAudioContext：只解码、不碰音频设备
        const ctx = new OfflineAudioContext(1, 1, 44100);
        return ctx.decodeAudioData(buf.buffer);
      };

      const buffers = {};
      for (const [stem, uri] of Object.entries(window.__MR_AUDIO__)) {
        if (uri) buffers[stem] = await decodeOne(uri);
      }
      app.setAudio(murRippleApp.mixToMono(buffers));

      window.__EXPORT__ = app;
      return app.timeline.meta.duration;
    },
    { width, height },
  );
}

async function main() {
  const { songDir, opt } = parseArgs(process.argv.slice(2));
  const artifact = join(songDir, "dist", "index.html");
  if (!existsSync(artifact)) {
    throw new Error(
      `找不到 ${artifact}。先跑 \`uv run murripple pack ${basename(songDir)}\``,
    );
  }
  const source = findSource(songDir);

  const browser = await chromium.launch();
  const page = await (
    await browser.newContext({
      viewport: { width: opt.width, height: opt.height },
      deviceScaleFactor: 1,
    })
  ).newPage();

  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errs.push(m.text()));

  await page.goto("file://" + artifact);
  const duration = await prepare(page, opt.width, opt.height);

  const to = opt.to ?? duration;
  const frames = Math.max(1, Math.round((to - opt.from) * opt.fps));
  const outDir = join(songDir, "dist");
  mkdirSync(outDir, { recursive: true });
  const out = join(outDir, `${basename(songDir)}.mp4`);

  console.log(
    `导出 ${basename(songDir)}：${opt.width}×${opt.height} @ ${opt.fps}fps，` +
      `${fmtDuration(opt.from)}–${fmtDuration(to)}，共 ${frames} 帧`,
  );

  const args = [
    "-y",
    "-f", "image2pipe",
    "-framerate", String(opt.fps),
    "-i", "-",
  ];
  // 只导一段时，音频也要从同一处切起，否则音画错位
  if (opt.from > 0) args.push("-ss", String(opt.from));
  args.push(
    "-i", source,
    "-c:v", "libx264",
    "-crf", String(opt.crf),
    "-preset", "medium",
    "-pix_fmt", "yuv420p",
    // 音频原样封装，不重编码——导出没有体积压力，用原文件
    "-c:a", "copy",
    "-shortest",
    out,
  );
  const ff = spawn("ffmpeg", args, { stdio: ["pipe", "ignore", "pipe"] });
  let ffErr = "";
  ff.stderr.on("data", (d) => (ffErr += d));

  const t0 = Date.now();
  for (let i = 0; i < frames; i++) {
    const t = opt.from + i / opt.fps;
    const url = await page.evaluate((tt) => {
      window.__EXPORT__.renderFrame(tt);
      return document.getElementById("cv").toDataURL("image/png");
    }, t);
    const png = Buffer.from(url.slice(url.indexOf(",") + 1), "base64");
    // 背压：写不进去就等 drain。丢一帧就是丢一帧，视频里补不回来。
    if (!ff.stdin.write(png)) await once(ff.stdin, "drain");

    if (i % Math.max(1, Math.round(opt.fps * 2)) === 0 || i === frames - 1) {
      const done = i + 1;
      const elapsed = (Date.now() - t0) / 1000;
      const eta = (elapsed / done) * (frames - done);
      process.stdout.write(
        `\r  ${done}/${frames} 帧 · ${((done / frames) * 100).toFixed(1)}% · ` +
          `已用 ${fmtDuration(elapsed)} · 剩余 ${fmtDuration(eta)}   `,
      );
    }
  }
  process.stdout.write("\n");

  ff.stdin.end();
  const [code] = await once(ff, "close");
  await browser.close();

  if (code !== 0) {
    throw new Error(`ffmpeg 退出码 ${code}：\n${ffErr.split("\n").slice(-12).join("\n")}`);
  }
  if (errs.length) {
    console.error("页面报错：\n" + errs.join("\n"));
  }
  console.log(
    `完成：${out}\n  ${(statSync(out).size / 1e6).toFixed(1)} MB · ` +
      `耗时 ${fmtDuration((Date.now() - t0) / 1000)}`,
  );
}

main().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
