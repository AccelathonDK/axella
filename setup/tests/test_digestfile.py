#!/usr/bin/env python3
"""digestfile.update: every pass that changes a digest after its run (scope check, scam check, Mark safe, the
subscriptions line) locks the file and re-reads it, so two passes at the same time keep both changes.
Invented data only. Run: python3 setup/tests/test_digestfile.py"""
import json
import os
import re
import sys
import tempfile
import threading
from email.message import EmailMessage

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import digestfile  # noqa: E402
import safety as S  # noqa: E402
import scope as SC  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


tmp = tempfile.mkdtemp()
dg, st = os.path.join(tmp, 'digests'), os.path.join(tmp, 'state')
os.makedirs(dg)
os.makedirs(st)

# many writers, one file: no lost update
path = os.path.join(dg, '2027-01-04-0730.json')
json.dump({'n': 0, 'items': []}, open(path, 'w'))


def bump(d):
    d['n'] += 1
    return True, d['n']


ts = [threading.Thread(target=lambda: [digestfile.update(path, bump) for _ in range(100)]) for _ in range(4)]
[t.start() for t in ts]
[t.join() for t in ts]
ok(json.load(open(path))['n'] == 400, '4 threads × 100 updates: every one kept')
ok(digestfile.update(os.path.join(dg, 'missing.json'), bump) is None, 'a missing file: nothing written, None')

# the scope check and the scam check on the same digest at the same time: both changes survive
S.BRANDS = [(re.compile(r'acme ?post', re.I), re.compile(r'(^|\.)(acmepost\.example)$', re.I))]
m = EmailMessage()
m['From'], m['To'], m['Subject'] = 'Acme Post <service@acmepost-levering.example>', 'alex@example.com', 'Your parcel is waiting'
m.set_content('Pay a customs fee within 24 hours: https://acmepost-levering.example/pay')
RAW = m.as_bytes()
both_ok = True
for i in range(15):
    name = '2027-01-%02d-0900.json' % (i + 5)
    p = os.path.join(dg, name)
    json.dump({'spoken': 'Your work digest.', 'items': [
        {'id': 'w1', 'section': 'p1', 'channel': 'mail', 'context': 'work', 'message_id': 'scam@x', 'headline': 'Parcel',
         'from': {'name': 'Acme Post', 'address': 'service@acmepost-levering.example'}},
        {'id': 'p1', 'section': 'p2', 'channel': 'mail', 'context': 'private', 'headline': 'Robin: dinner?',
         'from': {'name': 'Robin', 'address': 'robin@example.org'}}]}, open(p, 'w'))
    saf = S.Safety(st, dg, lambda mid: RAW, lambda: (set(), set()))
    a = threading.Thread(target=SC.enforce, args=(p, ['work'], st))
    b = threading.Thread(target=saf.scan_digest, args=(name,))
    a.start(); b.start(); a.join(); b.join()
    d = json.load(open(p))
    ids = [x['id'] for x in d['items']]
    w1 = next((x for x in d['items'] if x['id'] == 'w1'), {})
    if not (d.get('scope') == ['work'] and ids == ['w1'] and w1.get('safety', {}).get('level') == 'scam'):
        both_ok = False
ok(both_ok, 'scope check + scam check from two threads, 15 times: the scope, the removed private item and the scam label all survive')
ok('Robin' not in json.load(open(p)).get('spoken', '') and json.load(open(p)).get('spoken_replaced') == 'scope',
   'a run that ignored its scope: its spoken text is replaced by a neutral one')

print('%d failed' % fails if fails else 'all passed')
sys.exit(1 if fails else 0)
