#!/usr/bin/env python3
"""Manually re-do the YouTube OAuth flow to refresh token.pickle.

Run this whenever a scheduled upload fails with 401 / youtubeSignupRequired /
invalid_grant — i.e. whenever the cached refresh token has stopped working.

Opens your default browser for a one-time Google authorization. **Make sure
Chrome is set to the Quizzy Springs Google account before running**, or use
a browser/profile that's logged into the QS account.

Usage:
    /Users/marcsylvester/Quizzy\\ Springs\\ Videos/.venv/bin/python refresh_youtube_token.py

After it completes, retry the failed upload manually:
    EPISODE_SLUG=<slug> /Users/marcsylvester/Quizzy\\ Springs\\ Videos/.venv/bin/python \\
        script/youtube_upload_movies.py <slug>
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIENT_SECRETS = ROOT / "client_secrets.json"
TOKEN_FILE = ROOT / "token.pickle"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def main() -> int:
    if not CLIENT_SECRETS.exists():
        print(f"❌ Missing {CLIENT_SECRETS}")
        print("   Download from Google Cloud Console → APIs & Services → Credentials")
        return 1

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("❌ google-auth-oauthlib not installed.")
        print(f"   Run: {ROOT}/.venv/bin/pip install google-auth-oauthlib")
        return 1

    print("🌐 Opening browser for OAuth authorization...")
    print("   Make sure your browser is logged into the Quizzy Springs Google account!")
    print()
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    with open(TOKEN_FILE, "wb") as f:
        pickle.dump(creds, f)
    print(f"\n✅ Refreshed token saved to {TOKEN_FILE}")
    print("   Next cron run should upload without browser intervention.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
