"""Calendar invitations in mail: read the invite (.ics) from the message on the Mac mini, and build the standard reply
(iTIP METHOD:REPLY, RFC 5546) that Accept / Maybe / Decline sends to the organizer – on the owner's tap only, through
Mail like every other send (axella-actions.py "invite_respond").

Python 3.9 (the Mac mini's /usr/bin/python3): no 3.10+ syntax.
"""
import datetime
import email
import email.policy
import glob
import os
import re

try:
    from zoneinfo import ZoneInfo
except ImportError:                                    # pragma: no cover – 3.9 has it
    ZoneInfo = None

PARTSTAT = {'accepted': 'ACCEPTED', 'tentative': 'TENTATIVE', 'declined': 'DECLINED'}
SUBJECT = {'accepted': 'Accepted', 'tentative': 'Tentative', 'declined': 'Declined'}
MAX_ICS = 512 * 1024
# Outlook / Exchange send Windows zone names
WINDOWS_TZ = {
    'W. Europe Standard Time': 'Europe/Berlin', 'Romance Standard Time': 'Europe/Paris', 'Central Europe Standard Time': 'Europe/Budapest',
    'Central European Standard Time': 'Europe/Warsaw', 'GMT Standard Time': 'Europe/London', 'Greenwich Standard Time': 'Atlantic/Reykjavik',
    'FLE Standard Time': 'Europe/Helsinki', 'E. Europe Standard Time': 'Europe/Chisinau', 'GTB Standard Time': 'Europe/Bucharest',
    'Eastern Standard Time': 'America/New_York', 'Central Standard Time': 'America/Chicago', 'Mountain Standard Time': 'America/Denver',
    'Pacific Standard Time': 'America/Los_Angeles', 'UTC': 'UTC', 'Coordinated Universal Time': 'UTC',
    'Tokyo Standard Time': 'Asia/Tokyo', 'China Standard Time': 'Asia/Shanghai', 'India Standard Time': 'Asia/Kolkata',
    'AUS Eastern Standard Time': 'Australia/Sydney', 'E. Africa Standard Time': 'Africa/Nairobi',
}


class Bad(Exception):
    pass


# ---------- finding the .ics in a message ----------
def ics_from_message(raw):
    """The first text/calendar part (or .ics attachment) of an RFC 822 message, as text – else None."""
    msg = email.message_from_bytes(raw, policy=email.policy.compat32)
    for part in msg.walk():
        ctype = (part.get_content_type() or '').lower()
        name = (part.get_filename() or '').lower()
        if ctype in ('text/calendar', 'application/ics', 'application/x-ics') or name.endswith('.ics'):
            data = part.get_payload(decode=True)
            if data:
                cs = part.get_content_charset() or 'utf-8'
                try:
                    return data[:MAX_ICS].decode(cs, errors='replace')
                except LookupError:
                    return data[:MAX_ICS].decode('utf-8', errors='replace')
    return None


def ics_from_attachments(emlx_path):
    """Mail keeps big or not-yet-downloaded attachments next to the mailbox: …/Attachments/<id>/<n>/<file>.ics"""
    base = os.path.basename(emlx_path).split('.')[0]
    root = os.path.join(os.path.dirname(os.path.dirname(emlx_path)), 'Attachments', base)
    for f in sorted(glob.glob(os.path.join(root, '*', '*.ics'))):
        if os.path.getsize(f) <= MAX_ICS:
            with open(f, encoding='utf-8', errors='replace') as fh:
                return fh.read()
    return None


# ---------- reading iCalendar ----------
def _unfold(text):
    return re.sub(r'\r?\n[ \t]', '', str(text or '')).replace('\r\n', '\n').replace('\r', '\n').split('\n')


MAX_LINE = 4000                                  # characters where a line's name and parameters must end


def _line(l):
    """'DTSTART;TZID=Europe/Copenhagen:20261105T090000' → ('DTSTART', {'TZID': 'Europe/Copenhagen'}, '20261105T090000')"""
    # a quoted parameter may hold a colon (SENT-BY="mailto:…", CN="Team: Sales") – the value starts after the first
    # colon outside quotes (RFC 5545 3.1)
    # no comma in an unquoted value, so each one splits only one way (no backtracking blow-up on a crafted line).
    # Only the name and parameters are matched, within the first MAX_LINE characters; the value (a long DESCRIPTION
    # with a join link) is everything after them
    m = re.match(r'([A-Za-z0-9-]+)((?:;[A-Za-z0-9-]+=(?:"[^"]*"|[^";:,]*)(?:,(?:"[^"]*"|[^";:,]*))*)*):', l[:MAX_LINE])
    if not m:
        return None
    params = {}
    for pm in re.finditer(r';([A-Za-z0-9-]+)=("[^"]*"|[^;]*)', m.group(2)):
        params[pm.group(1).upper()] = pm.group(2).strip('"')
    return m.group(1).upper(), params, l[m.end():]


def _text(v):
    return re.sub(r'\\([,;\\])', r'\1', str(v or '').replace('\\n', '\n').replace('\\N', '\n')).strip()


def _when(value, params):
    """(datetime aware or date, all_day)"""
    v = value.strip()
    if params.get('VALUE') == 'DATE' or re.match(r'^\d{8}$', v):
        return datetime.date(int(v[:4]), int(v[4:6]), int(v[6:8])), True
    d = datetime.datetime.strptime(v[:15], '%Y%m%dT%H%M%S')
    if v.endswith('Z'):
        return d.replace(tzinfo=datetime.timezone.utc), False
    tz = params.get('TZID')
    if tz and ZoneInfo:
        for name in (tz, WINDOWS_TZ.get(tz), tz.split('/', 1)[-1] if tz.startswith('/') else None):
            if not name:
                continue
            try:
                return d.replace(tzinfo=ZoneInfo(name)), False
            except Exception:
                continue
    return d.astimezone(), False                       # floating or unknown zone: the Mac mini's own


def _mail(v):
    return re.sub(r'^mailto:', '', str(v or '').strip(), flags=re.I).strip().lower()


def parse(ics):
    """The first VEVENT of an invitation: what Accept needs, plus the raw lines the reply copies."""
    lines = _unfold(ics)
    method, ev, depth, raw = None, None, 0, {}
    for l in lines:
        p = _line(l)
        if not p:
            continue
        name, params, value = p
        if name == 'METHOD' and ev is None:
            method = value.strip().upper()
        elif name == 'BEGIN' and value.strip().upper() == 'VEVENT' and ev is None:
            ev, depth = {'attendees': []}, 1
        elif ev is not None and depth == 1:
            if name == 'BEGIN':
                depth += 1                             # a VALARM inside the event
                continue
            if name == 'END' and value.strip().upper() == 'VEVENT':
                break
            if name in ('UID', 'SEQUENCE', 'RECURRENCE-ID', 'DTSTART', 'DTEND', 'ORGANIZER', 'RRULE'):
                raw[name] = l
            if name == 'UID':
                ev['uid'] = value.strip()
            elif name == 'SEQUENCE':
                ev['sequence'] = int(re.sub(r'\D', '', value) or 0)
            elif name == 'SUMMARY':
                ev['summary'] = _text(value)
            elif name == 'LOCATION':
                ev['location'] = _text(value)
            elif name == 'DESCRIPTION':
                ev['description'] = _text(value)[:4000]
            elif name == 'URL':
                ev['url'] = value.strip()
            elif name == 'STATUS':
                ev['status'] = value.strip().upper()
            elif name == 'RRULE':
                ev['recurring'] = True
            elif name in ('DTSTART', 'DTEND'):
                try:
                    ev[name.lower()], ev['all_day'] = _when(value, params)
                except ValueError:
                    raise Bad('the invite has a date Axella cannot read')
            elif name == 'ORGANIZER':
                ev['organizer'] = {'email': _mail(value), 'name': _text(params.get('CN')) or _mail(value)}
            elif name == 'ATTENDEE':
                ev['attendees'].append({'email': _mail(value), 'name': _text(params.get('CN')) or _mail(value),
                                        'partstat': (params.get('PARTSTAT') or 'NEEDS-ACTION').upper(),
                                        'line': l})
        elif ev is not None and name == 'END':
            depth -= 1
    if not ev or not ev.get('uid') or not ev.get('dtstart'):
        raise Bad('no calendar invitation found in this mail')
    if 'dtend' not in ev:
        ev['dtend'] = ev['dtstart'] + (datetime.timedelta(days=1) if ev.get('all_day') else datetime.timedelta(hours=1))
    ev['method'] = method or 'REQUEST'
    ev['raw'] = raw
    ev.setdefault('sequence', 0)
    ev.setdefault('summary', '(no title)')
    return ev


def me_in(ev, own):
    """The owner's attendee entry (matched on any of the owner's addresses), or None."""
    own = {a.lower() for a in own if a}
    return next((a for a in ev['attendees'] if a['email'] in own), None)


def public(ev, own):
    """What the dashboard shows – no raw lines."""
    me = me_in(ev, own)
    iso = lambda d: d.isoformat() if isinstance(d, datetime.date) else None
    local = lambda d: d.astimezone().isoformat(timespec='minutes') if isinstance(d, datetime.datetime) else d.isoformat()
    return {'uid': ev['uid'], 'summary': ev['summary'], 'start': local(ev['dtstart']), 'end': local(ev['dtend']),
            'all_day': bool(ev.get('all_day')), 'location': ev.get('location') or '', 'url': ev.get('url') or '',
            'description': ev.get('description') or '', 'organizer': ev.get('organizer'), 'recurring': bool(ev.get('recurring')),
            'method': ev['method'], 'cancelled': ev['method'] == 'CANCEL' or ev.get('status') == 'CANCELLED',
            'attendees': [{'name': a['name'], 'email': a['email'], 'partstat': a['partstat']} for a in ev['attendees']][:50],
            'me': {'email': me['email'], 'partstat': me['partstat']} if me else None, 'raw_start': iso(ev['dtstart'])}


# ---------- the reply ----------
def _esc(v):
    return str(v or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def _fold(l):
    out, b = [], l.encode('utf-8')
    while len(b) > 75:
        cut = 75
        while cut > 0 and (b[cut] & 0xC0) == 0x80:      # never split a UTF-8 character
            cut -= 1
        out.append(b[:cut].decode('utf-8'))
        b = b' ' + b[cut:]
    out.append(b.decode('utf-8'))
    return '\r\n'.join(out)


def reply_ics(ev, me_email, me_name, response, now=None):
    """METHOD:REPLY with the owner's PARTSTAT – UID, SEQUENCE, RECURRENCE-ID, DTSTART and ORGANIZER as the invite had them."""
    if response not in PARTSTAT:
        raise Bad('accepted, tentative or declined')
    if not ev.get('organizer') or not ev['organizer'].get('email'):
        raise Bad('the invite has no organizer to answer')
    now = (now or datetime.datetime.now(datetime.timezone.utc)).strftime('%Y%m%dT%H%M%SZ')
    raw = ev['raw']
    cn = (';CN="%s"' % me_name.replace('"', "'")) if me_name else ''
    lines = ['BEGIN:VCALENDAR', 'PRODID:-//Axella//Meeting reply//EN', 'VERSION:2.0', 'CALSCALE:GREGORIAN', 'METHOD:REPLY',
             'BEGIN:VEVENT', raw.get('UID') or 'UID:' + ev['uid'], 'SEQUENCE:%d' % ev.get('sequence', 0), 'DTSTAMP:' + now]
    for k in ('RECURRENCE-ID', 'DTSTART', 'DTEND', 'ORGANIZER'):
        if raw.get(k):
            lines.append(raw[k])
    lines += ['SUMMARY:' + _esc(ev.get('summary')),
              'ATTENDEE;PARTSTAT=%s%s:mailto:%s' % (PARTSTAT[response], cn, me_email),
              'END:VEVENT', 'END:VCALENDAR']
    return '\r\n'.join(_fold(l) for l in lines) + '\r\n'


def reply_text(ev, owner_name, response):
    """The plain-text part, for people whose mail program doesn't read the calendar part."""
    verb = {'accepted': 'accepted', 'tentative': 'tentatively accepted', 'declined': 'declined'}[response]
    d = ev['dtstart']
    when = d.astimezone().strftime('%A %d %B %Y, %H:%M') if isinstance(d, datetime.datetime) else d.strftime('%A %d %B %Y')
    return '%s has %s the invitation:\n\n%s\n%s%s\n' % (owner_name or 'The invitee', verb, ev.get('summary'), when.replace(' 0', ' '),
                                                       ('\n' + ev['location']) if ev.get('location') else '')


def reply_subject(ev, response):
    return '%s: %s' % (SUBJECT[response], ev.get('summary') or 'Invitation')[:300]
