/**
 * 跳帧：state 没变就不重画。
 *
 * 这组测试守的是两件事，分量完全不同：
 *
 * 一、**跳过的是"画不画"，不是"画成什么"。** 同一个 t 必须永远给出同一帧，
 *     中间跳过多少帧都一样。
 * 二、**失效通道不许漏。** 凡是在 t 不变时也能改变画面的输入，都必须能让
 *     下一帧重画。漏一个的后果是画面卡住不动——比多烧 CPU 严重得多，
 *     所以这里不满足于"测我想到的那两个"，而是拿 FIELD_ROLE 跟真实的
 *     state 字段逐个对，让"想不到"这件事本身变成红灯。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { FIELD_ROLE, assertFieldsClassified } from "../src/main.js";

const here = dirname(fileURLToPath(import.meta.url));
const harness = `file://${resolve(here, "harness.html")}`;

async function openPage(browser) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(e.message));
  await page.goto(harness);
  return { page, ctx, errs };
}

/** 在页面里现造一个实时模式的 app（harness 自带那个是 offline，不跳帧）。 */
const MAKE_APP = `
(mode) => {
  const cv = document.createElement("canvas");
  cv.style.width = "320px";
  cv.style.height = "200px";
  document.body.appendChild(cv);
  const app = murRippleApp.createApp({
    doc: document, canvas: cv, mode,
    timelineDoc: window.__HARNESS_DOC__,
  });
  app.resize();
  app.setAudio(window.__HARNESS_AUDIO__);
  window.__A = app;
  window.__CV = cv;
  return true;
}`;

// ── 一、穷举：FIELD_ROLE 必须与真实的 state 字段严丝合缝 ──────────────

test("FIELD_ROLE 覆盖 state 的每一个字段，不多不少", async () => {
  // 这是"列举得出"的那条守卫。往 state 里加字段却忘了分类，这里当场红；
  // 在 FIELD_ROLE 里留下 state 已经没有的字段，这里也红。
  //
  // 取真实字段用的是 createApp 已有的 layers 测试口子（"只为测试而存在"），
  // 不为此在生产代码里新开接口。
  const browser = await chromium.launch();
  try {
    const { page, ctx, errs } = await openPage(browser);
    const keys = await page.evaluate(() => {
      const cv = document.createElement("canvas");
      cv.style.width = "200px";
      cv.style.height = "120px";
      document.body.appendChild(cv);
      let seen = null;
      const app = murRippleApp.createApp({
        doc: document,
        canvas: cv,
        mode: "offline",
        timelineDoc: window.__HARNESS_DOC__,
        layers: [{ name: "spy", draw: (g, state) => { seen = Object.keys(state); } }],
      });
      app.resize();
      app.renderFrame(1.25);
      return seen;
    });
    await ctx.close();

    assert.deepEqual(
      [...keys].sort(),
      Object.keys(FIELD_ROLE).sort(),
      "drawAt 组出来的 state 字段与 FIELD_ROLE 对不上——" +
        "新加的字段必须表态是 t / const 还是 key",
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("state 里混进没分类的字段会当场抛错，不是悄悄放过", () => {
  // FIELD_ROLE 的穷举性靠这个运行时检查兜底：上面那条测试盯的是"现在
  // 对得上"，这一条盯的是"对不上时真的会喊"。
  assert.throws(
    () => assertFieldsClassified({ t: 1, hoverLane: null, 新来的字段: 2 }),
    /新来的字段/,
    "多出来的字段必须点名报出来",
  );
  assert.doesNotThrow(() => assertFieldsClassified({ t: 1, hoverLane: null }));
});

test("每个 key 角色的字段都真的进了指纹——逐个改，逐个必须重画", async () => {
  // 判据要求"列举得出"，所以这里不写死"测 hover 和 resize"，而是从
  // FIELD_ROLE 里筛出全部 key 字段，逐个施加一次真实改动，断言画面重画。
  // 少测一个都会被下面的覆盖率断言拦住。
  const keyFields = Object.entries(FIELD_ROLE)
    .filter(([, role]) => role === "key")
    .map(([k]) => k);

  const browser = await chromium.launch();
  try {
    const { page, ctx, errs } = await openPage(browser);
    await page.evaluate(`(${MAKE_APP})("realtime")`);

    const r = await page.evaluate(() => {
      const app = window.__A;
      const cv = window.__CV;
      const out = {};
      const T = 2.5;

      // 先画一帧，再确认"什么都不改就会跳过"——否则下面每一条都是平凡通过
      app.renderFrame(T);
      const base = app.drawStats.drawn;
      app.renderFrame(T);
      out.__不改就跳过 = app.drawStats.drawn === base;

      const probe = (name, mutate) => {
        const before = app.drawStats.drawn;
        const hashBefore = app.frameHash();
        mutate();
        app.renderFrame(T); // t 一个字没动
        out[name] = {
          重画了: app.drawStats.drawn > before,
          画面变了: app.frameHash() !== hashBefore,
        };
      };

      probe("hoverLane", () => app.setHoverLane("kick"));
      probe("audio", () => app.setAudio(null));
      probe("geom", () => { cv.style.width = "480px"; });
      // world 的状态由 simT 代表，两者共用这一个探针：seek 把世界重放到
      // 规范位置，t 一个字不动而 simT 变了（详见下面那条单独的测试）。
      const STEP = 1 / 120;
      const T2 = 5 - STEP * 0.6;
      app.renderFrame(5);
      app.renderFrame(T2); // 容差内后退，simT 停在 5.0
      const w0 = app.drawStats.drawn, h0 = app.frameHash();
      app.seek(T2); // 世界重放到 T2 的规范位置，simT 变成 4.99167
      app.renderFrame(T2); // 同一个 t
      out.simT = { 重画了: app.drawStats.drawn > w0, 画面变了: app.frameHash() !== h0 };
      out.world = out.simT;
      return out;
    });

    const covered = { ...r };
    delete covered.__不改就跳过;

    assert.equal(r.__不改就跳过, true, "什么都不改却仍在重画，跳帧根本没生效");
    for (const f of keyFields) {
      assert.ok(f in covered, `FIELD_ROLE 里的 key 字段 ${f} 没有对应的探针`);
      assert.equal(covered[f].重画了, true, `改了 ${f} 却没有重画——画面会卡住`);
      assert.equal(
        covered[f].画面变了,
        true,
        `改了 ${f} 之后画面居然没变，这个探针没有分辨力，换一个改法`,
      );
    }
    await ctx.close();
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("同一个 t 也可能对应两个世界——simT 必须进指纹", async () => {
  // 反直觉，但实测如此：clock.advanceOrRewind 对**小于一个步长的后退**
  // 有意不倒带（clock.js 里那段容差说明），于是"同一个 t"可以对应相差一步
  // 的两个世界状态，画出来的帧不一样。
  //
  // 这一条是变异检验挖出来的：把 simT 从指纹里删掉时全部测试仍然全绿，
  // 说明当时没有任何测试走到这条路径。补上之后那个变异才会红。
  const browser = await chromium.launch();
  try {
    const { page, ctx, errs } = await openPage(browser);
    const r = await page.evaluate(() => {
      const cv = document.createElement("canvas");
      cv.style.width = "360px";
      cv.style.height = "220px";
      document.body.appendChild(cv);
      const app = murRippleApp.createApp({
        doc: document, canvas: cv, mode: "realtime",
        timelineDoc: window.__HARNESS_DOC__,
      });
      app.resize();
      app.setAudio(window.__HARNESS_AUDIO__);

      const STEP = 1 / 120;
      const T = 5 - STEP * 0.6; // 退不满一个步长
      app.renderFrame(5);
      app.renderFrame(T); // 容差内后退：simT 仍停在 5.0
      const simBefore = app.clock.simT;
      const hashBefore = app.frameHash();
      app.seek(T); // 世界重放到 T 的规范位置
      const simAfter = app.clock.simT;
      app.renderFrame(T); // t 一个字没变
      return { simBefore, simAfter, hashBefore, hashAfter: app.frameHash(), T };
    });
    await ctx.close();

    assert.notEqual(
      r.simBefore, r.simAfter,
      `前提：同一个 t=${r.T} 下 simT 该有两种取值，实得都是 ${r.simBefore}——` +
        "容差行为若改了，这条测试就失去意义，要重新构造",
    );
    assert.notEqual(
      r.hashAfter, r.hashBefore,
      "simT 变了画面却没跟着变——指纹里漏掉 simT 会让画面停在旧世界那一帧",
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

// ── 二、跳过的是"画不画"，不是"画成什么" ──────────────────────────

test("跳帧不改变任何一帧的内容：与从不跳帧的实例逐步比对", async () => {
  // 这是本次改动的主护栏。跑一段带 hover、resize、回跳、重复 t 的脚本，
  // 每一步都拿"会跳帧的实时实例"与"从不跳帧的离线实例"比帧哈希。
  // 两边必须步步相同——跳帧只能省下重画，不能改变画布上的像素。
  const browser = await chromium.launch();
  try {
    const { page, ctx, errs } = await openPage(browser);
    const r = await page.evaluate(() => {
      const mk = (mode) => {
        const cv = document.createElement("canvas");
        cv.style.width = "360px";
        cv.style.height = "220px";
        document.body.appendChild(cv);
        const app = murRippleApp.createApp({
          doc: document, canvas: cv, mode,
          timelineDoc: window.__HARNESS_DOC__,
        });
        app.resize();
        app.setAudio(window.__HARNESS_AUDIO__);
        return { app, cv };
      };
      const rt = mk("realtime");
      const off = mk("offline");

      // 脚本：t 前进、原地停留、hover、取消 hover、改尺寸、回跳
      const script = [
        ["t", 0], ["t", 1], ["t", 1], ["t", 1],
        ["hover", "kick"], ["t", 1], ["t", 1],
        ["hover", null], ["t", 1],
        ["t", 2.5], ["t", 2.5],
        ["size", "300px"], ["t", 2.5],
        ["t", 0.5], ["t", 0.5],
        ["t", 4], ["t", 4], ["t", 4],
      ];
      const pairs = [];
      for (const [op, v] of script) {
        for (const { app, cv } of [rt, off]) {
          if (op === "t") app.renderFrame(v);
          else if (op === "hover") app.setHoverLane(v);
          else if (op === "size") cv.style.width = v;
        }
        if (op === "t") pairs.push([rt.app.frameHash(), off.app.frameHash()]);
      }
      return { pairs, rtStats: { ...rt.app.drawStats }, offStats: { ...off.app.drawStats } };
    });
    await ctx.close();

    const bad = r.pairs.map((p, i) => [i, p]).filter(([, [a, b]]) => a !== b);
    assert.deepEqual(
      bad, [],
      `第 ${bad.map(([i]) => i).join(",")} 步跳帧实例与不跳帧实例画面不同——` +
        "跳帧改变了画面内容，这是最严重的失败",
    );
    assert.ok(
      r.rtStats.skipped > 0,
      `实时实例一帧都没跳过（${JSON.stringify(r.rtStats)}），这条比对毫无意义`,
    );
    assert.equal(
      r.offStats.skipped, 0,
      `离线实例不该跳任何一帧，实得 ${JSON.stringify(r.offStats)}`,
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

// ── 三、两条绕过 renderFrame 的路径，漏了就画面卡住 ────────────────

test("previewFrame 之后必须重画——否则松手落回原位画面会卡在预览那一帧", async () => {
  // 拖拽走带条走的是 previewFrame，它画的是别的 t。松手若正好落回拖拽前
  // 那个 t，指纹一致会被判成"可以跳"，画布就永远停在预览的那一帧上。
  // 这一处是写实现时先想漏、后补上的，所以单独立一条。
  const browser = await chromium.launch();
  try {
    const { page, ctx, errs } = await openPage(browser);
    await page.evaluate(`(${MAKE_APP})("realtime")`);
    const r = await page.evaluate(() => {
      const app = window.__A;
      const T = 2;
      app.renderFrame(T);
      const atT = app.frameHash();
      app.previewFrame(7); // 拖到别处预览
      const preview = app.frameHash();
      app.renderFrame(T); // 松手落回原位
      return { atT, preview, back: app.frameHash() };
    });
    await ctx.close();
    assert.notEqual(r.preview, r.atT, "前提：预览的那一帧本来就该与 t=2 不同");
    assert.equal(
      r.back, r.atT,
      "松手落回 t=2 之后画面仍停在预览那一帧——previewFrame 没有作废指纹",
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("resize 之后必须重画——给 canvas.width 赋值会清空画布，哪怕尺寸没变", async () => {
  // resize() 里 canvas.width = geom.W 是无条件赋值，而给 canvas.width 赋值
  // **本身就会清空画布**，赋的是同一个数也照清。若 resize 不作废指纹，
  // 一次尺寸没变的 resize 事件（滚动条出现、旋转到同尺寸）会留下一张空白
  // 画布，而指纹显示"没变、可以跳"——画面就此全黑。
  const browser = await chromium.launch();
  try {
    const { page, ctx, errs } = await openPage(browser);
    await page.evaluate(`(${MAKE_APP})("realtime")`);
    const r = await page.evaluate(() => {
      const app = window.__A;
      const T = 3;
      app.renderFrame(T);
      const before = app.frameHash();
      app.resize(); // 尺寸一个像素都没变，但画布被清空了
      const cleared = app.frameHash();
      app.renderFrame(T); // 同一个 t
      return { before, cleared, after: app.frameHash() };
    });
    await ctx.close();
    assert.notEqual(
      r.cleared, r.before,
      "前提：resize() 确实把画布清空了，否则这条测试测不到东西",
    );
    assert.equal(
      r.after, r.before,
      "resize 之后同一个 t 没有重画，画面停在被清空的状态——resize 漏了作废",
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("离线模式一帧都不跳——MP4 那条路不走跳帧分支", async () => {
  const browser = await chromium.launch();
  try {
    const { page, ctx, errs } = await openPage(browser);
    await page.evaluate(`(${MAKE_APP})("offline")`);
    const stats = await page.evaluate(() => {
      const app = window.__A;
      for (let i = 0; i < 20; i++) app.renderFrame(1.5); // 同一个 t 反复渲
      return { ...app.drawStats };
    });
    await ctx.close();
    assert.equal(stats.skipped, 0, `离线模式不该跳帧，实得 ${JSON.stringify(stats)}`);
    assert.equal(stats.drawn, 20, `离线模式该老老实实画满 20 帧，实得 ${stats.drawn}`);
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});
