"""Calendar → invitees and online meetings: which calendar can do what, and the three taps (Send invites, Send update /
Save, Send cancellation). Glue between the dashboard, meeting_providers.py (the services) and calendar_invites.py
(the calendar servers); axella-actions.py only routes to it.

Per calendar (Macuse's calendars + actions-config "calendars" + "workplaces"):
  - an iCloud calendar → invites through iCloud CalDAV, from your iCloud address (once its app password is set up);
  - a work calendar → invites through Microsoft Graph, from the work account Teams is connected with;
  - a protected workplace's calendar → only from that workplace's own account (its domains), and only the meeting
    services connected with that account;
  - anything else → no invitees here (the dialog says why).
Nothing is sent without its confirm word ('send', or 'save' for a change without telling people) – the same rule as mail.
"""
import re

import calendar_invites as CI
import meeting_providers as MP

Bad = MP.Bad


def _dom(addr):
    return str(addr or '').rsplit('@', 1)[-1].lower() if '@' in str(addr or '') else ''


class Online:
    def __init__(self, services, invites, profile_cals, workplaces, accounts, macuse_cals, own, dashboard_url=None):
        self.svc, self.inv = services, invites
        self.profile_cals = profile_cals        # () → [{"name", "kind", "workplace"}]
        self.workplaces = workplaces            # () → [{"id", "domains", "protected"}]
        self.accounts = accounts                # () → {name: {"kind", "address"}}
        self.macuse_cals = macuse_cals          # () → [{"title", "source", "can_modify"}]
        self.own = own                          # () → {own addresses}
        self.dashboard_url = dashboard_url      # () → "https://…/axella" or None

    # ---- what each calendar can do
    def _icloud_from(self, source):
        """The address of the Mail account behind the calendar's account (same name, e.g. "iCloud"), else an iCloud address."""
        accs = self.accounts() or {}
        for name, a in accs.items():
            if str(name).lower() == str(source or '').lower() and (a or {}).get('address'):
                return a['address']
        for a in accs.values():
            addr = str((a or {}).get('address') or '')
            if (a or {}).get('kind') == 'private' and re.search(r'@(icloud|me|mac)\.com$', addr, re.I):
                return addr
        return None

    def calendars(self):
        prof = {c['name']: c for c in self.profile_cals()}
        wps = {w['id']: w for w in self.workplaces()}
        teams = self.svc.provider('teams').status()
        out = []
        for c in self.macuse_cals():
            title = c.get('title')
            if not title or not c.get('can_modify'):
                continue
            pc = prof.get(title) or {}
            kind = pc.get('kind') or 'private'
            wp = wps.get(pc.get('workplace')) if pc.get('workplace') else None
            prot = bool(wp and wp.get('protected'))
            row = {'title': title, 'kind': kind, 'workplace': (wp or {}).get('id'), 'protected': prot, 'path': None, 'from': None, 'why': None}
            src = str(c.get('source') or '').lower()
            if 'icloud' in src:
                frm = self._icloud_from(c.get('source'))
                if prot:
                    row['why'] = 'This workplace\'s invites go from its own account – not iCloud'
                elif not frm:
                    row['why'] = 'Your iCloud address isn\'t in actions-config.json'
                elif not self.inv.caldav.configured():
                    row['why'] = 'Set up iCloud invites once – SETUP "Meeting services"'
                else:
                    row.update(path='icloud', **{'from': frm})
            elif kind == 'work':
                acc = teams.get('account')
                if teams['state'] == 'needs_approval':
                    row['why'] = 'Waiting for your IT to approve Axella for your work calendar'
                elif teams['state'] != 'connected':
                    row['why'] = 'Connect Microsoft Teams (your work account) in Settings → Calendar'
                elif prot and _dom(acc) not in (wp.get('domains') or []):
                    row['why'] = 'Teams is connected with another account than this workplace\'s'
                else:
                    row.update(path='graph', **{'from': acc})
            else:
                row['why'] = 'This calendar can\'t send invitations from Axella'
            allowed = None
            if prot:
                allowed = {k for k, p in self.svc.providers.items() if _dom(p.status().get('account')) in (wp.get('domains') or [])}
            row['services'] = [s for s in self.svc.offered(kind, allowed)]
            d = self.svc.load()['defaults'].get(title)
            row['default'] = d if any(s['key'] == d and s['offered'] for s in row['services']) else None
            out.append(row)
        return out

    def _cal(self, title):
        row = next((c for c in self.calendars() if c['title'] == title), None)
        if not row:
            raise Bad('that calendar can\'t be changed from here')
        return row

    def _times(self, p):
        title = re.sub(r'[\x00-\x1f\x7f]', ' ', str(p.get('title') or '')).strip()[:300]
        if not title:
            raise Bad('give the event a title')
        start, end = str(p.get('start') or ''), str(p.get('end') or '')
        if CI._dt(end) <= CI._dt(start):
            raise Bad('the event ends before it starts')
        if p.get('all_day'):
            raise Bad('an all-day event can\'t have invitees from here')
        tz = str(p.get('tz') or '')[:60] or None
        loc = str(p.get('location') or '')[:300]
        notes = str(p.get('notes') or '')[:3000]
        return title, start, end, tz, loc, notes

    def meeting(self, row, online, idem, title, start, end, tz):
        """The online meeting chosen in the dialog → a join dict, or None. Created on this tap (once per key)."""
        if not online or online.get('kind') in (None, 'none'):
            return None, False
        if online.get('kind') == 'link':
            return {'join_url': MP.check_link(online.get('url')), 'provider': 'link'}, False
        key = str(online.get('provider') or '')
        s = next((x for x in row['services'] if x['key'] == key), None)
        if not s or not s['offered']:
            raise Bad('%s isn\'t available for this calendar' % (s or {}).get('label', 'that meeting service'))
        if key == 'teams' and row['path'] == 'graph':
            return None, True                   # Exchange makes the Teams meeting on the event itself
        m = self.svc.create_once(idem, key, title, start, end, tz)
        return dict(m, provider=key, idem=idem), False

    # ---- the taps
    def send(self, p):
        if p.get('confirm') != 'send':
            raise Bad('sending invitations needs your confirmation')
        idem = str(p.get('send_id') or '')
        if not re.match(r'^[A-Za-z0-9_-]{16,64}$', idem):
            raise Bad('missing send_id')
        row = self._cal(str(p.get('calendar') or ''))
        if not row['path']:
            raise Bad(row['why'] or 'this calendar can\'t send invitations')
        title, start, end, tz, loc, notes = self._times(p)
        people = CI.people(p.get('attendees'), own=self.own())
        if not people:
            raise Bad('add someone to invite')
        join, teams = self.meeting(row, p.get('online'), idem, title, start, end, tz)
        org = {'email': row['from'], 'name': p.get('_owner_name') or None}
        rec = self.inv.send(idem, row['path'], row['title'], org, title, start, end, tz, people, loc, notes, join,
                            meeting_key=(join or {}).get('idem'), teams=teams, dashboard_url=self.dashboard_url())
        return self.summary(rec)

    def update(self, p):
        if p.get('confirm') not in ('send', 'save'):
            raise Bad('a change needs your confirmation')
        uid = str(p.get('uid') or '')
        rec = self.inv.get(uid)
        if not rec:
            raise Bad('unknown invitation')
        title, start, end, tz, loc, notes = self._times(p)
        people = CI.people(p.get('attendees') if p.get('attendees') is not None else rec['attendees'], own=self.own())
        if not people:
            raise Bad('an invitation needs someone – cancel the event instead')
        moved = False
        if p.get('move_meeting') and rec.get('meeting'):
            r = self.svc.move(rec['meeting'], title, start, end, tz)
            moved = bool(r.get('updated'))
        rec = self.inv.update(uid, title, start, end, tz, people, loc, notes, tell=p['confirm'] == 'send')
        return dict(self.summary(rec), meeting_moved=moved)

    def cancel(self, p):
        if p.get('confirm') != 'send':
            raise Bad('a cancellation needs your confirmation')
        uid = str(p.get('uid') or '')
        rec = self.inv.cancel(uid, str(p.get('comment') or '')[:500])
        gone = None
        if p.get('delete_meeting') and rec.get('meeting'):
            gone = self.svc.remove(rec['meeting'])
        return {'uid': uid, 'title': rec.get('title'), 'meeting': gone}

    def add_meeting(self, p):
        """New event without invitees but with an online meeting: the link for Macuse's own event (url + notes)."""
        idem = str(p.get('send_id') or '')
        if not re.match(r'^[A-Za-z0-9_-]{16,64}$', idem):
            raise Bad('missing send_id')
        row = self._cal(str(p.get('calendar') or ''))
        title, start, end, tz, _, _ = self._times(p)
        if (p.get('online') or {}).get('provider') == 'teams' and row['kind'] != 'work':
            raise Bad('Teams only works on a work calendar')
        join, teams = self.meeting(dict(row, path=None), p.get('online'), idem, title, start, end, tz)
        return join

    def for_event(self, ev):
        """What the event sheet shows for an event: the invitation (if Axella sent it) and its answers."""
        rec = self.inv.match(ev)
        if not rec:
            return None
        out = self.summary(rec)
        try:
            out.update(self.inv.answers(rec['uid']))
        except Bad as e:
            out['answers_error'] = str(e)
        return out

    @staticmethod
    def summary(rec):
        j = rec.get('join') or {}
        return {'uid': rec.get('uid'), 'calendar': rec.get('calendar'), 'from': (rec.get('organizer') or {}).get('email'),
                'people': [{'email': a['email'], 'name': a.get('name')} for a in rec.get('attendees') or []],
                'join': {k: j.get(k) for k in ('join_url', 'passcode', 'code', 'dial_in', 'provider') if j.get(k)} or None,
                'meeting': rec.get('meeting'), 'path': rec.get('path'), 'repeat': bool(rec.get('repeat')),
                'cancelled': bool(rec.get('cancelled')), 'silent_save': rec.get('path') == 'icloud'}
