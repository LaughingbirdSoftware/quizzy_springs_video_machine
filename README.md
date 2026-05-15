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
- **Image model (thumbnails + backgrounds):** OpenAI `gpt-image-2` via `script/gen_thumbnail_openai.py` and `script/gen_background_openai.py`

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
  "intro": "Today on Quizzy Springs we're testing your knowledge of <topic> — the <topic> trivia quiz. Twenty questions: six easy, ten medium, four hard. Keep track of your score and let's see how you do!",
  "outro": "That's a wrap on today's <topic> quiz! Drop your score in the comments — we love seeing how everyone did. If you had fun, subscribe to Quizzy Springs and tap the bell so you don't miss the next one. See you next time!",
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
- **Difficulty floor — even the easiest question must require thought.**
  - ❌ Too easy: "Who is the king of the jungle?" → "What role did Tom Hanks play in Forrest Gump?"
  - ✅ Easy-but-engaging tier: "Who played Forrest's mother in Forrest Gump?" / "What was the name of the diner where Forrest ate?"
  - The reference target: 80%+ of viewers should still get easy questions right, but only after a beat of recall — not instantly. If the answer is obvious from a 2-second glance at the topic, it's too easy.
- Era spread: **~30% classic / 40% 2000s-2010s / 30% recent** (recent = last 8 yrs)
- Mix categories — never two adjacent questions of the same category
- Family-friendly. No copyrighted lyrics. Reference titles/artists factually
- Each question ≤17 words. Each option ≤5 words. Each fun_fact ≤17 words
- `intro_subtitle` is the line rendered under "QUIZZY SPRINGS" on the intro card (e.g. `"ANIMAL QUIZ"`, `"SPORTS QUIZ"`, `"90s MOVIES QUIZ"`). Keep it ≤20 chars, ALL CAPS. **Always set this** — without it the intro card falls back to a generic "QUIZ".
- **Intro line MUST lead with the topic keyword phrase** (e.g. *"Today on Quizzy Springs we're testing your knowledge of \<topic\> — the \<topic\> trivia quiz..."*). YouTube's algorithm indexes the first ~30 seconds heavily; "Welcome back" wastes prime SEO real estate.
- **Outro line MUST be date-agnostic** — never name a day of the week ("see you Friday" — the next video might be Saturday). Use "see you next time" or "see you soon" instead.

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

### 3. Theme the backgrounds (OpenAI gpt-image-2) — generate the FULL set of 7

Generate **all 7 backgrounds** per episode using `script/gen_background_openai.py`. The renderer auto-picks up per-episode `bg_*.png` files from `episodes/<slug>/` first, then falls back to shared `visuals/bg_*.png`. Generating all 7 gives the episode a visually coherent identity from intro through outro — same palette, same atmospheric vibe, just composed differently for each card.

```bash
# Repeat for all 7 names below, each with a topical opener that shares
# the same palette + atmosphere story.
EPISODE_SLUG="<slug>" .venv/bin/python script/gen_background_openai.py <bg_name> "<topical opener>"
```

**The 7 slots:**

| Slot | Mode (auto) | What sits on top | What to ask for |
|---|---|---|---|
| `bg_intro` | scene | "QUIZZY SPRINGS" title + subtitle + "20 QUESTIONS" | Topical scene, blurred, dim center for big text |
| `bg_outro` | scene | "Subscribe" / closing text | Same scene style as intro, gentler |
| `bg_easy` | scene | "EASY ROUND" big label | Same palette as intro, brighter mood |
| `bg_medium` | scene | "MEDIUM ROUND" | Same palette, slightly more intense |
| `bg_hard` | scene | "HARD ROUND" | Same palette, most intense / dramatic mood |
| `bg_question` | abstract | The dark navy question card | Pure gradient atmosphere, NO objects, same color story |
| `bg_reveal` | abstract | The answer-reveal card | Pure gradient atmosphere, NO objects, slightly more "celebratory" tone |

**Critical rule: maintain palette + atmosphere coherence across all 7.** If `bg_intro` is sepia-and-azure travel atlas, then `bg_question` should be a sepia parchment gradient (not pink clouds). If `bg_intro` is dreamy theme-park magenta-and-purple, `bg_question` should be that same magenta-and-purple, just emptier. Viewers should feel like one consistent episode aesthetic, not seven random images.

See the **Themed backgrounds per episode** section below for palette examples per topic and the IP-safety constraints. The script handles size, cropping, and IP guardrails automatically (1920×1080).

**Cost:** ~$0.06 per background × 7 = ~$0.42 per episode. ~$5.46/month across the trivia pipeline. Worth it for the visual coherence.

### 4. Run the pipeline

```bash
EPISODE_SLUG="<slug>" .venv/bin/python script/pipeline.py
```

This runs three stages automatically (~5-7 min total):
1. **Voiceover** — 62 TTS calls with timestamps (max 3 parallel, exp backoff on 429)
2. **Frame rendering** — ~20,800 frames across 25 segments (parallelized across CPUs)
3. **Audio assembly + xfade transitions + final mux** — single-pass ffmpeg

Final video lands at `episodes/<slug>/final/video.mp4`.

### 5. Generate thumbnails (OpenAI gpt-image-2)

Just run the helper — it reads `intro_subtitle` from `questions.json`, generates 3 distinct thumbnails with topic-direct text, crops to 16:9, and saves to `final/thumbnail_{1,2,3}.png` at 1280×720 (under 2 MB each).

```bash
EPISODE_SLUG="<slug>" .venv/bin/python script/gen_thumbnail_openai.py
```

**Cost:** ~$0.18 per episode (3 × $0.06).

**Why gpt-image-2 over Higgsfield:** the older Higgsfield path garbled text ("Sleepless in Seella," "Can YASS this quiz") and invented distorted celebrity faces. gpt-image-2 renders text accurately.

#### Thumbnail vs. title wording — split surfaces strategically

| Surface | Style | Example for a sports quiz |
|---|---|---|
| **Thumbnail text** (auto, baked into the helper prompts) | **Topic-direct, 3–5 words, ALL CAPS** | "SPORTS TRIVIA QUIZ" |
| **Video title** (line 1 of `title_options.txt`) | Hook / curiosity gap | "Can You Score 20/20 on This Sports Quiz?" |
| **Description hook (line 1 of `description.txt`)** | Challenge / question | "Think you know your sports trivia?" |

The thumbnail is a 0.3-second scroll-stopping device — viewers scan for "what is this?" in that window. Topic-direct words classify instantly and out-perform curiosity-gap lines on the thumbnail. Save the curiosity hook for the *title*.

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
- Cost estimate (~$3-5 in ElevenLabs credits; ~$0.18 thumbnails; ~$0.42 backgrounds if generated fresh)
- Paths to final/video.mp4, the 3 thumbnails, and the 3 metadata files

---

## SEO filename note

The pipeline writes the final video as `final/video.mp4`. The upload step
(`script/youtube_upload_trivia.py`, called by `run-episode.sh`) automatically
renames it to a topic-derived filename (e.g. `sports-trivia-quiz.mp4`)
before uploading, so the filename YouTube sees matches the content. This
is a minor but real ranking signal.

You don't need to do anything for this — the rename happens automatically
in the upload wrapper.

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

**Generation:** use `script/gen_background_openai.py` (OpenAI gpt-image-2). Pass the background name and a topical prompt; the script handles 16:9 cropping, 1920×1080 sizing, IP-safety guardrails, and PNG output automatically.

```bash
EPISODE_SLUG="<slug>" .venv/bin/python script/gen_background_openai.py bg_intro \
    "<topical opener — see examples below>"
```

Repeat for each of the 7 background names. The script picks the right composition mode automatically based on the name:

- **`bg_intro`, `bg_outro`, `bg_easy`, `bg_medium`, `bg_hard`** → **scene mode**.
  Generic, blurred, topical scene imagery with a dimmed center so the foreground
  title text remains legible. Used wherever large text overlays the background.

- **`bg_question`, `bg_reveal`** → **abstract mode**.
  Pure gradient atmosphere with no objects. Used where a full content card sits
  on top of the bg — any scene imagery would compete with the card.

You can force mode with an optional third arg: `... bg_intro "<prompt>" abstract` or `... bg_question "<prompt>" scene`. Rarely needed.

### Topical opener examples — keep them generic for IP safety

The script's tail enforces "no logos, no trademarked characters, no celebrity likenesses, no real-world IP." Your opener should reinforce the topic *evocatively* — period/genre cues, not specific brands. Examples:

| Topic | ✅ Topical opener (scene mode) |
|---|---|
| Marvel / superheroes | "Generic comic-book panel burst, halftone dot pattern in red and blue, radiating energy lines, abstract superhero comic aesthetic, no specific characters" |
| 90s rom-coms | "90s living room interior with a vintage CRT television, soft sunset light through blinds, retro pastel decor, no people, dreamy nostalgic atmosphere" |
| Sports | "Empty stadium under dimmed floodlights at dusk, blurred distant field, faint motion-streak haze, no team logos or markings" |
| Horror | "Foggy candlelit gothic interior at midnight, deep blood-red and obsidian tones, smoke drifting, no figures or faces" |
| Sci-fi / Star Wars | "Generic deep-space starfield with soft nebula clouds, distant abstract spaceship silhouettes far in the background, no specific franchise" |
| Pixar / animation | "Dreamy stylized animation studio backlot at golden hour, soft chalky pastels, generic cartoony shapes in background, no specific characters" |
| Disney / theme-park | "Generic theme-park nighttime sky with distant colorful fireworks bursts in pinks and purples, soft bokeh, abstract suggestion of a fairy-tale castle silhouette far in the background, dreamy storybook magical atmosphere, pastel color palette, no specific characters or franchise references, sense of childhood wonder" |
| Disney Channel era | "Generic 2000s teen-show set: stage lights, colorful pop graphics, abstract bokeh, no logos or characters" |
| Reality TV | "Generic competition-show stage with dim spotlights, bokeh audience silhouettes far back, dramatic side lighting, no logos" |
| Tarantino films | "Sun-bleached 1970s diner interior, vintage neon outside, cinematic widescreen mood, no people, grindhouse film grain" |
| HBO drama | "Moody prestige-drama atmosphere, dark cinematic side lighting, abstract suggestion of a city skyline, no specific show references" |
| Geography / travel / "guess the country" | "Generic blurred travel-atlas atmosphere with a soft glowing globe orb suggested in the deep background, faint vintage map line textures, blurry pastel silhouettes of generic landmark shapes (distant mountain ranges, towers, domes, columns) along the edges far out of focus, dreamy sepia-and-azure travel-poster palette, no specific country names, no recognizable national flags, no real-world landmarks, abstract sense of global exploration" |
| Music | "Generic concert atmosphere with dim stage lights, abstract sound-wave bokeh, soft purple-and-amber glow, distant blurred crowd silhouettes, no specific artist or band, no logos, no recognizable venue" |
| Video games | "Generic retro arcade atmosphere with soft pixel-light bokeh, abstract joystick and arcade-cabinet silhouettes far out of focus, neon magenta and cyan palette, no specific game titles or characters, dreamy retro-gaming mood" |
| Cartoons / animation history | "Dreamy hand-painted animation studio vibe at golden hour, soft chalky pastel cels stacked in the deep background, faint generic cartoon-style cloud shapes far out of focus, no specific characters or studios, soft nostalgic palette" |
| Sitcoms | "Generic warmly-lit living-room sitcom set at night, soft camera-haze bokeh from production lights, distant blurred apartment-set background, no actors or recognizable shows, cozy nostalgic palette" |

**The pattern that works:** *"Generic blurred \<topical\> atmosphere with \<evocative elements\> at the edges in soft focus, dimmed center for text overlay, no specific \<IP elements\>, abstract sense of \<topic\>."* Reach for this shape on any topic.

### Critical IP guardrails

For Hollywood-edition episodes especially, the opener must NEVER include any of:

- Real brand names ("Marvel", "Disney", "Star Wars", "Netflix")
- Trademarked character names ("Spider-Man", "Mickey Mouse", "Iron Man")
- Specific franchise design elements (the actual Death Star, an actual Iron Man helmet, etc.)
- Celebrity names or likeness cues

The tail enforces this in the prompt to OpenAI, but reinforce it in the opener too. Words like "generic," "abstract suggestion of," "evocative of the era," "no specific characters" are your friends.

**Theme prompt skeleton** (write a topical opener, then ALWAYS append the universal tail):

> Premium luxury YouTube quiz background. [topical palette + atmosphere — see examples]. Cinematic, atmospheric, sophisticated, modern. Pure abstract atmospheric background. NO central objects, NO devices, NO screens, NO podiums, NO furniture, NO people, NO animals, NO trophies, NO text. Ambient gradient and abstract atmospheric design only. Center of frame must be visually clean for text overlay.

Topical palette examples:
- **Animals** (reference: [`episodes/2026-05-11-animals/bg_intro.png`](episodes/2026-05-11-animals/bg_intro.png)): "Lush deep emerald-green jungle canopy with golden god-rays, soft bokeh leaves, faint paw-print and feather motifs in gold particles. Rich teal-to-forest-green gradient with warm amber accents."
- **Sports:** "Dynamic stadium-light streaks, deep navy with electric orange and white motion trails, subtle scoreboard glow."
- **Horror:** "Smoky crimson-and-charcoal atmosphere, faint candle glow, slow swirling fog, deep blood-red gradient with obsidian edges."
- **Sci-fi:** "Deep space gradient, nebula purples and cyans, faint starfield, subtle hex-grid pattern, holographic edge glow."
- **90s movies:** "VHS-grain texture with bold magenta and teal gradient, soft chromatic aberration, subtle film-burn edges."

**Cost:** ~$0.06 per background (OpenAI gpt-image-2 standard). Recommended minimum (intro only): ~$0.06. Full themed set of 7: ~$0.42.

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
| Thumbnails (3 × OpenAI gpt-image-2 standard) | 3 | ~$0.18 |
| Backgrounds (7 × OpenAI gpt-image-2, full themed set per episode) | 7 | ~$0.42 |
| **Total per new episode** | — | **~$3.50-7.50** |

Wall-clock time per episode after questions approved: **~5-7 minutes**.
