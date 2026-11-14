#!/usr/bin/env python3
"""What Axella handles through the action service: the 403 gate for actions and pages of a switched-off feature (for
everyone when the owner switched it off; for one person when they did), GET features per person, card_set with the
dependency question, owner-only data delete, About you, and the
background loops idling. A test install – never the owner's real switches. Run: python3 setup/tests/test_features_actions.py"""
import importlib.util
import io
import json
import time
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
import features as F  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


tmp = tempfile.mkdtemp(prefix='axtest-')
st = os.path.join(tmp, 'state')
os.makedirs(st)
open(os.path.join(st, 'tasks.json'), 'w').write('[{"id": "t1", "text": "Call Robin"}]')        # an install in use: everything on
A.FEAT = F.Features(st, tmp)
REAL_CONFIG, REAL_STATE = A.CONFIG_FILE, A.STATE_DIR
_real_before = open(REAL_CONFIG, 'rb').read() if os.path.exists(REAL_CONFIG) else None
A.ABOUT_FILE = os.path.join(st, 'about.json')
cfgf = os.path.join(tmp, 'actions-config.json')
A.CONFIG_FILE = cfgf                                # never the real settings – set before any action runs
A.STATE_DIR = st                                    # the copy of the old settings goes to the test install
A.owner_logins = lambda: {'alex@example.com'}
A.log = lambda *a, **k: None
O, S = 'alex@example.com', 'sam@example.com'


def get(path, login):
    h = object.__new__(A.Handler)
    h.path = '/axella/api/' + path
    h.headers = {}
    out = {}
    h._login = lambda: login
    h._send = lambda code, obj: out.update(code=code, body=obj)
    h.do_GET()
    return out


def post(action, body, login):
    h = object.__new__(A.Handler)
    raw = json.dumps(body).encode()
    h.path = '/axella/api/' + action
    h.headers = {'X-Axella': '1', 'Content-Type': 'application/json', 'Content-Length': str(len(raw))}
    h.rfile = io.BytesIO(raw)
    out = {}
    h._login = lambda: login
    h._send = lambda code, obj: out.update(code=code, body=obj)
    h.do_POST()
    return out


A.do_action = (lambda real: (lambda action, p: 'did ' + action if action in ('trip_rename', 'task_add', 'birthday_show') else real(action, p)))(A.do_action)

print('The gate')
ok(get('features', S)['code'] == 200 and get('features', O)['body']['owner'] is True, 'GET features for anyone on the access list')
A.FEAT.set('trips', False, O, True)
r = get('trips', O)
ok(r['code'] == 403 and r['body']['feature_off'] == 'trips' and 'Trips is off' in r['body']['error'], 'a page of a feature the owner switched off: 403 feature_off')
r = post('trip_rename', {'id': 'x', 'name': 'y'}, S)
ok(r['code'] == 403 and r['body']['feature_off'] == 'trips', '… its actions too, for everyone')
ok(post('task_add', {'text': 'Call Robin'}, S)['code'] == 200, 'core actions are never gated')
A.FEAT.set('birthdays', False, S, False)
ok(post('birthday_show', {'id': 'x'}, S)['code'] == 403, "Sam's own switch gates Sam …")
ok(post('birthday_show', {'id': 'x'}, O)['code'] == 200, '… not the owner')
r = post('meeting_record_chunk', {}, O)
A.FEAT.set_card('calendar', False, O, True, confirm=True)
r = post('meeting_record_chunk', {}, O)
ok(r['code'] == 403 and r['body']['feature_off'] == 'meeting_recordings', 'raw uploads are gated before their body is read')
A.FEAT.set_card('calendar', True, O, True, confirm=True)

print('Switching from Settings')
r = post('card_set', {'card': 'money', 'on': False}, O)
ok(r['code'] == 200 and set(r['body']['result']['changed']) == set(F.features_of('money')), 'card_set off: the whole card')
r = post('feature_set', {'id': 'renewals', 'on': True}, O)
ok(r['code'] == 200 and 'needs Receipts' in r['body']['result']['confirm'], 'feature_set answers with the dependency question first')
r = post('feature_set', {'id': 'renewals', 'on': True, 'confirm': True}, O)
ok(set(r['body']['result']['changed']) == {'renewals', 'receipts'}, '… then switches both')
ok(post('feature_data_delete', {'card': 'trips'}, S)['code'] == 403, "deleting an area's data: owner only")
r = post('feature_data_delete', {'card': 'trips'}, O)
ok(r['code'] == 200 and r['body']['result']['backup'].startswith('trips-'), '… the owner can, while it is off')

print('About you (owner only)')
ok(post('setup_about', {'name': 'Alex Example'}, S)['code'] == 403, 'not for anyone else')
A.RUNNER.load = lambda: {'digests': [{'id': 'morning', 'task': 'digest-morning', 'time': '07:30', 'days': [0, 1], 'enabled': True}]}
sent = []
A.RUNNER.action = lambda a, p: sent.append((a, p)) or 'saved'
r = post('setup_about', {'name': 'Alex Example', 'language': 'en', 'work_hours': {'days': [0, 1, 2, 3, 4], 'from': '08:30', 'to': '16:30'},
                         'digest_time': '07:15', 'mode': 'mixed'}, O)
ok(r['code'] == 200 and A.config()['owner']['first_name'] == 'Alex' and A.config()['work_hours']['from'] == '08:30', 'saved, and the settings read it')
ok(sent and sent[0][1]['digests'][0]['time'] == '07:15', 'the morning digest time goes to the schedule')
ok(post('setup_about', {'work_hours': {'days': [], 'from': '09:00', 'to': '08:00'}}, O)['code'] == 400, 'nonsense work hours are refused')
v = get('features', O)['body']
ok(v['about']['name'] == 'Alex Example' and v['about']['mode'] == 'mixed', 'GET features shows About you to the owner …')
ok(get('features', S)['body']['about'] is None, '… and not to anyone else')

print('Background work idles')
A.FEAT.set('bills', False, O, True)
ok(not A._bg('bills') and A._bg('to_answer'), "_bg follows the owner's switches")
src = open(os.path.join(HERE, 'axella-actions.py'), encoding='utf-8').read()
for fn, fid in (('_bills_loop', 'bills'), ('_trip_watch_loop', 'trips'), ('_scheduled_loop', 'send_later'),
                ('_commit_loop', 'to_answer'), ('_birthday_loop', 'birthdays'), ('_renewals_loop', 'renewals'), ('_recurring_loop', 'subscriptions')):
    body = src[src.index('def %s(' % fn):]
    body = body[:body.index('\ndef ', 1)]
    ok("if not _bg(%r)" % fid in body, '%s idles while %s is off' % (fn, fid))
ok("_when_on('receipts', DOCS.run" in src and "_when_on('mail_tidy', CLEAN.run)" in src and "_when_on('call_agent', VOICE.run)" in src,
   "the modules' own loops start only once their feature is on")

print('The guided setup writes the real settings (with a copy of the old ones)')
json.dump({'owner': {'name': 'Alex Example', 'first_name': 'Alex', 'sign_off': 'br Alex'},
           'accounts': {'iCloud': {'label': 'iCloud', 'kind': 'private', 'address': 'alex.home@example.com'},
                        'Northwind': {'label': 'Northwind', 'kind': 'work', 'workplace': 'northwind'}},
           'calendars': [{'name': 'Home', 'kind': 'private'}]}, open(cfgf, 'w'))
A.osa = lambda *a, **k: 'id1\tiCloud\nid2\tNorthwind\nid3\tOld club\n'
A.calendar_view_calendars = None
v = get('setup_sources', O)['body']
ok([(a['name'], a['read'], a['found']) for a in v['accounts']] == [('iCloud', True, True), ('Northwind', True, True), ('Old club', False, True)],
   "the accounts on this Mac, with what is read now (names only)")
ok(get('setup_sources', S)['code'] == 403, '… owner only')
r = post('setup_sources_save', {'accounts': [{'name': 'iCloud', 'read': True, 'kind': 'private'}, {'name': 'Northwind', 'read': False},
                                             {'name': 'Old club', 'read': True, 'kind': 'work'}],
                                'calendars': [{'name': 'Home', 'kind': 'ignore'}, {'name': 'Northwind', 'kind': 'work'}],
                                'channels': {'imessage': True, 'whatsapp': False, 'signal': True}, 'lookback': 30}, O)
c = json.load(open(cfgf))
ok(r['code'] == 200 and set(c['accounts']) == {'iCloud', 'Old club'} and c['accounts']['Old club']['kind'] == 'work'
   and c['accounts']['iCloud']['address'] == 'alex.home@example.com', 'accounts: read or not, work or private – the rest of each entry kept')
ok([x['name'] for x in c['calendars']] == ['Northwind'] and c['channels'] == {'imessage': True, 'whatsapp': False, 'signal': True}, 'calendars and channels')
ok(len(os.listdir(os.path.join(st, 'config-backups'))) == 1 and oct(os.stat(cfgf).st_mode & 0o777) == '0o600', 'a copy of the old settings first; the new file owner-only')
ok(post('setup_sources_save', {'accounts': []}, S)['code'] == 403, '… owner only')

print('What the runs are told')
import scheduler as SCH  # noqa: E402
import axprofile  # noqa: E402
axprofile.CONFIG = cfgf
sch = SCH.Scheduler(tmp, st, None, lambda *a, **k: None)
note = sch._setup_note('digest-morning')
ok('iCloud (private), Old club (work). Leave any other mailbox out.' in note and 'Not read, by the owner\'s choice: WhatsApp.' in note, 'the digest is told which accounts and channels')
ok('look back 30 days' in note, '… and, before the first digest, how far back')
ok(sch._channels().get('whatsapp') is False, 'WhatsApp off: its export is denied to the runs (see _command)')

print('Search leaves out what is off')
A.STORE.search = lambda q: [{'id': 'a', 'section': 'file', 'channel': 'mail'}, {'id': 'b', 'section': 'p1', 'channel': 'call', 'project': 'acme'},
                            {'id': 'c', 'section': 'p2', 'channel': 'mail', 'project': 'acme'}]
A.SAFETY.flag_of = lambda h: None
A.FEAT.set('call_agent', False, O, True)
A.FEAT.set('projects', False, O, True, confirm=True)
ids = [(h['id'], h.get('project')) for h in get('search?q=acme', O)['body']['items']]
ok(ids == [('a', None), ('c', None)], 'no calls when the call agent is off, no project tags when Projects is off')
A.FEAT.set('filing', False, S, False)
ok([h['id'] for h in get('search?q=acme', S)['body']['items']] == ['c'], "… and Sam's own switch (filing) only for Sam")

print('The real Axella is never touched')
ok((open(REAL_CONFIG, 'rb').read() if os.path.exists(REAL_CONFIG) else None) == _real_before, 'the real setup/actions-config.json is unchanged')
ok(not os.path.exists(os.path.join(REAL_STATE, 'config-backups')) or all(not f.startswith('actions-config-' + time.strftime('%Y%m%d-%H%M'))
   for f in os.listdir(os.path.join(REAL_STATE, 'config-backups'))), '… and no copy landed in the real state/')

print()
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
