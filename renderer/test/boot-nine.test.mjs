/**
 * boot() 在九条分轨（合成曲量级）下的接线。
 *
 * boot.test.mjs 用的 boot-harness.html 只声明四条分轨——那是四首真歌走的
 * 那一路，必须继续有人守，不能因为要测九条就把它改掉。但四条夹具下
 * "解码循环按 timeline.stems 遍历" 与 "解码循环写死四条" 行为完全相同，
 * 测不出走的是哪一条。这份文件用 boot-harness-nine.html（九条分轨）单独
 * 守住这一路：真歌与合成曲是两种不同的行为（点一行鼓联动三行 vs 点一行
 * 只动它自己），本来就该是两条测试，不是一份夹具改来改去。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const harness = `file://${resolve(here, "boot-harness-nine.html")}`;

async function booted(browser) {
  const page = await (
    await browser.newContext({ viewport: { width: 900, height: 520 } })
  ).newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(e.message));
  await page.goto(harness);
  await page.click("#mr-start");
  await page.waitForFunction(() => !document.getElementById("mr-title"), null, {
    timeout: 20000,
  });
  return { page, errs };
}

test("标题页环上的声部名也是九个——main.js 把 lanes 传给了 createTitle", async () => {
  // 与 boot.test.mjs 的同名断言成对，见那边的注释。
  const browser = await chromium.launch();
  try {
    const page = await (
      await browser.newContext({ viewport: { width: 900, height: 520 } })
    ).newPage();
    const errs = [];
    page.on("pageerror", (e) => errs.push(e.message));
    await page.goto(harness);
    const count = await page.evaluate(
      () => document.querySelectorAll("#mr-t-names i").length,
    );
    assert.equal(count, 9, `标题页环上应有九个声部名，实得 ${count}`);
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("九条分轨全部解码、全部起播——不是只有写死的前四条", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    // player.start(0) 在 boot 完成时恰好跑过一次：这一刻 __SRC_STARTS__
    // 里的条数就是"实际起播的分轨数"。写死四条的错误实现在这份九条夹具
    // 下只会有 4 条，而不是 9 条。
    const starts = await page.evaluate(() => window.__SRC_STARTS__.length);
    assert.equal(
      starts,
      9,
      `九条分轨都应解码并起播，实得 ${starts} 条——这正是"只解出前四条"` +
        `那类缺陷会露出来的地方`,
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("声部面板真的渲染出九行——不是写死的七行（Task 6）", async () => {
  // 这条是在真正渲染出来的 DOM 面板上验行数，不是只调 buildVoiceRows 这个
  // 纯函数。boot-harness-nine.html 的 lanes 是八条、逐条独立的 stem，
  // buildVoiceRows 被改成永远返回写死的七行时，这里应该数出 7 而不是 9，
  // 从而变红——见 task-6-report.md 的变异检验一节。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    const r = await page.evaluate(() => ({
      rows: document.querySelectorAll(".mr-voice").length,
      meters: document.querySelectorAll(".mr-meter > i").length,
      stems: [...document.querySelectorAll(".mr-voice")].map((row) => row.dataset.stem),
    }));
    assert.equal(r.rows, 9, `合成曲面板应有九行（1 人声 + 8 条轨道），实得 ${r.rows}`);
    assert.equal(r.meters, 9, `九条电平条，实得 ${r.meters}`);
    assert.equal(
      new Set(r.stems).size,
      9,
      `九行应各自指向不同的 stem，没有两行共用一条，实得 ${JSON.stringify(r.stems)}`,
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("合成曲面板上一道连动竖脊都没有，也没有那行说明", async () => {
  // 归组标记是从 lane.stem 推出来的。九条轨道各占一条 stem，谁都不与谁
  // 连动——面板上就一个 data-group-pos 都不该出现，说明小字也不该挂。
  //
  // 这一条守的是判据「合成曲九行行行独立，不能出现任何虚假归组暗示」，
  // 守不了「实现是不是硬编码了 kick/snare/hat 一组」——这份 harness 的
  // lane id 是 drums/bass/other/pad/pluck/arp/bell/chime，压根没有 kick/
  // snare/hat 可撞。抓硬编码的是 voices.test.mjs 的「归组只认 stem」。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    const r = await page.evaluate(() => ({
      marked: [...document.querySelectorAll(".mr-voice")]
        .filter((row) => row.dataset.groupPos)
        .map((row) => row.dataset.lane),
      note: document.querySelectorAll(".mr-voice-note").length,
      stems: [...document.querySelectorAll(".mr-voice")].map((row) => row.dataset.stem),
    }));
    assert.equal(
      new Set(r.stems).size,
      r.stems.length,
      `前提：九行本来就该各占一条 stem，实得 ${JSON.stringify(r.stems)}`,
    );
    assert.deepEqual(
      r.marked,
      [],
      `九行逐轨独立，不该有归组标记，实得 ${JSON.stringify(r.marked)}`,
    );
    assert.equal(r.note, 0, "没有连动就不该出现解释连动的那行小字");
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("本轮新拟的四个声部名（泠泠/霜铎/流岚/缥缈）真的显示在面板上，不是退回 lane.label", async () => {
  // 评审指出：pad/pluck/arp/bell 这四个 LABELS 条目此前一条断言都没有——
  // 把 voices.js 里这四条从 LABELS 表整个删掉，238 条测试照样全绿（面板
  // 退回 lane.label，画布静默跳过，errs 仍是空数组）。这条断言直接盯着
  // 渲染出来的文本，不是盯 LABELS 这个数据结构本身。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    const names = await page.evaluate(() =>
      Object.fromEntries(
        [...document.querySelectorAll(".mr-voice")].map((row) => [
          row.dataset.lane,
          row.querySelector(".mr-name b").textContent,
        ]),
      ),
    );
    // boot-harness-nine.html 里这四条 lane 的 label 字段就是它们自己的
    // id（例如 { id:"pad", label:"pad" }）——如果面板显示的是 "pad" 而
    // 不是 "流岚"，说明 LABELS 表根本没被用上，退回了 lane.label 兜底。
    assert.equal(names.pad, "流岚", `pad 应显示 LABELS 里的"流岚"，实得 ${names.pad}`);
    assert.equal(names.pluck, "缥缈", `pluck 应显示 LABELS 里的"缥缈"，实得 ${names.pluck}`);
    assert.equal(names.arp, "泠泠", `arp 应显示 LABELS 里的"泠泠"，实得 ${names.arp}`);
    assert.equal(names.bell, "霜铎", `bell 应显示 LABELS 里的"霜铎"，实得 ${names.bell}`);
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("环外小字（导出 MP4 里唯一会出现名字的地方）九条 lane 一条不落，都有非空标签", async () => {
  // 评审的推理链：render.mjs 逐帧导出的是 canvas，侧栏是 DOM 浮层——不进
  // MP4。laneLabels.js 原来 `LABELS[lane.id]?.zh` 查不到就 `if (!label)
  // return`，悄悄跳过不画。boot-harness-nine.html 的 lanes 里 drums/
  // other/chime 三个 id 不在 LABELS 表里，缺兜底时会让导出的 MP4 出现
  // "4 个声部有名字、5 个没有"这种半身不遂的画面。
  //
  // 断言直接读**这份 harness 实际装配出来的** window.__murRipple.timeline
  // .lanes，不是另起一份手写的 lane 数组去重复 boot-harness-nine.html 的
  // 内容——夹具的 lanes 以后要是改了，这条测试跟着自动测新的那一份，不会
  // 变成"测的是一份早已过时的影子数据"。
  //
  // 四条真歌那份夹具（boot.test.mjs）故意不配同款断言：控制器已实测
  // LABELS 的键集合 {kick,snare,hat,bass,mid,air,pad,pluck,arp,bell} 完
  // 全覆盖四首真歌用到的六个 lane id（并集 {air,bass,hat,kick,mid,
  // snare}，取自 tests/fixtures/real-songs-baseline.json），四条那份对
  // 这个缺兜底的缺陷天然是盲的——断言写在那份夹具上会永远绿，等于没测。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    const rows = await page.evaluate(() =>
      window.__murRipple.timeline.lanes.map((lane) => ({
        id: lane.id,
        label: murRippleApp.labelFor(lane),
      })),
    );
    assert.equal(rows.length, 8, `这份 harness 应有八条 lane，实得 ${rows.length}`);
    const missing = rows.filter((r) => !r.label).map((r) => r.id);
    assert.deepEqual(
      missing,
      [],
      `以下 lane 在环外小字里没有标签，导出的 MP4 里这几条会没有名字：${JSON.stringify(missing)}`,
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("点静音钮：九条分轨时只压其中一条，其余八条原样写 1——不是只有四条", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    await page.evaluate(() => {
      window.__MUTE_WRITES__.length = 0;
    });
    // bass 是九条里的第三条（vocals/drums/bass/…），对应 stem3。
    await page.click('.mr-voice[data-stem="bass"]');
    const writes = await page.evaluate(() => window.__MUTE_WRITES__);
    assert.deepEqual(
      writes,
      [
        "stem1=1", "stem2=1", "stem3=0", "stem4=1", "stem5=1",
        "stem6=1", "stem7=1", "stem8=1", "stem9=1",
      ],
      `九条分轨时静音贝斯应只压第三条、其余八条原样写 1，实得 ${JSON.stringify(writes)}`,
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});
