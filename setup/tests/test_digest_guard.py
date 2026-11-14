#!/usr/bin/env python3
"""The "digest missing" alert follows Settings → Schedule (Scheduler.due_digests): no warning for a slot that isn't set up
that day, is switched off, falls on a vacation day, or is work-only on a paused work day; a moved time is watched at its
new time. Invented schedules only. Run: python3 setup/tests/test_digest_guard.py"""
import datetime
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import digest_guard as G  # noqa: E402
import scheduler as S  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


class Sched:                                    # stands in for schedule.Schedule
    def __init__(self):
        self.st = {'digests': True, 'urgent': True, 'reason': None}

    def status(self, now=None):
        return dict(self.st)


base = tempfile.mkdtemp(prefix='axtest-guard-')
state, digests = os.path.join(base, 'state'), os.path.join(base, 'digests')
os.makedirs(state)
os.makedirs(digests)
sch = Sched()
R = S.Scheduler(base, state, sch, lambda *a: None)


def cfg(digests_cfg, enabled=True):
    c = R.load()
    c['enabled'], c['digests'] = enabled, digests_cfg
    json.dump(c, open(os.path.join(state, 'scheduler.json'), 'w'))


SAT, MON = datetime.datetime(2027, 3, 13, 8, 45), datetime.datetime(2027, 3, 15, 8, 45)   # a Saturday and a Monday
sf = os.path.join(state, 'guard.json')


def run(now):
    sent = []
    G.check(now, digests, sf, sent.append, R.due_digests)
    return sent


cfg([{'id': 'morning', 'task': 'digest-morning', 'time': '07:30', 'days': [0, 1, 2, 3, 4], 'enabled': True}])
ok(run(SAT) == [], 'a weekday-only morning digest: no alert on Saturday')
sent = run(MON)
ok(len(sent) == 1 and '07:30' in sent[0]['title'] and 'Runs in Axella' in sent[0]['body'] and 'Claude' not in sent[0]['body'],
   'Monday, nothing written by 08:45: one alert, pointing at Runs: ' + (sent[0]['body'] if sent else '–'))
ok(run(MON) == [], '… and only once per slot')

os.remove(sf)
cfg([{'id': 'morning', 'task': 'digest-morning', 'time': '07:30', 'days': [0, 1, 2, 3, 4], 'enabled': False}])
ok(run(MON) == [], 'a slot switched off: no alert')

cfg([{'id': 'morning', 'task': 'digest-morning', 'time': '08:00', 'days': [0, 1, 2, 3, 4, 5, 6], 'enabled': True}])
ok(run(SAT) == [], 'moved to 08:00: not yet at 08:45')
ok(len(run(SAT.replace(hour=9, minute=5))) == 1, '… alert at 09:05')

os.remove(sf)
open(os.path.join(digests, '2027-03-13-0800.md'), 'w').write('x')
t = datetime.datetime(2027, 3, 13, 7, 55).timestamp()
os.utime(os.path.join(digests, '2027-03-13-0800.md'), (t, t))
ok(run(SAT.replace(hour=9, minute=5)) == [], 'a digest written around the slot: no alert')

os.remove(os.path.join(digests, '2027-03-13-0800.md'))
sch.st = {'digests': False, 'urgent': True, 'reason': 'Vacation mode – urgent only'}
ok(run(SAT.replace(hour=9, minute=5)) == [], 'vacation / day off: no alert')
sch.st = {'digests': True, 'urgent': True, 'reason': None, 'work_paused': True}
cfg([{'id': 'morning', 'task': 'digest-morning', 'time': '08:00', 'days': [5], 'enabled': True, 'worlds': ['work']}])
ok(run(SAT.replace(hour=9, minute=5)) == [], 'a work-only slot on a paused work day: no alert')
sch.st = {'digests': True, 'urgent': True, 'reason': None}
cfg([{'id': 'morning', 'task': 'digest-morning', 'time': '08:00', 'days': [5], 'enabled': True}], enabled=False)
ok(run(SAT.replace(hour=9, minute=5)) == [], 'scheduled digests off altogether: no alert')

print()
print('all ok' if not fails else '%d failed' % fails)
sys.exit(1 if fails else 0)
