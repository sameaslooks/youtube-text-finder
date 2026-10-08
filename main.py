"""
youtube-text-finder
Search for any text in YouTube video frames via OCR — no full download needed.
Pipeline: yt-dlp -> ffmpeg -> OpenCV -> EasyOCR -> fuzzysearch
Scans an entire channel, remembers progress, saves matching frames.
"""

import os
import sys
import json
import glob
import time
import argparse
import subprocess
from datetime import datetime, timedelta

import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import cv2
import numpy as np
import easyocr
from fuzzysearch import find_near_matches

# --- HARDCODED TOOL PATHS ---
# Winget installs to non-standard locations not always on PATH.
# Adjust for your machine or remove if tools are already in PATH.
_EXTRA_PATHS = [
    r"C:\Program Files\Tesseract-OCR",
    r"C:\Users\SergeiIU\AppData\Local\Microsoft\WinGet\Packages\DenoLand.Deno_Microsoft.Winget.Source_8wekyb3d8bbwe",
    r"C:\Users\SergeiIU\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin",
]
for _p in _EXTRA_PATHS:
    if os.path.isdir(_p) and _p not in os.environ["PATH"]:
        os.environ["PATH"] = _p + os.pathsep + os.environ["PATH"]

_reader = None

# ---------------------- DEFAULTS ----------------------

DEFAULTS = {
    "interval": 60,
    "ocr_lang": "eng",
    "max_l_dist": 2,
    "min_text_len": 3,
    "min_video_duration": 60,
    "limit": 0,
}

FRAMES_ROOT = "frames_found"

# ---------------------- I18N ----------------------

LANG = 'en'

STRINGS = {
    'en': {
        'easyocr_init':       "[*] Initializing EasyOCR (downloads models on first run)...",
        'easyocr_ready':      "[+] EasyOCR ready, device: {device}",
        'easyocr_fail':       "[!] EasyOCR not working: {error}",
        'tool_found':         "[+] {tool} found: {path}",
        'tool_not_found':     "[!] {tool} not found in PATH.",
        'getting_videos':     "[*] Fetching video list from channel...",
        'videos_found':       "[+] Videos found: {count}",
        'timeout_list':       "[!] Timeout fetching video list (10 min).",
        'ytdlp_error':        "[!] yt-dlp error: {error}",
        'video_info':         "    -> {title} | {duration} | {width}x{height}",
        'frames_for_ocr':     "    -> {count} frames for OCR",
        'found_at':           "    [\u2713] FOUND at {ts}s -> {link}",
        'frame_saved':        "        frame: {fname}",
        'ocr_text_label':     "        text: {text}",
        'debug_frame':        "    [i] Debug frame: {path}",
        'ocr_error':          "    [!] OCR error ts={ts}: {error}",
        'grab_error':         "    [!] grab_frame error ts={ts}: {error}",
        'no_videos':          "[!] Could not get video list.",
        'limit_msg':          "[*] Limit: processing first {count}",
        'progress_reset':     "[*] Progress reset: {path}",
        'interrupt':          "\n[!] Interrupted. Saving progress...",
        'progress_saved':     "[+] Progress saved.",
        'progress_info':      "    progress: {done} processed, {skip} skipped, {found} with matches | elapsed: {elapsed}",
        'done_header':        "DONE",
        'processed_videos':   "  Videos processed:      {count}",
        'skipped_videos':     "  Skipped (already done): {count}",
        'found_videos':       "  Videos with matches:   {count}",
        'progress_file':      "  Progress / results:    {path}",
        'frames_dir':         "  Frames:                {path}",
        'no_metadata':        "no metadata",
        'too_short':          "too short",
        'no_direct_url':      "no direct url",
        'no_timestamps':      "no timestamps",
        'stats_header':       "EXISTING SEARCHES",
        'stats_text':         "     text: {text} | channel: {channel}",
        'stats_counts':       "     processed: {done} | with matches: {found}",
        'stats_read_error':   "  {idx}. {path} -- read error: {error}",
        'stats_detail_prompt':"\nShow details by number (0 = back)",
        'details_header':     "DETAILS: {path}",
        'found_label':        " \u2713 {count} matches",
        'menu_header':        "youtube-text-finder",
        'menu_1':             "  1. New search",
        'menu_2':             "  2. Resume existing",
        'menu_3':             "  3. Statistics",
        'menu_lang':          "  4. Language / \u042f\u0437\u044b\u043a",
        'menu_exit':          "  5. Exit",
        'choice':             "\nChoice",
        'channel_url_prompt': "Channel URL",
        'text_prompt':        "Text to search for",
        'interval_prompt':    "Frame interval (seconds)",
        'limit_prompt':       "Video limit (0 = all)",
        'debug_prompt':       "Save debug first frame? (y/n)",
        'save_all_prompt':    "Save ALL frames to frames_debug/? (y/n)",
        'skip_checks_prompt': "Skip tool checks? (y/n)",
        'empty_url':          "[!] Empty URL.",
        'empty_text':         "[!] Empty text.",
        'tools_header':       "\n[*] Checking tools...",
        'tools_fail':         "[!] Not all tools found. Run run.bat.",
        'resume_no_files':    "[!] No progress files. Start a new search first.",
        'resume_entry':       "  {idx}. {path}  (text: {text})",
        'resume_select':      "Number",
        'resume_info':        "[*] Resuming: text={text}, channel={channel}",
        'invalid_choice':     "[!] Invalid choice.",
        'goodbye':            "Bye.",
        'lang_prompt':        "Select language / \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u044f\u0437\u044b\u043a:\n  1. English\n  2. \u0420\u0443\u0441\u0441\u043a\u0438\u0439",
        'invalid_value':      "[!] Invalid value, using default: {default}",
    },
    'ru': {
        'easyocr_init':       "[*] \u0418\u043d\u0438\u0446\u0438\u0430\u043b\u0438\u0437\u0438\u0440\u0443\u044e EasyOCR (\u043f\u0440\u0438 \u043f\u0435\u0440\u0432\u043e\u043c \u0437\u0430\u043f\u0443\u0441\u043a\u0435 \u0441\u043a\u0430\u0447\u0430\u0435\u0442 \u043c\u043e\u0434\u0435\u043b\u0438)...",
        'easyocr_ready':      "[+] EasyOCR \u0433\u043e\u0442\u043e\u0432, \u0443\u0441\u0442\u0440\u043e\u0439\u0441\u0442\u0432\u043e: {device}",
        'easyocr_fail':       "[!] EasyOCR \u043d\u0435 \u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0442: {error}",
        'tool_found':         "[+] {tool} \u043d\u0430\u0439\u0434\u0435\u043d: {path}",
        'tool_not_found':     "[!] {tool} \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d \u0432 PATH.",
        'getting_videos':     "[*] \u041f\u043e\u043b\u0443\u0447\u0430\u044e \u0441\u043f\u0438\u0441\u043e\u043a \u0432\u0438\u0434\u0435\u043e \u0441 \u043a\u0430\u043d\u0430\u043b\u0430...",
        'videos_found':       "[+] \u041d\u0430\u0439\u0434\u0435\u043d\u043e \u0432\u0438\u0434\u0435\u043e: {count}",
        'timeout_list':       "[!] \u0422\u0430\u0439\u043c\u0430\u0443\u0442 \u043f\u043e\u043b\u0443\u0447\u0435\u043d\u0438\u044f \u0441\u043f\u0438\u0441\u043a\u0430 (10 \u043c\u0438\u043d).",
        'ytdlp_error':        "[!] yt-dlp \u043e\u0448\u0438\u0431\u043a\u0430: {error}",
        'video_info':         "    -> {title} | {duration} | {width}x{height}",
        'frames_for_ocr':     "    -> {count} \u043a\u0430\u0434\u0440\u043e\u0432 \u0434\u043b\u044f OCR",
        'found_at':           "    [\u2713] \u041d\u0410\u0419\u0414\u0415\u041d\u041e \u043d\u0430 {ts}s -> {link}",
        'frame_saved':        "        \u043a\u0430\u0434\u0440: {fname}",
        'ocr_text_label':     "        \u0442\u0435\u043a\u0441\u0442: {text}",
        'debug_frame':        "    [i] \u041e\u0442\u043b\u0430\u0434\u043e\u0447\u043d\u044b\u0439 \u043a\u0430\u0434\u0440: {path}",
        'ocr_error':          "    [!] OCR \u043e\u0448\u0438\u0431\u043a\u0430 ts={ts}: {error}",
        'grab_error':         "    [!] grab_frame \u043e\u0448\u0438\u0431\u043a\u0430 ts={ts}: {error}",
        'no_videos':          "[!] \u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u044c \u0441\u043f\u0438\u0441\u043e\u043a \u0432\u0438\u0434\u0435\u043e.",
        'limit_msg':          "[*] \u041e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d\u0438\u0435: \u043e\u0431\u0440\u0430\u0431\u0430\u0442\u044b\u0432\u0430\u044e \u043f\u0435\u0440\u0432\u044b\u0435 {count}",
        'progress_reset':     "[*] \u041f\u0440\u043e\u0433\u0440\u0435\u0441\u0441 \u0441\u0431\u0440\u043e\u0448\u0435\u043d: {path}",
        'interrupt':          "\n[!] \u041f\u0440\u0435\u0440\u044b\u0432\u0430\u043d\u0438\u0435. \u0421\u043e\u0445\u0440\u0430\u043d\u044f\u044e \u043f\u0440\u043e\u0433\u0440\u0435\u0441\u0441...",
        'progress_saved':     "[+] \u041f\u0440\u043e\u0433\u0440\u0435\u0441\u0441 \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d.",
        'progress_info':      "    \u043f\u0440\u043e\u0433\u0440\u0435\u0441\u0441: {done} \u043e\u0431\u0440., {skip} \u043f\u0440\u043e\u043f\u0443\u0449., {found} \u0441 \u043d\u0430\u0445\u043e\u0434\u043a\u0430\u043c\u0438 | \u043f\u0440\u043e\u0448\u043b\u043e: {elapsed}",
        'done_header':        "\u0413\u041e\u0422\u041e\u0412\u041e",
        'processed_videos':   "  \u041e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u043d\u043e \u0432\u0438\u0434\u0435\u043e:      {count}",
        'skipped_videos':     "  \u041f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e (\u0443\u0436\u0435 \u0431\u044b\u043b\u043e):  {count}",
        'found_videos':       "  \u0412\u0438\u0434\u0435\u043e \u0441 \u043d\u0430\u0445\u043e\u0434\u043a\u0430\u043c\u0438:     {count}",
        'progress_file':      "  \u041f\u0440\u043e\u0433\u0440\u0435\u0441\u0441/\u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u044b:   {path}",
        'frames_dir':         "  \u041a\u0430\u0434\u0440\u044b:                 {path}",
        'no_metadata':        "\u043d\u0435\u0442 \u043c\u0435\u0442\u0430\u0434\u0430\u043d\u043d\u044b\u0445",
        'too_short':          "\u0441\u043b\u0438\u0448\u043a\u043e\u043c \u043a\u043e\u0440\u043e\u0442\u043a\u043e\u0435",
        'no_direct_url':      "\u043d\u0435\u0442 \u043f\u0440\u044f\u043c\u043e\u0433\u043e URL",
        'no_timestamps':      "\u043d\u0435\u0442 \u0442\u0430\u0439\u043c\u043a\u043e\u0434\u043e\u0432",
        'stats_header':       "\u0421\u0423\u0429\u0415\u0421\u0422\u0412\u0423\u042e\u0429\u0418\u0415 \u041f\u041e\u0418\u0421\u041a\u0418",
        'stats_text':         "     \u0442\u0435\u043a\u0441\u0442: {text} | \u043a\u0430\u043d\u0430\u043b: {channel}",
        'stats_counts':       "     \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u043d\u043e: {done} | \u0441 \u043d\u0430\u0445\u043e\u0434\u043a\u0430\u043c\u0438: {found}",
        'stats_read_error':   "  {idx}. {path} -- \u043e\u0448\u0438\u0431\u043a\u0430 \u0447\u0442\u0435\u043d\u0438\u044f: {error}",
        'stats_detail_prompt':"\n\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c \u0434\u0435\u0442\u0430\u043b\u0438 \u043f\u043e \u043d\u043e\u043c\u0435\u0440\u0443 (0 = \u043d\u0430\u0437\u0430\u0434)",
        'details_header':     "\u0414\u0415\u0422\u0410\u041b\u0418: {path}",
        'found_label':        " \u2713 {count} \u043d\u0430\u0445\u043e\u0434\u043e\u043a",
        'menu_header':        "youtube-text-finder",
        'menu_1':             "  1. \u041d\u0430\u0447\u0430\u0442\u044c \u043d\u043e\u0432\u044b\u0439 \u043f\u043e\u0438\u0441\u043a",
        'menu_2':             "  2. \u041f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0443\u044e\u0449\u0438\u0439",
        'menu_3':             "  3. \u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430",
        'menu_lang':          "  4. \u042f\u0437\u044b\u043a / Language",
        'menu_exit':          "  5. \u0412\u044b\u0445\u043e\u0434",
        'choice':             "\n\u0412\u044b\u0431\u043e\u0440",
        'channel_url_prompt': "URL \u043a\u0430\u043d\u0430\u043b\u0430",
        'text_prompt':        "\u0422\u0435\u043a\u0441\u0442 \u0434\u043b\u044f \u043f\u043e\u0438\u0441\u043a\u0430",
        'interval_prompt':    "\u0418\u043d\u0442\u0435\u0440\u0432\u0430\u043b \u043a\u0430\u0434\u0440\u043e\u0432 (\u0441\u0435\u043a\u0443\u043d\u0434\u044b)",
        'limit_prompt':       "\u041b\u0438\u043c\u0438\u0442 \u0432\u0438\u0434\u0435\u043e (0 = \u0432\u0441\u0435)",
        'debug_prompt':       "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u043e\u0442\u043b\u0430\u0434\u043e\u0447\u043d\u044b\u0439 \u043f\u0435\u0440\u0432\u044b\u0439 \u043a\u0430\u0434\u0440? (y/n)",
        'save_all_prompt':    "\u0421\u043e\u0445\u0440\u0430\u043d\u044f\u0442\u044c \u0412\u0421\u0415 \u043a\u0430\u0434\u0440\u044b \u0432 frames_debug/? (y/n)",
        'skip_checks_prompt': "\u041f\u0440\u043e\u043f\u0443\u0441\u0442\u0438\u0442\u044c \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443 \u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u043e\u0432? (y/n)",
        'empty_url':          "[!] \u041f\u0443\u0441\u0442\u043e\u0439 URL.",
        'empty_text':         "[!] \u041f\u0443\u0441\u0442\u043e\u0439 \u0442\u0435\u043a\u0441\u0442.",
        'tools_header':       "\n[*] \u041f\u0440\u043e\u0432\u0435\u0440\u044f\u044e \u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u044b...",
        'tools_fail':         "[!] \u041d\u0435 \u0432\u0441\u0435 \u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u044b \u043d\u0430 \u043c\u0435\u0441\u0442\u0435. \u0417\u0430\u043f\u0443\u0441\u0442\u0438 run.bat.",
        'resume_no_files':    "[!] \u041d\u0435\u0442 progress-\u0444\u0430\u0439\u043b\u043e\u0432. \u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u043d\u0430\u0447\u043d\u0438 \u043d\u043e\u0432\u044b\u0439 \u043f\u043e\u0438\u0441\u043a.",
        'resume_entry':       "  {idx}. {path}  (\u0442\u0435\u043a\u0441\u0442: {text})",
        'resume_select':      "\u041d\u043e\u043c\u0435\u0440",
        'resume_info':        "[*] \u041f\u0440\u043e\u0434\u043e\u043b\u0436\u0430\u044e: \u0442\u0435\u043a\u0441\u0442={text}, \u043a\u0430\u043d\u0430\u043b={channel}",
        'invalid_choice':     "[!] \u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u044b\u0439 \u0432\u044b\u0431\u043e\u0440.",
        'goodbye':            "\u041f\u043e\u043a\u0430.",
        'lang_prompt':        "Select language / \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u044f\u0437\u044b\u043a:\n  1. English\n  2. \u0420\u0443\u0441\u0441\u043a\u0438\u0439",
        'invalid_value':      "[!] \u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u043e\u0435 \u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435, \u0431\u0435\u0440\u0443 \u0434\u0435\u0444\u043e\u043b\u0442: {default}",
    },
}


def T(key, **kwargs):
    s = STRINGS.get(LANG, STRINGS['en']).get(key) or STRINGS['en'].get(key, key)
    return s.format(**kwargs) if kwargs else s


# ---------------------- EASYOCR ----------------------

def get_reader():
    global _reader
    if _reader is None:
        print(T('easyocr_init'))
        _reader = easyocr.Reader(['en'], gpu=True, verbose=False)
        print(T('easyocr_ready', device=_reader.device))
    return _reader


# ---------------------- OUTPUT HELPERS ----------------------

def hr(char="=", n=60):
    print(char * n)


def header(title):
    print()
    hr()
    print(f"  {title}")
    hr()


def ask(prompt, default=None, cast=str):
    suffix = f" [{default}]" if default is not None else ""
    try:
        raw = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        print()
        return default
    if not raw and default is not None:
        return default
    try:
        return cast(raw)
    except (ValueError, TypeError):
        print(T('invalid_value', default=default))
        return default


# ---------------------- TOOL CHECK ----------------------

def check_tools():
    ok = True
    for tool in ("yt-dlp", "ffmpeg", "deno"):
        r = subprocess.run(f"where {tool}", capture_output=True, shell=True, text=True)
        if r.returncode != 0:
            print(T('tool_not_found', tool=tool))
            ok = False
        else:
            path = r.stdout.strip().splitlines()[0]
            print(T('tool_found', tool=tool, path=path))
    try:
        get_reader()
    except Exception as e:
        print(T('easyocr_fail', error=e))
        ok = False
    return ok


# ---------------------- CHANNEL IMPORT ----------------------

def get_channel_videos(channel_url: str):
    print(T('getting_videos'))
    print(f"    {channel_url}")
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--no-warnings",
             "--print", "%(id)s\t%(title)s", channel_url],
            capture_output=True, text=True, timeout=600
        )
    except subprocess.TimeoutExpired:
        print(T('timeout_list'))
        return []

    if result.returncode != 0:
        print(T('ytdlp_error', error=result.stderr.strip()[:500]))
        return []

    videos = []
    for line in result.stdout.strip().splitlines():
        if "\t" not in line:
            continue
        vid, title = line.split("\t", 1)
        vid = vid.strip()
        if not vid:
            continue
        videos.append({
            "id": vid,
            "title": title.strip(),
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    print(T('videos_found', count=len(videos)))
    return videos


def get_video_meta(url: str):
    try:
        result = subprocess.run(
            ["yt-dlp", "--js-runtimes", "deno", "--no-warnings",
             "--print", "%(title)s\t%(duration)s\t%(width)s\t%(height)s",
             url],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return None
        parts = result.stdout.strip().split("\t")
        if len(parts) != 4:
            return None
        title, duration, width, height = parts
        return {
            "title": title,
            "duration": int(float(duration)) if duration not in ("NA", "") else 0,
            "width": int(width) if width not in ("NA", "") else 0,
            "height": int(height) if height not in ("NA", "") else 0,
        }
    except Exception as e:
        print(f"[!] meta error: {e}")
        return None


# ---------------------- OCR / FUZZY SEARCH ----------------------

def find_text_match(ocr_text: str, search_text: str, max_l_dist: int) -> bool:
    if len(search_text) < DEFAULTS["min_text_len"]:
        return False
    return len(find_near_matches(search_text.lower(), ocr_text.lower(),
                                 max_l_dist=max_l_dist)) > 0


# ---------------------- SINGLE VIDEO PROCESSING ----------------------

def get_direct_url(url: str) -> str | None:
    try:
        result = subprocess.run(
            ["yt-dlp", "--js-runtimes", "deno", "--no-warnings",
             "--get-url", "-f",
             "bestvideo[ext=mp4][height<=1080]/best[ext=mp4]/best", url],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return None
        line = result.stdout.strip().splitlines()[0]
        return line if line.startswith("http") else None
    except Exception as e:
        print(f"[!] get_direct_url error: {e}")
        return None


def grab_frame(direct_url: str, ts: int) -> np.ndarray | None:
    cmd = [
        "ffmpeg", "-loglevel", "error",
        "-hwaccel", "cuda",
        "-ss", str(ts),
        "-i", direct_url,
        "-vframes", "1",
        "-vf", "scale=1280:720:flags=lanczos",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        raw = result.stdout
        expected = 1280 * 720 * 3
        if len(raw) < expected:
            return None
        return np.frombuffer(raw[:expected], np.uint8).reshape((720, 1280, 3))
    except subprocess.TimeoutExpired:
        return None
    except Exception as e:
        print(T('grab_error', ts=ts, error=e))
        return None


def text_dir(search_text: str) -> str:
    safe = "".join(c for c in search_text if c.isalnum() or c in "_- ")[:40].strip()
    return safe or "unknown"


def process_video(url, search_text, interval, ocr_lang, max_l_dist,
                  min_duration, debug_frame=False, skip_checks=False, save_all=False):
    meta = get_video_meta(url)
    if not meta:
        return {"status": "failed", "error": T('no_metadata')}

    if meta["duration"] and meta["duration"] < min_duration:
        return {"status": "skipped", "reason": T('too_short')}

    duration = meta["duration"]
    print(T('video_info', title=meta['title'], duration=timedelta(seconds=duration),
            width=meta['width'], height=meta['height']))

    direct_url = get_direct_url(url)
    if not direct_url:
        return {"status": "failed", "error": T('no_direct_url')}

    video_id = url.split("v=")[-1].split("&")[0]
    timestamps = list(range(interval, duration, interval)) if duration else []
    if not timestamps:
        return {"status": "skipped", "reason": T('no_timestamps')}

    print(T('frames_for_ocr', count=len(timestamps)))

    found_at = []
    reader = get_reader()

    tdir = text_dir(search_text)
    found_dir = os.path.join(FRAMES_ROOT, tdir)
    all_frames_dir = os.path.join("frames_debug", tdir, video_id)
    if save_all:
        os.makedirs(all_frames_dir, exist_ok=True)

    FETCH_WORKERS = 6
    _SENTINEL = object()
    frame_queue = queue.Queue(maxsize=FETCH_WORKERS * 2)

    def fetch_all():
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            futures = {pool.submit(grab_frame, direct_url, ts): ts
                       for ts in timestamps}
            results = {}
            for future in as_completed(futures):
                ts = futures[future]
                results[ts] = future.result()
            for ts in timestamps:
                frame_queue.put((ts, results.get(ts)))
        frame_queue.put(_SENTINEL)

    fetcher = threading.Thread(target=fetch_all, daemon=True)
    fetcher.start()

    try:
        while True:
            item = frame_queue.get()
            if item is _SENTINEL:
                break
            ts, frame = item
            if frame is None:
                continue

            if save_all:
                ts_str = str(timedelta(seconds=ts)).replace(":", "-")
                cv2.imwrite(f"{all_frames_dir}/{ts_str}.png", frame)

            if debug_frame and not found_at and ts == timestamps[0]:
                os.makedirs(found_dir, exist_ok=True)
                dbg = os.path.join(found_dir, f"_debug_{video_id}_first.png")
                cv2.imwrite(dbg, frame)
                print(T('debug_frame', path=dbg))

            try:
                ocr_result = reader.readtext(frame, detail=0, paragraph=True)
                ocr_text = "\n".join(ocr_result)
            except Exception as e:
                print(T('ocr_error', ts=ts, error=e))
                continue

            if not ocr_text.strip():
                continue

            if find_text_match(ocr_text, search_text, max_l_dist):
                found_at.append(ts)
                os.makedirs(found_dir, exist_ok=True)
                ts_str = str(timedelta(seconds=ts)).zfill(8).replace(":", "-")
                fname = os.path.join(found_dir, f"{video_id}_{ts_str}.png")
                cv2.imwrite(fname, frame)
                link = f"https://youtu.be/{video_id}?t={ts}"
                print(T('found_at', ts=ts, link=link))
                print(T('frame_saved', fname=fname))
                print(T('ocr_text_label', text=ocr_text.strip()[:200]))

    except KeyboardInterrupt:
        print(T('interrupt'))
        raise

    return {"status": "done", "found_at": found_at}


# ---------------------- PROGRESS (JSON) ----------------------

def load_progress(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if "nick" in data and "text" not in data:
            data["text"] = data.pop("nick")
        return data
    return {"processed": {}}


def save_progress(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def progress_path_for(search_text: str, channel_url=""):
    safe_text = "".join(c for c in search_text if c.isalnum() or c in "_-")[:30]
    channel_slug = channel_url.rstrip("/").split("/")[-1].lstrip("@")[:20]
    if channel_slug:
        return f"progress_{channel_slug}_{safe_text}.json"
    return f"progress_{safe_text}.json"


# ---------------------- MAIN CHANNEL LOOP ----------------------

def run_search(channel_url, search_text, interval, ocr_lang, max_l_dist,
               min_duration, limit, reset=False, debug_frame=False,
               skip_checks=False, save_all=False):
    progress_path = progress_path_for(search_text, channel_url)

    if reset and os.path.exists(progress_path):
        os.remove(progress_path)
        print(T('progress_reset', path=progress_path))

    progress = load_progress(progress_path)
    progress.setdefault("channel_url", channel_url)
    progress.setdefault("text", search_text)
    progress.setdefault("processed", {})

    videos = get_channel_videos(channel_url)
    if not videos:
        print(T('no_videos'))
        return

    if limit > 0:
        videos = videos[:limit]
        print(T('limit_msg', count=len(videos)))

    total = len(videos)
    done_count = 0
    skip_count = 0
    found_videos = 0
    start = time.time()

    for i, v in enumerate(videos, 1):
        vid = v["id"]
        if vid in progress["processed"] and \
           progress["processed"][vid].get("status") == "done":
            skip_count += 1
            continue

        print(f"\n[{i}/{total}] {v['title']}")
        progress["processed"][vid] = {"title": v["title"], "status": "in_progress"}
        save_progress(progress_path, progress)

        try:
            result = process_video(
                v["url"], search_text, interval, ocr_lang, max_l_dist,
                min_duration, debug_frame=debug_frame,
                skip_checks=skip_checks, save_all=save_all
            )
            progress["processed"][vid] = {
                "title": v["title"],
                "url": v["url"],
                **result,
                "processed_at": datetime.now().isoformat(timespec="seconds"),
            }
            if result.get("status") == "done":
                done_count += 1
                if result.get("found_at"):
                    found_videos += 1
        except KeyboardInterrupt:
            print(T('interrupt'))
            save_progress(progress_path, progress)
            print(T('progress_saved'))
            return
        except Exception as e:
            progress["processed"][vid] = {
                "title": v["title"], "status": "failed",
                "error": str(e)[:200],
                "processed_at": datetime.now().isoformat(timespec="seconds"),
            }

        save_progress(progress_path, progress)
        elapsed = time.time() - start
        print(T('progress_info', done=done_count, skip=skip_count,
                found=found_videos, elapsed=timedelta(seconds=int(elapsed))))

    header(T('done_header'))
    print(T('processed_videos', count=done_count))
    print(T('skipped_videos', count=skip_count))
    print(T('found_videos', count=found_videos))
    print(T('progress_file', path=progress_path))
    print(T('frames_dir', path=f"{FRAMES_ROOT}/{text_dir(search_text)}/"))
    if found_videos:
        hr("-")
        for vid, info in progress["processed"].items():
            if info.get("found_at"):
                print(f"\n  {info['title']}")
                print(f"  {info.get('url', f'https://youtu.be/{vid}')}")
                for ts in info["found_at"]:
                    print(f"    https://youtu.be/{vid}?t={ts}")
    hr()


# ---------------------- STATISTICS ----------------------

def show_stats():
    files = glob.glob("progress_*.json")
    if not files:
        print("[!] No progress files found.")
        return

    header(T('stats_header'))
    for idx, path in enumerate(files, 1):
        try:
            data = load_progress(path)
            processed = data.get("processed", {})
            done = sum(1 for v in processed.values() if v.get("status") == "done")
            found = sum(1 for v in processed.values() if v.get("found_at"))
            search_text = data.get("text") or data.get("nick", "?")
            channel = data.get("channel_url", "?")
            print(f"  {idx}. {path}")
            print(T('stats_text', text=search_text, channel=channel))
            print(T('stats_counts', done=done, found=found))
            print()
        except Exception as e:
            print(T('stats_read_error', idx=idx, path=path, error=e))

    choice = ask(T('stats_detail_prompt'), 0, int)
    if 1 <= choice <= len(files):
        data = load_progress(files[choice - 1])
        header(T('details_header', path=files[choice - 1]))
        for vid, info in data.get("processed", {}).items():
            found_list = info.get("found_at", [])
            mark = T('found_label', count=len(found_list)) if found_list else ""
            status = info.get("status", "?")
            print(f"  [{status}]{mark} {info.get('title', vid)}")
            if found_list:
                for ts in found_list:
                    print(f"      -> https://youtu.be/{vid}?t={ts}")


# ---------------------- INTERACTIVE MENU ----------------------

def menu():
    global LANG
    while True:
        header(T('menu_header'))
        print(T('menu_1'))
        print(T('menu_2'))
        print(T('menu_3'))
        print(T('menu_lang'))
        print(T('menu_exit'))
        choice = ask(T('choice'), 1, int)

        if choice == 1:
            print()
            try:
                channel = input(f"{T('channel_url_prompt')}: ").strip()
                search_text = input(f"{T('text_prompt')}: ").strip()
            except EOFError:
                print()
                continue
            if not channel:
                print(T('empty_url'))
                continue
            if not search_text:
                print(T('empty_text'))
                continue
            interval = ask(T('interval_prompt'), DEFAULTS["interval"], int)
            limit = ask(T('limit_prompt'), 0, int)
            debug = ask(T('debug_prompt'), "n").lower() == "y"
            save_all = ask(T('save_all_prompt'), "n").lower() == "y"
            skip = ask(T('skip_checks_prompt'), "n").lower() == "y"

            if not skip:
                print(T('tools_header'))
                if not check_tools():
                    print(T('tools_fail'))
                    continue

            run_search(
                channel_url=channel, search_text=search_text,
                interval=interval, ocr_lang=DEFAULTS["ocr_lang"],
                max_l_dist=DEFAULTS["max_l_dist"],
                min_duration=DEFAULTS["min_video_duration"],
                limit=limit, debug_frame=debug, skip_checks=skip,
                save_all=save_all
            )

        elif choice == 2:
            files = glob.glob("progress_*.json")
            if not files:
                print(T('resume_no_files'))
                continue
            print()
            for idx, p in enumerate(files, 1):
                data = load_progress(p)
                t = data.get("text") or data.get("nick", "?")
                print(T('resume_entry', idx=idx, path=p, text=t))
            num = ask(T('resume_select'), 1, int)
            if not (1 <= num <= len(files)):
                continue
            data = load_progress(files[num - 1])
            t = data.get("text") or data.get("nick", "")
            print(T('resume_info', text=t, channel=data.get('channel_url')))
            interval = ask(T('interval_prompt'), DEFAULTS["interval"], int)
            skip = ask(T('skip_checks_prompt'), "n").lower() == "y"
            if not skip and not check_tools():
                continue

            run_search(
                channel_url=data["channel_url"], search_text=t,
                interval=interval, ocr_lang=DEFAULTS["ocr_lang"],
                max_l_dist=DEFAULTS["max_l_dist"],
                min_duration=DEFAULTS["min_video_duration"],
                limit=0, skip_checks=skip
            )

        elif choice == 3:
            show_stats()

        elif choice == 4:
            print()
            print(T('lang_prompt'))
            lang_choice = ask("", 1, int)
            if lang_choice == 1:
                LANG = 'en'
            elif lang_choice == 2:
                LANG = 'ru'

        elif choice == 5:
            print(T('goodbye'))
            return
        else:
            print(T('invalid_choice'))


# ---------------------- ENTRY POINT ----------------------

def main():
    global LANG

    parser = argparse.ArgumentParser(
        description="Search for text in YouTube channel videos via OCR."
    )
    parser.add_argument("channel_url", nargs="?", help="Channel URL")
    parser.add_argument("search_text", nargs="?", help="Text to search for")
    parser.add_argument("--interval", type=int, default=DEFAULTS["interval"],
                        help=f"Frame interval in seconds (default {DEFAULTS['interval']})")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only first N videos (0 = all)")
    parser.add_argument("--reset", action="store_true",
                        help="Reset progress and start over")
    parser.add_argument("--debug-frame", action="store_true",
                        help="Save first frame of each video for inspection")
    parser.add_argument("--skip-checks", action="store_true",
                        help="Skip tool availability checks at startup")
    parser.add_argument("--save-all-frames", action="store_true",
                        help="Save all extracted frames to frames_debug/")
    parser.add_argument("--lang", default="en", choices=["en", "ru"],
                        help="Interface language (default: en)")
    args = parser.parse_args()
    LANG = args.lang

    if args.channel_url and args.search_text:
        if not args.skip_checks and not check_tools():
            sys.exit(1)
        run_search(
            channel_url=args.channel_url, search_text=args.search_text,
            interval=args.interval, ocr_lang=DEFAULTS["ocr_lang"],
            max_l_dist=DEFAULTS["max_l_dist"],
            min_duration=DEFAULTS["min_video_duration"],
            limit=args.limit, reset=args.reset,
            debug_frame=args.debug_frame, skip_checks=args.skip_checks,
            save_all=args.save_all_frames
        )
    elif args.channel_url or args.search_text:
        parser.print_usage()
        sys.exit(1)
    else:
        menu()


if __name__ == "__main__":
    main()
