import test from "node:test";
import assert from "node:assert/strict";
import {
  createMuteState,
  createPlayer,
  lanesForStem,
  dataUriToArrayBuffer,
  resumeFrom,
} from "../src/core/audio.js";

const lanes = [
  { id: "kick", stem: "drums" },
  { id: "snare", stem: "drums" },
  { id: "hat", stem: "drums" },
  { id: "bass", stem: "bass" },
  { id: "mid", stem: "other" },
  { id: "air", stem: "other" },
];

// 四首真歌的分轨列表。曾经是 audio.js 里写死的 STEMS 常量，Task 5 把它
// 删掉、改成由 timeline.stems 声明——这里的测试相应地自己带上这份列表，
// 不再从 audio.js 导入。
const FOUR = ["vocals", "drums", "bass", "other"];

test("一个 stem 可对应多条视觉轨道——6 画 4 静音的不对称", () => {
  assert.deepEqual(lanesForStem(lanes, "drums"), ["kick", "snare", "hat"]);
  assert.deepEqual(lanesForStem(lanes, "other"), ["mid", "air"]);
  assert.deepEqual(lanesForStem(lanes, "bass"), ["bass"]);
  assert.deepEqual(lanesForStem(lanes, "vocals"), [], "人声不占轨道，它驱动判定环");
});

test("静音状态默认全开", () => {
  const m = createMuteState(FOUR);
  for (const s of FOUR) {
    assert.equal(m.isMuted(s), false);
    assert.equal(m.gainFor(s), 1);
  }
});

test("toggle 切换并影响增益，且只影响被切的那一轨", () => {
  const m = createMuteState(FOUR);
  m.toggle("drums");
  assert.equal(m.isMuted("drums"), true);
  assert.equal(m.gainFor("drums"), 0);
  assert.equal(m.gainFor("bass"), 1, "只应影响被切的那一轨");
  assert.equal(m.gainFor("vocals"), 1);
  m.toggle("drums");
  assert.equal(m.gainFor("drums"), 1);
});

test("toggle 未知 stem 抛错而不是静默无效", () => {
  assert.throws(() => createMuteState(FOUR).toggle("guitar"), /guitar/);
});

test("dataUriToArrayBuffer 还原原始字节", () => {
  const bytes = Uint8Array.from([0, 1, 250, 255]);
  const b64 = Buffer.from(bytes).toString("base64");
  const out = new Uint8Array(dataUriToArrayBuffer(`data:audio/mp4;base64,${b64}`));
  assert.deepEqual([...out], [...bytes]);
});

test("dataUriToArrayBuffer 拒绝非 data URI", () => {
  assert.throws(() => dataUriToArrayBuffer("audio/vocals.m4a"), /data:/);
  assert.throws(() => dataUriToArrayBuffer("data:audio/mp4;base64"), /data:/);
});

// --- Task 5：分轨列表从 timeline.stems 来，不再写死四条 ---
// 下面四条是 task-5-brief.md Step 1 给的测试。brief 原文里这段追加了
// `import { createMuteState, lanesForStem } from "../src/core/audio.js";`，
// 但两者都已经在本文件顶部导入过——重复 import 同一个绑定会是
// SyntaxError，且 lanesForStem 在这四条测试里根本没用到，因此这里不重复
// 导入，直接复用文件顶部已有的绑定。

test("静音状态认得九条分轨", () => {
  const nine = ["vocals", "bass", "pad", "pluck", "arp", "bell", "kick", "snare", "hat"];
  const mute = createMuteState(nine);
  mute.toggle("arp");
  assert.equal(mute.isMuted("arp"), true);
  assert.equal(mute.isMuted("bell"), false);
});

test("未知分轨名仍然当场报错，且点名是哪个", () => {
  const mute = createMuteState(["vocals", "bass"]);
  assert.throws(() => mute.toggle("ghost"), /ghost/);
});

test("静音一条不影响其余任何一条", () => {
  const nine = ["vocals", "bass", "pad", "pluck", "arp", "bell", "kick", "snare", "hat"];
  const mute = createMuteState(nine);
  mute.toggle("kick");
  for (const s of nine.filter((x) => x !== "kick")) {
    assert.equal(mute.isMuted(s), false, `${s} 被连累了`);
  }
});

test("四条分轨的真歌行为不变", () => {
  const mute = createMuteState(["vocals", "drums", "bass", "other"]);
  mute.toggle("drums");
  assert.equal(mute.isMuted("drums"), true);
  assert.throws(() => mute.toggle("arp"), /arp/);
});

// --- createPlayer：按 buffers 的 key 集合建增益节点，brief 没给测试，
// 但正是"九条分轨只解出前四条"这个缺陷可能藏身的三处之一，必须补。
//
// 假 AudioContext 沿用 ui.test.mjs（"音量与静音是两条独立的增益"那条）
// 的做法：createGain 按调用顺序打标签、记连线（wires）与写入的增益值
// （log），不新造一套 stub。createPlayer 是纯函数、不碰 DOM，可以直接在
// node --test 下跑，不必上 playwright。

/** 假 AudioContext。createGain 按调用顺序打标签：第一个是 master，其余
 * 按调用顺序编号 g1、g2……与 ui.test.mjs 的假 ctx 同一套记账方式。 */
function fakeCtx() {
  const log = [];
  const wires = [];
  const sources = [];
  let n = 0;
  const dest = { tag: "destination" };
  return {
    currentTime: 0,
    destination: dest,
    createGain() {
      const tag = n++ === 0 ? "master" : `g${n - 1}`;
      const node = {
        tag,
        gain: { setTargetAtTime: (v) => log.push(`${tag}=${v}`) },
        connect: (to) => wires.push(`${tag}->${to.tag}`),
      };
      return node;
    },
    createBufferSource() {
      const src = { connect() {}, start() {}, stop() {} };
      sources.push(src);
      return src;
    },
    log,
    wires,
    sources,
  };
}

const NINE = ["vocals", "bass", "pad", "pluck", "arp", "bell", "kick", "snare", "hat"];

test("createPlayer 按 buffers 的 key 集合建增益节点——九条全部处理，不是至少四条", () => {
  const buffers = Object.fromEntries(NINE.map((s) => [s, {}]));
  const ctx = fakeCtx();
  const player = createPlayer(ctx, buffers);

  // 拓扑：每条 stem 的增益节点都应汇入 master。用计数相等而不是"至少
  // 四条"——写死四条的旧实现在九条 buffers 下也会连出四条线，"存在性"
  // 断言（wires.length >= 4）会被这种半对半错的实现骗过。
  const stemWires = ctx.wires.filter((w) => w.endsWith("->master"));
  assert.equal(
    stemWires.length,
    NINE.length,
    `九条分轨都应各建一个增益节点，实得 ${stemWires.length} 条：${JSON.stringify(ctx.wires)}`,
  );

  // applyMute 同理：写入的增益条数必须等于 buffers 里的 stem 数，而不是
  // 卡死在 4。这里只比条数，不比"具体覆盖了哪些 stem"——假 ctx 的
  // createGain 按调用顺序打标签（g1、g2……），不认识真实 stem 名，没法
  // 做真正的集合相等；条数已经够用：applyMute 循环是在 gains 上跑
  // （`for (const stem of Object.keys(gains))`），gains 又是在上面那条
  // "拓扑"断言里、按 Object.keys(buffers) 顺序建出来的，条数对上就意味着
  // gains 里的九个 key 一个没漏。
  const mute = createMuteState(NINE);
  player.applyMute(mute);
  const gainWrites = ctx.log.filter((x) => !x.startsWith("master="));
  assert.equal(
    gainWrites.length,
    NINE.length,
    `applyMute 应为九条分轨各写一次增益，实得 ${JSON.stringify(gainWrites)}`,
  );
});

test("createPlayer.start 为 buffers 里每一条 stem 都起一个 source", () => {
  const buffers = Object.fromEntries(NINE.map((s) => [s, { fake: true }]));
  const ctx = fakeCtx();
  const player = createPlayer(ctx, buffers);
  player.start(0);
  assert.equal(
    ctx.sources.length,
    NINE.length,
    `九条分轨都应起播放 source，实得 ${ctx.sources.length} 条`,
  );
});

test("currentTime 越过曲长照涨——自然播到尾与跳到接近结尾再播过去，是同一个根因", () => {
  // 走带条计时器越界那个 bug 的根因就在这里：缓冲播完之后没有人把
  // playing 落下来，`ctx.currentTime - startedAt + offset` 于是一路涨。
  //
  // 任务书里列为"未测"的那一点在这条测掉了：**两种路径完全同源**。
  // offset 只决定起点，越不越界跟"怎么走到结尾的"无关——下面两个播放器
  // 一个从 0 自然播到尾、一个先跳到 265 再播过去，同一个墙钟时刻读出的
  // currentTime 一模一样，都越过 270。
  //
  // 这一条是在**记录职责边界**，不是在说"越界是对的"。
  //
  // 【本段于"播完之后"那一棒改写；断言一个字没动】原文写的是"钳位是显示
  // 层的事，做在 hud.update 里；谁要把钳位挪进播放器，得先想清楚 pause()
  // 拿 currentTime() 当 offset 的语义"。现在钳位确实挪进播放器了——但
  // **只在告诉它曲长的时候**：createPlayer(ctx, buffers, duration) 会把
  // currentTime() 钳在 duration 上。pause() 那个语义问题是这么解决的：放完
  // 之后 offset 落在曲末，而按播放键走的是 resumeFrom()，它在 ended 时返回
  // 0，从头再放一遍。
  //
  // 下面这两个播放器是**两参数**调用，曲长缺省为 Infinity，即"永远不结束、
  // 不钳位"，与改动之前逐字节同义——所以这条测试的断言原封不动仍然成立，
  // 它现在守的正是那个缺省行为。
  const DURATION = 270;
  const buffers = { vocals: { fake: true } };

  const ctxA = fakeCtx();
  const a = createPlayer(ctxA, buffers);
  a.start(0); // 自然从头播
  ctxA.currentTime = 283; // 墙钟走了 283 秒

  const ctxB = fakeCtx();
  const b = createPlayer(ctxB, buffers);
  b.seek(265);
  b.start(265); // 跳到接近结尾再播过去
  ctxB.currentTime = 18; // 起播之后墙钟走了 18 秒 → 265 + 18 = 283

  assert.equal(a.currentTime(), 283);
  assert.equal(b.currentTime(), 283);
  assert.equal(
    a.currentTime(),
    b.currentTime(),
    "两条路径读数必须一致，否则'只有 seek 过才越界'的猜测才成立",
  );
  assert.ok(
    a.currentTime() > DURATION,
    `播放器不负责钳位，越过曲长 ${DURATION} 是它的既定行为`,
  );
});

// ── 播完之后：三个状态必须分清 ──────────────────────────────────────
//
// 上一棒只钳了显示（hud.update），播放器本身仍然"越过曲长照涨"，而且
// playing 永远是 true——于是播放键在一首放完的歌上仍然显示 ❚❚（"正在放"），
// 实际一点声音都没有。这一组锁的是 running / ended / playing 三者的分工。

/** 造一个知道自己曲长的播放器，并把假时钟推到 at 秒。 */
function playerAt(duration, at, { from = 0 } = {}) {
  const ctx = fakeCtx();
  const p = createPlayer(ctx, { vocals: { fake: true } }, duration);
  p.start(from);
  ctx.currentTime = at - from;
  return { p, ctx };
}

test("播完之后 playing 变 false，而 running 仍是 true", () => {
  const { p } = playerAt(270, 283);
  assert.equal(p.ended, true, "283 > 270，该算放完了");
  assert.equal(p.playing, false, "放完之后不该再说'正在放'——播放键看的就是它");
  assert.equal(p.running, true, "用户没按暂停，播放意图还在（走带条续播看的是它）");
});

test("没播完的时候 playing 与 running 一致，ended 是 false", () => {
  const { p } = playerAt(270, 100);
  assert.equal(p.ended, false);
  assert.equal(p.playing, true);
  assert.equal(p.running, true);
});

test("知道曲长的播放器，currentTime 钳在曲长上", () => {
  const { p } = playerAt(270, 283);
  assert.equal(p.currentTime(), 270, "越过结尾之后不该再往上报");
});

test("不传曲长时永远不结束——既有的两参数调用行为一个字都不变", () => {
  // 这一条是既有调用点的护栏：audio.test.mjs 上面那几条、以及任何
  // createPlayer(ctx, buffers) 的两参数用法，都必须与改动之前逐字节同义。
  const ctx = fakeCtx();
  const p = createPlayer(ctx, { vocals: { fake: true } });
  p.start(0);
  ctx.currentTime = 100000;
  assert.equal(p.ended, false, "没给曲长就没有'结尾'可言");
  assert.equal(p.playing, true);
  assert.equal(p.currentTime(), 100000, "不钳位");
});

test("resumeFrom：播完了从 0 起播，没播完从当前位置续播", () => {
  // 判决性实验：把 resumeFrom 写成永远返回 player.currentTime()（也就是
  // 改动之前的写法），第二条断言照绿，只有第一条抓得住它——而那一条正是
  // "按了播放却一点声音都没有"的那个 bug。
  const ended = playerAt(270, 283).p;
  assert.equal(resumeFrom(ended), 0, "放完之后按播放，必须从头，不能从结尾");

  const mid = playerAt(270, 100).p;
  assert.equal(resumeFrom(mid), 100, "没放完的时候还是续播，不能被打回开头");
});

test("放完之后回跳，running 还在，所以走带条松手会续播", () => {
  // 上一棒在真产物上验过这条路径：4:30 放完 → 拖回 25% → 1:08 → 1:11 继续走。
  // main.js 的 onScrub 记的是 player.running；若改成记 player.playing，
  // 放完之后拖回中段就会停住不放，把已经验过的行为改坏。
  const { p, ctx } = playerAt(270, 283);
  assert.equal(p.running, true);
  p.seek(60);
  ctx.currentTime += 5;
  assert.equal(p.playing, true, "回跳到曲中应恢复'真的在放'");
  assert.equal(p.ended, false);
});
