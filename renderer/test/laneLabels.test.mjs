/**
 * 环外小字（laneLabels 层）的标签查找逻辑。
 *
 * 评审发现的缺口：voices.js 的 buildVoiceRows 对不在 LABELS 表里的
 * lane id 有兜底（`?? l.label`），laneLabels.js 原来没有——`LABELS
 * [lane.id]?.zh` 查不到就 `if (!label) return`，直接跳过不画。改动前
 * 面板与画布铭文由同一份 VOICES 驱动，一条 lane 不可能一边有一边没有；
 * 现在面板由 timeline.lanes 全量驱动、画布只画 LABELS 里有的，两边会
 * 静默分叉。boot-harness-nine.html 的 drums/other/chime 三个 lane id
 * 不在 LABELS 表里，正好踩中这个缺口：9 行面板、只有 5 段环外小字，
 * 而这条差没有任何测试盯着——这份文件补上。
 *
 * 用纯函数测试而不是像 layers.test.mjs 那样抠像素：labelFor 本身不碰
 * canvas/DOM，从 draw() 里拆出来更容易直接钉住"每条 lane 都能算出一个
 * 非空标签"这件事，等价于「面板行数 == 画布小字条数」。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { labelFor } from "../src/layers/laneLabels.js";

test("面板行数 == 画布小字条数：每条 lane 都能算出一个非空标签，不会被静默跳过", () => {
  // 合成曲九条 harness 里三条 lane id（drums/other/chime）不在 LABELS
  // 表里——它们是用来撑大 stems 列表的占位名，不是真实乐器名。这三条必须
  // 落到 lane.label 兜底，不能返回 undefined 让 draw() 里的
  // `if (!label) return` 把它们从画布上悄悄抹掉。
  const lanes = ["drums", "bass", "other", "pad", "pluck", "arp", "bell", "chime"].map(
    (id, i) => ({ id, label: id, hue: i * 41, stem: id }),
  );
  for (const lane of lanes) {
    const label = labelFor(lane);
    assert.ok(label, `lane ${lane.id} 应该有一个可画的标签，实得 ${JSON.stringify(label)}`);
  }
});

test("LABELS 表里有条目时优先用 LABELS，不是永远退回 lane.label", () => {
  const lane = { id: "kick", label: "raw-kick-should-not-show", hue: 0, stem: "drums" };
  assert.equal(labelFor(lane), "撼岳");
});

test("LABELS 表里没有条目时退回 lane.label", () => {
  const lane = { id: "totally-unknown-lane-id", label: "自定义名字", hue: 0, stem: "x" };
  assert.equal(labelFor(lane), "自定义名字");
});
