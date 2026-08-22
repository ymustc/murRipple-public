"""硬字幕 OCR。

**这一步的产出不是"一段文字"，而是「文字 + 出现时刻」。** 后者才是它相对
现成歌词的独有价值：我们目前最大的质量短板是歌词对齐，WhisperX 听唱歌会
出错（实测把「陇西」听成「吹息」）。硬字幕能直接给出每行的演唱时刻，这首
歌于是可以完全跳过 WhisperX，精度反而更高。

`merge_bright` 与 `classify_bands` 是这里仅有的两处判断，且不需要 OCR 依赖
就能测，所以都单独导出。抽帧与识别本身是 I/O，测不出什么东西来。
"""

from __future__ import annotations

import json
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

from murripple.ingest.scan import IngestError

#: 抽帧频率。歌词一行至少停留一两秒，2 fps 足够，比逐帧快十五倍。
DEFAULT_FPS = 2.0

#: 已唱／未唱的亮度分界。实测这段素材：已唱行的 p95 亮度是 237–255，
#: 未唱行是 176–207，中间空得很开，220 落在正中间。
#: 用 p95 而不是峰值：峰值容易被一个抗锯齿的亮像素顶满，分不开。
BRIGHT_THRESHOLD = 220.0

#: 判定亮度用的分位数。见上。
BRIGHT_PERCENTILE = 95

#: 自动找歌词带时取样多少帧。要够多才能看出"哪条带子的文字在变"。
LAYOUT_SAMPLES = 16

#: 两个文字框的纵向中心差在这个比例（占画面高）以内，算同一条带子。
BAND_TOLERANCE = 0.012

#: 一条带子至少要出现这么多种不同文字，才算"歌词在这儿"。
#: 不能只要求"大于一种"：水印被 OCR 一会儿读成 MADEWITHSUNO、一会儿读成
#: MADEWITH SUNO，两种写法就足以让它冒充歌词带（实测踩过）。归一化能消掉
#: 这一例，但同类抖动防不胜防，再加一道数量门槛。
MIN_DISTINCT_TEXTS = 4

#: 一行至少要在"已唱"集合里连续待这么多帧才算数。少于这个数的多半是
#: OCR 抖动，不是真的出现过一行。
MIN_FRAMES = 2

#: 一行最多在画面上留这么久。
#: 超出的部分是间奏——歌词带上那句还挂着，但已经没人在唱了。不设上限的话
#: 每行都延续到下一行开始，整首歌的歌词覆盖率是 99.9%，间奏里画面上一直
#: 挂着上一句。
#:
#: **样本数：1 首歌，48 行。** 8.0 是从第一首歌一个样本推出来的——WhisperX
#: 量的是真实演唱时长，那 48 行里中位 3.54 秒、p90 5.01 秒、最长 7.42 秒，
#: 8.0 就是在那个最长值上留了点余量。一首歌不足以说明 8.0 对所有歌都对：
#: 慢歌的长拖腔、戏腔的甩腔都可能真的唱过 8 秒，那时这个上限会把还在唱的
#: 后半句切掉；反过来，快歌的间奏挂字也可能远在 8 秒之内，切不干净。
#:
#: 素材多起来（第二首往后每首都有 lyrics.timing.json，那正是 WhisperX 量
#: 出来的真实演唱时长）就该回头把这个分布重算一遍，用多首歌的最长值重定
#: 这个数——**这件事目前没有人在管，也没有任何测试在替它把关**。
#:
#: tests/test_ingest_subtitle.py 里那条 `test_max_line_sec_is_a_ratchet`
#: 只是**棘轮**：它把 8.0 钉住，好让日后谁改动这个数都得连带改测试、说清
#: 理由，不会悄悄漂走。它不是"8.0 是对的"的证据——它一个样本都没多量。
MAX_LINE_SEC = 8.0

#: 两段文字的相似度到这个程度就当成同一行。
#: OCR 对同一行的识别并不是每帧一模一样（多认一个字、少认一个字），按
#: 全等比对的话，一次抖动就会被当成"又来了一行新的"。
SIMILARITY = 0.75


def compare_key(text: str) -> str:
    """比对用的形式：去掉空白与标点符号。

    标点是 OCR 最不稳的部分。实测同一行「X——」在相邻帧里被读成
    `X` / `X-` / `X—` / `X一` 四种；破折号只有一个字符，在三字短句里
    一变就把相似度拉到 0.67，于是同一行被记成三行。剥掉标点之后它们
    都是「X」，一次就对上了。（真实那一行的原文是私产，守卫见
    `tests/test_no_private_lyrics.py`；同形的例子在
    `tests/test_ingest_subtitle.py` 里用自造语料写着。）
    """
    return "".join(
        c for c in text
        if not unicodedata.category(c).startswith(("P", "S", "Z", "C"))
    )


def _similar(a: str, b: str) -> bool:
    ka, kb = compare_key(a), compare_key(b)
    if ka == kb:
        return True
    return SequenceMatcher(None, ka, kb).ratio() >= SIMILARITY


def _seen_in(text: str, frames: list[list[str]]) -> bool:
    return any(_similar(text, other) for frame in frames for other in frame)


def merge_bright(frames: list[list[str]], fps: float) -> list[dict]:
    """"已唱"集合的逐帧快照 → 带时间戳的行。

    `frames[i]` 是第 i 帧里所有已经唱过的行，从上到下。

    **判据是"谁刚进入这个集合"，不是"谁在最下面"。** 一开始写的是后者，
    真实素材上漏了整整一行：有一行只在一帧里当过最下面的亮行，随即被闪帧
    过滤当噪声丢掉。而一行进了已唱集合就会一直待着往上
    滚十几秒，按"新增"判就跟采样率无关了。
    """
    if fps <= 0:
        raise ValueError(f"fps 必须为正，收到 {fps}")

    norm = [[t for t in (norm_text(x) for x in frame) if t] for frame in frames]

    events: list[tuple[int, str]] = []
    for i, cur in enumerate(norm):
        # 跟前 MIN_FRAMES 帧比，而不是只跟上一帧：OCR 偶尔漏认一帧，
        # 只比上一帧的话那一行会被当成"又新来了一次"，多出一条重复的。
        recent = norm[max(0, i - MIN_FRAMES):i]
        for text in cur:
            if not _seen_in(text, recent):
                events.append((i, text))

    kept: list[tuple[int, str, int]] = []
    for i, text in events:
        last = i
        for j in range(i + 1, len(norm)):
            if not _seen_in(text, [norm[j]]):
                break
            last = j
        if last - i + 1 >= MIN_FRAMES:
            kept.append((i, text, last))

    # 同一帧里冒出好几行时，把它们摊在这一个采样间隔内。
    #
    # 不摊的话它们的 t0 全等、时长全是 0，下游会当成空行整段丢掉。摊开是
    # 插值、不是测量：我们只知道这几句都出现在这半秒里，不知道各自的确切
    # 时刻，所以只在这半秒内部摊，不占用到下一行为止的整段时间。
    starts: list[float] = []
    k = 0
    while k < len(kept):
        i = kept[k][0]
        group = [e for e in kept[k:] if e[0] == i]
        for m in range(len(group)):
            starts.append((i + m / len(group)) / fps)
        k += len(group)

    lines = []
    for k, (i, text, last) in enumerate(kept):
        # t1 取下一行开始的时刻。一行进了已唱集合会一直待到滚出画面，
        # 那是十几秒之后的事，拿它当结束会跟后面好几行重叠。
        end = starts[k + 1] if k + 1 < len(kept) else (last + 1) / fps
        lines.append({
            "t0": starts[k],
            "t1": min(end, starts[k] + MAX_LINE_SEC),
            "text": text,
        })
    return lines


@dataclass(frozen=True)
class TextBox:
    """OCR 认出的一块文字。坐标是被识别那张图里的像素。"""

    text: str
    x0: int
    y0: int
    x1: int
    y1: int
    score: float


#: OCR 后端的接口：吃一张 BGR 图，吐若干文字框。做成可注入的，一是逻辑
#: 部分不必装 OCR 依赖就能测，二是换引擎不用改这里。
Ocr = Callable[[np.ndarray], list[TextBox]]


@dataclass(frozen=True)
class Layout:
    """自动看出来的画面分区。"""

    #: 歌词带，占画面高度的比例 (y0, y1)。
    band: tuple[float, float]

    #: 从头到尾不变的文字，(纵向中心占比, 文字)。曲名、作者、水印都在这里
    #: ——它们正因为不变才被排除在歌词带之外，顺手就能拿来当标题。
    static: list[tuple[float, str]]


def load_ocr() -> Ocr:
    """拿一个默认 OCR 后端。没装依赖时报错要说清怎么办。"""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise IngestError(
            "没装 OCR 依赖，认不了硬字幕。装一下：\n"
            "  uv sync --extra ocr\n"
            "也可以绕开：自己写一份 lyrics.txt 放进歌曲目录，"
            "ingest 会优先用现成的歌词。"
        ) from exc

    engine = RapidOCR()

    def run(image: np.ndarray) -> list[TextBox]:
        result, _ = engine(image)
        boxes = []
        for quad, text, score in result or []:
            xs = [p[0] for p in quad]
            ys = [p[1] for p in quad]
            boxes.append(
                TextBox(
                    text=text,
                    x0=int(min(xs)), y0=int(min(ys)),
                    x1=int(max(xs)), y1=int(max(ys)),
                    score=float(score),
                )
            )
        return boxes

    return run


def video_size(video: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(video)],
        capture_output=True, text=True,
    )
    try:
        w, h = out.stdout.strip().split("x")
        return int(w), int(h)
    except ValueError as exc:
        raise IngestError(f"读不出 {Path(video).name} 的画面尺寸：{out.stderr.strip()}") from exc


def read_frames(
    video: Path, fps: float, band: tuple[float, float] | None = None
) -> Iterator[np.ndarray]:
    """按 `fps` 抽帧，裁到 `band` 指定的横向带子，逐帧吐 BGR 数组。

    走 ffmpeg 的 rawvideo 管道而不是先写一堆 PNG：150 秒的片子在 2 fps 下
    是 300 张图，落盘再读一遍纯属白费，而且要管临时目录的清理。
    """
    w, h = video_size(video)
    y0, y1 = (0.0, 1.0) if band is None else band
    top = max(0, int(h * y0)) & ~1
    height = max(2, (int(h * y1) - top)) & ~1
    height = min(height, h - top)

    vf = f"fps={fps}"
    if band is not None:
        vf += f",crop={w}:{height}:0:{top}"

    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vf", vf,
         "-pix_fmt", "bgr24", "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    frame_bytes = w * height * 3
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(height, w, 3)
    finally:
        proc.stdout.close()
        proc.wait()


def norm_text(text: str) -> str:
    """比对用的归一化形式。

    去掉所有空白：OCR 对同一块文字的分词并不稳定，实测同一个水印一会儿是
    「MADEWITHSUNO」一会儿是「MADEWITH SUNO」。按原样比对的话，它会被当成
    "文字在变"，于是既冒充了歌词带、又躲过了静态文字的排除。
    """
    return "".join(text.split())


def _gray(image: np.ndarray) -> np.ndarray:
    """BGR → 灰度。自己算，省得为了一行公式把 cv2 拉成必需依赖。"""
    b, g, r = image[:, :, 0], image[:, :, 1], image[:, :, 2]
    return 0.114 * b + 0.587 * g + 0.299 * r


def brightness_of(image: np.ndarray, box: TextBox) -> float:
    sub = _gray(image)[max(0, box.y0):box.y1, max(0, box.x0):box.x1]
    return float(np.percentile(sub, BRIGHT_PERCENTILE)) if sub.size else 0.0


def bright_lines(
    image: np.ndarray,
    boxes: list[TextBox],
    threshold: float = BRIGHT_THRESHOLD,
    exclude: frozenset[str] = frozenset(),
) -> list[str]:
    """这一帧里所有"已经唱过"的行，从上到下。

    Suno 的歌词带是滚动列表：唱过的行满亮，还没唱到的行渐暗。哪一行刚进
    这个集合，哪一行就是此刻这一句（见 `merge_bright`）。

    `exclude` 是全曲不变的那些文字（水印、作者署名）。它们可能落在歌词带
    里——实测 `MADE WITH SUNO` 就在带子下沿以内——一直待在集合里没什么害处，
    但它会以"新来的一行"的身份被记一次，白多一行歌词。
    """
    bright = [
        b for b in boxes
        if norm_text(b.text) not in exclude and brightness_of(image, b) >= threshold
    ]
    return [b.text for b in sorted(bright, key=lambda b: b.y0)]


def analyze_layout(
    video: Path, ocr: Ocr, samples: int = LAYOUT_SAMPLES
) -> Layout:
    """看出歌词带在哪，顺带把从头到尾不变的文字挑出来。

    判据是**变不变**，不是位置或字号：曲名、作者、`MADE WITH SUNO` 水印在
    整首歌里一个字都不动，歌词每几秒就换一批。按位置猜的话，换一个来源的
    录屏就得重调参数；按"变不变"判，换谁都成立。
    """
    _, h = video_size(video)
    duration = _duration(video)
    if not duration:
        raise IngestError(f"读不出 {Path(video).name} 的时长")

    # 掐头去尾：片头片尾常是纯封面，没有歌词，会把取样浪费掉。
    fps = samples / (duration * 0.8)
    frames = list(read_frames(video, fps))
    if not frames:
        raise IngestError(f"从 {Path(video).name} 一帧都没抽出来")

    return classify_bands([ocr(f) for f in frames], h)


def classify_bands(per_frame: list[list[TextBox]], height: int) -> Layout:
    """逐帧的文字框 → 歌词带 + 静态文字。

    单独导出因为这是这一段唯一有判断的地方，且不需要 ffmpeg 与 OCR 就能测。
    """
    if height <= 0:
        raise ValueError(f"height 必须为正，收到 {height}")

    bands: list[dict] = []
    for boxes in per_frame:
        for box in boxes:
            center = (box.y0 + box.y1) / 2 / height
            for band in bands:
                if abs(band["center"] - center) <= BAND_TOLERANCE:
                    band["texts"].add(norm_text(box.text))
                    band["frames"] += 1
                    band["span"] = (min(band["span"][0], box.y0 / height),
                                    max(band["span"][1], box.y1 / height))
                    break
            else:
                bands.append({
                    "center": center,
                    "texts": {norm_text(box.text)},
                    "frames": 1,
                    "span": (box.y0 / height, box.y1 / height),
                })

    # 大多数帧都在、且文字始终不变 → 静态元素（曲名／作者／水印）。
    static = [
        (b["center"], next(iter(b["texts"])))
        for b in sorted(bands, key=lambda b: b["center"])
        if len(b["texts"]) == 1 and b["frames"] >= len(per_frame) * 0.8
    ]
    changing = [b for b in bands if len(b["texts"]) >= MIN_DISTINCT_TEXTS]
    if not changing:
        raise IngestError(
            "画面里没找到反复更换的文字，看不出歌词在哪。"
            "请自己写一份 lyrics.txt 放进歌曲目录。"
        )

    top = min(b["span"][0] for b in changing)
    bottom = max(b["span"][1] for b in changing)
    # 留一点余量：字的上下沿会被 OCR 的框切掉一点，而歌词行会往下滚。
    pad = 0.012
    return Layout(
        band=(max(0.0, top - pad), min(1.0, bottom + pad)),
        static=static,
    )


def _duration(path: Path) -> float | None:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def extract_subtitles(
    video: Path,
    band: tuple[float, float] | None = None,
    fps: float = DEFAULT_FPS,
    ocr: Ocr | None = None,
    threshold: float = BRIGHT_THRESHOLD,
    on_progress: Callable[[int], None] | None = None,
) -> tuple[list[dict], Layout | None]:
    """认出硬字幕，返回带时间戳的行，以及自动分区的结论（band 给定时为 None）。"""
    video = Path(video)
    ocr = ocr or load_ocr()

    layout = None
    if band is None:
        layout = analyze_layout(video, ocr)
        band = layout.band
    exclude = frozenset(t.strip() for _, t in layout.static) if layout else frozenset()

    snapshots: list[list[str]] = []
    for i, frame in enumerate(read_frames(video, fps, band)):
        snapshots.append(bright_lines(frame, ocr(frame), threshold, exclude))
        if on_progress and i % 20 == 0:
            on_progress(i)

    return merge_bright(snapshots, fps), layout


#: 行首的段落标记。Suno 的歌词单每段开头都挂一个，`[Verse 1]某一句歌词…`
#: 会被当成歌词的一部分显示出来。方括号在各家歌词单里都是结构标记的写法，
#: 剥掉是安全的；圆括号不剥——真歌词里的和声、语气词都用圆括号。
SECTION_MARKER = re.compile(r"^\s*\[[^\]]*\]\s*")


def strip_section_marker(text: str) -> str:
    stripped = SECTION_MARKER.sub("", text)
    # 整行只有一个标记时保留原样：删成空串会让这一行凭空消失，
    # 而 lyrics.txt 与 lyrics.timing.json 是按行数配对的。
    return stripped or text


def write_lyrics(lines: list[dict], path: Path) -> Path:
    """歌词原文。一行一句，就是管线一直吃的那种 lyrics.txt。

    **必须让人过一眼再往下走。** OCR 会错字（实测这段素材把「僭越」认成
    「臂越」），而歌词原文的准确度直接决定强制对齐的质量——错的地方会一路
    错到底，而且看画面时根本看不出是哪一步错的。
    """
    path = Path(path)
    path.write_text(
        "\n".join(strip_section_marker(line["text"]) for line in lines) + "\n",
        encoding="utf-8",
    )
    return path


#: 硬字幕拿到的演唱时刻。跟 lyrics.txt 并排放，一行对一行。
TIMING_FILENAME = "lyrics.timing.json"


def write_timing(lines: list[dict], song_dir: Path) -> Path:
    """把 OCR 拿到的演唱时刻单独存一份。

    **不写进 overrides.json。** 那一层是按下标打进"对齐之后"的歌词列表的，
    而对齐会把没对上的行丢掉——实测这首歌 32 行进去、30 行出来，下标当场
    整体错位、报越界。演唱时刻不是对齐结果的补丁，它**就是**对齐结果，
    该在对齐之前就顶掉 WhisperX。
    """
    path = Path(song_dir) / TIMING_FILENAME
    doc = [
        {"t0": round(line["t0"], 3), "t1": round(line["t1"], 3), "text": line["text"]}
        for line in lines
    ]
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def load_timing(song_dir: Path) -> list[dict] | None:
    """读回演唱时刻，并对齐到当前的 lyrics.txt。缺文件时返回 None。

    **文字以 lyrics.txt 为准。** 人过一眼时改的正是那份（这首歌就把「臂越」
    改回了「僭越」），时间戳这边留的是 OCR 的原文，不能拿它去盖。
    """
    song_dir = Path(song_dir)
    path = song_dir / TIMING_FILENAME
    lyrics_file = song_dir / "lyrics.txt"
    if not path.exists() or not lyrics_file.exists():
        return None

    doc = json.loads(path.read_text(encoding="utf-8"))
    texts = [t for t in lyrics_file.read_text(encoding="utf-8").splitlines() if t.strip()]
    if len(doc) != len(texts):
        raise IngestError(
            f"{TIMING_FILENAME} 有 {len(doc)} 行，lyrics.txt 有 {len(texts)} 行，"
            f"对不上——多半是校对时拆了或并了行。删掉 {TIMING_FILENAME} 走常规对齐，"
            f"或者重跑 ingest --force。"
        )
    return [
        {"t0": float(d["t0"]), "t1": float(d["t1"]), "text": text, "words": None}
        for d, text in zip(doc, texts)
    ]
