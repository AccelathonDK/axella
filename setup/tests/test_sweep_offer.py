#!/usr/bin/env python3
"""The sweep offered outside digest hours (sweep_offer.py) and the "In an hour" one-off sweep (schedule.py / scheduler.py):
the gap from the scheduler's own rules, once per gap, the learning question, the scope, and the one-off sweep that runs
by itself, survives a restart, can be cancelled and is skipped when a digest ran meanwhile. Invented schedules, dates
and counts only. Run: python3 setup/tests/test_sweep_offer.py"""
import datetime
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import schedule as SC  # noqa: E402
import scheduler as S  # noqa: E402
import sweep_offer as O  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def bad(fn, label):
    try:
        fn()
    except (O.Bad, SC.Bad):
        return ok(True, label)
    ok(False, label)


base = tempfile.mkdtemp(prefix='axtest-offer-')
state = os.path.join(base, 'state')
os.makedirs(state)
sched = SC.Schedule(state)
R = S.Scheduler(base, state, sched, lambda *a: None)
NEW = {'n': 3}
R.count_new = lambda since: (None, 'mail not checkable') if NEW['n'] is None else ({'mail': NEW['n']}, 'mail %d' % NEW['n'])
HOURS = {'days': [0, 1, 2, 3, 4], 'from': '08:00', 'to': '16:30'}
off = O.SweepOffer(state, R, sched, lambda: HOURS)


def cfg(digests):
    c = R.load()
    c['enabled'], c['digests'] = True, digests
    json.dump(c, open(os.path.join(state, 'scheduler.json'), 'w'))


def at(y, mo, d, h, mi):
    return datetime.datetime(y, mo, d, h, mi).astimezone()


def runs(*rs):
    json.dump({'runs': [{'id': rid, 'task': task, 'label': task, 'status': st, 'trigger': 'schedule', 'attempt': 1,
                         'started': a.isoformat(timespec='seconds'), 'ended': (a + datetime.timedelta(minutes=12)).isoformat(timespec='seconds')}
                        for rid, task, a, st in rs], 'slots': {}}, open(os.path.join(state, 'runs.json'), 'w'))


def sched_set(**kw):
    d = sched.load()
    d.update(kw)
    json.dump(d, open(os.path.join(state, 'schedule.json'), 'w'))


WEEKDAYS = [{'id': 'morning', 'task': 'digest-morning', 'time': '07:30', 'days': [0, 1, 2, 3, 4], 'enabled': True},
            {'id': 'afternoon', 'task': 'digest-afternoon', 'time': '15:30', 'days': [0, 1, 2, 3, 4], 'enabled': True},
            {'id': 'week', 'task': 'week-ahead', 'time': '20:30', 'days': [6], 'enabled': True}]
cfg(WEEKDAYS)
FRI, SAT, MON = (2027, 3, 12), (2027, 3, 13), (2027, 3, 15)

print('A day without digests')
runs(('r-fri', 'digest-afternoon', at(*FRI, 15, 30), 'ok'))
v = off.view(at(*SAT, 14, 0))
ok(v['show'] and v['kind'] == 'day-5' and v['count'] == 3 and v['gap'] == 'r-fri', 'Saturday, 3 new: the offer shows')
ok(v['text'] == 'No digest today. 3 new since yesterday 15:30 – sweep now?', 'its text: ' + str(v.get('text')))
ok(v['worlds'] == ['private', 'work'], 'digests not split into work and private: a full sweep')
NEW['n'] = 0
ok(not off.view(at(*SAT, 14, 0))['show'], 'nothing new: no offer')
NEW['n'] = None
ok(not off.view(at(*SAT, 14, 0))['show'], "a stream that can't be counted: no offer")
NEW['n'] = 1

print('Weekday gaps')
runs(('r-am', 'digest-morning', at(*MON, 7, 30), 'ok'))
ok(off.view(at(*MON, 15, 0))['why'] == 'a digest is due within the hour', '15:00 with the 15:30 digest due: no offer')
ok(off.view(at(*MON, 11, 0))['show'] and off.view(at(*MON, 11, 0))['kind'] == 'daytime', '11:00, between digests: offer')
runs(('r-pm', 'digest-afternoon', at(*MON, 15, 30), 'ok'))
ok(off.view(at(*MON, 17, 30))['why'] == 'a digest ran in the last 2 hours', '17:30, the 15:30 digest ended 15:42: no offer yet')
v = off.view(at(*MON, 18, 0))
ok(v['show'] and v['kind'] == 'evening' and v['text'] == 'Quiet evening. 1 new since 15:30 – sweep now?', 'evening: ' + str(v.get('text')))
runs(('r-pm', 'digest-afternoon', at(*MON, 15, 30), 'running'))
ok(not off.view(at(*MON, 18, 0))['show'], 'a digest running: no offer')

print('Once per gap')
runs(('r-pm', 'digest-afternoon', at(*MON, 15, 30), 'ok'))
ok(off.action({'act': 'dismiss', 'gap': 'r-pm'}, 'owner', at(*MON, 18, 0)) == {'dismissed': True}, 'Dismiss')
ok(off.view(at(*MON, 21, 0))['why'] == 'dismissed for this gap', '… no new offer in the same gap')
bad(lambda: off.action({'act': 'dismiss', 'gap': 'r-pm'}, 'owner', at(*MON, 21, 0)), 'acting on a closed offer is refused')
bad(lambda: off.action({'act': 'now', 'gap': '../x y'}, 'owner', at(*MON, 21, 0)), 'a bad gap id is refused')
bad(lambda: off.action({'act': 'run_anything', 'gap': 'r-pm'}, 'owner', at(*MON, 21, 0)), 'an unknown act is refused')

print('Learning: three dismissals of one kind')
TUE, WED, THU = (2027, 3, 16), (2027, 3, 17), (2027, 3, 18)
for i, day in enumerate((TUE, WED)):
    runs(('r-%d' % i, 'digest-afternoon', at(*day, 15, 30), 'ok'))
    v = off.view(at(*day, 19, 0))
    ok(v['show'] and not v['ask_stop'], 'evening %d: an ordinary offer' % (i + 2))
    off.action({'act': 'dismiss', 'gap': v['gap']}, 'owner', at(*day, 19, 0))
runs(('r-thu', 'digest-afternoon', at(*THU, 15, 30), 'ok'))
v = off.view(at(*THU, 19, 0))
ok(v['ask_stop'] and v['stop_text'] == 'Stop offering a sweep in the evening?', 'after 3 dismissals: ' + str(v.get('stop_text')))
r = off.action({'act': 'stop', 'gap': 'r-thu'}, 'owner', at(*THU, 19, 0))
ok(r['stopped'] == 'evening' and sched.load()['sweep_offer']['off_kinds'] == ['evening'], 'Stop: evenings switched off in Settings')
runs(('r-fri2', 'digest-afternoon', at(*FRI, 15, 30), 'ok'))
ok(off.view(at(*FRI, 19, 0))['why'] == 'not offered in the evening', '… no evening offer any more')
ok(off.view(at(*SAT, 14, 0))['show'], '… Saturdays still offered')
sched_set(sweep_offer={'on': True, 'off_kinds': []})
ok(not off.view(at(*FRI, 19, 0))['ask_stop'], 'removed in Settings: offered again, and never asked again')

print('Keep offering')
st = json.load(open(os.path.join(state, 'sweep-offer.json')))
st['dismiss'] = {'day-5': 3}
json.dump(st, open(os.path.join(state, 'sweep-offer.json'), 'w'))
v = off.view(at(*SAT, 14, 0))
ok(v['ask_stop'] and v['stop_text'] == 'Stop offering a sweep on Saturdays?', 'Saturdays: the question once')
off.action({'act': 'keep', 'gap': v['gap']}, 'owner', at(*SAT, 14, 0))
v = off.view(at(*SAT, 14, 0))
ok(v['show'] and not v['ask_stop'] and 'day-5' not in sched.load()['sweep_offer']['off_kinds'], 'Keep offering: the offer stays, the question is gone')

print('Paused, off, split')
sched_set(vacation={'on': True, 'mode': 'urgent', 'from': None, 'until': None})
ok(off.view(at(*SAT, 14, 0))['why'] == 'paused', 'vacation: no offer')
sched_set(vacation={'on': False, 'mode': 'urgent', 'from': None, 'until': None}, off_dates=['2027-03-13'], off_work_only=True)
v = off.view(at(*SAT, 14, 0))
ok(v['show'] and v['worlds'] == ['private'] and v['text'].endswith('private sweep now?'), 'a work-paused day off: a private sweep')
sched_set(off_dates=[], off_work_only=False, sweep_offer={'on': False, 'off_kinds': []})
ok(off.view(at(*SAT, 14, 0))['why'] == 'off in Settings', 'switched off in Settings: no offer')
sched_set(sweep_offer={'on': True, 'off_kinds': []})
cfg([dict(WEEKDAYS[0], worlds=['work']), WEEKDAYS[1], WEEKDAYS[2]])
ok(off.view(at(*SAT, 14, 0))['worlds'] == ['private'], 'digests split, outside work hours: a private sweep')
ok(O.scope(datetime.datetime(*MON, 10, 0), {}, R.load()['digests'], HOURS) == ['private', 'work'], '… inside work hours: both')
cfg(WEEKDAYS)

print('Now and In an hour')
v = off.view(at(*SAT, 14, 0))
r = off.action({'act': 'now', 'gap': v['gap']}, 'owner', at(*SAT, 14, 0))
ok(sched.load()['sweep_request']['worlds'] == ['private', 'work'] and 'pending_since' in r, 'Now: the usual sweep request, with its scope')
ok(off.view(at(*SAT, 14, 0))['why'] == 'a sweep is requested', '… no offer while it is requested')
sched_set(sweep_request=None)
r = off.action({'act': 'later', 'gap': v['gap']}, 'owner', at(*SAT, 14, 0))
lt = sched.later()
ok(lt and r['at'] == lt['at'] and abs((datetime.datetime.fromisoformat(lt['at']) - datetime.datetime.fromisoformat(lt['asked'])).total_seconds() - 3600) < 2,
   'In an hour: a one-off sweep 60 min after asking')
ok(off.view(at(*SAT, 14, 0))['why'] == 'a sweep is planned', '… no offer while it is planned')
ok(SC.Schedule(state).later() == lt, '… kept in state/schedule.json (survives a restart)')
off.action({'act': 'undo'}, 'owner')
ok(sched.later() is None, 'Undo cancels it')

print('The one-off sweep runs by itself')
R2 = S.Scheduler(base, state, SC.Schedule(state), lambda *a: None)
R2.sweep_scope = lambda now: ['private']
asked = at(*SAT, 14, 0)
sched_set(sweep_later={'at': (asked + datetime.timedelta(hours=1)).isoformat(), 'asked': asked.isoformat(), 'by': 'owner'})
runs(('r-fri', 'digest-afternoon', at(*FRI, 15, 30), 'ok'))
d = R2._load_runs()
with S.LOCK:            # as in _tick
    R2._later_sweep(d, at(*SAT, 14, 30))
ok(not R2.queue and sched.later(), 'not before its time')
with S.LOCK:
    R2._later_sweep(d, at(*SAT, 15, 1))
ok(len(R2.queue) == 1 and R2.queue[0]['task'] == 'on-demand' and R2.queue[0]['trigger'] == 'later' and R2.queue[0]['worlds'] == ['private']
   and R2.queue[0]['label'].startswith('Sweep · ') and R2.queue[0]['label'].endswith('(you asked)'), 'at its time: queued, scope decided now')
ok(sched.later() is None, '… and taken off the schedule (once)')
R2.queue.clear()
sched_set(sweep_later={'at': (asked + datetime.timedelta(hours=1)).isoformat(), 'asked': asked.isoformat(), 'by': 'owner'})
runs(('r-sweep', 'on-demand', at(*SAT, 14, 20), 'ok'))
d = R2._load_runs()
with S.LOCK:
    R2._later_sweep(d, at(*SAT, 15, 1))
ok(not R2.queue and d['runs'][-1]['status'] == 'skipped' and d['runs'][-1]['reason'] == 'skipped – a digest ran meanwhile',
   'a sweep ran in between: skipped, and said so on Runs')
ok(S.Scheduler._resume_job({'task': 'on-demand', 'attempt': 1, 'trigger': 'later', 'started': at(*SAT, 15, 1).isoformat()}, at(*SAT, 15, 5)) is not None,
   'a one-off sweep cut off by a restart runs again')
sched_set(sweep_later={'at': at(*SAT, 16, 0).isoformat(), 'asked': at(*SAT, 15, 0).isoformat(), 'by': 'owner'})
ok(R2.overview()['later']['at'] == at(*SAT, 16, 0).isoformat(), 'Runs lists it')
sched.action('sweep_later_cancel', {}, 'owner')
ok(R2.overview()['later'] is None, '… with Cancel')
bad(lambda: sched.action('sweep_request', {'worlds': ['work', 'elsewhere']}, 'owner'), 'a sweep request with an unknown world is refused')
bad(lambda: sched.action('schedule_set', {'sweep_offer_off_kinds': ['tuesday-ish']}, 'owner'), 'an unknown offer exception is refused')

print()
print('all ok' if not fails else '%d failed' % fails)
sys.exit(1 if fails else 0)
