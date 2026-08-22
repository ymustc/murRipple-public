/**
 * 命中光屑。
 *
 * 画在环之上——否则命中的爆发感会被环盖住（M2 spec 第 7 节）。
 *
 * 粒子坐标是相对判定环的归一化偏移，这里才乘以 geom.R 变成像素。
 */

import { makeGlowSprite } from "../core/glow.js";

/** 低于这个归一化尺寸就不画辉光——不足一像素，白费一次 drawImage。 */
const GLOW_MIN_SIZE = 0.004;

/** 拖尾长度 = 速度 × 这个秒数（归一化单位，绘制时乘 R）。 */
const TAIL_SEC = 0.16;

export const NAME = "particles";

export function draw(g, state) {
  const { world, geom, palette, doc, t } = state;
  if (!world || geom.W === 0) return;

  g.save();
  g.globalCompositeOperation = "lighter";

  for (const p of world.particles) {
    const fade = Math.max(0, Math.min(1, p.life / p.maxLife));
    // 归一化偏移 → 像素。发射点在判定环上，沿发射角向外
    const originX = geom.cx + Math.cos(p.anchor) * geom.R;
    const originY = geom.cy + Math.sin(p.anchor) * geom.R;
    const x = originX + p.x * geom.R;
    const y = originY + p.y * geom.R;
    const scaled = p.size * (0.6 + fade * 0.8);
    const size = scaled * geom.R;
    const hue = (p.hue + palette.hueShift) % 360;

    // 阈值用归一化尺寸而非像素：用像素的话同一颗粒子大窗口有辉光、小
    // 窗口没有，画面就跟窗口大小有关了。
    if (doc && scaled > GLOW_MIN_SIZE) {
      const sprite = makeGlowSprite(doc, hue, palette.sat, 64);
      g.globalAlpha = fade * 0.5;
      g.drawImage(sprite, x - size * 2, y - size * 2, size * 4, size * 4);
    }
    // 彗星拖尾：沿速度的反方向拖一段渐隐线段。
    //
    // 此前是个小圆点，散在画面里像噪点；拖尾一出来才有"星云被搅动"的
    // 方向感。长度正比于速度，所以刚炸开时最长、慢下来自然收成一点。
    const speed = Math.hypot(p.vx, p.vy);
    const tail = speed * TAIL_SEC * geom.R;
    const light = 66 + fade * 22;
    const sat = Math.min(100, palette.sat + 20);
    if (tail > 1) {
      const ux = p.vx / speed;
      const uy = p.vy / speed;
      const grad = g.createLinearGradient(x, y, x - ux * tail, y - uy * tail);
      grad.addColorStop(0, `hsla(${hue} ${sat}% ${light}% / ${fade * 0.85})`);
      grad.addColorStop(1, `hsla(${hue} ${sat}% ${light}% / 0)`);
      g.globalAlpha = 1;
      g.strokeStyle = grad;
      g.lineWidth = Math.max(0.8, size * 1.5);
      g.lineCap = "round";
      g.beginPath();
      g.moveTo(x, y);
      g.lineTo(x - ux * tail, y - uy * tail);
      g.stroke();
    }

    if (p.glint) {
      // 十字星芒：高频轨的光屑是"细碎的光"，圆点表达不出那种锐利。
      // 旋转角由 t 算，不累积——这一层每帧都在变。
      const arm = size * 3.2 * (0.5 + fade);
      g.save();
      g.translate(x, y);
      g.rotate(p.anchor + t * 0.7);
      g.globalAlpha = fade * 0.9;
      g.strokeStyle = `hsl(48 90% 80%)`;
      g.lineWidth = 0.9 * geom.dpr;
      g.beginPath();
      g.moveTo(-arm, 0);
      g.lineTo(arm, 0);
      g.moveTo(0, -arm);
      g.lineTo(0, arm);
      g.stroke();
      g.restore();
    }

    // 头部：一点实心，拖尾才有"头"
    g.globalAlpha = fade * 0.95;
    g.fillStyle = `hsl(${hue} ${sat}% ${light}%)`;
    g.beginPath();
    g.arc(x, y, Math.max(0.6, size), 0, Math.PI * 2);
    g.fill();
  }

  g.restore();
}
