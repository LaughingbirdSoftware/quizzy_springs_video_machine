#!/usr/bin/env python3
"""Voiceover for the MOVIES quiz — same engine as gen_voiceover.py, bumped style.

Why: the host voice should sound more expressive on the Hollywood show. We
override only the `style` parameter (0.3 → 0.5) to give her more inflection
for sarcasm + dad-joke delivery. Voice ID, stability, similarity, and model
stay identical so the host sounds like the same person across both shows.

Zero edits to gen_voiceover.py — we monkey-patch its module-level VS dict.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_voiceover  # noqa: E402

# Override only the style — keep stability / similarity / voice_id / model.
gen_voiceover.VS = {
    "stability": 0.45,
    "similarity_boost": 0.85,
    "style": 0.5,           # ↑ from 0.3 for more expressive delivery
    "use_speaker_boost": True,
}

if __name__ == "__main__":
    gen_voiceover.main()
