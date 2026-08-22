/**
 * 走带条：进度、段落刻度、时间、音量。
 *
 * 是 DOM 而不是 canvas 图层。M3 逐帧抓 canvas 导出，画进 canvas 的界面
 * 元素会被烤进每一帧视频里；DOM 覆盖层让导出天然干净，零额外代价。
 * 顺带白得文本渲染、命中测试、光标样式。
 */

import { sectionIndexAt } from "../core/timeline.js";

/** m:ss。时长上限按单曲算，不做小时位。 */
function fmt(sec) {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function createHud(doc, root, opts) {
  const {
    duration,
    sections,
    title = "",
    onTogglePlay,
    onScrub,
    onScrubEnd,
    onVolume,
    onHide,
    onExport,
  } = opts;

  const el = doc.createElement("div");
  el.id = "mr-hud";
  // 居中的圆角卡片，不是横贯全屏的细条：细条把画面下沿整个切掉一道，
  // 而这幅画是圆的，两侧本来就空着。卡片只占中间，画面呼吸得开。
  el.innerHTML = `
    <div id="mr-hud-row">
      <span id="mr-section"><b></b><em></em></span>
      <span id="mr-time">0:00 / ${fmt(duration)}</span>
      <button id="mr-play" type="button" aria-label="播放/暂停">▶</button>
      <button id="mr-mix" type="button" title="按当前静音状态导出混音 WAV">⇩ 混音</button>
      <a id="mr-download" download="" title="下载这个页面">⤓ 下载</a>
      <input id="mr-vol" type="range" min="0" max="100" value="100"
             aria-label="音量">
      <button id="mr-hide" type="button" aria-label="收起界面（H）"
              title="收起界面（H）">⌄</button>
    </div>
    <div id="mr-bar" role="slider" aria-label="进度"
         aria-valuemin="0" aria-valuemax="${Math.round(duration)}">
      <div id="mr-ticks"></div>
      <div id="mr-fill"></div>
      <div id="mr-knob"></div>
    </div>
  `;
  root.appendChild(el);

  const bar = el.querySelector("#mr-bar");
  const fill = el.querySelector("#mr-fill");
  const knob = el.querySelector("#mr-knob");
  const time = el.querySelector("#mr-time");
  const play = el.querySelector("#mr-play");

  // 段落刻度。sections[0].t 恒为 0，那是起点不是分界，不画。
  const ticks = el.querySelector("#mr-ticks");
  for (const s of sections) {
    if (s.t <= 0 || s.t >= duration) continue;
    const d = doc.createElement("i");
    d.style.left = `${(s.t / duration) * 100}%`;
    ticks.appendChild(d);
  }

  /** 事件坐标 → 秒。钳到 [0, duration]，拖出条外也不会算出负数。 */
  function timeAt(ev) {
    const r = bar.getBoundingClientRect();
    const f = r.width > 0 ? (ev.clientX - r.left) / r.width : 0;
    return Math.max(0, Math.min(1, f)) * duration;
  }

  let dragging = false;

  /**
   * 收尾：一定要把 dragging 复位并落定。
   *
   * 释放捕获放在 try 里、回调放在 finally：releasePointerCapture 对已失效
   * 的 pointerId 会抛 NotFoundError，排在回调前面的话一抛就再也落定不了，
   * 掉进下面说的那个卡死状态。
   */
  function endDrag(ev) {
    if (!dragging) return;
    dragging = false;
    try {
      bar.releasePointerCapture(ev.pointerId);
    } catch {
      /* 捕获已失效，无所谓 */
    } finally {
      onScrubEnd(timeAt(ev));
    }
  }

  bar.addEventListener("pointerdown", (ev) => {
    dragging = true;
    try {
      bar.setPointerCapture(ev.pointerId);
    } catch {
      // 拿不到捕获也照样能拖，只是划出元素外就收不到 move 了。
      // 不能让它把整个 pointerdown 掀翻——那样连 onScrub 都不会执行。
    }
    onScrub(timeAt(ev));
  });
  bar.addEventListener("pointermove", (ev) => {
    if (dragging) onScrub(timeAt(ev));
  });
  bar.addEventListener("pointerup", endDrag);
  // pointercancel / lostpointercapture 必须走同一条收尾路径。
  //
  // 只听 pointerup 时，拖拽被系统打断（触摸被滚动接管、切窗口、设备旋转）
  // 会让 dragging 与调用方的 scrubT 一起永久卡住：画面冻结在按下的那一刻，
  // 按空格音频照走而画面不动，而且此后**鼠标只要划过走带条**（一个键都没
  // 按）就会触发 onScrub 暂停音频并跳时间。
  bar.addEventListener("pointercancel", endDrag);
  bar.addEventListener("lostpointercapture", endDrag);
  // 点击（按下即抬起）走的也是这条路：pointerdown 预览、pointerup 落定。
  // 单独再挂 click 会让一次点击跳转两次。

  el.querySelector("#mr-vol").addEventListener("input", (ev) => {
    onVolume(Number(ev.target.value) / 100);
  });
  play.addEventListener("click", () => onTogglePlay());
  el.querySelector("#mr-hide").addEventListener("click", () => onHide());

  const mix = el.querySelector("#mr-mix");
  mix.addEventListener("click", async () => {
    // 渲染要几秒，按钮必须给反馈——否则用户会以为没点上、连点好几次
    mix.disabled = true;
    const label = mix.textContent;
    mix.textContent = "导出中…";
    try {
      await onExport();
    } finally {
      mix.disabled = false;
      mix.textContent = label;
    }
  });

  // 下载：产物是自包含单文件，"下载"就是把这个文件本身存下来——挂在
  // Pages 上的人点一下就能带走离线看。参考项目导出的是它现场合成的 WAV，
  // 那对我们没有意义：音频本来就是用户自己的文件（M1 spec 第 18 节）。
  //
  // file:// 下浏览器会拒绝下载同源文件，此时**藏起按钮**而不是让它点了
  // 没反应——本地双击打开的人手上已经有这个文件了，本就不需要它。
  const dl = el.querySelector("#mr-download");
  if (doc.defaultView?.location?.protocol === "file:") {
    dl.style.display = "none";
  } else {
    dl.href = doc.defaultView.location.href;
    dl.download = `${title || "murRipple"}.html`;
  }

  // 上一次真正写进 DOM 的值。每帧无条件写会让浏览器每帧重排——时间显示
  // 每秒才变一次，进度条以像素为粒度，挡掉之后写入不到十分之一。
  const sectionEl = el.querySelector("#mr-section");
  let lastPct = -1;
  let lastSec = -1;
  let lastPlaying = null;
  let lastSection = -1;

  return {
    el,

    update(rawT, playing) {
      // 走带条上的一切都按钳过的 t 走，越过结尾就停在总时长上。
      //
      // 传进来的 t 是 player.currentTime()，而那是
      // `ctx.currentTime - startedAt + offset`——音频缓冲播完之后 playing
      // 仍是 true，这个差值就一路涨下去不回头。实测 4:31 的曲子播到结尾，
      // 计时器继续跳到 4:44 还在涨。**自然从头播到尾与先跳到接近结尾再播
      // 过去，成因是同一个**：offset 只决定起点，越界与怎么到的无关。
      //
      // 原先只有进度百分比钳了（fill/knob 停在 100%），时间文本与
      // aria-valuenow 直接用生的 t——于是把手停着、数字还在走，同一条
      // 走带条自己跟自己打架，aria-valuenow 还会越过 aria-valuemax。
      //
      // 钳在这里而不是钳 player.currentTime()：越界的是"显示"，播放器
      // 报告自己起播至今走了多久并没有错，改它会连带影响暂停/续播的
      // offset 语义。离线导出不经过 hud（video/render.mjs 只抓 canvas，
      // 自己造 mode:"offline" 的实例），这条改动碰不到 MP4 那条路。
      const t = duration > 0 ? Math.max(0, Math.min(duration, rawT)) : Math.max(0, rawT);
      const pct = duration > 0 ? t / duration : 0;
      const rounded = Math.round(pct * 1000) / 10;
      if (rounded !== lastPct) {
        lastPct = rounded;
        fill.style.width = `${rounded}%`;
        knob.style.left = `${rounded}%`;
        bar.setAttribute("aria-valuenow", String(Math.round(t)));
      }
      const sec = Math.floor(t);
      if (sec !== lastSec) {
        lastSec = sec;
        time.textContent = `${fmt(t)} / ${fmt(duration)}`;
      }
      if (playing !== lastPlaying) {
        lastPlaying = playing;
        play.textContent = playing ? "❚❚" : "▶";
      }
      // 段落名：换段光扫说明"换了"，这里说明"换到哪了"，两者配套
      const si = sectionIndexAt(sections, t);
      if (si !== lastSection) {
        lastSection = si;
        const name = sections[si]?.name ?? "";
        sectionEl.querySelector("b").textContent = name;
        sectionEl.querySelector("em").textContent = name ? `第 ${si + 1} 段` : "";
      }
    },

    destroy() {
      el.remove();
    },
  };
}
