#!/usr/bin/env python3
"""Failure pushes (scheduler.Scheduler._alert_failed/_alert_ok): one push when a problem starts, one reminder after
ALERT_REMIND, one when it works again – not one per failed run. Macuse failures from different tasks share one alert.
Invented tasks and times. Run: python3 setup/tests/test_run_alerts.py"""
import json
import os
import stat
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


d = tempfile.mkdtemp()
json.dump({'enabled': True, 'digests': []}, open(os.path.join(d, 'scheduler.json'), 'w'))
sent = []
R = scheduler.Scheduler(d, d, None, sent.append)
MAC = 'Macuse (Mail/Messages/Calendar) not available – 0 tools'
T0 = 2000000000.0

R._alert_failed('p0-check', 'Urgent check', MAC, now=T0)
ok(len(sent) == 1 and sent[0]['title'] == 'Axella: Macuse not available', 'first failure: one push')
for k in range(1, 8):                                   # every 15 minutes for close to two hours
    R._alert_failed('p0-check', 'Urgent check', MAC, now=T0 + k * 900)
R._alert_failed('kb-harvest', 'Knowledge harvest', MAC, now=T0 + 1000)
ok(len(sent) == 1, 'repeated failures, and another task failing on Macuse too: no more pushes')
p = os.path.join(d, 'run-alerts.json')
a = json.load(open(p))
ok(list(a) == ['macuse'] and a['macuse']['count'] == 9 and set(a['macuse']['tasks']) == {'p0-check', 'kb-harvest'}, 'one shared Macuse alert, counted')
ok(stat.S_IMODE(os.stat(p).st_mode) == 0o600, 'run-alerts.json is mode 600')

R2 = scheduler.Scheduler(d, d, None, sent.append)       # a restart keeps the state
R2._alert_failed('p0-check', 'Urgent check', MAC, now=T0 + 2 * 3600)
ok(len(sent) == 1, 'after a restart: still quiet')
R2._alert_failed('p0-check', 'Urgent check', MAC, now=T0 + scheduler.ALERT_REMIND + 1)
ok(len(sent) == 2 and 'still' in sent[1]['title'] and '11 failed runs' in sent[1]['body'], 'after ALERT_REMIND: one reminder')
R2._alert_failed('p0-check', 'Urgent check', MAC, now=T0 + scheduler.ALERT_REMIND + 900)
ok(len(sent) == 2, '… then quiet again')

R2._alert_ok('briefing', now=T0 + 7 * 3600)
ok(len(sent) == 2, 'a run that does not use Macuse succeeding does not clear it')
R2._alert_ok('p0-check', now=T0 + 7 * 3600)
ok(len(sent) == 3 and sent[2]['title'] == 'Axella: Macuse works again' and sent[2]['tag'] == sent[0]['tag'], 'fixed: one "works again", same tag')
ok(json.load(open(p)) == {}, 'and the alert is cleared')
R2._alert_ok('p0-check', now=T0 + 8 * 3600)
ok(len(sent) == 3, 'the next OK run pushes nothing')

R2._alert_failed('digest-morning', 'Morning digest', 'finished but wrote no output file', now=T0)
R2._alert_failed('kb-harvest', 'Knowledge harvest', 'finished but wrote no output file', now=T0)
ok(len(sent) == 5 and sent[3]['title'] == 'Axella: Morning digest failed twice', 'other failures: one push per task')
R2._alert_failed('digest-morning', 'Morning digest', 'timeout', now=T0 + 60)
ok(len(sent) == 5, '… and quiet while that task keeps failing')
R2._alert_ok('digest-morning', now=T0 + 120)
ok(len(sent) == 6 and 'Morning digest works again' in sent[5]['title'] and 'kb-harvest' in json.load(open(p)), 'only that task is cleared')

def boom(m):
    raise RuntimeError('push down')
R3 = scheduler.Scheduler(d, d, None, boom)
R3._alert_failed('p0-check', 'Urgent check', MAC, now=T0)
ok('macuse' in json.load(open(p)), 'a failing push is logged, never raised')


# the session line tells whether Macuse was configured – a run that wrote nothing because Macuse gave 0 tools says so

for servers, tools, want in [([{'name': 'macuse', 'status': 'connected'}], [], True), ([], [], False)]:
    st = {}
    ev = json.dumps({'type': 'system', 'subtype': 'init', 'model': 'x', 'mcp_servers': servers, 'tools': tools})
    scheduler.Scheduler._event(ev, lambda *a: None, st)
    ok(st.get('macuse_server') is want and st.get('macuse_tools') == 0, 'session line: macuse configured = %s' % want)


# Runs → Run now on the knowledge harvest prepares its request like the nightly run (it ran with ref None before)
class H:
    on, refs = True, []
    def nightly_request(self, rid):
        self.refs.append(rid)
        return self.on
R4 = scheduler.Scheduler(d, d, None, sent.append)
R4.harvest = H()
ok(R4.action('run_now', {'task': 'kb-harvest'}) == 'queued', 'kb-harvest Run now: queued')
j = [x for x in R4.queue if x['task'] == 'kb-harvest']
ok(len(j) == 1 and j[0]['ref'] == R4.harvest.refs[0] and j[0]['ref'].startswith('kb'), '… with a request ref')
ok(R4.action('run_now', {'task': 'kb-harvest'}) == 'already queued' and len(R4.harvest.refs) == 1, 'twice: already queued, no second request')
R4.queue.clear(); R4.harvest.on = False
try:
    R4.action('run_now', {'task': 'kb-harvest'}); ok(False, 'switched off: refused')
except scheduler.Bad:
    ok(not R4.queue, 'switched off: refused, nothing queued')

print('all ok' if not fails else '%d failed' % fails)
sys.exit(1 if fails else 0)
