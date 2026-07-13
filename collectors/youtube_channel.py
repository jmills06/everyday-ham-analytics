"""YouTube Data API v3 collector.

Collects:
- Channel lifetime totals (views, subscribers, video count)
- Per-video statistics for every upload (views, likes, comments)
- Video metadata (title, publish date, duration) into content/videos.json,
  preserving any hand-tagged or AI-tagged "topics" field on re-runs

Writes:
- data/latest/youtube.json            (board-facing snapshot)
- data/history/youtube_daily.jsonl    (one channel row per UTC day)
- data/history/videos/videos_daily.jsonl (one row per video per UTC day)
- data/content/videos.json            (metadata + topics, merged)

Auth: plain API key (YT_API_KEY). Read-only public data.
"""

import sys

import requests

from common import (
    CONTENT, HISTORY, LATEST, YT_CHANNEL_ID,
    ensure_dirs, read_json, require_env, upsert_daily_row,
    upsert_daily_rows, utc_now_iso, utc_today, write_json,
)

API = "https://www.googleapis.com/youtube/v3"
TIMEOUT = 30


def get(path: str, **params) -> dict:
    params["key"] = KEY
    r = requests.get(f"{API}/{path}", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_channel() -> dict:
    data = get("channels", part="statistics,contentDetails", id=YT_CHANNEL_ID)
    items = data.get("items", [])
    if not items:
        print("ERROR: channel not found", file=sys.stderr)
        sys.exit(1)
    ch = items[0]
    stats = ch["statistics"]
    return {
        "views": int(stats.get("viewCount", 0)),
        "subscribers": int(stats.get("subscriberCount", 0)),
        "videos": int(stats.get("videoCount", 0)),
        "uploads_playlist": ch["contentDetails"]["relatedPlaylists"]["uploads"],
    }


def fetch_all_video_ids(uploads_playlist: str) -> list[str]:
    ids, page_token = [], None
    while True:
        params = {"part": "contentDetails", "playlistId": uploads_playlist, "maxResults": 50}
        if page_token:
            params["pageToken"] = page_token
        data = get("playlistItems", **params)
        ids += [it["contentDetails"]["videoId"] for it in data.get("items", [])]
        page_token = data.get("nextPageToken")
        if not page_token:
            return ids


def fetch_videos(video_ids: list[str]) -> list[dict]:
    videos = []
    for i in range(0, len(video_ids), 50):
        batch = ",".join(video_ids[i:i + 50])
        data = get("videos", part="snippet,statistics,contentDetails", id=batch)
        for v in data.get("items", []):
            st = v.get("statistics", {})
            sn = v.get("snippet", {})
            videos.append({
                "id": v["id"],
                "title": sn.get("title", ""),
                "published_at": sn.get("publishedAt", ""),
                "duration": v.get("contentDetails", {}).get("duration", ""),
                "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)),
                "comments": int(st.get("commentCount", 0)),
            })
    videos.sort(key=lambda v: v["published_at"], reverse=True)
    return videos


def merge_content_metadata(videos: list[dict]) -> None:
    """Update content/videos.json, preserving existing 'topics' tags."""
    path = CONTENT / "videos.json"
    existing = {v["id"]: v for v in (read_json(path, default=[]) or [])}
    merged = []
    for v in videos:
        prev = existing.get(v["id"], {})
        merged.append({
            "id": v["id"],
            "title": v["title"],
            "published_at": v["published_at"],
            "duration": v["duration"],
            "topics": prev.get("topics", []),
        })
    write_json(path, merged)


def main() -> None:
    ensure_dirs()
    today = utc_today()

    channel = fetch_channel()
    video_ids = fetch_all_video_ids(channel.pop("uploads_playlist"))
    videos = fetch_videos(video_ids)

    # Board-facing snapshot
    write_json(LATEST / "youtube.json", {
        "fetched_at": utc_now_iso(),
        "channel": channel,
        "videos": videos,
    })

    # Channel daily history row
    upsert_daily_row(HISTORY / "youtube_daily.jsonl", {"date": today, **channel})

    # Per-video daily snapshots
    upsert_daily_rows(
        HISTORY / "videos" / "videos_daily.jsonl",
        [{"date": today, "id": v["id"], "views": v["views"],
          "likes": v["likes"], "comments": v["comments"]} for v in videos],
        key_fields=("date", "id"),
    )

    merge_content_metadata(videos)
    print(f"youtube_channel OK: {channel['subscribers']} subs, "
          f"{channel['views']} views, {len(videos)} videos")


if __name__ == "__main__":
    KEY = require_env("YT_API_KEY")
    main()
