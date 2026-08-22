/**
 * 左上角标题卡：曲名 + 一行元信息。
 *
 * 标题页点进去之后曲名就消失了，看视频或截图的人无从知道这是哪首歌。
 * 一张小卡片常驻左上，代价极小。
 *
 * 与 hud 一样是 DOM 覆盖层——它不该出现在导出的视频里，视频有自己的
 * 片头（标题页）。
 */

export function createTitleCard(doc, root, { title, duration, bpm }) {
  const el = doc.createElement("div");
  el.id = "mr-titlecard";
  el.innerHTML = `<b></b><em></em>`;
  // textContent 而不是拼进 innerHTML：曲名是用户给的
  el.querySelector("b").textContent = title;
  const s = Math.max(0, Math.floor(duration));
  el.querySelector("em").textContent =
    `murRipple · ${bpm ? `${Math.round(bpm)} BPM · ` : ""}` +
    `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  root.appendChild(el);
  return {
    el,
    destroy() {
      el.remove();
    },
  };
}
