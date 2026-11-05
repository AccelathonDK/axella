#!/usr/bin/env python3
"""Calls and private contacts: a private caller's call never lands in calls/ (the digest runs read it) – only who and
when reach the Private card; a hidden caller is not kept and not sent to the call agent. No network.
Run: python3 setup/tests/test_voice_privacy.py"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import privacy  # noqa: E402
import voice_sync as V  # noqa: E402
import whatsapp_export  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


base = tempfile.mkdtemp()
state = os.path.join(base, 'state')
os.makedirs(state)
whatsapp_export.OUT = os.path.join(state, 'whatsapp.json')          # private-inbox.json lands next to it
json.dump({'defaults': {}, 'contacts': [
    {'id': 'c1', 'name': 'Lee Chen', 'ids': ['+4500000001'], 'levels': {'calls': 'private'}},
    {'id': 'c2', 'name': 'Sam Rivera', 'ids': ['+4500000002'], 'levels': {'calls': 'hidden'}},
    {'id': 'c3', 'name': 'Robin', 'ids': ['+4500000003'], 'levels': {'whatsapp': 'private'}}]},
    open(os.path.join(state, 'privacy.json'), 'w'))
pv = privacy.Privacy(state)

reqs, pushes = [], []


def call(cid, num, said='Caller'):
    return {'id': cid, 'started': '2099-01-01T10:00:00+01:00', 'priority': 'p2', 'summary': 'secret summary text',
            'from': {'number': num, 'said_name': said, 'name': 'X', 'caller_id_match': True},
            'transcript': [{'who': 'Caller', 'text': 'secret transcript text'}]}


calls = [call('call-a', '+4500000001'), call('call-b', '+4500000002'), call('call-c', '+4500000003'), call('call-d', '+4500000009')]
vs = V.VoiceSync(base, state, lambda: {'voice': {'url': 'https://agent.example'}}, None, pushes.append, privacy=pv)
open(os.path.join(state, 'voice-token'), 'w').write('t' * 40)


def fake_req(method, url, token, body=None, timeout=20):
    reqs.append((method, url))
    return {'calls': calls} if method == 'GET' else {}


vs._req = fake_req
vs._push_call = lambda cid, c: pushes.append(cid)
n = vs.fetch_once()
saved = sorted(os.listdir(os.path.join(base, 'calls')))
ok(saved == ['call-c.json', 'call-d.json'], 'only normal callers are saved in calls/ (private-elsewhere and unknown count as normal)')
ok(sorted(pushes) == ['call-c', 'call-d'], 'no call push for private or hidden callers')
ok(sum(1 for m, u in reqs if m == 'DELETE') == 4, 'every call is removed from the call agent, private and hidden too')
pc = json.load(open(os.path.join(state, 'private-calls.json')))
raw = json.dumps(pc)
ok(list(pc) == ['c1'] and 'secret' not in raw and pc['c1']['name'] == 'Lee Chen', 'private: who and when only; hidden: nothing')
inbox = json.load(open(os.path.join(state, 'private-inbox.json')))
row = inbox['calls']['chats'][0]
ok(row['name'] == 'Lee Chen' and row['channel'] == 'calls' and row['last_at'].startswith('2099'), 'Private card row for the call')
ok('secret' not in json.dumps(inbox), 'no summary or transcript on the Private card')

# someone made private later: their saved call leaves calls/
d = json.load(open(os.path.join(state, 'privacy.json')))
d['contacts'][2]['levels']['calls'] = 'private'
json.dump(d, open(os.path.join(state, 'privacy.json'), 'w'))
pv = privacy.Privacy(state); vs.privacy = pv
ok(vs.scrub() == 1 and sorted(os.listdir(os.path.join(base, 'calls'))) == ['call-d.json'], 'scrub: moved out of calls/')
ok(os.path.exists(os.path.join(state, 'private-calls', 'call-c.json')), '… into state/private-calls/, not deleted')
ok('c3' in json.load(open(os.path.join(state, 'private-calls.json'))), '… and listed on the Private card')
ok(vs._level({'from': {'number': '+4500000002'}}) == 'hidden', 'hidden level for the contacts push')

# every way a private caller's number may be written (security review 4, P2-2) – contact saved with and without +45
for saved in ('12345678', '+45 12 34 56 78'):
    st2 = tempfile.mkdtemp()
    json.dump({'defaults': {}, 'contacts': [{'id': 'c9', 'name': 'Kim Example', 'ids': [saved], 'levels': {'calls': 'private'}}]},
              open(os.path.join(st2, 'privacy.json'), 'w'))
    v2 = V.VoiceSync(base, st2, lambda: {}, None, lambda *a: None, privacy=privacy.Privacy(st2))
    for form in ('+4512345678', '+45 12 34 56 78', '004512345678', '12345678'):
        ok(v2._level({'from': {'number': form}}) == 'private', 'contact saved as %s, caller %s: private' % (saved, form))
    ok(v2._level({'from': {'number': '+4587654321'}}) == 'normal', 'contact saved as %s: another number stays normal' % saved)
    ok(v2._level({'from': {'number': ''}}) == 'normal' and v2._level({'from': {'number': None}}) == 'normal',
       'empty or withheld number: normal (nobody to match)')
# the contacts sent to the call agent (security review 4, P2-3): Private flagged, Hidden left out, no plain mode
st3 = tempfile.mkdtemp()
json.dump({'defaults': {}, 'contacts': [
    {'id': 'p1', 'name': 'Lee Chen', 'ids': ['+4500000001'], 'levels': {'calls': 'private'}},
    {'id': 'p2', 'name': 'Sam Rivera', 'ids': ['+4500000002'], 'levels': {'calls': 'hidden'}},
    {'id': 'p3', 'name': 'Robin Example', 'ids': ['00 45 00 00 00 07'], 'levels': {'calls': 'private'}}]},   # not in Contacts
    open(os.path.join(st3, 'privacy.json'), 'w'))
osa_out = '\x1e'.join('\x1f'.join(x) for x in [('Lee Chen', '+45 00 00 00 01'), ('Sam Rivera', '00000002'), ('Jamie Test', '+4500000003')])
bodies = []
v3 = V.VoiceSync(base, st3, lambda: {'voice': {'url': 'https://agent.example'}}, lambda sc, timeout=0: osa_out, lambda *a: None,
                 privacy=privacy.Privacy(st3))
v3._req = lambda m, u, t, b=None, timeout=20: bodies.append(b) or {'contacts': len((b or {}).get('contacts') or []), 'lookup_key': True}
open(os.path.join(st3, 'voice-token'), 'w').write('t' * 40)
ok(v3.push_config() is None and not bodies, 'plain mode (no lookup key) with private/hidden callers: nothing pushed')
ok(json.load(open(os.path.join(st3, 'voice-status.json'))).get('lookup') == 'refused-plain-private', '… and the status says why')
open(os.path.join(st3, 'voice-lookup-key'), 'w').write('k' * 40)
v3.push_config()
cs = bodies[-1]['contacts']
firsts = {c['first']: c for c in cs}
ok(firsts.get('Lee', {}).get('private') is True and 'Jamie' in firsts and not firsts['Jamie'].get('private'), 'Private flagged, Normal not')
ok('Sam' not in firsts, 'Hidden not sent at all')
ok(firsts.get('Robin', {}).get('private') is True, 'a Private caller not in Contacts is sent too (flagged)')
ok(all(set(c) <= {'h', 'first', 'tier', 'private'} for c in cs), 'hashed form only: no names or numbers')
ok(V.normalise_number('004512345678') == V.normalise_number('12345678') == '+4512345678', 'normalise_number: 00 and 8 digits')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
