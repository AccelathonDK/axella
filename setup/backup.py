"""Backup and move: one encrypted file with everything Axella has learned, a weekly automatic copy to a folder the
owner picks, and a restore on a new (or the same) Mac mini. Python 3.9, stdlib plus the `age` tool (Homebrew):
`age -e -j batchpass` – age's own passphrase encryption (scrypt key derivation, authenticated: a wrong passphrase or
one changed byte fails), with the passphrase handed over on a file descriptor, never on the command line or in the
environment. Nothing is sent anywhere: the file goes where the owner says.

The file (axella-backup-<date>.axbak) is age(tar.gz) with:
  manifest.json   {"format", "axella_version", "created", "base", "home", "history", "parts", "files": {path: {size,
                   sha256}}, "left_out", "reconnect"}
  data/<path>     the files, relative to the Axella folder
Core parts: state/ (settings, tasks, projects, trips, meetings, promises, privacy, VIPs, subscriptions, the SQLite
store – copied consistently), knowledge/, notes/, AXELLA.md, contacts.md, setup/actions-config.json.
History (a choice): digests/, calls/, the activity log (state/actions.log) and recordings (state/audio/).
Never: the keys and tokens (TOKENS) and machine-only files (logs, sockets, temporary files, our own exports).

  plan(base, history)                      → [(relpath, abspath)] what goes in, and what is left out
  build(base, out, passphrase, history)    → manifest (writes out atomically, mode 600)
  read(path, passphrase, work)             → manifest – decrypted and checked in `work`; raises Bad on any doubt
  restore(path, passphrase, base, apply)   → what would change (dry run) or what changed
  Auto(state_dir, …)                       → the weekly copy to the owner's folder, keep 4, status for System status
"""
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import threading
import time

FORMAT = 1
SUFFIX = '.axbak'
MIN_PASS = 10
KEEP = 4
NAME = re.compile(r'^axella-backup-\d{4}-\d{2}-\d{2}(?:-\d+)?\.axbak$')
CORE = ('state', 'knowledge', 'notes', 'AXELLA.md', 'contacts.md', 'setup/actions-config.json')
HISTORY = ('digests', 'calls', 'state/actions.log', 'state/audio')
# keys and tokens – never in a backup; set up again after a restore (the RECONNECT list)
TOKENS = ('state/voice-token', 'state/voice-lookup-key', 'state/report-install-token', 'state/report-triage-token',
          'state/vapid.json', 'state/push-subscriptions.json', 'state/mcp.json', 'state/signal-store.json')
# machine-only: logs, sockets, caches, half-written files, outgoing uploads, our own exports
SKIP_DIRS = ('state/ask-notes', 'state/runs', 'state/outbox', 'state/export', 'state/sock', 'state/kb', 'digests/archive/.tmp')
SKIP_FILES = ('state/macuse-calendar-tools.json', 'state/backup.json')
SKIP_RE = re.compile(r'(\.lock|\.tmp|\.db-wal|\.db-shm|\.DS_Store|\.pyc)$|/\.[^/]*\.tmp$|\.\d+\.\d+\.tmp$')
RECONNECT = [
    ('mail', 'Mail accounts – add them in Mail on this Mac'),
    ('messages', 'Messages and Full Disk Access for the Axella service'),
    ('whatsapp', 'WhatsApp export (Settings → Channels)'),
    ('signal', 'Signal – link this Mac again'),
    ('calls', 'The call agent – a new token in Vercel (docs/SETUP.md)'),
    ('push', 'Push notifications – turn them on again on each device'),
    ('meetings', 'Meeting services (Teams, Meet, Zoom) – connect again; their tokens stay in the old Mac\'s Keychain'),
    ('macuse', 'Macuse (state/mcp.json) – set up as in docs/SETUP.md'),
    ('claude', 'The Claude login – run `claude` once in Terminal'),
    ('reports', 'Report a problem – its tokens are made again on first use'),
    ('backup', 'Automatic backups – pick the folder and passphrase again'),
]


class Bad(Exception):
    pass


# ---------------- age ----------------
AGE_DIRS = ('/opt/homebrew/bin', '/usr/local/bin')     # Homebrew only: fixed paths, never an environment variable or PATH


def age_bin():
    for d in AGE_DIRS:
        if os.path.isfile(os.path.join(d, 'age')) and os.path.isfile(os.path.join(d, 'age-plugin-batchpass')):
            return os.path.join(d, 'age')
    return None


def _age(args, passphrase, timeout=1800):
    """Run age with the passphrase on fd 3 (AGE_PASSPHRASE_FD) – never on argv or in the environment."""
    a = age_bin()
    if not a:
        raise Bad('the age tool is missing – install it on the Mac mini: brew install age (version 1.3 or later)')
    r, w = os.pipe()
    try:
        os.write(w, passphrase.encode('utf-8'))
    finally:
        os.close(w)
    env = {k: v for k, v in os.environ.items() if not k.startswith('AGE_')}
    env['PATH'] = os.path.dirname(a) + os.pathsep + '/usr/bin:/bin'   # age finds its batchpass plugin next to it
    env['AGE_PASSPHRASE_FD'] = str(r)                  # the read end, inherited by age only (pass_fds)
    try:
        p = subprocess.run([a] + args, env=env, capture_output=True, timeout=timeout, pass_fds=(r,))
    finally:
        os.close(r)
    return p


def encrypt(src, dst, passphrase):
    p = _age(['-e', '-j', 'batchpass', '-o', dst, src], passphrase)
    if p.returncode != 0:
        raise Bad('encryption failed: ' + p.stderr.decode('utf-8', 'replace').strip().splitlines()[0][:200] if p.stderr else 'encryption failed')


def decrypt(src, dst, passphrase):
    p = _age(['-d', '-j', 'batchpass', '-o', dst, src], passphrase)
    if p.returncode != 0:
        msg = p.stderr.decode('utf-8', 'replace').lower()
        try:
            os.remove(dst)
        except OSError:
            pass
        if 'incorrect passphrase' in msg:
            raise Bad('wrong passphrase – nothing was changed')
        raise Bad('the backup file is damaged or was changed – nothing was changed')


def check_passphrase(p, again=None):
    p = str(p or '')
    if len(p) < MIN_PASS:
        raise Bad('a passphrase of at least %d characters' % MIN_PASS)
    if again is not None and p != again:
        raise Bad('the two passphrases are not the same')
    return p


# ---------------- what goes in ----------------
def _skipped(rel):
    if rel in TOKENS or rel in SKIP_FILES or SKIP_RE.search(rel):
        return True
    return any(rel == d or rel.startswith(d + '/') for d in SKIP_DIRS)


def plan(base, history=False):
    """[(relpath, abspath)] in the backup, and [relpath] of the keys and tokens left out."""
    parts = list(CORE) + (list(HISTORY) if history else [])
    hist = set(HISTORY)
    out, left = [], []
    for part in parts:
        top = os.path.join(base, part)
        if os.path.isfile(top) and not os.path.islink(top):
            out.append((part, top))
            continue
        for root, dirs, files in os.walk(top):
            dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(root, d)))
            for f in sorted(files):
                ab = os.path.join(root, f)
                rel = os.path.relpath(ab, base).replace(os.sep, '/')
                if os.path.islink(ab) or not os.path.isfile(ab):
                    continue
                if not history and any(rel == h or rel.startswith(h + '/') for h in hist):
                    continue                                    # history lives inside state/ too
                if rel in TOKENS:
                    left.append(rel)
                    continue
                if _skipped(rel):
                    continue
                out.append((rel, ab))
    return sorted(set(out)), sorted(set(left))


def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def _snapshot_db(src, dst):
    """A consistent copy of a SQLite store while the service may be writing it."""
    s = sqlite3.connect('file:%s?mode=ro' % src, uri=True)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def build(base, out, passphrase, history=False, version='', now=None):
    passphrase = check_passphrase(passphrase)
    now = now or datetime.datetime.now().astimezone()
    files, left = plan(base, history)
    work = tempfile.mkdtemp(prefix='axbak-')
    try:
        tar_path = os.path.join(work, 'b.tar.gz')
        man = {'format': FORMAT, 'axella_version': version, 'created': now.isoformat(timespec='seconds'),
               'base': os.path.abspath(base), 'home': os.path.expanduser('~'), 'history': bool(history),
               'parts': [p for p in list(CORE) + (list(HISTORY) if history else []) if os.path.exists(os.path.join(base, p))],
               'files': {}, 'left_out': left, 'reconnect': [k for k, _ in RECONNECT]}
        with tarfile.open(tar_path, 'w:gz') as tar:
            for rel, ab in files:
                src = ab
                if rel.endswith('.db'):
                    src = os.path.join(work, 'snap.db')
                    try:
                        _snapshot_db(ab, src)
                    except sqlite3.Error:
                        src = ab
                try:
                    size, sha = os.path.getsize(src), _sha(src)
                    ti = tarfile.TarInfo('data/' + rel)
                    ti.size, ti.mtime, ti.mode = size, int(os.path.getmtime(ab)), 0o600
                    with open(src, 'rb') as fh:
                        tar.addfile(ti, fh)
                except OSError:
                    continue                                    # gone meanwhile (a temporary file)
                man['files'][rel] = {'size': size, 'sha256': sha}
            raw = json.dumps(man, indent=1, ensure_ascii=False).encode('utf-8')
            ti = tarfile.TarInfo('manifest.json')
            ti.size, ti.mtime, ti.mode = len(raw), int(time.time()), 0o600
            tar.addfile(ti, io.BytesIO(raw))
        tmp = out + '.%d.tmp' % os.getpid()
        encrypt(tar_path, tmp, passphrase)
        os.chmod(tmp, 0o600)
        os.replace(tmp, out)
        return dict(man, size=os.path.getsize(out), name=os.path.basename(out))
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------- reading and checking ----------------
MIGRATIONS = {}        # {from_format: fn(extract_dir, manifest) -> manifest} – none yet (format 1 is the first)


def inside(rel, parts):
    """rel lies in one of these parts (a file part itself, or under a folder part)."""
    return any(rel == p or rel.startswith(p + '/') for p in parts)


def allowed_parts(man):
    """The backup's own parts, limited to the core and history lists – anything else is refused."""
    parts = man.get('parts') if isinstance(man.get('parts'), list) else []
    bad = [p for p in parts if p not in CORE and p not in HISTORY]
    if bad:
        raise Bad('the backup names a part Axella never backs up (%s) – nothing was changed' % str(bad[0])[:80])
    return [p for p in parts if p in CORE or p in HISTORY]


def _safe_member(m):
    n = m.name
    if not (m.isfile() and (n == 'manifest.json' or n.startswith('data/'))):
        return False
    return not (n.startswith('/') or '\\' in n or any(x in ('..', '') for x in n.split('/')))


def read(path, passphrase, work):
    """Decrypt into `work`, unpack into work/x and check everything against the manifest. Raises Bad."""
    tar_path = os.path.join(work, 'b.tar.gz')
    decrypt(path, tar_path, str(passphrase or ''))
    x = os.path.join(work, 'x')
    os.makedirs(x, exist_ok=True)
    try:
        with tarfile.open(tar_path, 'r:gz') as tar:
            for m in tar.getmembers():
                if not _safe_member(m):
                    raise Bad('the backup holds something unexpected (%s) – nothing was changed' % m.name[:80])
                dst = os.path.join(x, m.name)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with tar.extractfile(m) as src, open(dst, 'wb') as out:
                    shutil.copyfileobj(src, out)
    except (tarfile.TarError, OSError, EOFError) as e:
        raise Bad('the backup could not be unpacked (%s) – nothing was changed' % str(e)[:80])
    try:
        with open(os.path.join(x, 'manifest.json'), encoding='utf-8') as f:
            man = json.load(f)
    except (OSError, ValueError):
        raise Bad('the backup has no manifest – nothing was changed')
    fmt = man.get('format')
    if not isinstance(fmt, int) or fmt < 1:
        raise Bad('not an Axella backup – nothing was changed')
    if fmt > FORMAT:
        raise Bad('this backup was made by a newer Axella (format %d, this one reads %d) – update Axella first' % (fmt, FORMAT))
    while man['format'] < FORMAT:
        man = MIGRATIONS[man['format']](x, man)
    data = os.path.join(x, 'data')
    seen = set()
    for root, _d, files in os.walk(data):
        for f in files:
            seen.add(os.path.relpath(os.path.join(root, f), data).replace(os.sep, '/'))
    want = man.get('files') or {}
    parts = allowed_parts(man)
    for rel in want:
        if not inside(rel, parts):
            raise Bad('the backup holds a file outside its parts (%s) – refused, nothing was changed' % str(rel)[:80])
    if seen != set(want):
        raise Bad('the backup\'s files don\'t match its manifest – nothing was changed')
    for rel, meta in want.items():
        p = os.path.join(data, rel)
        if os.path.getsize(p) != meta.get('size') or _sha(p) != meta.get('sha256'):
            raise Bad('a file in the backup doesn\'t match its checksum (%s) – nothing was changed' % rel[:80])
        if any(rel == t for t in TOKENS):
            raise Bad('the backup holds a key or token (%s) – refused' % rel)
    return man


def describe(man):
    """What's in it, per part: files and bytes."""
    per = {}
    for rel, meta in (man.get('files') or {}).items():
        part = next((p for p in sorted(list(CORE) + list(HISTORY), key=len, reverse=True) if rel == p or rel.startswith(p + '/')), rel.split('/')[0])
        a = per.setdefault(part, {'files': 0, 'bytes': 0})
        a['files'] += 1
        a['bytes'] += int(meta.get('size') or 0)
    return per


# ---------------- restore ----------------
TEXT_RE = re.compile(r'\.(json|md|txt|toml|yaml|yml|plist)$')


def rewrite_paths(root, rels, old_base, new_base, old_home, new_home):
    """The Axella folder or the home folder moved (a new Mac, another user name): rewrite them in text files. The
    longer path first, and only whole path prefixes. Returns the files changed."""
    pairs = [(o, n) for o, n in ((old_base, new_base), (old_home, new_home)) if o and n and o != n]
    pairs.sort(key=lambda p: -len(p[0]))
    if not pairs:
        return []
    changed = []
    for rel in rels:
        if not TEXT_RE.search(rel):
            continue
        p = os.path.join(root, rel)
        try:
            with open(p, encoding='utf-8') as f:
                s = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        t = s
        for o, n in pairs:
            t = re.sub(re.escape(o) + r'(?=$|[/"\'\s,\]})])', n.replace('\\', '\\\\'), t)
        if t != s:
            with open(p, 'w', encoding='utf-8') as f:
                f.write(t)
            changed.append(rel)
    return changed


def unique_aside(base, now):
    """A new pre-restore-<time> folder – pre-restore-<time>-2, -3 … when that name is taken (two restores in the same
    second). Created with exist_ok=False, so an existing folder is never reused."""
    stem = os.path.join(base, 'pre-restore-' + now.strftime('%Y%m%d-%H%M%S'))
    n = 1
    while True:
        p = stem if n == 1 else '%s-%d' % (stem, n)
        try:
            os.makedirs(p, exist_ok=False)
            return p
        except FileExistsError:
            n += 1
            if n > 1000:
                raise Bad('could not make a folder to move the current data aside – nothing was changed')


def restore(path, passphrase, base, apply=False, now=None):
    """Dry run (apply=False): what's in the backup and what would be replaced – nothing changes. apply=True: the
    current parts are moved aside to <base>/pre-restore-<time>/ (never deleted), the backup's put in place, paths
    rewritten for this Mac, and this Mac's own keys and tokens kept. Everything is checked before anything moves."""
    now = now or datetime.datetime.now()
    base = os.path.abspath(base)
    work = tempfile.mkdtemp(prefix='axrestore-')
    try:
        man = read(path, passphrase, work)
        data = os.path.join(work, 'x', 'data')
        parts = allowed_parts(man)
        stray = [r for r in man.get('files') or {} if not inside(r, parts)]   # read() refused these already – again here,
        if stray:                                                             # before anything is shown or moved
            raise Bad('the backup holds a file outside its parts (%s) – refused, nothing was changed' % stray[0][:80])
        tops = sorted({p.split('/')[0] if p.startswith(('state/',)) else p for p in parts})
        steps = [{'part': p, 'exists': os.path.exists(os.path.join(base, p))} for p in tops]
        out = {'manifest': {k: man.get(k) for k in ('format', 'axella_version', 'created', 'history', 'left_out', 'reconnect')},
               'contents': describe(man), 'steps': steps, 'applied': False,
               'reconnect': [t for k, t in RECONNECT if k in (man.get('reconnect') or [])]}
        if not apply:
            return out
        aside = unique_aside(base, now)
        moved = []
        for s in steps:
            if s['exists']:
                dst = os.path.join(aside, s['part'])
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.rename(os.path.join(base, s['part']), dst)
                moved.append(s['part'])
        rels = sorted(man['files'])
        rewritten = rewrite_paths(data, rels, man.get('base'), base, man.get('home'), os.path.expanduser('~'))
        for rel in rels:
            if not inside(rel, parts):
                raise Bad('refused %s – outside the backup\'s parts' % rel[:80])
            dst = os.path.join(base, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(data, rel), dst)
            os.chmod(dst, 0o600)
        kept = []
        for t in TOKENS:                                        # restoring on the same Mac: its own keys stay
            old = os.path.join(aside, t)
            if os.path.isfile(old) and not os.path.exists(os.path.join(base, t)):
                os.makedirs(os.path.dirname(os.path.join(base, t)), exist_ok=True)
                shutil.copy2(old, os.path.join(base, t))
                kept.append(t)
        out.update(applied=True, aside=aside, moved=moved, rewritten=rewritten, kept_tokens=kept)
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------- automatic weekly backups ----------------
WEEK = 7 * 86400
WARN_AFTER = 14 * 86400
KEYCHAIN = ('axella-backup', 'automatic')


def check_folder(folder, base):
    f = os.path.abspath(os.path.expanduser(str(folder or '').strip()))
    if not str(folder or '').strip():
        raise Bad('pick a folder')
    if not os.path.isdir(f):
        raise Bad('that folder doesn\'t exist on the Mac mini (is the disk connected?)')
    b = os.path.abspath(base)
    if f == b or f.startswith(b + os.sep):
        raise Bad('not inside the Axella folder – pick a folder on another disk, a NAS share or iCloud Drive')
    probe = os.path.join(f, '.axella-write-test')
    try:
        with open(probe, 'w') as fh:
            fh.write('x')
        os.remove(probe)
    except OSError:
        raise Bad('Axella can\'t write to that folder')
    return f


def is_icloud(folder):
    return 'Mobile Documents' in (folder or '') or 'iCloud' in (folder or '')


def prune(folder, keep=KEEP):
    """Keep the newest `keep` automatic backups in the folder; only Axella's own file names are ever removed."""
    def when(n):
        try:
            return (os.path.getmtime(os.path.join(folder, n)), n)
        except OSError:
            return (0, n)
    names = sorted((n for n in os.listdir(folder) if NAME.match(n)), key=when)
    gone = []
    for n in names[:-keep] if len(names) > keep else []:
        try:
            os.remove(os.path.join(folder, n))
            gone.append(n)
        except OSError:
            pass
    return gone


def next_name(folder, day):
    n = 'axella-backup-%s%s' % (day.isoformat(), SUFFIX)
    i = 2
    while os.path.exists(os.path.join(folder, n)):
        n = 'axella-backup-%s-%d%s' % (day.isoformat(), i, SUFFIX)
        i += 1
    return n


class Auto:
    """state/backup.json: {"on", "folder", "history", "since", "last_ok", "last_try", "last_error", "last_name",
    "warned"}. The passphrase is in the Keychain (only while automatic backups are on)."""

    def __init__(self, state_dir, base, keychain, version='', push=None):
        self.file = os.path.join(state_dir, 'backup.json')
        self.base, self.kc, self.version, self.push = base, keychain, version, push
        self.lock = threading.Lock()

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        d = d if isinstance(d, dict) else {}
        for k, v in (('on', False), ('folder', None), ('history', True), ('since', None), ('last_ok', None), ('last_try', None),
                     ('last_error', None), ('last_name', None), ('warned', None)):
            d.setdefault(k, v)
        return d

    def _save(self, d):
        tmp = '%s.%d.%d.tmp' % (self.file, os.getpid(), threading.get_ident())
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)

    def settings(self, p):
        with self.lock:
            d = self.load()
            if 'history' in p:
                d['history'] = bool(p['history'])
            if p.get('on') is False:
                d['on'] = False
                self.kc.delete(*KEYCHAIN)                       # the passphrase is kept only while it's on
            elif p.get('on') is True:
                folder = check_folder(p.get('folder') or d.get('folder'), self.base)
                if p.get('passphrase'):
                    self.kc.set(KEYCHAIN[0], KEYCHAIN[1], check_passphrase(p['passphrase'], p.get('again')))
                elif not self.kc.get(*KEYCHAIN):
                    raise Bad('choose a passphrase for the automatic backups')
                d.update(on=True, folder=folder, since=d.get('since') if d.get('on') else _iso(), last_error=None)
            self._save(d)
            return self.status(d)

    def status(self, d=None):
        d = d or self.load()
        return {k: d.get(k) for k in ('on', 'folder', 'history', 'last_ok', 'last_try', 'last_error', 'last_name')} | \
            {'icloud': is_icloud(d.get('folder')), 'keep': KEEP}

    def due(self, now=None, d=None):
        d = d or self.load()
        now = now or time.time()
        if not d['on'] or not d['folder']:
            return False
        if d['last_try'] and now - _ts(d['last_try']) < 6 * 3600:
            return False                                       # a failed try waits 6 hours
        return not d['last_ok'] or now - _ts(d['last_ok']) >= WEEK

    def run(self, now=None, force=False):
        with self.lock:
            d = self.load()
            if not (force or self.due(now, d)):
                return None
            d['last_try'] = _iso()
            self._save(d)
        try:
            folder = check_folder(d['folder'], self.base)
            pw = self.kc.get(*KEYCHAIN)
            if not pw:
                raise Bad('the passphrase is missing from the Keychain – set automatic backups up again')
            name = next_name(folder, datetime.date.today())
            build(self.base, os.path.join(folder, name), pw, history=d['history'], version=self.version)
            prune(folder)
            res = {'last_ok': _iso(), 'last_error': None, 'last_name': name, 'warned': None}
        except (Bad, OSError) as e:
            res = {'last_error': str(e)[:200]}
        with self.lock:
            d = self.load()
            d.update(res)
            self._save(d)
        self.warn(d)
        return res

    def warn(self, d=None, now=None):
        """One push when two weeks pass without a good automatic backup."""
        d = d or self.load()
        now = now or time.time()
        ref = d['last_ok'] or d['since']
        if not d['on'] or not ref or now - _ts(ref) < WARN_AFTER or d.get('warned'):
            return False
        if self.push:
            try:
                self.push({'title': 'Axella backup', 'body': 'No good automatic backup for two weeks – see Settings → System → Backup.', 'tag': 'axella-backup'})
            except Exception:
                pass
        with self.lock:
            x = self.load()
            x['warned'] = _iso()
            self._save(x)
        return True

    def health(self, now=None):
        """(state, detail) for System status: off · ok · warn · down."""
        d = self.load()
        now = now or time.time()
        if not d['on']:
            return 'off', 'Automatic backups are off'
        if d['last_ok'] and now - _ts(d['last_ok']) < WEEK + 86400:
            return ('warn', 'The last try failed: %s' % d['last_error']) if d['last_error'] else ('ok', 'Last backup %s' % d['last_ok'][:10])
        if d['last_error']:
            return 'down', 'Backup failed: %s' % d['last_error']
        return 'warn', 'No automatic backup yet' if not d['last_ok'] else 'The weekly backup is late'


def _iso():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def _ts(s):
    try:
        return datetime.datetime.fromisoformat(str(s)).timestamp()
    except ValueError:
        return 0


# ---------------- Terminal: tools/restore.sh (and an export while the service is down) ----------------
def _main(argv):
    import getpass
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if len(argv) >= 2 and argv[0] == 'restore':
        path, apply = argv[1], '--apply' in argv[2:]
        pw = getpass.getpass('Passphrase for %s: ' % os.path.basename(path))
        try:
            r = restore(path, pw, base, apply=False)
        except Bad as e:
            print('✗ ' + str(e))
            return 1
        m = r['manifest']
        print('Backup from %s (Axella %s, format %s)%s' % (m['created'], m.get('axella_version') or '?', m['format'], ' – with history' if m['history'] else ''))
        for part, a in sorted(r['contents'].items()):
            print('  %-28s %5d files  %8.1f MB' % (part, a['files'], a['bytes'] / 1e6))
        print('Into %s:' % base)
        for s in r['steps']:
            print('  %-28s %s' % (s['part'], 'replaced – the current one is moved aside, not deleted' if s['exists'] else 'added'))
        if not apply:
            print('Dry run – nothing was changed. To restore: tools/restore.sh "%s" --apply' % path)
            return 0
        if input('Type yes to restore: ').strip().lower() != 'yes':
            print('Nothing was changed.')
            return 0
        try:
            r = restore(path, pw, base, apply=True)
        except Bad as e:
            print('✗ ' + str(e))
            return 1
        print('✓ Restored. The previous data is in %s' % r['aside'])
        if r['rewritten']:
            print('  Paths rewritten for this Mac in %d file(s).' % len(r['rewritten']))
        if r['kept_tokens']:
            print('  Kept this Mac\'s own keys: %s' % ', '.join(os.path.basename(t) for t in r['kept_tokens']))
        print('Reconnect after restore (System status shows what isn\'t working yet):')
        for t in r['reconnect']:
            print('  – ' + t)
        return 0
    if len(argv) >= 2 and argv[0] == 'export':
        pw = getpass.getpass('Choose a passphrase (at least %d characters): ' % MIN_PASS)
        try:
            check_passphrase(pw, getpass.getpass('Once more: '))
            m = build(base, argv[1], pw, history='--history' in argv[2:])
        except Bad as e:
            print('✗ ' + str(e))
            return 1
        print('✓ %s – %d files, %.1f MB. Keep the passphrase safe: without it the backup can\'t be opened.' % (m['name'], len(m['files']), m['size'] / 1e6))
        return 0
    print('usage: python3 setup/backup.py restore <file.axbak> [--apply] | export <file.axbak> [--history]')
    return 2


if __name__ == '__main__':
    import sys
    sys.exit(_main(sys.argv[1:]))
