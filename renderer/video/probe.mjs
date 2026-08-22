/**
 * M3 Task 0：动手前先量三个数。
 *
 * 1. 无头浏览器里能否解出音频（频谱与波形两层都要 audio.channel，而无头
 *    环境没有音频设备）
 * 2. 抓帧速度（3 分钟 60fps = 10800 帧，单帧超 80 ms 就要跑三个多小时）
 * 3. ffmpeg 管道通不通
 *
 * 留着当性能回归——哪天导出突然变慢，先跑它。
 */

import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { statSync } from "node:fs";
import { resolve } from "node:path";

const artifact = resolve(process.argv[2] ?? "songs/demo/dist/index.html");
const OUT = resolve(process.argv[3] ?? "video/probe-out.mp4");
const W = 1920;
const H = 1080;
const N = 100;

const browser = await chromium.launch();
const page = await (
  await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1 })
).newPage();
const errs = [];
page.on("pageerror", (e) => errs.push(String(e)));
await page.goto("file://" + artifact);

// —— 1. 解码 ——
// 关键：用 OfflineAudioContext 而不是 AudioContext。前者不碰音频设备，
// 无头环境里也能解；后者在没有设备时会被挂起，currentTime 永不前进。
const decode = await page.evaluate(async () => {
  const t0 = performance.now();
  const uri = window.__MR_AUDIO__.vocals;
  const bin = atob(uri.slice(uri.indexOf(",") + 1));
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  try {
    const ctx = new OfflineAudioContext(1, 1, 44100);
    const d = await ctx.decodeAudioData(buf.buffer);
    return { ok: true, sr: d.sampleRate, sec: +d.duration.toFixed(2), ms: Math.round(performance.now() - t0) };
  } catch (e) {
    return { ok: false, err: String(e) };
  }
});
console.log("解码：", JSON.stringify(decode));
if (!decode.ok) {
  console.error("解码失败——方案要改成 Node 侧解码再注入页面");
  await browser.close();
  process.exit(1);
}

// 造一个离线实例并喂上音频（不点开始按钮：那会启动实时循环，与逐帧推进打架）
await page.evaluate(async () => {
  const cv = document.getElementById("cv");
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
    const ctx = new OfflineAudioContext(1, 1, 44100);
    return ctx.decodeAudioData(buf.buffer);
  };
  const bufs = {};
  for (const [k, v] of Object.entries(window.__MR_AUDIO__)) bufs[k] = await decodeOne(v);
  app.setAudio(murRippleApp.mixToMono ? murRippleApp.mixToMono(bufs) : null);
  window.__EXPORT__ = app;
  document.getElementById("mr-title")?.remove();
});

// —— 2. 抓帧速度：两种办法各测一遍 ——
const timeIt = async (label, fn) => {
  const t0 = Date.now();
  let bytes = 0;
  for (let i = 0; i < N; i++) bytes += await fn(40 + i / 60);
  const ms = (Date.now() - t0) / N;
  console.log(
    `${label}：${ms.toFixed(1)} ms/帧，平均 ${(bytes / N / 1024).toFixed(0)} KB，` +
      `推算全曲 10800 帧 ${((ms * 10800) / 60000).toFixed(1)} 分钟`,
  );
  return ms;
};

const viaDataUrl = (t) =>
  page.evaluate((tt) => {
    window.__EXPORT__.renderFrame(tt);
    return document.getElementById("cv").toDataURL("image/png").length;
  }, t);

const viaScreenshot = async (t) => {
  await page.evaluate((tt) => window.__EXPORT__.renderFrame(tt), t);
  // 只抓 canvas，不抓整页——界面是 DOM 覆盖层，抓整页会把走带条烤进视频
  const buf = await page.locator("#cv").screenshot({ type: "png" });
  return buf.length;
};

// 拆开量：渲染本身多少、编码与回传多少，才知道该优化谁
await timeIt("renderFrame 单独", (t) =>
  page.evaluate((tt) => {
    window.__EXPORT__.renderFrame(tt);
    return 0;
  }, t),
);
await timeIt("toDataURL", viaDataUrl);
await timeIt("locator.screenshot", viaScreenshot);

// —— 3. ffmpeg 管道 ——
const ff = spawn("ffmpeg", [
  "-y", "-f", "image2pipe", "-framerate", "60", "-i", "-",
  "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", OUT,
], { stdio: ["pipe", "ignore", "ignore"] });

const t0 = Date.now();
for (let i = 0; i < N; i++) {
  // 用 toDataURL 而不是 locator.screenshot：实测前者 88 ms/帧、后者
  // 345 ms/帧，差近四倍。元素截图要做裁剪与合成，比直接读 canvas 贵得多。
  const url = await page.evaluate((tt) => {
    window.__EXPORT__.renderFrame(tt);
    return document.getElementById("cv").toDataURL("image/png");
  }, 40 + i / 60);
  const png = Buffer.from(url.slice(url.indexOf(",") + 1), "base64");
  // 背压：写不进去就等 drain，绝不丢帧
  if (!ff.stdin.write(png)) await once(ff.stdin, "drain");
}
ff.stdin.end();
await once(ff, "close");
console.log(
  `管道：${N} 帧 → ${(statSync(OUT).size / 1e6).toFixed(2)} MB，` +
    `耗时 ${((Date.now() - t0) / 1000).toFixed(1)} 秒`,
);
console.log(errs.length ? "控制台错误：" + errs.join(" | ") : "控制台零错误");
await browser.close();
