#!/bin/bash
#
# run-movies-episode.sh — Quizzy Springs Hollywood Edition (movies/TV/celebrities)
#
# Flow:
#   10:00 AM (Tue/Thu/Sat) — script fires, picks next topic, runs Claude Code pipeline
#   ~10:08 AM — video done, uploads to YouTube as PRIVATE with scheduled 2 PM publish
#   2:00 PM — YouTube auto-flips it to PUBLIC, fully encoded
#
# Mirror of run-episode.sh but points at README-movies.md and topics-movies.txt.
# The current trivia pipeline (Mon/Wed/Fri) is unaffected.
# Logs in logs/run-movies-YYYY-MM-DD.log
# ─────────────────────────────────────────────────────────────────────────────

set -e

# ─── CONFIG ─────────────────────────────────────────────────────────────────
PROJECT_DIR="/Users/marcsylvester/Quizzy Springs Videos"
CLAUDE_BIN="/Users/marcsylvester/.nvm/versions/node/v20.20.2/bin/claude"
TOPICS_FILE="$PROJECT_DIR/topics-movies.txt"
README_FILE="README-movies.md"
# ────────────────────────────────────────────────────────────────────────────

cd "$PROJECT_DIR"

mkdir -p logs
DATE_STAMP=$(date +%Y-%m-%d)
LOG="$PROJECT_DIR/logs/run-movies-$DATE_STAMP.log"

echo "════════════════════════════════════════════════════════" >> "$LOG"
echo "▶ STARTED (movies): $(date)" >> "$LOG"
echo "════════════════════════════════════════════════════════" >> "$LOG"

osascript -e 'display notification "Building today'"'"'s Hollywood quiz..." with title "Quizzy Springs · Movies"' || true

# ─── 1. Pick next topic ─────────────────────────────────────────────────────
if [ ! -s "$TOPICS_FILE" ]; then
    echo "❌ $TOPICS_FILE is empty. Refill and try again." >> "$LOG"
    osascript -e 'display notification "topics-movies.txt is empty! Add more topics." with title "Quizzy Springs MOVIES ERROR"' || true
    exit 1
fi

TOPIC=$(head -n 1 "$TOPICS_FILE")
echo "🎬 Today's topic: $TOPIC" >> "$LOG"

SLUG_TOPIC=$(echo "$TOPIC" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//' | sed 's/-$//')
SLUG="$DATE_STAMP-$SLUG_TOPIC"
echo "📁 Slug: $SLUG" >> "$LOG"

# ─── 2. Run Claude Code with the prompt ─────────────────────────────────────
PROMPT="Read $README_FILE top to bottom, then produce a complete new Hollywood Edition episode for today's topic: $TOPIC.

Use this exact slug for the episode folder: $SLUG

IMPORTANT: This is a fully automated unattended run. Do NOT pause for user approval after generating questions.json. The full procedure:

  1. Plan 20 questions following the difficulty floor + format mix rules in $README_FILE.
  2. Fetch TMDB data and images for every question (use script/tmdb_fetch.py — save under episodes/$SLUG/tmdb/img/).
  3. Write questions.json with main_image + reveal_image paths AND personality-laden intro/outro/fun_fact text per the Voice & Tone section.
  4. Run the validation snippet from $README_FILE step 5.
  5. Run the pipeline: EPISODE_SLUG='$SLUG' .venv/bin/python script/pipeline_movies.py
  6. Generate 3 thumbnails via Higgsfield MCP.
  7. Write title_options.txt, description.txt, tags.txt with personality (see $README_FILE step 8).
  8. Append the TMDB attribution block to description.txt.

When complete, print 'EPISODE_COMPLETE: $SLUG' on its own line so the automation knows the run succeeded."

echo "🤖 Invoking Claude Code..." >> "$LOG"
echo "" >> "$LOG"

"$CLAUDE_BIN" -p "$PROMPT" \
    --output-format text \
    --dangerously-skip-permissions \
    >> "$LOG" 2>&1

CLAUDE_EXIT=$?
echo "" >> "$LOG"
echo "🤖 Claude Code exited with code: $CLAUDE_EXIT" >> "$LOG"

FINAL_VIDEO="$PROJECT_DIR/episodes/$SLUG/final/video.mp4"
if [ ! -f "$FINAL_VIDEO" ]; then
    echo "❌ Video file not found at $FINAL_VIDEO — pipeline failed." >> "$LOG"
    osascript -e 'display notification "Movies pipeline failed — check log" with title "Quizzy Springs MOVIES ERROR"' || true
    exit 1
fi

echo "✅ Video created: $FINAL_VIDEO" >> "$LOG"
ls -lh "$FINAL_VIDEO" >> "$LOG"

# ─── 2b. Verify metadata + thumbnails before upload ─────────────────────────
FINAL_DIR="$PROJECT_DIR/episodes/$SLUG/final"
MISSING=""
for f in title_options.txt description.txt tags.txt; do
    if [ ! -s "$FINAL_DIR/$f" ]; then MISSING="$MISSING $f"; fi
done
if [ -n "$MISSING" ]; then
    echo "❌ Metadata files missing or empty:$MISSING" >> "$LOG"
    echo "   Claude headless did not finish step 8 of README-movies.md." >> "$LOG"
    osascript -e 'display notification "Metadata missing — video on disk, NOT uploaded" with title "Quizzy Springs MOVIES ERROR"' || true
    exit 1
fi

# Shrink thumbnails > 1.9 MB to 1280x720 PNG (optimize) — YouTube caps at 2 MB.
for i in 1 2 3; do
    PNG="$FINAL_DIR/thumbnail_${i}.png"
    if [ -f "$PNG" ]; then
        SIZE=$(stat -f %z "$PNG")
        if [ "$SIZE" -gt 1900000 ]; then
            "$PROJECT_DIR/.venv/bin/python" -c "
from PIL import Image
im = Image.open('$PNG').convert('RGB').resize((1280, 720), Image.LANCZOS)
im.save('$PNG', 'PNG', optimize=True)
" >> "$LOG" 2>&1
            NEW_SIZE=$(stat -f %z "$PNG")
            echo "  shrank thumbnail_${i}.png: $((SIZE/1024)) KB → $((NEW_SIZE/1024)) KB" >> "$LOG"
        fi
    fi
done

# ─── 3. Upload to YouTube (scheduled for 2 PM publish) ──────────────────────
echo "" >> "$LOG"
echo "📤 Uploading to YouTube (scheduled for 2 PM)..." >> "$LOG"

"$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/script/youtube_upload_movies.py" "$SLUG" >> "$LOG" 2>&1
UPLOAD_EXIT=$?

if [ $UPLOAD_EXIT -ne 0 ]; then
    echo "⚠️  YouTube upload failed — video is still on disk." >> "$LOG"
    osascript -e 'display notification "Movies video done, but YouTube upload failed" with title "Quizzy Springs MOVIES"' || true
    exit 1
fi

# ─── 4. Success ─────────────────────────────────────────────────────────────
sed -i '' '1d' "$TOPICS_FILE"
REMAINING=$(wc -l < "$TOPICS_FILE" | tr -d ' ')

echo "" >> "$LOG"
echo "════════════════════════════════════════════════════════" >> "$LOG"
echo "✅ DONE (movies): $(date)" >> "$LOG"
echo "📊 $REMAINING movies topics remaining in queue" >> "$LOG"
echo "════════════════════════════════════════════════════════" >> "$LOG"

osascript -e "display notification \"$TOPIC quiz scheduled to go live at 2 PM. $REMAINING movies topics left.\" with title \"Quizzy Springs MOVIES ✅\"" || true

if [ "$REMAINING" -lt 5 ]; then
    osascript -e "display notification \"Only $REMAINING movies topics left! Refill topics-movies.txt.\" with title \"Quizzy Springs MOVIES ⚠️\"" || true
fi

exit 0
