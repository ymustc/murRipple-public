import test from "node:test";
import assert from "node:assert/strict";
import { renderMixdown } from "../src/core/mixdown.js";
import { HEADER_BYTES } from "../src/core/wav.js";

/**
 * `renderMixdown` 是 renderer/src/main.js 里"导出当前混音"用的那条管线。
 * brief 没给这一处的测试，但它正是"九条分轨只解出前四条"缺陷可能藏身
 * 的三处之一（另两处是 createPlayer、main.js 的解码循环，见 audio.test.mjs
 * 与本任务报告）：旧实现按写死的 STEMS 过滤 present，九条 buffers 进去
 * 只会混前四条。
 */

/** 假 AudioBuffer：单样本、单声道，值可控，便于算出期望的混音结果。 */
function fakeBuffer(value, sr = 8000) {
  return {
    sampleRate: sr,
    numberOfChannels: 1,
    length: 1,
    getChannelData: () => Float32Array.from([value]),
  };
}

/**
 * 假 OfflineAudioContext，忠实复刻 renderMixdown 里的接线方式：
 * 每条 stem 各自 createBufferSource() -> createGain() -> destination，
 * 再在 startRendering() 里按增益把各条 source 的样本加总。
 */
function makeFakeOfflineCtor() {
  return class FakeOfflineContext {
    constructor(numberOfChannels, length, sampleRate) {
      this.numberOfChannels = numberOfChannels;
      this.length = length;
      this.sampleRate = sampleRate;
      this.destination = { tag: "destination" };
      this._sources = [];
    }
    createGain() {
      return { gain: { value: 1 }, connect() {} };
    }
    createBufferSource() {
      const self = this;
      const src = {
        buffer: null,
        _gain: null,
        connect(dest) {
          src._gain = dest;
        },
        start() {
          self._sources.push(src);
        },
      };
      return src;
    }
    async startRendering() {
      const out = Array.from(
        { length: this.numberOfChannels },
        () => new Float32Array(this.length),
      );
      for (const src of this._sources) {
        const gainVal = src._gain.gain.value;
        const buf = src.buffer;
        for (let c = 0; c < this.numberOfChannels; c++) {
          const data = buf.getChannelData(Math.min(c, buf.numberOfChannels - 1));
          for (let i = 0; i < Math.min(this.length, data.length); i++) {
            out[c][i] += data[i] * gainVal;
          }
        }
      }
      return {
        numberOfChannels: this.numberOfChannels,
        getChannelData: (c) => out[c],
      };
    }
  };
}

function decodeFirstSample(buffer) {
  const view = new DataView(buffer);
  const raw = view.getInt16(HEADER_BYTES, true);
  return raw / (raw < 0 ? 0x8000 : 0x7fff);
}

const NINE = ["vocals", "bass", "pad", "pluck", "arp", "bell", "kick", "snare", "hat"];

test("renderMixdown 混入 buffers 里全部的 stem，不是写死的四条", async () => {
  const buffers = {};
  NINE.forEach((s, i) => {
    // 每条 0.01 * 序号，量化误差（1/32767）远小于差异，且累加和留在
    // ±1 量程内不会被钳位——钳位会把"少混了几条"这个差异吃掉。
    buffers[s] = fakeBuffer(0.01 * (i + 1));
  });
  const FakeOffline = makeFakeOfflineCtor();

  const { buffer, sampleRate } = await renderMixdown(buffers, () => 1, FakeOffline);

  assert.equal(sampleRate, 8000);
  const expected = 0.01 * NINE.reduce((sum, _, i) => sum + (i + 1), 0); // 0.45
  const decoded = decodeFirstSample(buffer);
  assert.ok(
    Math.abs(decoded - expected) < 1e-3,
    `九条应全部混入，期望约 ${expected}，实得 ${decoded}`,
  );
});

test("renderMixdown 遇到静音的 stem 时不计入那条", async () => {
  const buffers = {};
  NINE.forEach((s, i) => {
    buffers[s] = fakeBuffer(0.01 * (i + 1));
  });
  const FakeOffline = makeFakeOfflineCtor();
  const muted = new Set(["pad", "kick"]);

  const { buffer } = await renderMixdown(
    buffers,
    (s) => (muted.has(s) ? 0 : 1),
    FakeOffline,
  );

  const total = 0.01 * NINE.reduce((sum, _, i) => sum + (i + 1), 0);
  const excluded = 0.01 * (NINE.indexOf("pad") + 1) + 0.01 * (NINE.indexOf("kick") + 1);
  const expected = total - excluded;
  const decoded = decodeFirstSample(buffer);
  assert.ok(
    Math.abs(decoded - expected) < 1e-3,
    `静音的两条不该计入，期望约 ${expected}，实得 ${decoded}`,
  );
});
