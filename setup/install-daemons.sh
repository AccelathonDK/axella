#!/bin/bash
# Installs the web server and the watchdog as LaunchDaemons that run as you (see docs/SETUP.md, section 6,
# "Keep it running when other users log in"). Safe to run again. Needs your password once (sudo).
# The old web LaunchAgent is moved to ~/Library/LaunchAgents-disabled/, never deleted.
set -euo pipefail
# run as yourself – sudo is asked for below. Run with sudo, the daemons would run as root on scripts in your own,
# user-writable folder (a privilege escalation for anything running as you).
if [ "$(id -u)" -eq 0 ]; then echo "Run this without sudo, as yourself – it asks for your password when it needs it."; exit 1; fi
AX="$(cd "$(dirname "$0")/.." && pwd)"
WWW="$(cd "$AX/../www" && pwd)"
LOG="$HOME/Library/Logs/axella"
ME="$(id -un)"
case "$ME" in root|"") echo "Refusing to install daemons for user '$ME'."; exit 1;; esac
mkdir -p -m 700 "$LOG"

OLD="$(grep -l "www-server.py" "$HOME"/Library/LaunchAgents/*.plist 2>/dev/null | head -1 || true)"
if [ -n "$OLD" ]; then
  WEB="$(/usr/libexec/PlistBuddy -c 'Print :Label' "$OLD")"
else
  WEB="$(grep -l "www-server.py" /Library/LaunchDaemons/*.plist 2>/dev/null | head -1 | xargs -I{} /usr/libexec/PlistBuddy -c 'Print :Label' {} 2>/dev/null || true)"
  WEB="${WEB:-local.axella.web}"
fi
case "$WEB" in
  *web) DOG="${WEB%web}watchdog" ;;
  *) DOG="$WEB-watchdog" ;;
esac
echo "Web server label: $WEB"
echo "Watchdog label:   $DOG"

TMP="$(mktemp -d)"
sed -e "s#__LABEL__#$WEB#" -e "s#__USER__#$ME#" -e "s#__HOME__#$HOME#" -e "s#__WWW_DIR__#$WWW#" -e "s#__LOG_DIR__#$LOG#" \
  "$AX/setup/axella-web.daemon.plist.template" > "$TMP/$WEB.plist"
sed -e "s#__LABEL__#$DOG#" -e "s#__USER__#$ME#" -e "s#__HOME__#$HOME#" -e "s#__AXELLA_DIR__#$AX#" -e "s#__LOG_DIR__#$LOG#" \
  "$AX/setup/axella-watchdog.daemon.plist.template" > "$TMP/$DOG.plist"
plutil -lint "$TMP/$WEB.plist" "$TMP/$DOG.plist"

if [ -n "$OLD" ]; then
  echo "Stopping the web LaunchAgent and moving it aside: $OLD"
  launchctl bootout "gui/$(id -u)/$WEB" 2>/dev/null || true
  mkdir -p "$HOME/Library/LaunchAgents-disabled"
  mv "$OLD" "$HOME/Library/LaunchAgents-disabled/"
fi

sudo launchctl bootout "system/$WEB" 2>/dev/null || true
sudo launchctl bootout "system/$DOG" 2>/dev/null || true
sudo install -m 644 -o root -g wheel "$TMP/$WEB.plist" "$TMP/$DOG.plist" /Library/LaunchDaemons/
sudo launchctl bootstrap system "/Library/LaunchDaemons/$WEB.plist"
sudo launchctl bootstrap system "/Library/LaunchDaemons/$DOG.plist"
rm -rf "$TMP"

sleep 3
echo
sudo launchctl print "system/$WEB" | grep -E "state =|pid =" | head -2
sudo launchctl print "system/$DOG" | grep -E "state =|pid =" | head -2
echo
/usr/bin/python3 "$AX/setup/watchdog.py" --once
echo
echo "Done. Reload the dashboard: System status should show Web server and Watchdog as OK."
echo "After a change to www-server.py or watchdog.py: sudo launchctl kickstart -k system/$WEB (or system/$DOG)"
