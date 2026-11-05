"""App stores and payment platforms in Subscriptions: one charge from a store is several things (an app, a cloud plan,
a music plan …). This reads the line items from the store's own receipt and renewal mails, by rules, on the Mac mini –
no Claude, nothing leaves the home – so recurring.py can show one subscription per item under the store.

A store is a small rule set (STORES): its own mail domain, which subjects are receipts, the section headings and
boilerplate lines of its layout, and the store's own subscriptions page. That page is a fixed link kept here, never a
link taken from a mail. Item lines are read only from mail that passed DKIM or DMARC for the store's own domain
(recurring.auth_ok – the same rule as the scam check); axella-actions.py also skips scam-flagged and private mail.

Item names are written by app makers, not by the store: they are shown as written, never spoken (Listen and Siri get
"<store>: N subscription changes"), and never go into a prompt.
"""
import datetime
import email
import email.policy
import email.utils
import html
import re

import recurring as R

STORES = {
    'apple': {
        'name': 'Apple', 'domain': 'apple.com', 'manage': 'https://apps.apple.com/account/subscriptions',
        'subject': re.compile(r'receipt|kvittering|subscription|abonnement', re.I),
        'headings': re.compile(r'^(app store|mac app store|itunes store|apple services|apple books|book store|'
                               r'tjenester fra apple|apple-tjenester)$', re.I),
    },
    'google_play': {
        'name': 'Google Play', 'domain': 'google.com', 'manage': 'https://play.google.com/store/account/subscriptions',
        'subject': re.compile(r'google play', re.I),
        'headings': re.compile(r'^(google play|order summary|ordreoversigt)$', re.I),
    },
    'paypal': {
        'name': 'PayPal', 'domain': 'paypal.com', 'manage': 'https://www.paypal.com/myaccount/autopay/',
        'subject': re.compile(r'recurring payment|automatic payment|subscription|tilbagevendende betaling|automatisk betaling|'
                              r'abonnement', re.I),
        'headings': re.compile(r'^(merchant|forhandler|modtager|recipient|payment details|betalingsoplysninger)$', re.I),
    },
}

# lines that are layout, not an item (any store, English and Danish)
BOILER = re.compile(
    r'^(apple id|apple-id|apple-konto|apple account|billed to|faktureret til|date|dato|order id|ordre-?id|order number|ordrenummer|order|ordre|'
    r'document( no\.?)?|dokument(nr\.?| nr\.?)?|invoice|faktura|receipt|kvittering|your receipt|din kvittering|'
    r'report a problem|rapportér et problem|rapporter et problem|write a review|skriv en anmeldelse|'
    r'cancel subscription|annuller abonnement|manage subscriptions?|administrer abonnementer?|'
    r'privacy policy|anonymitetspolitik|terms of sale|salgsbetingelser|learn more|få mere at vide|'
    r'payment method|betalingsmetode|paid with|betalt med|transaction id|transaktions-?id|'
    r'quantity|antal|qty|price|pris|item|vare|description|beskrivelse|amount|beløb|view order|se ordre)\b.{0,40}$', re.I)
TOTAL = re.compile(r'^(sub-?total|subtotal|total|i alt|beløb i alt|samlet beløb|moms|heraf moms|vat|tax|skat|'
                   r'total paid|betalt i alt|order total|ordretotal)\b', re.I)
# "incl. VAT kr 11,80" under an item's price: part of that price, not an item
TAXLINE = re.compile(r'^(inkl\.?|inklusive|incl\.?|including|heraf|herof|of which)\b.{0,30}\b(moms|vat|tax|skat)\b', re.I)
# "Mastercard •••• 0000  kr 59,00" (or the amount in the next cell): the amount charged, i.e. the receipt's total
PAIDLINE = re.compile(r'^(visa|mastercard|maestro|american express|amex|dankort|apple pay|mobilepay|paypal|apple-saldo|'
                      r'apple balance|apple account balance|kontosaldo|account balance|betalt med|paid with|charged to)\b', re.I)
RENEWS = re.compile(r'\b(renews?|renewal|fornyes|fornyelse|next (billing|payment|charge)|næste (betaling|opkrævning)|'
                    r'billed (monthly|yearly|annually)|faktureres)\b', re.I)
TRIAL = re.compile(r'\b(free trial|trial ends|trial period|prøveperiode)\b', re.I)
SUBWORD = re.compile(r'\b(subscription|abonnement|membership|medlemskab|plan)\b', re.I)
ID_LIKE = re.compile(r'^[A-Z0-9][A-Z0-9-]{5,}$|^\d[\d\s-]{4,}$|^[•*·.]{2,}\s*\d{2,4}$|@')
DATE_ONLY = re.compile(r'^\W*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\.?\s+[a-zæøå]+\.?\s+\d{4}|'
                       r'[a-z]+\.?\s+\d{1,2},?\s+\d{4})\W*$', re.I)
BLOCK_TAGS = re.compile(r'<\s*(br|/p|/div|/tr|/td|/th|/li|/h\d|/table|p|div|tr|li|h\d)\b[^>]{0,2000}>', re.I)


def store_of(addr):
    """The store a sender address belongs to (by its own base domain), or None."""
    dom = str(addr or '').rsplit('@', 1)[-1].strip('<> ').lower() if '@' in str(addr or '') else ''
    base = R._base(dom) if dom else ''
    return next((k for k, s in STORES.items() if s['domain'] == base), None)


def is_candidate(subject, addr):
    s = store_of(addr)
    return bool(s and STORES[s]['subject'].search(str(subject or '')[:500]))


def clean(s, n=80):
    """Shown as written, but one line, no control characters, capped."""
    s = re.sub(r'[\x00-\x1f\x7f​-‏‪-‮⁦-⁩]', ' ', str(s or ''))
    return re.sub(r'\s+', ' ', s).strip()[:n]


def lines_of(msg):
    """The mail's text, one layout line per list entry (the HTML part is preferred – receipts are tables)."""
    text, htm = '', ''
    for p in msg.walk():
        if p.is_multipart():
            continue
        if p.get_content_type() in ('text/plain', 'text/html'):
            try:
                body = str(p.get_content())[:200000]
            except Exception:
                body = (p.get_payload(decode=True) or b'').decode('utf-8', 'ignore')[:200000]
            if p.get_content_type() == 'text/plain':
                text += body
            else:
                htm += body
    if htm:
        htm = re.sub(r'(?is)<(style|script|head)\b.*?</\1\s*>', ' ', htm)
        t = BLOCK_TAGS.sub('\n', htm)
        t = html.unescape(re.sub(r'<[^>]{0,2000}>', ' ', t))
    else:
        t = text
    out = []
    for ln in t.split('\n'):
        ln = clean(ln, 200)
        if ln:
            out.append(ln)
    return out[:3000]


def _price(line):
    """(amount, currency, the line without the price) when the line holds a price; 'kr 0,00' counts (free)."""
    found = [(m, R._num(m.group('a1') or m.group('a2')), (m.group('c1') or m.group('c2') or '').lower())
             for m in R.AMOUNT.finditer(line)]
    found = [f for f in found if f[2] in R.CUR and f[1] is not None]
    if not found:
        if re.search(r'^(free|gratis)$', line, re.I):
            return 0.0, None, ''
        return None
    m, a, c = found[-1]
    rest = clean(line[:m.start()] + ' ' + line[m.end():])
    return a, R.CUR[c], rest


def _interval_from(renews, sent):
    if not renews or not sent:
        return None
    days = (renews - sent).days
    for name, _, lo, hi in R.INTERVALS:
        if lo <= days <= hi:
            return name
    return None


def _item(block, price, sent, rules):
    """A block of layout lines that ended in a price line → an item, or None when it is layout."""
    amount, cur, rest = price
    texts, renews, trial_ends, blob = [], None, None, ' '.join(block + [rest])
    for ln in block + ([rest] if rest else []):
        if ID_LIKE.search(ln):          # an order number, an address: header values – the item's own lines come after them
            texts = []
            continue
        if BOILER.match(ln) or rules['headings'].match(ln) or DATE_ONLY.match(ln):
            continue
        if TRIAL.search(ln):
            ds = [d for d in R.dates_in(ln, sent) if d >= sent]
            trial_ends = trial_ends or (ds[0] if ds else None)
            continue
        if RENEWS.search(ln):
            ds = [d for d in R.dates_in(ln, sent) if d >= sent]
            renews = renews or (ds[0] if ds else None)
            continue
        if not re.search(r'[A-Za-zÆØÅæøå]', ln):
            continue
        texts.append(ln)
    if not texts:
        return None
    name = clean(texts[0])
    plan = clean(texts[1], 60) if len(texts) > 1 else ''
    plan = re.sub(r'^\((.*)\)$', r'\1', plan)
    interval = R.interval_in(blob) or _interval_from(renews, sent)
    sub = bool(renews or interval or trial_ends or SUBWORD.search(plan))
    return {'name': name, 'plan': plan or None, 'amount': amount, 'currency': cur, 'interval': interval,
            'renews': renews.isoformat() if renews else None, 'trial_ends': trial_ends.isoformat() if trial_ends else None,
            'kind': 'subscription' if sub else 'purchase'}


def parse_receipt(raw, sent=None):
    """A store's receipt or renewal mail → {"store", "sent", "auth_ok", "items": [...], "total", "subtotal",
    "currency"} or None (not a store's mail). Items are read only when auth_ok: a look-alike gets no items."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    _, addr = email.utils.parseaddr(str(msg.get('From', ''))[:500])
    store = store_of(addr)
    if not store:
        return None
    rules = STORES[store]
    try:
        sent = sent or email.utils.parsedate_to_datetime(str(msg.get('Date'))).date()
    except (TypeError, ValueError):
        sent = sent or datetime.date.today()
    out = {'store': store, 'sent': sent.isoformat(), 'auth_ok': R.auth_ok(msg, rules['domain']), 'items': [],
           'total': None, 'subtotal': None, 'currency': None}
    if not out['auth_ok']:
        return out
    block, seen, pending, totals = [], set(), None, False

    def put(key, p):
        if key and p and p[1] and out[key] is None:
            out[key], out['currency'] = p[0], out['currency'] or p[1]

    for ln in lines_of(msg):
        if PAIDLINE.match(ln):
            # "Billed to: Visa …" in the header is layout; after the items it is the amount charged
            if out['items']:
                p = _price(ln)
                if p and p[1]:
                    put('total', p)
                else:
                    pending = 'total'
                totals = True
            block = []
            continue
        if TAXLINE.match(ln):
            block = []
            continue
        if TOTAL.match(ln):
            # the label and its amount on one line, or the amount in the next cell (a table row)
            key = 'subtotal' if re.match(r'^sub-?total', ln, re.I) else '' if re.match(r'^(moms|heraf|vat|tax|skat)', ln, re.I) else 'total'
            p = _price(ln)
            if p:
                put(key, p)
                pending = None
            else:
                pending = key
            block, totals = [], True
            continue
        p = _price(ln)
        if pending is not None:
            if p and not p[2]:
                put(pending, p)
                pending = None
                continue
            pending = None
        if p is None:
            block = (block + [ln])[-8:]
            continue
        if totals:                      # the items come before the totals: a price further down is layout (tax, paid …)
            block = []
            continue
        it = _item(block, p, sent, rules)
        block = []
        if not it:
            continue
        if it['currency'] is None:
            it['currency'] = out['currency']
        k = (it['name'].lower(), (it['plan'] or '').lower())
        if k not in seen and len(out['items']) < 40:
            seen.add(k)
            out['items'].append(it)
    cur = next((i['currency'] for i in out['items'] if i['currency']), None)
    for i in out['items']:
        i['currency'] = i['currency'] or cur or out['currency']
    out['currency'] = out['currency'] or cur
    return out


def itemised(rec):
    """True when the items account for the whole charge: their sum is the receipt's subtotal or total (when the
    receipt shows one). A receipt that is only partly read stays an un-itemised charge – nothing is counted twice."""
    if not rec or not rec.get('auth_ok') or not rec.get('items'):
        return False
    s = round(sum(i.get('amount') or 0 for i in rec['items']), 2)
    marks = [x for x in (rec.get('subtotal'), rec.get('total')) if isinstance(x, (int, float))]
    return not marks or any(abs(s - m) <= 0.05 for m in marks)
