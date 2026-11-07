"""Download the newest SubsPlease release, extract English subtitles, and upload it to VK."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, parse_qs

import feedparser
import requests

RSS_URL = "https://subsplease.org/rss/?r=1080"
VK_API_VERSION = "5.199"
ROOT = Path(__file__).resolve().parent
DOWNLOAD_DIR = ROOT / ".downloads"
SUBTITLE_DIR = ROOT / "subtitles"
POSTER_DIR = ROOT / "posters"
REQUEST_TIMEOUT = 60


def slugify(title: str) -> str:
    """Create a stable, filesystem-safe slug from an RSS title."""
    title = re.sub(r"^\[SubsPlease\]\s*", "", title, flags=re.I)
    title = re.sub(r"\s*\[[0-9A-F]{8}\]", "", title, flags=re.I)
    title = re.sub(r"\s*\((?:480|720|1080|2160)p\)", "", title, flags=re.I)
    title = re.sub(r"\.[^.]+$", "", title)
    title = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()
    return title or "latest-anime"


def latest_release() -> dict[str, str]:
    feed = feedparser.parse(RSS_URL)
    if getattr(feed, "bozo", False) and not feed.entries:
        raise RuntimeError(f"Could not parse SubsPlease RSS: {feed.bozo_exception}")
    if not feed.entries:
        raise RuntimeError("SubsPlease RSS returned no entries")
    entry = feed.entries[0]
    return {
        "title": entry.get("title", "SubsPlease release"),
        "magnet": entry.get("link", ""),
        "id": entry.get("id", ""),
    }


def download_release(magnet: str) -> Path:
    if not magnet.startswith("magnet:"):
        raise RuntimeError("The RSS entry does not contain a magnet URL")
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    # aria2c selects the video file from the torrent and does not retain the torrent.
    command = [
        "aria2c", "--dir", str(DOWNLOAD_DIR), "--seed-time=0",
        "--bt-stop-timeout=60", "--file-allocation=none",
        "--max-connection-per-server=4", "--summary-interval=30", magnet,
    ]
    subprocess.run(command, check=True)
    videos = sorted(
        p for p in DOWNLOAD_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in {".mkv", ".mp4", ".webm"}
    )
    if not videos:
        raise RuntimeError("aria2c completed but no video file was downloaded")
    return max(videos, key=lambda p: p.stat().st_size)


def extract_english_subtitle(video_path: Path, slug: str) -> Path:
    SUBTITLE_DIR.mkdir(exist_ok=True)
    output = SUBTITLE_DIR / f"{slug}-en.vtt"
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "s",
         "-show_entries", "stream=index:stream_tags=language",
         "-of", "json", str(video_path)],
        check=True, capture_output=True, text=True,
    )
    streams = json.loads(probe.stdout).get("streams", [])
    english = next((s for s in streams if (s.get("tags") or {}).get("language", "").lower() in {"en", "eng", "english"}), None)
    selected = english or (streams[0] if streams else None)
    if not selected:
        raise RuntimeError("The downloaded video has no subtitle stream")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-map", f"0:{selected['index']}", str(output)],
        check=True,
    )
    return output


def fetch_kitsu_poster(title: str, slug: str) -> Path:
    POSTER_DIR.mkdir(exist_ok=True)
    # Remove release metadata before searching Kitsu.
    query = re.sub(r"^\[SubsPlease\]\s*|\s*-\s*\d+\s*\(.*$", "", title, flags=re.I).strip()
    response = requests.get(
        "https://kitsu.io/api/edge/anime",
        params={"filter[text]": query},
        headers={"Accept": "application/vnd.api+json"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json().get("data", [])
    if not data:
        raise RuntimeError(f"No Kitsu anime result for {query!r}")
    image_url = (data[0].get("attributes", {}).get("posterImage") or {}).get("original")
    if not image_url:
        raise RuntimeError("Kitsu result has no poster image")
    image = requests.get(image_url, timeout=REQUEST_TIMEOUT)
    image.raise_for_status()
    output = POSTER_DIR / f"{slug}.jpg"
    output.write_bytes(image.content)
    return output


def upload_video_to_vk(video_path: Path, title: str) -> dict:
    token = os.getenv("VK_ACCESS_TOKEN")
    group_id = os.getenv("VK_GROUP_ID")
    if not token or not group_id:
        raise RuntimeError("VK_ACCESS_TOKEN and VK_GROUP_ID must be configured")
    try:
        group_id = str(abs(int(group_id.strip())))
    except ValueError as exc:
        raise RuntimeError("VK_GROUP_ID must be a numeric VK community ID") from exc
    params = {"access_token": token, "v": VK_API_VERSION, "group_id": group_id,
              "name": title, "description": "Uploaded via Anime Automation Pipeline", "wallpost": 0}
    saved = requests.post("https://api.vk.com/method/video.save", params=params, timeout=REQUEST_TIMEOUT)
    saved.raise_for_status()
    payload = saved.json()
    if "error" in payload:
        raise RuntimeError(f"VK video.save failed: {payload['error']}")
    upload_url = payload.get("response", {}).get("upload_url")
    if not upload_url:
        raise RuntimeError("VK video.save returned no upload URL")
    with video_path.open("rb") as video:
        uploaded = requests.post(upload_url, files={"video_file": (video_path.name, video, "video/x-matroska")}, timeout=REQUEST_TIMEOUT)
    uploaded.raise_for_status()
    result = uploaded.json()
    if "error" in result:
        raise RuntimeError(f"VK upload failed: {result['error']}")
    return result


def validate_vk_configuration() -> None:
    """Validate the token and group before downloading a large release."""
    token = os.getenv("VK_ACCESS_TOKEN")
    raw_group_id = (os.getenv("VK_GROUP_ID") or "").strip()
    if not token or not raw_group_id:
        raise RuntimeError("VK_ACCESS_TOKEN and VK_GROUP_ID must be configured")
    try:
        group_id = str(abs(int(raw_group_id)))
    except ValueError as exc:
        raise RuntimeError("VK_GROUP_ID must be a numeric VK community ID") from exc
    response = requests.get(
        "https://api.vk.com/method/groups.getById",
        params={"access_token": token, "v": VK_API_VERSION, "group_id": group_id},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        error = payload["error"]
        raise RuntimeError(
            f"VK preflight failed (code {error.get('error_code')}): {error.get('error_msg')}"
        )
    groups = payload.get("response", {}).get("groups", [])
    if not groups:
        raise RuntimeError("VK preflight found no accessible group for VK_GROUP_ID")
    print(f"VK preflight passed for group {groups[0].get('id')} ({groups[0].get('name', 'unnamed')})")


def commit_assets() -> None:
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=ROOT, check=True)
    subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=ROOT, check=True)
    subprocess.run(["git", "add", "subtitles", "posters"], cwd=ROOT, check=True)
    status = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if status.returncode == 0:
        print("No new subtitle or poster assets to commit.")
        return
    commit_message = f"Add assets for {os.getenv('ANIME_SLUG', 'latest release')}"
    subprocess.run(["git", "commit", "-m", commit_message], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=ROOT, check=True)


def main() -> int:
    validate_vk_configuration()
    release = latest_release()
    slug = slugify(release["title"])
    os.environ["ANIME_SLUG"] = slug
    print(f"Processing: {release['title']} ({slug})")
    video = download_release(release["magnet"])
    extract_english_subtitle(video, slug)
    fetch_kitsu_poster(release["title"], slug)
    upload_video_to_vk(video, release["title"])
    commit_assets()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        raise
