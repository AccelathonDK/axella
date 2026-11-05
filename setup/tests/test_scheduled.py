#!/usr/bin/env python3
"""Send later (setup/scheduled.py): waits on the Mac mini, goes through the normal send path at its time, can be
changed or cancelled until then, never goes twice. Fictional cast. Run: python3 setup/tests/test_scheduled.py"""
import datetime
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import scheduled as S  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def raises(f, label):
    try:
        f()
    except S.Bad:
        return ok(True, label)
    ok(False, label)


d = tempfile.mkdtemp()
st, ob = os.path.join(d, 'state'), os.path.join(d, 'state', 'outbox')
os.makedirs(os.path.join(ob, 'f1'))
open(os.path.join(ob, 'f1', 'quote.pdf'), 'wb').write(b'%PDF')
Q = S.Scheduled(st, ob)
now = datetime.datetime(2026, 11, 6, 17, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
mon = (now + datetime.timedelta(days=3)).replace(hour=8, minute=0)
mail = {'account': 'iCloud', 'to': 'lee@acme.example', 'subject': 'Quote', 'text': 'Hi Lee, here it is.', 'title': 'Quote',
        'attachments': ['f1/quote.pdf'], 'confirm': 'send', 'send_id': 'x', 'evil': 'drop me', 'force': True}
r = Q.add('mail_send', mail, mon.isoformat(), 'owner@example.com', now=now)
x = Q.get(r['id'])
ok(x['status'] == 'scheduled' and x['at'].startswith('2026-11-09T08:00'), 'scheduled for Monday 08:00')
ok('evil' not in x['payload'] and 'confirm' not in x['payload'], 'only known fields are kept – the confirmation is the tap, given again at send time')
ok('force' not in x['payload'], 'force is never kept – a scheduled mail never overrides the repeat guard')
ok(len(x['send_id']) == 32, 'each scheduled mail has its own send_id')
ok(not os.path.exists(os.path.join(ob, 'f1')) and os.path.isfile(os.path.join(st, 'scheduled-files', r['id'], '0', 'quote.pdf')),
   'the attachment leaves the 24-hour outbox and waits with the mail')
raises(lambda: Q.add('mail_send', dict(mail, attachments=[]), (now + datetime.timedelta(seconds=10)).isoformat(), 'o', now=now), 'a time in the past or right now is refused')
raises(lambda: Q.add('mail_send', dict(mail, attachments=[]), (now + datetime.timedelta(days=90)).isoformat(), 'o', now=now), 'at most 60 days ahead')
raises(lambda: Q.add('sms_send', mail, mon.isoformat(), 'o', now=now), 'only mails and replies')
ok('text' not in Q.list(now)[0] and Q.list(now)[0]['attachments'] == 1, 'the list carries no mail text')
Q.update(r['id'], {'text': 'Hi Lee, here is the quote.', 'at': mon.replace(hour=9).isoformat()}, now=now)
ok(Q.text(r['id'])['text'] == 'Hi Lee, here is the quote.' and Q.get(r['id'])['at'].startswith('2026-11-09T09:00'), 'text and time can be changed until it goes')
ok(Q.due(now) == [], 'nothing is due yet')

sent = []


def send(action, p, checked=False):
    sent.append((action, dict(p)))
    files = [os.path.join(ob, a) for a in p['attachments']]
    ok(all(os.path.isfile(f) for f in files), 'at send time the attachment is back in the outbox for the send path')
    return {'status': 'sent', 'to': p.get('to') or p.get('expect_to')}


late = mon.replace(hour=9, minute=14)                           # the Mac mini was asleep until 09:14 (within the hour)
notes = []
Q.run_due(send, log=lambda x, st_, err, lm: notes.append((st_, lm)), now=late)
ok(len(sent) == 1 and sent[0][0] == 'mail_send' and sent[0][1]['confirm'] == 'send', 'at its time it goes through the normal send path')
ok(Q.get(r['id'])['status'] == 'sent' and Q.get(r['id'])['late_min'] == 14 and notes == [('sent', 14)], 'sent, with "14 min late"')
ok(not os.path.exists(os.path.join(st, 'scheduled-files', r['id'])), 'its kept attachment is gone once sent')
Q.run_due(send, now=late + datetime.timedelta(hours=1))
ok(len(sent) == 1, 'never sent twice')
raises(lambda: Q.cancel(r['id']), 'a sent mail cannot be cancelled')

r2 = Q.add('reply_send', {'account': 'iCloud', 'message_id': '<m@x>', 'expect_to': 'kim@example.org', 'text': 'Yes', 'item_id': 'i2'}, mon.isoformat(), 'o', now=now)
Q.cancel(r2['id'])
Q.run_due(send, now=late)
ok(Q.get(r2['id'])['status'] == 'cancelled' and len(sent) == 1, 'a cancelled reply is never sent')

r3 = Q.add('reply_send', {'account': 'iCloud', 'message_id': '<m@y>', 'expect_to': 'sam@example.org', 'text': 'Done'}, mon.isoformat(), 'o', now=now)
Q.send_now(r3['id'], now=now)


def refuse(a, p, checked=False):
    raise RuntimeError('more than 20 mails in an hour')


Q.run_due(refuse, now=now)
ok(Q.get(r3['id'])['status'] == 'failed' and 'hour' in Q.get(r3['id'])['error'], 'a refused send is marked failed, with the reason')

r4 = Q.add('reply_send', {'account': 'iCloud', 'message_id': '<m@z>', 'expect_to': 'robin@example.org', 'text': 'Ok'}, mon.isoformat(), 'o', now=now)
dd = Q.load()
next(y for y in dd if y['id'] == r4['id'])['status'] = 'sending'
Q._save(dd)
Q.recover()
Q.run_due(send, now=late)
ok(Q.get(r4['id'])['status'] == 'unknown' and len(sent) == 1, 'interrupted while sending: "check Sent" – never resent by itself')
Q.send_now(r3['id'], now=now)
Q.run_due(send, now=now)
ok(Q.get(r3['id'])['status'] == 'sent', 'a failed one can be tried again on your tap')

# ---- a timeout: unknown, and Try again only after you checked Sent
class Slow(Exception):
    pass


def timeout(a, p, checked=False):
    raise S.Unknown("Mail didn't confirm in time – it may have sent anyway")


r5 = Q.add('reply_send', {'account': 'iCloud', 'message_id': '<m@t>', 'expect_to': 'jamie@example.org', 'text': 'On my way'}, mon.isoformat(), 'o', now=now)
Q.send_now(r5['id'], now=now)
Q.run_due(timeout, now=now)
ok(Q.get(r5['id'])['status'] == 'unknown', 'a Mail timeout gives "unknown" (it may have gone), not "failed"')
raises(lambda: Q.send_now(r5['id'], now=now), '"unknown": Try again refused until you confirm you checked Sent')
seen = []
Q.send_now(r5['id'], checked=True, now=now)
Q.run_due(lambda a, p, checked=False: seen.append((p['send_id'], checked)) or {'status': 'sent'}, now=now)
ok(seen == [(Q.get(r5['id'])['send_id'], True)], 'Try again keeps the same send_id and passes your check along')

# ---- missed: 3 h overdue at start-up is never sent by itself
r6 = Q.add('reply_send', {'account': 'iCloud', 'message_id': '<m@u>', 'expect_to': 'kim@example.org', 'text': 'See you at 9'}, mon.isoformat(), 'o', now=now)
pushed, calls = [], []
Q.run_due(lambda a, p, checked=False: calls.append(1) or {'status': 'sent'}, now=mon + datetime.timedelta(hours=3), notify=lambda x: pushed.append(x['id']))
ok(Q.get(r6['id'])['status'] == 'missed' and not calls and pushed == [r6['id']], '3 h overdue: "missed", one notification, not sent')
Q.run_due(lambda a, p, checked=False: calls.append(1) or {'status': 'sent'}, now=mon + datetime.timedelta(hours=4), notify=lambda x: pushed.append(x['id']))
ok(not calls and pushed == [r6['id']], '… and it stays that way – no second notification, no send')
raises(lambda: Q.update(r6['id'], {'text': 'x'}, now=now), 'a missed mail needs a new time to go back in the queue')
Q.update(r6['id'], {'at': (mon + datetime.timedelta(hours=5)).isoformat()}, now=mon + datetime.timedelta(hours=4))
ok(Q.get(r6['id'])['status'] == 'scheduled', 'rescheduled')

print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
