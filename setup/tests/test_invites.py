#!/usr/bin/env python3
"""Calendar invitations (setup/invites.py): reading Google / Outlook invites and building the iTIP reply.
Fictional cast only. Run: python3 setup/tests/test_invites.py"""
import datetime
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import invites as I  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


GOOGLE = """BEGIN:VCALENDAR
PRODID:-//Google Inc//Google Calendar 70.9054//EN
VERSION:2.0
CALSCALE:GREGORIAN
METHOD:REQUEST
BEGIN:VTIMEZONE
TZID:Europe/Copenhagen
BEGIN:STANDARD
DTSTART:19701025T030000
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
DTSTART;TZID=Europe/Copenhagen:20261105T090000
DTEND;TZID=Europe/Copenhagen:20261105T094500
DTSTAMP:20261104T154300Z
ORGANIZER;CN=Lee Chen:mailto:lee@acme.example
UID:abc123@calendar.example
ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=
 TRUE;CN=alex@example.com;X-NUM-GUESTS=0:mailto:alex@example.com
ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED;CN=Lee Chen:mailto:lee@acme.example
DESCRIPTION:Join with Google Meet: https://meet.google.com/abc-defg-hij\\nSee you
SEQUENCE:2
STATUS:CONFIRMED
SUMMARY:Alex x Lee\\, kick-off
LOCATION:
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:This is an event reminder
TRIGGER:-P0DT0H10M0S
END:VALARM
END:VEVENT
END:VCALENDAR
""".replace('\n', '\r\n')

ev = I.parse(GOOGLE)
ok(ev['uid'] == 'abc123@calendar.example' and ev['sequence'] == 2 and ev['method'] == 'REQUEST', 'uid, sequence, method')
ok(ev['summary'] == 'Alex x Lee, kick-off', 'summary unescaped')
ok(ev['dtstart'].hour == 9 and str(ev['dtstart'].tzinfo) == 'Europe/Copenhagen' and (ev['dtend'] - ev['dtstart']).seconds == 2700, 'times with their zone')
ok(ev['organizer'] == {'email': 'lee@acme.example', 'name': 'Lee Chen'}, 'organizer')
ok(I.me_in(ev, ['Alex@Example.com'])['partstat'] == 'NEEDS-ACTION', 'folded attendee line: the owner found')
ok('This is an event reminder' not in (ev.get('description') or ''), 'an alarm inside the event does not overwrite it')
pub = I.public(ev, ['alex@example.com'])
ok(pub['start'].startswith('2026-11-05T') and 'meet.google.com' in pub['description'] and pub['me']['email'] == 'alex@example.com', 'the dashboard view')

r = I.reply_ics(ev, 'alex@example.com', 'Alex Example', 'accepted', now=datetime.datetime(2026, 11, 4, 18, 0, tzinfo=datetime.timezone.utc))
ok('METHOD:REPLY' in r and 'UID:abc123@calendar.example' in r and 'SEQUENCE:2' in r, 'reply: method, uid, sequence')
flat = r.replace('\r\n ', '')
ok('ATTENDEE;PARTSTAT=ACCEPTED;CN="Alex Example":mailto:alex@example.com' in flat, 'reply: the owner accepts')
ok('DTSTART;TZID=Europe/Copenhagen:20261105T090000' in flat and 'ORGANIZER;CN=Lee Chen:mailto:lee@acme.example' in flat, 'reply: DTSTART and ORGANIZER as the invite had them')
ok(all(len(l.encode()) <= 75 for l in r.split('\r\n')) and r.endswith('\r\n'), 'reply: lines folded at 75 octets, CRLF')
ok(r.count('ATTENDEE') == 1, 'reply: one attendee – the owner')
ok('TENTATIVE' in I.reply_ics(ev, 'alex@example.com', '', 'tentative') and 'DECLINED' in I.reply_ics(ev, 'alex@example.com', '', 'declined'), 'Maybe and Decline')
try:
    I.reply_ics(ev, 'alex@example.com', '', 'delegated')
    ok(False, 'unknown answers refused')
except I.Bad:
    ok(True, 'unknown answers refused')
ok(I.reply_subject(ev, 'accepted') == 'Accepted: Alex x Lee, kick-off' and 'has accepted' in I.reply_text(ev, 'Alex Example', 'accepted'), 'subject and text')

OUTLOOK = """BEGIN:VCALENDAR
METHOD:REQUEST
BEGIN:VEVENT
ORGANIZER;CN="Sam Rivera":MAILTO:Sam@Acme.example
ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE;CN=Alex:MAILTO:alex@example.com
SUMMARY;LANGUAGE=en-US:Budget review
DTSTART;TZID=W. Europe Standard Time:20261110T140000
DTEND;TZID=W. Europe Standard Time:20261110T150000
UID:040000008200E00074C5B7101A82E008
RECURRENCE-ID;TZID=W. Europe Standard Time:20261110T140000
SEQUENCE:0
END:VEVENT
END:VCALENDAR"""
o = I.parse(OUTLOOK)
ok(str(o['dtstart'].tzinfo) == 'Europe/Berlin' and o['organizer']['email'] == 'sam@acme.example', 'Outlook: Windows zone name, MAILTO in capitals')
ok('RECURRENCE-ID;TZID=W. Europe Standard Time:20261110T140000' in I.reply_ics(o, 'alex@example.com', 'Alex', 'accepted').replace('\r\n ', ''), 'one occurrence of a series: RECURRENCE-ID kept')
a = I.parse('BEGIN:VCALENDAR\nMETHOD:CANCEL\nBEGIN:VEVENT\nUID:x1\nDTSTART;VALUE=DATE:20261112\nSUMMARY:Off-site\nEND:VEVENT\nEND:VCALENDAR')
ok(a['all_day'] and a['dtend'] == datetime.date(2026, 11, 13) and I.public(a, [])['cancelled'], 'all-day and a cancellation')
try:
    I.parse('BEGIN:VCALENDAR\nEND:VCALENDAR')
    ok(False, 'no event: refused')
except I.Bad:
    ok(True, 'no event: refused')

# in a message, and in Mail's Attachments folder
raw = ('From: Lee Chen <lee@acme.example>\r\nSubject: Invitation\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary="b"\r\n\r\n'
       '--b\r\nContent-Type: text/plain\r\n\r\nYou are invited\r\n--b\r\nContent-Type: text/calendar; charset=UTF-8; method=REQUEST\r\n'
       'Content-Transfer-Encoding: base64\r\n\r\n' + __import__('base64').b64encode(GOOGLE.encode()).decode() + '\r\n--b--\r\n').encode()
ok(I.parse(I.ics_from_message(raw))['uid'] == 'abc123@calendar.example', 'the calendar part of a mail')
ok(I.ics_from_message(b'From: x\r\n\r\nhello') is None, 'no calendar part: None')
d = tempfile.mkdtemp()
os.makedirs(os.path.join(d, 'INBOX.mbox', 'Messages'))
os.makedirs(os.path.join(d, 'INBOX.mbox', 'Attachments', '4711', '2'))
open(os.path.join(d, 'INBOX.mbox', 'Attachments', '4711', '2', 'invite.ics'), 'w').write(OUTLOOK)
ok(I.parse(I.ics_from_attachments(os.path.join(d, 'INBOX.mbox', 'Messages', '4711.partial.emlx')))['summary'] == 'Budget review', 'an attachment Mail keeps beside the message')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
