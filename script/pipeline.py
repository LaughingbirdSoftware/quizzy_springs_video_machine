#!/usr/bin/env python3
"""Episode pipeline: voiceover → render → assemble.

Usage:
    EPISODE_SLUG=<slug> .venv/bin/python script/pipeline.py

Requires episodes/<slug>/questions.json to already exist (Claude generates it).
Outputs land in episodes/<slug>/{vo,segments,final}/.

Thumbnails and metadata files are NOT generated here — they're produced by
Claude via the Higgsfield MCP and by writing text files directly to
episodes/<slug>/final/.
"""
import os, sys, subprocess, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths

if not paths.SLUG:
    print("ERROR: set EPISODE_SLUG env var. Example:")
    print('  EPISODE_SLUG="2026-05-15-sports" .venv/bin/python script/pipeline.py')
    sys.exit(1)

if not paths.QUESTIONS_FILE.exists():
    print(f"ERROR: missing {paths.QUESTIONS_FILE}")
    print("Create questions.json first (Claude generates this).")
    sys.exit(1)

PY = str(paths.VENV_PY)
SCRIPT_DIR = paths.SCRIPT_DIR

def stage(name, cmd):
    print(f"\n=== {name} ===")
    t0 = time.time()
    result = subprocess.run(cmd, env={**os.environ})
    if result.returncode != 0:
        print(f"FAILED at stage: {name}")
        sys.exit(result.returncode)
    print(f"   {name} done in {time.time()-t0:.1f}s")

def main():
    print(f"Episode: {paths.SLUG}")
    print(f"Output:  {paths.EP_DIR}")

    # Write script.txt from questions.json (no API call)
    import json
    d = json.loads(paths.QUESTIONS_FILE.read_text())
    lines = [f"=== {d.get('title', paths.SLUG)} ===", "", "--- INTRO ---", d["intro"], ""]
    for q in d["questions"]:
        lines.append(f"--- Q{q['n']:02d} [{q['difficulty'].upper()}] {q['category']} | {q.get('era','')} ---")
        lines.append(f"Question {q['n']}. {q['question']}")
        o = q["options"]
        lines.append(f"Is it A: {o['A']}. B: {o['B']}. C: {o['C']}. Or D: {o['D']}.")
        lines.append("[6 SECOND PAUSE — countdown]")
        lines.append(f"The answer is {q['answer']}! {o[q['answer']]}. {q['fun_fact']}")
        lines.append("")
    lines += ["--- OUTRO ---", d["outro"], ""]
    paths.SCRIPT_TXT.write_text("\n".join(lines))

    stage("Voiceover (ElevenLabs, 62 TTS calls)", [PY, str(SCRIPT_DIR/"gen_voiceover.py")])
    stage("Pillow frame render (~20k frames)",    [PY, str(SCRIPT_DIR/"render.py")])
    stage("Audio + transitions + final assembly",  [PY, str(SCRIPT_DIR/"assemble.py")])

    final_video = paths.FINAL_DIR / "video.mp4"
    if final_video.exists():
        size_mb = final_video.stat().st_size / 1024 / 1024
        print(f"\nDONE → {final_video}  ({size_mb:.1f} MB)")
        print(f"\nNext steps for Claude:")
        print(f"  - Generate 3 thumbnails (1280x720) via Higgsfield MCP → episodes/{paths.SLUG}/final/thumbnail_{{1,2,3}}.png")
        print(f"  - Write episodes/{paths.SLUG}/final/{{title_options,description,tags}}.txt")
    else:
        print(f"\nFINAL VIDEO MISSING: expected {final_video}")
        sys.exit(1)

if __name__ == "__main__":
    main()
