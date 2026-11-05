"""Projects → Scan mail: the mails that make up a project, found on the Mac mini by rules (never Claude) from the
project's own Matches, sorted by the owner, and kept on the project's Mails card. The Trips pattern for projects.

Matches (projects.json): the tag, the keywords, the senders (addresses or domains), and the mails already shown in the
project from digests (their message ids, and their threads). Candidates come from Mail's index
(mailsearch.booking_candidates – subject and sender only; no message text is read to find them). Left out: private and
hidden contacts, a protected workplace's mail (unless the project belongs to that workplace), scam-flagged mail, and
mails outside the project's world (work / private / both). A mail is offered once; "Not this project" is final (Undo).

state/project-mail.json (chmod 600, in SECRETS – who wrote about what):
  {"projects": {<pid>: {"since", "last_scan", "candidates": {<mid>: {...}}, "added": {<mid>: {...}}, "not": [<mid>],
                        "dismissed_matches": [...], "trips": [<trip id>]}}}
Only what a row shows is kept: account, message id, subject, sender, date, thread, why it matched – never the text.
"""
import datetime
import json
import os
import re
import threading

LOCK = threading.Lock()
SCAN_DAYS = 548                         # at most 18 months back
DEFAULT_DAYS = 183                      # Scan since: 6 months back by default
MAX_CANDIDATES = 400
MAX_ADDED = 2000


class Bad(Exception):
    pass


def _base(d):
    p = [x for x in str(d or '').lower().split('.') if x]
    if len(p) >= 3 and len(p[-1]) == 2 and p[-2] in ('co', 'com', 'org', 'net'):
        return '.'.join(p[-3:])
    return '.'.join(p[-2:])


def _dom(addr):
    return str(addr or '').rsplit('@', 1)[-1].strip('<> ').lower() if '@' in str(addr or '') else ''


def _thread(subject):
    """A thread key from the subject: Re:/Fwd:/SV:/VS: and [tags] stripped, case and spaces folded."""
    s = str(subject or '').strip()
    while True:
        t = re.sub(r'^\s*((re|fw|fwd|sv|vs|aw|wg|tr|antw)\s*(\[\d+\])?\s*:|\[[^\]]{1,40}\])\s*', '', s, flags=re.I)
        if t == s:
            break
        s = t
    return re.sub(r'\s+', ' ', s).strip().lower()[:200]


class Matcher:
    """The project's Matches as a rule: (subject, sender) → the reasons it matched, or []."""

    def __init__(self, project, extra_mids=(), threads=()):
        self.tag = str(project.get('tag') or '').lower()
        self.words = [w.strip() for w in (project.get('keywords') or []) if isinstance(w, str) and len(w.strip()) >= 3][:30]
        senders = [str(s).strip().lower() for s in project.get('senders') or [] if str(s).strip()][:50]
        self.addrs = {s for s in senders if '@' in s}
        self.domains = {s.lstrip('@') for s in senders if '@' not in s and '.' in s}
        self.mids = set(extra_mids)
        self.threads = {t for t in threads if len(t) >= 6}
        self._rx = [(w, re.compile(r'(?<![\w])%s(?![\w])' % re.escape(w), re.I)) for w in self.words]
        self._tag = re.compile(r'(?<![\w])#?%s(?![\w])' % re.escape(self.tag), re.I) if len(self.tag) >= 3 else None

    def __call__(self, subject, addr, mid=None):
        why = []
        subj = str(subject or '')[:500]
        a = str(addr or '').lower()
        if mid and mid in self.mids:
            why.append('shown in a digest')
        if self._tag and self._tag.search(subj):
            why.append('tag: ' + self.tag)
        for w, rx in self._rx:
            if rx.search(subj):
                why.append('keyword: ' + w)
                break
        if a and a in self.addrs:
            why.append('sender: ' + a)
        elif a and (_dom(a) in self.domains or _base(_dom(a)) in self.domains):
            why.append('domain: ' + _dom(a))
        if not why and self.threads and _thread(subj) in self.threads:
            why.append('same thread as an added mail')
        return why

    def any(self):
        return bool(self._tag or self.words or self.addrs or self.domains or self.mids or self.threads)


def since_of(entry, today):
    try:
        d = datetime.date.fromisoformat(str((entry or {}).get('since') or '')[:10])
    except ValueError:
        d = None
    return d or today - datetime.timedelta(days=DEFAULT_DAYS)


class ProjectMail:
    def __init__(self, state_dir):
        self.file = os.path.join(state_dir, 'project-mail.json')
        self.status = {}

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        if not isinstance(d, dict) or not isinstance(d.get('projects'), dict):
            d = {'projects': {}}
        return d

    def _save(self, d):
        tmp = '%s.%d.tmp' % (self.file, os.getpid())
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)

    @staticmethod
    def _entry(d, pid):
        e = d['projects'].setdefault(pid, {})
        for k, v in (('candidates', {}), ('added', {}), ('not', []), ('dismissed_matches', []), ('trips', [])):
            e.setdefault(k, v)
        return e

    def entry(self, pid):
        return self._entry(self.load(), pid)

    def set_since(self, pid, since, today=None):
        today = today or datetime.date.today()
        try:
            s = datetime.date.fromisoformat(str(since)[:10])
        except ValueError:
            raise Bad('give the date as YYYY-MM-DD')
        if s > today or (today - s).days > SCAN_DAYS:
            raise Bad('a date in the last 18 months')
        with LOCK:
            d = self.load()
            self._entry(d, pid)['since'] = s.isoformat()
            self._save(d)
        return s

    def matcher(self, project, digest_mids=()):
        e = self.entry(project['id'])
        threads = {a.get('thread') for a in e['added'].values() if a.get('thread')}
        return Matcher(project, digest_mids, threads)

    def merge(self, pid, found, now=None):
        """New candidates from a scan: a mail is offered once (never again once added, refused or offered)."""
        now = now or datetime.datetime.now().astimezone().isoformat(timespec='seconds')
        with LOCK:
            d = self.load()
            e = self._entry(d, pid)
            seen = set(e['candidates']) | set(e['added']) | set(e['not'])
            new = 0
            for c in found:
                mid = c.get('message_id')
                if not mid or mid in seen:
                    continue
                seen.add(mid)
                e['candidates'][mid] = {k: c.get(k) for k in ('account', 'message_id', 'subject', 'from', 'address', 'date', 'why', 'thread')}
                new += 1
            if len(e['candidates']) > MAX_CANDIDATES:
                keep = sorted(e['candidates'].values(), key=lambda x: str(x.get('date') or ''), reverse=True)[:MAX_CANDIDATES]
                e['candidates'] = {x['message_id']: x for x in keep}
            e['last_scan'] = now
            self._save(d)
        return new

    def action(self, action, pid, p, other_pid=None):
        with LOCK:
            d = self.load()
            e = self._entry(d, pid)
            mid = str(p.get('message_id') or '')[:300]
            if action == 'project_mail_add':
                c = e['candidates'].pop(mid, None) or (p.get('mail') if isinstance(p.get('mail'), dict) else None)
                if not c or not mid:
                    raise Bad('that mail isn\'t offered for this project')
                if mid in e['not']:
                    e['not'].remove(mid)
                rec = {k: c.get(k) for k in ('account', 'message_id', 'subject', 'from', 'address', 'date', 'why', 'thread')}
                rec['message_id'] = mid
                rec['thread'] = rec.get('thread') or _thread(rec.get('subject'))
                rec['added'] = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
                e['added'][mid] = rec
                if len(e['added']) > MAX_ADDED:
                    raise Bad('a project holds at most %d mails' % MAX_ADDED)
            elif action == 'project_mail_not':
                c = e['candidates'].pop(mid, None)
                if mid not in e['not']:
                    e['not'].append(mid)
                e.setdefault('undo', {})[mid] = c
            elif action == 'project_mail_undo_not':
                if mid in e['not']:
                    e['not'].remove(mid)
                c = (e.get('undo') or {}).pop(mid, None)
                if c:
                    e['candidates'][mid] = c
            elif action == 'project_mail_remove':
                rec = e['added'].pop(mid, None)
                if not rec:
                    raise Bad('that mail isn\'t on this project')
                e.setdefault('removed', {})[mid] = rec
            elif action == 'project_mail_undo_remove':
                rec = (e.get('removed') or {}).pop(mid, None)
                if rec:
                    e['added'][mid] = rec
            elif action == 'project_mail_move':
                if not other_pid or other_pid == pid:
                    raise Bad('pick another project')
                c = e['candidates'].pop(mid, None) or e['added'].pop(mid, None)
                if not c:
                    raise Bad('that mail isn\'t on this project')
                o = self._entry(d, other_pid)
                o['candidates'].pop(mid, None)
                if mid in o['not']:
                    o['not'].remove(mid)
                o['added'][mid] = dict(c, thread=c.get('thread') or _thread(c.get('subject')),
                                       added=datetime.datetime.now().astimezone().isoformat(timespec='seconds'))
                if mid not in e['not']:
                    e['not'].append(mid)                 # not offered here again
            elif action == 'project_match_dismiss':
                m = str(p.get('match') or '').lower()[:200]
                if m and m not in e['dismissed_matches']:
                    e['dismissed_matches'].append(m)
            elif action in ('project_trip_link', 'project_trip_unlink'):
                tid = str(p.get('trip') or '')[:100]
                if not re.match(r'^[A-Za-z0-9_-]{1,100}$', tid):
                    raise Bad('unknown trip')
                if action == 'project_trip_link' and tid not in e['trips']:
                    e['trips'].append(tid)
                if action == 'project_trip_unlink' and tid in e['trips']:
                    e['trips'].remove(tid)
            else:
                raise Bad('unknown action')
            self._save(d)
            return {'candidates': len(e['candidates']), 'added': len(e['added'])}

    # ---- Read with Claude: suggestion cards, each confirmed or dismissed by the owner
    def set_suggestions(self, pid, cards, rid=None):
        with LOCK:
            d = self.load()
            e = self._entry(d, pid)
            have = e.setdefault('suggestions', [])
            n = len(have)
            for i, c in enumerate(cards):
                have.append(dict(c, id='s%s%d' % ((rid or 'x')[-8:], n + i)))
            e['suggestions'] = have[-100:]
            e['reading'] = None
            self._save(d)
        return len(cards)

    def suggestion_done(self, pid, sid):
        with LOCK:
            d = self.load()
            e = self._entry(d, pid)
            before = len(e.get('suggestions') or [])
            e['suggestions'] = [c for c in e.get('suggestions') or [] if c.get('id') != sid]
            if len(e['suggestions']) == before:
                raise Bad('that suggestion is gone')
            self._save(d)
        return 'ok'

    def set_reading(self, pid, rid):
        with LOCK:
            d = self.load()
            self._entry(d, pid)['reading'] = rid
            self._save(d)

    # ---- what the page shows
    def view(self, project):
        e = self.entry(project['id'])
        groups = {}
        for a in sorted(e['added'].values(), key=lambda x: str(x.get('date') or ''), reverse=True):
            groups.setdefault(a.get('thread') or a['message_id'], []).append(a)
        return {'since': e.get('since'), 'last_scan': e.get('last_scan'),
                'candidates': sorted(e['candidates'].values(), key=lambda x: str(x.get('date') or ''), reverse=True),
                'threads': [{'thread': k, 'mails': v} for k, v in groups.items()],
                'added': len(e['added']), 'suggest': self.suggest_matches(project), 'trips': list(e['trips']),
                'suggestions': list(e.get('suggestions') or []), 'reading': e.get('reading')}

    def suggest_matches(self, project, min_mails=2):
        """A sender (or domain) that several added mails share and that isn't in Matches yet – offered once."""
        e = self.entry(project['id'])
        have = {str(s).lower().lstrip('@') for s in project.get('senders') or []}
        by_addr, by_dom = {}, {}
        for a in e['added'].values():
            ad = str(a.get('address') or '').lower()
            if not ad or '@' not in ad:
                continue
            by_addr[ad] = by_addr.get(ad, 0) + 1
            by_dom[_base(_dom(ad))] = by_dom.get(_base(_dom(ad)), 0) + 1
        out = []
        for ad, n in sorted(by_addr.items(), key=lambda kv: -kv[1]):
            if n >= min_mails and ad not in have and _base(_dom(ad)) not in have and ad not in e['dismissed_matches']:
                out.append({'match': ad, 'mails': n})
        for dom, n in sorted(by_dom.items(), key=lambda kv: -kv[1]):
            if n >= min_mails + 1 and dom not in have and dom not in e['dismissed_matches'] and \
                    sum(1 for ad in by_addr if _base(_dom(ad)) == dom) >= 2:
                out.append({'match': dom, 'mails': n})
        return out[:3]

    def trip_suggestions(self, project, trips):
        """Confirmed trips whose booking mails were added to this project – offered as Link to trip."""
        e = self.entry(project['id'])
        mids = set(e['added'])
        out = []
        for t in trips:
            if t.get('id') in e['trips'] or t.get('status') == 'suggested':
                continue
            src = {((b.get('source') or {}).get('message_id')) for b in t.get('bookings') or []}
            if mids & {m for m in src if m}:
                out.append({'id': t['id'], 'title': t.get('title')})
        return out


DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
TIME_RE = re.compile(r'^\d{2}:\d{2}$')


def _clip(v, n):
    return re.sub(r'[\x00-\x1f\x7f]', ' ', str(v or '')).strip()[:n]


def clean_read(res, asked):
    """Claude's reading of the picked mails → suggestion cards: tasks, notes and key dates, each tied to one of the
    asked mails. Anything else is dropped (a run can't add a card for a mail that wasn't picked)."""
    asked = {m.get('message_id') for m in asked if m.get('message_id')}
    out = []
    if not isinstance(res, dict):
        return out
    for kind, key in (('task', 'tasks'), ('note', 'notes'), ('date', 'dates')):
        for x in (res.get(key) or [])[:30]:
            if not isinstance(x, dict) or x.get('message_id') not in asked:
                continue
            c = {'kind': kind, 'message_id': x['message_id']}
            if kind == 'task':
                c['text'] = _clip(x.get('text') or x.get('title'), 300)
                due = str(x.get('due') or '')
                c['due'] = due if DATE_RE.match(due) else None
            elif kind == 'note':
                c['text'] = _clip(x.get('text'), 1000)
            else:
                c['text'] = _clip(x.get('title') or x.get('text'), 200)
                d = str(x.get('date') or '')
                if not DATE_RE.match(d):
                    continue
                c['date'] = d
                t = str(x.get('time') or '')
                c['time'] = t if TIME_RE.match(t) else None
            if c['text']:
                out.append(c)
    return out[:60]


def scan(project, candidates, matcher, keep, today=None, since=None):
    """The scan itself, given Mail's index rows (newest first): → the new candidates with why they matched.
    keep(c) → (ok, reason) applies the left-out rules (private, protected workplace, scam, world)."""
    today = today or datetime.date.today()
    since = since or today - datetime.timedelta(days=DEFAULT_DAYS)
    out = []
    for c in candidates:
        try:
            day = datetime.date.fromisoformat(str(c.get('date') or '')[:10])
        except ValueError:
            continue
        if day < since:
            continue
        why = matcher(c.get('subject'), c.get('from_address'), c.get('message_id'))
        if not why:
            continue
        ok, _ = keep(c)
        if not ok:
            continue
        out.append({'account': c.get('account'), 'message_id': c.get('message_id'), 'subject': str(c.get('subject') or '')[:200],
                    'from': (c.get('from_name') or c.get('from_address') or '')[:120], 'address': str(c.get('from_address') or '').lower()[:200],
                    'date': c.get('date'), 'why': why[:3], 'thread': _thread(c.get('subject'))})
    return out


def nightly(projects, store, run_scan, today=None):
    """The nightly re-scan: active projects only, rules only, from the last scan on. → {pid: new candidates}."""
    out = {}
    for p in projects:
        if p.get('status') != 'active':
            continue
        e = store.entry(p['id'])
        if not e.get('last_scan'):                # never scanned by hand: the owner starts it
            continue
        try:
            since = datetime.date.fromisoformat(e['last_scan'][:10]) - datetime.timedelta(days=1)
        except ValueError:
            continue
        out[p['id']] = store.merge(p['id'], run_scan(p, since))
    return out
