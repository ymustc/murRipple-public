/**
 * 标题页。
 *
 * 布局照参考项目的形制：一圈细环，声部名沿环排布，中心一团光球，曲名与
 * 元信息压在环内，播放钮落在环下缘。它同时是错误出口——音频解码失败时
 * 必须在这里显示可执行的信息，不能静默卡在"载入中"（M2 spec 第 11 节）。
 *
 * 是 DOM 而不是 canvas：标题页在 canvas 之外，M3 导出时它本来就不该在。
 */

import { buildVoiceRows } from "./voices.js";

function fmt(sec) {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * `lanes` 默认空数组：调用方没传时（既有 ui.test.mjs 的两条 createTitle
 * 测试只关心曲名/失败流程，不关心环上的名字）仍只画心籁一行，不炸。真正
 * 的启动路径（main.js boot()）会传 app.timeline.lanes。
 */
export function createTitle(doc, root, { title, duration, bpm, onStart, lanes = [] }) {
  const el = doc.createElement("div");
  el.id = "mr-title";
  el.innerHTML = `
    <div id="mr-t-stage">
      <i id="mr-t-orb"></i>
      <i id="mr-t-ring"></i>
      <div id="mr-t-names"></div>
      <div id="mr-t-body">
        <h1></h1>
        <p id="mr-t-sub">murRipple</p>
        <p id="mr-t-meta"></p>
        <button id="mr-start" type="button">▶</button>
      </div>
    </div>
    <p id="mr-t-hint">空格 暂停 / 继续 · 点右侧声部可静音 · 点进度条跳转 · H 收起界面</p>
    <p id="mr-t-msg" role="status"></p>
    <p id="mr-t-credit">知漪 · murRipple</p>
  `;
  // textContent 而不是拼进 innerHTML：曲名是用户给的，拼字符串会让带
  // 尖括号的名字破坏页面结构。
  el.querySelector("h1").textContent = title;
  el.querySelector("#mr-t-meta").textContent = `${
    bpm ? `${Math.round(bpm)} BPM · ` : ""
  }${fmt(duration)}`;

  // 声部名沿环排布。自正上方起算，与画面里车道弧的排布同向。行数与声部
  // 面板一致：1 + lanes.length（真歌 7、合成曲 9），不再写死七个。
  const names = el.querySelector("#mr-t-names");
  const voiceRows = buildVoiceRows({ lanes });
  voiceRows.forEach((v, i) => {
    const a = -Math.PI / 2 + (i / voiceRows.length) * Math.PI * 2;
    const tag = doc.createElement("i");
    tag.textContent = v.zh;
    // 50% 是环心，46% 是环半径——名字贴在环外一点点
    tag.style.left = `${50 + Math.cos(a) * 46}%`;
    tag.style.top = `${50 + Math.sin(a) * 46}%`;
    names.appendChild(tag);
  });

  root.appendChild(el);

  const msg = el.querySelector("#mr-t-msg");
  const btn = el.querySelector("#mr-start");
  btn.addEventListener("click", () => {
    btn.disabled = true;
    msg.textContent = "解码中…";
    onStart();
  });

  return {
    el,

    /** 解码失败：留在标题页，把可执行的信息显示出来，并允许重试。 */
    fail(text) {
      msg.textContent = text;
      btn.disabled = false;
      btn.textContent = "重试";
    },

    close() {
      el.remove();
    },
  };
}
