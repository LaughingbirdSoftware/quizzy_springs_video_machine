#!/usr/bin/env python3
"""Generate 12 SFX via ElevenLabs /v1/sound-generation."""
import os, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

ROOT = Path(__file__).resolve().parent.parent
for ln in (ROOT / ".env").read_text().splitlines():
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
API = os.environ["ELEVENLABS_API_KEY"]
SFX_DIR = ROOT / "audio" / "sfx"
SFX_DIR.mkdir(parents=True, exist_ok=True)

SFX = [
    ("tick", 0.5, "Sharp clean clock tick, mechanical, crisp single tick"),
    ("correct", 1.5, "Cheerful correct answer chime, bright magical bell, game show success, sparkle"),
    ("whoosh", 0.5, "Quick whoosh transition, smooth swipe, modern game show, energetic"),
    ("whoosh_big", 0.8, "Bigger whoosh sweep for round transitions, dramatic but fun"),
    ("flash_hit", 0.5, "Bright flash impact sound, light burst, magical pop"),
    ("bounce", 0.5, "Cute soft bouncy pop, playful UI chirp"),
    ("drop_thud", 0.5, "Soft cartoon drop landing, playful bounce thud"),
    ("bump_easy", 1.5, "Fun friendly stinger, light cheerful welcoming level intro hit"),
    ("bump_medium", 1.5, "Energetic level-up stinger, medium intensity exciting"),
    ("bump_hard", 2.0, "Dramatic intense stinger, powerful boss-level entrance"),
    ("intro_sting", 2.0, "Big exciting intro stinger, dramatic opener, bright impact with sparkle tail"),
    ("outro_sting", 2.0, "Warm friendly outro sound, satisfying closer, light chime"),
]

def gen(spec, retries=4):
    name, dur, prompt = spec
    out = SFX_DIR / f"{name}.mp3"
    if out.exists() and out.stat().st_size > 1000:
        print(f"[skip] {name}"); return name
    delay = 5
    for attempt in range(retries + 1):
        r = requests.post("https://api.elevenlabs.io/v1/sound-generation",
            headers={"xi-api-key": API, "Content-Type": "application/json"},
            json={"text": prompt, "duration_seconds": dur, "prompt_influence": 0.4},
            timeout=120)
        if r.status_code == 200:
            out.write_bytes(r.content)
            print(f"[done] {name} ({len(r.content)/1024:.0f} KB)")
            return name
        if r.status_code == 429:
            time.sleep(delay); delay *= 2; continue
        raise RuntimeError(f"{name}: HTTP {r.status_code} {r.text[:200]}")
    raise RuntimeError(f"{name}: retries exhausted")

def main():
    with ThreadPoolExecutor(max_workers=3) as p:
        futs = [p.submit(gen, s) for s in SFX]
        for f in as_completed(futs):
            try: f.result()
            except Exception as e: print(f"[FAIL] {e}")
    print(f"SFX done: {len(list(SFX_DIR.glob('*.mp3')))}/12 files")

if __name__ == "__main__":
    main()
