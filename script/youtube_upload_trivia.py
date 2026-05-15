#!/usr/bin/env python3
"""YouTube upload wrapper for the TRIVIA pipeline that renames video.mp4
→ <topic-slug>.mp4 for SEO before delegating to youtube_upload.py.

Drop-in replacement for `python youtube_upload.py <slug>` used by run-episode.sh.
Identical logic to youtube_upload_movies.py but kept separate so the two
pipelines stay decoupled.

Reads intro_subtitle from questions.json to derive a clean filename
(e.g. "sports-trivia-quiz.mp4"), renames the video file, then delegates
to youtube_upload.py via monkey-patched read_metadata.
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
    happy. The patched read_metadata then swaps the returned path to the
    SEO-named file before the actual upload call.
    """
    final_dir = paths.ROOT / "episodes" / slug / "final"
    qjson = json.loads((paths.ROOT / "episodes" / slug / "questions.json").read_text())
    topic = qjson.get("intro_subtitle") or qjson.get("title") or slug
    t = topic.upper().strip()
    for suffix in (" QUIZ", " TRIVIA QUIZ"):
        if t.endswith(suffix):
            t = t[: -len(suffix)].strip()
    name_slug = slugify(t) + "-trivia-quiz"
    seo_path = final_dir / f"{name_slug}.mp4"
    video_path = final_dir / "video.mp4"

    if video_path.exists() and not video_path.is_symlink() and not seo_path.exists():
        video_path.rename(seo_path)
        video_path.symlink_to(seo_path.name)
        print(f"📝 Renamed video.mp4 → {seo_path.name}  (+ symlink for compatibility)")
    elif seo_path.exists():
        print(f"📝 SEO file already exists: {seo_path.name}")

    return seo_path


def main():
    if len(sys.argv) < 2:
        print("usage: youtube_upload_trivia.py <slug>")
        sys.exit(2)
    slug = sys.argv[1]
    seo_path = ensure_seo_filename(slug)

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
