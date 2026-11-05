"""People view and keep in touch (feature pack §2a–b, part 2 #4). Everything here is local: nothing is sent to Claude.

A person is a Contacts card (contacts_book.Book.overview) – their e-mails and phone numbers join their items across
streams (mail, iMessage/SMS, WhatsApp, Signal), calls and your replies sent from Axella. A correspondent who is only in
your mail has the id "mail:<address>".

The page (view): header (name, company, world, last contact per channel), open between you (to answer, waiting on
them, your promises), meetings (preps they're invited to), timeline (newest first) and your own notes.
A private contact shows metadata only: channel and time, never a title or a snippet.
"Last contact" also uses the times the commitments scan already reads (Mail's index – sent and received – Messages,
WhatsApp and Signal), passed in as Index.extra, so mail you wrote in Mail itself counts too.

Keep in touch: you pick a rhythm (every 2 weeks, month or quarter). When it has passed with no contact in any channel,
one private-world digest gets ONE discreet line ("It's been five weeks since you spoke to Robin.") – at most one per
day, the same person at most once a week, never a private contact (digests are read by later runs), and the push
watcher adds it deterministically (the run is not involved). No streaks, no scores.

state/keep-in-touch.json: {"people": {"<person id>": {"every": 14|30|91, "since": "YYYY-MM-DD", "mentioned": "YYYY-MM-DD"|null}},
                           "last_line": "YYYY-MM-DD"|null}
state/people-notes.json:  {"<person id>": {"text": "…", "updated": "<iso>"}}
Both files are on the scheduler's SECRETS list: no Claude run reads your notes or who you keep in touch with.
Python 3.9.
"""
import datetime
import json
import os
import re
import threading

import contacts_book

LOCK = threading.Lock()
RHYTHMS = {14: 'every 2 weeks', 30: 'every month', 91: 'every quarter'}
NOTE_MAX = 2000
REPLIES = ('reply_send', 'sms_send', 'mail_send')      # your replies sent from Axella – contact too
ANSWER = ('p0', 'p1', 'p2', 'open')                   # digest sections that mean "to answer"
HANDLED = ('done', 'file', 'trash') + REPLIES
PID_RE = re.compile(r'^[\w:.@+\'%-]{1,160}$')
WORDS = ('zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve')


class Bad(Exception):
    pass


def _key(raw):
    """One identity key: a lower-case address, or a phone number as +digits."""
    s = str(raw or '').strip()
    if '@' in s:
        return s.lower()
    return contacts_book.phone(s)


def keys_of(p):
    out = set()
    for v in list(p.get('emails') or []) + list(p.get('mail_only') or []) + list(p.get('phones') or []):
        k = _key(v.get('value') if isinstance(v, dict) else v)
        if k:
            out.add(k)
    return out


def pid_of(p):
    if p.get('id'):
        return str(p['id'])
    em = [e for e in (p.get('emails') or []) if e]
    return 'mail:' + str(em[0]).lower() if em else ''


def find(people, pid):
    pid = str(pid or '')
    return next((p for p in people or [] if pid_of(p) == pid), None)


def _name_key(n):
    n = ' '.join(str(n or '').lower().split())
    return n if len(n.split()) >= 2 else ''           # only a full name is safe to match a message without an address


def _day(s):
    try:
        return datetime.date.fromisoformat(str(s or '')[:10])
    except ValueError:
        return None


def _ok(result):
    r = str(result or '')
    return r.split(':')[0] in ('ok', 'done', 'already') or r.startswith('sent')


class Index:
    """Everything that says "you and this person were in touch", read once from the store and keyed by identity."""

    def __init__(self, store, days=400, today=None):
        today = today or datetime.date.today()
        since = (today - datetime.timedelta(days=days)).isoformat()
        self.by_key, self.by_name, self.calls, self.out = {}, {}, {}, {}
        self.extra = {}       # {key: {channel: iso}} – Mail's index, Messages, WhatsApp, Signal (times only, set by the caller)
        with store._db() as db:
            rows = [dict(r) for r in db.execute(
                "SELECT id, digest, generated, first_seen, section, channel, account, context, from_name, from_address, subject, "
                "headline, detail FROM item_latest WHERE section NOT IN ('file', 'cal') AND substr(generated,1,10) >= ?", (since,)).fetchall()]
            calls = [dict(r) for r in db.execute("SELECT id, started, duration_s, number FROM calls WHERE substr(started,1,10) >= ?",
                                                 (since,)).fetchall()]
            acts = [dict(r) for r in db.execute(
                "SELECT at, action, result, item FROM actions WHERE substr(at,1,10) >= ? AND item IS NOT NULL", (since,)).fetchall()]
        self.rows = {r['id']: r for r in rows}
        for r in rows:
            k = _key(r['from_address'])
            if k:
                self.by_key.setdefault(k, []).append(r)
            elif _name_key(r['from_name']):
                self.by_name.setdefault(_name_key(r['from_name']), []).append(r)
        for c in calls:
            k = _key(c['number'])
            if k:
                self.calls.setdefault(k, []).append(c)
        self.handled = set()
        for a in acts:
            if a['action'] in HANDLED and _ok(a['result']):
                self.handled.add(a['item'])
            if a['action'] in REPLIES and _ok(a['result']) and a['item'] in self.rows:
                self.out.setdefault(a['item'], []).append(a['at'])

    def items_of(self, p, unique_name=True):
        seen, out = set(), []
        lists = [self.by_key.get(k, []) for k in keys_of(p)]
        if unique_name and _name_key(p.get('name')):
            lists.append(self.by_name.get(_name_key(p.get('name')), []))
        for lst in lists:
            for r in lst:
                if r['id'] not in seen:
                    seen.add(r['id'])
                    out.append(r)
        return out

    def calls_of(self, p):
        return [c for k in keys_of(p) for c in self.calls.get(k, [])]

    def last_contact(self, p, unique_name=True):
        """{channel: latest iso time} – their messages, your replies from Axella and calls."""
        last = {}

        def put(ch, at):
            if at and (ch not in last or str(at) > last[ch]):
                last[ch] = str(at)
        for r in self.items_of(p, unique_name):
            put(r['channel'] or 'mail', r['first_seen'] or r['generated'])
            for at in self.out.get(r['id'], []):
                put(r['channel'] or 'mail', at)
        for c in self.calls_of(p):
            put('call', c['started'])
        for k in keys_of(p):
            for ch, at in (self.extra.get(k) or {}).items():
                put(ch, at)
        return last


def ambiguous_names(people):
    seen, dup = set(), set()
    for p in people or []:
        n = _name_key(p.get('name'))
        if n in seen:
            dup.add(n)
        seen.add(n)
    return dup


def _world(store, rows):
    world = store._world()
    n = {'work': 0, 'private': 0}
    for r in rows:
        w = world(r['id'], r['from_address'], r['context'], r['account'])
        if w in n:
            n[w] += 1
    return None if not rows else 'work' if n['work'] > n['private'] else 'private'


def view(p, store, idx, digest_items=(), debt=(), promises=(), tasks=(), preps=(), note=None, keep=None, today=None,
         unique_name=True, timeline_n=40):
    """The People page for one person (owner only). Private contacts: metadata only."""
    today = today or datetime.date.today()
    private = bool(p.get('private'))
    keys = keys_of(p)
    rows = idx.items_of(p, unique_name)
    rows.sort(key=lambda r: str(r['first_seen'] or r['generated']), reverse=True)

    def mine(i):
        fr = i.get('from') if isinstance(i.get('from'), dict) else {}
        k = _key(fr.get('address') or i.get('from_address'))
        if k:
            return k in keys
        nk = _name_key(fr.get('name') or i.get('from_name'))
        return bool(unique_name and nk and nk == _name_key(p.get('name')))

    def line(i):
        o = {'id': i.get('id'), 'channel': i.get('channel') or 'mail', 'at': i.get('first_seen') or i.get('generated')}
        if not private:
            o['title'] = str(i.get('headline') or i.get('subject') or '')[:160]
        return o
    to_answer = [line(i) for i in digest_items if i.get('section') in ANSWER and mine(i) and i.get('id') not in idx.handled]
    waiting = [line(i) for i in digest_items if i.get('section') == 'wait' and mine(i) and i.get('id') not in idx.handled]
    owed = [{'days': d.get('days'), 'channel': d.get('channel') or 'mail'} for d in debt if _key(d.get('who')) in keys]
    proms = []
    for x in promises:
        if x.get('status') in ('suggested', 'added') and _key((x.get('person') or {}).get('address')) in keys:
            proms.append({'id': x.get('id'), 'text': None if x.get('protected') else str(x.get('text') or '')[:200],
                          'due': x.get('due'), 'status': x.get('status'), 'task_id': x.get('task_id')})
    done_tasks = {x.get('task_id') for x in proms}
    for t in tasks:
        ref = t.get('ref') or {}
        if t.get('status') != 'done' and t.get('id') not in done_tasks and _key((ref.get('person') or {}).get('address')) in keys:
            proms.append({'id': None, 'text': str(t.get('text') or '')[:200], 'due': t.get('due'), 'status': 'added', 'task_id': t.get('id')})
    meets = []
    for m in preps:
        if any(_key(a.get('email')) in keys for a in m.get('attendees') or [] if isinstance(a, dict)):
            meets.append({'id': m.get('id'), 'title': str(m.get('title') or '')[:120], 'start': m.get('start'), 'status': m.get('status')})
    now = today.isoformat()
    meets.sort(key=lambda m: str(m.get('start') or ''))
    timeline = []
    for r in rows[:timeline_n]:
        e = {'id': r['id'], 'digest': r['digest'], 'channel': r['channel'] or 'mail', 'at': r['first_seen'] or r['generated'], 'dir': 'in'}
        if not private:
            e['title'] = str(r['subject'] or r['headline'] or '')[:160]
            e['snippet'] = str(r['detail'] or '')[:200]
        timeline.append(e)
        for at in idx.out.get(r['id'], []):
            timeline.append({'id': r['id'], 'digest': r['digest'], 'channel': r['channel'] or 'mail', 'at': at, 'dir': 'out'})
    for c in idx.calls_of(p)[:20]:
        timeline.append({'id': c['id'], 'channel': 'call', 'at': c['started'], 'dir': 'call', 'minutes': round((c['duration_s'] or 0) / 60)})
    timeline.sort(key=lambda e: str(e['at'] or ''), reverse=True)
    last = idx.last_contact(p, unique_name)
    return {
        'id': pid_of(p), 'name': p.get('name'), 'first': p.get('first'), 'company': p.get('company'),
        'emails': sorted({str(e).lower() for e in (p.get('emails') or []) + (p.get('mail_only') or [])}),
        'phones': [x.get('value') if isinstance(x, dict) else x for x in p.get('phones') or []],
        'private': private, 'vip': bool(p.get('vip')), 'in_contacts': bool(p.get('id')), 'birthday': p.get('birthday'),
        'world': _world(store, rows), 'last_contact': last,
        'open': {'to_answer': to_answer[:20], 'waiting': waiting[:20], 'reply_owed': owed[:1], 'promises': proms[:20]},
        'meetings': {'upcoming': [m for m in meets if str(m.get('start') or '')[:10] >= now][:10],
                     'past': [m for m in reversed(meets) if str(m.get('start') or '')[:10] < now][:10]},
        'timeline': timeline[:timeline_n], 'note': note, 'keep': keep,
    }


def last_any(last):
    return max(last.values())[:10] if last else None


def span(days):
    """'12 days', 'five weeks', 'three months' – how long since you spoke, in words a person would use."""
    if days < 14:
        return '%d days' % days
    if days < 63:
        w = days // 7
        return '%s weeks' % (WORDS[w] if w < len(WORDS) else w)
    m = days // 30
    return '%s months' % (WORDS[m] if m < len(WORDS) else m) if m < 24 else 'over a year'


def line(name, days):
    return "It's been %s since you spoke to %s." % (span(days), name)


class People:
    def __init__(self, state_dir):
        self.keep_file = os.path.join(state_dir, 'keep-in-touch.json')
        self.notes_file = os.path.join(state_dir, 'people-notes.json')

    @staticmethod
    def _read(path, default):
        try:
            with open(path, encoding='utf-8') as f:
                d = json.load(f)
            return d if isinstance(d, dict) else default
        except (OSError, ValueError):
            return default

    @staticmethod
    def _write(path, d):
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)

    def load_keep(self):
        d = self._read(self.keep_file, {})
        ppl = d.get('people') if isinstance(d.get('people'), dict) else {}
        return {'people': {k: v for k, v in ppl.items() if isinstance(v, dict) and v.get('every') in RHYTHMS},
                'last_line': d.get('last_line')}

    def keep(self):
        return self.load_keep()['people']

    def set_keep(self, pid, every, today=None):
        pid = self._pid(pid)
        if every is not None:
            try:
                every = int(every)
            except (TypeError, ValueError):
                raise Bad('every 14, 30 or 91 days')
            if every not in RHYTHMS:
                raise Bad('every 14, 30 or 91 days')
        with LOCK:
            d = self.load_keep()
            if every is None:
                d['people'].pop(pid, None)
            else:
                old = d['people'].get(pid) or {}
                d['people'][pid] = {'every': every, 'since': old.get('since') or (today or datetime.date.today()).isoformat(),
                                    'mentioned': old.get('mentioned')}
            self._write(self.keep_file, d)
            return d['people'].get(pid)

    def notes(self):
        return {k: v for k, v in self._read(self.notes_file, {}).items() if isinstance(v, dict)}

    def set_note(self, pid, text, now=None):
        pid = self._pid(pid)
        text = str(text or '').replace('\r', '').strip()[:NOTE_MAX]
        with LOCK:
            d = self.notes()
            if text:
                d[pid] = {'text': text, 'updated': now or datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
            else:
                d.pop(pid, None)
            self._write(self.notes_file, d)
            return d.get(pid)

    @staticmethod
    def _pid(pid):
        pid = str(pid or '').strip()
        if not PID_RE.match(pid):
            raise Bad('unknown person')
        return pid

    def due(self, people, idx, today=None):
        """Keep-in-touch people whose rhythm has passed with no contact: [{id, name, days, every, private, mentioned}],
        most overdue (against their rhythm) first."""
        today = today or datetime.date.today()
        dup = ambiguous_names(people)
        out = []
        for pid, k in self.keep().items():
            p = find(people, pid)
            if not p:
                continue
            last = last_any(idx.last_contact(p, _name_key(p.get('name')) not in dup))
            known = [x for x in (_day(last), _day(k.get('since'))) if x]
            ref = max(known) if known else today
            days = (today - ref).days
            if days >= k['every']:
                out.append({'id': pid, 'name': (p.get('first') or str(p.get('name') or '').split(' ')[0]).strip()[:60],
                            'days': days, 'every': k['every'], 'private': bool(p.get('private')), 'mentioned': k.get('mentioned'),
                            'last': last})
        out.sort(key=lambda x: -x['days'] / x['every'])
        return out

    def pick_line(self, due, today=None):
        """The one person for today's digest line, or None: never a private contact, the same person at most once a week,
        at most one line a day."""
        today = today or datetime.date.today()
        if self.load_keep().get('last_line') == today.isoformat():
            return None
        for x in due:
            m = _day(x.get('mentioned'))
            if x['private'] or not x['name'] or (m and (today - m).days < 7):
                continue
            return x
        return None

    def mark_line(self, pid, today=None):
        today = (today or datetime.date.today()).isoformat()
        with LOCK:
            d = self.load_keep()
            if pid in d['people']:
                d['people'][pid]['mentioned'] = today
            d['last_line'] = today
            self._write(self.keep_file, d)

    def add_to_digest(self, digests_dir, name, due_fn, today=None):
        """One discreet keep-in-touch line in a private-world regular digest (deterministic, through digestfile.update).
        due_fn() → the due list (computed only when this digest can take a line). Returns the person id or None."""
        import digestfile
        from recurring import add_spoken
        if not re.match(r'^\d{4}-\d{2}-\d{2}-\d{4}\.json$', name):
            return None
        today = today or _day(name[:10]) or datetime.date.today()
        if self.load_keep().get('last_line') == today.isoformat() or not self.keep():
            return None
        picked = {}

        def change(dg):
            if not isinstance(dg, dict) or not isinstance(dg.get('items'), list) or dg.get('keep_in_touch') is not None:
                return False, None
            sc = dg.get('scope')
            if isinstance(sc, list) and sc and 'private' not in sc:
                return False, None                       # a work-only digest: no keep-in-touch line
            x = self.pick_line(due_fn(), today)
            dg['keep_in_touch'] = x['id'] if x else ''
            if x:
                text = line(x['name'], x['days'])
                dg['items'].append({'id': '%s-p3-keepintouch' % name[:-5].replace('-', '')[:12], 'section': 'p3', 'channel': 'people',
                                    'context': 'private', 'topic': 'Keep in touch', 'headline': text,
                                    'detail': 'Open their page in People – Draft a note is there when you want it.',
                                    'link': 'person', 'person': x['id'], 'first_seen': dg.get('generated') or ''})
                add_spoken(digests_dir, name, dg, text)
                picked['x'] = x
            return True, x['id'] if x else None
        res = digestfile.update(os.path.join(digests_dir, name), change)
        if picked.get('x'):
            self.mark_line(picked['x']['id'], today)
        return res
