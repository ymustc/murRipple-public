/**
 * 下落音符 + 彗尾。
 *
 * 音符从外圈坠向判定环，命中时消失、由粒子层接管爆开的光屑。
 *
 * 彗尾用同一条径向线上的多段渐隐描出，**不用 canvas 的累积残影**——
 * 那是跨帧状态，会让同一个 t 在实时与离线下画出不同的帧。
 */

import { visibleNotes, laneAngle } from "../core/notes.js";
import { OUTER_RATIO, NOTE_START_RATIO } from "../core/geometry.js";
import { makeGlowSprite } from "../core/glow.js";

const TAIL_SEGMENTS = 5;
const TAIL_SEGMENTS_LOW = 2;

/**
 * 每段彗尾占整段下落距离的比例。
 *
 * 原先取 0.012——下落距离是 0.6R，1280×720 下每段只有 1.5 像素、五段合计
 * 7 像素，肉眼根本看不出有尾巴。截图目视才发现，单测覆盖不到这种事。
 */
const TAIL_SPACING = 0.075;

/**
 * 音符本体与辉光的尺寸，单位是判定环半径 R。
 *
 * 不能按 geom.dpr 定：dpr 封顶为 2 且与窗口大小无关，而 R 随窗口涨。
 * 窗口一变大，音符不变大、它炸出的光屑（按 R 定尺寸）却变大，两者对不
 * 上；M3 若以更高分辨率离线导出，「网页上看到的就是导出视频里的」也
 * 就不成立了。dpr 只该用在 lineWidth 上。
 */
const DOT_R = 0.0129;
const DOT_R_BY_V = 0.0198;
const GLOW_R = 0.079;
const GLOW_R_BY_V = 0.149;

/**
 * 彗尾外端的半径上限，单位 R。
 *
 * geometry.js 写明的预算是：最外圈 1.6R = 短边的 0.448，余下 10% 留给
 * 辉光外溢，即短边一半 = 1.786R。TAIL_SPACING 从 0.012 提到 0.075 后，
 * 尾尖到 1.870R——当前六轨排布下离画幅边只剩 7.7 像素，把外溢余量吃光
 * 了，换个轨道数就会被上下裁掉。与刚修掉的谱线裁切是同一类问题。
 */
const MAX_TAIL_R = NOTE_START_RATIO * 1.02;

export const NAME = "notes";

export function draw(g, state) {
  const { timeline, palette, geom, t, simT, doc, quality } = state;
  if (geom.W === 0) return;

  const n = timeline.lanes.length;
  const innerR = geom.R * OUTER_RATIO;
  const outerR = geom.R * NOTE_START_RATIO;
  const segments = quality < 1 ? TAIL_SEGMENTS_LOW : TAIL_SEGMENTS;

  g.save();
  g.globalCompositeOperation = "lighter";

  timeline.lanes.forEach((lane, laneIdx) => {
    const hue = (lane.hue + palette.hueShift) % 360;

    // emittedThrough 用粒子世界的 simT 而不是 t：两者判据不一致时，
    // simT < note.t ≤ t 的那一小段里音符已消失、光屑还没生成，命中会
    // 闪掉一帧。实测最坏相位下半数命中受影响。
    for (const { note, progress } of visibleNotes(
      lane.notes,
      t,
      undefined,
      simT,
    )) {
      // 与粒子层共用同一个方位角，光屑才会从音符落点上爆开
      const ang = laneAngle(laneIdx, n, note.pitch);
      const r = outerR + (innerR - outerR) * progress;
      const x = geom.cx + Math.cos(ang) * r;
      const y = geom.cy + Math.sin(ang) * r;

      // 彗尾：沿来路多段渐隐
      g.strokeStyle = `hsl(${hue} ${palette.sat}% 66%)`;
      const tailCap = geom.R * MAX_TAIL_R;
      for (let s = 1; s <= segments; s++) {
        const back = Math.min(
          tailCap,
          r + (outerR - innerR) * TAIL_SPACING * s,
        );
        g.globalAlpha = (1 - s / (segments + 1)) * 0.34 * note.v;
        g.lineWidth = (3.4 - s * 0.45) * geom.dpr;
        g.beginPath();
        g.moveTo(geom.cx + Math.cos(ang) * back, geom.cy + Math.sin(ang) * back);
        const prev = Math.min(
          tailCap,
          back + (outerR - innerR) * TAIL_SPACING,
        );
        g.lineTo(geom.cx + Math.cos(ang) * prev, geom.cy + Math.sin(ang) * prev);
        g.stroke();
      }

      // 音符本体：越接近判定环越亮
      const heat = 0.35 + progress * 0.65;
      if (doc) {
        const size = (GLOW_R + note.v * GLOW_R_BY_V) * geom.R * heat;
        const sprite = makeGlowSprite(doc, hue, palette.sat, 64);
        g.globalAlpha = heat * (0.4 + note.v * 0.5);
        g.drawImage(sprite, x - size / 2, y - size / 2, size, size);
      }
      g.globalAlpha = heat;
      g.fillStyle = `hsl(${hue} ${Math.min(100, palette.sat + 15)}% ${
        60 + progress * 28
      }%)`;
      g.beginPath();
      g.arc(
        x,
        y,
        (DOT_R + note.v * DOT_R_BY_V) * geom.R * heat,
        0,
        Math.PI * 2,
      );
      g.fill();
    }
  });

  g.restore();
}
