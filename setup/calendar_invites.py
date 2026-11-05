"""Invitees for Calendar's New event / Edit event: the calendar's own server sends the invitations, so the people
invited get a real invitation (Accept / Decline), and their answers come back to that server.

  - private (iCloud) calendar → iCloud CalDAV (caldav.icloud.com, an app-specific password in the Keychain). The event
    is stored with ORGANIZER = your iCloud address and the ATTENDEE lines; iCloud sends the invitations itself
    (server-side scheduling, RFC 6638), as Calendar does. Update = PUT with SEQUENCE+1 (iCloud sends the update;
    "Save without telling them" marks the people SCHEDULE-AGENT=CLIENT for that save). Cancel = DELETE (iCloud sends
    the cancellation).
  - work (Microsoft 365) calendar → Microsoft Graph /me/events with the attendees; Exchange sends the invitations, and
    "New Teams meeting" makes the Teams meeting on the same event (lobby set right after). Exchange always tells the
    people about a change, so there is no silent save there. Cancel = /cancel.

Nothing is sent before the owner's tap on Send invites / Send update / Send cancellation (axella-actions.py checks the
confirm word and a send_id). Contacts and invitees never go to Claude. state/calendar-invites.json (chmod 600,
SECRETS) keeps what was sent: uid, server reference, sequence, the people and the meeting key.
"""
import base64
import datetime
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

try:
    from zoneinfo import ZoneInfo
except ImportError:                                  # pragma: no cover (Python 3.9 has it)
    ZoneInfo = None

import oauth_flow as O

Bad = O.Bad
CALDAV_SERVICE = 'axella-caldav'
ICLOUD = 'https://caldav.icloud.com/'
MAX_PEOPLE = 50
_LOCK = threading.Lock()
EMAIL = re.compile(r'^[A-Za-z0-9._%+\'-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$')


# ---------- people and times ----------
def people(lst, own=()):
    """[{"email", "name"}] – each address once, valid, not one of your own, at most 50."""
    out, seen = [], set(a.lower() for a in own)
    for x in lst or []:
        if isinstance(x, str):
            x = {'email': x}
        e = str((x or {}).get('email') or '').strip()
        n = re.sub(r'[\x00-\x1f\x7f"<>;:\\,]', ' ', str((x or {}).get('name') or '')).strip()[:80]
        if not EMAIL.match(e) or re.search(r'(^|[.@])(no-?reply|donotreply)', e, re.I):
            raise Bad('not an address an invitation can go to: %s' % e[:80])
        if e.lower() in seen:
            continue
        seen.add(e.lower())
        out.append({'email': e, 'name': n or None})
    if len(out) > MAX_PEOPLE:
        raise Bad('at most %d people per invitation' % MAX_PEOPLE)
    return out


def _dt(iso):
    try:
        d = datetime.datetime.fromisoformat(str(iso).replace('Z', '+00:00'))
    except ValueError:
        raise Bad('a time is not valid')
    return d if d.tzinfo else d.astimezone()


def _zone(tz):
    if ZoneInfo and tz:
        try:
            return ZoneInfo(str(tz)), str(tz)
        except Exception:
            pass
    return None, None


# ---------- iCalendar ----------
def _esc(v):
    return str(v or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\r\n', '\\n').replace('\n', '\\n')


def _fold(line):
    b = line.encode('utf-8')
    if len(b) <= 75:
        return line
    out, cur = [], b''
    for ch in line:
        c = ch.encode('utf-8')
        if len(cur) + len(c) > (75 if not out else 74):
            out.append(cur.decode('utf-8'))
            cur = b''
        cur += c
    out.append(cur.decode('utf-8'))
    return '\r\n '.join(out)


def _param(v):
    v = re.sub(r'["\x00-\x1f\x7f]', '', str(v or ''))[:80]
    return '"%s"' % v


def vtimezone(tzname, year):
    """A VTIMEZONE for one year, built from the zone's own transitions (no RRULE needed for a single event)."""
    z, name = _zone(tzname)
    if not z:
        return []
    jan = datetime.datetime(year, 1, 1, tzinfo=z)
    trans, prev = [], jan.utcoffset()
    t = datetime.datetime(year, 1, 1, tzinfo=datetime.timezone.utc)
    while t.year == year:                            # hour steps around a change, day steps otherwise
        nxt = t + datetime.timedelta(days=1)
        if nxt.astimezone(z).utcoffset() != prev:
            h = t
            while h.astimezone(z).utcoffset() == prev:
                h += datetime.timedelta(hours=1)
            new = h.astimezone(z).utcoffset()
            trans.append((h.astimezone(z).replace(tzinfo=None), prev, new, h.astimezone(z).dst() != datetime.timedelta(0)))
            prev, t = new, h
            continue
        t = nxt
    off = lambda td: ('+' if td >= datetime.timedelta(0) else '-') + '%02d%02d' % divmod(abs(int(td.total_seconds())) // 60, 60)
    lines = ['BEGIN:VTIMEZONE', 'TZID:' + name]
    if not trans:
        o = off(jan.utcoffset())
        lines += ['BEGIN:STANDARD', 'DTSTART:19700101T000000', 'TZOFFSETFROM:' + o, 'TZOFFSETTO:' + o, 'END:STANDARD']
    for local, a, b, dst in trans:
        kind = 'DAYLIGHT' if dst else 'STANDARD'
        lines += ['BEGIN:' + kind, 'DTSTART:' + local.strftime('%Y%m%dT%H%M%S'), 'TZOFFSETFROM:' + off(a), 'TZOFFSETTO:' + off(b), 'END:' + kind]
    return lines + ['END:VTIMEZONE']


def event_ics(uid, seq, title, start, end, tz, organizer, attendees, location='', notes='', join=None, url=None,
              method=None, silent=False, now=None):
    """One VEVENT. method None = the object stored on a CalDAV server; 'REQUEST' / 'CANCEL' = an iMIP message."""
    s, e = _dt(start), _dt(end)
    if e <= s:
        raise Bad('the event ends before it starts')
    z, name = _zone(tz)
    now = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(datetime.timezone.utc)

    def when(prop, d):
        if z:
            return '%s;TZID=%s:%s' % (prop, name, d.astimezone(z).strftime('%Y%m%dT%H%M%S'))
        return '%s:%s' % (prop, d.astimezone(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))

    desc = str(notes or '').strip()
    if join:
        lines_ = ['Join: ' + join['join_url']]
        if join.get('code'):
            lines_.append('Meeting ID: %s' % join['code'])
        if join.get('passcode'):
            lines_.append('Passcode: %s' % join['passcode'])
        if join.get('dial_in'):
            lines_.append('Dial in: %s' % join['dial_in'])
        desc = '\n'.join(lines_) + ('\n\n' + desc if desc else '')
    L = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Axella//Calendar invites//EN', 'CALSCALE:GREGORIAN']
    if method:
        L.append('METHOD:' + method)
    if z:
        L += vtimezone(name, s.astimezone(z).year)
    L += ['BEGIN:VEVENT', 'UID:' + uid, 'SEQUENCE:%d' % int(seq), 'DTSTAMP:' + now.strftime('%Y%m%dT%H%M%SZ'),
          when('DTSTART', s), when('DTEND', e), 'SUMMARY:' + _esc(title)]
    if location:
        L.append('LOCATION:' + _esc(location))
    if desc:
        L.append('DESCRIPTION:' + _esc(desc))
    if url:
        L.append('URL:' + url)
    if method == 'CANCEL':
        L.append('STATUS:CANCELLED')
    org = organizer['email']
    L.append('ORGANIZER;CN=%s:mailto:%s' % (_param(organizer.get('name') or org), org))
    L.append('ATTENDEE;CN=%s;ROLE=CHAIR;PARTSTAT=ACCEPTED:mailto:%s' % (_param(organizer.get('name') or org), org))
    for a in attendees:
        extra = ';SCHEDULE-AGENT=CLIENT' if silent else ''
        L.append('ATTENDEE;CN=%s;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE%s:mailto:%s' % (
            _param(a.get('name') or a['email']), extra, a['email']))
    L += ['END:VEVENT', 'END:VCALENDAR']
    return '\r\n'.join(_fold(x) for x in L) + '\r\n'


PARTSTAT = {'ACCEPTED': 'accepted', 'DECLINED': 'declined', 'TENTATIVE': 'maybe', 'NEEDS-ACTION': 'none', 'DELEGATED': 'none'}


def answers_ics(ics, organizer=''):
    """[{"email", "answer"}] from a stored event's ATTENDEE lines (PARTSTAT), organizer left out."""
    text = re.sub(r'\r?\n[ \t]', '', str(ics or ''))[:500000]
    out = []
    for m in re.finditer(r'^ATTENDEE([^:\r\n]*):mailto:([^\r\n]+?)\r?$', text, re.M | re.I):
        email = m.group(2).strip()
        if email.lower() == organizer.lower():
            continue
        ps = re.search(r';PARTSTAT=([A-Z-]+)', m.group(1), re.I)
        out.append({'email': email, 'answer': PARTSTAT.get((ps.group(1) if ps else 'NEEDS-ACTION').upper(), 'none')})
    return out


def answers_line(ans, names=None):
    """'Lee accepted · Robin hasn't answered' – first names from the invite list, else the address."""
    names = {k.lower(): v for k, v in (names or {}).items()}
    word = {'accepted': 'accepted', 'declined': 'declined', 'maybe': 'said maybe', 'none': 'hasn\'t answered'}
    parts = []
    for a in ans:
        who = (names.get(a['email'].lower()) or a['email']).split(' ')[0]
        parts.append('%s %s' % (who, word.get(a['answer'], 'hasn\'t answered')))
    return ' · '.join(parts)


# ---------- iCloud CalDAV ----------
class CalDav:
    """The smallest CalDAV client iCloud needs: find the calendar by its title, then PUT / GET / DELETE one event."""
    NS = {'d': 'DAV:', 'c': 'urn:ietf:params:xml:ns:caldav'}

    def __init__(self, keychain, raw_http=None, note=None):
        self.kc = keychain
        self.raw = raw_http or raw_http_default
        self.note = note or (lambda *a: None)
        self._home = None

    def login(self):
        c = self.kc.get(CALDAV_SERVICE, 'icloud')
        if not isinstance(c, dict) or not c.get('apple_id') or not c.get('password'):
            raise Bad('iCloud invites are not set up – run tools/meeting-services.py on the Mac mini')
        return c

    def configured(self):
        try:
            self.login()
            return True
        except Bad:
            return False

    def _req(self, method, url, body=None, headers=None, action=''):
        c = self.login()
        if not url.startswith('https://') or not re.match(r'^https://([a-z0-9-]+\.)*icloud\.com(:443)?/', url):
            raise Bad('not an iCloud address')
        h = {'Authorization': 'Basic ' + base64.b64encode(('%s:%s' % (c['apple_id'], c['password'])).encode()).decode()}
        h.update(headers or {})
        self.note('icloud', action or method)
        return self.raw(method, url, h, body)

    def _xml(self, text):
        try:
            return ET.fromstring(text[:2_000_000])
        except ET.ParseError:
            raise Bad('iCloud sent something unexpected')

    def _prop(self, url, body, depth='0'):
        st, text, _ = self._req('PROPFIND', url, body.encode(), {'Depth': depth, 'Content-Type': 'application/xml; charset=utf-8'}, 'find calendar')
        if st == 401:
            raise Bad('iCloud didn\'t accept the app-specific password – make a new one (SETUP "Meeting services")')
        if st not in (207, 200):
            raise Bad('iCloud refused (%s)' % st)
        return self._xml(text)

    def calendar_url(self, title):
        if not self._home:
            x = self._prop(ICLOUD, '<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>')
            href = x.find('.//d:current-user-principal/d:href', self.NS)
            if href is None or not href.text:
                raise Bad('iCloud gave no calendar account')
            principal = urllib.parse.urljoin(ICLOUD, href.text.strip())
            x = self._prop(principal, '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><c:calendar-home-set/></d:prop></d:propfind>')
            h = x.find('.//c:calendar-home-set/d:href', self.NS)
            if h is None or not h.text:
                raise Bad('iCloud gave no calendar home')
            self._home = urllib.parse.urljoin(principal, h.text.strip())
        x = self._prop(self._home, '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:displayname/>'
                                   '<d:resourcetype/></d:prop></d:propfind>', depth='1')
        for r in x.findall('d:response', self.NS):
            name = r.find('.//d:displayname', self.NS)
            is_cal = r.find('.//d:resourcetype/c:calendar', self.NS) is not None
            href = r.find('d:href', self.NS)
            if is_cal and name is not None and (name.text or '').strip() == title and href is not None:
                return urllib.parse.urljoin(self._home, href.text.strip())
        raise Bad('the calendar "%s" isn\'t on iCloud' % title[:60])

    def put(self, url, ics, etag=None):
        h = {'Content-Type': 'text/calendar; charset=utf-8'}
        h.update({'If-Match': etag} if etag else {'If-None-Match': '*'})
        st, _, hdrs = self._req('PUT', url, ics.encode('utf-8'), h, 'save event with invitees')
        if st == 412:
            raise Bad('the event was changed elsewhere – open it again')
        if st not in (200, 201, 204):
            raise Bad('iCloud refused the event (%s)' % st)
        return hdrs.get('etag') or hdrs.get('ETag')

    def get(self, url):
        st, text, hdrs = self._req('GET', url, action='read answers')
        if st == 404:
            return None, None
        if st != 200:
            raise Bad('iCloud refused (%s)' % st)
        return text, hdrs.get('etag') or hdrs.get('ETag')

    def delete(self, url, etag=None):
        st, _, _ = self._req('DELETE', url, headers={'If-Match': etag} if etag else {}, action='cancel event')
        if st not in (200, 204, 404):
            raise Bad('iCloud refused (%s)' % st)


def raw_http_default(method, url, headers, body, timeout=20):
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(2_000_000).decode('utf-8', 'replace'), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read(200_000).decode('utf-8', 'replace'), {k.lower(): v for k, v in e.headers.items()}
    except (urllib.error.URLError, OSError) as e:
        raise Bad('could not reach iCloud (%s)' % type(e).__name__)


# ---------- Microsoft Graph (work calendar) ----------
GRAPH = 'https://graph.microsoft.com/v1.0'
GRAPH_ANSWER = {'accepted': 'accepted', 'declined': 'declined', 'tentativelyAccepted': 'maybe', 'none': 'none', 'notResponded': 'none',
                'organizer': None}


class Graph:
    def __init__(self, auth, http_fn=None, note=None):
        self.auth = auth
        self.http = http_fn or O.http
        self.note = note or (lambda *a: None)

    def _call(self, method, path, body=None, action=''):
        tok = self.auth.access_token('teams')
        self.note('teams', action or method)
        st, out = self.http(method, GRAPH + path, headers={'Authorization': 'Bearer ' + tok, 'Prefer': 'outlook.timezone="UTC"'}, body=body)
        if st == 403:
            if re.search(r'consent|admin', json.dumps(out), re.I):
                self.auth.set_approval('teams', 'needs_approval')
                raise Bad('Waiting for your IT to approve Axella for your work calendar')
            raise Bad('Microsoft refused: not allowed for this account')
        if st == 401:
            raise Bad('Microsoft Teams needs you to connect again')
        if st >= 400:
            raise Bad('Microsoft refused (%s)' % st)
        return out

    @staticmethod
    def _utc(iso):
        return {'dateTime': _dt(iso).astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': 'UTC'}

    def body(self, title, start, end, attendees, location, notes, teams, join=None):
        text = str(notes or '').strip()
        if join and not teams:
            text = 'Join: %s%s%s' % (join['join_url'], ('\nPasscode: %s' % join['passcode']) if join.get('passcode') else '',
                                     ('\n\n' + text) if text else '')
        b = {'subject': str(title)[:250], 'start': self._utc(start), 'end': self._utc(end),
             'attendees': [{'emailAddress': {'address': a['email'], **({'name': a['name']} if a.get('name') else {})}, 'type': 'required'}
                           for a in attendees], 'allowNewTimeProposals': True,
             'body': {'contentType': 'text', 'content': text}}
        if location:
            b['location'] = {'displayName': str(location)[:250]}
        if teams:
            b.update(isOnlineMeeting=True, onlineMeetingProvider='teamsForBusiness')
        return b

    def events_path(self, calendar):
        """/me/events for the default calendar, /me/calendars/{id}/events for another one – found by its name."""
        if not calendar:
            return '/me/events'
        cals = self._call('GET', '/me/calendars?$select=id,name,isDefaultCalendar', action='find calendar').get('value') or []
        c = next((x for x in cals if x.get('name') == calendar), None)
        if not c:
            raise Bad('the calendar "%s" isn\'t in your Microsoft 365 account' % str(calendar)[:60])
        return '/me/events' if c.get('isDefaultCalendar') else '/me/calendars/%s/events' % urllib.parse.quote(c['id'], safe='')

    def create(self, idem, title, start, end, attendees, location, notes, teams, join=None, calendar=None):
        b = self.body(title, start, end, attendees, location, notes, teams, join)
        b['transactionId'] = idem                       # Graph's own guard: the same key never makes a second event
        out = self._call('POST', self.events_path(calendar), b, 'create event with invitees')
        jurl = ((out.get('onlineMeeting') or {}).get('joinUrl') or '') if teams else ''
        if teams and jurl.startswith('https://'):
            self.lobby(jurl)
        return {'graph_id': out.get('id'), 'uid': out.get('iCalUId'), 'join_url': jurl or None}

    def lobby(self, join_url):
        """Everyone but you waits in the lobby; only you present. A failure here never undoes the event."""
        try:
            q = urllib.parse.quote("JoinWebUrl eq '%s'" % join_url.replace("'", "''"), safe='')
            found = self._call('GET', '/me/onlineMeetings?$filter=' + q, action='find meeting')
            m = next(iter(found.get('value') or []), None)
            if m and m.get('id'):
                self._call('PATCH', '/me/onlineMeetings/' + urllib.parse.quote(m['id'], safe=''),
                           {'lobbyBypassSettings': {'scope': 'organizer', 'isDialInBypassEnabled': False}, 'allowedPresenters': 'organizer'},
                           'set lobby')
                return True
        except Bad:
            pass
        return False

    def update(self, graph_id, title, start, end, attendees, location, notes):
        b = self.body(title, start, end, attendees, location, notes, False)
        b.pop('allowNewTimeProposals', None)
        self._call('PATCH', '/me/events/' + urllib.parse.quote(graph_id, safe=''), b, 'update event with invitees')

    def cancel(self, graph_id, comment=''):
        self._call('POST', '/me/events/%s/cancel' % urllib.parse.quote(graph_id, safe=''), {'comment': str(comment or '')[:500]},
                   'cancel event')

    def answers(self, graph_id, own=''):
        out = self._call('GET', '/me/events/%s?$select=attendees' % urllib.parse.quote(graph_id, safe=''), action='read answers')
        res = []
        for a in out.get('attendees') or []:
            email = ((a.get('emailAddress') or {}).get('address') or '')
            ans = GRAPH_ANSWER.get(((a.get('status') or {}).get('response') or 'none'), 'none')
            if email and ans is not None and email.lower() != own.lower():
                res.append({'email': email, 'answer': ans})
        return res


# ---------- what was sent ----------
class Invites:
    def __init__(self, state_dir, caldav, graph):
        self.file = os.path.join(state_dir, 'calendar-invites.json')
        self.caldav, self.graph = caldav, graph

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        return d if isinstance(d, dict) and isinstance(d.get('events'), dict) else {'events': {}}

    def save(self, d):
        d['events'] = dict(sorted(d['events'].items(), key=lambda kv: kv[1].get('end', ''))[-1000:])
        tmp = '%s.%d.tmp' % (self.file, os.getpid())
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)

    def get(self, uid):
        return self.load()['events'].get(str(uid or ''))

    def match(self, ev):
        """The record behind a dashboard event: by the invite link in its URL, else same calendar, title and start minute."""
        evs = self.load()['events']
        m = re.search(r'[?&]invite=([A-Za-z0-9-]{8,80})', str(ev.get('url') or ''))
        if m and m.group(1) in evs:
            return evs[m.group(1)]
        st = str(ev.get('start') or '')[:16]
        for r in evs.values():
            if r.get('calendar') == ev.get('calendar') and r.get('title') == ev.get('title') and str(r.get('start_local') or '')[:16] == st:
                return r
        return None

    def send(self, idem, path, calendar, organizer, title, start, end, tz, attendees, location='', notes='', join=None,
             meeting_key=None, teams=False, dashboard_url=None):
        """Create the event with its invitees – once per key."""
        if not attendees:
            raise Bad('no one to invite')
        with _LOCK:
            d = self.load()
            for r in d['events'].values():
                if r.get('idem') == idem:
                    return dict(r, repeat=True)
        rec = {'idem': idem, 'path': path, 'calendar': calendar, 'organizer': organizer, 'title': title, 'start': start, 'end': end,
               'start_local': start, 'tz': tz, 'attendees': attendees, 'location': location or '', 'meeting': meeting_key,
               'join': join, 'sent': datetime.datetime.now().astimezone().isoformat(timespec='seconds'), 'sequence': 0}
        if path == 'icloud':
            uid = str(uuid.uuid4()).upper()
            url = (dashboard_url.rstrip('/') + '/?v=calendar&invite=' + uid) if dashboard_url and dashboard_url.startswith('https://') else None
            cal = self.caldav.calendar_url(calendar)
            href = cal.rstrip('/') + '/' + uid + '.ics'
            etag = self.caldav.put(href, event_ics(uid, 0, title, start, end, tz, organizer, attendees, location, notes, join, url))
            rec.update(uid=uid, href=href, etag=etag, link=url)
        elif path == 'graph':
            r = self.graph.create(idem, title, start, end, attendees, location, notes, teams, join, calendar)
            rec.update(uid=r['uid'] or ('graph-' + idem), graph_id=r['graph_id'])
            if r.get('join_url'):
                rec['join'] = {'join_url': r['join_url'], 'provider': 'teams'}
        else:
            raise Bad('this calendar can\'t send invitations')
        with _LOCK:
            d = self.load()
            d['events'][rec['uid']] = rec
            self.save(d)
        return rec

    def update(self, uid, title, start, end, tz, attendees, location='', notes='', tell=True):
        with _LOCK:
            rec = self.load()['events'].get(uid)
        if not rec:
            raise Bad('unknown invitation')
        if rec.get('cancelled'):
            raise Bad('that event was cancelled')
        rec = dict(rec, title=title, start=start, end=end, start_local=start, tz=tz, attendees=attendees, location=location or '')
        if rec['path'] == 'icloud':
            rec['sequence'] = int(rec.get('sequence') or 0) + 1
            ics = event_ics(uid, rec['sequence'], title, start, end, tz, rec['organizer'], attendees, location, notes, rec.get('join'),
                            rec.get('link'), silent=not tell)
            try:
                rec['etag'] = self.caldav.put(rec['href'], ics, rec.get('etag') or '*')
            except Bad as e:
                if 'changed elsewhere' not in str(e):
                    raise
                _, etag = self.caldav.get(rec['href'])    # an answer from someone changes the stored event – take its tag
                rec['etag'] = self.caldav.put(rec['href'], ics, etag)
        else:
            if not tell:
                raise Bad('a work calendar always tells the people about a change')
            self.graph.update(rec['graph_id'], title, start, end, attendees, location, notes)
        rec['updated'] = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
        with _LOCK:
            d = self.load()
            d['events'][uid] = rec
            self.save(d)
        return rec

    def cancel(self, uid, comment=''):
        with _LOCK:
            rec = self.load()['events'].get(uid)
        if not rec:
            raise Bad('unknown invitation')
        if rec['path'] == 'icloud':
            _, etag = self.caldav.get(rec['href'])
            self.caldav.delete(rec['href'], etag)
        else:
            self.graph.cancel(rec['graph_id'], comment)
        with _LOCK:
            d = self.load()
            if uid in d['events']:
                d['events'][uid]['cancelled'] = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
                self.save(d)
        return rec

    def answers(self, uid):
        rec = self.get(uid)
        if not rec or rec.get('cancelled'):
            return {'answers': [], 'line': ''}
        if rec['path'] == 'icloud':
            text, _ = self.caldav.get(rec['href'])
            ans = answers_ics(text, rec['organizer']['email']) if text else []
        else:
            ans = self.graph.answers(rec['graph_id'], rec['organizer'].get('email') or '')
        names = {a['email']: a.get('name') or a['email'] for a in rec.get('attendees') or []}
        return {'answers': ans, 'line': answers_line(ans, names)}
