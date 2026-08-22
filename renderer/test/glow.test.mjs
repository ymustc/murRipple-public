import test from "node:test";
import assert from "node:assert/strict";
import { glowStops } from "../src/core/glow.js";

test("止点从中心到边缘单调衰减", () => {
  const stops = glowStops(1);
  for (let i = 1; i < stops.length; i++) {
    assert.ok(stops[i][1] <= stops[i - 1][1], `第 ${i} 个止点的 alpha 回升了`);
  }
});

test("offset 覆盖 0 到 1 且严格升序", () => {
  const stops = glowStops(1);
  assert.equal(stops[0][0], 0);
  assert.equal(stops[stops.length - 1][0], 1);
  for (let i = 1; i < stops.length; i++) {
    assert.ok(stops[i][0] > stops[i - 1][0], "offset 必须严格升序");
  }
});

test("边缘 alpha 必须归零，否则精灵会有硬边", () => {
  const stops = glowStops(1);
  assert.equal(stops[stops.length - 1][1], 0);
});

test("intensity 线性缩放中心 alpha", () => {
  assert.ok(Math.abs(glowStops(0.5)[0][1] - glowStops(1)[0][1] * 0.5) < 1e-6);
});

test("intensity 为 0 时全透明", () => {
  assert.ok(glowStops(0).every(([, a]) => a === 0));
});

test("alpha 恒在 [0,1]，即使 intensity 越界", () => {
  for (const intensity of [-1, 0, 0.3, 1, 2, 99]) {
    for (const [, a] of glowStops(intensity)) {
      assert.ok(a >= 0 && a <= 1, `intensity=${intensity} 出现越界 alpha ${a}`);
    }
  }
});

test("中段衰减必须够快，否则叠加后是一团糊光而非辉光", () => {
  const stops = glowStops(1);
  const mid = stops.find(([o]) => o >= 0.25 && o < 0.6);
  assert.ok(mid, "应有一个位于 0.25~0.6 的中段止点");
  assert.ok(mid[1] < 0.6, `中段 alpha 应显著低于中心，实得 ${mid[1]}`);
});
