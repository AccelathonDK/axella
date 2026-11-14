#!/usr/bin/env python3
"""Claude signed out on the Mac mini (scheduler.AUTH_RE / AUTH_REASON): a run that fails because Claude Code's sign-in
expired gets a plain reason ("… claude, then /login"), no pointless retry, and one shared push for every task – one
more when any run works again. Settings → System status shows a "Claude sign-in" row while it lasts. Claude is faked
with a tiny shell command; invented tasks only. Run: python3 setup/tests/test_run_auth.py"""
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


print('Recognising a signed-out Claude')
for text in ('Failed to authenticate: OAuth session expired and could not be refreshed', 'Invalid API key · Please run /login',
             'API Error: 401 {"type":"error","error":{"type":"authentication_error"}}', 'OAuth token has expired'):
    ok(scheduler.AUTH_RE.search(text), 'recognised: ' + text[:50])
for text in ('Macuse (Mail/Messages/Calendar) not available – 0 tools', 'timed out after 15 min', 'exit code 1', 'The meeting about logins'):
    ok(not scheduler.AUTH_RE.search(text), 'not a sign-in problem: ' + text)

print('A run that fails on the sign-in')
d = tempfile.mkdtemp(prefix='axtest-auth-')
json.dump({'enabled': True, 'digests': []}, open(os.path.join(d, 'scheduler.json'), 'w'))
sent = []
R = scheduler.Scheduler(d, d, None, sent.append)
R._feature_off = lambda job: None
RESULT = json.dumps({'type': 'result', 'subtype': 'success', 'is_error': True, 'num_turns': 1,
                     'result': 'Failed to authenticate: OAuth session expired and could not be refreshed'})
R._command = lambda task, job: (['/bin/sh', '-c', "printf '%s\\n' \"$0\"; exit 1", RESULT], 'sonnet')
R._run({'task': 'p0-check', 'slot': None, 'trigger': 'schedule', 'not_before': 0, 'attempt': 1})
run = R._load_runs()['runs'][-1]
ok(run['status'] == 'failed' and run['reason'] == scheduler.AUTH_REASON and '/login' in run['reason'], 'the run says what to do: ' + str(run['reason']))
ok(not [j for j in R.queue if j.get('trigger') == 'retry'], 'no retry – a retry cannot fix a sign-in')
ok(len(sent) == 1 and 'signed out' in sent[0]['title'] and '/login' in sent[0]['body'], 'one push at once: ' + (sent[0]['title'] if sent else '–'))
R._run({'task': 'kb-harvest', 'slot': None, 'trigger': 'schedule', 'not_before': 0, 'attempt': 1})
a = json.load(open(os.path.join(d, 'run-alerts.json')))
ok(len(sent) == 1 and list(a) == ['claude-auth'] and a['claude-auth']['count'] == 2, 'another task failing the same way: the same alert, no second push')

print('Signed in again')
R._command = lambda task, job: (['/bin/sh', '-c', 'exit 0'], 'sonnet')
R._alert_ok('briefing')                              # any task that works proves the sign-in, not only the ones that failed
ok(len(sent) == 2 and 'signed in again' in sent[1]['title'] and not json.load(open(os.path.join(d, 'run-alerts.json'))), 'one push when it works again')

print('An ordinary failure still retries')
sent.clear()
R._command = lambda task, job: (['/bin/sh', '-c', "echo 'boom' 1>&2; exit 1"], 'sonnet')
R._run({'task': 'p0-check', 'slot': None, 'trigger': 'schedule', 'not_before': 0, 'attempt': 1})
ok([j for j in R.queue if j.get('trigger') == 'retry'] and not sent, 'a retry is queued, no push yet')

print()
print('all ok' if not fails else '%d failed' % fails)
sys.exit(1 if fails else 0)
