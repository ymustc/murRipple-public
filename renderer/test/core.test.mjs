import test from "node:test";
import assert from "node:assert/strict";
import { coreSize, coreYield } from "../src/layers/core.js";

test("安静时光核收得很小——它要有'静'的状态才谈得上呼吸", () => {
  const rest = coreSize(0, 0);
  assert.ok(rest < 0.45, `静息应小于 0.45R，实得 ${rest}`);
});

test("底鼓主导脉冲，贝斯只做底噪", () => {
  // 这条守的是意图而不是数字。我们的贝斯来自 Demucs 分离，中位 0.677、
  // 几乎一直在响；底鼓中位 0.057、P95 0.756，动态范围极大。让贝斯主导
  // 会把光核钉在一个大尺寸上，看着像恒定的光而不是在呼吸。
  const byKick = coreSize(0, 1) - coreSize(0, 0);
  const byBass = coreSize(1, 0) - coreSize(0, 0);
  assert.ok(
    byKick > byBass * 2.5,
    `底鼓的贡献应远大于贝斯：底鼓 +${byKick.toFixed(2)}、贝斯 +${byBass.toFixed(2)}`,
  );
});

test("满打满算也不超出车道弧太多", () => {
  // 光核比车道弧（1.0R）大一点是对的——它是背景光；但不能盖到谱线上去。
  const max = coreSize(1, 1);
  assert.ok(max > 1.0 && max < 1.5, `峰值应在 1.0–1.5R，实得 ${max}`);
});

test("单调：两个输入都越大，光核越大", () => {
  assert.ok(coreSize(0.5, 0.5) > coreSize(0.2, 0.2));
  assert.ok(coreSize(0, 0.8) > coreSize(0, 0.3));
  assert.ok(coreSize(0.8, 0) > coreSize(0.3, 0));
});

// —— coreYield：有歌词时光核让位 ——

test("没有歌词时一分不让", () => {
  // 前奏、间奏、尾奏光核就是主角，这时收一点都是白丢亮度。
  assert.deepEqual(coreYield(0), { base: 1, lobe: 1, inner: 1, innerR: 1 });
});

test("内芯让得远比基底狠——把字冲白的是它", () => {
  // 内芯是一小团近白的高光，正好落在字后面；基底与瓣是大而散的柔光，
  // 撑着整个中心的存在感。一刀切地整体调暗，画面会塌。
  const y = coreYield(1);
  assert.ok(
    1 - y.inner > (1 - y.base) * 3,
    `内芯让 ${((1 - y.inner) * 100).toFixed(0)}%、基底让 ` +
      `${((1 - y.base) * 100).toFixed(0)}%，内芯没有明显让得更多`,
  );
  assert.ok(y.inner < 0.4, `内芯只让到 ${y.inner}，不足以把字露出来`);
});

test("基底与瓣只收一点，中心不能塌", () => {
  const y = coreYield(1);
  assert.ok(y.base > 0.7, `基底掉到 ${y.base}，中心该有的光被收走了`);
  assert.ok(y.lobe > 0.7, `等离子瓣掉到 ${y.lobe}，光团的起伏会看不出来`);
});

test("让位是连续的，跟着字的淡入淡出走", () => {
  // 突变会让人看见光核"啪"地暗一下。四个量都必须单调。
  let prev = coreYield(0);
  for (let a = 0.05; a <= 1.0001; a += 0.05) {
    const y = coreYield(a);
    for (const k of ["base", "lobe", "inner", "innerR"]) {
      assert.ok(y[k] <= prev[k] + 1e-9, `a=${a.toFixed(2)} 时 ${k} 反而涨了`);
    }
    prev = y;
  }
});

test("越界输入被钳住，不会把光核调成负数或调过头", () => {
  assert.deepEqual(coreYield(-1), coreYield(0));
  assert.deepEqual(coreYield(5), coreYield(1));
});
