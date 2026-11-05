#!/usr/bin/env python3
"""Week wrap (setup/wrap.py + scheduler.py): the week's facts for a work or private wrap, and the run being told to
write it (Friday work wrap; the Sunday week-ahead unless the slot turned it off). Invented data only.
Run: python3 setup/tests/test_wrap.py"""
import datetime
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import wrap as W  # noqa: E402
import scheduler as S  # noqa: E402
from store import Store  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


FRI = datetime.date(2027, 3, 19)
ok(W.week_of(FRI) == (datetime.date(2027, 3, 15), FRI) and W.next_week(FRI) == (datetime.date(2027, 3, 22), datetime.date(2027, 3, 28)),
   'this week Mon–today, next week Mon–Sun')

tmp = tempfile.mkdtemp()
state = os.path.join(tmp, 'state')
os.makedirs(state)
st = Store(tmp, state)
st.init()
st._world = lambda: (lambda item_id, addr, context, account: context or 'private')
with st._db() as db:
    for d, i, ctx, mid in (('2027-03-16-0930', 'a', 'work', 'm-a'), ('2027-03-16-0930', 'b', 'work', 'm-b'),
                           ('2027-03-17-0930', 'b', 'work', 'm-b'), ('2027-03-17-0930', 'c', 'private', 'm-c'),
                           ('2027-03-08-0930', 'z', 'work', 'm-z')):
        db.execute('INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (d, i, d[:10] + 'T09:30:00', 'p2', 'mail', 'iCloud', ctx, 'X', 'x@example.org', None, None, None, mid, None, None, None, 0, 0, 0))
    for at, act, res, item in (('2027-03-16T10:00:00', 'reply_send', 'ok', 'a'), ('2027-03-17T10:00:00', 'done', 'done', 'b'),
                               ('2027-03-17T11:00:00', 'should_have_reached', 'ok', 'b'), ('2027-03-17T12:00:00', 'done', 'done', 'c'),
                               ('2027-03-17T13:00:00', 'reply_send', 'error: no', 'b')):
        db.execute('INSERT INTO actions VALUES (?,?,?,?,?,?,?,?)', (at, 'owner', act, res, item, None, None, None))
json.dump([{'id': 't1', 'text': 'Send Lee the quote', 'due': '2027-03-23', 'status': 'open', 'ctx': 'work', 'ref': {'kind': 'promise'}},
           {'id': 't2', 'text': 'Book the dentist', 'due': '2027-03-12', 'status': 'open', 'ctx': 'private'},
           {'id': 't3', 'text': 'Old report', 'due': '2027-03-10', 'status': 'open', 'ctx': 'work'}], open(os.path.join(state, 'tasks.json'), 'w'))
preps = [{'start': '2027-03-23T10:00', 'event': {'id': 'ev1'}, 'ctx': 'work', 'title': 'not passed on'},
         {'start': '2027-03-30T10:00', 'event': {'id': 'ev2'}, 'ctx': 'work'}]


class Bday:
    def due(self, people, day):
        return [{'name': 'Robin', 'turns': 40}] if day == datetime.date(2027, 3, 24) else []


trips = [{'title': 'Acme conference', 'start': '2027-03-25', 'end': '2027-03-26', 'ctx': 'work'},
         {'title': 'Lake weekend', 'start': '2027-03-27', 'end': '2027-03-28', 'ctx': 'private'}]
f = W.facts(['work'], FRI, st, state, preps=preps, people=[], birthdays=Bday(), trips=trips, calm_line='This month so far: …')
ok(f['handled'] == 2 and f['arrived'] == 2 and f['missed'] == 1, 'work: 2 handled, 2 arrived (a message counted once), 1 should have reached me')
ok(f['tasks'] == {'overdue': 1, 'due_next_week': 1}, 'work tasks: 1 overdue, 1 due next week (a private task is left out)')
ok([p['task_id'] for p in f['promises_due_next_week']] == ['t1'], 'promises due next week')
ok(f['preps_next_week'] == [{'start': '2027-03-23T10:00', 'event_id': 'ev1'}], 'preps next week: time and event id only, no title')
ok('birthdays_next_week' not in f and [t['title'] for t in f['trips_next_week']] == ['Acme conference'], 'work wrap: no birthdays, only work trips')
p = W.facts(['private'], datetime.date(2027, 3, 21), st, state, preps=preps, people=[], birthdays=Bday(), trips=trips)
ok(p['handled'] == 1 and p['birthdays_next_week'] == [{'day': '2027-03-24', 'name': 'Robin', 'turns': 40}], 'private wrap: its own count and the birthdays')
ok([t['title'] for t in p['trips_next_week']] == ['Lake weekend'], '… and private trips')

tl = json.load(open(os.path.join(state, 'tasks.json')))
json.dump(tl + [{'id': 'b1', 'type': 'bill', 'text': 'Pay Acme Power', 'due': '2027-03-24', 'status': 'open', 'ctx': 'work',
                 'bill': {'payee': 'Acme Power', 'amount': 1245.0, 'currency': 'DKK'}},
                {'id': 'b2', 'type': 'bill', 'text': 'Pay Lee Plumbing', 'due': '2027-04-20', 'status': 'open', 'ctx': 'work', 'bill': {'payee': 'Lee Plumbing'}}],
          open(os.path.join(state, 'tasks.json'), 'w'))
fb = W.facts(['work'], FRI, st, state, preps=[], people=[], birthdays=None, trips=[])
ok(fb['bills_due_next_week'] == [{'payee': 'Acme Power', 'amount': 1245.0, 'currency': 'DKK', 'due': '2027-03-24', 'task_id': 'b1'}],
   'bills due next week: payee, exact amount, due – a later bill left out')
json.dump(tl, open(os.path.join(state, 'tasks.json'), 'w'))

# the scheduler: which runs write a wrap, and the facts file they read
s = S.Scheduler(tmp, state, None, None, log=open(os.devnull, 'w'))
asked = []
s.wrap_facts = lambda worlds: asked.append(worlds) or {'worlds': worlds, 'handled': 3}
ok('WEEK WRAP for work' in s._wrap_note('week-wrap', {'worlds': ['work']}) and asked[-1] == ['work'], 'Friday work wrap: the note, and the facts for work')
ok(json.load(open(os.path.join(state, 'week-wrap.json')))['handled'] == 3, '… written to state/week-wrap.json')
ok('WEEK WRAP for private' in s._wrap_note('week-ahead', {'worlds': ['private']}), 'Sunday week-ahead: the private wrap')
ok(s._wrap_note('week-ahead', {'worlds': ['private'], 'wrap': False}) == '', '… unless the slot turned it off')
ok(s._wrap_note('digest-morning', {}) == '', 'other digests: no wrap')
ok('under 90 seconds' in W.prompt_note(['work']), 'the spoken wrap stays under 90 seconds')
ok(any(x['task'] == 'week-wrap' and x['worlds'] == ['work'] and x['days'] == [4] for x in S.DEFAULT['digests']), 'a new installation gets the Friday work wrap')

print('%d failed' % fails if fails else 'all passed')
sys.exit(1 if fails else 0)
