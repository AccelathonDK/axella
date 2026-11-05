"""Knowledge base (knowledge/entries/*.md) – short, checked facts and answers that drafts may build on.

One Markdown file per entry; the files are the truth (readable, editable by hand, read by the Claude runs with Grep/Read).
Frontmatter lines are `key: <JSON value>` so no YAML library is needed:

  ---
  id: "k20261101…"
  title: "Invoicing terms"
  scope: "overall"            or ["p-acme", …]  (project ids)
  category: "own company"     employer | own company | holiday rental | private | other
  visibility: "internal"      private (never in replies) | internal (owner, colleagues, own companies) | shareable (anyone)
  status: "active"            suggested | active | dismissed   (only active entries are used)
  sources: [{"kind": "manual|mail|file|url", "ref": "…", "date": "YYYY-MM-DD", "label": "…"}]
  created / updated: iso      check_after: "YYYY-MM-DD" | null      language: "en|da|…" (optional)
  learned: "sent|draft-edit|thread" (suggestions from the knowledge harvest, kb_harvest.py)   from_others: "<name>" | null
  outdated: {"reason", "source", "at"} | null   – newer mail contradicts this active entry; cleared when the owner
                                                  confirms ("Still correct") or edits it
  ---
  The fact or answer, short.

Deleting moves the file to knowledge/.deleted/ (never a hard delete from the dashboard). See docs/ROADMAP.md (G) and
the knowledge-base spec for steps 2–4 (sent-mail harvest, imports, URL snapshots, auto-reply rules).
"""
import datetime
import json
import os
import re
import threading

LOCK = threading.Lock()
SCOPES_MAX = 20
CATEGORIES = ('employer', 'own company', 'holiday rental', 'private', 'other')
VISIBILITY = ('private', 'internal', 'shareable')
STATUS = ('suggested', 'active', 'dismissed')
KINDS = ('manual', 'mail', 'file', 'url')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
ID = re.compile(r'^k[0-9a-z]{6,40}$')
FIELDS = ('id', 'title', 'scope', 'category', 'visibility', 'status', 'sources', 'created', 'updated', 'check_after', 'language',
          'learned', 'from_others', 'outdated')
LEARNED = ('manual', 'sent', 'draft-edit', 'thread')


class Bad(Exception):
    pass


def _iso():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def dump(e):
    head = '\n'.join('%s: %s' % (k, json.dumps(e.get(k), ensure_ascii=False)) for k in FIELDS)
    return '---\n%s\n---\n%s\n' % (head, (e.get('body') or '').strip())


def parse(text):
    m = re.match(r'^---\n(.*?)\n---\n?(.*)$', text, re.S)
    if not m:
        raise ValueError('no frontmatter')
    e = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(':')
        k = k.strip()
        if k in FIELDS:
            try:
                e[k] = json.loads(v.strip())
            except ValueError:
                e[k] = v.strip()          # tolerate a hand-edited plain value
    e['body'] = m.group(2).strip()
    return e


class Knowledge:
    def __init__(self, base_dir, today=None):
        self.dir = os.path.join(base_dir, 'knowledge', 'entries')
        self.bin = os.path.join(base_dir, 'knowledge', '.deleted')
        self.today = today or datetime.date.today

    # ---------- storage ----------
    def _path(self, eid):
        if not isinstance(eid, str) or not ID.match(eid):
            raise Bad('bad id')
        return os.path.join(self.dir, eid + '.md')

    def load(self):
        out = []
        try:
            names = sorted(os.listdir(self.dir))
        except OSError:
            return out
        for n in names:
            if not n.endswith('.md'):
                continue
            try:
                with open(os.path.join(self.dir, n), encoding='utf-8') as f:
                    e = parse(f.read())
            except (OSError, ValueError):
                continue
            e['id'] = n[:-3]
            out.append(self._norm(e))
        return out

    def _norm(self, e):
        sc = e.get('scope')
        if isinstance(sc, str) and sc not in ('', 'overall'):
            sc = [x.strip() for x in sc.split(',') if x.strip()]       # hand-edited "p-kitchen" or "p-a, p-b"
        if not (isinstance(sc, list) and sc and all(isinstance(x, str) for x in sc)):
            sc = 'overall'
        e['scope'] = sc
        e.setdefault('status', 'active')
        e.setdefault('visibility', 'internal')
        e.setdefault('category', 'other')
        e.setdefault('sources', [])
        ca = e.get('check_after')
        e['stale'] = bool(isinstance(ca, str) and DATE.match(ca) and ca <= self.today().isoformat())
        return e

    def _save(self, e):
        os.makedirs(self.dir, exist_ok=True)
        p = self._path(e['id'])
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(dump(e))
        os.replace(tmp, p)

    # ---------- read API ----------
    def status(self, project=None):
        es = self.load()
        if project:
            es = [e for e in es if e['scope'] == 'overall' or project in (e['scope'] or [])]
        es.sort(key=lambda e: e.get('updated') or '', reverse=True)
        return {'entries': es}

    def search(self, q, project=None, limit=20):
        """Simple word search over title + body; project entries rank above overall ones."""
        words = [w for w in re.findall(r'\w+', (q or '').lower()) if len(w) > 1]
        if not words:
            return {'entries': []}
        hits = []
        for e in self.load():
            if e['status'] == 'dismissed':
                continue
            if project and not (e['scope'] == 'overall' or project in (e['scope'] or [])):
                continue
            hay = ((e.get('title') or '') + ' ' + e.get('body', '')).lower()
            score = sum(hay.count(w) + 3 * (e.get('title') or '').lower().count(w) for w in words)
            if score and all(w in hay for w in words[:3]):
                if project and e['scope'] != 'overall':
                    score += 5
                hits.append((score, e))
        hits.sort(key=lambda x: -x[0])
        return {'entries': [e for _, e in hits[:limit]]}

    # ---------- dashboard actions ----------
    def _fields(self, p, e):
        if 'title' in p:
            t = str(p.get('title') or '').strip()
            if not t or len(t) > 200:
                raise Bad('title must be 1–200 characters')
            e['title'] = t
        if 'body' in p:
            b = str(p.get('body') or '').strip()
            if not b or len(b) > 20000:
                raise Bad('text must be 1–20000 characters')
            e['body'] = b
        if 'scope' in p:
            s = p['scope']
            if s == 'overall':
                e['scope'] = 'overall'
            elif isinstance(s, list) and s and len(s) <= SCOPES_MAX and all(isinstance(x, str) and re.match(r'^p-[\w-]{1,80}$', x) for x in s):
                e['scope'] = list(dict.fromkeys(s))
            else:
                raise Bad('scope must be "overall" or a list of project ids')
        for k, allowed in (('category', CATEGORIES), ('visibility', VISIBILITY), ('status', STATUS)):
            if k in p:
                if p[k] not in allowed:
                    raise Bad('bad ' + k)
                e[k] = p[k]
        if 'check_after' in p:
            ca = p['check_after']
            if ca not in (None, '') and not (isinstance(ca, str) and DATE.match(ca)):
                raise Bad('bad check-after date')
            e['check_after'] = ca or None
        if 'language' in p:
            e['language'] = str(p['language'] or '')[:10] or None
        if 'learned' in p:
            e['learned'] = p['learned'] if p['learned'] in LEARNED else None
        if 'from_others' in p:
            e['from_others'] = str(p['from_others'] or '')[:120] or None
        if 'outdated' in p:
            o = p['outdated']
            if o is not None and not (isinstance(o, dict) and isinstance(o.get('reason'), str)):
                raise Bad('bad outdated note')
            e['outdated'] = o
        elif any(k in p for k in ('title', 'body')) and e.get('outdated'):
            e['outdated'] = None                 # the owner edited it – that settles the warning
        if 'source' in p and p['source']:       # one more source (e.g. "Save as knowledge" from a draft)
            s = p['source']
            if not isinstance(s, dict) or s.get('kind') not in KINDS:
                raise Bad('bad source')
            src = {'kind': s['kind'], 'ref': str(s.get('ref') or '')[:500], 'label': str(s.get('label') or '')[:200],
                   'date': s.get('date') if isinstance(s.get('date'), str) and DATE.match(s['date']) else self.today().isoformat()}
            e['sources'] = [x for x in e.get('sources', []) if not (x.get('kind') == src['kind'] and x.get('ref') == src['ref'] and src['ref'])] + [src]
            e['sources'] = e['sources'][-20:]

    def action(self, action, p):
        with LOCK:
            if action == 'kb_add':
                if 'title' not in p or 'body' not in p:
                    raise Bad('title and text are needed')
                now = _iso()
                e = {'id': 'k' + datetime.datetime.now().strftime('%Y%m%d%H%M%S%f'), 'scope': 'overall', 'category': 'other',
                     'visibility': 'internal', 'status': 'active', 'sources': [], 'created': now, 'updated': now,
                     'check_after': None, 'language': None}
                p = dict(p)
                p.setdefault('source', {'kind': 'manual', 'ref': '', 'label': 'Added on the dashboard'})
                self._fields(p, e)
                self._save(e)
                return e['id']
            path = self._path(p.get('id'))
            if not os.path.exists(path):
                raise Bad('entry not found')
            with open(path, encoding='utf-8') as f:
                e = parse(f.read())
            e['id'] = p['id']
            if action == 'kb_update':
                self._fields(p, e)
                e['updated'] = _iso()
                self._save(e)
            elif action == 'kb_delete':
                os.makedirs(self.bin, exist_ok=True)
                os.replace(path, os.path.join(self.bin, os.path.basename(path)))
            else:
                raise Bad('unknown action')
            return e['id']
