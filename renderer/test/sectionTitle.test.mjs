import test from "node:test";
import assert from "node:assert/strict";
import { fadeAt, SHOW_SEC } from "../src/layers/sectionTitle.js";

test("淡入到满、停留、再淡出，两端恰好为 0", () => {
  assert.equal(fadeAt(0), 0, "段落刚开始时应为 0，不能凭空出现");
  assert.ok(Math.abs(fadeAt(0.25) - 0.5) < 1e-9, "淡入中点应为一半");
  assert.equal(fadeAt(0.5), 1, "淡入结束应满");
  assert.equal(fadeAt(2.0), 1, "停留期恒满");
  assert.ok(Math.abs(fadeAt(SHOW_SEC - 1e-9)) < 1e-6, "淡出末尾应趋于 0");
});

test("停留期之后彻底消失，不留残影", () => {
  assert.equal(fadeAt(SHOW_SEC), 0);
  assert.equal(fadeAt(SHOW_SEC + 10), 0);
  assert.equal(fadeAt(120), 0, "段落再长也只显示开头那几秒");
});

test("负的年龄返回 0", () => {
  // sectionIndexAt 理论上不会给出负值，但兜底比断言便宜
  assert.equal(fadeAt(-1), 0);
});

test("是纯函数：倒着查与正着查一致", () => {
  const fwd = [0.2, 0.8, 2.5, 3.4].map(fadeAt);
  const bwd = [3.4, 2.5, 0.8, 0.2].map(fadeAt).reverse();
  assert.deepEqual(fwd, bwd);
});
