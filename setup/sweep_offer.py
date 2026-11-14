"""Offer a sweep outside digest hours (dev request "Offer a sweep outside digest hours").

When the owner has the dashboard open in a gap of the schedule – a day without digests, the evening after the last
slot – and something new has arrived, Today shows one quiet row: Now · In an hour · Dismiss. Never a push, and never a
sweep without a tap; the only automatic run is the "In an hour" one the owner asked for (schedule.py sweep_later).

Which gap: the scheduler's own rules (Scheduler.due_digests, the same as the digest guard and the runs), so days without
slots, switched-off slots and moved times are respected. A gap starts with the last digest or sweep run and ends with
the next one; the offer shows at most once per gap. New items are counted here (Scheduler.count_new), never by Claude.
"Is the owner there" (visible, focused, input in the last minute) is decided by the dashboard – it only asks then.

State: settings in state/schedule.json "sweep_offer" ({on, off_kinds}); the per-gap answer and the learning counters in
state/sweep-offer.json {"dismissed_gap": id, "dismiss": {kind: n}, "asked": [kind, ...]}. Owner only. Python 3.9.
"""
import datetime
import json
import os
import re
import threading

QUIET_AFTER = datetime.timedelta(hours=2)     # no offer within 2 h of a digest or sweep
SOON = datetime.timedelta(minutes=60)          # … nor when a digest is due within the hour
STREAK = 3                                     # dismissals in a row of one kind before "stop offering …?" is asked once
DAYS = ['Mondays', 'Tuesdays', 'Wednesdays', 'Thursdays', 'Fridays', 'Saturdays', 'Sundays']
GAP = re.compile(r'^[\w.:+-]{1,80}$')
LOCK = threading.Lock()


class Bad(Exception):
    pass


def kind_of(now, due_today):
    """The kind of gap: 'day-N' (no digest that weekday), 'evening' (after the last slot), 'morning', 'daytime'."""
    if not due_today:
        return 'day-%d' % now.weekday()
    mins = now.hour * 60 + now.minute
    times = [int(hm[:2]) * 60 + int(hm[3:]) for _sid, hm, _l in due_today]
    if mins >= max(times):
        return 'evening'
    if mins < min(times):
        return 'morning'
    return 'daytime'


def kind_text(kind):
    """How Settings and the question name a kind: "on Saturdays", "in the evening" …"""
    if kind.startswith('day-'):
        return 'on ' + DAYS[int(kind[4:])]
    return {'evening': 'in the evening', 'morning': 'in the morning', 'daytime': 'between digests'}.get(kind, kind)


def scope(now, status, slots, work_hours):
    """The worlds of a sweep that runs now: private only on a work-paused day off, or outside work hours when the
    digests are split into work and private; otherwise both."""
    if status.get('work_paused'):
        return ['private']
    split = any(sorted(set(s.get('worlds') or ['private', 'work'])) != ['private', 'work']
                for s in slots if s.get('enabled', True))
    if split and work_hours:
        try:
            mins = now.hour * 60 + now.minute
            fr, to = (int(x[:2]) * 60 + int(x[3:5]) for x in (work_hours['from'], work_hours['to']))
            if now.weekday() not in work_hours.get('days', [0, 1, 2, 3, 4]) or not fr <= mins < to:
                return ['private']
        except (KeyError, TypeError, ValueError):
            pass
    return ['private', 'work']


def _since_text(since, now):
    hm = since.strftime('%H:%M')
    if since.date() == now.date():
        return hm
    if since.date() == now.date() - datetime.timedelta(days=1):
        return 'yesterday ' + hm
    return since.strftime('%a ') + hm


def text(kind, n, since, now, worlds):
    what = 'private sweep' if worlds == ['private'] else 'work sweep' if worlds == ['work'] else 'sweep'
    lead = 'No digest today' if kind.startswith('day-') else {'evening': 'Quiet evening', 'morning': 'Quiet morning'}.get(kind, 'Between digests')
    return '%s. %d new since %s – %s now?' % (lead, n, _since_text(since, now), what)


class SweepOffer:
    def __init__(self, state_dir, runner, sched, work_hours=None):
        """runner: scheduler.Scheduler; sched: schedule.Schedule; work_hours: () -> {'days', 'from', 'to'} or None."""
        self.file = os.path.join(state_dir, 'sweep-offer.json')
        self.runner, self.sched, self.work_hours = runner, sched, work_hours or (lambda: None)

    def _load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            d = {}
        d = d if isinstance(d, dict) else {}
        return {'dismissed_gap': d.get('dismissed_gap') if isinstance(d.get('dismissed_gap'), str) else None,
                'dismiss': {k: int(v) for k, v in (d.get('dismiss') or {}).items() if isinstance(v, int)},
                'asked': [k for k in (d.get('asked') or []) if isinstance(k, str)]}

    def _save(self, d):
        tmp = self.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, self.file)

    def scope(self, now=None):
        now = (now or datetime.datetime.now().astimezone()).replace(tzinfo=None)
        cfg = self.runner.load()
        return scope(now, self.sched.status(now), cfg.get('digests') or [], self.work_hours())

    def view(self, now=None):
        """{'show': False, 'why'} or the offer: {'show', 'gap', 'kind', 'count', 'since', 'worlds', 'text', 'ask_stop'}."""
        now = now or datetime.datetime.now().astimezone()
        local = now.replace(tzinfo=None)
        no = lambda why: {'show': False, 'why': why}        # noqa: E731
        sd = self.sched.load()
        if not sd['sweep_offer']['on']:
            return no('off in Settings')
        if not self.runner.load().get('enabled'):
            return no('the Mac mini does not run the schedule')
        st = self.sched.status(local)
        if not st.get('digests'):
            return no('paused')                      # vacation or a day off
        sw = self.sched.sweep()
        if sw and not sw.get('fired_at'):
            return no('a sweep is requested')
        if self.sched.later():
            return no('a sweep is planned')
        if self.runner.digest_busy():
            return no('a digest is running')
        last = self.runner.last_digest_run()
        try:
            started = datetime.datetime.fromisoformat(last['started']) if last else None
            ended = datetime.datetime.fromisoformat(last['ended']) if last and last.get('ended') else None
        except (TypeError, ValueError):
            started = ended = None
        if last and (last.get('status') == 'running' or (started and (ended or started) > now - QUIET_AFTER)):
            return no('a digest ran in the last 2 hours')
        due = self.runner.due_digests(local.date())
        soon = [hm for _s, hm, _l in due] + ['+' + hm for _s, hm, _l in self.runner.due_digests(local.date() + datetime.timedelta(days=1))]
        for hm in soon:
            day = local.date() + datetime.timedelta(days=1 if hm.startswith('+') else 0)
            hm = hm.lstrip('+')
            at = datetime.datetime.combine(day, datetime.time(int(hm[:2]), int(hm[3:])))
            if local <= at < local + SOON:
                return no('a digest is due within the hour')
        gap = last['id'] if last else 'none'
        mine = self._load()
        if mine['dismissed_gap'] == gap:
            return no('dismissed for this gap')
        kind = kind_of(local, due)
        if kind in sd['sweep_offer']['off_kinds']:
            return no('not offered ' + kind_text(kind))
        since = started or (now - datetime.timedelta(hours=24))
        counts, why = self.runner.count_new(since)
        if counts is None:
            return no(why)
        n = sum(counts.values())
        if n < 1:
            return no('nothing new')
        worlds = self.scope(now)
        ask = mine['dismiss'].get(kind, 0) >= STREAK and kind not in mine['asked']
        return {'show': True, 'gap': gap, 'kind': kind, 'count': n, 'since': since.isoformat(timespec='minutes'), 'worlds': worlds,
                'text': text(kind, n, since.astimezone(now.tzinfo).replace(tzinfo=None), local, worlds),
                'ask_stop': ask, 'stop_text': 'Stop offering a sweep %s?' % kind_text(kind) if ask else None}

    def action(self, p, login, now=None):
        act, gap = p.get('act'), str(p.get('gap') or '')
        if act not in ('now', 'later', 'undo', 'dismiss', 'stop', 'keep'):
            raise Bad('unknown sweep offer action')
        if act == 'undo':                                    # the 6-second Undo after "In an hour"
            self.sched.action('sweep_later_cancel', {}, login)
            return {'undone': True}
        if not GAP.match(gap):
            raise Bad('bad gap')
        v = self.view(now)
        if not v.get('show') or v['gap'] != gap:
            raise Bad('this offer is no longer open')
        kind = v['kind']
        with LOCK:
            mine = self._load()
            if act in ('now', 'later'):
                mine['dismiss'][kind] = 0
                self._save(mine)
                if act == 'now':
                    return self.sched.action('sweep_request', {'worlds': v['worlds']}, login)
                return self.sched.action('sweep_later', {}, login)
            if act == 'dismiss':
                mine['dismissed_gap'] = gap
                mine['dismiss'][kind] = mine['dismiss'].get(kind, 0) + 1
                self._save(mine)
                return {'dismissed': True}
            if kind not in mine['asked']:                    # stop / keep: the question is asked once per kind
                mine['asked'].append(kind)
            mine['dismiss'][kind] = 0
            if act == 'stop':
                mine['dismissed_gap'] = gap
            self._save(mine)
        if act == 'stop':
            off = sorted(set(self.sched.load()['sweep_offer']['off_kinds']) | {kind})
            self.sched.action('schedule_set', {'sweep_offer_off_kinds': off}, login)
            return {'stopped': kind, 'text': 'No sweep offers %s – change it in Settings → Schedule.' % kind_text(kind)}
        return {'kept': kind}
