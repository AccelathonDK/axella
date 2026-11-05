#!/usr/bin/env python3
"""Report a problem – the Mac mini side: the allow-list payload, error templates, the text check, save/send.
Fictional data only; nothing is sent anywhere (the intake is replaced by a function). Run: python3 setup/tests/test_reports.py"""
import base64
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import reports as R  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


PNG = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'\0' * 40).decode()

# templates: values out of error messages
t = R.template('Failed to parse message from "Lee Chen" <lee@clientb.example> at /Users/alex/Library/Mail id 1234567')
ok('Lee' not in t and 'clientb' not in t and '/Users' not in t and '1234567' not in t and t.startswith('Failed to parse message from'),
   'error message becomes a template: ' + t)
ok('Sam Rivera' not in R.template('Could not reach Sam Rivera'), 'two capitalised words count as a name')

# the payload: allow-list only
rep = {'class': 'annoying', 'text': 'The Send button does nothing', 'route': 'today', 'trail': ['open_route:today', 'tap:send', 'Lee Chen opened', 'act:reply_send'],
       'errors': [{'message': 'TypeError: x of "Lee" undefined', 'frames': ['at f (assets/index-AbC12.js:1:200)', 'at /Users/alex/x.js:1:1'], 'secret': 1}],
       'meta': {'app_version': '2026.11', 'commit': 'abc1234', 'os': 'macOS', 'os_version': '15.1', 'mac_model': 'Macmini9,1', 'ram_tier': '16 GB',
                'connectors': ['mail', 'whatsapp', 'evil'], 'theme': 'dark', 'locale': 'en-GB', 'hostname': 'alexs-mac-mini', 'user': 'alex@x.example'},
       'owner_email': 'alex@x.example', 'at': 'x'}
pl = R.payload(rep, 'tok')
s = json.dumps(pl)
ok(set(pl) == {'v', 'class', 'text', 'route', 'trail', 'errors', 'meta', 'render', 'install'}, 'only allow-listed top-level keys')
ok(set(pl['meta']) == set(R.META_KEYS) and 'hostname' not in s and 'alex@x.example' not in s, 'only allow-listed metadata (no hostname, no account)')
ok(pl['meta']['connectors'] == ['mail', 'whatsapp'], 'connector types from the fixed list only')
ok(pl['trail'] == ['open_route:today', 'tap:send', 'act:reply_send'], 'trail keeps action names only')
ok(pl['errors'][0]['frames'] == ['at f (assets/index-AbC12.js:1:200)'] and 'Lee' not in s and '/Users' not in s, 'own-code frames only, message templated')
try:
    R.payload({**rep, 'class': 'whatever'}, 'tok'); ok(False, 'class is checked')
except R.Bad:
    ok(True, 'class is checked')
ok(R.payload(rep, 'tok', reply='lee@clientb.example')['reply'] == 'lee@clientb.example', 'optional reply address')

# the text check
fl = R.check_text('Lee Chen sent it to lee@clientb.example, call +45 00 00 00 07, card 4111 1111 1111 1111, see https://acme.example/inbox/123',
                  ['Lee Chen', 'Sam Rivera'])
kinds = {f['kind'] for f in fl}
ok({'email', 'phone number', 'card or account number', 'link with a path', 'name from your contacts'} <= kinds, 'text check flags: %s' % sorted(kinds))
ok(not R.check_text('The Today page loads slowly', ['Lee Chen']), 'ordinary text is not flagged')
ok(R.suggest_class('The app crashed and my draft is gone') == 'critical' and R.suggest_class('Could you add dark mode for briefs') == 'missing'
   and R.suggest_class('The icon is misaligned') == 'cosmetic' and R.suggest_class('Filing takes two taps') == 'annoying', 'class suggestion')

# save → preview → send (community, with a fake intake) and developer mode
base = tempfile.mkdtemp(); st = os.path.join(base, 'state'); os.makedirs(st)
cfg = {'reports': {'mode': 'community', 'intake': 'https://intake.example/api/report'}}
rs = R.Reports(base, st, lambda: cfg)
r = rs.save({**rep, 'render': PNG, 'full': PNG, 'suggested': 'annoying'})
ok(r['status'] == 'kept' and r['has_render'] and not r['has_full'], 'saved locally first; the real screen is not kept in community mode')
ok(oct(os.stat(rs.dir).st_mode)[-3:] == '700', 'reports/ is 0700')
pv = rs.preview(r['id'])
ok(pv['render'].startswith('<privacy render') and pv['install'] == '<install token>', 'preview shows what would leave')
sent = {}
r2 = rs.send(r['id'], post=lambda url, body: (sent.update(url=url, body=json.loads(body)) or {'ok': True, 'code': 'K7Q2', 'status_url': 'https://intake.example/s/K7Q2'}))
ok(sent['url'] == 'https://intake.example/api/report' and set(sent['body']) == {'v', 'class', 'text', 'route', 'trail', 'errors', 'meta', 'render', 'install'},
   'community send posts the allow-listed payload')
ok(sent['body']['render'] and r2['status'] == 'sent' and r2['code'] == 'K7Q2', 'render included, code and status kept')
ok(len(sent['body']['install']) == 32 and sent['body']['install'] == rs.install_token(), 'random install token')
cfg['reports']['mode'] = 'developer'
r3 = rs.save({**rep, 'render': PNG, 'full': PNG})
ok(r3['has_full'], 'developer mode keeps the real screen')
r4 = rs.send(r3['id'], post=lambda *a: ok(False, 'developer mode never posts'))
ok(r4['status'] == 'sent' and 'developer' in r4['sent_to'], 'developer mode: the full report stays in reports/')
import io, zipfile
z = zipfile.ZipFile(io.BytesIO(rs.zip(community=[{'id': 'abcdef12-0000', 'created': '2026-11-02', 'class': 'missing', 'text': 'Please add X', 'route': 'today',
                                                  'trail': [], 'errors': [], 'meta': {'os': 'macOS'}, '_png': b'png'}])))
names = z.namelist()
md = z.read([n for n in names if n.endswith('report.md') and r3['id'] in n][0]).decode()
ok('README.md' in names and any(n.endswith(r3['id'] + '-annoying/screen.png') for n in names) and any(n.startswith('community/abcdef12-missing/') for n in names),
   'zip: one folder per report with report.md and pictures, plus community reports: %d files' % len(names))
ok('## What happened' in md and 'open_route:today' in md and '## Errors' in md and 'mac_model' in md, 'report.md has the text, actions, errors and versions')
rs.discard(r3['id'])
ok(os.path.isdir(os.path.join(rs.dir, '_discarded', r3['id'])) and all(x['id'] != r3['id'] for x in rs.list()), 'discard moves, never deletes')
try:
    rs.get('../state'); ok(False, 'ids are checked')
except R.Bad:
    ok(True, 'ids are checked')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
