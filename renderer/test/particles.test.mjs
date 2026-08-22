import test from "node:test";
import assert from "node:assert/strict";
import { createParticleWorld, PARTICLES_PER_HIT } from "../src/core/particles.js";
import { STEP } from "../src/core/clock.js";
import { laneAngle } from "../src/core/notes.js";

function fakeTimeline() {
  return {
    lanes: [
      {
        id: "kick", hue: 28, gain: 1,
        notes: [
          { t: 0.5, v: 0.9, pitch: null },
          { t: 1.0, v: 0.5, pitch: null },
        ],
      },
      {
        id: "bass", hue: 225, gain: 1,
        notes: [{ t: 0.75, v: 0.7, pitch: 36 }],
      },
    ],
  };
}

/**
 * 用固定步长把世界推进到**绝对时刻** t。
 *
 * 必须读 world.simT 而不是自己从 0 数：连着调两次时，自己数会变成
 * "再推进 t 秒"而不是"推进到 t 秒"，确定性那条测试就会以错误的理由
 * 失败——最消耗人的那种假阳性。
 */
function advanceTo(world, t) {
  while (world.simT + STEP <= t) world.step(STEP);
  return world;
}

test("命中后才发射，命中前一粒都没有", () => {
  const w = createParticleWorld(fakeTimeline(), 1);
  advanceTo(w, 0.4);
  assert.equal(w.particles.length, 0, "第一个音符在 0.5 秒，之前不该有粒子");
});

test("命中时发射，粒子数与命中数成比例", () => {
  const w = createParticleWorld(fakeTimeline(), 1);
  advanceTo(w, 0.55);
  assert.ok(w.particles.length > 0, "0.5 秒的音符应已发射");
  assert.ok(
    w.particles.length <= PARTICLES_PER_HIT,
    `只命中一个音符，不该超过 ${PARTICLES_PER_HIT} 粒`,
  );
});

test("同一个音符只发射一次", () => {
  const a = createParticleWorld(fakeTimeline(), 1);
  advanceTo(a, 0.55);
  const afterFirst = a.particles.length;
  // 断言绝对值而不是「没有变多」：只要两次发射都落在第一个取样点之前，
  // later <= afterFirst 照样成立，什么也没测到。
  assert.equal(
    afterFirst,
    Math.round(PARTICLES_PER_HIT * (0.4 + 0.9 * 0.6)),
    `0.9 力度的单次命中应恰好发射这么多粒，实得 ${afterFirst}——多了就是重复发射`,
  );
  advanceTo(a, 0.6);
  assert.equal(
    a.particles.length,
    afterFirst,
    "0.55→0.6 之间没有新音符，粒子数必须一字不动",
  );
});

test("光屑的 anchor 就是音符落点的方位角，不是别的角", () => {
  // 这条守着 bbebd65 的核心修复：原先 anchor 错用了随机飞散方向，每次
  // 爆发均匀撒在整个环上，与音符落在哪儿毫无关系——而全部测试都是绿的。
  const w = createParticleWorld(fakeTimeline(), 1);
  advanceTo(w, 0.8);
  const kick = w.particles.filter((p) => p.hue === 28);
  const bass = w.particles.filter((p) => p.hue === 225);
  assert.ok(kick.length > 0 && bass.length > 0, "两条轨道都应已命中");
  for (const p of kick) {
    assert.ok(
      Math.abs(p.anchor - laneAngle(0, 2, null)) < 1e-9,
      `底鼓光屑应从 lane0 落点爆开，实得 ${p.anchor}`,
    );
  }
  for (const p of bass) {
    assert.ok(
      Math.abs(p.anchor - laneAngle(1, 2, 36)) < 1e-9,
      `贝斯光屑应从 lane1 落点爆开，实得 ${p.anchor}`,
    );
  }
  assert.notEqual(kick[0].anchor, bass[0].anchor, "不同轨道不能从同一点爆开");
});

test("光屑确实会飞出去，而且会减速", () => {
  // 「坐标是归一化偏移」那条只有 |x| < 5 的上界，取样又在刚发射的时刻，
  // 位移本就 ≈0——粒子完全不动、初速为零、没有阻尼，三种都能骗过它。
  const w = createParticleWorld(fakeTimeline(), 1);
  advanceTo(w, 0.51);
  const born = w.particles.map((p) => Math.hypot(p.vx, p.vy));
  assert.ok(born.length > 0);

  advanceTo(w, 0.9);
  const alive = w.particles.filter((p) => p.hue === 28);
  const maxR = Math.max(...alive.map((p) => Math.hypot(p.x, p.y)));
  assert.ok(maxR > 0.05, `0.4 秒后最远的一粒只飞了 ${maxR} 个环半径，等于没动`);
  assert.ok(maxR < 1.0, `飞出 ${maxR} 个环半径，太远了——不该盖到外圈去`);

  const now = Math.max(...alive.map((p) => Math.hypot(p.vx, p.vy)));
  assert.ok(
    now < Math.max(...born) * 0.95,
    `应有阻尼：初速 ${Math.max(...born)} → 0.4 秒后 ${now}`,
  );
});

test("发射数随力度增长，且满力度用满配额", () => {
  const mk = (v) => {
    const w = createParticleWorld(
      { lanes: [{ id: "k", hue: 1, gain: 1, notes: [{ t: 0.5, v, pitch: null }] }] },
      1,
    );
    advanceTo(w, 0.55);
    return w.particles.length;
  };
  const soft = mk(0.1);
  const loud = mk(1.0);
  assert.ok(loud > soft * 1.5, `强命中应明显多于弱命中：${soft} → ${loud}`);
  assert.equal(loud, PARTICLES_PER_HIT, `满力度应发满 ${PARTICLES_PER_HIT} 粒`);
  assert.ok(
    soft >= 1 && soft <= PARTICLES_PER_HIT / 2,
    `弱命中应少于半配额，实得 ${soft}`,
  );
});

test("t=0 的音符也会炸开", () => {
  // 发射区间左开，若左端点从 simT=0 起算，首步就是 (0, STEP]，t=0 的音符
  // 被漏掉——而 analyze.py 的 onset 回溯完全可能把首个 onset 推到 0.0，
  // 那个音符会落地却不炸。demo 首曲最早的 onset 是 0.0232，只差一帧。
  const w = createParticleWorld(
    { lanes: [{ id: "k", hue: 9, gain: 1, notes: [{ t: 0, v: 0.8, pitch: null }] }] },
    1,
  );
  advanceTo(w, 0.4);
  assert.ok(w.particles.length > 0, "落在 t=0 的音符同样该爆开光屑");
});

test("每个音符、每条轨道的光屑图案都不一样", () => {
  // 上一条只验了「不受之前发射了多少粒影响」，没验种子真的**含**这两项：
  // 丢掉 noteIdx（同轨道每个音符炸出同一图案）或丢掉 laneIdx（不同轨道
  // 同下标图案相同），它照样是绿的。
  const shape = (w, hue, lifeMin) =>
    w.particles
      .filter((p) => p.hue === hue && p.life > lifeMin)
      .map((p) => `${p.vx.toFixed(6)}|${p.vy.toFixed(6)}`)
      .sort()
      .join(",");

  const sameLane = {
    lanes: [
      {
        id: "k", hue: 28, gain: 1,
        notes: [
          { t: 0.5, v: 0.6, pitch: null },
          { t: 1.0, v: 0.6, pitch: null },
        ],
      },
    ],
  };
  const first = shape(advanceTo(createParticleWorld(sameLane, 1), 0.55), 28, 0);
  const second = shape(advanceTo(createParticleWorld(sameLane, 1), 1.05), 28, 0.4);
  assert.ok(first.length > 0 && second.length > 0);
  assert.notEqual(second, first, "同轨道相邻音符图案相同——种子没带上 noteIdx");

  const twoLanes = {
    lanes: [
      { id: "a", hue: 10, gain: 1, notes: [{ t: 0.5, v: 0.6, pitch: null }] },
      { id: "b", hue: 200, gain: 1, notes: [{ t: 0.5, v: 0.6, pitch: null }] },
    ],
  };
  const w3 = advanceTo(createParticleWorld(twoLanes, 1), 0.55);
  assert.notEqual(
    shape(w3, 200, 0),
    shape(w3, 10, 0),
    "两条轨道图案相同——种子没带上 laneIdx",
  );
});

test("粒子会过期消失", () => {
  const w = createParticleWorld(fakeTimeline(), 1);
  advanceTo(w, 0.55);
  assert.ok(w.particles.length > 0);
  advanceTo(w, 5.0);
  assert.equal(w.particles.length, 0, "5 秒后早该全部过期");
});

test("确定性：推进节奏不影响最终状态", () => {
  // 一步到位
  const a = createParticleWorld(fakeTimeline(), 1);
  advanceTo(a, 1.2);

  // 分多次推进到同一时刻
  const b = createParticleWorld(fakeTimeline(), 1);
  for (const t of [0.3, 0.55, 0.8, 1.0, 1.2]) advanceTo(b, t);

  assert.equal(a.particles.length, b.particles.length, "粒子数必须一致");
  const key = (p) =>
    `${p.x.toFixed(9)}|${p.y.toFixed(9)}|${p.life.toFixed(9)}|${p.hue}`;
  assert.deepEqual(
    a.particles.map(key).sort(),
    b.particles.map(key).sort(),
    "每一粒的位置与寿命都必须完全一致——这是逐帧导出的地基",
  );
});

test("种子按 (轨道, 音符下标) 派生，不受之前发射了多少粒影响", () => {
  // 上面那条确定性测试防不住这个：两个世界的发射顺序完全一致，用全局
  // 随机序列也能得到相同结果。这里让**前一个**音符的力度不同——粒子数
  // 因而不同，全局序列会被推歪——但后一个音符的粒子必须一模一样。
  //
  // 这条约束是给 M3 留的：全曲 270 秒 × 120 步 = 32400 步，每次跳转都从
  // 头重放代价太大；种子只依赖 (轨道, 下标) 才允许将来直接跳。
  // 第二个音符挪到 2.0 秒：粒子最长寿命是 LIFE_SEC×1.45 ≈ 1.16 秒，第一批
  // 在 1.66 秒前全部过期，取样时画面上只剩第二批。此前用"life > 0.4"筛，
  // 寿命区间一拉宽（0.35…1.45）那条筛子就漏了，第一批的残留混了进来。
  const withHeavyFirst = { lanes: [{ id: "kick", hue: 28, gain: 1, notes: [
    { t: 0.5, v: 0.9, pitch: null },
    { t: 2.0, v: 0.5, pitch: null },
  ] }] };
  const withLightFirst = { lanes: [{ id: "kick", hue: 28, gain: 1, notes: [
    { t: 0.5, v: 0.3, pitch: null },
    { t: 2.0, v: 0.5, pitch: null },
  ] }] };

  const a = advanceTo(createParticleWorld(withHeavyFirst, 1), 2.05);
  const b = advanceTo(createParticleWorld(withLightFirst, 1), 2.05);

  const fresh = (w) =>
    w.particles
      .map((p) => `${p.vx.toFixed(9)}|${p.vy.toFixed(9)}|${p.size.toFixed(9)}`)
      .sort();

  assert.ok(fresh(a).length > 0, "2.05 秒时第二个音符应已发射");
  assert.deepEqual(
    fresh(a),
    fresh(b),
    "第二个音符的粒子必须与之前发射过多少粒无关",
  );
});

test("clear 之后从零开始", () => {
  const w = createParticleWorld(fakeTimeline(), 1);
  advanceTo(w, 1.2);
  assert.ok(w.particles.length > 0);
  w.clear();
  assert.equal(w.particles.length, 0);
  advanceTo(w, 0.4);
  assert.equal(w.particles.length, 0, "clear 后重新推进到 0.4 秒，仍不该有粒子");
});

test("坐标与画布尺寸无关——存的是归一化偏移", () => {
  const w = createParticleWorld(fakeTimeline(), 1);
  advanceTo(w, 0.55);
  for (const p of w.particles) {
    assert.ok(Math.abs(p.x) < 5, `x=${p.x} 看着像像素而不是归一化偏移`);
    assert.ok(Math.abs(p.y) < 5, `y=${p.y} 同上`);
  }
});

test("低 quality 发射更少的粒子", () => {
  const full = createParticleWorld(fakeTimeline(), 1);
  const low = createParticleWorld(fakeTimeline(), 0.5);
  advanceTo(full, 0.55);
  advanceTo(low, 0.55);
  assert.ok(
    low.particles.length < full.particles.length,
    `降级应减少粒子：full=${full.particles.length} low=${low.particles.length}`,
  );
});

test("粒子色相取自各自的轨道，不是同一个常数", () => {
  // 只在 0.55 秒取样、断言 every(hue === 28) 是不够的：那时只有底鼓命中，
  // 把 hue 写死成常量 28 同样通过。推到两条轨道都命中之后再看。
  const w = createParticleWorld(fakeTimeline(), 1);
  advanceTo(w, 0.8);
  const hues = [...new Set(w.particles.map((p) => p.hue))].sort((a, b) => a - b);
  assert.deepEqual(hues, [28, 225], `应恰好有两种色相，实得 ${hues}`);
});

test("阻尼是每秒衰到 16.3%，与步长无关", () => {
  // 断言实际的衰减率，而不是拍脑袋的阈值。写这条时我一度以为我们的阻尼
  // 比参考项目弱、要改成它的 pow(0.25, dt)——方向搞反了：每秒 25% 比每秒
  // 16.3% 衰得**慢**。有这条在，下次再想"照搬参考参数"时会立刻被拦下。
  const w = createParticleWorld(fakeTimeline(), 1);
  advanceTo(w, 0.51);
  const born = Math.max(...w.particles.map((p) => Math.hypot(p.vx, p.vy)));
  assert.ok(born > 0, "刚发射时应有速度");

  const DT = 0.25;
  advanceTo(w, 0.51 + DT);
  const alive = w.particles.filter((p) => p.hue === 28);
  assert.ok(alive.length > 0, "0.25 秒后还该有粒子在场");
  const now = Math.max(...alive.map((p) => Math.hypot(p.vx, p.vy)));

  const want = Math.pow(0.163, DT);
  const got = now / born;
  assert.ok(
    Math.abs(got - want) < 0.03,
    `0.25 秒后速度比应为 ${want.toFixed(3)}（每秒 16.3%），实得 ${got.toFixed(3)}`,
  );
});

test("高频轨的光屑带十字星芒标记", () => {
  // 碎玉（hat）与缥缈（air）本来就是"细碎的光"，圆点表达不出那种锐利。
  const w = createParticleWorld(
    {
      lanes: [
        { id: "hat", hue: 195, gain: 1, notes: [{ t: 0.5, v: 0.8, pitch: null }] },
        { id: "bass", hue: 225, gain: 1, notes: [{ t: 0.5, v: 0.8, pitch: null }] },
      ],
    },
    1,
  );
  advanceTo(w, 0.55);
  const hat = w.particles.filter((p) => p.hue === 195);
  const bass = w.particles.filter((p) => p.hue === 225);
  assert.ok(hat.length > 0 && bass.length > 0);
  assert.ok(hat.every((p) => p.glint), "hat 的光屑都该带星芒");
  assert.ok(bass.every((p) => !p.glint), "bass 的不该带");
});
