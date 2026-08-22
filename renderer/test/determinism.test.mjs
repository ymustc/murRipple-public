import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const harness = `file://${resolve(here, "harness.html")}`;

const FRAMES = [0, 0.25, 1, 2.5, 4.99, 5, 7.5, 9.9];

/** 开一个全新的浏览器上下文跑一遍，返回逐帧哈希。 */
async function runOnce(browser, frames) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(harness);
  const hashes = await page.evaluate((ts) => {
    const app = window.__HARNESS__;
    return ts.map((t) => {
      app.renderFrame(t);
      return app.frameHash();
    });
  }, frames);
  await ctx.close();
  return { hashes, errors };
}

test("同一 timeline 两次独立运行，逐帧哈希完全一致", async () => {
  const browser = await chromium.launch();
  try {
    const a = await runOnce(browser, FRAMES);
    const b = await runOnce(browser, FRAMES);

    assert.deepEqual(a.errors, [], `第一次运行有页面错误：${a.errors.join("; ")}`);
    assert.deepEqual(b.errors, [], `第二次运行有页面错误：${b.errors.join("; ")}`);
    assert.deepEqual(a.hashes, b.hashes, "两次独立运行的逐帧哈希必须完全相同");
  } finally {
    await browser.close();
  }
});

test("不同时间点画出不同的帧——否则哈希一致毫无意义", async () => {
  const browser = await chromium.launch();
  try {
    const { hashes } = await runOnce(browser, FRAMES);
    assert.ok(
      new Set(hashes).size > 1,
      `所有帧的哈希都相同（${hashes[0]}），说明画面根本没变，这个测试就是摆设`,
    );
  } finally {
    await browser.close();
  }
});

test("实时模式与离线模式画出同一帧", async () => {
  // M2 spec 第 11 节验收第 2 条。M2-1 的画面还不读 quality，所以现在是
  // 平凡通过——但设施必须现在就立起来：等 M2-2 的层开始按 quality 调
  // 密度时，这条测试是唯一守着"降级只能改密度、不能改几何"的东西。
  const browser = await chromium.launch();
  try {
    const hashesFor = async (mode, quality) => {
      const ctx = await browser.newContext();
      const page = await ctx.newPage();
      await page.goto(harness);
      const out = await page.evaluate(
        ({ mode, quality, ts }) => {
          const app = murRippleApp.createApp({
            doc: document,
            canvas: document.getElementById("cv"),
            timelineDoc: window.__HARNESS_DOC__,
            mode,
            quality,
          });
          app.resize();
          app.setAudio(window.__HARNESS_AUDIO__);
          return ts.map((t) => {
            app.renderFrame(t);
            return app.frameHash();
          });
        },
        { mode, quality, ts: FRAMES },
      );
      await ctx.close();
      return out;
    };

    const offline = await hashesFor("offline", 1);
    const realtime = await hashesFor("realtime", 1);
    assert.deepEqual(realtime, offline, "同 quality 下两种模式必须画出同一帧");
  } finally {
    await browser.close();
  }
});

test("实时模式下不同 quality 必须画出不同的帧", async () => {
  // 这条守的是降级路径本身。评审用 mutant 证实过：把 background.js 与
  // waveform.js 里的 quality 三元表达式替换成常量（等于删掉降级逻辑），
  // 81 个测试仍然全绿——代码是对的，但没人守着。
  //
  // 注意它与上一条测试的方向相反：上一条断言"同 quality 下两种模式
  // 画出同一帧"，这一条断言"同模式下不同 quality 画出不同帧"。两条
  // 合起来才说清楚 quality 该影响什么、不该影响什么。
  const browser = await chromium.launch();
  try {
    const hashesFor = async (quality) => {
      const ctx = await browser.newContext();
      const page = await ctx.newPage();
      await page.goto(harness);
      const out = await page.evaluate(
        ({ quality, ts }) => {
          const app = murRippleApp.createApp({
            doc: document,
            canvas: document.getElementById("cv"),
            timelineDoc: window.__HARNESS_DOC__,
            mode: "realtime",
            quality,
          });
          app.resize();
          app.setAudio(window.__HARNESS_AUDIO__);
          return ts.map((t) => {
            app.renderFrame(t);
            return app.frameHash();
          });
        },
        { quality, ts: FRAMES },
      );
      await ctx.close();
      return out;
    };

    const full = await hashesFor(1);
    const degraded = await hashesFor(0.5);
    assert.notDeepEqual(
      degraded,
      full,
      "quality=0.5 与 quality=1 画出了完全相同的帧——降级逻辑没有生效或已被删掉",
    );
  } finally {
    await browser.close();
  }
});

test("乱序渲染与顺序渲染得出同一帧", async () => {
  const browser = await chromium.launch();
  try {
    const ordered = await runOnce(browser, [1, 2, 3]);
    const shuffled = await runOnce(browser, [3, 1, 2]);
    const map = new Map([
      [3, shuffled.hashes[0]],
      [1, shuffled.hashes[1]],
      [2, shuffled.hashes[2]],
    ]);
    assert.equal(map.get(1), ordered.hashes[0], "t=1 的帧不应受渲染顺序影响");
    assert.equal(map.get(2), ordered.hashes[1], "t=2 的帧不应受渲染顺序影响");
  } finally {
    await browser.close();
  }
});

test("放到结尾闲置很久之后回到同一个 t，必须画出同一帧", async () => {
  // 本次改动（播完之后把主循环拿到的 t 钳在曲长上）唯一可能破坏确定性的
  // 地方就在这里：世界被"停"在结尾之后，再回到曲中，画出来的必须与从来
  // 没放到过结尾时一模一样。
  //
  // 判决性：把 clock.advanceOrRewind 里的倒带分支删掉（只前进不回退），
  // 这一条会红而上面"两次独立运行哈希一致"仍然全绿——那条测的是两次
  // 干净运行，压根不经过"先到结尾再回来"这条路径。
  const browser = await chromium.launch();
  try {
    const T = 3.5;
    const DUR = 10; // harness.html 的 meta.duration

    const clean = await (async () => {
      const ctx = await browser.newContext();
      const page = await ctx.newPage();
      await page.goto(harness);
      const h = await page.evaluate((t) => {
        window.__HARNESS__.renderFrame(t);
        return window.__HARNESS__.frameHash();
      }, T);
      await ctx.close();
      return h;
    })();

    const afterIdling = await (async () => {
      const ctx = await browser.newContext();
      const page = await ctx.newPage();
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto(harness);
      const r = await page.evaluate(
        ({ t, dur }) => {
          const app = window.__HARNESS__;
          // 正常播到尾
          for (let x = 0; x <= dur; x += 1 / 60) app.renderFrame(x);
          // 放完之后闲置：主循环仍在跑，但拿到的 t 被钳死在曲长上
          const pinned = [];
          app.renderFrame(dur);
          // 第一帧会把世界补到真正的曲末：上面那个 x += 1/60 的循环因为
          // 浮点累积停在 9.983 附近（1198 步），补到 10 是 1200 步。要问的
          // 是"补齐之后还会不会再涨"，所以基准取这一帧之后，不是循环之后。
          const stepsAtEnd = app.clock.steps;
          for (let i = 0; i < 600; i++) {
            app.renderFrame(dur);
            if (i % 200 === 0) pinned.push(app.frameHash());
          }
          const stepsAfterIdle = app.clock.steps;
          // 回到曲中。**步数必须在这一步之前读**：它会把时钟倒带到 t，
          // 读晚了量到的是倒带后的 420 步而不是结尾处的步数（第一版就是
          // 这么写的，测试当场把这个读数时机的错误抓了出来）。
          app.renderFrame(t);
          return { back: app.frameHash(), pinned, stepsAtEnd, stepsAfterIdle };
        },
        { t: T, dur: DUR },
      );
      await ctx.close();
      return { ...r, errors };
    })();

    assert.deepEqual(afterIdling.errors, [], afterIdling.errors.join("; "));
    assert.equal(
      afterIdling.back,
      clean,
      "先放到结尾、闲置 600 帧、再回到 t=3.5，画出来的必须与干净渲染同一帧",
    );
    // 顺带把"钳住之后画面是静止的"钉下来：这既是确定性的直接推论，也是
    // 报告里"结尾之后每帧都在重画同一张图"那条结论的依据。
    assert.equal(
      new Set(afterIdling.pinned).size,
      1,
      `t 被钳死之后每一帧都该是同一张图，实得 ${afterIdling.pinned.length} 种不同哈希`,
    );
    // 时钟确实停住了：闲置那 600 帧一步都不该再走。
    assert.equal(
      afterIdling.stepsAfterIdle,
      afterIdling.stepsAtEnd,
      `t 钳在曲长上闲置 600 帧，世界不该再步进；实际多走了 ` +
        `${afterIdling.stepsAfterIdle - afterIdling.stepsAtEnd} 步`,
    );
    assert.equal(
      afterIdling.stepsAtEnd,
      Math.round(DUR * 120),
      `世界该正好停在曲末（${Math.round(DUR * 120)} 步 = 曲长 × 120Hz），` +
        `实得 ${afterIdling.stepsAtEnd}`,
    );
  } finally {
    await browser.close();
  }
});
