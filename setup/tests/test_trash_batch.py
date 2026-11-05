#!/usr/bin/env python3
"""Filing suggestions → Delete (axella-actions.py trash_batch): one job moves at most 200 mails to Trash (never a
permanent delete), marks each item done and writes ONE activity-log line; the reports still count every item as
handled. Mail is stubbed. Fictional cast. Run: python3 setup/tests/test_trash_batch.py"""
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
import store  # noqa: E402
import activity  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


d = tempfile.mkdtemp()
A.LOG_FILE = os.path.join(d, 'actions.log')
A.STATE_FILE = os.path.join(d, 'state.json')
A.config = lambda: {'accounts': {'Acme': {'kind': 'work', 'address': 'alex@acme.example'}}}
calls = []


def osa(script, *args, timeout=60, tries=1):
    calls.append((script, args))
    if args[1] == '<bad@acme.example>':
        raise RuntimeError('execution error: Mail got an error')
    return 'ok'


A.osa = osa
items = [{'item_id': 'f%d' % i, 'account': 'Acme', 'message_id': '<m%d@acme.example>' % i} for i in range(201)]


def refused(p, label):
    n = len(calls)
    try:
        A.do_action('trash_batch', p)
        ok(False, label)
    except A.Bad:
        ok(len(calls) == n, label)


refused({'items': items}, '201 mails in one batch are refused – nothing moved')
refused({'items': items[:2] + [{'item_id': 'x', 'account': 'Private', 'message_id': '<p@x>'}]}, 'a mail on an account not configured: the whole batch is refused')
refused({'items': []}, 'an empty batch is refused')

batch = items[:200]
p = {'items': batch}
r = A.do_action('trash_batch', p)
ok(r == {'moved': 200, 'failed': 0} and len(calls) == 200 and all(c[0] is A.TRASH_SCRIPT for c in calls), '200 mails: each moved to Trash with the Trash script')
st = json.load(open(A.STATE_FILE))
ok(all(st['f%d' % i]['status'] == 'done' and st['f%d' % i]['how'] == 'trash' for i in range(200)), 'each item is marked done')
A.log('m@x', 'trash_batch', p, 'ok')
lines = open(A.LOG_FILE).read().splitlines()
e = json.loads(lines[0])
ok(len(lines) == 1 and e['title'] == 'Moved 200 mails to Trash' and len(e['items']) == 200, 'one line in the activity log for the whole batch')
ok('acme.example' not in lines[0].replace('"items"', ''), '… with item ids only – no addresses or message ids')
ok(activity.LABELS.get('trash_batch') and any('trash_batch' in v for v in activity.TYPES.values()), 'the activity log has a label and a filter for it')

calls.clear()
p2 = {'items': [items[0], {'item_id': 'b', 'account': 'Acme', 'message_id': '<bad@acme.example>'}]}
r = A.do_action('trash_batch', p2)
ok(r == {'moved': 1, 'failed': 1} and p2['title'] == 'Moved 1 of 2 mails to Trash', 'one Mail error: the rest still move, the title says how many')

db = sqlite3.connect(':memory:')
db.executescript(store.SCHEMA if hasattr(store, 'SCHEMA') else 'CREATE TABLE actions (at TEXT, login TEXT, action TEXT, result TEXT, item TEXT, message_id TEXT, folder TEXT, title TEXT);')
store.Store._action_lines(db, (lines[0] + '\n').encode())
rows = db.execute("SELECT COUNT(*) FROM actions WHERE action = 'trash' AND item LIKE 'f%'").fetchone()[0]
ok(rows == 200, 'the reports read the batch as 200 handled items')
ok('trash_batch' in A.SLOW_ACTIONS, 'runs in the Mail job queue, one at a time')

print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
