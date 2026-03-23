#!/usr/bin/env python3
"""
ingest.py — Parse a FortiGate SD-WAN email and append the event to the data store.

Usage:
    cat email.html | python scripts/ingest.py
    python scripts/ingest.py < email.html

The script:
  1. Reads HTML from stdin
  2. Extracts the FortiGate log line
  3. Appends event to the current data file (events-00N.json)
  4. Rotates to a new file if size > MAX_FILE_BYTES
  5. Updates data/index.json
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
INDEX_FILE = DATA_DIR / "index.json"
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB


def parse_email(html: str) -> dict:
    """Extract event fields from the FortiGate HTML email body."""
    pat = (
        r'date=(\S+)\s+time=(\S+)\s+devid="\S+"\s+devname="\S+"\s+'
        r'eventtime=(\d+)\s+tz="([^"]+)".*?'
        r'interface="([^"]+)".*?oldvalue="([^"]+)".*?newvalue="([^"]+)"'
    )
    m = re.search(pat, html, re.DOTALL)
    if not m:
        raise ValueError("Could not parse FortiGate log line from email HTML")

    date, time_, eid, tz, iface, from_state, to_state = m.groups()

    # Build ISO 8601 timestamp: normalize +0100 → +01:00
    ts = f"{date}T{time_}{tz}"
    ts = re.sub(r'([+-])(\d{2})(\d{2})$', r'\1\2:\3', ts)

    return {
        "ts": ts,
        "iface": iface,
        "from": from_state,
        "to": to_state,
        "eid": eid,
    }


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))


def next_filename(current: str) -> str:
    """events-001.json → events-002.json"""
    m = re.match(r"(events-)(\d+)(\.json)$", current)
    if not m:
        raise ValueError(f"Unexpected filename format: {current}")
    return f"{m.group(1)}{int(m.group(2)) + 1:03d}{m.group(3)}"


def rotate(index: dict) -> tuple[dict, Path]:
    """Create a new data file, update and save the index. Returns updated index and new path."""
    new_name = next_filename(index["current"])
    new_path = DATA_DIR / new_name
    file_num = int(re.search(r"\d+", new_name).group())
    save_json(new_path, {
        "meta": {
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "version": 1,
            "file_index": file_num,
        },
        "events": [],
    })
    index["files"].append(new_name)
    index["current"] = new_name
    save_json(INDEX_FILE, index)
    print(f"[ingest] Rotated data file → {new_name}", file=sys.stderr)
    return index, new_path


def main():
    html = sys.stdin.read()
    if not html.strip():
        print("[ingest] No input received on stdin", file=sys.stderr)
        sys.exit(1)

    event = parse_email(html)

    index = load_json(INDEX_FILE)
    data_path = DATA_DIR / index["current"]
    data = load_json(data_path)

    # Deduplicate by eventtime id
    if any(e["eid"] == event["eid"] for e in data["events"]):
        print(f"[ingest] Duplicate event eid={event['eid']}, skipping", file=sys.stderr)
        return

    data["events"].append(event)
    save_json(data_path, data)

    print(f"[ingest] Appended: {event['ts']}  {event['iface']}  {event['from']} → {event['to']}", file=sys.stderr)

    # Rotate if file exceeds size limit
    if data_path.stat().st_size > MAX_FILE_BYTES:
        rotate(index)


if __name__ == "__main__":
    main()
