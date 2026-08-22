import test from "node:test";
import assert from "node:assert/strict";
import {
  STEP,
  MODE_REALTIME,
  MODE_OFFLINE,
  createClock,
  mulberry32,
} from "../src/core/clock.js";

/** 记录被推进了多少步的假世界。 */
function fakeWorld() {
  return {
    steps: 0,
    cleared: 0,
    step(dt) {
      assert.equal(dt, STEP, "世界只应收到固定步长");
      this.steps++;
    },
    clear() {
      this.cleared++;
      this.steps = 0;
    },
  };
}

test("步长是 1/120", () => {
  assert.equal(STEP, 1 / 120);
});

test("离线模式强制 quality=1，传什么都覆盖不掉", () => {
  const c = createClock({ mode: MODE_OFFLINE, quality: 0.25 });
  assert.equal(c.quality, 1, "离线模式的 quality 必须恒为 1，否则逐帧导出会掉质量");
});

test("实时模式允许降级", () => {
  assert.equal(createClock({ mode: MODE_REALTIME, quality: 0.5 }).quality, 0.5);
});

test("advanceTo 按固定步长推进，步数只由目标时间决定", () => {
  const c = createClock({ mode: MODE_OFFLINE });
  const w = fakeWorld();
  c.advanceTo(1.0, w);
  assert.equal(w.steps, 120, `1 秒应推进 120 步，实得 ${w.steps}`);
});

test("分多次推进与一次推进到底，结果相同", () => {
  const a = createClock({ mode: MODE_OFFLINE });
  const wa = fakeWorld();
  for (const t of [0.1, 0.37, 0.5, 0.913, 1.0]) a.advanceTo(t, wa);

  const b = createClock({ mode: MODE_OFFLINE });
  const wb = fakeWorld();
  b.advanceTo(1.0, wb);

  assert.equal(wa.steps, wb.steps, "推进节奏不应影响总步数——这正是确定性的核心");
});

test("advanceTo 不会倒退", () => {
  const c = createClock({ mode: MODE_OFFLINE });
  const w = fakeWorld();
  c.advanceTo(1.0, w);
  const before = w.steps;
  c.advanceTo(0.5, w);
  assert.equal(w.steps, before, "目标时间早于当前时不应推进");
});

test("advanceOrRewind 倒退时重放，前进时不重放", () => {
  // 这是 renderFrame 该用的入口。advanceTo 只会前进，先画 t=3 再画 t=1，
  // t=1 那帧拿到的是 t=3 的世界——M2-1 到 M2-2 期间 world 是空壳，这个
  // 缺陷一直看不出来，粒子接进来的第一次运行确定性测试就红了。
  const w = fakeWorld();
  const c = createClock({ mode: MODE_REALTIME });

  c.advanceOrRewind(3, w);
  assert.equal(w.cleared, 0, "从 0 前进不该重放");
  const at3 = w.steps;

  c.advanceOrRewind(1, w);
  assert.equal(w.cleared, 1, "倒退必须重放");
  assert.equal(w.steps, 120, "重放后应是从 0 走到 1 秒的步数");

  c.advanceOrRewind(3, w);
  assert.equal(w.cleared, 1, "再前进不该又重放");
  assert.equal(w.steps, at3, "回到 t=3 应与当初同一步数");
});

test("advanceOrRewind 对一步以内的倒退不重放", () => {
  // 音频 currentTime 会有微小抖动。小于一步的倒退 advanceTo 本来就什么
  // 都不做，却要付整段重放的代价——3 分钟处每帧重放 21600 步。
  const w = fakeWorld();
  const c = createClock({ mode: MODE_REALTIME });
  c.advanceOrRewind(10, w);
  c.advanceOrRewind(10 - STEP / 2, w);
  assert.equal(w.cleared, 0, "抖动幅度小于一个步长，不该触发重放");
});

test("超过一个步长的倒退必须重放（容差是一步，不是随便多少步）", () => {
  // 上一条只给了容差的下界。把容差放大到 STEP*100 它照样绿——那时倒退
  // 将近一秒都不重放，画面与音频脱节。
  const w = fakeWorld();
  const c = createClock({ mode: MODE_REALTIME });
  c.advanceOrRewind(10, w);
  c.advanceOrRewind(10 - STEP * 3, w);
  assert.equal(w.cleared, 1, "倒退三个步长已超出一步容差，必须重放");
  assert.equal(
    w.steps,
    Math.floor((10 - STEP * 3) / STEP),
    "重放后应是从 0 走到目标时刻的步数",
  );
});

test("reset 清空世界并从 0 快进，保证与离线渲染同一状态", () => {
  const c = createClock({ mode: MODE_REALTIME });
  const w = fakeWorld();
  c.advanceTo(3.0, w);
  c.reset(1.0, w);
  assert.equal(w.cleared, 1);
  assert.equal(w.steps, 120, `reset 到 1 秒应重新推进 120 步，实得 ${w.steps}`);
  assert.ok(Math.abs(c.simT - 1.0) < STEP);
});

test("长时间推进不累积浮点误差", () => {
  // simT += STEP 会累积误差：1/120 在二进制里不精确，3 分钟下来少走
  // 整整一步（21599 而非 21600）。改用整数步数计数后应当精确。
  const c = createClock({ mode: MODE_OFFLINE });
  const w = fakeWorld();
  c.advanceTo(180, w);
  assert.equal(w.steps, 21600, `180 秒应精确推进 21600 步，实得 ${w.steps}`);
  assert.equal(c.simT, 180, `simT 应精确等于 180，实得 ${c.simT}`);
});

test("mulberry32 同种子同序列", () => {
  const a = mulberry32(42);
  const b = mulberry32(42);
  for (let i = 0; i < 10; i++) assert.equal(a(), b());
});

test("mulberry32 不同种子不同序列", () => {
  assert.notEqual(mulberry32(1)(), mulberry32(2)());
});

test("mulberry32 值域在 [0,1)", () => {
  const r = mulberry32(7);
  for (let i = 0; i < 200; i++) {
    const v = r();
    assert.ok(v >= 0 && v < 1, `越界值 ${v}`);
  }
});
