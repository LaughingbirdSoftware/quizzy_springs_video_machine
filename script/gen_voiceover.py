#!/usr/bin/env python3
"""Generate voiceover for the quiz using ElevenLabs with-timestamps endpoint."""
import os, sys, json, base64, time, threading, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths
paths.load_env()
paths.ensure_dirs()

API_KEY = os.environ["ELEVENLABS_API_KEY"]
VOICE_ID = "cgSgspJ2msm6clMCkdW9"
MODEL = "eleven_multilingual_v2"
VS = {"stability": 0.45, "similarity_boost": 0.85, "style": 0.3, "use_speaker_boost": True}
URL = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/with-timestamps"
AUDIO_DIR = paths.AUDIO_DIR
FPS = 30

print_lock = threading.Lock()
def log(*a):
    with print_lock:
        print(*a, flush=True)

def find_letter_frames(text, alignment, fps=FPS):
    chars = alignment.get("characters", list(text))
    starts = alignment.get("character_start_times_seconds", [])
    frames = {}
    # walk through chars list and detect 'A:', 'B:', 'C:', 'D:'
    s = "".join(chars)
    for letter in "ABCD":
        pos = s.find(f"{letter}:")
        if pos >= 0 and pos < len(starts):
            frames[letter] = int(starts[pos] * fps)
    return frames

def tts(text, retries=4):
    payload = {"text": text, "model_id": MODEL, "voice_settings": VS,
               "output_format": "mp3_44100_128"}
    delay = 5
    for attempt in range(retries + 1):
        try:
            r = requests.post(URL, headers={"xi-api-key": API_KEY,
                "Content-Type": "application/json"}, json=payload, timeout=120)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                log(f"  429 rate-limited, sleeping {delay}s (attempt {attempt+1})")
                time.sleep(delay); delay *= 2; continue
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        except requests.RequestException as e:
            log(f"  network err {e}, sleeping {delay}s")
            time.sleep(delay); delay *= 2
    raise RuntimeError(f"failed after {retries} retries: {text[:60]}")

def job(spec):
    name, text, save_align = spec
    out_mp3 = AUDIO_DIR / f"{name}.mp3"
    if out_mp3.exists() and out_mp3.stat().st_size > 1000:
        log(f"[skip] {name} (exists)")
        if save_align:
            return name, "skipped"
        return name, "skipped"
    t0 = time.time()
    resp = tts(text)
    audio = base64.b64decode(resp["audio_base64"])
    out_mp3.write_bytes(audio)
    if save_align:
        align = resp.get("alignment") or {}
        (AUDIO_DIR / f"{name}.json").write_text(json.dumps(align))
        # extract letter frames if this looks like options text
        if "A:" in text and "B:" in text:
            qnum = name.split("_")[1]  # e.g. q01
            lf = find_letter_frames(text, align)
            (AUDIO_DIR / f"vo_{qnum}_letter_frames.json").write_text(json.dumps(lf))
            log(f"[done] {name} ({time.time()-t0:.1f}s) letters={lf}")
            return name, lf
    log(f"[done] {name} ({time.time()-t0:.1f}s)")
    return name, None

def main():
    q = json.loads(paths.QUESTIONS_FILE.read_text())
    jobs = []
    jobs.append(("vo_intro", q["intro"], False))
    jobs.append(("vo_outro", q["outro"], False))
    for item in q["questions"]:
        n = f"q{item['n']:02d}"
        qt = f"Question {item['n']}. {item['question']}"
        o = item["options"]
        opts_text = f"Is it A: {o['A']}. B: {o['B']}. C: {o['C']}. Or D: {o['D']}."
        ans_text = f"The answer is {item['answer']}! {o[item['answer']]}. {item['fun_fact']}"
        jobs.append((f"vo_{n}_question", qt, False))
        jobs.append((f"vo_{n}_options", opts_text, True))
        jobs.append((f"vo_{n}_answer", ans_text, False))
    log(f"Total VO jobs: {len(jobs)}")

    results = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(job, j): j[0] for j in jobs}
        done = 0
        for f in as_completed(futs):
            name = futs[f]
            try:
                results[name] = f.result()
                done += 1
                if done % 10 == 0:
                    log(f"--- progress: {done}/{len(jobs)} ---")
            except Exception as e:
                log(f"[FAIL] {name}: {e}")
                results[name] = ("error", str(e))
    log(f"Completed. {sum(1 for v in results.values() if not (isinstance(v,tuple) and v[0]=='error'))}/{len(jobs)} ok")
    # Letter-frame summary
    lfs = {k: v[1] for k, v in results.items() if k.endswith("_options") and isinstance(v, tuple) and isinstance(v[1], dict)}
    log(f"Letter-frame extractions: {len(lfs)}/20")

    durations = {}
    for mp3 in sorted(AUDIO_DIR.glob("vo_*.mp3")):
        out = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(mp3),
        ], text=True).strip()
        durations[mp3.stem] = float(out)
    paths.DURATIONS_FILE.write_text(json.dumps(durations, indent=2, sort_keys=True))
    log(f"Wrote {paths.DURATIONS_FILE} ({len(durations)} entries)")

if __name__ == "__main__":
    main()
