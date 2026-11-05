#!/usr/bin/env python3
"""Reply sprint (setup/sprint.py): which replies are quick, the order (reply debt, urgency, age), the time estimate,
and the left-out rules (handled, snoozed, Send later, flagged, long, no-reply, private and protected via the caller).
Invented data only. Run: python3 setup/tests/test_sprint.py"""
import datetime
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import sprint as S  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def item(iid, sec='p2', who='lee@example.com', text='Thanks Lee – Thursday works for me. See you then.', seen='2027-03-09T07:30:00', **kw):
    return dict({'id': iid, 'section': sec, 'channel': 'mail', 'account': 'Work', 'message_id': '<%s@example.com>' % iid,
                 'from': {'name': 'Lee Chen', 'address': who}, 'headline': 'Lee asks about Thursday', 'detail': 'Lee asks if Thursday still works.',
                 'draft': {'mode': 'reply', 'to': who, 'text': text}, 'first_seen': seen}, **kw)


NOW = datetime.datetime(2027, 3, 10, 9, 0).astimezone()
ok(S.why_not(item('a')) is None, 'a short Axella reply draft on a P2 mail is quick')
ok(S.why_not(item('a', text=' '.join(['word'] * 79))) is None and S.why_not(item('a', text=' '.join(['word'] * 80))) == 'long', 'under 80 words')
ok(S.why_not(item('a', sec='p3')) == 'section' and S.why_not(item('a', sec='wait')) == 'section' and S.why_not(item('a', sec='open')) is None, 'P1, P2 or Still open only')
ok(S.why_not(item('a', safety={'level': 'scam'})) == 'flagged', 'a scam-flagged item never')
ok(S.why_not(item('a', draft={'mode': 'new', 'text': 'Hi'})) == 'no draft' and S.why_not(item('a', draft=None)) == 'no draft', 'only a ready reply draft')
ok(S.why_not(item('a', channel='whatsapp')) == 'not a mail' and S.why_not(item('a', message_id=None)) == 'not a mail', 'mail with a message id only')
ok(S.why_not(item('a', who='no-reply@example.com')) == 'no reply' and S.why_not(item('a', who='notifications@example.org')) == 'no reply', 'never to a no-reply address')
ok(S.why_not(item('a', readonly=True)) == 'read only' and S.why_not(item('a', found='x')) == 'read only', 'read-only and Search items never')

its = [item('old', seen='2027-03-08T07:30:00'), item('p1', sec='p1'), item('open', sec='open'),
       item('debt', who='sam@example.org', seen='2027-03-09T11:30:00'), item('debt2', who='robin@example.net'),
       item('done'), item('snz'), item('later'), item('back')]
state = {'done': {'status': 'done', 'how': 'sent'}, 'snz': {'status': 'snoozed', 'until': '2027-03-11T07:00:00+00:00'},
         'back': {'status': 'snoozed', 'until': '2027-03-09T07:00:00+00:00'}}
debt = [{'who': 'robin@example.net', 'days': 4}, {'who': 'Sam@Example.org', 'days': 9}]
q = [i['id'] for i in S.pick(its, state, debt, scheduled=['later'], now=NOW)]
ok(q == ['debt', 'debt2', 'p1', 'old', 'back', 'open'], 'order: owed longest first, then P1, P2, Still open, oldest first (%s)' % q)
ok('done' not in q and 'snz' not in q and 'later' not in q and 'back' in q, 'handled, snoozed and Send later are left out; a snooze that ran out is back')
q2 = [i['id'] for i in S.pick(its, state, debt, ['later'], left_out=lambda it: S.sender(it) == 'sam@example.org', now=NOW)]
ok('debt' not in q2 and len(q2) == 5, 'the caller\'s left-out rule (a private contact, a protected workplace) is applied')
ok(S.addresses(item('a', draft={'mode': 'reply', 'to': 'Lee@example.com, kim@example.org', 'text': 'Hi'})) == ['lee@example.com', 'kim@example.org'],
   'the left-out rule sees the sender and the draft\'s To')
ok(len(S.pick([item('x'), item('x')], {}, now=NOW)) == 1, 'one item once')

ok(S.seconds(item('a', text='Yes.', detail='Ok?')) == 30, 'a tiny one: about 30 s')
ok(S.seconds(item('a', text=' '.join(['w'] * 79), detail=' '.join(['w'] * 60))) == 60, 'a long one: at most 60 s')
v = S.view(its, state, debt, ['later'], now=NOW)
ok(v['count'] == 6 and v['show'] and v['minutes'] == round(v['seconds'] / 60.0) and 3 <= v['minutes'] <= 6, 'six ready: the card shows, about %d minutes' % v['minutes'])
ok(v['items'][0]['sprint']['owed'] and not v['items'][2]['sprint']['owed'], 'reply debt is marked')
v2 = S.view(its[:2], {}, now=NOW)
ok(v2['count'] == 2 and not v2['show'], 'fewer than 3: no card')
ok(S.view([], {})['minutes'] == 0, 'nothing: 0 minutes')
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
