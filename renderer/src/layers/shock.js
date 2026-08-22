/**
 * 命中冲击弧：击中判定环的瞬间，沿该轨方位扩出一道弧，0.55 秒淡尽。
 *
 * 这是"打中了"最直接的反馈。此前只有光屑，缺一个明确的击中感——光屑是
 * 四散的，冲击弧是有方向的，两者一起才像"撞上去"。
 *
 * **写成 t 的纯函数。** 参考实现是 `shocks.push` 逐帧累积再 filter 的；
 * 那在逐帧导出下不可复现——跳到第 200 秒直接渲染，数组是空的，冲击弧整个
 * 消失。这里按音符反查，怎么跳都对。
 */

import { hitIndicesIn, laneAngle } from "../core/notes.js";
import { OUTER_RATIO } from "../core/geometry.js";

export const SHOCK_LIFE = 0.55;

/** 扩张距离的基准与力度系数（相对 R 的倍数）。 */
const REACH = 0.2;
const REACH_BY_V = 0.23;
/** 半跨度，弧度。 */
const SPAN = 0.34;
const ALPHA0 = 0.55;

/**
 * t 时刻仍在场的冲击弧。
 *
 * `reach` 取 q² 而不是线性：冲击应当"猛地弹出、后段变缓"。线性看着像匀速
 * 涟漪，会与小节涟漪撞车，两者就分不出来了。
 */
export function activeShocks(notes, t, life = SHOCK_LIFE) {
  const out = [];
  for (const i of hitIndicesIn(notes, t - life, t)) {
    const age = t - notes[i].t;
    const q = age / life;
    const v = notes[i].v;
    out.push({
      noteIdx: i,
      age,
      q,
      v,
      reach: q * q * (REACH + v * REACH_BY_V),
      span: SPAN * (1 - q * 0.5),
      alpha: ALPHA0 * (1 - q),
    });
  }
  return out;
}

export const NAME = "shock";

export function draw(g, state) {
  const { timeline, palette, geom, t } = state;
  if (geom.W === 0) return;

  const n = timeline.lanes.length;
  const base = geom.R * OUTER_RATIO;

  g.save();
  g.globalCompositeOperation = "lighter";

  timeline.lanes.forEach((lane, laneIdx) => {
    const hue = (lane.hue + palette.hueShift) % 360;
    for (const s of activeShocks(lane.notes, t)) {
      const ang = laneAngle(laneIdx, n, lane.notes[s.noteIdx].pitch);
      g.strokeStyle = `hsla(${hue} 85% 72% / ${s.alpha})`;
      g.lineWidth = (2.6 * (1 - s.q) + 0.6) * geom.dpr;
      g.beginPath();
      g.arc(
        geom.cx,
        geom.cy,
        base + s.reach * geom.R,
        ang - s.span,
        ang + s.span,
      );
      g.stroke();
    }
  });

  g.restore();
}
