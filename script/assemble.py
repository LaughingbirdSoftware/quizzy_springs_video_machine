#!/usr/bin/env python3
"""Assemble final video:
- Step 7: rhythm transitions between segments (xfade)
- Step 8: build audio track per question + intro/outro/bumps with ducking + SFX
- Step 9: mux final audio + transitioned video
"""
import os, sys, json, math, subprocess, shutil, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths
paths.ensure_dirs()

ROOT = paths.ROOT
SEG = paths.SEG_DIR
AUDIO = paths.AUDIO_DIR
SFX = paths.SFX_DIR
MUSIC = paths.MUSIC_DIR
FINAL = paths.FINAL_DIR
WORK = paths.EP_DIR / "_work"
WORK.mkdir(parents=True, exist_ok=True)
FPS = 30

DURS = json.loads(paths.DURATIONS_FILE.read_text())
TIMINGS = json.loads(paths.TIMINGS_FILE.read_text())
QUESTIONS = json.loads(paths.QUESTIONS_FILE.read_text())["questions"]


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL, **kw)

def dur_of(path):
    return float(subprocess.check_output(["ffprobe","-v","quiet","-of","csv=p=0",
        "-show_entries","format=duration", str(path)]).decode().strip())

# ---------- STEP 8: Audio per segment ----------
# --- AUDIO MIX LEVELS (see README "Audio mixing rules") ---
# Voice is always 1.0 reference. Music sits well below the VO so dialogue stays
# intelligible on phone speakers. Sub-1.0 here means quieter than the VO.
MIX_VO          = 1.00   # voiceover reference
MIX_MUSIC_INTRO = 0.16   # intro music under VO
MIX_MUSIC_OUTRO = 0.16   # outro music under VO
MIX_MUSIC_BUMP  = 0.22   # bump music (no VO competing, can be a touch hotter)
MIX_MUSIC_QUIZ  = 0.20   # thinking music during questions (set inside build_question_audio)
MIX_STING       = 0.55   # intro/outro stings
MIX_CORRECT     = 0.85   # correct-answer chime
MIX_TICK        = 0.55   # countdown tick
MIX_BOUNCE      = 0.30   # letter bounce SFX
MIX_TRANSITION  = 0.65   # whoosh / flash / wipe between segments

def build_intro_audio(out):
    """vo_intro under intro_outro music, sfx intro_sting at start."""
    vo_dur = DURS["vo_intro"]
    total = vo_dur + 0.6  # match seg_intro frames
    cmd = ["ffmpeg","-y",
        "-i", str(AUDIO/"vo_intro.mp3"),         # 0
        "-i", str(MUSIC/"intro_outro.mp3"),       # 1
        "-i", str(SFX/"intro_sting.mp3"),         # 2
        "-filter_complex",
        f"[0:a]volume={MIX_VO},apad,atrim=0:{total}[vo];"
        f"[1:a]volume={MIX_MUSIC_INTRO},atrim=0:{total},afade=t=out:st={total-0.6}:d=0.6[mus];"
        f"[2:a]volume={MIX_STING},adelay=0|0[sting];"
        f"[mus][sting]amix=inputs=2:duration=longest:normalize=0[bed];"
        f"[bed][vo]amix=inputs=2:duration=first:normalize=0[a]",
        "-map","[a]","-t",f"{total}","-ar","48000","-ac","2","-b:a","192k", str(out)]
    run(cmd)

def build_outro_audio(out):
    vo_dur = DURS["vo_outro"]
    total = vo_dur + 1.0
    cmd = ["ffmpeg","-y",
        "-i", str(AUDIO/"vo_outro.mp3"),
        "-i", str(MUSIC/"intro_outro.mp3"),
        "-i", str(SFX/"outro_sting.mp3"),
        "-filter_complex",
        f"[0:a]volume={MIX_VO},adelay=200|200,apad,atrim=0:{total}[vo];"
        f"[1:a]volume={MIX_MUSIC_OUTRO},atrim=0:{total},afade=t=out:st={total-0.8}:d=0.8[mus];"
        f"[2:a]volume={MIX_STING},adelay=0|0[sting];"
        f"[mus][sting]amix=inputs=2:duration=longest:normalize=0[bed];"
        f"[bed][vo]amix=inputs=2:duration=first:normalize=0[a]",
        "-map","[a]","-t",f"{total}","-ar","48000","-ac","2","-b:a","192k", str(out)]
    run(cmd)

def build_bump_audio(level, out):
    """3s bump: bump_xxx sfx + brief intro_outro music."""
    cmd = ["ffmpeg","-y",
        "-i", str(SFX/f"bump_{level}.mp3"),
        "-i", str(MUSIC/"intro_outro.mp3"),
        "-filter_complex",
        f"[0:a]volume=1.0[s];"
        f"[1:a]volume={MIX_MUSIC_BUMP},atrim=0:3.0,afade=t=in:st=0:d=0.2,afade=t=out:st=2.5:d=0.5[m];"
        f"[m][s]amix=inputs=2:duration=longest:normalize=0[a]",
        "-map","[a]","-t","3.0","-ar","48000","-ac","2","-b:a","192k", str(out)]
    run(cmd)

def build_question_audio(qn, out):
    """Phase A: question + options under thinking music at -18, bounce on each letter.
       Phase B: 6s countdown - ticks + countdown.mp3 sting.
       Phase C: correct.mp3 + answer VO under thinking music at -18."""
    t = TIMINGS[f"q{qn:02d}"]
    fps = FPS
    pa = t["phase_a"] / fps   # in seconds
    pb = t["phase_b"] / fps
    pc = t["phase_c"] / fps
    total = pa + pb + pc

    qd = DURS[f"vo_q{qn:02d}_question"]
    od = DURS[f"vo_q{qn:02d}_options"]
    ad = DURS[f"vo_q{qn:02d}_answer"]

    # Times
    vo_q_start = 1.0  # 30 frames intro animation = 1.0s
    vo_o_start = vo_q_start + qd + 0.2
    # letter bounce frames in vo_options (in ms via alignment) — translate to delays
    letter_frames = json.loads((AUDIO / f"vo_q{qn:02d}_letter_frames.json").read_text())
    # Each letter_frames[letter] is a frame index within options playback => second offset = frame/30
    # Actual time relative to segment start = vo_o_start + frame/30
    bounce_times = sorted([vo_o_start + letter_frames[L]/fps for L in "ABCD" if L in letter_frames])

    # Phase B: countdown begins at pa
    cd_start = pa
    # tick at each second 0..5 of countdown
    tick_times = [cd_start + i for i in range(6)]
    # countdown.mp3 plays under countdown phase
    # Phase C: correct.mp3 at start, then answer VO 0.3s in
    pc_start = pa + pb
    correct_time = pc_start + 0.1
    vo_a_start = pc_start + 0.3

    # Build the filter graph
    inputs = []
    def add(path): inputs.append(("-i", str(path))); return len(inputs)-1
    # 0: thinking music (loops)
    i_mus = add(MUSIC/"thinking.mp3")
    # 1: vo_question
    i_q = add(AUDIO/f"vo_q{qn:02d}_question.mp3")
    # 2: vo_options
    i_o = add(AUDIO/f"vo_q{qn:02d}_options.mp3")
    # 3: vo_answer
    i_a = add(AUDIO/f"vo_q{qn:02d}_answer.mp3")
    # 4: countdown sting
    i_cd = add(MUSIC/"countdown.mp3")
    # 5..10: ticks
    i_ticks = [add(SFX/"tick.mp3") for _ in range(6)]
    # 11: correct
    i_correct = add(SFX/"correct.mp3")
    # bounces
    i_bounces = [add(SFX/"bounce.mp3") for _ in bounce_times]

    parts = []
    # music: loop, trim, ducked under VO
    parts.append(f"[{i_mus}:a]aloop=loop=-1:size=2e9,atrim=0:{total},volume={MIX_MUSIC_QUIZ}[mus]")
    # vo_question delayed
    parts.append(f"[{i_q}:a]adelay={int(vo_q_start*1000)}|{int(vo_q_start*1000)},volume={MIX_VO}[voq]")
    # vo_options delayed
    parts.append(f"[{i_o}:a]adelay={int(vo_o_start*1000)}|{int(vo_o_start*1000)},volume={MIX_VO}[voo]")
    # vo_answer
    parts.append(f"[{i_a}:a]adelay={int(vo_a_start*1000)}|{int(vo_a_start*1000)},volume={MIX_VO}[voa]")
    # countdown sting fits in phase B (6s)
    cd_offset = cd_start  # actual countdown.mp3 is 8s; truncate to 6
    parts.append(f"[{i_cd}:a]atrim=0:6.0,adelay={int(cd_offset*1000)}|{int(cd_offset*1000)},volume=0.45[cds]")
    # ticks
    for ti, tt in zip(i_ticks, tick_times):
        parts.append(f"[{ti}:a]adelay={int(tt*1000)}|{int(tt*1000)},volume={MIX_TICK}[t{ti}]")
    # bounces
    for bi, bt in zip(i_bounces, bounce_times):
        parts.append(f"[{bi}:a]adelay={int(bt*1000)}|{int(bt*1000)},volume={MIX_BOUNCE}[b{bi}]")
    # correct
    parts.append(f"[{i_correct}:a]adelay={int(correct_time*1000)}|{int(correct_time*1000)},volume={MIX_CORRECT}[crk]")

    # Mix: voice + sfx + music
    mix_labels = ["mus","voq","voo","voa","cds","crk"]
    mix_labels += [f"t{ti}" for ti in i_ticks]
    mix_labels += [f"b{bi}" for bi in i_bounces]
    mix_in = "".join(f"[{l}]" for l in mix_labels)
    parts.append(f"{mix_in}amix=inputs={len(mix_labels)}:duration=first:dropout_transition=0:normalize=0[a]")

    filter_complex = ";".join(parts)
    cmd = ["ffmpeg","-y"] + [x for pair in inputs for x in pair] + [
        "-filter_complex", filter_complex,
        "-map","[a]","-t",f"{total:.3f}",
        "-ar","48000","-ac","2","-b:a","192k", str(out)]
    run(cmd)


def mux_segment(video_in, audio_in, out):
    """Mux silent video + audio into a new file with both."""
    run(["ffmpeg","-y","-i", str(video_in), "-i", str(audio_in),
         "-c:v","copy","-c:a","copy","-shortest", str(out)])


def build_all_segments():
    """Generate audio for each segment and mux."""
    muxed = WORK / "muxed"
    muxed.mkdir(exist_ok=True)
    aud = WORK / "aud"
    aud.mkdir(exist_ok=True)

    # intro
    print("[audio] intro")
    build_intro_audio(aud/"intro.m4a")
    mux_segment(SEG/"seg_intro.mp4", aud/"intro.m4a", muxed/"01_intro.mp4")
    # bump_easy
    print("[audio] bump_easy")
    build_bump_audio("easy", aud/"bump_easy.m4a")
    mux_segment(SEG/"seg_bump_easy.mp4", aud/"bump_easy.m4a", muxed/"02_bump_easy.mp4")
    # Q01-06
    for n in range(1, 7):
        print(f"[audio] q{n:02d}")
        build_question_audio(n, aud/f"q{n:02d}.m4a")
        mux_segment(SEG/f"seg_q{n:02d}.mp4", aud/f"q{n:02d}.m4a", muxed/f"{2+n:02d}_q{n:02d}.mp4")
    # bump_medium
    print("[audio] bump_medium")
    build_bump_audio("medium", aud/"bump_medium.m4a")
    mux_segment(SEG/"seg_bump_medium.mp4", aud/"bump_medium.m4a", muxed/"09_bump_medium.mp4")
    # Q07-16
    for n in range(7, 17):
        print(f"[audio] q{n:02d}")
        build_question_audio(n, aud/f"q{n:02d}.m4a")
        mux_segment(SEG/f"seg_q{n:02d}.mp4", aud/f"q{n:02d}.m4a", muxed/f"{3+n:02d}_q{n:02d}.mp4")
    # bump_hard
    print("[audio] bump_hard")
    build_bump_audio("hard", aud/"bump_hard.m4a")
    mux_segment(SEG/"seg_bump_hard.mp4", aud/"bump_hard.m4a", muxed/"20_bump_hard.mp4")
    # Q17-20
    for n in range(17, 21):
        print(f"[audio] q{n:02d}")
        build_question_audio(n, aud/f"q{n:02d}.m4a")
        mux_segment(SEG/f"seg_q{n:02d}.mp4", aud/f"q{n:02d}.m4a", muxed/f"{4+n:02d}_q{n:02d}.mp4")
    # outro
    print("[audio] outro")
    build_outro_audio(aud/"outro.m4a")
    mux_segment(SEG/"seg_outro.mp4", aud/"outro.m4a", muxed/"25_outro.mp4")
    return sorted(muxed.glob("*.mp4"))


# ---------- STEP 7: rhythm transitions ----------
TRANSITIONS = [
    # (xfade_mode, duration_s, sfx_path_or_None)
    ("fadewhite", 0.5, "flash_hit"),    # intro -> bump_easy
    ("slideleft", 0.4, "whoosh"),       # bump_easy -> Q01
    ("slideleft", 0.35, "whoosh"),      # Q01 -> Q02
    ("slideleft", 0.35, "whoosh"),
    ("slideleft", 0.35, "whoosh"),
    ("slideleft", 0.35, "whoosh"),
    ("slideleft", 0.35, "whoosh"),      # Q05 -> Q06
    ("wipeleft", 0.6, "whoosh_big"),    # Q06 -> bump_medium
    ("slideleft", 0.4, "whoosh"),       # bump_medium -> Q07
    ("slideleft", 0.35, "whoosh"),      # Q07 -> Q08
    ("slideleft", 0.35, "whoosh"),
    ("slideleft", 0.35, "whoosh"),
    ("slideleft", 0.35, "whoosh"),
    ("slideleft", 0.35, "whoosh"),
    ("slideleft", 0.35, "whoosh"),
    ("slideleft", 0.35, "whoosh"),
    ("slideleft", 0.35, "whoosh"),
    ("slideleft", 0.35, "whoosh"),      # Q15 -> Q16
    ("wipeleft", 0.8, "whoosh_big"),    # Q16 -> bump_hard (plus flash via SFX)
    ("slideleft", 0.4, "whoosh"),       # bump_hard -> Q17
    ("slideleft", 0.35, "whoosh"),      # Q17 -> Q18
    ("slideleft", 0.35, "whoosh"),
    ("slideleft", 0.35, "whoosh"),      # Q19 -> Q20
    ("fadeblack", 1.0, "outro_sting"),  # Q20 -> outro
]

def chain_with_xfade(segments):
    """Build a single filter_complex that xfades all 25 segments together, then layer SFX."""
    assert len(segments) - 1 == len(TRANSITIONS), f"{len(segments)-1} != {len(TRANSITIONS)}"
    work = WORK / "chain"
    work.mkdir(exist_ok=True)

    # 1) Pre-compute all segment durations and cumulative offsets
    seg_durs = [dur_of(s) for s in segments]
    offsets = []
    cum = seg_durs[0]
    sfx_layers = []  # (sfx_name, time_in_master)
    for i, (mode, td, sfx) in enumerate(TRANSITIONS):
        off = cum - td
        offsets.append(off)
        if sfx:
            sfx_layers.append((sfx, off + td*0.1))
        cum = off + seg_durs[i+1]
    total_dur = cum
    print(f"  master will be {total_dur:.1f}s, {len(sfx_layers)} SFX overlays")

    # 2) Build the filter_complex string
    parts = []
    prev_v, prev_a = "[0:v]", "[0:a]"
    for i, ((mode, td, _sfx), off) in enumerate(zip(TRANSITIONS, offsets)):
        ni = i + 1
        vlab = f"[v{i}]"
        alab = f"[a{i}]"
        parts.append(f"{prev_v}[{ni}:v]xfade=transition={mode}:duration={td}:offset={off:.3f}{vlab}")
        parts.append(f"{prev_a}[{ni}:a]acrossfade=d={td}{alab}")
        prev_v, prev_a = vlab, alab

    # 3) Bring in SFX inputs and layer them
    base_input_count = len(segments)  # 0..24
    sfx_inputs_flat = []
    if sfx_layers:
        sfx_delay_labels = []
        for k, (sfx_name, tt) in enumerate(sfx_layers):
            idx = base_input_count + k
            sfx_inputs_flat += ["-i", str(SFX/f"{sfx_name}.mp3")]
            lab = f"[sfx{k}]"
            parts.append(f"[{idx}:a]adelay={int(tt*1000)}|{int(tt*1000)},volume={MIX_TRANSITION}{lab}")
            sfx_delay_labels.append(lab)
        parts.append(f"{prev_a}{''.join(sfx_delay_labels)}amix=inputs={1+len(sfx_layers)}:duration=first:dropout_transition=0:normalize=0[afinal]")
        final_a = "[afinal]"
    else:
        final_a = prev_a

    filter_complex = ";".join(parts)
    final_path = FINAL / "video.mp4"

    seg_inputs = []
    for s in segments:
        seg_inputs += ["-i", str(s)]

    cmd = ["ffmpeg","-y", *seg_inputs, *sfx_inputs_flat,
           "-filter_complex", filter_complex,
           "-map", prev_v, "-map", final_a,
           "-c:v","libx264","-preset","slow","-crf","18","-pix_fmt","yuv420p",
           "-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
           "-r","30",
           str(final_path)]
    # log a snippet of filter
    print(f"  ffmpeg filter_complex length: {len(filter_complex)} chars")
    run(cmd)
    print(f"FINAL: {final_path} ({dur_of(final_path):.1f}s, {final_path.stat().st_size/1024/1024:.1f} MB)")
    return final_path


def main():
    print("--- Step 8: building per-segment audio + mux ---")
    segments = build_all_segments()
    print(f"Got {len(segments)} muxed segments")
    print("--- Step 7+9: chaining transitions ---")
    final = chain_with_xfade(segments)
    print(f"Done: {final}")

if __name__ == "__main__":
    main()
