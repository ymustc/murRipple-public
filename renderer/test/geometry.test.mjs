import test from "node:test";
import assert from "node:assert/strict";
import {
  computeGeometry,
  OUTER_RATIO,
  SPECTRUM_MAX_RATIO,
} from "../src/core/geometry.js";

/** 假 canvas 与 document，避开 DOM。 */
function fake(clientW, clientH, dpr = 1) {
  return {
    canvas: { clientWidth: clientW, clientHeight: clientH, width: 0, height: 0 },
    doc: { defaultView: { devicePixelRatio: dpr } },
  };
}

test("按 dpr 放大画布像素尺寸", () => {
  const { canvas, doc } = fake(800, 450, 2);
  const g = computeGeometry(canvas, doc);
  assert.equal(g.W, 1600);
  assert.equal(g.H, 900);
  assert.equal(g.dpr, 2);
});

test("dpr 上限为 2——再高只是烧显存，肉眼看不出", () => {
  const { canvas, doc } = fake(800, 450, 4);
  const g = computeGeometry(canvas, doc);
  assert.equal(g.dpr, 2);
  // 只断言 dpr 字段被封顶是不够的：字段封顶、W/H 仍用原始 dpr 计算的
  // 实现同样能通过，而那正好把 MAX_DPR 限制像素成本的本意完全架空。
  assert.equal(g.W, 1600, "W 必须用封顶后的 dpr 算，而不只是 dpr 字段被封顶");
  assert.equal(g.H, 900, "H 同上");
});

test("圆心横向居中，纵向略高", () => {
  const { canvas, doc } = fake(800, 450);
  const g = computeGeometry(canvas, doc);
  assert.equal(g.cx, 400);
  assert.equal(g.cy, 450 * 0.485, "底部要放走带条，正中会让画面显得下坠");
});

test("半径取短边，保证竖屏横屏都不出界", () => {
  const wide = computeGeometry(...Object.values(fake(1600, 400)));
  const tall = computeGeometry(...Object.values(fake(400, 1600)));
  assert.equal(wide.R, tall.R, "长短边互换后半径应相同");
  assert.ok(
    wide.R * SPECTRUM_MAX_RATIO < 400 / 2,
    "含谱线在内的最外沿不得超出短边一半",
  );
  assert.equal(
    wide.R,
    400 * 0.225,
    "R 占短边的比例是本期的核心决定，改它等于改整个画面的尺度",
  );
});

test("零尺寸画布不抛错，返回零几何", () => {
  const g = computeGeometry(...Object.values(fake(0, 0)));
  assert.equal(g.W, 0);
  assert.equal(g.R, 0);
});

test("车道弧只占短边的 22.5% 左右", () => {
  // 本期的要害。实心结构做大了就笨——M2-4 之前车道弧在短边的 45%，
  // 几乎顶到画幅。靠向外发散的谱线撑轮廓，骨架本身要细。
  const { canvas, doc } = fake(1280, 720);
  const geom = computeGeometry(canvas, doc);
  const frac = (geom.R * OUTER_RATIO) / Math.min(geom.W, geom.H);
  assert.ok(
    Math.abs(frac - 0.225) < 0.02,
    `车道弧应在短边的 22.5% 附近，实得 ${(frac * 100).toFixed(1)}%`,
  );
});

test("整套结构的最外沿落在短边的 43% 附近，不顶到画面边缘", () => {
  const { canvas, doc } = fake(1280, 720);
  const geom = computeGeometry(canvas, doc);
  const frac =
    (geom.R * SPECTRUM_MAX_RATIO) / Math.min(geom.W, geom.H);
  assert.ok(
    frac > 0.4 && frac < 0.46,
    `最外沿应在短边的 40%–46%，实得 ${(frac * 100).toFixed(1)}%——` +
      `太小则空旷，太大则顶到画幅、失去纤细感`,
  );
});

test("中心略微偏上，给底部走带条让位", () => {
  const { canvas, doc } = fake(1000, 1000);
  const geom = computeGeometry(canvas, doc);
  assert.ok(geom.cy < geom.H / 2, "圆心应高于几何中心");
  assert.ok(geom.cy > geom.H * 0.45, "但不能高太多，否则上重下轻");
});
