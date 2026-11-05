#!/usr/bin/env python3
"""Back-from-away briefing (setup/away.py): when it comes (Away end, paused days, at least 2 days, weekends bridge,
once per absence), the facts for the run and the fallback when no digests exist, the "Sorted itself out" rules, and
the briefing hook (groups added, absence marked briefed, no push). Invented data only. Run: python3 setup/tests/test_away.py"""
import datetime
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import away as A  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


D = datetime.date
days = lambda *ds: (lambda d: d in set(ds))
weekend = lambda d: d.weekday() >= 5
MON = D(2027, 3, 15)
# away Tue 9 – Fri 12 March, back on Monday 15th: the weekend bridges
ab = A.absence(MON, days(D(2027, 3, 9), D(2027, 3, 10), D(2027, 3, 11), D(2027, 3, 12)), weekend)
ok(ab == {'from': '2027-03-09', 'to': '2027-03-12', 'days': 4}, 'Away Tue–Fri, back Monday: a 4-day absence (%s)' % ab)
ok(A.absence(MON, days(D(2027, 3, 12)), weekend) is None, 'a 1-day pause (Friday off) does not trigger it')
ok(A.absence(MON, days(D(2027, 3, 12), D(2027, 3, 11)), weekend)['days'] == 2, '2 days does')
ok(A.absence(MON, days(D(2027, 3, 12), D(2027, 3, 15)), weekend) is None and
   A.absence(D(2027, 3, 16), days(D(2027, 3, 12), D(2027, 3, 15)), weekend)['days'] == 4, 'Friday and Monday off: briefed on Tuesday, over the weekend')
ok(A.absence(MON, lambda d: False, weekend) is None, 'a weekend alone is not an absence')
ok(A.absence(MON, days(D(2027, 3, 11), D(2027, 3, 12), MON), weekend) is None, 'still away today: not yet')
ok(A.absence(D(2027, 3, 11), days(D(2027, 3, 8), D(2027, 3, 9)), weekend) is None, 'only right after the absence – not two days later')

st = tempfile.mkdtemp()
W = A.Away(st)
isaway = days(D(2027, 3, 9), D(2027, 3, 10), D(2027, 3, 11), D(2027, 3, 12))
ok(W.due(MON, isaway, weekend)['from'] == '2027-03-09', 'due: the absence to brief')
W.mark_briefed(W.due(MON, isaway, weekend))
ok(W.due(MON, isaway, weekend) is None, 'once per absence')

# ---- digests written while away
dd = tempfile.mkdtemp()
NOW = datetime.datetime(2027, 3, 15, 7, 30)


def it(iid, sec, **kw):
    return dict({'id': iid, 'section': sec, 'channel': 'mail', 'headline': 'About ' + iid, 'from': {'name': 'Lee Chen', 'address': 'lee@example.com'}}, **kw)


ITEMS1 = [it('ans', 'p2'), it('news', 'p3'), it('file1', 'file'), it('ev', 'cal', event={'start': '2027-03-10T10:00:00', 'end': '2027-03-10T11:00:00'}),
          it('evnext', 'cal', event={'start': '2027-03-16T10:00:00', 'end': '2027-03-16T11:00:00'}), it('call1', 'p3', channel='calls'),
          it('callback', 'p1', channel='calls'), it('urgent', 'p0'), it('still', 'p1'), it('done', 'p2')]
for n, items in (('2027-03-08-1530.json', [it('before', 'p2')]), ('2027-03-10-0730.json', ITEMS1), ('2027-03-10-1000-p0.json', [it('u2', 'p0')]),
                 ('2027-03-11-0730.json', [it('news', 'p3', headline='About news (newer)'), it('left', 'p1')])):
    json.dump({'items': items}, open(os.path.join(dd, n), 'w'))
ok(A.digests_between(dd, '2027-03-09', '2027-03-15') == ['2027-03-10-0730.json', '2027-03-11-0730.json'], 'the regular digests written while away (not urgent ones, not from before)')
ok(A.load_items(dd, ['2027-03-10-0730.json', '2027-03-11-0730.json'])['news']['headline'] == 'About news (newer)', 'each item once, its newest version')

items = A.load_items(dd, ['2027-03-10-0730.json', '2027-03-11-0730.json'])
so = A.sorted_out(items, {'done': {'status': 'done'}}, keep_ids=['still'], now=NOW, last_ids=['news', 'left'])
g = {x['key']: sorted(i['id'] for i in x['items']) for x in so['groups']}
ok(g.get('answered') == ['ans'], 'answered or settled: an open item a later regular digest no longer carries (%s)' % g.get('answered'))
ok('left' not in str(g), 'an open item the newest digest still carries, left out by the briefing alone: not grouped, stays open')
ok('answered' not in str([x['key'] for x in A.sorted_out(items, {}, ['still'], NOW)['groups']]), 'no evidence (no later digest known): nothing counts as answered')
ok(g.get('events') == ['ev'] and 'evnext' not in str(g), 'events that have passed – not coming ones')
ok(g.get('bulk') == ['file1', 'news'], 'newsletters, notifications and FYIs')
ok(g.get('calls') == ['call1'], 'calls already handled – a call waiting for a callback is not')
ok('urgent' not in str(g) and 'still' not in str(g) and 'done' not in str(g), 'never: urgent items, what the briefing still shows, handled ones')
ok(so['count'] == 5 and [x['key'] for x in so['groups']] == ['answered', 'events', 'bulk', 'calls'], 'grouped counts, in a fixed order')

TASKS = [{'id': 't1', 'text': 'Send Kim the plan', 'due': '2027-03-14', 'source': 'promise'},
         {'id': 't2', 'text': 'Acme invoice', 'due': '2027-03-18', 'type': 'bill', 'bill': {'payee': 'Acme', 'amount': 100, 'currency': 'DKK'}},
         {'id': 't3', 'text': 'Later', 'due': '2027-04-30'}, {'id': 't4', 'text': 'Done one', 'due': '2027-03-01', 'status': 'done'}]
f = A.facts({'from': '2027-03-09', 'to': '2027-03-12', 'days': 4}, ['private', 'work'], dd, {}, TASKS, MON.__class__(2027, 3, 15),
            preps=[{'start': '2027-03-16T10:00:00', 'event': {'id': 'e1'}}], trips=[{'title': 'Spring trip', 'start': '2027-03-19', 'end': '2027-03-21'}],
            renewals=[{'name': 'Passport', 'date': '2027-04-01'}])
ok(f['digests'] == ['2027-03-10-0730.json', '2027-03-11-0730.json'] and f['arrived'] == 11 and f['fallback_rescan'] is None, 'facts: the digests and how many things arrived')
ok([x['task_id'] for x in f['promises_due']] == ['t1'] and [x['task_id'] for x in f['bills_due']] == ['t2'] and f['tasks_overdue'] == 1,
   '… promises and bills due this week (overdue included), not done or later ones')
ok(f['preps_this_week'][0]['event_id'] == 'e1' and f['trips_this_week'][0]['title'] == 'Spring trip' and f['renewals_soon'][0]['name'] == 'Passport', '… preps, trips, renewals')
empty = tempfile.mkdtemp()
f2 = A.facts({'from': '2027-02-20', 'to': '2027-03-12', 'days': 21}, ['work'], empty, {}, [], D(2027, 3, 15))
ok(f2['digests'] == [] and f2['fallback_rescan'] == {'from': '2027-03-01', 'to': '2027-03-15'}, 'no digests while away: fall back to an inbox re-scan, at most 14 days')
ok('re-scan the mail inboxes from 2027-03-01' in A.prompt_note(f2) and 're-scan' not in A.prompt_note(f), '… and the run is told so')

# ---- the hook after the run
W2 = A.Away(tempfile.mkdtemp())
W2.write_facts(f)
json.dump({'items': [it('still', 'p1')], 'away': {'headline': 'Welcome back.'}}, open(os.path.join(dd, '2027-03-15-0730.json'), 'w'))
r = W2.add_to_digest(dd, '2027-03-15-0730.json', lambda: {'done': {'status': 'done'}}, now=NOW)
dg = json.load(open(os.path.join(dd, '2027-03-15-0730.json')))
ok(r is True and dg['away']['sorted']['count'] == 5 and dg['away']['arrived'] == 11, 'the briefing gets "Sorted itself out" and the count that arrived')
ok(W2.due(MON, isaway, weekend) is None, '… and the absence counts as briefed')
ok(W2.add_to_digest(dd, '2027-03-11-0730.json', lambda: {}) is False, 'a normal digest is left alone (and pushed as usual)')
BN = '2027-03-15-0730.json'
ok(dg['away']['sorted_by'] == 'axella' and dg['away']['sorted_hash'] == A.ids_hash(W2.stored_ids(BN)) and len(W2.stored_ids(BN)) == 5,
   'Python marks its own list, and keeps its ids and hash in state/away.json')
ok(W2.group_ids(BN, keep=['ans']) and 'ans' not in W2.group_ids(BN, keep=['ans']) and len(W2.group_ids(BN)) == 5, 'Archive all: the stored ids, minus what you kept back')
b = W2.archive(BN, W2.group_ids(BN))
ok(sorted(W2.take_batch(b)['ids']) == sorted(W2.group_ids(BN)), 'one batch for the one Undo')
try:
    W2.take_batch(b)
    ok(False, 'an Undo works once')
except A.Bad:
    ok(True, 'an Undo works once')

# ---- a run-written list is never used: Python's replaces it
W3 = A.Away(tempfile.mkdtemp())
W3.write_facts(f)
fake = {'groups': [{'key': 'answered', 'label': 'x', 'count': 1, 'items': [{'id': 'left', 'headline': 'About left'}]}], 'count': 1}   # 'left': a P1 still open
json.dump({'items': [it('urgent2', 'p2')], 'away': {'headline': 'Welcome back.', 'sorted': fake, 'sorted_by': 'axella', 'sorted_hash': A.ids_hash(['left'])}},
          open(os.path.join(dd, '2027-03-15-0800.json'), 'w'))
W3.add_to_digest(dd, '2027-03-15-0800.json', lambda: {}, now=NOW)
dg3 = json.load(open(os.path.join(dd, '2027-03-15-0800.json')))
ids3 = A.list_ids(dg3['away']['sorted'])
ok(dg3['away']['sorted'] != fake and dg3['away']['sorted_hash'] == A.ids_hash(W3.stored_ids('2027-03-15-0800.json')),
   'a list the run wrote (even marked "axella") is thrown away and Python\'s list is added')
ok('left' not in ids3 and 'left' not in W3.group_ids('2027-03-15-0800.json'), '… so the P1 the run listed is not in it, and Archive all can\'t reach it')
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
