#!/usr/bin/env python3
"""Final assembly for the MOVIES quiz pipeline.

Mirrors assemble.py but supports a variable question count + difficulty mix.
Reads the question_order and bumps list written by render_movies.py into
segments/timings.json, then builds per-segment audio, muxes, and xfades into
final/video.mp4.

Audio mixing constants and per-segment audio builders are imported from
assemble.py — we do NOT duplicate that logic.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths
import assemble  # reuse audio builders + mix constants

paths.ensure_dirs()

# Movies-pipeline audio mix overrides. Voice intelligibility is paramount,
# so music sits noticeably lower than the trivia show. These names are
# read by assemble.build_*_audio at call time, so overriding here is enough
# (no edits to assemble.py).
assemble.MIX_MUSIC_INTRO = 0.11   # was 0.16
assemble.MIX_MUSIC_OUTRO = 0.11   # was 0.16
assemble.MIX_MUSIC_QUIZ = 0.13    # was 0.20 — most critical (under VO entire question)
# MIX_MUSIC_BUMP unchanged (0.22) — no VO competing during bumps

SEG = paths.SEG_DIR
SFX = paths.SFX_DIR
FINAL = paths.FINAL_DIR
WORK = paths.EP_DIR / "_work"
WORK.mkdir(parents=True, exist_ok=True)

TIMINGS = json.loads(paths.TIMINGS_FILE.read_text())
QUESTION_ORDER: list[int] = TIMINGS.get("question_order") or sorted(
    int(k[1:]) for k in TIMINGS if k.startswith("q") and k[1:].isdigit()
)
BUMPS_PRESENT: list[str] = TIMINGS.get("bumps", ["easy", "medium", "hard"])


# ---- segment list / order ---------------------------------------------

def _difficulty_of(qn: int) -> str:
    questions = json.loads(paths.QUESTIONS_FILE.read_text())["questions"]
    for q in questions:
        if q["n"] == qn:
            return q.get("difficulty", "medium").lower()
    return "medium"


def build_segment_plan() -> list[tuple[str, str]]:
    """Return ordered list of (kind, name) where kind in {intro, bump, question, outro}."""
    plan: list[tuple[str, str]] = [("intro", "intro")]
    by_level: dict[str, list[int]] = {"easy": [], "medium": [], "hard": []}
    for qn in QUESTION_ORDER:
        by_level[_difficulty_of(qn)].append(qn)
    for level in ("easy", "medium", "hard"):
        if not by_level[level]:
            continue
        plan.append(("bump", level))
        for qn in by_level[level]:
            plan.append(("question", f"q{qn:02d}"))
    plan.append(("outro", "outro"))
    return plan


# ---- per-segment audio + mux ------------------------------------------

def build_all_segments() -> list[Path]:
    muxed = WORK / "muxed"
    muxed.mkdir(exist_ok=True)
    aud = WORK / "aud"
    aud.mkdir(exist_ok=True)

    plan = build_segment_plan()
    out_paths: list[Path] = []

    for idx, (kind, name) in enumerate(plan):
        prefix = f"{idx:02d}"
        if kind == "intro":
            print(f"[audio] {name}")
            audio = aud / "intro.m4a"
            assemble.build_intro_audio(audio)
            video = SEG / "seg_intro.mp4"
            out = muxed / f"{prefix}_intro.mp4"
        elif kind == "bump":
            print(f"[audio] bump_{name}")
            audio = aud / f"bump_{name}.m4a"
            assemble.build_bump_audio(name, audio)
            video = SEG / f"seg_bump_{name}.mp4"
            out = muxed / f"{prefix}_bump_{name}.mp4"
        elif kind == "question":
            qn = int(name[1:])
            print(f"[audio] {name}")
            audio = aud / f"{name}.m4a"
            assemble.build_question_audio(qn, audio)
            video = SEG / f"seg_{name}.mp4"
            out = muxed / f"{prefix}_{name}.mp4"
        elif kind == "outro":
            print(f"[audio] {name}")
            audio = aud / "outro.m4a"
            assemble.build_outro_audio(audio)
            video = SEG / "seg_outro.mp4"
            out = muxed / f"{prefix}_outro.mp4"
        else:
            raise ValueError(kind)
        assemble.mux_segment(video, audio, out)
        out_paths.append(out)

    return out_paths


# ---- dynamic transitions ----------------------------------------------

def generate_transitions(plan: list[tuple[str, str]]):
    """Return transitions list parallel to (len(plan)-1) gaps between segments."""
    transitions: list[tuple[str, float, str | None]] = []
    for i in range(len(plan) - 1):
        a_kind, _ = plan[i]
        b_kind, _ = plan[i + 1]
        if a_kind == "intro" and b_kind == "bump":
            transitions.append(("fadewhite", 0.5, "flash_hit"))
        elif a_kind == "bump" and b_kind == "question":
            transitions.append(("slideleft", 0.4, "whoosh"))
        elif a_kind == "question" and b_kind == "question":
            transitions.append(("slideleft", 0.35, "whoosh"))
        elif a_kind == "question" and b_kind == "bump":
            transitions.append(("wipeleft", 0.7, "whoosh_big"))
        elif a_kind == "question" and b_kind == "outro":
            transitions.append(("fadeblack", 1.0, "outro_sting"))
        else:
            transitions.append(("slideleft", 0.4, "whoosh"))
    return transitions


# ---- chain with xfade -------------------------------------------------

def chain_with_xfade(segments: list[Path], transitions) -> Path:
    assert len(segments) - 1 == len(transitions), \
        f"{len(segments)} segments needs {len(segments)-1} transitions, got {len(transitions)}"

    seg_durs = [assemble.dur_of(s) for s in segments]
    offsets: list[float] = []
    cum = seg_durs[0]
    sfx_layers: list[tuple[str, float]] = []
    for i, (mode, td, sfx) in enumerate(transitions):
        off = cum - td
        offsets.append(off)
        if sfx:
            sfx_layers.append((sfx, off + td * 0.1))
        cum = off + seg_durs[i + 1]
    total_dur = cum
    print(f"  master {total_dur:.1f}s, {len(sfx_layers)} sfx overlays")

    parts = []
    prev_v, prev_a = "[0:v]", "[0:a]"
    for i, ((mode, td, _sfx), off) in enumerate(zip(transitions, offsets)):
        ni = i + 1
        vlab = f"[v{i}]"
        alab = f"[a{i}]"
        parts.append(f"{prev_v}[{ni}:v]xfade=transition={mode}:duration={td}:offset={off:.3f}{vlab}")
        parts.append(f"{prev_a}[{ni}:a]acrossfade=d={td}{alab}")
        prev_v, prev_a = vlab, alab

    base_input_count = len(segments)
    sfx_inputs_flat: list[str] = []
    if sfx_layers:
        sfx_labels = []
        for k, (sfx_name, tt) in enumerate(sfx_layers):
            idx = base_input_count + k
            sfx_inputs_flat += ["-i", str(SFX / f"{sfx_name}.mp3")]
            lab = f"[sfx{k}]"
            parts.append(f"[{idx}:a]adelay={int(tt*1000)}|{int(tt*1000)},"
                         f"volume={assemble.MIX_TRANSITION}{lab}")
            sfx_labels.append(lab)
        parts.append(f"{prev_a}{''.join(sfx_labels)}amix=inputs={1+len(sfx_layers)}:"
                     f"duration=first:dropout_transition=0:normalize=0[afinal]")
        final_a = "[afinal]"
    else:
        final_a = prev_a

    filter_complex = ";".join(parts)
    final_path = FINAL / "video.mp4"

    seg_inputs: list[str] = []
    for s in segments:
        seg_inputs += ["-i", str(s)]

    cmd = ["ffmpeg", "-y", *seg_inputs, *sfx_inputs_flat,
           "-filter_complex", filter_complex,
           "-map", prev_v, "-map", final_a,
           "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
           "-r", "30",
           str(final_path)]
    print(f"  filter_complex length: {len(filter_complex)} chars")
    subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)
    size_mb = final_path.stat().st_size / 1024 / 1024
    print(f"FINAL: {final_path} ({assemble.dur_of(final_path):.1f}s, {size_mb:.1f} MB)")
    return final_path


def main():
    print("--- Step 8: per-segment audio + mux ---")
    segments = build_all_segments()
    plan = build_segment_plan()
    print(f"Got {len(segments)} muxed segments")
    print("--- Step 7+9: chaining transitions ---")
    transitions = generate_transitions(plan)
    chain_with_xfade(segments, transitions)


if __name__ == "__main__":
    main()
