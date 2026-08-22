/**
 * 确定性粒子世界。
 *
 * 这是整个 M2 里唯一需要真实模拟的一层，也是 M3 逐帧导出的唯一风险点：
 * 其余所有视觉量都是"给定 t 查表或现场算"，天然确定；粒子的位置靠逐步
 * 累积，必须靠固定步长与固定种子才能复现。
 *
 * 三条设计约束：
 *
 * 一、坐标与画布尺寸无关。存的是相对判定环的归一化偏移，绘制时才乘以
 *     geom.R。否则窗口一改大小同一个 t 的画面就变了——离线渲染用固定
 *     分辨率、实时窗口任意大小，两者必须画出同一帧。
 * 二、随机数按 mulberry32(SEED ^ noteIndex) 派生，不用全局序列。全局
 *     序列依赖调用顺序，跳帧或改变发射顺序就会错位。
 * 三、每帧重建数组，不做对象池。实测稳态约 79 粒（2217 个音符 / 270 秒
 *     × 12 粒 × 0.8 秒存活），这个规模下对象池是过度设计。
 */

import { mulberry32 } from "./clock.js";
import { hitIndicesIn, laneAngle } from "./notes.js";

export const PARTICLES_PER_HIT = 12;
const LIFE_SEC = 0.8;
/** 归一化速度：1 表示每秒飞出一个判定环半径。 */
const SPEED = 0.55;
const SEED = 0x9e3779b9;

export function createParticleWorld(timeline, quality = 1) {
  const perHit = Math.max(2, Math.round(PARTICLES_PER_HIT * quality));
  let particles = [];
  let simT = 0;
  // 发射区间的左端点，独立于 simT。若直接用 simT，首步就是 (0, STEP]，
  // 左开区间会把 t=0 的音符漏掉——而 onset 回溯（analyze.py 的
  // backtrack=True）完全可能把首个 onset 推到 0.0，那个音符会落地却不炸。
  let emitFrom = -1;

  function emit(lane, laneIdx, noteIdx) {
    const note = lane.notes[noteIdx];
    // 种子由轨道与音符下标共同决定，与发射顺序无关
    const rng = mulberry32(SEED ^ ((laneIdx + 1) * 0x85ebca6b) ^ noteIdx);
    const count = Math.max(1, Math.round(perHit * (0.4 + note.v * 0.6)));
    // 命中点：与音符层用同一个 laneAngle。最初这里错用了飞散方向当
    // 发射点，结果每次爆发都均匀撒在整个环上，与音符落在哪儿毫无关系。
    const ang = laneAngle(laneIdx, timeline.lanes.length, note.pitch);
    for (let i = 0; i < count; i++) {
      const dir = rng() * Math.PI * 2;
      // 取值区间比第一版宽得多：此前是 0.35+rng×0.9，看着整齐划一。
      // 参考项目的速度/寿命/尺寸全是 Math.random() 的宽分布，参差感就来自
      // 这里。我们不能改回 Math.random()（按 (轨道,音符下标) 派生固定种子
      // 是为逐帧导出刻意做的取舍，有测试守着），但把区间拉开一样有效。
      const speed = SPEED * (0.25 + rng() * 1.9) * (0.5 + note.v * 0.5);
      // maxLife 必须是这一粒自己的初始寿命，不是常量。取常量时寿命长的
      // 那半数粒子 life/maxLife > 1，绘制层一钳位，淡出曲线的前三分之一
      // 就是平的——半数光屑不淡出，突然才开始暗。
      const life = LIFE_SEC * (0.35 + rng() * 1.1);
      particles.push({
        x: 0,
        y: 0,
        vx: Math.cos(dir) * speed,
        vy: Math.sin(dir) * speed,
        life,
        maxLife: life,
        hue: lane.hue,
        // 高频轨画成十字星芒而不是圆点——碎玉与缥缈本来就是"细碎的光"
        glint: lane.id === "hat" || lane.id === "air",
        size: 0.006 + rng() * 0.022,
        // 命中点在环上的方位角，绘制层据此定位这团光屑
        anchor: ang,
      });
    }
  }

  return {
    get particles() {
      return particles;
    },

    /** 只读，供测试推进到绝对时刻。 */
    get simT() {
      return simT;
    },

    step(dt) {
      const from = emitFrom;
      simT += dt;
      emitFrom = simT;

      timeline.lanes.forEach((lane, laneIdx) => {
        for (const noteIdx of hitIndicesIn(lane.notes, from, simT)) {
          emit(lane, laneIdx, noteIdx);
        }
      });

      // 阻尼：每秒衰到 16.3%。
      //
      // 写成"每秒衰减率"而不是"每步乘 0.985"：后者的实际速率取决于步长，
      // 读的人算不出来。0.985 每步 × 120 步/秒 = 0.985^120 = 0.163。
      //
      // 一度以为这里比参考项目弱、要改成它的 pow(0.25, dt)——**方向搞反了**：
      // 每秒 25% 比每秒 16.3% 衰得**慢**，我们本来就刹得更狠。于淼说的
      // "固定方向、固定节奏"不是阻尼的问题，是取值区间太窄（见 emit）。
      const damp = Math.pow(0.163, dt);
      for (const p of particles) {
        p.x += p.vx * dt;
        p.y += p.vy * dt;
        p.vx *= damp;
        p.vy *= damp;
        p.life -= dt;
      }
      particles = particles.filter((p) => p.life > 0);
    },

    clear() {
      particles = [];
      simT = 0;
      emitFrom = -1;
    },
  };
}
