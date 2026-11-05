#!/usr/bin/env python3
"""Protect your blocks (setup/blocks.py): free-block finding (overlaps, all-day, free and tentative events), at most one
suggestion a day, work hours and the minimum block, "Don't suggest for this day", the digest line (morning and Sunday,
work world only) and Your time. Invented events only. Run: python3 setup/tests/test_blocks.py"""
import datetime
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import blocks as B  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


TUE = datetime.date(2027, 3, 9)            # a Tuesday


def ev(start, end, day=TUE, **kw):
    return dict({'title': 'Meeting', 'start': '%sT%s:00' % (day, start), 'end': '%sT%s:00' % (day, end), 'all_day': False,
                 'availability': 'busy', 'ctx': 'work', 'attendees': 3}, **kw)


FULL = [ev('09:00', '10:30'), ev('10:00', '11:00'), ev('11:00', '12:30'), ev('15:00', '16:00'), ev('16:00', '17:00')]
fb = B.free_blocks(FULL, TUE)
ok([(a.strftime('%H:%M'), b.strftime('%H:%M')) for a, b in fb] == [('12:30', '15:00')], 'free blocks: overlapping meetings merged, inside work hours')
ok(B.free_blocks(FULL + [ev('13:00', '14:00', availability='free')], TUE) == fb, 'a "free" event doesn\'t block')
ok(len(B.free_blocks(FULL + [ev('13:00', '13:30', availability='tentative')], TUE)) == 2, 'a tentative one does')
ok(B.free_blocks(FULL + [dict(ev('00:00', '00:00'), all_day=True, availability='free', end='2027-03-10T00:00:00')], TUE) == fb, 'an all-day free event (a birthday) doesn\'t')
s = B.suggestion(FULL, TUE)
ok(s == {'date': '2027-03-09', 'start': '12:30', 'end': '14:30', 'text': 'Tuesday has only one free 2-hour block left. Hold 12:30–14:30?'},
   'a busy Tuesday with one block left: one suggestion, inside work hours, of the minimum length (%s)' % (s and s['text']))
ok(B.suggestion(FULL, TUE, minutes=180) is None, 'no block of 3 hours: nothing to hold')
ok(B.suggestion([ev('09:00', '10:00'), ev('11:00', '14:00'), ev('15:00', '17:00')], TUE, minutes=60) is None, 'two 1-hour blocks left: not the last one – no suggestion')
ok(B.suggestion([ev('09:00', '10:00')], TUE) is None, 'a quiet day: no suggestion')
ok(B.suggestion([dict(e, date=None) for e in FULL] + [dict(ev('00:00', '00:00'), all_day=True, availability='busy', end='2027-03-10T00:00:00')], TUE) is None,
   'out of office (all-day busy): no suggestion')
SAT = datetime.date(2027, 3, 13)
ok(B.suggestion([ev(a, b, SAT) for a, b in (('09:00', '12:30'), ('15:00', '17:00'))], SAT) is None, 'never on a day off')
ok(B.suggestion(FULL, TUE, hours={'days': [0, 1, 2, 3, 4], 'from': '08:00', 'to': '16:00'})['end'] == '14:30' and
   B.suggestion(FULL, TUE, hours={'days': [0, 2, 3, 4], 'from': '09:00', 'to': '17:00'}) is None, 'work hours and workdays from the setting')
late = B.suggestion(FULL, TUE, now=datetime.datetime(2027, 3, 9, 13, 10))
ok(late is None, 'after the block has started: no longer offered')
ok(B.suggestion(FULL, TUE, never={'2027-03-09'}) is None, '"Don\'t suggest for this day" is respected')

st = tempfile.mkdtemp()
S = B.Blocks(st)
WED = TUE + datetime.timedelta(days=1)
both = FULL + [ev(a, b, WED) for a, b in (('09:00', '12:00'), ('14:30', '17:00'))]
p = S.pick(both, [TUE, WED])
ok(p['date'] == '2027-03-09', 'at most one suggestion: the first busy day')
S.mark('2027-03-09', 'shown')
ok(S.pick(both, [TUE, WED])['date'] == '2027-03-10', 'shown once: not again that day – the next busy day is offered')
S.mark('2027-03-10', 'never')
ok(S.pick(both, [TUE, WED]) is None and '2027-03-10' in S.load()['never'], 'Don\'t suggest for this day')
try:
    S.settings({'minutes': 45})
    ok(False, 'block length: 1, 1½, 2 or 3 hours')
except B.Bad:
    ok(True, 'block length: 1, 1½, 2 or 3 hours')
ok(S.settings({'minutes': 90, 'calendar': 'Work', 'name': ''}, calendars=['Work'])['name'] == 'Focus', 'the event name defaults to "Focus"')

yt = B.your_time(FULL + [ev('09:00', '10:00', WED, ctx='private', title='Dentist', attendees=0)], datetime.date(2027, 3, 8))
ok(yt['meeting_hours'] == {'work': 5.5, 'private': 0} and len(yt['days']) == 5, 'Your time: hours in meetings (own blocks not counted), workdays')
ok({'date': '2027-03-09', 'longest': 150} in yt['days'] and yt['no_block'] == [] and
   B.your_time(FULL, datetime.date(2027, 3, 8), minutes=180)['no_block'] == ['2027-03-09'], '… the longest free block, and days with none of the minimum length')

# ---- the digest line
dd = tempfile.mkdtemp()
S2 = B.Blocks(tempfile.mkdtemp())
for nm, scope in (('2027-03-09-0730.json', None), ('2027-03-09-1130.json', None), ('2027-03-08-0730.json', ['private'])):
    json.dump({'items': [], 'generated': nm, **({'scope': scope} if scope else {})}, open(os.path.join(dd, nm), 'w'))
S2.add_to_digest(dd, '2027-03-09-0730.json', lambda a, b: FULL, now=datetime.datetime(2027, 3, 9, 7, 30))
it = json.load(open(os.path.join(dd, '2027-03-09-0730.json')))['items']
ok(len(it) == 1 and it[0]['link'] == 'focus' and it[0]['focus'] == {'date': '2027-03-09', 'start': '12:30', 'end': '14:30'}, 'the morning digest gets one line with Hold it')
S2.add_to_digest(dd, '2027-03-09-0730.json', lambda a, b: FULL)
ok(len(json.load(open(os.path.join(dd, '2027-03-09-0730.json')))['items']) == 1, '… once')
S2.add_to_digest(dd, '2027-03-09-1130.json', lambda a, b: FULL)
ok(json.load(open(os.path.join(dd, '2027-03-09-1130.json')))['items'] == [], 'never in the midday digest')
S2.add_to_digest(dd, '2027-03-08-0730.json', lambda a, b: FULL)
ok(json.load(open(os.path.join(dd, '2027-03-08-0730.json')))['items'] == [], 'only in a digest that covers the work world')
nm = '2027-03-07-2030.json'
json.dump({'items': []}, open(os.path.join(dd, nm), 'w'))
S3 = B.Blocks(tempfile.mkdtemp())
S3.add_to_digest(dd, nm, lambda a, b: both)
w = json.load(open(os.path.join(dd, nm)))['items']
ok(len(w) == 1 and w[0]['focus']['date'] == '2027-03-09', 'the Sunday week-ahead: one suggestion for the week')
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
