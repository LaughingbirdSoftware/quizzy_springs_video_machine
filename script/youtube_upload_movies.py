#!/usr/bin/env python3
"""YouTube upload wrapper that renames video.mp4 → <topic-slug>.mp4 for SEO.

Drop-in replacement for `python youtube_upload.py <slug>` used by the movies
pipeline. Reads questions.json to derive a clean filename from the episode
topic (e.g. "90s-rom-coms.mp4") so that the uploaded filename matches the
content — a minor but real YouTube ranking signal.

Zero edits to youtube_upload.py — we monkey-patch its read_metadata return.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# youtube_upload.py lives at the project root, not in script/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paths
import youtube_upload as yu


def slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s or "quiz")[:80]


def ensure_seo_filename(slug: str) -> Path:
    """Rename final/video.mp4 to final/<topic>.mp4 and add a video.mp4 symlink.

    The symlink keeps the existence-check inside youtube_upload.read_metadata
    happy (it asserts video.mp4 exists). The patched read_metadata then
    swaps the returned path to the SEO-named file before the actual upload.
    """
    final_dir = paths.ROOT / "episodes" / slug / "final"
    qjson = json.loads((paths.ROOT / "episodes" / slug / "questions.json").read_text())
    topic = qjson.get("intro_subtitle") or qjson.get("title") or slug
    # Strip " QUIZ" if the topic ends in it, then slugify
    t = topic.upper().strip()
    for suffix in (" QUIZ", " TRIVIA QUIZ"):
        if t.endswith(suffix):
            t = t[: -len(suffix)].strip()
    name_slug = slugify(t)
    seo_path = final_dir / f"{name_slug}.mp4"
    video_path = final_dir / "video.mp4"

    if video_path.exists() and not video_path.is_symlink() and not seo_path.exists():
        video_path.rename(seo_path)
        # Backwards-compat symlink for any other scripts looking for video.mp4
        video_path.symlink_to(seo_path.name)
        print(f"📝 Renamed video.mp4 → {seo_path.name}  (+ symlink for compatibility)")
    elif seo_path.exists():
        print(f"📝 SEO file already exists: {seo_path.name}")

    return seo_path


def main():
    if len(sys.argv) < 2:
        print("usage: youtube_upload_movies.py <slug>")
        sys.exit(2)
    slug = sys.argv[1]
    seo_path = ensure_seo_filename(slug)

    # Monkey-patch youtube_upload.read_metadata to return the SEO-named file
    orig_read = yu.read_metadata

    def patched(s):
        meta = orig_read(s)
        if seo_path.exists():
            meta["video"] = seo_path
        return meta

    yu.read_metadata = patched
    yu.main()


if __name__ == "__main__":
    main()
