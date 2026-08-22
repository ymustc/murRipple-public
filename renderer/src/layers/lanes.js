/**
 * 弧形轨道，条数从 timeline.lanes 读——真歌六条、合成曲八条，都按实际
 * 条数画（Task 6 之后不再写死 6）。
 *
 * 视觉轨道数不等于可静音的分组数：真歌里底鼓/军鼓/踩镲滤自同一条鼓轨，
 * 能分开画不能分开静音，六条视觉轨道只对应四个可静音按钮；合成曲每条
 * 轨道自己的 stem 独立，视觉轨道数与可静音数相等。归属一律由
 * lane.stem 声明，这一层不关心分组，只管画弧。
 *
 * 亮度用 pow(v, 0.7) 而非线性：首曲实测六条轨道的包络均值差四五倍
 * （中层 138、低音 120 vs 气层 26、军鼓 30、踩镲 27），线性映射会让
 * 一半的轨道几乎不可见。这条曲线是全局默认，lanes[].gain 仍是 per-lane
 * 的手工调节点。
 */

import { sampleAt } from "../core/timeline.js";
import { OUTER_RATIO } from "../core/geometry.js";
import { makeGlowSprite } from "../core/glow.js";

const PERCEPTUAL_EXP = 0.7;
const GAP = 0.09;

export const NAME = "lanes";

export function draw(g, state) {
  const { timeline, palette, geom, beat, t, doc, hoverLane } = state;
  if (geom.W === 0) return;

  const n = timeline.lanes.length;
  const radius = geom.R * OUTER_RATIO * (1 - beat.pulse * 0.006);

  g.save();
  g.globalCompositeOperation = "lighter";

  timeline.lanes.forEach((lane, i) => {
    const raw = Math.min(1, (sampleAt(lane.env, t) / 255) * lane.gain);
    const v = Math.pow(raw, PERCEPTUAL_EXP);
    const hue = (lane.hue + palette.hueShift) % 360;
    const a0 = -Math.PI / 2 + (i * Math.PI * 2) / n + GAP / 2;
    const a1 = a0 + (Math.PI * 2) / n - GAP;

    // 侧栏悬停：被指到的那条提亮，其余压暗。hoverLane 只在实时交互里
    // 非空，离线导出时恒为 null——它不进确定性比对的路径。
    const dim = hoverLane && hoverLane !== lane.id ? 0.28 : 1;
    const lift = hoverLane === lane.id ? 1.45 : 1;

    // 弧本体
    g.globalAlpha = (0.5 + v * 0.5) * dim * lift;
    g.strokeStyle = `hsl(${hue} ${palette.sat}% ${20 + v * 52}%)`;
    // 参考项目的车道弧是 3 + 能量×8，很细。我们此前 4 + 能量×20，
    // 粗到成了色块，纤细感全无。
    g.lineWidth = (2.4 + v * 7) * lift * geom.dpr;
    g.lineCap = "round";
    g.beginPath();
    g.arc(geom.cx, geom.cy, radius, a0, a1);
    g.stroke();

    // 弧中点的辉光，让亮起来的轨道有体积感
    if (doc && v > 0.08) {
      const mid = (a0 + a1) / 2;
      const size = (30 + v * 90) * geom.dpr;
      const sprite = makeGlowSprite(doc, hue, palette.sat, 64);
      g.globalAlpha = v * 0.55;
      g.drawImage(
        sprite,
        geom.cx + Math.cos(mid) * radius - size / 2,
        geom.cy + Math.sin(mid) * radius - size / 2,
        size,
        size,
      );
    }
  });

  g.restore();
}
