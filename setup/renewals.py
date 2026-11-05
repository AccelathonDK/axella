"""Renewals (Receipts → Renewals): things that don't charge monthly but expire or renew on a date and need action in
time – insurance worth comparing, a domain, a passport, the car's inspection. Rules only, on the Mac mini; nothing
leaves the home, no Claude.

Sources: renewal and expiry mails (EN/DA, genuine sender only – DKIM/DMARC pass for the sender's own domain, scam-flagged
and private mail skipped by the caller), each a suggestion you confirm; yearly subscriptions from Subscriptions, linked
(not copied); and entries you add by hand. Notices that come through e-Boks or Digital Post are added by hand.

Never stored: document numbers (passport, ID, licence, policy numbers). There is no field for them, and a name or a
note that looks like one is refused with the reason.

state/renewals.json: {"items": {<id>: {...}}, "suggestions": {<message_id>: {...}}, "dismissed": [<message_id>],
                      "last_line": <date of the last digest line>}
"""
import datetime
import email
import email.policy
import email.utils
import json
import os
import re
import secrets
import threading

import recurring as R

LOCK = threading.Lock()
# kind → (label, default lead time in days, months to the next date when it renews; None = a one-off)
KINDS = {
    'insurance': ('Insurance', 42, 12), 'domain': ('Domain', 30, 12), 'membership': ('Membership', 30, 12),
    'account': ('Account', 30, 12), 'agreement': ('Agreement', 30, 12), 'passport': ('Passport', 183, None),
    'id_card': ('ID card', 183, None), 'driving_licence': ('Driving licence', 91, None),
    'vehicle_inspection': ('Vehicle inspection', 42, 24), 'other': ('Other', 30, None),
}
CURRENCIES = ('DKK', 'EUR', 'USD', 'SEK', 'NOK', 'GBP', 'CHF')
# a run of 6+ digits, or a token of 7+ letters and digits mixed (AB1234567) – what document numbers look like
DOCNO = re.compile(r'\d[\d\s-]{5,}\d|\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{7,}\b')
SUBJECT = re.compile(r'expir|udløb|renew|fornye|fornyelse|forny|due for renewal|time to renew|police|policy', re.I)
EXPIRE = re.compile(r'expires?|expiry|expiring|will expire|udløber|udløbsdato|ophører', re.I)
RENEW = re.compile(r'renews?|renewal|will be renewed|fornyes|fornyelse|forlænges|automatisk fornyet|auto-?renew', re.I)
AUTO = re.compile(r'automatically|auto-?renew|automatisk|will be renewed|fornyes automatisk|vi fornyer', re.I)
GUESS = (('domain', re.compile(r'\bdomain|domæne|\.(com|dk|net|org|io|app|dev)\b', re.I)),
         ('insurance', re.compile(r'insurance|forsikring|police\b|policy', re.I)),
         ('membership', re.compile(r'membership|medlemskab|kontingent', re.I)),
         ('agreement', re.compile(r'agreement|aftale|contract|kontrakt', re.I)),
         ('vehicle_inspection', re.compile(r'\bsyn\b|synsfrist|inspection|bilsyn', re.I)))


class Bad(Exception):
    pass


def _day(s):
    try:
        return datetime.date.fromisoformat(str(s or '')[:10])
    except ValueError:
        return None


def no_docno(text, what):
    if DOCNO.search(str(text or '')):
        raise Bad('%s looks like it holds a document or policy number – Axella never stores those; leave it out' % what)
    return text


def _clip(v, n):
    return re.sub(r'[\x00-\x1f\x7f]', ' ', str(v or '')).strip()[:n]


def add_months(d, n):
    return R._add_months(d, n)


def read_mail(raw, sent=None):
    """A renewal or expiry mail → a suggestion {kind, name, date, cost, currency, auto_renews, domain, auth_ok} or None.
    The name is the sender's own domain word (never a display name or text from the mail); the owner can rename it."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    subject = str(msg.get('Subject', ''))[:500]
    _, addr = email.utils.parseaddr(str(msg.get('From', ''))[:500])
    dom = addr.rsplit('@', 1)[-1].lower() if '@' in addr else ''
    if not dom or not SUBJECT.search(subject):
        return None
    try:
        sent = sent or email.utils.parsedate_to_datetime(str(msg.get('Date'))).date()
    except (TypeError, ValueError):
        sent = sent or datetime.date.today()
    text = ''
    for p in msg.walk():
        if p.is_multipart() or p.get_content_type() not in ('text/plain', 'text/html'):
            continue
        try:
            body = str(p.get_content())[:50000]
        except Exception:
            body = (p.get_payload(decode=True) or b'').decode('utf-8', 'ignore')[:50000]
        text += re.sub(r'<[^>]{0,2000}>', ' ', body) if p.get_content_type() == 'text/html' else body
    blob = subject + '\n' + re.sub(r'\s+', ' ', text)[:50000]
    m = EXPIRE.search(blob) or RENEW.search(blob)
    if not m:
        return None
    near = blob[max(0, m.start() - 80):m.start() + 400]
    dates = [d for d in R.dates_in(near, sent) if d > sent] or [d for d in R.dates_in(blob, sent) if d > sent]
    if not dates:
        return None
    amts = R.amounts_in(near) or R.amounts_in(blob)
    kind = next((k for k, rx in GUESS if rx.search(subject + ' ' + near)), 'other')
    base = R._base(dom)
    word = base.split('.')[0].replace('-', ' ').title()
    out = {'kind': kind, 'name': '%s %s' % (word, KINDS[kind][0].lower()) if kind != 'other' else word,
           'date': dates[0].isoformat(), 'cost': amts[0][0] if amts else None, 'currency': amts[0][1] if amts else None,
           'auto_renews': bool(AUTO.search(near)), 'domain': base, 'sent': sent.isoformat(), 'auth_ok': R.auth_ok(msg, dom)}
    return out if out['auth_ok'] else None


class Renewals:
    def __init__(self, state_dir):
        self.file = os.path.join(state_dir, 'renewals.json')

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        for k, v in (('items', {}), ('suggestions', {}), ('dismissed', [])):
            d.setdefault(k, v)
        return d

    def _save(self, d):
        d['dismissed'] = d['dismissed'][-500:]
        tmp = '%s.%d.%d.tmp' % (self.file, os.getpid(), threading.get_ident())
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)

    # ---- entries
    @staticmethod
    def _fields(p, old=None):
        e = dict(old or {})
        if 'name' in p or not old:
            name = _clip(p.get('name'), 80)
            if not name:
                raise Bad('give it a name')
            e['name'] = no_docno(name, 'The name')
        if 'kind' in p or not old:
            if p.get('kind') not in KINDS:
                raise Bad('pick a kind')
            e['kind'] = p['kind']
        if 'date' in p or not old:
            d = _day(p.get('date'))
            if not d:
                raise Bad('give the date as YYYY-MM-DD')
            e['date'] = d.isoformat()
        if 'lead_days' in p or not old:
            lead = p.get('lead_days')
            lead = KINDS[e['kind']][1] if lead in (None, '') else int(lead)
            if not 1 <= lead <= 400:
                raise Bad('lead time between 1 and 400 days')
            e['lead_days'] = lead
        if 'cost' in p:
            if p.get('cost') in (None, ''):
                e['cost'] = e['currency'] = None
            else:
                c = float(p['cost'])
                cur = str(p.get('currency') or 'DKK').upper()
                if c < 0 or c > 10_000_000 or cur not in CURRENCIES:
                    raise Bad('a cost and a currency (%s)' % ', '.join(CURRENCIES))
                e['cost'], e['currency'] = round(c, 2), cur
        if 'ctx' in p:
            if p['ctx'] not in ('work', 'private', None):
                raise Bad('work, private or none')
            e['ctx'] = p['ctx']
        if 'auto_renews' in p:
            e['auto_renews'] = bool(p['auto_renews'])
        if 'notes' in p:
            e['notes'] = no_docno(_clip(p.get('notes'), 500), 'The note') or None
        return e

    def action(self, action, p, today=None):
        today = today or datetime.date.today()
        with LOCK:
            d = self.load()
            if action == 'renewal_add':
                e = self._fields(p)
                e.update(id='rn' + secrets.token_hex(5), source=p.get('source') if p.get('source') in ('mail', 'hand') else 'hand',
                         status='active', created=today.isoformat(), cost=e.get('cost'), currency=e.get('currency'))
                e.setdefault('auto_renews', False)
                mid = str(p.get('message_id') or '')[:300]
                if mid:
                    if mid not in d['suggestions']:
                        raise Bad('that suggestion is gone')
                    d['suggestions'].pop(mid)
                    d['dismissed'].append(mid)
                    e['source'] = 'mail'
                d['items'][e['id']] = e
                self._save(d)
                return e
            if action == 'renewal_not':
                mid = str(p.get('message_id') or '')[:300]
                d['suggestions'].pop(mid, None)
                if mid and mid not in d['dismissed']:
                    d['dismissed'].append(mid)
                self._save(d)
                return 'ok'
            e = d['items'].get(str(p.get('id') or ''))
            if not e:
                raise Bad('unknown renewal')
            if action == 'renewal_update':
                d['items'][e['id']] = dict(self._fields({k: v for k, v in p.items() if k in
                                                         ('name', 'kind', 'date', 'lead_days', 'cost', 'currency', 'ctx', 'auto_renews', 'notes')}, e),
                                           snoozed_until=None if 'date' in p else e.get('snoozed_until'))
            elif action == 'renewal_snooze':
                days = {'week': 7, 'month': 30}.get(p.get('for'))
                if not days:
                    raise Bad('a week or a month')
                e['snoozed_until'] = (today + datetime.timedelta(days=days)).isoformat()
            elif action == 'renewal_let_renew':
                e['handled'] = e['date']                   # nothing to do this time – asked again after the date
            elif action == 'renewal_task':
                e['task_id'] = str(p.get('task_id') or '')[:60] or None
                e['handled'] = e['date']
            elif action == 'renewal_renewed':              # after the date: the next date (a year, or the kind's period, on)
                nd = _day(p.get('next')) or (add_months(_day(e['date']), KINDS[e['kind']][2]) if KINDS[e['kind']][2] else None)
                if not nd or nd <= _day(e['date']):
                    raise Bad('give the next date')
                e.update(date=nd.isoformat(), handled=None, snoozed_until=None, task_id=None, announced=None)
            elif action == 'renewal_past':
                e['status'] = 'past'
            elif action == 'renewal_delete':
                d['items'].pop(e['id'])
                d.setdefault('deleted', []).append(dict(e, deleted=today.isoformat()))
                d['deleted'] = d['deleted'][-50:]
            elif action == 'renewal_restore':
                raise Bad('unknown action')
            else:
                raise Bad('unknown action')
            self._save(d)
            return d['items'].get(e['id'], e)

    # ---- mail suggestions
    def suggest(self, found, known_domains=()):
        """New suggestions from renewal mails: offered once; a sender that is a known subscription's domain is left out
        (Subscriptions shows it, and the timeline links it)."""
        with LOCK:
            d = self.load()
            n = 0
            have = {(e.get('domain'), e.get('date')) for e in d['items'].values()}
            for s in found:
                mid = s.get('message_id')
                if not mid or mid in d['suggestions'] or mid in d['dismissed'] or s.get('domain') in known_domains:
                    continue
                if (s.get('domain'), s.get('date')) in have:
                    continue
                d['suggestions'][mid] = {k: s.get(k) for k in ('message_id', 'account', 'kind', 'name', 'date', 'cost', 'currency',
                                                               'auto_renews', 'domain', 'sent')}
                n += 1
            if len(d['suggestions']) > 100:
                d['suggestions'] = dict(sorted(d['suggestions'].items(), key=lambda kv: str(kv[1].get('sent') or ''))[-100:])
            self._save(d)
        return n

    # ---- what is due
    @staticmethod
    def due_from(e):
        return _day(e['date']) - datetime.timedelta(days=int(e.get('lead_days') or KINDS[e['kind']][1]))

    def state_of(self, e, today):
        """lead (in its lead time, nothing done yet) · waiting (before the lead time) · after (the date passed) · handled
        · snoozed · past."""
        if e.get('status') == 'past':
            return 'past'
        day = _day(e['date'])
        if day < today:
            return 'after'
        if e.get('handled') == e['date']:
            return 'handled'
        if e.get('snoozed_until') and _day(e['snoozed_until']) and _day(e['snoozed_until']) > today:
            return 'snoozed'
        return 'lead' if today >= self.due_from(e) else 'waiting'

    def view(self, today=None, yearly=(), trips=()):
        today = today or datetime.date.today()
        d = self.load()
        rows, past = [], []
        for e in d['items'].values():
            st = self.state_of(e, today)
            r = dict(e, state=st, days=(_day(e['date']) - today).days, lead_from=self.due_from(e).isoformat(),
                     label=KINDS[e['kind']][0], recurring=bool(KINDS[e['kind']][2]))
            if st == 'past':
                past.append(r)
            elif _day(e['date']) <= add_months(today, 12) or st == 'after':
                rows.append(r)
        # yearly subscriptions: linked, not copied – their actions stay on Subscriptions, they're never counted here
        for s in yearly:
            nd = _day(s.get('next'))
            if nd and today <= nd <= add_months(today, 12):
                rows.append({'id': 'sub:' + str(s.get('id')), 'name': s.get('vendor'), 'kind': 'subscription', 'label': 'Subscription',
                             'date': nd.isoformat(), 'days': (nd - today).days, 'cost': s.get('amount'), 'currency': s.get('currency'),
                             'auto_renews': True, 'source': 'subscription', 'state': 'linked', 'linked': True})
        rows.sort(key=lambda r: r['date'])
        return {'rows': rows, 'past': sorted(past, key=lambda r: r['date'], reverse=True)[:30],
                'suggestions': sorted(d['suggestions'].values(), key=lambda s: str(s.get('date') or '')),
                'trip_warnings': trip_warnings(d['items'].values(), trips, today=today), 'kinds': {k: {'label': v[0], 'lead_days': v[1], 'recurring': bool(v[2])}
                                                                                    for k, v in KINDS.items()}}

    def cards(self, today=None):
        """The suggested To do cards: entries in their lead time with nothing done yet."""
        today = today or datetime.date.today()
        return [dict(e, state='lead') for e in self.load()['items'].values() if self.state_of(e, today) == 'lead']

    def digest_line(self, today=None, scope=None):
        """At most one line: the renewals that reached their lead time and weren't announced yet (marked announced)."""
        today = today or datetime.date.today()
        with LOCK:
            d = self.load()
            new = [e for e in d['items'].values() if self.state_of(e, today) == 'lead' and e.get('announced') != e['date']
                   and (not scope or not e.get('ctx') or e['ctx'] in scope)]
            if not new:
                return None
            for e in new:
                e['announced'] = e['date']
            self._save(d)
        new.sort(key=lambda e: e['date'])
        e = new[0]
        day = _day(e['date'])
        when = '%d %s' % (day.day, day.strftime('%b'))
        cost = (' – %s last time' % R._fmt(e['cost'], e['currency'])) if e.get('cost') and e.get('currency') else ''
        if e['kind'] == 'insurance':
            cmp_ = day - datetime.timedelta(days=14)
            first = '%s renews %s%s. Compare before %d %s?' % (e['name'], when, cost, cmp_.day, cmp_.strftime('%b'))
        elif KINDS[e['kind']][2] is None:
            first = '%s expires %s – renew in time.' % (e['name'], when)
        else:
            first = '%s %s %s%s.' % (e['name'], 'renews' if e.get('auto_renews') else 'is due', when, cost)
        return first + ('' if len(new) == 1 else ' And %d more renewal%s.' % (len(new) - 1, '' if len(new) == 2 else 's'))

    def add_to_digest(self, digests_dir, name):
        """One line in a morning digest (05:00–09:59) when a renewal reaches its lead time – deterministic, once."""
        import digestfile
        if not re.match(r'^\d{4}-\d{2}-\d{2}-0[5-9]\d\d\.json$', name):
            return None
        today = _day(name[:10]) or datetime.date.today()

        def change(dg):
            if not isinstance(dg, dict) or not isinstance(dg.get('items'), list) or dg.get('renewals_line') is not None:
                return False, None
            sc = dg.get('scope') if isinstance(dg.get('scope'), list) and dg.get('scope') else None
            text = self.digest_line(today, sc)
            dg['renewals_line'] = 1 if text else 0
            if text:
                dg['items'].append({'id': '%s-p3-renewals' % name[:-5].replace('-', '')[:12], 'section': 'p3', 'channel': 'renewals',
                                    'topic': 'Renewals', 'headline': text, 'detail': 'Receipts → Renewals. Axella never renews or pays anything.',
                                    'link': 'renewals', 'first_seen': dg.get('generated') or ''})
                R.add_spoken(digests_dir, name, dg, text)
            return True, bool(text)
        return digestfile.update(os.path.join(digests_dir, name), change)


def trip_warnings(items, trips, months=6, today=None):
    """A confirmed trip that ends less than 6 months before a passport's expiry (or after it): shown on Renewals and on
    the trip."""
    out = []
    for e in items:
        exp = _day(e.get('date'))
        if e.get('kind') != 'passport' or e.get('status') == 'past' or not exp:
            continue
        for t in trips:
            end = _day(t.get('end'))
            if not end or t.get('status') == 'suggested' or end < (today or datetime.date.today()) - datetime.timedelta(days=1):
                continue
            if end > exp:
                text = '%s expires before you return from %s.' % (e['name'], t.get('title'))
                m = 0
            elif exp < add_months(end, months):
                m = max(0, (exp.year - end.year) * 12 + exp.month - end.month - (1 if exp.day < end.day else 0))
                text = '%s expires %s after you return from %s – many countries require 6.' % (
                    e['name'], 'less than a month' if m == 0 else '%d month%s' % (m, '' if m == 1 else 's'), t.get('title'))
            else:
                continue
            out.append({'trip': t.get('id'), 'trip_title': t.get('title'), 'renewal': e['id'], 'months': m, 'text': text})
    return out
