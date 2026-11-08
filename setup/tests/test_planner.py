#!/usr/bin/env python3
"""Targets and Now · Next · Later (setup/planner.py): project states and their suggestions, people on a project,
targets and steps, idea-target progress and signals, free slots with a buffer, the day plan, None today, the week
heads-up and the digest lines. Invented projects, people and calendar. Run: python3 setup/tests/test_planner.py"""
import datetime
import json
import os
import stat
import sys
import tempfile
import time

os.environ['TZ'] = 'Europe/Copenhagen'           # the invented calendar is in +01:00 (winter): plan in that time zone
time.tzset()

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import planner  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def bad(fn, label):
    try:
        fn()
        ok(False, label)
    except planner.Bad:
        ok(True, label)


d0 = tempfile.mkdtemp()
P = planner.Planner(d0)
MON = datetime.date(2030, 1, 7)                       # a Monday
IDS = ['p-acme', 'p-lighthouse', 'p-garden', 'p-website', 'p-rental']
PROJ = [{'id': 'p-acme', 'name': 'Acme proposal', 'status': 'active', 'ctx': 'work', 'created': '2029-12-01T09:00:00+01:00',
         'senders': ['lee@example.com', 'example.org']},
        {'id': 'p-lighthouse', 'name': 'Lighthouse', 'status': 'active', 'ctx': 'work', 'created': '2029-12-01T09:00:00+01:00'},
        {'id': 'p-garden', 'name': 'Garden deck', 'status': 'active', 'ctx': 'private', 'created': '2029-12-01T09:00:00+01:00'},
        {'id': 'p-website', 'name': 'Website refresh', 'status': 'active', 'ctx': 'work', 'created': '2029-12-01T09:00:00+01:00'},
        {'id': 'p-rental', 'name': 'Holiday rental', 'status': 'active', 'ctx': 'private', 'created': '2029-12-01T09:00:00+01:00'}]
act = lambda a, p, today=MON: P.action(a, p, IDS, today)

# ---------- Part 1: states
for st in planner.STATES:
    ok(act('project_state', {'id': 'p-rental', 'state': st})['state'] == st, 'state can be set: ' + st)
bad(lambda: act('project_state', {'id': 'p-rental', 'state': 'sleeping'}), 'an unknown state is refused')
bad(lambda: act('project_state', {'id': 'p-nope', 'state': 'active'}), 'an unknown project is refused')
act('project_state', {'id': 'p-rental', 'state': 'running'})
act('project_state', {'id': 'p-website', 'state': 'waiting', 'waiting_for': {'kind': 'person', 'ref': 'Kim@Example.net', 'label': 'Kim'}})
bad(lambda: act('project_state', {'id': 'p-garden', 'state': 'paused', 'until': MON.isoformat()}), 'paused until: a date after today')
act('project_state', {'id': 'p-garden', 'state': 'paused', 'until': (MON + datetime.timedelta(days=3)).isoformat()})
d = P.load()
ok(d['projects']['p-website']['waiting_for'] == {'kind': 'person', 'ref': 'kim@example.net', 'label': 'Kim'}, 'waiting for a person (key lowercased)')
ok(stat.S_IMODE(os.stat(os.path.join(d0, 'planner.json')).st_mode) == 0o600, 'planner.json is mode 600')

since = d['projects']['p-website']['since']
s = planner.state_suggestions(d, PROJ, MON, recent={'kim@example.net': {'at': '2020-01-01T08:00:00', 'name': 'Kim'}})
ok(not [x for x in s if x['kind'] == 'back'], 'a mail from before the wait: no suggestion')
s = planner.state_suggestions(d, PROJ, MON, recent={'kim@example.net': {'at': '2099-01-01T08:00:00', 'name': 'Kim'}})
back = [x for x in s if x['kind'] == 'back']
ok(len(back) == 1 and back[0]['text'].startswith('Website refresh can move again – Kim wrote') and back[0]['yes'] == 'Back to Active',
   'Waiting for Kim → Kim writes → "can move again"')
ok(P.load()['projects']['p-website']['state'] == 'waiting', '… and the state is unchanged (a suggestion only)')
act('plan_suggestion', {'key': back[0]['key']})
ok(not [x for x in planner.state_suggestions(P.load(), PROJ, MON, recent={'kim@example.net': {'at': '2099-01-01T08:00:00'}}) if x['kind'] == 'back'],
   'Keep waiting: not asked again for that cause')
s = planner.state_suggestions(P.load(), PROJ, MON + datetime.timedelta(days=3))
ok(any(x['kind'] == 'resume' and 'Garden deck was paused until' in x['text'] for x in s), 'Paused until a date → resume suggested on that date')
ok(not any(x['kind'] == 'resume' for x in planner.state_suggestions(P.load(), PROJ, MON + datetime.timedelta(days=2))), '… not before')
idle = planner.state_suggestions(P.load(), PROJ, MON + datetime.timedelta(days=60), last_activity={'p-acme': '2030-01-01T10:00:00'})
ok(any(x['kind'] == 'idle' and x['pid'] == 'p-acme' and 'no activity for' in x['text'] for x in idle), 'no activity for 3 weeks → pause suggested')
ok(not any(x['kind'] == 'idle' and x['pid'] == 'p-acme' for x in planner.state_suggestions(P.load(), PROJ, MON + datetime.timedelta(days=10), last_activity={'p-acme': '2030-01-05'})),
   '… not within 3 weeks')
act('project_state', {'id': 'p-website', 'state': 'waiting', 'waiting_for': {'kind': 'task', 'ref': 't-123', 'label': 'Get the copy'}})
ok(any(x['kind'] == 'back' and '"Get the copy" is closed' in x['text'] for x in planner.state_suggestions(P.load(), PROJ, MON, closed={'t-123'})),
   'Waiting for a task → the task closes → suggestion')

# ---------- Part 3: targets (before the planner needs them)
r = act('project_target_add', {'id': 'p-acme', 'kind': 'date', 'title': 'Proposal sent to Acme', 'date': '2030-01-11',
                               'done_means': 'Lee has a complete proposal with pricing.'})
TA = r['id']
for txt, mins in (('Scope agreed with Lee', 30), ('Section 1: the problem', 60), ('Section 2: pricing', 45),
                  ('Section 4: delivery plan', 120), ('Final read-through', 120)):
    act('project_entry_add', {'id': 'p-acme', 'target': TA, 'list': 'steps', 'text': txt, 'mins': mins})
st = P.load()['projects']['p-acme']['targets'][0]['steps']
for x in st[:2]:
    act('project_entry_update', {'id': 'p-acme', 'target': TA, 'list': 'steps', 'entry': x['id'], 'done': True})
t = P.load()['projects']['p-acme']['targets'][0]
ok(planner.progress(t) == '2 of 5 steps done', 'date target: "2 of 5 steps done" (a count, never a percentage)')
act('project_entry_reorder', {'id': 'p-acme', 'target': TA, 'list': 'steps', 'ids': [x['id'] for x in reversed(t['steps'])]})
ok(P.load()['projects']['p-acme']['targets'][0]['steps'][0]['text'] == 'Final read-through', 'steps can be reordered')
act('project_entry_reorder', {'id': 'p-acme', 'target': TA, 'list': 'steps', 'ids': [x['id'] for x in t['steps']]})
bad(lambda: act('project_entry_add', {'id': 'p-acme', 'target': TA, 'list': 'questions', 'text': 'x'}), 'questions only on idea targets')
bad(lambda: act('project_target_add', {'id': 'p-acme', 'kind': 'period', 'title': 'Window', 'from': '2030-02-10', 'to': '2030-02-01'}), 'a period ends after it starts')
rp = act('project_target_add', {'id': 'p-acme', 'kind': 'period', 'title': 'Follow-up calls', 'from': '2030-02-01', 'to': '2030-02-10'})
act('project_target_delete', {'id': 'p-acme', 'target': rp['id']})
ri = act('project_target_add', {'id': 'p-lighthouse', 'kind': 'idea', 'title': 'A calmer app', 'brief': 'lighthouse-watch'})
TI = ri['id']
for q in ('Which calls are needed?', 'Do they stay stable for weeks?', 'How long does a sign-in last?', 'What do the service terms allow developers?', 'Where is personal data kept?'):
    act('project_entry_add', {'id': 'p-lighthouse', 'target': TI, 'list': 'questions', 'text': q})
for g in ('The technical access is proven', 'A clear legal footing', 'Enough people want it'):
    act('project_entry_add', {'id': 'p-lighthouse', 'target': TI, 'list': 'go', 'text': g})
for x, m in (('Measure how long a sign-in lasts', 90), ('Prototype one screen', 90)):
    act('project_entry_add', {'id': 'p-lighthouse', 'target': TI, 'list': 'experiments', 'text': x, 'mins': m})
ti = P.load()['projects']['p-lighthouse']['targets'][0]
for x in ti['questions'][:2]:
    act('project_entry_update', {'id': 'p-lighthouse', 'target': TI, 'list': 'questions', 'entry': x['id'], 'done': True})
act('project_entry_update', {'id': 'p-lighthouse', 'target': TI, 'list': 'go', 'entry': ti['go'][0]['id'], 'done': True})
ti = P.load()['projects']['p-lighthouse']['targets'][0]
ok(planner.progress(ti) == '2 of 5 answered · 1 of 3 go', 'idea target: "2 of 5 answered · 1 of 3 go"')
briefs = [{'at': '2030-01-06T07:30', 'items': [
    {'title': 'The service published new developer terms', 'summary': 'What developers are allowed to build on the service terms.', 'url': 'https://example.com/terms'},
    {'title': 'Weather this week', 'summary': 'Rain.', 'url': 'https://example.com/weather'}]}]
sg = planner.signals(ti, briefs)
ok(len(sg) == 1 and sg[0]['url'] == 'https://example.com/terms' and 'terms' in sg[0]['for'], 'a brief item that may answer an open question is a signal')
act('project_target_signal_not', {'id': 'p-lighthouse', 'target': TI, 'url': 'https://example.com/terms'})
ok(planner.signals(P.load()['projects']['p-lighthouse']['targets'][0], briefs) == [], 'Not relevant: gone for good')
ok(planner.checks_due(P.load(), PROJ, MON)[0]['text'].endswith('2 of 5 answered · 1 of 3 go. Still worth pursuing?'), 'the monthly check')
act('plan_check', {'key': TI})
ok(planner.checks_due(P.load(), PROJ, MON) == [], '… answered: not again this month')

# ---------- Part 2: people
act('project_person_add', {'id': 'p-acme', 'key': 'Lee@Example.com', 'name': 'Lee Chen', 'role': 'Client'})
act('project_person_update', {'id': 'p-acme', 'key': 'lee@example.com', 'star': True})
e = P.load()['projects']['p-acme']
ok(e['people'][0]['key'] == 'lee@example.com' and e['people'][0]['role'] == 'Client' and e['people'][0]['star'], 'manual person with a free-text role and a star')
preps = [{'id': 'm1', 'title': 'Acme pricing', 'project': 'p-acme', 'attendees': [{'name': 'Robin', 'email': 'robin@example.org'}, {'name': 'Lee Chen', 'email': 'lee@example.com'}]}]
notes = [{'title': 'Ask Kim', 'links': [{'kind': 'project', 'ref': 'p-acme'}, {'kind': 'person', 'ref': 'c:kim', 'label': 'Kim', 'keys': ['kim@example.net']}]}]
au = planner.auto_people('p-acme', PROJ[0], e, preps, notes, own=['me@example.com'])
ok([(x['key'], x['why']) for x in au] == [('robin@example.org', 'On your Acme pricing prep'), ('kim@example.net', 'In your note "Ask Kim"')],
   'auto people: a prep attendee and a note person, each with its reason; a manual person isn\'t repeated; a domain match is not a person')
act('project_person_remove', {'id': 'p-acme', 'key': 'robin@example.org'})
ok('robin@example.org' not in [x['key'] for x in planner.auto_people('p-acme', PROJ[0], P.load()['projects']['p-acme'], preps, notes)],
   'an auto person removed stays removed')
mails = [{'from': 'Sam Rivera <sam@example.org>'}] * 7 + [{'from': 'lee@example.com'}] * 2 + [{'from': 'Jamie <jamie@example.net>'}]
sp = planner.suggested_people(PROJ[0], P.load()['projects']['p-acme'], mails)
ok(len(sp) == 1 and sp[0]['why'] == 'Sam Rivera appears in 7 of 10 Acme proposal mails.', 'suggested: someone in 7 of 10 mails')
act('project_person_not', {'id': 'p-acme', 'key': 'sam@example.org'})
ok(planner.suggested_people(PROJ[0], P.load()['projects']['p-acme'], mails) == [], 'Not for this project: never asked again')
bad(lambda: [(act('project_person_add', {'id': 'p-acme', 'key': k}), act('project_person_update', {'id': 'p-acme', 'key': k, 'star': True}))
             for k in ('a@example.com', 'b@example.com')], 'at most two key people')
for k in ('a@example.com', 'b@example.com'):
    act('project_person_remove', {'id': 'p-acme', 'key': k})

# ---------- Part 4: free slots, the day, None today
TZ = '+01:00'
ev = lambda d_, a, b, title='Meeting', **k: dict({'start': '%sT%s:00%s' % (d_, a, TZ), 'end': '%sT%s:00%s' % (d_, b, TZ), 'title': title}, **k)
day = MON.isoformat()
events = [ev(day, '09:00', '10:00', 'Stand-up'), ev(day, '11:00', '12:00', 'Call with Kim'), ev(day, '14:00', '14:30', 'Free', availability='free')]
WH = {'days': [0, 1, 2, 3, 4], 'from': '09:00', 'to': '17:00'}
sl = planner.free_slots(events, MON, planner.day_window(MON, 'work', WH), 10)
fmt = [(a.strftime('%H:%M'), b.strftime('%H:%M')) for a, b in sl]
ok(fmt == [('10:10', '10:50'), ('12:10', '17:00')], 'free slots: 10 min buffer around meetings, a "free" event doesn\'t block')
ok(planner.free_slots(events, MON, planner.day_window(MON, 'work', WH), 10, now=datetime.datetime(2030, 1, 7, 13, 2))[0][0].strftime('%H:%M') == '13:05',
   'never in the past, on a 5-minute mark')
ok(planner.free_slots([dict(ev(day, '00:00', '23:59'), all_day=True, start=day, end=(MON + datetime.timedelta(days=1)).isoformat(), availability='busy')], MON,
                      planner.day_window(MON, 'work', WH), 10) == [], 'an all-day busy event closes the day')
ok(planner.day_window(datetime.date(2030, 1, 12), 'work', WH) is None and planner.day_window(datetime.date(2030, 1, 12), 'private', WH) is not None,
   'weekend: no work window, a private one')

f = planner.suggest_focus(P.load(), PROJ, MON, 255)
ok(f['projects'] == ['p-acme', 'p-lighthouse'] and f['reason'].startswith('Axella suggests Acme proposal and Lighthouse. Proposal sent to Acme is due Friday with 3 of 5 steps left'),
   'focus: the closest target first, with a one-line reason')
ok('p-website' not in f['projects'] and 'p-rental' not in f['projects'], 'only Active projects are suggested')
ok(planner.suggest_focus(P.load(), PROJ, datetime.date(2030, 1, 12))['projects'] == [], 'weekend: work projects aren\'t suggested')
bad(lambda: act('plan_focus', {'projects': ['p-website']}), 'a Waiting project can\'t be today\'s focus')
act('plan_focus', {'projects': ['p-acme', 'p-lighthouse']})
now = datetime.datetime(2030, 1, 7, 10, 0)
pl = planner.plan_day(P.load(), PROJ, MON, events, WH, now)
ok(pl['now'] and pl['now']['title'] == 'Section 2: pricing' and pl['now']['start'] == '12:10',
   'Now: the current step in the first stretch it fits (45 min don\'t fit 10:10–10:50)')
titles = [x['title'] for x in pl['next']]
ok('Section 4: delivery plan' in titles and 'Measure how long a sign-in lasts' in titles, 'Next: the following steps and an experiment, in today\'s stretches')
ok(pl['free'] == 40 + 290, 'free minutes today (inside work hours, minus buffers)')
act('plan_item', {'key': pl['now']['key'], 'status': 'done'})
ok(P.load()['projects']['p-acme']['targets'][0]['steps'][2]['done'], 'Done on the plan ticks the step on its target')
pl2 = planner.plan_day(P.load(), PROJ, MON, events, WH, now)
ok(pl2['now']['title'] != 'Section 2: pricing' and pl2['done'][0]['title'] == 'Section 2: pricing', 're-planned after Done')
act('plan_item', {'key': pl2['now']['key'], 'status': 'notnow'})
pl3 = planner.plan_day(P.load(), PROJ, MON, events, WH, now)
ok(any(x['key'] == pl2['now']['key'] and x['why'] == 'not now today' for x in pl3['later']), 'Not now: to Later, and it teaches the order')
ok(P.load()['notnow'][pl2['now']['key']] == 1, '… counted')
act('plan_item', {'key': pl2['now']['key'], 'status': None})
act('plan_swap', {'key': pl3['now']['key']})
pl4 = planner.plan_day(P.load(), PROJ, MON, events, WH, now)
ok(pl4['now']['key'] != pl3['now']['key'], 'Swap: the next one takes the stretch')
act('plan_none', {})
pn = planner.plan_day(P.load(), PROJ, MON, events, WH, now)
ok(pn['none'] and pn['now'] is None and pn['next'] == [] and pn['later'] == [], 'None today: an empty plan, nothing nagging')
act('plan_focus', {'projects': ['p-acme']})
long_ev = events + [ev(day, '12:30', '13:30', 'Lunch'), ev(day, '14:40', '17:00', 'Workshop')]
pl5 = planner.plan_day(P.load(), PROJ, MON, long_ev, WH, now,
                       week_slots=[(MON + datetime.timedelta(days=3), [(datetime.datetime(2030, 1, 10, 9, 0), datetime.datetime(2030, 1, 10, 12, 0))])])
lat = {x['title']: x for x in pl5['later']}
ok(lat.get('Final read-through', {}).get('when') == 'Thu 09:00' and lat['Final read-through']['why'] == 'needs 2 h, no 2 h free today',
   'Later: "Thu 09:00 · needs 2 h"')
act('project_entry_update', {'id': 'p-acme', 'target': TA, 'list': 'steps', 'entry': st[3]['id'], 'waits': 'lee@example.com', 'waits_label': "Lee's reply"})
pl6 = planner.plan_day(P.load(), PROJ, MON, events, WH, now)
ok(any(x['title'] == 'Section 4: delivery plan' and x['why'] == "waits for Lee's reply" for x in pl6['later']), "Later: waits for Lee's reply")
ex = planner.plan_day(P.load(), PROJ, MON, events, WH, now, extras=[{'key': 'sprint', 'title': '3 quick replies', 'mins': 15, 'world': 'work', 'first': True}])
ok(ex['now']['key'] == 'sprint', 'what is due anyway (a reply sprint) comes first')

# ---------- the week and the heads-up
act('project_entry_update', {'id': 'p-acme', 'target': TA, 'list': 'steps', 'entry': st[3]['id'], 'waits': None})
busy_week = []
for i in range(5):
    dd = (MON + datetime.timedelta(days=i)).isoformat()
    busy_week += [ev(dd, '09:00', '12:00'), ev(dd, '13:00', '16:30')]
wk = planner.week(P.load(), PROJ, MON, busy_week, WH, now)
ok([x['date'] for x in wk['days']][0] == MON.isoformat() and len(wk['days']) == 7, 'the rest of the week: one entry per day to Sunday')
ok(any(t['title'] == 'Proposal sent to Acme' for t in wk['days'][4]['targets']), 'the target day is marked (Friday)')
hu = wk['heads_up']
ok(hu and hu['text'].startswith('Proposal sent to Acme needs about') and 'more than Mon–Thu give' in hu['text'], 'heads-up when a date target won\'t fit')
act('plan_heads_up', {'key': hu['key'], 'how': 'keep'})
ok(planner.week(P.load(), PROJ, MON, busy_week, WH, now)['heads_up'] is None, 'Keep the plan: no heads-up again this week')
ok(planner.week(P.load(), PROJ, MON, [], WH, now)['heads_up'] is None, 'enough free time: no heads-up')
sat = [x for x in wk['days'] if x['date'] == '2030-01-12'][0]
ok(sat['private'] and not any(it.get('world') == 'work' for it in sat['items']), 'the weekend is private: no work items')
ok(len(planner.week(P.load(), PROJ, MON + datetime.timedelta(days=6), [], WH)['days']) == 8, 'on Sunday: today and the coming week')

# ---------- all targets met → Done suggested; Done closes targets
for x in P.load()['projects']['p-acme']['targets'][0]['steps']:
    act('project_entry_update', {'id': 'p-acme', 'target': TA, 'list': 'steps', 'entry': x['id'], 'done': True})
ok(any(x['kind'] == 'done' and x['text'] == 'All targets met – mark Acme proposal done?' for x in planner.state_suggestions(P.load(), PROJ, MON)),
   'all targets met → "mark … done?"')
act('project_state', {'id': 'p-acme', 'state': 'done'})
ok(all(t['status'] == 'done' for t in P.load()['projects']['p-acme']['targets']), 'Done closes its targets')

# ---------- digest lines and the on/off switch
dg = tempfile.mkdtemp()
name = '2030-01-08-0730.json'
json.dump({'generated': '2030-01-08T07:30:00+01:00', 'items': []}, open(os.path.join(dg, name), 'w'))
r = planner.add_to_digest(P, dg, name, lambda day: {'projects': ['Lighthouse'], 'reason': 'Lighthouse has waited.'}, lambda: [], lambda: [])
it = json.load(open(os.path.join(dg, name)))['items']
ok(r == 1 and it[0]['headline'] == 'What are we working on today? Axella suggests Lighthouse.' and it[0]['link'] == 'plan', 'the morning digest asks the focus question')
ok(planner.add_to_digest(P, dg, name, lambda day: {'projects': ['X'], 'reason': ''}, lambda: [], lambda: []) is None, '… once')
fri = '2030-01-11-1530.json'
json.dump({'generated': '2030-01-11T15:30:00+01:00', 'items': []}, open(os.path.join(dg, fri), 'w'))
planner.add_to_digest(P, dg, fri, lambda day: None, lambda: ['A calmer app: 2 of 5 answered · 1 of 3 go. Still worth pursuing?'], lambda: ['Acme proposal'])
heads = [x['headline'] for x in json.load(open(os.path.join(dg, fri)))['items']]
ok(heads == ['A calmer app: 2 of 5 answered · 1 of 3 go. Still worth pursuing?', 'Acme proposal is done.'], 'the Friday wrap: the monthly check and a calm Done line')
act('plan_settings', {'enabled': False})
n2 = '2030-01-09-0730.json'
json.dump({'generated': '2030-01-09T07:30:00+01:00', 'items': []}, open(os.path.join(dg, n2), 'w'))
ok(planner.add_to_digest(P, dg, n2, lambda day: {'projects': ['X']}, lambda: [], lambda: []) is None and not P.enabled(),
   'switched off: no focus question')
ok(P.load()['projects']['p-lighthouse']['targets'], '… and states, people and targets are kept')
bad(lambda: act('plan_settings', {'buffer': 7}), 'buffer: one of the offered values')
ok(act('plan_settings', {'buffer': 15})['buffer'] == 15, 'buffer editable')

import scheduler  # noqa: E402
ok('state/planner.json' in scheduler.SECRETS, 'planner.json is on the SECRETS list (no Claude run reads it)')

print('all ok' if not fails else '%d failed' % fails)
sys.exit(1 if fails else 0)
