#!/usr/bin/env python3
"""Search and Insights polish (user test 6, item 5): digest roll-up lines never show as search hits; this week is
compared with the whole of last week, also when history starts on its Tuesday; a calendar is not a topic.
Fictional data. Run: python3 setup/tests/test_search_insights.py"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import store  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


for h in ('Noise (P4): 12 newsletters', 'Messages – nothing waiting on you', 'Messages – nothing else open',
          'WhatsApp – nothing new since 07:30', 'Family messages – nothing open', 'Rest of today – nothing left',
          'Messages – Kim and the family group, nothing else new', 'WhatsApp – 3 chats, nothing open',
          'WhatsApp – two groups, nothing to answer', 'Family chat – 2 chats, nothing open',
          'Rest of today: nothing left. Tomorrow 1 meeting at 09:00', 'Rest of today nothing more after 18:00'):
    ok(bool(store.SUMMARY_RE.match(h)), 'roll-up hidden: ' + h)
for h in ('Sam Rivera – nothing to add, approved the quote', 'Lee: nothing works on the laptop', 'Invoice 42 – nothing due',
          'Lee Chen – the server is down, nothing open yet works', 'Robin – asks whether anything is new'):
    ok(not store.SUMMARY_RE.match(h), 'real item kept: ' + h)
a, b, pa, pb = store.Store.period('week', datetime.date(2026, 11, 3))
ok((a, b, pa, pb) == ('2026-11-02', '2026-11-03', '2026-10-26', '2026-11-01'), 'this week (Mon–Tue) vs the whole of last week')

# Insights on a small fictional store: history from last week's Tuesday still compares; no calendar as a topic
import tempfile  # noqa: E402
st = tempfile.mkdtemp()
S = store.Store(tempfile.mkdtemp(), st)
S.init()
today = datetime.date.today()
mon = today - datetime.timedelta(days=today.weekday())
last_tue = (mon - datetime.timedelta(days=6)).isoformat()
with S._db() as db:
    db.execute("INSERT INTO digests VALUES ('d0', 'digest', 't', ?, '', 1)", (last_tue + 'T07:30:00+01:00',))
    rows = [('d0', 'i1', last_tue + 'T07:30:00+01:00', 'p2', 'mail', 'lee@clientb.example', 'Lee Chen', 'Kitchen project', 'Quote'),
            ('d1', 'i2', today.isoformat() + 'T07:30:00+01:00', 'p2', 'mail', 'lee@clientb.example', 'Lee Chen', 'Kitchen project', 'Quote again'),
            ('d1', 'i3', today.isoformat() + 'T07:30:00+01:00', 'cal', 'calendar', None, None, 'Acme calendar', 'Meeting')]
    for d, i, g, sec, ch, addr, name, topic, head in rows:
        db.execute('INSERT INTO items (digest, id, generated, section, channel, from_address, from_name, topic, headline) '
                   'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (d, i, g, sec, ch, addr, name, topic, head))
ins = S.insights('week', people_only=False)
ok(ins['compare'] is True and ins['prev_partial'] is True, 'history from last Tuesday: compared with last week (partial)')
ok(not any('calendar' in t['topic'].lower() for t in ins.get('topics') or []), 'a calendar is not listed as a topic')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
