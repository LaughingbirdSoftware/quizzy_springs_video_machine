#!/usr/bin/env bash
# Re-target the global elevenlabs-player MCP output to a project of your choice.
#
# Setup (once):
#   ln -s "$(pwd)/audio" ~/.elevenlabs-output
#   # then set Claude Code → Settings → Extensions → elevenlabs-player
#   # → Output Directory = /Users/<you>/.elevenlabs-output
#
# Usage:
#   ./script/set_elevenlabs_output.sh                       # points at THIS project's audio/
#   ./script/set_elevenlabs_output.sh /path/to/other/audio  # points elsewhere
#
# NOTE: this only affects the elevenlabs-player MCP. The Quizzy Springs
# quiz pipeline does NOT use that MCP — it calls the ElevenLabs REST API
# directly and writes to episodes/<slug>/vo/ regardless of this setting.

set -euo pipefail
TARGET="${1:-$(cd "$(dirname "$0")/.." && pwd)/audio}"
LINK="$HOME/.elevenlabs-output"

if [ ! -d "$TARGET" ]; then
    echo "ERROR: target directory does not exist: $TARGET" >&2
    exit 1
fi

ln -sfn "$TARGET" "$LINK"
echo "elevenlabs-player output → $TARGET"
echo "(symlink: $LINK)"
