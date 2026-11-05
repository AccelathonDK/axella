"""Subscriptions overview: paid recurring charges (dev request "feature pack, part 2", #2 – §4 of the feature pack).

Not the newsletters module (subscriptions.py = bulk mail). Local rules only, no AI:
  - the Receipts register (documents.py): the same vendor, in the same currency, at a regular interval (monthly,
    quarterly, yearly) with a similar amount – at least three receipts, invoices or bills;
  - renewal, trial-ending and price-change mails from Mail's index (subject words, then the mail's own text): one such
    mail is enough to list a subscription. A mail the scam check flags is ignored. Links are never opened; the vendor's
    own account link is only kept for "Open account page" (opened by you, on your device).
Changes (new, price up/down, trial ending, not seen for a while) are noted once each; the morning digest gets one
quiet line for the new ones (add_to_digest, called by the push watcher – deterministic, no prompt involved).
Axella never cancels, pays or changes anything with a vendor.

state/recurring.json:
  {"subs": {<id = vendor_key:currency>: {"id", "vendor", "vendor_key", "currency", "amount", "interval", "monthly",
            "first_seen", "last_seen", "next", "count", "history": [{"date", "amount", "message_id"}], "source",
            "account_link", "status": "active|cancelled|not", "ctx", "project", "company", "auto_ctx"}},
   "changes": [{"id", "sub", "kind", "at", "text", "announced", "seen"}],
   "notices": {<message_id>: {...}}, "built": iso, "last_scan": iso}
Python 3.9.
"""
import datetime
import email
import email.policy
import email.utils
import json
import os
import re
import statistics
import threading

LOCK = threading.Lock()
KINDS = ('receipt', 'invoice', 'bill')
INTERVALS = (('monthly', 30.44, 24, 38), ('quarterly', 91.31, 80, 103), ('yearly', 365.25, 340, 392))
PER_MONTH = {'monthly': 1.0, 'quarterly': 1 / 3.0, 'yearly': 1 / 12.0}
LABEL = {'monthly': 'month', 'quarterly': 'quarter', 'yearly': 'year'}
STATUSES = ('active', 'cancelled', 'not')

NOTICE_SUBJ = re.compile(r'renew|renewal|fornye|fornyelse|trial|prøveperiode|price (change|increase|update|is changing)|'
                         r'new price|prisændring|ny pris|prisstigning|prisjustering|your (subscription|membership|plan)|'
                         r'dit (abonnement|medlemskab)', re.I)
TRIAL = re.compile(r'(free )?trial (ends|is ending|will end|expires|period ends)|prøveperiode(n)? (udløber|slutter|ophører)', re.I)
PRICE = re.compile(r'price (change|increase|update|is changing|will change|goes up)|new price|prisændring|ny pris|'
                   r'prisstigning|prisjustering|hæver prisen|prisen (stiger|ændres)', re.I)
RENEW = re.compile(r'(will |automatically )?renew(s|al|ed)?\b|fornyes|fornyelse|automatisk forny', re.I)
EVERY = (('yearly', re.compile(r'\b(yearly|annual(ly)?|per year|a year|/\s?(year|yr)|årlig(t)?|pr\.? år|om året)\b', re.I)),
         ('quarterly', re.compile(r'\b(quarterly|per quarter|kvartalsvis|pr\.? kvartal)\b', re.I)),
         ('monthly', re.compile(r'\b(monthly|per month|a month|/\s?(month|mo)|månedlig(t)?|pr\.? md\.?|pr\.? måned|om måneden)\b', re.I)))
CUR = {'dkk': 'DKK', 'kr': 'DKK', 'kr.': 'DKK', 'eur': 'EUR', '€': 'EUR', 'usd': 'USD', '$': 'USD', 'sek': 'SEK', 'nok': 'NOK',
       'gbp': 'GBP', '£': 'GBP', 'chf': 'CHF'}
_C = r'DKK|EUR|USD|SEK|NOK|GBP|CHF|kr\.?|€|\$|£'
_N = r'\d{1,3}(?:[.,  ]\d{3}){0,3}(?:[.,]\d{1,2})?|\d{1,7}(?:[.,]\d{1,2})?'
AMOUNT = re.compile(r'(?:(?P<c1>%s)\s?(?P<a1>%s))|(?:(?P<a2>%s)\s?(?P<c2>%s))(?![a-z])' % (_C, _N, _N, _C), re.I)
MONTHS = {m: i + 1 for i, m in enumerate('january february march april may june july august september october november december'.split())}
MONTHS.update({m: i + 1 for i, m in enumerate('januar februar marts april maj juni juli august september oktober november december'.split())})
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MON = '|'.join(sorted(MONTHS, key=len, reverse=True))
DATE_RES = (
    ('iso', re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')),
    ('dmy', re.compile(r'\b(\d{1,2})[./](\d{1,2})[./](\d{4}|\d{2})\b')),
    ('dmon', re.compile(r'\b(\d{1,2})\.?\s+(%s)\.?,?\s*(\d{4})?\b' % MON, re.I)),
    ('mond', re.compile(r'\b(%s)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?\b' % MON, re.I)),
)
IN_DAYS = re.compile(r'\b(?:in|om)\s+(\d{1,2})\s+(?:days?|dage?)\b', re.I)
ACCOUNT_WORDS = re.compile(r'account|manage|subscription|billing|membership|settings|abonnement|konto|indstillinger|medlemskab', re.I)
GENERIC_NAMES = re.compile(r'^(no-?reply|noreply|info|support|billing|service|team|notifications?|hello|hej|kundeservice)$', re.I)


def vendor_key(name):
    return re.sub(r'[^a-z0-9]+', '', (name or '').lower())[:60]


def _num(s):
    """'1.245,00' → 1245.0, '1,245.00' → 1245.0, '139,00' → 139.0, '9.99' → 9.99, '1 245' → 1245.0"""
    s = re.sub(r'[  ]', '', str(s or ''))
    if not s:
        return None
    if ',' in s and '.' in s:
        dec = ',' if s.rfind(',') > s.rfind('.') else '.'
        s = s.replace('.' if dec == ',' else ',', '').replace(dec, '.')
    elif ',' in s or '.' in s:
        sep = ',' if ',' in s else '.'
        head, _, tail = s.rpartition(sep)
        s = (head.replace(sep, '') + '.' + tail) if len(tail) in (1, 2) else s.replace(sep, '')
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def amounts_in(text):
    """[(amount, currency), …] in reading order."""
    out = []
    for m in AMOUNT.finditer(str(text or '')[:50000]):
        c = (m.group('c1') or m.group('c2') or '').lower()
        a = _num(m.group('a1') or m.group('a2'))
        if a and a > 0 and c in CUR:
            out.append((a, CUR[c]))
    return out


def _date(y, mo, d):
    try:
        y = int(y)
        y = y + 2000 if y < 100 else y
        return datetime.date(y, int(mo), int(d))
    except (TypeError, ValueError):
        return None


def dates_in(text, sent):
    """Dates in reading order (a missing year = the next such day on or after the mail's own date)."""
    text = str(text or '')[:50000]
    found = []
    for kind, rx in DATE_RES:
        for m in rx.finditer(text):
            g = m.groups()
            if kind == 'iso':
                d = _date(g[0], g[1], g[2])
            elif kind == 'dmy':
                d = _date(g[2], g[1], g[0])
            else:
                day, mon = (g[0], g[1]) if kind == 'dmon' else (g[1], g[0])
                mo = MONTHS.get(mon.lower().rstrip('.'))
                d = _date(g[2] or sent.year, mo, day) if mo else None
                if d and not g[2] and d < sent:
                    d = _date(sent.year + 1, mo, day)
            if d:
                found.append((m.start(), d))
    for m in IN_DAYS.finditer(text):
        found.append((m.start(), sent + datetime.timedelta(days=int(m.group(1)))))
    return [d for _, d in sorted(found)]


def interval_in(text):
    for name, rx in EVERY:
        if rx.search(str(text or '')[:50000]):
            return name
    return None


def _base(d):
    p = [x for x in str(d or '').lower().split('.') if x]
    if len(p) >= 3 and len(p[-1]) == 2 and p[-2] in ('co', 'com', 'org', 'net'):
        return '.'.join(p[-3:])
    return '.'.join(p[-2:])


def read_notice(raw, sent=None):
    """A renewal / trial / price-change mail → {"kind", "vendor", "domain", "date", "amount", "currency", "old_amount",
    "interval", "account_link"} or None. Rules only; the text never leaves this function."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    subject = str(msg.get('Subject', ''))[:500]
    name, addr = email.utils.parseaddr(str(msg.get('From', ''))[:500])
    try:
        sent = sent or email.utils.parsedate_to_datetime(str(msg.get('Date'))).date()
    except (TypeError, ValueError):
        sent = sent or datetime.date.today()
    text, htm = '', ''
    for p in msg.walk():
        if p.is_multipart():
            continue
        if p.get_content_type() in ('text/plain', 'text/html'):
            try:
                body = str(p.get_content())[:50000]
            except Exception:
                body = (p.get_payload(decode=True) or b'').decode('utf-8', 'ignore')[:50000]
            if p.get_content_type() == 'text/plain':
                text += body
            else:
                htm += body
    if not text and htm:
        text = re.sub(r'<[^>]{0,2000}>', ' ', htm)
    text = re.sub(r'[ \t ]+', ' ', text)[:50000]
    blob = subject + '\n' + text
    kind = 'trial' if TRIAL.search(blob) else 'price' if PRICE.search(blob) else 'renewal' if RENEW.search(blob) else None
    if not kind:
        return None
    rx = {'trial': TRIAL, 'price': PRICE, 'renewal': RENEW}[kind]
    m = rx.search(blob)
    near = blob[m.start():m.start() + 600] if m else blob
    later = [d for d in dates_in(near, sent) if d >= sent] or [d for d in dates_in(blob, sent) if d >= sent]
    amts = amounts_in(near) or amounts_in(blob)
    dom = addr.rsplit('@', 1)[-1].lower() if '@' in addr else ''
    vendor = name.strip().strip('"') if name and not GENERIC_NAMES.match(name.strip()) and '@' not in name else ''
    vendor = re.sub(r'\s+(team|billing|support|no-?reply)$', '', vendor, flags=re.I)[:60] or \
        (_base(dom).split('.')[0].replace('-', ' ').title() if dom else '')
    link = None
    from safety import _Links, find_links, _host                     # the same linear link search as the scam check
    pl = _Links()
    try:
        pl.feed(htm[:50000])
    except Exception:
        pass
    cands = [(h, t) for h, t in pl.links] + [(u, '') for u in find_links(text)]
    for href, label in cands:
        h = _host(href[:2000])
        if h and dom and _base(h) == _base(dom) and href.lower().startswith('https://') and \
                (ACCOUNT_WORDS.search(label[:300]) or ACCOUNT_WORDS.search(href[:300])):
            link = href[:500]
            break
    out = {'kind': kind, 'vendor': vendor, 'domain': _base(dom) if dom else '', 'date': later[0].isoformat() if later else None,
           'interval': interval_in(near) or interval_in(blob), 'account_link': link, 'sent': sent.isoformat(),
           'auth_ok': auth_ok(msg, dom)}
    if amts:
        if kind == 'price' and len(amts) >= 2 and amts[0][1] == amts[1][1] and amts[0][0] != amts[1][0]:
            out.update(old_amount=amts[0][0], amount=amts[1][0], currency=amts[1][1])
        else:
            out.update(amount=amts[0][0], currency=amts[0][1])
    return out


def auth_ok(msg, dom):
    """True when your own mail provider says DKIM or DMARC passed for the sender's own (base) domain, and no
    header says the checks failed (safety.sender_checks – the same rule as the scam check)."""
    if not dom:
        return False
    from safety import sender_checks
    chk = sender_checks(msg)
    return not chk['failed'] and _base(dom) in chk['passed']


def _interval(gaps):
    if not gaps:
        return None
    med = statistics.median(gaps)
    for name, days, lo, hi in INTERVALS:
        if lo <= med <= hi and sum(1 for g in gaps if lo <= g <= hi) >= max(2, round(len(gaps) * 0.6)):
            return name
    return None


def _add_months(d, n):
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    last = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return datetime.date(y, m, min(d.day, last))


STEP_MONTHS = {'monthly': 1, 'quarterly': 3, 'yearly': 12}


def _day(s):
    try:
        return datetime.date.fromisoformat(str(s or '')[:10])
    except ValueError:
        return None


def detect(documents, today=None):
    """{id: sub} from the Receipts register – at least three regular charges with similar amounts."""
    today = today or datetime.date.today()
    groups = {}
    for doc in documents.values() if isinstance(documents, dict) else documents:
        if not isinstance(doc, dict) or doc.get('hidden') or doc.get('kind') not in KINDS:
            continue
        amt, cur, d = doc.get('amount'), doc.get('currency'), _day(doc.get('date'))
        if not isinstance(amt, (int, float)) or amt <= 0 or not cur or not d or not doc.get('vendor_key'):
            continue
        groups.setdefault('%s:%s' % (doc['vendor_key'], cur), []).append((d, float(amt), doc))
    out = {}
    for gid0, allrows in groups.items():
        # one vendor can bill several things (a plan and one-off purchases): group the charges by similar amount first
        clusters = []
        for r in sorted(allrows, key=lambda r: r[1]):
            if clusters and abs(r[1] - statistics.median(x[1] for x in clusters[-1])) <= max(0.25 * statistics.median(x[1] for x in clusters[-1]), 5):
                clusters[-1].append(r)
            else:
                clusters.append([r])
        regular = [c for c in clusters if len({x[0] for x in c}) >= 3 and _interval(_gaps(c))]
        for rows in regular:
            gid = gid0 if len(regular) == 1 else '%s:%d' % (gid0, round(min(x[1] for x in rows)))
            sub = _sub(gid, rows)
            if sub:
                out[gid] = sub
    return out


def _gaps(rows):
    days = sorted({r[0] for r in rows})
    return [(b - a).days for a, b in zip(days, days[1:])]


def _sub(gid, rows):
    """One regular series (similar amounts) → a subscription, or None when it isn't regular."""
    rows.sort(key=lambda r: r[0])
    by_day = {}
    for d, a, doc in rows:                        # one charge per day (an invoice and its receipt are one)
        by_day.setdefault(d, (d, a, doc))
    rows = list(by_day.values())
    if len(rows) < 3:
        return None
    iv = _interval([(b[0] - a[0]).days for a, b in zip(rows, rows[1:])])
    if not iv:
        return None
    last, doc = rows[-1][0], rows[-1][2]
    names = {}
    for r in rows:
        names[r[2].get('vendor') or ''] = names.get(r[2].get('vendor') or '', 0) + 1
    return {'id': gid, 'vendor': max(names, key=names.get) or doc.get('vendor_key'), 'vendor_key': doc['vendor_key'],
                'currency': doc['currency'], 'amount': rows[-1][1], 'interval': iv,
                'monthly': round(rows[-1][1] * PER_MONTH[iv], 2), 'first_seen': rows[0][0].isoformat(),
                'last_seen': last.isoformat(), 'next': _add_months(last, STEP_MONTHS[iv]).isoformat(),
                'count': len(rows), 'source': 'receipts',
                'history': [{'date': r[0].isoformat(), 'amount': r[1], 'message_id': r[2].get('message_id')} for r in rows][-24:],
                'domains': sorted({_base(str(r[2].get('from') or '').rsplit('@', 1)[-1].strip('<> ').lower())
                                   for r in rows if '@' in str(r[2].get('from') or '')}),
                'auto_ctx': 'work' if any(r[2].get('ctx') == 'work' or r[2].get('sent') for r in rows) else None,
                'project': next((r[2].get('project') for r in reversed(rows) if r[2].get('project')), None)}


def store_items(recs, charged):
    """{id: sub} – one subscription per item on a store's receipts (app_stores.py). Charges are the itemised receipts
    with a total; a renewal or trial mail without one only adds the next date or the trial's end. Purchases are left
    out (they stay in Receipts)."""
    import app_stores as S
    rows = {}
    for mid, r in sorted(recs.items(), key=lambda kv: kv[1].get('sent', '')):
        if not r.get('auth_ok') or r.get('store') not in S.STORES or not _day(r.get('sent')):
            continue
        for it in r.get('items') or []:
            if not it.get('name'):
                continue
            key = (r['store'], vendor_key(it['name']))
            rows.setdefault(key, []).append((_day(r['sent']), it, mid if mid in charged else None))
    out = {}
    for (store, vk), rs in rows.items():
        if not vk or not any(it.get('kind') == 'subscription' for _, it, _ in rs):
            continue
        st = S.STORES[store]
        by_day = {}
        for day, it, mid in rs:
            if mid and it.get('amount') is not None:
                by_day.setdefault(day, (day, it, mid))
        ch = [by_day[k] for k in sorted(by_day)]
        last_it = rs[-1][1]
        iv = next((it.get('interval') for _, it, _ in reversed(rs) if it.get('interval')), None)
        if not iv and len(ch) >= 2:
            g = [(b[0] - a[0]).days for a, b in zip(ch, ch[1:])]
            iv = _interval(g) if len(g) >= 2 else next((n for n, _, lo, hi in INTERVALS if lo <= g[0] <= hi), None)
        amount = ch[-1][1]['amount'] if ch else last_it.get('amount')
        cur = (ch[-1][1] if ch else last_it).get('currency')
        last = ch[-1][0] if ch else rs[-1][0]
        nxt = max((it.get('renews') or '' for _, it, _ in rs), default='') or None
        if (not nxt or nxt < last.isoformat()) and iv:
            nxt = _add_months(last, STEP_MONTHS[iv]).isoformat()
        trial = max((it.get('trial_ends') or '' for _, it, _ in rs), default='') or None
        sid = 'store:%s:%s' % (store, vk)
        out[sid] = {'id': sid, 'vendor': last_it['name'], 'vendor_key': vk, 'store': store, 'store_name': st['name'],
                    'manage': st['manage'], 'plan': next((it.get('plan') for _, it, _ in reversed(rs) if it.get('plan')), None),
                    'currency': cur, 'amount': amount, 'interval': iv,
                    'monthly': round(amount * PER_MONTH[iv], 2) if iv and amount is not None else None,
                    'first_seen': rs[0][0].isoformat(), 'last_seen': last.isoformat(), 'next': nxt, 'trial_ends': trial,
                    'count': len(ch), 'source': 'store', 'domains': [st['domain']],
                    'history': [{'date': c[0].isoformat(), 'amount': c[1]['amount'], 'message_id': c[2]} for c in ch][-24:],
                    'auto_ctx': None, 'project': None}
    return out


def _fmt(amount, cur):
    s = ('%.2f' % amount).rstrip('0').rstrip('.') if amount != int(amount) else '%d' % amount
    return '%s %s' % (s.replace('.', ','), cur)


class Bad(Exception):
    pass


class Recurring:
    def __init__(self, state_dir, digests_dir=None, log=None):
        self.file = os.path.join(state_dir, 'recurring.json')
        self.digests = digests_dir
        self.log = log

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        for k, v in (('subs', {}), ('changes', []), ('notices', {}), ('store_receipts', {}), ('store_tags', {}), ('store_seen', {})):
            d.setdefault(k, v)
        return d

    def _save(self, d):
        d['changes'] = d['changes'][-300:]
        d['notices'] = dict(sorted(d['notices'].items(), key=lambda kv: kv[1].get('sent', ''))[-300:])
        d['store_receipts'] = dict(sorted(d['store_receipts'].items(), key=lambda kv: kv[1].get('sent', ''))[-400:])
        tmp = self.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.file)

    def _change(self, d, sub, kind, key, text, quiet=False):
        cid = '%s|%s|%s' % (sub['id'], kind, key)
        if any(c['id'] == cid for c in d['changes']):
            return
        d['changes'].append({'id': cid, 'sub': sub['id'], 'kind': kind, 'text': text,
                             'at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                             'announced': 'quiet' if quiet else None, 'seen': bool(quiet),
                             **({'store': sub['store_name']} if sub.get('store_name') and sub.get('source') == 'store' else {})})

    def refresh(self, documents, notices=(), today=None, receipts=()):
        """Rebuild from the register, the notice mails and the store receipts (app_stores.py), keeping your own choices
        and every change noted before."""
        today = today or datetime.date.today()
        with LOCK:
            d = self.load()
            first = not d.get('built')                     # the very first build notes nothing as "new"
            for r in receipts:
                if isinstance(r, dict) and r.get('message_id'):
                    d['store_receipts'][r['message_id']] = r
            found, store_new, drop = self._with_stores(d, documents, today, first)
            for n in notices:
                if n.get('message_id'):
                    d['notices'][n['message_id']] = n
            # a notice joins a subscription of the same vendor (name or mail domain), or lists one by itself
            for mid, n in sorted(d['notices'].items(), key=lambda kv: kv[1].get('sent', '')):
                # matched by the mail's own domain only – a display name is free text anyone can write
                dom = n.get('domain') or ''
                if dom in d.get('_store_domains', ()):      # a store's own mail is read item by item (app_stores.py)
                    continue
                sub = next((s for s in found.values() if dom and dom in s.get('domains', [])), None)
                if sub is None and dom and (n.get('kind') == 'renewal' or n.get('kind') == 'trial') and (n.get('amount') or n.get('date')):
                    cur = n.get('currency') or ''
                    word = dom.split('.')[0].replace('-', ' ').title()       # the domain word, never the display name
                    vk = vendor_key(dom.split('.')[0])
                    sid = '%s:%s' % (vk, cur or 'notice')
                    sub = found.setdefault(sid, {'id': sid, 'vendor': word or vk, 'vendor_key': vk, 'currency': cur or None,
                                                 'amount': n.get('amount'), 'interval': n.get('interval'), 'count': 0,
                                                 'first_seen': n.get('sent'), 'last_seen': n.get('sent'), 'next': n.get('date'),
                                                 'source': 'mail', 'history': [], 'domains': [n['domain']] if n.get('domain') else []})
                    if sub['amount'] and sub['interval']:
                        sub['monthly'] = round(sub['amount'] * PER_MONTH[sub['interval']], 2)
                if sub is None:
                    continue
                # Open account page: only for a vendor known from Receipts, from its own Receipts domain, and only when the
                # mail really is from that domain (DKIM or DMARC pass) – never for a subscription known from mail alone
                if n.get('account_link') and sub.get('source') == 'receipts' and dom in sub.get('domains', []) and n.get('auth_ok'):
                    sub['account_link'] = n['account_link']
                if n.get('kind') in ('renewal', 'trial') and n.get('date') and n['date'] >= (sub.get('last_seen') or ''):
                    sub['next'] = n['date']
                n['sub'] = sub['id']
            for sid, sub in found.items():
                old = d['subs'].get(sid) or {}
                for k in ('status', 'ctx', 'project', 'company'):
                    if old.get(k) is not None and (k != 'project' or old.get('project_manual')):
                        sub[k] = old[k]
                sub['project_manual'] = old.get('project_manual', sub.get('project_manual', False))
                sub.setdefault('status', 'active')
                if not old and sub.get('store_other'):
                    pass                                    # "<store> – other" is the old store row, not something new
                elif not old:
                    self._change(d, sub, 'new', sub['first_seen'], 'New subscription: %s%s' % (
                        sub['vendor'], ' – ' + _fmt(sub['amount'], sub['currency']) + '/' + LABEL[sub['interval']]
                        if sub.get('amount') and sub.get('currency') and sub.get('interval') else ''),
                        quiet=first or sub.get('store') in store_new)
                h = sub.get('history') or []
                if len(h) >= 2 and h[-2]['amount'] and abs(h[-1]['amount'] - h[-2]['amount']) / h[-2]['amount'] > 0.02:
                    up = h[-1]['amount'] > h[-2]['amount']
                    self._change(d, sub, 'price_up' if up else 'price_down', h[-1]['date'], '%s price went %s to %s/%s' % (
                        sub['vendor'], 'up' if up else 'down', _fmt(h[-1]['amount'], sub['currency']), LABEL[sub['interval']]),
                        quiet=first or _day(h[-1]['date']) < today - datetime.timedelta(days=45))
                watch = sub.get('source') in ('receipts', 'store') and not sub.get('store_other')
                if sub.get('interval') and sub['status'] == 'active' and watch:
                    step = dict((n, x) for n, x, _, _ in INTERVALS)[sub['interval']]
                    due = _day(sub['last_seen']) + datetime.timedelta(days=round(step * 1.5))
                    if due < today:
                        self._change(d, sub, 'quiet', sub['next'], 'Not seen for a while: %s – possibly cancelled' % sub['vendor'], quiet=True)
                sub['quiet'] = bool(sub.get('interval') and watch and
                                    _day(sub['last_seen']) + datetime.timedelta(days=round(dict((n, x) for n, x, _, _ in INTERVALS)[sub['interval']] * 1.5)) < today)
                if sub.get('trial_ends') and _day(sub['trial_ends']) and _day(sub['trial_ends']) >= today and sub['status'] == 'active':
                    when = _day(sub['trial_ends'])
                    self._change(d, sub, 'trial', sub['trial_ends'], 'Your free trial of %s ends on %s' % (
                        sub['vendor'], when.strftime('%A') if (when - today).days < 7 else '%d %s' % (when.day, when.strftime('%B'))))
            for mid, n in d['notices'].items():
                sub = found.get(n.get('sub') or '')
                if not sub:
                    continue
                if n.get('kind') == 'trial' and n.get('date') and _day(n['date']) and _day(n['date']) >= today:
                    when = _day(n['date'])
                    self._change(d, sub, 'trial', mid, 'Your free trial of %s ends on %s' % (
                        sub['vendor'], when.strftime('%A') if (when - today).days < 7 else '%d %s' % (when.day, when.strftime('%B'))))
                if n.get('kind') == 'price' and n.get('amount') and n.get('currency'):
                    old = n.get('old_amount')
                    self._change(d, sub, 'price_up' if not old or n['amount'] > old else 'price_down', mid, '%s price is changing to %s%s' % (
                        sub['vendor'], _fmt(n['amount'], n['currency']), '/' + LABEL[sub['interval']] if sub.get('interval') else ''))
            # subscriptions no longer found keep their history and your choices (a vendor may skip a month)
            for sid, old in d['subs'].items():
                if sid not in found and sid not in drop:
                    found[sid] = {k: v for k, v in dict(old, gone=True).items() if k != 'account_link'}
            d['subs'] = found
            d.pop('_store_domains', None)
            d['built'] = d.get('built') or datetime.datetime.now().astimezone().isoformat(timespec='seconds')
            d['last_scan'] = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
            self._save(d)
            return d

    def _with_stores(self, d, documents, today, first):
        """detect() over the register with the itemised store charges taken out, plus one subscription per store item.
        Returns (found, the stores itemised for the first time now, ids to drop for good)."""
        import app_stores as S
        recs = d['store_receipts']
        charged = {mid: r for mid, r in recs.items() if S.itemised(r) and (r.get('total') is not None or r.get('subtotal') is not None)}
        docs = documents.values() if isinstance(documents, dict) else documents
        docs = [x for x in docs if isinstance(x, dict) and x.get('message_id') not in charged]
        found = detect(docs, today)
        items = store_items(recs, charged)
        live = {s['store'] for s in items.values()}
        d['_store_domains'] = {S.STORES[k]['domain'] for k in live}
        store_new, drop = set(), set()
        for key in live:
            st = S.STORES[key]
            if key not in d['store_seen']:
                store_new.add(key)
                d['store_seen'][key] = today.isoformat()
            # the old one-row store: its tags become the group's defaults, the row itself goes
            for sid, old in list(d['subs'].items()):
                if not sid.startswith('store:') and st['domain'] in (old.get('domains') or []):
                    tags = d['store_tags'].setdefault(key, {})
                    for k in ('ctx', 'project', 'company'):
                        if old.get(k) is not None and k not in tags:
                            tags[k] = old[k]
                    drop.add(sid)
            first_it = min((_day(r['sent']) for r in charged.values() if r.get('store') == key), default=today)
            loose = [_day(x.get('date')) for x in docs if x.get('kind') in KINDS and _day(x.get('date')) and
                     _base(str(x.get('from') or '').rsplit('@', 1)[-1].strip('<> ').lower()) == st['domain']]
            covered = (today - first_it).days >= 90 and not any(x >= today - datetime.timedelta(days=90) for x in loose)
            for gid, sub in list(found.items()):
                if st['domain'] not in sub.get('domains', []):
                    continue
                del found[gid]
                oid = 'store:%s:other:%s' % (key, sub.get('currency') or '')
                if covered:                                 # three months fully itemised: "other" is gone for good
                    drop.add(oid)
                    continue
                found[oid] = dict(sub, id=oid, vendor='%s – other' % st['name'], store=key, store_name=st['name'],
                                  manage=st['manage'], store_other=True,
                                  superseded=_day(sub['last_seen']) < first_it)   # charges from before the itemised receipts
            for sid in [x for x in d['subs'] if x.startswith('store:%s:other:' % key) and x not in found]:
                if covered:
                    drop.add(sid)
        for sid, sub in items.items():
            if sid not in d['subs']:                        # a new item takes the group's tags
                for k, v in (d['store_tags'].get(sub['store']) or {}).items():
                    if v is not None:
                        sub[k] = v
                sub['project_manual'] = bool(sub.get('project'))
            found[sid] = sub
        # a store with a rule set but no itemised receipts yet stays one row – with the store's own page
        for sub in found.values():
            k = next((k for k, st in S.STORES.items() if st['domain'] in sub.get('domains', [])), None)
            if k and not sub.get('store'):
                sub.update(store=k, store_name=S.STORES[k]['name'], manage=S.STORES[k]['manage'])
        return found, store_new, drop

    def view(self):
        d = self.load()
        subs = sorted(d['subs'].values(), key=lambda s: (s.get('status') != 'active', -(s.get('monthly') or 0)))
        totals = {}
        for s in subs:
            if s.get('status') == 'active' and not s.get('gone') and not s.get('superseded') and s.get('monthly') and s.get('currency'):
                t = totals.setdefault(s['currency'], {'month': 0.0, 'year': 0.0, 'count': 0})
                t['month'] = round(t['month'] + s['monthly'], 2)
                per_year = (s.get('amount') or 0) * {'monthly': 12, 'quarterly': 4, 'yearly': 1}.get(s.get('interval'), 0)
                t['year'] = round(t['year'] + (per_year or s['monthly'] * 12), 2)   # a yearly charge is exact
                t['count'] += 1
        changes = [c for c in d['changes'] if not c.get('seen')][-20:]
        import app_stores as S
        stores = {}
        for s in subs:
            if s.get('store') and not s.get('gone'):
                g = stores.setdefault(s['store'], {'name': S.STORES[s['store']]['name'], 'manage': S.STORES[s['store']]['manage'],
                                                   'count': 0, 'month': {}, 'tags': d['store_tags'].get(s['store']) or {}})
                if s.get('source') == 'store':
                    g['count'] += 1
                if s.get('status') == 'active' and not s.get('superseded') and s.get('monthly') and s.get('currency'):
                    g['month'][s['currency']] = round(g['month'].get(s['currency'], 0) + s['monthly'], 2)
        return {'subs': subs, 'totals': totals, 'changes': changes, 'stores': stores, 'last_scan': d.get('last_scan')}

    def digest_lines(self, today=None):
        """The changes not yet in a digest (new, price, trial) – at most three, marked as announced."""
        today = (today or datetime.date.today()).isoformat()
        with LOCK:
            d = self.load()
            live = {sid for sid, s in d['subs'].items() if s.get('status') == 'active'}
            rank = {'trial': 0, 'price_up': 1, 'price_down': 1, 'new': 2}
            todo = sorted((c for c in d['changes'] if c.get('announced') is None and c['sub'] in live and c['kind'] in rank),
                          key=lambda c: rank[c['kind']])[:3]
            for c in todo:
                c['announced'] = today
            if todo:
                self._save(d)
            out, per = [], {}
            for c in todo:
                if c.get('store'):
                    per[c['store']] = per.get(c['store'], 0) + 1
                else:
                    out.append(c['text'])
            for name, n in per.items():
                out.append('%s: %d subscription change%s' % (name, n, '' if n == 1 else 's'))
            return out

    def add_to_digest(self, name):
        """One FYI item in a morning digest for the new changes (deterministic – the run is not involved).
        The digest file is changed through digestfile.update (locked, re-read, atomic)."""
        import digestfile
        if not self.digests or not re.match(r'^\d{4}-\d{2}-\d{2}-0[5-9]\d\d\.json$', name):
            return 0

        def change(dg):
            if not isinstance(dg, dict) or not isinstance(dg.get('items'), list) or dg.get('subscriptions_added') is not None:
                return False, 0
            lines = self.digest_lines(_day(name[:10]))       # marks them announced – only now that they go in
            dg['subscriptions_added'] = len(lines)
            if lines:
                dg['items'].append({'id': '%s-p3-subscriptions' % name[:-5].replace('-', '')[:12], 'section': 'p3', 'channel': 'subscriptions',
                                    'topic': 'Subscriptions', 'headline': lines[0] if len(lines) == 1 else 'Subscriptions: %d changes' % len(lines),
                                    'detail': ' · '.join(lines) if len(lines) > 1 else 'See Receipts → Subscriptions.',
                                    'link': 'subscriptions', 'first_seen': dg.get('generated') or ''})
                add_spoken(self.digests, name, dg, ' '.join(l.rstrip('.') + '.' for l in lines))
            return True, len(lines)
        return digestfile.update(os.path.join(self.digests, name), change) or 0

    def action(self, action, p):
        with LOCK:
            d = self.load()
            if action == 'recurring_seen':
                ids = set(p.get('ids') or [])
                for c in d['changes']:
                    if not ids or c['id'] in ids:
                        c['seen'] = True
                self._save(d)
                return 'saved'
            gid = str(p.get('id') or '')
            if action == 'recurring_set' and re.match(r'^store:[a-z_]+$', gid):
                import app_stores as S
                if gid[6:] not in S.STORES:
                    raise Bad('unknown store')
                tags = d['store_tags'].setdefault(gid[6:], {})
                if 'ctx' in p:
                    if p['ctx'] not in ('work', 'private', None):
                        raise Bad('work, private or none')
                    tags['ctx'] = p['ctx']
                if 'project' in p:
                    tags['project'] = (str(p['project'])[:60] or None) if p['project'] else None
                if 'company' in p:
                    tags['company'] = re.sub(r'\s+', ' ', str(p['company'] or '')).strip()[:40] or None
                self._save(d)
                return {'message': 'Saved – new items get these', 'tags': tags}
            sub = d['subs'].get(gid)
            if not sub:
                raise Bad('unknown subscription')
            if action != 'recurring_set':
                raise Bad('unknown action')
            if 'status' in p:
                if p['status'] not in STATUSES:
                    raise Bad('status is active, cancelled or not')
                sub['status'] = p['status']
            if 'ctx' in p:
                if p['ctx'] not in ('work', 'private', None):
                    raise Bad('work, private or none')
                sub['ctx'] = p['ctx']
            if 'project' in p:
                sub['project'] = (str(p['project'])[:60] or None) if p['project'] else None
                sub['project_manual'] = True
            if 'company' in p:
                c = re.sub(r'\s+', ' ', str(p['company'] or '')).strip()[:40]
                sub['company'] = c or None
            self._save(d)
            return {'message': 'Saved', 'sub': sub}


def add_spoken(digests_dir, name, dg, line):
    """Add one sentence to a digest's spoken text – in its JSON, and in spoken-digest.md when that file was written by
    the same run (Listen and Siri read the .md)."""
    if isinstance(dg.get('spoken'), str) and line not in dg['spoken']:
        dg['spoken'] = dg['spoken'].rstrip() + ' ' + line
    md = os.path.join(digests_dir, 'spoken-digest.md')
    try:
        same = abs(os.path.getmtime(md) - os.path.getmtime(os.path.join(digests_dir, name))) < 20 * 60
        if same:
            with open(md, encoding='utf-8') as f:
                text = f.read()
            if line not in text:
                tmp = md + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    f.write(text.rstrip() + '\n\n' + line + '\n')
                os.replace(tmp, md)
    except OSError:
        pass
