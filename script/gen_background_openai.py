#!/usr/bin/env python3
"""Generate a single themed background for the current episode using OpenAI gpt-image-2.

Usage:
    EPISODE_SLUG=<slug> .venv/bin/python script/gen_background_openai.py \\
        <bg_name> "<topical opener prompt>" [scene|abstract]

Where <bg_name> is one of:
    bg_intro  bg_outro  bg_easy  bg_medium  bg_hard  bg_question  bg_reveal

The script appends a composition tail based on the mode:
  - "scene" mode (default for bg_intro/outro/easy/medium/hard): topical
    out-of-focus background imagery with dim center for text overlay
    (e.g. "blurred 90s living room with old CRT TV").
  - "abstract" mode (default for bg_question/reveal): pure abstract
    gradient with NO objects (since the question/reveal card overlays
    the center).

Output goes to episodes/<slug>/<bg_name>.png  (1920×1080).

Cost: ~$0.06 per call (gpt-image-2 standard, 1536×1024 cropped to 1920×1080).

IP-safety guardrails are baked into both tails — STRICTLY no logos, no
trademarked characters, no celebrity likenesses. Use generic period /
genre cues only (e.g. "generic superhero comic-book burst with halftone
dots and energy lines" — not "Marvel").
"""
from __future__ import annotations

import base64
import io
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
GEN_SIZE = os.environ.get("OPENAI_IMAGE_SIZE", "1536x1024")
ENDPOINT = "https://api.openai.com/v1/images/generations"
OUT_W, OUT_H = 1920, 1080

VALID_NAMES = {
    "bg_intro", "bg_outro", "bg_easy", "bg_medium", "bg_hard",
    "bg_question", "bg_reveal",
}

# Two composition modes:
#
# "themed_scene" — backgrounds that carry topical imagery (a generic 90s
#   living room for a 90s episode, a comic-book burst for a superhero one,
#   stadium lights for sports). Used for bg_intro, bg_outro, bg_easy/
#   medium/hard — cards that overlay LARGE text + branding, where a
#   slightly visible scene reinforces the topic. The prompt requires
#   shallow depth of field, vignette, and a dimmed center so the text
#   overlay stays legible.
#
# "abstract" — pure gradient/atmospheric background with no objects.
#   Used for bg_question and bg_reveal where a full content card sits
#   on top and ANY scene imagery would compete with it.

THEMED_SCENE_TAIL = (
    " Cinematic shallow depth of field. Soft focus, heavy gaussian blur on "
    "the entire scene — the topical imagery should read as out-of-focus "
    "background atmosphere, NOT as a sharp central subject. Strong dark "
    "vignette in the center 60% of the frame so text overlays remain "
    "legible. Soft, desaturated, dreamy. Avoid all sharp focal subjects. "
    "STRICTLY NO logos, NO brand marks, NO trademarked characters, NO "
    "celebrity likenesses, NO recognizable copyrighted IP, NO real-world "
    "team names or symbols. Generic period/genre cues only — evocative, "
    "not specific. NO text in the image. Premium cinematic YouTube quiz "
    "background."
)

ABSTRACT_TAIL = (
    " Cinematic, atmospheric, sophisticated, modern. Pure abstract "
    "atmospheric background. NO central objects, NO devices, NO screens, "
    "NO podiums, NO furniture, NO people, NO animals, NO trophies, NO "
    "text, NO logos. Ambient gradient and abstract atmospheric design "
    "only. Center of frame must be visually clean for text/card overlay. "
    "Premium luxury YouTube quiz background."
)

# Which mode each named slot uses by default.
SCENE_NAMES = {"bg_intro", "bg_outro", "bg_easy", "bg_medium", "bg_hard"}
ABSTRACT_NAMES = {"bg_question", "bg_reveal"}


def crop_to_1920x1080(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    w, h = img.size
    target = OUT_W / OUT_H
    src = w / h
    if src > target:
        new_w = int(h * target)
        offset = (w - new_w) // 2
        img = img.crop((offset, 0, offset + new_w, h))
    else:
        new_h = int(w / target)
        offset = (h - new_h) // 2
        img = img.crop((0, offset, w, offset + new_h))
    return img.resize((OUT_W, OUT_H), Image.LANCZOS)


def generate(prompt: str, out_path: Path) -> None:
    print(f"→ gpt-image request: {out_path.name}", flush=True)
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
    img = crop_to_1920x1080(img)
    img.save(out_path, "PNG", optimize=True)
    print(f"  ✅ {out_path.name}  ({out_path.stat().st_size // 1024} KB)", flush=True)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    name = sys.argv[1].strip()
    if name not in VALID_NAMES:
        print(f"ERROR: <bg_name> must be one of {sorted(VALID_NAMES)}")
        sys.exit(2)
    if not paths.SLUG:
        print("ERROR: set EPISODE_SLUG env var.")
        sys.exit(1)

    # Optional 3rd arg overrides the mode: "scene" or "abstract"
    mode = sys.argv[3].strip().lower() if len(sys.argv) >= 4 else None
    if mode not in (None, "scene", "abstract"):
        print("ERROR: optional <mode> must be 'scene' or 'abstract'.")
        sys.exit(2)
    if mode is None:
        mode = "scene" if name in SCENE_NAMES else "abstract"

    opener = sys.argv[2].strip()
    tail = THEMED_SCENE_TAIL if mode == "scene" else ABSTRACT_TAIL
    prompt = opener + tail
    out = paths.EP_DIR / f"{name}.png"
    paths.EP_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Mode: {mode}")
    generate(prompt, out)


if __name__ == "__main__":
    main()
