#!/usr/bin/env python3
"""The commitments scan (axella-actions.py scan_commitments) with Mail, Messages and the exports stubbed: private
contacts are never read, a promise becomes a suggestion, Add puts it in To do with its source. Fictional cast.
Run: python3 setup/tests/test_commitments_scan.py"""
import datetime
import importlib.util
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
import commitments  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


d = tempfile.mkdtemp()
A.PROM = commitments.Promises(d)
A.TASKS_FILE = os.path.join(d, 'tasks.json')
A.config = lambda: {'accounts': {'iCloud': {'kind': 'private', 'address': 'alex@example.com'}, 'Acme': {'kind': 'work', 'address': 'alex@acme.example'}}}
A.profile.is_protected = lambda acc=None, addr=None, cfg=None: False
A.profile.workplaces = lambda cfg=None: []
A.mail_accounts = lambda: {'a1': 'iCloud', 'a2': 'Acme'}
now = time.time()
rows = [
    {'dir': 'out', 'addr': 'alex@acme.example', 'name': '', 'date': now - 3600, 'rowid': 1, 'mid': 'm1', 'subject': 'Quote', 'account': 'Acme',
     'to': [('Lee Chen', 'lee@acme.example')]},
    {'dir': 'out', 'addr': 'alex@example.com', 'name': '', 'date': now - 3600, 'rowid': 2, 'mid': 'm2', 'subject': 'Hi', 'account': 'iCloud',
     'to': [('Anna', 'anna@private.example')]},
    {'dir': 'in', 'addr': 'kim@example.org', 'name': 'Kim', 'date': now - 8 * 86400, 'rowid': 3, 'mid': 'm3', 'subject': 'Dinner?', 'account': 'iCloud', 'to': []},
    {'dir': 'out', 'addr': 'alex@example.com', 'name': '', 'date': now - 30 * 86400, 'rowid': 4, 'mid': 'm4', 'subject': 'Old', 'account': 'iCloud',
     'to': [('Kim', 'kim@example.org')]},
]
A.mailsearch.correspondence = lambda names, own, days=120: rows
read = []
A.mailsearch.message_text = lambda r: (read.append(r['rowid']) or ("I'll send the revised quote Friday." if r['rowid'] == 1 else "I'll call you tomorrow."), False)
A.mail_privacy = lambda addrs: ('private', 'Anna') if 'anna@private.example' in addrs else (None, None)
A.PRIV.level = lambda ch, ident, name=None: 'private' if '9999' in str(ident) else None
A._imessage_rows = lambda days: [('+4500000009', True, now - 600, "Jeg ringer i morgen"), ('+4599999999', True, now - 600, "Jeg sender den i dag")]
A.WA_FILE = os.path.join(d, 'wa.json')
A._people_names = lambda: {'00000009': 'Sam Rivera'}
r = A.scan_commitments()
sug = A.PROM.suggestions()
ok(2 not in read, 'a private contact\'s mail is never read')
ok(sorted(x['person']['name'] for x in sug) == ['Lee Chen', 'Sam Rivera'], 'promises from mail and Messages; the private number is skipped')
lee = next(x for x in sug if x['person']['name'] == 'Lee Chen')
ok(lee['world'] == 'work' and lee['source']['message_id'] == 'm1' and lee['due'], 'linked to its source, work world, with a due date')
ok([x['who'] for x in A._COMMIT['debt']] == ['kim@example.org'], 'reply debt: Kim (you wrote to her before, she waits 8 days)')
res = A.promise_action('promise_add', {'id': lee['id']})
tasks = A.load_json(A.TASKS_FILE, [])
ok(tasks and tasks[0]['source'] == 'promise' and tasks[0]['ref']['person']['name'] == 'Lee Chen' and tasks[0]['ctx'] == 'work', 'Add: in To do with the person and its source')
ok(A.PROM.suggestions() and all(x['id'] != lee['id'] for x in A.PROM.suggestions()), 'and it leaves the suggestions')
A.promise_action('replydebt_never', {'who': 'kim@example.org'})
A.scan_commitments()
ok(A._COMMIT['debt'] == [], '"Never for this person" sticks')

# a protected workplace: the promise is found, but no sentence or subject is stored
A.PROM = commitments.Promises(tempfile.mkdtemp())
A.PROM.set_never('kim@example.org', False)
A.profile.is_protected = lambda acc=None, addr=None, cfg=None: acc == 'Acme' or str(addr or '').endswith('@acme.example')
rows.append({'dir': 'in', 'addr': 'sam@acme.example', 'name': 'Sam Rivera', 'date': now - 9 * 86400, 'rowid': 5, 'mid': 'm5',
             'subject': 'Secret merger plan', 'account': 'Acme', 'to': []})
rows.append({'dir': 'out', 'addr': 'alex@acme.example', 'name': '', 'date': now - 40 * 86400, 'rowid': 6, 'mid': 'm6', 'subject': 'Old',
             'account': 'Acme', 'to': [('Sam Rivera', 'sam@acme.example')]})
A._COMMIT['seen'] = set()
A.scan_commitments()
raw = open(os.path.join(A.PROM.file)).read()
lee = next(x for x in A.PROM.suggestions() if x['person']['name'] == 'Lee Chen')
ok(lee['protected'] and lee['sentence'] == '' and lee['source']['subject'] == '' and lee['due'] is None, 'protected: who/when-only card')
ok('revised quote' not in raw and 'Quote' not in raw, 'protected: neither the sentence nor the subject is in promises.json')
sam = next((x for x in A._COMMIT['debt'] if x['who'] == 'sam@acme.example'), None)
ok(sam is not None and not sam['subject'], 'reply debt for a protected sender carries no subject')
res = A.promise_action('promise_add', {'id': lee['id']})
t = A.load_json(A.TASKS_FILE, [])[-1]
ok('revised' not in t['text'] + t.get('notes', '') and 'protected workplace' in t['notes'], 'its To do keeps the words out too')

# fix round 7, P2-1, end to end: an authority, a Cc-only mail and a "Tak!" are not owed; a direct question is
A.profile.is_protected = lambda acc=None, addr=None, cfg=None: False
rows[:] = [r for r in rows if r['rowid'] not in (5, 6)]
for i, (who, extra) in enumerate([('sagsbehandler@example-kommune.dk', {}), ('robin@example.org', {'direct': False}),
                                  ('jamie@example.org', {}), ('sam.rivera@acme.example', {'direct': True})]):
    rows.append(dict({'dir': 'in', 'addr': who, 'name': '', 'date': now - 9 * 86400, 'rowid': 20 + i, 'mid': 'n%d' % i, 'subject': 'S',
                      'account': 'Acme' if 'acme' in who else 'iCloud', 'to': []}, **extra))
    rows.append({'dir': 'out', 'addr': 'alex@example.com', 'name': '', 'date': now - 30 * 86400, 'rowid': 40 + i, 'mid': 'o%d' % i,
                 'subject': 'Old', 'account': 'iCloud', 'to': [('', who)]})
texts = {22: 'Tak!\n\nMvh\nJamie', 23: 'Hi Alex, can you send the signed copy?'}
A.mailsearch.message_text = lambda r: (texts.get(r['rowid'], "I'll call you tomorrow."), False)
A._COMMIT['seen'], A._COMMIT['thanks'] = set(), {}
A.scan_commitments()
got = sorted(x['who'] for x in A._COMMIT['debt'])
ok('sagsbehandler@example-kommune.dk' not in got, 'scan: a municipality address you once wrote to is not owed a reply')
ok('robin@example.org' not in got, 'scan: a mail where you were only on Cc is not owed a reply')
ok('jamie@example.org' not in got, 'scan: a last message that is just "Tak!" is not owed a reply')
ok('sam.rivera@acme.example' in got and 'kim@example.org' in got, 'scan: a direct question still counts')
ok(all('@' not in x['name'] for x in A._COMMIT['debt']) and 'Sam Rivera' in [x['name'] for x in A._COMMIT['debt']], 'scan: names, never addresses (Sam Rivera from sam.rivera@)')

# Done on a reply-debt line: gone now and after the next scan, back when they write again
A.promise_action('replydebt_done', {'who': 'sam.rivera@acme.example'})
ok(all(x['who'] != 'sam.rivera@acme.example' for x in A._COMMIT['debt']), 'Done: gone from the list at once')
A.scan_commitments()
ok(all(x['who'] != 'sam.rivera@acme.example' for x in A._COMMIT['debt']), '… and after the next scan')
rows.append({'dir': 'in', 'addr': 'sam.rivera@acme.example', 'name': '', 'date': now - 6 * 86400, 'rowid': 60, 'mid': 'n60', 'subject': 'S',
             'account': 'Acme', 'to': [], 'direct': True})
A.scan_commitments()
ok(any(x['who'] == 'sam.rivera@acme.example' for x in A._COMMIT['debt']), '… and back when Sam writes again')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
