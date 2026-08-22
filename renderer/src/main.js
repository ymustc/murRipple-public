/**
 * 装配与主循环。
 *
 * M2-1 的画面仍是探针级——这一期的产出是地基，不是好看。地基包括：
 * 可播放、可静音、可跳转、可打包成单文件、确定性可验证。
 */

import { loadTimeline } from "./core/timeline.js";
import { paletteAt } from "./core/palette.js";
import { computeGeometry } from "./core/geometry.js";
import { createClock, MODE_REALTIME } from "./core/clock.js";
import {
  createMuteState,
  createPlayer,
  dataUriToArrayBuffer,
  resumeFrom,
} from "./core/audio.js";
import { computeBeat } from "./core/beat.js";
import * as backgroundLayer from "./layers/background.js";
import * as ringLayer from "./layers/ring.js";
import * as lanesLayer from "./layers/lanes.js";
import * as rippleLayer from "./layers/ripple.js";
import * as sweepLayer from "./layers/sweep.js";
import * as shockLayer from "./layers/shock.js";
import * as laneLabelsLayer from "./layers/laneLabels.js";
import * as dialLayer from "./layers/dial.js";
import * as spectrumLayer from "./layers/spectrum.js";
import * as notesLayer from "./layers/notes.js";
import * as coreLayer from "./layers/core.js";
import * as particlesLayer from "./layers/particles.js";
import * as sectionTitleLayer from "./layers/sectionTitle.js";
import { createParticleWorld } from "./core/particles.js";
import { mixToMono } from "./core/mix.js";
import { renderMixdown } from "./core/mixdown.js";
import * as waveformLayer from "./layers/waveform.js";
import * as lyricsLayer from "./layers/lyrics.js";
import { createHud } from "./ui/hud.js";
import { createVoices } from "./ui/voices.js";
import { createTitle } from "./ui/title.js";
import { createTitleCard } from "./ui/titleCard.js";

// 测试页要装配界面，而 bundle 是 iife：只有 export 的才挂在 murRippleApp 上
export { createHud } from "./ui/hud.js";
export { createVoices } from "./ui/voices.js";
export { createTitle } from "./ui/title.js";
export { createTitleCard } from "./ui/titleCard.js";
// 测试要在真正跑起来的 harness 上核环外小字有没有漏标——不能另起一份
// 手写的 lane 列表，那样夹具换了测试也测不出来（见 boot-nine.test.mjs）
export { labelFor } from "./layers/laneLabels.js";
export { createPlayer, createMuteState, resumeFrom } from "./core/audio.js";
export { sampleAt } from "./core/timeline.js";
export { computeGeometry } from "./core/geometry.js";
// 导出管线要在页面里自己解码并混轨
export { mixToMono } from "./core/mix.js";
export { encodeWav } from "./core/wav.js";
export { renderMixdown } from "./core/mixdown.js";

/**
 * 绘制顺序即叠放顺序。M2-2 会在此插入 background / waveform / lyrics，
 * M2-3 再插入 spectrum / notes / particles / sectionTitle——位置见 M2
 * spec 第 7 节，不要随手往后追加：歌词必须压在波形之上（否则波形锯齿
 * 切碎字形），光屑必须压在环之上（否则命中的爆发感被环盖住）。
 */
export const LAYERS = [
  backgroundLayer,
  rippleLayer,
  sweepLayer,
  spectrumLayer,
  dialLayer,
  lanesLayer,
  laneLabelsLayer,
  notesLayer,
  shockLayer,
  ringLayer,
  coreLayer,
  waveformLayer,
  lyricsLayer,
  particlesLayer,
  sectionTitleLayer,
];

/**
 * drawAt 组出来的 state 里，每个字段对"这一帧还要不要重画"意味着什么。
 *
 * 实时模式下主循环每秒调 60 次 renderFrame，而**画面只是 state 的函数**：
 * state 一模一样时重画一遍，画出来的必然是同一张图，纯属白烧。实测这条
 * 白烧的循环占一个核的 111%（暂停时也一样烧，见 DECISIONS.md）。
 *
 * 要跳过重画，就必须说得清"什么变了才需要重画"。三种角色：
 *
 * - `"t"`     —— 完全由 t 决定（palette 与 beat 是 t 的纯函数）。t 本身进
 *                指纹就够了。
 * - `"const"` —— 建好之后不再变。
 * - `"key"`   —— **可变，且变了画面就不同**。必须进指纹，漏一个就是画面
 *                卡住不更新——那比多烧 CPU 严重得多。
 *
 * 这张表是**穷举**的：drawAt 第一次执行时会拿它跟真实的 state 字段对一遍，
 * 多出任何没分类的字段就当场抛错（见 assertFieldsClassified）。谁往 state
 * 里加字段，都被迫在这里表态它属于哪一类，不可能"忘了"。
 */
export const FIELD_ROLE = Object.freeze({
  t: "t",
  palette: "t", // paletteAt(sections, t)
  beat: "t", // computeBeat(timeline, t)
  timeline: "const",
  doc: "const",
  // createClock 建好之后 quality 不再变（没有任何 setter），因此它不可能让
  // "同一个 app 的同一个 t"画出两种结果，不必进指纹。**若哪天它变得可调，
  // 这里要改成 "key" 并进 frameKey。** "不同 quality 画出不同帧"这件事由
  // determinism.test.mjs 那条既有测试守着，与跳帧无关。
  //
  // （最初把它写成 "key" 并放进了指纹。变异检验把它从指纹里删掉时全绿——
  // 追下去才发现它根本不可变，"进指纹不花钱"是句糊涂话：不可变的东西进
  // 指纹既没用也无法被守卫，只会让分类表说假话。）
  quality: "const",
  geom: "key", // 改窗口 / 换屏幕 dpr
  audio: "key", // setAudio：标题页关掉那一刻从 null 变成真数据
  hoverLane: "key", // 侧栏悬停，t 不动画面也会变——正是最容易漏的那个
  // world 与 simT 由时钟推进，**它们不是 t 的纯函数**：advanceOrRewind 对
  // 小于一个步长的后退有意不倒带（见 clock.js 的容差说明），于是同一个 t
  // 可能对应相差一步的两个世界。实测 t=4.99167 处，simT 为 5.0 与 4.99167
  // 时画出的帧哈希不同（3265dc48… vs bfeb4c98…）。所以 simT 必须进指纹，
  // world 的状态由 simT 代表。
  world: "key",
  simT: "key",
});

/** state 里出现了 FIELD_ROLE 没收录的字段就抛错。只在第一帧查一次。 */
export function assertFieldsClassified(state) {
  const unknown = Object.keys(state).filter((k) => !(k in FIELD_ROLE));
  if (unknown.length) {
    throw new Error(
      `state 里有没分类的字段：${unknown.join(", ")}。` +
        "请在 main.js 的 FIELD_ROLE 里表态它是 t / const 还是 key——" +
        "若它可变且影响画面（key），还必须进 frameKey，否则跳帧会让画面卡住。",
    );
  }
}

export function createApp({
  doc,
  canvas,
  timelineDoc,
  mode = MODE_REALTIME,
  quality = 1,
  // 只为测试而存在：抠掉某一层再渲一遍、比较像素差，才能钉住"这一层
  // 真的在画"。帧哈希只把两次运行互相比对，整层被跳过它照样是绿的。
  layers = LAYERS,
}) {
  const timeline = loadTimeline(timelineDoc);
  const clock = createClock({ mode, quality });
  // M2-1 起这里一直是个空世界，clock.advanceTo/reset 推进的是"什么都不干"。
  // 从这一步起它是真的粒子世界，那两个方法才第一次有事可做。
  const world = createParticleWorld(timeline, clock.quality);
  const mute = createMuteState(timeline.stems);
  const g = canvas.getContext("2d", { alpha: false });

  let audio = null;
  let hoverLane = null;
  // audio 是个大对象，指纹里不放对象，放"换过几次"的代次号。
  let audioGen = 0;

  /**
   * 只有实时模式跳帧。
   *
   * 离线导出**一个分支都不走**：render.mjs 造的是 mode:"offline" 的实例，
   * 逐帧渲染每帧 t 都不同、本来也不会命中跳帧。写死成"离线永不跳"是为了
   * 让"MP4 不受影响"成为结构性事实而不是概率论断——同理，harness.html
   * （确定性测试用的那份）也是 offline，那几条既有守卫因此原样有效。
   */
  const skipUnchanged = mode === MODE_REALTIME;
  /** 上一帧真正画出来时的指纹。null = 作废，下一帧必须重画。 */
  let lastKey = null;
  let fieldsChecked = false;
  const drawStats = { drawn: 0, skipped: 0 };

  /** 画面指纹：由 FIELD_ROLE 里所有 "key" 角色的字段 + t 组成。 */
  function frameKey(t, geom) {
    return `${t}|${clock.simT}|${hoverLane}|${audioGen}|${geom.W}x${geom.H}@${geom.dpr}`;
  }

  /**
   * 让下一帧无条件重画。
   *
   * **凡是绕过 renderFrame 改动画布内容或几何的地方，都必须叫它一声。**
   * 漏一处的后果是画面卡住不动，不是慢——比多烧 CPU 严重得多。
   * 目前有两处：resize（给 canvas.width 赋值本身就会清空画布，哪怕赋的是
   * 同一个数）与 previewFrame（拖拽预览画的是别的 t，画完之后画布内容
   * 已经跟 lastKey 对不上了）。
   */
  function invalidate() {
    lastKey = null;
  }

  function resize() {
    const geom = computeGeometry(canvas, doc);
    canvas.width = geom.W;
    canvas.height = geom.H;
    invalidate();
  }

  /**
   * 给定 t 画一帧。这是确定性的唯一入口——离线导出也走它。
   *
   * 各层的调用顺序就是叠放顺序，见 LAYERS 上方的注释与 M2 spec 第 7 节。
   */
  function drawAt(t, geom = computeGeometry(canvas, doc)) {
    // 画布尺寸随布局变化时同步过来。加载瞬间 clientWidth 可能是 0
    // （隐藏标签页、布局未完成），此时 resize() 会把画布设成 0×0 且
    // 再也不会恢复——除非恰好触发一次 window resize。实测在预览面板
    // 里就是这个表现：音频在播、时钟在走，画面却是空的。
    if (canvas.width !== geom.W || canvas.height !== geom.H) {
      canvas.width = geom.W;
      canvas.height = geom.H;
    }

    const state = {
      t,
      timeline,
      quality: clock.quality,
      palette: paletteAt(timeline.sections, t),
      geom,
      audio,
      beat: computeBeat(timeline, t),
      world,
      simT: clock.simT,
      // 侧栏悬停高亮。纯交互态，离线导出恒为 null。
      hoverLane,
      doc,
    };

    if (!fieldsChecked) {
      fieldsChecked = true;
      assertFieldsClassified(state);
    }

    g.fillStyle = "#06070d";
    g.fillRect(0, 0, geom.W, geom.H);

    for (const layer of layers) layer.draw(g, state);
    drawStats.drawn++;
  }

  function renderFrame(t) {
    clock.advanceOrRewind(t, world);
    // 时钟推进要在指纹之前算：simT 是指纹的一部分。
    const geom = computeGeometry(canvas, doc);
    const key = frameKey(t, geom);
    if (skipUnchanged && key === lastKey) {
      // 指纹一致 = state 一致 = 画出来必然是同一张图，而画布上现在正是
      // 那张图。**跳过的是"画不画"，不是"画成什么"。**
      drawStats.skipped++;
      return;
    }
    lastKey = key;
    drawAt(t, geom);
  }

  /**
   * 当前帧的哈希。用于确定性比对，不落盘图片。
   *
   * 两个累加器而非一个：单 32 位在一万多帧的比对里碰撞概率虽小但不必
   * 冒这个险，多三行的事。
   */
  function frameHash() {
    const d = g.getImageData(0, 0, canvas.width, canvas.height).data;
    let h1 = 0x811c9dc5;
    let h2 = 0x01000193;
    for (let i = 0; i < d.length; i += 4) {
      h1 = Math.imul(h1 ^ d[i], 0x01000193) >>> 0;
      h2 = Math.imul(h2 ^ (d[i + 1] * 31 + d[i + 2]), 0x85ebca6b) >>> 0;
    }
    return `${h1.toString(16)}-${h2.toString(16)}`;
  }

  return {
    timeline,
    clock,
    mute,
    resize,
    renderFrame,

    /**
     * 只画一帧，不推进也不重放粒子世界。
     *
     * 专供拖拽走带条：每次倒退都从 0 重放整个世界，实测 t=200 处 5.8 ms、
     * t=270 处 7.8 ms，拖拽时每帧一次会吃掉 60fps 预算的三分之一。拖拽中
     * 光屑是空的，松手调 seek 一次性补齐——光屑寿命只有 0.8 秒，松手后
     * 立刻正确，而拖拽中画面本来就在飞速变化。
     */
    previewFrame(t) {
      drawAt(t);
      // 画的是别的 t，画布内容已经跟 lastKey 对不上了。不作废的话，
      // 拖拽后松手若正好落回原来那个 t，指纹一致会被判成"可以跳"，
      // 画布就永远停在预览的那一帧上。
      invalidate();
    },

    frameHash,
    /** 画了多少帧、跳了多少帧。给测试与实测用。 */
    drawStats,
    seek(t) {
      clock.reset(t, world);
    },
    setAudio(a) {
      audio = a;
      audioGen++;
    },
    setHoverLane(id) {
      hoverLane = id;
    },
  };
}

/** 浏览器入口。测试页不走这里，它直接调 createApp。 */
async function boot() {
  const canvas = document.getElementById("cv");
  const uiRoot = document.getElementById("mr-ui");

  const app = createApp({
    doc: document,
    canvas,
    timelineDoc: window.__MR_TIMELINE__,
    mode: MODE_REALTIME,
  });
  app.resize();
  window.addEventListener("resize", () => app.resize());
  window.__murRipple = app;

  const title = createTitle(document, uiRoot, {
    title: window.__MR_TITLE__ ?? app.timeline.meta.title,
    duration: app.timeline.meta.duration,
    bpm: app.timeline.meta.bpm,
    lanes: app.timeline.lanes,
    onStart: start,
  });

  // 跨次重试复用同一个 AudioContext。每次重试都新建且从不 close，连续
  // 失败几次就会撞上浏览器的并发上限，那时抛出的是构造失败，把真正的
  // 解码原因盖掉——而标题页存在的理由正是显示可执行的错误信息。
  let ctx = null;
  // 解码后的各条分轨，导出混音时要用
  let decoded = null;

  async function start() {
    let player;
    try {
      ctx ??= new (window.AudioContext || window.webkitAudioContext)();
      const buffers = {};
      for (const stem of app.timeline.stems) {
        const uri = window.__MR_AUDIO__[stem];
        if (!uri) continue;
        buffers[stem] = await ctx.decodeAudioData(dataUriToArrayBuffer(uri));
      }
      // 曲长交给播放器，它才知道什么时候算"放完了"。见 audio.js 顶部
      // 关于"为什么用 meta.duration 而不是 buffer 自己的 duration"。
      player = createPlayer(ctx, buffers, app.timeline.meta.duration);
      decoded = buffers;
      player.start(0);
      app.setAudio(mixToMono(buffers));
    } catch (err) {
      title.fail(`音频解码失败：${err.message}`);
      return;
    }
    title.close();

    // 拖拽中的时间。非 null 时主循环画它而不是 player.currentTime()——
    // 拖拽时音频是暂停的，currentTime 会停在按下的那一刻。
    let scrubT = null;
    // 按下走带条时的播放状态，松手时用来决定要不要续播
    let wasPlaying = null;

    function togglePlay() {
      // player.playing 是"此刻真的有声音"，不是"用户按过播放"。曲子放完
      // 之后它是 false，于是这里走 else 分支——而 resumeFrom 在放完的情况
      // 下给的是 0，从头再放一遍。写成 player.currentTime() 的话等于从结尾
      // 起播，用户按了播放却一点声音都没有。
      if (player.playing) player.pause();
      else player.start(resumeFrom(player));
    }

    /**
     * 界面显隐是**手动**的，不做闲置自动淡出。
     *
     * 收起后必须留一条回来的路：H 键之外还要能点画面任意处恢复——触屏
     * 上没有键盘，只留快捷键等于把人锁在外面。收起状态下 #mr-ui 的子元素
     * pointer-events 是 none，点击直接落到 document 上，不会误触到控件。
     */
    function setUiHidden(hidden) {
      uiRoot.classList.toggle("mr-hidden", hidden);
    }
    document.addEventListener("pointerdown", () => {
      if (uiRoot.classList.contains("mr-hidden")) setUiHidden(false);
    });

    document.addEventListener("keydown", (ev) => {
      if (ev.code === "KeyH") {
        ev.preventDefault();
        setUiHidden(!uiRoot.classList.contains("mr-hidden"));
        return;
      }
      if (ev.code !== "Space") return;
      // 空格**永远**是播放/暂停，这是播放器的通用约定。
      //
      // 原先的判据是"焦点不在 document.body 上就让路"。点击会让按钮取得
      // 焦点，于是"点过静音钮之后按空格"切的是静音而不是播放——用户想
      // 暂停，得到的是取消静音。
      //
      // 只是让全局处理器让路还不够：浏览器照样会用空格激活那个焦点控件。
      // preventDefault 一并挡掉（同时也挡掉页面滚动）。
      ev.preventDefault();
      togglePlay();
    });

    const hud = createHud(document, document.getElementById("mr-ui"), {
      duration: app.timeline.meta.duration,
      sections: app.timeline.sections,
      title: window.__MR_TITLE__ ?? app.timeline.meta.title,
      onTogglePlay: togglePlay,
      onScrub: (t) => {
        // 记住按下时在不在播：松手后只在原本就在播时续播。无条件 start
        // 会让"暂停中点走带条挪个位置"变成强制开始播放。
        //
        // **两行必须看同一个状态**，都看 running（用户的播放意图），不看
        // playing（此刻有没有声音）。只有放完之后两者才会不一致，而那正是
        // 出事的地方：曲子放完时 running 仍是 true 而 playing 是 false，
        // 若这里按 playing 判断就不会暂停，于是 running 一直挂着——松手时
        // player.seek() 看见 running 自己先起播了一次，下面那行 start() 又
        // 起了第二次，同一次拖拽把所有分轨停掉重起两遍。
        //
        // 这处不一致是变异检验逼出来的：把上一行改回 player.playing 时
        // 全部测试仍然全绿，因为 seek() 内部那次起播把差异盖住了。两行
        // 统一之后那个变异才会真的变红。
        if (wasPlaying === null) wasPlaying = player.running;
        if (player.running) player.pause();
        scrubT = t;
        app.previewFrame(t);
      },
      onScrubEnd: (t) => {
        scrubT = null;
        // 不必在这里 app.seek(t)：scrubT 一清空，下一帧主循环就走
        // renderFrame，advanceOrRewind 该重放的自会重放。多调一次等于
        // 白付一次全量重放（t=270 处约 7.8 ms）。
        player.seek(t);
        if (wasPlaying) player.start(t);
        wasPlaying = null;
      },
      onVolume: (v) => player.setVolume(v),
      onHide: () => setUiHidden(true),
      onExport: async () => {
        const Offline = window.OfflineAudioContext || window.webkitOfflineAudioContext;
        const { buffer } = await renderMixdown(decoded, (s) => app.mute.gainFor(s), Offline);
        const url = URL.createObjectURL(new Blob([buffer], { type: "audio/wav" }));
        const a = document.createElement("a");
        a.href = url;
        const muted = app.timeline.stems.filter((s) => app.mute.isMuted(s));
        // 文件名带上静音了哪几轨——导出好几版之后光看文件名要能分得清
        a.download = `${window.__MR_TITLE__ ?? "murRipple"}${
          muted.length ? `-无${muted.join("无")}` : ""
        }.wav`;
        a.click();
        // 立刻撤销会让下载拿不到数据，等一拍
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      },
    });

    createTitleCard(document, uiRoot, {
      title: window.__MR_TITLE__ ?? app.timeline.meta.title,
      duration: app.timeline.meta.duration,
      bpm: app.timeline.meta.bpm,
    });

    const voices = createVoices(document, document.getElementById("mr-ui"), {
      lanes: app.timeline.lanes,
      ring: app.timeline.ring,
      mute: app.mute,
      onToggle: (stem) => {
        app.mute.toggle(stem);
        player.applyMute(app.mute);
        voices.syncMute();
      },
      onHover: (id) => app.setHoverLane(id),
    });

    const loop = () => {
      const t = scrubT ?? player.currentTime();
      // 拖拽中只画不推进世界。写成无条件 renderFrame 的话，previewFrame
      // 画出的那一帧当帧就被这里覆盖，等于从来没生效过——而每次倒退都是
      // 一次从 0 开始的全量重放，实测拖一次触发 6 次。
      if (scrubT !== null) app.previewFrame(t);
      else app.renderFrame(t);
      hud.update(t, player.playing);
      voices.update(t);
      requestAnimationFrame(loop);
    };
    loop();
  }
}

// 判据是注入的数据而不是某个 DOM 元素：测试页也有 #mr-ui，用它当判据
// 会让 boot 在测试页里跑起来，拿不到 __MR_TIMELINE__ 就抛错。
if (typeof window !== "undefined" && window.__MR_TIMELINE__) {
  boot();
}
