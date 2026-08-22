/**
 * 把各分轨解码结果合成一条单声道，供波形层与（M2-3 的）频谱层取样。
 *
 * 270 秒 × 48kHz × 4 字节 ≈ 51.8 MB（四轨时），一次性算好。
 *
 * 已知限制：结果不随静音变化。跟随静音需要保留各条独立通道（四轨约
 * 208 MB，分轨数越多越贵）或每次切换重算，两者都不划算——波形表达的是
 * "这首歌此刻的样子"，不是"你正在听到的样子"。
 *
 * 一个隐含假设，写下来免得日后踩：各分轨是**直接相加**的（只按声道数
 * 平均，不按轨数归一），所以理论上峰值可以超过 1.0，被 waveformAt 钳掉。
 *
 * 这个"实际不会削波"的前提**只对 Demucs 分离出的真歌成立，对独立编写
 * 的多轨（M5v2 的合成曲）不成立**——两者的物理条件不同，不能共用同一句
 * 论证：
 *
 * - 真歌：四条 stem 是从一条已经母带处理、未过载的混音里分离出来的，
 *   加总天然回到原混音的响度量级——demo 曲目实测峰值 -1.8 dB，不削波。
 * - 合成曲：九条 stem 是各自独立生成的，从未经过统一母带处理，上面那条
 *   物理保证不成立。全仓评审实测：九条求和峰值 **2.03**（用旧的四组
 *   分组方式对同一批波形求和是 **1.87**——这是这批波形本身就有的问题，
 *   不是本轮把四组拆成九条引入的；九分比四分再涨约 8.6%，是因为按"单条
 *   最大值"归一化时，切得越细单条峰值越低，给同一批总能量分配到的增益
 *   就越大）。
 *
 * 这个超限值不在这里修——它是 `render_score` 归一化策略的地盘，是后续
 * 步骤要处理的问题；这里只负责把"前提在什么条件下成立"这件事写清楚。
 */

export function mixToMono(buffers) {
  if (!buffers) return null;
  const list = Object.values(buffers).filter(Boolean);
  if (!list.length) return null;

  const sr = list[0].sampleRate;
  const length = list.reduce((m, b) => Math.max(m, b.length), 0);
  const out = new Float32Array(length);

  for (const buf of list) {
    const chans = buf.numberOfChannels;
    for (let c = 0; c < chans; c++) {
      const data = buf.getChannelData(c);
      for (let i = 0; i < data.length; i++) out[i] += data[i] / chans;
    }
  }
  return { channel: out, sr };
}
