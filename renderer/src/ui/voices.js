/**
 * 声部面板：色点 + 中英文名 + 横向电平。
 *
 * 与 hud 一样是 DOM 覆盖层，理由见 hud.js 顶部。
 *
 * **行数 = 1 + timeline.lanes.length，不再写死七行**：真歌六条轨道、
 * 合成曲八条轨道，人声/主奏之外每条轨道一行——它没有轨道弧，电平取判定
 * 环的包络（人声本来就驱动那个环）。
 *
 * **音频按 timeline.stems 声明的分轨静音**（真歌四个：vocals/drums/bass/
 * other；合成曲九个，逐轨独立）。真歌里点「撼岳」会把整个鼓组静音、
 * 撼岳/裂帛/碎玉三行一起变暗；合成曲每条轨道自己的 stem 独立，点一行
 * 只动它自己。
 *
 * **连动必须在按下之前就看得见。** 原先只靠「一起变暗」表达分组——那是
 * 点下去之后才出现的反馈，面板静止时四条鼓行看上去仍是四个独立开关，
 * 界面在骗人。现在每行带上 data-group-* （见 buildVoiceRows），共用同一
 * 条分轨的相邻行左侧连成一道竖脊，面板底部再挂一行说明；不点、不悬停
 * 就能看出哪几行是一体的。
 *
 * 归组关系**只从 lane.stem 推**，不认识 "kick/snare/hat 是鼓" 这种事实
 * ——素材换了、htdemucs_6s 上了，硬编码当场开始骗人。真歌今天推出来的
 * 是两组（drums 三行 + other 两行，见 murripple/lanes.py 的 LANE_SPECS），
 * 合成曲推出来一组都没有。
 */

import { sampleAt } from "../core/timeline.js";

/**
 * 轨道 id → 中英文名。
 *
 * 不沿用参考项目的那一套声部名——那是它的创作内容，不得挪用（MGMT 第
 * 六节）。这一套按各声部在乐曲里的角色取意——最低最沉的一击是撼岳，撕帛
 * 之声是裂帛，高频细碎是碎玉，深处的持续轰鸣是渊鸣。
 *
 * **mid/pad 共用「流岚」、air/pluck 共用「缥缈」**：真歌的 lane 只会是
 * kick/snare/hat/bass/mid/air，合成曲的 lane 只会是
 * bass/pad/pluck/arp/bell/kick/snare/hat（design 稿第四节声部名表、
 * task-8-brief 的 NAMES 表口径一致）——mid 与 pad 不会同时出现在同一首
 * 歌的面板里，air 与 pluck 也一样，因此复用同一个名字不会在面板上撞出
 * 两行同名。
 */
export const LABELS = {
  kick: { zh: "撼岳", en: "QUAKING PEAK" },
  snare: { zh: "裂帛", en: "RENT SILK" },
  hat: { zh: "碎玉", en: "JADE SHARDS" },
  bass: { zh: "渊鸣", en: "ABYSS TOLL" },
  mid: { zh: "流岚", en: "DRIFTING HAZE" },
  air: { zh: "缥缈", en: "ETHER" },
  pad: { zh: "流岚", en: "DRIFTING HAZE" },
  pluck: { zh: "缥缈", en: "ETHER" },
  arp: { zh: "泠泠", en: "LIMPID RUN" },
  bell: { zh: "霜铎", en: "FROST CHIME" },
};

/**
 * 面板行：第一行是人声/主奏，驱动判定环、不占轨道；其余每条 timeline.lanes
 * 一行。真歌 1+6=7 行，合成曲 1+8=9 行。
 *
 * 每行另外带两个从数据推出来的归组字段：
 *
 * - `groupSize`：面板上共用这条 stem 的行数。1 就是独立的一行。
 * - `groupPos`：`null`（独立）或 `"first" | "mid" | "last" | "lone"`。
 *   竖脊按它画：first 封上口、mid 直通、last 封下口。
 *
 * **groupPos 只看紧邻的上下两行**，不看整组。这样即使某天 lane 顺序变得
 * 不连续（同一条 stem 中间隔着别的 stem），画出来的也是两段各自封口的
 * 竖脊，而不是一道横跨无关行的长线——宁可少说，不可说错。那种落单的一行
 * （groupSize>1 却上下都不同组）标成 `"lone"`：它仍然是连动的，只是脊
 * 连不过去。
 */
export function buildVoiceRows(timeline) {
  const head = { lane: null, stem: "vocals", zh: "心籁", en: "SOUL REED", hue: 300 };
  const rest = timeline.lanes.map((l) => ({
    lane: l.id,
    stem: l.stem,
    zh: LABELS[l.id]?.zh ?? l.label,
    en: LABELS[l.id]?.en ?? l.id.toUpperCase(),
    hue: l.hue,
  }));
  const rows = [head, ...rest];

  const count = new Map();
  for (const r of rows) count.set(r.stem, (count.get(r.stem) ?? 0) + 1);

  return rows.map((r, i) => {
    const groupSize = count.get(r.stem);
    if (groupSize < 2) return { ...r, groupSize, groupPos: null };
    const prevSame = rows[i - 1]?.stem === r.stem;
    const nextSame = rows[i + 1]?.stem === r.stem;
    const groupPos = prevSame
      ? nextSame
        ? "mid"
        : "last"
      : nextSame
        ? "first"
        : "lone";
    return { ...r, groupSize, groupPos };
  });
}

export const NAME = "voices";

export function createVoices(doc, root, { lanes, ring, mute, onToggle, onHover }) {
  const el = doc.createElement("div");
  el.id = "mr-voices";
  root.appendChild(el);

  const rows = [];
  const voiceRows = buildVoiceRows({ lanes });

  for (const v of voiceRows) {
    const lane = v.lane ? lanes.find((l) => l.id === v.lane) : null;
    // 人声没有轨道弧，电平取判定环的包络
    const env = lane ? lane.envSmooth : ring.envSmooth;
    const gain = lane ? lane.gain : 1;
    const hue = lane ? lane.hue : v.hue;

    const row = doc.createElement("button");
    row.type = "button";
    row.className = "mr-voice";
    row.dataset.stem = v.stem;
    if (v.lane) row.dataset.lane = v.lane;
    // 归组标记只在真的有连动时才写。合成曲九行 groupSize 全是 1，
    // 一个 data-group-pos 都不会出现，CSS 那条竖脊自然一道也画不出来
    // ——「没有虚假归组暗示」是靠属性根本不存在保证的，不是靠样式盖住。
    if (v.groupPos) {
      row.dataset.groupPos = v.groupPos;
      row.dataset.groupSize = String(v.groupSize);
    }
    row.setAttribute("aria-pressed", "false");
    row.innerHTML = `
      <i class="mr-dot" style="background:hsl(${hue} 72% 62%)"></i>
      <span class="mr-name"><b></b><em></em></span>
      <i class="mr-meter"><i></i></i>
    `;
    row.querySelector("b").textContent = v.zh;
    row.querySelector("em").textContent = v.en;

    row.addEventListener("click", () => onToggle(v.stem));
    // 悬停：环上对应那段弧高亮，其余压暗
    row.addEventListener("pointerenter", () => onHover(v.lane));
    row.addEventListener("pointerleave", () => onHover(null));

    el.appendChild(row);
    rows.push({ row, env, gain, stem: v.stem, bar: row.querySelector(".mr-meter > i"), last: -1 });
  }

  // 竖脊说明它「是一体的」，这一行说明「一体在哪」。**只在真有连动时才挂**
  // ——合成曲九行全独立，多这一行就是凭空给出一个不存在的概念。
  //
  // 同时用 aria-describedby 指向它：竖脊是纯视觉的，读屏用户拿不到，得让
  // 那几个按钮自己把连动说出来。
  const grouped = voiceRows.filter((v) => v.groupPos);
  if (grouped.length) {
    const note = doc.createElement("p");
    note.id = "mr-voice-note";
    note.className = "mr-voice-note";
    note.textContent = "左侧连线的几行共用一条分轨，静音时一起走";
    el.appendChild(note);
    for (const r of rows) {
      if (r.row.dataset.groupPos) r.row.setAttribute("aria-describedby", note.id);
    }
  }

  /** 按当前静音状态刷新全部行的明暗。同一 stem 的行一起变。 */
  function syncMute() {
    for (const r of rows) {
      const m = mute.isMuted(r.stem);
      r.row.setAttribute("aria-pressed", String(m));
      r.row.classList.toggle("muted", m);
    }
  }

  return {
    el,
    syncMute,

    update(t) {
      for (const r of rows) {
        const level = Math.min(1, (sampleAt(r.env, t) / 255) * r.gain);
        const v = Math.round(level * 100);
        // 只在整数百分点变化时写 DOM，理由同 hud.update
        if (v !== r.last) {
          r.last = v;
          r.bar.style.width = `${Math.max(2, v)}%`;
        }
      }
    },

    destroy() {
      el.remove();
    },
  };
}
