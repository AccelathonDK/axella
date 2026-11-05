#!/usr/bin/env python3
"""Renewals in the action service (axella-actions.py): the mail scan's left-out rules (private contacts, scam-flagged),
Add to To do (a task with the date as its due date, linked back), and the view with a yearly subscription linked.
Mail is stubbed; invented data only. Run: python3 setup/tests/test_renewals_actions.py"""
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
import renewals as RN  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


st = tempfile.mkdtemp()
A.RENEW = RN.Renewals(st)
A.mail_accounts = lambda: {'1': 'iCloud'}
ROWS = [{'path': 'p1', 'account': 'iCloud', 'message_id': 'm1@x', 'subject': 'Your domain expires soon', 'from_address': 'billing@acme-domains.example'},
        {'path': 'p2', 'account': 'iCloud', 'message_id': 'm2@x', 'subject': 'Din forsikring fornyes', 'from_address': 'anna@example.com'},
        {'path': 'p3', 'account': 'iCloud', 'message_id': 'm3@x', 'subject': 'Your account expires', 'from_address': 'x@scam.example'}]
A.mailsearch.booking_candidates = lambda names, match, days, limit: [r for r in ROWS if match(r['subject'], r['from_address'])]
A.mailsearch.addresses_of = lambda path: [next(r['from_address'] for r in ROWS if r['path'] == path)]
A.mail_privacy = lambda addrs: ('anna@example.com' in addrs, None)
A.mailsearch._raw = lambda path: path.encode()
A._known_people = lambda: ([],)
A._safety.check_mail = lambda raw, *a: (raw == b'p3', None)
read = []
A._renewals.read_mail = lambda raw: (read.append(raw), {'kind': 'domain', 'name': 'Acme domain', 'date': '2027-04-02', 'domain': 'acme-domains.example'})[1]
found = A._renewal_mails()
ok([f['message_id'] for f in found] == ['m1@x'] and read == [b'p1'], 'the scan: a private contact\'s and a scam-flagged mail are never read or suggested')

A.TASKS_FILE = os.path.join(st, 'tasks.json')
json.dump([], open(A.TASKS_FILE, 'w'))
e = A.renewal_action('renewal_add', {'name': 'Car insurance', 'kind': 'insurance', 'date': '2027-05-01', 'ctx': 'private'})
r = A.renewal_action('renewal_todo', {'id': e['id']})
tasks = json.load(open(A.TASKS_FILE))
ok(len(tasks) == 1 and tasks[0]['due'] == '2027-05-01' and tasks[0]['ref'] == {'kind': 'renewal', 'id': e['id']} and tasks[0]['ctx'] == 'private',
   'Add to To do: a task with the date as its due date, linked back')
ok(r['task_id'] == tasks[0]['id'] and r['handled'] == '2027-05-01', '… and the card is done for this time')
try:
    A.renewal_action('renewal_add', {'name': 'Passport', 'kind': 'passport', 'date': '2027-10-01', 'cost': 'lots'})
    ok(False, 'a bad cost is refused')
except A.Bad:
    ok(True, 'a bad cost is refused')
A.RECUR.view = lambda: {'subs': [{'id': 's1', 'vendor': 'Acme Cloud', 'interval': 'yearly', 'status': 'active', 'next': (__import__('datetime').date.today() + __import__('datetime').timedelta(days=60)).isoformat(), 'amount': 59, 'currency': 'EUR'},
                                 {'id': 's2', 'vendor': 'Acme Stream', 'interval': 'monthly', 'status': 'active', 'next': '2026-12-01'}]}
A.TRIPS.load = lambda: {'trips': []}
v = A.renewals_view()
ok([x['name'] for x in v['rows'] if x.get('linked')] == ['Acme Cloud'], 'a yearly subscription is linked on the timeline')
ok(not any(x.get('name') == 'Acme Stream' for x in v['rows']), 'a monthly subscription is not a renewal')
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
