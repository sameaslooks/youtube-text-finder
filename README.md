# YouTube Text Finder

> Scan an entire YouTube channel for any text appearing in video frames — no full download required.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)](https://www.microsoft.com/windows)
[![GPU optional](https://img.shields.io/badge/GPU-optional%20but%20recommended-green)](https://developer.nvidia.com/cuda-toolkit)

## What it does

**YouTube Text Finder** uses OCR to scan frames from YouTube videos and find any text you specify — without downloading the full video files. It fetches individual frames at a configurable interval, runs them through [EasyOCR](https://github.com/JaidedAI/EasyOCR), and uses fuzzy matching to tolerate OCR imperfections.

**Common use cases:**
- Find every video where a specific **username / gamer tag** appears on screen
- Track when a **custom text overlay**, URL, or watermark is shown
- Locate timestamps where a **chat message**, **score**, or **in-game text** is visible
- Monitor when a **phrase** appears in subtitles or on-screen captions

## How it works

```
YouTube channel URL
        │
        ▼
   yt-dlp          fetch full video list + direct CDN stream URLs (no full download)
        │
        ▼
   ffmpeg           seek to timestamp, extract single frame (~few KB per frame)
        │
        ▼
   EasyOCR          run OCR on frame (GPU-accelerated when available)
        │
        ▼
   fuzzysearch      fuzzy-match your query (tolerates up to 2 OCR character errors)
        │
        ▼
 frames_found/      save matching frames as PNG with direct YouTube timestamp links
```

Progress is saved to a JSON file after each video, so you can safely interrupt and resume at any time.

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | |
| ffmpeg | any recent | installed automatically by `run.bat` |
| Deno | any recent | required by yt-dlp since November 2025 |
| EasyOCR | 1.7+ | GPU strongly recommended for speed |
| NVIDIA GPU | optional | ~5–10× speedup; CPU works |

## Quick start (Windows)

**1. Clone the repository:**
```bash
git clone https://github.com/your-username/youtube-text-finder.git
cd youtube-text-finder
```

**2. Double-click `run.bat`** (or run it from the terminal).

The launcher automatically:
- Checks for ffmpeg, Deno, and Tesseract — installs them via `winget` if missing
- Creates a Python virtual environment
- Installs Python dependencies
- Launches the interactive menu

## Usage

### Interactive mode

Run `run.bat` or `python main.py` with no arguments:

```
============================================================
  youtube-text-finder
============================================================

  1. New search
  2. Resume existing
  3. Statistics
  4. Language / Язык
  5. Exit

Choice [1]:
```

Enter a channel URL and the text to search for. The tool samples one frame per minute by default and saves all matches.

### CLI / batch mode

```bash
python main.py <channel_url> <search_text> [options]
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--interval N` | 60 | Sample one frame every N seconds |
| `--limit N` | 0 (all) | Process only the first N videos |
| `--reset` | — | Discard saved progress and restart |
| `--debug-frame` | — | Save first frame of each video for inspection |
| `--save-all-frames` | — | Save every extracted frame to `frames_debug/` |
| `--skip-checks` | — | Skip tool availability checks at startup |
| `--lang en\|ru` | en | Interface language |

## Examples

### Find a gamer tag / username

Search every video on a gaming channel for a player's tag appearing on screen:

```bash
python main.py https://www.youtube.com/@SomeGamingChannel "xXDarkSlayer99Xx" --interval 30
```

Use cases:
- Find when you were killed by a specific player in a streamer's VODs
- Check if a famous content creator featured a particular account on screen
- Track appearances of a username across a tournament archive

### Find specific text shown on screen

Find every video that shows a Discord invite link:

```bash
python main.py https://www.youtube.com/@Creator "discord.gg/myserver" --interval 60
```

Find videos where a specific score or ranking appears:

```bash
python main.py https://www.youtube.com/@TournamentChannel "1st Place" --interval 15
```

Find a custom watermark or channel tag text:

```bash
python main.py https://www.youtube.com/@Channel "BestClips2024" --interval 45
```

### Scan a few videos first (test run)

```bash
python main.py https://www.youtube.com/@Channel "SearchTerm" --limit 5 --debug-frame
```

The `--debug-frame` flag saves the first extracted frame from each video so you can verify the pipeline is working before running the full scan.

### Resume an interrupted search

Just re-run the same command — or use menu option 2. Already-processed videos are skipped automatically.

```bash
python main.py https://www.youtube.com/@Channel "SearchTerm"
```

### Russian interface

```bash
python main.py https://www.youtube.com/@Channel "SearchTerm" --lang ru
```

## Output

**Matching frames** are saved to `frames_found/<search_text>/`:

```
frames_found/
└── xXDarkSlayer99Xx/
    ├── abc123_0-01-30.png    ← frame at 1m 30s in video abc123
    └── xyz789_0-04-00.png    ← frame at 4m 00s in video xyz789
```

**Progress JSON** tracks every processed video:

```
progress_SomeGamingChannel_xXDarkSlayer99Xx.json
```

At the end of a run, the tool prints a summary with direct timestamp links:

```
============================================================
  DONE
============================================================
  Videos processed:       47
  Skipped (already done):  3
  Videos with matches:     2
  Progress / results:     progress_SomeGamingChannel_xXDarkSlayer99Xx.json
  Frames:                 frames_found/xXDarkSlayer99Xx/

------------------------------------------------------------
  The Grand Finals VOD
  https://www.youtube.com/watch?v=abc123
    https://youtu.be/abc123?t=90
    https://youtu.be/abc123?t=240
```

## Configuration

Edit the `DEFAULTS` dict at the top of `main.py`:

```python
DEFAULTS = {
    "interval": 60,            # seconds between sampled frames
    "max_l_dist": 2,           # fuzzy match tolerance (Levenshtein distance)
    "min_text_len": 3,         # ignore queries shorter than this
    "min_video_duration": 60,  # skip Shorts and very short clips (seconds)
}
```

**For non-Latin text (Cyrillic, Japanese, etc.)**, update the EasyOCR languages in `get_reader()`:

```python
_reader = easyocr.Reader(['en', 'ru'], gpu=True, verbose=False)
```

**If ffmpeg / Deno are installed to non-standard paths**, update `_EXTRA_PATHS` near the top of `main.py` to match your system.

## Troubleshooting

**No frames extracted / all frames empty**

Run with `--debug-frame --limit 3` to save the first extracted frame from each video and confirm the pipeline is working.

**ffmpeg not found after `run.bat`**

Winget may install ffmpeg to a path not yet on your system `PATH`. Update `_EXTRA_PATHS` in `main.py` with your actual ffmpeg bin directory.

**EasyOCR running on CPU (very slow)**

Install CUDA-enabled PyTorch before installing EasyOCR:
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install easyocr
```

**Deno not found**

Required by yt-dlp since November 2025. `run.bat` installs it via winget. For manual install: [deno.land](https://deno.land/).

**Too many false positives**

Lower `max_l_dist` in `DEFAULTS` (try `1` or `0` for exact matching).

**Missing matches (OCR misreads text)**

Raise `max_l_dist` to `3` and lower `interval` to sample frames more frequently.

## Platform

Currently Windows-only — `run.bat` uses `winget` for dependency installation and `_EXTRA_PATHS` contains Windows tool paths. On Linux/macOS, install dependencies manually and remove the `_EXTRA_PATHS` block (or update it for your system).

## License

MIT
