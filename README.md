# Quizzy Springs Video Pipeline

End-to-end automation for producing animated YouTube quiz videos for the **Quizzy Springs** channel.
Each video is ~11 minutes, 1920×1080 30fps H.264, with synced voiceover, music, SFX, animated
question cards, countdowns, reveals, rhythm transitions, and a branded outro with a "watch next" placeholder.

This file is the runbook. **A fresh Claude Code session can read this top-to-bottom and produce a new episode** without needing prior conversation context.

---

## Channel facts

- **Channel:** Quizzy Springs
- **Logo:** [`assets/logo.png`](assets/logo.png) (frog mascot, used in intro + outro)
- **Format:** 20-question multiple-choice quiz, mixed difficulty (6 easy / 10 medium / 4 hard)
- **Length target:** 10-12 min
- **Aspect:** 1920×1080, 30 fps
- **Voice (ElevenLabs):** voice_id `cgSgspJ2msm6clMCkdW9`, model `eleven_multilingual_v2`, stability 0.45 / similarity 0.85 / style 0.3
- **Image model (Higgsfield via MCP):** `nano_banana_2` at 16:9

---

## Repo layout

```
Quizzy Springs Videos/
├── README.md                  ← you are here
├── .env                       ← ELEVENLABS_API_KEY (chmod 600, not in git)
├── .venv/                     ← Python venv (Pillow, requests)
├── assets/
│   ├── logo.png               ← channel logo
│   └── fonts/                 ← Montserrat Bold / ExtraBold / Black
├── audio/
│   ├── music/                 ← SHARED: intro_outro / thinking / countdown
│   └── sfx/                   ← SHARED: 12 effects (whoosh, correct, bounce, etc.)
├── visuals/
│   └── bg_*.png               ← SHARED: 7 background cards (1920×1080)
├── script/
│   ├── paths.py               ← path resolver (reads EPISODE_SLUG env var)
│   ├── gen_voiceover.py       ← ElevenLabs TTS with-timestamps for letter sync
│   ├── gen_music.py           ← (run once, already generated)
│   ├── gen_sfx.py             ← (run once, already generated)
│   ├── render.py              ← Pillow per-frame compositor + mp4 encoder
│   ├── assemble.py            ← per-segment audio + xfade transitions + final mux
│   └── pipeline.py            ← driver: voiceover → render → assemble
└── episodes/
    └── <slug>/                ← ONE FOLDER PER EPISODE (the only thing that changes)
        ├── questions.json     ← 20 questions + intro/outro text
        ├── script.txt         ← auto-generated read-aloud script
        ├── vo/                ← 62 mp3 + letter_frames.json per question
        ├── segments/          ← 25 silent mp4 segments
        ├── _work/             ← intermediate ffmpeg files
        └── final/
            ├── video.mp4
            ├── thumbnail_1.png  thumbnail_2.png  thumbnail_3.png
            ├── title_options.txt   description.txt   tags.txt
```

**Shared resources** (music, SFX, backgrounds, fonts, logo) live at the project root and are reused across every episode. **Per-episode resources** (questions, voiceover, segments, final video, thumbnails, metadata) live under `episodes/<slug>/`.

---

## To produce a new episode (workflow for Claude)

When the user says *"let's do a sports quiz"* or *"new episode: 90s movies"*:

### 1. Set up the episode slug

Pick a `<slug>` that's filesystem-safe and dated, e.g.:
- `2026-05-15-sports`
- `2026-05-18-90s-movies`
- `2026-05-22-anime-mixed`

Create the folder:
```bash
mkdir -p "episodes/<slug>"
```

### 2. Generate `questions.json` — and PAUSE for user review

Write `episodes/<slug>/questions.json` with exactly this schema (Pop Culture episode is the reference: [`episodes/2026-05-11-pop-culture-001/questions.json`](episodes/2026-05-11-pop-culture-001/questions.json)):

```json
{
  "channel": "Quizzy Springs",
  "title": "<short title>",
  "intro_subtitle": "<TOPIC> QUIZ",
  "intro": "Welcome back to Quizzy Springs! Today we're testing your <topic> knowledge with 20 questions... Six easy, ten medium, four hard. Keep track of your score and let's see how you do!",
  "outro": "That's a wrap on today's <topic> quiz! Drop your score in the comments — we love seeing how everyone did. If you had fun, subscribe to Quizzy Springs and tap the bell so you don't miss the next one. See you soon!",
  "questions": [
    {
      "n": 1, "difficulty": "easy", "category": "<topical category>", "era": "classic|2000s-2010s|recent",
      "question": "<under 18 words>",
      "options": {"A": "<≤5 words>", "B": "<≤5 words>", "C": "<≤5 words>", "D": "<≤5 words>"},
      "answer": "A|B|C|D",
      "fun_fact": "<under 18 words>"
    }
    // ... 20 total
  ]
}
```

**Constraints (must all hold):**
- 20 questions exactly, numbered 1-20
- Difficulty split: **Q1-6 easy, Q7-16 medium, Q17-20 hard**
- Era spread: **~30% classic / 40% 2000s-2010s / 30% recent** (recent = last 8 yrs)
- Mix categories — never two adjacent questions of the same category
- Family-friendly. No copyrighted lyrics. Reference titles/artists factually
- Each question ≤17 words. Each option ≤5 words. Each fun_fact ≤17 words
- `intro_subtitle` is the line rendered under "QUIZZY SPRINGS" on the intro card (e.g. `"ANIMAL QUIZ"`, `"SPORTS QUIZ"`, `"90s MOVIES QUIZ"`). Keep it ≤20 chars, ALL CAPS. **Always set this** — without it the intro card falls back to a generic "QUIZ".

Validate by running:
```bash
EPISODE_SLUG="<slug>" .venv/bin/python -c "
import sys; sys.path.insert(0,'script'); import paths, json
d=json.loads(paths.QUESTIONS_FILE.read_text())
from collections import Counter
for q in d['questions']:
    assert len(q['question'].split()) < 18, f\"Q{q['n']} question too long\"
    for k,v in q['options'].items(): assert len(v.split()) < 6, f\"Q{q['n']}.{k} too long\"
    assert len(q['fun_fact'].split()) < 18, f\"Q{q['n']} fun_fact too long\"
prev=None
for q in d['questions']:
    assert q['category']!=prev, f\"clustered at Q{q['n']}\"
    prev = q['category']
print('difficulty:', Counter(q['difficulty'] for q in d['questions']))
print('era:', Counter(q['era'] for q in d['questions']))
print('OK')
"
```

**STOP HERE and show the user the question list for approval before continuing.** Voiceover generation costs real ElevenLabs credits (~$3-5/episode).

### 3. Theme the intro background (always) — and other backgrounds if desired

Before running the pipeline, generate at least a themed `bg_intro.png` for the episode and save it to `episodes/<slug>/bg_intro.png` (1920×1080). See the **Themed backgrounds per episode** section below for the prompt skeleton, palette examples, and resize procedure. The renderer auto-picks up per-episode backgrounds — no code edits.

Optionally do the full set of 7 (`bg_outro`, `bg_easy`, `bg_medium`, `bg_hard`, `bg_question`, `bg_reveal`) for a fully themed episode (~$2).

### 4. Run the pipeline

```bash
EPISODE_SLUG="<slug>" .venv/bin/python script/pipeline.py
```

This runs three stages automatically (~5-7 min total):
1. **Voiceover** — 62 TTS calls with timestamps (max 3 parallel, exp backoff on 429)
2. **Frame rendering** — ~20,800 frames across 25 segments (parallelized across CPUs)
3. **Audio assembly + xfade transitions + final mux** — single-pass ffmpeg

Final video lands at `episodes/<slug>/final/video.mp4`.

### 5. Generate thumbnails (Higgsfield MCP)

Call `mcp__93a90592-e086-4c0e-a93a-b4b2f62d8180__generate_image` three times with model `nano_banana_2`, `aspect_ratio: "16:9"`, `resolution: "1k"`. Prompt templates:

- **Thumbnail 1:** `Bold YouTube quiz thumbnail. Vibrant purple to hot pink gradient with electric neon accents. Giant bold white text '<TOPIC IN CAPS>' top half. Bold yellow text '20 QUESTIONS' bottom half. High contrast energetic. NO logos, NO celebrity faces, NO real-world likenesses. 1280x720.`
- **Thumbnail 2:** `Bold YouTube quiz thumbnail. Electric blue and magenta neon glow. Massive bold yellow text 'CAN YOU SCORE 20/20?'. Question mark graphics in corners. Modern game show energy. NO logos. 1280x720.`
- **Thumbnail 3:** `Bold YouTube quiz thumbnail. Dark navy with vibrant pink and yellow neon text '<HOW TOPIC ARE YOU?>'. Retro arcade aesthetic. Glowing edges. NO logos. 1280x720.`

Poll with `job_display`, then download via the returned `rawUrl`, resize to 1280×720 with Pillow, save to `episodes/<slug>/final/thumbnail_{1,2,3}.png`.

### 6. Write metadata files

In `episodes/<slug>/final/`, write three files. These are the YouTube-ready metadata that the upload script reads.

#### `title_options.txt` — 5 candidate titles

- Each ≤60 characters
- The FIRST line will be auto-selected by the upload script, so put the strongest title first
- Format: just the title text, one per line, NO numbering prefixes like "1." or "2)"
- Style: hook-driven, NOT generic. Use specifics, questions, challenges, or surprising claims
- Good: `Can You Score 20/20 on This 2000s Quiz?`, `Only 90s Kids Will Get These Right`, `The Animal Trivia Quiz That Stumps Everyone`
- Avoid: `Quizzy Springs - Sports Quiz` (generic), `Test Your Knowledge!` (lazy)

#### `description.txt` — algorithm-optimized, ~200 words

Strict structure. Write it in this exact order:

**Line 1 (HOOK + EMOJIS — the only 150 chars most people will ever see):**
- Open with `Think you know <TOPIC>?` followed by 3 relevant emojis
- Then: `Test your knowledge with 20 fun trivia questions covering <3-4 sub-categories>!`
- Sub-categories come from the actual `category` fields in questions.json (e.g. for a sports quiz: "football, basketball, the Olympics, and tennis legends")

**Line 2 (NAMED ENTITIES — single biggest algorithm signal):**
- Look at the 20 questions in questions.json. Pick **5-6 of the most recognizable proper nouns** that appear (names of people, places, brands, characters, titles, teams, products).
- Mix recent (last 8 years) and classic — at least 2 of each — so the algorithm sees both nostalgia and timeliness.
- Format: `From <Entity 1> and <Entity 2> to <Entity 3>, <Entity 4>, and <Entity 5> — this quiz starts easy… but gets MUCH harder as you go 👀`

**Line 3 (Engagement CTA):**
- `🏆 Keep track of your score and comment your final result below!`

**Line 4 (Difficulty structure):**
👇 PLAY ALONG:
Easy Questions: 1–6
Medium Questions: 7–16
Hard Questions: 17–20
How many did YOU get right?

**Line 5 (Subscribe + related-content algorithm signal):**
🎯 Subscribe to Quizzy Springs for more:

trivia quizzes
<topic-relevant content type 1>
<topic-relevant content type 2>
guess the movie games
emoji challenges
nostalgia games
pop culture challenges


The two `<topic-relevant>` bullets should be specific to the episode's topic (e.g. for sports: "sports trivia challenges", "all-time greats quizzes"; for 90s movies: "movie guessing games", "decade-themed challenges").

**Line 6 (Hashtags — 8-10, mix of broad + specific):**
- Always include: `#QuizzySprings #Trivia #QuizGame`
- Topic-specific: 5-7 more, including 2-3 that name specific entities from the quiz (e.g. `#TaylorSwift #Mario` for pop culture, `#NFL #SuperBowl` for football)
- Format on one line, space-separated

**Line 7 (Chapters — proven algorithm signal):**
0:00 Intro
0:21 Easy Questions Begin
3:29 Medium Difficulty Starts
8:50 Hard Questions Begin
10:59 Final Score & Results

**Hard rules:**
- Do NOT start with "Welcome back to Quizzy Springs" — that's already in the voiceover, and the first 150 chars are too valuable for a greeting
- Do NOT include "Gear & affiliate links: [placeholder]" or any placeholder text
- Do NOT include meta-commentary like "this quiz follows our signature format"
- Do NOT mention the channel's hiatus or "we're back"
- Keep total length under 1000 characters — YouTube truncates long descriptions and the algorithm doesn't reward padding

#### `tags.txt` — 25 comma-separated tags

- Cover the topic + general quiz/trivia tags
- Include 5-8 specific named entities from the quiz (the same ones featured in the description, plus more)
- Format: comma-separated on a single line or wrapped — YouTube's tag field accepts comma-separated input directly, so this format pastes cleanly

Reference: [`episodes/2026-05-11-pop-culture-001/final/description.txt`](episodes/2026-05-11-pop-culture-001/final/description.txt)

### 7. Report to user

- Total runtime
- Final video duration + size
- Cost estimate (~$3-5 in ElevenLabs credits; $0 if backgrounds reused)
- Paths to final/video.mp4, the 3 thumbnails, and the 3 metadata files

---

## Themed backgrounds per episode

**Recommendation: always theme at minimum the `bg_intro.png` for every new episode.** The intro card is the first thing viewers see and the generic "electric neon" intro background feels off-brand for topical episodes. Strongly prefer themed backgrounds across the whole episode for a premium feel; at the very least, do `bg_intro`.

**How the renderer resolves backgrounds:** `script/render.py:load_bg()` checks `episodes/<slug>/bg_<name>.png` first, then falls back to the shared `visuals/bg_<name>.png`. So dropping any number of `bg_*.png` files into `episodes/<slug>/` automatically themes just those, with the rest reused from the shared set. **No code edits needed, no overwriting `visuals/`.**

The seven background names the renderer looks for:
- `bg_intro` — opening title card (under "QUIZZY SPRINGS / <TOPIC> QUIZ")
- `bg_outro` — closing card
- `bg_easy` / `bg_medium` / `bg_hard` — round bumps
- `bg_question` — question cards
- `bg_reveal` — answer reveal cards

**Generation:** call `mcp__93a90592-e086-4c0e-a93a-b4b2f62d8180__generate_image` with model `nano_banana_2`, `aspect_ratio: "16:9"`, `resolution: "2k"` (the 2k crop is ~2752×1536, which Pillow downsamples cleanly to 1920×1080). Poll with `job_display`, download the `rawUrl`, resize to **exactly 1920×1080** with Pillow `LANCZOS`, save to `episodes/<slug>/bg_<name>.png`.

**Theme prompt skeleton** (write a topical opener, then ALWAYS append the universal tail):

> Premium luxury YouTube quiz background. [topical palette + atmosphere — see examples]. Cinematic, atmospheric, sophisticated, modern. Pure abstract atmospheric background. NO central objects, NO devices, NO screens, NO podiums, NO furniture, NO people, NO animals, NO trophies, NO text. Ambient gradient and abstract atmospheric design only. Center of frame must be visually clean for text overlay.

Topical palette examples:
- **Animals** (reference: [`episodes/2026-05-11-animals/bg_intro.png`](episodes/2026-05-11-animals/bg_intro.png)): "Lush deep emerald-green jungle canopy with golden god-rays, soft bokeh leaves, faint paw-print and feather motifs in gold particles. Rich teal-to-forest-green gradient with warm amber accents."
- **Sports:** "Dynamic stadium-light streaks, deep navy with electric orange and white motion trails, subtle scoreboard glow."
- **Horror:** "Smoky crimson-and-charcoal atmosphere, faint candle glow, slow swirling fog, deep blood-red gradient with obsidian edges."
- **Sci-fi:** "Deep space gradient, nebula purples and cyans, faint starfield, subtle hex-grid pattern, holographic edge glow."
- **90s movies:** "VHS-grain texture with bold magenta and teal gradient, soft chromatic aberration, subtle film-burn edges."

**Cost:** ~$0.30 per background. Recommended minimum (intro only): ~$0.30. Full themed set of 7: ~$2.

---

## Audio mixing rules

**Voice intelligibility is sacred.** Music sits well below the VO so dialogue stays clear on phone speakers (the dominant playback device on YouTube). All mix levels live as named constants at the top of [`script/assemble.py`](script/assemble.py) — change them there, not inside individual filter strings.

Current levels (voice = 1.0 reference):

| Constant | Value | What it controls |
|---|---|---|
| `MIX_VO` | 1.00 | Voiceover reference — never change |
| `MIX_MUSIC_INTRO` | 0.16 | Intro background music (under "Welcome back…") |
| `MIX_MUSIC_OUTRO` | 0.16 | Outro background music (under "That's a wrap…") |
| `MIX_MUSIC_BUMP` | 0.22 | Round bumps (no VO competing) |
| `MIX_MUSIC_QUIZ` | 0.20 | Thinking music during questions |
| `MIX_STING` | 0.55 | Intro/outro stings |
| `MIX_CORRECT` | 0.85 | Correct-answer chime (should feel punchy) |
| `MIX_TICK` | 0.55 | Countdown tick |
| `MIX_BOUNCE` | 0.30 | Letter bounce SFX |
| `MIX_TRANSITION` | 0.65 | Whoosh / flash / wipe between segments |

**Tuning guidance:** if music ever feels loud against the voice, drop the music constant by 0.04-0.06 (~3-4 dB) rather than boosting the VO. The VO is already at peak; pushing it further just clips the limiter. If you change `MIX_VO`, change *nothing else* — every other level is relative to it.

The music files themselves are loudnormed at generation time ([`gen_music.py`](script/gen_music.py)) to -14/-18/-16 LUFS for intro_outro/thinking/countdown. The runtime `volume=` multiplier in `assemble.py` is applied on top of that loudnorm, so the effective level on the final master is roughly (loudnorm target dBFS) × (multiplier).

---

## Gotchas / things that bit us

1. **TextEdit `.env.txt` problem:** macOS TextEdit auto-appends `.txt`. The `.env` file at root MUST be exactly `.env` (chmod 600).
2. **ELEVENLABS_API_KEY must have TTS + music + sound-generation scopes.** It does NOT need `user_read` (that 401 is benign).
3. **Bash tool runs non-interactive shells.** `~/.zshrc` env vars don't propagate. Always source `.env` via `paths.load_env()` in Python or `set -a && . ./.env && set +a` in shell.
4. **Montserrat fonts are NOT on macOS by default.** They live in `assets/fonts/` and are downloaded once from `github.com/JulietaUla/Montserrat`. If missing, Pillow throws `OSError: unknown file format`.
5. **Emoji glyphs render as tofu in Montserrat.** Avoid emoji in rendered text. Use ASCII alternatives (arrows like ↓ and → do work; bell 🔔 doesn't).
6. **xfade `zoomout` doesn't exist.** Q20→outro uses `fadeblack`.
7. **Output pix_fmt is yuvj420p** (full-range). YouTube handles it. Force `yuv420p` only if a strict-validator complains.
8. **Higgsfield jobs return `pending` first.** Poll with `job_display`. They usually complete in 30-60s.
9. **letter_frames timestamps come from the ElevenLabs `/with-timestamps` endpoint.** `character_start_times_seconds[N]` is the time the Nth char starts. Find positions of `"A:"`, `"B:"`, `"C:"`, `"D:"` in the rendered text to grab the four bounce frames. See [`script/gen_voiceover.py`](script/gen_voiceover.py) `find_letter_frames`.
10. **Disk space:** the macOS drive was 96% full when this was built. ~5 GB free per episode is comfortable; the renderer cleans frames after encoding each segment.

---

## Quick re-run / partial rebuild

Each step is idempotent:
- **Re-render one segment:** edit `render.py`, then call `render_segment_parallel(SEG_DIR/"seg_<name>.mp4", N, "seg_type")` directly. Then re-run `assemble.py`.
- **Re-render the outro only:** delete `episodes/<slug>/segments/seg_outro.mp4`, run the targeted render snippet, re-run `assemble.py`.
- **Re-generate one VO clip:** delete the file in `episodes/<slug>/vo/` and re-run `gen_voiceover.py` — it skips existing files.
- **Re-generate music or SFX:** delete the target file in `audio/music/` or `audio/sfx/` and re-run the corresponding script. Other tracks are preserved.

---

## Reference episode

[`episodes/2026-05-11-pop-culture-001/`](episodes/2026-05-11-pop-culture-001/) — the original Pop Culture quiz. Use its `questions.json` as the schema reference and its `final/description.txt` as the metadata template.

---

## Costs per new episode (approximate)

| Item | Calls | Cost |
|---|---|---|
| Voiceover (62 ElevenLabs TTS clips, ~30k chars total) | 62 | $3-5 |
| Music | 0 (reused) | $0 |
| SFX | 0 (reused) | $0 |
| Backgrounds | 0 (reused) — or ~$2 themed | $0-2 |
| Thumbnails (3 × Higgsfield `nano_banana_2` 1k) | 3 | ~$0.50 |
| **Total per new episode** | — | **~$3.50-7.50** |

Wall-clock time per episode after questions approved: **~5-7 minutes**.
