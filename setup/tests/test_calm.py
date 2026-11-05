#!/usr/bin/env python3
"""Calm in numbers (setup/calm.py): held vs broke through, digests read and heard, reply time per world, work outside
work hours, "should have reached me", drafts sent with little editing, promises kept – this month and last.
Invented data only. Run: python3 setup/tests/test_calm.py"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import calm as C  # noqa: E402
from store import Store  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


ok(C.month_range('2027-02') == ('2027-02-01', '2027-02-28') and C.prev_month('2027-01') == '2026-12', 'months')
H = {'days': [0, 1, 2, 3, 4], 'from': '08:00', 'to': '17:00'}
ok(C.outside('2027-03-16T20:00:00', H) and C.outside('2027-03-20T10:00:00', H) and not C.outside('2027-03-16T10:00:00', H),
   'outside work hours: evenings and weekends')

tmp = tempfile.mkdtemp()
state = os.path.join(tmp, 'state')
os.makedirs(state)
st = Store(tmp, state)
st.init()
st._world = lambda: (lambda item_id, addr, context, account: context or 'private')
rows = [  # digest, id, generated, section, context, message_id, first_seen
    ('2027-03-16-0930', 'a', '2027-03-16T09:30:00', 'p1', 'work', 'm-a', '2027-03-16T09:30:00'),
    ('2027-03-16-0930', 'b', '2027-03-16T09:30:00', 'p3', 'private', 'm-b', '2027-03-16T09:30:00'),
    ('2027-03-16-1015-p0', 'c', '2027-03-16T10:15:00', 'p0', 'private', 'm-c', '2027-03-16T10:15:00'),
    ('2027-03-16-1130', 'c', '2027-03-16T11:30:00', 'p0', 'private', 'm-c', '2027-03-16T10:15:00'),   # same message again
    ('2027-03-16-2000', 'd', '2027-03-16T20:00:00', 'p2', 'work', 'm-d', '2027-03-16T20:00:00'),       # work, in the evening
    ('2027-03-16-2000', 'e', '2027-03-16T20:00:00', 'cal', 'work', None, '2027-03-16T20:00:00'),       # calendar: not a message
    ('2027-02-10-0930', 'f', '2027-02-10T09:30:00', 'p2', 'work', 'm-f', '2027-02-10T09:30:00'),
]
with st._db() as db:
    for r in rows:
        db.execute('INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (r[0], r[1], r[2], r[3], 'mail', 'iCloud', r[4], 'X', 'x@example.org', None, None, None, r[5], None, None, r[6], 0, 0, 0))
    for n, g in (('2027-03-16-0930', '2027-03-16T09:30:00'), ('2027-03-16-1015-p0', '2027-03-16T10:15:00'),
                 ('2027-03-16-1130', '2027-03-16T11:30:00'), ('2027-03-16-2000', '2027-03-16T20:00:00'), ('2027-02-10-0930', '2027-02-10T09:30:00')):
        db.execute('INSERT INTO digests VALUES (?,?,?,?,?,?)', (n, 'digest', 'T', g, '', 1))
C.mark_read(state, '2027-03-16-0930', 'seen')
C.mark_read(state, '2027-03-16-0930', 'listened')
C.mark_read(state, '2027-03-16-1130', 'seen')
ok(not C.mark_read(state, '2027-03-16-0930', 'seen'), 'a digest counts as read once')
log = [
    {'at': '2027-03-16T10:30:00+01:00', 'action': 'reply_send', 'result': 'ok', 'item': 'a', 'edit': 'none'},
    {'at': '2027-03-16T21:00:00+01:00', 'action': 'reply_send', 'result': 'ok', 'item': 'd', 'edit': 'much'},
    {'at': '2027-03-16T12:15:00+01:00', 'action': 'sms_send', 'result': 'ok', 'item': 'c'},
    {'at': '2027-03-16T12:00:00+01:00', 'action': 'should_have_reached', 'result': 'ok', 'item': 'b'},
    {'at': '2027-03-17T09:00:00+01:00', 'action': 'reply_send', 'result': 'error: no', 'item': 'b'},
]
with open(os.path.join(state, 'actions.log'), 'w') as f:
    f.write('\n'.join(json.dumps(e) for e in log) + '\n')
json.dump([{'id': 't1', 'text': 'Send Lee the quote', 'due': '2027-03-18', 'status': 'done', 'done': '2027-03-17T10:00:00+01:00', 'ref': {'kind': 'promise'}},
           {'id': 't2', 'text': 'Call Kim', 'due': '2027-03-10', 'status': 'done', 'done': '2027-03-12T10:00:00+01:00', 'ref': {'kind': 'promise'}},
           {'id': 't3', 'text': 'Water the plants', 'due': '2027-03-10', 'status': 'done', 'done': '2027-03-09T10:00:00+01:00'}],
          open(os.path.join(state, 'tasks.json'), 'w'))

c = C.calm(st, state, '2027-03', H)
t = c['this']
ok(t['held'] == 3 and t['broke_through'] == 1, 'held 3 (a, b, d), broke through 1 (c) – a pushed message counts once')
ok(t['digests'] == 3 and t['read'] == 2 and t['listened'] == 1, 'digests delivered 3 (not the P0 file), read 2, heard 1')
ok(t['reply_minutes'] == {'work': 60, 'private': 120} and t['replies'] == {'work': 2, 'private': 1},
   'median reply time per world (a failed send does not count)')
ok(t['work_outside_hours'] == 1, 'one work item surfaced outside work hours (the calendar entry is not a message)')
ok(t['missed'] == 1, '"should have reached me" counted')
ok(t['drafts_sent'] == 2 and t['drafts_light'] == 1, 'drafts: 2 sent, 1 with little or no editing')
ok(t['promises_due'] == 2 and t['promises_kept'] == 1, 'promises: 1 of 2 kept on time; an ordinary task is not a promise')
ok(c['last']['held'] == 1 and c['last']['month'] == '2027-02', 'last month for comparison')
ok(C.one_line(c).startswith('This month so far: 3 messages waited for a digest, 1 broke through'), 'the week wrap\'s one line')

# the send's edit bucket and the quiet "digest seen" (axella-actions.py)
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
ok(A.edit_bucket('Hi Lee, Friday 10:00 works for me.', 'Hi Lee, Friday 10:00 works for me.') == 'none', 'sent as drafted: "none"')
ok(A.edit_bucket('Hi Lee, Friday 10:00 works for me.', 'Hi Lee, Friday 10:30 works for me!') == 'little', 'a small change: "little"')
ok(A.edit_bucket('Hi Lee, Friday 10:00 works for me.', 'Sorry Lee, next week instead – Monday?') == 'much', 'rewritten: "much"')
ok(A.edit_bucket(None, 'x') is None, 'no draft: no bucket')
ok('digest_seen' in A.QUIET, '"digest seen" is bookkeeping, not an activity log line')

print('%d failed' % fails if fails else 'all passed')
sys.exit(1 if fails else 0)
