/**
 * 拍点脉冲。
 *
 * 531 个拍点与 133 条小节线在 M2-1 里一个都没被用上。加上之后画面会
 * 跟着节奏活起来——静态截图看不出、一播放就明显。
 *
 * 必须是 t 的纯函数：不能在 draw 里累积衰减状态，否则 seek 之后与离线
 * 渲染不一致（M2 spec 第 6 节铁则二）。
 */

/** 二分找最后一个不晚于 t 的元素下标；没有则返回 -1。 */
function lastNotAfter(sorted, t) {
  let lo = 0;
  let hi = sorted.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (sorted[mid] <= t) {
      ans = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return ans;
}

/**
 * t 处的脉冲强度，0–1。刚过一个拍点时为 1，之后按指数衰减。
 *
 * 用"最近的、不晚于 t 的拍点"而非相位取模——真实曲目的拍点网格有偏移
 * （首曲从 1.776 秒起），取模会整体错位。
 */
export function pulseAt(times, t, tauMs = 140) {
  if (!times.length) return 0;
  const i = lastNotAfter(times, t);
  if (i < 0) return 0;
  return Math.exp(-((t - times[i]) * 1000) / tauMs);
}

/** 一次算好拍点与小节线两种脉冲，供各层共用。 */
export function computeBeat(timeline, t) {
  return {
    pulse: pulseAt(timeline.beats, t),
    downPulse: pulseAt(timeline.downbeats, t, 260),
  };
}
