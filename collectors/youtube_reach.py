"""YouTube Reporting API collector: thumbnail impressions and click-through rate.

These two numbers are not in the YouTube Analytics API (the one youtube_analytics.py
uses); they exist only as bulk daily reports from the Reporting API, report type
`channel_reach_basic_a1` (dimensions date, channel_id, video_id; metrics
video_thumbnail_impressions, video_thumbnail_impressions_ctr).

How the Reporting API works, and why this collector is shaped the way it is:
- A reporting *job* is created once. YouTube then generates one CSV per day,
  usually within 48 hours, plus a one-time backfill of the 30 days before the
  job was created. Nothing older than that can ever be fetched.
- Report files can only be downloaded for 30 to 60 days, so every run fetches
  whatever has not been ingested yet. Missing a few days is harmless; missing
  a month loses data for good.
- YouTube can re-issue a day (a backfill report with a new report id). Reports
  are applied oldest-created first and rows are upserted by (date, video_id),
  so the newest revision of a day wins.

First run creates the job and exits 0 ("no reports yet"). This step runs with
continue-on-error in collect.yml: it is additive and must never block the core
collectors. On any error it exits non-zero and writes nothing.

Writes:
- data/history/videos/reach_daily.jsonl  (date + video_id composite key)
      {date, video_id, impressions, ctr}   ctr as reported (a fraction, 0.078 = 7.8%)
- data/history/videos/reach_reports.json (job id + ingested report ids; bookkeeping)

Auth: refresh-token flow (YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN),
scope yt-analytics.readonly (reach reports are non-monetary).
"""

import csv
import io
import sys
from datetime import datetime, timedelta, timezone

import requests

from common import HISTORY, ensure_dirs, read_json, upsert_daily_rows, utc_now_iso, write_json
from youtube_analytics import get_access_token

API = "https://youtubereporting.googleapis.com/v1"
REPORT_TYPE = "channel_reach_basic_a1"
JOB_NAME = "everyday-ham-reach"
TIMEOUT = 60
OUT = HISTORY / "videos" / "reach_daily.jsonl"
STATE = HISTORY / "videos" / "reach_reports.json"
SEEN_KEEP_DAYS = 90     # reports vanish after 60 days; keep ids a little longer


def api(token: str, method: str, path: str, **kw) -> dict:
    r = requests.request(method, f"{API}/{path}", headers={"Authorization": f"Bearer {token}"},
                         timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r.json() if r.content else {}


def find_or_create_job(token: str) -> tuple[str, bool]:
    jobs, page = [], None
    while True:
        resp = api(token, "GET", "jobs", params={"pageToken": page} if page else None)
        jobs += resp.get("jobs", [])
        page = resp.get("nextPageToken")
        if not page:
            break
    for j in jobs:
        if j.get("reportTypeId") == REPORT_TYPE:
            return j["id"], False
    job = api(token, "POST", "jobs", json={"reportTypeId": REPORT_TYPE, "name": JOB_NAME})
    return job["id"], True


def list_reports(token: str, job_id: str) -> list[dict]:
    reports, page = [], None
    while True:
        params = {"pageToken": page} if page else None
        resp = api(token, "GET", f"jobs/{job_id}/reports", params=params)
        reports += resp.get("reports", [])
        page = resp.get("nextPageToken")
        if not page:
            return reports


def parse_report(text: str) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        d = r["date"]
        rows.append({
            "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d,
            "video_id": r["video_id"],
            "impressions": int(float(r["video_thumbnail_impressions"] or 0)),
            "ctr": round(float(r["video_thumbnail_impressions_ctr"] or 0), 6),
        })
    return rows


def main() -> None:
    ensure_dirs()
    token = get_access_token()
    state = read_json(STATE, {}) or {}
    job_id, created = find_or_create_job(token)
    seen = state.get("ingested", {}) if state.get("job_id") == job_id else {}

    new_reports = sorted((r for r in list_reports(token, job_id) if r["id"] not in seen),
                         key=lambda r: r.get("createTime", ""))
    rows_by_key: dict = {}
    for rep in new_reports:
        resp = requests.get(rep["downloadUrl"], headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
        resp.raise_for_status()
        for row in parse_report(resp.text):
            rows_by_key[(row["date"], row["video_id"])] = row   # later-created revision wins
        seen[rep["id"]] = rep.get("createTime", "")

    # Only now touch the data: everything above succeeded.
    if rows_by_key:
        upsert_daily_rows(OUT, list(rows_by_key.values()), key_fields=("date", "video_id"))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SEEN_KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    write_json(STATE, {"job_id": job_id, "report_type": REPORT_TYPE, "updated_at": utc_now_iso(),
                       "ingested": seen})

    dates = sorted({k[0] for k in rows_by_key})
    print(f"youtube_reach OK: job {'created' if created else 'found'}, {len(new_reports)} new reports, "
          f"{len(rows_by_key)} rows" + (f" ({dates[0]}..{dates[-1]})" if dates else "")
          + (" (first reports usually appear within 48 hours)" if created else ""))


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as exc:
        # Status code only: response bodies and URLs can carry tokens.
        print(f"ERROR: youtube_reach failed: HTTP {exc.response.status_code if exc.response is not None else '?'}",
              file=sys.stderr)
        sys.exit(1)
