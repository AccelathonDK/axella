#!/usr/bin/env python3
"""Send later through the send_id guard (axella-actions.py scheduled_send_via_queue): a timeout is "unknown", a retry
after a refusal sends, a retry after a send never sends twice, and a retry after a timeout needs your check of Sent.
The job queue is stubbed. Fictional cast. Run: python3 setup/tests/test_scheduled_guard.py"""
import importlib.util
import os
import sys
import tempfile
import uuid

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
import scheduled as S  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


d = tempfile.mkdtemp()
A.SEND_IDS_FILE = os.path.join(d, 'send-ids.json')
A.LOG_FILE = os.path.join(d, 'actions.log')
outcome = {'next': 'ok'}
mails = []


def queue_job(action, payload, login):
    """Like the job worker: runs at once, records the outcome on the job and on the send_id."""
    jid = uuid.uuid4().hex[:12]
    if outcome['next'] == 'ok':
        mails.append(payload['send_id'])
        A.JOBS[jid] = {'id': jid, 'state': 'ok', 'result': {'status': 'sent'}}
        A.send_id_update(payload['send_id'], state='ok')
    else:
        if outcome['next'] == 'timeout':
            mails.append(payload['send_id'])                 # Mail did send it, but didn't say so in time
            err = "Mail didn't confirm in time – it may have sent anyway. Check Sent in Mail before sending again."
        else:
            err = 'more than 20 mails in an hour – wait a little'
        A.JOBS[jid] = {'id': jid, 'state': 'error', 'error': err}
        A.send_id_update(payload['send_id'], state='error', error=err)
    return jid


A.queue_job = queue_job
sid = uuid.uuid4().hex
p = {'send_id': sid, 'account': 'iCloud', 'to': 'lee@acme.example', 'subject': 'Quote', 'text': 'Hi', 'confirm': 'send'}

outcome['next'] = 'refused'
try:
    A.scheduled_send_via_queue('mail_send', dict(p), '')
    ok(False, 'a refusal raises')
except A.Bad:
    ok(not mails, 'refused before sending: Bad, nothing went')
outcome['next'] = 'ok'
r = A.scheduled_send_via_queue('mail_send', dict(p), '')
ok(r == {'status': 'sent'} and mails == [sid], 'Try again after a refusal sends – once')
r = A.scheduled_send_via_queue('mail_send', dict(p), '')
ok(r.get('repeat') and mails == [sid], 'Try again after it went: the earlier outcome, never a second mail')

sid2 = uuid.uuid4().hex
outcome['next'] = 'timeout'
try:
    A.scheduled_send_via_queue('mail_send', dict(p, send_id=sid2), '')
    ok(False, 'a timeout raises Unknown')
except S.Unknown:
    ok(mails == [sid, sid2], 'a timeout: Unknown (Mail may have sent it)')
outcome['next'] = 'ok'
try:
    A.scheduled_send_via_queue('mail_send', dict(p, send_id=sid2), '')
    ok(False, 'retry without your check refused')
except S.Unknown:
    ok(mails == [sid, sid2], 'Try again after a timeout without checking Sent: refused, nothing sent')
A.scheduled_send_via_queue('mail_send', dict(p, send_id=sid2), '', checked=True)
ok(mails == [sid, sid2, sid2], '… and sent once you confirmed Sent does not have it')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
