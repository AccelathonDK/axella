#!/usr/bin/env python3
"""Calendar – invitees and online meetings (setup/oauth_flow.py, meeting_providers.py, calendar_invites.py).
Every service call is stubbed; invented people, titles and times only. Run: python3 setup/tests/test_calendar_invites.py"""
import json
import os
import re
import sys
import tempfile
import urllib.parse

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import oauth_flow as O  # noqa: E402
import meeting_providers as MP  # noqa: E402
import calendar_invites as CI  # noqa: E402

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


class KC:
    def __init__(self):
        self.d = {}

    def get(self, s, a):
        v = self.d.get((s, a))
        return json.loads(v) if v else None

    def set(self, s, a, v):
        self.d[(s, a)] = json.dumps(v)

    def delete(self, s, a):
        self.d.pop((s, a), None)


class Clock:
    t = 1_800_000_000.0

    def __call__(self):
        return self.t


REDIRECT = 'https://mini.tailnet-example.ts.net/axella/api/oauth_callback'
kc, clock, calls, notes = KC(), Clock(), [], []


def http(method, url, headers=None, body=None, form=None):
    calls.append({'method': method, 'url': url, 'headers': headers or {}, 'body': body, 'form': form})
    if form is not None:
        if form.get('code') == 'bad':
            return 400, {'error': 'invalid_grant'}
        return 200, {'access_token': 'at-%d' % len(calls), 'refresh_token': 'rt-1', 'expires_in': 3600}
    if url.endswith('/me/onlineMeetings') and method == 'POST':
        return 201, {'id': 'tm-1', 'joinWebUrl': 'https://teams.microsoft.com/l/meetup-join/invented', 'joinMeetingIdSettings':
                     {'joinMeetingId': '000 000 000', 'passcode': 'abc123'}, 'audioConferencing': {'tollNumber': '+45 00 00 00 01'}}
    if '/onlineMeetings' in url and method in ('PATCH', 'DELETE'):
        return 204, {}
    if url.endswith('/spaces'):
        return 200, {'name': 'spaces/invented', 'meetingUri': 'https://meet.google.com/abc-defg-hij', 'meetingCode': 'abc-defg-hij'}
    if url.endswith('/users/me/meetings'):
        return 201, {'id': 81234567890, 'join_url': 'https://acme.zoom.us/j/81234567890?pwd=x', 'password': body['password'],
                     'settings': {'waiting_room': True}}
    if '/meetings/' in url:
        return 204, {}
    return 404, {}


auth = O.OAuth(kc, http, clock, note=lambda *a: notes.append(a))

# ---- OAuth: PKCE and state
bad(lambda: auth.start('teams', REDIRECT), 'not set up: Connect says so', 'not set up')
for k in O.PROVIDERS:
    kc.set(O.APP_SERVICE, k, {'client_id': 'cid-' + k, 'client_secret': 'sec-' + k})
bad(lambda: auth.start('teams', 'http://mini.local/api/oauth_callback'), 'only the https dashboard address', 'https')
url = auth.start('teams', REDIRECT)
q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
ok(url.startswith('https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize?') and q['code_challenge_method'] == 'S256'
   and len(q['state']) >= 40 and q['redirect_uri'] == REDIRECT and 'OnlineMeetings.ReadWrite' in q['scope'] and 'Mail' not in q['scope'],
   'Teams sign-in: PKCE S256, a long state, the smallest scopes (no mail)')
bad(lambda: auth.callback('made-up-state', 'code'), 'an unknown state is refused', 'unknown')
auth.callback(q['state'], 'code-1')
tf = calls[-1]['form']
ok(tf['code_verifier'] and tf['redirect_uri'] == REDIRECT and tf['client_secret'] == 'sec-teams', 'the code is exchanged with the verifier')
ok(auth.status('teams')['state'] == 'connected' and kc.get(O.TOKEN_SERVICE, 'teams')['refresh_token'] == 'rt-1', 'tokens in the Keychain: connected')
bad(lambda: auth.callback(q['state'], 'code-1'), 'a state works once', 'unknown')
q2 = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(auth.start('zoom', REDIRECT)).query))
clock.t += 700
bad(lambda: auth.callback(q2['state'], 'code'), 'a sign-in older than 10 minutes is refused', 'too old')
q3 = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(auth.start('teams', REDIRECT)).query))
bad(lambda: auth.callback(q3['state'], None, 'access_denied', 'AADSTS90094: Admin approval required'), 'the work tenant needs IT: says so', 'IT')
ok(auth.status('teams')['state'] == 'needs_approval' and 'IT' in auth.status('teams')['why'], '… and Teams shows "Waiting for your IT"')
q4 = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(auth.start('teams', REDIRECT)).query))
auth.callback(q4['state'], 'code-2')
ok(auth.status('teams')['state'] == 'connected', 'approved later: connected again')
clock.t += 4000
n = len(calls)
tok = auth.access_token('teams')
ok(len(calls) == n + 1 and calls[-1]['form']['grant_type'] == 'refresh_token' and tok.startswith('at-'), 'an expired token is refreshed')
q5 = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(auth.start('zoom', REDIRECT)).query))
auth.callback(q5['state'], 'code-z')
ok(calls[-1]['headers'].get('Authorization', '').startswith('Basic ') and 'client_secret' not in calls[-1]['form'], 'Zoom: the client in a Basic header')
q6 = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(auth.start('google_meet', REDIRECT)).query))
ok('meetings.space.created' in q6['scope'] and q6.get('access_type') == 'offline', 'Google: the Meet scope only, offline access')
auth.callback(q6['state'], 'code-g')

# ---- one shared suite for every provider
st = tempfile.mkdtemp()
svc = MP.Services(st, auth, http, note=lambda *a: notes.append(a))
START, END, TZ = '2027-03-04T10:00:00+01:00', '2027-03-04T10:30:00+01:00', 'Europe/Copenhagen'
for key in ('teams', 'google_meet', 'zoom'):
    p = svc.provider(key)
    cap = p.capabilities()
    ok(set(cap) == {'lobby', 'passcode', 'has_time', 'dial_in', 'can_send_invites'} and cap['lobby'], '%s: capabilities, lobby on' % key)
    n = len(calls)
    m = svc.create_once('key-%s-0001' % key, key, 'Acme planning', START, END, TZ)
    sent = [c for c in calls[n:]]
    ok(m['join_url'].startswith('https://') and m.get('meeting_id'), '%s: a new meeting with a join link' % key)
    blob = json.dumps([c['body'] for c in sent])
    ok('Acme planning' in blob or key == 'google_meet', '%s: the title is sent' % key)
    ok(not re.search(r'notes|location|attendee|lee@|example\.com', blob, re.I), '%s: nothing beyond title and times' % key)
    ok(all(c['headers'].get('Authorization', '').startswith('Bearer ') for c in sent), '%s: with its own token' % key)
    again = svc.create_once('key-%s-0001' % key, key, 'Acme planning', START, END, TZ)
    ok(again.get('repeat') and again['join_url'] == m['join_url'] and len(calls) == n + len(sent), '%s: a double tap makes no second meeting' % key)
    m2 = svc.create_once('key-%s-0002' % key, key, 'Acme planning', START, END, TZ)
    ok(m2['meeting_id'] and len(calls) > n + len(sent), '%s: a second event gets its own meeting' % key)
    mv = svc.move('key-%s-0001' % key, 'Acme planning', '2027-03-04T11:00:00+01:00', '2027-03-04T11:30:00+01:00', TZ)
    ok(mv['updated'] == cap['has_time'], '%s: moving updates the time where the service has one' % key)
    rm = svc.remove('key-%s-0001' % key)
    ok(rm['deleted'] or rm.get('why'), '%s: delete (or why it can\'t)' % key)
tc = [c for c in calls if '/onlineMeetings/' in c['url'] and c['method'] == 'PATCH' and c['body'] and 'lobbyBypassSettings' in c['body']]
ok(tc and tc[0]['body']['lobbyBypassSettings']['scope'] == 'organizer', 'Teams: the lobby is set for everyone but you')
zc = next(c for c in calls if c['url'].endswith('/users/me/meetings'))
ok(zc['body']['settings']['waiting_room'] and len(zc['body']['password']) == 10 and zc['body']['start_time'] == '2027-03-04T09:00:00Z'
   and zc['body']['duration'] == 30, 'Zoom: waiting room, a passcode, the time in UTC and the length')
gc = next(c for c in calls if c['url'].endswith('/spaces'))
ok(gc['body'] == {'config': {'accessType': 'TRUSTED'}}, 'Meet: a space for trusted people only – nothing else sent')
ok(all(n_[0] in ('teams', 'google_meet', 'zoom') for n_ in notes), 'every call is counted under What leaves my home')
bad(lambda: svc.create_once('x', 'zoom', 'T', START, END, TZ), 'a request key is required', 'key')

# ---- which services a calendar is offered
ok([o['offered'] for o in svc.offered('work')] == [True, True, True], 'work calendar: every connected service')
pv = {o['key']: o for o in svc.offered('private')}
ok(not pv['teams']['offered'] and 'work account' in pv['teams']['why'] and pv['zoom']['offered'], 'private calendar: no Teams (work accounts only)')
ok([o['key'] for o in svc.offered('work', allowed={'teams'}) if o['offered']] == ['teams'], 'a protected workplace: only services on its own account')
auth.disconnect('zoom')
ok(not {o['key']: o for o in svc.offered('work')}['zoom']['offered'] and kc.get(O.TOKEN_SERVICE, 'zoom') is None,
   'disconnected: not offered, the tokens are gone from the Keychain')
svc.set_default('Work', 'teams')
ok(svc.load()['defaults'] == {'Work': 'teams'}, 'a default service per calendar')
bad(lambda: svc.set_default('Work', 'jitsi'), 'only a known service', 'unknown')
ok(oct(os.stat(svc.file).st_mode & 0o777) == '0o600', 'online-meetings.json is private (600)')

# ---- Paste a link
ok(MP.check_link(' https://teams.microsoft.com/l/meetup-join/x ') == 'https://teams.microsoft.com/l/meetup-join/x', 'a Teams link')
ok(MP.check_link('https://acme.zoom.us/j/123') and MP.check_link('https://facetime.apple.com/join#v=1') and MP.check_link('https://meet.google.com/abc'),
   'Zoom, FaceTime, Meet links')
for u in ('http://meet.google.com/abc', 'https://meet.google.com.evil.example/x', 'https://user:pw@acme.zoom.example/j/1', 'https://example.com/meet',
          'javascript:alert(1)', 'https://zoom.us/j/1"onmouseover=x'):
    bad(lambda u=u: MP.check_link(u), 'refused: %s' % u[:40])
ok(MP.service_of('https://acme.zoom.us/j/1') == 'Zoom', 'the service shown for a link')

# ---- the invitation itself (iCalendar)
ORG = {'email': 'alex@example.com', 'name': 'Alex Example'}
PEOPLE = CI.people([{'email': 'lee@example.com', 'name': 'Lee Chen'}, 'sam@example.net', 'LEE@example.com'], own=['alex@example.com'])
ok([p['email'] for p in PEOPLE] == ['lee@example.com', 'sam@example.net'], 'each person once')
bad(lambda: CI.people(['Lee <lee@example.com>']), 'only plain addresses')
bad(lambda: CI.people(['noreply@example.com']), 'no no-reply addresses')
ok(CI.people(['alex@example.com'], own=['alex@example.com']) == [], 'you are not invited to your own event')
join = {'join_url': 'https://teams.microsoft.com/l/meetup-join/invented', 'passcode': 'abc123', 'code': '000 000 000'}
ics = CI.event_ics('UID-1', 0, 'Acme planning; budget', START, END, TZ, ORG, PEOPLE, 'Room 2', 'Bring the brief', join,
                   'https://mini.tailnet-example.ts.net/axella/?v=calendar&invite=UID-1', method='REQUEST')
un = re.sub(r'\r\n[ \t]', '', ics)
ok('METHOD:REQUEST' in un and 'UID:UID-1' in un and 'SEQUENCE:0' in un, 'REQUEST: method, UID, sequence')
ok('DTSTART;TZID=Europe/Copenhagen:20270304T100000' in un and 'BEGIN:VTIMEZONE' in un and 'TZID:Europe/Copenhagen' in un
   and 'TZOFFSETTO:+0200' in un and 'TZOFFSETTO:+0100' in un, 'times with TZID and the zone\'s own rules for that year')
ok('ORGANIZER;CN="Alex Example":mailto:alex@example.com' in un and 'RSVP=TRUE:mailto:lee@example.com' in un
   and 'CN="Lee Chen"' in un and 'mailto:sam@example.net' in un, 'organizer and each person, asked to answer')
ok('SUMMARY:Acme planning\\; budget' in un and 'Join: https://teams.microsoft.com' in un and 'Passcode: abc123' in un, 'escaped title; the join link and passcode')
ok(all(len(l.encode()) <= 75 for l in ics.split('\r\n')), 'lines folded at 75 octets')
upd = re.sub(r'\r\n[ \t]', '', CI.event_ics('UID-1', 1, 'Acme planning', START, END, TZ, ORG, PEOPLE))
ok('SEQUENCE:1' in upd and 'METHOD' not in upd, 'an update: sequence + 1 (stored on the server, no METHOD)')
sil = CI.event_ics('UID-1', 2, 'Acme planning', START, END, TZ, ORG, PEOPLE, silent=True)
ok(sil.count('SCHEDULE-AGENT=CLIENT') == 2, '"Save without telling them": the server is told not to send')
can = re.sub(r'\r\n[ \t]', '', CI.event_ics('UID-1', 3, 'Acme planning', START, END, TZ, ORG, PEOPLE, method='CANCEL'))
ok('METHOD:CANCEL' in can and 'STATUS:CANCELLED' in can and 'SEQUENCE:3' in can, 'CANCEL')
bad(lambda: CI.event_ics('U', 0, 'x', END, START, TZ, ORG, PEOPLE), 'an event that ends before it starts', 'ends before')
ans = CI.answers_ics('ATTENDEE;CN="Alex";PARTSTAT=ACCEPTED:mailto:alex@example.com\r\nATTENDEE;CN="Lee Chen";PARTSTAT=ACCEPTED;RSVP=TRUE:mailto:lee@example.com\r\n'
                     'ATTENDEE;CN="Sam";PARTSTAT=NEEDS-ACTION;\r\n RSVP=TRUE:mailto:sam@example.net', 'alex@example.com')
ok(ans == [{'email': 'lee@example.com', 'answer': 'accepted'}, {'email': 'sam@example.net', 'answer': 'none'}], 'answers from the stored event')
ok(CI.answers_line(ans, {'lee@example.com': 'Lee Chen', 'sam@example.net': 'Sam Rivera'}) == 'Lee accepted · Sam hasn\'t answered', 'the answers line')

# ---- iCloud: the server sends the invitations
dav = []
stored = {}


def raw(method, url, headers, body):
    dav.append((method, url, dict(headers), body))
    if method == 'PROPFIND' and url == CI.ICLOUD:
        return 207, '<d:multistatus xmlns:d="DAV:"><d:response><d:propstat><d:prop><d:current-user-principal><d:href>/100001/principal/</d:href>' \
                    '</d:current-user-principal></d:prop></d:propstat></d:response></d:multistatus>', {}
    if method == 'PROPFIND' and url.endswith('/principal/'):
        return 207, '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:propstat><d:prop><c:calendar-home-set>' \
                    '<d:href>https://p01-caldav.icloud.com:443/100001/calendars/</d:href></c:calendar-home-set></d:prop></d:propstat></d:response></d:multistatus>', {}
    if method == 'PROPFIND':
        return 207, ('<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                     '<d:response><d:href>/100001/calendars/home/</d:href><d:propstat><d:prop><d:displayname>Home</d:displayname>'
                     '<d:resourcetype><d:collection/><c:calendar/></d:resourcetype></d:prop></d:propstat></d:response>'
                     '<d:response><d:href>/100001/calendars/inbox/</d:href><d:propstat><d:prop><d:displayname>Home</d:displayname>'
                     '<d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response></d:multistatus>'), {}
    if method == 'PUT':
        if headers.get('If-None-Match') == '*' and url in stored:
            return 412, '', {}
        if headers.get('If-Match') and headers['If-Match'] != stored.get(url, ('', ''))[1]:
            return 412, '', {}
        tag = '"e%d"' % len(dav)
        stored[url] = (body.decode(), tag)
        return 201, '', {'etag': tag}
    if method == 'GET':
        return (200, stored[url][0], {'etag': stored[url][1]}) if url in stored else (404, '', {})
    if method == 'DELETE':
        stored.pop(url, None)
        return 204, '', {}
    return 500, '', {}


bad(lambda: CI.CalDav(kc, raw).calendar_url('Home'), 'iCloud not set up: says so', 'not set up')
kc.set(CI.CALDAV_SERVICE, 'icloud', {'apple_id': 'alex@example.com', 'password': 'aaaa-bbbb-cccc-dddd'})
cd = CI.CalDav(kc, raw, note=lambda *a: notes.append(a))
inv = CI.Invites(st, cd, CI.Graph(auth, http))
r = inv.send('idem-0001', 'icloud', 'Home', ORG, 'Acme planning', START, END, TZ, PEOPLE, 'Room 2', 'Bring the brief', join,
             dashboard_url='https://mini.tailnet-example.ts.net/axella')
put = next(x for x in dav if x[0] == 'PUT')
ok(put[1] == 'https://p01-caldav.icloud.com:443/100001/calendars/home/' + r['uid'] + '.ics' and put[2]['If-None-Match'] == '*',
   'iCloud: found the calendar by its title, the event put once (If-None-Match)')
ok('ORGANIZER' in put[3].decode() and 'mailto:lee@example.com' in put[3].decode() and 'METHOD' not in put[3].decode(),
   '… with the organizer and the people, so iCloud sends the invitations')
ok(put[2]['Authorization'].startswith('Basic ') and all(re.match(r'^https://([a-z0-9-]+\.)*icloud\.com', x[1]) for x in dav), 'only to iCloud, with the app password')
ok(inv.send('idem-0001', 'icloud', 'Home', ORG, 'Acme planning', START, END, TZ, PEOPLE).get('repeat') and
   len([x for x in dav if x[0] == 'PUT']) == 1, 'a double tap sends no second invitation')
ok(inv.match({'url': r['link'], 'calendar': 'Home'})['uid'] == r['uid'] and
   inv.match({'calendar': 'Home', 'title': 'Acme planning', 'start': START})['uid'] == r['uid'], 'the event found again (by link, or by title and time)')
href = r['href']
stored[href] = (re.sub(r'\r\n[ \t]', '', stored[href][0]).replace('PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:lee@example.com', 'PARTSTAT=ACCEPTED;RSVP=TRUE:mailto:lee@example.com'), '"answered"')
ok(inv.answers(r['uid'])['line'] == 'Lee accepted · sam@example.net hasn\'t answered', 'answers read back from iCloud')
u = inv.update(r['uid'], 'Acme planning', '2027-03-04T11:00:00+01:00', '2027-03-04T11:30:00+01:00', TZ, PEOPLE, 'Room 2', 'Bring the brief')
lastput = [x for x in dav if x[0] == 'PUT'][-1]
ok(u['sequence'] == 1 and 'SEQUENCE:1' in lastput[3].decode() and lastput[2]['If-Match'] == '"answered"', 'Send update: sequence + 1, on the current version')
inv.update(r['uid'], 'Acme planning', '2027-03-04T11:00:00+01:00', '2027-03-04T11:30:00+01:00', TZ, PEOPLE, tell=False)
ok('SCHEDULE-AGENT=CLIENT' in [x for x in dav if x[0] == 'PUT'][-1][3].decode(), 'Save without telling them')
inv.cancel(r['uid'])
ok(dav[-1][0] == 'DELETE' and href not in stored and inv.get(r['uid'])['cancelled'], 'Send cancellation: deleted on iCloud (it tells the people)')
bad(lambda: inv.update(r['uid'], 'x', START, END, TZ, PEOPLE), 'a cancelled event can\'t be changed', 'cancelled')
ok(oct(os.stat(inv.file).st_mode & 0o777) == '0o600', 'calendar-invites.json is private (600)')

# ---- the work calendar: Exchange sends the invitations, Teams on the same event
gcalls = []


def ghttp(method, url, headers=None, body=None, form=None):
    gcalls.append((method, url, body))
    if '/me/calendars?' in url:
        return 200, {'value': [{'id': 'c-def', 'name': 'Calendar', 'isDefaultCalendar': True}, {'id': 'c-2', 'name': 'Work'}]}
    if url.endswith('/events') and method == 'POST':
        return 201, {'id': 'ev-1', 'iCalUId': 'GRAPH-UID-1', 'onlineMeeting': {'joinUrl': 'https://teams.microsoft.com/l/meetup-join/ev'}}
    if '/me/onlineMeetings?$filter=' in url:
        return 200, {'value': [{'id': 'om-1'}]}
    if '/me/events/ev-1?$select=attendees' in url:
        return 200, {'attendees': [{'emailAddress': {'address': 'lee@example.com'}, 'status': {'response': 'declined'}},
                                   {'emailAddress': {'address': 'sam@example.net'}, 'status': {'response': 'tentativelyAccepted'}}]}
    return 204, {}


winv = CI.Invites(tempfile.mkdtemp(), cd, CI.Graph(auth, ghttp))
w = winv.send('idem-work-01', 'graph', 'Work', {'email': 'alex@acme.example'}, 'Acme planning', START, END, TZ, PEOPLE, 'Room 2', 'Agenda', None,
              meeting_key='teams', teams=True)
ev = next(b_ for m_, u_, b_ in gcalls if m_ == 'POST' and u_.endswith('/events'))
ok(any(u_.endswith('/me/calendars/c-2/events') for m_, u_, b_ in gcalls), 'work: in the chosen calendar, found by its name')
ok(ev['isOnlineMeeting'] and ev['onlineMeetingProvider'] == 'teamsForBusiness' and ev['transactionId'] == 'idem-work-01'
   and [a['emailAddress']['address'] for a in ev['attendees']] == ['lee@example.com', 'sam@example.net'],
   'work: one event with the people and a Teams meeting (Graph\'s own double-tap guard)')
ok(ev['start'] == {'dateTime': '2027-03-04T09:00:00', 'timeZone': 'UTC'}, '… times in UTC')
ok(any(m == 'PATCH' and 'onlineMeetings/om-1' in u_ and b_['lobbyBypassSettings']['scope'] == 'organizer' for m, u_, b_ in gcalls),
   '… and the lobby set on its Teams meeting')
ok(w['join']['join_url'].startswith('https://teams.microsoft.com/') and w['uid'] == 'GRAPH-UID-1', 'the join link kept for the event sheet')
ok(winv.answers(w['uid'])['line'] == 'Lee declined · sam@example.net said maybe', 'answers from Exchange')
bad(lambda: winv.update(w['uid'], 'Acme planning', START, END, TZ, PEOPLE, tell=False), 'work: no silent save (Exchange always tells them)', 'always')
winv.cancel(w['uid'], 'Sorry')
ok(gcalls[-1][0] == 'POST' and gcalls[-1][1].endswith('/me/events/ev-1/cancel'), 'work: Send cancellation')

print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
