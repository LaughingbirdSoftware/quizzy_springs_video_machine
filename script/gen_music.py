#!/usr/bin/env python3
"""Generate 3 music tracks via ElevenLabs /v1/music/compose, then loudnorm."""
import os, sys, subprocess, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
for ln in (ROOT / ".env").read_text().splitlines():
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
API = os.environ["ELEVENLABS_API_KEY"]
MUSIC_DIR = ROOT / "audio" / "music"
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

TRACKS = [
    ("intro_outro", 30000, -14,
     "Upbeat energetic modern game show theme music, fun and playful, bright synth chords, light percussion, electronic pop, exciting and welcoming, instrumental only, loopable"),
    ("thinking", 60000, -18,
     "Playful bouncy quiz show background music, light synth bells, soft rhythmic percussion, fun and curious mood, medium tempo, modern game show feel, instrumental, seamless loop"),
    ("countdown", 8000, -16,
     "Quick rising tension countdown sting, building energy fast, pulsing synth, suspenseful but fun, instrumental, ends with anticipation"),
]

def compose(prompt, ms, retries=4):
    delay = 5
    for attempt in range(retries + 1):
        r = requests.post("https://api.elevenlabs.io/v1/music/compose",
            headers={"xi-api-key": API, "Content-Type": "application/json"},
            json={"prompt": prompt, "music_length_ms": ms}, timeout=300)
        if r.status_code == 200:
            return r.content
        if r.status_code == 429:
            print(f"  429, sleeping {delay}s"); time.sleep(delay); delay *= 2; continue
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    raise RuntimeError("retries exhausted")

def loudnorm(in_path, out_path, target_lufs):
    # single-pass loudnorm + 0.5s fade in/out
    dur = float(subprocess.check_output(["ffprobe","-v","quiet","-of","csv=p=0",
        "-show_entries","format=duration", str(in_path)]).decode().strip())
    fade_out_start = max(0, dur - 0.5)
    subprocess.run(["ffmpeg","-y","-i", str(in_path),
        "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11,afade=t=in:st=0:d=0.4,afade=t=out:st={fade_out_start:.2f}:d=0.5",
        "-ar","44100","-b:a","192k", str(out_path)], check=True, stderr=subprocess.DEVNULL)

def main():
    for name, ms, lufs, prompt in TRACKS:
        raw = MUSIC_DIR / f"_{name}_raw.mp3"
        final = MUSIC_DIR / f"{name}.mp3"
        if final.exists() and final.stat().st_size > 5000:
            print(f"[skip] {name} (exists)"); continue
        t0 = time.time()
        print(f"[gen ] {name} ({ms/1000:.0f}s, target {lufs} LUFS)")
        audio = compose(prompt, ms)
        raw.write_bytes(audio)
        print(f"  raw ok ({len(audio)/1024:.0f} KB, {time.time()-t0:.1f}s)")
        loudnorm(raw, final, lufs)
        raw.unlink()
        print(f"  loudnormed → {final.name}")
    print("Music done.")

if __name__ == "__main__":
    main()
