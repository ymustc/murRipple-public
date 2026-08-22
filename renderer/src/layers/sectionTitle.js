/**
 * 段落大字。
 *
 * M2-3 时推迟到了 M3：那时 `sections[].name` 恒为空串（原来那组名字是借
 * 来的，已清空），做了也是一层永远不显示的死代码。overrides.json 落地
 * 之后它才有内容可显示。
 *
 * **名字为空的段落不显示。** 绝大多数歌不会去写名字，不能让它们看到一个
 * 空框或者一片突然亮起的空白。
 *
 * 是 `t` 的纯函数：由 `sections[].t` 反查当前段落与它开始了多久。
 */

import { sectionIndexAt } from "../core/timeline.js";
import { OUTER_RATIO, SPECTRUM_MAX_RATIO } from "../core/geometry.js";

const FADE_IN = 0.5;
const HOLD = 2.2;
const FADE_OUT = 0.8;
export const SHOW_SEC = FADE_IN + HOLD + FADE_OUT;

const FONT_STACK = '"Songti SC","STSong",serif';

export const NAME = "sectionTitle";

/**
 * 段落开始 age 秒后的不透明度。淡入 → 停留 → 淡出，之后恒为 0。
 *
 * 单独导出是为了能在 Node 里测——它是这一层唯一有逻辑的部分。
 */
export function fadeAt(age) {
  if (age < 0 || age >= SHOW_SEC) return 0;
  if (age < FADE_IN) return age / FADE_IN;
  if (age < FADE_IN + HOLD) return 1;
  return 1 - (age - FADE_IN - HOLD) / FADE_OUT;
}

export function draw(g, state) {
  const { timeline, palette, geom, t } = state;
  if (geom.W === 0) return;

  const i = sectionIndexAt(timeline.sections, t);
  const sec = timeline.sections[i];
  // 没写名字就不显示——绝大多数歌都是这种情况
  if (!sec || !sec.name) return;

  const alpha = fadeAt(t - sec.t);
  if (alpha <= 0) return;

  const hue = (palette.hueShift + 200) % 360;
  const fontPx = Math.min(geom.W, geom.H) * 0.042;
  // 放在谱线冠形之外的下方，避开歌词与环
  const y = geom.cy + geom.R * (OUTER_RATIO + SPECTRUM_MAX_RATIO) * 0.52 + fontPx;

  g.save();
  g.globalCompositeOperation = "lighter";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.font = `300 ${fontPx}px ${FONT_STACK}`;
  // 淡入时略微上浮，比单纯改透明度活一点
  const lift = (1 - alpha) * fontPx * 0.35;
  g.globalAlpha = alpha * 0.85;
  g.fillStyle = `hsl(${hue} ${palette.sat}% 78%)`;
  // 字距靠逐字画出来：canvas 没有 letter-spacing
  const chars = [...sec.name];
  const gap = fontPx * 0.28;
  const widths = chars.map((c) => g.measureText(c).width);
  const total = widths.reduce((a, b) => a + b, 0) + gap * (chars.length - 1);
  let x = geom.cx - total / 2;
  for (let k = 0; k < chars.length; k++) {
    g.fillText(chars[k], x + widths[k] / 2, y + lift);
    x += widths[k] + gap;
  }
  g.restore();
}
