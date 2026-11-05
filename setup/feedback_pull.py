#!/usr/bin/env python3
"""Pull new axella.dev feedback into the Axella service on the Mac mini.

Outbound only: the Mac mini calls https://axella.dev/api/feedback/export with a read-only
token. Nothing on the Mac mini is exposed. Python 3.9, standard library only.

  token   macOS Keychain, generic password, service "axella-feedback-export"
          (security add-generic-password -a axella -s axella-feedback-export -w)
  cursor  state/feedback-pull.json          last entry seq seen (D1)
  output  feedback/inbox/YYYY-MM.jsonl      one JSON entry per line, appended

Run from the repo root:  python3 setup/feedback_pull.py
Exit codes: 0 ok (prints how many new), 1 config/token problem, 2 network/HTTP problem.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EXPORT_URL = os.environ.get("AXELLA_FEEDBACK_URL", "https://axella.dev/api/feedback/export")
STATE = os.path.join(ROOT, "state", "feedback-pull.json")
INBOX = os.path.join(ROOT, "feedback", "inbox")
KEYCHAIN_SERVICE = "axella-feedback-export"


def token():
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def load_cursor():
    try:
        with open(STATE) as f:
            return int(json.load(f).get("cursor", 0) or 0)
    except (OSError, ValueError, TypeError):
        return 0


def save_state(cursor, new):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"cursor": cursor, "last_run": datetime.now(timezone.utc).isoformat(), "last_new": new}, f, indent=2)
    os.replace(tmp, STATE)


def fetch(since, tok):
    url = EXPORT_URL + "?" + urllib.parse.urlencode({"since": since})
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok, "User-Agent": "axella-feedback-pull"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)


def main():
    tok = token()
    if not tok:
        print("No export token in Keychain (service %s)." % KEYCHAIN_SERVICE, file=sys.stderr)
        return 1
    cursor = load_cursor()
    total = 0
    try:
        while True:
            data = fetch(cursor, tok)
            entries = data.get("entries", [])
            if not entries:
                break
            os.makedirs(INBOX, exist_ok=True)
            for e in entries:
                month = (e.get("receivedAt") or "")[:7] or "unknown"
                with open(os.path.join(INBOX, month + ".jsonl"), "a") as f:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            total += len(entries)
            cursor = data.get("cursor", cursor)
            save_state(cursor, total)  # save per page, so a failure never re-imports
            if len(entries) < 500:
                break
    except urllib.error.HTTPError as err:
        print("Export failed: HTTP %s" % err.code, file=sys.stderr)
        return 2
    except (urllib.error.URLError, TimeoutError, ValueError) as err:
        print("Export failed: %s" % err, file=sys.stderr)
        return 2
    save_state(cursor, total)
    print("%d new" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
