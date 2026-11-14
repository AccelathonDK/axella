#!/usr/bin/env python3
"""Accept / Maybe / Decline (axella-actions.py invite_respond): the reply goes to the organizer through Mail, only with
confirm=send, and Accept puts the meeting in the chosen calendar. Mail and Calendar are stubbed. Fictional cast.
Run: python3 setup/tests/test_invite_respond.py"""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
import invites  # noqa: E402
import calendar_answer  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


ICS = ('BEGIN:VCALENDAR\nMETHOD:REQUEST\nBEGIN:VEVENT\nUID:u-42\nSEQUENCE:1\nDTSTART:20261105T080000Z\nDTEND:20261105T084500Z\n'
       'ORGANIZER;CN=Lee Chen:mailto:lee@acme.example\nATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:alex@example.com\nSUMMARY:Alex x Lee\n'
       'DESCRIPTION:https://meet.google.com/abc\nEND:VEVENT\nEND:VCALENDAR')
d = tempfile.mkdtemp()
A.SENT_FILE = os.path.join(d, 'sent.json')
A.STATE_FILE = os.path.join(d, 'state.json')
A.OUTBOX_DIR = os.path.join(d, 'outbox')
A.config = lambda: {'accounts': {'iCloud': {'kind': 'private', 'address': 'alex@example.com'}}}
A.profile.calendar_names = lambda cfg=None: ['Home', 'Work']
A.profile.owner = lambda cfg=None: {'name': 'Alex Example', 'first_name': 'Alex'}
A.invite_load = lambda account, mid: invites.parse(ICS)
calls = []
A._latest_digest_items = lambda sec: [{'id': 'cal-1', 'section': 'cal', 'event': {'title': 'Alex x Lee', 'start': '2026-11-05T08:00:00+00:00'}},
                                      {'id': 'cal-2', 'section': 'cal', 'event': {'title': 'Dentist', 'start': '2026-11-06T08:00:00+00:00'}}]
import calendar_view  # noqa: E402
calendar_view._cache[('2026-11-05', '2026-11-06')] = (9e18, {'events': []})


def osa(script, *args, timeout=60, tries=1):
    calls.append((script, args))
    if script is calendar_answer.SCRIPT:          # these invitations are not in Calendar: the mail reply (test_invite_calendar.py has the rest)
        return 'not_found'
    if script is A.SEND_NEW_SCRIPT:
        calls.append(('ics', open(args[5]).read()))
        return 'sent'
    return 'created'


A.osa = osa
try:
    A.invite_respond({'account': 'iCloud', 'message_id': '<m@x>', 'response': 'accepted'})
    ok(False, 'without confirm=send nothing is sent')
except A.Bad:
    ok(not calls, 'without confirm=send nothing is sent')
r = A.invite_respond({'account': 'iCloud', 'message_id': '<m@x>', 'response': 'accepted', 'confirm': 'send', 'calendar': 'Work', 'item_id': 'i1', 'title': 'Accepted: Alex x Lee'})
send = next(c for c in calls if c[0] is A.SEND_NEW_SCRIPT)
ok(send[1][:3] == ('iCloud', 'lee@acme.example', 'Accepted: Alex x Lee'), 'the reply goes to the organizer from the account')
ics = next(c[1] for c in calls if c[0] == 'ics')
ok('METHOD:REPLY' in ics and 'PARTSTAT=ACCEPTED' in ics.replace('\r\n ', '') and 'UID:u-42' in ics, 'with the calendar reply attached')
ok(not os.path.exists(send[1][5]), 'the reply file is removed after sending')
ok(send[1][4] == 'alex@example.com', 'sent from the invited address (from the config, not Mail\'s own list)')
ev = next(c for c in calls if c[0] is A.EVENT_SCRIPT)
ok(ev[1][0] == 'Work' and ev[1][1] == 'Alex x Lee' and 'meet.google.com' in ev[1][3], 'Accept puts the meeting in the chosen calendar')
ok(r['status'] == 'sent' and r['calendar'] == 'Work', 'result')
ok(not calendar_view._cache, 'the calendar is read again after the meeting was added')
ok(r['handled'] == ['cal-1'] and A.load_json(A.STATE_FILE, {}).get('cal-1', {}).get('status') == 'done', 'the digest\'s "not in the calendar" note for the same meeting is handled too')
ok(A.load_json(A.STATE_FILE, {}).get('i1', {}).get('how') == 'invite:accepted', 'the item is handled')
try:
    A.invite_respond({'account': 'iCloud', 'message_id': '<m@x>', 'response': 'accepted', 'confirm': 'send'})
    ok(False, 'the same answer twice within minutes: refused')
except A.Bad:
    ok(True, 'the same answer twice within minutes: refused')
calls.clear()
A.invite_respond({'account': 'iCloud', 'message_id': '<m@x>', 'response': 'declined', 'confirm': 'send', 'calendar': 'Work'})
ok(not any(c[0] is A.EVENT_SCRIPT for c in calls), 'Decline never adds to the calendar')
try:
    A.invite_respond({'account': 'iCloud', 'message_id': '<m@x>', 'response': 'tentative', 'confirm': 'send', 'calendar': 'Somewhere'})
    ok(False, 'an unknown calendar is refused')
except A.Bad:
    ok(True, 'an unknown calendar is refused')
ok('invite_respond' in A.SLOW_ACTIONS and 'invite_respond' in A.SENDS, 'runs in the send queue; the log keeps the title only')
# Mail refusing before sending: nothing went out, the retry is not blocked
A.SENT_FILE = os.path.join(d, 'sent2.json')
def osa_fail(script, *args, timeout=60, tries=1):
    if script is calendar_answer.SCRIPT:
        return 'not_found'
    raise RuntimeError('execution error: Mail got an error')
A.osa = osa_fail
try:
    A.invite_respond({'account': 'iCloud', 'message_id': '<m@x>', 'response': 'accepted', 'confirm': 'send'})
    ok(False, 'a Mail error is reported')
except A.Bad as e:
    ok('nothing was sent' in str(e), 'a Mail error is reported as not sent')
A.osa = osa
r = A.invite_respond({'account': 'iCloud', 'message_id': '<m@x>', 'response': 'accepted', 'confirm': 'send'})
ok(r['status'] == 'sent', 'and trying again right away works')

# ---- whom the answer goes to (security review 5): no-reply organizers refused, another domain than From warned
NR = ICS.replace('mailto:lee@acme.example', 'mailto:no-reply@acme.example')
A.invite_load = lambda account, mid: invites.parse(NR)
n_calls = len(calls)
try:
    A.invite_respond({'account': 'iCloud', 'message_id': '<nr@x>', 'response': 'accepted', 'confirm': 'send'})
    ok(False, 'a no-reply organizer is refused')
except A.Bad as e:
    ok('no-reply' in str(e) and len(calls) == n_calls, 'a no-reply organizer is refused – nothing is sent')
A.invite_load = lambda account, mid: invites.parse(ICS)
chk = lambda org, frm: A.invite_check({'organizer': {'email': org}, 'mail_from': frm})
ok(not chk('lee@acme.example', 'lee@acme.example')['mismatch'], 'organizer and From on the same domain: no warning')
ok(not chk('lee@acme.example', 'calendar@mail.acme.example')['mismatch'], '… a subdomain of it: no warning')
c = chk('lee@acme.example', 'sam@rivera.example')
ok(c['mismatch'] and c['organizer_domain'] == 'acme.example' and c['mail_domain'] == 'rivera.example',
   'an organizer on another domain than the mail came from: the sheet warns')
ok(chk('noreply@acme.example', 'lee@acme.example')['no_reply'], 'the sheet knows a no-reply organizer')
ok(not chk('lee@acme.example', '')['mismatch'], 'no From to compare: no warning')

# ---- invitations still waiting for an answer (Calendar page, Meetings, Today)
def ics(uid, start, method='REQUEST', seq=0, summary='Meeting', partstat='NEEDS-ACTION'):
    return ('BEGIN:VCALENDAR\nMETHOD:%s\nBEGIN:VEVENT\nUID:%s\nSEQUENCE:%d\nDTSTART:%s\nDTEND:%s\nORGANIZER:mailto:lee@acme.example\n'
            'ATTENDEE;PARTSTAT=%s:mailto:alex@example.com\nSUMMARY:%s\nEND:VEVENT\nEND:VCALENDAR' % (method, uid, seq, start, start[:-3] + '59Z', partstat, summary))
import datetime as _dt  # noqa: E402
fut = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=2)).strftime('%Y%m%dT0900') + '00Z'
past = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=2)).strftime('%Y%m%dT0900') + '00Z'
mails = {'a': ics('p-1', fut, summary='Kick-off'), 'b': ics('p-2', fut, summary='Old time'), 'b2': ics('p-2', fut, seq=1, summary='New time'),
         'c': ics('p-3', fut), 'c2': ics('p-3', fut, method='CANCEL'), 'd': ics('p-4', past), 'e': ics('p-5', fut, summary='In calendar'),
         'f': ics('u-42', fut, summary='Answered already'), 'g': ics('p-7', fut, summary='Hidden by you'), 'h': ics('p-8', fut, partstat='ACCEPTED')}
A.mail_accounts = lambda: {'acc': 'iCloud'}
A.mailsearch.invite_candidates = lambda names: [{'path': k, 'account': 'iCloud', 'message_id': k + '@x', 'subject': 'Invitation', 'from_name': 'Lee',
                                                  'from_address': 'lee@acme.example', 'date': None} for k in mails]
A.mailsearch.addresses_of = lambda p: ['lee@acme.example']
A.mailsearch._raw = lambda p: ('Content-Type: text/calendar\r\n\r\n' + mails[p]).encode()
A.mail_privacy = lambda addrs: (None, None)
in_cal = invites.public(invites.parse(mails['e']), [])['start']
calendar_view.events = lambda *a, **k: {'events': [{'title': 'In calendar', 'start': in_cal}]}
A.INVITES_DISMISSED = os.path.join(d, 'dismissed.json')
A.invite_dismiss({'uid': 'p-7'})
got = A.pending_invites(fresh=True)
ok(sorted(x['summary'] for x in got['invites']) == ['Kick-off', 'New time'],
   'waiting: only open requests – not cancelled, past, already in the calendar, answered, hidden or already accepted')
ok(next(x for x in got['invites'] if x['uid'] == 'p-2')['message_id'] == 'b2@x', 'an updated invitation replaces the older one')
ok(A.invite_in_calendar({'summary': 'Visit  Alex in CH', 'all_day': True, 'start': '2026-11-16'},
                        [{'title': 'visit alex in CH', 'all_day': True, 'start': '2026-11-16T00:00:00+01:00'}]), 'an all-day meeting already in the calendar is found')
ok(not A.invite_in_calendar({'summary': 'Visit Alex in CH', 'all_day': True, 'start': '2026-11-16'},
                            [{'title': 'Visit Alex in CH', 'all_day': True, 'start': '2026-11-17T00:00:00+01:00'}]), '… but not on another day')
A.mail_privacy = lambda addrs: ('hidden', None)
ok(A.pending_invites(fresh=True)['invites'] == [], 'a hidden contact\'s invitation is never shown')
# AppleScript gets no stray quotes: every line of the send script has its quotes in pairs (osacompile isn't here)
for name in ('SEND_NEW_SCRIPT', 'EVENT_SCRIPT'):
    bad = [l for l in getattr(A, name).split('\n') if l.count('"') % 2]
    ok(not bad, name + ': quotes balanced on every line')

# a forwarded invite: ORGANIZER with a quoted SENT-BY="mailto:…" (a colon inside a quoted parameter)
FWD = ICS.replace('ORGANIZER;CN=Lee Chen:mailto:lee@acme.example',
                  'ORGANIZER;CN="Robin Example";SENT-BY="mailto:alex.old@example.net":mailto:robin@example.org')
ev = invites.parse(FWD)
ok(ev['organizer'] == {'email': 'robin@example.org', 'name': 'Robin Example'}, 'a quoted SENT-BY="mailto:…" no longer swallows the organizer address')
ok(invites._line('ATTENDEE;CN="Team: Sales";PARTSTAT=ACCEPTED:mailto:kim@example.net')[2] == 'mailto:kim@example.net', 'a colon inside a quoted name too')
calls.clear()
A.invite_load = lambda account, mid: invites.parse(FWD)
A.invite_respond({'account': 'iCloud', 'message_id': '<m2@x>', 'response': 'declined', 'confirm': 'send', 'item_id': 'i2'})
send = next(c for c in calls if c[0] is A.SEND_NEW_SCRIPT)
ok(send[1][1] == 'robin@example.org', '… and the answer goes to that organizer')

import time as _t  # noqa: E402
t0 = _t.time()
ok(invites._line('X' + ';A=b,c' * 40 + '"') is None and _t.time() - t0 < 0.5, 'a crafted line (40 comma parameters, no colon) fails fast')
t0 = _t.time()
ok(invites._line('X' + ';A=b,c' * 5000 + '"') is None and _t.time() - t0 < 0.5, '… also a very long one')
long_desc = 'DESCRIPTION:' + 'x' * 6000 + ' https://teams.example.com/l/meetup-join/abc'
ok(invites._line(long_desc)[2].endswith('meetup-join/abc'), 'a long DESCRIPTION is still read whole (its join link)')
ok(invites._line('CATEGORIES:a,b') == ('CATEGORIES', {}, 'a,b') and invites._line('DTSTART;TZID=Europe/Copenhagen:20261105T090000')[1] == {'TZID': 'Europe/Copenhagen'},
   'ordinary lines still read')

print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
