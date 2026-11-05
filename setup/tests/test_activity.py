#!/usr/bin/env python3
"""The activity log: dashboard actions and Axella's own (runs, notifications, automatic forwards) newest first,
filters, the 1,000 cap, and archiving after 90 days (moved, never deleted). Fictional data.
Run: python3 setup/tests/test_activity.py"""
import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import activity as A  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


d = tempfile.mkdtemp()
log = os.path.join(d, 'actions.log')
rows = [
    {'at': '2026-07-01T10:00:00+02:00', 'login': 'owner@example.com', 'action': 'file', 'result': 'ok', 'folder': 'Archive'},
    {'at': '2026-11-03T09:00:00+01:00', 'login': 'owner@example.com', 'action': 'reply_send', 'result': 'ok', 'title': 'Quote for Acme'},
    {'at': '2026-11-03T09:05:00+01:00', 'login': 'axella', 'action': 'push', 'result': 'ok', 'title': 'call → 2 devices'},
    {'at': '2026-11-03T09:10:00+01:00', 'login': 'sam@example.com', 'action': 'contact_delete', 'result': 'rejected: owner only'},
    {'at': '2026-11-03T09:20:00+01:00', 'login': 'owner@example.com', 'action': 'contact_delete', 'result': 'ok', 'title': 'Lee Chen', 'backup': '20261103-092000-abc'},
]
with open(log, 'w') as f:
    f.write('\n'.join(json.dumps(r) for r in rows) + '\n{broken\n')
runs = [{'started': '2026-11-03T07:30:00+01:00', 'label': 'Morning digest', 'status': 'ok', 'trigger': 'schedule'},
        {'started': '2026-11-03T11:30:00+01:00', 'label': 'Midday digest', 'status': 'failed', 'reason': 'timeout'}]
r = A.entries(log, runs)
ok([e['action'] for e in r['entries'][:2]] == ['run', 'contact_delete'] and r['total'] == 7, 'newest first, runs merged, a broken line skipped')
ok(next(e for e in r['entries'] if e['action'] == 'contact_delete' and e['ok'])['backup'] == '20261103-092000-abc', 'a delete carries its backup (Restore)')
ok([e['type'] for e in A.entries(log, runs, {'type': 'mail'})['entries']] == ['mail', 'mail'], 'filter: type')
ok({e['action'] for e in A.entries(log, runs, {'result': 'error'})['entries']} == {'run', 'contact_delete'}, 'filter: errors only')
ok(all(e['who'] == 'axella' for e in A.entries(log, runs, {'who': 'axella'})['entries']), 'filter: who')
ok(len(A.entries(log, runs, {'text': 'acme'})['entries']) == 1, 'filter: text')
ok(A.label_of('reply_send') == 'Reply sent' and A.type_of('task_add') == 'tasks' and A.type_of('vip_add') == 'contacts', 'labels and types')
big = os.path.join(d, 'big.log')
with open(big, 'w') as f:
    for i in range(1500):
        f.write(json.dumps({'at': '2026-11-03T10:%02d:%02d+01:00' % (i // 60 % 60, i % 60), 'login': 'x', 'action': 'done', 'result': 'ok'}) + '\n')
b = A.entries(big, [])
ok(len(b['entries']) == 1000 and b['capped'], 'at most 1,000 shown')
n = A.archive(log, os.path.join(d, 'archive'), threading.Lock(), '2026-11-04')
ok(n == 1 and os.path.isfile(os.path.join(d, 'archive', '2026-07.log')), 'older than 90 days → archive/2026-07.log')
ok('Archive' not in open(log).read() and 'Quote for Acme' in open(log).read(), 'the rest stays in the log')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
