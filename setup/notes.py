"""Notes (dev request notes): Axella's own notes – plain text, one file per note, with links to a person, project, trip,
meeting prep, mail or chat thread, and an optional "Remind me when they write".

notes/<id>.txt   the text (the first line is the title)
notes/index.json the rest: created, updated, pinned, Work/Private, links, remind, kept items

Owner only. Never in git, never read by a digest / urgent-check / compose / assistant run (scheduler.SECRETS); Ask
Axella gets a filtered copy for one run (export_for_ask) – never a note linked to a private or hidden contact, nor one
linked to a protected workplace whose Claude setting is "none". The reminder chips are matched here, locally, when the
dashboard asks (chips) – they are never written into a digest, a prompt or the spoken digest."""
import datetime
import json
import os
import re
import shutil
import threading
import time
import uuid

LOCK = threading.RLock()
KINDS = ('person', 'project', 'trip', 'meeting', 'mail', 'chat')
ID_RE = re.compile(r'^n[0-9a-f]{10}$')
BACKUP_RE = re.compile(r'^[0-9a-f]{12}$')
MAX_TEXT = 20000
MAX_LINKS = 12
SUBJ_PREFIX = re.compile(r'^\s*((re|fwd?|fw|sv|aw|vs|wg|tr)\s*(\[\d+\])?\s*:\s*)+', re.I)


class Bad(Exception):
    pass


def _now():
    return datetime.datetime.now().replace(microsecond=0)


def _iso(d=None):
    return (d or _now()).isoformat(timespec='seconds')


def _parse(s):
    try:
        d = datetime.datetime.fromisoformat(str(s or '').replace('Z', '+00:00')[:25])
    except ValueError:
        return None
    return d.astimezone().replace(tzinfo=None) if d.tzinfo else d


def title_of(text):
    for line in str(text or '').split('\n'):
        if line.strip():
            return line.strip()[:120]
    return 'Untitled note'


def thread_key(subject):
    """"Re: Quote v2" and "Quote v2" are one thread."""
    return ' '.join(SUBJ_PREFIX.sub('', str(subject or '')).lower().split())[:200]


def ident(raw):
    """An identity: a lower-case address, or a phone number as + and digits."""
    s = str(raw or '').strip()
    if '@' in s:
        return s.lower()[:200]
    d = re.sub(r'[^\d+]', '', s)
    return d if len(re.sub(r'\D', '', d)) >= 6 else ''


def clean_link(x):
    """One checked link: {kind, ref, label, keys?, account?, thread?, date?}."""
    if not isinstance(x, dict) or x.get('kind') not in KINDS:
        raise Bad('unknown kind of link')
    ref = str(x.get('ref') or '').strip()[:500]
    if not ref:
        raise Bad('a link needs what it points to')
    out = {'kind': x['kind'], 'ref': ref, 'label': ' '.join(str(x.get('label') or '').split())[:120]}
    keys = sorted({ident(k) for k in (x.get('keys') or []) if ident(k)})[:20]
    if keys:
        out['keys'] = keys
    if x['kind'] in ('mail', 'chat'):
        out['account'] = str(x.get('account') or '')[:100]
        out['thread'] = thread_key(x.get('thread') or '')
    if x['kind'] in ('meeting', 'trip') and x.get('date'):
        out['date'] = str(x['date'])[:10]
    return out


class Notes:
    def __init__(self, base, backup_dir):
        self.dir = os.path.join(base, 'notes')
        self.index_path = os.path.join(self.dir, 'index.json')
        self.backup_dir = backup_dir

    # ---------- storage ----------
    def load(self):
        try:
            with open(self.index_path, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        notes = d.get('notes') if isinstance(d, dict) and isinstance(d.get('notes'), dict) else {}
        return {'notes': {k: v for k, v in notes.items() if ID_RE.match(k) and isinstance(v, dict)}}

    def _save(self, d):
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        tmp = self.index_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.index_path)

    def _path(self, nid):
        if not ID_RE.match(str(nid or '')):
            raise Bad('unknown note')
        return os.path.join(self.dir, nid + '.txt')

    def text(self, nid):
        try:
            with open(self._path(nid), encoding='utf-8') as f:
                return f.read()
        except OSError:
            return ''

    def _write_text(self, nid, text):
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        p = self._path(nid)
        with open(p + '.tmp', 'w', encoding='utf-8') as f:
            f.write(text)
        os.chmod(p + '.tmp', 0o600)
        os.replace(p + '.tmp', p)

    # ---------- the dashboard ----------
    def view(self, nid, d=None):
        d = d or self.load()
        m = d['notes'].get(nid)
        if not m:
            raise Bad('unknown note')
        return dict(m, id=nid, text=self.text(nid))

    def list(self, q='', kind=None, ref=None):
        """Pinned first, then the newest. q searches the text; kind/ref: only notes linked to that."""
        d = self.load()
        q = ' '.join(str(q or '').lower().split())[:200]
        out = []
        for nid, m in d['notes'].items():
            if kind and not any(l['kind'] == kind and (ref is None or l['ref'] == ref) for l in m.get('links') or []):
                continue
            text = self.text(nid)
            if q and q not in text.lower():
                continue
            body = text.split('\n', 1)[1].strip() if '\n' in text else ''
            out.append(dict(m, id=nid, snippet=' '.join(body.split())[:160]))
        out.sort(key=lambda m: (m.get('updated') or '', m.get('ts') or 0), reverse=True)
        out.sort(key=lambda m: not m.get('pinned'))
        return out

    def save(self, p):
        """New note (no id) or a change: text, links, pinned, ctx, remind. Returns the note."""
        with LOCK:
            d = self.load()
            nid = str(p.get('id') or '')
            new = not nid
            if new:
                nid = 'n' + uuid.uuid4().hex[:10]
                m = {'created': _iso(), 'links': [], 'pinned': False, 'ctx': None, 'remind': False, 'kept': []}
            else:
                m = d['notes'].get(nid)
                if m is None:
                    raise Bad('unknown note')
            if 'text' in p or new:
                text = str(p.get('text') or '').replace('\r\n', '\n').replace('\r', '\n')
                if len(text) > MAX_TEXT:
                    raise Bad('a note is at most 20,000 characters')
                if new and not text.strip():
                    raise Bad('write something first')
                self._write_text(nid, text)
                m['title'] = title_of(text)
            if 'links' in p:
                links = [clean_link(x) for x in (p.get('links') or [])[:MAX_LINKS]]
                seen, uniq = set(), []
                for l in links:
                    if (l['kind'], l['ref']) not in seen:
                        seen.add((l['kind'], l['ref']))
                        uniq.append(l)
                m['links'] = uniq
            if 'pinned' in p:
                m['pinned'] = bool(p.get('pinned'))
            if 'ctx' in p:
                m['ctx'] = p['ctx'] if p.get('ctx') in ('work', 'private') else None
            if 'remind' in p:
                m['remind'] = bool(p.get('remind'))
                if m['remind']:
                    m['remind_from'] = _iso()       # only what arrives from now on
                    m['kept'] = []
            m['updated'], m['ts'] = _iso(), time.time()      # ts: the order within one second
            d['notes'][nid] = m
            self._save(d)
            return self.view(nid, d)

    def keep(self, nid, item_id):
        """"Keep" on a chip: not on this item again, but the reminder stays for the next message."""
        with LOCK:
            d = self.load()
            m = d['notes'].get(nid)
            if not m:
                raise Bad('unknown note')
            m['kept'] = (list(m.get('kept') or []) + [str(item_id)[:200]])[-200:]
            self._save(d)
        return {'id': nid}

    def delete(self, nid):
        """Backup, then delete: the copy in state/deleted/notes for 90 days (restore from the activity log)."""
        with LOCK:
            d = self.load()
            m = d['notes'].get(nid)
            if not m:
                raise Bad('unknown note')
            bid = uuid.uuid4().hex[:12]
            os.makedirs(self.backup_dir, mode=0o700, exist_ok=True)
            with open(os.path.join(self.backup_dir, bid + '.json'), 'w', encoding='utf-8') as f:
                json.dump({'id': nid, 'meta': m, 'text': self.text(nid), 'deleted': _iso()}, f, ensure_ascii=False)
            os.chmod(os.path.join(self.backup_dir, bid + '.json'), 0o600)
            d['notes'].pop(nid)
            self._save(d)
            try:
                os.remove(self._path(nid))
            except OSError:
                pass
        return {'backup': bid, 'title': m.get('title')}

    def restore(self, bid):
        if not BACKUP_RE.match(str(bid or '')):
            raise Bad('unknown copy')
        path = os.path.join(self.backup_dir, bid + '.json')
        try:
            with open(path, encoding='utf-8') as f:
                b = json.load(f)
        except (OSError, ValueError):
            raise Bad('that copy is gone (kept 90 days)')
        nid = b.get('id')
        with LOCK:
            d = self.load()
            if nid in d['notes']:
                raise Bad('that note is already back')
            self._write_text(nid, str(b.get('text') or ''))
            d['notes'][nid] = b.get('meta') or {}
            self._save(d)
        os.remove(path)
        return self.view(nid)

    def prune_backups(self, days=90):
        cut = _now().timestamp() - days * 86400
        try:
            for n in os.listdir(self.backup_dir):
                p = os.path.join(self.backup_dir, n)
                if n.endswith('.json') and os.path.getmtime(p) < cut:
                    os.remove(p)
        except OSError:
            pass

    # ---------- "Remind me when they write" – matched here, never written into a digest ----------
    def chips(self, items, today=None, meetings=(), trips=()):
        """{'items': {item_id: chip}, 'meetings': {prep_id: chip}, 'trips': {trip_id: chip}} – chip = {id, title, more}.
        items: the digest's items; meetings: [(prep_id, 'YYYY-MM-DD')]; trips: [(trip_id, start 'YYYY-MM-DD')].
        An item matches a note with Remind on when it arrived after the reminder was switched on and comes from a
        linked person (any identity) or belongs to a linked mail / chat thread. At most one chip per item: the newest
        note, plus how many more."""
        today = (today or datetime.date.today()).isoformat()
        d = self.load()
        live = [(nid, m) for nid, m in d['notes'].items() if m.get('remind')]
        live.sort(key=lambda x: (x[1].get('updated') or '', x[1].get('ts') or 0), reverse=True)
        out = {'items': {}, 'meetings': {}, 'trips': {}}

        def put(where, key, nid, m):
            c = out[where].get(key)
            if c:
                c['more'] += 1
            else:
                out[where][key] = {'id': nid, 'title': m.get('title') or 'Note', 'more': 0}
        for it in items or []:
            if not isinstance(it, dict) or not it.get('id') or it.get('section') in ('file',):
                continue
            seen = _parse(it.get('first_seen'))
            frm = ident((it.get('from') or {}).get('address'))
            thread = thread_key(it.get('subject') or '')
            for nid, m in live:
                start = _parse(m.get('remind_from') or m.get('created'))
                if it['id'] in (m.get('kept') or []) or (seen and start and seen < start):
                    continue
                hit = False
                for l in m.get('links') or []:
                    if l['kind'] == 'person' and frm and frm in (l.get('keys') or []):
                        hit = True
                    elif l['kind'] in ('mail', 'chat') and ((l.get('thread') and thread and l['thread'] == thread
                                                             and (not l.get('account') or l['account'] == it.get('account')))
                                                            or l['ref'] == it.get('message_id')):
                        hit = hit or l['ref'] != it.get('message_id')     # the linked message itself isn't "new"
                if hit:
                    put('items', it['id'], nid, m)
        for pid, day in meetings or []:
            if day == today:
                for nid, m in live:
                    if any(l['kind'] == 'meeting' and l['ref'] == pid for l in m.get('links') or []):
                        put('meetings', pid, nid, m)
        for tid, start in trips or []:
            if start == today:
                for nid, m in live:
                    if any(l['kind'] == 'trip' and l['ref'] == tid for l in m.get('links') or []):
                        put('trips', tid, nid, m)
        return out

    # ---------- Ask Axella: a filtered copy for one run ----------
    def export_for_ask(self, dest, readable):
        """Copy the notes Ask may read (readable(note) -> bool) into dest, one file per note. Returns how many."""
        d = self.load()
        os.makedirs(dest, mode=0o700, exist_ok=True)
        n = 0
        for nid, m in d['notes'].items():
            try:
                ok = readable(dict(m, id=nid))
            except Exception:
                ok = False
            if not ok:
                continue
            with open(os.path.join(dest, nid + '.txt'), 'w', encoding='utf-8') as f:
                f.write(self.text(nid))
            n += 1
        return n

    @staticmethod
    def drop_export(dest):
        shutil.rmtree(dest, ignore_errors=True)
