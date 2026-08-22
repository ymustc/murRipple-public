/**
 * 小节涟漪：每到一条小节线，从中心弹开一圈极淡的环。
 *
 * **写成 t 的纯函数，不维护数组。** 参考实现是 `ripples.push(...)` 逐帧
 * 累积再 filter 的；那在逐帧导出下不可复现——跳到第 200 秒直接渲染，
 * 数组里什么都没有，涟漪就消失了。
 *
 * 小节线在 `timeline.downbeats` 里是已知的，所以给定 t 反查"最近 0.72
 * 秒内有哪几条"即可，画面完全一样，而且怎么跳帧都对得上。
 */

/** 起始半径（R 的倍数）。 */
const START_RATIO = 0.18;
/** 扩散速度，像素/秒（按短边 720 的画面标定）。 */
const SPEED_PX = 300;
const ALPHA0 = 0.16;
/** 透明度衰减速率：1/1.4 ≈ 0.714 秒后归零。 */
const FADE_RATE = 1.4;
export const LIFE_SEC = 1 / FADE_RATE;

export const NAME = "ripple";

/** 第一个 > x 的下标。 */
function upperBound(arr, x) {
  let lo = 0;
  let hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] <= x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/**
 * t 时刻仍在场的涟漪。返回按小节线时刻升序。
 *
 * 区间取 `(t - life, t]`：恰好到寿命的那一圈 alpha 已经是 0，画不画都
 * 一样，但排除掉能少一次描边。
 */
export function activeRipples(downbeats, t, life = LIFE_SEC) {
  const out = [];
  let i = upperBound(downbeats, t - life);
  while (i < downbeats.length && downbeats[i] <= t) {
    const age = t - downbeats[i];
    out.push({
      t0: downbeats[i],
      age,
      alpha: Math.max(0, ALPHA0 * (1 - age * FADE_RATE)),
    });
    i++;
  }
  return out;
}

export function draw(g, state) {
  const { geom, palette, timeline, t } = state;
  if (geom.W === 0) return;

  const hue = (palette.hueShift + 200) % 360;
  // 速度按短边缩放，窄窗口里涟漪才不会一闪就出界
  const speed = SPEED_PX * (Math.min(geom.W, geom.H) / 720);
  const start = geom.R * START_RATIO;
  const maxR = Math.max(geom.W, geom.H);

  g.save();
  g.lineWidth = 1 * geom.dpr;
  for (const rp of activeRipples(timeline.downbeats, t)) {
    const r = start + rp.age * speed;
    if (r > maxR) continue;
    g.strokeStyle = `hsla(${hue} 80% 70% / ${rp.alpha})`;
    g.beginPath();
    g.arc(geom.cx, geom.cy, r, 0, Math.PI * 2);
    g.stroke();
  }
  g.restore();
}
