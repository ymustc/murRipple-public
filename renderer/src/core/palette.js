/**
 * 段落配色。
 *
 * 段落名默认为空串（见 M2 spec 第 2 节：原来的名字是借来的，已移除），
 * 所以段落结构只能靠颜色传达——这一层因此比看上去重要。
 */

import { sectionIndexAt } from "./timeline.js";

/** 每段旋转的角度。与 360 互质，段落再多也不会提前撞色。 */
export const HUE_STEP = 37;

const SAT_MIN = 45;
const SAT_RANGE = 40;

/** 返回 t 处的配色。同一段落内恒定，不随 t 漂移。 */
export function paletteAt(sections, t) {
  const index = sectionIndexAt(sections, t);
  const energy = sections[index].energy;
  return {
    index,
    hueShift: (index * HUE_STEP) % 360,
    sat: SAT_MIN + energy * SAT_RANGE,
    energy,
  };
}
