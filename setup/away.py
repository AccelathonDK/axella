"""Back-from-away briefing: after an Away period or paused days (vacation, days off) of 2 days or more, the first
digest is one calm picture of what still matters (task "return-briefing", kind digest), plus "Sorted itself out"
with Archive all. Also on demand: "Catch me up since…" a date. Python 3.9.

Who decides what:
  - Python: when it comes (absence), the facts the run can't see itself (state/return-briefing.json, written just
    before the run), the "Sorted itself out" groups (after the run, from the digests written while away) and
    Archive all with its one Undo. Archive all only marks items handled in Axella – nothing moves in Mail.
  - The run (one Claude run, read-only like every digest): the "away" block's headline, "Still needs you" and
    "Coming up this week", the carried-over items with drafts, and the spoken version.

  absence(today, is_away, is_bridge)      → {'from', 'to', 'days'} for an absence that ended yesterday, or None.
                                            Away days: Away (ooo) or a paused day; days without digest slots
                                            (a weekend) bridge two away days but don't start or end an absence.
  digests_between(dir, a, b)              → regular digest names written from day a to day b (not urgent ones)
  sorted_out(items, state, keep_ids, now) → {'groups': [{'key', 'label', 'count', 'items'}], 'count'}
  Away(state_dir)                         → due(), mark_briefed(), archive(), undo(), add_to_digest()

state/away.json: {"briefed": {"<from>..<to>": iso}, "batches": {"<id>": {"ids": [...], "at": iso, "digest"}},
                  "lists": {"<briefing digest>": {"ids": [...], "hash": sha256}}}  – Python's own "Sorted itself out" list;
                  the digest's away.sorted (sorted_by "axella", sorted_hash) must match it, and Archive all uses only it
state/return-briefing.json: the facts for the run (see facts()).
"""
import datetime
import hashlib
import json
import os
import re
import threading
import uuid

MIN_DAYS = 2
MAX_LOOKBACK = 60
RESCAN_CAP = 14
FILE = 'away.json'
FACTS = 'return-briefing.json'
LOCK = threading.Lock()
GROUPS = (('answered', 'threads were answered or settled'), ('events', 'events have passed'),
          ('bulk', 'newsletters, notifications and FYIs'), ('calls', 'calls with messages already handled'))
OPEN = ('p0', 'p1', 'p2', 'open', 'wait')
CALLS = ('call', 'calls')


class Bad(Exception):
    pass


def _day(s):
    try:
        return datetime.date.fromisoformat(str(s or '')[:10])
    except ValueError:
        return None


def _dt(s):
    try:
        d = datetime.datetime.fromisoformat(str(s or '').replace('Z', '+00:00'))
    except ValueError:
        return None
    return d.astimezone().replace(tzinfo=None) if d.tzinfo else d


def absence(today, is_away, is_bridge, min_days=MIN_DAYS):
    """The absence that ended yesterday: walk back from yesterday over away days, bridging days without digests.
    Still away today (Away set, digests running): not yet."""
    if is_away(today):
        return None
    first = last = None
    d = today - datetime.timedelta(days=1)
    for _ in range(MAX_LOOKBACK):
        if is_away(d):
            first, last = d, last or d
        elif not is_bridge(d):
            break
        d -= datetime.timedelta(days=1)
    if not first or (last - first).days + 1 < min_days:
        return None
    return {'from': first.isoformat(), 'to': last.isoformat(), 'days': (last - first).days + 1}


def key_of(ab):
    return '%s..%s' % (ab['from'], ab['to'])


NAME = re.compile(r'^(\d{4}-\d{2}-\d{2})-\d{4}\.json$')


def digests_between(digests_dir, a, b):
    """Regular digests written from day a through day b (names YYYY-MM-DD-HHMM.json; urgent -p0 ones left out)."""
    try:
        names = sorted(os.listdir(digests_dir))
    except OSError:
        return []
    out = []
    for n in names:
        m = NAME.match(n)
        if m and a <= m.group(1) <= b:
            out.append(n)
    return out


def load_items(digests_dir, names):
    """Each item once (by id), its newest version."""
    by = {}
    for n in names:
        try:
            with open(os.path.join(digests_dir, n), encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        for it in (d.get('items') if isinstance(d, dict) and isinstance(d.get('items'), list) else []):
            if isinstance(it, dict) and it.get('id'):
                by[str(it['id'])] = it
    return by


def handled(st, now=None):
    if not isinstance(st, dict):
        return False
    if st.get('status') == 'done':
        return True
    if st.get('status') == 'snoozed':
        u = _dt(st.get('until'))
        return bool(u and u > (now or datetime.datetime.now()))
    return False


def _event_over(it, now):
    ev = it.get('event') if isinstance(it.get('event'), dict) else {}
    end = _dt(ev.get('end') or ev.get('start'))
    return bool(end and end < now)


def group_of(it, now):
    """Which "Sorted itself out" group an item belongs to, or None (it might still matter)."""
    sec, ch = it.get('section'), str(it.get('channel') or '')
    if sec == 'p0':
        return None                                     # urgent ones are never archived in bulk
    if ch in CALLS:
        return 'calls' if sec not in OPEN or sec == 'wait' else None
    if sec == 'cal':
        return 'events' if _event_over(it, now) else None
    if sec in ('p3', 'file'):
        return 'bulk'
    if sec in OPEN:
        return 'answered'                               # only with evidence – see sorted_out (last_ids)
    return None


def sorted_out(items, state, keep_ids=(), now=None, last_ids=None):
    """items: {id: item} from the digests written while away. keep_ids: what the briefing still shows (it matters).
    last_ids: what the newest regular digest written while away still carries. Handled items are left out.
    "Answered or settled" needs evidence: a later regular digest no longer carries the item (it is not in last_ids).
    An open item the briefing alone leaves out is not grouped – it stays open, never archived in bulk."""
    now = now or datetime.datetime.now()
    keep = {str(x) for x in keep_ids}
    last = {str(x) for x in last_ids} if last_ids is not None else set()
    groups = {k: [] for k, _ in GROUPS}
    for iid, it in items.items():
        if iid in keep or handled((state or {}).get(iid), now):
            continue
        g = group_of(it, now)
        if g == 'answered' and (last_ids is None or iid in last):
            continue
        if g:
            groups[g].append({'id': iid, 'headline': str(it.get('headline') or it.get('subject') or '')[:120],
                              'who': str(((it.get('from') or {}) if isinstance(it.get('from'), dict) else {}).get('name') or '')[:60],
                              'section': it.get('section')})
    out = [{'key': k, 'label': lb, 'count': len(groups[k]), 'items': groups[k][:300]} for k, lb in GROUPS if groups[k]]
    return {'groups': out, 'count': sum(g['count'] for g in out)}


def ids_hash(ids):
    return hashlib.sha256('\n'.join(sorted(str(i) for i in ids)).encode('utf-8')).hexdigest()


def list_ids(sorted_block):
    return [i['id'] for g in (sorted_block or {}).get('groups') or [] for i in g.get('items') or [] if i.get('id')]


def facts(ab, worlds, digests_dir, state, tasks, today, preps=(), trips=(), renewals=(), manual=False):
    """What the run reads (state/return-briefing.json): the absence, the digests written meanwhile (none → the
    fallback re-scan of the inboxes for the period, at most 14 days), how many things arrived, and the facts the run
    can't see itself – promises and bills due this week, meeting preps and trips this week, renewals soon."""
    names = digests_between(digests_dir, ab['from'], today.isoformat())
    items = load_items(digests_dir, names)
    week = today + datetime.timedelta(days=6)
    open_t = [t for t in tasks or [] if isinstance(t, dict) and t.get('status') != 'done'
              and (t.get('ctx') in (None, '') or t.get('ctx') in worlds)]
    due = lambda t: _day(t.get('due'))
    rescan_from = max(_day(ab['from']), today - datetime.timedelta(days=RESCAN_CAP))
    return {
        'absence': dict(ab, manual=bool(manual)), 'worlds': sorted(worlds), 'today': today.isoformat(),
        'digests': names, 'arrived': len(items),
        'fallback_rescan': None if names else {'from': rescan_from.isoformat(), 'to': today.isoformat()},
        'promises_due': [{'text': str(t.get('text') or '')[:120], 'due': str(t.get('due'))[:10], 'task_id': t.get('id')}
                         for t in open_t if (t.get('source') == 'promise' or (t.get('ref') or {}).get('kind') == 'promise')
                         and due(t) and due(t) <= week][:10],
        'bills_due': [{'payee': str((t.get('bill') or {}).get('payee') or t.get('text') or '')[:80], 'amount': (t.get('bill') or {}).get('amount'),
                       'currency': (t.get('bill') or {}).get('currency'), 'due': str(t.get('due'))[:10], 'task_id': t.get('id')}
                      for t in open_t if t.get('type') == 'bill' and due(t) and due(t) <= week][:10],
        'tasks_overdue': sum(1 for t in open_t if due(t) and due(t) < today),
        'preps_this_week': sorted(({'start': p.get('start'), 'event_id': (p.get('event') or {}).get('id')} for p in preps or []
                                   if _day(p.get('start')) and today <= _day(p.get('start')) <= week and (p.get('ctx') or 'work') in worlds),
                                  key=lambda x: str(x['start']))[:40],
        'trips_this_week': [{'title': str(t.get('title') or '')[:80], 'start': str(t.get('start'))[:10], 'end': str(t.get('end') or t.get('start'))[:10]}
                            for t in trips or [] if _day(t.get('start')) and _day(t.get('start')) <= week and (_day(t.get('end') or t.get('start')) or today) >= today
                            and (t.get('ctx') or 'private') in worlds][:5],
        'renewals_soon': [{'name': str(r.get('name') or '')[:80], 'date': str(r.get('date'))[:10]} for r in renewals or []
                          if _day(r.get('date')) and _day(r.get('date')) <= today + datetime.timedelta(days=30)][:5],
    }


def prompt_note(f):
    ab = f['absence']
    s = ('\n\nThis run is the BACK-FROM-AWAY BRIEFING for %s to %s (%d days%s). Read state/return-briefing.json (the Mac mini '
         'wrote it just now) before anything else and follow setup/local-tasks/return-briefing.md.'
         % (ab['from'], ab['to'], ab['days'], ', asked for with "Catch me up since…"' if ab.get('manual') else ''))
    if f.get('fallback_rescan'):
        s += (' No digests were written while away, so re-scan the mail inboxes from %s instead (step 3b).'
              % f['fallback_rescan']['from'])
    return s


class Away:
    def __init__(self, state_dir):
        self.state_dir = state_dir
        self.file = os.path.join(state_dir, FILE)

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        d.setdefault('briefed', {})
        d.setdefault('batches', {})
        d.setdefault('lists', {})
        return d

    def _save(self, d):
        d['briefed'] = dict(sorted(d['briefed'].items())[-50:])
        d['batches'] = dict(sorted(d['batches'].items(), key=lambda kv: kv[1].get('at', ''))[-20:])
        d['lists'] = dict(sorted(d['lists'].items())[-20:])
        tmp = '%s.%d.%d.tmp' % (self.file, os.getpid(), threading.get_ident())
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)

    def due(self, today, is_away, is_bridge):
        """The absence to brief now, once: None if there is none or it was briefed already."""
        ab = absence(today, is_away, is_bridge)
        if ab and key_of(ab) not in self.load()['briefed']:
            return ab
        return None

    def mark_briefed(self, ab):
        with LOCK:
            d = self.load()
            d['briefed'][key_of(ab)] = datetime.datetime.now().isoformat(timespec='seconds')
            self._save(d)

    def write_facts(self, f):
        tmp = os.path.join(self.state_dir, FACTS + '.tmp')
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(f, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(self.state_dir, FACTS))

    def read_facts(self):
        try:
            with open(os.path.join(self.state_dir, FACTS), encoding='utf-8') as f:
                d = json.load(f)
            return d if isinstance(d, dict) else None
        except (OSError, ValueError):
            return None

    def add_to_digest(self, digests_dir, name, state_fn, now=None):
        """After the briefing run: add "Sorted itself out" (deterministic) to its "away" block and mark the absence
        briefed. True when this digest is a briefing – no push for it (calm)."""
        import digestfile
        f = self.read_facts()
        done = {}

        mine = self.load()['lists'].get(name)

        def change(dg):
            if not isinstance(dg, dict) or not isinstance(dg.get('away'), dict):
                return False, False
            w = dg['away']
            if mine and w.get('sorted_by') == 'axella' and w.get('sorted_hash') == mine.get('hash') \
                    and ids_hash(list_ids(w.get('sorted'))) == mine.get('hash'):
                return False, True                      # Python's own list, already added
            # whatever the run (or anyone) wrote as "sorted" is thrown away: only Python makes this list
            for k in ('sorted', 'sorted_by', 'sorted_hash'):
                w.pop(k, None)
            ab = (f or {}).get('absence') or {}
            names = [n for n in (f or {}).get('digests') or [] if n != name]
            items = load_items(digests_dir, names)
            last = [n for n in names if NAME.match(n)][-1:]
            last_ids = set(load_items(digests_dir, last)) if last else set()
            keep = {str(i.get('id')) for i in dg.get('items') or [] if isinstance(i, dict)}
            so = sorted_out(items, state_fn(), keep, now, last_ids=last_ids)
            h = ids_hash(list_ids(so))
            w['sorted'], w['sorted_by'], w['sorted_hash'] = so, 'axella', h
            w['arrived'] = (f or {}).get('arrived') if (f or {}).get('arrived') is not None else w.get('arrived')
            w['absence'] = {k: ab.get(k) for k in ('from', 'to', 'days', 'manual')}
            done.update(ab=ab, ids=list_ids(so), hash=h)
            return True, True
        res = digestfile.update(os.path.join(digests_dir, name), change)
        if 'hash' in done:
            with LOCK:
                d = self.load()
                d['lists'][name] = {'ids': done['ids'][:2000], 'hash': done['hash']}
                self._save(d)
        if done.get('ab', {}).get('from'):
            self.mark_briefed(done['ab'])
        return bool(res)

    def stored_ids(self, name):
        """Python's own "Sorted itself out" ids for this briefing (state/away.json), or [] – Archive all uses only these."""
        x = self.load()['lists'].get(name) or {}
        ids = [str(i) for i in x.get('ids') or []]
        return ids if ids and ids_hash(ids) == x.get('hash') else []

    def group_ids(self, name, keep=()):
        """Archive all's ids: Python's stored list for this briefing, minus what you kept back – never ids read from
        the digest file."""
        keep = {str(x) for x in keep}
        return [i for i in self.stored_ids(name) if i not in keep]

    def archive(self, digest, ids):
        """Remember one Archive all (its item ids) for the one-tap Undo; returns the batch id."""
        with LOCK:
            d = self.load()
            bid = uuid.uuid4().hex[:12]
            d['batches'][bid] = {'ids': list(ids)[:2000], 'at': datetime.datetime.now().isoformat(timespec='seconds'), 'digest': digest}
            self._save(d)
            return bid

    def take_batch(self, bid):
        with LOCK:
            d = self.load()
            b = d['batches'].pop(str(bid or ''), None)
            if not b:
                raise Bad('nothing to undo')
            self._save(d)
            return b
