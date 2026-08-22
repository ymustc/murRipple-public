"""任务目录：把 `songs/<歌名>/source.mp3` + `lyrics.txt` 那套约定藏起来。

用户在页面上只做两件事：挑一个文件、（可选）贴一段歌词。`source.*` 和
`lyrics.txt` 这两个名字他一个都不该见到——这份测试守的就是「他不用知道，
但盘上确实是这两个名字」。

## 路径穿越是这里的安全性守卫

上传的文件名是**用户可控的字符串**，而它要变成一个目录名。判据不是「有没有
抛异常」——把 `../../x.mp3` 消毒成 `x.mp3` 的实现不抛，把它原样写出去的实现
也不抛。**唯一有分辨力的断言是：把文件真的落下去，`resolve()` 出绝对路径，
再看它到底在哪。**

而且「在 `songs/` 里面」这一条**本身还不够**。实测（见
`test_hostile_names_land_inside_songs` 的注释）：完全不消毒的实现拿到
`../../x.mp3` 会建出 `songs/web-<ts>-../../x/`，而 `web-<ts>-` 这个前缀
恰好把第一层 `..` 吃掉了一级，`resolve()` 之后落在 `songs/x/source.mp3`
——**还在 `songs/` 里**。所以每个恶意名字都要连着断三件事：

1. 绝对路径在 `songs/` 里（防真的逃出去）
2. 深度正好是 `songs/<一个目录>/<一个文件>`（防落到别的层）
3. `songs/` 下**只多出那一个目录**（防顺手在旁边建出 `web-<ts>-..` 这种）

## 一个测试都不许碰仓内真实的 `songs/`

`tests/test_regression_real_songs.py::test_the_baseline_covers_every_song_on_disk`
扫的是真实的 `songs/`。所以这里全部用 `tmp_path`，靠 `create_job` 的
`songs_root=` 参数注进去。**那个参数是测试注入点，不是逃生口**：它没有环境
变量，默认值就是仓内的 `songs/`，而且每一次改写默认行为都必须写在调用现场。
`test_the_default_root_is_the_repo_songs_dir` 守着这一条。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from murripple.web import jobs

# 一个固定时刻，好让目录名可预期。真实调用不传 `now`，走 `datetime.now()`。
NOW = dt.datetime(2026, 8, 14, 15, 30, 12)
STAMP = "20260814-153012"

MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00fake mp3 bytes"
MP4 = b"\x00\x00\x00\x20ftypisom fake mp4 bytes"


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "songs"
    root.mkdir()
    return root


# ------------------------------------------------------------ 藏起来的两个名字


def test_uploading_a_chinese_named_mp3_becomes_a_song_dir_with_source_mp3(tmp_path):
    """`我的歌.mp3` → `songs/web-<时间戳>-我的歌/source.mp3`，字节原样。"""
    root = _root(tmp_path)
    job = jobs.create_job("我的歌.mp3", MP3, songs_root=root, now=NOW)

    assert job.song_dir == root / f"web-{STAMP}-我的歌"
    assert job.media_path == job.song_dir / "source.mp3"
    assert job.media_path.read_bytes() == MP3
    assert job.route == jobs.ROUTE_RUN


def test_the_lyrics_land_as_lyrics_txt(tmp_path):
    """歌词写成 `lyrics.txt`——用户从头到尾没打过这个名字。"""
    root = _root(tmp_path)
    job = jobs.create_job(
        "我的歌.mp3", MP3, lyrics="第一句\n第二句\n", songs_root=root, now=NOW
    )

    assert job.lyrics_path == job.song_dir / "lyrics.txt"
    assert job.lyrics_path.read_text("utf-8") == "第一句\n第二句\n"


def test_no_lyrics_means_no_lyrics_txt(tmp_path):
    """没贴歌词就不该留一个空 `lyrics.txt`。

    空文件会骗过 `cli.run` 的 `lyrics.txt.exists()` 检查，让「没有歌词」
    静悄悄变成「有一份空歌词」，而 `ingest` 也会因为它已存在而跳过 OCR。
    """
    root = _root(tmp_path)
    for blank in (None, "", "   \n\n  "):
        job = jobs.create_job("歌.mp3", MP3, lyrics=blank, songs_root=root, now=NOW)
        assert job.lyrics_path is None, f"lyrics={blank!r}"
        assert not (job.song_dir / "lyrics.txt").exists(), f"lyrics={blank!r}"


# ------------------------------------------------------------------ 两条路线


@pytest.mark.parametrize("suffix", [".mp3", ".wav", ".m4a", ".flac"])
def test_audio_goes_straight_to_run(tmp_path, suffix):
    """音频已经是标准输入，直接叫 `source.<ext>`，`run` 拿了就跑。"""
    root = _root(tmp_path)
    job = jobs.create_job(f"我的歌{suffix}", MP3, songs_root=root, now=NOW)

    assert job.route == jobs.ROUTE_RUN
    assert job.media_path == job.song_dir / f"source{suffix}"
    assert not (job.song_dir / "_in").exists(), "音频不该绕 _in/"


@pytest.mark.parametrize("suffix", [".mp4", ".mov", ".mkv"])
def test_video_goes_into_in_for_ingest(tmp_path, suffix):
    """视频要先抽轨（还可能 OCR 硬字幕），那是 `ingest` 读 `_in/` 的活。

    落点是 `_in/<原名>` 而不是 `source.<ext>`：`murripple.ingest.scan`
    按扩展名认素材，把 mp4 叫成 `source.mp4` 只会让 `cli.find_source`
    找不到、`scan` 也扫不到。
    """
    root = _root(tmp_path)
    job = jobs.create_job(f"我的歌{suffix}", MP4, songs_root=root, now=NOW)

    assert job.route == jobs.ROUTE_INGEST
    assert job.media_path == job.song_dir / "_in" / f"我的歌{suffix}"
    assert job.media_path.read_bytes() == MP4
    assert not list(job.song_dir.glob("source.*")), "视频不该假装成 source.*"


def test_lyrics_on_the_video_route_still_land_beside_the_song_dir(tmp_path):
    """视频路线上贴了歌词，也写 `song_dir/lyrics.txt`（不是 `_in/`）。

    `cli.ingest` 见到 `lyrics.txt` 已存在就跳过 OCR——这正是想要的：用户
    自己给的歌词是权威，OCR 会错字（`ingest/scan.py` 自己也是这么写的）。
    """
    root = _root(tmp_path)
    job = jobs.create_job("我的歌.mp4", MP4, lyrics="一句", songs_root=root, now=NOW)

    assert job.lyrics_path == job.song_dir / "lyrics.txt"
    assert not (job.song_dir / "_in" / "lyrics.txt").exists()


# ---------------------------------------------------------------- 路径穿越

# 每一个都是「用户可控字符串」能长成的样子。右边是消毒之后该剩下的片段。
#
# **这里存的是不带扩展名的部分**，因为同一个恶意串要走两条路线各跑一遍
# （见下面那条测试的 docstring）。`("..", …)` 接上 `.mp3` 正好是 `...mp3`。
HOSTILE = [
    ("../../x", "x"),
    ("../../../../../../x", "x"),
    ("/etc/passwd", "passwd"),
    ("..\\..\\x", "x"),  # Windows 风格
    ("..", jobs.FALLBACK_STEM),  # 消毒后什么都不剩
    ("我 的 歌", "我 的 歌"),  # 空格照留
    ("a\x00b", "a-b"),  # NUL 会让 open() 直接 ValueError
    ("a\nb", "a-b"),
]

# 两条路线各一个后缀。**两条都要跑**：视频路线比音频路线多一个用户可控的
# 写入点（见下面 docstring），只测音频等于只测了较窄的那一条。
ROUTE_SUFFIXES = [(".mp3", MP3), (".mp4", MP4)]


@pytest.mark.parametrize(
    "suffix,content", ROUTE_SUFFIXES, ids=[s for s, _ in ROUTE_SUFFIXES]
)
@pytest.mark.parametrize("stem,clean", HOSTILE, ids=[h[0] for h in HOSTILE])
def test_hostile_names_land_inside_songs(tmp_path, stem, clean, suffix, content):
    """恶意文件名既不能炸，也不能写到 `songs/` 外面去。**两条路线都要跑。**

    ## 为什么视频那条也得跑（而且它的面更宽）

    音频路线上用户串**只出现在目录名一处**——文件名是写死的
    `source{suffix}`，而 `suffix` 已经被 `route_for` 的白名单锁死了。视频
    路线把 `stem` 直接当文件名用（`jobs.py` 的 `_in/<原名>`），**用户串出
    现在两处**：目录名一处，`_in/` 里的文件名又一处。只测 `.mp3` 就是只
    覆盖了两条里较窄的那一条，而漏掉的是较宽的那条。

    ## 判据是最终落盘的绝对路径，不是「抛没抛异常」

    把 `../../x.mp3` 消毒成 `x.mp3` 的实现不抛，把它原样写出去的实现也不
    抛。所以下面全部断真实落盘位置。

    **哪条断言实际在承重（实跑出来的，不是推出来的，见 task-3 报告 §3.5）**：

    0. **没炸**——`create_job` 抛任何异常都算这一条红，失败原文里写着「炸
       了」，跟下面三条长得完全不一样。这一条不是摆设：把消毒掐掉再喂
       `../../x.mp4`，视频路线在 `_in/` 那步抛 `FileNotFoundError`；喂
       `/etc/passwd.mp4` 则是 `FileExistsError: '/etc'`（它真的去 mkdir
       `/etc` 了）。「炸了」和「逃出去了」是两种不同的坏，必须分得开。
    1. 绝对路径在 `songs/` 里。**这一条被第 2 条逻辑蕴含**（`parents[k]`
       等于 `here`，`here` 自然就在 `parents` 里），所以它永远不可能是唯一
       红的那条。留着是因为 brief 指定的判据就是它，而且它的失败原文最直白
       （「落到了 X，在 songs/ 外面」）。**它不是一道独立的防线，别当它是。**
    2. 深度正好（音频 `songs/<目录>/<文件>`，视频多一层 `_in/`）。**已验独
       立承重**：把音频也塞进 `_in/`，目录名全对（第 3 条绿）、路径也没出
       `songs/`（第 1 条绿），只有这条红。
    3. `songs/` 下**只多出那一个目录，且名字精确**。**这是实际抓住了全部已
       展示变异的那条**——包括那些第 1、2 条都绿着的（`../../x.mp3` 不消毒
       时落在 `songs/x/`，路径和深度都合格，只有它旁边那个叫
       `web-<ts>-..` 的残骸露了馅）。**谁要是把它放松成「只多出一个」的计
       数断言，路径穿越这道守卫就只剩第 2 条了。**

    另外视频路线还要断 `_in/` 里的**文件名**本身消毒过——那是第二个用户可
    控写入点，上面四条只看得见目录那一处。
    """
    root = _root(tmp_path)
    filename = stem + suffix

    # 「不能炸」是 brief 单列的一条判据，给它一条自己的失败原文：抛异常和
    # 落错地方是两种不同的坏，混在一起报的话，报告里分不出是哪一种。
    try:
        job = jobs.create_job(filename, content, songs_root=root, now=NOW)
    except Exception as exc:  # noqa: BLE001  ——就是要网住全部
        pytest.fail(f"{filename!r} 把 create_job 炸了：{type(exc).__name__}: {exc}")

    # **两边都要 resolve()。** 实测（2026-08-14）：把 `songs/` 做成一个指向
    # 别处的符号链接，`media_path.resolve()` 会解到链接的真身，此时拿**没
    # 解析过**的 root 去比，`root in landed.parents` 返回 False——一条本来
    # 完全正常的落盘会被判成"逃出去了"。谁要是哪天把下面的 `.resolve()`
    # 顺手删掉，那就是这个结果。
    landed = job.media_path.resolve()
    here = root.resolve()

    # 音频落 songs/<目录>/source.<ext>，视频落 songs/<目录>/_in/<原名>。
    depth = 2 if job.route == jobs.ROUTE_RUN else 3

    assert here in landed.parents, f"{filename!r} 落到了 {landed}，在 songs/ 外面"
    assert landed.parents[depth - 1] == here, (
        f"{filename!r} 落在 {landed}，深度不对：{job.route} 这条路线该是"
        f" songs/ 下面 {depth} 层"
    )
    assert sorted(p.name for p in here.iterdir()) == [f"web-{STAMP}-{clean}"], (
        f"{filename!r} 在 songs/ 下留了别的东西："
        f"{sorted(p.name for p in here.iterdir())}"
    )

    # 第二个用户可控写入点：视频路线的文件名。前面三条只看得见目录那一处。
    if job.route == jobs.ROUTE_INGEST:
        assert landed.parent.name == "_in"
        assert landed.name == f"{clean}{suffix}", (
            f"{filename!r} 在 _in/ 里的文件名没消毒：{landed.name!r}"
        )
    else:
        assert landed.name == f"source{suffix}"

    assert landed.read_bytes() == content


def test_a_very_long_name_still_lands(tmp_path):
    """超长名不能炸。

    实测（macOS 15 / APFS，2026-08-14）：单个路径段 255 个**字符**就到顶，
    第 256 个字符起 `OSError errno 63 ENAMETOOLONG`——中文和 ASCII 都在
    255 字符处翻车，也就是说这台机器数的是字符不是字节。但 ext4 数的是
    **字节**（255 字节 = 85 个汉字），所以截断按字节算才两边都活。
    """
    root = _root(tmp_path)
    job = jobs.create_job("歌" * 300 + ".mp3", MP3, songs_root=root, now=NOW)

    assert job.media_path.read_bytes() == MP3
    assert len(job.song_dir.name.encode("utf-8")) <= 200
    assert job.song_dir.name.startswith(f"web-{STAMP}-歌歌歌")


# ------------------------------------------------------------------ 撞名字


def test_two_uploads_in_the_same_second_do_not_overwrite_each_other(tmp_path):
    """同一秒传两首同名的歌，第二首不能把第一首的音频盖掉。

    目录名只精确到秒，页面上连点两下就会撞——撞上了是**默默丢数据**，
    第一份 `source.mp3` 被覆盖，用户看到的是一首歌变成了另一首。
    """
    root = _root(tmp_path)
    first = jobs.create_job("我的歌.mp3", b"first", songs_root=root, now=NOW)
    second = jobs.create_job("我的歌.mp3", b"second", songs_root=root, now=NOW)

    assert first.song_dir != second.song_dir
    assert first.media_path.read_bytes() == b"first"
    assert second.media_path.read_bytes() == b"second"


def test_names_that_differ_only_in_case_do_not_collide(tmp_path):
    """`Song.mp3` 与 `song.mp3`：macOS 默认的 APFS 大小写不敏感。

    实测（2026-08-14，本机 APFS）：建了 `Abc/` 之后 `Path("abc").exists()`
    返回 True。所以「目录已存在」这一步在 macOS 上自然连大小写变体一起认，
    在 Linux 上它们本来就是两个目录——两边都不会覆盖。
    """
    root = _root(tmp_path)
    first = jobs.create_job("Song.mp3", b"first", songs_root=root, now=NOW)
    second = jobs.create_job("song.mp3", b"second", songs_root=root, now=NOW)

    assert first.media_path.read_bytes() == b"first"
    assert second.media_path.read_bytes() == b"second"


# ------------------------------------------------------------------ 认不出的


REJECTED = ["", "..", ".", "/etc/passwd", "歌词.txt", "x.exe", ".mp3", "我的歌"]


@pytest.mark.parametrize("filename", REJECTED)
def test_files_that_are_not_audio_or_video_are_rejected_before_anything_lands(
    tmp_path, filename
):
    """认不出的东西一律拒，而且**一个字节都不许先写下去**。

    先建目录再校验的话，用户传错一次文件就在 `songs/` 下留一个空壳，而他
    在页面上看到的是「失败了」——盘上多出来的东西没人会去收。
    """
    root = _root(tmp_path)
    with pytest.raises(jobs.JobError):
        jobs.create_job(filename, MP3, songs_root=root, now=NOW)
    assert list(root.iterdir()) == [], f"{filename!r} 被拒了却留下了东西"


def test_the_rejection_says_what_it_would_have_accepted(tmp_path):
    """拒绝的话要能让人知道下一步该传什么，否则用户只能一个个试。"""
    root = _root(tmp_path)
    with pytest.raises(jobs.JobError) as exc:
        jobs.create_job("我的歌.exe", MP3, songs_root=root, now=NOW)

    message = str(exc.value)
    assert ".exe" in message, "得说清是哪个后缀没认出来"
    for accepted in (".mp3", ".wav", ".mp4"):
        assert accepted in message, f"没列出 {accepted}"


# ------------------------------------------------------------------ 默认根目录


def test_the_accepted_suffixes_still_match_the_pipeline():
    """两条路线的扩展名表是**抄**来的，不是 import 来的——所以要钉住。

    没直接 import：`murripple.cli` 一进来就拉 librosa + numpy，而网页壳子
    每个请求都要判一次扩展名，不该为此付这个启动代价。代价是多了一份会漂
    的副本：哪天有人往 `cli.AUDIO_SUFFIXES` 里加了 `.ogg`，这里不跟上的话，
    用户传 ogg 会被页面当场拒掉，而命令行明明做得成。
    """
    from murripple import cli

    # `from murripple.ingest import scan` 拿到的是**函数** `scan`（包的
    # `__init__` 把它提上来了），不是模块——照那么写这条会 AttributeError。
    from murripple.ingest.scan import VIDEO_SUFFIXES

    assert jobs.AUDIO_SUFFIXES == cli.AUDIO_SUFFIXES
    assert jobs.VIDEO_SUFFIXES == VIDEO_SUFFIXES


def test_the_default_root_is_the_repo_songs_dir():
    """`songs_root=` 是测试注入点，**不是逃生口**。

    它没有环境变量、没有全局开关：不传就是仓内的 `songs/`，想改只能写在
    调用现场。这条断言守的是「测试用 tmp_path 跑得再欢，产品行为仍然落在
    真实的 `songs/` 下」——否则这一整份测试可能全绿而产品把歌建到了别处。
    """
    repo = Path(jobs.__file__).resolve().parent.parent.parent
    assert jobs.SONGS_ROOT == repo / "songs"
    assert (repo / "murripple" / "cli.py").exists(), "仓根认错了，上一条就是空的"
