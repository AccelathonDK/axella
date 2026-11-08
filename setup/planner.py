"""Targets and Now · Next · Later (claude/dev-request-targets-now-next-later.md): project working states, people on a
project, targets with steps, and a suggested day and week. Rules only, on the Mac mini – no Claude run reads or writes
any of it, nothing is sent, and nothing changes without the owner's tap. "Hold" is the one calendar change, and it
goes through the existing block_hold (cal_add, with its backup and undo).

state/planner.json (chmod 600, on the scheduler's SECRETS list – who is on which project, and your plans):
  {"settings": {"enabled": true, "buffer": 10, "idle_weeks": 3},
   "projects": {<pid>: {"state": "active|waiting|paused|running|done", "since": iso,
                        "waiting_for": {"kind": "person|item|task", "ref", "label"} | null, "paused_until": "YYYY-MM-DD" | null,
                        "people": [{"key", "pid", "name", "role", "star", "source": "manual|suggested", "why", "added"}],
                        "people_not": [key], "auto_removed": [key],
                        "targets": [{"id", "kind": "date|period|idea", "title", "done_means", "date", "from", "to",
                                     "status": "open|done", "brief", "steps": [{"id", "text", "mins", "day", "done", "src", "waits"}],
                                     "questions": [{"id", "text", "done"}], "go": [...], "experiments": [{"id", "text", "mins", "done"}],
                                     "signals_not": [url]}],
                        "touched": iso}},
   "days": {"YYYY-MM-DD": {"focus": [pid], "none": bool, "status": {<item key>: "done|notnow"}, "swap": [<item key>]}},
   "dismissed": {<suggestion key>: iso}, "notnow": {<item key>: n}, "moved": {<item key>: "YYYY-MM-DD"},
   "heads_up": {<key>: "keep|moved"}, "checks": {<target id>: "YYYY-MM"}}

States and focus: only Active projects are ever suggested as focus. Axella never changes a state; it suggests
(back from waiting, resume after a pause, pause after weeks without activity, done when every target is met).
Python 3.9.
"""
import datetime
import json
import os
import re
import secrets
import threading

LOCK = threading.Lock()
STATES = ('active', 'waiting', 'paused', 'running', 'done')
KINDS = ('date', 'period', 'idea')
LISTS = {'steps': 'text', 'questions': 'text', 'go': 'text', 'experiments': 'text'}
DEFAULTS = {'enabled': True, 'buffer': 10, 'idle_weeks': 3}
BUFFERS = (0, 5, 10, 15, 20, 30)
STEP_MINS = 45                         # a step with no estimate
MIN_SLOT = 15                          # a free stretch shorter than this is not offered
SPRINT_MINS = 15
TASK_MINS = 20
PRIVATE_HOURS = {'weekday': ('18:00', '21:00'), 'weekend': ('09:00', '17:00')}
MAX_PEOPLE = 40
MAX_TARGETS = 12
MAX_ENTRIES = 40
WORDS_RE = re.compile(r"[a-zæøåäöüé0-9]{4,}", re.I)
STOP = {'that', 'this', 'with', 'from', 'have', 'what', 'when', 'which', 'there', 'their', 'about', 'they', 'would',
        'could', 'should', 'into', 'than', 'then', 'them', 'will', 'your', 'been', 'were', 'does', 'more', 'some',
        'enough', 'people', 'want', 'clear'}


class Bad(Exception):
    pass


def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def _id(prefix):
    return prefix + secrets.token_hex(4)


def _clip(v, n):
    return re.sub(r'[\x00-\x1f\x7f]', ' ', str(v or '')).strip()[:n]


def _day(s):
    try:
        return datetime.date.fromisoformat(str(s or '')[:10])
    except ValueError:
        return None


def _hm(s):
    h, m = str(s).split(':')[:2]
    return int(h), int(m)


def person_key(raw):
    """One key per person: a lowercased e-mail address, a phone number's digits (+), or a People id."""
    s = str(raw or '').strip()
    if '@' in s:
        return s.lower()[:200]
    d = re.sub(r'[^\d+]', '', s)
    if len(re.sub(r'\D', '', d)) >= 6 and not s.startswith(('mail:', 'c:')):
        return d[:30]
    return s[:160]


# ---------------------------------------------------------------- storage
class Planner:
    def __init__(self, state_dir):
        self.file = os.path.join(state_dir, 'planner.json')

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        d['settings'] = dict(DEFAULTS, **(d.get('settings') if isinstance(d.get('settings'), dict) else {}))
        for k in ('projects', 'days', 'dismissed', 'notnow', 'moved', 'heads_up', 'checks'):
            if not isinstance(d.get(k), dict):
                d[k] = {}
        return d

    def _save(self, d):
        cut = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
        d['days'] = {k: v for k, v in d['days'].items() if k >= cut}
        d['dismissed'] = dict(sorted(d['dismissed'].items(), key=lambda kv: kv[1])[-400:])
        d['notnow'] = dict(list(d['notnow'].items())[-400:])
        tmp = '%s.%d.%d.tmp' % (self.file, os.getpid(), threading.get_ident())
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.file)

    @staticmethod
    def entry(d, pid):
        e = d['projects'].setdefault(pid, {})
        e.setdefault('state', 'active')
        for k in ('people', 'people_not', 'auto_removed', 'targets'):
            if not isinstance(e.get(k), list):
                e[k] = []
        return e

    def enabled(self):
        return bool(self.load()['settings'].get('enabled', True))

    # ---------------------------------------------------------------- actions
    def action(self, action, p, project_ids=(), today=None):
        """Every change is the owner's own tap. project_ids: the projects that exist (active ones for states)."""
        today = today or datetime.date.today()
        with LOCK:
            d = self.load()
            if action == 'plan_settings':
                s = d['settings']
                if 'enabled' in p:
                    s['enabled'] = bool(p['enabled'])
                if 'buffer' in p:
                    try:
                        b = int(p['buffer'])
                    except (TypeError, ValueError):
                        raise Bad('the buffer in minutes')
                    if b not in BUFFERS:
                        raise Bad('0, 5, 10, 15, 20 or 30 minutes')
                    s['buffer'] = b
                self._save(d)
                return dict(s)
            if action in ('plan_focus', 'plan_none', 'plan_item', 'plan_swap', 'plan_suggestion', 'plan_heads_up', 'plan_check'):
                r = self._day_action(d, action, p, project_ids, today)
                self._save(d)
                return r
            pid = _clip(p.get('id'), 100)
            if pid not in project_ids:
                raise Bad('project not found')
            e = self.entry(d, pid)
            if action == 'project_state':
                r = self._state(e, p, today)
            elif action.startswith('project_person_'):
                r = self._person(e, action, p)
            elif action.startswith('project_target_') or action.startswith('project_entry_'):
                r = self._target(e, action, p)
            else:
                raise Bad('unknown action')
            e['touched'] = _now()
            self._save(d)
            return r

    @staticmethod
    def _state(e, p, today):
        st = str(p.get('state') or '')
        if st not in STATES:
            raise Bad('Active, Waiting, Paused, Running or Done')
        e['state'] = st
        e['since'] = _now()                        # a new cause each time: a dismissed suggestion doesn't hide the next
        e.pop('waiting_for', None)
        e.pop('paused_until', None)
        if st == 'waiting' and isinstance(p.get('waiting_for'), dict):
            w = p['waiting_for']
            kind = str(w.get('kind') or '')
            if kind not in ('person', 'item', 'task'):
                raise Bad('waiting for a person, a Waiting item or a task')
            ref = person_key(w.get('ref')) if kind == 'person' else _clip(w.get('ref'), 200)
            if not ref:
                raise Bad('who or what is it waiting for?')
            e['waiting_for'] = {'kind': kind, 'ref': ref, 'label': _clip(w.get('label'), 120) or ref}
        if st == 'paused' and p.get('until'):
            u = _day(p.get('until'))
            if not u or u <= today:
                raise Bad('a date after today')
            e['paused_until'] = u.isoformat()
        if st == 'done':
            for t in e['targets']:
                t['status'] = 'done'
        return {'state': st}

    @staticmethod
    def _person(e, action, p):
        key = person_key(p.get('key'))
        if not key:
            raise Bad('which person?')
        ppl = e['people']
        cur = next((x for x in ppl if x.get('key') == key), None)
        if action == 'project_person_add':          # manual from Contacts, or a suggestion / auto person you keep
            if cur:
                return {'key': key}
            if len(ppl) >= MAX_PEOPLE:
                raise Bad('at most %d people on a project' % MAX_PEOPLE)
            src = 'suggested' if p.get('source') == 'suggested' else 'manual'
            ppl.append({'key': key, 'pid': _clip(p.get('pid'), 160) or None, 'name': _clip(p.get('name'), 120) or key,
                        'role': _clip(p.get('role'), 60), 'star': False, 'source': src, 'why': _clip(p.get('why'), 160), 'added': _now()})
            e['people_not'] = [k for k in e['people_not'] if k != key]
            e['auto_removed'] = [k for k in e['auto_removed'] if k != key]
            return {'key': key}
        if action == 'project_person_update':
            if not cur:                                # an auto person you give a role or a star: kept as yours
                cur = {'key': key, 'pid': _clip(p.get('pid'), 160) or None, 'name': _clip(p.get('name'), 120) or key, 'role': '',
                       'star': False, 'source': 'auto', 'why': _clip(p.get('why'), 160), 'added': _now()}
                ppl.append(cur)
            if 'role' in p:
                cur['role'] = _clip(p.get('role'), 60)
            if 'star' in p:
                if p['star'] and sum(1 for x in ppl if x.get('star') and x is not cur) >= 2:
                    raise Bad('one or two key people')
                cur['star'] = bool(p['star'])
            return {'key': key}
        if action == 'project_person_remove':      # off this project; an auto person never comes back by itself
            e['people'] = [x for x in ppl if x.get('key') != key]
            if key not in e['auto_removed']:
                e['auto_removed'].append(key)
            return {'key': key}
        if action == 'project_person_not':         # "Not for this project": never asked again
            if key not in e['people_not']:
                e['people_not'].append(key)
            return {'key': key}
        raise Bad('unknown action')

    @staticmethod
    def _target(e, action, p):
        ts = e['targets']
        if action == 'project_target_add':
            kind = str(p.get('kind') or '')
            if kind not in KINDS:
                raise Bad('Date, Period or Idea')
            if len(ts) >= MAX_TARGETS:
                raise Bad('at most %d targets' % MAX_TARGETS)
            t = {'id': _id('t'), 'kind': kind, 'status': 'open', 'steps': [], 'questions': [], 'go': [], 'experiments': [], 'signals_not': []}
            Planner._target_fields(t, p, new=True)
            ts.append(t)
            return {'id': t['id']}
        t = next((x for x in ts if x.get('id') == p.get('target')), None)
        if not t:
            raise Bad('target not found')
        for k in LISTS:
            t.setdefault(k, [])
        if action == 'project_target_update':
            Planner._target_fields(t, p)
            if 'status' in p:
                if p['status'] not in ('open', 'done'):
                    raise Bad('open or done')
                t['status'] = p['status']
            return {'id': t['id']}
        if action == 'project_target_delete':
            e['targets'] = [x for x in ts if x is not t]
            return {'id': t['id']}
        if action == 'project_target_signal_not':
            u = _clip(p.get('url'), 500)
            t.setdefault('signals_not', [])
            if u and u not in t['signals_not']:
                t['signals_not'] = (t['signals_not'] + [u])[-100:]
            return {'id': t['id']}
        lst = str(p.get('list') or '')
        if lst not in LISTS or (lst in ('steps',) and t['kind'] == 'idea') or (lst in ('questions', 'go', 'experiments') and t['kind'] != 'idea'):
            raise Bad('not on this kind of target')
        L = t[lst]
        if action == 'project_entry_add':
            if len(L) >= MAX_ENTRIES:
                raise Bad('at most %d' % MAX_ENTRIES)
            x = {'id': _id('s'), 'text': _clip(p.get('text'), 200), 'done': False}
            if not x['text']:
                raise Bad('what is it?')
            Planner._entry_fields(x, p, lst)
            if p.get('src'):
                x['src'] = _clip(p.get('src'), 60)
            L.append(x)
            return {'id': x['id']}
        x = next((y for y in L if y.get('id') == p.get('entry')), None)
        if action == 'project_entry_reorder':
            ids = p.get('ids')
            if not isinstance(ids, list) or sorted(ids) != sorted(y['id'] for y in L):
                raise Bad('the whole list, in the new order')
            pos = {i: n for n, i in enumerate(ids)}
            L.sort(key=lambda y: pos[y['id']])
            return {'ok': True}
        if not x:
            raise Bad('not found')
        if action == 'project_entry_update':
            if 'text' in p:
                x['text'] = _clip(p.get('text'), 200) or x['text']
            if 'done' in p:
                x['done'] = bool(p['done'])
                if x['done']:
                    x['done_at'] = _now()
                else:
                    x.pop('done_at', None)
            Planner._entry_fields(x, p, lst)
            return {'id': x['id']}
        if action == 'project_entry_delete':
            t[lst] = [y for y in L if y is not x]
            return {'id': x['id']}
        raise Bad('unknown action')

    @staticmethod
    def _target_fields(t, p, new=False):
        if new or 'title' in p:
            t['title'] = _clip(p.get('title'), 120)
            if not t['title']:
                raise Bad('name the target')
        if 'done_means' in p or new:
            t['done_means'] = _clip(p.get('done_means'), 400)
        if t['kind'] == 'date' and (new or 'date' in p):
            dd = _day(p.get('date'))
            if not dd:
                raise Bad('the date it is done by')
            t['date'] = dd.isoformat()
        if t['kind'] == 'period' and (new or 'from' in p or 'to' in p):
            a, b = _day(p.get('from', t.get('from'))), _day(p.get('to', t.get('to')))
            if not a or not b or b < a:
                raise Bad('a window: from and to')
            t['from'], t['to'] = a.isoformat(), b.isoformat()
        if t['kind'] == 'idea' and 'brief' in p:
            b = _clip(p.get('brief'), 40)
            t['brief'] = b if re.match(r'^[a-z0-9-]{1,40}$', b) else None

    @staticmethod
    def _entry_fields(x, p, lst):
        if lst in ('steps', 'experiments') and 'mins' in p:
            try:
                m = int(p['mins']) if p['mins'] not in (None, '') else None
            except (TypeError, ValueError):
                raise Bad('minutes')
            if m is not None and not 5 <= m <= 8 * 60:
                raise Bad('5 minutes to 8 hours')
            x['mins'] = m
        if lst == 'steps' and 'day' in p:
            dd = _day(p.get('day')) if p.get('day') else None
            x['day'] = dd.isoformat() if dd else None
        if lst == 'steps' and 'waits' in p:
            w = person_key(p.get('waits')) if p.get('waits') else None
            x['waits'] = w or None
            x['waits_label'] = _clip(p.get('waits_label'), 80) or None if w else None

    # ---------------------------------------------------------------- the day
    def _day_action(self, d, action, p, project_ids, today):
        day = _day(p.get('date')) or today
        dd = d['days'].setdefault(day.isoformat(), {})
        dd.setdefault('status', {})
        dd.setdefault('swap', [])
        if action == 'plan_focus':                 # "Plan my day" with these projects (the tap is the capacity signal)
            ids = p.get('projects')
            if not isinstance(ids, list) or not ids or len(ids) > 3 or any(i not in project_ids for i in ids):
                raise Bad('pick one to three active projects')
            act = {pid for pid in project_ids if self.entry(d, pid).get('state', 'active') == 'active'}
            if any(i not in act for i in ids):
                raise Bad('only Active projects can be today\'s focus')
            dd['focus'], dd['none'] = list(dict.fromkeys(ids)), False
            return {'focus': dd['focus']}
        if action == 'plan_none':                  # None today: an empty plan, no nagging
            dd['focus'], dd['none'] = [], bool(p.get('none', True))
            return {'none': dd['none']}
        key = _clip(p.get('key'), 300)
        if action == 'plan_item':
            how = p.get('status')
            if how not in ('done', 'notnow', None):
                raise Bad('done or not now')
            if how:
                dd['status'][key] = how
                if how == 'notnow':                # teaches the order, like Teach Axella
                    d['notnow'][key] = int(d['notnow'].get(key) or 0) + 1
                    d['notnow'] = dict(list(d['notnow'].items())[-400:])
            else:
                dd['status'].pop(key, None)        # undo
            if how == 'done':
                self._tick_step(d, key)
            elif how is None:
                self._tick_step(d, key, undo=True)
            return {'key': key, 'status': how}
        if action == 'plan_swap':                  # Swap: the next one takes this stretch, this one goes to the end
            if key not in dd['swap']:
                dd['swap'].append(key)
            return {'key': key}
        if action == 'plan_suggestion':            # Keep waiting / Not now on a state suggestion: not again for that cause
            d['dismissed'][key] = _now()
            return {'key': key}
        if action == 'plan_heads_up':
            how = p.get('how')
            if how not in ('keep', 'moved'):
                raise Bad('keep or move')
            d['heads_up'][key] = how
            if how == 'moved' and p.get('item'):
                nxt = today + datetime.timedelta(days=7 - today.weekday())
                d['moved'][_clip(p.get('item'), 300)] = nxt.isoformat()
            return {'key': key, 'how': how}
        if action == 'plan_check':                 # the monthly "still worth pursuing?" answered
            d['checks'][key] = today.strftime('%Y-%m')
            return {'key': key}
        raise Bad('unknown action')

    def _tick_step(self, d, key, undo=False):
        """Done on a plan item that is a step or an experiment ticks it on its target too."""
        m = re.match(r'^(.+):(t[0-9a-f]{8}):(steps|experiments):(s[0-9a-f]{8})$', key or '')
        if not m:
            return
        e = d['projects'].get(m.group(1)) or {}
        t = next((x for x in e.get('targets') or [] if x.get('id') == m.group(2)), None)
        x = next((y for y in (t or {}).get(m.group(3)) or [] if y.get('id') == m.group(4)), None)
        if x:
            x['done'] = not undo
            if undo:
                x.pop('done_at', None)
            else:
                x['done_at'] = _now()


# ---------------------------------------------------------------- states: suggestions only
def _fmt_day(dd, today):
    if dd == today:
        return 'today'
    if dd == today - datetime.timedelta(days=1):
        return 'yesterday'
    return '%s %d %s' % (dd.strftime('%a'), dd.day, dd.strftime('%b'))


def _ago(iso, today):
    dd = _day(iso)
    if not dd:
        return 'recently'
    if dd == today:
        return 'this morning' if str(iso)[11:13] < '12' else 'today'
    return _fmt_day(dd, today)


def state_suggestions(d, projects, today, recent=None, closed=(), last_activity=None):
    """One card per cause, never a change. recent: {person key: {"at", "name"}} – who wrote lately (digest items);
    closed: refs of tasks / Waiting items that are closed now; last_activity: {pid: iso}."""
    recent, last_activity = recent or {}, last_activity or {}
    weeks = int(d['settings'].get('idle_weeks') or 3)
    out = []
    for pr in projects:
        if pr.get('status') != 'active':
            continue
        pid = pr['id']
        e = d['projects'].get(pid) or {}
        st = e.get('state', 'active')
        name = pr.get('name') or pid
        since = str(e.get('since') or '')
        w = e.get('waiting_for') or {}
        if st == 'waiting' and w:
            hit = None
            if w.get('kind') == 'person':
                r = recent.get(w.get('ref'))
                if r and str(r.get('at') or '') > since:
                    hit = '%s can move again – %s wrote %s.' % (name, r.get('name') or w.get('label'), _ago(r.get('at'), today))
            elif w.get('ref') in closed:
                hit = '%s can move again – "%s" is closed.' % (name, w.get('label'))
            if hit:
                out.append({'key': 'back:%s:%s:%s' % (pid, since[:19], w.get('ref')), 'pid': pid, 'kind': 'back', 'text': hit,
                            'yes': 'Back to Active', 'no': 'Keep waiting'})
        if st == 'paused' and e.get('paused_until') and _day(e['paused_until']) and _day(e['paused_until']) <= today:
            out.append({'key': 'resume:%s:%s' % (pid, e['paused_until']), 'pid': pid, 'kind': 'resume',
                        'text': '%s was paused until %s – pick it up again?' % (name, _fmt_day(_day(e['paused_until']), today)),
                        'yes': 'Back to Active', 'no': 'Keep paused'})
        if st == 'active':
            last = max([x for x in (last_activity.get(pid), e.get('touched'), e.get('since'), pr.get('accepted'), pr.get('created')) if x] or [''])
            ld = _day(last)
            if ld and (today - ld).days >= weeks * 7:
                n = (today - ld).days // 7
                out.append({'key': 'idle:%s:%s' % (pid, ld.isoformat()), 'pid': pid, 'kind': 'idle',
                            'text': '%s has had no activity for %d weeks – pause it?' % (name, n), 'yes': 'Pause', 'no': 'Not now'})
        ts = [t for t in e.get('targets') or []]
        if st not in ('done',) and ts and all(t.get('status') == 'done' or _met(t) for t in ts):
            out.append({'key': 'done:%s:%d' % (pid, len(ts)), 'pid': pid, 'kind': 'done',
                        'text': 'All targets met – mark %s done?' % name, 'yes': 'Mark done', 'no': 'Not yet'})
    return [x for x in out if x['key'] not in d['dismissed']]


def _met(t):
    if t.get('kind') == 'idea':
        g = t.get('go') or []
        return bool(g) and all(x.get('done') for x in g)
    s = t.get('steps') or []
    return bool(s) and all(x.get('done') for x in s)


def progress(t):
    """Counts, never a percentage: '2 of 5 steps done' or '2 of 5 answered · 1 of 3 go'."""
    if t.get('kind') == 'idea':
        q, g = t.get('questions') or [], t.get('go') or []
        return '%d of %d answered · %d of %d go' % (sum(1 for x in q if x.get('done')), len(q), sum(1 for x in g if x.get('done')), len(g))
    s = t.get('steps') or []
    return '%d of %d steps done' % (sum(1 for x in s if x.get('done')), len(s))


# ---------------------------------------------------------------- people on a project
def auto_people(pid, project, e, preps=(), notes=(), own=()):
    """People the owner's own actions put on the project – each with its reason, removable for good."""
    out, seen = [], set(x.get('key') for x in e.get('people') or []) | set(e.get('auto_removed') or []) | set(own)

    def add(key, name, why, ppid=None):
        key = person_key(key)
        if key and key not in seen:
            seen.add(key)
            out.append({'key': key, 'pid': ppid, 'name': name or key, 'role': '', 'star': False, 'source': 'auto', 'why': why})
    for m in preps:
        if m.get('project') == pid:
            for a in m.get('attendees') or []:
                if isinstance(a, dict) and a.get('email'):
                    add(a['email'], a.get('name'), 'On your %s prep' % _clip(m.get('title') or 'meeting', 60))
    for s in project.get('senders') or []:
        if '@' in str(s):
            add(s, None, 'A sender you added to the matches')
    for n in notes:
        links = n.get('links') or []
        if any(l.get('kind') == 'project' and l.get('ref') == pid for l in links):
            for l in links:
                if l.get('kind') == 'person':
                    k = (l.get('keys') or [l.get('ref')])[0]
                    add(k, l.get('label'), 'In your note "%s"' % _clip(n.get('title'), 50), l.get('ref'))
    w = e.get('waiting_for') or {}
    if w.get('kind') == 'person':
        add(w.get('ref'), w.get('label'), '%s waits for them' % (project.get('name') or 'The project'))
    for t in e.get('targets') or []:
        for s in t.get('steps') or []:
            if s.get('waits') and not s.get('done'):
                add(s['waits'], s.get('waits_label'), 'A step waits for them')
    return out


def suggested_people(project, e, mails, own=(), min_mails=3):
    """Someone recurring in the project's mails: 'Sam Rivera appears in 7 of 10 Acme mails.' Asked once."""
    total = len(mails)
    if total < min_mails:
        return []
    count, names = {}, {}
    for m in mails:
        a, nm = _addr(m.get('from'))
        if a:
            count[a] = count.get(a, 0) + 1
            names.setdefault(a, nm)
    have = set(x.get('key') for x in e.get('people') or []) | set(e.get('people_not') or []) | set(own)
    out = []
    for a, n in sorted(count.items(), key=lambda kv: -kv[1]):
        if a in have or n < min_mails or n * 10 < total * 3:
            continue
        out.append({'key': a, 'name': names.get(a) or a, 'mails': n, 'of': total, 'source': 'suggested',
                    'why': '%s appears in %d of %d %s mails.' % (names.get(a) or a, n, total, project.get('name') or 'project')})
    return out[:3]


def _addr(raw):
    if isinstance(raw, dict):
        return str(raw.get('address') or '').strip().lower(), str(raw.get('name') or '').strip()
    s = str(raw or '')
    m = re.search(r'<([^<>@\s]+@[^<>\s]+)>', s)
    if m:
        return m.group(1).lower(), s[:m.start()].strip().strip('"')
    m = re.search(r'[^\s<>"]+@[^\s<>"]+', s)
    return (m.group(0).lower(), '') if m else ('', '')


# ---------------------------------------------------------------- idea targets: signals from a Topic brief
def _words(s):
    return {w.lower() for w in WORDS_RE.findall(str(s or ''))} - STOP


def signals(t, briefs, limit=3):
    """Brief items that might answer an open question or meet a go condition – the owner confirms (Open / Not relevant)."""
    if t.get('kind') != 'idea':
        return []
    asks = [(x, _words(x.get('text'))) for x in (t.get('questions') or []) + (t.get('go') or []) if not x.get('done')]
    no = set(t.get('signals_not') or [])
    out = []
    for br in briefs:
        for it in br.get('items') or []:
            url = str(it.get('url') or '')
            if not url or url in no or any(o['url'] == url for o in out):
                continue
            hay = _words(it.get('title')) | _words(it.get('summary'))
            best = max(((len(ws & hay), x) for x, ws in asks if ws), key=lambda z: z[0], default=(0, None))
            if best[0] >= 2:
                out.append({'url': url, 'title': _clip(it.get('title'), 200), 'for': best[1].get('text'), 'at': br.get('at')})
    return out[:limit]


# ---------------------------------------------------------------- free time
def _dt(s):
    try:
        x = datetime.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except ValueError:
        return None
    return x.astimezone().replace(tzinfo=None) if x.tzinfo else x


def _busy(e):
    return str(e.get('availability') or 'busy').lower() != 'free' and str(e.get('status') or '').lower() not in ('cancelled', 'canceled', 'declined')


def day_window(day, world, work_hours):
    """(start, end) of the time a plan may use that day: work hours on workdays for work, evenings and weekends for
    private. None when there is none."""
    if world == 'work':
        if day.weekday() not in (work_hours or {}).get('days', [0, 1, 2, 3, 4]):
            return None
        a, b = (work_hours or {}).get('from', '09:00'), (work_hours or {}).get('to', '17:00')
    else:
        a, b = PRIVATE_HOURS['weekend' if day.weekday() >= 5 else 'weekday']
    (h1, m1), (h2, m2) = _hm(a), _hm(b)
    return datetime.datetime.combine(day, datetime.time(h1, m1)), datetime.datetime.combine(day, datetime.time(h2, m2))


def closed_day(events, day):
    for e in events:
        if e.get('all_day') and _busy(e) and str(e.get('availability') or '').lower() == 'busy':
            s, en = _dt(e.get('start')), _dt(e.get('end'))
            if s and en and s.date() <= day < en.date():
                return True
    return False


def free_slots(events, day, window, buffer=10, now=None):
    """Free stretches inside the window, minus `buffer` minutes around every busy event; at least MIN_SLOT long,
    starting on a 5-minute mark, never in the past."""
    if not window or closed_day(events, day):
        return []
    a, b = window
    pad = datetime.timedelta(minutes=buffer)
    spans = []
    for e in events:
        if e.get('all_day') or not _busy(e):
            continue
        s, en = _dt(e.get('start')), _dt(e.get('end'))
        if not s or not en or en + pad <= a or s - pad >= b:
            continue
        spans.append((s - pad, en + pad))
    spans.sort()
    out, t = [], a
    if now and now > t:
        t = now
    for s, en in spans:
        if s > t:
            out.append((t, min(s, b)))
        t = max(t, en)
    if t < b:
        out.append((t, b))
    res = []
    for s, en in out:
        m = (5 - s.minute % 5) % 5
        s = (s + datetime.timedelta(minutes=m)).replace(second=0, microsecond=0)
        if en > s and (en - s).total_seconds() >= MIN_SLOT * 60:
            res.append((s, en))
    return res


def _mins(a, b):
    return int((b - a).total_seconds() // 60)


def _len(m):
    h, mm = divmod(int(m), 60)
    return ('%d h %d min' % (h, mm) if mm else '%d h' % h) if h else '%d min' % mm


# ---------------------------------------------------------------- what could be worked on
def _target_due(t):
    return t.get('date') if t.get('kind') == 'date' else t.get('to') if t.get('kind') == 'period' else None


def candidates(d, projects, focus, day, extras=None):
    """The items a plan is made of, in order: the focus projects' open steps (target date first, then their own order)
    and experiments, then what is due anyway (extras: [{"key", "title", "mins", "why", "world"}])."""
    out = []
    for n, pid in enumerate(focus):
        pr = next((x for x in projects if x.get('id') == pid), None)
        if not pr:
            continue
        e = d['projects'].get(pid) or {}
        world = 'private' if pr.get('ctx') == 'private' else 'work'
        for t in sorted([t for t in e.get('targets') or [] if t.get('status') != 'done'],
                        key=lambda t: (_target_due(t) or '9999', t.get('kind') == 'idea')):
            lst = 'experiments' if t.get('kind') == 'idea' else 'steps'
            L = t.get(lst) or []
            todo = [x for x in L if not x.get('done')]
            for i, x in enumerate(todo):
                pos = L.index(x) + 1
                c = {'key': '%s:%s:%s:%s' % (pid, t['id'], lst, x['id']), 'pid': pid, 'project': pr.get('name'), 'world': world,
                     'title': x.get('text'), 'mins': int(x.get('mins') or (60 if lst == 'experiments' else STEP_MINS)),
                     'target': t.get('title'), 'due': _target_due(t), 'current': i == 0,
                     'where': ('step %d of %d' % (pos, len(L))) if lst == 'steps' else ('experiment %d' % pos),
                     'rank': (i, n, _target_due(t) or '9999')}
                if x.get('waits'):
                    c['waits'] = x.get('waits_label') or x['waits']
                if x.get('day') and x['day'] > day.isoformat():
                    c['later_day'] = x['day']
                out.append(c)
    for x in extras or []:
        out.append(dict(x, rank=(-1 if x.get('first') else 50, 0, '')))
    return out


def _order(cands, d, day):
    dd = d['days'].get(day.isoformat()) or {}
    swap = dd.get('swap') or []
    nn = d.get('notnow') or {}
    def k(c):
        r = c['rank']
        return (c['key'] in swap, r[0] + min(3, int(nn.get(c['key']) or 0)), r[1], r[2])
    return sorted(cands, key=k)


def _next_fit(slots_by_day, mins, after):
    for dday, sl in slots_by_day:
        if dday <= after:
            continue
        for s, en in sl:
            if _mins(s, en) >= mins:
                return '%s %s' % (dday.strftime('%a'), s.strftime('%H:%M'))
    return None


def plan_day(d, projects, day, events, work_hours, now=None, extras=None, week_slots=None, focus=None):
    """Now · Next · Later for one day: the focus projects' items in today's real free stretches (minus the buffer).
    Returns {"date", "focus", "none", "now", "next", "later", "done", "free"}."""
    dd = d['days'].get(day.isoformat()) or {}
    buf = int(d['settings'].get('buffer', 10))
    focus = focus if focus is not None else (dd.get('focus') or [])
    res = {'date': day.isoformat(), 'focus': focus, 'none': bool(dd.get('none')), 'now': None, 'next': [], 'later': [], 'done': [], 'free': 0, 'buffer': buf}
    if res['none'] and focus == dd.get('focus'):
        return res
    if not focus:
        extras = None                                # what is due anyway joins a plan; it isn't a plan by itself
    worlds = {}
    for w in ('work', 'private'):
        worlds[w] = [list(s) for s in free_slots(events, day, day_window(day, w, work_hours), buf, now)]
    longest = {w: max([_mins(s, en) for s, en in sl] or [0]) for w, sl in worlds.items()}
    used_worlds = {('private' if (next((x for x in projects if x.get('id') == pid), {}) or {}).get('ctx') == 'private' else 'work') for pid in focus}
    used_worlds = used_worlds or {'private' if day.weekday() >= 5 else 'work'}
    res['free'] = sum(_mins(s, en) for w in used_worlds for s, en in worlds[w])
    status = dd.get('status') or {}
    moved = d.get('moved') or {}
    cands = _order(candidates(d, projects, focus, day, extras), d, day)
    placed = []
    for c in cands:
        st = status.get(c['key'])
        if st == 'done':
            res['done'].append({'key': c['key'], 'title': c['title'], 'project': c.get('project'), 'pid': c.get('pid')})
            continue
        if st == 'notnow':
            res['later'].append(dict(_pub(c), when='Later', why='not now today'))
            continue
        if moved.get(c['key']) and moved[c['key']] > day.isoformat():
            res['later'].append(dict(_pub(c), when='Next week', why='moved to next week'))
            continue
        if c.get('waits'):
            res['later'].append(dict(_pub(c), when='Waiting', why='waits for %s' % c['waits']))
            continue
        if c.get('later_day'):
            ld = _day(c['later_day'])
            res['later'].append(dict(_pub(c), when=ld.strftime('%a') if ld else 'Later', why='planned for that day'))
            continue
        spot = None
        for sl in worlds.get(c.get('world') or 'work') or []:
            if _mins(sl[0], sl[1]) >= c['mins']:
                spot = sl
                break
        if spot is None:
            fit = _next_fit(week_slots or [], c['mins'], day)
            why = 'needs %s, no %s free today' % (_len(c['mins']), _len(c['mins'])) if longest[c.get('world') or 'work'] < c['mins'] else "doesn't fit today"
            res['later'].append(dict(_pub(c), when=fit or 'Later', why=why))
            continue
        s = spot[0]
        en = s + datetime.timedelta(minutes=c['mins'])
        spot[0] = en
        placed.append(dict(_pub(c), start=s.strftime('%H:%M'), end=en.strftime('%H:%M'), mins=c['mins'], _s=s, _e=en))
    seen = {x['key'] for x in res['done']}
    for k, v in status.items():                      # a step ticked from the plan is no longer a candidate: still listed
        if v == 'done' and k not in seen:
            x = item_of(d, projects, k)
            if x:
                res['done'].append(x)
    placed.sort(key=lambda x: x['_s'])
    t = now or datetime.datetime.combine(day, datetime.time(0, 0))
    for x in placed:
        nxt = next((e for e in sorted(events, key=lambda e: str(e.get('start') or '')) if not e.get('all_day') and _busy(e)
                    and _dt(e.get('start')) and x['_e'] <= _dt(e['start']) <= x['_e'] + datetime.timedelta(minutes=buf + 30)), None)
        if nxt:
            x['why'] = 'before your %s %s' % (_dt(nxt['start']).strftime('%H:%M'), _clip(nxt.get('title') or 'meeting', 60))
        x.pop('_s'), x.pop('_e')
    if placed and (day > t.date() or placed[0]['end'] > t.strftime('%H:%M')):
        res['now'] = placed[0]
        res['next'] = placed[1:]
    else:
        res['next'] = placed
    if not focus:
        res['later'] = [x for x in res['later'] if x.get('pid') is None]
    return res


def item_of(d, projects, key):
    m = re.match(r'^(.+):(t[0-9a-f]{8}):(steps|experiments):(s[0-9a-f]{8})$', key or '')
    if not m:
        return None
    pr = next((x for x in projects if x.get('id') == m.group(1)), None)
    t = next((x for x in ((d['projects'].get(m.group(1)) or {}).get('targets') or []) if x.get('id') == m.group(2)), None)
    x = next((y for y in (t or {}).get(m.group(3)) or [] if y.get('id') == m.group(4)), None)
    if not pr or not x:
        return None
    return {'key': key, 'title': x.get('text'), 'project': pr.get('name'), 'pid': pr.get('id')}


def _pub(c):
    return {k: c.get(k) for k in ('key', 'pid', 'project', 'title', 'mins', 'target', 'where', 'due', 'world') if c.get(k) is not None}


def other_later(d, projects, focus, limit=3):
    """Active projects with targets that are not today's focus: their next step, under Later."""
    out = []
    for pr in projects:
        pid = pr.get('id')
        if pid in focus or pr.get('status') != 'active' or (d['projects'].get(pid) or {}).get('state', 'active') != 'active':
            continue
        c = candidates(d, projects, [pid], datetime.date.today())
        c = [x for x in c if not x.get('waits')]
        if c:
            out.append(dict(_pub(c[0]), when='Later', why='not a focus project today'))
    return out[:limit]


# ---------------------------------------------------------------- the focus question
def suggest_focus(d, projects, day, free_mins=0, limit=2):
    """One or two Active projects with a one-line reason. Rules: a target close or slipping first, then what has
    waited longest since it was last a focus; weekends only private projects."""
    weekend = day.weekday() >= 5
    scored = []
    for pr in projects:
        pid = pr.get('id')
        e = d['projects'].get(pid) or {}
        if pr.get('status') != 'active' or e.get('state', 'active') != 'active':
            continue
        if weekend and pr.get('ctx') != 'private':
            continue
        open_t = [t for t in e.get('targets') or [] if t.get('status') != 'done']
        if not open_t:
            continue
        due = min([_day(_target_due(t)) for t in open_t if _day(_target_due(t))] or [None], key=lambda x: x or datetime.date.max)
        last = max([k for k, v in d['days'].items() if pid in (v.get('focus') or []) and k < day.isoformat()] or [''])
        days_left = (due - day).days if due else 999
        waited = (day - _day(last)).days if last else 60
        score = (days_left if days_left >= 0 else -1, -waited)
        scored.append((score, pr, open_t, due, days_left))
    scored.sort(key=lambda x: x[0])
    pick = scored[:limit]
    if not pick:
        return {'projects': [], 'reason': ''}
    names = [x[1].get('name') for x in pick]
    first = pick[0]
    bits = []
    if first[3]:
        t = next(t for t in first[2] if _day(_target_due(t)) == first[3])
        left = len([s for s in t.get('steps') or [] if not s.get('done')])
        when = 'today' if first[4] == 0 else 'tomorrow' if first[4] == 1 else ('was due %s' % _fmt_day(first[3], day) if first[4] < 0 else first[3].strftime('%A'))
        bits.append('%s is due %s with %d of %d steps left' % (t.get('title') or first[1].get('name'), when, left, len(t.get('steps') or []))
                    if first[4] >= 0 else '%s %s' % (t.get('title') or first[1].get('name'), when))
    else:
        bits.append("%s hasn't been a focus for a while" % first[1].get('name'))
    if free_mins:
        bits.append('today has %s free between meetings' % _len(free_mins))
    why = ', and '.join(bits)
    reason = 'Axella suggests %s. %s.' % (' and '.join(names), why[:1].upper() + why[1:])
    return {'projects': [x[1]['id'] for x in pick], 'reason': reason}


# ---------------------------------------------------------------- the rest of the week
def week(d, projects, today, events, work_hours, now=None, extras=None, whole=False):
    """One entry per day to Sunday (or Mon–Sun): focus, the slotted items, target days; plus at most one heads-up when
    a date target won't fit. Items already placed on an earlier day aren't placed again."""
    mon = today - datetime.timedelta(days=today.weekday())
    days = [mon + datetime.timedelta(days=i) for i in range(7)]
    if not whole:
        days = [x for x in days if x >= today]
        if today.weekday() == 6:                     # Sunday: today and the coming week
            days += [today + datetime.timedelta(days=i) for i in range(1, 8)]
    buf = int(d['settings'].get('buffer', 10))
    slots_by_day = []
    for x in days:
        sl = []
        for w in ('work', 'private'):
            sl += free_slots(events, x, day_window(x, w, work_hours), buf, now if x == today else None)
        slots_by_day.append((x, sorted(sl)))
    used = set()
    out = []
    placed_by_target = {}
    for x in days:
        stored = (d['days'].get(x.isoformat()) or {})
        if x < today:
            out.append({'date': x.isoformat(), 'past': True, 'focus': stored.get('focus') or [], 'items': [], 'targets': [], 'private': x.weekday() >= 5})
            continue
        focus = stored.get('focus')
        if focus is None or (not focus and not stored.get('none')):
            focus = suggest_focus(d, projects, x)['projects']
        fake = dict(d, days=dict(d['days'], **{x.isoformat(): dict(stored, status=dict(stored.get('status') or {}, **{k: 'done' for k in used}))}))
        p = plan_day(fake, projects, x, events, work_hours, now if x == today else None, extras if x == today else None, focus=focus)
        items = ([p['now']] if p['now'] else []) + p['next']
        for it in items:
            used.add(it['key'])
            tid = (it['key'].split(':') + ['', ''])[1]
            placed_by_target[tid] = placed_by_target.get(tid, 0) + int(it.get('mins') or 0)
        tg = []
        for pr in projects:
            for t in (d['projects'].get(pr.get('id')) or {}).get('targets') or []:
                if t.get('status') != 'done' and _target_due(t) == x.isoformat():
                    tg.append({'pid': pr['id'], 'project': pr.get('name'), 'title': t.get('title')})
        busy = sum(_mins(_dt(e['start']), _dt(e['end'])) for e in events if not e.get('all_day') and _busy(e) and _dt(e.get('start'))
                   and _dt(e.get('end')) and _dt(e['start']).date() == x)
        out.append({'date': x.isoformat(), 'focus': focus, 'none': bool(stored.get('none')), 'items': items, 'targets': tg,
                    'private': x.weekday() >= 5, 'meeting_mins': busy, 'free': p['free']})
    return {'days': out, 'heads_up': heads_up(d, projects, today, days, placed_by_target, out)}


def heads_up(d, projects, today, days, placed, plan):
    """'Acme proposal needs about 1 h more than Mon–Thu give.' – at most one, calm, two buttons."""
    for pr in projects:
        e = d['projects'].get(pr.get('id')) or {}
        if pr.get('status') != 'active' or e.get('state', 'active') != 'active':
            continue
        for t in e.get('targets') or []:
            due = _day(t.get('date')) if t.get('kind') == 'date' and t.get('status') != 'done' else None
            if not due or not days or not (today <= due <= days[-1]):
                continue
            need = sum(int(s.get('mins') or STEP_MINS) for s in t.get('steps') or [] if not s.get('done') and not s.get('waits'))
            got = placed.get(t['id'], 0)
            short = need - got
            if short < 30:
                continue
            key = 'hu:%s:%s' % (t['id'], (today - datetime.timedelta(days=today.weekday())).isoformat())
            if key in d['heads_up']:
                continue
            before = [x for x in days if x < due] or [due]
            span = before[0].strftime('%a') + ('–' + before[-1].strftime('%a') if len(before) > 1 else '')
            move = None
            for day_ in plan:
                for it in day_.get('items') or []:
                    if ':experiments:' in it['key'] and it.get('pid') != pr['id'] and (not move or it['mins'] > move['mins']):
                        move = it
            text = '%s needs about %s more than %s give%s.' % (t.get('title') or pr.get('name'), _len(round(short / 15) * 15 or 15), span, '' if len(before) > 1 else 's')
            r = {'key': key, 'pid': pr['id'], 'text': text}
            if move:
                r['move'] = {'key': move['key'], 'label': 'Move %s %s to next week' % (move.get('project'), move.get('where'))}
            return r
    return None


# ---------------------------------------------------------------- the monthly check (idea targets)
def checks_due(d, projects, today):
    out = []
    month = today.strftime('%Y-%m')
    for pr in projects:
        if pr.get('status') != 'active':
            continue
        for t in (d['projects'].get(pr['id']) or {}).get('targets') or []:
            if t.get('kind') == 'idea' and t.get('status') != 'done' and d['checks'].get(t['id']) != month:
                out.append({'key': t['id'], 'pid': pr['id'], 'text': '%s: %s. Still worth pursuing?' % (t.get('title') or pr.get('name'), progress(t))})
    return out


# ---------------------------------------------------------------- digest lines (the push watcher adds them, deterministic)
def add_to_digest(pl, digests_dir, name, focus_fn, checks_fn, done_fn):
    """The morning digest asks the focus question; the Sunday week-ahead carries "This week's focus"; the Friday wrap
    gets the monthly check of idea targets and one calm line per project marked Done this week. Once per digest,
    through digestfile.update. focus_fn(day) → {"projects": [names], "reason"}; checks_fn() → [text]; done_fn() → [name]."""
    import digestfile
    m = re.match(r'^(\d{4}-\d{2}-\d{2})-(\d{2})\d{2}\.json$', name)
    if not m or not pl.enabled():
        return None
    day0 = datetime.date.fromisoformat(m.group(1))
    hour = int(m.group(2))
    morning = 5 <= hour <= 9 and day0.weekday() < 5
    sunday = day0.weekday() == 6 and hour >= 17
    friday = day0.weekday() == 4 and hour >= 14
    if not (morning or sunday or friday):
        return None
    stem = name[:-5].replace('-', '')[:12]

    def change(dg):
        if not isinstance(dg, dict) or not isinstance(dg.get('items'), list) or dg.get('plan_line') is not None:
            return False, None
        sc = dg.get('scope') if isinstance(dg.get('scope'), list) and dg.get('scope') else None
        if sc and 'work' not in sc:
            dg['plan_line'] = 0
            return True, None
        add = []
        if morning or sunday:
            day = day0 if morning else day0 + datetime.timedelta(days=1)
            f = focus_fn(day)
            if f and f.get('projects'):
                head = ('What are we working on today? Axella suggests %s.' if morning else "This week's focus: %s.") % ' and '.join(f['projects'])
                add.append({'id': '%s-p3-plan' % stem, 'section': 'p3', 'channel': 'calendar', 'ctx': 'work', 'topic': 'Your day' if morning else 'Your week',
                            'headline': head, 'detail': f.get('reason') or '', 'link': 'plan'})
        if friday:
            for i, t in enumerate((checks_fn() or [])[:2]):
                add.append({'id': '%s-p3-check%d' % (stem, i), 'section': 'p3', 'channel': 'calendar', 'ctx': 'work', 'topic': 'Targets',
                            'headline': t, 'detail': 'An idea target – keep it, change it or mark it done on the project page.', 'link': 'plan'})
            for i, n in enumerate((done_fn() or [])[:3]):
                add.append({'id': '%s-p3-done%d' % (stem, i), 'section': 'p3', 'channel': 'calendar', 'ctx': 'work', 'topic': 'Targets',
                            'headline': '%s is done.' % n, 'detail': 'Archive it whenever you are ready.', 'link': 'plan'})
        for it in add:
            it['first_seen'] = dg.get('generated') or ''
        dg['items'].extend(add)
        dg['plan_line'] = len(add)
        return True, len(add)
    return digestfile.update(os.path.join(digests_dir, name), change)
