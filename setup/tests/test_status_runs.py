#!/usr/bin/env python3
"""System status and run counts (user test 6, items 1, 2 and 5): the newest digest wins whatever the list order, an
overdue slot turns the row to warn, runs are kept by age not count, and "What leaves my home" groups runs by kind
(no recipient in a label) with failed runs counted. Fictional data. Run: python3 setup/tests/test_status_runs.py"""
import datetime
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
import scheduler  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


old = {'task': 'digest-morning', 'started': '2026-11-02T07:30:00+01:00', 'status': 'ok'}
new = {'task': 'on-demand', 'started': '2026-11-03T19:13:00+01:00', 'status': 'ok'}
mid = {'task': 'digest-afternoon', 'started': '2026-11-03T15:30:00+01:00', 'status': 'ok'}
other = {'task': 'compose', 'started': '2026-11-03T20:00:00+01:00', 'status': 'ok'}
ok(A.latest_digest([old, mid, new, other]) is new, 'oldest-first list (runs.json): the newest digest')
ok(A.latest_digest([other, new, mid, old]) is new, 'newest-first list (overview): the newest digest')
ok(A.latest_digest([other]) is None, 'no digest at all: None')

today = [{'time': '07:30', 'task': 'digest-morning', 'status': 'ok'}, {'time': '11:30', 'task': 'digest-midday', 'status': 'due'},
         {'time': '15:30', 'task': 'digest-afternoon', 'status': 'planned'}]
ok([t['time'] for t in A.overdue_digests(today, datetime.datetime(2026, 11, 3, 12, 30))] == ['11:30'], '11:30 not run at 12:30: overdue')
ok(A.overdue_digests(today, datetime.datetime(2026, 11, 3, 11, 50)) == [], 'within the grace period: not yet overdue')

# runs kept by age (30 days), not by count
st = tempfile.mkdtemp()
s = scheduler.Scheduler(tempfile.mkdtemp(), st, None, lambda *a: None)
now = datetime.datetime.now().astimezone()
runs = [{'id': 'r%d' % i, 'task': 'ask', 'started': (now - datetime.timedelta(hours=i)).isoformat()} for i in range(500)]
runs.append({'id': 'ancient', 'task': 'ask', 'started': (now - datetime.timedelta(days=31)).isoformat()})
s._save_runs({'runs': sorted(runs, key=lambda r: r['started']), 'slots': {}})
kept = s._load_runs()['runs']
ok(len(kept) == 500 and all(r['id'] != 'ancient' for r in kept), '500 runs in 21 days all kept; 31 days old dropped')
ok(scheduler.RUNS_CAP >= 3000, 'hard cap well above a month of runs')

# What leaves my home: grouped by kind, failed counted, no addresses
week = [{'task': 'compose', 'label': 'Compose mail to lee@clientb.example', 'started': now.isoformat(), 'status': 'ok'},
        {'task': 'compose', 'label': 'Compose mail to sam@acme.example', 'started': now.isoformat(), 'status': 'ok'},
        {'task': 'briefing', 'label': 'Briefing: Example topic', 'started': now.isoformat(), 'status': 'ok'},
        {'task': 'briefing', 'label': 'Briefing: (deleted)', 'started': now.isoformat(), 'status': 'failed'}]
A.RUNNER._load_runs = lambda: {'runs': week, 'slots': {}}
out = A.outbound()
by = {b['what']: b for b in out['claude']['by']}
ok(by.get('Compose mail', {}).get('count') == 2, 'compose runs grouped as "Compose mail: 2"')
ok('@' not in str(out['claude']), 'no address in the run rows')
ok(by.get('Briefings', {}).get('count') == 2 and by['Briefings'].get('failed') == 1, 'briefings: 2 runs (1 failed)')
ok(out['claude']['capped'] is False, 'not capped')
ok(A.plural(1, 'chat') == '1 chat' and A.plural(4, 'device') == '4 devices', 'plurals')
# a task that failed and then ran OK is fixed: not "failing", the count stays as information
T = '2026-11-03'
fr = [{'task': 'p0-check', 'label': 'Urgent check', 'started': T + 'T07:%02d:00+01:00' % m, 'status': 'failed'} for m in range(0, 50, 15)]
ok(A.run_failures(fr, T) == (['Urgent check'], 4), 'still failing: named, counted')
fr.append({'task': 'p0-check', 'label': 'Urgent check', 'started': T + 'T08:45:00+01:00', 'status': 'ok'})
ok(A.run_failures(fr, T) == ([], 4), 'then OK: nothing failing, 4 failed earlier')
fr.append({'task': 'kb-harvest', 'label': 'Knowledge harvest', 'started': '2026-11-02T01:30:00+01:00', 'status': 'failed'})
ok(A.run_failures(fr, T) == ([], 4), "yesterday's failure doesn't count today")
fr.insert(0, {'task': 'digest-morning', 'label': 'Morning digest', 'started': T + 'T09:00:00+01:00', 'status': 'failed'})
ok(A.run_failures(fr, T) == (['Morning digest'], 5), 'list order does not matter – the newest run decides')

MAC = 'Macuse (Mail/Messages/Calendar) not available – 0 tools'
mr = [{'task': 'kb-harvest', 'label': 'Knowledge harvest', 'started': T + 'T01:30:00+01:00', 'status': 'failed', 'reason': MAC},
      {'task': 'p0-check', 'label': 'Urgent check', 'started': T + 'T07:00:00+01:00', 'status': 'failed', 'reason': MAC}]
ok(A.run_failures(mr, T)[0] == ['Knowledge harvest', 'Urgent check'], 'Macuse down: both failing')
mr.append({'task': 'p0-check', 'label': 'Urgent check', 'started': T + 'T08:45:00+01:00', 'status': 'ok'})
ok(A.run_failures(mr, T) == ([], 2), 'Macuse works again: the nightly run that failed on it alone is fixed too')
mr.append({'task': 'digest-morning', 'label': 'Morning digest', 'started': T + 'T07:30:00+01:00', 'status': 'failed', 'reason': 'timeout'})
ok(A.run_failures(mr, T)[0] == ['Morning digest'], '… but not a failure for another reason')

print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
