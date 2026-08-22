/**
 * AudioBuffer → WAV（16 位 PCM）。
 *
 * 用于"导出当前混音"：把各分轨按当前静音状态混一遍导出。这是原始音频文件
 * 给不了的东西——把鼓静音之后的那一版只存在于播放器里。
 *
 * 自己写而不是找库：一个 44 字节的头加一次量化，比引一个依赖便宜得多，
 * 而且产物必须零依赖。
 *
 * WAV 头的字节序容易写错且**错了也能生成文件**——播放器要么拒绝打开，
 * 要么放出噪音，都难查。所以头部逐字段有测试。
 */

/** RIFF 头固定 44 字节。 */
export const HEADER_BYTES = 44;

/**
 * @param channels 每声道一个 Float32Array，长度必须一致
 * @param sampleRate 采样率
 * @returns ArrayBuffer，可直接塞进 Blob
 */
export function encodeWav(channels, sampleRate) {
  if (!channels.length) throw new Error("至少要有一个声道");
  const n = channels[0].length;
  for (const ch of channels) {
    if (ch.length !== n) throw new Error("各声道长度必须一致");
  }
  const numCh = channels.length;
  const bytesPerSample = 2;
  const blockAlign = numCh * bytesPerSample;
  const dataBytes = n * blockAlign;

  const buf = new ArrayBuffer(HEADER_BYTES + dataBytes);
  const view = new DataView(buf);
  const ascii = (offset, str) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  };

  ascii(0, "RIFF");
  // 除去 "RIFF" 与本字段自身的 8 字节
  view.setUint32(4, 36 + dataBytes, true);
  ascii(8, "WAVE");
  ascii(12, "fmt ");
  view.setUint32(16, 16, true); // fmt 块长度
  view.setUint16(20, 1, true); // 1 = PCM
  view.setUint16(22, numCh, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true); // 字节率
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 8 * bytesPerSample, true);
  ascii(36, "data");
  view.setUint32(40, dataBytes, true);

  // 交织写入。**必须先钳位再量化**：叠加各分轨之后超过 ±1 是常事，
  // 不钳位的话 Math.round 会溢出 int16 并回绕，听感是爆音。
  let off = HEADER_BYTES;
  for (let i = 0; i < n; i++) {
    for (let c = 0; c < numCh; c++) {
      const s = Math.max(-1, Math.min(1, channels[c][i]));
      // 负半轴乘 0x8000、正半轴乘 0x7fff：满量程的 -1 与 +1 都要落在
      // int16 的合法范围内，用同一个系数会让 +1 溢出。
      view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      off += 2;
    }
  }
  return buf;
}
