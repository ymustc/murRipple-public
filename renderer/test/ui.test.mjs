/**
 * 界面全部在浏览器里测——零依赖意味着没有 jsdom，而这几个模块的产出
 * 就是 DOM 与事件，没有浏览器就没有意义。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));
const harness = `file://${resolve(here, "ui-harness.html")}`;

async function openPage(browser) {
  const page = await (
    await browser.newContext({ viewport: { width: 900, height: 520 } })
  ).newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(e.message));
  await page.goto(harness);
  return { page, errs };
}

/**
 * 产物真正用的那份样式（template.html 的 <style> 块）。
 *
 * ui-harness.html 自己那份 CSS 只是"最小子集，测的是行为不是外观"，用它
 * 去断言画面等于自问自答：竖脊从 template.html 里整段删掉，harness 照样
 * 绿。要守住"界面不骗人"就必须读发出去的那一份。
 */
function shippedStyle() {
  const html = readFileSync(resolve(here, "..", "template.html"), "utf8");
  const m = html.match(/<style>([\s\S]*?)<\/style>/);
  if (!m) throw new Error("template.html 里找不到 <style> 块");
  return m[1];
}

test("layers 之外没人往 canvas 上画", async () => {
  // 本期最要紧的一条。M3 逐帧抓 canvas 导出，任何画进 canvas 的界面元素
  // 都会被烤进每一帧视频里，等到 M3 才发现就得推倒重来。
  //
  // 最初的写法是「隐藏 DOM 覆盖层，比对隐藏前后的帧哈希」——那是同义
  // 反复：DOM 与 canvas 本来就互不影响，隐藏与否当然一样。往 renderFrame
  // 里加一条白带做变异，那条测试照样是绿的。
  //
  // 真正该问的是：除了 LAYERS 的循环，还有没有别的东西在画？传空层集渲
  // 一帧，画面必须是纯背景色，多一笔都说明有东西绕过了图层机制。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const r = await page.evaluate(() => {
      const cv = document.getElementById("cv");
      const bare = murRippleApp.createApp({
        doc: document,
        canvas: cv,
        timelineDoc: window.__HARNESS_DOC__,
        mode: "offline",
        layers: [],
      });
      bare.resize();
      bare.setAudio(window.__HARNESS_AUDIO__);
      bare.renderFrame(3.5);
      // 主循环每帧还会调这两个；只在 renderFrame 之后取样，它们往 canvas
      // 上画的东西看不见——而那同样会被烤进 M3 导出的每一帧。
      window.__UI__.hud.update(3.5, true);
      window.__UI__.voices.update(3.5);
      const d = cv.getContext("2d").getImageData(0, 0, cv.width, cv.height).data;
      const colors = new Set();
      for (let i = 0; i < d.length; i += 4) {
        colors.add(`${d[i]},${d[i + 1]},${d[i + 2]}`);
        if (colors.size > 4) break;
      }
      return { colors: [...colors], w: cv.width, h: cv.height };
    });
    assert.ok(r.w > 0 && r.h > 0, "画布尺寸为 0，这条测试什么也没测到");
    assert.deepEqual(
      r.colors,
      ["6,7,13"],
      `传空层集渲一帧，画面应只有背景色 #06070d，实得 ${r.colors.join(" / ")}` +
        `——有东西绕过图层机制直接往 canvas 上画了`,
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("LAYERS 里只有 layers/ 的模块，界面不许混进去", async () => {
  // 上一条防「在 renderFrame 里另外画」，这一条防「把界面做成一个图层
  // 塞进 LAYERS」——后者会规规矩矩走图层循环，上一条抓不到。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const names = await page.evaluate(() =>
      murRippleApp.LAYERS.map((l) => l.NAME),
    );
    assert.deepEqual(
      names,
      [
        "background", "ripple", "sweep", "spectrum", "dial", "lanes",
        "laneLabels", "notes", "shock", "ring", "core", "waveform",
        "lyrics", "particles", "sectionTitle",
      ],
      "LAYERS 的内容与顺序都是设计决策（M2 spec 第 7 节），改动要连这条一起改",
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("走带条按位置比例跳转，并钳在两端", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const box = await page.locator("#mr-bar").boundingBox();
    const dur = await page.evaluate(
      () => window.__UI__.app.timeline.meta.duration,
    );

    const clickAt = async (frac) => {
      await page.mouse.click(box.x + box.width * frac, box.y + box.height / 2);
      return page.evaluate(() => window.__UI__.lastSeek);
    };

    const quarter = await clickAt(0.25);
    assert.ok(
      Math.abs(quarter - dur * 0.25) < dur * 0.03,
      `点四分之一处应跳到 ${dur * 0.25}s 附近，实得 ${quarter}`,
    );
    const three = await clickAt(0.75);
    assert.ok(three > quarter, `点更靠右应跳到更晚：${quarter} → ${three}`);

    // 钳位：拖到条外不该算出负数或超出时长
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x - 400, box.y + box.height / 2);
    const left = await page.evaluate(() => window.__UI__.lastScrub);
    await page.mouse.move(box.x + box.width + 400, box.y + box.height / 2);
    const right = await page.evaluate(() => window.__UI__.lastScrub);
    await page.mouse.up();
    assert.equal(left, 0, `拖到条左外应钳到 0，实得 ${left}`);
    assert.equal(right, dur, `拖到条右外应钳到时长，实得 ${right}`);
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("一次点击只落定一次跳转", async () => {
  // pointerdown 预览、pointerup 落定。若再单独挂一个 click 监听，一次点击
  // 会落定两次——两次坐标相同，画面看不出异常，却白白重放一遍粒子世界。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const box = await page.locator("#mr-bar").boundingBox();
    await page.evaluate(() => {
      window.__UI__.endCount = 0;
    });
    await page.mouse.click(box.x + box.width * 0.4, box.y + box.height / 2);
    const after = await page.evaluate(() => window.__UI__.endCount);
    assert.equal(after, 1, `一次点击应只落定一次，实得 ${after} 次`);
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("段落刻度按 sections 画，起点那条不画", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const { ticks, sections, dur } = await page.evaluate(() => ({
      ticks: [...document.querySelectorAll("#mr-ticks i")].map(
        (d) => Math.round(parseFloat(d.style.left) * 10) / 10,
      ),
      sections: window.__UI__.app.timeline.sections.map((s) => s.t),
      dur: window.__UI__.app.timeline.meta.duration,
    }));
    const want = sections
      .filter((t) => t > 0 && t < dur)
      .map((t) => Math.round((t / dur) * 1000) / 10);
    assert.ok(want.length > 0, "合成数据要有分界点才测得动");
    assert.deepEqual(ticks, want, "刻度位置应与 sections 一一对应");
    assert.ok(!ticks.includes(0), "t=0 是起点不是分界，不该有刻度");
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("时间显示随 t 变化，且不每帧重写 DOM", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const r = await page.evaluate(() => {
      const { hud } = window.__UI__;
      const el = document.getElementById("mr-time");
      hud.update(10, true); // 先落定到 0:10，再开始计数
      // 必须用同步的 takeRecords()：MutationObserver 的回调是微任务，
      // evaluate 同步返回时它还没跑，计数器恒为 0，什么也测不到。
      const obs = new MutationObserver(() => {});
      obs.observe(el, { childList: true, characterData: true, subtree: true });
      // 一秒之内推进 60 帧：秒数没跨过整数，显示值一次都不该变
      for (let i = 0; i < 60; i++) hud.update(10 + i / 61, true);
      const writes = obs.takeRecords().length;
      const midway = el.textContent;
      hud.update(30, true);
      obs.disconnect();
      return { midway, later: el.textContent, writes };
    });
    assert.equal(r.midway, "0:10 / 4:30", `实得 ${r.midway}`);
    assert.equal(r.later, "0:30 / 4:30", `实得 ${r.later}`);
    assert.ok(
      r.writes <= 1,
      `一秒内推进 60 帧，秒数没跨过整数，时间文本一次都不该改写，` +
        `实得 ${r.writes} 次——每帧无条件写会让浏览器每帧重排`,
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("音量与静音是两条独立的增益，互不吞噬", async () => {
  // 拿总音量兼作静音开关，是这类播放器最常见的错：调过音量之后取消静音，
  // 响度回不到原来的值。这里用一个记账用的假 ctx 验接线。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const r = await page.evaluate(() => {
      const log = [];
      const wires = [];
      let n = 0;
      const dest = { tag: "destination" };
      const ctx = {
        currentTime: 0,
        destination: dest,
        createGain: () => {
          const tag = n++ === 0 ? "master" : `stem${n - 1}`;
          const node = {
            tag,
            gain: { setTargetAtTime: (v) => log.push(`${tag}=${v}`) },
            connect: (to) => wires.push(`${tag}->${to.tag}`),
          };
          return node;
        },
        createBufferSource: () => ({ connect() {}, start() {}, stop() {} }),
      };
      // createPlayer 按 buffers 的 key 集合建增益节点（Task 5 起不再是
      // 写死的四个）——四个 key 都给空对象即可，这里只测接线，不测真的
      // 解码播放。
      const player = murRippleApp.createPlayer(ctx, {
        vocals: {}, drums: {}, bass: {}, other: {},
      });
      const mute = murRippleApp.createMuteState(["vocals", "drums", "bass", "other"]);
      player.setVolume(0.4);
      mute.toggle("drums");
      player.applyMute(mute);
      return { log, wires };
    });
    // 拓扑：四条 stem 必须都汇进总增益，总增益再进输出。少了这条，
    // stem 直连 destination 时 setVolume 完全失效，而上面的断言照样绿。
    assert.deepEqual(
      r.wires.slice().sort(),
      [
        "master->destination",
        "stem1->master",
        "stem2->master",
        "stem3->master",
        "stem4->master",
      ],
      `音频图接错了：${JSON.stringify(r.wires)}`,
    );
    assert.ok(
      r.log.includes("master=0.4"),
      `音量应落在总增益上，实得 ${JSON.stringify(r.log)}`,
    );
    assert.deepEqual(
      r.log.filter((x) => x.startsWith("master=")),
      ["master=0.4"],
      `静音不该动总增益，否则会吞掉音量设置：${JSON.stringify(r.log)}`,
    );
    // 全量对比而不是"某条是 0"：存在性断言放得过"把四条一起压成被静音
    // 那条的增益"——点一下鼓，整首歌全哑。假 ctx 里 stem1…stem4 正好按
    // STEMS 顺序，drums 是第二条。
    assert.deepEqual(
      r.log.filter((x) => !x.startsWith("master=")),
      ["stem1=1", "stem2=0", "stem3=1", "stem4=1"],
      `静音鼓时只有第二条该压到 0，实得 ${JSON.stringify(r.log)}`,
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("setVolume 钳在 0…1", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const r = await page.evaluate(() => {
      const log = [];
      const ctx = {
        currentTime: 0,
        createGain: () => ({
          gain: { setTargetAtTime: (v) => log.push(v) },
          connect() {},
        }),
        createBufferSource: () => ({ connect() {}, start() {}, stop() {} }),
      };
      const p = murRippleApp.createPlayer(ctx, {});
      p.setVolume(3);
      p.setVolume(-1);
      p.setVolume(0.5);
      return log;
    });
    assert.deepEqual(r, [1, 0, 0.5], `越界应钳到 0/1，实得 ${JSON.stringify(r)}`);
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("七行，每行绑定自己的轨道与所属声部", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const r = await page.evaluate(() => ({
      perStem: [...document.querySelectorAll(".mr-voice")].map((row) => [
        row.dataset.stem,
        row.dataset.lane ?? null,
      ]),
    }));
    assert.deepEqual(
      r.perStem,
      [
        ["vocals", null],
        ["drums", "kick"],
        ["drums", "snare"],
        ["drums", "hat"],
        ["bass", "bass"],
        ["other", "mid"],
        ["other", "air"],
      ],
      "七行：六条视觉轨道各一行，人声单独一行（它没有轨道弧，电平取判定环）",
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("共用一条分轨的几行带着归组标记，独立的行没有", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const r = await page.evaluate(() =>
      [...document.querySelectorAll(".mr-voice")].map((row) => [
        row.dataset.lane ?? "vocals",
        row.dataset.groupPos ?? null,
      ]),
    );
    assert.deepEqual(
      r,
      [
        ["vocals", null],
        ["kick", "first"],
        ["snare", "mid"],
        ["hat", "last"],
        ["bass", null],
        ["mid", "first"],
        ["air", "last"],
      ],
      "鼓三行连成一段、流岚缥缈连成一段；人声与渊鸣各自独立，不能有标记",
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("那道竖脊在产物的真样式下确实画得出来，而且三行是连着的", async () => {
  // 只断言 data-group-pos 是不够的：属性齐全而 template.html 里那几条
  // CSS 规则被删掉，面板看上去与从前一模一样，界面照样在骗人。这一条把
  // 产物真正用的样式灌进来，量 ::before 的实际几何。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    await page.addStyleTag({ content: shippedStyle() });
    const r = await page.evaluate(() => {
      const rows = [...document.querySelectorAll(".mr-voice")];
      const rail = (row) => {
        const cs = getComputedStyle(row, "::before");
        return {
          lane: row.dataset.lane ?? "vocals",
          painted: cs.content !== "none",
          width: parseFloat(cs.width) || 0,
          height: parseFloat(cs.height) || 0,
          rowTop: row.getBoundingClientRect().top,
          rowBottom: row.getBoundingClientRect().bottom,
          top: parseFloat(cs.top),
          bottom: parseFloat(cs.bottom),
        };
      };
      return {
        rails: rows.map(rail),
        note: document.querySelector(".mr-voice-note")?.textContent ?? null,
      };
    });

    const by = Object.fromEntries(r.rails.map((x) => [x.lane, x]));
    for (const lane of ["kick", "snare", "hat", "mid", "air"]) {
      assert.equal(by[lane].painted, true, `${lane} 该有一道竖脊，实际没画出来`);
      assert.ok(by[lane].width > 0, `${lane} 的竖脊宽度是 0，等于没画`);
      assert.ok(by[lane].height > 0, `${lane} 的竖脊高度是 0，等于没画`);
    }
    for (const lane of ["vocals", "bass"]) {
      assert.equal(by[lane].painted, false, `${lane} 是独立的一行，不该有竖脊`);
    }

    // 连着：上一行竖脊的下沿必须够到下一行竖脊的上沿，否则画出来是三小段
    // 而不是一道括号，"这三行是一体的"就传达不出去。
    const railTop = (x) => x.rowTop + x.top;
    const railBottom = (x) => x.rowBottom - x.bottom;
    for (const [a, b] of [
      ["kick", "snare"],
      ["snare", "hat"],
      ["mid", "air"],
    ]) {
      assert.ok(
        railBottom(by[a]) >= railTop(by[b]) - 0.5,
        `${a} 与 ${b} 之间断开了：${a} 脊底 ${railBottom(by[a])}，${b} 脊顶 ${railTop(by[b])}`,
      );
    }

    assert.ok(
      r.note && r.note.includes("一条分轨"),
      `面板该有一行说明竖脊含义的小字，实得 ${JSON.stringify(r.note)}`,
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("静音钮只切换自己那个 stem", async () => {
  // 点 bass 而不是第一个非空的 drums：把 onToggle 的参数写死成 "drums"
  // 是最自然的手滑，而点 drums 去测它，变异体的行为与正确实现完全一致。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    await page.click('.mr-voice[data-stem="bass"]');
    const after = await page.evaluate(() => {
      const m = window.__UI__.mute;
      return {
        state: Object.fromEntries(
          ["vocals", "drums", "bass", "other"].map((s) => [s, m.isMuted(s)]),
        ),
        got: window.__UI__.toggledStems,
      };
    });
    assert.deepEqual(after.got, ["bass"], `回调收到的 stem 应是 bass，实得 ${after.got}`);
    assert.deepEqual(
      after.state,
      { vocals: false, drums: false, bass: true, other: false },
      "点贝斯的静音钮，只有贝斯该静音",
    );
    assert.equal(
      await page.getAttribute('.mr-voice[data-stem="bass"]', "aria-pressed"),
      "true",
      "按钮状态要跟着变，否则用户看不出点没点上",
    );
    assert.equal(
      await page.evaluate(() =>
        document
          .querySelector('.mr-voice[data-stem="bass"]')
          .classList.contains("muted"),
      ),
      true,
      "整行要变暗，静音的视觉反馈不能只在按钮上",
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("电平条真的跟着自己那条轨道的包络走", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const r = await page.evaluate(() => {
      const { voices, app } = window.__UI__;
      const read = () =>
        [...document.querySelectorAll(".mr-meter > i")].map((i) =>
          parseFloat(i.style.width),
        );
      // 第 0 行是人声（取判定环），第 1 行才是 lanes[0]
      const lane = app.timeline.lanes[0];
      // 找出该轨道包络最低与最高的两个时刻
      let loT = 0, hiT = 0, lo = Infinity, hi = -Infinity;
      for (let t = 0; t < 9; t += 0.05) {
        // voices 读的是 envSmooth（与 lanes 图层一致），测试必须扫同一条
        const v = murRippleApp.sampleAt(lane.envSmooth, t);
        if (v < lo) { lo = v; loT = t; }
        if (v > hi) { hi = v; hiT = t; }
      }
      voices.update(loT);
      const atLo = read();
      voices.update(hiT);
      const atHi = read();
      return { atLo, atHi, lo, hi, gain: lane.gain };
    });
    assert.ok(r.hi > r.lo, `合成包络本身要有起伏才测得动：${r.lo} → ${r.hi}`);
    assert.ok(
      r.atHi[1] > r.atLo[1] + 5,
      `包络从 ${r.lo} 涨到 ${r.hi}，电平条却只从 ${r.atLo[1]}% 到 ${r.atHi[1]}%`,
    );
    // 满包络对应满高度：只断言"变大了"，把读数除以 2 之类的错误抓不到
    const want = Math.round(Math.min(1, (r.hi / 255) * r.gain) * 100);
    assert.equal(
      r.atHi[1],
      want,
      `包络 ${r.hi}/255 × gain ${r.gain} 应对应 ${want}%，实得 ${r.atHi[1]}%` +
        `——只断言"变大了"，读数除以 2 之类的错误抓不到`,
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("曲名里的尖括号不会破坏页面结构", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const r = await page.evaluate(() => {
      const host = document.createElement("div");
      document.body.appendChild(host);
      const t = murRippleApp.createTitle(document, host, {
        title: '<img src=x onerror="window.__PWNED__=1">风起',
        duration: 65,
        bpm: 120,
        onStart() {},
      });
      const h1 = t.el.querySelector("h1");
      const out = {
        text: h1.textContent,
        childTags: [...h1.children].map((c) => c.tagName),
        pwned: !!window.__PWNED__,
        meta: t.el.querySelector("#mr-t-meta").textContent,
      };
      t.close();
      host.remove();
      return out;
    });
    assert.equal(r.text, '<img src=x onerror="window.__PWNED__=1">风起');
    assert.deepEqual(r.childTags, [], "曲名必须是纯文本，不能被解析成元素");
    assert.equal(r.pwned, false);
    assert.equal(r.meta, "120 BPM · 1:05", `实得 ${r.meta}`);
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("解码失败留在标题页并可重试，不静默卡住", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const r = await page.evaluate(() => {
      const host = document.createElement("div");
      document.body.appendChild(host);
      let started = 0;
      const t = murRippleApp.createTitle(document, host, {
        title: "x",
        duration: 10,
        onStart: () => started++,
      });
      const btn = t.el.querySelector("#mr-start");
      const msgEl = t.el.querySelector("#mr-t-msg");
      btn.click();
      const whileLoading = { disabled: btn.disabled, msg: msgEl.textContent };
      t.fail("音频解码失败：浏览器不支持 AAC");
      const afterFail = {
        disabled: btn.disabled,
        label: btn.textContent,
        msg: msgEl.textContent,
        attached: document.body.contains(t.el),
      };
      btn.click();
      const out = { whileLoading, afterFail, started };
      t.close();
      host.remove();
      return out;
    });
    assert.equal(r.whileLoading.disabled, true, "解码中不该能重复点");
    assert.equal(r.whileLoading.msg, "解码中…", `实得 ${r.whileLoading.msg}`);
    assert.equal(
      r.afterFail.attached,
      true,
      "失败了不能把标题页关掉——那就是静默卡住",
    );
    assert.ok(r.afterFail.msg.includes("AAC"), `错误信息要显示，实得 ${r.afterFail.msg}`);
    assert.equal(r.afterFail.disabled, false, "失败后要能重试");
    assert.equal(r.started, 2, "重试要真的再次触发启动");
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("进度条的填充、把手、aria-valuenow 都随 t 走", async () => {
  // 「时间显示不每帧重写」那条只管文本。进度条本身停在 0%、或者倒着走，
  // 它一概看不见——而那是走带条最主要的视觉。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const r = await page.evaluate(() => {
      const { hud } = window.__UI__;
      const read = () => ({
        fill: document.getElementById("mr-fill").style.width,
        knob: document.getElementById("mr-knob").style.left,
        aria: document.getElementById("mr-bar").getAttribute("aria-valuenow"),
      });
      hud.update(67.5, true);
      const quarter = read();
      hud.update(135, true);
      return { quarter, half: read() };
    });
    assert.deepEqual(r.quarter, { fill: "25%", knob: "25%", aria: "68" });
    assert.deepEqual(r.half, { fill: "50%", knob: "50%", aria: "135" });
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("播过结尾之后计时器停在总时长上，不再往上涨；回跳仍然正常", async () => {
  // 实测（私仓 songs/01，270 秒那首）：播到结尾计时器继续单调递增，
  // 4:31 → 4:44 还在走。根因在 player.currentTime()——缓冲播完之后 playing 仍是 true，
  // `ctx.currentTime - startedAt + offset` 一路涨。走带条的百分比本来就
  // 钳过（fill/knob 停在 100%），时间文本与 aria-valuenow 没钳，于是把手
  // 停着、数字还在走。
  //
  // 这一条同时守回跳：台账里一度记成"且无法回跳"并已撤回（那次点击的 y
  // 落在画面之外，根本没打中走带条）。回跳本来是好的，别在修越界时把它
  // 一起钳死——只钳上界不钳"从大回到小"。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const r = await page.evaluate(() => {
      const { hud } = window.__UI__;
      const read = () => ({
        time: document.getElementById("mr-time").textContent,
        fill: document.getElementById("mr-fill").style.width,
        aria: document.getElementById("mr-bar").getAttribute("aria-valuenow"),
      });
      const out = {};
      hud.update(268, true);
      out.before = read();
      hud.update(270, true);
      out.atEnd = read();
      // 结尾之后又过了 13 秒——正是实测里 4:31 → 4:44 那 13 秒
      hud.update(283, true);
      out.past = read();
      hud.update(400, true);
      out.wayPast = read();
      // 回跳
      hud.update(30, true);
      out.back = read();
      out.max = document.getElementById("mr-bar").getAttribute("aria-valuemax");
      return out;
    });

    assert.equal(r.before.time, "4:28 / 4:30");
    assert.equal(r.atEnd.time, "4:30 / 4:30");
    assert.equal(
      r.past.time,
      "4:30 / 4:30",
      `播过结尾 13 秒后计时器该停在总时长上，实得 ${r.past.time}`,
    );
    assert.equal(
      r.wayPast.time,
      "4:30 / 4:30",
      `再过两分多钟也还是总时长，实得 ${r.wayPast.time}`,
    );
    assert.equal(r.past.fill, "100%");
    assert.ok(
      Number(r.past.aria) <= Number(r.max),
      `aria-valuenow(${r.past.aria}) 不得越过 aria-valuemax(${r.max})`,
    );
    assert.equal(r.back.time, "0:30 / 4:30", "回跳要照常显示，不能被钳死在结尾");
    assert.equal(r.back.fill, "11.1%");
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("播放钮点得动，图标跟着播放状态翻", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    await page.evaluate(() => {
      window.__UI__.toggles = 0;
    });
    await page.click("#mr-play");
    await page.click("#mr-play");
    const r = await page.evaluate(() => {
      const { hud } = window.__UI__;
      const btn = document.getElementById("mr-play");
      hud.update(1, true);
      const playing = btn.textContent;
      hud.update(1, false);
      return { toggles: window.__UI__.toggles, playing, paused: btn.textContent };
    });
    assert.equal(r.toggles, 2, `两次点击应回调两次，实得 ${r.toggles}`);
    assert.equal(r.playing, "❚❚", "播放中该显示暂停图标");
    assert.equal(r.paused, "▶", "暂停中该显示播放图标");
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("音量滑块把 0…100 换算成 0…1", async () => {
  // 忘了除以 100 的话，setVolume 一钳位就永远是满格——音量滑块形同虚设，
  // 而画面与声音都看不出异常。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const r = await page.evaluate(() => {
      const el = document.getElementById("mr-vol");
      const set = (v) => {
        el.value = String(v);
        el.dispatchEvent(new Event("input", { bubbles: true }));
        return window.__UI__.lastVolume;
      };
      return { mid: set(40), zero: set(0), max: set(100) };
    });
    assert.deepEqual(r, { mid: 0.4, zero: 0, max: 1 });
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("拖拽被系统打断时收尾，不卡在拖拽状态", async () => {
  // 只听 pointerup 的话，pointercancel（触摸被滚动接管、切窗口、设备旋转）
  // 会让 dragging 与调用方的 scrubT 一起永久卡住：画面冻结、按空格音频照走
  // 而画面不动，此后鼠标只要划过走带条就会暂停音频并跳时间。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const box = await page.locator("#mr-bar").boundingBox();
    const r = await page.evaluate((b) => {
      const bar = document.getElementById("mr-bar");
      const at = (frac, type) =>
        bar.dispatchEvent(
          new PointerEvent(type, {
            bubbles: true,
            pointerId: 7,
            clientX: b.x + b.width * frac,
            clientY: b.y + b.height / 2,
          }),
        );
      window.__UI__.endCount = 0;
      at(0.5, "pointerdown");
      at(0.5, "pointercancel");
      const endedOnCancel = window.__UI__.endCount;

      // 卡住的话，此后不按键光移动也会触发 onScrub
      window.__UI__.lastScrub = null;
      at(0.9, "pointermove");
      return { endedOnCancel, scrubAfterCancel: window.__UI__.lastScrub };
    }, box);
    assert.equal(r.endedOnCancel, 1, "pointercancel 必须走与 pointerup 同一条收尾路径");
    assert.equal(
      r.scrubAfterCancel,
      null,
      "取消之后光移动鼠标不该再跳转——dragging 卡在 true 了",
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test("收起按钮回调一次，且不与走带条抢事件", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    await page.evaluate(() => {
      window.__UI__.hides = 0;
      window.__UI__.endCount = 0;
    });
    await page.click("#mr-hide");
    const r = await page.evaluate(() => ({
      hides: window.__UI__.hides,
      ends: window.__UI__.endCount,
    }));
    assert.equal(r.hides, 1, `点一次该回调一次，实得 ${r.hides}`);
    assert.equal(r.ends, 0, "收起按钮不该顺带触发走带条跳转");
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});

test('"lone" 那一档真的画得出来——不相邻的同组行各自封口，不连成长线', async () => {
  // 上一棒坦白的一条：buildVoiceRows 的 "lone" 分支只有纯函数测试，从来
  // 没在屏幕上出现过（真素材里同一条 stem 永远相邻）。这里造一份最小的
  // 假 lanes 让它真渲染一次，并按产物的真样式量竖脊的几何。
  //
  // 形状：drums 两行中间隔着一条 bass。两条 drums 都该是 lone，各自是一段
  // 独立的短脊；中间那条 bass 没有脊。如果实现改成"按整组连线"，中间这条
  // 无关的行会被一道长脊圈进去——那正是"界面骗人"的另一种形态。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    await page.addStyleTag({ content: shippedStyle() });
    const r = await page.evaluate(() => {
      const host = document.createElement("div");
      host.id = "lone-host";
      document.body.appendChild(host);
      const lanes = [
        { id: "kick", label: "撼岳", hue: 28, stem: "drums", gain: 1, envSmooth: new Float32Array(10) },
        { id: "bass", label: "渊鸣", hue: 225, stem: "bass", gain: 1, envSmooth: new Float32Array(10) },
        { id: "snare", label: "裂帛", hue: 350, stem: "drums", gain: 1, envSmooth: new Float32Array(10) },
      ];
      murRippleApp.createVoices(document, host, {
        lanes,
        ring: { envSmooth: new Float32Array(10) },
        mute: murRippleApp.createMuteState(["vocals", "drums", "bass"]),
        onToggle: () => {},
        onHover: () => {},
      });
      return [...host.querySelectorAll(".mr-voice")].map((row) => {
        const cs = getComputedStyle(row, "::before");
        const rr = row.getBoundingClientRect();
        return {
          lane: row.dataset.lane ?? "vocals",
          pos: row.dataset.groupPos ?? null,
          painted: cs.content !== "none",
          top: rr.top + parseFloat(cs.top),
          bottom: rr.bottom - parseFloat(cs.bottom),
          rowTop: rr.top,
          rowBottom: rr.bottom,
        };
      });
    });

    const by = Object.fromEntries(r.map((x) => [x.lane, x]));
    assert.equal(by.kick.pos, "lone");
    assert.equal(by.snare.pos, "lone");
    assert.equal(by.bass.pos, null, "夹在中间的渊鸣与鼓无关");

    assert.equal(by.kick.painted, true, '"lone" 也该画出一段竖脊，不能什么都不画');
    assert.equal(by.snare.painted, true);
    assert.equal(by.bass.painted, false, "中间那条无关的行不该有脊");

    // 关键：两段脊都必须收在**自己那一行之内**，不能越过中间那条 bass。
    assert.ok(
      by.kick.bottom <= by.bass.rowTop + 0.5,
      `撼岳的脊探进了渊鸣那一行：脊底 ${by.kick.bottom}，渊鸣行顶 ${by.bass.rowTop}`,
    );
    assert.ok(
      by.snare.top >= by.bass.rowBottom - 0.5,
      `裂帛的脊探进了渊鸣那一行：脊顶 ${by.snare.top}，渊鸣行底 ${by.bass.rowBottom}`,
    );
    assert.deepEqual(errs, [], errs.join("; "));
  } finally {
    await browser.close();
  }
});
