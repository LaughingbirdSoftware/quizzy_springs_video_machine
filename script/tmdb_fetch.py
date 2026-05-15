"""TMDB (themoviedb.org) client used by the Hollywood/Movies episode pipeline.

Self-contained: no edits to the existing audio/quiz pipeline. Reads
TMDB_READ_ACCESS_TOKEN (v4 bearer, preferred) or TMDB_API_KEY (v3) from .env.

On-disk cache layout (override with TMDB_CACHE_DIR):
    <cache>/json/<safe-endpoint>.json   API responses
    <cache>/img/<safe-name>             downloaded posters/headshots/stills

When EPISODE_SLUG is set, cache defaults to episodes/<slug>/tmdb/.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import paths

paths.load_env()

API_ROOT = "https://api.themoviedb.org/3"
IMG_ROOT = "https://image.tmdb.org/t/p"
BEARER = os.environ.get("TMDB_READ_ACCESS_TOKEN", "").strip()
API_KEY = os.environ.get("TMDB_API_KEY", "").strip()

if not BEARER and not API_KEY:
    raise RuntimeError("Neither TMDB_READ_ACCESS_TOKEN nor TMDB_API_KEY found in .env")


def _cache_root() -> Path:
    override = os.environ.get("TMDB_CACHE_DIR")
    if override:
        return Path(override)
    if paths.SLUG:
        return paths.EP_DIR / "tmdb"
    return paths.ROOT / "tmdb_cache"


def _safe(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", s).strip("_")[:180]


def _request_json(url: str, retries: int = 4) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if BEARER:
        headers["Authorization"] = f"Bearer {BEARER}"
    elif "api_key=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}api_key={API_KEY}"

    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt
                time.sleep(wait)
                last_err = e
                continue
            if 500 <= e.code < 600:
                time.sleep(1 + attempt)
                last_err = e
                continue
            raise
        except URLError as e:
            time.sleep(1 + attempt)
            last_err = e
    raise RuntimeError(f"TMDB request failed after {retries} attempts: {url} — {last_err}")


def api(endpoint: str, **params: Any) -> dict[str, Any]:
    """GET an endpoint with disk caching. Endpoint is the path after /3, e.g. 'movie/680'."""
    qs = "&".join(f"{k}={quote(str(v))}" for k, v in sorted(params.items()) if v is not None)
    cache_key = _safe(endpoint + ("__" + qs if qs else ""))
    cache_file = _cache_root() / "json" / f"{cache_key}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    url = f"{API_ROOT}/{endpoint.lstrip('/')}"
    if qs:
        url = f"{url}?{qs}"
    data = _request_json(url)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return data


# ---- High-level helpers -------------------------------------------------

def search_movie(query: str, year: int | None = None) -> dict[str, Any] | None:
    data = api("search/movie", query=query, year=year, include_adult="false")
    results = data.get("results") or []
    return results[0] if results else None


def search_tv(query: str, first_air_date_year: int | None = None) -> dict[str, Any] | None:
    data = api("search/tv", query=query, first_air_date_year=first_air_date_year, include_adult="false")
    results = data.get("results") or []
    return results[0] if results else None


def search_person(query: str) -> dict[str, Any] | None:
    data = api("search/person", query=query, include_adult="false")
    results = data.get("results") or []
    return results[0] if results else None


def movie(movie_id: int) -> dict[str, Any]:
    return api(f"movie/{movie_id}")


def tv(tv_id: int) -> dict[str, Any]:
    return api(f"tv/{tv_id}")


def person(person_id: int) -> dict[str, Any]:
    return api(f"person/{person_id}")


def movie_credits(movie_id: int) -> dict[str, Any]:
    return api(f"movie/{movie_id}/credits")


def tv_credits(tv_id: int) -> dict[str, Any]:
    return api(f"tv/{tv_id}/aggregate_credits")


def person_movie_credits(person_id: int) -> dict[str, Any]:
    return api(f"person/{person_id}/movie_credits")


def person_images(person_id: int) -> dict[str, Any]:
    return api(f"person/{person_id}/images")


def movie_images(movie_id: int) -> dict[str, Any]:
    return api(f"movie/{movie_id}/images", include_image_language="en,null")


def tv_images(tv_id: int) -> dict[str, Any]:
    return api(f"tv/{tv_id}/images", include_image_language="en,null")


# ---- Cast / character lookup -------------------------------------------

def find_actor_for_character(movie_id: int, character_pattern: str) -> dict[str, Any] | None:
    """Return the cast entry whose 'character' field matches the pattern (case-insensitive substring or regex)."""
    cast = movie_credits(movie_id).get("cast") or []
    rx = re.compile(character_pattern, re.IGNORECASE)
    for c in cast:
        if rx.search(c.get("character") or ""):
            return c
    return None


# ---- Image download ----------------------------------------------------

def _best_image(images: Iterable[dict[str, Any]], min_width: int) -> dict[str, Any] | None:
    candidates = [im for im in images if (im.get("width") or 0) >= min_width]
    if not candidates:
        return None
    candidates.sort(key=lambda im: (im.get("vote_average") or 0, im.get("vote_count") or 0), reverse=True)
    return candidates[0]


def best_poster_path(movie_or_tv: dict[str, Any], min_width: int = 1000) -> str | None:
    posters = movie_or_tv.get("posters") or []
    pick = _best_image(posters, min_width)
    return (pick or {}).get("file_path")


def best_backdrop_path(movie_or_tv: dict[str, Any], min_width: int = 1280) -> str | None:
    backdrops = movie_or_tv.get("backdrops") or []
    pick = _best_image(backdrops, min_width)
    return (pick or {}).get("file_path")


def best_profile_path(person_imgs: dict[str, Any], min_width: int = 500) -> str | None:
    profiles = person_imgs.get("profiles") or []
    pick = _best_image(profiles, min_width)
    return (pick or {}).get("file_path")


def download_image(file_path: str, size: str = "original", dest_name: str | None = None) -> Path:
    """Download an image by its TMDB file_path (e.g. '/abc123.jpg'). Cached on disk."""
    if not file_path:
        raise ValueError("file_path is empty")
    name = dest_name or _safe(file_path.lstrip("/"))
    out = _cache_root() / "img" / name
    if out.exists() and out.stat().st_size > 0:
        return out
    url = f"{IMG_ROOT}/{size}{file_path}"
    out.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"Accept": "image/*"})
    with urlopen(req, timeout=30) as resp:
        out.write_bytes(resp.read())
    return out


# ---- CLI smoke test ----------------------------------------------------

if __name__ == "__main__":
    import sys
    title = " ".join(sys.argv[1:]) or "Pretty Woman"
    hit = search_movie(title)
    if not hit:
        print(f"No match for: {title}")
        sys.exit(1)
    print(f"{hit['title']} ({hit.get('release_date','?')[:4]})  id={hit['id']}")
    poster = hit.get("poster_path")
    if poster:
        p = download_image(poster, size="w780", dest_name=f"{_safe(hit['title'])}_poster.jpg")
        print(f"Poster saved: {p}")
    creds = movie_credits(hit["id"])
    for c in (creds.get("cast") or [])[:5]:
        print(f"  - {c.get('name')} as {c.get('character')}")
