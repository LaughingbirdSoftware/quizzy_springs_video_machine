#!/usr/bin/env python3
"""
youtube_upload.py — Upload a finished Quizzy Springs episode to YouTube.

Usage:
    python youtube_upload.py <episode_slug>

Behavior:
    - Uploads the video as PRIVATE
    - Schedules it to go PUBLIC automatically at 2:00 PM Pacific today
    - This gives YouTube ~4 hours to fully encode HD/4K before viewers see it,
      so the first viewers don't get a blurry 360p version.

Reads from episodes/<slug>/final/:
    - video.mp4           → uploads as the video
    - title_options.txt   → uses first non-empty line as the title
    - description.txt     → full description
    - tags.txt            → comma-separated tags
    - thumbnail_1.png     → uploaded as custom thumbnail

First run opens a browser for OAuth authorization. After that, token.pickle
saves credentials and uploads are silent forever.
"""

import os
import re
import sys
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# ─── CONFIG ─────────────────────────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]
CATEGORY_ID = "24"             # 24 = Entertainment, 27 = Education
MADE_FOR_KIDS = False

# Scheduled publish time (local Pacific time, 24-hour format)
PUBLISH_HOUR = 14              # 2 PM
PUBLISH_MINUTE = 0
PUBLISH_TIMEZONE = "America/Los_Angeles"

# Minimum buffer between upload finish and publish time.
# If less than this remains, push the publish to next day at the same time.
MIN_BUFFER_MINUTES = 30
# ────────────────────────────────────────────────────────────────────────────

PROJECT_DIR = Path(__file__).parent.resolve()
CLIENT_SECRETS = PROJECT_DIR / "client_secrets.json"
TOKEN_FILE = PROJECT_DIR / "token.pickle"


def compute_publish_time():
    """Return ISO 8601 UTC string for today at 2pm Pacific (or tomorrow if too soon)."""
    pacific = ZoneInfo(PUBLISH_TIMEZONE)
    now_pacific = datetime.now(pacific)

    target = now_pacific.replace(
        hour=PUBLISH_HOUR,
        minute=PUBLISH_MINUTE,
        second=0,
        microsecond=0,
    )

    buffer = timedelta(minutes=MIN_BUFFER_MINUTES)
    if target - now_pacific < buffer:
        target = target + timedelta(days=1)
        print(f"⚠️  Less than {MIN_BUFFER_MINUTES} min until 2 PM — scheduling for tomorrow.")

    # YouTube wants RFC 3339 / ISO 8601 in UTC with Z suffix
    target_utc = target.astimezone(ZoneInfo("UTC"))
    iso = target_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    print(f"📅 Will go public at: {target.strftime('%A, %b %d at %-I:%M %p %Z')}")
    return iso, target


def get_authenticated_service():
    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Refreshing expired token...")
            creds.refresh(Request())
        else:
            if not CLIENT_SECRETS.exists():
                print(f"❌ Missing {CLIENT_SECRETS}")
                print("   Download OAuth credentials from Google Cloud Console.")
                sys.exit(1)
            print("🌐 Opening browser for one-time YouTube authorization...")
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    return build("youtube", "v3", credentials=creds)


def read_metadata(slug):
    final_dir = PROJECT_DIR / "episodes" / slug / "final"

    video_path = final_dir / "video.mp4"
    if not video_path.exists():
        print(f"❌ Video not found: {video_path}")
        sys.exit(1)

    # Title: first non-empty line of title_options.txt, stripped of numbering
    title_file = final_dir / "title_options.txt"
    title = None
    if title_file.exists():
        for line in title_file.read_text().splitlines():
            cleaned = re.sub(r'^\s*\d{1,2}[.\)\-:]\s*', '', line.strip())
            if cleaned and len(cleaned) > 5:
                title = cleaned[:100]
                break
    if not title:
        title = f"Quizzy Springs Quiz - {slug}"

    # Description
    desc_file = final_dir / "description.txt"
    description = desc_file.read_text() if desc_file.exists() else ""
    description = description[:5000]

    # Tags: comma-separated, total under 500 chars
    tags_file = final_dir / "tags.txt"
    tags = []
    if tags_file.exists():
        raw = tags_file.read_text().replace("\n", ",")
        tags = [t.strip() for t in raw.split(",") if t.strip()]
    while tags and sum(len(t) for t in tags) + len(tags) > 480:
        tags.pop()

    thumbnail_path = final_dir / "thumbnail_1.png"

    return {
        "video": video_path,
        "title": title,
        "description": description,
        "tags": tags,
        "thumbnail": thumbnail_path if thumbnail_path.exists() else None,
    }


def upload_video(youtube, meta, publish_iso):
    """Upload as private + scheduled — YouTube auto-flips to public at publish_iso."""
    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": CATEGORY_ID,
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": "private",   # MUST be 'private' when using publishAt
            "publishAt": publish_iso,
            "selfDeclaredMadeForKids": MADE_FOR_KIDS,
            "embeddable": True,
        },
    }

    media = MediaFileUpload(str(meta["video"]), chunksize=-1, resumable=True,
                            mimetype="video/mp4")

    print(f"📤 Uploading: {meta['title']}")
    print(f"   File: {meta['video']} ({meta['video'].stat().st_size / 1_048_576:.1f} MB)")

    request = youtube.videos().insert(part=",".join(body.keys()), body=body,
                                       media_body=media)

    response = None
    last_progress = -10
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            if pct >= last_progress + 10:
                print(f"   ...{pct}%")
                last_progress = pct

    video_id = response["id"]
    print(f"✅ Uploaded (scheduled): https://www.youtube.com/watch?v={video_id}")

    if meta["thumbnail"]:
        try:
            print(f"🖼️  Setting custom thumbnail...")
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(meta["thumbnail"]))
            ).execute()
            print("✅ Thumbnail set")
        except HttpError as e:
            print(f"⚠️  Thumbnail upload failed (account may need verification): {e}")

    return video_id


def main():
    if len(sys.argv) < 2:
        print("Usage: python youtube_upload.py <episode_slug>")
        sys.exit(1)

    slug = sys.argv[1]
    print(f"🎬 Episode: {slug}")

    publish_iso, publish_local = compute_publish_time()
    meta = read_metadata(slug)

    print(f"📝 Title: {meta['title']}")
    print(f"🏷️  Tags: {len(meta['tags'])} tags")
    print(f"🖼️  Thumbnail: {'yes' if meta['thumbnail'] else 'none'}")

    youtube = get_authenticated_service()
    video_id = upload_video(youtube, meta, publish_iso)

    # Save the YouTube URL + scheduled time for reference
    url_file = PROJECT_DIR / "episodes" / slug / "final" / "youtube_url.txt"
    url_file.write_text(
        f"https://www.youtube.com/watch?v={video_id}\n"
        f"Scheduled to go public: {publish_local.strftime('%A, %b %d at %-I:%M %p %Z')}\n"
    )
    print(f"💾 URL saved to {url_file}")


if __name__ == "__main__":
    try:
        main()
    except HttpError as e:
        print(f"❌ YouTube API error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        sys.exit(1)
