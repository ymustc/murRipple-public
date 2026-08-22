/**
 * 歌词即光核 —— M2 的核心视觉决策（spec 第 3 节）。
 *
 * 不设独立的中心光核，让歌词本身发光：环是人声的轮廓，歌词是人声的
 * 内容，两者本就是一件事。这也是 light-loom 结构上做不到的——他们是
 * 八声部器乐，没有歌词。
 *
 * presence 为 0 的段落（前奏、间奏、尾奏）歌词消失，此时光核回归为
 * 纯粹的光，填补空缺。
 *
 * 字体用系统字体栈，不内嵌也不外链（零依赖约束）。
 */

import { sampleAt } from "../core/timeline.js";

const FONT_STACK = '-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
/**
 * 一行放得下多少个汉字宽。**导出是给守卫用的**：`splitLine` 的「每一行都
 * 放得下」这句话拆成两半验——`lyricsFit.test.mjs` 一半断「没有任何一行
 * 超过这个预算」（纯函数，全语料穷举），一半在真浏览器里量像素，证明
 * 这个预算真的落在画面里。
 */
export const MAX_CHARS_PER_LINE = 9;

/**
 * 淡入必须在 t0 **之前**完成，唱到那一刻字已经在了。
 *
 * 初版是从 t0 开始淡入，于是 t0 时刻 alpha 恰好为 0、要过 0.45 秒才全亮
 * ——观感就是"歌词晚于声音"。这与音符提前 1.7 秒落下是同一个道理：画面
 * 要领先声音，不能等声音来了才动。
 */
export const LEAD_IN = 0.5;
/** 唱完之后再停留一会儿才退，避免句与句之间闪断。 */
export const TAIL = 0.4;

/**
 * 用空格分词的文字：拉丁（含带重音的扩展区）、希腊、西里尔。
 *
 * **这是整条断行规则的分水岭。** 中文里的空格是句读——`锈色电台　夜里还醒`
 * 的那一格是"这里停一下"，删掉不丢信息；法语／英语里的空格是**词的边界**，
 * 删掉就把 `spare part` 粘成 `sparepart`、把整句法语糊成一坨。原实现只有
 * 一条规则（"首个空白处断成两半，后半段空白全删"），对中文是对的，对拉丁
 * 文是灾难——私仓 `songs/02` 里那句中英混排在**已交付的产物里**两个
 * 英文词就是粘着的，这个缺陷从第一天就在，只是四首中文歌里只有那一句撞上。
 *
 * 判定放在**整句**上而不是逐个空格上：一句里只要出现用空格分词的文字，
 * 这一句的空白就按词界处理。真实语料支持这个二分——句读句里一个拉丁字母
 * 都没有，唯一那句带空格的正是唯一带拉丁字母的那句，05 的 22 句全是法语。
 * 自造语料（renderer/test/fixtures/synthetic-lyric-rows.json）照这个二分捏了
 * 两侧各一批，见 `renderer/test/lyricsSyntheticCorpus.test.mjs`。
 */
const WORD_SCRIPT = /[A-Za-zÀ-ʯͰ-ϿЀ-ӿ]/;

/**
 * 占一个汉字宽的字符：CJK 表意文字、假名、CJK 标点与全角形。其余按半宽算。
 *
 * 这是个**静态**宽度模型，不问 canvas。`splitLine` 必须是纯函数（确定性
 * 三铁律：画面是 `t` 的纯函数），量真实字宽要 `measureText`，那就把断行
 * 结果绑到了字体与设备上，同一个 `t` 在两台机器上会断出不同的行。
 * 半宽 0.5 是拉丁小写字母平均字宽的常见近似值；真实字宽由
 * `renderer/test/lyricsFit.test.mjs` 在浏览器里量着，那条才是"放得下"的
 * 判据，这里只要够粗略地正确。
 */
const WIDE =
  /[⺀-〾ぁ-㏿㐀-䶿一-鿿豈-﫿︰-﹏＀-｠￠-￦]/;

/** 以"一个汉字宽"为 1 的估算宽度。 */
export function displayWidth(s) {
  let w = 0;
  for (const ch of s) w += WIDE.test(ch) ? 1 : 0.5;
  return w;
}

/**
 * 把一句切成"不许从中间断开"的最小单位，并记下它前面接什么胶水。
 *
 * 两处断点：**空白**（胶水是一个半角空格，词界要看得见）与**宽窄字交界**
 * （胶水为空——`知漪murRipple` 里中文与拉丁之间本来就没有空格，在那儿换行
 * 不算切开一个词）。切完每个 token 要么全是宽字、要么全是窄字，
 * 于是"能不能硬切"这件事由 token 自己说了算。
 */
function tokenize(s) {
  const out = [];
  const chunks = s.split(/[\s　]+/).filter(Boolean);
  for (let ci = 0; ci < chunks.length; ci++) {
    // 一个 chunk 里按宽窄再分段；段首之外的段胶水为空。
    const parts = [];
    let wide = null;
    for (const ch of chunks[ci]) {
      const w = WIDE.test(ch);
      if (wide !== w) parts.push("");
      wide = w;
      parts[parts.length - 1] += ch;
    }
    for (let pi = 0; pi < parts.length; pi++) {
      out.push({ text: parts[pi], glue: ci > 0 && pi === 0 ? " " : "" });
    }
  }
  return out;
}

/**
 * 一个 token 放不下时切成几块。**只有全宽 token 才切**——中文没有词间
 * 空格，在哪儿断都不算断在词中间；而一个超长的拉丁单词没有正确的断点
 * （要断词表），宁可让它溢出也不许断在词里（判据 4）。
 */
function pieces(tok) {
  if (displayWidth(tok) <= MAX_CHARS_PER_LINE) return [tok];
  if (!WIDE.test(tok[0])) return [tok];
  const out = [];
  for (let i = 0; i < tok.length; i += MAX_CHARS_PER_LINE) {
    out.push(tok.slice(i, i + MAX_CHARS_PER_LINE));
  }
  return out;
}

/** 贪心装箱：塞不下就换行。**空白原样留着**，词与词之间看得出边界。 */
function wrapWords(s) {
  const rows = [];
  let row = "";
  for (const { text, glue } of tokenize(s)) {
    for (const [pi, piece] of pieces(text).entries()) {
      const sep = row === "" ? "" : pi === 0 ? glue : "";
      if (row !== "" && displayWidth(row + sep + piece) > MAX_CHARS_PER_LINE) {
        rows.push(row);
        row = piece;
      } else {
        row += sep + piece;
      }
    }
  }
  if (row) rows.push(row);
  return rows;
}

/**
 * 中文句读断行——**原样保留**，01 那 44 行是产品效果。
 *
 * 首曲的歌词用全角空格分隔句读（48 行里 44 行如此），那是天然断点；
 * 多个分隔符时只按第一个断、其余删掉，避免碎成三行以上；没有分隔符
 * 且过长时从中点断，尽量均分。
 */
function splitByCaesura(s) {
  const sep = s.search(/[\s　]/);
  if (sep > 0) {
    const head = s.slice(0, sep).trim();
    const tail = s.slice(sep).replace(/[\s　]/g, "");
    return tail ? [head, tail] : [head];
  }

  if (s.length <= MAX_CHARS_PER_LINE) return [s];
  const mid = Math.round(s.length / 2);
  return [s.slice(0, mid), s.slice(mid)];
}

/**
 * 断行。**两条规则，按这一句用不用空格分词来选。**
 *
 * 出来的每一行都不超过 `MAX_CHARS_PER_LINE` 个汉字宽——句读那一路末尾
 * 也过一遍装箱，是为了让"放得下"成为这个函数的性质，而不是"现有四首歌
 * 恰好没有超长行"这个巧合。实测：01 最宽的行 6 字、03/04 最宽 9 字，
 * 所以这一道对既有中文歌**一个字符都不改**。
 */
export function splitLine(text) {
  const s = String(text).trim();
  if (!s) return [];
  if (WORD_SCRIPT.test(s)) return wrapWords(s);
  return splitByCaesura(s).flatMap((row) => pieces(row));
}

/**
 * 句子在 t 处的不透明度。
 *
 * 时间轴：[t0-LEAD_IN, t0] 淡入 → [t0, t1] 全亮 → [t1, t1+TAIL] 淡出。
 * 关键是 t0 时必须已经是 1，不是才开始涨。
 */
export function fadeAt(line, t) {
  if (t < line.t0 - LEAD_IN || t >= line.t1 + TAIL) return 0;
  if (t < line.t0) return (t - (line.t0 - LEAD_IN)) / LEAD_IN;
  if (t <= line.t1) return 1;
  return 1 - (t - line.t1) / TAIL;
}

/** 找 t 处该显示的句子下标，窗口含提前量与拖尾；没有则 -1。 */
function visibleLineAt(lyrics, t) {
  for (let i = 0; i < lyrics.length; i++) {
    if (t >= lyrics[i].t0 - LEAD_IN && t < lyrics[i].t1 + TAIL) return i;
    if (lyrics[i].t0 - LEAD_IN > t) break;
  }
  return -1;
}

/**
 * t 处歌词的在场程度，0…1。没有歌词就是 0。
 *
 * 单独导出是给 core 层用的：光核要在有字的时候让位，而"有没有字、有多
 * 少"这件事只有这一层说了算，不能在那边照抄一份窗口判定——两份判定迟早
 * 会错开一帧，那时字最亮的瞬间光核恰好还没让。
 */
export function lyricAlphaAt(lyrics, t) {
  const i = visibleLineAt(lyrics, t);
  return i < 0 ? 0 : fadeAt(lyrics[i], t);
}

export const NAME = "lyrics";

/**
 * 压幕：字后面那一小片被压暗的天空。
 *
 * 这是"字看不清"的正解。**加色混合在亮底上无解**——`lighter` 的结果是
 * 相加，底已经接近 255 时字再亮也加不出差别，于是字与光核糊成一团白
 * （于淼原话："歌词与背后中心的光晕有点重叠、过亮"）。改色相没用，那
 * 不是配色问题，是合成模式问题。
 *
 * 底既然压不亮，就把底压暗：先用一片极软的径向暗幕把字后的光核按下去，
 * 字芯才有可落笔的余地。软到看不出边界是硬指标——一旦看得出是块板子，
 * 那股仙气就没了。
 */
const SCRIM = 0.5;
/** 暗幕的颜色，取背景基色，不是纯黑——纯黑会在暖色段落里显出一块灰。 */
const SCRIM_RGB = "3,5,11";

export function draw(g, state) {
  const { timeline, palette, geom, t } = state;
  if (geom.W === 0) return;

  const idx = visibleLineAt(timeline.lyrics, t);

  // 没有歌词时直接退场。中心的光交给 core 层——M2-2 时这一层自己带一圈
  // 光晕（那时它就是"光核"），现在两层叠加会把中心冲成一团白，字反而
  // 看不清了。光核的活已经交出去，这里只管字。
  if (idx < 0) return;

  const energy = sampleAt(timeline.ring.env, t) / 255;
  const hue = (210 + palette.hueShift) % 360;

  const line = timeline.lyrics[idx];
  const alpha = fadeAt(line, t);
  const rows = splitLine(line.text);
  // 字号按**短边**定，不跟 R 缩。
  //
  // 歌词是我们区别于参考项目的核心（它是纯器乐，中心可以纯做光）。R 从
  // 短边的 0.28 缩到 0.225 之后，若字号还乘 R，字会小掉两成还多，而它是
  // 主角。按短边定尺寸，允许略微溢出波形环。
  const fontPx = Math.max(14, Math.min(geom.W, geom.H) * 0.031);

  g.save();
  g.font = `300 ${fontPx}px ${FONT_STACK}`;
  g.textAlign = "center";
  g.textBaseline = "middle";
  const lead = fontPx * 1.42;
  const top = geom.cy - ((rows.length - 1) * lead) / 2;

  // —— 压幕。椭圆而不是正圆：字块是横的，正圆要么压不住两端、要么上下
  // 挖掉太多光核 ——
  let widest = 0;
  for (const row of rows) widest = Math.max(widest, g.measureText(row).width);
  const hx = widest * 0.62 + fontPx * 1.5;
  const hy = (rows.length * lead) / 2 + fontPx * 0.95;
  g.save();
  g.translate(geom.cx, geom.cy);
  g.scale(1, hy / hx);
  const scrim = g.createRadialGradient(0, 0, 0, 0, 0, hx);
  const sa = alpha * SCRIM;
  // 四个止点而不是两个：中间留一段近乎平的高原压住光核，最后一段拉长
  // 才化得开。两点线性渐变会在中途留下一圈看得见的边。
  scrim.addColorStop(0, `rgba(${SCRIM_RGB},${sa})`);
  scrim.addColorStop(0.42, `rgba(${SCRIM_RGB},${sa * 0.86})`);
  scrim.addColorStop(0.75, `rgba(${SCRIM_RGB},${sa * 0.34})`);
  scrim.addColorStop(1, `rgba(${SCRIM_RGB},0)`);
  g.fillStyle = scrim;
  g.fillRect(-hx, -hx, hx * 2, hx * 2);
  g.restore();

  rows.forEach((row, i) => {
    const y = top + i * lead;

    // —— 柔边：这里**保留加色**。它是"歌词即光核"的全部来源，字确实要
    // 往外发光，而柔边落在压幕压暗过的地方，加得起来 ——
    g.globalCompositeOperation = "lighter";
    g.strokeStyle = `hsl(${hue} ${palette.sat}% 62%)`;
    g.globalAlpha = alpha * (0.10 + energy * 0.12);
    g.lineWidth = fontPx * 0.34;
    g.strokeText(row, geom.cx, y);
    g.globalAlpha = alpha * (0.20 + energy * 0.26);
    g.lineWidth = fontPx * 0.15;
    g.strokeText(row, geom.cx, y);

    // —— 字芯：**不加色**。加色的字芯在亮底上必然饱和成白，而
    // source-over 画出来的颜色与底无关，多亮的光核底下字都是这一个色 ——
    g.globalCompositeOperation = "source-over";
    g.globalAlpha = alpha * (0.88 + energy * 0.12);
    g.fillStyle = `hsl(${hue} ${Math.max(0, palette.sat - 35)}% ${
      84 + energy * 8
    }%)`;
    g.fillText(row, geom.cx, y);
  });

  g.restore();
}
