#!/usr/bin/env python3
"""A digest the action-service restart interrupted is run again (attempt 2) with the same scope – not left failed.
Invented data only. Run: python3 setup/tests/test_scheduler_resume.py"""
import datetime
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import scheduler as S  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


NOW = datetime.datetime(2027, 3, 15, 11, 40, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
run = {'id': '20270315-113700-digest-midday', 'task': 'digest-midday', 'label': 'Midday digest', 'slot': '2027-03-15 11:30 s2',
       'trigger': 'schedule', 'attempt': 1, 'started': '2027-03-15T11:37:00+01:00', 'job': {'worlds': ['work'], 'wrap': False}}
j = S.Scheduler._resume_job(run, NOW)
ok(j and j['task'] == 'digest-midday' and j['attempt'] == 2 and j['trigger'] == 'retry' and j['slot'] == run['slot'],
   'an interrupted scheduled digest is queued again as attempt 2, same slot')
ok(j['worlds'] == ['work'] and j['wrap'] is False and j['retry_of'] == run['id'], '… with the same scope and wrap choice')
ok(S.Scheduler._resume_job(dict(run, attempt=2), NOW) is None, 'a second attempt is not repeated')
ok(S.Scheduler._resume_job(dict(run, started='2027-03-15T09:00:00+01:00'), NOW) is None, 'not when it started more than 90 minutes ago')
ok(S.Scheduler._resume_job(dict(run, task='p0-check'), NOW) is None, 'urgent checks are not repeated (the next one comes soon)')
ok(S.Scheduler._resume_job(dict(run, task='compose', trigger='manual'), NOW) is None, 'only digests')
ok(S.Scheduler._resume_job(dict(run, job=None), NOW)['task'] == 'digest-midday', 'a run from before this change (no "job") is repeated too')
import json  # noqa: E402
import tempfile  # noqa: E402
base = tempfile.mkdtemp()
state = os.path.join(base, 'state')
os.makedirs(state)
started = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
rf = os.path.join(state, 'runs.json')
json.dump({'runs': [dict(run, started=started, status='running')], 'slots': {}}, open(rf, 'w'))
before = open(rf).read()
R = S.Scheduler(base, state, None, lambda *a: None)
ok(open(rf).read() == before and not R.queue, 'creating the scheduler (a test importing axella-actions) never touches runs.json')
R.recover()
d = json.load(open(rf))
ok(d['runs'][0]['status'] == 'failed' and 'running it again' in d['runs'][0]['reason'] and len(R.queue) == 1 and R.queue[0]['attempt'] == 2,
   'recover() at service start: the interrupted digest is failed and queued again')
mt = os.path.getmtime(rf)
R2 = S.Scheduler(base, state, None, lambda *a: None)
R2.recover()
ok(os.path.getmtime(rf) == mt and not R2.queue, 'nothing running: recover() writes nothing and queues nothing')
ok(not [f for f in os.listdir(state) if f.endswith('.tmp')], 'no temporary file left behind')

print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
