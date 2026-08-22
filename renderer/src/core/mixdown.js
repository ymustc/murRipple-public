/**
 * 按当前静音状态把各分轨混成一条，导出 WAV。
 *
 * **这是原始音频文件给不了的东西**：把鼓静音之后的那一版只存在于播放器
 * 里。参考项目导出的是它现场合成的音乐（那是它唯一能把音乐带走的途径）；
 * 我们的音频本来就是用户自己的文件，原样吐回没有意义——有意义的是"我调
 * 出来的这一版"。
 *
 * 用 OfflineAudioContext 而不是实时录：离线渲染比实时快得多，且不受播放
 * 位置影响，导出的永远是完整一首。
 */

import { encodeWav } from "./wav.js";

/**
 * @param buffers {stem: AudioBuffer}
 * @param gainFor (stem) => 0|1，通常传 muteState.gainFor
 * @returns Promise<{ blob 用的 ArrayBuffer, sampleRate }>
 */
export async function renderMixdown(buffers, gainFor, OfflineCtor) {
  // 分轨列表由 buffers 自己的 key 集合决定——不再靠写死的 STEMS 过滤，
  // 否则合成曲九条只会混前四条。
  const present = Object.keys(buffers).filter((s) => buffers[s]);
  if (!present.length) throw new Error("没有可混的音轨");

  const first = buffers[present[0]];
  const sampleRate = first.sampleRate;
  // 取最长的一轨：各分轨理论上等长，但解码后差几个样本是常事，取短的会截尾
  const length = Math.max(...present.map((s) => buffers[s].length));
  const channels = Math.max(...present.map((s) => buffers[s].numberOfChannels));

  const ctx = new OfflineCtor(channels, length, sampleRate);
  for (const stem of present) {
    const g = ctx.createGain();
    g.gain.value = gainFor(stem);
    g.connect(ctx.destination);
    const src = ctx.createBufferSource();
    src.buffer = buffers[stem];
    src.connect(g);
    src.start(0);
  }

  const rendered = await ctx.startRendering();
  const data = Array.from({ length: rendered.numberOfChannels }, (_, i) =>
    rendered.getChannelData(i),
  );
  return { buffer: encodeWav(data, sampleRate), sampleRate };
}
