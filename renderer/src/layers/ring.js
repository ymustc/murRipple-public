/**
 * 判定环 —— 人声驱动。
 *
 * 环是人声的轮廓，歌词是人声的内容（M2 spec 第 3 节）。
 *
 * 三层叠加而非单描边：
 *   内芯  跟瞬时包络，出现"咬字"感
 *   中晕  跟平滑包络，**呼吸感来自这一层的滞后**
 *   外散  跟段落能量，撑住画面体量
 *
 * 平滑值来自 timeline.js 加载时预计算的数组，不在这里累积（铁则二）。
 * 辉光用预渲染精灵 + lighter 叠加，不用 shadowBlur——后者的实现随浏览器
 * 与硬件而异，会破坏逐帧导出的可复现性。
 */

import { RING_RATIO } from "../core/geometry.js";
import { sampleAt } from "../core/timeline.js";
import { makeGlowSprite } from "../core/glow.js";

/** 拍点让环微缩：每拍 1%，小节线 3%。 */
const BEAT_SHRINK = 0.01;
const DOWNBEAT_SHRINK = 0.03;

export const NAME = "ring";

export function draw(g, state) {
  const { timeline, palette, geom, beat, t, doc } = state;
  if (geom.W === 0) return;

  const v = sampleAt(timeline.ring.env, t) / 255;
  const smooth = sampleAt(timeline.ring.envSmooth, t) / 255;
  const awake = sampleAt(timeline.ring.presence, t) > 0;
  const hue = (210 + palette.hueShift) % 360;

  const R =
    geom.R *
    RING_RATIO *
    (1 - beat.pulse * BEAT_SHRINK - beat.downPulse * DOWNBEAT_SHRINK);

  g.save();
  g.globalCompositeOperation = "lighter";

  // 外散：一张放大的辉光精灵铺在环外围
  if (doc) {
    const sprite = makeGlowSprite(doc, hue, palette.sat, 64);
    const spread = R * 2.9;
    g.globalAlpha = 0.1 + palette.energy * 0.16 + smooth * 0.12;
    g.drawImage(sprite, geom.cx - spread / 2, geom.cy - spread / 2, spread, spread);
  }

  // 中晕：粗而柔，呼吸感的来源
  g.globalAlpha = 0.34 + smooth * 0.3;
  g.strokeStyle = `hsl(${hue} ${palette.sat}% 58%)`;
  // 收细一半：环缩小之后原来的粗细占比翻倍，成了画面里最重的块
    g.lineWidth = (2.2 + smooth * 11) * geom.dpr;
  g.beginPath();
  g.arc(geom.cx, geom.cy, R, 0, Math.PI * 2);
  g.stroke();

  // 内芯：细而亮，人声不在时压暗
  g.globalAlpha = awake ? 0.9 : 0.28;
  g.strokeStyle = `hsl(${hue} ${Math.min(100, palette.sat + 20)}% ${62 + v * 30}%)`;
  g.lineWidth = (0.9 + v * 2.4) * geom.dpr;
  g.beginPath();
  g.arc(geom.cx, geom.cy, R, 0, Math.PI * 2);
  g.stroke();

  g.restore();
}
