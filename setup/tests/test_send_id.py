#!/usr/bin/env python3
"""Sends are idempotent (security review 4, P2-4): the same send_id posted twice – here 30 minutes apart, after the
job is long finished and "force" is set – sends one mail; the repeat gets "already sent". Fictional data, no Mail.
Run: python3 setup/tests/test_send_id.py"""
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

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


A.SEND_IDS_FILE = os.path.join(tempfile.mkdtemp(), 'send-ids.json')
clock = [1_800_000_000.0]
A.time.time = lambda: clock[0]
A.log = lambda *a, **k: None
sent = []


def post(payload):
    """The POST path of the action service for reply_send, with the Mail step replaced by a counter."""
    repeat, sid = A.send_id_accept('reply_send', payload, 'm@x')
    if repeat is not None:
        return repeat
    jid = uuid.uuid4().hex[:12]
    A.JOBS[jid] = {'id': jid, 'action': 'reply_send', 'state': 'queued'}
    A.send_id_update(sid, job=jid)
    sent.append(payload['text'])                        # the worker: Mail sends it
    A.JOBS[jid]['state'] = 'ok'
    A.send_id_update(sid, state='ok', error=None)
    return {'queued': True, 'job': jid}


sid = str(uuid.uuid4())
body = {'item_id': 'i1', 'message_id': 'm1', 'expect_to': 'lee@clientb.example', 'text': 'Thanks, Lee', 'send_id': sid}
r1 = post(dict(body))
ok(len(sent) == 1 and r1.get('job'), 'first POST: sent once')
clock[0] += 30 * 60                                     # the outbox re-sends 30 minutes later …
A.JOBS.clear()                                          # … the job is long gone (or the service restarted)
r2 = post(dict(body, force=True))
ok(len(sent) == 1 and r2.get('already_sent') and r2.get('repeat'), '30 minutes later, with force: "already sent", no second mail')
st = A.send_id_status(sid)
ok(st and st['state'] == 'ok', 'send_status: known, ok – the outbox drops it without sending')
ok(A.send_id_status(str(uuid.uuid4())) is None, 'send_status: an unknown send_id → never received')
post(dict(body, send_id=str(uuid.uuid4()), text='Second, on purpose'))
ok(len(sent) == 2, 'a new tap (new send_id) is a new send')
clock[0] += 49 * 3600
post(dict(body))
ok(len(sent) == 3, 'after 48 h the id is forgotten (the outbox drops replies after 24 h)')
# a send that failed: the repeat gets the same failure, not a new attempt
sid2 = str(uuid.uuid4())
A.send_id_accept('reply_send', {'send_id': sid2}, 'm@x')
A.send_id_update(sid2, state='error', error='Mail is not running')
try:
    A.send_id_accept('reply_send', {'send_id': sid2}, 'm@x')
    ok(False, 'a repeat of a failed send is refused with the earlier error')
except A.Bad as e:
    ok('Mail is not running' in str(e), 'a repeat of a failed send is refused with the earlier error')
for badid in ('x', '../etc', 'a' * 80):
    try:
        A.send_id_accept('reply_send', {'send_id': badid}, 'm@x')
        ok(False, 'bad send_id refused: %r' % badid[:10])
    except A.Bad:
        ok(True, 'bad send_id refused: %r' % badid[:10])
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
