"""YouTube Analytics API v2 collector (OAuth).

Collects, per UTC day for the trailing window:
- Audience: views, watch minutes, average view duration,
  subscribers gained/lost, likes, comments, shares
- Revenue: estimated revenue, CPM, playback-based CPM, monetized playbacks
- 30-day traffic source breakdown
- 30-day top earning videos

Writes:
- data/latest/analytics.json          (board-facing 30-day summary)
- data/latest/monetization.json       (board-facing revenue summary)
- data/history/analytics_daily.jsonl  (upserted; converges as YT finalizes)
- data/history/monetization_daily.jsonl

Revenue lag note: YouTube finalizes revenue 2-3 days behind. We re-fetch a
trailing window every run and UPSERT each day's row, so early provisional
numbers get replaced by final ones automatically.

Auth: refresh-token flow. Needs YT_CLIENT_ID, YT_CLIENT_SECRET,
YT_REFRESH_TOKEN. Access token is minted fresh each run (auto-refresh).
"""

import sys
from datetime import datetime, timedelta, timezone

import requests

from common import (
    HISTORY, LATEST, YT_CHANNEL_ID,
    ensure_dirs, require_env, upsert_daily_rows, utc_now_iso, write_json,
)

API = "https://youtubeanalytics.googleapis.com/v2/reports"
TOKEN_URL = "https://oauth2.googleapis.com/token"
TIMEOUT = 30
WINDOW_DAYS = 35        # trailing fetch window; wide enough to cover revenue lag
BOARD_DAYS = 30         # what "rolling 30 days" means on the boards


def get_access_token() -> str:
    r = requests.post(TOKEN_URL, data={
        "client_id": require_env("YT_CLIENT_ID"),
        "client_secret": require_env("YT_CLIENT_SECRET"),
        "refresh_token": require_env("YT_REFRESH_TOKEN"),
        "grant_type": "refresh_token",
    }, timeout=TIMEOUT)
    if r.status_code != 200:
        print(f"ERROR: token refresh failed: {r.status_code} {r.text}", file=sys.stderr)
        sys.exit(1)
    return r.json()["access_token"]


def query(token: str, **params) -> dict:
    params.setdefault("ids", f"channel=={YT_CHANNEL_ID}")
    r = requests.get(API, params=params,
                     headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def rows_as_dicts(resp: dict) -> list[dict]:
    headers = [h["name"] for h in resp.get("columnHeaders", [])]
    return [dict(zip(headers, row)) for row in resp.get("rows", []) or []]


def main() -> None:
    ensure_dirs()
    token = get_access_token()

    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    end = today.isoformat()
    board_start = (today - timedelta(days=BOARD_DAYS)).isoformat()

    # ---- Daily audience metrics ----
    audience = rows_as_dicts(query(
        token,
        startDate=start, endDate=end, dimensions="day",
        metrics=("views,estimatedMinutesWatched,averageViewDuration,"
                 "subscribersGained,subscribersLost,likes,comments,shares"),
        sort="day",
    ))
    audience_rows = [{
        "date": r["day"],
        "views": int(r.get("views", 0)),
        "watch_minutes": int(r.get("estimatedMinutesWatched", 0)),
        "avg_view_duration_sec": int(r.get("averageViewDuration", 0)),
        "subs_gained": int(r.get("subscribersGained", 0)),
        "subs_lost": int(r.get("subscribersLost", 0)),
        "likes": int(r.get("likes", 0)),
        "comments": int(r.get("comments", 0)),
        "shares": int(r.get("shares", 0)),
    } for r in audience]
    upsert_daily_rows(HISTORY / "analytics_daily.jsonl", audience_rows)

    # ---- Daily revenue metrics ----
    revenue = rows_as_dicts(query(
        token,
        startDate=start, endDate=end, dimensions="day",
        metrics="estimatedRevenue,cpm,playbackBasedCpm,monetizedPlaybacks",
        sort="day",
    ))
    revenue_rows = [{
        "date": r["day"],
        "revenue": round(float(r.get("estimatedRevenue", 0)), 2),
        "cpm": round(float(r.get("cpm", 0)), 2),
        "playback_cpm": round(float(r.get("playbackBasedCpm", 0)), 2),
        "monetized_plays": int(r.get("monetizedPlaybacks", 0)),
    } for r in revenue]
    upsert_daily_rows(HISTORY / "monetization_daily.jsonl", revenue_rows)

    # ---- 30-day traffic sources ----
    traffic = rows_as_dicts(query(
        token,
        startDate=board_start, endDate=end,
        dimensions="insightTrafficSourceType",
        metrics="views", sort="-views",
    ))

    # ---- 30-day top earning videos ----
    top_earning = rows_as_dicts(query(
        token,
        startDate=board_start, endDate=end,
        dimensions="video", metrics="estimatedRevenue,views",
        sort="-estimatedRevenue", maxResults=5,
    ))

    # ---- Board-facing summaries (last 30 complete-ish days) ----
    a30 = [r for r in audience_rows if r["date"] >= board_start]
    r30 = [r for r in revenue_rows if r["date"] >= board_start]

    write_json(LATEST / "analytics.json", {
        "fetched_at": utc_now_iso(),
        "window_days": BOARD_DAYS,
        "totals": {
            "views": sum(r["views"] for r in a30),
            "watch_hours": round(sum(r["watch_minutes"] for r in a30) / 60, 1),
            "subs_gained": sum(r["subs_gained"] for r in a30),
            "subs_lost": sum(r["subs_lost"] for r in a30),
            "subs_net": sum(r["subs_gained"] - r["subs_lost"] for r in a30),
            "likes": sum(r["likes"] for r in a30),
            "comments": sum(r["comments"] for r in a30),
            "shares": sum(r["shares"] for r in a30),
        },
        "daily": a30,
        "traffic_sources": [
            {"source": t["insightTrafficSourceType"], "views": int(t["views"])}
            for t in traffic
        ],
    })

    write_json(LATEST / "monetization.json", {
        "fetched_at": utc_now_iso(),
        "window_days": BOARD_DAYS,
        "totals": {
            "revenue": round(sum(r["revenue"] for r in r30), 2),
            "monetized_plays": sum(r["monetized_plays"] for r in r30),
        },
        "daily": r30,
        "top_earning_videos": [
            {"video_id": t["video"],
             "revenue": round(float(t["estimatedRevenue"]), 2),
             "views": int(t["views"])}
            for t in top_earning
        ],
    })

    print(f"youtube_analytics OK: {len(audience_rows)} audience rows, "
          f"{len(revenue_rows)} revenue rows upserted")


if __name__ == "__main__":
    main()
