#!/bin/bash
# Restore an Axella backup (setup/backup.py) into this Axella folder – on a new Mac mini or the same one.
#   tools/restore.sh <file.axbak>           dry run: what's in it and what would be replaced (nothing changes)
#   tools/restore.sh <file.axbak> --apply   restore: asks for the passphrase and "yes"; the current data is moved
#                                           aside to pre-restore-<time>/, never deleted
# Stop the Axella service first (the script tells you how if it's running from this folder).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
F="${1:-}"
MODE="${2:-}"
if [ -z "$F" ] || [ ! -f "$F" ]; then
  echo "usage: tools/restore.sh <file.axbak> [--apply]"
  exit 2
fi
PY=/usr/bin/python3; [ -x "$PY" ] || PY=python3
if [ "$MODE" = "--apply" ] && pgrep -f "$PWD/setup/axella-actions.py" >/dev/null 2>&1; then
  echo "✗ The Axella service is running from this folder – stop it first, then run this again:"
  launchctl list 2>/dev/null | awk '/axella/ && /action/ {print $3}' | while read -r L; do
    echo "   launchctl bootout gui/$(id -u)/$L"
  done
  echo "   (a system daemon: sudo launchctl bootout system/<its label>)"
  exit 3
fi
"$PY" setup/backup.py restore "$F" $MODE
rc=$?
if [ "$MODE" = "--apply" ] && [ $rc -eq 0 ]; then
  echo "Start Axella again as docs/SETUP.md describes (launchctl bootstrap …), then open Settings → System status."
fi
exit $rc
