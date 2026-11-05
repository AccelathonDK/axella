#!/usr/bin/env python3
"""LIVE check of transcription on the Mac mini – run in Terminal (not part of tools/run-tests.sh):
  cd ~/dev/own/home-server/axella && python3 setup/live-checks/meeting_transcribe_live.py
macOS `say` makes a short invented clip (nobody's voice, an invented sentence), whisper.cpp transcribes it with the
model from actions-config.json (or the usual places), and the check compares a few words. Nothing leaves the Mac mini,
and the clip and its text are deleted afterwards."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import meetings  # noqa: E402

SENTENCE = 'Acme planning meeting. Lee will send the revised brief on Friday.'
try:
    cfg = (json.load(open(os.path.join(HERE, 'actions-config.json'))) or {}).get('meetings') or {}
except (OSError, ValueError):
    cfg = {}
lines = []
tr = meetings.Transcriber(cfg, note=lambda status, summary, *a: lines.append((status, summary)))
st = tr.status()
if not st['transcribe']:
    print('✗ not set up: %s – run tools/setup-whisper.sh' % st['why'])
    sys.exit(1)
print('✓ whisper and %s found' % st['model'])
tmp = tempfile.mkdtemp(prefix='ax-live-')
clip = os.path.join(tmp, 'clip.aiff')
try:
    subprocess.run(['/usr/bin/say', '-o', clip, SENTENCE], check=True, timeout=60)
    text = tr.transcribe(clip).lower()
    want = ['acme', 'brief', 'friday']
    got = [w for w in want if w in text]
    print('%s %d of %d words heard (%s)' % ('✓' if len(got) == len(want) else '✗', len(got), len(want), ', '.join(got) or 'none'))
    print('  Runs line: %s – %s' % lines[-1] if lines else '  (no Runs line)')
    sys.exit(0 if len(got) == len(want) else 1)
finally:
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)
