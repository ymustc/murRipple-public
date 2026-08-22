/**
 * 下落音符的几何。
 *
 * 提前量 1.7 秒是 M1 spec 就定下的：分析在构建时离线完成，画面因此可以
 * 任意提前于声音——这正是实时频谱分析做不到的事，也是整个"预分析驱动"
 * 架构的立足点。
 *
 * 音符列表按 t 升序（lanes.py 产出时即有序），所以查找用二分：2217 个
 * 音符 × 60fps 的线性扫描是白费的。
 */

export const LEAD_T = 1.7;

/** 低音音符按音高微偏落点的取值范围（MIDI）。实测首曲为 24.0–60.1。 */
const PITCH_LO = 24;
const PITCH_HI = 60;

/** 音高偏移落点的最大角度（弧度）。 */
const PITCH_SWING = 0.16;

/** 第一个 t 严格大于 x 的下标。 */
function upperBound(notes, x) {
  let lo = 0;
  let hi = notes.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (notes[mid].t <= x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/**
 * t 时刻可见的音符。progress 0 = 刚出现在外圈，1 = 命中判定环。
 *
 * 命中后立即移出——爆开的光屑由粒子层接管，音符本身不该滞留。
 *
 * emittedThrough 是"光屑已经发射到哪一刻"。默认取 t（自成一体，单测
 * 用得上），但绘制时必须传粒子世界的 simT：粒子按固定步长推进，simT
 * 总是 ≤ t，若音符按 t 判消失，simT < note.t ≤ t 的那一小段里音符已
 * 经不见、光屑却还没生成，命中会闪掉一帧。实测最坏相位下半数命中如此。
 */
export function visibleNotes(notes, t, lead = LEAD_T, emittedThrough = t) {
  const out = [];
  // 可见窗口是 (emittedThrough, t+lead]：还没炸开的都还在路上
  let i = upperBound(notes, emittedThrough - 1e-9);
  while (i < notes.length && notes[i].t <= t + lead) {
    out.push({
      note: notes[i],
      index: i,
      // 封顶：simT 落后于 t 时，已过判定环的那几个音符会算出 >1
      progress: Math.min(1, 1 - (notes[i].t - t) / lead),
    });
    i++;
  }
  return out;
}

/** 音高 → −1…1。null 视作中点；越界钳制。 */
export function pitchOffset(pitch, lo = PITCH_LO, hi = PITCH_HI) {
  if (pitch === null || pitch === undefined) return 0;
  const clamped = Math.max(lo, Math.min(hi, pitch));
  return ((clamped - lo) / (hi - lo)) * 2 - 1;
}

/**
 * 一个音符落在环上的方位角。
 *
 * 放在 core 里而不是绘制层：音符层用它决定落点，粒子层用它决定光屑从
 * 哪里爆开，两者必须是同一个角。各写一份的话，某天改了轨道排布就会
 * 变成"音符落在这边、光屑炸在那边"——而且画面上未必一眼看得出来。
 */
export function laneAngle(laneIdx, laneCount, pitch = null) {
  return (
    -Math.PI / 2 +
    ((laneIdx + 0.5) * Math.PI * 2) / laneCount +
    pitchOffset(pitch) * PITCH_SWING
  );
}

/**
 * 落在 (t0, t1] 内的音符下标。
 *
 * 左开右闭是刻意的：粒子世界按固定步长推进，每步查一次；若两端都闭，
 * 恰好落在步长边界上的音符会在相邻两步各发射一次。
 */
export function hitIndicesIn(notes, t0, t1) {
  const out = [];
  let i = upperBound(notes, t0);
  while (i < notes.length && notes[i].t <= t1) {
    out.push(i);
    i++;
  }
  return out;
}
