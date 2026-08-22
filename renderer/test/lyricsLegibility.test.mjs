/**
 * 歌词在亮底上必须读得清——于淼实际反馈的问题。
 *
 * 原实现给整层设 `globalCompositeOperation = "lighter"`，字画在中心光核
 * 上时亮度是**相加**的：底本来就接近 255，字再亮也加不出差别，字与光晕
 * 糊成一团白。这不是配色问题，改色相解决不了，所以也不该用"色相对不对"
 * 之类的断言去守。
 *
 * 这里直接量**像素**：把画布刷成纯白（比真实光核还狠的极端底），只画一
 * 层歌词，看字块范围内的亮度分布。只画这一层是必须的——混着环、光核、
 * 谱线一起量，差多差少都不知道是谁贡献的。
 *
 * 三条阈值都是变异检验定出来的，不是实测值的复述：
 *   字芯改回加色     → 饱和像素 0 → 1979
 *   去掉压幕         → 饱和像素 0 → 6508，最暗一成 152 → 219
 *   去掉两道加色柔边 → 柔光像素 4993 → 467
 */

import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const harness = `file://${resolve(here, "harness.html")}`;

/** harness 第一句歌词是 1…4 秒，取正中间——淡入淡出都不参与。 */
const T = 2.5;

/**
 * 在指定底色上单画歌词层，回报字块范围内的亮度分布。
 */
function measure(page, bg) {
  return page.evaluate(
    ({ bg, T }) => {
      const cv = document.getElementById("cv");
      const g = cv.getContext("2d");
      const app = murRippleApp.createApp({
        doc: document,
        canvas: cv,
        timelineDoc: window.__HARNESS_DOC__,
        mode: "offline",
      });
      app.resize();
      const geom = murRippleApp.computeGeometry(cv, document);
      const layer = murRippleApp.LAYERS.find((l) => l.NAME === "lyrics");
      if (!layer) throw new Error("lyrics 层不在 LAYERS 里");

      g.globalCompositeOperation = "source-over";
      g.globalAlpha = 1;
      g.fillStyle = bg;
      g.fillRect(0, 0, cv.width, cv.height);

      layer.draw(g, {
        t: T,
        timeline: app.timeline,
        quality: 1,
        // 层只用到这两个字段；给定值，免得断言跟着调色板漂
        palette: { hueShift: 0, sat: 60 },
        geom,
        doc: document,
      });

      // 字块包围盒。字号公式与层内一致；harness 第一句断成两行四字，
      // 半宽取两个字、半高取一个行距，稳稳落在字上。
      const fontPx = Math.max(14, Math.min(geom.W, geom.H) * 0.031);
      const hx = Math.round(fontPx * 2);
      const hy = Math.round(fontPx * 1.42);
      const d = g.getImageData(
        Math.round(geom.cx - hx),
        Math.round(geom.cy - hy),
        hx * 2,
        hy * 2,
      ).data;

      const lum = [];
      let blown = 0;
      for (let i = 0; i < d.length; i += 4) {
        lum.push((d[i] * 299 + d[i + 1] * 587 + d[i + 2] * 114) / 1000);
        if (d[i] === 255 && d[i + 1] === 255 && d[i + 2] === 255) blown++;
      }
      lum.sort((a, b) => a - b);
      const at = (q) => lum[Math.floor((lum.length - 1) * q)];

      // 柔光的量：落在"既不是黑底也不是字芯"这一档的像素数。字芯附近的
      // 抗锯齿也会造出中间值，所以它只在与"抽掉柔边"相比时才有意义。
      const halo = lum.filter((v) => v >= 6 && v <= 70).length;

      return { p10: at(0.1), p90: at(0.9), blown, halo, n: lum.length };
    },
    { bg, T },
  );
}

/**
 * deviceScaleFactor 取 2：harness 的画布是固定的 800×450 CSS 像素，dpr=1
 * 时字号会掉到 14px 的下限，字块只剩两千来个像素，抗锯齿占的比重大到
 * 淹没要测的东西。
 */
async function openPage(browser) {
  const page = await (
    await browser.newContext({ deviceScaleFactor: 2 })
  ).newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(e.message));
  await page.goto(harness);
  return { page, errs };
}

test("纯白底上字块仍有明暗差，且底确实被压下去了", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const w = await measure(page, "#ffffff");
    assert.deepEqual(errs, [], errs.join("; "));

    assert.ok(
      w.p90 - w.p10 >= 55,
      `纯白底上字块的 p90−p10 只有 ${(w.p90 - w.p10).toFixed(1)}——` +
        `字与背景一样亮，等于看不见`,
    );
    // 光有差别还不够：差别得来自"底被压暗了"。去掉压幕之后最暗的一成
    // 反而是 219（字芯比纯白还暗一点），这一条就是冲它去的。
    assert.ok(
      w.p10 <= 200,
      `纯白底上字块最暗的一成是 ${w.p10.toFixed(1)}，底根本没被压下去`,
    );
  } finally {
    await browser.close();
  }
});

test("纯白底上字块一个饱和像素都不许有——加色的字芯必然饱和", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const w = await measure(page, "#ffffff");
    assert.deepEqual(errs, [], errs.join("; "));

    // 饱和成 255,255,255 的像素，字形就没了：笔画之间、笔画与底全钉在
    // 同一个值上。source-over 的字芯颜色与底无关，怎么亮的底都不会饱和。
    assert.equal(
      w.blown,
      0,
      `纯白底上字块里有 ${w.blown} 个像素饱和成纯白——字芯还在跟底相加`,
    );
  } finally {
    await browser.close();
  }
});

/**
 * 单画光核层，回报字块正中那一小片的平均亮度。
 *
 * 两次的差别只在 timeline.lyrics：同一个 t、同一套包络、同一个调色板，
 * 一次让它看得见歌词、一次把歌词整个抽空。这样量出来的差只可能来自
 * "光核有没有让位"，不会被别的东西混进来。
 */
function coreBrightness(page, hasLyrics) {
  return page.evaluate(
    ({ hasLyrics, T }) => {
      const cv = document.getElementById("cv");
      const g = cv.getContext("2d");
      const app = murRippleApp.createApp({
        doc: document,
        canvas: cv,
        timelineDoc: window.__HARNESS_DOC__,
        mode: "offline",
      });
      app.resize();
      const geom = murRippleApp.computeGeometry(cv, document);
      const layer = murRippleApp.LAYERS.find((l) => l.NAME === "core");
      if (!layer) throw new Error("core 层不在 LAYERS 里");

      g.globalCompositeOperation = "source-over";
      g.globalAlpha = 1;
      g.fillStyle = "#000000";
      g.fillRect(0, 0, cv.width, cv.height);

      const timeline = hasLyrics
        ? app.timeline
        : { ...app.timeline, lyrics: [] };
      layer.draw(g, {
        t: T,
        timeline,
        quality: 1,
        palette: { hueShift: 0, sat: 60 },
        geom,
        doc: document,
      });

      const half = Math.round(Math.min(geom.W, geom.H) * 0.05);
      const d = g.getImageData(
        Math.round(geom.cx - half),
        Math.round(geom.cy - half),
        half * 2,
        half * 2,
      ).data;
      let sum = 0;
      for (let i = 0; i < d.length; i += 4) {
        sum += (d[i] * 299 + d[i + 1] * 587 + d[i + 2] * 114) / 1000;
      }
      return sum / (d.length / 4);
    },
    { hasLyrics, T },
  );
}

test("有歌词时中心光核确实让位了", async () => {
  // 这一条守的是"两处配合"里的另一处。压幕只管字那边；光核不让位的话，
  // 底鼓一砸内芯照样胀回来，压幕就白压了。
  //
  // 它同时是 coreYield 那几条单测的接线检查：纯函数写得再对，draw 里
  // 不调用照样全绿。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const on = await coreBrightness(page, true);
    const off = await coreBrightness(page, false);
    assert.deepEqual(errs, [], errs.join("; "));

    assert.ok(
      off > on * 1.15,
      `字块正中的光核亮度：有歌词 ${on.toFixed(1)}、没歌词 ${off.toFixed(1)}` +
        `——光核根本没让位`,
    );
  } finally {
    await browser.close();
  }
});

test("字仍然往外发光——'歌词即光核'不能为了看清而丢掉", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const dark = await measure(page, "#000000");
    assert.deepEqual(errs, [], errs.join("; "));

    assert.ok(
      dark.halo >= 2500,
      `黑底上字块里的柔光像素只有 ${dark.halo} 个——柔边没了，` +
        `字成了贴上去的白块`,
    );
  } finally {
    await browser.close();
  }
});
