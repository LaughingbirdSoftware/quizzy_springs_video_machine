# Quizzy Springs — Hollywood Edition (movies/TV/celebrities)

The Tuesday/Thursday/Saturday show. Companion to the original trivia pipeline
documented in `README.md` — runs in parallel, shares the same channel and host
voice, but has its own format, look, and personality.

**A fresh Claude Code session can read this file top-to-bottom and produce a
new Hollywood episode unattended.** That is the contract: do not rely on
prior conversation context, do not skip the data-grounding step, do not
write filler.

---

## What this show is

20-question MOVIE / TV / CELEBRITY trivia. Each question pairs a TMDB-sourced
image (poster, headshot, or still) with a 4-choice multiple-choice question.
The viewer can see *the obvious thing* (the poster), but the question asks
something *non-obvious about it* (the supporting cast, the year, the
co-stars).

**Difficulty floor:** the easiest question should still require thought.
"Forrest's mom tier" — never "what show is this?" when the poster is right
there.

- Length target: 9–11 minutes (20 questions × ~25s each + intro/outro)
- Aspect: 1920×1080, 30 fps
- Channel: Quizzy Springs (same channel as the trivia show)
- Voice: ElevenLabs voice_id `cgSgspJ2msm6clMCkdW9`, model `eleven_multilingual_v2`,
  stability 0.45 / similarity 0.85 / **style 0.5** (bumped from 0.3 for personality)

---

## Voice & tone — the host's personality

The same voice as the trivia show, but **the writing should give her a real
personality**. Think: smart older sister who's seen every movie, isn't
impressed by the obvious, drops a dad joke when there's an opening.

### Persona profile

- **Smart but not academic.** Knows the trivia cold, would never lecture.
- **Lightly sarcastic.** Especially when the question is "obvious" — she's
  in on the joke with the viewer.
- **Valley-girl adjacent but never cartoonish.** Modern, casual,
  conversational. *Not* "like, oh my god" — more "okay, this one's a
  layup" / "honestly, same energy."
- **Era-aware.** When the question is about the 90s, lean into the 90s
  vibe ("peak hair gel era"). When it's recent, drop a current reference.
- **Dad jokes only when earned.** One genuine pun per episode max. If none
  presents itself naturally, skip it. Forced jokes are worse than no joke.
- **Never mean.** She roasts a *movie*, not a person.

### Where the personality shows up

Personality lives in **four places** in `questions.json`:

1. `intro` — the welcome line
2. `outro` — the goodbye line
3. `fun_fact` — the one-liner after each answer reveal (most important —
   20 of these per episode)
4. The connective tissue inside the option-introduction line is generated
   automatically — DO NOT try to embellish "Is it A: ...". Keep that flat.

### Examples — neutral vs. with personality

**Intro (SEO-critical — see template below):**

- ❌ Buries the keywords: *"Hey hey, welcome back to Quizzy Springs. Today:
  90s rom-coms — peak hair gel..."* (YouTube algorithm parses the first
  ~30 seconds heavily; "Welcome back" filler wastes prime SEO real estate)
- ✅ Leads with the keyword phrase, then personality: *"Today on Quizzy
  Springs we're going back to the 90s for the ultimate rom-com trivia quiz.
  Peak hair gel, peak boom boxes, peak 'I'm sorry, I should not have done
  that.' Twenty questions, mixed difficulty. Let's go."*

**REQUIRED intro template** (the keyword phrase MUST fire in the first 7
seconds — that's what YouTube's auto-transcript indexes):

> *"Today on Quizzy Springs we're [going back to / diving into / testing your
> knowledge of] **[TOPIC]** — the **[TOPIC]** trivia quiz. [One short
> personality line, ≤15 words]. Twenty questions, mixed difficulty. Let's go."*

The full topic phrase ("the 90s rom-com trivia quiz", "the Marvel actors
quiz", "the Pixar voice actors trivia quiz") MUST appear in spoken form
within the first 7 seconds. Personality follows.

**Fun fact (supporting cast question):**

- ❌ *"Alexander filmed this the same year Seinfeld's second season aired."*
- ✅ *"Yep — Alexander was already Costanza-ing it up on Seinfeld that same
  year. 1990 was just his year."*

**Fun fact (recognizable actor):**

- ❌ *"Rudd was 26 when this came out."*
- ✅ *"Paul Rudd was 26 playing a college student here. The man simply
  refuses to age — at this point we just accept it."*

**Fun fact (factual / year question):**

- ❌ *"Released in 1997."*
- ✅ *"1997. Same year Titanic ate the box office — and somehow this one
  still hit too."*

**Outro — date-agnostic ONLY:**

The host has no reliable way to know which day of the week the next episode
will publish. **Never name a specific day** in the outro — say "see you
next time" or "see you in a few days" instead.

- ❌ *"...so we can do this again Tuesday. See you then."* (the next video
  might be Thursday or Saturday — model has no way to know)
- ❌ *"...catch you Friday."*
- ✅ *"Annnd that's a wrap. Drop your score in the comments — be honest, no
  one's grading. If you had fun, smash that subscribe button so you don't
  miss the next one. See you next time."*
- ✅ *"...subscribe so you catch the next quiz. See you soon."*

### Hard rules — DO NOT violate

These break the voiceover or break the brand:

- **No profanity, no slurs, no anything PG-13+.** This is a family-friendly
  channel.
- **No emoji in TTS text.** ElevenLabs reads them literally as "smiley face."
- **No slang that mispronounces.** Avoid "amirite," "yeet," text-speak.
  Modern but spoken-English-only.
- **No "subscribe" / "like" CTAs inside questions** — only in intro/outro.
- **No fourth-wall-breaking that references the script** (e.g., "as the
  questions are generated"). She's a host, not an AI narrator.
- **Question text + option text stays NEUTRAL.** Personality only in
  `intro`, `outro`, and `fun_fact`. The question itself must be a clean
  factual question — anything else makes the audio for that question feel
  weird.
- **Never roast a real living person.** Roast a *movie*, a *plot*, an
  *era*, a *trope*. Not a human being.
- **One dad joke max per episode.** Less is more.
- **No specific weekdays in the outro.** Date-agnostic closers only (see
  outro examples above).
- **Lead with the topic keyword in the intro.** Required (see intro
  template above).

### A note on style=0.5

The voiceover is generated with ElevenLabs `style=0.5` (vs. 0.3 on the
trivia show). This means the voice will lean harder into the inflection
implicit in the writing. **Write punctuation deliberately** — em-dashes
for natural pauses, italics for emphasis (just bake the emphasis into the
phrasing, ElevenLabs doesn't read markdown), short sentences for punch.

---

## Repo layout (movies-specific files)

```
Quizzy Springs Videos/
├── README.md                   ← trivia show runbook (Mon/Wed/Fri)
├── README-movies.md            ← THIS FILE (Tue/Thu/Sat)
├── topics-movies.txt           ← queue of upcoming Hollywood topics
├── run-movies-episode.sh       ← launchd-fired daily driver
├── com.quizzysprings.movies.plist  ← Tue/Thu/Sat 10 AM trigger
├── script/
│   ├── tmdb_fetch.py             ← TMDB client + image cache
│   ├── gen_voiceover_movies.py   ← style=0.5 wrapper around gen_voiceover.py
│   ├── gen_thumbnail_openai.py   ← OpenAI gpt-image-2 thumbnail generator
│   ├── render_movies.py          ← new layout (image card left + options right)
│   ├── assemble_movies.py        ← parallel of assemble.py, parameterized
│   ├── pipeline_movies.py        ← orchestrator
│   └── youtube_upload_movies.py  ← upload wrapper (renames video for SEO)
├── refresh_youtube_token.py    ← manual OAuth re-auth (run if uploads start failing)
├── visuals/
│   ├── bg_intro_movies.png     ← intro background
│   ├── bg_question_movies.png  ← question card background (badge + logo baked in)
│   ├── bg_outro_movies.png     ← outro still (fallback)
│   └── bg_outro_movies.mp4     ← 5s animated outro w/ end-screen placeholders
└── episodes/<slug>/
    ├── questions.json          ← 20 questions WITH TMDB image paths
    ├── tmdb/                   ← cached TMDB API responses + downloaded images
    ├── vo/ segments/ _work/    ← intermediate (gitignored)
    └── final/                  ← video.mp4 + thumbnails + metadata
```

---

## To produce a new Hollywood episode (workflow for Claude)

When the user / cron says *"new Hollywood episode: 90s rom-coms"*:

### 1. Set up the episode slug

```
SLUG="$(date +%Y-%m-%d)-<slugified-topic>"   # e.g. 2026-05-19-90s-romcoms
mkdir -p "episodes/$SLUG"
```

### 2. Plan the 20 questions

Apply the **difficulty floor** rule: every question requires thought.

- Q1–6 easy   (recognizable supporting cast / iconic costars / well-known years)
- Q7–16 medium (character names, second-billed roles, year specifics)
- Q17–20 hard  (deep-cut characters, less obvious cast, niche trivia)

**Mix of formats** within a 20-question episode (don't repeat the same
format more than 8 times):

| Format | Show | Ask | Reveal |
|---|---|---|---|
| `cast_from_poster` | movie poster | "Who played [supporting character]?" | actor headshot |
| `co_star_film` | 2 actor headshots | "Which film did they both star in?" | poster |
| `filmography` | 3 movie posters | "Which actor was in all three?" | actor headshot |
| `year_guess` | 1 poster | "What year did this come out?" | (same poster) |
| `character_to_actor` | actor in costume still | "Who is this character?" | (same image) |

### 3. Fetch TMDB data + images

Use `script/tmdb_fetch.py`. For every question:

- Look up the movie / TV / person you need
- Pull the best image (≥1000px wide for posters, ≥500px wide for headshots)
- Save to `episodes/<slug>/tmdb/img/<descriptive_name>.jpg`
- Record the relative path in the question's `main_image` and
  `reveal_image` fields

Reference the `_sandbox/sanity_pull_90s_romcoms.py` for an example pattern.
For autonomous runs, write a small per-episode pull script following that
template.

### 4. Write `questions.json`

Schema (every field required unless noted):

```json
{
  "channel": "Quizzy Springs",
  "title": "<short title>",
  "intro_subtitle": "90S ROM-COMS",
  "intro": "<personality intro, see Voice & Tone above>",
  "outro": "<personality outro>",
  "questions": [
    {
      "n": 1,
      "difficulty": "easy",
      "category": "supporting cast",
      "era": "classic",
      "question_type": "cast_from_poster",
      "question": "<neutral question text, ≤17 words>",
      "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
      "answer": "A",
      "fun_fact": "<personality fun fact, ≤18 words>",
      "main_image": "tmdb/img/poster_xxx.jpg",
      "reveal_image": "tmdb/img/actor_yyy.jpg"
    }
  ]
}
```

**Constraints:**

- 20 questions, numbered 1–20
- Difficulty split: 6 / 10 / 4 (easy / medium / hard)
- Each question ≤17 words, each option ≤5 words, each fun_fact ≤18 words
- `intro_subtitle` ≤20 chars, ALL CAPS — appears as the big yellow line on every question card
- Never two adjacent questions of the same `question_type`
- For `year_guess`, set `reveal_image` = `main_image`
- For `character_to_actor`, often `reveal_image` = `main_image` (same still, just highlighted)

### 5. Validate

```bash
EPISODE_SLUG="$SLUG" .venv/bin/python -c "
import sys; sys.path.insert(0,'script'); import paths, json
d = json.loads(paths.QUESTIONS_FILE.read_text())
assert len(d['questions']) == 20
from collections import Counter
for q in d['questions']:
    assert len(q['question'].split()) < 18
    for k, v in q['options'].items(): assert len(v.split()) < 6
    assert len(q['fun_fact'].split()) < 18
    assert (paths.EP_DIR / q['main_image']).exists(), q['main_image']
    assert (paths.EP_DIR / q['reveal_image']).exists(), q['reveal_image']
prev = None
for q in d['questions']:
    assert q.get('question_type') != prev or prev is None, f'clustered at Q{q[\"n\"]}'
    prev = q.get('question_type')
print('difficulty:', Counter(q['difficulty'] for q in d['questions']))
print('OK')
"
```

For automated unattended runs the validation must pass before proceeding.

### 6. Run the pipeline

```bash
EPISODE_SLUG="$SLUG" .venv/bin/python script/pipeline_movies.py
```

Three stages run in sequence (~5–8 min total):

1. **Voiceover** (`gen_voiceover_movies.py` — 62 ElevenLabs TTS calls at style=0.5)
2. **Render** (`render_movies.py` — image-card layout, option fly-in)
3. **Assemble** (`assemble_movies.py` — audio mix, xfade transitions, final mux)

Final video lands at `episodes/<slug>/final/video.mp4`.

### 7. Generate thumbnails — **OpenAI `gpt-image-2`, NOT Higgsfield**

The movies pipeline uses **OpenAI's `gpt-image-2`** for thumbnails, not
Higgsfield. Reason: Higgsfield's `nano_banana_2` garbles text ("Sleepless
in Seella," "Can YASS this quiz") and invents distorted celebrity faces.
gpt-image-2 renders text and typography accurately.

**Just run the helper — it does everything:**

```bash
EPISODE_SLUG="<slug>" .venv/bin/python script/gen_thumbnail_openai.py
```

It reads `intro_subtitle` from `questions.json`, generates 3 distinct
thumbnails (topic-direct text on different palettes), crops to 16:9, and
saves to `final/thumbnail_{1,2,3}.png` at 1280×720 (under 2 MB each — no
post-processing needed).

**Cost:** ~$0.18/episode (3 images × $0.06 at 1536×1024 standard quality).

#### Thumbnail vs. title wording — split surfaces strategically

| Surface | Style | Example for 90s rom-coms |
|---|---|---|
| **Thumbnail text** | **Topic-direct, 3–5 words, ALL CAPS** | "90s ROM-COM QUIZ" |
| **Video title** (line 1 of `title_options.txt`) | Hook / curiosity gap | "Only 90s Kids Will Get This Rom-Com Quiz" |
| **Description hook (line 1 of `description.txt`)** | Challenge / question | "Think you know your 90s rom-coms?" |

The thumbnail is a 0.3-second scroll-stopping device — viewers scan for
"what is this?" before clicking. Topic-direct words classify instantly and
out-perform curiosity-gap lines on the thumbnail. Curiosity hooks belong
in the *title*, not the thumbnail. The helper script handles the thumbnail
wording automatically — you only need to write the title and description.

### 8. Write metadata — **REQUIRED — do not skip**

The automated runner now refuses to upload to YouTube if any of these three
files are missing or empty. Write all three before printing `EPISODE_COMPLETE`.

**Files (all under `episodes/<slug>/final/`):**

1. `title_options.txt` — 5 candidate titles, one per line, no numbering.
   First line will be used as the actual YouTube title.
   - ❌ "Quizzy Springs — 90s Rom-Coms Quiz"
   - ✅ "Can You Pass This 90s Rom-Com Cast Quiz? (Tough)"
   - ✅ "Only Real 90s Kids Know Who Played Phil Stuckey"

2. `description.txt` — algorithm-optimized, ~200 words. Same structure as
   the trivia README's Step 6 (hook + named entities + CTA + chapters +
   hashtags). Personality on the first line (the 150-char hook):
   *"Think you know your 90s rom-coms? Twenty questions, mixed difficulty,
   and yes — Q17 is unfair on purpose."*
   The TMDB attribution block (see below) MUST be appended last.

3. `tags.txt` — 25 comma-separated tags, mix of broad ("movie trivia",
   "90s movies") + specific named entities pulled from the actual questions.

**Verification before printing EPISODE_COMPLETE:** Confirm each file exists
and is non-empty. The runner's guardrail will halt the upload if any of
the three is missing, leaving the video on disk but unpublished.

---

## TMDB attribution

YouTube descriptions for movies episodes **must** include:

```
Movie and TV data and images provided by TMDB (themoviedb.org).
This product uses the TMDB API but is not endorsed or certified by TMDB.
```

Add this as the last block of `description.txt`, before the hashtags.

---

## Costs per episode

| Item | Calls | Cost |
|---|---|---|
| Voiceover (62 ElevenLabs TTS clips, style=0.5) | 62 | $3–5 |
| TMDB | ~80 | $0 (free) |
| Music / SFX / fonts / backgrounds | 0 | $0 (reused) |
| Thumbnails (3 × OpenAI gpt-image-2 at 1536×1024 std) | 3 | ~$0.18 |
| **Total** | — | **~$3.20–5.20** |

Wall-clock after questions written: ~5–8 minutes.

---

## Filename / SEO note

The pipeline writes the final video as `final/video.mp4`. The upload step
(`youtube_upload_movies.py`) automatically renames it to a topic-derived
filename (e.g. `90s-rom-coms.mp4`) before uploading, so the filename
YouTube sees matches the content. This is a minor but real ranking signal.

You don't need to do anything for this — the rename happens automatically
in the upload wrapper.

---

## Troubleshooting YouTube uploads

If a cron run fails with `401`, `youtubeSignupRequired`, or `invalid_grant`,
the OAuth refresh token has expired/been revoked. Fix:

1. Make sure your default browser is logged into the **Quizzy Springs**
   Google account (not Mindstorm, not personal).
2. Run: `.venv/bin/python refresh_youtube_token.py`
3. Complete the browser flow.
4. Retry the failed upload:
   `EPISODE_SLUG=<slug> .venv/bin/python script/youtube_upload_movies.py <slug>`
