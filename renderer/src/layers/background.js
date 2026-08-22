/**
 * 背景：三重色场 + 星云 + 星野 + 六星连珠 + 浮尘 + 流星 + 经线 + 颗粒 + 暗角。
 *
 * 这一层是"有没有中心感"的全部来源。此前它只是一块平色加几条竖线，
 * 于是整个画面像浮在纯黑上；现在是这一叠东西的合成，圆心附近最亮、
 * 向四角褪成近黑，画面才有纵深与星云感。
 *
 * **全部是 t 的纯函数。** 星云的轨道角与浮尘的高度都写成闭式
 * （`a0 + t*sp`、`(y0 - t*vy) mod H`）而不是逐帧累加——累加在逐帧导出
 * 下不可复现，而这一层每一帧都在动。星野与噪点瓦片用固定种子在加载时
 * 生成一次，之后只读。
 */

import { mulberry32 } from "../core/clock.js";
import { sampleAt } from "../core/timeline.js";
import { makeGlowSprite } from "../core/glow.js";

const BASE = "#04060c";

/** 星云光斑：绕圆心走椭圆轨道的大团柔光。 */
const NEBULA_COUNT = 7;
const NEBULA_SQUASH = 0.7;

const STAR_COUNT = 220;
const MOTE_COUNT = 64;
const GRAIN_SIZE = 256;

const LINE_SPACING_PX = 46;

/**
 * 英仙座辐射点，归一化坐标。
 *
 * 流星雨之所以叫"英仙座"，是因为**所有流星都从同一个点射出**；随机划线
 * 只是随机划线。
 *
 * 从右上挪到左上：右上让给了六星连珠（于淼要行星挂在偏上方，而右侧中段
 * 是声部面板，只剩右上），两个天象不能挤在一处。左上角是标题卡，但辐射点
 * 本身不需要被看见——被卡片盖住的只是最靠近辐射点那一小段，流星是往外
 * 飞的。
 */
export const RADIANT = { x: 0.1, y: 0.06 };

/**
 * 射出方向的扇面：向下与右下偏下。
 *
 * 这一段扇面里的每条射线离圆心都在 2R 以外，流星整程都在画左那条空带里
 * 走，不用靠"接近圆环就烧尽"那道保险去救。再往右转就直冲圆心，再往左转
 * 几步就出画。
 */
const FAN0 = (62 * Math.PI) / 180;
const FAN1 = (122 * Math.PI) / 180;

/**
 * 单颗从出现到消失的秒数——只管"一颗飞多久"，不管"多久来一颗"。
 *
 * 这两件事故意拆成两个独立常量：METEOR_LIFE 只喂给 `one()` 里的
 * `p = age / METEOR_LIFE`，决定进度条走多快，也就是头部沿射线挪动的
 * 速度与整条尾迹淡入淡出的节奏；METEOR_PERIODS（下面）只喂给
 * `u = t / 周期 + 相位`，决定第几轮出现第几颗。改前者不动后者，一颗
 * 流星飞得更慢，但还是同样十几秒才轮到下一颗——不拆开的话，"划得慢"
 * 和"来得勤"就没法分别调。
 *
 * 于淼原话"流星效果有点太快了可能看不到"：初版 0.62s 一晃而过，尾迹
 * 和亮度上一轮已经提过一档，这轮改的是这个数，其余全部不动。
 *
 * 幅度：先按腰斩一半试过（1.24s，飞行速度减半），实测双星或跨槽位撞在
 * 一起的时长占比在若干个 600 秒窗口里摸到 1.29%，个别窗口已经超过
 * "偶尔两颗齐落"守的 <1% 那条线——飞得越慢，两颗流星共存的那段时间
 * 也跟着变长，2× 已经在拿于淼验收过的"偶尔"分寸冒险。改用 1.5×
 * （0.93s）后同样窗口测得的峰值是 0.87%，稳稳留在线内，而画面上头部
 * 移动的距离肉眼仍明显比原版慢一大截（验收时截过同一颗流星前后两版的
 * 连续帧对比，见交接记录）。
 */
export const METEOR_LIFE = 0.93;

/**
 * 四个槽位的周期（秒）——只管"多久来一颗"，见上面 METEOR_LIFE 的注释。
 * 四个槽合起来平均十几秒一颗，相位互不相干，偶尔撞上两颗齐落——这是
 * 于淼定的分寸："偶尔一颗"，不是流星雨。这次调速度没有碰这里。
 *
 * 周期取互不成倍数的数：成倍数的话它们会周期性地一起出现，看得出节奏。
 */
const METEOR_PERIODS = [47, 53, 61, 71];

/** 各槽的相位。固定种子，加载时算一次。 */
const METEOR_PHASES = (() => {
  const rng = mulberry32(0x5e11);
  return METEOR_PERIODS.map(() => rng());
})();

/**
 * t 时刻在场的流星。**闭式**，不是逐帧累加。
 *
 * `u = t / 周期 + 相位` 一步算到"第几颗（k）、这一颗进行到哪（p）"。写成
 * `p += dt` 的话逐帧导出与实时播放会对不上——这是全项目的第一铁律，
 * background.js 里星云的轨道角与浮尘的高度都是同一个路子。
 *
 * 方向与长短按 k 二次播种，而不是按槽位固定：固定的话四条轨迹会在一首
 * 歌里各重复六七次，一眼看出是套路。k 由 t 算出，所以整体仍是 t 的纯
 * 函数。
 */
export function meteorsAt(t) {
  const out = [];
  for (let i = 0; i < METEOR_PERIODS.length; i++) {
    const u = t / METEOR_PERIODS[i] + METEOR_PHASES[i];
    const k = Math.floor(u);
    const age = (u - k) * METEOR_PERIODS[i]; // 本轮已经过去几秒
    // 绝大多数时刻这里什么都没有。上界要留够双星的滞后。
    if (age >= METEOR_LIFE * 2) continue;

    const rng = mulberry32((i * 0x9e3779b1 + k * 0x85ebca6b) >>> 0);
    const one = (p, lead) => ({
      i,
      k,
      // (i, k, lead) 三者合起来才是一颗流星的身份——一轮里可能有两颗
      lead,
      p,
      ang: FAN0 + rng() * (FAN1 - FAN0),
      // 起点离辐射点多远、一生划过多远，都相对短边
      d: 0.05 + rng() * 0.26 + p * (0.2 + rng() * 0.3),
      // 尾迹长度与峰值亮度都比初版提了一档：于淼说初版"容易整颗错过"。
      // 提的是**看得见**，不是**看得多**——周期与槽位数一个没动，仍是
      // 平均十几秒一颗。
      tail: 0.085 + rng() * 0.075,
      bright: 0.8 + rng() * 0.7,
    });

    // 双星：小概率跟一颗，错开一点点时间与角度。真实流星雨里成对出现
    // 本来就有，而单靠四个独立槽位随机撞上要十来分钟才一回——一首歌都
    // 放完了还没见着，于淼说的"偶尔两颗齐落"就等于没有。
    const paired = rng() < 0.1;
    const lag = 0.16 + rng() * 0.14;

    // 两颗都算出来再挑，不能"活着才算"：one() 每调一次就要走五个随机数，
    // 少调一次，后一颗抽到的就是前一颗那份，飞到一半会突然换方向。
    const lead = one(age / METEOR_LIFE, true);
    const follow = one((age - lag) / METEOR_LIFE, false);
    if (lead.p < 1) out.push(lead);
    if (paired && follow.p >= 0 && follow.p < 1) out.push(follow);
  }
  return out;
}

/**
 * 六星连珠：常驻天象，不是特效。
 *
 * 初版六颗只是"略大一点、色差极淡"的亮点，于淼一眼指出问题：跟星野里的
 * 恒星、跟下落音符的光屑分不开。**要害在画法，不在大小与位置**——均匀
 * 发亮的圆盘无论放多大、挪到哪，都还是个光点。
 *
 * 分界线是**明暗交界**：有相位的圆是球，均匀发亮的圆是光斑。光屑永远是
 * 后者（它是加色叠出来的亮团），所以只要行星有相位，两者就再也不会混。
 *
 * **仍然不闪烁**——会眨眼的是恒星（大气湍流对点光源才明显），行星有视面，
 * 稳得多。这条是它"像真夜空"的根据，动效只准慢慢挪、慢慢转，不准忽明忽暗。
 *
 * 挂在右上：左上是标题卡，右侧中段（画高 35%–70%）是声部面板，中间是
 * 圆环与谱线——只剩右上这一块。最靠左那颗离圆心 1.98R，正好在谱线尖端外。
 */
const ECLIPTIC = { x0: 0.695, y0: 0.205, x1: 0.945, y1: 0.116 };

/**
 * 六颗行星。
 *
 * r 是半径基数（会再乘风格系数与画幅），大小差是"看得出各自特点"里最省
 * 事的一维：第三颗是气态巨行星，明显大一些，环也归它。spin 是各自
 * 的自转相位，让六条明暗交界不同步地转。
 *
 * at 间距不等——真实的连珠本来就不是均分的，等分一眼就假。
 */
export const PLANETS = [
  { at: 0, r: 3.4, hoff: -30, spin: 0.0, ring: false },
  { at: 0.17, r: 2.6, hoff: 12, spin: 1.9, ring: false },
  { at: 0.31, r: 5.0, hoff: 34, spin: 3.4, ring: true },
  { at: 0.53, r: 3.0, hoff: -14, spin: 5.0, ring: false },
  { at: 0.74, r: 4.2, hoff: 22, spin: 2.4, ring: false },
  { at: 1, r: 2.8, hoff: -38, spin: 4.3, ring: false },
];

/**
 * 六星连珠的画法参数。
 *
 * 返工时列过三档给于淼挑，在尺寸（r）、饱和度（sat）、有没有环（ring）、
 * 有没有带纹这四维上逐档拉开：最克制的一档小而哑、无环无带纹，只靠相位
 * 和大小差跟光屑分开；最清晰的一档更大更亮，环与三道带纹全上，代价是
 * 容易滑向"太阳系示意图"。三档共同的底线是 term（明暗交界的强度）
 * ——不管哪档都不为零，这是这次返工的根因，不能再退回去。
 *
 * 于淼选了中间这档：**环是最强的辨识符号**——一眼就能定性"这是行星"，
 * 而代价只是多画一圈 1px 的椭圆线，比调大整体尺寸或加带纹克制得多。
 * 带纹没跟着环一起选，是因为于淼觉得它在这个尺寸下容易糊，识别度不如
 * 环高但视觉噪声更大，两者不对等，就没必要一起要。
 *
 * 以后想调回更克制或更清晰：先动 r 和 sat（尺寸与饱和度决定"抢不抢眼"）；
 * term 是底线，不要动到零。要不要环，改的是下面 draw() 里 `p.ring` 那个
 * 判断（哪颗行星带环），不在这个对象上。
 */
const PLANET = {
  r: 1.0,
  sat: 32,
  lit: 88,
  dark: 22,
  hue: 1.0,
  halo: 0.19,
  term: 0.68,
};

export const planetStyle = () => PLANET;

/**
 * 暖色段落里六星连珠的色相压缩补偿。
 *
 * 六颗共用同一批固定色相偏移量（`PLANETS[].hoff`，-38°…+34°），在 HSL
 * 高亮度（`PLANET.lit` = 88）下，这批偏移量落进红橙黄一带（约
 * 340°…360°/0°…100°）时会明显挤成两簇："粉红一簇"（偏移量互相靠近的
 * 那几颗，都在近红端）、"淡黄绿一簇"（偏移量偏正的那几颗，都在近黄端）
 * ——这一带越亮越快趋近白，同样 72° 的色相跨度换算成 RGB 后已经很难
 * 分辨。落在蓝紫一带（约 100°…340°，紫色段落 hue≈321 在其中）的同一批
 * 偏移量不受这问题困扰，色相差得出来，不用补。
 *
 * 只在暖色区间生效：把六颗之间的色相间距拉开一些、饱和度提一点，抵消
 * 这段区间视觉上的"近白难分"；不在暖色区间时原样返回，紫色一类的段落
 * 因此不会被误伤。
 *
 * 纯函数，只吃 `hue`（背景这一层里已经算好的、由 `palette.hueShift`
 * 派生出的段落基色相，参见 `draw()`），不读时间也不读状态。
 */
export function warmHueCompensation(hue) {
  const warm = hue < 100 || hue >= 340;
  return warm ? { spread: 1.6, satBoost: 18 } : { spread: 1, satBoost: 0 };
}

/** 环的倾角。正着看是一条线，太斜又像个圈——这个角度最像土星照片。 */
const RING_TILT = -0.42;

/**
 * 行星在归一化画面坐标里的位置。
 *
 * **整条星链刚性平移**，两个周期不同的正弦叠出一个不重复的慢漂：约 108 秒
 * 一个横向来回、153 秒一个纵向来回，一秒挪不到半个像素。刚性是有意的——
 * 各挪各的就不是"连珠"了，共线是这个天象的全部意思。
 *
 * 闭式，不累加：`sin(t * 系数)` 直接由 t 算出。逐帧累加在导出时对不上。
 */
export function planetPos(p, t = 0) {
  return {
    x:
      ECLIPTIC.x0 +
      (ECLIPTIC.x1 - ECLIPTIC.x0) * p.at +
      0.0085 * Math.sin(t * 0.058),
    y:
      ECLIPTIC.y0 +
      (ECLIPTIC.y1 - ECLIPTIC.y0) * p.at +
      0.0055 * Math.sin(t * 0.041 + 1.7),
  };
}

/**
 * 明暗交界的朝向：亮面朝画面中心那侧。
 *
 * 六颗共用一个光源方向才成立——各朝各的就露馅了。在这个方向上再叠一个
 * 极慢的摆动（约 84 秒一周期），相当于行星自转，让它"活着"但不跳动；
 * 各自的相位不同，六条交界线不会齐步走。
 */
export function lightAngle(p, px, py, cx, cy, t) {
  return Math.atan2(cy - py, cx - px) + 0.42 * Math.sin(t * 0.075 + p.spin);
}

export const NAME = "background";

/**
 * 加载时生成一次的静态资源。
 *
 * 用 state.doc 作缓存键：同一页里只有一个 document，实际只会建一次。
 * 不放模块级单例是因为测试会在同一页开多个 app。
 */
const CACHE = new WeakMap();

function assets(doc) {
  let a = CACHE.get(doc);
  if (a) return a;

  const rng = mulberry32(0x5eed);

  const nebula = Array.from({ length: NEBULA_COUNT }, () => ({
    r: 0.15 + rng() * 0.5, // 轨道半径，相对短边
    a0: rng() * Math.PI * 2,
    sp: (rng() - 0.5) * 0.06, // 角速度，正负都有
    sz: 0.18 + rng() * 0.3, // 光斑尺寸，相对短边
    hoff: rng() * 120 - 60,
  }));

  const stars = Array.from({ length: STAR_COUNT }, () => ({
    r: rng() * 0.75, // 相对短边
    a: rng() * Math.PI * 2,
    s: rng() < 0.82 ? 1 : 2, // 边长（设备像素）
    tw: rng() * Math.PI * 2,
    ts: 0.5 + rng() * 1.5,
  }));

  const motes = Array.from({ length: MOTE_COUNT }, () => ({
    x0: rng(),
    y0: rng(),
    vy: 0.004 + rng() * 0.012, // 每秒上升的画面高度比例
    tw: rng() * Math.PI * 2,
    sz: 0.5 + rng() * 1.8,
  }));

  // 确定性噪点瓦片。种子写死，导出与实时必须是同一张。
  const grain = doc.createElement("canvas");
  grain.width = grain.height = GRAIN_SIZE;
  const gx = grain.getContext("2d");
  const img = gx.createImageData(GRAIN_SIZE, GRAIN_SIZE);
  const grng = mulberry32(11);
  for (let i = 0; i < img.data.length; i += 4) {
    const v = grng() * 255;
    img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
    img.data[i + 3] = 255;
  }
  gx.putImageData(img, 0, 0);

  a = { nebula, stars, motes, grain };
  CACHE.set(doc, a);
  return a;
}

/** 某条轨道在 t 处的能量，0…1。找不到就返回 0。 */
function laneEnergy(timeline, id, t) {
  const lane = timeline.lanes.find((l) => l.id === id);
  return lane ? sampleAt(lane.envSmooth, t) / 255 : 0;
}

export function draw(g, state) {
  const { geom, palette, beat, quality, t, timeline, doc } = state;
  if (geom.W === 0) return;

  const { W, H, cx, cy, dpr } = geom;
  const short = Math.min(W, H);
  const long = Math.max(W, H);
  const hue = (210 + palette.hueShift) % 360;
  const bass = laneEnergy(timeline, "bass", t);
  const air = laneEnergy(timeline, "air", t);
  const mid = laneEnergy(timeline, "mid", t);

  g.fillStyle = BASE;
  g.fillRect(0, 0, W, H);

  // —— 三重色场：主场居中，两个副场缓慢漂移，合成出不均匀的星云底 ——
  const field = (fx, fy, radius, h, sat, light, alpha) => {
    const gr = g.createRadialGradient(fx, fy, 0, fx, fy, radius);
    gr.addColorStop(0, `hsla(${h}, ${sat}%, ${light}%, ${alpha})`);
    gr.addColorStop(1, "rgba(4,6,12,0)");
    g.fillStyle = gr;
    g.fillRect(0, 0, W, H);
  };
  field(cx, cy, long * 0.7, hue, 45, 12, 0.32 + bass * 0.2);
  field(
    cx - W * 0.32 + Math.sin(t * 0.05) * W * 0.04,
    cy - H * 0.3,
    long * 0.55,
    (hue + 48) % 360,
    55,
    14,
    0.22,
  );
  field(
    cx + W * 0.34,
    cy + H * 0.3 + Math.cos(t * 0.04) * H * 0.05,
    long * 0.5,
    (hue + 318) % 360,
    50,
    13,
    0.18,
  );

  const { nebula, stars, motes, grain } = assets(doc);

  // —— 星云：椭圆轨道上的大团柔光。y 压扁，看起来才像躺着的星云盘 ——
  g.save();
  g.globalCompositeOperation = "lighter";
  const nebAlpha = 0.055 + air * 0.1 + mid * 0.06;
  for (const nb of nebula) {
    // 闭式：角度直接由 t 算，不累加
    const a = nb.a0 + t * nb.sp;
    const x = cx + Math.cos(a) * nb.r * short;
    const y = cy + Math.sin(a) * nb.r * short * NEBULA_SQUASH;
    const sz = nb.sz * short;
    // 色相取整：makeGlowSprite 按 (hue, sat) 缓存，连续变化的色相会把
    // 缓存撑爆。段落内 hueShift 恒定，取整后每段只有七种。
    const nh = Math.round((hue + nb.hoff + 720) % 360);
    g.globalAlpha = nebAlpha;
    g.drawImage(makeGlowSprite(doc, nh, 60, 128), x - sz, y - sz, sz * 2, sz * 2);
  }
  g.restore();

  // —— 星野：极慢自转 + 各自的闪烁相位 ——
  g.save();
  for (const s of stars) {
    const a = s.a + t * 0.004 * (0.4 + s.s * 0.3);
    const x = cx + Math.cos(a) * s.r * short;
    const y = cy + Math.sin(a) * s.r * short;
    if (x < -4 || x > W + 4 || y < -4 || y > H + 4) continue;
    g.globalAlpha = (0.25 + 0.45 * Math.abs(Math.sin(t * s.ts + s.tw))) * 0.8;
    g.fillStyle = "#cdd9ff";
    g.fillRect(x, y, s.s * dpr, s.s * dpr);
  }
  g.restore();

  // —— 六星连珠：一直挂在那儿，亮度与 t 无关，只是极慢地挪与转 ——
  const st = planetStyle();
  // 暖色段落里六颗会挤成两簇（见 warmHueCompensation 的注释），补一点
  // 色相间距与饱和度；紫色一类的段落不落在暖色区间，这里原样不动。
  const { spread: hueSpread, satBoost } = warmHueCompensation(hue);
  const psat = st.sat + satBoost;
  g.save();
  for (const p of PLANETS) {
    const pos = planetPos(p, t);
    const px = pos.x * W;
    const py = pos.y * H;
    // 窄画幅下黄道会蹭到谱线区。与其挪位置，不如让蹭上的那颗自己淡掉
    // ——横幅（本项目的产出画幅）里六颗都在 1.98R 之外，这一句不触发。
    const clear = Math.hypot(px - cx, py - cy) / geom.R;
    const vis = Math.max(0, Math.min(1, (clear - 1.25) / 0.45));
    if (vis <= 0) continue;

    const ph = Math.round((hue + p.hoff * st.hue * hueSpread + 720) % 360);
    // 半径跟画幅走而不是跟 dpr 走：同一段视频不论渲成 720p 还是 1080p，
    // 行星在画面里都该是同一个大小。
    const rp = p.r * st.r * (short / 900);
    const la = lightAngle(p, px, py, cx, cy, t);
    const lx = Math.cos(la);
    const ly = Math.sin(la);

    // 一圈极淡的光晕，让它嵌在夜空里而不是贴在上面。只有这一笔是加色。
    g.globalCompositeOperation = "lighter";
    g.globalAlpha = st.halo * vis;
    const halo = rp * 4.6;
    g.drawImage(makeGlowSprite(doc, ph, 45, 32), px - halo, py - halo, halo * 2, halo * 2);

    // 球面：**普通合成，不是加色**。
    //
    // 加色画出来的圆永远是越叠越亮的一团，暗面会被底下的星云吃掉——而暗面
    // 正是"这是个球不是个光点"的全部根据。光屑是加色的亮团，行星是不透明
    // 的小圆盘，两者从合成方式上就分开了。
    g.globalCompositeOperation = "source-over";
    g.globalAlpha = vis;
    const face = g.createRadialGradient(
      px + lx * rp * 0.55,
      py + ly * rp * 0.55,
      rp * 0.06,
      px,
      py,
      rp * 1.02,
    );
    face.addColorStop(0, `hsl(${ph} ${psat}% ${st.lit}%)`);
    face.addColorStop(0.55, `hsl(${ph} ${psat + 8}% ${st.lit - 30 * st.term}%)`);
    face.addColorStop(1, `hsl(${ph} ${psat + 12}% ${st.dark}%)`);
    g.beginPath();
    g.arc(px, py, rp, 0, Math.PI * 2);
    g.fillStyle = face;
    g.fill();

    // 明暗交界：沿光照方向压一道线性暗幕。半影用两个止点做柔——几个像素
    // 的圆盘上硬切会崩成锯齿，而"柔和的交界"本来也是于淼要的。
    g.save();
    g.beginPath();
    g.arc(px, py, rp, 0, Math.PI * 2);
    g.clip();
    const term = g.createLinearGradient(
      px + lx * rp,
      py + ly * rp,
      px - lx * rp,
      py - ly * rp,
    );
    term.addColorStop(0, "rgba(2,4,10,0)");
    term.addColorStop(0.4, "rgba(2,4,10,0)");
    term.addColorStop(1, `rgba(2,4,10,${0.62 * st.term})`);
    g.fillStyle = term;
    g.fillRect(px - rp, py - rp, rp * 2, rp * 2);
    g.restore();

    // 环：最强的辨识符号，一眼就知道是行星。细、半透、稍微倾斜。只给
    // PLANETS 里那颗气态巨行星（p.ring），不是每颗都有。
    if (p.ring) {
      g.save();
      g.globalAlpha = vis * 0.6;
      g.translate(px, py);
      g.rotate(RING_TILT);
      g.beginPath();
      g.ellipse(0, 0, rp * 2.15, rp * 0.62, 0, 0, Math.PI * 2);
      g.strokeStyle = `hsl(${ph} ${psat + 6}% ${st.lit - 10}%)`;
      g.lineWidth = Math.max(1, rp * 0.17);
      g.stroke();
      g.restore();
    }
  }
  g.restore();

  // —— 浮尘：向上飘。闭式取模，跨帧不留状态 ——
  if (quality >= 1) {
    g.save();
    g.fillStyle = "#9fb4dd";
    for (const m of motes) {
      const y = ((m.y0 - t * m.vy) % 1 + 1) % 1;
      const x = m.x0 + (Math.sin(t * 0.4 + m.tw) * 6) / W;
      g.globalAlpha = 0.10 + 0.08 * Math.abs(Math.sin(t * 0.7 + m.tw));
      g.fillRect(x * W, y * H, m.sz * dpr, m.sz * dpr);
    }
    g.restore();
  }

  // —— 流星：偶尔一颗，细、快、尾巴短。降级档整个不画（与浮尘同规矩：
  // 由渲染**模式**决定，不由实测帧率决定） ——
  if (quality >= 1) {
    g.save();
    g.globalCompositeOperation = "lighter";
    g.lineCap = "round";
    const rx = RADIANT.x * W;
    const ry = RADIANT.y * H;
    for (const m of meteorsAt(t)) {
      const ca = Math.cos(m.ang);
      const sa = Math.sin(m.ang);
      const hx = rx + ca * m.d * short;
      const hy = ry + sa * m.d * short;
      // 靠近圆环就烧尽。辐射点定在哪儿都挡不住某几个方向正对圆心，只能
      // 按到圆心的距离让它自己消失——流星是点缀，压不得主体。
      const rr = Math.hypot(hx - cx, hy - cy) / geom.R;
      const a =
        Math.sin(Math.PI * m.p) *
        m.bright *
        Math.max(0, Math.min(1, (rr - 1.05) / 0.65)) *
        0.5;
      if (a <= 0.004) continue;
      const tx = hx - ca * m.tail * short;
      const ty = hy - sa * m.tail * short;
      const grad = g.createLinearGradient(hx, hy, tx, ty);
      grad.addColorStop(0, `rgba(228,240,255,${a})`);
      grad.addColorStop(0.35, `rgba(198,216,255,${a * 0.4})`);
      grad.addColorStop(1, "rgba(160,190,255,0)");
      g.strokeStyle = grad;
      g.lineWidth = 1.05 * dpr;
      g.beginPath();
      g.moveTo(hx, hy);
      g.lineTo(tx, ty);
      g.stroke();
      // 头上一点点柔光。没有它是一根线，有了才是一颗在烧的东西
      const hs = 7 * dpr;
      g.globalAlpha = a * 0.6;
      g.drawImage(makeGlowSprite(doc, 218, 35, 32), hx - hs, hy - hs, hs * 2, hs * 2);
      g.globalAlpha = 1;
    }
    g.restore();
  }

  // —— 织机经线：竖向细线，给画面一点织物的经纬感 ——
  const spacing = LINE_SPACING_PX * dpr * (quality < 1 ? 2 : 1);
  g.strokeStyle = `hsla(${hue}, ${palette.sat}%, 60%, ${
    0.03 + beat.downPulse * 0.02
  })`;
  g.lineWidth = 1 * dpr;
  g.beginPath();
  for (let x = spacing / 2; x < W; x += spacing) {
    g.moveTo(x, 0);
    g.lineTo(x, H);
  }
  g.stroke();

  // —— 颗粒：极淡的胶片噪点，把渐变的色带切碎 ——
  if (quality >= 1) {
    g.save();
    g.globalAlpha = 0.028;
    const pat = g.createPattern(grain, "repeat");
    g.fillStyle = pat;
    g.fillRect(0, 0, W, H);
    g.restore();
  }

  // —— 暗角：四角压暗，把视线收回中心 ——
  const vg = g.createRadialGradient(
    cx,
    H * 0.46,
    short * 0.36,
    cx,
    H * 0.5,
    long * 0.78,
  );
  vg.addColorStop(0, "rgba(2,3,9,0)");
  vg.addColorStop(1, "rgba(1,2,7,0.62)");
  g.fillStyle = vg;
  g.fillRect(0, 0, W, H);
}
