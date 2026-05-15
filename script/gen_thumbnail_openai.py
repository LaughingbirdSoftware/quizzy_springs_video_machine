#!/usr/bin/env python3
"""Generate 3 YouTube thumbnails for the current episode using OpenAI's image API.

Replaces the Higgsfield path for the movies pipeline — gpt-image renders text
accurately (no more "Sleepless in Seella" or "Can YASS this quiz").

Reads:
    episodes/<slug>/questions.json   — for intro_subtitle (used as on-thumbnail text)

Writes:
    episodes/<slug>/final/thumbnail_{1,2,3}.png   — 1280×720 PNGs (≤2 MB each)

Usage:
    EPISODE_SLUG=<slug> .venv/bin/python script/gen_thumbnail_openai.py

The model name is configurable via OPENAI_IMAGE_MODEL env var. Defaults to
gpt-image-2 (released April 2026). If that model is unavailable, fall back
to gpt-image-1 by exporting OPENAI_IMAGE_MODEL=gpt-image-1.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
from pathlib import Path

import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths

paths.load_env()

API_KEY = os.environ["OPENAI_API_KEY"]
MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2")
GEN_SIZE = os.environ.get("OPENAI_IMAGE_SIZE", "1536x1024")  # closest to 16:9 the API offers
ENDPOINT = "https://api.openai.com/v1/images/generations"
THUMB_W, THUMB_H = 1280, 720


def crop_to_16_9(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    w, h = img.size
    target = THUMB_W / THUMB_H
    src = w / h
    if src > target:
        new_w = int(h * target)
        offset = (w - new_w) // 2
        img = img.crop((offset, 0, offset + new_w, h))
    else:
        new_h = int(w / target)
        offset = (h - new_h) // 2
        img = img.crop((0, offset, w, offset + new_h))
    return img.resize((THUMB_W, THUMB_H), Image.LANCZOS)


def generate_one(prompt: str, out_path: Path) -> None:
    print(f"→ gpt request: {out_path.name}", flush=True)
    r = requests.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"model": MODEL, "prompt": prompt, "size": GEN_SIZE, "n": 1},
        timeout=180,
    )
    if r.status_code != 200:
        raise RuntimeError(f"OpenAI error {r.status_code}: {r.text[:400]}")
    data = r.json()["data"][0]
    if "b64_json" in data:
        raw = base64.b64decode(data["b64_json"])
    elif "url" in data:
        raw = requests.get(data["url"], timeout=60).content
    else:
        raise RuntimeError(f"Unexpected response: {data}")
    img = Image.open(io.BytesIO(raw))
    img = crop_to_16_9(img)
    img.save(out_path, "PNG", optimize=True)
    size_kb = out_path.stat().st_size // 1024
    print(f"  ✅ {out_path.name}  ({size_kb} KB)", flush=True)


def thumbnail_prompts(topic: str) -> list[str]:
    """Return 3 distinct thumbnail prompts. `topic` is the on-thumbnail short phrase."""
    topic_caps = topic.upper().strip()
    # Strategy: topic-direct text wins on click-through (per Marc's stats). Each
    # variant uses a different palette/composition so we have aesthetic options.
    return [
        (
            f"Bold YouTube quiz thumbnail. Massive yellow text reading exactly '{topic_caps} QUIZ' "
            f"as the dominant element, centered. Vibrant purple-to-hot-pink gradient background. "
            f"Modern, energetic, high contrast. Composition strictly inside the central 16:9 frame — "
            f"all text and key visual elements fully visible, with at least 8% safe-margin padding "
            f"on all four sides so nothing gets cropped. No movie posters, no celebrity faces, no "
            f"hands. Clean, graphic-design quality typography. The text MUST be spelled correctly: "
            f"'{topic_caps} QUIZ'."
        ),
        (
            f"Bold YouTube quiz thumbnail. Massive bright yellow text reading exactly '20 QUESTIONS' "
            f"on the top half. Below it, slightly smaller white text reading exactly 'CAN YOU SCORE "
            f"20/20?'. Electric blue and magenta neon gradient background. Modern game-show energy. "
            f"Composition strictly inside the central 16:9 frame with 8% safe-margin padding. "
            f"Stylized question mark graphics in the corners as accent only. No real photos. "
            f"Spelling MUST be exact."
        ),
        (
            f"Bold YouTube quiz thumbnail. Massive bright yellow text reading exactly '{topic_caps}' "
            f"centered top half. Below in white, slightly smaller: 'THE TRIVIA QUIZ'. Dark navy "
            f"background with bright magenta and yellow neon accents. Retro arcade aesthetic with "
            f"glowing text edges. Composition strictly inside the central 16:9 frame with 8% safe "
            f"margin. Spelling MUST be exact: '{topic_caps}' and 'THE TRIVIA QUIZ'."
        ),
    ]


def main():
    if not paths.SLUG:
        print("ERROR: set EPISODE_SLUG env var.")
        sys.exit(1)
    qjson = json.loads(paths.QUESTIONS_FILE.read_text())
    topic = qjson.get("intro_subtitle") or qjson.get("title") or "TRIVIA"
    # Strip trailing " QUIZ" if present so we don't print "QUIZ QUIZ"
    topic = topic.upper().strip()
    for suffix in (" QUIZ", " TRIVIA QUIZ"):
        if topic.endswith(suffix):
            topic = topic[: -len(suffix)].strip()
    paths.FINAL_DIR.mkdir(parents=True, exist_ok=True)
    prompts = thumbnail_prompts(topic)
    print(f"Topic on thumbnail: {topic!r}")
    print(f"Model: {MODEL}   Size requested: {GEN_SIZE}")
    for i, p in enumerate(prompts, 1):
        out = paths.FINAL_DIR / f"thumbnail_{i}.png"
        generate_one(p, out)
    print("Done.")


if __name__ == "__main__":
    main()
