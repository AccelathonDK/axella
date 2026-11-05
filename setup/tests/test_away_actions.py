#!/usr/bin/env python3
"""Back-from-away briefing in the scheduler and the action service: the first digest slot after 2+ days away becomes
the briefing (once; a 1-day pause doesn't), its run is told where its facts are, "Catch me up since…" queues it for a
chosen date, Archive all marks the grouped items handled in Axella only with one Undo, and the briefing gets no push.
Invented data; no Claude call. Run: python3 setup/tests/test_away_actions.py"""
import datetime
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import scheduler as S  # noqa: E402
import away as AW  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


# ---- the scheduler: the slot's digest becomes the briefing
tmp = tempfile.mkdtemp()
state = os.path.join(tmp, 'state')
for d in (state, os.path.join(tmp, 'digests'), os.path.join(tmp, 'setup', 'local-tasks')):
    os.makedirs(d, exist_ok=True)
for t in ('digest-morning', 'return-briefing'):
    open(os.path.join(tmp, 'setup', 'local-tasks', t + '.md'), 'w').write('# Task\n')
open(os.path.join(state, 'mcp.json'), 'w').write('{}')
t = (datetime.datetime.now() - datetime.timedelta(minutes=2)).strftime('%H:%M')
wd = datetime.datetime.now().weekday()


class Sched:
    def sweep(self):
        return None

    def status(self, *_):
        return {'digests': True, 'urgent': True, 'reason': None}


def runner(ab):
    json.dump({'enabled': True, 'enabled_at': '2000-01-01T00:00:00', 'p0': {'enabled': False}, 'digests': [
        {'id': 'm', 'label': 'Morning digest', 'task': 'digest-morning', 'time': t, 'days': [wd]}]}, open(os.path.join(state, 'scheduler.json'), 'w'))
    try:
        os.remove(os.path.join(state, 'runs.json'))
    except OSError:
        pass
    s = S.Scheduler(tmp, state, Sched(), None, log=open(os.devnull, 'w'))
    for f in ('_auto_briefings', '_auto_receipts', '_auto_feedback_pull', '_auto_feedback_summary', '_auto_kb'):
        setattr(s, f, lambda *a: None)
    s.away_due = lambda today: ab
    s._tick()
    return s


AB = {'from': '2027-03-09', 'to': '2027-03-12', 'days': 4}
s = runner(AB)
ok([j['task'] for j in s.queue] == ['return-briefing'] and s.queue[0]['away'] == AB and s.queue[0]['label'] == 'Back-from-away briefing',
   'back from 4 days away: the morning slot runs the briefing instead')
s2 = runner(None)
ok([j['task'] for j in s2.queue] == ['digest-morning'], 'no absence to brief: the normal digest')
seen = {}
s.away_facts = lambda job: (seen.update(job=job), {'absence': dict(job['away']), 'digests': ['2027-03-10-0730.json'], 'fallback_rescan': None})[1]
s.claude_bin = lambda: '/bin/true'
cmd, _ = s._command('return-briefing', s.queue[0])
prompt = ' '.join(cmd)
ok('BACK-FROM-AWAY BRIEFING for 2027-03-09 to 2027-03-12' in prompt and 'state/return-briefing.json' in prompt and seen['job']['away'] == AB,
   'its run gets the facts (written just before) and the note')
try:
    s.action('run_now', {'task': 'return-briefing'})
    ok(False, 'run_now without an absence is refused')
except S.Bad:
    ok(True, 'run_now without an absence is refused')

# ---- the action service
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
d = tempfile.mkdtemp()
A.DIGESTS_DIR = d
A.STATE_FILE = os.path.join(d, 'actions.json')
A.AWAY = AW.Away(tempfile.mkdtemp())
mk = lambda iid, sec: {'id': iid, 'section': sec, 'channel': 'mail', 'headline': 'About ' + iid, 'from': {'name': 'Kim', 'address': 'kim@example.org'}}
json.dump({'items': [mk('a1', 'p2'), mk('a2', 'p2'), mk('n1', 'p3'), mk('n2', 'p3'), mk('p1x', 'p1')]}, open(os.path.join(d, '2027-03-10-0730.json'), 'w'))
json.dump({'items': [mk('p1x', 'p1')]}, open(os.path.join(d, '2027-03-11-0730.json'), 'w'))     # the P1 is still carried
A.AWAY.write_facts({'absence': AB, 'digests': ['2027-03-10-0730.json', '2027-03-11-0730.json'], 'arrived': 5})
BN = '2027-03-15-0730.json'
run_list = {'groups': [{'key': 'answered', 'label': 'x', 'count': 1, 'items': [{'id': 'p1x'}]}], 'count': 1}
json.dump({'items': [], 'away': {'headline': 'Welcome back.', 'sorted': run_list, 'sorted_by': 'axella'}}, open(os.path.join(d, BN), 'w'))
json.dump({'a2': {'status': 'done', 'how': 'sent'}}, open(A.STATE_FILE, 'w'))
try:
    A.away_action('away_archive', {'digest': BN})
    ok(False, 'Archive all before Python added its own list is refused')
except A.Bad:
    ok(True, 'Archive all before Python added its own list is refused')
A.AWAY.add_to_digest(d, BN, lambda: json.load(open(A.STATE_FILE)))
dg = json.load(open(os.path.join(d, BN)))
ok('p1x' not in AW.list_ids(dg['away']['sorted']) and dg['away']['sorted_by'] == 'axella', 'the run-written list (with a P1) is replaced by Python\'s')
dg['away']['sorted']['groups'][0]['items'].append({'id': 'p1x'})          # edited in the file afterwards
json.dump(dg, open(os.path.join(d, BN), 'w'))
mail_calls = []
A.osa = lambda *a, **k: mail_calls.append(a)
p = {'digest': BN, 'keep': ['n2']}
r = A.away_action('away_archive', p)
st = json.load(open(A.STATE_FILE))
ok(r['count'] == 2 and st['n1']['status'] == 'done' and st['a1']['status'] == 'done' and 'n2' not in st, 'Archive all: the grouped items are handled – not the one kept back')
ok('p1x' not in st, '… and never the P1 – not even when an id is added to the file: only the stored list counts')
ok(st['a2']['how'] == 'sent' and not mail_calls, '… one you had handled stays as it was, and nothing is done in Mail')
ok(sorted(p['_items']) == ['a1', 'n1'] and 'nothing moved in Mail' in p['title'], '… one activity-log line for the batch')
st['n1'] = {'status': 'done', 'how': 'filed:Archive'}            # filed it yourself since
json.dump(st, open(A.STATE_FILE, 'w'))
u = A.away_action('away_undo', {'batch': r['batch']})
st = json.load(open(A.STATE_FILE))
ok(u['count'] == 1 and 'a1' not in st and st['n1']['how'] == 'filed:Archive' and st['a2']['how'] == 'sent', 'one Undo brings the batch back (not what you changed since)')
try:
    A.away_action('away_undo', {'batch': r['batch']})
    ok(False, 'the Undo works once')
except A.Bad:
    ok(True, 'the Undo works once')
for bad in ({'digest': '../x.json'}, {'digest': '2027-03-11-0730.json'}):
    try:
        A.away_action('away_archive', bad)
        ok(False, 'refused: %s' % bad)
    except A.Bad:
        ok(True, 'refused: %s' % bad)
queued = []
A.RUNNER.action = lambda a, pp: (queued.append(pp), 'queued')[1]
since = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
ok(A.away_action('away_catchup', {'since': since}) == 'queued' and queued[0]['away']['from'] == since and
   queued[0]['away']['to'] == (datetime.date.today() - datetime.timedelta(days=1)).isoformat(), 'Catch me up since… a date: the briefing from then to yesterday')
for bad in ({'since': datetime.date.today().isoformat()}, {'since': 'soon'}, {'since': '2000-01-01'}):
    try:
        A.away_action('away_catchup', bad)
        ok(False, 'refused: %s' % bad)
    except A.Bad:
        ok(True, 'refused: %s' % bad)
ok({'away_archive', 'away_undo', 'away_catchup'} <= A.OWNER_ONLY, 'owner only')
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
