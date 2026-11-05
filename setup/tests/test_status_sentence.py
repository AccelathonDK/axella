#!/usr/bin/env python3
"""System status in one sentence, in the action service (axella-actions.py system_status): the sentence comes with the
rows, "since" is kept in state/status-since.json, and the next digest's time is named. Run in a scratch state folder.
Run: python3 setup/tests/test_status_sentence.py"""
import datetime
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


A.STATE_DIR = tempfile.mkdtemp()
r = A.system_status()
s = r.get('sentence') or {}
bad = [c for c in r['components'] if c['state'] in ('down', 'warn')]
ok(s.get('level') in ('ok', 'warn', 'down') and isinstance(s.get('text'), str) and s['text'], 'system_status carries the sentence')
ok(len(s.get('problems') or []) == len(bad), 'one analysis block per problem row')
ok((s['text'].startswith('Everything works')) == (not bad), '"Everything works" only when no row is bad')
ok(os.path.exists(os.path.join(A.STATE_DIR, 'status-since.json')) == bool(bad), '"since" kept in status-since.json when something is bad')


class R:
    def load(self):
        return {'enabled': True, 'digests': []}

    def slots_for(self, day, cfg):
        return [('morning', 'digest-morning', '07:30', 'Morning'), ('p0-0745', 'p0-check', '07:45', 'Urgent check'), ('mid', 'digest-midday', '11:30', 'Midday')]


A.RUNNER = R()
ok(A._next_digest_label(datetime.datetime(2027, 3, 4, 9, 0)) == '11:30', 'the next digest today, urgent checks left out')
ok(A._next_digest_label(datetime.datetime(2027, 3, 4, 12, 0)) == 'Fri 07:30', '… or the next day\'s')
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
