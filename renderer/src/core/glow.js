/**
 * 辉光。
 *
 * Canvas 2D 没有原生 bloom。做法是预渲染径向渐变精灵，再用
 * globalCompositeOperation = 'lighter' 叠加——标准图形技术，比
 * shadowBlur 快一个数量级，且完全确定性（shadowBlur 的实现随浏览器
 * 与硬件而异，会破坏逐帧导出的可复现性）。
 */

/**
 * 径向渐变的止点。分离成纯函数以便单测——精灵生成需要 DOM，测不了。
 *
 * 三段式：中心实、中段快速衰减、边缘归零。边缘必须归零，否则精灵会有
 * 一圈硬边，叠加时非常显眼。
 */
export function glowStops(intensity) {
  const a = Math.max(0, Math.min(1, intensity));
  return [
    [0.0, a],
    [0.25, a * 0.55],
    [0.55, a * 0.18],
    [1.0, 0],
  ];
}

/**
 * 精灵缓存。**没有淘汰策略，是量过之后决定不加的，不是漏了。**
 *
 * 量法（2026-08-14，私仓 songs/01 的真产物：270 秒、9 个段落、6 条
 * 轨道）：不改本文件，在页面最外层包一层 `document.createElement` 计数器
 * ——每一次缓存未命中都恰好建一个 canvas，从外面就数得出条目数。
 *
 *   起播后实时播 4 秒                          22
 *   renderFrame 扫完全曲（步长 0.05 s）        199
 *   同样再扫两遍                               +0
 *   0…20 s 用 0.004 s 的细步长扫两遍           +0
 *   全曲按 1/60 s 逐帧扫两遍（16200 帧/遍）    +0
 *   再实时播 4 秒                              +0
 *
 * 199 个里有 1 个是 background.js 的噪点瓦片（256×256），其余 198 个是
 * 精灵：128×128 的 82 个、64×64 的 62 个、32×32 的 54 个，像素内存合计
 * 约 6.6 MB，一次播放里到此为止，长时间播放不再增长。
 *
 * 有上界的原因不在本文件，在 palette.js：`paletteAt` 在同一段落内恒定，
 * hue 与 sat 都不随 t 连续漂移，键的取值因此被"段落数 × 轨道数"框住。
 * 这条性质已经有测试守着（palette.test.mjs「同一段落内配色恒定，不随 t
 * 漂移」），所以这里不另加守卫。**验证过它确实是那个承重点**：把
 * hueShift 改成随 t 漂移，同一遍扫描的条目数从 199 涨到 3706，而那条
 * palette 测试当场变红。
 *
 * 顺带修正一处推断：background.js 星云那里的 `Math.round` 注释说"连续
 * 变化的色相会把缓存撑爆"。把那个取整去掉实测仍是 199——那里的色相本来
 * 就不连续（段落内恒定 + 每团星云一个固定偏移），取整是为将来留的余量，
 * 不是当下的承重点。
 */
const SPRITE_CACHE = new Map();

/**
 * 生成一个辉光精灵。按 (hue, sat, size) 缓存，只生成一次。
 *
 * doc 由调用方传入而非直接用全局 document——这样依赖是显式的，离线
 * 渲染时也可以喂别的文档实现。
 */
export function makeGlowSprite(doc, hue, sat, size = 64) {
  const key = `${Math.round(hue)}|${Math.round(sat)}|${size}`;
  const hit = SPRITE_CACHE.get(key);
  if (hit) return hit;

  const cv = doc.createElement("canvas");
  cv.width = cv.height = size;
  const g = cv.getContext("2d");
  const r = size / 2;
  const grad = g.createRadialGradient(r, r, 0, r, r, r);
  for (const [offset, alpha] of glowStops(1)) {
    grad.addColorStop(offset, `hsla(${hue}, ${sat}%, 62%, ${alpha})`);
  }
  g.fillStyle = grad;
  g.fillRect(0, 0, size, size);

  SPRITE_CACHE.set(key, cv);
  return cv;
}

/** 测试与热重载用。 */
export function clearSpriteCache() {
  SPRITE_CACHE.clear();
}
