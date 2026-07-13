"""YouTube Analytics API v2 collector (OAuth).

Collects, per UTC day for the trailing window:
- Audience: views, watch minutes, avg duration, avg percentage viewed,
  subscribers gained/lost, likes, comments, shares
- Revenue: estimated revenue, CPM, playback-based CPM, monetized playbacks
- Traffic mix per day (historized, so mix *shifts* are trendable)
- Subscribed vs non-subscribed viewing per day
- 30-day detail: top videos by views, top search terms, top suggested-by
  videos, top earning videos, revenue by ad type
- Launch curves (daily views since publish) for videos younger than
  CURVE_DAYS, keeping launch_curves.json current after the one-time backfill

Writes:
- data/latest/analytics.json
- data/latest/monetization.json
- data/history/analytics_daily.jsonl
- data/history/monetization_daily.jsonl
- data/history/traffic_daily.jsonl        (date + source composite key)
- data/history/subscribed_daily.jsonl
- data/history/search_terms_daily.jsonl   (date + term composite key)
- data/history/suggested_daily.jsonl      (date + video id composite key)
- data/history/videos/launch_curves.json  (young-video entries refreshed)

Revenue lag note: YouTube finalizes revenue 2-3 days behind. We re-fetch a
trailing window every run and UPSERT each day's row, so provisional numbers
converge to final automatically. Same for the tail of any launch curve.

Auth: refresh-token flow (YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN).
Optional: YT_API_KEY, used only to resolve titles of suggested-by videos.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import requests

from common import (
    HISTORY, LATEST, YT_CHANNEL_ID,
    ensure_dirs, read_json, require_env, upsert_daily_rows,
    utc_now_iso, write_json,
)

API = "https://youtubeanalytics.googleapis.com/v2/reports"
DATA_API = "https://www.googleapis.com/youtube/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
TIMEOUT = 30
WINDOW_DAYS = 35        # trailing fetch window; covers revenue lag
BOARD_DAYS = 30         # what "rolling 30 days" means on the boards
CURVE_DAYS = 40         # keep launch curves fresh for videos younger than this
RUN_RATE_DAYS = 7       # projection basis: recent complete days
REVENUE_LAG = 3         # days considered not-yet-final for projections
DETAIL_MAX = 10         # rows kept for search terms / suggested videos


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


def resolve_video_titles(video_ids: list[str]) -> dict:
    """Best-effort title lookup for suggested-by videos (other channels)."""
    key = os.environ.get("YT_API_KEY", "").strip()
    if not key or not video_ids:
        return {}
    try:
        r = requests.get(f"{DATA_API}/videos", params={
            "part": "snippet", "id": ",".join(video_ids[:50]), "key": key,
        }, timeout=TIMEOUT)
        r.raise_for_status()
        return {v["id"]: v["snippet"]["title"] for v in r.json().get("items", [])}
    except Exception as exc:
        print(f"WARN: title resolution skipped: {exc}", file=sys.stderr)
        return {}


def update_launch_curves(token: str) -> int:
    """Refresh launch_curves.json entries for recently published videos."""
    yt = read_json(LATEST / "youtube.json")
    if not yt:
        return 0
    path = HISTORY / "videos" / "launch_curves.json"
    store = read_json(path, default={"videos": {}}) or {"videos": {}}
    curves = store.get("videos", {})

    today = datetime.now(timezone.utc).date()
    updated = 0
    for v in yt.get("videos", []):
        pub = datetime.fromisoformat(
            v["published_at"].replace("Z", "+00:00")).date()
        age = (today - pub).days
        if age < 1 or age > CURVE_DAYS:
            continue
        resp = query(
            token,
            startDate=pub.isoformat(), endDate=today.isoformat(),
            metrics="views", dimensions="day",
            filters=f"video=={v['id']}", sort="day",
        )
        by_date = {r["day"]: int(r["views"]) for r in rows_as_dicts(resp)}
        curves[v["id"]] = {
            "published": pub.isoformat(),
            "daily_views": [
                by_date.get((pub + timedelta(days=i)).isoformat(), 0)
                for i in range(age)
            ],
        }
        updated += 1

    if updated:
        write_json(path, {"updated_at": utc_now_iso(), "videos": curves})
    return updated


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
                 "averageViewPercentage,subscribersGained,subscribersLost,"
                 "likes,comments,shares"),
        sort="day",
    ))
    audience_rows = [{
        "date": r["day"],
        "views": int(r.get("views", 0)),
        "watch_minutes": int(r.get("estimatedMinutesWatched", 0)),
        "avg_view_duration_sec": int(r.get("averageViewDuration", 0)),
        "avg_view_pct": round(float(r.get("averageViewPercentage", 0)), 1),
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

    # ---- Traffic mix per day (historized) ----
    traffic_day = rows_as_dicts(query(
        token,
        startDate=start, endDate=end,
        dimensions="day,insightTrafficSourceType",
        metrics="views", sort="day",
    ))
    upsert_daily_rows(
        HISTORY / "traffic_daily.jsonl",
        [{"date": r["day"], "source": r["insightTrafficSourceType"],
          "views": int(r["views"])} for r in traffic_day],
        key_fields=("date", "source"),
    )

    # ---- Subscribed vs non-subscribed viewing per day ----
    sub_split = rows_as_dicts(query(
        token,
        startDate=start, endDate=end,
        dimensions="day,subscribedStatus",
        metrics="views", sort="day",
    ))
    split_by_date = {}
    for r in sub_split:
        d = split_by_date.setdefault(r["day"], {"date": r["day"],
                                                "subscribed": 0, "not_subscribed": 0})
        if r["subscribedStatus"] == "SUBSCRIBED":
            d["subscribed"] = int(r["views"])
        else:
            d["not_subscribed"] = int(r["views"])
    upsert_daily_rows(HISTORY / "subscribed_daily.jsonl",
                      sorted(split_by_date.values(), key=lambda x: x["date"]))

    # ---- 30-day details ----
    traffic_30 = rows_as_dicts(query(
        token, startDate=board_start, endDate=end,
        dimensions="insightTrafficSourceType", metrics="views", sort="-views",
    ))

    top_videos = rows_as_dicts(query(
        token, startDate=board_start, endDate=end,
        dimensions="video", metrics="views,estimatedMinutesWatched,likes",
        sort="-views", maxResults=5,
    ))

    search_terms = rows_as_dicts(query(
        token, startDate=board_start, endDate=end,
        dimensions="insightTrafficSourceDetail",
        filters="insightTrafficSourceType==YT_SEARCH",
        metrics="views", sort="-views", maxResults=DETAIL_MAX,
    ))
    upsert_daily_rows(
        HISTORY / "search_terms_daily.jsonl",
        [{"date": end, "term": r["insightTrafficSourceDetail"],
          "views": int(r["views"])} for r in search_terms],
        key_fields=("date", "term"),
    )

    suggested = rows_as_dicts(query(
        token, startDate=board_start, endDate=end,
        dimensions="insightTrafficSourceDetail",
        filters="insightTrafficSourceType==RELATED_VIDEO",
        metrics="views", sort="-views", maxResults=DETAIL_MAX,
    ))
    sug_titles = resolve_video_titles(
        [r["insightTrafficSourceDetail"] for r in suggested])
    upsert_daily_rows(
        HISTORY / "suggested_daily.jsonl",
        [{"date": end, "video_id": r["insightTrafficSourceDetail"],
          "views": int(r["views"])} for r in suggested],
        key_fields=("date", "video_id"),
    )

    top_earning = rows_as_dicts(query(
        token, startDate=board_start, endDate=end,
        dimensions="video", metrics="estimatedRevenue,views",
        sort="-estimatedRevenue", maxResults=5,
    ))

    ad_types = rows_as_dicts(query(
        token, startDate=board_start, endDate=end,
        dimensions="adType", metrics="grossRevenue", sort="-grossRevenue",
    ))

    # ---- Launch curves for young videos ----
    curve_count = update_launch_curves(token)

    # ---- Board-facing summaries ----
    a30 = [r for r in audience_rows if r["date"] >= board_start]
    r30 = [r for r in revenue_rows if r["date"] >= board_start]
    views_30 = sum(r["views"] for r in a30)
    revenue_30 = round(sum(r["revenue"] for r in r30), 2)

    # Views-weighted average percentage viewed
    wsum = sum(r["avg_view_pct"] * r["views"] for r in a30)
    avg_view_pct = round(wsum / views_30, 1) if views_30 else 0

    sub30 = [r for r in sorted(split_by_date.values(), key=lambda x: x["date"])
             if r["date"] >= board_start]

    write_json(LATEST / "analytics.json", {
        "fetched_at": utc_now_iso(),
        "window_days": BOARD_DAYS,
        "totals": {
            "views": views_30,
            "watch_hours": round(sum(r["watch_minutes"] for r in a30) / 60, 1),
            "avg_view_pct": avg_view_pct,
            "subs_gained": sum(r["subs_gained"] for r in a30),
            "subs_lost": sum(r["subs_lost"] for r in a30),
            "subs_net": sum(r["subs_gained"] - r["subs_lost"] for r in a30),
            "likes": sum(r["likes"] for r in a30),
            "comments": sum(r["comments"] for r in a30),
            "shares": sum(r["shares"] for r in a30),
            "subscribed_views": sum(r["subscribed"] for r in sub30),
            "not_subscribed_views": sum(r["not_subscribed"] for r in sub30),
        },
        "daily": a30,
        "traffic_sources": [
            {"source": t["insightTrafficSourceType"], "views": int(t["views"])}
            for t in traffic_30
        ],
        "top_videos": [
            {"video_id": t["video"], "views": int(t["views"]),
             "watch_hours": round(int(t["estimatedMinutesWatched"]) / 60, 1),
             "likes": int(t["likes"])}
            for t in top_videos
        ],
        "search_terms": [
            {"term": r["insightTrafficSourceDetail"], "views": int(r["views"])}
            for r in search_terms
        ],
        "suggested_by": [
            {"video_id": r["insightTrafficSourceDetail"],
             "title": sug_titles.get(r["insightTrafficSourceDetail"]),
             "views": int(r["views"])}
            for r in suggested
        ],
    })

    # Run-rate projection from recent complete (finalized) days
    final_rows = [r for r in revenue_rows
                  if r["date"] <= (today - timedelta(days=REVENUE_LAG)).isoformat()]
    basis = final_rows[-RUN_RATE_DAYS:]
    run_rate = (sum(r["revenue"] for r in basis) / len(basis)) if basis else 0
    best = max(r30, key=lambda r: r["revenue"], default=None)

    write_json(LATEST / "monetization.json", {
        "fetched_at": utc_now_iso(),
        "window_days": BOARD_DAYS,
        "totals": {
            "revenue": revenue_30,
            "monetized_plays": sum(r["monetized_plays"] for r in r30),
            "rpm": round(revenue_30 / views_30 * 1000, 2) if views_30 else 0,
            "daily_avg": round(revenue_30 / BOARD_DAYS, 2),
            "projected_monthly": round(run_rate * 30.44, 2),
            "projection_basis_days": len(basis),
        },
        "best_day": best,
        "daily": r30,
        "ad_types": [
            {"type": a["adType"],
             "gross_revenue": round(float(a["grossRevenue"]), 2)}
            for a in ad_types
        ],
        "top_earning_videos": [
            {"video_id": t["video"],
             "revenue": round(float(t["estimatedRevenue"]), 2),
             "views": int(t["views"])}
            for t in top_earning
        ],
    })

    print(f"youtube_analytics OK: {len(audience_rows)} audience rows, "
          f"{len(revenue_rows)} revenue rows, {len(traffic_day)} traffic rows, "
          f"{len(search_terms)} search terms, {len(suggested)} suggested, "
          f"{curve_count} launch curves updated")


if __name__ == "__main__":
    main()
