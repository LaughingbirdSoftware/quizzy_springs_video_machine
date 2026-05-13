"""Centralized path resolver. All other scripts import from here.

Shared resources (music, sfx, backgrounds, fonts, logo, .env) live at ROOT.
Per-episode resources (questions, VO, segments, final video) live under
ROOT/episodes/<slug>/ when EPISODE_SLUG env var is set.

If EPISODE_SLUG is unset, legacy flat layout is used (root-level audio/,
visuals/segments/, final/, script/questions.json).
"""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- shared (always at root) ---
ASSETS = ROOT / "assets"
FONTS_DIR = ASSETS / "fonts"
LOGO_PATH = ASSETS / "logo.png"
MUSIC_DIR = ROOT / "audio" / "music"
SFX_DIR = ROOT / "audio" / "sfx"
BG_DIR = ROOT / "visuals"  # bg_*.png live here
ENV_FILE = ROOT / ".env"
SCRIPT_DIR = ROOT / "script"
VENV_PY = ROOT / ".venv" / "bin" / "python"

# --- per-episode (or legacy root) ---
SLUG = os.environ.get("EPISODE_SLUG")

if SLUG:
    EP_DIR = ROOT / "episodes" / SLUG
    AUDIO_DIR = EP_DIR / "vo"
    SEG_DIR = EP_DIR / "segments"
    FINAL_DIR = EP_DIR / "final"
    QUESTIONS_FILE = EP_DIR / "questions.json"
    SCRIPT_TXT = EP_DIR / "script.txt"
    DURATIONS_FILE = AUDIO_DIR / "durations.json"
    TIMINGS_FILE = SEG_DIR / "timings.json"
else:
    # Legacy flat layout (original Pop Culture v1)
    EP_DIR = ROOT
    AUDIO_DIR = ROOT / "audio"
    SEG_DIR = ROOT / "visuals" / "segments"
    FINAL_DIR = ROOT / "final"
    QUESTIONS_FILE = ROOT / "script" / "questions.json"
    SCRIPT_TXT = ROOT / "script" / "script.txt"
    DURATIONS_FILE = AUDIO_DIR / "durations.json"
    TIMINGS_FILE = SEG_DIR / "timings.json"

def ensure_dirs():
    for d in [AUDIO_DIR, SEG_DIR, FINAL_DIR]:
        d.mkdir(parents=True, exist_ok=True)

def load_env():
    """Load .env into os.environ if not already set."""
    if not ENV_FILE.exists():
        return
    for ln in ENV_FILE.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
