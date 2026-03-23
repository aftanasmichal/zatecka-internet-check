#!/usr/bin/env python3
"""
poll.py — Fetch FortiGate SD-WAN emails from Gmail and ingest new events.

Reads credentials from environment variables:
  GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN

Exit codes:
  0 — new events were ingested (caller should commit & deploy)
  1 — no new events (nothing changed)
"""

import base64
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# Import shared logic from ingest.py
sys.path.insert(0, str(Path(__file__).parent))
from ingest import parse_email, load_json, save_json, rotate, INDEX_FILE, DATA_DIR, MAX_FILE_BYTES


def get_access_token(client_id, client_secret, refresh_token):
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["access_token"]


def gmail_get(path, token):
    req = urllib.request.Request(
        f"https://gmail.googleapis.com/gmail/v1{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def extract_html_body(msg):
    payload = msg.get("payload", {})
    # Single-part message
    data = payload.get("body", {}).get("data", "")
    if data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    # Multipart — find text/html part
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/html":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    return ""


def main():
    client_id     = os.environ["GMAIL_CLIENT_ID"]
    client_secret = os.environ["GMAIL_CLIENT_SECRET"]
    refresh_token = os.environ["GMAIL_REFRESH_TOKEN"]

    token = get_access_token(client_id, client_secret, refresh_token)

    # Fetch up to 100 FortiGate emails from the last 8 days
    # 8 days (not 7) gives a safe overlap across timezone/clock drift
    result = gmail_get(
        "/users/me/messages?q=from:fgt%40palefire.com+newer_than:8d&maxResults=100",
        token,
    )
    messages = result.get("messages", [])
    if not messages:
        print("[poll] No FortiGate emails found in last 8 days", file=sys.stderr)
        sys.exit(1)

    print(f"[poll] Found {len(messages)} emails to check", file=sys.stderr)

    index     = load_json(INDEX_FILE)
    data_path = DATA_DIR / index["current"]
    data      = load_json(data_path)
    seen_eids = {e["eid"] for e in data["events"]}

    new_count = 0
    for msg_ref in messages:
        msg  = gmail_get(f"/users/me/messages/{msg_ref['id']}?format=full", token)
        body = extract_html_body(msg)
        if not body:
            continue

        try:
            event = parse_email(body)
        except ValueError:
            continue  # not a parseable FortiGate event

        if event["eid"] in seen_eids:
            continue  # already stored

        data["events"].append(event)
        seen_eids.add(event["eid"])
        new_count += 1
        print(f"[poll] +event: {event['ts']}  {event['iface']}  {event['from']}→{event['to']}", file=sys.stderr)

    if new_count == 0:
        print("[poll] No new events", file=sys.stderr)
        sys.exit(1)

    # Sort chronologically before saving
    data["events"].sort(key=lambda e: e["ts"])
    save_json(data_path, data)

    # Rotate file if it exceeds size limit
    if data_path.stat().st_size > MAX_FILE_BYTES:
        rotate(index)

    print(f"[poll] Done — {new_count} new event(s) ingested", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
