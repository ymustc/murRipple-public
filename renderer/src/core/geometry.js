/**
 * 画布尺寸 → 绘制几何。
 *
 * 单独拆出来是因为每一层都要用同一套坐标，而且这段逻辑在 M2-1 里是
 * 内联在 renderFrame 里的——图层化之后必须共享，否则各层各算一套，
 * 改个半径要改五个地方。
 *
 * 所有半径一律以 R 为单位表达，常量集中在这里。各层不得自己定半径。
 */

const MAX_DPR = 2;

/**
 * 判定环 / 车道弧的半径，占短边的比例。
 *
 * M2-4 之前取 0.28，且车道弧还在 1.6R 上——合短边的 0.45，实心结构几乎
 * 顶到画幅，谱线只能往里画，环内被填满，整体又满又钝。
 *
 * 新方案让实心结构只占 0.225，靠**向外发散**的谱线撑出 0.43 的轮廓：
 * 骨架细、轮廓大，这才是纤细灵动的来源。
 */
const R_RATIO = 0.225;

/**
 * 圆心的纵向位置。
 *
 * 略高于几何中心：底部要放走带条，正中会让画面显得下坠。
 */
const CY_RATIO = 0.485;

/**
 * 各层半径，自内向外，互不重叠。
 *
 * 参考项目只有一圈弧（车道弧即落点环），我们多一圈判定环——人声在场时
 * 点亮，是歌词光核的边界。两者若同在 1.0R 会叠成一团（实测第一版就是
 * 这样），所以判定环让到 0.90，车道弧占最外的实心位。
 */
export const WAVE_RATIO = 0.55;
export const DIAL_IN_RATIO = 0.8;
export const RING_RATIO = 0.9;
/** 车道弧 = 音符落点环，实心结构的最外沿。 */
export const OUTER_RATIO = 1.0;
export const DIAL_OUT_RATIO = 1.06;
/** 谱线自这里向外发散。 */
export const SPECTRUM_BASE_RATIO = 1.02;
/** 谱线最长伸到（R 的倍数）。 */
export const SPECTRUM_MAX_RATIO = 1.95;
/** 音符自这个半径开始下落。 */
export const NOTE_START_RATIO = 1.95;

export function computeGeometry(canvas, doc) {
  const dpr = Math.min(MAX_DPR, doc.defaultView?.devicePixelRatio || 1);
  const W = Math.round(canvas.clientWidth * dpr);
  const H = Math.round(canvas.clientHeight * dpr);
  const short = Math.min(W, H);
  return {
    W,
    H,
    dpr,
    cx: W / 2,
    cy: H * CY_RATIO,
    R: short * R_RATIO,
  };
}
