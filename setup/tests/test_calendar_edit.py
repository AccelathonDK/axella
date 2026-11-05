#!/usr/bin/env python3
"""Calendar editing (owner only): own events only (no other attendees), move only within one account, a copy before
every delete and Restore from it, "this / all future" for repeating events, and nothing done when Macuse's argument
shapes aren't understood. A fake Macuse – fictional events. Run: python3 setup/tests/test_calendar_edit.py"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import calendar_view as CV  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


REF = {'$defs': {'EventReference': {'type': 'object', 'properties': {'id': {'type': 'string'}, 'occurrence_date': {'type': 'string'}}},
                 'EventScope': {'type': 'string', 'enum': ['this_event', 'future_events']},
                 'ShiftStrategy': {'oneOf': [{'type': 'object', 'properties': {'type': {'const': 'absolute'}, 'start_date': {}, 'end_date': {}}},
                                             {'type': 'object', 'properties': {'type': {'const': 'offset'}, 'minutes': {}}}]}}}
TOOLS = [
    {'name': 'calendar_create_event', 'inputSchema': {'properties': {'title': {}, 'start_date': {}}}},
    {'name': 'calendar_update_event', 'inputSchema': {**REF, 'properties': {'event': {'$ref': '#/$defs/EventReference'}, 'scope': {'$ref': '#/$defs/EventScope'}}}},
    {'name': 'calendar_reschedule_event', 'inputSchema': {**REF, 'properties': {'event': {'$ref': '#/$defs/EventReference'},
                                                                                 'scope': {'$ref': '#/$defs/EventScope'}, 'strategy': {'$ref': '#/$defs/ShiftStrategy'}}}},
    {'name': 'calendar_cancel_event', 'inputSchema': {**REF, 'properties': {'event': {'$ref': '#/$defs/EventReference'}, 'scope': {'$ref': '#/$defs/EventScope'}}}},
]
CALS = [{'title': 'Home', 'source': 'iCloud', 'can_modify': True}, {'title': 'Work', 'source': 'iCloud', 'can_modify': True},
        {'title': 'Calendar', 'source': 'Exchange', 'can_modify': True}, {'title': 'Birthdays', 'source': 'Other', 'can_modify': False}]
EVENTS = [
    {'id': 'mine', 'title': 'Dentist', 'calendar_title': 'Home', 'start_date': '2026-11-10T09:00:00+01:00', 'end_date': '2026-11-10T10:00:00+01:00',
     'attendees': [], 'is_recurring': False},
    {'id': 'meet', 'title': 'Acme review', 'calendar_title': 'Calendar', 'start_date': '2026-11-10T13:00:00+01:00', 'end_date': '2026-11-10T14:00:00+01:00',
     'attendees': [{'is_current_user': True}, {'is_current_user': False, 'name': 'Lee Chen'}], 'is_recurring': False},
    {'id': 'gym', 'title': 'Gym', 'calendar_title': 'Home', 'start_date': '2026-11-10T18:00:00+01:00', 'end_date': '2026-11-10T19:00:00+01:00',
     'attendees': [], 'is_recurring': True, 'recurrence': {'frequency': 'weekly'}},
]


class Fake:
    def __init__(self, tools=TOOLS):
        self.tools, self.calls = tools, []

    def request(self, method, params):
        if method == 'tools/list':
            return {'tools': self.tools}
        name, args = params['name'], params['arguments']
        self.calls.append((name, args))
        data = {'calendar_list_calendars': {'calendars': CALS}, 'calendar_search_events': {'events': EVENTS},
                'calendar_create_event': {'event': {'id': 'new1'}}}.get(name, {})
        return {'content': [{'type': 'text', 'text': json.dumps({'data': data})}]}


def run(action, p, fake=None):
    CV._schema_cache.clear()
    f = fake or Fake()
    try:
        return CV.edit('/x', [], action, p, bk, client=f), f
    except CV.CalendarError as e:
        return e, f


bk = tempfile.mkdtemp()
writes = lambda f: [c for c, _ in f.calls if c not in ('calendar_list_calendars', 'calendar_search_events')]

r, f = run('cal_add', {'title': 'Lunch with Sam', 'start': '2026-11-11T12:00:00+01:00', 'end': '2026-11-11T13:00:00+01:00', 'calendar': 'Home'})
ok(isinstance(r, dict) and r['id'] == 'new1' and writes(f) == ['calendar_create_event'], 'add an event to Home')
ok('attendees' not in f.calls[-1][1] and 'invitees' not in f.calls[-1][1], 'no invitees are ever sent')
r, f = run('cal_add', {'title': 'x', 'start': '2026-11-11T12:00:00+01:00', 'end': '2026-11-11T13:00:00+01:00', 'calendar': 'Birthdays'})
ok(isinstance(r, CV.CalendarError) and not writes(f), 'a read-only calendar is refused')
r, f = run('cal_update', {'id': 'meet', 'start': '2026-11-10T13:00:00+01:00', 'title': 'Changed'})
ok(isinstance(r, CV.CalendarError) and 'other people' in str(r) and not writes(f), 'a meeting with other attendees is read only')
r, f = run('cal_update', {'id': 'mine', 'start': '2026-11-10T09:00:00+01:00', 'calendar': 'Work'})
ok(isinstance(r, dict) and f.calls[-1][1].get('calendar') == 'Work', 'move Home → Work (same iCloud account)')
r, f = run('cal_update', {'id': 'mine', 'start': '2026-11-10T09:00:00+01:00', 'calendar': 'Calendar'})
ok(isinstance(r, CV.CalendarError) and 'same account' in str(r) and not writes(f), 'move iCloud → Exchange refused')
r, f = run('cal_update', {'id': 'gym', 'start': '2026-11-10T18:00:00+01:00', 'scope': 'future',
                          'new_start': '2026-11-10T19:00:00+01:00', 'new_end': '2026-11-10T20:00:00+01:00'})
res = [a for c, a in f.calls if c == 'calendar_reschedule_event']
ok(isinstance(r, dict) and res and res[0]['scope'] == 'future_events' and res[0]['strategy'] == {
    'type': 'absolute', 'start_date': '2026-11-10T19:00:00+01:00', 'end_date': '2026-11-10T20:00:00+01:00'}, 'repeating: all future, moved to 19:00')
ok(res and res[0]['event'] == {'id': 'gym', 'occurrence_date': '2026-11-10T18:00:00+01:00'}, 'the occurrence is named by id and start')
r, f = run('cal_delete', {'id': 'mine', 'start': '2026-11-10T09:00:00+01:00'})
ok(isinstance(r, dict) and r.get('backup') and writes(f) == ['calendar_cancel_event'], 'delete: one cancel after the copy')
saved = json.load(open(os.path.join(bk, r['backup'] + '.json')))
ok(saved['event']['title'] == 'Dentist' and oct(os.stat(os.path.join(bk, r['backup'] + '.json')).st_mode)[-3:] == '600', 'the copy is kept, chmod 600')
r2, f = run('cal_restore', {'backup': r['backup']})
ok(isinstance(r2, dict) and f.calls[-1][0] == 'calendar_create_event' and f.calls[-1][1]['title'] == 'Dentist', 'restore re-creates it')
broken = [dict(t) for t in TOOLS]
broken[3] = {'name': 'calendar_cancel_event', 'inputSchema': {'properties': {'event': {'type': 'integer'}}}}
r, f = run('cal_delete', {'id': 'mine', 'start': '2026-11-10T09:00:00+01:00'}, Fake(broken))
ok(isinstance(r, CV.CalendarError) and not writes(f), 'an event shape Macuse names differently: nothing is done')
CV._schema_cache.clear()
c = CV.caps('/x', client=Fake())
ok(c['can_edit'] and {x['title'] for x in c['calendars'] if x['can_modify']} == {'Home', 'Work', 'Calendar'}, 'caps: editable calendars listed')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
