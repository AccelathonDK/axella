#!/usr/bin/env python3
"""Work/private per schedule (setup/scope.py + scheduler.py + schedule.py): slot scopes, the run's scope note, the
gather window per world (nothing lost between scoped digests), the post-run check, urgent breaking through and
"Pause work digests only". Invented data; no Claude call. Run: python3 setup/tests/test_scope.py"""
import datetime
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import scope as SC  # noqa: E402
import schedule as SCH  # noqa: E402
import scheduler as S  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


# ---- slot parsing
ok(SC.worlds_of({}) == ['private', 'work'] and SC.worlds_of({'worlds': []}) == ['private', 'work'], 'no worlds = both (existing schedules unchanged)')
ok(SC.worlds_of({'worlds': ['work']}) == ['work'] and SC.worlds_of({'worlds': ['private', 'nonsense']}) == ['private'], 'worlds: only work and private')
ok(SC.norm_slot({'worlds': ['work']}) == {'worlds': ['work'], 'mention_other': True}, 'the other-world line is on by default')
ok(SC.effective(['work'], work_paused=True) == [] and SC.effective(['private', 'work'], True) == ['private'], 'a day off from work: work leaves the slot')

tmp = tempfile.mkdtemp()
base, state = tmp, os.path.join(tmp, 'state')
for d in (state, os.path.join(tmp, 'digests'), os.path.join(tmp, 'setup', 'local-tasks')):
    os.makedirs(d, exist_ok=True)
open(os.path.join(tmp, 'setup', 'local-tasks', 'digest-morning.md'), 'w').write('# Task: digest\n')
open(os.path.join(state, 'mcp.json'), 'w').write('{}')
json.dump({'enabled': True, 'digests': [
    {'id': 'old', 'label': 'Morning digest', 'task': 'digest-morning', 'time': '07:30', 'days': [0, 1, 2, 3, 4, 5, 6]}]},
    open(os.path.join(state, 'scheduler.json'), 'w'))


class Sched:
    paused_work = False
    def sweep(self):
        return None

    def status(self, *_):
        if self.paused_work:
            return {'digests': True, 'urgent': True, 'work_paused': True, 'reason': 'Day off – work digests paused'}
        return {'digests': True, 'urgent': True, 'reason': None}


sch = Sched()
s = S.Scheduler(base, state, sch, None, log=open(os.devnull, 'w'))
for f in ('_auto_briefings', '_auto_receipts', '_auto_feedback_pull', '_auto_feedback_summary', '_auto_kb'):
    setattr(s, f, lambda *a: None)
cfg = s.load()
ok(cfg['digests'][0]['worlds'] == ['private', 'work'] and cfg['digests'][0]['mention_other'] is True, 'a saved slot without worlds loads as both')
ok([x.get('worlds') for x in S.DEFAULT['digests']][-1] == ['private'], 'a new installation\'s Sunday week-ahead is private')

# Settings saves scopes and duplicates
s.action('scheduler_set', {'digests': [
    {'id': 'wm', 'label': 'Work morning', 'task': 'digest-morning', 'time': '09:00', 'days': [0, 1, 2, 3, 4], 'worlds': ['work']},
    {'id': 'pe', 'label': 'Evening wrap', 'task': 'digest-morning', 'time': '20:00', 'days': [0, 1, 2, 3, 4], 'worlds': ['private'], 'mention_other': False},
    {'id': 'we', 'label': 'Weekend', 'task': 'digest-morning', 'time': '09:30', 'days': [5, 6], 'worlds': ['private']}]})
ok([(x['id'], x['worlds'], x['mention_other']) for x in s.load()['digests']] ==
   [('wm', ['work'], True), ('pe', ['private'], False), ('we', ['private'], True)], 'scopes and the mention checkbox are saved')
for bad in ({'worlds': ['office']}, {'worlds': []}):
    try:
        s.action('scheduler_set', {'digests': [dict({'id': 'x', 'task': 'digest-morning', 'time': '08:00', 'days': [0]}, **bad)]})
        ok(False, 'refused: %s' % bad)
    except S.Bad:
        ok(True, 'refused: %s' % bad)
try:
    s.action('scheduler_set', {'digests': [{'id': 'x', 'task': 'digest-morning', 'time': '08:00', 'days': [0]},
                                           {'id': 'x', 'task': 'digest-morning', 'time': '09:00', 'days': [0]}]})
    ok(False, 'two slots with one id are refused')
except S.Bad:
    ok(True, 'two slots with one id are refused')

# ---- the scope note and the gather window per world
now = datetime.datetime(2027, 3, 16, 9, 0)          # a Tuesday
dg = os.path.join(tmp, 'digests')
json.dump({'items': []}, open(os.path.join(dg, '2027-03-15-2000.json'), 'w'))                       # Monday evening: both (older digest)
json.dump({'items': [], 'scope': ['work']}, open(os.path.join(dg, '2027-03-16-0730.json'), 'w'))    # this morning: work only
since = SC.last_covered(dg, now)
ok(since == {'work': datetime.datetime(2027, 3, 16, 7, 30), 'private': datetime.datetime(2027, 3, 15, 20, 0)},
   'gather window: private from the last digest that covered private, not from this morning\'s work digest')
s.load = (lambda c=s.load(): c)                     # freeze the config for the next lines
note = s._scope_note({'worlds': ['work'], 'mention_other': True}, now)
ok('WORK ONLY' in note and '"scope": ["work"]' in note and 'Your work digest.' in note, 'the run is told its scope and how to open')
ok('gather work since 2027-03-16 07:30' in note, '… and its gather window')
ok('waiting for this evening (20:00)' in note and 'COUNT' in note and 'never names' in note, '… and the other-world line: a count and the next private digest')
ok('urgent (P0) private items are the exception' in note, '… and that urgent private items still break through')
quiet = s._scope_note({'worlds': ['private'], 'mention_other': False}, now)
ok('do not mention the work world' in quiet, '"no mention" leaves the other world out')
both = s._scope_note({}, now)
ok('work and private (both)' in both and 'private since 2027-03-15 20:00' in both, 'a digest for both still gathers each world from its own last digest')

# ---- after the run: only its world, urgent other-world kept and marked, nothing marked handled
path = os.path.join(dg, '2027-03-16-0900.json')
json.dump({'items': [
    {'id': 'w1', 'section': 'p1', 'context': 'work', 'headline': 'Lee: review'},
    {'id': 'p1', 'section': 'p2', 'context': 'private', 'headline': 'Robin: dinner?'},
    {'id': 'p2', 'section': 'p0', 'context': 'private', 'headline': 'Kim: urgent'},
    {'id': 'p3', 'section': 'cal', 'context': 'private', 'headline': 'Dentist'},
    {'id': 'w2', 'section': 'p3', 'context': 'private', 'from': {'address': 'sam@acme.example'}, 'headline': 'Sam'}]},
    open(path, 'w'))
json.dump({'sender': {'sam@acme.example': 'work'}}, open(os.path.join(state, 'context-overrides.json'), 'w'))
ok(SC.enforce(path, ['work'], state) == 2, 'two private items taken out of the work digest')
d = json.load(open(path))
ok([i['id'] for i in d['items']] == ['w1', 'p2', 'w2'] and d['scope'] == ['work'], 'work items kept; your Work correction counts; scope set')
ok(next(i for i in d['items'] if i['id'] == 'p2').get('world') == 'private', 'urgent private item kept, marked with its world')
ok(not os.path.exists(os.path.join(state, 'actions.json')), 'nothing is marked handled')
since = SC.last_covered(dg, datetime.datetime(2027, 3, 16, 20, 0))
ok(since['private'] == datetime.datetime(2027, 3, 15, 20, 0), '… so the evening private digest still gathers private from Monday evening')
p_both = os.path.join(dg, '2027-03-16-1200.json')
json.dump({'items': [{'id': 'a', 'section': 'p2', 'context': 'private'}, {'id': 'b', 'section': 'p2', 'context': 'work'}]}, open(p_both, 'w'))
ok(SC.enforce(p_both, ['private', 'work'], state) == 0 and len(json.load(open(p_both))['items']) == 2, 'a digest for both keeps everything')

# ---- the clock: work-only slots skip on a day off from work; both-world slots run as private
s2 = S.Scheduler(base, state, sch, None, log=open(os.devnull, 'w'))
for f in ('_auto_briefings', '_auto_receipts', '_auto_feedback_pull', '_auto_feedback_summary', '_auto_kb'):
    setattr(s2, f, lambda *a: None)
t = (datetime.datetime.now() - datetime.timedelta(minutes=2)).strftime('%H:%M')
wd = datetime.datetime.now().weekday()
json.dump({'enabled': True, 'enabled_at': '2000-01-01T00:00:00', 'p0': {'enabled': False}, 'digests': [
    {'id': 'wo', 'label': 'Work only', 'task': 'digest-morning', 'time': t, 'days': [wd], 'worlds': ['work']},
    {'id': 'bo', 'label': 'Both', 'task': 'digest-morning', 'time': t, 'days': [wd]}]}, open(os.path.join(state, 'scheduler.json'), 'w'))
sch.paused_work = True
s2._tick()
q = {j['label']: j for j in s2.queue}
runs = json.load(open(os.path.join(state, 'runs.json')))['slots']
ok('Work only' not in q and any(v.startswith('skipped: Day off – work digests paused') for k, v in runs.items() if k.startswith('wo@')),
   'Pause work digests only: the work-only slot is skipped')
ok(q.get('Both', {}).get('worlds') == ['private'], '… and the both-world slot runs as private only')

# ---- the push watcher leaves a digest alone while its run is still going (the scope check runs at its end)
import time as _t  # noqa: E402
ok(s2.writing_since() is None, 'no run going: nothing held back')
s2.current = {'run': {'task': 'digest-morning'}, 't0': _t.time() - 30}
ok(abs(s2.writing_since() - (_t.time() - 30)) < 2, 'a digest run going: its start time, so its files wait')
s2.current = {'run': {'task': 'compose'}, 't0': _t.time()}
ok(s2.writing_since() is None, '… but not for other kinds of run')
s2.current = None

# ---- schedule.py: the pause rule's checkbox
st = SCH.Schedule(state)
day = datetime.date.today().isoformat()
st.action('schedule_set', {'off_dates': [day]}, 'owner')
ok(st.status()['digests'] is False and not st.status().get('work_paused'), 'a day off without the checkbox: no digests, as before')
st.action('schedule_set', {'off_work_only': True}, 'owner')
v = st.status()
ok(v['digests'] is True and v['work_paused'] is True and v['urgent'] is True, '"Pause work digests only": private digests and urgent checks run')

print('%d failed' % fails if fails else 'all passed')
sys.exit(1 if fails else 0)
