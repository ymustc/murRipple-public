import test from "node:test";
import assert from "node:assert/strict";
import { paletteAt, HUE_STEP } from "../src/core/palette.js";

const sections = [
  { t: 0, name: "", energy: 0.1 },
  { t: 10, name: "", energy: 0.5 },
  { t: 20, name: "", energy: 0.9 },
];

test("相邻段落的色相明显不同", () => {
  const a = paletteAt(sections, 5);
  const b = paletteAt(sections, 15);
  const diff = Math.abs(a.hueShift - b.hueShift);
  assert.ok(Math.min(diff, 360 - diff) > 20, `相邻段落色相差应显著，实得 ${diff}`);
});

test("色相步长与 360 互质，段落多时不会提前撞色", () => {
  const gcd = (a, b) => (b ? gcd(b, a % b) : a);
  assert.equal(gcd(HUE_STEP, 360), 1, `HUE_STEP=${HUE_STEP} 与 360 不互质，会提前重复`);
});

test("能量越高越饱和", () => {
  assert.ok(paletteAt(sections, 25).sat > paletteAt(sections, 5).sat);
});

test("饱和度落在约定区间内", () => {
  for (const t of [0, 5, 10, 15, 20, 25, 999]) {
    const p = paletteAt(sections, t);
    assert.ok(p.sat >= 45 && p.sat <= 85, `t=${t} 的 sat=${p.sat} 越界`);
    assert.ok(p.hueShift >= 0 && p.hueShift < 360, `t=${t} 的 hueShift=${p.hueShift} 越界`);
  }
});

test("同一段落内配色恒定，不随 t 漂移", () => {
  assert.deepEqual(paletteAt(sections, 1), paletteAt(sections, 9));
});

test("单段落也能工作", () => {
  const p = paletteAt([{ t: 0, name: "", energy: 0.3 }], 5);
  assert.equal(p.index, 0);
});
