#!/usr/bin/env python3
"""What you pushed to Later (axella-actions.later_view – the line at the bottom of Today): the snoozed items that
haven't come back yet, soonest first, each with its item from the newest digest that has it, or only the title when
that digest is gone. Read-only. Invented data. Run: python3 setup/tests/test_later.py"""
import datetime
import importlib.util
import json
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


d = tempfile.mkdtemp()
A.DIGESTS_DIR = os.path.join(d, 'digests')
os.makedirs(A.DIGESTS_DIR)
A.STATE_FILE = os.path.join(d, 'actions.json')
NOW = datetime.datetime(2030, 3, 14, 9, 0)
json.dump({'items': [{'id': 'k1', 'section': 'p2', 'headline': 'Kim: dinner? (old)', 'from': {'name': 'Kim'}}]},
          open(os.path.join(A.DIGESTS_DIR, '2030-03-13-0730.json'), 'w'))
json.dump({'items': [{'id': 'k1', 'section': 'open', 'headline': 'Kim: dinner?', 'channel': 'mail', 'from': {'name': 'Kim'}},
                     {'id': 'l1', 'section': 'p1', 'headline': 'Lee: the quote', 'from': {'name': 'Lee Chen'}}]},
          open(os.path.join(A.DIGESTS_DIR, '2030-03-14-0730.json'), 'w'))
json.dump({
    'k1': {'status': 'snoozed', 'until': '2030-03-15T06:00:00.000Z', 'title': 'Kim: dinner?'},
    'l1': {'status': 'snoozed', 'until': '2030-03-14T15:00:00', 'title': 'Lee: the quote'},
    'g1': {'status': 'snoozed', 'until': '2030-03-20T06:00:00+00:00', 'title': 'Sam: an old one'},
    'past': {'status': 'snoozed', 'until': '2030-03-14T06:00:00+00:00', 'title': 'back already'},
    'd1': {'status': 'done', 'title': 'done'},
    'bad': {'status': 'snoozed', 'until': 'not a date', 'title': 'x'}}, open(A.STATE_FILE, 'w'))
v = A.later_view(NOW)['items']
ok([x['id'] for x in v] == ['l1', 'k1', 'g1'], 'only what hasn\'t come back yet, soonest first (back already, done and a bad date left out)')
ok(v[0]['until'] == '2030-03-14T15:00' and v[1]['until'][:10] == '2030-03-15', 'the times, as local time')
ok(v[1]['item']['headline'] == 'Kim: dinner?', 'each with its item from the newest digest that has it')
ok(v[2]['item'] is None and v[2]['title'] == 'Sam: an old one', 'a digest that is gone: the title it was pushed under')
src = open(os.path.join(HERE, 'axella-actions.py'), encoding='utf-8').read()
ok("if a == 'later':" in src, 'GET later')

print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
