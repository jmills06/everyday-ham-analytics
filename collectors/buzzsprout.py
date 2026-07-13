"""Buzzsprout collector.

Buzzsprout's API only exposes lifetime totals per episode, not daily
downloads. Snapshotting per-episode totals every day lets us compute daily
downloads ourselves as deltas later, which is history that cannot be
reconstructed retroactively. This file is the reason the repo exists.

Writes:
- data/latest/buzzsprout.json           (board-facing snapshot)
- data/history/buzzsprout_daily.jsonl   (show total per UTC day)
- data/history/episodes_daily.jsonl     (per-episode total per UTC day)
- data/content/episodes.json            (metadata + topics, merged)

Auth: BUZZSPROUT_TOKEN + BUZZSPROUT_PODCAST_ID.
"""

import requests

from common import (
    CONTENT, HISTORY, LATEST,
    ensure_dirs, read_json, require_env, upsert_daily_row,
    upsert_daily_rows, utc_now_iso, utc_today, write_json,
)

TIMEOUT = 30


def fetch_episodes(token: str, podcast_id: str) -> list[dict]:
    url = f"https://www.buzzsprout.com/api/{podcast_id}/episodes.json"
    headers = {
        "Authorization": f"Token token={token}",
        "User-Agent": "everyday-ham-analytics (jmills06@gmail.com)",
    }
    episodes, page = [], 1
    while True:
        r = requests.get(url, headers=headers,
                         params={"page": page, "per_page": 100}, timeout=TIMEOUT)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            return episodes
        episodes += batch
        if len(batch) < 100:
            return episodes
        page += 1


def merge_content_metadata(episodes: list[dict]) -> None:
    path = CONTENT / "episodes.json"
    existing = {e["id"]: e for e in (read_json(path, default=[]) or [])}
    merged = []
    for e in episodes:
        prev = existing.get(e["id"], {})
        merged.append({
            "id": e["id"],
            "title": e.get("title", ""),
            "episode_number": e.get("episode_number"),
            "published_at": e.get("published_at", ""),
            "duration_sec": e.get("duration"),
            "topics": prev.get("topics", []),
        })
    write_json(path, merged)


def main() -> None:
    ensure_dirs()
    token = require_env("BUZZSPROUT_TOKEN")
    podcast_id = require_env("BUZZSPROUT_PODCAST_ID")
    today = utc_today()

    raw = fetch_episodes(token, podcast_id)
    # Published, non-private episodes only for stats
    episodes = [e for e in raw if not e.get("private") and e.get("published_at")]
    episodes.sort(key=lambda e: e.get("published_at", ""), reverse=True)

    total = sum(int(e.get("total_plays", 0)) for e in episodes)

    write_json(LATEST / "buzzsprout.json", {
        "fetched_at": utc_now_iso(),
        "total_downloads": total,
        "episode_count": len(episodes),
        "episodes": [{
            "id": e["id"],
            "title": e.get("title", ""),
            "episode_number": e.get("episode_number"),
            "published_at": e.get("published_at", ""),
            "plays": int(e.get("total_plays", 0)),
        } for e in episodes],
    })

    upsert_daily_row(HISTORY / "buzzsprout_daily.jsonl", {
        "date": today,
        "total_downloads": total,
        "episode_count": len(episodes),
    })

    upsert_daily_rows(
        HISTORY / "episodes_daily.jsonl",
        [{"date": today, "id": e["id"], "plays": int(e.get("total_plays", 0))}
         for e in episodes],
        key_fields=("date", "id"),
    )

    merge_content_metadata(episodes)
    print(f"buzzsprout OK: {total} lifetime downloads across {len(episodes)} episodes")


if __name__ == "__main__":
    main()
