"""Protect your blocks: a gentle look at meeting load (Insights → Your time) and, now and then, one suggestion to hold a
free block on a busy workday before it's gone. Rules only, on the Mac mini, from the calendar Axella already reads. No
AI, nothing leaves the home, no pushes, at most one suggestion a day, work world only. Never moves, declines or touches
anyone else's meeting: "Hold it" adds one busy event of your own (cal_add, with its backup and undo).

  free_blocks(events, day, hours)  → [(start, end)] free inside work hours (busy events block; free ones don't;
                                     tentative ones do; an all-day busy event – out of office – closes the day)
  suggestion(events, day, …)       → {date, start, end, text} or None – a busy day (meetings ≥ half the work hours)
                                     with only one free block of the minimum length left
  your_time(events, week_start, …) → hours in meetings per week (work, private), longest free block per workday,
                                     days with no free block of the minimum length
state/blocks.json: {"settings": {"minutes", "calendar", "name"}, "never": [<date>], "shown": {<date>: <iso>}}
"""
import datetime
import json
import os
import re
import threading

LOCK = threading.Lock()
MINUTES = (60, 90, 120, 180)
DEFAULTS = {'minutes': 120, 'calendar': None, 'name': 'Focus'}
WORK_HOURS = {'days': [0, 1, 2, 3, 4], 'from': '09:00', 'to': '17:00'}


class Bad(Exception):
    pass


def _dt(s):
    try:
        d = datetime.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except ValueError:
        return None
    return d.astimezone().replace(tzinfo=None) if d.tzinfo else d


def _hm(s):
    h, m = str(s or '00:00').split(':')[:2]
    return int(h), int(m)


def window(day, hours):
    (h1, m1), (h2, m2) = _hm(hours.get('from')), _hm(hours.get('to'))
    return (datetime.datetime.combine(day, datetime.time(h1, m1)), datetime.datetime.combine(day, datetime.time(h2, m2)))


def _busy(e):
    return str(e.get('availability') or 'busy').lower() not in ('free',) and str(e.get('status') or '').lower() not in ('cancelled', 'canceled', 'declined')


def day_closed(events, day):
    """An all-day busy event (out of office, a holiday you blocked) – no suggestion that day."""
    for e in events:
        if e.get('all_day') and _busy(e) and str(e.get('availability') or '').lower() == 'busy':
            s, en = _dt(e.get('start')), _dt(e.get('end'))
            if s and en and s.date() <= day < en.date():
                return True
    return False


def busy_spans(events, day, hours):
    a, b = window(day, hours)
    spans = []
    for e in events:
        if e.get('all_day') or not _busy(e):
            continue
        s, en = _dt(e.get('start')), _dt(e.get('end'))
        if not s or not en or en <= a or s >= b:
            continue
        spans.append((max(s, a), min(en, b)))
    spans.sort()
    merged = []
    for s, en in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], en))
        else:
            merged.append((s, en))
    return merged


def free_blocks(events, day, hours=None):
    hours = hours or WORK_HOURS
    a, b = window(day, hours)
    out, t = [], a
    for s, en in busy_spans(events, day, hours):
        if s > t:
            out.append((t, s))
        t = max(t, en)
    if t < b:
        out.append((t, b))
    return out


def _mins(span):
    return int((span[1] - span[0]).total_seconds() // 60)


def _round_up(t):
    m = (15 - t.minute % 15) % 15
    return (t + datetime.timedelta(minutes=m)).replace(second=0, microsecond=0)


def suggestion(events, day, minutes=120, hours=None, never=(), now=None):
    """One suggestion for a busy workday: meetings fill at least half the work hours and only one free block of the
    minimum length is left – hold it before it's gone. None otherwise."""
    hours = hours or WORK_HOURS
    if day.weekday() not in hours.get('days', []) or day.isoformat() in never or day_closed(events, day):
        return None
    a, b = window(day, hours)
    if now and b <= now:
        return None
    meet = sum(_mins(s) for s in busy_spans(events, day, hours))
    if meet * 2 < _mins((a, b)):
        return None
    fits = []
    for s, en in free_blocks(events, day, hours):
        if now and s < now:
            s = _round_up(now)
        s = _round_up(s)
        if en > s and _mins((s, en)) >= minutes:
            fits.append((s, en))
    if len(fits) != 1:
        return None
    s = fits[0][0]
    en = s + datetime.timedelta(minutes=minutes)
    wd = day.strftime('%A')
    return {'date': day.isoformat(), 'start': s.strftime('%H:%M'), 'end': en.strftime('%H:%M'),
            'text': '%s has only one free %s block left. Hold %s–%s?' % (wd, _len(minutes), s.strftime('%H:%M'), en.strftime('%H:%M'))}


def _len(minutes):
    return {60: '1-hour', 90: '1½-hour', 120: '2-hour', 180: '3-hour'}.get(minutes, '%d-minute' % minutes)


def your_time(events, week_start, minutes=120, hours=None):
    """Insights → Your time for one week (Monday): hours in meetings (work, private), the longest free block per
    workday, and the workdays with no free block of the minimum length. No scores, no ranks."""
    hours = hours or WORK_HOURS
    spans = {'work': [], 'private': []}
    for e in events:
        if e.get('all_day') or not _busy(e):
            continue
        s, en = _dt(e.get('start')), _dt(e.get('end'))
        if not s or not en or not (week_start <= s.date() < week_start + datetime.timedelta(days=7)):
            continue
        if not (e.get('attendees') or e.get('meeting')):
            continue                                        # your own blocks aren't meetings
        spans['private' if e.get('ctx') == 'private' else 'work'].append((s, en))
    per = {}
    for k, lst in spans.items():                            # overlapping meetings count once
        total, end = 0, None
        for s, en in sorted(lst):
            if end and s < end:
                if en > end:
                    total += _mins((end, en))
                    end = en
            else:
                total += _mins((s, en))
                end = en
        per[k] = total
    days, none = [], []
    for i in range(7):
        d = week_start + datetime.timedelta(days=i)
        if d.weekday() not in hours.get('days', []):
            continue
        longest = max((_mins(x) for x in free_blocks(events, d, hours)), default=0)
        days.append({'date': d.isoformat(), 'longest': longest})
        if longest < minutes and not day_closed(events, d):
            none.append(d.isoformat())
    return {'week': week_start.isoformat(), 'meeting_hours': {k: round(v / 60, 1) for k, v in per.items()}, 'days': days, 'no_block': none}


class Blocks:
    def __init__(self, state_dir):
        self.file = os.path.join(state_dir, 'blocks.json')

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        d['settings'] = dict(DEFAULTS, **(d.get('settings') or {}))
        d.setdefault('never', [])
        d.setdefault('shown', {})
        return d

    def _save(self, d):
        d['never'] = sorted(set(d['never']))[-200:]
        d['shown'] = dict(sorted(d['shown'].items())[-60:])
        tmp = '%s.%d.%d.tmp' % (self.file, os.getpid(), threading.get_ident())
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)

    def settings(self, p, calendars=()):
        with LOCK:
            d = self.load()
            s = d['settings']
            if 'minutes' in p:
                if int(p['minutes']) not in MINUTES:
                    raise Bad('1, 1½, 2 or 3 hours')
                s['minutes'] = int(p['minutes'])
            if 'calendar' in p:
                if p['calendar'] and p['calendar'] not in calendars:
                    raise Bad('pick one of your work calendars')
                s['calendar'] = p['calendar'] or None
            if 'name' in p:
                n = re.sub(r'[\x00-\x1f\x7f]', ' ', str(p.get('name') or '')).strip()[:60]
                s['name'] = n or 'Focus'
            self._save(d)
            return s

    def mark(self, day, how):
        """'shown' (in a digest: not again that day), 'never' (Don't suggest for this day)."""
        with LOCK:
            d = self.load()
            if how == 'never':
                d['never'].append(day)
            d['shown'][day] = datetime.datetime.now().isoformat(timespec='seconds')
            self._save(d)

    def pick(self, events, days, hours=None, now=None):
        """At most one suggestion among these days: the first busy day not shown or refused yet."""
        d = self.load()
        for day in days:
            if day.isoformat() in d['shown']:
                continue
            s = suggestion(events, day, d['settings']['minutes'], hours, d['never'], now)
            if s:
                return s
        return None

    def add_to_digest(self, digests_dir, name, events_fn, hours=None, now=None):
        """The morning digest (today and tomorrow) and the Sunday week-ahead (the coming week): at most one line, only
        in a digest that covers the work world. Deterministic, through digestfile.update."""
        import digestfile
        from recurring import add_spoken
        m = re.match(r'^(\d{4}-\d{2}-\d{2})-(\d{2})\d{2}\.json$', name)
        if not m:
            return None
        day0 = datetime.date.fromisoformat(m.group(1))
        morning, sunday = 5 <= int(m.group(2)) <= 9, day0.weekday() == 6 and int(m.group(2)) >= 17
        if not (morning or sunday):
            return None
        days = [day0 + datetime.timedelta(days=i) for i in ((0, 1) if morning else range(1, 8))]
        done = {}

        def change(dg):
            if not isinstance(dg, dict) or not isinstance(dg.get('items'), list) or dg.get('blocks_line') is not None:
                return False, None
            sc = dg.get('scope') if isinstance(dg.get('scope'), list) and dg.get('scope') else None
            if sc and 'work' not in sc:
                dg['blocks_line'] = 0
                return True, None
            ev = events_fn(days[0], days[-1] + datetime.timedelta(days=1))
            s = self.pick(ev, days, hours, now)
            dg['blocks_line'] = 1 if s else 0
            if s:
                dg['items'].append({'id': '%s-p3-focus' % name[:-5].replace('-', '')[:12], 'section': 'p3', 'channel': 'calendar',
                                    'ctx': 'work', 'topic': 'Your time', 'headline': s['text'],
                                    'detail': 'Hold it adds one busy event of your own – nothing else in your calendar changes.',
                                    'link': 'focus', 'focus': {'date': s['date'], 'start': s['start'], 'end': s['end']},
                                    'first_seen': dg.get('generated') or ''})
                add_spoken(digests_dir, name, dg, s['text'].replace('Hold', 'You could hold'))
                done['day'] = s['date']
            return True, s
        res = digestfile.update(os.path.join(digests_dir, name), change)
        if done.get('day'):
            self.mark(done['day'], 'shown')
        return res
