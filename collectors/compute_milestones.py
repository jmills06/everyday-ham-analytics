"""Server-side milestone detection.

Replaces the old localStorage-based logic on the milestone board. Compares
today's values against the most recent PRIOR day in history and records any
thresholds crossed into data/milestones.json with a UTC timestamp.

Boards read milestones.json and show a celebration takeover for any event
newer than DISPLAY_HOURS. State lives here, not in the DakBoard browser, so
every screen agrees and cache clears change nothing.

Run AFTER the other collectors (it reads their history files).
"""

import sys

from common import DATA, HISTORY, read_json, read_jsonl, utc_now_iso, utc_today, write_json

MILESTONES = [
    500, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 7500,
    10000, 15000, 20000, 25000, 30000, 40000, 50000,
    75000, 100000, 150000, 200000, 250000, 500000, 1000000,
]

TRACKED = [
    # (history file, field, human label)
    ("youtube_daily.jsonl", "subscribers", "Subscribers"),
    ("youtube_daily.jsonl", "views", "Channel Views"),
    ("buzzsprout_daily.jsonl", "total_downloads", "All-Time Downloads"),
]

DISPLAY_HOURS = 36          # boards show events newer than this
RETENTION_EVENTS = 50       # keep a rolling log of past celebrations

# A metric can be restated overnight rather than earned: YouTube realigned
# view counting on 2026-08-24 (see VIEW_METHODOLOGY_CHANGE), and a restated
# lifetime total can clear several thresholds at once, putting a 36-hour
# celebration on every screen for a milestone nobody reached. A gain has to
# fail BOTH tests to count as a restatement - a genuinely viral day can beat
# the trailing average many times over, but it is never a large slice of a
# lifetime total.
JUMP_FACTOR = 5             # times the trailing average daily gain
JUMP_SHARE = 0.10           # and this share of the metric's own size
JUMP_BASIS_DAYS = 14        # trailing days averaged


def crossed(old: int, new: int) -> list[int]:
    return [m for m in MILESTONES if old < m <= new]


def looks_restated(prior: list[dict], field: str, old: int, new: int) -> bool:
    """True if a one-day gain looks like a definition change, not growth."""
    delta = new - old
    if delta <= 0 or old <= 0:
        return False
    rows = [r for r in prior if r.get(field) is not None][-(JUMP_BASIS_DAYS + 1):]
    if len(rows) < 3:
        return False                  # too little history to judge
    gains = [int(rows[i][field]) - int(rows[i - 1][field])
             for i in range(1, len(rows))]
    avg = sum(gains) / len(gains)
    return avg > 0 and delta > JUMP_FACTOR * avg and delta > JUMP_SHARE * old


def main() -> None:
    today = utc_today()
    out_path = DATA / "milestones.json"
    state = read_json(out_path, default={"events": []}) or {"events": []}
    events = state.get("events", [])
    already = {(e["metric"], e["value"]) for e in events}

    new_events = []
    for filename, field, label in TRACKED:
        rows = read_jsonl(HISTORY / filename)
        today_row = next((r for r in rows if r.get("date") == today), None)
        prior = [r for r in rows if r.get("date", "") < today]
        if not today_row or not prior:
            continue                      # need two days of history to compare
        old_val = int(prior[-1].get(field, 0))
        new_val = int(today_row.get(field, 0))
        restated = looks_restated(prior, field, old_val, new_val)
        for m in crossed(old_val, new_val):
            if (label, m) in already:
                continue
            if restated:
                # Suppressed for good: tomorrow's comparison starts above the
                # threshold, so it is never re-detected.
                print(f"WARN: {label} jumped {old_val:,} -> {new_val:,} in one "
                      f"day; skipping the {m:,} milestone as a counting change",
                      file=sys.stderr)
                continue
            new_events.append({
                "metric": label,
                "value": m,
                "reached_at": utc_now_iso(),
                "actual_value": new_val,
            })

    if new_events:
        events.extend(new_events)
        for e in new_events:
            print(f"MILESTONE: {e['value']:,} {e['metric']}")
    else:
        print("compute_milestones OK: no new milestones")

    events = events[-RETENTION_EVENTS:]
    write_json(out_path, {
        "updated_at": utc_now_iso(),
        "display_hours": DISPLAY_HOURS,
        "events": events,
    })


if __name__ == "__main__":
    main()
