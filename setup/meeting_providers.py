"""Online meetings for Calendar's New event: every meeting service is a provider behind one small interface, so the
dialog, the invite, the event sheet and Meeting prep never know which service it is. Adding one (e.g. Webex) means
adding a class here – nothing else changes.

  create(title, start, end, tz) → {"join_url", "meeting_id", "dial_in"?, "passcode"?}
  update(meeting_id, title, start, end, tz)
  delete(meeting_id)            → {"deleted": bool, "why"?}
  capabilities()                → {"lobby", "passcode", "has_time", "dial_in", "can_send_invites"}
  status()                      → {"state": connected | needs_approval | not_connected | not_set_up, …}

What goes to a service: the title, start, end and time zone. Never notes, place, invitees or anything from mail
(invitees only through the work calendar's own server, calendar_invites.py). Every call is counted under What leaves
my home (note(provider, action)). Creating is idempotent per key: the same key never makes a second meeting.

"Paste a link" is not a provider: check_link() accepts an https link to a known meeting service only.
"""
import datetime
import json
import os
import re
import secrets
import threading
import urllib.parse

import oauth_flow as O

Bad = O.Bad
_LOCK = threading.Lock()


def _utc(iso):
    """'2027-03-04T10:00:00+01:00' → '2027-03-04T09:00:00Z'."""
    try:
        d = datetime.datetime.fromisoformat(str(iso).replace('Z', '+00:00'))
    except ValueError:
        raise Bad('a time is not valid')
    if d.tzinfo is None:
        d = d.astimezone()
    return d.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _minutes(start, end):
    a = datetime.datetime.fromisoformat(_utc(start).replace('Z', '+00:00'))
    b = datetime.datetime.fromisoformat(_utc(end).replace('Z', '+00:00'))
    if b <= a:
        raise Bad('the meeting ends before it starts')
    return max(1, int((b - a).total_seconds() // 60))


def _title(t):
    t = re.sub(r'[\x00-\x1f\x7f]', ' ', str(t or '')).strip()[:250]
    if not t:
        raise Bad('the meeting needs a title')
    return t


class Provider:
    key, label, offer = '', '', ''
    api = ''

    def __init__(self, auth, http_fn=None, note=None):
        self.auth = auth
        self.http = http_fn or O.http
        self.note = note or (lambda *a: None)

    def status(self):
        return self.auth.status(self.key)

    def _call(self, method, path, body=None, action=''):
        tok = self.auth.access_token(self.key)
        self.note(self.key, action or method)
        status, out = self.http(method, self.api + path, headers={'Authorization': 'Bearer ' + tok}, body=body)
        if status in (401,):
            raise Bad('%s needs you to connect again' % self.label)
        if status == 403:
            self._forbidden(out)
        if status >= 400:
            raise Bad('%s refused (%s)' % (self.label, status))
        return out

    def _forbidden(self, out):
        raise Bad('%s refused: not allowed for this account' % self.label)


class Teams(Provider):
    """Microsoft Graph, a work or school account (personal Microsoft accounts can't create Teams meetings here)."""
    key, label, offer = 'teams', 'Microsoft Teams', 'New Teams meeting'
    api = 'https://graph.microsoft.com/v1.0'

    def capabilities(self):
        return {'lobby': True, 'passcode': True, 'has_time': True, 'dial_in': True, 'can_send_invites': True}

    def _forbidden(self, out):
        if 'consent' in json.dumps(out).lower() or 'admin' in json.dumps(out).lower():
            self.auth.set_approval(self.key, 'needs_approval')
            raise Bad('Waiting for your IT to approve creating meetings')
        raise Bad('Microsoft Teams refused: this account can\'t create meetings')

    def create(self, title, start, end, tz):
        body = {'subject': _title(title), 'startDateTime': _utc(start), 'endDateTime': _utc(end),
                'joinMeetingIdSettings': {'isPasscodeRequired': True}}
        out = self._call('POST', '/me/onlineMeetings', body, 'create meeting')
        mid = out.get('id')
        if not mid or not str(out.get('joinWebUrl') or '').startswith('https://'):
            raise Bad('Microsoft Teams sent no meeting link')
        # the lobby: everyone except you waits until let in; only you present (PATCH is the documented way)
        self._call('PATCH', '/me/onlineMeetings/' + urllib.parse.quote(mid, safe=''),
                   {'lobbyBypassSettings': {'scope': 'organizer', 'isDialInBypassEnabled': False}, 'allowedPresenters': 'organizer'},
                   'set lobby')
        ac = out.get('audioConferencing') or {}
        jm = out.get('joinMeetingIdSettings') or {}
        return {'join_url': out['joinWebUrl'], 'meeting_id': mid, 'dial_in': ac.get('tollNumber') or None,
                'passcode': jm.get('passcode') or None, 'code': jm.get('joinMeetingId') or None, 'lobby': True}

    def update(self, meeting_id, title, start, end, tz):
        self._call('PATCH', '/me/onlineMeetings/' + urllib.parse.quote(str(meeting_id), safe=''),
                   {'subject': _title(title), 'startDateTime': _utc(start), 'endDateTime': _utc(end)}, 'move meeting')
        return {'updated': True}

    def delete(self, meeting_id):
        self._call('DELETE', '/me/onlineMeetings/' + urllib.parse.quote(str(meeting_id), safe=''), action='delete meeting')
        return {'deleted': True}


class GoogleMeet(Provider):
    """Meet REST API v2: a meeting space for trusted people (others knock). A space has no time and can't be deleted –
    its code expires after a year unused."""
    key, label, offer = 'google_meet', 'Google Meet', 'New Google Meet'
    api = 'https://meet.googleapis.com/v2'

    def capabilities(self):
        return {'lobby': True, 'passcode': False, 'has_time': False, 'dial_in': False, 'can_send_invites': False}

    def create(self, title, start, end, tz):
        _title(title), _minutes(start, end)          # checked, but a space takes neither
        out = self._call('POST', '/spaces', {'config': {'accessType': 'TRUSTED'}}, 'create meeting')
        uri = str(out.get('meetingUri') or '')
        if not uri.startswith('https://meet.google.com/'):
            raise Bad('Google Meet sent no meeting link')
        return {'join_url': uri, 'meeting_id': out.get('name'), 'code': out.get('meetingCode'), 'passcode': None,
                'dial_in': None, 'lobby': True}

    def update(self, meeting_id, title, start, end, tz):
        return {'updated': False, 'why': 'A Google Meet link has no time – nothing to move'}

    def delete(self, meeting_id):
        return {'deleted': False, 'why': 'A Google Meet link can\'t be deleted; it stops working after a year unused'}


class Zoom(Provider):
    """Zoom REST API v2, a user-managed (General) app on your own account: a passcode and the waiting room on."""
    key, label, offer = 'zoom', 'Zoom', 'New Zoom meeting'
    api = 'https://api.zoom.us/v2'

    def capabilities(self):
        return {'lobby': True, 'passcode': True, 'has_time': True, 'dial_in': True, 'can_send_invites': False}

    def create(self, title, start, end, tz):
        pw = ''.join(secrets.choice('abcdefghjkmnpqrstuvwxyz23456789') for _ in range(10))
        body = {'topic': _title(title), 'type': 2, 'start_time': _utc(start), 'duration': _minutes(start, end),
                'timezone': str(tz or 'UTC')[:60], 'password': pw,
                'settings': {'waiting_room': True, 'join_before_host': False}}
        out = self._call('POST', '/users/me/meetings', body, 'create meeting')
        uri = str(out.get('join_url') or '')
        if not re.match(r'^https://([a-z0-9-]+\.)?zoom\.us/', uri):
            raise Bad('Zoom sent no meeting link')
        dial = next((x.get('number') for x in (out.get('settings') or {}).get('global_dial_in_numbers') or [] if x.get('number')), None)
        return {'join_url': uri, 'meeting_id': str(out.get('id')), 'passcode': out.get('password') or pw, 'dial_in': dial,
                'code': str(out.get('id') or '') or None, 'lobby': bool((out.get('settings') or {}).get('waiting_room', True))}

    def update(self, meeting_id, title, start, end, tz):
        self._call('PATCH', '/meetings/' + urllib.parse.quote(str(meeting_id), safe=''),
                   {'topic': _title(title), 'start_time': _utc(start), 'duration': _minutes(start, end), 'timezone': str(tz or 'UTC')[:60]},
                   'move meeting')
        return {'updated': True}

    def delete(self, meeting_id):
        self._call('DELETE', '/meetings/' + urllib.parse.quote(str(meeting_id), safe=''), action='delete meeting')
        return {'deleted': True}


CLASSES = (Teams, GoogleMeet, Zoom)

# ---------- "Paste a link" ----------
KNOWN = re.compile(r'^(teams\.microsoft\.com|teams\.live\.com|meet\.google\.com|([a-z0-9-]+\.)?zoom\.us|facetime\.apple\.com|'
                   r'([a-z0-9-]+\.)?webex\.com|whereby\.com)$')


def check_link(url):
    """An https link to a known meeting service, or Bad. No user:password@, no control characters, at most 600 long."""
    u = str(url or '').strip()
    if not u or len(u) > 600 or re.search(r'[\x00-\x20\x7f<>"]', u):
        raise Bad('paste the whole meeting link')
    p = urllib.parse.urlsplit(u)
    host = (p.hostname or '').lower()
    if p.scheme != 'https' or p.username or p.password or not KNOWN.match(host):
        raise Bad('that isn\'t a link to a meeting service Axella knows (Teams, Meet, Zoom, FaceTime, Webex, Whereby)')
    return u


def service_of(url):
    host = (urllib.parse.urlsplit(str(url or '')).hostname or '').lower()
    for name, rx in (('Microsoft Teams', r'teams\.'), ('Google Meet', r'meet\.google'), ('Zoom', r'zoom\.us'),
                     ('FaceTime', r'facetime'), ('Webex', r'webex'), ('Whereby', r'whereby')):
        if re.search(rx, host):
            return name
    return None


class Services:
    """All providers, the per-calendar defaults, and the meetings made (state/online-meetings.json, chmod 600 –
    in SECRETS: it holds join links and invitees)."""

    def __init__(self, state_dir, auth, http_fn=None, note=None):
        self.file = os.path.join(state_dir, 'online-meetings.json')
        self.auth = auth
        self.providers = {c.key: c(auth, http_fn, note) for c in CLASSES}

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        d.setdefault('meetings', {})
        d.setdefault('defaults', {})
        return d

    def save(self, d):
        d['meetings'] = dict(sorted(d['meetings'].items(), key=lambda kv: kv[1].get('created', ''))[-500:])
        tmp = '%s.%d.tmp' % (self.file, os.getpid())
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)

    def provider(self, key):
        p = self.providers.get(str(key or ''))
        if not p:
            raise Bad('unknown meeting service')
        return p

    def offered(self, kind, allowed=None):
        """The services offered for a calendar of this kind (work/private): connected ones only, and Teams only for a
        work account. allowed: the services connected with that workplace's own account (protected workplaces)."""
        out = []
        for k, p in self.providers.items():
            st = p.status()
            ok = st['state'] == 'connected' and (k != 'teams' or kind == 'work') and (allowed is None or k in allowed)
            out.append({'key': k, 'label': p.label, 'offer': p.offer, 'state': st['state'], 'offered': ok,
                        'why': None if ok else ('Teams only works with a work account' if k == 'teams' and kind != 'work' and st['state'] == 'connected'
                                                else st.get('why') or {'not_connected': 'Not connected', 'not_set_up': 'Not set up'}.get(st['state'])),
                        'capabilities': p.capabilities()})
        return out

    def set_default(self, calendar, key):
        with _LOCK:
            d = self.load()
            if key in (None, '', 'none'):
                d['defaults'].pop(str(calendar)[:200], None)
            else:
                self.provider(key)
                d['defaults'][str(calendar)[:200]] = key
            self.save(d)
        return d['defaults']

    def create_once(self, idem, key, title, start, end, tz):
        """One meeting per key – a double tap or a resend gets the same meeting back."""
        if not re.match(r'^[A-Za-z0-9_-]{8,64}$', str(idem or '')):
            raise Bad('missing request key')
        with _LOCK:
            d = self.load()
            if idem in d['meetings']:
                return dict(d['meetings'][idem], repeat=True)
        m = self.provider(key).create(title, start, end, tz)
        rec = dict(m, provider=key, created=datetime.datetime.now().astimezone().isoformat(timespec='seconds'))
        with _LOCK:
            d = self.load()
            if idem in d['meetings']:              # made in the meantime by the same key: keep the first
                return dict(d['meetings'][idem], repeat=True)
            d['meetings'][idem] = rec
            self.save(d)
        return rec

    def find(self, idem):
        return self.load()['meetings'].get(str(idem or ''))

    def move(self, idem, title, start, end, tz):
        m = self.find(idem)
        if not m:
            raise Bad('unknown online meeting')
        return self.provider(m['provider']).update(m['meeting_id'], title, start, end, tz)

    def remove(self, idem):
        m = self.find(idem)
        if not m:
            raise Bad('unknown online meeting')
        r = self.provider(m['provider']).delete(m['meeting_id'])
        with _LOCK:
            d = self.load()
            if idem in d['meetings']:
                d['meetings'][idem]['deleted'] = bool(r.get('deleted'))
                self.save(d)
        return r
