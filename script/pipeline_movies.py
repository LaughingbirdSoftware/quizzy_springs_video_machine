#!/usr/bin/env python3
"""Movies episode pipeline: voiceover → render_movies → assemble_movies.

Usage:
    EPISODE_SLUG=<slug> .venv/bin/python script/pipeline_movies.py

Requires episodes/<slug>/questions.json to exist (with `main_image` and
`reveal_image` paths per question, plus the standard intro/outro/options/answer
fields). The questions.json schema is a superset of the trivia format —
gen_voiceover.py reads the same fields and ignores the image references.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths

if not paths.SLUG:
    print("ERROR: set EPISODE_SLUG env var. Example:")
    print('  EPISODE_SLUG="2026-05-15-90s-romcoms" .venv/bin/python script/pipeline_movies.py')
    sys.exit(1)

if not paths.QUESTIONS_FILE.exists():
    print(f"ERROR: missing {paths.QUESTIONS_FILE}")
    sys.exit(1)

PY = str(paths.VENV_PY)
SCRIPT_DIR = paths.SCRIPT_DIR


def stage(name: str, cmd: list[str]):
    print(f"\n=== {name} ===")
    t0 = time.time()
    result = subprocess.run(cmd, env={**os.environ})
    if result.returncode != 0:
        print(f"FAILED at stage: {name}")
        sys.exit(result.returncode)
    print(f"   {name} done in {time.time() - t0:.1f}s")


def write_script_txt():
    """Build script.txt from questions.json so gen_voiceover.py reads what it needs."""
    d = json.loads(paths.QUESTIONS_FILE.read_text())
    lines = [f"=== {d.get('title', paths.SLUG)} ===", "", "--- INTRO ---", d["intro"], ""]
    for q in d["questions"]:
        lines.append(f"--- Q{q['n']:02d} [{q['difficulty'].upper()}] {q.get('category','')} ---")
        lines.append(f"Question {q['n']}. {q['question']}")
        o = q["options"]
        lines.append(f"Is it A: {o['A']}. B: {o['B']}. C: {o['C']}. Or D: {o['D']}.")
        lines.append("[6 SECOND PAUSE — countdown]")
        lines.append(f"The answer is {q['answer']}! {o[q['answer']]}. {q['fun_fact']}")
        lines.append("")
    lines += ["--- OUTRO ---", d["outro"], ""]
    paths.SCRIPT_TXT.write_text("\n".join(lines))


def main():
    print(f"Episode (movies): {paths.SLUG}")
    print(f"Output:           {paths.EP_DIR}")

    write_script_txt()

    stage("Voiceover (ElevenLabs TTS, style=0.5)",
          [PY, str(SCRIPT_DIR / "gen_voiceover_movies.py")])
    stage("Pillow frame render (movies)",   [PY, str(SCRIPT_DIR / "render_movies.py")])
    stage("Audio + transitions + assembly", [PY, str(SCRIPT_DIR / "assemble_movies.py")])

    final_video = paths.FINAL_DIR / "video.mp4"
    if final_video.exists():
        size_mb = final_video.stat().st_size / 1024 / 1024
        print(f"\nDONE → {final_video}  ({size_mb:.1f} MB)")
        print(f"\nNext steps:")
        print(f"  - Generate 3 thumbnails (1280x720) via Higgsfield MCP → "
              f"episodes/{paths.SLUG}/final/thumbnail_{{1,2,3}}.png")
        print(f"  - Write episodes/{paths.SLUG}/final/{{title_options,description,tags}}.txt")
    else:
        print(f"\nFINAL VIDEO MISSING: expected {final_video}")
        sys.exit(1)


if __name__ == "__main__":
    main()
