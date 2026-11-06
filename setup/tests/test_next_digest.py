#!/usr/bin/env python3
"""The next digest (scheduler.Scheduler.next_digest) for the line at the top of Today: the same rules the clock fires
by – the slots, vacation and days off, a work-only slot on a paused work day. Invented schedule.
Run: python3 setup/tests/test_next_digest.py"""
import datetime
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import scheduler  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


class Sched:
    """schedule.Schedule's status(at) – off on the dates in `off`, work paused on the dates in `work_off`."""
    def __init__(self):
        self.off, self.work_off = set(), set()

    def status(self, now=None):
        day = now.date().isoformat()
        if day in self.off:
            return {'digests': False, 'urgent': True, 'reason': 'Day off', 'vacation_until': None}
        return {'digests': True, 'urgent': True, 'reason': None, 'vacation_until': None, 'work_paused': day in self.work_off}


d = tempfile.mkdtemp()
WD = [0, 1, 2, 3, 4]
json.dump({'enabled': True, 'digests': [
    {'id': 'morning', 'task': 'digest-morning', 'label': 'Morning digest', 'time': '07:30', 'days': WD, 'enabled': True},
    {'id': 'afternoon', 'task': 'digest-afternoon', 'label': 'Afternoon digest', 'time': '15:30', 'days': WD, 'enabled': True, 'worlds': ['work']},
    {'id': 'week', 'task': 'week-ahead', 'label': 'Sunday week-ahead', 'time': '20:30', 'days': [6], 'enabled': True}]},
    open(os.path.join(d, 'scheduler.json'), 'w'))
S = Sched()
R = scheduler.Scheduler(d, d, S, lambda *a: None)
at = lambda y, m, dd, h, mi: datetime.datetime(2030, m, dd, h, mi)
# 2030-01-07 is a Monday
n = R.next_digest(at(2030, 1, 7, 6, 0))
ok(n == {'at': '2030-01-07T07:30', 'label': 'Morning digest', 'worlds': ['private', 'work']}, 'before the morning digest: today 07:30')
ok(R.next_digest(at(2030, 1, 7, 7, 30))['at'] == '2030-01-07T15:30', 'at 07:30 sharp the morning one is under way: the next is 15:30')
ok(R.next_digest(at(2030, 1, 7, 11, 0))['worlds'] == ['work'], 'a work-only slot says so')
ok(R.next_digest(at(2030, 1, 7, 18, 0))['at'] == '2030-01-08T07:30', 'after the last one: tomorrow morning')
ok(R.next_digest(at(2030, 1, 11, 18, 0)) == {'at': '2030-01-13T20:30', 'label': 'Sunday week-ahead', 'worlds': ['private', 'work']},
   'Friday evening: the Sunday week-ahead')
S.off = {'2030-01-08', '2030-01-09'}
ok(R.next_digest(at(2030, 1, 7, 18, 0))['at'] == '2030-01-10T07:30', 'days off are skipped')
S.off, S.work_off = set(), {'2030-01-07'}
ok(R.next_digest(at(2030, 1, 7, 11, 0))['at'] == '2030-01-08T07:30', 'a work-only slot on a paused work day is skipped')
S.off = {(datetime.date(2030, 1, 7) + datetime.timedelta(days=k)).isoformat() for k in range(40)}
ok(R.next_digest(at(2030, 1, 7, 6, 0)) is None, 'nothing in the next 31 days: none')
S.off = set()
c = json.load(open(os.path.join(d, 'scheduler.json')))
c['enabled'] = False
json.dump(c, open(os.path.join(d, 'scheduler.json'), 'w'))
ok(R.next_digest(at(2030, 1, 7, 6, 0)) is None, 'scheduled digests off: none')
src = open(os.path.join(HERE, 'axella-actions.py'), encoding='utf-8').read()
ok("'next': nxt" in src, 'GET schedule sends it as "next"')

print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
