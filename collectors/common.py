"""Shared helpers for all Everyday Ham collectors.

Conventions:
- All timestamps are UTC. Date keys are YYYY-MM-DD strings (UTC).
- History files are JSONL: one JSON object per line, keyed by "date".
- Appending a row for a date that already exists REPLACES that row
  (so re-running a collector on the same day never duplicates).
- On any fetch failure, collectors exit non-zero WITHOUT touching files,
  preserving last-known-good data (stale data beats no data).
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LATEST = DATA / "latest"
HISTORY = DATA / "history"
CONTENT = DATA / "content"

# ---- Everyday Ham constants (not secrets) ----
YT_CHANNEL_ID = "UCK3ct4iOm2HqnOiv8sgMHxA"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        print(f"ERROR: missing required environment variable {name}", file=sys.stderr)
        sys.exit(1)
    return val


def ensure_dirs() -> None:
    for d in (LATEST, HISTORY, HISTORY / "videos", CONTENT):
        d.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj) -> None:
    """Atomic-ish JSON write: write temp file then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def upsert_daily_row(path: Path, row: dict, key_fields=("date",)) -> None:
    """Insert row into a JSONL history file, replacing any existing row
    with the same key fields (default: same date). Keeps file sorted by date."""
    rows = read_jsonl(path)
    key = tuple(row.get(k) for k in key_fields)
    rows = [r for r in rows if tuple(r.get(k) for k in key_fields) != key]
    rows.append(row)
    rows.sort(key=lambda r: tuple(str(r.get(k, "")) for k in key_fields))
    write_jsonl(path, rows)


def upsert_daily_rows(path: Path, new_rows: list, key_fields=("date",)) -> None:
    """Bulk version of upsert_daily_row: one read/write for many rows."""
    rows = read_jsonl(path)
    new_keys = {tuple(r.get(k) for k in key_fields) for r in new_rows}
    rows = [r for r in rows if tuple(r.get(k) for k in key_fields) not in new_keys]
    rows.extend(new_rows)
    rows.sort(key=lambda r: tuple(str(r.get(k, "")) for k in key_fields))
    write_jsonl(path, rows)


def previous_row(path: Path, before_date: str) -> dict | None:
    """Most recent row strictly before the given date. Used for deltas/milestones."""
    rows = [r for r in read_jsonl(path) if r.get("date", "") < before_date]
    return rows[-1] if rows else None
