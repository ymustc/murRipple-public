import test from "node:test";
import assert from "node:assert/strict";
import {
  ENVELOPE_RATE,
  decodeU8,
  smooth,
  sampleAt,
  loadTimeline,
  sectionIndexAt,
  lyricIndexAt,
} from "../src/core/timeline.js";

const b64 = (bytes) => Buffer.from(Uint8Array.from(bytes)).toString("base64");

test("解码与 Python 端的 encode_u8 配对", () => {
  assert.deepEqual([...decodeU8(b64([0, 1, 127, 254, 255]))], [0, 1, 127, 254, 255]);
});

test("采样率是 60Hz", () => {
  assert.equal(ENVELOPE_RATE, 60);
});

test("sampleAt 按 60Hz 取帧，越界钳制到首尾", () => {
  const arr = Uint8Array.from([10, 20, 30]);
  assert.equal(sampleAt(arr, 0), 10);
  assert.equal(sampleAt(arr, 1 / 60), 20);
  assert.equal(sampleAt(arr, 999), 30, "超出时长应钳到最后一帧");
  assert.equal(sampleAt(arr, -5), 10, "负时间应钳到第一帧");
  assert.equal(sampleAt(new Uint8Array(0), 1), 0, "空数组返回 0");
});

test("smooth 是无状态的纯函数：同样输入永远同样输出", () => {
  const arr = Uint8Array.from([0, 255, 0, 255, 0, 255]);
  assert.deepEqual([...smooth(arr, 250)], [...smooth(arr, 250)]);
});

test("smooth 确实起到滞后作用：阶跃响应不会立刻到顶", () => {
  const step = Uint8Array.from(new Array(120).fill(0).concat(new Array(120).fill(255)));
  const out = smooth(step, 250);
  const jumpIdx = 120;
  assert.ok(out[jumpIdx] < 60, `阶跃处不应立刻跟上，实得 ${out[jumpIdx]}`);
  assert.ok(out[out.length - 1] > 200, `足够久之后应接近目标，实得 ${out[out.length - 1]}`);
  for (let i = jumpIdx + 1; i < out.length; i++) {
    assert.ok(out[i] >= out[i - 1] - 1e-6, `第 ${i} 帧不应回落`);
  }
});

test("tau 越大滞后越明显", () => {
  const step = Uint8Array.from(new Array(60).fill(0).concat(new Array(60).fill(255)));
  const fast = smooth(step, 50);
  const slow = smooth(step, 500);
  assert.ok(fast[70] > slow[70], `tau=50 应比 tau=500 跟得快：${fast[70]} vs ${slow[70]}`);
});

// 九条、且顺序与曾经写死的 STEMS 常量（["vocals","drums","bass","other"]）
// 不同——用这份列表才能把"透传 doc.stems"与"第五份写死的四条列表"两种
// 实现分开：若还用旧常量原样那四条，改成写死也测不出来。
const FAKE_STEMS = ["bass", "vocals", "pad", "pluck", "arp", "bell", "kick", "snare", "hat"];

function fakeDoc() {
  return {
    meta: { title: "demo", duration: 10, bpm: 120, codec: "aac-64k", schemaVersion: 1 },
    stems: FAKE_STEMS,
    sections: [
      { t: 0, name: "", energy: 0.2 },
      { t: 5, name: "", energy: 0.8 },
    ],
    beats: [0, 0.5, 1],
    downbeats: [0, 2],
    ring: { envelope: b64([0, 128, 255]), presence: b64([0, 255, 255]) },
    lanes: [
      {
        id: "kick", label: "底鼓", hue: 28, stem: "drums", gain: 1,
        notes: [{ t: 0.5, v: 0.8, pitch: null }],
        envelope: b64([10, 20, 30]),
      },
    ],
    lyrics: [
      { t0: 1, t1: 2, text: "第一句", words: null },
      { t0: 3, t1: 4, text: "第二句", words: null },
    ],
  };
}

test("loadTimeline 解出可用结构，并预计算平滑数组", () => {
  const tl = loadTimeline(fakeDoc());
  assert.equal(tl.meta.duration, 10);
  // Task 5：分轨列表从 doc.stems 透传——main.js 的解码循环与静音过滤
  // 都靠这个字段遍历分轨，真歌四条、合成曲九条。FAKE_STEMS 刻意跟旧
  // STEMS 常量不同（九条、顺序也不同），这样"透传"与"写死四条"两种
  // 实现在这条断言下才分得出来。
  assert.deepEqual(tl.stems, FAKE_STEMS);
  assert.ok(tl.ring.env instanceof Uint8Array);
  assert.ok(tl.ring.envSmooth instanceof Float32Array);
  assert.equal(tl.ring.env.length, tl.ring.envSmooth.length);
  assert.equal(tl.lanes.length, 1);
  assert.ok(tl.lanes[0].envSmooth instanceof Float32Array);
  assert.equal(tl.lanes[0].hue, 28);
});

test("sectionIndexAt 找当前段落", () => {
  const s = fakeDoc().sections;
  assert.equal(sectionIndexAt(s, 0), 0);
  assert.equal(sectionIndexAt(s, 4.9), 0);
  assert.equal(sectionIndexAt(s, 5), 1);
  assert.equal(sectionIndexAt(s, 99), 1);
});

test("lyricIndexAt 只在句子时间窗内返回下标", () => {
  const l = fakeDoc().lyrics;
  assert.equal(lyricIndexAt(l, 0.5), -1, "第一句之前应为 -1");
  assert.equal(lyricIndexAt(l, 1.5), 0);
  assert.equal(lyricIndexAt(l, 2.5), -1, "两句之间的空隙应为 -1");
  assert.equal(lyricIndexAt(l, 3.5), 1);
  assert.equal(lyricIndexAt(l, 9), -1, "末句之后应为 -1");
});
