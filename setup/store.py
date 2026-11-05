"""Axella store: one SQLite file (state/axella.db) that indexes what Axella already writes as files.

Files stay the source of truth and the interface for Claude runs (digests, calls, actions.log, runs.json). This
module only copies them into tables so they can be queried over time (Insights) and searched (full text), and it is
the place later features (knowledge base, learning) build on. Deleting state/axella.db is safe: the next pass
rebuilds it from the files.

Every 60 s (thread in the action service), only files that changed since the last pass:
  digests/*.json + digests/archive/**/*.json  → digests, items (+ items_fts)  – rebuilt per file when it changes
  calls/call-*.json                           → calls
  state/actions.log                           → actions (appended from the last byte read)
  state/runs.json                             → runs

Protected workplaces (setup/actions-config.json "workplaces", AXELLA.md "Workplaces" – their content stays in the
digest files): items from their mail accounts or senders on their domains are stored as metadata only (sender,
section, project, topic, times, message id) – no
headline, detail or subject, and they are not in the full-text index.

Python 3.9 standard library only (sqlite3 with FTS5, as shipped with macOS).
"""
import glob
import re
import json
import os
import sqlite3
import sys
import threading
import time

import axprofile as profile

SCHEMA_VERSION = 1
SCHEMA = '''
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, mtime REAL, size INTEGER);
CREATE TABLE IF NOT EXISTS digests (
  name TEXT PRIMARY KEY, kind TEXT, title TEXT, generated TEXT, intro TEXT, n_items INTEGER);
CREATE TABLE IF NOT EXISTS items (
  digest TEXT, id TEXT, generated TEXT, section TEXT, channel TEXT, account TEXT, context TEXT,
  from_name TEXT, from_address TEXT, subject TEXT, headline TEXT, detail TEXT, message_id TEXT,
  project TEXT, topic TEXT, first_seen TEXT, carried INTEGER, overdue INTEGER, has_draft INTEGER,
  PRIMARY KEY (digest, id));
CREATE INDEX IF NOT EXISTS items_id ON items(id);
CREATE INDEX IF NOT EXISTS items_from ON items(from_address);
CREATE INDEX IF NOT EXISTS items_gen ON items(generated);
CREATE TABLE IF NOT EXISTS calls (
  id TEXT PRIMARY KEY, started TEXT, duration_s INTEGER, name TEXT, number TEXT, tier TEXT, priority TEXT,
  context TEXT, summary TEXT, lang TEXT);
CREATE TABLE IF NOT EXISTS actions (
  at TEXT, login TEXT, action TEXT, result TEXT, item TEXT, message_id TEXT, folder TEXT, title TEXT);
CREATE INDEX IF NOT EXISTS actions_at ON actions(at);
CREATE INDEX IF NOT EXISTS actions_item ON actions(item);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, task TEXT, trigger TEXT, status TEXT, started TEXT, ended TEXT, model TEXT,
  input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL, reason TEXT);
-- one row per item id (an item carried through several digests appears once, with its latest text)
CREATE VIEW IF NOT EXISTS item_latest AS
  SELECT i.* FROM items i JOIN (SELECT id, MAX(generated) g FROM items GROUP BY id) l
  ON i.id = l.id AND i.generated = l.g;
'''
FTS = '''CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
  headline, detail, subject, from_name, digest UNINDEXED, id UNINDEXED, tokenize = 'unicode61 remove_diacritics 2')'''


def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%S%z')


# the digest's own roll-up line ("Noise (P4): 12 newsletters …") is a count, not a message: never a search hit or an insight
# … and its "nothing" lines ("Messages – nothing waiting on you", "WhatsApp – nothing new since 07:30")
SUMMARY_RE = re.compile(r'^\s*(Noise \(P4\)|[^–:\n]{2,40}?\s[–-]\s*nothing (else )?(new|open|waiting|left|pending)\b'
                        # … with a count first ("Messages – 2 chats and a group, nothing else new"), fix round 7
                        r'|(?:messages|whatsapp|signal|imessage|sms|mail|calls|beskeder|opkald)\s[–-]\s[^\n]{0,80}?\bnothing (?:else )?'
                        r'(?:new|open|waiting|left|pending|to (?:answer|reply|do|handle))\b'
                        r'|[^–:\n]{2,40}?\s[–-]\s[^\n]{0,60}?\bnothing (?:else )?(?:new|open|waiting|left|pending)(?: since [\d:.]+)?\s*[.)]?\s*$'
                        r'|rest of (?:today|the day)\s*[:–-]?\s*nothing\b)', re.I)


class Store:
    def __init__(self, base, state_dir, log=sys.stderr):
        self.base, self.state_dir, self.log = base, state_dir, log
        self.path = os.path.join(state_dir, 'axella.db')
        self.lock = threading.Lock()
        self.fts = False
        self.last = {'at': None, 'error': None, 'changed': 0}

    # ---------- connection ----------
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=NORMAL')
        return db

    def init(self):
        with self.lock, self._db() as db:
            db.executescript(SCHEMA)
            try:
                db.execute(FTS)
                self.fts = True
            except sqlite3.OperationalError as e:          # SQLite without FTS5: everything else still works
                self.log.write('%s store: no full-text search (%s)\n' % (_now(), e))
            db.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # ---------- change tracking ----------
    @staticmethod
    def _changed(db, path):
        try:
            st = os.stat(path)
        except OSError:
            return None
        row = db.execute('SELECT mtime, size FROM files WHERE path=?', (path,)).fetchone()
        if row and row['mtime'] == st.st_mtime and row['size'] == st.st_size:
            return None
        return st

    @staticmethod
    def _seen(db, path, st):
        db.execute('INSERT OR REPLACE INTO files VALUES (?,?,?)', (path, st.st_mtime, st.st_size))

    # ---------- ingest ----------
    def _digest(self, db, path):
        name = os.path.basename(path)[:-5]
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        items = d.get('items') or []
        gen = d.get('generated') or ''
        db.execute('INSERT OR REPLACE INTO digests VALUES (?,?,?,?,?,?)',
                   (name, d.get('kind'), d.get('title'), gen, d.get('intro'), len(items)))
        db.execute('DELETE FROM items WHERE digest=?', (name,))
        if self.fts:
            db.execute('DELETE FROM items_fts WHERE digest=?', (name,))
        for it in items:
            if not isinstance(it, dict) or not it.get('id'):
                continue
            fr = it.get('from') or {}
            addr = (fr.get('address') or fr.get('number') or '').strip().lower()
            # protected workplace (its mailbox, or one of its senders writing to a private mailbox): metadata only
            ds = profile.is_protected(it.get('account'), addr, self._cfg)
            row = (name, str(it['id']), gen, it.get('section'), it.get('channel'), it.get('account'), it.get('context'),
                   fr.get('name') or None, addr or None,
                   None if ds else it.get('subject'), None if ds else it.get('headline'), None if ds else it.get('detail'),
                   it.get('message_id'), it.get('project'), it.get('topic'), it.get('first_seen'),
                   1 if it.get('carried') else 0, 1 if it.get('overdue') else 0, 1 if it.get('draft') else 0)
            db.execute('INSERT OR REPLACE INTO items VALUES (%s)' % ','.join('?' * len(row)), row)
            if self.fts and not ds:
                db.execute('INSERT INTO items_fts VALUES (?,?,?,?,?,?)',
                           (it.get('headline'), it.get('detail'), it.get('subject'), fr.get('name'), name, str(it['id'])))

    def _call(self, db, path):
        with open(path, encoding='utf-8') as f:
            c = json.load(f)
        fr = c.get('from') or {}
        db.execute('INSERT OR REPLACE INTO calls VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (c.get('id') or os.path.basename(path)[:-5], c.get('started'), c.get('duration_s'), fr.get('name'),
                    fr.get('number'), fr.get('tier'), c.get('priority'), c.get('context'), c.get('summary'), c.get('lang')))

    def _actions(self, db):
        path = os.path.join(self.state_dir, 'actions.log')
        try:
            size = os.path.getsize(path)
        except OSError:
            return 0
        row = db.execute("SELECT v FROM meta WHERE k='actions_offset'").fetchone()
        off = int(row['v']) if row else 0
        n = 0
        if size < off:                                     # rotated by housekeeping (renamed to actions.log.1): finish the
            try:                                           # old file, then read the new one from the start – the history
                with open(path + '.1', 'rb') as f:         # already in the database stays
                    f.seek(off)
                    n += self._action_lines(db, f.read())
            except OSError:
                pass
            off = 0
        if size == off:
            db.execute("INSERT OR REPLACE INTO meta VALUES ('actions_offset', ?)", (str(off),))
            return n
        with open(path, 'rb') as f:
            f.seek(off)
            data = f.read()
        end = data.rfind(b'\n') + 1                        # only complete lines
        n += self._action_lines(db, data[:end])
        db.execute("INSERT OR REPLACE INTO meta VALUES ('actions_offset', ?)", (str(off + end),))
        return n

    @staticmethod
    def _action_lines(db, data):
        n = 0
        for line in data.decode('utf-8', 'replace').splitlines():
            try:
                a = json.loads(line)
            except ValueError:
                continue
            if isinstance(a.get('items'), list):          # one log line for a batch: a row per item, as single actions
                for it in a['items'][:200]:
                    db.execute('INSERT INTO actions VALUES (?,?,?,?,?,?,?,?)',
                               (a.get('at'), a.get('login'), 'trash' if a.get('action') == 'trash_batch' else a.get('action'),
                                a.get('result'), it, None, None, None))
                n += 1
                continue
            db.execute('INSERT INTO actions VALUES (?,?,?,?,?,?,?,?)',
                       (a.get('at'), a.get('login'), a.get('action'), a.get('result'), a.get('item'),
                        a.get('message_id'), a.get('folder'), a.get('title')))
            n += 1
        return n

    def _runs(self, db):
        path = os.path.join(self.state_dir, 'runs.json')
        st = self._changed(db, path)
        if not st:
            return 0
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        for r in d.get('runs', []):
            u = r.get('usage') or {}
            db.execute('INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (r['id'], r.get('task'), r.get('trigger'), r.get('status'), r.get('started'), r.get('ended'),
                        r.get('model'), u.get('input'), u.get('output'), u.get('cost_usd'), r.get('reason')))
        self._seen(db, path, st)
        return 1

    def ingest(self):
        changed = 0
        self._cfg = profile.load()
        with self.lock, self._db() as db:
            paths = glob.glob(os.path.join(self.base, 'digests', '*.json')) + \
                glob.glob(os.path.join(self.base, 'digests', 'archive', '**', '*.json'), recursive=True)
            for p in paths:
                if p.endswith('.tmp'):
                    continue
                st = self._changed(db, p)
                if not st:
                    continue
                try:
                    self._digest(db, p)
                    self._seen(db, p, st)
                    changed += 1
                except (OSError, ValueError) as e:        # half-written file: try again next pass
                    self.log.write('%s store: %s: %s\n' % (_now(), os.path.basename(p), str(e)[:120]))
            for p in glob.glob(os.path.join(self.base, 'calls', 'call-*.json')):
                st = self._changed(db, p)
                if st:
                    try:
                        self._call(db, p)
                        self._seen(db, p, st)
                        changed += 1
                    except (OSError, ValueError):
                        pass
            changed += self._actions(db)
            changed += self._runs(db)
        return changed

    def run(self, every=60):
        try:
            self.init()
        except Exception as e:
            self.last.update(error=str(e)[:300])
            self.log.write('%s store init: %s\n' % (_now(), e))
            return
        while True:
            try:
                n = self.ingest()
                self.last = {'at': _now(), 'error': None, 'changed': n}
            except Exception as e:
                self.last = {'at': _now(), 'error': str(e)[:300], 'changed': 0}
                self.log.write('%s store: %s\n' % (_now(), str(e)[:300]))
            time.sleep(every)

    # ---------- read ----------
    def status(self):
        out = {'path': 'state/axella.db', 'fts': self.fts, **self.last}
        try:
            with self._db() as db:
                for t in ('digests', 'items', 'calls', 'actions', 'runs'):
                    out[t] = db.execute('SELECT COUNT(*) FROM %s' % t).fetchone()[0]
                out['since'] = db.execute('SELECT MIN(generated) FROM digests').fetchone()[0]
            out['size_kb'] = round(os.path.getsize(self.path) / 1024)
        except (sqlite3.Error, OSError) as e:
            out['error'] = out.get('error') or str(e)[:200]
        return out

    def search(self, q, limit=50):
        q = ' '.join(w for w in str(q or '').replace('"', ' ').split() if w)[:200]
        if not q or not self.fts:
            return []
        match = ' '.join('"%s"*' % w for w in q.split())   # every word, prefix match
        with self._db() as db:
            rows = db.execute('''SELECT i.digest, i.id, i.generated, i.section, i.channel, i.from_name, i.from_address,
                                        i.headline, i.subject, i.project
                                 FROM items_fts f JOIN items i ON i.digest = f.digest AND i.id = f.id
                                 WHERE items_fts MATCH ? ORDER BY i.generated DESC LIMIT ?''', (match, limit)).fetchall()
        seen, out = set(), []
        for r in rows:                                     # newest version of each item only
            if r['id'] in seen or SUMMARY_RE.match(r['headline'] or ''):
                continue
            seen.add(r['id'])
            out.append(dict(r))
        return out

    # ---------- insights ----------
    @staticmethod
    def period(name, today=None):
        """(from, to, prev_from, prev_to) as YYYY-MM-DD, inclusive."""
        import datetime as dt
        t = today or dt.date.today()
        def month_start(d):
            return d.replace(day=1)
        def add_months(d, n):
            y, m = divmod(d.month - 1 + n, 12)
            return d.replace(year=d.year + y, month=m + 1, day=1)
        if name == 'lastweek':
            a = t - dt.timedelta(days=t.weekday() + 7); b = a + dt.timedelta(days=6)
        elif name == 'month':
            a, b = month_start(t), t
        elif name == 'lastmonth':
            a = add_months(month_start(t), -1); b = month_start(t) - dt.timedelta(days=1)
        elif name == 'quarter':
            a = dt.date(t.year, 3 * ((t.month - 1) // 3) + 1, 1); b = t
        elif name == 'year':
            a, b = dt.date(t.year, 1, 1), t
        else:                                              # this week (Mon–today)
            a, b = t - dt.timedelta(days=t.weekday()), t
        # previous period of the same kind (same length, right before)
        if name in ('month', 'lastmonth'):
            pa = add_months(a, -1); pb = pa + (b - a) if name == 'month' else a - dt.timedelta(days=1)
            if name == 'month':
                pb = min(pb, a - dt.timedelta(days=1))
        elif name == 'quarter':
            pa = add_months(a, -3); pb = min(pa + (b - a), a - dt.timedelta(days=1))
        elif name == 'year':
            pa = dt.date(a.year - 1, 1, 1); pb = min(dt.date(a.year - 1, b.month, min(b.day, 28)), a - dt.timedelta(days=1))
        elif name == 'week':                              # this week so far against the whole of last week
            pa = a - dt.timedelta(days=7); pb = a - dt.timedelta(days=1)
        else:
            pa = a - dt.timedelta(days=7); pb = pa + (b - a)
        return a.isoformat(), b.isoformat(), pa.isoformat(), pb.isoformat()

    AUTOMATED = ('noreply', 'no-reply', 'donotreply', 'do-not-reply', 'notification', 'notifications', 'mailer',
                 'newsletter', 'news', 'info', 'support', 'billing', 'invoice', 'receipts', 'hello', 'team', 'updates',
                 'alerts', 'alert', 'service', 'kundeservice', 'system', 'automated', 'calendar', 'bounce')
    # services that write from a personal-looking address or a whole domain: government mailboxes, banks, app stores
    SERVICE_DOMAINS = ('e-boks.dk', 'e-boks.com', 'eboks.dk', 'digitalpost.dk', 'borger.dk', 'mitid.dk', 'nemid.nu',
                       'skat.dk', 'sktst.dk', 'virk.dk', 'apple.com', 'itunes.com', 'google.com', 'accounts.google.com',
                       'github.com', 'linkedin.com', 'facebookmail.com', 'paypal.com', 'mobilepay.dk', 'stripe.com',
                       # invoicing platforms that send a company's invoices on its behalf
                       'e-conomic.com', 'e-conomic.dk', 'economic.dk', 'dinero.dk', 'billy.dk', 'billysbilling.com',
                       'invoice.stripe.com', 'quickbooks.com', 'intuit.com', 'xero.com', 'fortnox.se', 'visma.com',
                       'zervant.com', 'sevdesk.de', 'freshbooks.com', 'chargebee.com', 'paddle.com')
    SERVICE_NAME = re.compile(r'\b(e-?boks|digital post|app store connect|mitid|nemid|bank|banken|paypal|mobilepay|'
                              r'e-?conomic|dinero|invoic\w*|billing|faktura\w*|regning\w*|invoicing system)\b|\(.*(invoic|billing|faktur).*\)', re.I)
    # "topics" that are really channels or buckets, not subjects
    NOT_TOPICS = {'messages', 'message', 'whatsapp', 'sms', 'imessage', 'mail', 'email', 'calls', 'call', 'calendar',
                  'family calendar', 'noise', 'p4', 'fyi', 'newsletters', 'notifications', 'receipts', 'other', 'misc'}

    def _bulk(self):
        try:
            with open(os.path.join(self.state_dir, 'senders.json'), encoding='utf-8') as f:
                return set((json.load(f).get('senders') or {}).keys())
        except (OSError, ValueError):
            return set()

    def _world(self):
        """Same rule as the dashboard's Work/Private filter (web/src/lib/data.ts ctxOf): your overrides per item, sender,
        domain first, then the digest's own "context", then the mailbox kind."""
        try:
            with open(os.path.join(self.state_dir, 'context-overrides.json'), encoding='utf-8') as f:
                o = json.load(f)
        except (OSError, ValueError):
            o = {}
        work_acc = {a['id'] for a in profile.accounts() if a.get('kind') == 'work'}

        def world(item_id, addr, context, account):
            addr = (addr or '').lower()
            dom = addr.split('@')[1] if '@' in addr else ''
            for v in ((o.get('item') or {}).get(str(item_id or '').lower()), (o.get('sender') or {}).get(addr) if addr else None,
                      (o.get('domain') or {}).get(dom) if dom else None, context if context in ('work', 'private') else None):
                if v in ('work', 'private'):
                    return v
            return 'work' if account in work_acc else 'private'
        return world

    def insights(self, period='week', limit=10, people_only=True, ctx='all'):
        a, b, pa, pb = self.period(period)
        limit = max(1, min(int(limit or 10), 50))
        bulk = self._bulk() if people_only else set()
        try:                                              # the owner (own addresses/number, test calls)
            with open(os.path.join(self.base, 'setup', 'actions-config.json'), encoding='utf-8') as f:
                me = json.load(f).get('self') or {}
        except (OSError, ValueError):
            me = {}
        my_ids = {x.lower() for x in me.get('addresses', [])}
        my_names = {x.lower() for x in me.get('names', [])}

        def human(addr):
            if not addr or addr.lower() in my_ids:
                return False
            if not people_only:
                return True
            if addr in bulk:
                return False
            dom = addr.split('@')[1].lower() if '@' in addr else ''
            if dom and any(dom == d or dom.endswith('.' + d) for d in self.SERVICE_DOMAINS) or re.search(r'(^|\.)[a-z0-9-]*bank[a-z0-9-]*\.', dom):
                return False
            local = addr.split('@')[0]
            return not any(local == w or local.startswith(w + '.') or local.startswith(w + '-') or local.startswith(w + '_')
                           or local.startswith(w) and w in ('noreply', 'no-reply', 'donotreply', 'notification', 'mailer')
                           for w in self.AUTOMATED)

        # one row per message/item in the range (an item carried over several digests counts once)
        q = '''SELECT COALESCE(message_id, id) k, MIN(id) id, from_address addr, MAX(from_name) name, channel,
                      MAX(COALESCE(topic, project)) topic, MAX(project) project, MIN(substr(generated,1,10)) day,
                      MAX(context) context, MAX(account) account
               FROM items WHERE section NOT IN ('file') AND COALESCE(headline, '') NOT LIKE 'Noise (P4)%' AND COALESCE(headline, '') NOT LIKE '% – nothing new%' AND COALESCE(headline, '') NOT LIKE '% – nothing else%'
                      AND COALESCE(headline, '') NOT LIKE '% – nothing open%' AND COALESCE(headline, '') NOT LIKE '% – nothing waiting%' AND substr(generated,1,10) BETWEEN ? AND ?
               GROUP BY k'''
        with self._db() as db:
            cur = [dict(r) for r in db.execute(q, (a, b)).fetchall()]
            prev = [dict(r) for r in db.execute(q, (pa, pb)).fetchall()]
            handled = {r[0] for r in db.execute(
                "SELECT DISTINCT item FROM actions WHERE item IS NOT NULL AND action IN ('done','file','trash','draft')").fetchall()}
            calls = [dict(r) for r in db.execute(
                'SELECT name, number, priority, context FROM calls WHERE substr(started,1,10) BETWEEN ? AND ?', (a, b)).fetchall()]
            since = db.execute('SELECT MIN(substr(generated,1,10)) FROM digests').fetchone()[0]
            topics_since = db.execute("SELECT MIN(substr(generated,1,10)) FROM items WHERE topic IS NOT NULL").fetchone()[0]

        if ctx in ('work', 'private'):                    # the dashboard's All / Work / Private filter
            world = self._world()
            keep = lambda r: world(r['id'], r['addr'], r['context'], r['account']) == ctx
            cur, prev = [r for r in cur if keep(r)], [r for r in prev if keep(r)]
            calls = [c for c in calls if world(None, c['number'], c['context'], None) == ctx]

        def people(rows):
            out = {}
            for r in rows:
                if not human(r['addr']) or (r['name'] or '').lower() in my_names:
                    continue
                if people_only and self.SERVICE_NAME.search(r['name'] or ''):
                    continue
                p = out.setdefault(r['addr'], {'address': r['addr'], 'name': r['name'] or '', 'count': 0, 'open': 0, 'channels': {}})
                p['count'] += 1
                p['name'] = p['name'] or (r['name'] or '')
                p['channels'][r['channel'] or 'other'] = p['channels'].get(r['channel'] or 'other', 0) + 1
                if r['id'] not in handled:
                    p['open'] += 1
            return out

        def topics(rows):
            out = {}
            for r in rows:
                t = (r['topic'] or '').strip()
                if not t or t.lower().strip('#') in self.NOT_TOPICS or re.search(r'\bcalendar\b', t, re.I):
                    continue                          # a calendar ("Acme calendar") is where things are, not a topic
                key = t.lower()
                e = out.setdefault(key, {'topic': t, 'count': 0, 'people': set()})
                e['count'] += 1
                if r['addr']:
                    e['people'].add(r['addr'])
            return out

        pc, pp = people(cur), people(prev)
        for c in calls:                                   # calls count as contact with that person
            if (c['number'] or '') in my_ids or (c['name'] or '').lower() in my_names:
                continue
            key = 'tel:' + (c['number'] or '')
            p = pc.setdefault(key, {'address': c['number'] or '', 'name': c['name'] or c['number'] or 'Unknown caller',
                                    'count': 0, 'open': 0, 'channels': {}})
            p['count'] += 1
            p['channels']['call'] = p['channels'].get('call', 0) + 1
        top_p = sorted(pc.values(), key=lambda p: (-p['count'], p['name']))[:limit]
        for p in top_p:
            p['prev'] = pp.get(p['address'], {}).get('count', 0)
        tc, tp = topics(cur), topics(prev)
        top_t = sorted(tc.values(), key=lambda t: (-t['count'], t['topic']))[:limit]
        for t in top_t:
            t['prev'] = tp.get(t['topic'].lower(), {}).get('count', 0)
            t['people'] = len(t['people'])
        # history that starts inside the comparison period makes every row look "new" – then don't compare at all
        # … unless it covers most of it (history from Tuesday still makes a fair week): then compare, and say from when
        import datetime as dt
        try:
            # days counted inclusively: history from Tuesday covers 6 of last week's 7 days
            covered = since and ((dt.date.fromisoformat(pb[:10]) - dt.date.fromisoformat(max(since[:10], pa[:10]))).days + 1) \
                / ((dt.date.fromisoformat(pb[:10]) - dt.date.fromisoformat(pa[:10])).days + 1)
        except ValueError:
            covered = 0
        compare = bool(since and (since <= pa or covered >= 0.7))
        if not compare:
            for x in top_p + top_t:
                x['prev'] = None
        return {'period': period, 'from': a, 'to': b, 'prev_from': pa, 'prev_to': pb, 'since': since, 'compare': compare,
                'prev_partial': bool(compare and since and since[:10] > pa[:10]),
                'topics_since': topics_since, 'people_only': people_only, 'ctx': ctx,
                'totals': {'items': len(cur), 'items_prev': len(prev), 'calls': len(calls),
                           'people': len(pc), 'handled': sum(1 for r in cur if r['id'] in handled)},
                'people': top_p, 'topics': top_t}
