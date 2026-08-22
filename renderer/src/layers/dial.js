/**
 * 双层反向刻度环。
 *
 * 两圈细密刻度，一内一外、反向缓慢自转，每 8 格一根长的。它不表达任何
 * 数据——纯粹是"这台机器在运转"的质感，画面因此有了机械的秩序感，而不
 * 只是一堆会亮的圆。
 *
 * 转速极慢（0.021 与 0.013 弧度/秒，一圈要五分钟以上），快了就成了跑马灯。
 * 角度由 t 算，不累加。
 */

import { sampleAt } from "../core/timeline.js";
import { DIAL_IN_RATIO, DIAL_OUT_RATIO } from "../core/geometry.js";

const RINGS = [
  { ratio: DIAL_OUT_RATIO, count: 96, spin: 0.021, alpha: 0.1, len: 4 },
  // 长度为负 = 朝内长，两圈的齿因此背向而生
  { ratio: DIAL_IN_RATIO, count: 64, spin: -0.013, alpha: 0.08, len: -3.5 },
];

/** 每隔这么多格来一根长齿。 */
const MAJOR_EVERY = 8;
const MAJOR_SCALE = 1.9;

export const NAME = "dial";

export function draw(g, state) {
  const { geom, palette, timeline, t, quality } = state;
  if (geom.W === 0) return;

  const kickLane = timeline.lanes.find((l) => l.id === "kick");
  const kick = kickLane ? sampleAt(kickLane.envSmooth, t) / 255 : 0;
  const hue = (palette.hueShift + 205) % 360;
  const baseR = geom.R + kick * 4 * geom.dpr;

  g.save();
  g.lineCap = "butt";
  g.lineWidth = 0.8 * geom.dpr;

  for (const ring of RINGS) {
    // 低质量档砍掉一半齿数：这一层是纯质感，稀一点看不出来
    const count = quality < 1 ? ring.count / 2 : ring.count;
    const rr = baseR * ring.ratio;
    g.strokeStyle = `hsla(${hue} 45% 72% / ${ring.alpha})`;
    g.beginPath();
    for (let i = 0; i < count; i++) {
      const ang = (i / count) * Math.PI * 2 + t * ring.spin;
      const len =
        (i % MAJOR_EVERY === 0 ? ring.len * MAJOR_SCALE : ring.len) * geom.dpr;
      const cos = Math.cos(ang);
      const sin = Math.sin(ang);
      g.moveTo(geom.cx + cos * rr, geom.cy + sin * rr);
      g.lineTo(geom.cx + cos * (rr + len), geom.cy + sin * (rr + len));
    }
    g.stroke();
  }

  g.restore();
}
