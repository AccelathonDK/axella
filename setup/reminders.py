"""Recurring reminders (state/reminders.json) – repeating to-dos the owner sets up on the dashboard.

Each reminder makes a task in the To do list (state/tasks.json, source "reminder") for every occurrence, `lead` days
before the occurrence's date, with the occurrence date as the task's due date. The digests then pick the task up like
any other (overdue and due-today tasks are in the morning digest). Nothing is ever sent – a reminder only adds a task
and, if `push` is on, an iPhone push when the task is created.

Shape:
  [{"id": "r…", "text": str, "every": "day|week|month|year", "interval": 1..12, "start": "YYYY-MM-DD",
    "lead": 0..60, "push": bool, "paused": bool, "next": "YYYY-MM-DD", "last": "YYYY-MM-DD"|null,
    "created": iso, "count": int}]
  start  = the first occurrence; weekly repeats on its weekday, monthly on its day of the month (31 → last day of
           shorter months), yearly on its date (29 Feb → 28 Feb in other years).
  next   = the next occurrence that has no task yet.
If the Mac mini was off for a while, only the newest missed occurrence becomes a task (no pile of old ones).
"""
import calendar
import datetime
import json
import os
import re
import sys
import threading
import time

LOCK = threading.Lock()
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
EVERY = ('day', 'week', 'month', 'year')
MAX = 200


class Bad(Exception):
    pass


def _iso():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def _date(s, what='date'):
    if not isinstance(s, str) or not DATE.match(s):
        raise Bad('bad ' + what)
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        raise Bad('bad ' + what)


def occurrence(start, every, interval, n):
    """The n-th occurrence (n = 0 is start)."""
    if every == 'day':
        return start + datetime.timedelta(days=n * interval)
    if every == 'week':
        return start + datetime.timedelta(weeks=n * interval)
    months = n * interval * (12 if every == 'year' else 1)
    y, m = divmod(start.month - 1 + months, 12)
    y, m = start.year + y, m + 1
    return datetime.date(y, m, min(start.day, calendar.monthrange(y, m)[1]))


def next_after(r, day):
    """First occurrence strictly after `day`."""
    start, every, iv = datetime.date.fromisoformat(r['start']), r['every'], r['interval']
    if day < start:
        return start
    # jump close, then step – cheap and exact for every rule
    span = (day - start).days
    est = {'day': span // iv, 'week': span // (7 * iv), 'month': span // (31 * iv), 'year': span // (366 * iv)}[every]
    n = max(0, est - 1)
    while occurrence(start, every, iv, n) <= day:
        n += 1
    return occurrence(start, every, iv, n)


def describe(r):
    """'Every month on the 7th' – the same wording the dashboard uses."""
    s, iv, e = datetime.date.fromisoformat(r['start']), r['interval'], r['every']
    unit = e if iv == 1 else f'{iv} {e}s'
    head = 'Every day' if (e == 'day' and iv == 1) else f'Every {unit}'
    if e == 'week':
        return f'{head} on {s.strftime("%A")}'
    if e == 'month':
        d = s.day
        suf = 'th' if 11 <= d % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d % 10, 'th')
        return f'{head} on the {d}{suf}'
    if e == 'year':
        return f'{head} on {s.day} {s.strftime("%B")}'
    return head


class Reminders:
    def __init__(self, state_dir, add_task, push=None, log=sys.stderr, today=None):
        self.file = os.path.join(state_dir, 'reminders.json')
        self.add_task, self.push, self.log = add_task, push, log
        self.today = today or datetime.date.today

    # ---------- storage ----------
    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
            return d if isinstance(d, list) else []
        except (OSError, ValueError):
            return []

    def _save(self, rs):
        tmp = self.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(rs, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.file)

    def status(self):
        rs = self.load()
        for r in rs:
            r['label'] = describe(r)
        return {'reminders': rs}

    # ---------- dashboard actions ----------
    @staticmethod
    def _fields(p, r):
        if 'text' in p:
            t = str(p.get('text') or '').strip()
            if not t or len(t) > 500:
                raise Bad('text must be 1–500 characters')
            r['text'] = t
        if 'every' in p:
            if p['every'] not in EVERY:
                raise Bad('bad repeat')
            r['every'] = p['every']
        if 'interval' in p:
            try:
                iv = int(p['interval'])
            except (TypeError, ValueError):
                raise Bad('bad interval')
            if not 1 <= iv <= 12:
                raise Bad('interval must be 1–12')
            r['interval'] = iv
        if 'start' in p:
            _date(p['start'], 'start date')
            r['start'] = p['start']
        if 'lead' in p:
            try:
                lead = int(p['lead'])
            except (TypeError, ValueError):
                raise Bad('bad lead')
            if not 0 <= lead <= 60:
                raise Bad('days before must be 0–60')
            r['lead'] = lead
        if 'push' in p:
            r['push'] = bool(p['push'])
        if 'paused' in p:
            r['paused'] = bool(p['paused'])

    def action(self, action, p):
        with LOCK:
            rs = self.load()
            if action == 'reminder_add':
                if len(rs) >= MAX:
                    raise Bad('too many reminders')
                r = {'id': datetime.datetime.now().strftime('r%Y%m%d%H%M%S%f'), 'text': '', 'every': 'month', 'interval': 1,
                     'start': self.today().isoformat(), 'lead': 0, 'push': True, 'paused': False, 'last': None,
                     'created': _iso(), 'count': 0}
                if 'text' not in p:
                    raise Bad('missing text')
                self._fields(p, r)
                # a first date in the past starts from today: no overdue task for something that never existed
                r['next'] = next_after(r, self.today() - datetime.timedelta(days=1)).isoformat()
                rs.append(r)
                self._save(rs)
                rid = r['id']
            else:
                r = next((x for x in rs if x.get('id') == p.get('id')), None)
                if not r:
                    raise Bad('reminder not found')
                rid = r['id']
                if action == 'reminder_update':
                    rule_changed = any(k in p and p[k] != r.get(k) for k in ('every', 'interval', 'start'))
                    self._fields(p, r)
                    if rule_changed:   # restart from the new rule, but never re-create today's task
                        yday = self.today() - datetime.timedelta(days=1)
                        last = datetime.date.fromisoformat(r['last']) if r.get('last') else None
                        r['next'] = next_after(r, max(yday, last) if last else yday).isoformat()
                elif action == 'reminder_delete':
                    rs.remove(r)
                else:
                    raise Bad('unknown action')
                self._save(rs)
        self.tick()          # a reminder due today (or within its lead) makes its task straight away
        return rid

    # ---------- background ----------
    def tick(self):
        today = self.today()
        made = []
        with LOCK:
            rs = self.load()
            changed = False
            for r in rs:
                if r.get('paused') or not r.get('next'):
                    continue
                nxt = datetime.date.fromisoformat(r['next'])
                lead = datetime.timedelta(days=int(r.get('lead') or 0))
                if nxt - lead > today:
                    continue
                # newest occurrence whose task is due by now; skip older missed ones
                occ = nxt
                while True:
                    after = next_after(r, occ)
                    if after - lead > today:
                        break
                    occ = after
                made.append((r, occ))
                r['last'], r['next'] = occ.isoformat(), next_after(r, occ).isoformat()
                r['count'] = int(r.get('count') or 0) + 1
                changed = True
            if changed:
                self._save(rs)
        for r, occ in made:      # outside the lock: add_task takes the tasks lock
            try:
                self.add_task(r['text'], occ.isoformat(), r['id'])
            except Exception as e:
                self.log.write('%s reminders: task for %s failed: %s\n' % (_iso(), r['id'], str(e)[:200]))
                continue
            if r.get('push', True) and self.push:
                when = 'today' if occ == today else occ.strftime('%a %-d %b')
                try:
                    self.push({'title': 'Reminder', 'body': f'{r["text"]} – due {when}', 'url': '/axella/#sec-tasks',
                               'tag': 'axella-reminder-' + r['id']})
                except Exception as e:
                    self.log.write('%s reminders: push failed: %s\n' % (_iso(), str(e)[:200]))
        return len(made)

    def run(self, every=300):
        while True:
            try:
                self.tick()
            except Exception as e:
                self.log.write('%s reminders: %s\n' % (_iso(), str(e)[:200]))
            time.sleep(every)
