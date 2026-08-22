import test from "node:test";
import assert from "node:assert/strict";
import {
  splitLine,
  fadeAt,
  lyricAlphaAt,
  LEAD_IN,
  TAIL,
} from "../src/layers/lyrics.js";

test("按全角空格断成两行——自造语料里 22 句句读句都是这个格式", () => {
  assert.deepEqual(splitLine("锈色电台　夜里还醒"), ["锈色电台", "夜里还醒"]);
});

test("半角空格同样处理", () => {
  assert.deepEqual(splitLine("锈色电台 夜里还醒"), ["锈色电台", "夜里还醒"]);
});

test("无分隔符且够短时不断行", () => {
  assert.deepEqual(splitLine("谁先眨眼就输"), ["谁先眨眼就输"]);
});

test("无分隔符但过长时从中点断", () => {
  const long = "一二三四五六七八九十一二三四五六";
  const out = splitLine(long);
  assert.equal(out.length, 2);
  assert.equal(out.join(""), long, "断行不得丢字");
  assert.ok(Math.abs(out[0].length - out[1].length) <= 1, "应尽量均分");
});

test("多个分隔符时只按第一个断，避免碎成三行以上", () => {
  const out = splitLine("锈色电台　还在　替谁守夜");
  assert.equal(out.length, 2);
  assert.equal(out[0], "锈色电台");
  assert.equal(out[1], "还在替谁守夜");
});

test("空串返回空数组", () => {
  assert.deepEqual(splitLine(""), []);
  assert.deepEqual(splitLine("   "), []);
});

test("是纯函数，同样输入同样输出", () => {
  assert.deepEqual(
    splitLine("报时的人　迟到　也不道歉"),
    splitLine("报时的人　迟到　也不道歉"),
  );
});

const line = { t0: 10, t1: 13, text: "锈色电台　夜里还醒", words: null };

test("唱到的那一刻歌词已经完全显现，不是才开始淡入", () => {
  // 原实现从 t0 开始淡入，t0 时刻 alpha 恰好是 0，要过 0.45 秒才到 1——
  // 观感上就是"歌词晚于声音"。这是于淼实际反馈的问题。
  assert.equal(fadeAt(line, line.t0), 1, "t0 时必须已经全亮");
});

test("淡入发生在 t0 之前", () => {
  const before = fadeAt(line, line.t0 - LEAD_IN / 2);
  assert.ok(before > 0 && before < 1, `t0 前应在淡入中，实得 ${before}`);
  assert.equal(fadeAt(line, line.t0 - LEAD_IN), 0, "淡入起点应为全透明");
});

test("整句演唱期间保持全亮", () => {
  for (const t of [10, 11, 12, 12.9]) {
    assert.equal(fadeAt(line, t), 1, `t=${t} 应全亮`);
  }
});

test("唱完之后才淡出", () => {
  assert.equal(fadeAt(line, line.t1), 1, "t1 时仍应全亮，之后才开始退");
  const during = fadeAt(line, line.t1 + TAIL / 2);
  assert.ok(during > 0 && during < 1, `应在淡出中，实得 ${during}`);
  assert.equal(fadeAt(line, line.t1 + TAIL), 0);
});

test("窗口之外为 0", () => {
  assert.equal(fadeAt(line, 0), 0);
  assert.equal(fadeAt(line, 99), 0);
});

// —— lyricAlphaAt：光核靠它决定让不让位 ——

const lines = [
  { t0: 10, t1: 13, text: "锈色电台　夜里还醒", words: null },
  { t0: 20, t1: 22, text: "谁先眨眼就输", words: null },
];

test("有字的时候在场程度就是那一句的不透明度", () => {
  // 两者必须是同一个数：光核让位的深浅要跟着字的淡入淡出走，让早了会
  // 看见光核先暗一下，让晚了字最亮的那一刻正好被冲白。
  for (const t of [9.7, 10, 11.5, 13.2, 20.5]) {
    assert.equal(lyricAlphaAt(lines, t), fadeAt(lines[t < 15 ? 0 : 1], t));
  }
});

test("间奏里没有字，在场程度是 0——光核这时该回到全亮", () => {
  assert.equal(lyricAlphaAt(lines, 0), 0);
  assert.equal(lyricAlphaAt(lines, 16), 0, "两句之间的空档");
  assert.equal(lyricAlphaAt(lines, 99), 0);
  assert.equal(lyricAlphaAt([], 5), 0, "整首没有歌词也不能炸");
});

test("取值范围恒在 0…1，且淡入段是单调涨的", () => {
  let prev = -1;
  for (let t = 9.4; t <= 10.05; t += 0.05) {
    const a = lyricAlphaAt(lines, t);
    assert.ok(a >= 0 && a <= 1, `t=${t} 时 ${a} 越界`);
    assert.ok(a >= prev - 1e-9, `t=${t} 时回落了`);
    prev = a;
  }
  assert.equal(prev, 1);
});
