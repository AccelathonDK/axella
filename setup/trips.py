"""Trips, part one (feature pack Nov 2026 §5): "Scan mail for upcoming trips" – booking confirmations already in your
mail, upcoming only, grouped into SUGGESTED trips you confirm. Found on the Mac mini by rules, never by Claude.

- Candidates: Mail's index – subjects that look like a booking (EN/DA/DE/SV/NO) or a known travel sender, last
  MONTHS months, never a private or hidden contact's mail (axella-actions.py filters before anything is read).
- Bookings: the schema.org reservation data most airlines, hotels, booking sites and ticket shops put in the mail
  (FlightReservation, LodgingReservation, TrainReservation, RentalCarReservation, BusReservation, BoatReservation,
  EventReservation …). Without that, a known travel sender's mail with a booking reference and dates is taken as a
  "check this" booking. Anything that has ended is left out.
- Trips: bookings whose dates touch or lie within GAP_DAYS of each other become one suggested trip, named after its
  places and month ("Lisbon and Porto, Oct 2027 – 7 bookings"). Confirm → yours; Not a trip → never suggested
  again. Nothing is booked, changed or cancelled with any provider.

state/trips.json: {"scanned": iso, "suggested": [trip], "trips": [trip], "dismissed": [booking keys],
  "removed": [trip], "undo": [{token, at, label, trips: [trip before], created: [ids], quotes?, after}]};
  trip = {id, title, start, end, places, bookings: [booking], planning: [quote], created}

Trips v2 (dev request 6 Nov), editing: merge two trips, split one (picked bookings or at a date), add an item by hand
(local time in its own zone), mark an item cancelled (struck through; left out of the calendar, the Today card and
alerts). Every step can be undone (trip_undo with the step's token – also "Restore" in the activity log), and only
while the trips it touched are unchanged since. Planning: quotes and enquiries under their trip, never bookings –
Booked (becomes a booking), Replace with the confirmation that arrived, Drop.
Calendar (step 3): on your tap, per trip or per item, into the calendar you choose (the last choice per world is
kept); a booking's event is remembered ("cal") and an applied update or a cancellation marks it "cal_stale" – the trip
then OFFERS Update / Remove in the calendar, never silently. Cancelled items never go in.
Today (step 4): today_card() – the next item on a travel day (and the evening before), the day's plan during a trip.
Changes (step 5): an update for a booking (Claude's reading says changed/cancelled, or a newer mail's own booking data
says so) is matched by its reference and leg. It is applied by itself ONLY when trust(update, booking) says so –
axella-actions.py checks that the mail is clean (scam check), passed the sender checks for its sender's domain, and
that this domain is the domain of the mail the booking came from. Anything else waits as "pending" (Apply / Ignore,
"From another sender than the booking – check with <provider>", never pushed); so does an update to a booking you
edited. Who an update is from is always the sender's DOMAIN, never a display name. The same rule applies to
"check-in is open" mails: one from another sender is not taken. Check-in opens: the airline's own "check-in is open" mail when
there is one, else an ESTIMATE – about 24 h before departure, or the window learnt from that airline's earlier mails
(kept as data in "checkin_windows", never a table in the code). Alerts: one digest line, and a push within 48 h of
departure (urgency rules and Discreet push apply in axella-actions.py).
The documents checklist (passports, visa/eTA, insurance, vaccinations, your own items) is NOT in trips.json – Claude
runs read that file – but in state/trip-checklists.json (SECRETS): ticked by you, nothing detected, no health data read.
booking = {key, kind, title, start, end, place, ref, provider, travellers, source: {account, message_id, subject, date},
  confidence: "data"|"check"}
Python 3.9.
"""
import datetime
import email
import email.policy
import hashlib
import html
import json
import os
import re
import secrets
import threading

LOCK = threading.Lock()
UNDO_KEEP = 40                   # undo steps kept (the newest)
CHECKIN_HOURS = 24               # check-in opens about this long before departure – the estimate when nothing is known
PUSH_HOURS = 48                  # alerts are pushed only this close to departure
TRANSPORT = ('flight', 'train', 'ferry', 'bus')
CHECKIN_RE = re.compile(r'check-?in (?:is )?(?:now )?open|online check-?in (?:is )?(?:now )?(?:open|available)|check in now|'
                        r'tjek ind nu|indtjekning(?:en)? er (?:nu )?åben|web check-?in (?:is )?open|check-in ist (?:jetzt )?geöffnet', re.I)
CHECK_DEFAULTS = (('passport', 'Passports'), ('visa', 'Visa / eTA'), ('insurance', 'Travel insurance'), ('vaccinations', 'Vaccinations'))
TZ_RE = re.compile(r'^[A-Za-z]+(?:/[A-Za-z0-9_+-]+){0,2}$|^UTC$')
MONTHS = 18                      # how far back the scan looks for bookings (trips are often booked long before)
GAP_DAYS = 2                     # bookings this close (or overlapping) are one trip
RETURN_DAYS = 30                 # ... and a way home within this many days of the way out closes the trip
SCAN_DAYS = 548                                # the furthest back a scan reads (18 months)
PAST_DAYS = 365                                # past trips: the last 12 months (the Past tab)
MAX_MAILS = 400

KINDS = {'FlightReservation': 'flight', 'LodgingReservation': 'hotel', 'TrainReservation': 'train',
         'RentalCarReservation': 'car', 'BusReservation': 'bus', 'BoatReservation': 'ferry', 'TaxiReservation': 'transfer',
         'EventReservation': 'ticket', 'FoodEstablishmentReservation': 'restaurant', 'Reservation': 'booking'}
SUBJECT_RE = re.compile(
    r'booking|reservation|confirmation|confirmed|itinerary|e-?ticket|e-?documents?|travel documents?|electronic ticket|for travel on|boarding pass|your trip|your flight|your stay|'
    r'check-?in|bekræftelse|reservation|rejseplan|din rejse|dit ophold|billet|booking|bestilling|'
    r'buchungsbestätigung|reservierung|ihre reise|bokningsbekräftelse|din resa|bestillingsbekreftelse|reisen din|'
    r'rejsebevis|e-?billet|flybillet|kvittering for din rejse|rejse til|trip to|your booking|your reservation|booking reference|'
    r'reservationsbekræftelse|ordrebekræftelse.*(?:rejse|billet|hotel)|boarding|check-?in (?:is )?(?:now )?open|online check-?in|'
    r'opholdet|overnatning|ferie|holiday|vacation|tour|flight (?:details|confirmation|booking|ticket)|flight to|'
    r'booking ref|\bpnr\b|travel itinerary|trip details|reservation details|your journey|ticket receipt|voucher|'
    r'flugbestätigung|reisebestätigung|resebekräftelse|reisebekreftelse|billetbekræftelse', re.I)



class Bad(Exception):
    pass


def looks_like_booking(subject, addr=''):
    """A booking candidate: booking words in the subject, in any of the languages above – never who sent it (no lists
    of airlines, hotels or companies). Claude, or the rules, then decide what the mail really holds."""
    return bool(SUBJECT_RE.search(str(subject or '')))


# ---------- reading one mail ----------
def _html_and_text(raw):
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    htm, txt = '', ''
    for part in msg.walk():
        ct = part.get_content_type()
        if ct not in ('text/html', 'text/plain') or part.get_filename():
            continue
        try:
            body = part.get_content()
        except Exception:
            body = (part.get_payload(decode=True) or b'').decode('utf-8', 'replace')
        if ct == 'text/html' and not htm:
            htm = body
        elif ct == 'text/plain' and not txt:
            txt = body
    if not txt and htm:
        t = re.sub(r'(?is)<(script|style|head)\b.*?</\1>', ' ', htm)
        txt = html.unescape(re.sub(r'<[^>]+>', ' ', re.sub(r'(?i)<br\s*/?>|</(p|div|tr|li|h\d)>', '\n', t)))
    return htm, re.sub(r'[ \t]+', ' ', txt)


def _ld_blocks(htm):
    out = []
    for m in re.finditer(r'(?is)<script[^>]+type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>', htm or ''):
        try:
            v = json.loads(html.unescape(m.group(1).strip()))
        except ValueError:
            continue
        stack = v if isinstance(v, list) else [v]
        while stack:
            x = stack.pop(0)
            if isinstance(x, dict):
                if '@graph' in x and isinstance(x['@graph'], list):
                    stack.extend(x['@graph'])
                out.append(x)
            elif isinstance(x, list):
                stack.extend(x)
    return out


def _type(x):
    t = x.get('@type')
    t = t[0] if isinstance(t, list) and t else t
    return str(t or '').split('/')[-1]


def _name(v):
    if isinstance(v, dict):
        return str(v.get('name') or v.get('iataCode') or '').strip()
    if isinstance(v, list):
        return ', '.join(filter(None, (_name(x) for x in v)))
    return str(v or '').strip()


def _city(v):
    """A place's town, else its name."""
    if isinstance(v, dict):
        a = v.get('address')
        if isinstance(a, dict) and a.get('addressLocality'):
            return str(a['addressLocality']).strip()
        return _name(v)
    return _name(v)


def parse_when(v):
    """ISO date/time → aware datetime (dates at 00:00 local); None if unreadable."""
    s = str(v or '').strip()
    if not s:
        return None
    try:
        d = datetime.datetime.fromisoformat(re.sub(r'([+-]\d\d)(\d\d)$', r'\1:\2', s.replace('Z', '+00:00')))   # 3.9: "+0200"
    except ValueError:
        try:
            d = datetime.datetime.strptime(s[:10], '%Y-%m-%d')
        except ValueError:
            return None
    return d if d.tzinfo else d.astimezone()


def _iso(d):
    return d.isoformat(timespec='minutes') if d else None


def from_reservation(x):
    """One schema.org reservation → a booking (without its source), or None."""
    t = _type(x)
    if t not in KINDS:
        return None
    kind = KINDS[t]
    it = x.get('reservationFor') if isinstance(x.get('reservationFor'), dict) else {}
    start = end = None
    place = title = provider = ''
    if kind == 'flight':
        dep, arr = it.get('departureAirport') or {}, it.get('arrivalAirport') or {}
        start, end = parse_when(it.get('departureTime')), parse_when(it.get('arrivalTime'))
        no = '%s %s' % ((it.get('airline') or {}).get('iataCode') or '', it.get('flightNumber') or '')
        title = ('Flight %s' % no.strip()).strip() + (' · %s → %s' % (_name(dep), _name(arr)) if _name(dep) and _name(arr) else '')
        place, provider = _city(arr) or _name(arr), _name(it.get('airline'))
    elif kind == 'hotel':
        start, end = parse_when(x.get('checkinTime') or x.get('checkinDate')), parse_when(x.get('checkoutTime') or x.get('checkoutDate'))
        title, place = _name(it) or 'Stay', _city(it)
        provider = _name(x.get('provider') or x.get('broker'))
    elif kind in ('train', 'bus', 'ferry', 'transfer'):
        dep = it.get('departureStation') or it.get('departureBusStop') or it.get('departureBoatTerminal') or it.get('pickupLocation') or {}
        arr = it.get('arrivalStation') or it.get('arrivalBusStop') or it.get('arrivalBoatTerminal') or it.get('dropoffLocation') or {}
        start, end = parse_when(it.get('departureTime') or x.get('pickupTime')), parse_when(it.get('arrivalTime'))
        title = '%s%s' % (kind.capitalize(), ' · %s → %s' % (_name(dep), _name(arr)) if _name(dep) and _name(arr) else '')
        place, provider = _city(arr) or _name(arr), _name(it.get('provider') or x.get('provider'))
    elif kind == 'car':
        start, end = parse_when(x.get('pickupTime')), parse_when(x.get('dropoffTime'))
        title = 'Car · %s' % (_name(it.get('rentalCompany')) or _name(it) or 'rental')
        place, provider = _city(x.get('pickupLocation')), _name(it.get('rentalCompany'))
    else:                                               # event, restaurant, a plain reservation
        start, end = parse_when(it.get('startDate') or x.get('startTime') or x.get('startDate')), parse_when(it.get('endDate') or x.get('endTime'))
        title, place = _name(it) or kind.capitalize(), _city(it.get('location')) if isinstance(it.get('location'), dict) else _name(it.get('location'))
        provider = _name(x.get('provider') or x.get('broker'))
    if not start:
        return None
    people = x.get('underName')
    trav = [n for n in (_name(p) for p in (people if isinstance(people, list) else [people])) if n][:9]
    out = {'kind': kind, 'title': title[:160], 'start': _iso(start), 'end': _iso(end or start), 'place': (place or '')[:80],
           'ref': str(x.get('reservationNumber') or x.get('reservationId') or '')[:40], 'provider': provider[:80],
           'travellers': trav, 'confidence': 'data'}
    if kind == 'flight':
        out['number'] = ('%s%s' % ((it.get('airline') or {}).get('iataCode') or '', it.get('flightNumber') or '')).strip()[:20]
    if 'cancel' in str(x.get('reservationStatus') or '').lower():
        out['status'] = 'cancelled'
    return out


# a booking without schema.org data: what kind (from the sender and words), a booking reference, the dates (the subject's
# first – "Copenhagen til Berlin, 3 mar - 7 mar" – also without a year), and where to (a route or a hotel name)
_MON = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'maj': 5, 'mai': 5, 'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10,
        'okt': 10, 'nov': 11, 'dec': 12, 'dez': 12, 'des': 12, 'mär': 3, 'mrt': 3}
_MONW = r'(jan|feb|mar|mär|mrt|apr|maj|may|mai|jun|jul|aug|sep|okt|oct|nov|dec|dez|des)[a-zæøåä]*\.?'
DATE_RES = (('ymd', re.compile(r'\b(20\d\d)-(\d\d)-(\d\d)\b')),
            ('dmy', re.compile(r'\b(\d{1,2})[./](\d{1,2})[./](20\d\d)\b')),
            ('d_m_y', re.compile(r'\b(\d{1,2})\.?\s+' + _MONW + r',?\s+(20\d\d)\b', re.I)),
            ('m_d_y', re.compile(r'\b' + _MONW + r'\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b', re.I)),
            ('d_m', re.compile(r'\b(\d{1,2})\.?\s+' + _MONW + r'(?!\s*,?\s*20\d\d)(?=[\s,.;)–-]|$)', re.I)),
            ('mdy_us', re.compile(r'\b' + _MONW + r'-(\d{1,2})-(20\d\d)\b', re.I)))
KIND_WORDS = (('flight', r'\bfly\b|flight|flyrejse|flybillet|boarding|departure|afgang|gate|terminal|airline|e-?ticket|rejsebevis|itinerary|\bpnr\b'),
              ('hotel', r'hotel|check-?in|check-?out|overnatning|indtjekning|udtjekning|your stay|dit ophold|room|værelse|nights?\b|nætter'),
              ('car', r'rental car|car rental|lejebil|billeje|pick-?up|mietwagen'),
              ('train', r'\btrain\b|\btog\b|\bzug\b|seat reservation|pladsbillet'),
              ('ferry', r'ferry|færge|fähre|overfart|crossing'),
              ('ticket', r'ticket|billet|koncert|concert|event|tickets'))
TRAVEL_WORDS = re.compile(r'flight|\bfly\b|hotel|check-?in|check-?out|departure|afgang|ankomst|arrival|overnatning|reservation|'
                          r'booking|rejse|trip|journey|reise|resa|ferry|færge|train|\btog\b|rental car|lejebil|boarding|gate|terminal', re.I)
REF_RE = re.compile(r'(?i:booking|reservation|reservations|confirmation|bekræftelses|bestillings|buchungs|boknings|order|pnr|'
                    r'booking ?reference|bookingreference|reference|referencenummer|ref)\.?\s*(?i:no\.?|number|nr\.?|nummer|code|kode|'
                    r'reference|id|nummer)?\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{4,14})\b')
REF_STOP = {'CONFIRMATION', 'CONFIRMED', 'BOOKING', 'NUMBER', 'RESERVATION', 'REFERENCE', 'DETAILS', 'BEKRÆFTET'}
ROUTE_RE = re.compile(r'([A-ZÆØÅ][\w.\'-]+(?: [A-ZÆØÅ][\w.\'-]+){0,2})\s+(?:til|to|→|->|nach|till|naar|à)\s+'
                      r'([A-ZÆØÅ][\w.\'-]+(?: [A-ZÆØÅ][\w.\'-]+){0,2})')


def dates_in(text, ref=None):
    """Dates in a text, sorted. Without a year ("18 nov") the next one on or after ref (the mail's date) is meant."""
    ref = ref or datetime.date.today()
    out = []
    for kind, rx in DATE_RES:
        for m in rx.finditer(text or ''):
            try:
                g = m.groups()
                if kind == 'ymd':
                    d = datetime.date(int(g[0]), int(g[1]), int(g[2]))
                elif kind == 'dmy':
                    d = datetime.date(int(g[2]), int(g[1]), int(g[0]))
                elif kind == 'd_m_y':
                    d = datetime.date(int(g[2]), _MON[g[1].lower()[:3]], int(g[0]))
                elif kind in ('m_d_y', 'mdy_us'):
                    d = datetime.date(int(g[2]), _MON[g[0].lower()[:3]], int(g[1]))
                else:
                    mo, dd = _MON[g[1].lower()[:3]], int(g[0])
                    d = datetime.date(ref.year, mo, dd)
                    if d < ref - datetime.timedelta(days=1):
                        d = datetime.date(ref.year + 1, mo, dd)
            except (ValueError, KeyError):
                continue
            out.append(d)
    return sorted(set(out))


def _provider(addr, from_name=''):
    """Who the booking is with: the sender's own display name ("Acme Air"), else its domain ("acme-air.example" → Acme-air)."""
    dom = str(addr or '').rsplit('@', 1)[-1].lower()
    parts = [x for x in dom.split('.') if x not in ('mail', 'email', 'info', 'noreply', 'no-reply', 'news', 'www')]
    key = parts[-2] if len(parts) >= 2 else (parts[0] if parts else '')
    n = re.sub(r'\s*(<.*|via .*|no-?reply.*)$', '', str(from_name or ''), flags=re.I).strip()
    return n if n and '@' not in n and len(n) <= 40 else key.capitalize()


def _kind(subject, text, addr=''):
    """flight, hotel, … from the words in the mail – never from who sent it"""
    blob = (subject or '') + ' ' + (text or '')[:4000]
    best = max(((len(re.findall(rx, blob, re.I)), k) for k, rx in KIND_WORDS), default=(0, 'booking'))
    return best[1] if best[0] else 'booking'


def _ref(subject, text):
    for src in (subject or '', text or ''):
        for m in REF_RE.finditer(src[:30000]):
            r = m.group(1).strip('-')
            if r.upper() in REF_STOP or len(r) < 5:
                continue
            if any(c.isdigit() for c in r) or (r.isupper() and r.isalpha() and len(r) == 6):
                return r[:40]
    return ''


def from_text(subject, addr, text, today, sent=None, from_name='', since=None):
    """A "check this" booking from a mail without schema.org data: a travel sender – or a booking subject with travel
    words in it – plus a booking reference and a date still ahead (the subject's dates first). Returns (booking, why)."""
    blob = (text or '')[:30000]
    travel = bool(SUBJECT_RE.search(subject or '')) and len(set(w.lower() for w in TRAVEL_WORDS.findall((subject or '') + ' ' + blob[:6000]))) >= 2
    if not travel:
        return None, 'not travel'
    ref_day = sent or today
    sub_dates = dates_in(subject, ref_day)
    # a forwarded mail's own header ("Date: Thursday, 15 October 2026 at 09.10") is when it was sent, not the trip
    blob = FWD_DATE_RE.sub('', blob)
    body_dates = [d for d in dates_in(blob, ref_day) if d >= ref_day - datetime.timedelta(days=1)]
    dates = sub_dates or body_dates
    if len(sub_dates) == 1:                              # "Your Dec-02-2026 confirmation": the end date is in the text
        dates = sorted(set(sub_dates + [d for d in body_dates if 0 <= (d - sub_dates[0]).days <= 60]))
    if not dates:
        return None, 'no dates'
    kind = _kind(subject, blob, addr)
    # how long one booking can last when its dates come from text: a stay up to 30 nights, a return flight or a
    # subject's own range ("18 nov - 22 nov") up to 30 days, anything else is one day – a stray date further down a
    # mail must never stretch a booking over weeks (and glue other trips to it)
    span = 30 if kind == 'hotel' or len(sub_dates) >= 2 or kind == 'flight' else 0
    window = [d for d in dates if (d - dates[0]).days <= span]
    start, end = window[0], window[-1]
    if end < (since or today - datetime.timedelta(days=PAST_DAYS)):
        return None, 'already over'
    ref = _ref(subject, blob)
    if not ref and not sub_dates:
        return None, 'no booking reference'
    route = ROUTE_RE.search(subject or '')           # the subject only: body text is full of "applicable to …"
    place, title = '', ''
    if route:
        place = route.group(2).strip()
        title = '%s · %s → %s' % ({'flight': 'Flight', 'train': 'Train', 'ferry': 'Ferry', 'bus': 'Bus'}.get(kind, 'Trip'),
                                  route.group(1).strip(), place)
    elif kind == 'hotel':
        m = re.search(r'(?:[—–]| - )\s*([^—–\n]{3,60})$', subject or '')
        name = m.group(1).strip() if m else ''
        prov0 = _provider(addr, from_name)
        title = name or ('Stay · %s' % prov0 if prov0 else 'Stay')
        if prov0 and name.lower().startswith(prov0.lower() + ' '):
            place = name[len(prov0):].strip()           # "Acme Inn Odense" → Odense
    s = datetime.datetime.combine(start, datetime.time()).astimezone()
    e = datetime.datetime.combine(end, datetime.time()).astimezone()
    prov = _provider(addr, from_name)
    return ({'kind': kind, 'title': (title or str(subject or '') or prov)[:160], 'start': _iso(s), 'end': _iso(e), 'place': place[:80],
             'ref': ref, 'provider': prov, 'travellers': [], 'confidence': 'check'}, None)


def bookings_in(raw, subject, addr, today, sent=None, from_name='', why=None, since=None):
    """Every booking in one mail (raw RFC 822 bytes). why (a list): the reason when nothing is found."""
    htm, text = _html_and_text(raw)
    out = [b for b in (from_reservation(x) for x in _ld_blocks(htm)) if b]
    if not out:
        b, reason = from_text(subject, addr, text, today, sent, from_name, since)
        if b:
            out.append(b)
        elif why is not None:
            # booking words, but the details are in a PDF (an e-ticket, a voucher): for Claude to read, via "To sort"
            why.append(IN_PDF if reason == 'not travel' and _has_pdf(raw) else reason)
    return out


IN_PDF = 'details in its PDF'


def _has_pdf(raw):
    """True when the mail has a PDF attachment (where e-tickets and vouchers keep the flights, times and names)."""
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception:
        return False
    return any(p.get_content_type() == 'application/pdf' or str(p.get_filename() or '').lower().endswith('.pdf') for p in msg.walk())


def key_of(b, n=0):
    """Stable across scans: the source mail and the booking's place in it (so better reading updates it, not doubles it)."""
    mid = (b.get('source') or {}).get('message_id')
    base = ('%s|%d' % (mid, n)) if mid else '|'.join(str(b.get(k) or '') for k in ('kind', 'ref', 'start', 'title'))
    return hashlib.sha1(base.encode('utf-8')).hexdigest()[:16]


def _when_of(day, hm, like):
    """'2026-11-18' + '19:30' → '2026-11-18T19:30:00+00:00' in the UTC offset of the time it replaces (the place's own);
    no time: the day only, kept as midnight. None if the day isn't a date."""
    try:
        d = datetime.date.fromisoformat(str(day or '')[:10])
    except ValueError:
        return None
    m = re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', str(hm or '').strip())
    old = parse_when(like)
    off = re.search(r'([+-]\d\d:\d\d|Z)$', str(like or ''))
    here = old and old.utcoffset() == old.astimezone().utcoffset()   # the time it replaces was in this Mac's own zone
    if here:                                     # local time: the new date's own offset (summer or winter time)
        t = datetime.time(int(m.group(1)), int(m.group(2))) if m else datetime.time()
        return datetime.datetime.combine(d, t).astimezone().isoformat(timespec='seconds')
    if off:
        tz = datetime.timezone.utc if off.group(1) == 'Z' else datetime.timezone(
            (1 if off.group(1)[0] == '+' else -1) * datetime.timedelta(hours=int(off.group(1)[1:3]), minutes=int(off.group(1)[4:6])))
    else:
        tz = (old.tzinfo if old else None) or datetime.datetime.now().astimezone().tzinfo
    t = datetime.time(int(m.group(1)), int(m.group(2))) if m else datetime.time()
    return datetime.datetime.combine(d, t, tzinfo=tz).isoformat(timespec='seconds')


def _span(t):
    """A trip's first and last day from its bookings (sorted); an empty trip keeps the dates it had."""
    if t.get('bookings'):
        t['bookings'].sort(key=lambda x: x['start'])
        t['start'], t['end'] = t['bookings'][0]['start'], max((x.get('end') or x['start']) for x in t['bookings'])


def _mid(b):
    return (b.get('source') or {}).get('message_id') or ''


ARROW_RE = re.compile(r'([^·→]+?)\s*→\s*([^·→]+)$')


def _route(b):
    """({from names}, {to names}) of a booking, lower case: its own fields and the "A → B" end of its title – a read
    flight says "BER" or "Berlin Brandenburg" where the rules' title says "Berlin"."""
    m = ARROW_RE.search(str(b.get('title') or ''))
    clean = lambda x: re.sub(r'^(flight|train|ferry|bus|trip)\s*·?\s*|^[a-z0-9]{2}\s?\d{1,4}\s+', '', str(x or '').strip().lower()).strip()
    f = {clean(x) for x in (b.get('from'), m and m.group(1)) if clean(x)}
    t = {clean(x) for x in (b.get('to'), m and m.group(2)) if clean(x)}
    return f, t


def _near(a, b):
    """Two sets of names for the same place: one name equal to, or inside, another ("vienna" / "vienna (vie)")."""
    return any(x == y or x in y or y in x for x in a for y in b)


def same_booking(old, new):
    """A rules booking ("check") that a better-read booking in the same trip already covers: same kind and day, and
    the same reference, or the same route, or (a stay) the same nights. A return booked as one rules booking is only
    covered when both legs are."""
    if old.get('kind') != new.get('kind') or _day(old['start']) != _day(new['start']):
        return False
    if old.get('ref') and new.get('ref'):              # both have a reference: the same booking only if it's the same one
        return old['ref'].strip().upper() == new['ref'].strip().upper()
    if old.get('kind') == 'hotel':
        return _day(old.get('end') or old['start']) == _day(new.get('end') or new['start'])
    (fa, ta), (fb, tb) = _route(old), _route(new)
    return _near(ta, tb) and (not fa or not fb or _near(fa, fb))


def _covered(b, good):
    if not any(same_booking(b, g) for g in good):
        return False
    if b.get('kind') == 'flight' and _day(b.get('end') or b['start']) != _day(b['start']):
        f, t = _route(b)                                  # the return leg must be there too
        back = dict(b, start=b['end'], title='', **{'from': ' '.join(t) if len(t) == 1 else min(t, key=len, default=''),
                                                  'to': ' '.join(f) if len(f) == 1 else min(f, key=len, default='')})
        return any(same_booking(back, g) for g in good)
    return True


def _flight_key(b):
    """One flight however many mails it comes in: kind, flight number and departure (a read booking only)."""
    n = str(b.get('number') or '').replace(' ', '').upper()
    return (b.get('kind'), n, b['start']) if n and b.get('confidence') != 'check' else None


TITLES = {'mr', 'mrs', 'ms', 'miss', 'mstr', 'master', 'dr', 'chd', 'child', 'inf', 'infant', 'adt', 'adult'}


def person_key(name):
    """One person however a mail prints the name: "Sam Example" = "EXAMPLE SAM MSTR (CHD)" (order, case, titles ignored)."""
    return ' '.join(sorted(w for w in re.split(r'[\s()/.,]+', str(name or '').lower()) if w and w not in TITLES))


def add_people(have, more):
    """have + the people in more who aren't in it yet (each person once, the first spelling kept)."""
    seen = {person_key(x) for x in have}
    out = list(have)
    for x in more:
        if x and person_key(x) not in seen:
            seen.add(person_key(x))
            out.append(x)
    return out


def _join(into, b):
    """b's traveller(s) and ticket onto into (the same flight, from another mail)."""
    into['travellers'] = add_people(into.get('travellers', []), b.get('travellers', []))
    if b.get('ticket') is not None and _mid(b) and _mid(b) != _mid(into) and _mid(b) not in {x.get('message_id') for x in into.get('tickets', [])}:
        into['tickets'] = into.get('tickets', []) + [{'account': (b.get('source') or {}).get('account'), 'message_id': _mid(b),
                                                      'ticket': b['ticket'], 'travellers': b.get('travellers', [])}]


def dedupe(d):
    """In every trip, a "check" booking that a read booking covers goes to the trip's Voided list (Restore there)."""
    for t in d['trips']:
        # the same flight read twice (each traveller's own e-ticket): one booking with everyone on it
        first, twice = {}, []
        for b in t['bookings']:
            k = (b.get('kind'), str(b.get('number') or '').replace(' ', '').upper(), b['start'], b.get('status'))
            if b.get('confidence') == 'check' or not k[1] or b.get('own_keep'):
                continue
            if k in first:
                f = first[k]
                f['travellers'] = add_people(f.get('travellers', []), b.get('travellers', []))
                if b.get('ticket') is not None and _mid(b) and _mid(b) != _mid(f):   # each traveller's own ticket stays openable
                    have = {x.get('message_id') for x in f.get('tickets', [])}
                    if _mid(b) not in have:
                        f['tickets'] = f.get('tickets', []) + [{'account': (b.get('source') or {}).get('account'), 'message_id': _mid(b),
                                                                 'ticket': b['ticket'], 'travellers': b.get('travellers', [])}]
                twice.append(b)
            else:
                first[k] = b
        if twice:
            ids = {id(b) for b in twice}
            t['bookings'] = [b for b in t['bookings'] if id(b) not in ids]
            t['voided'] = (t.get('voided', []) + [dict(b, voided='duplicate') for b in twice])[-100:]
            d['dismissed'] = sorted(set(d['dismissed']) | {b['key'] for b in twice})
        good = [b for b in t['bookings'] if b.get('confidence') != 'check' and b.get('status') != 'cancelled']
        seen, twins = [], []                              # two rules bookings of one stay (confirmation and receipt)
        for b in t['bookings']:
            if b.get('confidence') != 'check':
                continue
            if b.get('ref') and any(x.get('ref') == b['ref'] and same_booking(x, b) for x in seen):
                twins.append(b)
            else:
                seen.append(b)
        if twins:
            ids = {id(b) for b in twins}
            t['bookings'] = [b for b in t['bookings'] if id(b) not in ids]
            t['voided'] = (t.get('voided', []) + [dict(b, voided='duplicate') for b in twins])[-100:]
            d['dismissed'] = sorted(set(d['dismissed']) | {b['key'] for b in twins})
        dup = [b for b in t['bookings'] if b.get('confidence') == 'check' and not b.get('own_keep') and _covered(b, good)]
        if dup:
            ids = {b['key'] for b in dup}
            t['bookings'] = [b for b in t['bookings'] if b['key'] not in ids]
            t['voided'] = (t.get('voided', []) + [dict(b, voided='duplicate') for b in dup])[-100:]
            d['dismissed'] = sorted(set(d['dismissed']) | ids)
            if t['bookings']:
                _span(t)
        have = t['bookings']
        keep = []
        for b in t.get('new', []):
            # the same flight from another traveller's own mail (their e-ticket): joined onto the booking the trip has –
            # the traveller added, their PDF kept as an extra ticket – instead of being dropped as a duplicate
            twin = next((x for x in have if _flight_key(x) and _flight_key(x) == _flight_key(b) and _mid(x) != _mid(b)), None)
            if twin is not None:
                _join(twin, b)
            elif not any(same_booking(b, x) or same_booking(x, b) for x in have):
                keep.append(b)
        t['new'] = keep


# ---------- grouping ----------
def name_of(bs):
    """("Lisbon and Porto, Oct 2027", places) – the places of a trip's bookings (destinations first) and its month."""
    bs = sorted(bs, key=lambda b: b['start'])
    # home is where the first flight/train leaves from: a trip is named after where you go, not where you return to
    first = next((b for b in bs if b.get('kind') in ('flight', 'train', 'ferry', 'bus') and (_route(b)[0])), None)
    home = _route(first)[0] if first else set()
    places = []
    for b in bs:
        p = (b.get('place') or '').strip()
        if p and p not in places and not _near({p.lower()}, home):
            places.append(p)
    name = (' and '.join(places[:2]) if len(places) <= 2 else ', '.join(places[:2]) + ' and more') or \
        ('Stay at %s' % bs[0]['provider'] if bs[0].get('kind') == 'hotel' and bs[0].get('provider') else bs[0].get('provider') or 'Trip')
    return ('%s, %s' % (name, _day(bs[0]['start']).strftime('%b %Y')))[:120], places

def _day(s):
    d = parse_when(s)
    return d.date() if d else None


def since_of(d, today=None):
    """The first day trips are kept from: the date you picked for the scan, else 12 months back."""
    today = today or datetime.date.today()
    try:
        return datetime.date.fromisoformat(str(d.get('since') or '')[:10])
    except ValueError:
        return today - datetime.timedelta(days=PAST_DAYS)


def group(bookings, today=None, since=None):
    """Bookings of the last PAST_DAYS and ahead → suggested trips (overlapping or within GAP_DAYS), each with a title
    from its places."""
    today = today or datetime.date.today()
    since = since or today - datetime.timedelta(days=PAST_DAYS)
    up = [b for b in bookings if _day(b.get('end') or b['start']) and _day(b.get('end') or b['start']) >= since]
    up.sort(key=lambda b: b['start'])
    trips, cur, cur_end = [], [], None
    TRANSPORT = ('flight', 'train', 'ferry', 'bus')
    for b in up:
        s, e = _day(b['start']), _day(b.get('end') or b['start'])
        # the way home closes the trip it belongs to, however many nights lie between (a Saturday out, a Tuesday back)
        first = next((x for x in cur if x.get('kind') in TRANSPORT and _route(x)[0]), None)
        home_again = bool(first) and b.get('kind') in TRANSPORT and _near(_route(b)[1], _route(first)[0]) \
            and (s - _day(first['start'])).days <= RETURN_DAYS
        if cur and (s - cur_end).days > GAP_DAYS and not home_again:
            trips.append(cur)
            cur, cur_end = [], None
        cur.append(b)
        cur_end = max(cur_end, e) if cur_end else e
    if cur:
        trips.append(cur)
    out = []
    for bs in trips:
        title, places = name_of(bs)
        start, end = bs[0]['start'], max((b.get('end') or b['start']) for b in bs)
        out.append({'title': title, 'start': start, 'end': end, 'places': places[:8],
                    'bookings': bs, 'key': hashlib.sha1('|'.join(sorted(b['key'] for b in bs)).encode()).hexdigest()[:16]})
    return out


# ---------- the store ----------
class Trips:
    def __init__(self, state_dir):
        self.file = os.path.join(state_dir, 'trips.json')
        self.status = {'running': False, 'error': None, 'found': None}

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        for k in ('suggested', 'trips', 'dismissed', 'removed', 'unsorted', 'quotes', 'emptied'):
            d.setdefault(k, [])
        # only answers from the current instructions (v2) count as read: "could not be opened" was no reading, and a
        # run with the older instructions called another traveller's e-ticket a duplicate – such mails come back to
        # "To sort" on the next scan, to be read again
        d['read_none'] = [n for n in d.get('read_none', []) if n.get('v') and not UNOPENED_RE.match(str(n.get('reason') or ''))]
        return d

    def _save(self, d):
        dedupe(d)
        # a removed trip whose bookings are all in a trip again (refiled, restored, or read by Claude from the same
        # mail) has nothing left to restore: it leaves "Removed trips"
        filed = [b for t in d['trips'] for b in t['bookings'] + t.get('voided', [])]
        keys = {b['key'] for b in filed}
        mids = {_mid(b) for b in filed if _mid(b)}
        d['removed'] = [r for r in d['removed'] if not all(b['key'] in keys or (_mid(b) and _mid(b) in mids) for b in r['bookings'])]
        tmp = self.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)

    def set_since(self, since):
        """The first day the next scans read and keep trips from ("Scan since")."""
        with LOCK:
            d = self.load()
            d['since'] = since.isoformat()
            self._save(d)

    def set_unsorted(self, mails):
        """Travel-looking mails the scan couldn't read: kept until you put them in a trip or mark it "Void"."""
        with LOCK:
            d = self.load()
            # not again: a mail in a trip (or voided or offered there), one you voided, or one Claude has read
            placed = {_mid(b) for t in d['trips'] for b in t['bookings'] + t.get('voided', []) + t.get('new', [])} | \
                {k[2:] for k in d['dismissed'] if k.startswith('m:')} | {n.get('message_id') for n in d.get('read_none', [])}
            placed |= {x.get('message_id') for t in d['trips'] for b in t['bookings'] for x in b.get('tickets', [])}
            seen, out = set(), []
            for m in mails:
                mid = m.get('message_id')
                if mid and mid not in placed and mid not in seen:
                    seen.add(mid)
                    out.append(m)
            d['unsorted'] = out[:100]
            self._save(d)

    def merge_scan(self, bookings, today=None, now=None):
        """A finished scan: new suggestions from bookings not in a confirmed trip and not dismissed."""
        today = today or datetime.date.today()
        with LOCK:
            d = self.load()
            # what Claude read and is still waiting for you (a suggestion, "new" on a trip) stays through a rescan, and the
            # rules' copy of the same mail doesn't come back next to it
            read_keep = [b for x in d['suggested'] for b in x['bookings'] if b.get('confidence') in ('read', 'manual')] + \
                [b for t in d['trips'] for b in t.get('new', []) if b.get('confidence') in ('read', 'manual')]
            read_mids = {_mid(b) for b in read_keep if _mid(b)}
            given = {b['key'] for b in bookings}
            bookings = [b for b in bookings if _mid(b) not in read_mids or b.get('confidence') in ('read', 'manual')] + \
                [b for b in read_keep if b['key'] not in given]
            # a confirmed trip's bookings are read again: the same mail updates its booking (better dates, names)
            by_mid = {}
            for b in bookings:
                if _mid(b):
                    by_mid.setdefault(_mid(b), []).append(b)
            for t in d['trips']:
                seen_mid = {}
                for i, b in enumerate(t['bookings']):
                    m = _mid(b)
                    if m and m in by_mid and b.get('confidence') == 'check':
                        k = seen_mid.get(m, 0)
                        if k < len(by_mid[m]):
                            t['bookings'][i] = dict(by_mid[m][k], key=b['key'])
                            if b.get('own_title'):
                                t['bookings'][i].update(title=b['title'], own_title=True)
                            if b.get('own_kind'):
                                t['bookings'][i].update(kind=b['kind'], own_kind=True)
                            if b.get('status'):
                                t['bookings'][i]['status'] = b['status']
                        seen_mid[m] = k + 1
                t['bookings'].sort(key=lambda b: b['start'])
                _span(t)
                if t.get('auto_title', True) and t['title'] == t.get('suggested_title', t['title']):
                    t['title'], t['places'] = name_of(t['bookings'])   # a name you didn't change follows better reading
                    t['suggested_title'] = t['title']
            mids = {_mid(b) for t in d['trips'] for b in t['bookings'] if _mid(b)}
            freed = {b['key'] for r in d['removed'] for b in r['bookings']} | {'m:' + _mid(b) for r in d['removed'] for b in r['bookings'] if _mid(b)}
            gone = set(d['dismissed']) - freed        # removing a trip never meant "not travel" (see trip_remove)
            taken = {b['key'] for t in d['trips'] for b in t['bookings']} | gone
            fresh = [b for b in bookings if b['key'] not in taken and _mid(b) not in mids and ('m:' + _mid(b)) not in gone]
            # a new booking is offered to a confirmed trip only when it starts inside that trip's own dates (a day either
            # side) and you haven't said "not part of this trip" – one booking at a time, worked out again every scan
            for t in d['trips']:
                t['new'] = []
            rest = []
            for b in fresh:
                bs_, be_ = _day(b['start']), _day(b.get('end') or b['start'])
                home = None
                for t in d['trips']:
                    ts, te = _day(t['start']), _day(t['end'])
                    if b['key'] in t.get('not_part', []) or ('m:' + _mid(b)) in t.get('not_part', []):
                        continue
                    if ts and te and bs_ and ts - datetime.timedelta(days=1) <= bs_ <= te + datetime.timedelta(days=1):
                        home = t
                        break
                if home:
                    home['new'].append(b)
                else:
                    rest.append(b)
            sug = group(rest, today, since_of(d, today))
            old = {t['key']: t for t in d['suggested']}
            d['suggested'] = [dict(t, id=old[t['key']]['id'] if t['key'] in old else 'ts' + secrets.token_hex(5)) for t in sug]
            d['scanned'] = (now or datetime.datetime.now().astimezone()).isoformat(timespec='seconds')
            self._save(d)
            return d

    def view(self, today=None):
        today = today or datetime.date.today()
        d = self.load()
        for t in d['trips']:
            t['planning_view'] = planning_of(t, d)
            for b in t['bookings']:
                b['checkin_view'] = checkin_of(d, b)
        view_cal = d.get('cal_choice') or {}
        live = lambda t: (_day(t.get('end') or t['start']) or today) >= today
        return {'suggested': [t for t in d['suggested'] if live(t)],
                'past_suggested': sorted([t for t in d['suggested'] if not live(t)], key=lambda t: t['start'], reverse=True),
                'trips': sorted([t for t in d['trips'] if live(t)], key=lambda t: t['start']),
                'past': sorted([t for t in d['trips'] if not live(t)], key=lambda t: t['start'], reverse=True)[:20],
                'scanned': d.get('scanned'), 'scan': dict(self.status), 'unsorted': d['unsorted'],
                'since': since_of(d, today).isoformat(), 'cal_choice': view_cal,
                'quotes': [q for q in d['quotes'] if (_day(q.get('end') or q['start']) or today) >= today][-30:],
                'removed': [{'id': r['id'], 'title': r['title'], 'start': r['start'], 'end': r['end'], 'bookings': len(r['bookings']),
                             'removed_at': r.get('removed_at')} for r in reversed(d['removed'])][:20]}

    def action(self, action, p):
        tid = str(p.get('id') or p.get('backup') or '')
        with LOCK:
            d = self.load()
            if action == 'trip_confirm':
                t = next((x for x in d['suggested'] if x['id'] == tid), None)
                if not t:
                    raise Bad('that suggestion is gone – scan again')
                keep = set(p.get('bookings') or [b['key'] for b in t['bookings']])
                bs = [b for b in t['bookings'] if b['key'] in keep]
                if not bs:
                    raise Bad('pick at least one booking')
                d['dismissed'] = sorted(set(d['dismissed']) | {b['key'] for b in t['bookings'] if b['key'] not in keep}
                                        | {'m:' + _mid(b) for b in t['bookings'] if b['key'] not in keep and _mid(b)})
                title = ' '.join(str(p.get('title') or t['title']).split())[:120] or t['title']
                trip = dict(t, id='tr' + secrets.token_hex(5), title=title, bookings=bs, start=bs[0]['start'],
                            suggested_title=t['title'], auto_title=(title == t['title']),
                            end=max((b.get('end') or b['start']) for b in bs),
                            created=datetime.datetime.now().astimezone().isoformat(timespec='seconds'))
                trip.pop('key', None)
                d['trips'].append(trip)
                d['suggested'] = [x for x in d['suggested'] if x['id'] != tid]
                self._save(d)
                return {'id': trip['id'], 'title': trip['title']}
            if action == 'trip_dismiss':
                t = next((x for x in d['suggested'] if x['id'] == tid), None)
                if not t:
                    raise Bad('that suggestion is gone')
                keys = [b['key'] for b in t['bookings']] + ['m:' + _mid(b) for b in t['bookings'] if _mid(b)]
                d['dismissed'] = sorted(set(d['dismissed']) | set(keys))
                d['suggested'] = [x for x in d['suggested'] if x['id'] != tid]
                d['not_trips'] = (d.get('not_trips', []) + [t])[-50:]      # for Undo
                self._save(d)
                return {'id': tid, 'keys': keys}
            if action in ('trip_mail_add', 'trip_mail_new'):
                # a travel mail Axella couldn't read, put in a trip by hand – on the day you give, as you name it
                mid = str(p.get('message_id') or '')
                m = next((x for x in d['unsorted'] if x.get('message_id') == mid), None)
                if not m and isinstance(p.get('mail'), dict) and p['mail'].get('message_id') == mid and mid:
                    # a mail you found with "Add a mail" (checked in axella-actions.py: your account, no private contact)
                    m = {k: str(p['mail'].get(k) or '')[:300] for k in ('account', 'message_id', 'subject', 'date', 'from')}
                if not m:
                    raise Bad('that mail is not in the list any more – scan again')
                if any(_mid(b) == mid for t0 in d['trips'] for b in t0['bookings']):
                    raise Bad('that mail is already in a trip')
                day = str(p.get('date') or '')[:10]
                if not re.match(r'^\d{4}-\d{2}-\d{2}$', day) or not _day(day):
                    raise Bad('give the day it belongs to')
                end = str(p.get('end') or day)[:10]
                if not _day(end) or _day(end) < _day(day):
                    end = day
                kind = p.get('kind') if p.get('kind') in set(KINDS.values()) else 'booking'
                title = ' '.join(str(p.get('title') or m.get('subject') or 'Booking').split())[:160]
                b = {'kind': kind, 'title': title, 'start': day + 'T00:00', 'end': end + 'T00:00', 'place': ' '.join(str(p.get('place') or '').split())[:80],
                     'ref': '', 'provider': str(m.get('from') or '')[:80], 'travellers': [], 'confidence': 'manual',
                     'source': dict({k: m.get(k) for k in ('account', 'message_id', 'subject', 'date', 'from')}, address=_addr(m.get('from')))}
                b['key'] = key_of(b, 0)
                if action == 'trip_mail_new':
                    name = ' '.join(str(p.get('trip_title') or '').split())[:120]
                    if not name:
                        raise Bad('give the trip a name')
                    t = {'id': 'tr' + secrets.token_hex(5), 'title': name, 'auto_title': False, 'places': [b['place']] if b['place'] else [],
                         'bookings': [b], 'start': b['start'], 'end': b['end'],
                         'created': datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
                    d['trips'].append(t)
                else:
                    t = next((x for x in d['trips'] if x['id'] == tid), None)
                    if not t:
                        raise Bad('unknown trip')
                    t['bookings'] = sorted(t['bookings'] + [b], key=lambda x: x['start'])
                    _span(t)
                d['unsorted'] = [x for x in d['unsorted'] if x.get('message_id') != mid]
                self._save(d)
                return {'id': t['id'], 'title': t['title']}
            if action == 'trip_mail_not_travel':
                mid = str(p.get('message_id') or '')
                d['not_travel'] = (d.get('not_travel', []) + [x for x in d['unsorted'] if x.get('message_id') == mid])[-200:]
                d['unsorted'] = [x for x in d['unsorted'] if x.get('message_id') != mid]
                if mid:
                    d['dismissed'] = sorted(set(d['dismissed']) | {'m:' + mid})
                self._save(d)
                return {'message_id': mid, 'keys': ['m:' + mid] if mid else []}
            if action == 'trip_suggest_add':
                # bookings from a suggestion go into a trip you already have (the rest stay suggested)
                sg = next((x for x in d['suggested'] if x['id'] == tid), None)
                to = next((x for x in d['trips'] if x['id'] == str(p.get('to') or '')), None)
                if not sg or not to:
                    raise Bad('that suggestion or trip is gone – scan again')
                keys = set(p.get('bookings') or [b['key'] for b in sg['bookings']])
                moved = [b for b in sg['bookings'] if b['key'] in keys]
                if not moved:
                    raise Bad('pick at least one booking')
                have = {b['key'] for b in to['bookings']}
                to['bookings'] = sorted(to['bookings'] + [b for b in moved if b['key'] not in have], key=lambda b: b['start'])
                to['start'], to['end'] = to['bookings'][0]['start'], max((b.get('end') or b['start']) for b in to['bookings'])
                sg['bookings'] = [b for b in sg['bookings'] if b['key'] not in keys]
                d['suggested'] = [x for x in d['suggested'] if x['bookings']]
                self._save(d)
                return {'id': to['id'], 'title': to['title']}
            if action == 'trip_move_booking':
                # a booking moved from one trip to another; a trip left empty is dropped (Undo brings it back)
                src = next((x for x in d['trips'] if x['id'] == tid), None)
                to = next((x for x in d['trips'] if x['id'] == str(p.get('to') or '')), None)
                gone = next((x for x in d['emptied'] if x['id'] == str(p.get('to') or '')), None)
                if not to and gone:                           # Undo of moving a trip's last booking: the trip comes back
                    to = {k: v for k, v in gone.items() if k != 'emptied_at'}
                    to['bookings'] = []
                    d['trips'].append(to)
                    d['emptied'] = [x for x in d['emptied'] if x is not gone]
                b = next((x for x in (src or {}).get('bookings', []) if x['key'] == p.get('key')), None)
                if not src or not to or not b or src is to:
                    raise Bad('pick a booking and another trip')
                src['bookings'] = [x for x in src['bookings'] if x['key'] != b['key']]
                to['bookings'] = sorted(to['bookings'] + [b], key=lambda x: x['start'])
                for t0 in (src, to):
                    if t0['bookings']:
                        _span(t0)
                if not src['bookings']:
                    d['trips'] = [x for x in d['trips'] if x['id'] != src['id']]
                    # nothing left to restore, so not under "Removed trips" – kept out of sight for the move's Undo
                    d['emptied'] = (d['emptied'] + [dict(src, bookings=[], emptied_at=datetime.datetime.now().astimezone().isoformat(timespec='seconds'))])[-20:]
                self._save(d)
                return {'id': to['id'], 'title': to['title']}
            if action == 'trip_undismiss':
                keys = set(p.get('keys') or [])
                d['dismissed'] = [k for k in d['dismissed'] if k not in keys]
                back = [x for x in d.get('not_travel', []) if ('m:' + str(x.get('message_id'))) in keys]   # "Not travel" undone
                d['not_travel'] = [x for x in d.get('not_travel', []) if x not in back]
                d['unsorted'] = back + d['unsorted']
                sug = [x for x in d.get('not_trips', []) if {b['key'] for b in x['bookings']} & keys]   # "Not a trip" undone
                d['not_trips'] = [x for x in d.get('not_trips', []) if x not in sug]
                back_keys = {b['key'] for x in sug for b in x['bookings']} | {'m:' + _mid(b) for x in sug for b in x['bookings'] if _mid(b)}
                d['dismissed'] = [k for k in d['dismissed'] if k not in back_keys]
                d['suggested'] += [x for x in sug if x['id'] not in {y['id'] for y in d['suggested']}]
                self._save(d)
                return {'ok': True}
            if action == 'trip_undo':
                return self._undo(d, str(p.get('token') or p.get('backup') or ''))
            t = next((x for x in d['trips'] if x['id'] == tid), None)
            if action in EDITS:
                if not t:
                    raise Bad('unknown trip')
                return self._edit(d, t, action, p)
            if action == 'trip_restore':
                r = next((x for x in d['removed'] if x['id'] == tid), None)
                if not r:
                    raise Bad('that trip is gone')
                back = {b['key'] for b in r['bookings']} | {'m:' + _mid(b) for b in r['bookings'] if _mid(b)}
                d['dismissed'] = [k for k in d['dismissed'] if k not in back]
                d['removed'] = [x for x in d['removed'] if x['id'] != tid]
                inside = {b['key'] for t0 in d['trips'] for b in t0['bookings']}
                keys0 = {b['key'] for b in r['bookings']}
                r = dict(r, bookings=[b for b in r['bookings'] if b['key'] not in inside])
                keys = {b['key'] for b in r['bookings']}
                for sg in d['suggested']:                     # back in the trip: no longer a suggestion as well
                    sg['bookings'] = [b for b in sg['bookings'] if b['key'] not in keys]
                d['suggested'] = [x for x in d['suggested'] if x['bookings']]
                if not r['bookings']:                         # all already in a trip: nothing to bring back – tidy it away
                    where = next((t0['title'] for t0 in d['trips'] if keys0 & {b['key'] for b in t0['bookings']}), '')
                    self._save(d)
                    return {'id': tid, 'note': 'already in ' + where if where else 'already in your trips'}
                d['trips'].append({k: v for k, v in r.items() if k not in ('removed_at', 'emptied')})
                self._save(d)
                return {'id': tid}
            if not t:
                raise Bad('unknown trip')
            if action == 'trip_rename':
                title = ' '.join(str(p.get('title') or '').split())[:120]
                if not title:
                    raise Bad('give the trip a name')
                t['title'], t['auto_title'] = title, False
            elif action == 'trip_apply_new':
                pick = set(p.get('keys') or [b['key'] for b in t.get('new', [])])
                have = {b['key'] for b in t['bookings']}
                t['bookings'] = sorted(t['bookings'] + [b for b in t.get('new', []) if b['key'] in pick and b['key'] not in have],
                                       key=lambda b: b['start'])
                _span(t)
                t['new'] = [b for b in t.get('new', []) if b['key'] not in pick]
            elif action == 'trip_void':
                # "Void": a booking that's a duplicate or wrong leaves the trip (Restore under Voided) and isn't offered again
                b = next((x for x in t['bookings'] if x['key'] == p.get('key')), None)
                if not b:
                    raise Bad('that booking is gone')
                t['bookings'] = [x for x in t['bookings'] if x is not b]
                t['voided'] = (t.get('voided', []) + [dict(b, voided='you')])[-100:]
                d['dismissed'] = sorted(set(d['dismissed']) | {b['key']})
                if not t['bookings']:
                    raise Bad('it is the only booking – remove the trip instead')
                _span(t)
            elif action == 'trip_booking_rename':
                # your own name for a booking ("Stay" → "Acme Quinta"): kept when the mail is read again
                b = next((x for x in t['bookings'] if x['key'] == p.get('key')), None)
                name = ' '.join(str(p.get('name') or '').split())[:120]
                if not b:
                    raise Bad('that booking is gone')
                if not name:
                    raise Bad('give it a name')
                b['title'], b['own_title'] = name, True
            elif action == 'trip_ctx':
                # work or private: your say (the mails' accounts are only the first guess)
                c = p.get('ctx')
                if c not in ('work', 'private'):
                    raise Bad('work or private')
                t['ctx'] = c
            elif action == 'trip_booking_edit':
                # your own name, day and time for a booking (a wrong date typed by hand, a time the mail didn't give):
                # the place's own UTC offset is kept; an edited booking is yours – a rescan doesn't change it back
                b = next((x for x in t['bookings'] if x['key'] == p.get('key')), None)
                if not b:
                    raise Bad('that booking is gone')
                name = ' '.join(str(p.get('name') or '').split())[:120]
                if 'name' in p and not name:
                    raise Bad('give it a name')
                start = _when_of(p.get('day'), p.get('time'), b['start'])
                end = _when_of(p.get('until') or p.get('day'), p.get('until_time') if p.get('until') else p.get('time'), b.get('end') or b['start'])
                if p.get('day') and not start:
                    raise Bad('give the day as YYYY-MM-DD')
                if start and end and parse_when(end) < parse_when(start):
                    raise Bad('it ends before it starts')
                if name and name != b.get('title'):
                    b['title'], b['own_title'] = name, True
                if p.get('kind'):
                    if p['kind'] not in READ_KINDS:
                        raise Bad('unknown kind of booking')
                    if p['kind'] != b.get('kind'):
                        b['kind'], b['own_kind'] = p['kind'], True
                if start:
                    if (start, end or start) != (b['start'], b.get('end') or b['start']):
                        b['edited'] = True                 # your time: an update from the provider asks first
                    b['start'], b['end'] = start, end or start
                    b['confidence'] = 'manual' if b.get('confidence') == 'check' else b.get('confidence')
                t['bookings'].sort(key=lambda x: x['start'])
                _span(t)
            elif action == 'trip_unvoid':
                b = next((x for x in t.get('voided', []) if x['key'] == p.get('key')), None)
                if not b:
                    raise Bad('that booking is gone')
                t['voided'] = [x for x in t['voided'] if x is not b]
                b = {k: v for k, v in b.items() if k != 'voided'}
                b['confidence'] = 'manual' if b.get('confidence') == 'check' else b.get('confidence')   # you want it: kept
                b['own_keep'] = True                       # never voided again as a duplicate
                t['bookings'] = sorted(t['bookings'] + [b], key=lambda x: x['start'])
                d['dismissed'] = [k for k in d['dismissed'] if k != b['key']]
                _span(t)
            elif action == 'trip_part_again':
                # undo of "not part of this trip": it may be offered to the trip again (on the next scan)
                pick = set(p.get('keys') or [])
                t['not_part'] = [k for k in t.get('not_part', []) if k not in pick]
            elif action == 'trip_not_part':
                # "not part of this trip": never offered to it again; it can still be suggested as a trip of its own
                pick = set(p.get('keys') or [])
                drop = [b for b in t.get('new', []) if b['key'] in pick]
                t['not_part'] = sorted(set(t.get('not_part', [])) | {b['key'] for b in drop} | {'m:' + _mid(b) for b in drop if _mid(b)})[-500:]
                t['new'] = [b for b in t.get('new', []) if b['key'] not in pick]
            elif action == 'trip_remove':
                # Remove = "this isn't a trip of mine as it stands", not "these aren't bookings": the trip is kept under
                # Removed (Restore), and its bookings go straight back to the suggestions, to be added to another trip
                # or confirmed again. Only "Not a trip" on a suggestion keeps bookings away.
                d['trips'] = [x for x in d['trips'] if x['id'] != tid]
                d['removed'] = (d['removed'] + [dict(t, removed_at=datetime.datetime.now().astimezone().isoformat(timespec='seconds'))])[-50:]
                today = datetime.date.today()
                back = [b for b in t['bookings'] if not b['key'].endswith('-back')]
                for sg in group(back, today):
                    d['suggested'].append(dict(sg, id='ts' + secrets.token_hex(5)))
            else:
                raise Bad('unknown action')
            self._save(d)
            return {'id': tid, 'title': t['title'], 'backup': tid if action == 'trip_remove' else None}


    # ---------- Trips v2: calendar bookkeeping, the watch ----------
    def cal_targets(self, tid, keys=None):
        """(trip, [bookings]) to put in the calendar: not cancelled, not in it yet (or picked)."""
        d = self.load()
        t = next((x for x in d['trips'] if x['id'] == tid), None)
        if not t:
            raise Bad('unknown trip')
        pick = set(keys or [])
        bs = [b for b in t['bookings'] if _live(b) and (b['key'] in pick if pick else not b.get('cal'))]
        return t, bs, d.get('cal_choice') or {}

    def set_cal(self, tid, key, cal, world=None, calendar=None):
        """Remember a booking's event (cal = {id, calendar, start}) or that it left the calendar (None)."""
        with LOCK:
            d = self.load()
            t = next((x for x in d['trips'] if x['id'] == tid), None)
            b = next((x for x in (t or {}).get('bookings', []) if x['key'] == key), None)
            if not b:
                raise Bad('that booking is gone')
            if cal:
                b['cal'] = cal
            else:
                b.pop('cal', None)
            b.pop('cal_stale', None)
            if world in ('work', 'private') and calendar:
                d.setdefault('cal_choice', {})[world] = calendar
            self._save(d)

    def watch(self, bookings, checkin_mails=(), now=None, trust=None):
        """The watch (every 30 min, rules only): updates in newer mails' own booking data – a cancellation, or a new time
        for a booking of yours from a NEWER mail than the one it came from – and "check-in is open" mails."""
        now = now or datetime.datetime.now().astimezone()
        with LOCK:
            d = self.load()
            n = 0
            for b in bookings:
                if b.get('status') == 'cancelled':
                    n += bool(apply_update(d, b, now, trust) in ('applied', 'pending'))
                    continue
                t, x = find_booking(d, b)
                if not x or _mid(b) == _mid(x):
                    continue
                if str((b.get('source') or {}).get('date') or '') <= str((x.get('source') or {}).get('date') or ''):
                    continue                                    # an older (or the same) mail never changes a booking
                n += bool(apply_update(d, dict(b, status='changed'), now, trust) in ('applied', 'pending'))
            for m in checkin_mails:
                n += learn_checkin(d, m.get('text'), m['at'], m.get('provider') or '', trust, m.get('mail'))
            if n:
                self._save(d)
            return n

    def alerts(self, now=None, ctx_of=lambda t: None, worlds=None, mark=False):
        with LOCK:
            d = self.load()
            lines, marks = alert_lines(d, now, ctx_of, worlds)
            if mark and lines:
                mark_reported(d, marks)
                self._save(d)
            return lines

    def pushes(self, mark=None):
        with LOCK:
            d = self.load()
            if mark:
                mark_pushed(d, mark)
                self._save(d)
                return []
            return push_due(d)

    def today(self, now=None):
        return today_card(self.load(), now)

    # ---------- Trips v2: edits with undo ----------
    def _snap(self, d, trips, label, created=(), quotes=False):
        tok = 'u' + secrets.token_hex(6)
        rec = {'token': tok, 'at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'), 'label': label,
               'trips': json.loads(json.dumps(trips)), 'created': list(created)}
        if quotes:
            rec['quotes'] = json.loads(json.dumps(d.get('quotes', [])))
        d.setdefault('undo', []).append(rec)
        d['undo'] = d['undo'][-UNDO_KEEP:]
        return rec

    @staticmethod
    def _fp(d, ids):
        """A fingerprint of the trips an undo step touched – the step can be undone only while they are unchanged."""
        cur = [x for x in d['trips'] if x['id'] in ids]
        cur.sort(key=lambda x: x['id'])
        clean = [{k: v for k, v in x.items() if k not in ('new', 'planning_view')} for x in cur]
        return hashlib.sha1(json.dumps(clean, sort_keys=True).encode()).hexdigest()[:16]

    def _done(self, d, rec, t, extra=None):
        ids = {x['id'] for x in rec['trips']} | set(rec['created'])
        self._save(d)
        rec['after'] = self._fp(self.load(), ids)
        d2 = self.load()
        for r in d2.get('undo', []):
            if r['token'] == rec['token']:
                r['after'] = rec['after']
        self._save(d2)
        out = {'id': t['id'] if t else None, 'title': t['title'] if t else '', 'undo': rec['token'], 'backup': rec['token']}
        out.update(extra or {})
        return out

    def _undo(self, d, tok):
        rec = next((r for r in d.get('undo', []) if r['token'] == tok), None)
        if not rec:
            raise Bad('nothing to undo')
        ids = {x['id'] for x in rec['trips']} | set(rec['created'])
        if rec.get('after') and self._fp(d, ids) != rec['after']:
            raise Bad('the trip has changed since – undo the later steps first')
        d['trips'] = [x for x in d['trips'] if x['id'] not in ids] + rec['trips']
        if 'quotes' in rec:
            d['quotes'] = rec['quotes']
        d['undo'] = [r for r in d['undo'] if r['token'] != tok]
        self._save(d)
        first = rec['trips'][0] if rec['trips'] else {}
        return {'id': first.get('id'), 'title': rec['label'], 'undone': tok}

    def _edit(self, d, t, action, p):
        now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
        if action == 'trip_merge':
            # the other trip's bookings (and voided ones, planning) join this one; every booking keeps its source
            o = next((x for x in d['trips'] if x['id'] == str(p.get('other') or '')), None)
            if not o or o is t:
                raise Bad('pick another trip to merge with')
            rec = self._snap(d, [t, o], 'Trips merged: %s + %s' % (t['title'], o['title']))
            have = {b['key'] for b in t['bookings']}
            t['bookings'] = t['bookings'] + [b for b in o['bookings'] if b['key'] not in have]
            for k in ('voided', 'planning', 'not_part'):
                t[k] = (t.get(k) or []) + [x for x in (o.get(k) or []) if x not in (t.get(k) or [])]
            if p.get('title'):
                t['title'], t['auto_title'] = ' '.join(str(p['title']).split())[:120] or t['title'], False
            t['places'] = list(dict.fromkeys((t.get('places') or []) + (o.get('places') or [])))[:8]
            _span(t)
            d['trips'] = [x for x in d['trips'] if x['id'] != o['id']]
            return self._done(d, rec, t, {'merged': o['id']})
        if action == 'trip_split':
            # the picked bookings (or all from a date on) become a new trip
            keys = set(p.get('keys') or [])
            at = _day(p.get('at'))
            if at:
                keys = {b['key'] for b in t['bookings'] if _day(b['start']) and _day(b['start']) >= at}
            out = [b for b in t['bookings'] if b['key'] in keys]
            name = ' '.join(str(p.get('title') or '').split())[:120]
            if not out:
                raise Bad('pick the bookings for the new trip')
            if len(out) == len(t['bookings']):
                raise Bad('leave at least one booking in this trip')
            if not name:
                raise Bad('give the new trip a name')
            nid = 'tr' + secrets.token_hex(5)
            rec = self._snap(d, [t], 'Trip split: %s' % t['title'], created=[nid])
            t['bookings'] = [b for b in t['bookings'] if b['key'] not in keys]
            _span(t)
            new = {'id': nid, 'title': name, 'auto_title': False, 'bookings': out, 'places': name_of(out)[1][:8],
                   'ctx': t.get('ctx'), 'created': now}
            _span(new)
            d['trips'].append(new)
            return self._done(d, rec, new, {'from': t['id']})
        if action == 'trip_item_add':
            b = manual_item(p, p.get('mail') if isinstance(p.get('mail'), dict) else None)   # checked in axella-actions.py
            rec = self._snap(d, [t], 'Trip: item added – %s' % b['title'])
            t['bookings'] = t['bookings'] + [b]
            _span(t)
            return self._done(d, rec, t, {'key': b['key']})
        if action == 'trip_item_remove':
            # only an item you added by hand is removed (a booking from a mail is voided instead); undo / Restore bring it back
            b = next((x for x in t['bookings'] if x['key'] == p.get('key')), None)
            if not b or not b.get('by_hand'):
                raise Bad('only an item you added by hand can be removed – void a booking from a mail')
            if len(t['bookings']) == 1:
                raise Bad('it is the only item – remove the trip instead')
            rec = self._snap(d, [t], 'Trip: item removed – %s' % b['title'])
            t['bookings'] = [x for x in t['bookings'] if x is not b]
            _span(t)
            return self._done(d, rec, t)
        if action == 'trip_cancel':
            # cancelled by you (or undone): struck through, kept – out of the calendar, the Today card and alerts
            b = next((x for x in t['bookings'] if x['key'] == p.get('key')), None)
            if not b:
                raise Bad('that booking is gone')
            on = bool(p.get('on', True))
            rec = self._snap(d, [t], 'Trip: %s %s' % (b['title'], 'cancelled' if on else 'not cancelled'))
            if on:
                b['status'], b['own_status'] = 'cancelled', True
                if b.get('cal'):
                    b['cal_stale'] = 'cancelled'             # offered: Remove from the calendar (never silently)
            else:
                b['status'] = 'booked'
                b['own_status'] = True
            return self._done(d, rec, t)
        if action in ('trip_update_apply', 'trip_update_ignore'):
            # an update from the provider for a booking you edited: your edit wins unless you Apply it
            b = next((x for x in t['bookings'] if x['key'] == p.get('key')), None)
            if not b or not b.get('pending'):
                raise Bad('no update is waiting for that booking')
            pend = b['pending']
            rec = self._snap(d, [t], 'Trip: update from %s %s' % (pend.get('by') or 'the provider', 'applied' if action == 'trip_update_apply' else 'ignored'))
            if action == 'trip_update_apply':
                b.update(pend.get('now') or {})
                b['updated'] = dict(pend, applied='you')
                b.pop('edited', None)
                if b.get('cal'):
                    b['cal_stale'] = 'cancelled' if b.get('status') == 'cancelled' else 'changed'
                _span(t)
            else:
                b['ignored'] = (b.get('ignored') or []) + [pend.get('mail')]
            b.pop('pending', None)
            return self._done(d, rec, t)
        if action in ('trip_plan_booked', 'trip_plan_drop', 'trip_plan_replace'):
            key = p.get('key')
            q = next((x for x in t.get('planning', []) if x['key'] == key), None)
            loose = None if q else next((x for x in d.get('quotes', []) if x['key'] == key), None)
            q = q or loose
            if not q:
                raise Bad('that quote is gone')
            rec = self._snap(d, [t], 'Trip: %s – %s' % ({'trip_plan_booked': 'booked', 'trip_plan_drop': 'quote dropped',
                                                         'trip_plan_replace': 'confirmation in place of the quote'}[action], q['title']), quotes=True)
            t['planning'] = [x for x in t.get('planning', []) if x['key'] != key]
            d['quotes'] = [x for x in d.get('quotes', []) if x['key'] != key]
            d['plan_dropped'] = sorted(set(d.get('plan_dropped', [])) | {key})[-500:]
            if action == 'trip_plan_booked':
                b = dict(q, status='booked', confidence='manual', from_quote=True)
                if b['key'] not in {x['key'] for x in t['bookings']}:
                    t['bookings'] = t['bookings'] + [b]
            elif action == 'trip_plan_replace':
                by = next((x for x in t.get('new', []) if x['key'] == p.get('by')), None)
                if not by:
                    raise Bad('that confirmation is gone – scan again')
                t['bookings'] = t['bookings'] + [by]
                t['new'] = [x for x in t['new'] if x['key'] != by['key']]
            _span(t)
            return self._done(d, rec, t)
        raise Bad('unknown action')


EDITS = ('trip_merge', 'trip_split', 'trip_item_add', 'trip_item_remove', 'trip_cancel',
         'trip_plan_booked', 'trip_plan_drop', 'trip_plan_replace', 'trip_update_apply', 'trip_update_ignore')


# ---------- Trips v2, steps 3–5: calendar, Today, changes and alerts ----------
def _norm(v):
    return re.sub(r'[\s-]', '', str(v or '')).upper()


def provider_key(b):
    return re.sub(r'[^a-z0-9]', '', str(b.get('provider') or '').lower())[:40]


def same_leg(x, b):
    """Is booking b (from an update) about booking x: the same reference, and the same flight/train number – or, without
    numbers, the same kind within two days."""
    if not x.get('ref') or _norm(x.get('ref')) != _norm(b.get('ref')):
        return False
    if x.get('number') and b.get('number'):
        return _norm(x['number']) == _norm(b['number'])
    xs, bs = parse_when(x.get('start')), parse_when(b.get('start'))
    return x.get('kind') == b.get('kind') and bool(xs and bs) and abs((xs - bs).total_seconds()) <= 2 * 86400


def find_booking(d, b):
    for t in d['trips']:
        for x in t['bookings']:
            if same_leg(x, b):
                return t, x
    return None, None


def mail_domain(src):
    """The organisation domain of a mail's sender address (mail.acme.example → acme.example), or ''."""
    import safety
    a = str((src or {}).get('address') or '').strip().lower()
    return safety._base(a.rsplit('@', 1)[-1]) if re.match(r'^[^@\s]+@[\w.-]+\.[a-z]{2,}$', a) else ''


def apply_update(d, b, now=None, trust=None):
    """An update for one of your bookings (b: status changed/cancelled, from a mail). Returns 'applied', 'pending',
    'same' (nothing new) or None (no booking of yours matches). The mail is read once: linked to the booking.
    trust(b, x) → (ok, domain): only an ok update is applied by itself; without trust nothing is."""
    now = now or datetime.datetime.now().astimezone()
    t, x = find_booking(d, b)
    if not x:
        return None
    mid = _mid(b)
    if mid and (mid in (x.get('updates') or []) or mid in (x.get('ignored') or [])):
        return 'same'
    if mid:
        x['updates'] = ((x.get('updates') or []) + [mid])[-20:]
    change = {}
    if b.get('status') == 'cancelled':
        if x.get('status') != 'cancelled':
            change['status'] = 'cancelled'
    else:
        for k in ('start', 'end'):
            if b.get(k) and parse_when(b[k]) and parse_when(b[k]) != parse_when(x.get(k)):
                change[k] = b[k]
    if not change:
        return 'same'
    ok, dom = trust(b, x) if trust else (False, mail_domain(b.get('source')))
    dom = dom or mail_domain(b.get('source'))
    info = {'by': dom or 'an unknown sender', 'at': now.isoformat(timespec='seconds'),
            'was': {k: x.get(k) for k in change}, 'now': change, 'mail': mid}
    if not ok:
        info['other_sender'] = True                      # "From another sender than the booking – check with <provider>"
        info['provider'] = x.get('provider') or ''
    edited = bool(x.get('edited') or x.get('own_status') or x.get('by_hand')) or not ok
    if edited:
        x['pending'] = info                              # your edit (or an unverified sender): Apply / Ignore on the trip
    else:
        x.update(change)
        x['updated'] = info
        if x.get('cal'):
            x['cal_stale'] = 'cancelled' if x.get('status') == 'cancelled' else 'changed'
        _span(t)
    d.setdefault('alerts', []).append({'id': 'al' + secrets.token_hex(5), 'trip': t['id'], 'key': x['key'],
                                       'kind': 'cancelled' if change.get('status') == 'cancelled' else 'changed',
                                       'pending': edited, 'untrusted': not ok, 'provider': x.get('provider') or '',
                                       'at': info['at'], 'by': info['by'], 'was': info['was'], 'now': change,
                                       'title': x.get('title'), 'number': x.get('number'), 'reported': False, 'pushed': False})
    d['alerts'] = d['alerts'][-200:]
    return 'pending' if edited else 'applied'


def learn_checkin(d, text, mail_at, provider='', trust=None, mail=None):
    """An airline's "check-in is open" mail: the flight it names (its reference or number) gets the real opening time,
    and that airline's window (hours before departure) is kept as data for the next estimates – only when
    trust({'source': mail}, flight) says the mail is from the booking's own sender (checked, clean)."""
    t_ = str(text or '')[:200000]
    hit = 0
    for t in d['trips']:
        for x in t['bookings']:
            if x.get('kind') != 'flight' or x.get('status') == 'cancelled':
                continue
            dep = parse_when(x.get('start'))
            if not dep or not (0 < (dep - mail_at).total_seconds() <= 4 * 86400):
                continue
            named = (x.get('ref') and _norm(x['ref']) in _norm(t_)) or (x.get('number') and _norm(x['number']) in _norm(t_))
            if not named:
                continue
            if not trust or not trust({'source': mail or {}}, x)[0]:
                continue                                 # another sender's "check-in is open": not taken
            x['checkin'] = {'at': mail_at.isoformat(timespec='minutes'), 'estimated': False}
            hours = round((dep - mail_at).total_seconds() / 3600)
            k = provider_key(x) or re.sub(r'[^a-z0-9]', '', str(provider).lower())[:40]
            if k and 1 <= hours <= 72:
                d.setdefault('checkin_windows', {})[k] = hours
            hit += 1
    return hit


def checkin_of(d, x):
    """When check-in opens for a flight: the airline's own word, else an estimate (marked so)."""
    if x.get('kind') != 'flight' or x.get('status') == 'cancelled':
        return None
    if x.get('checkin'):
        return x['checkin']
    dep = parse_when(x.get('start'))
    if not dep or (x.get('start') or '')[11:16] in ('', '00:00'):
        return None
    hours = (d.get('checkin_windows') or {}).get(provider_key(x)) or CHECKIN_HOURS
    return {'at': (dep - datetime.timedelta(hours=hours)).isoformat(timespec='minutes'), 'estimated': True, 'hours': hours}


def _live(b):
    return b.get('status') != 'cancelled'


def today_card(d, now=None):
    """The Today card: on a travel day (or the evening before) the next item; during a trip the day's plan, in each
    place's own local time. Cancelled items never show. None on other days."""
    now = now or datetime.datetime.now().astimezone()
    today = now.date()
    best = None
    for t in d['trips']:
        items = sorted([b for b in t['bookings'] if _live(b) and parse_when(b.get('start'))], key=lambda b: parse_when(b['start']))
        if not items:
            continue
        ts, te = _day(t.get('start')), _day(t.get('end'))
        during = bool(ts and te and ts <= today <= te)
        on_day = [b for b in items if _day(b['start']) == today]
        eve = now.hour >= 17 and any(_day(b['start']) == today + datetime.timedelta(days=1) for b in items)
        if not (during or on_day or eve):
            continue
        nxt = next((b for b in items if (parse_when(b.get('end') or b['start']) or parse_when(b['start'])) >= now), None)
        if not nxt:
            continue
        mode = 'during' if during and ts < today else 'travel' if on_day else 'eve'
        day = on_day if mode == 'during' else []
        card = {'trip': {'id': t['id'], 'title': t['title']}, 'mode': mode, 'next': _card_item(d, nxt),
                'day': [_card_item(d, b) for b in day]}
        if best is None or parse_when(nxt['start']) < parse_when(best['next']['start']):
            best = card
    return best


def _card_item(d, b):
    out = {k: b.get(k) for k in ('key', 'kind', 'title', 'start', 'end', 'place', 'address', 'ref', 'number', 'provider')}
    out['checkin'] = checkin_of(d, b)
    src = b.get('source') or {}
    tk = next((x for x in b.get('tickets') or [] if x.get('message_id') and x.get('ticket') is not None), None)
    if tk:
        out['ticket'] = {'account': tk.get('account') or src.get('account'), 'message_id': tk['message_id'], 'n': tk['ticket']}
    elif b.get('ticket') is not None and src.get('message_id'):
        out['ticket'] = {'account': src.get('account'), 'message_id': src['message_id'], 'n': b['ticket']}
    return out


def alert_lines(d, now=None, ctx_of=lambda t: None, worlds=None):
    """The digest's trip line(s): changes and cancellations not reported yet, and check-in opening within 30 h.
    Returns (lines, marks) – marks are applied with mark_reported() once the line is in."""
    now = now or datetime.datetime.now().astimezone()
    trips = {t['id']: t for t in d['trips']}
    lines, marks = [], {'alerts': [], 'checkin': []}

    def ok_world(t):
        w = ctx_of(t)
        return not worlds or w not in ('work', 'private') or w in worlds

    def hm(v):
        x = parse_when(v)
        return x.strftime('%a %H:%M') if x else ''
    for a in d.get('alerts', []):
        t = trips.get(a['trip'])
        if a.get('reported') or not t or not ok_world(t):
            continue
        name = a.get('number') or a.get('title') or 'a booking'
        if a['kind'] == 'cancelled':
            line = '%s was cancelled (%s)' % (name, a.get('by'))
        else:
            was, new = hm((a.get('was') or {}).get('start')), hm((a.get('now') or {}).get('start'))
            line = '%s: new time %s → %s' % (name, was, new) if was and new else '%s was changed by %s' % (name, a.get('by'))
        if a.get('untrusted'):
            line += ' – from another sender than the booking: check with %s (Apply or Ignore in Trips)' % (a.get('provider') or 'them')
        elif a.get('pending'):
            line += ' – you edited it: Apply or Ignore in Trips'
        lines.append(line)
        marks['alerts'].append(a['id'])
    done = set(d.get('checkin_reported') or [])
    for t in d['trips']:
        if not ok_world(t):
            continue
        for x in t['bookings']:
            c = checkin_of(d, x)
            at = parse_when(c['at']) if c else None
            if not at or x['key'] in done or not (now - datetime.timedelta(hours=1) <= at <= now + datetime.timedelta(hours=30)):
                continue
            when = 'today' if at.date() == now.date() else 'tomorrow' if at.date() == now.date() + datetime.timedelta(days=1) else at.strftime('%a')
            lines.append('Check-in for %s opens %s %s%s' % (x.get('number') or x.get('title'), when, at.strftime('%H:%M'),
                                                            ' (estimated)' if c.get('estimated') else ''))
            marks['checkin'].append(x['key'])
    return lines, marks


def mark_reported(d, marks):
    ids = set(marks.get('alerts') or [])
    for a in d.get('alerts', []):
        if a['id'] in ids:
            a['reported'] = True
    d['checkin_reported'] = (list(d.get('checkin_reported') or []) + list(marks.get('checkin') or []))[-300:]


def push_due(d, now=None):
    """Pushes due now (within PUSH_HOURS of departure): changes, cancellations and check-in opening – each once.
    Returns [(kind, text, mark)]; the caller applies the urgency rules and Discreet push, then mark_pushed()."""
    now = now or datetime.datetime.now().astimezone()
    out = []
    keys = {(t['id'], x['key']): x for t in d['trips'] for x in t['bookings']}
    soon = lambda x: x and parse_when(x.get('start')) and now - datetime.timedelta(hours=2) <= parse_when(x['start']) <= now + datetime.timedelta(hours=PUSH_HOURS)
    for a in d.get('alerts', []):
        x = keys.get((a['trip'], a['key']))
        if a.get('pushed') or a.get('untrusted') or not soon(x):
            continue                                     # never a push for an update from another sender
        name = a.get('number') or a.get('title') or 'Your booking'
        txt = '%s was cancelled' % name if a['kind'] == 'cancelled' else '%s: the time has changed' % name
        out.append(('alert', txt, ('alert', a['id'])))
    sent = set(d.get('checkin_pushed') or [])
    for x in keys.values():
        c = checkin_of(d, x)
        at = parse_when(c['at']) if c else None
        if at and at <= now and soon(x) and x['key'] not in sent:
            out.append(('checkin', 'Check-in for %s is open%s' % (x.get('number') or x.get('title'), ' (estimated)' if c.get('estimated') else ''),
                        ('checkin', x['key'])))
    return out


def mark_pushed(d, marks):
    for kind, ref in marks:
        if kind == 'alert':
            for a in d.get('alerts', []):
                if a['id'] == ref:
                    a['pushed'] = True
        else:
            d['checkin_pushed'] = (list(d.get('checkin_pushed') or []) + [ref])[-300:]


def cal_event(t, b, calendar, link=''):
    """The calendar event for one booking: local times with their own offset, the reference, a way back to the trip."""
    s, e = b['start'], b.get('end') or b['start']
    all_day = s[11:16] in ('', '00:00') and e[11:16] in ('', '00:00')
    if all_day:
        s, e = s[:10] + 'T00:00:00', (e[:10] if e[:10] >= s[:10] else s[:10]) + 'T23:59:00'
    lines = [x for x in (b.get('number') and ('%s %s' % (KIND_LABEL.get(b.get('kind'), ''), b['number'])).strip(),
                         b.get('ref') and 'Booking reference: ' + b['ref'], b.get('provider'), b.get('address'),
                         ('Trip in Axella: %s' % t['title']) + (' – ' + link if link else '')) if x]
    return {'calendar': calendar, 'title': str(b.get('title') or 'Booking')[:300], 'start': s, 'end': e, 'all_day': all_day,
            'location': ' '.join(str(b.get('address') or b.get('place') or '').split())[:300], 'notes': '\n'.join(lines)[:3000]}


KIND_LABEL = {'flight': 'Flight', 'train': 'Train', 'ferry': 'Ferry', 'bus': 'Bus'}


def zoned(local, tz):
    """'2027-03-01T10:40' in 'Europe/Lisbon' → '2027-03-01T10:40:00+00:00' (the zone's own offset on that day)."""
    from zoneinfo import ZoneInfo
    m = re.match(r'^(\d{4}-\d{2}-\d{2})(?:T([01]\d|2[0-3]):([0-5]\d))?$', str(local or '').strip())
    if not m or not _day(m.group(1)):
        return None
    tz = str(tz or '').strip()
    if not TZ_RE.match(tz):
        raise Bad('unknown time zone')
    try:
        z = ZoneInfo(tz)
    except Exception:
        raise Bad('unknown time zone')
    d = datetime.datetime.combine(_day(m.group(1)), datetime.time(int(m.group(2) or 0), int(m.group(3) or 0)), tzinfo=z)
    return d.isoformat(timespec='seconds')


def manual_item(p, mail=None):
    """An item you add by hand: kind, title, start and end in local time with the zone, place, reference, travellers;
    optionally the mail it came in (checked by axella-actions.py: your account, no private contact)."""
    kind = p.get('kind') if p.get('kind') in READ_KINDS else 'booking'
    txt = lambda k, n: ' '.join(str(p.get(k) or '').split())[:n]
    title = txt('title', 160)
    if not title:
        raise Bad('give it a name')
    start = zoned(p.get('start'), p.get('tz'))
    if not start:
        raise Bad('give the start as a day (and time)')
    end = zoned(p.get('end'), p.get('end_tz') or p.get('tz')) if p.get('end') else start
    if not end:
        raise Bad('give the end as a day (and time)')
    if parse_when(end) < parse_when(start):
        raise Bad('it ends before it starts')
    b = {'kind': kind, 'status': 'booked', 'title': title, 'start': start, 'end': end, 'tz': str(p.get('tz')),
         'place': txt('place', 80), 'ref': txt('ref', 40), 'provider': txt('provider', 80), 'number': txt('number', 20),
         'travellers': [' '.join(str(x).split())[:80] for x in (p.get('travellers') or []) if str(x).strip()][:9],
         'confidence': 'manual', 'by_hand': True, 'source': {}}
    if mail and mail.get('message_id'):
        b['source'] = {k: str(mail.get(k) or '')[:300] for k in ('account', 'message_id', 'subject', 'date', 'from')}
    b['key'] = 'h' + secrets.token_hex(7)
    return b


def _same_plan(q, b):
    """A booking that confirms a quote: the same reference, or the same kind on the same day from the same provider."""
    if q.get('ref') and b.get('ref') and q['ref'].replace(' ', '').upper() == b['ref'].replace(' ', '').upper():
        return True
    return bool(q.get('kind') == b.get('kind') and _day(q.get('start')) and _day(q.get('start')) == _day(b.get('start'))
                and q.get('provider') and str(q.get('provider')).lower() == str(b.get('provider') or '').lower())


def planning_of(t, d):
    """A trip's planning: its own quotes and the loose ones whose dates fall in the trip (a day either side), each with
    the waiting booking that confirms it (confirmed_by), if one came."""
    ts, te = _day(t.get('start')), _day(t.get('end'))
    dropped = set(d.get('plan_dropped', []))
    own = list(t.get('planning') or [])
    keys = {q['key'] for q in own}
    for q in d.get('quotes', []):
        qs = _day(q.get('start'))
        if q['key'] not in keys and q['key'] not in dropped and ts and te and qs and \
                ts - datetime.timedelta(days=1) <= qs <= te + datetime.timedelta(days=1):
            own.append(dict(q, loose=True))
    out = []
    for q in own:
        if q['key'] in dropped:
            continue
        by = next((b['key'] for b in t.get('new', []) if _same_plan(q, b)), None)
        out.append(dict(q, confirmed_by=by))
    return out


# ---------- the documents checklist (state/trip-checklists.json – SECRETS: Claude runs never read it) ----------
class Checklists:
    def __init__(self, state_dir):
        self.file = os.path.join(state_dir, 'trip-checklists.json')

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, d):
        tmp = self.file + '.%d.tmp' % os.getpid()
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)

    def of(self, trip_id):
        items = self.load().get(str(trip_id))
        if items is None:
            return [{'id': k, 'text': v, 'done': False, 'date': None, 'default': True} for k, v in CHECK_DEFAULTS]
        return items

    def action(self, action, p, trip_ids):
        tid = str(p.get('id') or '')
        if tid not in trip_ids:
            raise Bad('unknown trip')
        with LOCK:
            d = self.load()
            items = d.get(tid)
            if items is None:
                items = self.of(tid)
            if action == 'trip_check_add':
                text = ' '.join(str(p.get('text') or '').split())[:120]
                if not text:
                    raise Bad('give the item a name')
                if len(items) >= 40:
                    raise Bad('the checklist is full')
                items.append({'id': 'c' + secrets.token_hex(4), 'text': text, 'done': False, 'date': None})
            else:
                it = next((x for x in items if x['id'] == p.get('item')), None)
                if not it:
                    raise Bad('that item is gone')
                if action == 'trip_check_set':
                    if 'done' in p:
                        it['done'] = bool(p['done'])
                    if 'date' in p:
                        if p['date'] and not _day(p['date']):
                            raise Bad('give the date as YYYY-MM-DD')
                        it['date'] = str(p['date'])[:10] if p['date'] else None
                    if p.get('text'):
                        it['text'] = ' '.join(str(p['text']).split())[:120]
                elif action == 'trip_check_remove':
                    items = [x for x in items if x is not it]
                else:
                    raise Bad('unknown action')
            d[tid] = items
            self._save(d)
            return {'id': tid, 'checklist': items}

    def due(self, trips, today, days=7):
        """Dated, unticked checklist items due within `days` (only items you gave a date) – for the digest (step 5)."""
        d = self.load()
        out = []
        for t in trips:
            for it in d.get(t['id']) or []:
                dd = _day(it.get('date'))
                if dd and not it.get('done') and dd <= today + datetime.timedelta(days=days):
                    out.append({'trip': t['id'], 'trip_title': t['title'], 'item': it['id'], 'text': it['text'], 'date': it['date']})
        return out


# ---------- Claude reading (setup/local-tasks/trip-read.md): checking and taking in what the run wrote ----------
READ_KINDS = {'flight', 'hotel', 'train', 'ferry', 'car', 'transfer', 'ticket', 'restaurant', 'booking'}
READ_STATUS = {'booked', 'quote', 'cancelled', 'changed'}


def _when_ok(v):
    v = str(v or '').strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', v):
        return v + 'T00:00'
    d = parse_when(v) if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', v) else None
    return v[:25] if d else None


def clean_read(result, asked):
    """The run's bookings, checked: only mails that were asked for, known kinds and statuses, real dates; text fields
    cut to size. Returns (bookings, none)."""
    mails = {m['message_id']: m for m in asked if m.get('message_id')}
    out = []
    for i, b in enumerate((result or {}).get('bookings') or []):
        if not isinstance(b, dict) or b.get('message_id') not in mails:
            continue
        start = _when_ok(b.get('start'))
        if not start:
            continue
        end = _when_ok(b.get('end')) or start
        if (parse_when(end) or parse_when(start)) < parse_when(start):
            end = start
        kind = b.get('kind') if b.get('kind') in READ_KINDS else 'booking'
        status = b.get('status') if b.get('status') in READ_STATUS else 'booked'
        txt = lambda k, n: ' '.join(str(b.get(k) or '').split())[:n]
        m = mails[b['message_id']]
        out.append({'kind': kind, 'status': status, 'title': txt('title', 160) or kind.capitalize(), 'start': start, 'end': end,
                    'place': txt('place', 80), 'ref': txt('ref', 40), 'provider': txt('provider', 80), 'number': txt('number', 20),
                    'from': txt('from', 60), 'to': txt('to', 60), 'address': txt('address', 200), 'notes': txt('notes', 200),
                    'travellers': [' '.join(str(x).split())[:80] for x in (b.get('travellers') or []) if str(x).strip()][:9],
                    'ticket': b.get('ticket') if isinstance(b.get('ticket'), int) and 0 <= b['ticket'] < 20 else None,
                    'confidence': 'read', 'source': dict({k: m.get(k) for k in ('account', 'message_id', 'subject', 'date', 'from')},
                                                         address=_addr(m.get('sender') or m.get('address') or m.get('from')))})
    none = [{'message_id': x.get('message_id'), 'reason': ' '.join(str(x.get('reason') or '').split())[:160]}
            for x in (result or {}).get('none') or [] if isinstance(x, dict) and x.get('message_id') in mails]
    # stable keys: the mail and the booking's place among that mail's bookings
    seen = {}
    for b in out:
        mid = b['source']['message_id']
        b['key'] = key_of(b, seen.get(mid, 0))
        seen[mid] = seen.get(mid, 0) + 1
    return out, none


def _addr(v):
    """The e-mail address in a From value ("Acme Air <news@acme-air.example>" → news@acme-air.example), or ''."""
    m = re.search(r'[\w.+%\'-]+@[\w-]+(?:\.[\w-]+)+', str(v or ''))
    return m.group(0).lower()[:200] if m else ''


FWD_DATE_RE = re.compile(r'^[ \t>*]*(date|sent|dato|sendt|datum|gesendt|envoyé|enviado|inviato)[ \t*]*:.*$', re.I | re.M)
# an older run's "it has ended" (when Trips was upcoming only): not a reason to keep a mail out any more
ENDED_RE = re.compile(r'.*\b(ended|already over|in the past|has passed)\b', re.I | re.S)
UNOPENED_RE = re.compile(r'\s*(could not|couldn.t|can.?not) (be )?open', re.I)


def take_read(store, bookings, none, today=None, trust=None):
    """Put what Claude read where it belongs: a mail already in a trip (by hand or by the rules) gets its real
    bookings in place of the old one; the rest is suggested (or offered to the trip whose dates it falls in) as on a
    scan; quotes are kept apart; mails without a booking leave "To sort" with the reason."""
    today = today or datetime.date.today()
    with LOCK:
        d = store.load()
        by_mid = {}
        for b in bookings:
            by_mid.setdefault(b['source']['message_id'], []).append(b)
        placed = set()
        for t in d['trips']:
            mids = {_mid(b) for b in t['bookings']}
            hit = [m for m in mids if m in by_mid]
            if not hit:
                continue
            old_of = {m: [b for b in t['bookings'] if _mid(b) == m] for m in hit}
            new_bs = []
            for m in hit:
                got = [dict(b) for b in by_mid[m] if b['status'] in ('booked', 'changed')]
                if not got:                               # a quote or a cancellation only: the trip keeps its booking
                    keep = old_of[m]
                    if any(b['status'] == 'cancelled' for b in by_mid[m]):
                        keep = [dict(b, status='cancelled') for b in keep]
                    new_bs += keep
                    continue
                if len(old_of[m]) == 1 and len(got) == 1:  # your own name and kind survive a reading of the same mail
                    o = old_of[m][0]
                    if o.get('own_status'):
                        got[0].update(status=o['status'], own_status=True)
                    if o.get('by_hand'):
                        got[0].update(by_hand=True)
                    if o.get('own_title'):
                        got[0].update(title=o['title'], own_title=True)
                    if o.get('own_kind'):
                        got[0].update(kind=o['kind'], own_kind=True)
                new_bs += got
            t['bookings'] = [b for b in t['bookings'] if _mid(b) not in hit] + new_bs
            t.setdefault('planning', [])
            t['planning'] = [q for q in t['planning'] if _mid(q) not in hit] + [b for m in hit for b in by_mid[m] if b['status'] == 'quote']
            _span(t)
            placed |= set(hit)
        # a mail Claude could not open was not read: it stays in "To sort" (and the next scan keeps it there)
        unopened = {n['message_id'] for n in none if UNOPENED_RE.match(str(n.get('reason') or ''))}
        none = [dict(n, v=2) for n in none if n['message_id'] not in unopened]    # v2: read with the 12-month rule
        done = {n['message_id'] for n in none} | set(by_mid)
        d['unsorted'] = [u for u in d['unsorted'] if u.get('message_id') not in done]
        d['read_none'] = ([n for n in d.get('read_none', []) if n.get('message_id') not in by_mid and n.get('message_id') not in {x['message_id'] for x in none}]
                          + none)[-200:]   # read again: the newer answer
        # an update (changed / cancelled) from a new mail goes to the booking it is about (same reference and leg):
        # applied when untouched, waiting for Apply / Ignore when you edited it – and that mail is not suggested again
        now = datetime.datetime.now().astimezone()
        for m, bs in by_mid.items():
            if m in placed:
                continue
            hit = [apply_update(d, b, now, trust) for b in bs if b['status'] in ('changed', 'cancelled')]
            if any(hit):
                placed.add(m)
        rest = [b for m, bs in by_mid.items() if m not in placed for b in bs if b['status'] in ('booked', 'changed')]
        d['quotes'] = (d.get('quotes', []) + [b for m, bs in by_mid.items() if m not in placed for b in bs if b['status'] == 'quote'])[-100:]
        store._save(d)
    if rest:
        # through the scan's own merge, so suggestions and "inside a trip's dates" work the same way
        d2 = store.load()
        # what's pending, without the rules' copies of the mails just read (the read bookings take their place)
        pending = [b for b in [b for s in d2['suggested'] for b in s['bookings']] + [b for t in d2['trips'] for b in t.get('new', [])]
                   if _mid(b) not in by_mid]
        store.merge_scan(pending + rest, today)
    return {'bookings': len(bookings), 'none': len(none), 'placed': len(placed)}
