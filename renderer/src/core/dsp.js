/**
 * 从解码后的音频现场算频谱与波形。
 *
 * 这两样东西不进 timeline.json：给定 t 取同一窗口必得同一结果，确定性
 * 天然成立，而 1024 点 FFT 一帧只要零点几毫秒，比多背 1MB 的频谱矩阵
 * 划算得多。
 */

const HANN_CACHE = new Map();

function hann(n) {
  let w = HANN_CACHE.get(n);
  if (!w) {
    w = new Float32Array(n);
    for (let i = 0; i < n; i++) w[i] = 0.5 * (1 - Math.cos((2 * Math.PI * i) / (n - 1)));
    HANN_CACHE.set(n, w);
  }
  return w;
}

/**
 * 原地 radix-2 FFT，返回前半部分的幅度谱。
 * re/im 长度必须是 2 的幂，且会被就地修改。
 */
export function fftMag(re, im) {
  const n = re.length;

  // 位反转置换
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [re[i], re[j]] = [re[j], re[i]];
      [im[i], im[j]] = [im[j], im[i]];
    }
  }

  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len;
    const wRe = Math.cos(ang);
    const wIm = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let curRe = 1;
      let curIm = 0;
      for (let k = 0; k < len / 2; k++) {
        const aRe = re[i + k];
        const aIm = im[i + k];
        const bRe = re[i + k + len / 2] * curRe - im[i + k + len / 2] * curIm;
        const bIm = re[i + k + len / 2] * curIm + im[i + k + len / 2] * curRe;
        re[i + k] = aRe + bRe;
        im[i + k] = aIm + bIm;
        re[i + k + len / 2] = aRe - bRe;
        im[i + k + len / 2] = aIm - bIm;
        const nextRe = curRe * wRe - curIm * wIm;
        curIm = curRe * wIm + curIm * wRe;
        curRe = nextRe;
      }
    }
  }

  const half = n >> 1;
  const mag = new Float32Array(half);
  for (let i = 0; i < half; i++) mag[i] = Math.hypot(re[i], im[i]) / half;
  return mag;
}

/** 取 t 处一个窗口的幅度谱。窗口以 t 为起点，加 Hann 窗。 */
export function spectrumAt(channel, sr, t, size = 1024) {
  const start = Math.max(0, Math.round(t * sr));
  const w = hann(size);
  const re = new Float32Array(size);
  const im = new Float32Array(size);
  for (let i = 0; i < size; i++) {
    const s = start + i;
    re[i] = (s < channel.length ? channel[s] : 0) * w[i];
  }
  return fftMag(re, im);
}

/** 取 t 处一小段波形，抽成 count 个点。span 为窗口秒数。 */
export function waveformAt(channel, sr, t, count = 128, span = 0.04) {
  const start = Math.max(0, Math.round(t * sr));
  const total = Math.max(1, Math.round(span * sr));
  const stride = total / count;
  const out = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const s = start + Math.round(i * stride);
    const v = s < channel.length ? channel[s] : 0;
    out[i] = Math.max(-1, Math.min(1, v));
  }
  return out;
}
