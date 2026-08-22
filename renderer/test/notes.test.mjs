import test from "node:test";
import assert from "node:assert/strict";
import {
  LEAD_T,
  visibleNotes,
  pitchOffset,
  hitIndicesIn,
  laneAngle,
} from "../src/core/notes.js";

const notes = [
  { t: 1.0, v: 0.5, pitch: null },
  { t: 2.0, v: 0.8, pitch: 36 },
  { t: 2.5, v: 0.3, pitch: null },
  { t: 10.0, v: 1.0, pitch: null },
];

test("提前量是 1.7 秒", () => {
  assert.equal(LEAD_T, 1.7);
});

test("命中时刻 progress 为 1，刚出现时为 0", () => {
  const atHit = visibleNotes(notes, 2.0).find((x) => x.note.t === 2.0);
  assert.ok(Math.abs(atHit.progress - 1) < 1e-9, `命中时应为 1，实得 ${atHit.progress}`);

  const atBirth = visibleNotes(notes, 2.0 - LEAD_T).find((x) => x.note.t === 2.0);
  assert.ok(Math.abs(atBirth.progress) < 1e-9, `刚出现时应为 0，实得 ${atBirth.progress}`);
});

test("progress 随时间单调递增", () => {
  const at = (t) => visibleNotes(notes, t).find((x) => x.note.t === 2.0)?.progress;
  // 偏移量必须全部小于 LEAD_T：超过提前量音符已经命中消失，at() 返回
  // undefined，比较会以"没有前进"的名义失败——而真正的原因是取样点选错了。
  const seq = [0.4, 0.9, 1.4, 1.69].map((d) => at(2.0 - LEAD_T + d));
  for (let i = 1; i < seq.length; i++) {
    assert.ok(seq[i] > seq[i - 1], `第 ${i} 步没有前进：${seq[i - 1]} → ${seq[i]}`);
  }
});

test("命中之后立即消失，不留在画面上", () => {
  assert.equal(
    visibleNotes(notes, 2.05).find((x) => x.note.t === 2.0),
    undefined,
    "命中后不该再可见——爆开的光屑由粒子层接管",
  );
});

test("提前量之外的音符不可见", () => {
  const ids = visibleNotes(notes, 2.0).map((x) => x.note.t);
  assert.ok(!ids.includes(10.0), "还早得很的音符不该出现");
  assert.ok(ids.includes(2.5), "1.7 秒内的应该出现");
});

test("是 t 的纯函数：倒着算与正着算一致", () => {
  const fwd = [1.0, 1.5, 2.0].map((t) => visibleNotes(notes, t).length);
  const bwd = [2.0, 1.5, 1.0].map((t) => visibleNotes(notes, t).length).reverse();
  assert.deepEqual(fwd, bwd);
});

test("空列表不抛错", () => {
  assert.deepEqual(visibleNotes([], 5), []);
});

test("pitchOffset 把音高映射到 -1…1，低音在下高音在上", () => {
  assert.ok(Math.abs(pitchOffset(24) + 1) < 1e-9, "下界应为 -1");
  assert.ok(Math.abs(pitchOffset(60) - 1) < 1e-9, "上界应为 1");
  assert.ok(Math.abs(pitchOffset(42)) < 1e-9, "中点应为 0");
  assert.ok(pitchOffset(50) > pitchOffset(30), "音高越高偏移越大");
});

test("pitchOffset 越界钳制，且 null 视作中点", () => {
  assert.equal(pitchOffset(0), -1);
  assert.equal(pitchOffset(999), 1);
  assert.equal(pitchOffset(null), 0);
});

test("laneAngle 把 N 条轨道均匀铺满整圈，互不重合", () => {
  const n = 6;
  const angs = Array.from({ length: n }, (_, i) => laneAngle(i, n));
  const norm = (a) => ((a % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
  assert.equal(
    new Set(angs.map((a) => norm(a).toFixed(9))).size,
    n,
    "六条轨道必须落在六个不同方位",
  );
  for (let i = 1; i < n; i++) {
    const d = angs[i] - angs[i - 1];
    assert.ok(
      Math.abs(d - (Math.PI * 2) / n) < 1e-9,
      `第 ${i} 条间隔应为 2π/6，实得 ${d}`,
    );
  }
  assert.ok(
    Math.abs(laneAngle(0, 4) - (-Math.PI / 2 + Math.PI / 4)) < 1e-9,
    "首条轨道自正上方起算",
  );
});

test("laneAngle 让音高真的偏转落点，方向与 pitchOffset 一致", () => {
  const lo = laneAngle(0, 6, 24);
  const mid = laneAngle(0, 6, null);
  const hi = laneAngle(0, 6, 60);
  assert.ok(hi > mid && mid > lo, `音高应单调偏转：${lo} < ${mid} < ${hi}`);
  const swing = hi - lo;
  assert.ok(
    swing > 0.3 && swing < 0.35,
    `全音域摆幅应为 2×PITCH_SWING=0.32，实得 ${swing}`,
  );
  assert.ok(
    Math.abs(hi - mid - pitchOffset(60) * 0.16) < 1e-9,
    "偏转量必须等于 pitchOffset × PITCH_SWING",
  );
});

test("emittedThrough 落后于 t 时，还没炸开的音符继续可见且 progress 封顶", () => {
  // 粒子按固定步长推进，simT 总是 ≤ t。若音符按 t 判消失，
  // simT < note.t ≤ t 那一小段里音符已不见、光屑还没生成，命中闪掉一帧。
  const seen = visibleNotes(notes, 2.02, LEAD_T, 1.995);
  const hit = seen.find((x) => x.note.t === 2.0);
  assert.ok(hit, "光屑尚未发射，音符必须还在画面上");
  assert.equal(hit.progress, 1, "已过判定环，progress 必须封在 1，不能超");

  // 光屑一旦发射（emittedThrough 越过 note.t），音符立刻交棒
  assert.equal(
    visibleNotes(notes, 2.02, LEAD_T, 2.005).find((x) => x.note.t === 2.0),
    undefined,
    "已经炸开了就不该再画音符本体",
  );
});

test("hitIndicesIn 取左开右闭区间，避免同一音符发射两次", () => {
  assert.deepEqual(hitIndicesIn(notes, 0.9, 1.0), [0], "右端点应包含");
  assert.deepEqual(hitIndicesIn(notes, 1.0, 1.5), [], "左端点应排除——上一步已经发射过了");
  assert.deepEqual(hitIndicesIn(notes, 1.5, 2.5), [1, 2]);
  assert.deepEqual(hitIndicesIn(notes, 100, 200), []);
});
