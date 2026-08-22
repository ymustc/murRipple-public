import test from "node:test";
import assert from "node:assert/strict";
import { sweepAt, SWEEP_DUR } from "../src/layers/sweep.js";

const secs = [{ t: 0 }, { t: 10 }, { t: 25 }];

test("每段开头扫一圈，扫完就没了", () => {
  assert.ok(sweepAt(secs, 10.2), "刚换段应该在扫");
  assert.equal(sweepAt(secs, 10 + SWEEP_DUR + 0.01), null, "扫完就没了");
  assert.ok(sweepAt(secs, 25.5), "下一段照样扫");
  assert.equal(sweepAt(secs, 20), null, "段落中间不扫");
});

test("第一段不扫", () => {
  // t=0 那段是曲子开头，不是「换段」。开场就来一道扫很突兀，而且那时画面
  // 还没建立起来，观众根本不知道自己在看什么。
  assert.equal(sweepAt(secs, 0), null);
  assert.equal(sweepAt(secs, 0.3), null);
  assert.equal(sweepAt(secs, 9.9), null);
});

test("头部角度在时长内恰好扫满一整圈", () => {
  const a0 = sweepAt(secs, 10.0001).head;
  const a1 = sweepAt(secs, 10 + SWEEP_DUR - 0.0001).head;
  assert.ok(
    Math.abs(a1 - a0 - Math.PI * 2) < 0.01,
    `应扫满 2π，实得 ${(a1 - a0).toFixed(4)}`,
  );
});

test("自正上方起扫", () => {
  const { head } = sweepAt(secs, 10.0001);
  assert.ok(Math.abs(head + Math.PI / 2) < 0.01, `应从 −π/2 起，实得 ${head}`);
});

test("是纯函数：倒着查与正着查一致", () => {
  const at = (t) => sweepAt(secs, t)?.head ?? null;
  const fwd = [10.2, 10.6, 25.3].map(at);
  const bwd = [25.3, 10.6, 10.2].map(at).reverse();
  assert.deepEqual(fwd, bwd);
});
