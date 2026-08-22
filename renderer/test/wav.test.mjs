import test from "node:test";
import assert from "node:assert/strict";
import { encodeWav, HEADER_BYTES } from "../src/core/wav.js";

const str = (view, off, len) =>
  Array.from({ length: len }, (_, i) => String.fromCharCode(view.getUint8(off + i))).join("");

test("RIFF 头逐字段正确", () => {
  // 头写错了照样能生成文件——播放器要么拒绝打开、要么放噪音，都难查。
  const sr = 44100;
  const n = 100;
  const buf = encodeWav([new Float32Array(n), new Float32Array(n)], sr);
  const v = new DataView(buf);

  assert.equal(str(v, 0, 4), "RIFF");
  assert.equal(str(v, 8, 4), "WAVE");
  assert.equal(str(v, 12, 4), "fmt ");
  assert.equal(str(v, 36, 4), "data");

  assert.equal(v.getUint32(16, true), 16, "fmt 块长度");
  assert.equal(v.getUint16(20, true), 1, "格式必须是 PCM");
  assert.equal(v.getUint16(22, true), 2, "声道数");
  assert.equal(v.getUint32(24, true), sr, "采样率");
  assert.equal(v.getUint16(34, true), 16, "位深");

  const dataBytes = n * 2 * 2;
  assert.equal(v.getUint32(40, true), dataBytes, "data 块长度");
  assert.equal(v.getUint32(4, true), 36 + dataBytes, "RIFF 长度 = 36 + data");
  assert.equal(v.getUint32(28, true), sr * 4, "字节率 = 采样率 × 块对齐");
  assert.equal(v.getUint16(32, true), 4, "块对齐 = 声道 × 每样本字节");
  assert.equal(buf.byteLength, HEADER_BYTES + dataBytes);
});

test("头部一律小端——写成大端也能生成文件，但没有播放器认", () => {
  const buf = encodeWav([new Float32Array(4)], 8000);
  const v = new DataView(buf);
  // 8000 = 0x1F40，小端存储首字节应是 0x40
  assert.equal(v.getUint8(24), 0x40, "采样率不是小端");
  assert.equal(v.getUint8(25), 0x1f);
});

test("样本交织：左右声道逐样本交替", () => {
  const L = new Float32Array([1, 0, -1]);
  const R = new Float32Array([0, 1, 0]);
  const v = new DataView(encodeWav([L, R], 8000));
  const at = (i) => v.getInt16(HEADER_BYTES + i * 2, true);
  assert.equal(at(0), 0x7fff, "第 0 样本的左声道");
  assert.equal(at(1), 0, "第 0 样本的右声道");
  assert.equal(at(2), 0, "第 1 样本的左声道");
  assert.equal(at(3), 0x7fff, "第 1 样本的右声道");
  assert.equal(at(4), -0x8000, "第 2 样本的左声道");
});

test("超出 ±1 的样本被钳位，不回绕成爆音", () => {
  // 四轨叠加后超过 ±1 是常事。不钳位的话 Math.round 溢出 int16 会回绕，
  // 正的峰值变成负的最大值——听感是刺耳的爆音，而文件本身完全合法。
  const v = new DataView(encodeWav([new Float32Array([3.5, -2.8])], 8000));
  assert.equal(v.getInt16(HEADER_BYTES, true), 0x7fff, "正向过载应钳到最大");
  assert.equal(v.getInt16(HEADER_BYTES + 2, true), -0x8000, "负向过载应钳到最小");
});

test("满量程的 +1 不溢出", () => {
  // 正负用同一个系数的话，+1 × 0x8000 = 32768 超出 int16，setInt16 会
  // 回绕成 -32768——最响的那一下变成反相的最响，是最难听的一种错。
  const v = new DataView(encodeWav([new Float32Array([1.0])], 8000));
  assert.equal(v.getInt16(HEADER_BYTES, true), 0x7fff);
});

test("单声道也能编", () => {
  const buf = encodeWav([new Float32Array(10)], 22050);
  const v = new DataView(buf);
  assert.equal(v.getUint16(22, true), 1);
  assert.equal(v.getUint16(32, true), 2, "单声道的块对齐是 2");
});

test("声道长度不一致要报错，而不是静默截断", () => {
  assert.throws(
    () => encodeWav([new Float32Array(10), new Float32Array(8)], 8000),
    /长度必须一致/,
  );
});
