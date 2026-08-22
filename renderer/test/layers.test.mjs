/**
 * 每一层都必须真的在画面上留下墨，而且留在该留的地方。
 *
 * determinism.test.mjs 只做三种比较：两次运行互比、乱序 vs 顺序互比、
 * 实时 vs 离线互比。**没有任何黄金基准**——它能抓「不确定」，抓不到
 * 「画错了」或「根本没画」，只要错得确定就行。实测把 spectrum、notes、
 * particles 三层从 LAYERS 里整个删掉，109 个测试依然全绿。
 *
 * 这里换一种办法：抠掉某一层再渲一遍，比较像素差。差得太少说明这层
 * 等于没画；差在不该出现的半径上说明位置错了，或者会被画幅裁掉。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const harness = `file://${resolve(here, "harness.html")}`;

/**
 * 每层：取样时刻、最少墨迹像素数、墨迹允许出现的半径区间（× R）。
 *
 * 半径上界来自 geometry.js：谱线尖端 1.95R = 短边的 0.44，短边一半是
 * 0.5 R 的 2.22 倍。超出就会被画幅裁掉。
 */
const CASES = [
  { name: "spectrum", ts: [1, 2.5, 5], minInk: 200, band: [1.02, 2.1] },
  // minSpan：音符必须同时出现在下落途中的各个位置。少了这条，把落点写死
  // 成判定环（音符根本不下落）也能满足墨迹量与半径区间——实测跨度会从
  // 0.81 掉到只剩彗尾的那 0.3。
  { name: "notes", ts: [1, 2.5, 5], minInk: 300, band: [0.9, 2.05], minSpan: 0.6 },
  { name: "particles", ts: [1, 2.5, 5], minInk: 150, band: [0.55, 1.6] },
  // 中心光核：一大团柔光，墨迹量远大于其他层
  { name: "core", ts: [1, 2.5, 5], minInk: 2000, band: [0, 1.9] },
];

async function inkFor(page, name, ts) {
  return page.evaluate(
    ({ name, ts }) => {
      const cv = document.getElementById("cv");
      const g = cv.getContext("2d");
      const mk = (layers) => {
        const app = murRippleApp.createApp({
          doc: document,
          canvas: cv,
          timelineDoc: window.__HARNESS_DOC__,
          mode: "offline",
          layers,
        });
        app.resize();
        app.setAudio(window.__HARNESS_AUDIO__);
        return app;
      };
      const all = murRippleApp.LAYERS;
      const without = all.filter((l) => l.NAME !== name);
      if (without.length !== all.length - 1) {
        throw new Error(`层 ${name} 不在 LAYERS 里`);
      }
      const grab = (app, t) => {
        app.renderFrame(t);
        return g.getImageData(0, 0, cv.width, cv.height).data;
      };
      const full = mk(all);
      const cut = mk(without);
      return ts.map((t) => {
        const a = grab(full, t);
        const b = grab(cut, t);
        // 半径与圆心一律问 geometry，不在这里复制一份常量——第一次改
        // 几何时这里就写死着旧的 0.28 与 H/2，band 全部对着错的基准算。
        const geom = murRippleApp.computeGeometry(cv, document);
        let ink = 0;
        let rMin = Infinity;
        let rMax = 0;
        for (let i = 0; i < a.length; i += 4) {
          if (a[i] !== b[i] || a[i + 1] !== b[i + 1] || a[i + 2] !== b[i + 2]) {
            ink++;
            const px = (i / 4) % cv.width;
            const py = Math.floor(i / 4 / cv.width);
            const r = Math.hypot(px - geom.cx, py - geom.cy) / geom.R;
            if (r < rMin) rMin = r;
            if (r > rMax) rMax = r;
          }
        }
        return { t, ink, rMin, rMax };
      });
    },
    { name, ts },
  );
}

for (const c of CASES) {
  test(`${c.name} 层真的在画，而且画在预算内的半径区间`, async () => {
    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext()).newPage();
      const errs = [];
      page.on("pageerror", (e) => errs.push(e.message));
      await page.goto(harness);
      const rows = await inkFor(page, c.name, c.ts);
      assert.deepEqual(errs, [], errs.join("; "));
      for (const r of rows) {
        assert.ok(
          r.ink >= c.minInk,
          `t=${r.t}：抠掉 ${c.name} 层后画面只差了 ${r.ink} 个像素` +
            `（要求 ≥${c.minInk}）——这一层等于没画`,
        );
        assert.ok(
          r.rMin >= c.band[0] && r.rMax <= c.band[1],
          `t=${r.t}：${c.name} 的墨迹落在 r=${r.rMin.toFixed(2)}…` +
            `${r.rMax.toFixed(2)} R，超出预算区间 ${c.band[0]}…${c.band[1]} R` +
            `——要么位置错了，要么会被画幅裁掉`,
        );
        if (c.minSpan !== undefined) {
          assert.ok(
            r.rMax - r.rMin >= c.minSpan,
            `t=${r.t}：${c.name} 的墨迹只铺开 ${(r.rMax - r.rMin).toFixed(2)} R` +
              `（要求 ≥${c.minSpan}）——它没有在下落，全挤在一个半径上`,
          );
        }
      }
    } finally {
      await browser.close();
    }
  });
}
