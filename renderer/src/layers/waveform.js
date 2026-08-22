/**
 * 径向波形：把一小段波形绕成闭合曲线，围在歌词外围。
 *
 * 数据不进 timeline.json——直接从解码后的音频取样，给定 t 取同一窗口
 * 必得同一结果，确定性天然成立且零字节成本。
 *
 * 没有音频时（确定性测试的部分场景、纯数据预览）整层跳过。
 */

import { waveformAt } from "../core/dsp.js";
import { sampleAt } from "../core/timeline.js";
import { WAVE_RATIO } from "../core/geometry.js";

const POINTS = 180;
const POINTS_LOW = 90;

/**
 * 波动幅度。
 *
 * 调了三轮才落在这个值：0.16 太不起眼、0.34 在高潮段又炸开成尖刺。
 * 现在取 0.20，人声能量只再推 25%——安静段的形态本来就对，要保的是
 * 那个手感，而不是让高潮段更响。
 */
const AMPLITUDE = 0.2;
const ENERGY_BOOST = 0.25;

/**
 * 相邻点平滑的窗口半径。
 *
 * 180 个点是在 40 毫秒里稀疏取单个采样点，高频内容会严重混叠——高潮段
 * 那些尖刺有一半是采样假象而不是音乐。取相邻点的加权平均把它压掉，留下
 * 真正的起伏。
 */
const SMOOTH_RADIUS = 2;

/** 环形平滑：首尾相接，不能在接缝处留下断点。 */
function smoothRing(src) {
  const n = src.length;
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    let sum = 0;
    let weight = 0;
    for (let d = -SMOOTH_RADIUS; d <= SMOOTH_RADIUS; d++) {
      const w = SMOOTH_RADIUS + 1 - Math.abs(d);
      sum += src[(i + d + n) % n] * w;
      weight += w;
    }
    out[i] = sum / weight;
  }
  return out;
}

export const NAME = "waveform";

export function draw(g, state) {
  const { audio, geom, palette, t, quality, timeline } = state;
  if (!audio || geom.W === 0) return;

  const count = quality < 1 ? POINTS_LOW : POINTS;
  const wave = smoothRing(waveformAt(audio.channel, audio.sr, t, count));
  const base = geom.R * WAVE_RATIO;
  const hue = (palette.hueShift + 190) % 360;

  // 人声越强，这一圈波动越大——让它跟着唱
  const energy = sampleAt(timeline.ring.env, t) / 255;
  const amp = AMPLITUDE * (1 + energy * ENERGY_BOOST);

  g.save();
  g.globalCompositeOperation = "lighter";
  // 亮度压在 66% 以内：两遍描边叠加法混合，再高就冲成白色、颜色全丢。
  // 上一轮取 72+energy*16（最高 88%）正是这个毛病。
  g.strokeStyle = `hsl(${hue} ${Math.min(100, palette.sat + 15)}% ${
    58 + energy * 8
  }%)`;

  // 画两遍：一遍粗而淡当辉光，一遍细而亮当芯
  for (const [widthMul, alpha] of [
    [3.0, 0.16 + energy * 0.1],
    [1.0, 0.52 + energy * 0.14],
  ]) {
    g.globalAlpha = alpha;
    g.lineWidth = (1.9 + energy * 1.0) * geom.dpr * widthMul;
    g.beginPath();
    for (let i = 0; i < count; i++) {
      const ang = (i / count) * Math.PI * 2 - Math.PI / 2;
      const r = base * (1 + wave[i] * amp);
      const x = geom.cx + Math.cos(ang) * r;
      const y = geom.cy + Math.sin(ang) * r;
      if (i === 0) g.moveTo(x, y);
      else g.lineTo(x, y);
    }
    g.closePath();
    g.stroke();
  }
  g.restore();
}
