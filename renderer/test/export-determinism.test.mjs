/**
 * 导出级确定性：M3 的完成标志（spec 第 16 节第 1 条）。
 *
 * determinism.test.mjs 已有的几条只比对少数几个时间点。这里比对**连续一
 * 整段**——粒子世界的累积、缓存的命中顺序、浮点漂移，都要跑够长才暴露
 * 得出来。
 *
 * 另一条更狠也更贴近真实用法：从中途某一帧直接开渲，必须与从头渲到那里
 * 结果相同。导出的 `--from` 正是这么用的，而"理论上成立"在这里最容易骗人
 * ——粒子是唯一有状态的一层。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const harness = `file://${resolve(here, "harness.html")}`;

const FPS = 60;
/** 连续帧数。10 秒 @60fps——短于此，累积类问题跑不出来。 */
const FRAMES = 600;

async function openPage(browser) {
  const page = await (
    await browser.newContext({ viewport: { width: 640, height: 360 } })
  ).newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(e.message));
  await page.goto(harness);
  return { page, errs };
}

/**
 * 新建一个离线实例，从 startFrame 顺序渲到 endFrame，返回逐帧哈希。
 *
 * 每次都新建实例：复用会让"第二次运行"其实是接着第一次的状态跑，
 * 那就不是独立运行了，这条测试也就白测。
 */
function collect(page, startFrame, endFrame, fps) {
  return page.evaluate(
    ({ startFrame, endFrame, fps }) => {
      const app = murRippleApp.createApp({
        doc: document,
        canvas: document.getElementById("cv"),
        timelineDoc: window.__HARNESS_DOC__,
        mode: "offline",
      });
      app.resize();
      app.setAudio(window.__HARNESS_AUDIO__);
      const out = [];
      for (let i = startFrame; i < endFrame; i++) {
        app.renderFrame(i / fps);
        out.push(app.frameHash());
      }
      return out;
    },
    { startFrame, endFrame, fps },
  );
}

test(`连续 ${FRAMES} 帧，两次独立运行逐帧哈希完全一致`, async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const a = await collect(page, 0, FRAMES, FPS);
    const b = await collect(page, 0, FRAMES, FPS);

    assert.equal(a.length, FRAMES);
    for (let i = 0; i < FRAMES; i++) {
      assert.equal(
        b[i],
        a[i],
        `第 ${i} 帧不一致（t=${(i / FPS).toFixed(3)}s）——` +
          `逐帧导出会在这里产生抖动`,
      );
    }

    // 光"两次一致"不够：全程画同一张静止图也满足它。
    const distinct = new Set(a).size;
    assert.ok(
      distinct > FRAMES * 0.9,
      `${FRAMES} 帧里只有 ${distinct} 个不同的哈希——画面几乎没在动，` +
        `这条测试也就没在测什么`,
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("从中途直接开渲，与从头渲到那里结果相同", async () => {
  // 导出的 --from 正是这么用的。粒子是唯一有状态的一层，clock 会从 0
  // 重放，所以理论上成立——而"理论上成立"正是最容易骗人的地方。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const MID = 300;
    const TAIL = 60;

    const full = await collect(page, 0, MID + TAIL, FPS);
    const partial = await collect(page, MID, MID + TAIL, FPS);

    for (let i = 0; i < TAIL; i++) {
      assert.equal(
        partial[i],
        full[MID + i],
        `第 ${MID + i} 帧不一致（t=${((MID + i) / FPS).toFixed(3)}s）——` +
          `从中途开渲与从头渲到那里画出了不同的帧`,
      );
    }
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("倒着渲一整段，与正着渲结果相同", async () => {
  // 比"乱序渲三帧"强得多：倒序会让每一帧都触发 advanceOrRewind 的重放
  // 分支，把粒子世界从 0 重建 120 次。任何残留状态都会在这里现形。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const N = 120;
    const forward = await collect(page, 0, N, FPS);

    const backward = await page.evaluate(
      ({ N, fps }) => {
        const app = murRippleApp.createApp({
          doc: document,
          canvas: document.getElementById("cv"),
          timelineDoc: window.__HARNESS_DOC__,
          mode: "offline",
        });
        app.resize();
        app.setAudio(window.__HARNESS_AUDIO__);
        const out = new Array(N);
        for (let i = N - 1; i >= 0; i--) {
          app.renderFrame(i / fps);
          out[i] = app.frameHash();
        }
        return out;
      },
      { N, fps: FPS },
    );

    for (let i = 0; i < N; i++) {
      assert.equal(
        backward[i],
        forward[i],
        `第 ${i} 帧不一致——倒序渲染暴露出了残留状态`,
      );
    }
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});
