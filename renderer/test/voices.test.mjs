/**
 * 声部面板的行数计算——buildVoiceRows 是纯函数，行为在这里锁死。
 *
 * 真正决定「后几行会不会在浏览器里静默消失」的是 boot.test.mjs /
 * boot-nine.test.mjs 里对渲染出来的 DOM 面板的行数断言（.mr-voice 计数），
 * 不是这份纯函数测试——Task 5 已经在同一个形状上栽过一次：单元测试全绿，
 * 真正的启动路径没人守。这份文件只锁 buildVoiceRows 本身的输入输出契约。
 *
 * 真歌的夹具用的是实测映射（来自 murripple/lanes.py 的 LANE_SPECS，第
 * 19-24 行——不是 tests/fixtures/real-songs-baseline.json，那份 fixture
 * 只有 timeline_sha256 与逐键 key_sha256 摘要，读不出 stem 映射），不是
 * 计划稿里那份把六条 lane 全部写成 stem:"drums" 的假夹具——那份假夹具
 * 下，一个把每行 stem 丢掉、全部硬写成 "drums" 的错误实现照样能通过
 * 「真歌仍是七行」与「三行鼓共用 drums」两条测试。真实映射能让它露馅。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { buildVoiceRows } from "../src/ui/voices.js";

/** 真歌六条 lane 的真实映射：id/stem 逐条抄自 murripple/lanes.py:19-24 的
 * LANE_SPECS。`label` 字段这里换成了面板实际显示的中文名（voices.js 的
 * LABELS 表），只是为了测试输出可读，不是 lanes.py 里 "底鼓"/"军鼓" 那份
 * 原始 label——buildVoiceRows 优先用 LABELS 查表，不读这个 label 字段
 * （它只在 LABELS 查不到时当兜底）。 */
const REAL_SONG_LANES = [
  { id: "kick", label: "撼岳", hue: 28, stem: "drums" },
  { id: "snare", label: "裂帛", hue: 350, stem: "drums" },
  { id: "hat", label: "碎玉", hue: 195, stem: "drums" },
  { id: "bass", label: "渊鸣", hue: 225, stem: "bass" },
  { id: "mid", label: "流岚", hue: 175, stem: "other" },
  { id: "air", label: "缥缈", hue: 270, stem: "other" },
];

test("真歌仍是七行：一行人声 + 六条轨道", () => {
  const rows = buildVoiceRows({
    stems: ["vocals", "drums", "bass", "other"],
    lanes: REAL_SONG_LANES,
  });
  assert.equal(rows.length, 7);
  assert.equal(rows[0].stem, "vocals");
});

test("真歌的分轨映射照单实现——不是把每行都硬写成 drums", () => {
  // 判决性实验：把 buildVoiceRows 写成对每条 lane 都返回 stem:"drums"，
  // 上一条「七行」与下面「三行鼓共用 drums」都会绿；只有这一条能抓住它。
  const rows = buildVoiceRows({
    stems: ["vocals", "drums", "bass", "other"],
    lanes: REAL_SONG_LANES,
  });
  assert.equal(rows.find((r) => r.lane === "bass").stem, "bass", "渊鸣应属于 bass");
  assert.equal(rows.find((r) => r.lane === "mid").stem, "other", "流岚应属于 other");
  assert.equal(rows.find((r) => r.lane === "air").stem, "other", "缥缈应属于 other");
  assert.equal(
    rows.filter((r) => r.stem === "drums").length,
    3,
    "只有撼岳/裂帛/碎玉三行该属于 drums",
  );
});

test("合成曲是九行：一行主奏 + 八条轨道", () => {
  const lanes = ["bass", "pad", "pluck", "arp", "bell", "kick", "snare", "hat"].map(
    (id) => ({ id, label: id, hue: 200, stem: id }),
  );
  const rows = buildVoiceRows({
    stems: ["vocals", ...lanes.map((l) => l.stem)],
    lanes,
  });
  assert.equal(rows.length, 9);
  assert.equal(rows[0].stem, "vocals");
});

test("每一行指向自己的分轨——九行没有两行共用一条", () => {
  const lanes = ["bass", "pad", "pluck", "arp", "bell", "kick", "snare", "hat"].map(
    (id) => ({ id, label: id, hue: 200, stem: id }),
  );
  const rows = buildVoiceRows({
    stems: ["vocals", ...lanes.map((l) => l.stem)],
    lanes,
  });
  const stems = rows.map((r) => r.stem);
  assert.equal(new Set(stems).size, stems.length, "有两行共用同一条分轨");
});

test("真歌的三行鼓确实共用 drums——面板对真歌仍然如实反映连动", () => {
  const rows = buildVoiceRows({
    stems: ["vocals", "drums", "bass", "other"],
    lanes: REAL_SONG_LANES.slice(0, 3),
  });
  assert.equal(rows.filter((r) => r.stem === "drums").length, 3);
});

// ── 归组标记：连动在按下之前就得看得见 ────────────────────────────────
//
// 下面几条锁的是 buildVoiceRows 吐出来的 groupSize/groupPos。它们只保证
// "数据算对了"；"面板上真的画出了那道竖脊" 由 ui.test.mjs 里那条读
// template.html 真样式的测试守——两边缺一不可，只有数据没有样式，界面
// 照样在骗人。

const realRows = () =>
  buildVoiceRows({
    stems: ["vocals", "drums", "bass", "other"],
    lanes: REAL_SONG_LANES,
  });

test("真歌的三行鼓被标成一组，竖脊首中尾齐全", () => {
  const rows = realRows();
  const pos = (lane) => rows.find((r) => r.lane === lane).groupPos;
  assert.equal(pos("kick"), "first");
  assert.equal(pos("snare"), "mid");
  assert.equal(pos("hat"), "last");
  for (const id of ["kick", "snare", "hat"]) {
    assert.equal(rows.find((r) => r.lane === id).groupSize, 3);
  }
});

test("流岚/缥缈同属 other，也是连动的一组——不是只有鼓", () => {
  // README 与任务书都只坦白了三行鼓，实际上 mid 与 air 共用 other
  // （murripple/lanes.py:23-24），点其中一行另一行同样会暗。归组是从
  // lane.stem 推的，所以这一组不用额外写一行代码就一起被认出来。
  const rows = realRows();
  assert.equal(rows.find((r) => r.lane === "mid").groupPos, "first");
  assert.equal(rows.find((r) => r.lane === "air").groupPos, "last");
  assert.equal(rows.find((r) => r.lane === "mid").groupSize, 2);
});

test("独立的行不带归组标记：心籁与渊鸣的 groupPos 是 null", () => {
  const rows = realRows();
  assert.equal(rows[0].groupPos, null, "人声独占 vocals，不该有竖脊");
  assert.equal(rows[0].groupSize, 1);
  assert.equal(rows.find((r) => r.lane === "bass").groupPos, null);
  assert.equal(rows.find((r) => r.lane === "bass").groupSize, 1);
});

test("合成曲九行一个归组标记都没有——面板上不能出现虚假的连动暗示", () => {
  const lanes = ["bass", "pad", "pluck", "arp", "bell", "kick", "snare", "hat"].map(
    (id) => ({ id, label: id, hue: 200, stem: id }),
  );
  const rows = buildVoiceRows({ stems: ["vocals", ...lanes.map((l) => l.stem)], lanes });
  assert.equal(rows.length, 9);
  assert.deepEqual(
    rows.filter((r) => r.groupPos !== null).map((r) => r.lane),
    [],
    "九行逐轨独立，任何一条 groupPos 非 null 都是在骗人",
  );
  assert.deepEqual(new Set(rows.map((r) => r.groupSize)), new Set([1]));
});

test("归组只认 stem，不认 kick/snare/hat 这三个名字", () => {
  // 判决性实验：把实现写成「id 属于 {kick,snare,hat} 就归一组」，前面
  // 几条真歌测试全部照绿。这一条给的正是素材换掉之后的形状——
  // htdemucs_6s 把鼓拆开、另外两条反倒并进同一条 stem。硬编码在这里当场
  // 露馅：它会把 kick/snare/hat 划成一组，把真正连动的 bass/mid 放过。
  const lanes = [
    { id: "kick", label: "撼岳", hue: 28, stem: "drums" },
    { id: "snare", label: "裂帛", hue: 350, stem: "snare" },
    { id: "hat", label: "碎玉", hue: 195, stem: "cymbals" },
    { id: "bass", label: "渊鸣", hue: 225, stem: "lowend" },
    { id: "mid", label: "流岚", hue: 175, stem: "lowend" },
    { id: "air", label: "缥缈", hue: 270, stem: "air" },
  ];
  const rows = buildVoiceRows({
    stems: ["vocals", "drums", "snare", "cymbals", "lowend", "air"],
    lanes,
  });
  const pos = (lane) => rows.find((r) => r.lane === lane).groupPos;
  assert.equal(pos("kick"), null, "kick 独占 drums，不该被划进任何一组");
  assert.equal(pos("snare"), null);
  assert.equal(pos("hat"), null);
  assert.equal(pos("bass"), "first", "真正连动的是 bass 与 mid");
  assert.equal(pos("mid"), "last");
  assert.equal(pos("air"), null);
});

test("同一条 stem 隔着别的行时，竖脊不横跨无关行", () => {
  // 竖脊只看紧邻的上下两行。同组但不相邻的两行各自标成 "lone"，画出来
  // 是两小段，而不是一道从第一行拉到第三行、把中间那条无关轨道也圈进去
  // 的长线——那才是真正的骗人。
  const lanes = [
    { id: "kick", label: "撼岳", hue: 28, stem: "drums" },
    { id: "bass", label: "渊鸣", hue: 225, stem: "bass" },
    { id: "snare", label: "裂帛", hue: 350, stem: "drums" },
  ];
  const rows = buildVoiceRows({ stems: ["vocals", "drums", "bass"], lanes });
  const pos = (lane) => rows.find((r) => r.lane === lane).groupPos;
  assert.equal(pos("kick"), "lone");
  assert.equal(pos("snare"), "lone");
  assert.equal(pos("bass"), null, "夹在中间的 bass 与鼓无关，不能被圈进去");
  assert.equal(
    rows.filter((r) => r.groupPos === "mid" || r.groupPos === "first").length,
    0,
    "不相邻就不该出现能连出长线的 first/mid",
  );
});
