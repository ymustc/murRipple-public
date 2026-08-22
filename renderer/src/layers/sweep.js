/**
 * 换段光扫：换段时一道光沿环外扫满一圈，1.25 秒。
 *
 * 段落切换此前只靠配色渐变，太隐蔽——一段过去了观众未必察觉。这一道扫过
 * 去，"换段了"就说清楚了，再配上段落大字说明"换到哪了"。
 *
 * 同样是 t 的纯函数，由 sections[].t 反查。
 */

import { sectionIndexAt } from "../core/timeline.js";

export const SWEEP_DUR = 1.25;
/** 扫过的半径，相对 R。 */
const RADIUS_RATIO = 1.55;
/** 拖尾段数。 */
const TAIL = 12;
const TAIL_STEP = 0.05;

export const NAME = "sweep";

/**
 * t 时刻的光扫状态，没有就返回 null。
 *
 * **第一段不扫**：t=0 那段是曲子开头，不是"换段"。开场就来一道扫会很突兀，
 * 而且那时画面还没建立起来，观众根本不知道自己在看什么。
 */
export function sweepAt(sections, t, dur = SWEEP_DUR) {
  const index = sectionIndexAt(sections, t);
  if (index <= 0) return null;
  const age = t - sections[index].t;
  if (age < 0 || age >= dur) return null;
  return {
    index,
    age,
    head: -Math.PI / 2 + (age / dur) * Math.PI * 2,
  };
}

export function draw(g, state) {
  const { timeline, palette, geom, t } = state;
  if (geom.W === 0) return;

  const sw = sweepAt(timeline.sections, t);
  if (!sw) return;

  const hue = (palette.hueShift + 200) % 360;
  const r = geom.R * RADIUS_RATIO;
  const fade = 1 - sw.age / SWEEP_DUR;

  g.save();
  g.globalCompositeOperation = "lighter";
  for (let k = 0; k < TAIL; k++) {
    const a = sw.head - k * TAIL_STEP;
    g.strokeStyle = `hsla(${hue} 80% 75% / ${(1 - k / TAIL) * fade * 0.4})`;
    g.lineWidth = Math.max(1, 26 - k * 1.7) * geom.dpr;
    g.beginPath();
    g.arc(geom.cx, geom.cy, r, a - 0.045, a);
    g.stroke();
  }
  g.restore();
}
