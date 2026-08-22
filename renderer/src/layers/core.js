/**
 * 中心光核：圆形基底 + 两片反向旋转的等离子瓣 + 内芯。
 *
 * 这一层是"光晕会动、不是正圆"的全部来源。做法是在一个圆形柔光基底上，
 * 叠两片**各自被压扁成不同长宽比、又反向缓慢旋转**的同类柔光
 * （1.85:0.58 与 0.6:1.7，转速 +0.2 与 −0.13 弧度/秒）。两片扁椭圆错开
 * 相位互相穿插，合成出来就是不断变形的有机光团——单独看每一片都规规
 * 矩矩，叠在一起才有星云感。
 *
 * 旋转角一律由 t 算，不用任何 wall clock：这一层每帧都在变，累加或读
 * 实时时钟都会让逐帧导出对不上。
 */

import { sampleAt } from "../core/timeline.js";
import { makeGlowSprite } from "../core/glow.js";
import { lyricAlphaAt } from "./lyrics.js";

/**
 * 基底半径 = R × (BASE_R + 贝斯 × BASE_BY_BASS + 底鼓 × BASE_BY_KICK)。
 *
 * 系数与参考项目不同（它是 0.5 / 0.55 / 0.30），因为素材性质不同：它的
 * 贝斯是合成的、音符之间有明确间隙；我们的贝斯是 Demucs 从混音里分出来
 * 的，**中位数高达 0.677、几乎一直在响**。照搬它的系数，光核中位会停在
 * 0.925R——大部分时间都胀着、没有"静"的状态，看着像一团恒定的光而不是
 * 在呼吸。
 *
 * 改为让**底鼓主导脉冲**（它中位 0.057、P95 0.756，动态范围极大），贝斯
 * 只做底噪。实测中位从 0.925 降到 0.606，峰值仍保持 1.11。
 */
const BASE_R = 0.4;
const BASE_BY_BASS = 0.22;
const BASE_BY_KICK = 0.75;

/**
 * 光核大小，单位是 R。单独导出以便单测——守的是"底鼓主导脉冲"这个意图，
 * 而不是三个数字本身。
 */
export function coreSize(bass, kick) {
  return BASE_R + bass * BASE_BY_BASS + kick * BASE_BY_KICK;
}

const LOBE_SCALE = 0.82;
const LOBE_A_SPIN = 0.2;
const LOBE_B_SPIN = -0.13;

/**
 * 有歌词时光核让位多少。
 *
 * 让位分轻重：**内芯让得最狠**，因为它才是把字冲白的那一个——它是一小团
 * 近白的高光，正好落在字后面。基底与两片等离子瓣是大而散的柔光，它们
 * 撑着整个中心的存在感，让太多画面就塌了，所以只收一点点。
 *
 * 让位是必要的但不是充分的：字那边还得有压幕（见 lyrics.js）。只做这一
 * 头的话，遇上底鼓砸下来内芯照样胀回去。
 */
export function coreYield(lyricAlpha) {
  const a = Math.max(0, Math.min(1, lyricAlpha));
  return {
    base: 1 - 0.22 * a,
    lobe: 1 - 0.18 * a,
    inner: 1 - 0.72 * a,
    innerR: 1 - 0.34 * a,
  };
}

export const NAME = "core";

function laneEnergy(timeline, id, t) {
  const lane = timeline.lanes.find((l) => l.id === id);
  return lane ? sampleAt(lane.envSmooth, t) / 255 : 0;
}

export function draw(g, state) {
  const { geom, palette, timeline, t, doc, quality } = state;
  if (geom.W === 0 || !doc) return;

  const bass = laneEnergy(timeline, "bass", t);
  const kick = laneEnergy(timeline, "kick", t);
  const hue = Math.round((palette.hueShift + 205) % 360);
  const sat = Math.min(100, palette.sat + 10);

  const csz = geom.R * coreSize(bass, kick);
  const lobe = csz * LOBE_SCALE;
  const yld = coreYield(lyricAlphaAt(timeline.lyrics, t));

  g.save();
  g.globalCompositeOperation = "lighter";

  // 基底：正圆，定调子
  g.globalAlpha = 0.7 * yld.base;
  g.drawImage(
    makeGlowSprite(doc, hue, sat, 128),
    geom.cx - csz,
    geom.cy - csz,
    csz * 2,
    csz * 2,
  );

  // 两片等离子瓣。低质量档只画一片——它们是这层最贵的部分（各一次
  // 带变换的 drawImage），而少一片只是少一层起伏，不影响结构。
  const lobes = quality < 1 ? [0] : [0, 1];
  for (const i of lobes) {
    const spin = i === 0 ? LOBE_A_SPIN : LOBE_B_SPIN;
    const sx = i === 0 ? 1.85 : 0.6;
    const sy = i === 0 ? 0.58 : 1.7;
    const size = i === 0 ? lobe : lobe * 0.8;
    const h = Math.round((hue + (i === 0 ? 24 : -30) + 360) % 360);
    g.save();
    g.globalAlpha = 0.32 * yld.lobe;
    g.translate(geom.cx, geom.cy);
    g.rotate(t * spin);
    g.scale(sx, sy);
    g.drawImage(makeGlowSprite(doc, h, sat, 128), -size, -size, size * 2, size * 2);
    g.restore();
  }

  // 内芯：一点白亮，让中心有实处可看。
  //
  // 收得比参考项目小：它那里中心是空的，我们要放歌词。内芯一大，字就
  // 被冲成一片白——歌词是主角，光核让位。
  g.globalAlpha = 0.55 * yld.inner;
  const inner = (7 + kick * 6 + bass * 5) * geom.dpr * yld.innerR;
  g.drawImage(
    makeGlowSprite(doc, hue, 30, 64),
    geom.cx - inner * 1.8,
    geom.cy - inner * 1.8,
    inner * 3.6,
    inner * 3.6,
  );

  g.restore();
}
