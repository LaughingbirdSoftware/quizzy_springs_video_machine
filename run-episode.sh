#!/bin/bash
#
# run-episode.sh — Quizzy Springs automated episode creation + scheduled YouTube publish
#
# Flow:
#   10:00 AM — script fires, picks next topic, runs Claude Code pipeline
#   ~10:08 AM — video done, uploads to YouTube as PRIVATE with scheduled 2 PM publish
#   2:00 PM — YouTube automatically flips it to PUBLIC, fully encoded in HD/4K
#
# Scheduled via launchd to run Mon/Wed/Fri at 10 AM Pacific.
# Logs in logs/run-YYYY-MM-DD.log
# ─────────────────────────────────────────────────────────────────────────────

set -e

# ─── CONFIG: EDIT THESE TWO PATHS ───────────────────────────────────────────
PROJECT_DIR="/Users/marcsylvester/Quizzy Springs Videos"
CLAUDE_BIN="/Users/marcsylvester/.nvm/versions/node/v20.20.2/bin/claude"
# ────────────────────────────────────────────────────────────────────────────

cd "$PROJECT_DIR"

mkdir -p logs
DATE_STAMP=$(date +%Y-%m-%d)
LOG="$PROJECT_DIR/logs/run-$DATE_STAMP.log"

echo "════════════════════════════════════════════════════════" >> "$LOG"
echo "▶ STARTED: $(date)" >> "$LOG"
echo "════════════════════════════════════════════════════════" >> "$LOG"

osascript -e 'display notification "Building today'"'"'s quiz video..." with title "Quizzy Springs"' || true

# ─── 1. Pick next topic ─────────────────────────────────────────────────────
if [ ! -s "$PROJECT_DIR/topics.txt" ]; then
    echo "❌ topics.txt is empty. Refill and try again." >> "$LOG"
    osascript -e 'display notification "topics.txt is empty! Add more topics." with title "Quizzy Springs ERROR"' || true
    exit 1
fi

TOPIC=$(head -n 1 "$PROJECT_DIR/topics.txt")
echo "📋 Today's topic: $TOPIC" >> "$LOG"

SLUG_TOPIC=$(echo "$TOPIC" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//' | sed 's/-$//')
SLUG="$DATE_STAMP-$SLUG_TOPIC"
echo "📁 Slug: $SLUG" >> "$LOG"

# ─── 2. Run Claude Code with the prompt ─────────────────────────────────────
PROMPT="Read the README.md file top to bottom, then produce a complete new episode for today's topic: $TOPIC.

Use this exact slug for the episode folder: $SLUG

IMPORTANT: This is a fully automated unattended run. Do NOT pause for user approval after generating questions.json. Generate the questions, validate them with the validation script in the README, and proceed directly through the entire pipeline:

  1. Generate questions.json (skip approval gate)
  2. Generate themed intro background (bg_intro.png minimum)
  3. Run the full pipeline (voiceover, render, assemble)
  4. Generate 3 thumbnails via Higgsfield
  5. Write title_options.txt, description.txt, tags.txt

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
    osascript -e 'display notification "Pipeline failed — check log" with title "Quizzy Springs ERROR"' || true
    exit 1
fi

echo "✅ Video created: $FINAL_VIDEO" >> "$LOG"
ls -lh "$FINAL_VIDEO" >> "$LOG"

# ─── 3. Upload to YouTube (scheduled for 2 PM publish) ──────────────────────
echo "" >> "$LOG"
echo "📤 Uploading to YouTube (scheduled for 2 PM)..." >> "$LOG"

"$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/youtube_upload.py" "$SLUG" >> "$LOG" 2>&1
UPLOAD_EXIT=$?

if [ $UPLOAD_EXIT -ne 0 ]; then
    echo "⚠️  YouTube upload failed — video is still on disk." >> "$LOG"
    osascript -e 'display notification "Video done, but YouTube upload failed" with title "Quizzy Springs"' || true
    exit 1
fi

# ─── 4. Success ─────────────────────────────────────────────────────────────
sed -i '' '1d' "$PROJECT_DIR/topics.txt"
REMAINING=$(wc -l < "$PROJECT_DIR/topics.txt" | tr -d ' ')

echo "" >> "$LOG"
echo "════════════════════════════════════════════════════════" >> "$LOG"
echo "✅ DONE: $(date)" >> "$LOG"
echo "📊 $REMAINING topics remaining in queue" >> "$LOG"
echo "════════════════════════════════════════════════════════" >> "$LOG"

osascript -e "display notification \"$TOPIC quiz scheduled to go live at 2 PM. $REMAINING topics left.\" with title \"Quizzy Springs ✅\"" || true

if [ "$REMAINING" -lt 5 ]; then
    osascript -e "display notification \"Only $REMAINING topics left! Refill topics.txt.\" with title \"Quizzy Springs ⚠️\"" || true
fi

exit 0
