"""voice_sync: call-record checks, push wording, quiet hours, hashed contacts, fetch. Run: python3 setup/tests/test_voice_sync.py
(no network, no real data: fake Contacts, fake call agent, temp folder)."""
import datetime, hashlib, hmac, io, json, os, sys, tempfile
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import voice_sync as V
fails = 0
def ok(c, m):
    global fails
    print(('PASS ' if c else 'FAIL ') + m); fails += 0 if c else 1

c = V.coerce_call({'id': 'call-CA1', 'priority': 'URGENT', 'summary': {'x': 1}, 'callback': 'now', 'from': {'name': 'Jamie', 'said_name': 'Sam Rivera', 'caller_id_match': True, 'number': '+4511111111', 'tier': 'VIP'},
                   'transcript': [{'who': 'Caller', 'text': 'hej'}, 'junk', {'who': 'x', 'text': 5}], 'sms_draft': 'Hej [link](https://x.example) <b>y</b>', 'duration_s': 'long'})
ok(c['priority'] == 'p2' and c['summary'] == '' and c['callback'] is None, 'coerce: bad priority/summary/callback')
ok(c['sms_draft'] == 'Hej link y', 'coerce: links and tags stripped')
ok(len(c['transcript']) == 2 and c['transcript'][1] == {'who': 'Axella', 'text': ''} and c['duration_s'] is None, 'coerce: transcript + duration')
ok(V.coerce_call('x') is None, 'coerce: non-dict → None')
t, b = V.VoiceSync.push_text(c)
ok('Sam Rivera (caller ID matches Jamie)' in t, 'push: mismatch shown as "matches": ' + t)
c2 = dict(c, **{'from': dict(c['from'], said_name='Jamie'), 'priority': 'p0', 'summary': '**Call** me', 'callback': {'by': None, 'number': '+4500000099', 'other_number': True}})
t, b = V.VoiceSync.push_text(c2)
ok(t == '⚠ Axella – caller says urgent: Jamie' and b.startswith('Asks for a call back on another number. Call me'), 'push: p0 + other number: %s / %s' % (t, b))
ok(V.no_message({'priority': 'p3', 'transcript': []}) and not V.no_message({'priority': 'p3', 'transcript': [{'who': 'Caller', 'text': 'x'}]}), 'no_message')
D = lambda h: datetime.datetime(2026, 11, 2, h)
ok(V.in_quiet_hours([22, 7], D(23)) and V.in_quiet_hours([22, 7], D(3)) and not V.in_quiet_hours([22, 7], D(12)) and not V.in_quiet_hours(None, D(23)), 'quiet hours')

base = tempfile.mkdtemp(); st = os.path.join(base, 'state'); os.makedirs(st)
open(os.path.join(base, 'contacts.md'), 'w').write('## VIP – family\n- Jamie Test (partner)\n- Kim Example – +45 88 88 88 88\n## Machines\n- Sam Rivera\n')
open(os.path.join(st, 'voice-token'), 'w').write('t' * 64)
key = 'k' * 64; open(os.path.join(st, 'voice-lookup-key'), 'w').write(key)
cfg = {'voice': {'url': 'https://example.invalid'}, 'owner': {'name': 'Alex Example'}}
osa_out = '\x1e'.join('\x1f'.join(x) for x in [('Jamie Test', '+45 11 11 11 11'), ('Kim Example', '0045 88888888'), ('Kim Example', '+45 99 99 99 99'), ('Sam Rivera', '22222222'), ('Lee Chen', '555-1234')]) + '\x1e'
pushed = []
vs = V.VoiceSync(base, st, lambda: cfg, lambda s, timeout=0: osa_out, pushed.append, log=io.StringIO())
sent = {}
def fake_req(method, url, token, body=None, timeout=20):
    sent[method + ' ' + url.split('example.invalid')[1]] = body
    if method == 'POST': return {'ok': True, 'contacts': len(body['contacts']), 'lookup_key': True}
    if method == 'GET': return {'calls': [
        {'id': 'call-CA2', 'priority': 'p2', 'summary': 'Wants **a call**', 'from': {'name': 'Jamie', 'said_name': 'Jamie', 'caller_id_match': True, 'number': '+4511111111', 'tier': 'VIP'}, 'transcript': [{'who': 'Caller', 'text': 'hej'}]},
        {'id': '../../etc/x', 'priority': 'p1', 'summary': 'x'},
        {'id': 'call-CA3', 'priority': 'p3', 'summary': 'Hung up without leaving a message.', 'from': {'number': '+4599999999'}, 'transcript': []}]}
    return {'ok': True}
vs._req = fake_req
res = vs.push_config()
body = sent['POST /api/config']
ok(all(set(x) == {'h', 'first', 'tier'} for x in body['contacts']), 'push_config: hashed form only')
hj = hmac.new(key.encode(), b'+4511111111', hashlib.sha256).hexdigest()
tiers = {x['h']: x['tier'] for x in body['contacts']}
hk1 = hmac.new(key.encode(), b'+4588888888', hashlib.sha256).hexdigest(); hk2 = hmac.new(key.encode(), b'+4599999999', hashlib.sha256).hexdigest()
ok(tiers.get(hj) == 'VIP' and tiers.get(hk1) == 'VIP' and tiers.get(hk2) == 'Known', 'VIP by name; VIP line with number → only that number')
ok(len(body['contacts']) == 4, 'number without country code (555-1234) skipped, 8-digit → +45')
ok(not any('Test' in json.dumps(x) for x in body['contacts']), 'no surnames sent')
n = vs.fetch_once()
files = sorted(os.listdir(os.path.join(base, 'calls')))
ok(n == 2 and files == ['call-CA2.json', 'call-CA3.json'], 'fetch: traversal id dropped, 2 saved: %s' % files)
saved = json.load(open(os.path.join(base, 'calls', 'call-CA2.json')))
ok(saved['from']['name'] == 'Jamie Test', 'full contact name restored on the Mac')
ok(oct(os.stat(os.path.join(base, 'calls', 'call-CA2.json')).st_mode & 0o777) == '0o600', 'call file 600')
ok(len(pushed) <= 1 and all('CA3' not in p['tag'] for p in pushed), 'no push for hang-up; pushes: %d' % len(pushed))
ok('DELETE /api/calls?id=call-CA2' in sent and 'DELETE /api/calls?id=call-CA3' in sent, 'deleted on Vercel')
cfg['voice']['url'] = 'http://example.invalid'
try: vs.fetch_once(); ok(False, 'http url refused')
except ValueError: ok(True, 'http url refused')
cfg['voice']['url'] = 'https://example.invalid'
vs.osa = lambda s, timeout=0: ''
ok(vs.push_config() is None, 'empty Contacts → not pushed')
print('ALL PASSED' if not fails else '%d FAILED' % fails); sys.exit(1 if fails else 0)
