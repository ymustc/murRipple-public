/**
 * 天象层：英仙座流星 + 六星连珠。
 *
 * 这里守三件事，一件比一件难骗：
 *
 * 一、**分寸**。于淼要的是"平均十几秒一颗、偶尔两颗齐落"，不是流星雨。
 *     密度写错了画面就俗了，而俗是这一项最大的风险。
 * 二、**辐射点**。流星雨之所以叫英仙座，是因为所有流星都从同一点射出；
 *     随机划线不是流星雨。光在纯函数里断言角度没用——真正要证的是"画
 *     出来的那道光就在从辐射点算出来的位置上"，所以量像素。
 * 三、**确定性**。进度必须是 t 的闭式，不能逐帧累加，否则逐帧导出的视频
 *     与实时播放对不上。这条有两道：倒着渲一遍，以及"直接渲第 N 帧"必须
 *     等于"从 0 一帧帧走到第 N 帧"。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  meteorsAt,
  planetPos,
  planetStyle,
  lightAngle,
  PLANETS,
  RADIANT,
  METEOR_LIFE,
  warmHueCompensation,
} from "../src/layers/background.js";

const here = dirname(fileURLToPath(import.meta.url));
const harness = `file://${resolve(here, "harness.html")}`;

/** 每一颗流星的身份。一轮里可能跟着一颗双星，所以 lead 也要进 key。 */
const idOf = (m) => `${m.i}:${m.k}:${m.lead ? "L" : "F"}`;

/** 扫一段时间，回报每一颗出现过的流星与在场情况。 */
function survey(span, step = 1 / 120) {
  const seen = new Map();
  let frames = 0;
  let busy = 0;
  let crowded = 0;
  const together = new Set();
  for (let t = 0; t < span; t += step) {
    const ms = meteorsAt(t);
    frames++;
    if (ms.length) busy++;
    if (ms.length >= 2) {
      crowded++;
      together.add(ms.map(idOf).sort().join("+"));
    }
    for (const m of ms) if (!seen.has(idOf(m))) seen.set(idOf(m), m);
  }
  return { seen, frames, busy, crowded, together };
}

test("平均十几秒一颗——是点缀，不是流星雨", () => {
  const s = survey(600);
  const gap = 600 / s.seen.size;
  assert.ok(
    gap >= 10 && gap <= 25,
    `平均 ${gap.toFixed(1)} 秒一颗。于淼定的是"平均十几秒一颗"：` +
      `密到几秒一颗就成了流星雨，稀到半分钟一颗又等于没有`,
  );
});

test("绝大多数时刻天上什么都没有", () => {
  const s = survey(600);
  const share = s.busy / s.frames;
  assert.ok(
    share < 0.08,
    `有流星的时间占了 ${(share * 100).toFixed(1)}%——画面主体是中心的` +
      `圆环与歌词，流星常驻就喧宾夺主了`,
  );
});

test("偶尔两颗齐落，但只是偶尔", () => {
  const s = survey(600);
  assert.ok(s.together.size >= 1, "六百秒里一次两颗齐落都没有");
  assert.ok(
    s.crowded / s.frames < 0.01,
    `两颗齐落占了 ${((s.crowded / s.frames) * 100).toFixed(2)}% 的时间，` +
      `那就不叫"偶尔"了`,
  );
});

test("所有流星都射向同一个扇面——辐射点的必要条件", () => {
  const { seen } = survey(600);
  const degs = [...seen.values()].map((m) => (m.ang * 180) / Math.PI);
  const lo = Math.min(...degs);
  const hi = Math.max(...degs);
  // 扇面要够宽才看得出是"从一点散开"，又不能宽到 360°——那就是四面八方
  // 乱飞，辐射点也就无从谈起。
  assert.ok(hi - lo > 40, `方向只散布在 ${(hi - lo).toFixed(0)}°，看着像平行线`);
  assert.ok(hi - lo < 150, `方向散布 ${(hi - lo).toFixed(0)}°，不像从一点射出`);
});

test("一颗流星一生只朝一个方向飞，长短也不变", () => {
  // 曾经踩过：双星的随机数是"活着才抽"，于是前一颗谢幕的那一帧，后一颗
  // 抽到的变成了前一颗那份，飞到一半突然换方向换长度。
  const { seen } = survey(300);
  const [id, sample] = [...seen.entries()][3];
  const track = [];
  for (let t = 0; t < 300; t += 1 / 240) {
    const hit = meteorsAt(t).find((m) => idOf(m) === id);
    if (hit) track.push(hit);
  }
  assert.ok(track.length > 20, `没跟踪到足够的帧（${track.length}）`);
  for (const m of track) {
    assert.equal(m.ang, sample.ang, `${id} 半路换了方向`);
    assert.equal(m.tail, sample.tail, `${id} 半路换了尾巴长度`);
    assert.equal(m.bright, sample.bright, `${id} 半路换了亮度`);
  }
  // 而位置必须一直往外走
  for (let j = 1; j < track.length; j++) {
    assert.ok(track[j].d > track[j - 1].d, `${id} 倒着飞了`);
  }
});

test("是 t 的纯函数：乱序、重复求值都得到同一答案", () => {
  const ts = [12.5, 25.24, 3.1, 45.86, 25.24, 0.4, 32.87];
  const first = ts.map((t) => JSON.stringify(meteorsAt(t)));
  const again = [...ts].reverse().map((t) => JSON.stringify(meteorsAt(t)));
  assert.deepEqual(again, [...first].reverse());
  assert.equal(first[1], first[4], "同一个 t 两次问出不同的答案");
});

test("进度是闭式：单调、有界，寿命就是 METEOR_LIFE", () => {
  const { seen } = survey(300);
  for (const m of seen.values()) {
    assert.ok(m.p >= 0 && m.p < 1, `进度 ${m.p} 越界`);
  }
  // 逐帧累加的实现活不出一个准确的寿命：这里量一颗从出现到消失有多久。
  const id = [...seen.keys()][1];
  let lo = Infinity;
  let hi = -Infinity;
  for (let t = 0; t < 300; t += 1 / 240) {
    if (meteorsAt(t).some((m) => idOf(m) === id)) {
      lo = Math.min(lo, t);
      hi = Math.max(hi, t);
    }
  }
  assert.ok(
    Math.abs(hi - lo - METEOR_LIFE) < 0.02,
    `一颗流星活了 ${(hi - lo).toFixed(3)} 秒，应当是 ${METEOR_LIFE}`,
  );
});

test("划过时长够慢，看得清——不是初版那个 0.62s 一晃而过", () => {
  // 于淼原话："流星效果有点太快了可能看不到"。初版 METEOR_LIFE 是
  // 0.62s，这条只守下限：往回改快了要在这里炸，不管改成多少都行，只要
  // 没有退回接近初版那个速度。上限交给"偶尔两颗齐落"那条测试去顶
  // 住——飞得越慢，双星共存与跨槽位撞在一起的时间越长，那条测试会先叫
  // （这也是为什么最终选的是 1.5×、不是最初试的 2×：2× 在多个 600
  // 秒窗口里把"两颗齐落"的占比推到了 1% 以上）。
  assert.ok(
    METEOR_LIFE >= 0.85,
    `METEOR_LIFE=${METEOR_LIFE}，太接近初版的 0.62s 了，于淼要的是明显` +
      `变慢，不是原速`,
  );
  // "多久来一颗"是另一件事，于淼没让动，这里只顺手确认没被这次调速度
  // 的改动捎带着改掉——真正的密度分寸由上面"平均十几秒一颗"那条测试守。
  const gapAvg = 600 / survey(600).seen.size;
  assert.ok(
    gapAvg >= 10 && gapAvg <= 25,
    `平均间隔变成 ${gapAvg.toFixed(1)}s 了，频次不该被这次调速度带偏`,
  );
});

// —— 六星连珠 ——

/** 某一刻六颗的位置。注意别写成 PLANETS.map(planetPos)——map 会把下标
 *  当成 t 传进去，六颗各漂各的，共线立刻就断了。 */
const posAt = (t) => PLANETS.map((p) => planetPos(p, t));

test("正好六颗，任何时刻都共线，而且只是微斜", () => {
  assert.equal(PLANETS.length, 6, "六星连珠就是六颗");
  // 挑几个时刻：慢漂是刚性平移，任何一刻都得还在一条线上。各漂各的
  // 就不是"连珠"了——共线是这个天象的全部意思。
  for (const t of [0, 13.7, 41.2, 88.9, 140]) {
    const pos = posAt(t);
    const dx = pos[5].x - pos[0].x;
    const dy = pos[5].y - pos[0].y;
    for (const p of pos) {
      const cross = (p.x - pos[0].x) * dy - (p.y - pos[0].y) * dx;
      assert.ok(Math.abs(cross) < 1e-12, `t=${t} 时六颗不在同一条黄道上`);
    }
    // 归一化坐标下的斜率。0 是死板的水平线，太陡就不像黄道了。
    const slope = Math.abs(dy / dx);
    assert.ok(slope > 0.15 && slope < 0.8, `黄道斜率 ${slope.toFixed(2)} 不对`);
  }
});

test("间距不均匀——真实的连珠不是等分的", () => {
  const at = PLANETS.map((p) => p.at);
  const gaps = at.slice(1).map((v, i) => v - at[i]);
  const min = Math.min(...gaps);
  const max = Math.max(...gaps);
  assert.ok(max > min * 1.4, `最疏 ${max} 最密 ${min}，几乎是等分的`);
  for (const g of gaps) assert.ok(g > 0, "顺序乱了或有重合");
});

test("六颗大小不一，且有一颗明显是大个儿", () => {
  // "看得出各自特点"是于淼返工的第一条要求。大小差是最省事的一维，
  // 而带环那颗必须是最大的——气态巨行星才有环，小石头顶着环是笑话。
  const rs = PLANETS.map((p) => p.r);
  assert.ok(Math.max(...rs) > Math.min(...rs) * 1.6, `六颗差不多大：${rs}`);
  const ringed = PLANETS.filter((p) => p.ring);
  assert.equal(ringed.length, 1, "环是辨识符号，多了就成装饰了");
  assert.equal(ringed[0].r, Math.max(...rs), "带环的不是最大那颗");
});

test("暖色补偿：只在暖色区间生效，冷色（紫）段落原样不动", () => {
  // 暖金段落（歌曲里 t≈81，段落 hueShift=185 → hue=35）六颗行星曾经挤成
  // "粉红一簇、淡黄绿一簇"；紫色段落（t≈27，hueShift=111 → hue=321）没有
  // 这问题。这条测试钉住 warmHueCompensation 的两条边：
  //
  //   一、暖色区间必须真的补偿——不能被删掉、退化成永远返回基线。
  //   二、冷色区间必须原样返回基线——不能变成"不看 hue 是多少，反正都补"，
  //      那样紫色段落会被推过头，把"改善暖色"的收益换成"弄坏紫色"的代价。
  //
  // 用一圈色相各测几个点，而不是只测 35 和 321 两个值：真出问题的实现
  // 往往是"忽略输入、返回固定值"——如果只测两个点，凑巧撞对也会看着像
  // 通过。这里暖色测了 35、358、72（区间两端各留一点余量），冷色测了
  // 321、210、146（紫、蓝紫、青绿一线）。
  const BASELINE = { spread: 1, satBoost: 0 };
  for (const warmHue of [35, 358, 72, 0, 99, 340]) {
    const c = warmHueCompensation(warmHue);
    assert.ok(
      c.spread > BASELINE.spread && c.satBoost > BASELINE.satBoost,
      `hue=${warmHue} 是暖色，理应比基线（spread=1, satBoost=0）分得更开，` +
        `实际拿到 ${JSON.stringify(c)}——补偿被删掉了，还是被写死了？`,
    );
  }
  for (const coolHue of [321, 210, 247, 284, 146, 100, 339]) {
    const c = warmHueCompensation(coolHue);
    assert.deepEqual(
      c,
      BASELINE,
      `hue=${coolHue} 是冷色（紫色段落 t≈27 就在这一带），理应原样返回` +
        `基线，实际拿到 ${JSON.stringify(c)}——补偿变成无条件生效了，` +
        `紫色段落会被误伤`,
    );
  }
});

test("连珠挂在偏上方，避开标题卡、声部面板与圆环", () => {
  // 左上是标题卡，右侧中段（画高 35%–70%）是声部面板。
  for (const p of PLANETS) {
    for (const t of [0, 27.1, 88.9]) {
      const pos = planetPos(p, t);
      assert.ok(pos.y < 0.3, `有行星掉到画高 ${pos.y.toFixed(2)}，压着声部面板`);
      assert.ok(pos.x > 0.6, `有行星漂到画宽 ${pos.x.toFixed(2)}，不在右上`);
      assert.ok(pos.x < 0.99 && pos.y > 0.02, "有行星要出画了");
    }
  }
});

test("连珠与流星辐射点错开，两个天象不挤在一起", () => {
  for (const p of PLANETS) {
    const pos = planetPos(p, 0);
    const d = Math.hypot(pos.x - RADIANT.x, pos.y - RADIANT.y);
    assert.ok(d > 0.5, `有行星离辐射点只有 ${d.toFixed(2)}（归一化）`);
  }
});

test("星链在动，但慢到只是'活着'——而且是闭式，不是累加", () => {
  const p = PLANETS[0];
  // 一、真的在动。初版是死的，于淼说"缺少动效甚至可能看不出来"。
  const span = [0, 20, 40, 60, 80].map((t) => planetPos(p, t));
  const moved = Math.max(
    ...span.map((q) => Math.hypot(q.x - span[0].x, q.y - span[0].y)),
  );
  assert.ok(moved > 0.004, `八十秒才挪了 ${moved.toFixed(5)}，等于没动`);

  // 二、慢。快了就成了飘浮的装饰，夜空该是静的。
  let fastest = 0;
  for (let t = 0; t < 200; t += 0.25) {
    const a = planetPos(p, t);
    const b = planetPos(p, t + 0.25);
    fastest = Math.max(fastest, Math.hypot(b.x - a.x, b.y - a.y) / 0.25);
  }
  assert.ok(fastest < 0.002, `最快每秒挪 ${fastest.toFixed(5)} 画宽，太急`);

  // 三、闭式。乱序求值必须与顺序求值一致——逐帧累加做不到。
  const ts = [77.3, 5.5, 130.1, 5.5];
  const fwd = ts.map((t) => JSON.stringify(planetPos(p, t)));
  assert.deepEqual(
    [...ts].reverse().map((t) => JSON.stringify(planetPos(p, t))),
    [...fwd].reverse(),
  );
  assert.equal(fwd[1], fwd[3], "同一个 t 两次问出不同的位置");
});

test("明暗交界慢慢转，六颗不齐步走，但共用一个光源方向", () => {
  const p = PLANETS[0];
  const q = PLANETS[3];
  // 同一位置、同一时刻，两颗的交界朝向不能一样——齐步走一眼假
  assert.notEqual(
    lightAngle(p, 100, 100, 800, 450, 12).toFixed(4),
    lightAngle(q, 100, 100, 800, 450, 12).toFixed(4),
  );
  // 但摆动幅度必须小：亮面始终大致朝着画面中心，那是"同一个太阳"的意思
  const base = Math.atan2(450 - 100, 800 - 100);
  for (let t = 0; t < 300; t += 0.5) {
    const dev = Math.abs(lightAngle(p, 100, 100, 800, 450, t) - base);
    assert.ok(dev < 0.6, `交界线偏离光源方向 ${dev.toFixed(2)} 弧度，太多`);
  }
  // 而且转得慢：一秒转不到两度
  let fastest = 0;
  for (let t = 0; t < 300; t += 0.5) {
    const d = Math.abs(
      lightAngle(p, 100, 100, 800, 450, t + 0.5) -
        lightAngle(p, 100, 100, 800, 450, t),
    );
    fastest = Math.max(fastest, d / 0.5);
  }
  assert.ok(fastest < 0.035, `每秒转 ${fastest.toFixed(3)} 弧度，看得出在转`);
});

// —— 以下是像素级的：纯函数写得再对，画错了照样是错 ——

/**
 * 开页，并在页内备好只装背景层的实例工厂。
 *
 * 只装这一层是必须的：别的层会往同一片天上画东西，混着量不出所以然。
 */
async function openPage(browser, deviceScaleFactor = 1) {
  const page = await (await browser.newContext({ deviceScaleFactor })).newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(e.message));
  await page.goto(harness);
  await page.evaluate(() => {
    const cv = document.getElementById("cv");
    const bg = murRippleApp.LAYERS.find((l) => l.NAME === "background");
    if (!bg) throw new Error("background 层不在 LAYERS 里");
    window.__sky = {
      cv,
      g: cv.getContext("2d"),
      bg,
      mk(mode, quality) {
        const a = murRippleApp.createApp({
          doc: document,
          canvas: cv,
          timelineDoc: window.__HARNESS_DOC__,
          mode,
          quality,
          layers: [bg],
        });
        a.resize();
        return a;
      },
      // 同一个厂子，但换一份 timelineDoc——用来钉住"某个段落号对应的
      // hueShift 落在暖色/冷色区间"这件事，不依赖真实歌曲的 timeline.json。
      mkDoc(timelineDoc, mode, quality) {
        const a = murRippleApp.createApp({
          doc: document,
          canvas: cv,
          timelineDoc,
          mode,
          quality,
          layers: [bg],
        });
        a.resize();
        return a;
      },
      geom: () => murRippleApp.computeGeometry(cv, document),
      lum: (d, i) => (d[i] * 299 + d[i + 1] * 587 + d[i + 2] * 114) / 1000,
    };
  });
  return { page, errs };
}

test("流星画在从辐射点射出的那个位置上——这才叫英仙座", async () => {
  // 底片用 quality 0 的实时实例：降级档不画流星（与浮尘同规矩，由渲染
  // 模式驱动而非帧率）。所以两张的差里，亮的那一处只可能是流星。
  //
  // 随机划线的实现会把光画在别处，这里预测的位置就只剩噪点那点差值。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const rows = await page.evaluate(
      ({ ts, radiant }) => {
        const { cv, g, bg, mk, lum } = window.__sky;
        const geom = window.__sky.geom();
        const short = Math.min(geom.W, geom.H);
        return ts.map((t) => {
          const on = mk("offline", 1);
          on.previewFrame(t);
          const A = g.getImageData(0, 0, cv.width, cv.height).data;
          const off = mk("realtime", 0);
          off.previewFrame(t);
          const B = g.getImageData(0, 0, cv.width, cv.height).data;

          const diff = new Float64Array(A.length / 4);
          for (let i = 0; i < A.length; i += 4) {
            diff[i / 4] = Math.abs(lum(A, i) - lum(B, i));
          }
          const sorted = Array.from(diff).sort((x, y) => x - y);
          const p99 = sorted[Math.floor(sorted.length * 0.99)];
          let best = 0;
          let ink = 0;
          for (let i = 1; i < diff.length; i++) {
            if (diff[i] > diff[best]) best = i;
            // 噪点的 p99 只有 7 上下，25 以上只可能是流星本身
            if (diff[i] > 25) ink++;
          }

          const heads = bg.meteorsAt(t).map((m) => {
            const hx = radiant.x * geom.W + Math.cos(m.ang) * m.d * short;
            const hy = radiant.y * geom.H + Math.sin(m.ang) * m.d * short;
            let peak = 0;
            for (let dy = -2; dy <= 2; dy++) {
              for (let dx = -2; dx <= 2; dx++) {
                const px = Math.round(hx) + dx;
                const py = Math.round(hy) + dy;
                if (px < 0 || px >= geom.W || py < 0 || py >= geom.H) continue;
                peak = Math.max(peak, diff[py * geom.W + px]);
              }
            }
            return { x: Math.round(hx), y: Math.round(hy), peak };
          });
          return {
            t,
            p99,
            ink,
            argmax: { x: best % geom.W, y: Math.floor(best / geom.W) },
            heads,
          };
        });
      },
      { ts: [25.2417, 45.8625, 32.875], radiant: RADIANT },
    );
    assert.deepEqual(errs, [], errs.join("; "));

    for (const r of rows) {
      assert.ok(r.heads.length >= 1, `t=${r.t} 这一刻本该有流星`);
      for (const h of r.heads) {
        // 噪点带来的差值 p99 只有 7 上下，流星头实测 27…142。
        assert.ok(
          h.peak >= 25,
          `t=${r.t}：辐射点算出的位置 (${h.x},${h.y}) 上只差了 ` +
            `${h.peak.toFixed(1)}（画面 p99 是 ${r.p99.toFixed(1)}）——` +
            `流星没画在那儿`,
        );
      }
      // 最亮的一处也必须落在某颗流星头上，不能画得满天都是
      const near = r.heads.some(
        (h) => Math.hypot(h.x - r.argmax.x, h.y - r.argmax.y) <= 4,
      );
      assert.ok(
        near,
        `t=${r.t}：最亮的差在 (${r.argmax.x},${r.argmax.y})，` +
          `不在任何一颗流星头上`,
      );
      // 于淼看过初版的图，说"容易整颗错过"，要求把亮度与长度各提一档。
      // 这一条守的是那次提档：明显亮于噪点的像素得铺开一条，不能只剩
      // 一个头。初版（tail 0.045…0.095、bright 0.5…1.0）实测 ink 在 25 上下，
      // 提档后 65 以上。这两个数是变异检验量出来的。
      assert.ok(
        r.ink >= 45,
        `t=${r.t}：明显亮过噪点的像素只有 ${r.ink} 个——流星细得看不见了`,
      );
    }
  } finally {
    await browser.close();
  }
});

test("有流星的那一段，倒着渲与正着渲逐帧一致", async () => {
  // 逐帧累加的实现在这里必炸：倒着渲时 t 在减小，累加器却只会往前爬。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const { fwd, bwd } = await page.evaluate(() => {
      const { mk } = window.__sky;
      const FPS = 60;
      const F0 = Math.round(24.8 * FPS);
      const F1 = Math.round(26.0 * FPS);
      const run = (order) => {
        const app = mk("offline", 1);
        const out = {};
        for (const i of order) {
          app.renderFrame(i / FPS);
          out[i] = app.frameHash();
        }
        return out;
      };
      const asc = [];
      for (let i = F0; i < F1; i++) asc.push(i);
      return { fwd: run(asc), bwd: run([...asc].reverse()) };
    });
    assert.deepEqual(errs, [], errs.join("; "));

    const keys = Object.keys(fwd);
    assert.ok(keys.length > 60, "取样窗口太短");
    for (const k of keys) {
      assert.equal(bwd[k], fwd[k], `第 ${k} 帧倒着渲与正着渲画得不一样`);
    }
    assert.ok(
      new Set(Object.values(fwd)).size > keys.length * 0.9,
      "这一段几乎没在动，这条测试也就没在测什么",
    );
  } finally {
    await browser.close();
  }
});

test("直接渲某一帧，等于从 0 一帧帧走到那一帧", async () => {
  // 这一条专抓"把闭式改成逐帧累加"：`p += 1/60` 的实现走了一千五百帧
  // 之后进度早已跑到天边，而新实例直接渲那一帧时进度还是 0。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser);
    const { direct, walked } = await page.evaluate(() => {
      const { mk } = window.__sky;
      const T = 25.2417; // 一颗流星正亮的时刻
      const jump = mk("offline", 1);
      jump.renderFrame(T);
      const direct = jump.frameHash();

      const app = mk("offline", 1);
      for (let t = 0; t < T; t += 1 / 24) app.renderFrame(t);
      app.renderFrame(T);
      return { direct, walked: app.frameHash() };
    });
    assert.deepEqual(errs, [], errs.join("; "));
    assert.equal(
      walked,
      direct,
      "走过去与跳过去画出了不同的一帧——有东西在逐帧累加",
    );
  } finally {
    await browser.close();
  }
});

/**
 * 星链漂到横向最远的那一刻取样。
 *
 * 不取 t=0：那时慢漂恰好为零，"画的时候有没有把漂算进去"就测不出来了。
 * 27.1 秒时横向已漂开约 14 个像素，比行星本身还宽——画里没跟着漂的话，
 * 下面按 planetPos(p, t) 去取样就会取到空处，level 那条立刻红。
 */
const T_SKY = 27.1;

/** 在 t 时刻单画背景层，量六颗行星各自的几件事。 */
function probePlanets(page, pts, t) {
  return page.evaluate(
    ({ pts, t }) => {
      const { cv, g, mk, lum } = window.__sky;
      const geom = window.__sky.geom();
      const app = mk("offline", 1);
      app.previewFrame(t);
      const d = g.getImageData(0, 0, cv.width, cv.height).data;
      const at = (x, y) => {
        const px = Math.round(x);
        const py = Math.round(y);
        if (px < 0 || px >= geom.W || py < 0 || py >= geom.H) return 0;
        return lum(d, (py * geom.W + px) * 4);
      };
      return {
        rows: pts.map((p) => {
          const px = p.x * geom.W;
          const py = p.y * geom.H;
          const rp = p.rp * (Math.min(geom.W, geom.H) / 900);
          // 圆盘整体的亮度总和：对明暗交界怎么转、对半个像素的漂移都不敏感，
          // 只有"整颗忽明忽暗"才动得了它——正是要守的那件事。
          let sum = 0;
          const box = Math.ceil(rp) + 1;
          for (let dy = -box; dy <= box; dy++) {
            for (let dx = -box; dx <= box; dx++) {
              if (dx * dx + dy * dy <= rp * rp) sum += at(px + dx, py + dy);
            }
          }
          // 明暗两侧：沿光照方向各取半径的一半处
          const lx = Math.cos(p.la);
          const ly = Math.sin(p.la);
          return {
            sum,
            lit: at(px + lx * rp * 0.5, py + ly * rp * 0.5),
            shade: at(px - lx * rp * 0.5, py - ly * rp * 0.5),
          };
        }),
      };
    },
    { pts, t },
  );
}

/**
 * 页内算不了 lightAngle（要圆心），在这里连同半径一起备好。
 *
 * 画幅按 dpr=2 的 harness 算：800×450 CSS 的画布在 dpr=1 下短边只有 450，
 * 行星半径会掉到两三个像素，明暗交界在那种尺寸上量出来全是抗锯齿噪声。
 */
function planetProbes(t, W = 1600, H = 900) {
  const st = planetStyle();
  const cx = W / 2;
  const cy = H * 0.485;
  return PLANETS.map((p) => {
    const pos = planetPos(p, t);
    return {
      x: pos.x,
      y: pos.y,
      rp: p.r * st.r,
      la: lightAngle(p, pos.x * W, pos.y * H, cx, cy, t),
    };
  });
}

test("每颗行星都有明暗交界——读成球，不是读成光点", async () => {
  // 这是于淼返工的要害：均匀发亮的圆盘无论多大、放哪儿，都还是个光点，
  // 跟下落的光屑分不开。光屑是加色叠出来的亮团，径向对称；有相位的球
  // 在亮面与暗面之间必须差出一大截。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser, 2);
    const r = await probePlanets(page, planetProbes(T_SKY), T_SKY);
    assert.deepEqual(errs, [], errs.join("; "));

    for (const [i, p] of r.rows.entries()) {
      assert.ok(
        p.lit > 40,
        `第 ${i + 1} 颗的亮面只有 ${p.lit.toFixed(0)} 级——没画上，` +
          `或者画的位置没跟着慢漂走`,
      );
      assert.ok(
        p.lit - p.shade >= 18,
        `第 ${i + 1} 颗亮面 ${p.lit.toFixed(0)}、暗面 ${p.shade.toFixed(0)}，` +
          `只差 ${(p.lit - p.shade).toFixed(0)} 级——这是个均匀的光斑不是球`,
      );
    }
  } finally {
    await browser.close();
  }
});

test("行星不眨眼，而同一把尺子量得出恒星在眨", async () => {
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser, 2);
    const a = await probePlanets(page, planetProbes(T_SKY), T_SKY);
    const b = await probePlanets(page, planetProbes(T_SKY + 0.5), T_SKY + 0.5);
    const maxDelta = await page.evaluate(
      ({ t }) => {
        const { cv, g, mk, lum } = window.__sky;
        const app = mk("offline", 1);
        app.previewFrame(t);
        const A = g.getImageData(0, 0, cv.width, cv.height).data;
        app.previewFrame(t + 0.5);
        const B = g.getImageData(0, 0, cv.width, cv.height).data;
        let m = 0;
        for (let i = 0; i < A.length; i += 4) {
          m = Math.max(m, Math.abs(lum(A, i) - lum(B, i)));
        }
        return m;
      },
      { t: T_SKY },
    );
    assert.deepEqual(errs, [], errs.join("; "));

    // 对照：同样这半秒里，画面别处（星野在闪）能差出几十级。没有这一条，
    // "行星没变"可能只是因为半秒里整幅画都没变。
    assert.ok(
      maxDelta > 40,
      `半秒里全画面最大只差了 ${maxDelta.toFixed(1)} 级，这把尺子量不出闪烁`,
    );
    for (const [i, p] of a.rows.entries()) {
      const q = b.rows[i];
      const rel = Math.abs(q.sum - p.sum) / Math.max(1, p.sum);
      assert.ok(
        rel < 0.06,
        `第 ${i + 1} 颗半秒里整盘亮度变了 ${(rel * 100).toFixed(1)}%——它在眨眼。` +
          `会眨的是恒星，行星不眨，这是这一层"像真夜空"的根据`,
      );
    }
  } finally {
    await browser.close();
  }
});

/**
 * 两份最小 timelineDoc：只有一件事不同——最后一段的 hueShift 落在暖色
 * 区间还是冷色区间。不借真实歌曲的 timeline.json，是因为这条测试要钉住
 * 的是"暖色/冷色区间"这条边界本身，跟哪首歌无关；用真实歌曲反而要事先
 * 算出 t 对应第几段，脆弱又绕远。
 *
 * 段落号 5 的 hueShift=(5*37)%360=185 → hue=(210+185)%360=35（暖，跟
 * 歌里 t≈81 的暖金段落同一个 hue）；段落号 3 的 hueShift=111 →
 * hue=321（冷，跟歌里 t≈27 的紫色段落同一个 hue）。段落全用同一份
 * energy/占位字段，只有数量（决定探到第几段）不同。
 */
function skySections(n) {
  return Array.from({ length: n }, (_, i) => ({ t: i, name: "", energy: 0.3 }));
}
const WARM_DOC = {
  meta: { title: "warm", duration: 20, bpm: 120, codec: "aac-64k", schemaVersion: 1 },
  sections: skySections(6), // 探 t=6 时用第 5 段：hue=35，暖
  beats: [0],
  downbeats: [0],
  ring: { envelope: "AA==", presence: "AA==" },
  lanes: [],
  lyrics: [],
};
const COOL_DOC = {
  meta: { title: "cool", duration: 20, bpm: 120, codec: "aac-64k", schemaVersion: 1 },
  sections: skySections(4), // 探 t=4 时用第 3 段：hue=321，冷（紫色那一档）
  beats: [0],
  downbeats: [0],
  ring: { envelope: "AA==", presence: "AA==" },
  lanes: [],
  lyrics: [],
};
const WARM_PROBE_T = 6;
const COOL_PROBE_T = 4;

/** sRGB → HSL，只要 h（0…360）与 s（0…100）。 */
function rgb2hs(r, g, b) {
  r /= 255;
  g /= 255;
  b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return { h: 0, s: 0 };
  const d = max - min;
  const s = d / (1 - Math.abs(2 * l - 1));
  let h;
  if (max === r) h = ((g - b) / d) % 6;
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  h = ((h * 60) % 360 + 360) % 360;
  return { h, s: s * 100 };
}

/**
 * 采样某颗行星球面最亮的那一点：`face` 渐变第 0 站正好落在
 * `(px + lx*rp*0.55, py + ly*rp*0.55)`，那一点的颜色就是
 * `hsl(ph, psat, st.lit)` 本身，不掺渐变插值、不掺明暗交界。
 */
function samplePlanetColor(page, p, t) {
  return page.evaluate(
    ({ p, t }) => {
      // bg 是 `import * as backgroundLayer` 的模块命名空间对象，
      // planetPos/lightAngle/planetStyle 都是它的属性——不用指望
      // main.js 把这些内部几何函数也重新导出成 murRippleApp.xxx。
      const { cv, g, bg } = window.__sky;
      const geom = window.__sky.geom();
      const st = bg.planetStyle();
      const pos = bg.planetPos(p, t);
      const short = Math.min(geom.W, geom.H);
      const px = pos.x * geom.W;
      const py = pos.y * geom.H;
      const rp = p.r * st.r * (short / 900);
      const la = bg.lightAngle(p, px, py, geom.cx, geom.cy, t);
      const lx = Math.cos(la);
      const ly = Math.sin(la);
      const sx = Math.round(px + lx * rp * 0.55);
      const sy = Math.round(py + ly * rp * 0.55);
      const d = g.getImageData(sx, sy, 1, 1).data;
      return { r: d[0], g: d[1], b: d[2] };
    },
    { p, t },
  );
}

test("暖色补偿真的画进了帧里：暖段饱和度提了、六颗色相间距拉开了；紫色段一点没动", async () => {
  // 上一条测试钉的是 warmHueCompensation() 这个纯函数本身；这一条钉的是
  // "draw() 真的在用它"——纯函数写对了，忘了接进 draw() 或者接错了地方，
  // 上一条测试照样是绿的，只有量实际画出来的像素才抓得住。
  const browser = await chromium.launch();
  try {
    const { page, errs } = await openPage(browser, 2);
    await page.evaluate(
      ({ warmDoc, coolDoc }) => {
        window.__sky.warmApp = window.__sky.mkDoc(warmDoc, "offline", 1);
        window.__sky.coolApp = window.__sky.mkDoc(coolDoc, "offline", 1);
      },
      { warmDoc: WARM_DOC, coolDoc: COOL_DOC },
    );

    // 暖段：先画一帧，再挨个采样六颗球面最亮点的颜色。
    await page.evaluate(
      ({ t }) => window.__sky.warmApp.previewFrame(t),
      { t: WARM_PROBE_T },
    );
    const warmPixels = [];
    for (const p of PLANETS) {
      warmPixels.push(await samplePlanetColor(page, p, WARM_PROBE_T));
    }

    // 冷（紫）段：同样采样。
    await page.evaluate(
      ({ t }) => window.__sky.coolApp.previewFrame(t),
      { t: COOL_PROBE_T },
    );
    const coolPixels = [];
    for (const p of PLANETS) {
      coolPixels.push(await samplePlanetColor(page, p, COOL_PROBE_T));
    }
    assert.deepEqual(errs, [], errs.join("; "));

    const warmHS = warmPixels.map((px) => rgb2hs(px.r, px.g, px.b));
    const coolHS = coolPixels.map((px) => rgb2hs(px.r, px.g, px.b));

    // 一、饱和度：暖段该比紫色段整体更饱和（satBoost=18）。**用六颗的均值
    // 比、不用逐颗比对固定门槛**——这几颗行星离圆心的实测距离各不相同，
    // 暗角（全画面统一的一圈暗角渐变）按到暗角圆心的距离压暗每一颗，越
    // 靠外压得越多，六颗压暗的幅度并不一样，逐颗设一个固定饱和度门槛会
    // 被这个位置相关的压暗量误伤（实测量过：确实有正确实现被单颗门槛
        // 冤枉判负的情况）。而暗角对暖、冷两段同一颗行星的压暗幅度几乎相同
    // （两段行星位置几乎一样，慢漂一秒挪不到半个像素），六颗一起取均值
    // 再比较，这个共同的压暗量会互相抵消，剩下的差距才是补偿本身的贡献。
    const meanSat = (rows) => rows.reduce((a, hs) => a + hs.s, 0) / rows.length;
    const warmMeanSat = meanSat(warmHS);
    const coolMeanSat = meanSat(coolHS);
    assert.ok(
      warmMeanSat - coolMeanSat > 5,
      `暖段六颗均值饱和度 ${warmMeanSat.toFixed(1)}%，紫色段 ` +
        `${coolMeanSat.toFixed(1)}%，只差 ${(warmMeanSat - coolMeanSat).toFixed(1)} ` +
        `个点——实测补偿被删掉时这个差只有 0.9 点、补偿无条件生效时只有 ` +
        `2.0 点，都进不了这条 5 点的门槛；正确实现量出来是约 10.4 点`,
    );

    // 二、色相间距：p2（hoff=34）与 p0（hoff=-30）基线相差 64°；暖段补偿
    // （spread=1.6）把它拉到约 102°，冷段原样是 64°。用循环色相距离，
    // 避免 360°/0° 卷绕算错。色相基本不受暗角影响（暗角是往同一个近黑色
    // 混，混合比例小时色相漂得很轻），实测这条即使不摊均值、只看 p2/p0
    // 单独一对，量出来的角度也和纯公式算出来的预期几乎吻合。
    const hueDist = (a, b) => {
      const d = Math.abs(a - b) % 360;
      return d > 180 ? 360 - d : d;
    };
    const warmSpan = hueDist(warmHS[2].h, warmHS[0].h);
    const coolSpan = hueDist(coolHS[2].h, coolHS[0].h);
    assert.ok(
      warmSpan > 80,
      `暖段 p2/p0 色相只差了 ${warmSpan.toFixed(1)}°（基线是 64°）——` +
        `色相间距没被拉开，补偿没生效`,
    );
    assert.ok(
      coolSpan < 80,
      `紫色段 p2/p0 色相差到了 ${coolSpan.toFixed(1)}°（基线是 64°）——` +
        `色相间距被拉开了，说明补偿在冷色段也生效了，紫色段被误伤`,
    );
  } finally {
    await browser.close();
  }
});
