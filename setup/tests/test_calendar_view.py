#!/usr/bin/env python3
"""Calendar page: events read through Macuse (MCP, paginated), shaped for the dashboard with Work/Private from the
calendar settings; ranges are checked. A fake MCP client – no Macuse, fictional events.
Run: python3 setup/tests/test_calendar_view.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import calendar_view as CV  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def ev(i, cal, start, **kw):
    return {'id': 'e%d' % i, 'title': 'Event %d' % i, 'calendar_title': cal, 'start_date': start, 'end_date': start,
            'is_all_day': False, 'attendees': [{'is_current_user': True}, {'is_current_user': False}],
            'deep_link': 'ical://ekevent/x', **kw}


class Fake:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def request(self, method, params):
        self.calls.append(params['arguments'])
        page = params['arguments']['offset'] // CV.PAGE
        evs, more = self.pages[page]
        return {'content': [{'type': 'resource_link'}, {'type': 'text', 'text': '[Resource link] ui://x' + json.dumps(
            {'data': {'events': evs, 'pagination': {'has_more': more}}})}]}


cals = [{'name': 'Home', 'label': 'Home (iCloud)', 'kind': 'private'}, {'name': 'Calendar', 'label': 'Acme', 'kind': 'work'}]
f = Fake([([ev(1, 'Home', '2026-11-04T09:00:00+01:00'), ev(2, 'Calendar', '2026-11-04T08:00:00+01:00')], True),
          ([ev(3, 'Shared', '2026-11-05T10:00:00+01:00', deep_link='javascript:x'), ev(1, 'Home', '2026-11-04T09:00:00+01:00')], False)])
r = CV.events('/nonexistent', cals, '2026-11-04', '2026-11-11', client=f)
ok(len(f.calls) == 2 and f.calls[1]['offset'] == CV.PAGE, 'paginated until has_more is false')
ok([e['id'] for e in r['events']] == ['e2', 'e1', 'e3'], 'sorted by start, a repeated occurrence only once')
by = {e['id']: e for e in r['events']}
ok(by['e2']['ctx'] == 'work' and by['e2']['calendar_label'] == 'Acme' and by['e1']['ctx'] == 'private', 'Work/Private from the calendar settings')
ok(by['e3']['ctx'] is None, 'a calendar not in the settings: shown under both')
ok(by['e1']['attendees'] == 1, 'attendees counted without you')
ok(by['e3']['deep_link'] is None and by['e1']['deep_link'].startswith('ical://'), 'only ical:// links are passed on')
for a, b in (('2026-11-10', '2026-11-04'), ('2026-01-01', '2026-06-01'), ('x', 'y')):
    try:
        CV.events('/nonexistent', cals, a, b, client=Fake([([], False)]))
        ok(False, 'refused: %s → %s' % (a, b))
    except CV.CalendarError:
        ok(True, 'refused: %s → %s' % (a, b))

# ---- fix round 7, P2-2: what counts as a meeting
work, home = {'kind': 'work'}, {'kind': 'private'}
me = {'is_current_user': True, 'email': 'alex@example.com'}
fam = [me, {'is_current_user': False, 'email': 'robin@example.org'}, {'is_current_user': False, 'email': 'jamie@example.org'}]
mk = lambda **kw: dict({'title': 'x', 'attendees': [], 'notes': None, 'url': None, 'location': None}, **kw)
ok(CV.meeting_kind(mk(attendees=[me, {'is_current_user': False, 'email': 'lee@acme.example'}]), work) == 'people', 'work: other attendees make a meeting')
ok(CV.meeting_kind(mk(notes='Join: https://meet.google.com/abc-defg-hij'), work) == 'join', 'a Meet link with no attendee list is a meeting')
for link in ('https://teams.microsoft.com/l/meetup-join/19%3a', 'https://acme.zoom.us/j/123456', 'https://acme.webex.com/meet/lee'):
    ok(CV.meeting_kind(mk(location=link), home) == 'join', 'a join link counts, also in a private calendar: ' + link.split('/')[2])
ok(CV.meeting_kind(mk(organizer={'is_current_user': False, 'email': 'sam@rivera.example'}), work) == 'invite', 'an invitation from someone else is a meeting')
ok(CV.meeting_kind(mk(title='Lunch'), work) is None, 'nobody else, no link, no invitation: not a meeting')
ok(CV.meeting_kind(mk(title="Kid's daily reading", attendees=fam, organizer=me), home) is None, 'a family event in a private calendar is not a meeting')
fam_cfg = {'kind': 'private', 'family': ['robin@example.org', 'jamie@example.org']}
ok(CV.meeting_kind(mk(attendees=fam), fam_cfg) is None, '… nor with the family listed')
ok(CV.meeting_kind(mk(attendees=fam + [{'is_current_user': False, 'email': 'kim@example.org'}]), fam_cfg) == 'people',
   'a private calendar counts with an attendee outside the family')
ok(CV.meeting_kind(mk(attendees=fam, organizer={'is_current_user': False, 'email': 'robin@example.org'}), home) is None,
   'a family event someone else put in a private calendar (no family list) is not a meeting')
ok(CV.meeting_kind(mk(attendees=fam + [{'is_current_user': False, 'email': 'kim@example.org'}]), home) is None,
   'a private calendar without a family list: people alone never make a meeting')
ok(CV.meeting_kind(mk(attendees=fam), {'kind': 'private', 'meetings': True}) == 'people', '"meetings": true makes a private calendar count')
ok(CV.meeting_kind(mk(attendees=fam, organizer={'is_current_user': False, 'email': 'robin@example.org'}), fam_cfg) is None,
   'an invitation from family in a private calendar is not a meeting')
ok(CV.meeting_kind(mk(attendees=[me, {'is_current_user': False, 'email': 'lee@acme.example'}]), {'kind': 'work', 'meetings': False}) is None,
   '"meetings": false turns a calendar off')
r = CV.shape(dict(ev(9, 'Calendar', '2026-11-05T09:00:00+01:00'), attendees=[], notes='https://meet.google.com/abc-defg-hij'), {'Calendar': {'kind': 'work'}})
ok(r['meeting'] == 'join' and r['join'].startswith('https://meet.google.com/'), 'shape() says whether and why an event is a meeting')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
