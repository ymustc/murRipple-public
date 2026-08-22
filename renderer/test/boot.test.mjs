/**
 * boot() 的接线。
 *
 * boot 只在打包产物里执行，ui-harness 装配的是各个 ui 模块而不走 boot。
 * 于是空格键、拖拽的三个回调、idle 的事件监听、主循环调不调 update——
 * 一条测试都没有。判决性实验：把 boot 整个改成抛异常，136 条测试全绿。
 *
 * 这里用伪产物页（boot-harness.html）让 boot 真的跑起来，音频时钟由
 * 测试推进，所以"暂停后时间不再前进"这类断言不必靠 sleep。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const harness = `file://${resolve(here, "boot-harness.html")}`;

/** 打开伪产物页并等 boot 装配完成（标题页消失即为成功）。 */
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

/** 推进假音频时钟并等主循环画过至少一帧。 */
async function tick(page, seconds) {
  await page.evaluate((s) => {
    window.__AUDIO_CLOCK__ += s;
  }, seconds);
  await page.evaluate(
    () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))),
  );
}

test("标题页环上的声部名也是七个——main.js 把 lanes 传给了 createTitle", async () => {
  // title.js 原先直接读写死的 VOICES 常量；Task 6 把它换成 buildVoiceRows，
  // 但 createTitle 本身不再自带 lanes，得靠 main.js 的 boot() 显式传
  // app.timeline.lanes 才能算对。这条测试在标题页关闭之前（booted() 会
  // 等标题页消失）就读 DOM，专门盯 main.js 这一处接线有没有漏传。
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
    assert.equal(count, 7, `标题页环上应有七个声部名，实得 ${count}`);
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("boot 装配完成后主循环真的在推动界面", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    await tick(page, 12);
    const r = await page.evaluate(() => ({
      time: document.getElementById("mr-time").textContent,
      fill: document.getElementById("mr-fill").style.width,
      meters: [...document.querySelectorAll(".mr-meter > i")].map((i) =>
        parseFloat(i.style.width),
      ),
    }));
    assert.equal(r.time, "0:12 / 4:30", `走带条时间没跟上，实得 ${r.time}`);
    assert.notEqual(r.fill, "0%", "进度条填充没动");
    assert.ok(
      r.meters.length === 7 && r.meters.some((h) => h > 2),
      `七条电平条应有读数，实得 ${JSON.stringify(r.meters)}`,
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("声部面板真的渲染出七行——四首真歌这一路不会被合成曲那档带跑（Task 6）", async () => {
  // 与 boot-nine.test.mjs 的同名断言成对：这条是在真正渲染出来的 DOM
  // 面板上验行数，不是只调 buildVoiceRows 这个纯函数。boot-harness.html
  // 的 lanes 仍是六条真歌形状，buildVoiceRows 被改成永远返回写死的七行
  // 时，这里应该继续数出 7——四条这一路必须正确地保持绿，不能被"写死七
  // 行"这种变异带偏，因为七行原本就是真歌的正确答案。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    const r = await page.evaluate(() => ({
      rows: document.querySelectorAll(".mr-voice").length,
      meters: document.querySelectorAll(".mr-meter > i").length,
      stems: [...document.querySelectorAll(".mr-voice")].map((row) => row.dataset.stem),
    }));
    assert.equal(r.rows, 7, `真歌面板应有七行（1 人声 + 6 条轨道），实得 ${r.rows}`);
    assert.equal(r.meters, 7, `七条电平条，实得 ${r.meters}`);
    assert.equal(
      r.stems.filter((s) => s === "drums").length,
      3,
      `三行鼓（撼岳/裂帛/碎玉）应共用 drums，实得 ${JSON.stringify(r.stems)}`,
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("空格永远切播放/暂停，不会误触焦点控件", async () => {
  // 设计决定：空格是播放器的通用约定，永远归播放/暂停。只让全局处理器
  // 让路是不够的——浏览器会用空格激活焦点控件，必须 preventDefault。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    await tick(page, 5);

    await page.keyboard.press("Space");
    await tick(page, 0); // 图标只在主循环的 hud.update 里更新，得等一帧
    const paused = await page.evaluate(() => ({
      icon: document.getElementById("mr-play").textContent,
      time: document.getElementById("mr-time").textContent,
    }));
    assert.equal(paused.icon, "▶", "暂停后图标该是 ▶");

    await tick(page, 4);
    const stillPaused = await page.textContent("#mr-time");
    assert.equal(stillPaused, paused.time, "暂停后时间不该继续走");

    await page.keyboard.press("Space");
    await tick(page, 3);
    assert.notEqual(
      await page.textContent("#mr-time"),
      paused.time,
      "再按空格应恢复播放",
    );

    // 点过静音钮之后按空格：切的必须是播放，不能是那个按钮
    await page.click('.mr-voice[data-stem="drums"]');
    const mutedBefore = await page.evaluate(() =>
      window.__murRipple.mute.isMuted("drums"),
    );
    const iconBefore = await page.textContent("#mr-play");
    await page.keyboard.press("Space");
    await tick(page, 0);
    const after = await page.evaluate(() => ({
      muted: window.__murRipple.mute.isMuted("drums"),
      icon: document.getElementById("mr-play").textContent,
    }));
    assert.equal(
      after.muted,
      mutedBefore,
      "点过静音钮后按空格，把静音又切了回去——光让全局处理器让路没用，" +
        "浏览器会用空格激活焦点按钮，必须 preventDefault",
    );
    assert.notEqual(after.icon, iconBefore, "空格该切播放状态");
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("拖拽只预览不重放，松手才把世界对齐到落点", async () => {
  // 这条守的是 previewFrame 存在的唯一理由。写成无条件 renderFrame 时它
  // 是红的——而那正是实现里真实存在过的 bug：向左拖每帧都从 0 全量重放。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    await tick(page, 40);

    const box = await page.locator("#mr-bar").boundingBox();
    const stepsBefore = await page.evaluate(() => window.__murRipple.clock.steps);

    await page.mouse.move(box.x + box.width * 0.8, box.y + box.height / 2);
    await page.mouse.down();
    for (const f of [0.7, 0.55, 0.4, 0.25]) {
      await page.mouse.move(box.x + box.width * f, box.y + box.height / 2);
      await tick(page, 0);
    }
    const during = await page.evaluate(() => ({
      steps: window.__murRipple.clock.steps,
      time: document.getElementById("mr-time").textContent,
    }));
    assert.equal(
      during.steps,
      stepsBefore,
      `拖拽中不该推进或重放世界（${stepsBefore} → ${during.steps}）——` +
        `主循环必须在 scrubT 非 null 时走 previewFrame`,
    );
    assert.notEqual(during.time, "0:40 / 4:30", "拖拽中画面时间应跟着指针走");

    await page.mouse.up();
    await tick(page, 0);
    const after = await page.evaluate(() => ({
      steps: window.__murRipple.clock.steps,
      lastStart: window.__SRC_STARTS__.at(-1),
    }));
    const wantT = 270 * 0.25;
    assert.ok(
      Math.abs(after.steps / 120 - wantT) < 3,
      `松手后世界应对齐到落点 ${wantT}s，实得 ${after.steps / 120}s`,
    );
    assert.ok(
      Math.abs(after.lastStart - wantT) < 3,
      `音频也应从落点起播，实得 ${after.lastStart}`,
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("暂停中点走带条只挪位置，不自动开始播放", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    await page.keyboard.press("Space"); // 先暂停
    await tick(page, 0);
    assert.equal(await page.textContent("#mr-play"), "▶");

    const box = await page.locator("#mr-bar").boundingBox();
    await page.mouse.click(box.x + box.width * 0.3, box.y + box.height / 2);
    await tick(page, 2);

    assert.equal(
      await page.textContent("#mr-play"),
      "▶",
      "用户显式暂停后只想挪个位置，不该被强制开始播放",
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("点静音钮真的会去动音频增益", async () => {
  // ui-harness 的 onToggle 只做自己的记账，player.applyMute 那一段在 boot 里，
  // 于是"点按钮 → 声音变小"这条链路此前从头到尾没人守。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    await page.evaluate(() => {
      window.__MUTE_WRITES__.length = 0;
    });
    await page.click('.mr-voice[data-stem="bass"]');
    const writes = await page.evaluate(() => window.__MUTE_WRITES__);
    assert.deepEqual(
      writes,
      ["stem1=1", "stem2=1", "stem3=0", "stem4=1"],
      `静音贝斯时只有第三条 stem 该压到 0，实得 ${JSON.stringify(writes)}`,
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("界面显隐是手动的：H 键切换，收起后点画面也能回来", async () => {
  // 触屏没有键盘，只留快捷键等于把人锁在外面——收起后必须还能靠点击回来。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    const hidden = () =>
      page.evaluate(() =>
        document.getElementById("mr-ui").classList.contains("mr-hidden"),
      );

    assert.equal(await hidden(), false, "默认必须是常驻，不做闲置自动淡出");

    await page.click("#mr-hide");
    assert.equal(await hidden(), true, "点收起按钮应当收起");

    // 收起状态下子元素 pointer-events:none，点击落到画布上
    await page.mouse.click(200, 200);
    assert.equal(await hidden(), false, "收起后点画面任意处必须能恢复");

    await page.keyboard.press("KeyH");
    assert.equal(await hidden(), true, "H 键应当收起");
    await page.keyboard.press("KeyH");
    assert.equal(await hidden(), false, "H 键应当能再切回来");
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("界面不会自己消失", async () => {
  // 这条守的是"不做闲置自动淡出"这个决定本身。光靠上一条的初始断言不够：
  // 那是装配后立刻读的，两秒后才淡出的实现照样通过。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    await page.waitForTimeout(3000); // 比原先的 2 秒闲置阈值长
    assert.equal(
      await page.evaluate(() =>
        document.getElementById("mr-ui").classList.contains("mr-hidden"),
      ),
      false,
      "播放中放着不动三秒，界面不该自己消失",
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

// ── 播完之后那摊事 ────────────────────────────────────────────────
//
// 这几条只能在这里测：togglePlay、主循环喂给 hud 的播放状态、走带条松手
// 续播的判据，全都是 boot() 里的闭包，ui-harness 装配不到，纯函数测不着。
// 假音频时钟由测试自己推（__AUDIO_CLOCK__），所以"放完"是确定性的，不靠等。
//
// boot-harness 的 meta.duration 是 270，假 buffer 只有 12 秒——播放器按
// **传进来的曲长**判定结尾（见 audio.js 顶部那段说明），所以这里要推过 270。

test("放完之后播放键说实话：不再显示'正在放'", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    await tick(page, 100);
    assert.equal(
      await page.textContent("#mr-play"),
      "❚❚",
      "曲中就该显示'正在放'，否则下面那条断言毫无意义",
    );

    await tick(page, 175); // 累计 275 > 曲长 270
    await tick(page, 0);
    const after = await page.evaluate(() => ({
      icon: document.getElementById("mr-play").textContent,
      time: document.getElementById("mr-time").textContent,
    }));
    assert.equal(
      after.icon,
      "▶",
      "放完之后播放键仍显示 ❚❚ 就是在骗人——一点声音都没有了",
    );
    assert.equal(after.time, "4:30 / 4:30", "计时器该停在总时长上");
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("放完之后再按播放：从头放，不是从结尾起播（那样一点声音都没有）", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    await tick(page, 275); // 放过结尾
    await tick(page, 0);

    await page.evaluate(() => { window.__SRC_STARTS__.length = 0; });
    await page.keyboard.press("Space");
    await tick(page, 0);

    const starts = await page.evaluate(() => window.__SRC_STARTS__);
    assert.ok(starts.length > 0, "按下播放该真的起播 source，实际一条都没起");
    assert.deepEqual(
      [...new Set(starts)],
      [0],
      `放完之后按播放，每条分轨都该从 0 起播；实得 ${JSON.stringify(starts)}` +
        "（若是 270 附近，说明还在从结尾'续播'，用户听不到任何声音）",
    );
    assert.equal(
      await page.textContent("#mr-play"),
      "❚❚",
      "从头放起来之后，播放键该回到'正在放'",
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("放完之后拖回曲中，仍然照常续播", async () => {
  // 上一棒在真产物上验过：4:30 放完 → 拖回 → 继续走。onScrub 记的若是
  // player.playing（放完后为 false）而不是 player.running，这条就会红。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    await tick(page, 275);
    await tick(page, 0);

    const box = await page.locator("#mr-bar").boundingBox();
    assert.ok(box && box.y >= 0 && box.y + box.height <= 520 + 1,
      `走带条必须在视口内才谈得上点得中，实得 ${JSON.stringify(box)}`);
    await page.evaluate(() => { window.__SRC_STARTS__.length = 0; });
    await page.mouse.click(box.x + box.width * 0.25, box.y + box.height / 2);
    await tick(page, 0);

    // 一次拖拽只该把各分轨重起**一遍**。
    //
    // 这条是变异检验逼出来的：onScrub 里"记 wasPlaying"与"要不要 pause"
    // 两行若看的状态不一致（一个 running、一个 playing），放完之后拖回去
    // 会起播两次——player.seek() 见 running 仍挂着自己先起了一次，
    // onScrubEnd 的 start() 又起一次，所有分轨被停掉重起两遍。下面那几条
    // 断言全都看不见它：最终结果一样是"从 t 继续放"。
    const starts = await page.evaluate(() => window.__SRC_STARTS__);
    assert.equal(
      starts.length,
      4,
      `一次拖拽该只起播一遍（四条分轨各一次），实得 ${starts.length} 次：` +
        `${JSON.stringify(starts)}——八次说明所有分轨被停掉重起了两遍`,
    );

    const seeked = await page.textContent("#mr-time");
    assert.equal(seeked, "1:07 / 4:30", `拖回 25% 该显示 1:07，实得 ${seeked}`);
    assert.equal(
      await page.textContent("#mr-play"),
      "❚❚",
      "放完之后拖回曲中，应恢复播放（走带条看的是 running，不是 playing）",
    );

    await tick(page, 3);
    assert.notEqual(
      await page.textContent("#mr-time"),
      seeked,
      "拖回之后时间该继续走，不能停在原地",
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("放完之后闲置，粒子世界不再被无限步进", async () => {
  // 这是"CPU 在放完的歌上一直烧"里唯一由本次改动负责的那一份：主循环拿到
  // 的 t 被钳在曲长上，clock.advanceTo 于是不再推进。实测（见报告）它只占
  // 总开销的约 1 个百分点——不严重，但确实是白烧的，而且它同时是"播放键
  // 说实话"的同一处改动带来的，不额外付代价。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await booted(browser);
    await tick(page, 275);
    await tick(page, 0);
    const s0 = await page.evaluate(() => window.__murRipple.clock.steps);
    await tick(page, 60); // 又过了一分钟
    await tick(page, 0);
    const s1 = await page.evaluate(() => window.__murRipple.clock.steps);
    assert.equal(
      s1,
      s0,
      `放完之后又闲置 60 秒，时钟不该再走；实际多走了 ${s1 - s0} 步` +
        "（改动之前是 120 步/秒，一直烧下去）",
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});
