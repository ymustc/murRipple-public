/**
 * 断行的**自造语料**回归：一份可以进公开仓的 CJK 断行金样本。
 *
 * 与 `lyricsRealSongs.test.mjs` 的关系
 * --------------------------------------------------------------------------
 * 那一条拿的是于淼四首歌的真句子（`fixtures/real-lyric-rows.json`），
 * 证的是「已交付产物里那些行的断法一个字符都没变」。**那份语料是他的私产，
 * 不进公开仓**——于是公开仓那边一条 CJK 断行回归都不剩，而
 * `renderer/src/layers/lyrics.js` 里最险的两条规则（中文句读要删空格、
 * 拉丁词界要留空格）恰恰只有中文语料撑得起来。
 *
 * 这一条补那个洞：`fixtures/synthetic-lyric-rows.json` 是**手写的四首不存在
 * 的歌**，形状照着真语料捏，一句都不来自他的歌。两条并存，各管一段：
 * 那条管「他那四首歌的产品效果没变」（私仓），这条管「断行规则本身没变」
 * （两边都跑）。
 *
 * 金样本天生有一个洞：**拿改坏的实现重新生成一遍，样本和实现一起挪，
 * 逐句比对照样全绿。** 所以下面除了逐句比对，还有五条**只从原句推性质**的
 * 断言（每行不超预算、非空白字符不许丢、句读那一路不许留空白、词界那一路
 * 不许把两个拉丁词粘成一个、多分隔符只断第一处）——重新生成救不了它们。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import {
  splitLine,
  displayWidth,
  MAX_CHARS_PER_LINE,
} from "../src/layers/lyrics.js";

const here = dirname(fileURLToPath(import.meta.url));
const DOC = JSON.parse(
  readFileSync(resolve(here, "fixtures/synthetic-lyric-rows.json"), "utf8"),
);
const CORPUS = DOC.songs;

/** 这一句里有没有用空格分词的文字——与 lyrics.js 的 WORD_SCRIPT 同一判据。 */
const HAS_WORD_SCRIPT = /[A-Za-zÀ-ʯͰ-ϿЀ-ӿ]/;
/** 句读：整句没有拉丁字母，却带着空白。 */
const isCaesura = (t) => !HAS_WORD_SCRIPT.test(t) && /[\s　]/.test(t);
const bare = (s) => s.replace(/[\s　]/g, "");
const allLines = () =>
  Object.entries(CORPUS).flatMap(([slug, lines]) =>
    lines.map((l, i) => ({ slug, i, ...l })),
  );

/**
 * 空 fixture 会让下面每一条参数化都收集出零个断言、全绿而一个字没核。
 * （抄 `lyricsRealSongs.test.mjs` 顶上那条同样理由的断言。）
 */
test("语料非空，四首自造的歌都在——空 fixture 会让整个文件空转", () => {
  assert.deepEqual(Object.keys(CORPUS).sort(), [
    "丁-舊城殘卷",
    "丙-无隙",
    "乙-halo拆解",
    "甲-锈色电台",
  ].sort());
  for (const [slug, lines] of Object.entries(CORPUS)) {
    assert.ok(lines.length > 0, `${slug} 一句歌词都没有`);
  }
  assert.ok(allLines().length >= 50, `语料只有 ${allLines().length} 句，太薄`);
});

// —— 一、金样本：逐句比对 ——————————————————————————————

for (const [slug, lines] of Object.entries(CORPUS)) {
  test(`${slug}：${lines.length} 句自造语料的断行一个字符都不许变`, () => {
    for (const [i, { text, rows }] of lines.entries()) {
      assert.deepEqual(
        splitLine(text),
        rows,
        `${slug} 第 ${i} 句 ${JSON.stringify(text)} 断行变了`,
      );
    }
  });
}

// —— 二、只从原句推的性质：重新生成救不了这几条 ————————————

test("每一行都放得下——全语料穷举，没有例外", () => {
  for (const { slug, i, text } of allLines()) {
    for (const row of splitLine(text)) {
      assert.ok(
        displayWidth(row) <= MAX_CHARS_PER_LINE,
        `${slug} 第 ${i} 句的「${row}」宽 ${displayWidth(row)}，超过 ${MAX_CHARS_PER_LINE}`,
      );
    }
  }
});

test("非空白字符一个都不许丢、不许添", () => {
  for (const { slug, i, text } of allLines()) {
    assert.equal(
      bare(splitLine(text).join("")),
      bare(text),
      `${slug} 第 ${i} 句断行前后字符对不上：${JSON.stringify(text)}`,
    );
  }
});

test("句读那一路：断出来的行里不许留任何空白（中文的空格是句读，删掉）", () => {
  const hit = allLines().filter((l) => isCaesura(l.text));
  assert.ok(hit.length >= 30, `句读句只有 ${hit.length} 条，语料形状塌了`);
  for (const { slug, i, text } of hit) {
    for (const row of splitLine(text)) {
      assert.ok(
        !/[\s　]/.test(row),
        `${slug} 第 ${i} 句的「${row}」里留下了空白——中文句读该删掉`,
      );
    }
  }
});

/**
 * ★ **这一条是「空格被删」那个 bug 的守卫**，也是这份语料存在的首要理由。
 *
 * 判据不是「空格必须留在同一行里」——`说明书上写着 do / not open` 那种
 * 断在词界上的换行是对的。判据是**两个拉丁词之间必须还看得见边界**：
 * 要么同一行里隔着一个空格，要么被断成了相邻的两行。粘成 `donot` 就红。
 */
test("词界那一路：拉丁词与拉丁词之间的边界必须还在，不许粘成一个词", () => {
  const pairs = [];
  for (const { slug, i, text } of allLines()) {
    for (const m of text.matchAll(/([A-Za-z]+)[ \t]+([A-Za-z]+)/g)) {
      pairs.push({ slug, i, text, a: m[1], b: m[2] });
    }
  }
  assert.ok(
    pairs.length >= 4,
    `中英混排里带内部空格的拉丁短语只有 ${pairs.length} 处——` +
      "那正是「空格被删」唯一撞得上的形状，语料不能把它丢了",
  );
  for (const { slug, i, text, a, b } of pairs) {
    const joined = splitLine(text).join("\n");
    assert.match(
      joined,
      new RegExp(`${a}[ \\n]${b}`),
      `${slug} 第 ${i} 句里 ${a} 与 ${b} 之间的边界没了：${JSON.stringify(joined)}`,
    );
  }
});

test("多个分隔符只按第一个断，其余删掉——不许碎成三行以上", () => {
  const hit = allLines().filter(
    (l) => isCaesura(l.text) && l.text.split(/[\s　]+/).filter(Boolean).length >= 3,
  );
  assert.ok(hit.length >= 2, `多分隔符句只有 ${hit.length} 条`);
  for (const { slug, i, text } of hit) {
    // 这些句子断完的两半都在预算内，所以恰好两行；超预算的长尾另有下面那条。
    assert.deepEqual(
      splitLine(text).length,
      2,
      `${slug} 第 ${i} 句 ${JSON.stringify(text)} 不是两行`,
    );
  }
});

/**
 * 句读断完之后后半段仍然超预算的那一支。真语料**一条都没有**（01 最宽 6 字），
 * 那道装箱当初是被变异检验逼出来的——删掉它 26 条测试全绿。这份自造语料
 * 刻意长了两条走得到那一支的句子，让它不再靠一个手写样例撑着。
 */
test("句读断完仍超预算的长尾，要继续装箱——三行以上，行行不超预算", () => {
  const hit = allLines().filter(
    (l) => isCaesura(l.text) && splitLine(l.text).length > 2,
  );
  assert.ok(hit.length >= 2, `断完仍超预算的句读句只有 ${hit.length} 条`);
  for (const { slug, i, text } of hit) {
    const rows = splitLine(text);
    for (const row of rows) {
      assert.ok(!/[\s　]/.test(row), `${slug} 第 ${i} 句的「${row}」里有空白`);
      assert.ok(
        displayWidth(row) <= MAX_CHARS_PER_LINE,
        `${slug} 第 ${i} 句的「${row}」超预算`,
      );
    }
  }
});

test("没有任何分隔符的句子：短的不断，长的均分且不丢字", () => {
  const hit = allLines().filter((l) => !/[\s　]/.test(l.text));
  assert.ok(hit.length >= 12, `无分隔符句只有 ${hit.length} 条`);
  let short = 0;
  let long = 0;
  for (const { slug, i, text } of hit) {
    const rows = splitLine(text);
    if (displayWidth(text) <= MAX_CHARS_PER_LINE) {
      short += 1;
      assert.deepEqual(rows, [text], `${slug} 第 ${i} 句短句被断开了`);
    } else {
      long += 1;
      assert.ok(rows.length >= 2, `${slug} 第 ${i} 句长句没断`);
    }
    assert.equal(rows.join(""), text, `${slug} 第 ${i} 句丢字了`);
  }
  assert.ok(short >= 4 && long >= 6, `短句 ${short} 条、长句 ${long} 条，形状不够`);
});

test("繁体句子走的是同一条规则，不因为字形不同就换路", () => {
  const trad = CORPUS["丁-舊城殘卷"];
  assert.ok(trad.length >= 6, "繁体那首太短");
  for (const [i, { text, rows }] of trad.entries()) {
    assert.deepEqual(splitLine(text), rows, `丁 第 ${i} 句断行变了`);
    assert.ok(
      !HAS_WORD_SCRIPT.test(text),
      `丁 第 ${i} 句混进了拉丁字母，它就不再走句读那一路了`,
    );
  }
});
