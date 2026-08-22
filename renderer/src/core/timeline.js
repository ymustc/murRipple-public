/**
 * timeline.json 的解码与查询。
 *
 * 这一层是渲染器与构建时管线之间的唯一接触面——各视觉层只跟本模块打
 * 交道，不认识 base64、不认识 60Hz 网格。
 */

export const ENVELOPE_RATE = 60;

/** base64 → Uint8Array。与 murripple/envelope.py 的 encode_u8 配对。 */
export function decodeU8(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/**
 * 单极点低通，对整条数组一次算完。
 *
 * 必须一次算完而不是逐帧累积：逐帧平滑是有状态的，实时模式 seek 之后
 * 滤波器状态与离线渲染不同，同一个 t 会画出不同的帧——与粒子系统同类
 * 的确定性陷阱。预计算之后各层只做查表，无状态、seek 安全、且更快。
 */
export function smooth(arr, tauMs, rate = ENVELOPE_RATE) {
  const out = new Float32Array(arr.length);
  if (!arr.length) return out;
  const a = Math.exp(-1 / ((tauMs / 1000) * rate));
  let y = arr[0];
  for (let i = 0; i < arr.length; i++) {
    y = a * y + (1 - a) * arr[i];
    out[i] = y;
  }
  return out;
}

/** 按 60Hz 网格取值，越界钳制到首尾。 */
export function sampleAt(arr, t, rate = ENVELOPE_RATE) {
  if (!arr.length) return 0;
  const i = Math.min(arr.length - 1, Math.max(0, Math.round(t * rate)));
  return arr[i];
}

/** 当前段落下标。sections 按 t 升序，首段的 t 为 0。 */
export function sectionIndexAt(sections, t) {
  let idx = 0;
  for (let i = 0; i < sections.length; i++) {
    if (sections[i].t <= t) idx = i;
    else break;
  }
  return idx;
}

/** 当前歌词下标；不在任何句子的时间窗内时返回 -1。 */
export function lyricIndexAt(lyrics, t) {
  for (let i = 0; i < lyrics.length; i++) {
    if (t >= lyrics[i].t0 && t < lyrics[i].t1) return i;
    if (lyrics[i].t0 > t) break;
  }
  return -1;
}

const RING_TAU_MS = 250;
const LANE_TAU_MS = 180;

/** 把 timeline.json 文档解成渲染器直接可用的结构。 */
export function loadTimeline(doc) {
  const ringEnv = decodeU8(doc.ring.envelope);
  return {
    meta: doc.meta,
    // Task 5：分轨列表由 timeline 顶层的 stems 字段声明（真歌四条、合成曲
    // 九条），main.js 的解码循环与静音过滤据此遍历 timeline.stems，不再
    // 写死 4 个 stem。brief 的 Files 列表没提 timeline.js，但没有这一行
    // 传递，main.js 里的 `timeline.stems` 永远是 undefined——这是计划稿
    // 的一处缺口，按 CONSTRAINTS.md「以现实为准」在此补上。
    stems: doc.stems,
    beats: doc.beats,
    downbeats: doc.downbeats,
    sections: doc.sections,
    lyrics: doc.lyrics,
    ring: {
      env: ringEnv,
      envSmooth: smooth(ringEnv, RING_TAU_MS),
      presence: decodeU8(doc.ring.presence),
    },
    lanes: doc.lanes.map((lane) => {
      const env = decodeU8(lane.envelope);
      return {
        id: lane.id,
        label: lane.label,
        hue: lane.hue,
        stem: lane.stem,
        gain: lane.gain,
        notes: lane.notes,
        env,
        envSmooth: smooth(env, LANE_TAU_MS),
      };
    }),
  };
}
