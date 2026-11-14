"""Axella schedule settings: vacation mode, days off and on-demand sweeps (state/schedule.json).

Written by the dashboard (Settings), read by every scheduled run (AXELLA.md "Pause, days off and on-demand sweep")
and by the digest guard. Shape:
  {"vacation": {"on": false, "mode": "urgent"|"off", "from": "YYYY-MM-DD"|null, "until": "YYYY-MM-DD"|null},
   "days": [0,1,2,3,4,5,6],            # weekdays (Mon=0) on which digests run
   "urgent_on_days_off": false,        # keep the P0 checks running on days off
   "off_work_only": false,             # a day off = a day off from work: Work-only digests pause, private ones run
   "off_dates": ["YYYY-MM-DD", ...],   # single days off (holidays)
   "sweep_request": {"at": iso, "by": login, "worlds"?: [...]} | null,
   "sweep_later": {"at": iso, "asked": iso, "by": login} | null,    # "In an hour": a one-off sweep the owner asked for
   "sweep_offer": {"on": true, "off_kinds": ["day-5", "evening", ...]}}   # "Offer a sweep outside digest hours"
A run that starts the on-demand digest writes state/sweep-fired.json {"request_at": <sweep_request.at>, "at": iso}.
"""
import datetime
import json
import os
import re
import threading

LOCK = threading.Lock()
DEFAULT = {'vacation': {'on': False, 'mode': 'urgent', 'from': None, 'until': None},
           'days': [0, 1, 2, 3, 4, 5, 6], 'urgent_on_days_off': False, 'off_work_only': False, 'off_dates': [], 'sweep_request': None,
           'sweep_later': None, 'sweep_offer': {'on': True, 'off_kinds': []}}
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
WEEKDAY = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
WORLDS = ('private', 'work')
OFFER_KIND = re.compile(r'^(day-[0-6]|evening|morning|daytime)$')   # the kinds of gap a sweep offer can be stopped for
LATER_MIN = 60
IMMEDIATE = None    # set by the action service: () -> True when the local scheduler picks sweeps up at once


class Bad(Exception):
    pass


class Schedule:
    def __init__(self, state_dir):
        self.file = os.path.join(state_dir, 'schedule.json')
        self.fired = os.path.join(state_dir, 'sweep-fired.json')

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            d = {}
        out = json.loads(json.dumps(DEFAULT))
        out.update({k: v for k, v in d.items() if k in DEFAULT})
        out['vacation'] = {**DEFAULT['vacation'], **(d.get('vacation') or {})}
        so = d.get('sweep_offer') if isinstance(d.get('sweep_offer'), dict) else {}
        out['sweep_offer'] = {'on': bool(so.get('on', True)),
                              'off_kinds': [k for k in (so.get('off_kinds') or []) if isinstance(k, str) and OFFER_KIND.match(k)]}
        return out

    def _save(self, d):
        tmp = self.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.file)

    # ---------- what applies today ----------
    def status(self, now=None):
        """{'digests': bool, 'urgent': bool, 'reason': str|None, 'vacation_until': date|None}"""
        now = now or datetime.datetime.now()
        d, today = self.load(), now.date().isoformat()
        v = d['vacation']
        if v['on'] and (not v['from'] or v['from'] <= today) and (not v['until'] or today <= v['until']):
            until = f" until {v['until']}" if v['until'] else ''
            if v['mode'] == 'off':
                return {'digests': False, 'urgent': False, 'reason': f'Vacation mode – completely off{until}', 'vacation_until': v['until']}
            return {'digests': False, 'urgent': True, 'reason': f'Vacation mode – urgent only{until}', 'vacation_until': v['until']}
        # weekdays are set per digest in Settings → Schedule (state/scheduler.json); here only single days off
        if today in d['off_dates'] and d.get('off_work_only'):
            # "Pause work digests only": private digests run, Work-only ones are skipped, both-world ones cover private
            return {'digests': True, 'urgent': True, 'work_paused': True, 'reason': 'Day off – work digests paused',
                    'vacation_until': None}
        if today in d['off_dates']:
            why = 'Day off'
            return {'digests': False, 'urgent': bool(d['urgent_on_days_off']),
                    'reason': why + (' – urgent checks only' if d['urgent_on_days_off'] else ' – no digests or checks'),
                    'vacation_until': None}
        return {'digests': True, 'urgent': True, 'reason': None, 'vacation_until': None}

    def sweep(self):
        """Pending on-demand sweep, or None. A request counts as done once a run has fired it."""
        d = self.load()
        req = d.get('sweep_request')
        if not req:
            return None
        try:
            with open(self.fired, encoding='utf-8') as f:
                fired = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            fired = {}
        return {**req, 'fired_at': fired.get('at') if fired.get('request_at') == req['at'] else None}

    def later(self):
        """The one-off "In an hour" sweep, or None."""
        lt = self.load().get('sweep_later')
        return lt if isinstance(lt, dict) and lt.get('at') else None

    def later_take(self, at):
        """Clear the one-off sweep once the scheduler has picked it up (only the one it saw)."""
        with LOCK:
            d = self.load()
            if (d.get('sweep_later') or {}).get('at') == at:
                d['sweep_later'] = None
                self._save(d)

    @staticmethod
    def worlds_ok(w):
        if w is None:
            return None
        if not isinstance(w, list) or not w or not set(w) <= set(WORLDS):
            raise Bad('worlds must be work, private or both')
        return sorted(set(w))

    @staticmethod
    def wait_text(now=None, general=False):
        """What to tell the user after tapping "Run sweep now" – or, general=True, what to expect before tapping it
        (the Settings card shows that one permanently, so it must not read like a live status)."""
        now = now or datetime.datetime.now()
        if general:
            if IMMEDIATE and IMMEDIATE():
                return 'When you start one, the digest is usually ready in 5–15 minutes. You get a push when it’s ready.'
            return ('When you start one, the digest is usually ready in 15–30 minutes on weekdays; otherwise it can take up '
                    'to about an hour, and at night it waits for the first morning check. You get a push when it’s ready.')
        if IMMEDIATE and IMMEDIATE():
            return 'Starting now – the digest is usually ready in 5–15 minutes. You’ll get a push when it’s ready.'
        wd, hm = now.weekday(), now.hour * 60 + now.minute
        if wd < 5 and 7 * 60 <= hm < 22 * 60 + 45:
            return 'Your digest is on its way – usually in 15–30 minutes. You’ll get a push when it’s ready.'
        if 8 * 60 <= hm < 22 * 60 + 30:
            return 'Your digest is on its way – outside weekday hours it can take up to about 1 hour. You’ll get a push when it’s ready.'
        return ('Requested – but no checks run at night, so it will start with the first check in the morning. '
                'For an immediate run, open the "Axella – on-demand digest" task in the Claude app and tap Run now.')

    # ---------- dashboard actions ----------
    def action(self, action, p, login):
        with LOCK:
            d = self.load()
            if action == 'schedule_set':
                if 'vacation' in p:
                    v = p['vacation'] or {}
                    if v.get('mode', 'urgent') not in ('urgent', 'off'):
                        raise Bad('bad vacation mode')
                    for k in ('from', 'until'):
                        if v.get(k) and not DATE.match(str(v[k])):
                            raise Bad(f'bad {k} date')
                    if v.get('from') and v.get('until') and v['from'] > v['until']:
                        raise Bad('vacation ends before it starts')
                    d['vacation'] = {'on': bool(v.get('on')), 'mode': v.get('mode', 'urgent'),
                                     'from': v.get('from') or None, 'until': v.get('until') or None}
                if 'days' in p:
                    days = sorted({int(x) for x in p['days'] if str(x).isdigit() and 0 <= int(x) <= 6})
                    d['days'] = days
                if 'urgent_on_days_off' in p:
                    d['urgent_on_days_off'] = bool(p['urgent_on_days_off'])
                if 'off_work_only' in p:
                    d['off_work_only'] = bool(p['off_work_only'])
                if 'off_dates' in p:
                    dates = sorted({str(x) for x in p['off_dates'] if DATE.match(str(x))})
                    d['off_dates'] = [x for x in dates if x >= (datetime.date.today() - datetime.timedelta(days=7)).isoformat()][:100]
                if 'sweep_offer_on' in p:
                    d['sweep_offer']['on'] = bool(p['sweep_offer_on'])
                if 'sweep_offer_off_kinds' in p:
                    ks = p['sweep_offer_off_kinds']
                    if not isinstance(ks, list) or not all(isinstance(k, str) and OFFER_KIND.match(k) for k in ks):
                        raise Bad('bad sweep offer exception')
                    d['sweep_offer']['off_kinds'] = sorted(set(ks))
                self._save(d)
                return 'saved'
            if action == 'sweep_request':
                s = self.sweep()
                if s and not s.get('fired_at'):
                    return {'pending_since': s['at'], 'message': 'A sweep is already requested. ' + self.wait_text()}
                d['sweep_request'] = {'at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'), 'by': login}
                w = self.worlds_ok(p.get('worlds'))
                if w:
                    d['sweep_request']['worlds'] = w
                self._save(d)
                return {'pending_since': d['sweep_request']['at'], 'message': self.wait_text()}
            if action == 'sweep_cancel':
                d['sweep_request'] = None
                self._save(d)
                return 'cancelled'
            if action == 'sweep_later':            # one fixed delay – no time from the dashboard, no other task
                if d.get('sweep_later'):
                    return {'at': d['sweep_later']['at'], 'message': 'A sweep is already planned.'}
                now = datetime.datetime.now().astimezone().replace(microsecond=0)
                d['sweep_later'] = {'at': (now + datetime.timedelta(minutes=LATER_MIN)).isoformat(), 'asked': now.isoformat(), 'by': login}
                self._save(d)
                return {'at': d['sweep_later']['at']}
            if action == 'sweep_later_cancel':
                d['sweep_later'] = None
                self._save(d)
                return 'cancelled'
            raise Bad('unknown action')
