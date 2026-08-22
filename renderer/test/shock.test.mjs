import test from "node:test";
import assert from "node:assert/strict";
import { activeShocks, SHOCK_LIFE } from "../src/layers/shock.js";

const notes = [
  { t: 1.0, v: 0.5, pitch: null },
  { t: 1.3, v: 0.9, pitch: null },
  { t: 5.0, v: 0.4, pitch: null },
];

test("冲击弧只由音符决定，跳到任意时刻都对", () => {
  // 参考实现是 shocks.push 逐帧累积的：跳到第 200 秒直接渲染时数组是空的，
  // 冲击弧整个消失。反查则怎么跳都对。
  assert.deepEqual(
    activeShocks(notes, 1.4).map((s) => s.noteIdx),
    [0, 1],
    "两次命中间隔 0.3 秒，都还在 0.55 秒寿命内",
  );
  assert.deepEqual(
    activeShocks(notes, 1.7).map((s) => s.noteIdx),
    [1],
    "1.0 那道已过期",
  );
  assert.deepEqual(activeShocks(notes, 0.5), [], "还没命中");
  assert.deepEqual(activeShocks([], 3), [], "空列表不抛错");
});

test("倒着查与正着查一致", () => {
  const fwd = [1.1, 1.4, 2.0].map((t) => activeShocks(notes, t).length);
  const bwd = [2.0, 1.4, 1.1].map((t) => activeShocks(notes, t).length).reverse();
  assert.deepEqual(fwd, bwd);
});

test("半径按 q² 加速扩张，不是匀速", () => {
  // q² 而不是线性：冲击应当是「猛地弹出、后段变缓」。线性看着像匀速涟漪，
  // 与已有的小节涟漪撞车，两者就分不出来了。
  const at = (dt) => activeShocks([{ t: 2.0, v: 1 }], 2.0 + dt)[0];
  const q25 = at(SHOCK_LIFE * 0.25).reach;
  const q50 = at(SHOCK_LIFE * 0.5).reach;
  const q75 = at(SHOCK_LIFE * 0.75).reach;
  // 匀速的话三段增量相等；q² 下后段增量必须明显更大
  assert.ok(
    q75 - q50 > (q50 - q25) * 1.4,
    `后半段应扩得更快（q² 的特征）：${(q50 - q25).toFixed(1)} → ${(q75 - q50).toFixed(1)}`,
  );
});

test("刚命中时 q 为 0、透明度最大；寿命末尾归零", () => {
  const [born] = activeShocks([{ t: 2.0, v: 1 }], 2.0);
  assert.equal(born.q, 0);
  assert.equal(born.reach, 0, "刚命中时还没扩出去");
  assert.ok(Math.abs(born.alpha - 0.55) < 1e-9, `实得 ${born.alpha}`);

  const [late] = activeShocks([{ t: 2.0, v: 1 }], 2.0 + SHOCK_LIFE - 1e-6);
  assert.ok(late.alpha < 1e-4, `寿命末尾 alpha 应趋于 0，实得 ${late.alpha}`);
  assert.deepEqual(
    activeShocks([{ t: 2.0, v: 1 }], 2.0 + SHOCK_LIFE + 0.01),
    [],
    "过期即消失",
  );
});

test("力度越大扩得越远，跨度随时间收窄", () => {
  const soft = activeShocks([{ t: 2.0, v: 0.1 }], 2.3)[0];
  const loud = activeShocks([{ t: 2.0, v: 1.0 }], 2.3)[0];
  assert.ok(loud.reach > soft.reach * 1.3, `${soft.reach} → ${loud.reach}`);

  const early = activeShocks([{ t: 2.0, v: 1 }], 2.05)[0];
  const later = activeShocks([{ t: 2.0, v: 1 }], 2.5)[0];
  assert.ok(later.span < early.span, `跨度应收窄：${early.span} → ${later.span}`);
});
