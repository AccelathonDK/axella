#!/usr/bin/env python3
"""Calendar → invitees and online meetings, per calendar (setup/calendar_online.py): which calendar sends invites how and
from which account, protected workplaces, the confirm words, a meeting on an event without invitees.
Stubbed services; invented people and calendars only. Run: python3 setup/tests/test_calendar_online.py"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import calendar_invites as CI  # noqa: E402
import calendar_online as CO  # noqa: E402
import meeting_providers as MP  # noqa: E402
import oauth_flow as O  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def bad(fn, label, word=''):
    try:
        fn()
        ok(False, label)
    except O.Bad as e:
        ok(word.lower() in str(e).lower(), label + ('' if word.lower() in str(e).lower() else ' (said: %s)' % e))


class Auth:
    def __init__(self):
        self.st = {'teams': {'state': 'connected', 'account': 'alex@acme.example'}, 'zoom': {'state': 'connected', 'account': 'alex@example.com'},
                   'google_meet': {'state': 'not_connected'}}

    def status(self, k):
        return dict(self.st[k], label=k)

    def access_token(self, k):
        return 'tok'

    def set_approval(self, k, s):
        pass


made = []


def http(method, url, headers=None, body=None, form=None):
    made.append((method, url, body))
    if url.endswith('/users/me/meetings'):
        return 201, {'id': 1, 'join_url': 'https://acme.zoom.us/j/1', 'password': body['password'], 'settings': {'waiting_room': True}}
    if '/meetings/' in url:
        return 204, {}
    return 404, {}


class Inv:
    class caldav:
        ready = True

        @classmethod
        def configured(cls):
            return cls.ready

    def __init__(self):
        self.sent, self.recs = [], {}

    def send(self, idem, path, cal, org, title, start, end, tz, people, loc, notes, join, meeting_key=None, teams=False, dashboard_url=None):
        rec = {'uid': 'U%d' % len(self.sent), 'idem': idem, 'path': path, 'calendar': cal, 'organizer': org, 'attendees': people,
               'join': join, 'meeting': meeting_key, 'teams': teams, 'title': title}
        self.sent.append(rec)
        self.recs[rec['uid']] = rec
        return rec

    def get(self, uid):
        return self.recs.get(uid)

    def update(self, uid, title, start, end, tz, people, loc, notes, tell=True):
        self.recs[uid].update(tell=tell, title=title)
        return self.recs[uid]

    def cancel(self, uid, comment=''):
        self.recs[uid]['cancelled'] = True
        return self.recs[uid]


auth = Auth()
svc = MP.Services(tempfile.mkdtemp(), auth, http)
inv = Inv()
MAC = [{'title': 'Home', 'source': 'iCloud', 'can_modify': True}, {'title': 'Calendar', 'source': 'Exchange', 'can_modify': True},
       {'title': 'Client', 'source': 'Exchange', 'can_modify': True}, {'title': 'Birthdays', 'source': 'Other', 'can_modify': False}]
PROF = [{'name': 'Home', 'kind': 'private'}, {'name': 'Calendar', 'kind': 'work'}, {'name': 'Client', 'kind': 'work', 'workplace': 'robin'}]
WPS = [{'id': 'robin', 'domains': ['robin.example'], 'protected': True}]
ACC = {'iCloud': {'kind': 'private', 'address': 'alex@example.com'}, 'Exchange': {'kind': 'work', 'address': 'alex@acme.example'}}
on = CO.Online(svc, inv, lambda: PROF, lambda: WPS, lambda: ACC, lambda: MAC, lambda: {'alex@example.com', 'alex@acme.example'},
               lambda: 'https://mini.tailnet-example.ts.net/axella')
cals = {c['title']: c for c in on.calendars()}
ok(set(cals) == {'Home', 'Calendar', 'Client'}, 'only calendars that can be changed')
ok(cals['Home']['path'] == 'icloud' and cals['Home']['from'] == 'alex@example.com', 'iCloud calendar: iCloud sends, from your iCloud address')
ok(cals['Calendar']['path'] == 'graph' and cals['Calendar']['from'] == 'alex@acme.example', 'work calendar: Exchange sends, from the Teams account')
ok(cals['Client']['path'] is None and 'another account' in cals['Client']['why'], 'a protected workplace: not from another account')
ok(not any(s['offered'] for s in cals['Client']['services']), '… and no meeting service connected with another account')
hs = {s['key']: s for s in cals['Home']['services']}
ok(not hs['teams']['offered'] and hs['zoom']['offered'] and not hs['google_meet']['offered'], 'Home: Zoom yes, Teams no (work only), Meet not connected')
Inv.caldav.ready = False
ok('Set up iCloud invites' in {c['title']: c for c in on.calendars()}['Home']['why'], 'iCloud not set up: says how')
Inv.caldav.ready = True
auth.st['teams'] = {'state': 'needs_approval', 'why': 'x'}
ok('IT' in {c['title']: c for c in on.calendars()}['Calendar']['why'], 'Teams waiting for IT: the work calendar says so')
auth.st['teams'] = {'state': 'connected', 'account': 'alex@acme.example'}
svc.set_default('Calendar', 'teams')
ok({c['title']: c for c in on.calendars()}['Calendar']['default'] == 'teams' and {c['title']: c for c in on.calendars()}['Home']['default'] is None,
   'the per-calendar default (only where offered)')

P = {'calendar': 'Calendar', 'title': 'Acme planning', 'start': '2027-03-04T10:00:00+01:00', 'end': '2027-03-04T10:30:00+01:00',
     'tz': 'Europe/Copenhagen', 'attendees': [{'email': 'lee@example.com', 'name': 'Lee Chen'}, 'sam@example.net', 'alex@acme.example'],
     'online': {'kind': 'provider', 'provider': 'teams'}, 'send_id': 'a1b2c3d4e5f60718', 'confirm': 'send'}
bad(lambda: on.send(dict(P, confirm=None)), 'nothing is sent without the tap', 'confirmation')
bad(lambda: on.send(dict(P, send_id='x')), 'a send_id is needed', 'send_id')
r = on.send(dict(P))
s0 = inv.sent[-1]
ok(s0['path'] == 'graph' and s0['teams'] and s0['join'] is None and [a['email'] for a in s0['attendees']] == ['lee@example.com', 'sam@example.net'],
   'work + Teams: one Exchange event makes the meeting; your own address isn\'t invited')
ok(not made, '… and no separate meeting is made')
r2 = on.send(dict(P, calendar='Home', online={'kind': 'provider', 'provider': 'zoom'}, send_id='b1b2c3d4e5f60718'))
s1 = inv.sent[-1]
ok(s1['path'] == 'icloud' and s1['join']['join_url'] == 'https://acme.zoom.us/j/1' and s1['meeting'] == 'b1b2c3d4e5f60718', 'Home + Zoom: a Zoom meeting, its link in the iCloud invite')
bad(lambda: on.send(dict(P, calendar='Home', send_id='c1b2c3d4e5f60718')), 'Teams on the private calendar is refused', 'isn\'t available')
bad(lambda: on.send(dict(P, calendar='Client', send_id='d1b2c3d4e5f60718')), 'a protected workplace from another account is refused', 'another account')
r3 = on.send(dict(P, calendar='Home', online={'kind': 'link', 'url': 'https://facetime.apple.com/join#v=1'}, send_id='e1b2c3d4e5f60718'))
ok(inv.sent[-1]['join'] == {'join_url': 'https://facetime.apple.com/join#v=1', 'provider': 'link'}, 'a pasted FaceTime link')
bad(lambda: on.send(dict(P, calendar='Home', online={'kind': 'link', 'url': 'https://example.com/x'}, send_id='f1b2c3d4e5f60718')), 'a pasted unknown link is refused', 'meeting service')
bad(lambda: on.send(dict(P, attendees=['alex@acme.example'], send_id='a2b2c3d4e5f60718')), 'only yourself: nothing to send', 'add someone')
bad(lambda: on.send(dict(P, all_day=True, send_id='a3b2c3d4e5f60718')), 'no all-day invitations', 'all-day')

bad(lambda: on.update({'uid': r['uid']}), 'a change needs its own tap', 'confirmation')
u = on.update(dict(P, uid=r2['uid'], confirm='save', move_meeting=True, start='2027-03-04T11:00:00+01:00', end='2027-03-04T11:30:00+01:00'))
ok(inv.recs[r2['uid']]['tell'] is False and u['meeting_moved'] and made[-1][0] == 'PATCH', 'Save without telling them; the Zoom meeting moved on tap')
c = on.cancel({'uid': r2['uid'], 'confirm': 'send', 'delete_meeting': True})
ok(inv.recs[r2['uid']]['cancelled'] and c['meeting']['deleted'] and made[-1][0] == 'DELETE', 'Send cancellation, and Also delete the online meeting')
bad(lambda: on.cancel({'uid': r['uid']}), 'a cancellation needs its own tap', 'confirmation')

j = on.add_meeting(dict(P, calendar='Home', attendees=[], online={'kind': 'provider', 'provider': 'zoom'}, send_id='a4b2c3d4e5f60718'))
ok(j['join_url'].startswith('https://acme.zoom.us/'), 'no invitees: a meeting link for the event itself')
bad(lambda: on.add_meeting(dict(P, calendar='Home', online={'kind': 'provider', 'provider': 'teams'}, send_id='a5b2c3d4e5f60718')),
    'no Teams on a private calendar', 'work calendar')
ok(on.add_meeting(dict(P, online={'kind': 'none'}, send_id='a6b2c3d4e5f60718')) is None, 'no meeting chosen: none made')

print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
