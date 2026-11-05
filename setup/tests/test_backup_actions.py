#!/usr/bin/env python3
"""Backup and move in the action service (axella-actions.py): Export backup checks the passphrase, builds one file
for its one download and never logs or keeps the passphrase; automatic backups keep it in the Keychain only; Back up
now reports a failure; old exports are cleared; owner only. The build itself is stubbed (test_backup.py covers it).
Invented data. Run: python3 setup/tests/test_backup_actions.py"""
import importlib.util
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
import backup as B  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


class KC(dict):
    def get(self, s, a):
        return dict.get(self, (s, a))

    def set(self, s, a, v):
        self[(s, a)] = v

    def delete(self, s, a):
        self.pop((s, a), None)


root = tempfile.mkdtemp()
base, state = os.path.join(root, 'axella'), os.path.join(root, 'axella', 'state')
os.makedirs(state)
A.BASE, A.STATE_DIR, A.EXPORT_DIR, A.LOG_FILE = base, state, os.path.join(state, 'export'), os.path.join(state, 'actions.log')
kc = KC()
A.BACKUP_AUTO = B.Auto(state, base, kc, version='1.0.0')
built = []


def fake_build(b, out, pw, history=False, version=''):
    built.append((b, out, pw, history))
    with open(out, 'wb') as f:
        f.write(b'age-encrypted-bytes')
    return {'size': 19, 'files': {'state/tasks.json': {}}, 'left_out': ['state/voice-token'], 'name': os.path.basename(out)}


A._backup.build = fake_build
PW = 'correct horse battery staple'
for bad, why in (({'passphrase': 'short', 'again': 'short'}, 'too short'), ({'passphrase': PW, 'again': PW + 'x'}, 'not the same')):
    try:
        A.backup_action('backup_export', dict(bad))
        ok(False, 'refused: %s' % why)
    except A.Bad:
        ok(not built, 'refused: a passphrase %s' % why)
p = {'passphrase': PW, 'again': PW, 'history': True}
r = A.backup_action('backup_export', p)
ok(A.EXPORT_ID.match(r['id']) and r['name'].startswith('axella-backup-') and r['name'].endswith('.axbak') and r['history'] and r['left_out'] == ['state/voice-token'],
   'Export backup: one file, ready for its download')
ok(built[0][0] == base and built[0][2] == PW and built[0][3] is True and os.path.isfile(os.path.join(A.EXPORT_DIR, r['id'] + '.axbak')), '… built from the Axella folder with your passphrase and history choice')
ok('passphrase' not in p and 'again' not in p, 'the passphrase is taken out of the request at once')
A.log('owner@example.com', 'backup_export', p, 'ok')
logged = open(A.LOG_FILE, encoding='utf-8').read()
ok(PW not in logged and 'Backup exported with history' in logged, '… so it never reaches the activity log')
ok(not any(PW in open(os.path.join(dp, f), encoding='utf-8', errors='ignore').read() for dp, _d, fs in os.walk(state) for f in fs if not f.endswith('.axbak')),
   '… and is stored nowhere in state/')

dest = tempfile.mkdtemp()
q = {'on': True, 'folder': dest, 'passphrase': PW, 'again': PW}
st = A.backup_action('backup_auto', q)
ok(st['on'] and st['folder'] == dest and kc.get(*B.KEYCHAIN) == PW and 'passphrase' not in q, 'automatic backups: on, the passphrase in the Keychain only')
ok(PW not in open(os.path.join(state, 'backup.json')).read(), '… not in state/backup.json')
ok(A.backup_action('backup_run', {})['last_ok'] and len(built) == 2 and built[1][1].startswith(dest), 'Back up now: one backup in your folder')
d = A.BACKUP_AUTO.load()
d['folder'] = os.path.join(root, 'unplugged')
A.BACKUP_AUTO._save(d)
try:
    A.backup_action('backup_run', {})
    ok(False, 'Back up now reports a failure')
except A.Bad as e:
    ok('doesn\'t exist' in str(e) and A.BACKUP_AUTO.health()[0] in ('warn', 'down'), 'Back up now reports a failure, and System status shows it')
A.backup_action('backup_auto', {'on': False})
ok(kc.get(*B.KEYCHAIN) is None, 'off: the passphrase leaves the Keychain')

old = os.path.join(A.EXPORT_DIR, 'f' * 24 + '.axbak')
open(old, 'w').write('x')
os.utime(old, (time.time() - 7200, time.time() - 7200))
A._prune_exports()
ok(not os.path.exists(old) and os.path.exists(os.path.join(A.EXPORT_DIR, r['id'] + '.axbak')), 'an export not downloaded within an hour is cleared')
ok({'backup_export', 'backup_auto', 'backup_run'} <= A.OWNER_ONLY, 'owner only')
v = A.backup_view()
ok(set(v) >= {'age', 'auto', 'reconnect', 'left_out'} and 'state/voice-token' in v['left_out'], 'GET backup: the tool, the settings, what is left out and what to reconnect')
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
