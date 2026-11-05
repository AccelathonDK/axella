#!/usr/bin/env python3
"""An unreadable state/privacy.json must make Axella stricter, never looser (security review 4, P2-1).
Missing file = first run (defaults). Present but unreadable = everyone private, the MCP filter on, no new exports.
Fictional data only. Run: python3 setup/tests/test_privacy_broken.py"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import privacy as P  # noqa: E402
import mcp_filter  # noqa: E402
import scheduler  # noqa: E402
import signal_export  # noqa: E402
import private_local  # noqa: E402
import voice_sync as V  # noqa: E402
import whatsapp_export  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def state_with(content):
    d = tempfile.mkdtemp()
    if content is not None:
        with open(os.path.join(d, 'privacy.json'), 'w', encoding='utf-8') as f:
            f.write(content)
    return d


good = json.dumps({'defaults': {}, 'contacts': [{'id': 'c1', 'name': 'Lee Chen', 'ids': ['+4500000001'], 'levels': {'calls': 'private'}}]})
missing, corrupt, wrong = state_with(None), state_with('{broken'), state_with('["not", "an", "object"]')

ok(P.Privacy(missing).broken() is False and P.Privacy(missing).level('calls', '+4500000009') == 'normal',
   'missing file: a first run with the defaults')
ok(P.Privacy(state_with(good)).broken() is False, 'a good file is not broken')
for name, d in (('corrupt JSON', corrupt), ('JSON that is not an object', wrong)):
    pv = P.Privacy(d)
    ok(pv.broken() and all(v == 'private' for v in pv.load()['defaults'].values()), name + ': broken, every platform private')
    ok(pv.level('calls', '+4500000001') == 'private' and pv.level('whatsapp', '+4500000009') == 'private',
       name + ': known and unknown people private')
try:
    P.Privacy(corrupt).set({'defaults': {'mail': 'normal'}})
    ok(False, 'saving while broken is refused')
except P.Bad:
    ok(open(os.path.join(corrupt, 'privacy.json')).read() == '{broken', 'saving while broken is refused; the file is left as it was')

# unreadable for the service (e.g. wrong owner after a restore)
unreadable = state_with(good)
os.chmod(os.path.join(unreadable, 'privacy.json'), 0)
if os.geteuid() != 0:                                     # root can read anything – skip there
    ok(P.Privacy(unreadable).broken(), 'no read permission: broken')

# voice_sync
vs = V.VoiceSync(tempfile.mkdtemp(), corrupt, lambda: {}, None, lambda *a: None, privacy=P.Privacy(corrupt))
ok(vs._level({'from': {'number': '+4500000001'}}) == 'private', 'call agent: a known number is private')
ok(vs._level({'from': {'number': None}}) == 'private', 'call agent: even a withheld number is private')

# the MCP filter
m = mcp_filter.Matcher(P.Privacy(corrupt), 'mail')
ok(m.all is True and not m.empty(), 'MCP filter: Matcher.all – every Mail result is withheld')
ok(mcp_filter.Matcher(P.Privacy(corrupt), 'calendar').all is True, 'MCP filter: calendar too')
base = tempfile.mkdtemp()
os.makedirs(os.path.join(base, 'setup'))
s = scheduler.Scheduler(base, corrupt, None, lambda *a: None)
ok(s._privacy_strict('mail') and s._privacy_strict('imessage'), 'scheduler: strict for Mail and iMessage')
ok(s.run_mcp_file().endswith('mcp-filtered.json'), 'scheduler: runs get the filtered MCP config')

# exporters write nothing new
whatsapp_export.OUT = os.path.join(corrupt, 'whatsapp.json')
whatsapp_export.export = lambda: {'ok': True, 'chats': [{'jid': '+4500000009', 'name': 'Sam Rivera', 'messages': [{'text': 'x'}]}]}
r = whatsapp_export.write()
ok(not r['ok'] and not os.path.exists(whatsapp_export.OUT), 'WhatsApp: no whatsapp.json written')
signal_export.STATE, signal_export.OUT = corrupt, os.path.join(corrupt, 'signal.json')
signal_export.binary = lambda: (_ for _ in ()).throw(AssertionError('signal-cli must not be called'))
r = signal_export.write()
ok(not r['ok'] and not os.path.exists(signal_export.OUT), 'Signal: nothing received, no signal.json written')
private_local.STATE = corrupt
private_local.imessage = private_local.mail = lambda pv: (_ for _ in ()).throw(AssertionError('must not be read'))
private_local.write()
ok(not os.path.exists(os.path.join(corrupt, 'private-inbox.json')), 'Private card: nothing new written')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
