import test from "node:test";
import assert from "node:assert/strict";
import { activeRipples, LIFE_SEC } from "../src/layers/ripple.js";

const dbs = [1.0, 2.0, 3.0];

test("涟漪只由小节线决定，不依赖任何累积状态", () => {
  // 参考实现是 ripples.push(...) 逐帧累积的；那样跳到第 200 秒直接渲染，
  // 数组是空的、涟漪消失。这里是反查，跳到哪儿都对。
  assert.deepEqual(
    activeRipples(dbs, 2.1).map((r) => r.t0),
    [2.0],
    "刚过 2.0 时只有它在场，1.0 那圈早过期了",
  );
  assert.deepEqual(activeRipples(dbs, 0.5), [], "还没到第一条小节线");
  assert.deepEqual(
    activeRipples([2.0, 2.5], 2.6).map((r) => r.t0),
    [2.0, 2.5],
    "挨得近的两条可以同时在场",
  );
});

test("倒着查与正着查完全一致", () => {
  const fwd = [1.5, 2.2, 3.4].map((t) => activeRipples(dbs, t).length);
  const bwd = [3.4, 2.2, 1.5].map((t) => activeRipples(dbs, t).length).reverse();
  assert.deepEqual(fwd, bwd);
});

test("年龄线性增长，透明度线性衰到 0 且不为负", () => {
  const [rp] = activeRipples([2.0], 2.3);
  assert.ok(Math.abs(rp.age - 0.3) < 1e-9, `age 应为 0.3，实得 ${rp.age}`);
  assert.ok(
    rp.alpha > 0 && rp.alpha < 0.16,
    `中途 alpha 应在 (0,0.16)，实得 ${rp.alpha}`,
  );

  // 寿命末尾必须趋于 0——留一圈突然消失的残环最难看
  const [late] = activeRipples([2.0], 2.0 + LIFE_SEC - 1e-6);
  assert.ok(late.alpha < 1e-4, `寿命末尾 alpha 应趋于 0，实得 ${late.alpha}`);

  assert.deepEqual(
    activeRipples([2.0], 2.0 + LIFE_SEC + 0.01),
    [],
    "过期就该消失",
  );
});

test("刚触发时透明度最大", () => {
  const [rp] = activeRipples([2.0], 2.0);
  assert.ok(Math.abs(rp.alpha - 0.16) < 1e-9, `实得 ${rp.alpha}`);
});

test("小节线为空时不抛错", () => {
  assert.deepEqual(activeRipples([], 5), []);
});
