import test from "node:test";
import assert from "node:assert/strict";
import { pulseAt, computeBeat } from "../src/core/beat.js";

// 刻意用有偏移的网格：真实曲目的拍点从 1.776s 起，不是 0
const beats = [1.776, 2.287, 2.798, 3.309, 3.82];

test("正好落在拍点上时脉冲为 1", () => {
  assert.ok(Math.abs(pulseAt(beats, 2.287) - 1) < 1e-9);
});

test("离拍点越远脉冲越小", () => {
  const near = pulseAt(beats, 2.31);
  const far = pulseAt(beats, 2.6);
  assert.ok(near > far, `越近应越大：${near} vs ${far}`);
  assert.ok(far >= 0 && far <= 1);
});

test("第一个拍点之前脉冲为 0", () => {
  assert.equal(pulseAt(beats, 0.5), 0, "网格有偏移，之前不应有脉冲");
});

test("末个拍点之后继续衰减而不是归零或翻转", () => {
  const a = pulseAt(beats, 3.9);
  const b = pulseAt(beats, 5.0);
  assert.ok(a > b && b >= 0, `应单调衰减：${a} → ${b}`);
});

test("是 t 的纯函数：同样输入永远同样输出，与调用顺序无关", () => {
  const forward = [2.0, 2.5, 3.0].map((t) => pulseAt(beats, t));
  const backward = [3.0, 2.5, 2.0].map((t) => pulseAt(beats, t)).reverse();
  assert.deepEqual(forward, backward, "倒着算与正着算必须一致——不能有累积状态");
});

test("tau 越大衰减越慢", () => {
  const t = 2.4;
  assert.ok(pulseAt(beats, t, 300) > pulseAt(beats, t, 80));
});

test("空拍点数组返回 0 而不是抛错", () => {
  assert.equal(pulseAt([], 5), 0);
});

test("computeBeat 同时给出拍点与小节线脉冲", () => {
  const timeline = { beats, downbeats: [1.776, 3.82] };
  const b = computeBeat(timeline, 3.82);
  assert.ok(Math.abs(b.downPulse - 1) < 1e-9, "正落在小节线上");
  assert.ok(Math.abs(b.pulse - 1) < 1e-9, "小节线也是拍点");
});

test("非小节线的拍点上，downPulse 明显小于 pulse", () => {
  const timeline = { beats, downbeats: [1.776, 3.82] };
  const b = computeBeat(timeline, 2.287);
  assert.ok(b.pulse > 0.9, `应正落在拍点上，实得 ${b.pulse}`);
  assert.ok(b.downPulse < 0.5, `离小节线远，实得 ${b.downPulse}`);
});
