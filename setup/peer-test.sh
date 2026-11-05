#!/bin/bash
# Which program connects to the Axella services on 127.0.0.1? Changes nothing. (docs/SETUP.md, troubleshooting)
# Run it, then reload the dashboard on your phone a few times within 30 seconds.
echo "Reload the dashboard on your phone a few times now – watching for 30 seconds…"
OUT=$(mktemp "${TMPDIR:-/tmp}/axella-peer.XXXXXX")   # your private temp folder, not shared /tmp
end=$((SECONDS + 30))
while [ $SECONDS -lt $end ]; do
  netstat -anv -p tcp 2>/dev/null | grep -E '127\.0\.0\.1\.(8787|8788)' | grep -v LISTEN >> "$OUT"
  lsof -nP -iTCP:8787 -iTCP:8788 2>/dev/null | grep -v LISTEN | grep -v '^COMMAND' >> "$OUT"
  sleep 0.2
done
echo "== netstat header"
netstat -anv -p tcp 2>/dev/null | sed -n 2p
echo "== connections seen (unique)"
sort -u "$OUT" | head -40
echo "== owners of the process ids in the last column(s)"
for p in $(sort -u "$OUT" | grep -oE '[A-Za-z][A-Za-z0-9._ -]*:[0-9]+' | grep -oE '[0-9]+$' | sort -u); do
  ps -o user=,pid=,comm= -p "$p" 2>/dev/null
done
rm -f "$OUT"
