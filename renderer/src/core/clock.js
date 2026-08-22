/**
 * 确定性时钟。
 *
 * 逐帧视频导出要求：给定时间 t，必须得出唯一确定的一帧。难点在于粒子
 * 系统天生有状态——位置靠"上一帧位置 + 速度"累积，而实时播放每帧间隔
 * 浮动。解法是物理永远按固定步长推进，实时按真实流逝补步数、离线按帧
 * 数补步数，两边算出同一结果。
 */

export const STEP = 1 / 120;

export const MODE_REALTIME = "realtime";
export const MODE_OFFLINE = "offline";

/**
 * 建一个时钟。
 *
 * quality 由 mode 决定，**不由实测帧率决定**。低性能设备上实时模式可以
 * 掉质量，但离线模式永远全质量——否则同一个 t 在两种模式下画出不同的
 * 帧，确定性就破了。各层从 state.quality 读取，不得自行判断帧率。
 */
export function createClock({ mode, quality = 1 }) {
  const effectiveQuality = mode === MODE_OFFLINE ? 1 : quality;

  // 用整数步数而非累加 simT。`simT += STEP` 会累积浮点误差——1/120 在
  // 二进制里不精确，3 分钟下来会少走整整一步。确定性本身不受影响（两
  // 边累积方式相同），但 M3 逐帧渲染要按 simT 对齐音频，误差没必要留。
  let steps = 0;

  return {
    mode,
    quality: effectiveQuality,

    get simT() {
      return steps * STEP;
    },

    get steps() {
      return steps;
    },

    /** 把世界推进到 targetT。永远按固定步长，绝不按真实帧间隔。 */
    advanceTo(targetT, world) {
      while ((steps + 1) * STEP <= targetT) {
        world.step(STEP);
        steps++;
      }
    },

    /**
     * 把世界推进到 t，必要时倒回重放。**renderFrame 应当用这个而不是
     * advanceTo。**
     *
     * advanceTo 只会前进：先画 t=3 再画 t=1，t=1 那帧拿到的是 t=3 的
     * 世界。M2-1 到 M2-2 期间 world 是个空壳，什么都不干，这个缺陷就
     * 一直看不出来；粒子接进来的第一次运行确定性测试就红了。
     *
     * 容差取一个步长：小于一步的倒退（音频 currentTime 的抖动）本来
     * advanceTo 就什么都不做，画面差异在一个物理步之内，不值得付整段
     * 重放的代价。
     */
    advanceOrRewind(targetT, world) {
      if (targetT < this.simT - STEP) this.reset(targetT, world);
      else this.advanceTo(targetT, world);
    },

    /**
     * 跳转：清空世界、从 0 快进到 t。
     *
     * 3 分钟 = 21600 步纯计算，几十毫秒，用户无感。好处是 seek 之后的
     * 画面与离线渲染一致——网页上看到的就是导出视频里的。
     */
    reset(t, world) {
      world.clear();
      steps = 0;
      this.advanceTo(t, world);
    },
  };
}

/** 固定种子的伪随机数发生器。粒子按 rng(SEED ^ id) 派生，不依赖调用顺序。 */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
