#!/usr/bin/env python3
"""Answering an invitation in Calendar itself (calendar_answer.py, axella-actions.py invite_respond): when the
invitation is under Calendar's "New", Axella presses Accept / Maybe / Decline there and sends no reply mail and adds no
event; only an invitation that isn't in Calendar gets the reply mail; every other outcome sends nothing at all – never
both routes for one invitation. The AppleScript gets the meeting only as argv and finds Calendar's elements by their
fixed identifiers. Mail and Calendar are stubbed; fictional cast. Run: python3 setup/tests/test_invite_calendar.py"""
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
import calendar_answer as C  # noqa: E402
import invites  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


print('The script')
ok(all(i in C.SCRIPT for i in ('CALMainWindow', 'inbox-button', 'inbox-switcher-control', 'replied-button')) and
   set(C.BUTTON.values()) == {'accept-button', 'maybe-button', 'decline-button'}, "Calendar's elements by their fixed identifiers (any language)")
ok('item 1 of argv' in C.SCRIPT and 'Alex x Lee' not in C.SCRIPT and '%s' not in C.SCRIPT and '{' not in C.SCRIPT.replace('{}', '').replace('{r, t}', ''),
   'the meeting reaches the script only as argv – nothing is pasted into it')
ok('perform action "AXPress"' in C.SCRIPT and 'keystroke' not in C.SCRIPT and 'click at' not in C.SCRIPT, 'buttons are pressed through Accessibility – no keystrokes, no screen coordinates')
ok(C.times('2026-11-05T15:00:00+00:00')[0].count('.') == 1 and C.times('nonsense') == ('\u0000', '\u0000'), "the start as Calendar writes it, only a tie-breaker")

ICS = ('BEGIN:VCALENDAR\nMETHOD:REQUEST\nBEGIN:VEVENT\nUID:u-77\nSEQUENCE:1\nDTSTART:20261117T150000Z\nDTEND:20261117T153000Z\n'
       'ORGANIZER;CN=Lee Chen:mailto:lee@acme.example\nATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:alex@acme.example\nSUMMARY:Roadmap review\n'
       'END:VEVENT\nEND:VCALENDAR')
d = tempfile.mkdtemp(prefix='axtest-invcal-')
A.SENT_FILE = os.path.join(d, 'sent.json')
A.STATE_FILE = os.path.join(d, 'state.json')
A.OUTBOX_DIR = os.path.join(d, 'outbox')
CFG = {'accounts': {'Acme': {'kind': 'work', 'address': 'alex@acme.example'}}}
A.config = lambda: CFG
A.profile.calendar_names = lambda cfg=None: ['Work']
A.profile.owner = lambda cfg=None: {'name': 'Alex Example', 'first_name': 'Alex'}
A.invite_load = lambda account, mid: invites.parse(ICS)
A._latest_digest_items = lambda sec: [{'id': 'cal-9', 'section': 'cal', 'event': {'title': 'Roadmap review', 'start': '2026-11-17T15:00:00+00:00'}}]
states = {}
A.set_state = lambda iid, v: states.__setitem__(iid, v)
calls = []
CAL = {'out': 'answered'}


def osa(script, *args, timeout=60, tries=1):
    calls.append((script, args))
    if script is C.SCRIPT:
        if isinstance(CAL['out'], Exception):
            raise CAL['out']
        return CAL['out']
    if script is A.SEND_NEW_SCRIPT:
        return 'sent'
    return 'created'


A.osa = osa
mails = lambda: [c for c in calls if c[0] is A.SEND_NEW_SCRIPT]
events = lambda: [c for c in calls if c[0] is A.EVENT_SCRIPT]
P = {'account': 'Acme', 'message_id': '<m77@acme.example>', 'confirm': 'send', 'calendar': 'Work', 'item_id': 'i77', 'title': 'Accepted: Roadmap review'}

print('In Calendar: answered there, nothing else')
r = A.invite_respond(dict(P, response='accepted'))
cal = [c for c in calls if c[0] is C.SCRIPT]
ok(r['status'] == 'answered' and r['via'] == 'calendar', 'Accept pressed in Calendar')
ok(cal[0][1][0] == 'Roadmap review' and cal[0][1][1] == 'Lee Chen' and cal[0][1][4] == 'accept-button', '… title, organizer and the Accept button as argv')
ok(not mails() and not events(), '… no reply mail, no event added – Exchange or iCloud does both')
ok(states.get('i77', {}).get('status') == 'done' and 'cal-9' in r['handled'], "… the item and the digest's note about the meeting are done")
sent = json.load(open(A.SENT_FILE))
ok(sent[-1]['status'] == 'calendar' and sent[-1]['attachments'] == [], '… logged as answered in Calendar')
try:
    A.invite_respond(dict(P, response='accepted'))
    ok(False, 'the same answer twice within minutes is refused')
except A.Bad:
    ok(True, 'the same answer twice within minutes is refused')
calls.clear()
A.invite_respond(dict(P, response='declined'))
ok([c[1][4] for c in calls if c[0] is C.SCRIPT] == ['decline-button'] and not mails(), 'Decline: the Decline button, no mail')

print('Not in Calendar: the reply mail, as before')
calls.clear()
CAL['out'] = 'not_found'
A.SENT_FILE = os.path.join(d, 'sent2.json')
r = A.invite_respond(dict(P, response='tentative'))
ok(r['status'] == 'sent' and len(mails()) == 1, 'not under New or Replied: answered by mail')

print('Anything else: nothing is sent at all')
for out, word in (('replied', 'already answered'), ('ambiguous', 'more than one'), ('no_access', 'Accessibility'), ('no_window', 'window'),
                  ('no_inbox', 'invitations panel'), ('no_button', 'button'), ('unconfirmed', 'check the invitation'), ('rubbish', 'invitations panel'),
                  (RuntimeError('Mail/Calendar did not answer within 90 s'), 'in time'), (RuntimeError('execution error'), "didn't respond")):
    calls.clear()
    A.SENT_FILE = os.path.join(d, 'sent-%s.json' % (out if isinstance(out, str) else type(out).__name__ + str(len(str(out)))))
    CAL['out'] = out
    try:
        A.invite_respond(dict(P, response='accepted'))
        ok(False, '%s: refused' % out)
    except A.Bad as e:
        ok(word in str(e) and ('Nothing was sent' in str(e) or 'Nothing else was sent' in str(e)) and not mails() and not events(),
           '%s → "%s…", no mail, no event' % (out if isinstance(out, str) else 'osascript ' + str(out)[:20], str(e)[:48]))

print('Switched off: the reply mail only')
calls.clear()
CAL['out'] = 'answered'
CFG['invites'] = {'answer_in_calendar': False}
A.SENT_FILE = os.path.join(d, 'sent3.json')
r = A.invite_respond(dict(P, response='accepted'))
ok(r['status'] == 'sent' and not [c for c in calls if c[0] is C.SCRIPT] and len(mails()) == 1, 'invites.answer_in_calendar: false – Calendar untouched, the mail as before')

print()
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
