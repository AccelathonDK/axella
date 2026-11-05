#!/usr/bin/env python3
"""Backup and move (setup/backup.py): what goes in and what never does (keys and tokens), the manifest, the round
trip with history to a different Axella folder and home, path rewriting, the version check, every way a bad file
fails (wrong passphrase, one changed byte, a doctored manifest, an unsafe name) without changing anything, the dry
run, moving an existing installation aside, and the weekly automatic copy (keep 4, failures, the 2-week push).
The encryption checks need the age tool (1.3+, with age-plugin-batchpass): brew install age. Invented data only.
Run: python3 setup/tests/test_backup.py"""
import datetime
import hashlib
import json
import os
import sqlite3
import sys
import tarfile
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import backup as B  # noqa: E402

if os.environ.get('AXELLA_TEST_AGE_DIR'):                  # a dev machine without Homebrew: the test points at its age
    B.AGE_DIRS = (os.environ['AXELLA_TEST_AGE_DIR'],) + B.AGE_DIRS

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def put(base, rel, text):
    p = os.path.join(base, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(text)


def tree_hash(root):
    h = hashlib.sha256()
    for r, d, fs in sorted(os.walk(root)):
        d.sort()
        for f in sorted(fs):
            p = os.path.join(r, f)
            h.update(os.path.relpath(p, root).encode() + b'\0' + open(p, 'rb').read())
    return h.hexdigest()


ROOT = tempfile.mkdtemp()
BASE = os.path.join(ROOT, 'Users', 'alex', 'axella')
OLDHOME = os.path.join(ROOT, 'Users', 'alex')
os.environ['HOME'] = OLDHOME
put(BASE, 'state/tasks.json', json.dumps([{'id': 't1', 'text': 'Send Kim the plan'}]))
put(BASE, 'state/projects.json', json.dumps({'projects': [{'id': 'p1', 'name': 'Acme launch'}]}))
put(BASE, 'state/trips.json', json.dumps({'trips': [{'id': 'tr1', 'title': 'Spring trip'}]}))
put(BASE, 'state/meetings/m1.json', json.dumps({'id': 'm1', 'title': 'Acme review'}))
put(BASE, 'state/documents.json', json.dumps({'folder': BASE + '/state/files', 'other': BASE + '2/elsewhere'}))
db = sqlite3.connect(os.path.join(BASE, 'state', 'axella.db'))
db.execute('create table items (id text)')
db.execute("insert into items values ('i1')")
db.commit()
db.close()
TOKENS = {'state/voice-token': 'tok-voice-ZQ81', 'state/voice-lookup-key': 'tok-lookup-ZQ82', 'state/report-install-token': 'tok-rep-ZQ83',
          'state/report-triage-token': 'tok-tri-ZQ84', 'state/vapid.json': '{"private": "tok-vapid-ZQ85"}',
          'state/push-subscriptions.json': '[{"endpoint": "https://push.example/tok-sub-ZQ86"}]', 'state/mcp.json': '{"k": "tok-mcp-ZQ87"}',
          'state/signal-store.json': '{"k": "tok-sig-ZQ88"}'}
for k, v in TOKENS.items():
    put(BASE, k, v)
put(BASE, 'state/runs/20270310-0730-digest-morning.log', 'a run log')
put(BASE, 'state/x.json.lock', '')
put(BASE, 'state/tasks.json.123.456.tmp', 'half')
put(BASE, 'state/actions.log', '{"action": "done"}\n')
put(BASE, 'state/audio/rec1.m4a', 'not really audio')
put(BASE, 'knowledge/prices.md', '# Prices\nAcme: 100 DKK\n')
put(BASE, 'AXELLA.md', '# Owner\nAlex Example\n')
put(BASE, 'contacts.md', '# VIP\n- Sam Rivera <sam@example.org>\n')
put(BASE, 'setup/actions-config.json', json.dumps({'owner': 'alex@example.com', 'document_folders': [OLDHOME + '/Documents/Axella']}))
put(BASE, 'setup/axella-actions.py', '# code is not in a backup')
put(BASE, 'digests/2027-03-10-0730.json', json.dumps({'items': [{'id': 'd1', 'section': 'p2'}]}))
put(BASE, 'calls/c1.json', json.dumps({'id': 'c1'}))

# ---- what goes in
files, left = B.plan(BASE, history=False)
rels = {r for r, _ in files}
ok({'state/tasks.json', 'state/axella.db', 'state/meetings/m1.json', 'knowledge/prices.md', 'AXELLA.md', 'contacts.md', 'setup/actions-config.json'} <= rels,
   'core: state/, the store, meetings, knowledge/, AXELLA.md, contacts.md, the account config')
ok(not rels & set(TOKENS) and sorted(left) == sorted(TOKENS), 'never the keys and tokens – they are listed as left out')
ok(not any(r.startswith(('state/runs/', 'digests/', 'calls/', 'setup/axella-')) or r.endswith(('.lock', '.tmp')) for r in rels)
   and 'state/actions.log' not in rels and 'state/audio/rec1.m4a' not in rels, 'no logs, locks, half-written files or code; history only when asked')
hfiles, _ = B.plan(BASE, history=True)
hr = {r for r, _ in hfiles}
ok({'digests/2027-03-10-0730.json', 'calls/c1.json', 'state/actions.log', 'state/audio/rec1.m4a'} <= hr, 'with history: digests/, calls/, the activity log and recordings')

# ---- path rewriting (no age needed)
rw = tempfile.mkdtemp()
put(rw, 'a.json', json.dumps({'p': '/Users/alex/axella/state', 'q': '/Users/alex/axella2/x', 'h': '/Users/alex/Documents', 'r': '/Users/alexandra/x'}))
put(rw, 'b.bin', '/Users/alex/axella')
B.rewrite_paths(rw, ['a.json', 'b.bin'], '/Users/alex/axella', '/Users/kim/ax', '/Users/alex', '/Users/kim')
a = json.load(open(os.path.join(rw, 'a.json')))
ok(a == {'p': '/Users/kim/ax/state', 'q': '/Users/kim/axella2/x', 'h': '/Users/kim/Documents', 'r': '/Users/alexandra/x'},
   'paths: the Axella folder and the home folder are rewritten as whole path prefixes only (%s)' % a)
ok(open(os.path.join(rw, 'b.bin')).read() == '/Users/alex/axella', '… text files only')
try:
    B.check_passphrase('short')
    ok(False, 'a passphrase of at least 10 characters')
except B.Bad:
    ok(True, 'a passphrase of at least 10 characters')
try:
    B.check_passphrase('correct horse battery', 'correct horse batter')
    ok(False, 'the two passphrases must match')
except B.Bad:
    ok(True, 'the two passphrases must match')

if not B.age_bin():
    print('  SKIP the encryption checks: the age tool (1.3+ with age-plugin-batchpass) is not installed here – brew install age')
    print('%d failed' % fails if fails else 'all ok (encryption checks skipped)')
    sys.exit(1 if fails else 0)

PW = 'correct horse battery staple'
out = os.path.join(ROOT, 'axella-backup-2027-03-15.axbak')
man = B.build(BASE, out, PW, history=True, version='1.0.0')
ok(os.path.exists(out) and oct(os.stat(out).st_mode & 0o777) == '0o600' and man['history'] and man['format'] == B.FORMAT, 'export: one encrypted file, only for the owner')
ok(set(man['files']) == hr and all(len(v['sha256']) == 64 for v in man['files'].values()) and man['left_out'] == sorted(TOKENS)
   and 'calls' in man['reconnect'] and man['axella_version'] == '1.0.0', 'the manifest: version, date, parts, a checksum per file, what to reconnect')
blob = open(out, 'rb').read()
ok(b'Send Kim' not in blob and b'Acme' not in blob, 'the file is encrypted (no readable data in it)')

w = tempfile.mkdtemp()
m2 = B.read(out, PW, w)
dec = b''
for r, _d, fs in os.walk(os.path.join(w, 'x')):
    for f in fs:
        dec += open(os.path.join(r, f), 'rb').read()
names = [n for n in tarfile.open(os.path.join(w, 'b.tar.gz')).getnames()]
ok(not any(n[5:] in TOKENS for n in names) and not any(v.split('"')[-2].encode() in dec if '"' in v else v.encode() in dec for v in TOKENS.values()),
   'no key or token anywhere in the decrypted archive (names and contents)')
ok(m2['files'] == man['files'], 'read back: every file matches its checksum')

# ---- failures change nothing
target = os.path.join(ROOT, 'Users', 'kim', 'axella')
os.makedirs(target)
put(target, 'state/tasks.json', '[]')
before = tree_hash(target)
for label, path, pw, want in (('wrong passphrase', out, 'wrong passphrase here', 'wrong passphrase'),):
    try:
        B.restore(path, pw, target, apply=True)
        ok(False, label)
    except B.Bad as e:
        ok(want in str(e) and tree_hash(target) == before, '%s fails clearly and changes nothing (%s)' % (label, e))
bad = os.path.join(ROOT, 'bad.axbak')
raw = bytearray(blob)
raw[len(raw) // 2] ^= 1
open(bad, 'wb').write(raw)
try:
    B.restore(bad, PW, target, apply=True)
    ok(False, 'one changed byte')
except B.Bad as e:
    ok('damaged or was changed' in str(e) and tree_hash(target) == before, 'one changed byte fails clearly and changes nothing (%s)' % e)


def craft(name, members):
    t = tempfile.mkdtemp()
    tp = os.path.join(t, 'c.tar.gz')
    with tarfile.open(tp, 'w:gz') as tar:
        for n, data in members:
            import io
            ti = tarfile.TarInfo(n)
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
    dst = os.path.join(ROOT, name)
    B.encrypt(tp, dst, PW)
    return dst


newer = craft('newer.axbak', [('manifest.json', json.dumps({'format': 99, 'files': {}}).encode())])
older_extra = craft('extra.axbak', [('manifest.json', json.dumps({'format': 1, 'files': {}, 'parts': ['state']}).encode()), ('data/state/sneaky.json', b'{}')])
unsafe = craft('unsafe.axbak', [('manifest.json', json.dumps({'format': 1, 'files': {}}).encode()), ('data/../../escape.txt', b'x')])
withtoken = craft('token.axbak', [('manifest.json', json.dumps({'format': 1, 'parts': ['state'], 'files': {'state/voice-token': {'size': 1, 'sha256': hashlib.sha256(b'x').hexdigest()}}}).encode()), ('data/state/voice-token', b'x')])
S = lambda b: hashlib.sha256(b).hexdigest()
code, hooks = b'import os  # not from a backup', b'{"hooks": {"x": "not from a backup"}}'
outside = craft('outside.axbak', [('manifest.json', json.dumps({'format': 1, 'parts': ['state', 'setup/actions-config.json'], 'files': {
    'setup/axella-actions.py': {'size': len(code), 'sha256': S(code)}, '.claude/settings.json': {'size': len(hooks), 'sha256': S(hooks)}}}).encode()),
    ('data/setup/axella-actions.py', code), ('data/.claude/settings.json', hooks)])
badpart = craft('badpart.axbak', [('manifest.json', json.dumps({'format': 1, 'parts': ['setup'], 'files': {'setup/axella-actions.py': {'size': len(code), 'sha256': S(code)}}}).encode()),
                                  ('data/setup/axella-actions.py', code)])
for label, apply_ in (('dry run', False), ('apply', True)):
    for path, want in ((outside, 'outside its parts'), (badpart, 'part Axella never backs up')):
        try:
            B.restore(path, PW, target, apply=apply_)
            ok(False, 'refused (%s): %s' % (label, want))
        except B.Bad as e:
            ok(want in str(e) and tree_hash(target) == before and not os.path.exists(os.path.join(target, 'setup', 'axella-actions.py'))
               and not os.path.exists(os.path.join(target, '.claude')) and not any(n.startswith('pre-restore-') for n in os.listdir(target)),
               'valid checksums but %s – refused by the %s, the folder unchanged (%s)' % ('code and .claude/ outside the parts' if path == outside else 'a part that isn\'t core or history', label, e))
ok(not B.inside('setup/axella-actions.py', ['state', 'setup/actions-config.json']) and B.inside('state/x/y.json', ['state']) and not B.inside('statex/y', ['state']),
   'inside(): only a part itself or under it')
for label, path, want in (('a newer Axella\'s backup is refused', newer, 'newer Axella'), ('a file the manifest doesn\'t list', older_extra, 'don\'t match its manifest'),
                          ('an unsafe name', unsafe, 'unexpected'), ('a key or token inside', withtoken, 'key or token')):
    try:
        B.restore(path, PW, target, apply=True)
        ok(False, label)
    except B.Bad as e:
        ok(want in str(e) and tree_hash(target) == before and not os.path.exists(os.path.join(ROOT, 'escape.txt')), '%s – nothing changed (%s)' % (label, e))

# ---- dry run, then the round trip to another folder and home
dry = B.restore(out, PW, target)
ok(not dry['applied'] and tree_hash(target) == before and {s['part']: s['exists'] for s in dry['steps']}.get('state') is True
   and dry['contents']['state']['files'] > 3 and dry['reconnect'], 'dry run: what is in it and what would be replaced – nothing changes')
os.environ['HOME'] = os.path.join(ROOT, 'Users', 'kim')
res = B.restore(out, PW, target, apply=True)
ok(res['applied'] and os.path.isdir(res['aside']) and json.load(open(os.path.join(res['aside'], 'state', 'tasks.json'))) == [],
   'apply: the existing installation is moved aside, not deleted')
ok(json.load(open(os.path.join(target, 'state', 'tasks.json')))[0]['text'] == 'Send Kim the plan' and
   json.load(open(os.path.join(target, 'state', 'projects.json')))['projects'][0]['name'] == 'Acme launch' and
   os.path.exists(os.path.join(target, 'knowledge', 'prices.md')) and os.path.exists(os.path.join(target, 'state', 'meetings', 'm1.json')) and
   json.load(open(os.path.join(target, 'state', 'trips.json')))['trips'][0]['title'] == 'Spring trip', 'the same tasks, projects, knowledge, trips and meetings')
ok(sqlite3.connect(os.path.join(target, 'state', 'axella.db')).execute('select id from items').fetchall() == [('i1',)], 'the store comes back')
docs = json.load(open(os.path.join(target, 'state', 'documents.json')))
cfg = json.load(open(os.path.join(target, 'setup', 'actions-config.json')))
ok(docs['folder'] == target + '/state/files' and docs['other'] == os.environ['HOME'] + '/axella2/elsewhere' and cfg['document_folders'] == [os.environ['HOME'] + '/Documents/Axella'],
   'a new home folder and user name: paths in the config are rewritten')
ok(os.path.exists(os.path.join(target, 'digests', '2027-03-10-0730.json')) and not any(os.path.exists(os.path.join(target, t)) for t in TOKENS)
   and 'The call agent' in ' '.join(res['reconnect']), 'history restored; no tokens – they are on the reconnect list')
# same Mac: its own keys stay
put(target, 'state/voice-token', 'this-macs-token')
res2 = B.restore(out, PW, target, apply=True)
ok(open(os.path.join(target, 'state', 'voice-token')).read() == 'this-macs-token' and 'state/voice-token' in res2['kept_tokens'],
   'restoring over a working installation keeps that Mac\'s own keys and tokens')
fixed = datetime.datetime(2027, 3, 15, 9, 0, 0)
taken = os.path.join(target, 'pre-restore-20270315-090000')
os.makedirs(taken, exist_ok=True)
open(os.path.join(taken, 'keep.txt'), 'w').write('from an earlier restore')
r3 = B.restore(out, PW, target, apply=True, now=fixed)
r4 = B.restore(out, PW, target, apply=True, now=fixed)
ok(r3['aside'] == taken + '-2' and r4['aside'] == taken + '-3' and open(os.path.join(taken, 'keep.txt')).read() == 'from an earlier restore'
   and os.listdir(taken) == ['keep.txt'], 'the same second twice: pre-restore-<time>-2, -3 – an earlier moved-aside folder is never reused')
os.environ['HOME'] = OLDHOME

# ---- automatic weekly backups


class KC(dict):
    def get(self, s, a):
        return dict.get(self, (s, a))

    def set(self, s, a, v):
        self[(s, a)] = v

    def delete(self, s, a):
        self.pop((s, a), None)


st = tempfile.mkdtemp()
kc, pushed = KC(), []
AU = B.Auto(st, BASE, kc, version='1.0.0', push=pushed.append)
ok(AU.health()[0] == 'off' and not AU.due(), 'automatic backups are off until you pick a folder')
dest = tempfile.mkdtemp()
for bad_folder in ('', os.path.join(BASE, 'state'), os.path.join(ROOT, 'nope')):
    try:
        AU.settings({'on': True, 'folder': bad_folder, 'passphrase': PW, 'again': PW})
        ok(False, 'refused folder: %r' % bad_folder)
    except B.Bad:
        ok(True, 'refused folder: %s' % (bad_folder.replace(ROOT, '…') or '(none)'))
s = AU.settings({'on': True, 'folder': dest, 'passphrase': PW, 'again': PW})
ok(s['on'] and kc.get(*B.KEYCHAIN) == PW and s['history'] is True and 'passphrase' not in json.dumps(AU.load()).lower().replace('"warned"', ''),
   'on: the passphrase goes to the Keychain only, history on by default for automatic backups')
r = AU.run()
ok(r['last_error'] is None and B.NAME.match(r['last_name']) and AU.health()[0] == 'ok' and not AU.due(), 'the weekly backup ran, System status says ok')
for i in range(5):
    AU.run(force=True)
    time.sleep(0.02)
kept = sorted(n for n in os.listdir(dest) if B.NAME.match(n))
ok(len(kept) == 4, 'keep the last 4 (%d)' % len(kept))
open(os.path.join(dest, 'my-notes.txt'), 'w').write('mine')
AU.run(force=True)
ok(os.path.exists(os.path.join(dest, 'my-notes.txt')), 'only Axella\'s own backup files are ever removed')
gone = tempfile.mkdtemp()
d = AU.load()
d.update(folder=os.path.join(gone, 'unplugged'))
AU._save(d)
r = AU.run(force=True)
ok(r['last_error'] and 'doesn\'t exist' in r['last_error'] and AU.health()[0] == 'warn', 'a failed backup shows on System status (%s)' % AU.health()[1])
ok(not pushed, '… no push for one failure')
d = AU.load()
d.update(last_ok=(datetime.datetime.now().astimezone() - datetime.timedelta(days=15)).isoformat(timespec='seconds'), warned=None)
AU._save(d)
ok(AU.warn() and len(pushed) == 1 and not AU.warn() and AU.health()[0] == 'down', 'two weeks without a good backup: one push')
AU.settings({'on': False})
ok(not AU.load()['on'] and kc.get(*B.KEYCHAIN) is None, 'off: the passphrase is removed from the Keychain')
ok(B.is_icloud('/Users/alex/Library/Mobile Documents/com~apple~CloudDocs/Axella') and not B.is_icloud(dest), 'an iCloud Drive folder is recognised (Settings says so plainly)')
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
