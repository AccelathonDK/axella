#!/usr/bin/env python3
"""Watchdog: session detection, the confirm-twice rule, one push on loss and one on recovery. No network, no ps.
Run: python3 setup/tests/test_watchdog.py"""
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import watchdog as W  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


PS = '  0 /sbin/launchd\n501 /System/Library/CoreServices/loginwindow.app/Contents/MacOS/loginwindow\n502 /usr/bin/zsh\n'
ok(W.has_session(501, PS) is True, 'owner logged in: their loginwindow runs')
ok(W.has_session(502, PS) is False, 'another user without a session')
ok(W.has_session(501, '501 /usr/bin/ssh\n') is False, 'only SSH: no session')

srv = socket.socket(); srv.bind(('127.0.0.1', 0)); srv.listen(1)
ok(W.port_open(srv.getsockname()[1]) is True, 'port open')
port = srv.getsockname()[1]; srv.close()
ok(W.port_open(port) is False, 'port closed')

sent = []
send = lambda t, b: sent.append(t)
bad = {'at': 't1', 'ok': False, 'problem': 'x', 'session': False, 'actions': False}
good = {'at': 't9', 'ok': True, 'problem': None, 'session': True, 'actions': True}
s = W.step({}, dict(bad), send)
ok(not sent and s['bad_checks'] == 1, 'first bad check: no push yet (a restart must not alert)')
s = W.step(s, dict(bad, at='t2'), send)
ok(sent == ['Axella is paused'] and s['since'] == 't1', 'second bad check: one push; since = first bad check')
s = W.step(s, dict(bad, at='t3'), send)
ok(sent == ['Axella is paused'], 'still down: no second push')
s = W.step(s, dict(good), send)
ok(sent == ['Axella is paused', 'Axella is back'] and s['since'] == 't9', 'recovery: one push')
s = W.step(s, dict(good, at='t10'), send)
ok(len(sent) == 2, 'all fine: quiet')
s = W.step(W.step({}, dict(bad), send), dict(good), send)
ok(len(sent) == 2, 'a one-minute blip: no push at all')

# sources: Mail from ps, WhatsApp/Signal from their export files – one push after an hour, one on recovery
import json, tempfile, datetime as _dt
W.STATE = tempfile.mkdtemp()
fresh = _dt.datetime.now().astimezone().isoformat(timespec='seconds')
json.dump({'ok': True, 'generated': fresh}, open(os.path.join(W.STATE, 'whatsapp.json'), 'w'))
ps = '501 /System/Applications/Mail.app/Contents/MacOS/Mail\n'
W.os.getuid = lambda: 501
ok(W.sources(ps) == {'Mail': None, 'WhatsApp': None}, 'all readable; Signal not set up is not checked')
json.dump({'ok': False, 'generated': fresh, 'error': 'x'}, open(os.path.join(W.STATE, 'whatsapp.json'), 'w'))
json.dump({'linked': True, 'generated': '2020-01-01T00:00:00+00:00'}, open(os.path.join(W.STATE, 'signal.json'), 'w'))
src = W.sources('')
ok(src['Mail'] and src['WhatsApp'] and 'hasn' in src['Signal'], 'Mail not running, WhatsApp unreadable, Signal stale')
sent2 = []
hour_ago = (_dt.datetime.now().astimezone() - _dt.timedelta(minutes=61)).isoformat(timespec='seconds')
base = {'at': fresh, 'ok': True, 'problem': None, 'session': True, 'actions': True}
s1 = W.step({}, dict(base, sources={'WhatsApp': 'WhatsApp can\'t be read'}), lambda t, b: sent2.append(t))
ok(not sent2 and s1['source_state']['WhatsApp']['since'] == fresh, 'source down: no push in the first hour')
s1['source_state']['WhatsApp']['since'] = hour_ago
s2 = W.step(s1, dict(base, sources={'WhatsApp': 'WhatsApp can\'t be read'}), lambda t, b: sent2.append(t))
s3 = W.step(s2, dict(base, sources={'WhatsApp': 'WhatsApp can\'t be read'}), lambda t, b: sent2.append(t))
ok(sent2 == ["Axella can't read WhatsApp"], 'after an hour: one push, not repeated')
W.step(s3, dict(base, sources={'WhatsApp': None}), lambda t, b: sent2.append(t))
ok(sent2[-1] == 'Axella reads WhatsApp again', 'readable again: one push')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
