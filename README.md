# murRipple

Weave a song into ripples you can see.

Give murRipple an audio file and its lyrics; it gives you back a **self-contained
single-file `index.html`** — double-click to open, mail it to a friend, drop it on
GitHub Pages — and a **1080p60 MP4** of the same thing.

**English** · [中文](README.zh-CN.md) · [Français](README.fr.md)

<p align="center">
  <img src="assets/shell.png" alt="The local shell: pick a file or paste a link, paste the lyrics, press start" width="720">
  <br><sub>This is the whole interface. It runs on your machine and binds to the loopback interface only. What it produces is <a href="https://ymustc.github.io/murripple-demo/">playable online</a> — that is the sample song shipped in this repository.</sub>
</p>

---

## How it works

<p align="center">
  <img src="assets/pipeline.svg" alt="The murRipple pipeline, in four steps" width="760">
</p>

## Everything runs on your machine

- **No large-language-model API. No API key. Nothing to sign up for.** There is no
  model-provider call anywhere in this project.
- **Audio analysis runs locally.** Source separation (Demucs), beat and pitch
  analysis (librosa) and lyric alignment (WhisperX, optional) all execute on your
  own CPU/GPU. Your audio is never uploaded.
- **The file it produces makes zero network requests.** `dist/index.html` inlines
  the audio, the timeline and the renderer; open it with the network unplugged and
  it still runs.
- The toolchain touches the network in exactly two optional places, and both are
  things you ask for: the separation/alignment models download their weights the
  first time you run them, and `murripple ingest --url <link>` deliberately goes
  out to fetch a video you pointed it at.

> ⚠ **You are responsible for the material you process and distribute.** Recordings
> pulled from a link are usually copyrighted; a murRipple artifact embeds the
> complete audio, so make sure you hold the rights before sharing one publicly.
> All processing happens on your own machine — nothing is uploaded.

## Requirements

- **Python 3.11** — pinned, not merely recommended. Demucs does not work on Python
  3.13, so the project isolates a 3.11 environment via [uv](https://docs.astral.sh/uv/).
- **ffmpeg** — `brew install ffmpeg` (or your platform's package manager).
- **Node.js** — only if you want to build the renderer bundle or export MP4.

## Install

```bash
uv sync --group dev
```

Two optional extras:

```bash
uv sync --group dev --extra align   # lyric alignment (WhisperX)
uv sync --group dev --extra ocr     # read burned-in subtitles from a screen recording
```

Without `align` the pipeline still runs — it degrades to "no lyric layer" and says so.

## Run the sample song

This repository ships one complete song so you can make something real before you
find your own material. **[*Trempe-moi*](songs/05-trempe-moi/) is the author's own
song** — music generated with Suno, lyrics written by him, copyright his.

```bash
uv run murripple run songs/05-trempe-moi
open songs/05-trempe-moi/dist/index.html
```

Then export the same thing as video:

```bash
cd renderer && npm install
node video/render.mjs ../songs/05-trempe-moi --size 1920x1080
```

## Make your own

```bash
mkdir -p songs/my-song
cp /path/to/song.mp3 songs/my-song/source.mp3
$EDITOR songs/my-song/lyrics.txt      # one line per subtitle line

uv run murripple run songs/my-song
```

`run` is analyse-then-pack, and every step skips itself if its output is already
there. Use `--force` to redo everything.

### …or do it in a browser

```bash
uv run murripple serve
```


This starts a shell **bound to the loopback interface only** — other machines on
your network cannot reach it. Pick a file, paste the lyrics, press start. Feed it a
video instead of audio and it pulls the audio track out, tries to read the
burned-in subtitles, then stops and hands the result back to you for correction
before continuing.

## What the renderer draws

A judgement ring driven by the lead voice; falling notes with comet tails; hit
sparks; lyrics that arrive as cores of light; a radial spectrum; a nebula
background; bar-line ripples; a scale ring; a transport bar; a per-stem voice panel
you can solo and mute; and a title card.

"What you see in the browser is what is in the exported MP4" is not a slogan — the
whole render is a deterministic function of `t`, and a test renders the same instant
twice and compares frame hashes (`renderer/test/export-determinism.test.mjs`).

## Tests

```bash
uv run pytest -q            # Python
cd renderer && npm test     # renderer
```

## What is not here

The parametric **compose** subsystem — the one that takes a seed instead of an audio
file and writes an instrumental piece of its own — is not part of this repository.

## License

**[PolyForm Noncommercial License 1.0.0](LICENSE)** — `Copyright (c) 2026 YU Miao`.

> **This is not an open source license.** It does not meet the Open Source
> Initiative's definition, because it restricts the field of use. Please do not
> describe murRipple as open source; "source-available, noncommercial" is accurate.

- **You may** use, study, modify, and share murRipple, and build new things on top
  of it, for any **noncommercial** purpose — personal projects, research, teaching,
  charities, public institutions.
- **You may not** use it commercially: no selling it, no bundling it into a paid
  product or service, no using it in the course of a business.
- **Want to use it commercially?** Ask. The license simply does not grant it by
  default; that is a conversation, not a refusal.

The full text in `LICENSE` governs. The three bullets above are a plain-language
summary and have no legal effect of their own.

---
---
