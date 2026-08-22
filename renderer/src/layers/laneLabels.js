/**
 * 声部铭文：把每条轨道的名字画在它那道弧的外侧。
 *
 * **为什么要进 canvas 而不是只留在侧栏**：导出的视频里没有侧栏——界面是
 * DOM 覆盖层，不进画面。观众看视频时根本不知道那几道弧各是什么。铭文进
 * canvas，视频里才有名字。
 *
 * 名字从 ui/voices.js 的 LABELS 表复用：一处定义，侧栏、标题页、铭文三处
 * 共用，改名字只改一个地方。轨道数从 timeline.lanes 读，真歌六条、合成
 * 曲八条都按实际条数画。
 */

import { sampleAt } from "../core/timeline.js";
import { laneAngle } from "../core/notes.js";
import { OUTER_RATIO } from "../core/geometry.js";
import { LABELS } from "../ui/voices.js";

/** 铭文所在的半径，相对 R。贴在弧外一点点。 */
const LABEL_RATIO = OUTER_RATIO * 1.12;
const FONT_STACK = '"Songti SC","STSong",serif';

export const NAME = "laneLabels";

/**
 * 单条 lane 的铭文文本。与 ui/voices.js 的 buildVoiceRows 同一套兜底
 * （`LABELS[id]?.zh ?? label`）：LABELS 表查不到就退回 lane.label，不能
 * 返回空值让下面 `if (!label) return` 把这条轨道从画布上悄悄抹掉——面板
 * 现在按 timeline.lanes 全量显示每一条，画布必须画出同样多条，两边不能
 * 静默分叉（评审 2026-08-14 指出：boot-harness-nine.html 的
 * drums/other/chime 三个 lane id 不在 LABELS 表里，此前会导致 9 行面板
 * 只有 5 段环外小字）。
 */
export function labelFor(lane) {
  return LABELS[lane.id]?.zh ?? lane.label;
}

export function draw(g, state) {
  const { timeline, palette, geom, t } = state;
  if (geom.W === 0) return;

  const n = timeline.lanes.length;
  const fontPx = Math.max(9, Math.min(geom.W, geom.H) * 0.0135);
  const r = geom.R * LABEL_RATIO;

  g.save();
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.font = `${fontPx}px ${FONT_STACK}`;

  timeline.lanes.forEach((lane, i) => {
    const label = labelFor(lane);
    if (!label) return;

    // 亮度随该轨能量：安静的轨道名字淡下去，正在响的浮上来
    const v = Math.min(1, (sampleAt(lane.envSmooth, t) / 255) * lane.gain);
    const hue = (lane.hue + palette.hueShift) % 360;
    const ang = laneAngle(i, n);

    g.globalAlpha = 0.3 + v * 0.55;
    g.fillStyle = `hsl(${hue} 70% 78%)`;
    // 字距靠逐字画：canvas 没有 letter-spacing
    const chars = [...label];
    const gap = fontPx * 0.22;
    const widths = chars.map((c) => g.measureText(c).width);
    const total = widths.reduce((a, b) => a + b, 0) + gap * (chars.length - 1);
    let x = geom.cx + Math.cos(ang) * r - total / 2;
    const y = geom.cy + Math.sin(ang) * r;
    for (let k = 0; k < chars.length; k++) {
      g.fillText(chars[k], x + widths[k] / 2, y);
      x += widths[k] + gap;
    }
  });

  g.restore();
}
