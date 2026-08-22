/**
 * 辐射谱线：环外一圈随频谱伸缩的短线。
 *
 * 这是画面视觉重量的主要来源。数据现场做 FFT，不进 timeline.json——
 * 给定 t 取同一窗口必得同一结果，确定性天然成立且零字节成本。
 *
 * 频段按**对数**分桶。线性分桶时低频挤在头几根、高频占掉大半，画出来
 * 是"一边一堆一边空"；而人对频率的感知本来就是对数的。
 */

import { spectrumAt } from "../core/dsp.js";
import {
  SPECTRUM_BASE_RATIO,
  SPECTRUM_MAX_RATIO,
} from "../core/geometry.js";

/**
 * 每侧的桶数；镜像后总根数是它的两倍。
 *
 * 参考项目是 66 个桶、每个桶左右各画一根 = 132 根。我起初写成每侧 33 根
 * （总 66 根），正好少了一半——肉眼一看就稀。
 */
const BUCKETS = 66;
const BUCKETS_LOW = 40;
/** 谱线长度相对判定环半径的最大比例。 */
const MAX_LEN = 0.42;
const FFT_SIZE = 1024;

/** dB 映射区间。窄一点线更活，宽一点更稳。 */
const DB_MIN = -78;
const DB_MAX = -18;

/**
 * 对数分桶的边界。
 *
 * 范围取 42 Hz – 13.5 kHz。低端到 42 Hz 才盖得住贝斯的基频，高端 13.5k
 * 之上乐曲基本没有内容，分了也是空桶。
 *
 * 下限取 bin 2（约 86 Hz）而非 1：bin 0/1 是直流与窗函数的泄漏，会让
 * 首根谱线常年拉满。次低频因此不进谱线，但低音本来就有自己的轨道。
 *
 * 边界强制逐格递增。纯几何分桶在低频端会挤成一团——实测 64 个桶里只有
 * 49 个不同的 bin 区间，最长一组 4 个桶读同一个 mag[2]，画出来是环顶
 * 那 8 根谱线永远等长同步伸缩。分辨率不可能细过一个 bin，与其让多个桶
 * 读同一格，不如把它们摊开。
 */
function bucketEdges(bins, count, sr = 44100) {
  const binHz = sr / 2 / bins;
  const lo = Math.max(1, Math.round(42 / binHz));
  const hi = Math.min(bins - 1, Math.round(13500 / binHz));
  const edges = new Uint16Array(count + 1);
  for (let i = 0; i <= count; i++) {
    const want = Math.round(lo * Math.pow(hi / lo, i / count));
    edges[i] = i === 0 ? lo : Math.max(want, edges[i - 1] + 1);
  }
  return edges;
}

// 分桶边界只由 (频点数, 谱线根数) 决定，与 t 无关，所以缓存起来不违反
// 确定性铁则二——那条禁止的是"随时间滞后的量跨帧累积"，这里是纯查表。
let cachedEdges = null;
let cachedKey = "";

export const NAME = "spectrum";

export function draw(g, state) {
  const { audio, geom, palette, t, quality } = state;
  if (!audio || geom.W === 0) return;

  const buckets = quality < 1 ? BUCKETS_LOW : BUCKETS;
  const mag = spectrumAt(audio.channel, audio.sr, t, FFT_SIZE);

  // 左右镜像：低频在正上方，向两侧各展开 π。角度即频段，而乐曲能量集中
  // 在中低频，一一映射的话只有小半圈有线。
  const key = `${mag.length}|${buckets}|${audio.sr}`;
  if (cachedKey !== key) {
    cachedEdges = bucketEdges(mag.length, buckets, audio.sr);
    cachedKey = key;
  }
  const edges = cachedEdges;

  // 谱线自最外圈**向内**伸。
  //
  // 起初是向外伸（base = R*1.6*1.08，长度到 0.42R），实测在 1280×720 下
  // 最远到 433 像素，而短边一半只有 360——上下两端被画幅整齐切掉。几何
  // 注释里其实写着预算：最外圈已占到短边的 0.448，余下 10% 是留给辉光
  // 外溢的，本来就没有谱线的位置。
  //
  // 向内伸反而更好：环与外圈之间那条带子是当前画面最空的地方。
  // 起点紧贴车道弧外沿：参考项目是 R + 8px，不是 1.1R
  const base = geom.R * SPECTRUM_BASE_RATIO + 8 * geom.dpr;
  const maxLen = geom.R * (SPECTRUM_MAX_RATIO - SPECTRUM_BASE_RATIO);
  const hue = (palette.hueShift + 200) % 360;

  g.save();
  g.globalCompositeOperation = "lighter";
  g.lineWidth = 2.4 * geom.dpr;
  // 圆头端点：柔光的关键。平端点画出来是硬线条，冠形就"硬"了。
  g.lineCap = "round";

  for (let i = 0; i < buckets; i++) {
    let peak = 0;
    for (let b = edges[i]; b < Math.max(edges[i] + 1, edges[i + 1]); b++) {
      if (mag[b] > peak) peak = mag[b];
    }
    // **必须走 dB 刻度，不能用线性幅度。**
    //
    // 参考项目的 v 取自 getByteFrequencyData，那本身就是 dB 映射
    // （默认 −100…−30 dB → 0…255），音乐素材上典型值 0.3–0.7，平方后
    // 长度只有 0.09–0.45 R。我起初直接拿线性幅度乘一个增益，为了让线
    // 够多把增益提到 16，结果 v 顶到接近 1、平方之后又长又少——线条
    // 长得离谱正是这么来的。
    const db = 20 * Math.log10(peak + 1e-9);
    const v = Math.max(0, Math.min(1, (db - DB_MIN) / (DB_MAX - DB_MIN)));
    if (v < 0.02) continue;

    // 长度取**平方**：弱频段被压得更狠，冠形因此是光滑包络而不是尖刺。
    const len = v * v * maxLen;
    const h2 = (hue + (i / buckets) * 90 - 45 + 360) % 360;
    // 透明度只有 0.06–0.24：它是柔光，不是骨架。画重了整圈就发死。
    g.strokeStyle = `hsla(${h2} ${palette.sat}% ${55 + v * 25}% / ${
      0.06 + v * 0.18
    })`;

    // 以正上方为轴，左右各展开 π
    for (const sgn of [1, -1]) {
      const a = -Math.PI / 2 + (sgn * (i + 0.5) * Math.PI) / buckets;
      const cos = Math.cos(a);
      const sin = Math.sin(a);
      g.beginPath();
      g.moveTo(geom.cx + cos * base, geom.cy + sin * base);
      g.lineTo(geom.cx + cos * (base + len), geom.cy + sin * (base + len));
      g.stroke();
    }
  }

  g.restore();
}
