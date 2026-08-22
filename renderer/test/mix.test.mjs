import test from "node:test";
import assert from "node:assert/strict";
import { mixToMono } from "../src/core/mix.js";

/** 假 AudioBuffer：只实现 mixToMono 用到的接口。 */
function fakeBuffer(channels, sr = 48000) {
  return {
    sampleRate: sr,
    numberOfChannels: channels.length,
    length: channels[0].length,
    getChannelData: (i) => channels[i],
  };
}

test("单轨单声道原样返回", () => {
  const out = mixToMono({ vocals: fakeBuffer([Float32Array.from([0.5, -0.5])]) });
  assert.deepEqual([...out.channel], [0.5, -0.5]);
  assert.equal(out.sr, 48000);
});

test("立体声取左右平均", () => {
  const out = mixToMono({
    vocals: fakeBuffer([Float32Array.from([1, 0]), Float32Array.from([0, 1])]),
  });
  assert.deepEqual([...out.channel], [0.5, 0.5]);
});

test("多轨相加", () => {
  const out = mixToMono({
    vocals: fakeBuffer([Float32Array.from([0.2, 0.2])]),
    drums: fakeBuffer([Float32Array.from([0.3, -0.1])]),
  });
  assert.ok(Math.abs(out.channel[0] - 0.5) < 1e-6);
  assert.ok(Math.abs(out.channel[1] - 0.1) < 1e-6);
});

test("长度不一时取最长，短的按静音补齐", () => {
  const out = mixToMono({
    vocals: fakeBuffer([Float32Array.from([1, 1, 1])]),
    drums: fakeBuffer([Float32Array.from([1])]),
  });
  assert.equal(out.channel.length, 3);
  assert.ok(Math.abs(out.channel[0] - 2) < 1e-6);
  assert.ok(Math.abs(out.channel[2] - 1) < 1e-6, "短轨之后不应影响长轨");
});

test("空输入返回 null 而不是空数组——调用方据此跳过波形层", () => {
  assert.equal(mixToMono({}), null);
  assert.equal(mixToMono(null), null);
});

test("九条 buffer 全部处理，不是只处理写死的四条——用求和值锁定，不是包含关系", () => {
  // mixToMono 走 Object.values(buffers)，本来就与 stem 名无关、不依赖
  // audio.js 的 STEMS——这条测试锁定这个保证，不让它在 Task 5 改动附近
  // 被误改回写死的四条。用具体求和值断言而不是"结果非空"这种存在性
  // 断言：只处理四条时求和值也非空，会把缺陷放过去。
  const nine = ["vocals", "bass", "pad", "pluck", "arp", "bell", "kick", "snare", "hat"];
  const buffers = {};
  nine.forEach((s, i) => {
    buffers[s] = fakeBuffer([Float32Array.from([i + 1])]);
  });
  const out = mixToMono(buffers);
  const expected = nine.reduce((sum, _, i) => sum + (i + 1), 0); // 45
  assert.equal(out.channel[0], expected, `九条应全部相加，实得 ${out.channel[0]}`);
});
