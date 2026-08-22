import test from "node:test";
import assert from "node:assert/strict";
import { fftMag, spectrumAt, waveformAt } from "../src/core/dsp.js";

const SR = 44100;
const SIZE = 1024;

function sine(freq, n, sr = SR) {
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = Math.sin((2 * Math.PI * freq * i) / sr);
  return out;
}

test("fftMag 对单频正弦给出单峰，峰在正确的 bin", () => {
  const binWidth = SR / SIZE;
  const targetBin = 10;
  const re = Float32Array.from(sine(binWidth * targetBin, SIZE));
  const im = new Float32Array(SIZE);

  const mag = fftMag(re, im);

  let peak = 0;
  for (let i = 1; i < mag.length; i++) if (mag[i] > mag[peak]) peak = i;
  assert.equal(peak, targetBin, `峰应在 bin ${targetBin}，实得 ${peak}`);
});

test("fftMag 的幅度等于输入正弦的幅度，且线性", () => {
  // 位置类断言与相对比较对整体缩放完全不敏感——把归一化的 /half 删掉
  // （幅度整体错 512 倍）仍能全绿。只有锁住绝对数值才挡得住。
  const binWidth = SR / SIZE;
  const at = (amp) => {
    const re = new Float32Array(SIZE);
    for (let i = 0; i < SIZE; i++) {
      re[i] = amp * Math.sin((2 * Math.PI * binWidth * 10 * i) / SR);
    }
    return fftMag(re, new Float32Array(SIZE))[10];
  };

  assert.ok(Math.abs(at(1.0) - 1.0) < 1e-3, `幅度 1 的正弦应给出 1.0，实得 ${at(1.0)}`);
  assert.ok(Math.abs(at(0.5) - 0.5) < 1e-3, `幅度 0.5 的正弦应给出 0.5，实得 ${at(0.5)}`);
});

test("同频不同相位给出同一幅度谱——否则确定性会被相位破坏", () => {
  const binWidth = SR / SIZE;
  const withPhase = (phase) => {
    const re = new Float32Array(SIZE);
    for (let i = 0; i < SIZE; i++) {
      re[i] = Math.sin((2 * Math.PI * binWidth * 10 * i) / SR + phase);
    }
    return fftMag(re, new Float32Array(SIZE))[10];
  };

  assert.ok(
    Math.abs(withPhase(0) - withPhase(Math.PI / 3)) < 1e-3,
    `相位不应影响幅度：${withPhase(0)} vs ${withPhase(Math.PI / 3)}`,
  );
});

test("fftMag 返回长度为 size/2", () => {
  const mag = fftMag(new Float32Array(SIZE), new Float32Array(SIZE));
  assert.equal(mag.length, SIZE / 2);
});

test("fftMag 对静音返回全零", () => {
  const mag = fftMag(new Float32Array(SIZE), new Float32Array(SIZE));
  assert.ok(mag.every((v) => v === 0));
});

test("spectrumAt 是确定性的：同一个 t 永远同一个结果", () => {
  const ch = sine(440, SR);
  assert.deepEqual([...spectrumAt(ch, SR, 0.3)], [...spectrumAt(ch, SR, 0.3)]);
});

test("spectrumAt 在不同 t 上能分辨出不同内容", () => {
  const ch = new Float32Array(SR);
  ch.set(sine(430.66, SR / 2), 0);
  ch.set(sine(4306.6, SR / 2), SR / 2);
  const early = spectrumAt(ch, SR, 0.2);
  const late = spectrumAt(ch, SR, 0.8);

  const peakOf = (m) => {
    let p = 1;
    for (let i = 2; i < m.length; i++) if (m[i] > m[p]) p = i;
    return p;
  };
  assert.ok(
    peakOf(late) > peakOf(early) * 5,
    `后半段的峰应明显更高：${peakOf(early)} → ${peakOf(late)}`,
  );
});

test("spectrumAt 越界安全：t 超出音频长度不抛错", () => {
  const ch = sine(440, 1000);
  const m = spectrumAt(ch, SR, 999);
  assert.equal(m.length, SIZE / 2);
});

test("waveformAt 返回指定个数、值域在 [-1,1]", () => {
  const ch = sine(440, SR);
  const w = waveformAt(ch, SR, 0.5, 128);
  assert.equal(w.length, 128);
  for (const v of w) assert.ok(v >= -1 && v <= 1, `越界值 ${v}`);
});

test("waveformAt 是确定性的", () => {
  const ch = sine(440, SR);
  assert.deepEqual([...waveformAt(ch, SR, 0.5)], [...waveformAt(ch, SR, 0.5)]);
});

test("waveformAt 对静音返回全零", () => {
  const w = waveformAt(new Float32Array(SR), SR, 0.5, 64);
  assert.ok(w.every((v) => v === 0));
});
