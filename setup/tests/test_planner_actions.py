#!/usr/bin/env python3
"""Targets and Now · Next · Later through the action service (axella-actions.py): owner-only actions and views, the
day plan from the calendar, a project's people with their reasons (a hidden contact left out, a private one without
content), step ideas from what the project already has, and Hold through block_hold with a "Focus: …" title.
Invented projects, people and calendar. Run: python3 setup/tests/test_planner_actions.py"""
import datetime
import importlib.util
import json
import os
import sys
import tempfile
import time

os.environ['TZ'] = 'Europe/Copenhagen'           # the invented calendar is in +01:00 (winter): plan in that time zone
time.tzset()

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
import planner  # noqa: E402
import projects as projects_mod  # noqa: E402
import project_scan  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


tmp = tempfile.mkdtemp()
A.PLAN = planner.Planner(tmp)
A.PROJ = projects_mod.Projects(tmp)
A.PSCAN = project_scan.ProjectMail(tmp)
A.TASKS_FILE = os.path.join(tmp, 'tasks.json')
json.dump([{'id': 't1', 'text': 'Send the stage plan #acme', 'status': 'open'}], open(A.TASKS_FILE, 'w'))
A.config = lambda: {'work_hours': {'days': [0, 1, 2, 3, 4], 'from': '09:00', 'to': '17:00'}}
pa = A.PROJ.action('project_add', {'name': 'Acme proposal', 'tag': 'acme'})
pb = A.PROJ.action('project_add', {'name': 'Lighthouse'})
MON = datetime.date(2030, 1, 7)
EV = [{'start': '2030-01-07T09:00:00+01:00', 'end': '2030-01-07T10:00:00+01:00', 'title': 'Stand-up'},
      {'start': '2030-01-07T11:00:00+01:00', 'end': '2030-01-07T12:00:00+01:00', 'title': 'Call with Kim'}]
A._block_events = lambda a, b: EV
A.sprint_view = lambda: {'items': [{'id': 'x1'}, {'id': 'x2'}]}

ok(set(A.PLAN_ACTIONS) <= A.OWNER_ONLY, 'every planner action is owner only')
A.do_action('project_target_add', {'id': pa, 'kind': 'date', 'title': 'Proposal sent', 'date': '2030-01-11'})
tid = A.PLAN.load()['projects'][pa]['targets'][0]['id']
A.do_action('project_entry_add', {'id': pa, 'target': tid, 'list': 'steps', 'text': 'Draft pricing', 'mins': 45})
A.do_action('project_state', {'id': pb, 'state': 'running'})
try:
    A.do_action('plan_focus', {'projects': [pb]})
    ok(False, 'a Running project can\'t be today\'s focus')
except A.Bad:
    ok(True, 'a Running project can\'t be today\'s focus')
v = A.plan_view(MON, datetime.datetime(2030, 1, 7, 8, 30))
ok(v['enabled'] and v['question']['projects'] == [pa] and not v['chosen'], 'the focus question suggests the Active project with a target')
ok(v['projects'][pb]['state'] == 'running' and v['projects'][pa]['targets'][0]['progress'] == '0 of 1 steps done', 'light per-project state and progress')
A.do_action('plan_focus', {'projects': [pa], 'date': MON.isoformat()})
v = A.plan_view(MON, datetime.datetime(2030, 1, 7, 8, 30))
ok(v['chosen'] and v['plan']['now']['title'] == '2 quick replies' and v['plan']['now']['start'] == '10:10', 'Plan my day: the reply sprint first, after the buffer')
ok(v['plan']['next'][0]['title'] == 'Draft pricing' and v['plan']['next'][0]['start'] == '12:10', '… then the step in the next free stretch')
w = A.plan_week_view(today=MON)
ok(w['enabled'] and len(w['days']) == 7, 'the week view')
A.do_action('plan_settings', {'enabled': False})
ok(A.plan_view(MON) == {'settings': A.PLAN.load()['settings'], 'projects': A.plan_view(MON)['projects'], 'enabled': False}, 'switched off: no question, no plan')
ok(A.plan_week_view(today=MON) == {'enabled': False, 'days': []}, '… and no week')
A.do_action('plan_settings', {'enabled': True})


# ---------- a project's people
class Idx:
    handled = set()
    by_key = {'sam@example.org': [{'channel': 'mail', 'first_seen': '2030-01-05T10:00:00', 'generated': ''}]}

    def last_contact(self, p, unique_name=True):
        return {'whatsapp': '2030-01-06T18:00:00'} if p.get('name') == 'Lee Chen' else {}


class Book:
    def overview(self):
        return {'people': [{'id': 'c1', 'name': 'Lee Chen', 'emails': ['lee@example.com'], 'phones': ['+4500000001']},
                           {'id': 'c2', 'name': 'Robin', 'emails': ['robin@example.org'], 'phones': [], 'private': True},
                           {'id': 'c3', 'name': 'Jamie', 'emails': ['jamie@example.net'], 'phones': [], 'hidden': True}]}


A.BOOK = Book()
A._people_index = lambda: Idx()
A._digest_items_newest = lambda: [{'id': 'i1', 'section': 'p1', 'from': {'name': 'Lee Chen', 'address': 'lee@example.com'}, 'headline': 'Delivery dates'}]
A.PROM.load = lambda: {'items': []}
A.MEET.overview = lambda: [{'id': 'm1', 'title': 'Acme pricing', 'project': pa, 'start': '2099-01-01T10:00:00+01:00',
                            'attendees': [{'name': 'Robin', 'email': 'robin@example.org'}, {'name': 'Jamie', 'email': 'jamie@example.net'}]}]
A.NOTES.list = lambda *a, **k: []
A.mail_privacy = lambda addrs: ('private', 'Robin') if 'robin@example.org' in addrs else ('hidden', None) if 'jamie@example.net' in addrs else (None, None)
A.do_action('project_person_add', {'id': pa, 'key': 'Lee@Example.com', 'name': 'Lee Chen', 'role': 'Client'})
pv = A.project_plan_view(pa)
ppl = {x['key']: x for x in pv['people']}
ok(ppl['lee@example.com']['source'] == 'manual' and ppl['lee@example.com']['role'] == 'Client' and ppl['lee@example.com']['to_answer'] == 1
   and ppl['lee@example.com']['last'] == {'whatsapp': '2030-01-06T18:00:00'} and ppl['lee@example.com']['phones'] == ['+4500000001'],
   'a manual person: role, last contact, one to answer, a phone for Message and Call')
ok(ppl['robin@example.org']['source'] == 'auto' and ppl['robin@example.org']['why'] == 'On your Acme pricing prep' and ppl['robin@example.org']['private'],
   'an auto person with its reason; a private contact is marked')
ok('jamie@example.net' not in ppl, 'a hidden contact is never shown')
ok(not any('headline' in x or 'title' in x for x in pv['people']), 'no message text in the people list')
ok([x['text'] for x in pv['step_ideas']] == ['Send the stage plan', 'Prepare: Acme pricing'], 'step ideas from a tagged task and an upcoming prep')
ok(pv['targets'][0]['progress'] == '0 of 1 steps done', 'targets with their progress')

# ---------- Hold: block_hold with a "Focus: …" title, Protect your blocks untouched
seen = {}
A._block_calendars = lambda: ['Work']


class CV:
    @staticmethod
    def edit(mcp, cals, action, p, backup, cache_file=None):
        seen.update(action=action, p=p)
        return {'id': 'ev1', 'title': p['title']}


sys.modules['calendar_view'] = CV
A.RUNNER.mcp_file = lambda: None
r = A.do_action('plan_hold', {'date': '2030-01-07', 'start': '12:10', 'end': '12:55', 'label': 'Draft pricing'})
ok(seen['action'] == 'cal_add' and seen['p']['title'] == 'Focus: Draft pricing' and r['id'] == 'ev1', 'Hold: one busy event "Focus: Draft pricing", its id for Undo')
ok('2030-01-07' not in A.BLOCKS.load()['shown'], '… and Protect your blocks still offers its own suggestion that day')

print('all ok' if not fails else '%d failed' % fails)
sys.exit(1 if fails else 0)
