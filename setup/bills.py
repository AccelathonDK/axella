"""Bills as a To do type (feature pack §3, part 2 #5). Local rules only – nothing here goes to Claude.

A bill is a To do (state/tasks.json) with "type": "bill" and a "bill" object – there is no second list:
  {"payee", "amount", "currency", "document": <message id in the Receipts register>, "account", "message_id",
   "subject", "attachments", warnings}
Its payment details ({"fi", "iban", "account", "mobilepay", "invoice_no"}) are NOT on the To do – Claude runs read
tasks.json. They live in state/bills.json "refs" {<task id>: {…}} (on the scheduler's SECRETS list, chmod 600), and
the dashboard gets them from GET bills.

Detection: documents in the Receipts register (documents.py) of kind "bill" or "reminder", or "invoice" with a due
date, not paid, not too old, become SUGGESTED bill cards – you confirm one into To do (Add), edit it, or say Not a
bill (it never comes back). The payment reference is read by rules from the mail itself (its text and its PDF, on the
Mac mini) – only for mail that isn't from a private contact and wasn't flagged by the scam check.
Ticking the To do = paid: the Receipts entry is marked paid too. A later receipt from the same payee for the same
amount suggests "Looks paid – tick it off?". The morning digest gets one line for bills due within a week (and
overdue ones). Axella never pays and never opens bank or payment links.

Safety (security review, 6 Nov): a bill card needs the mail itself on the Mac mini, and the mail must pass the scam
check (safety.check_mail) and the sender checks (safety.sender_checks) – any flag or failed check and there is no card,
whether or not the mail was ever in a digest. A FIRST bill from a sender (no earlier Receipts document from them, not in
Contacts) says "First bill from this sender – check the details with them before you pay", and its payment details
stay hidden until you tap "Show payment details". Each payee's last payment details are kept; when a new bill's IBAN,
account or FI creditor number differs, the card and the To do say so and nothing is prefilled. Those details are
seeded from the payee's earlier bill mails (read once, same checks), so the comparison works from the first card.
"First bill" means no earlier document from the same sender DOMAIN (a payee name is not enough); a bill whose payee's
earlier documents all came from other domains also says "From another address than <payee>'s earlier bills" – all
three warnings hide the payment details and nothing is prefilled.

state/bills.json: {"docs": {<message id>: {"status": "suggested"|"added"|"dismissed"|"paid"|"blocked", "task_id", "reference",
                   "read", "looks_paid", "looks_paid_ignored"}},
                   "payees": {<vendor key>: {"iban", "account", "fi_creditor", "at"}},
                   "refs": {<task id>: {"fi", "iban", "account", "mobilepay", "invoice_no"}}, "last_line": "YYYY-MM-DD"|null}
Python 3.9.
"""
import datetime
import json
import os
import re
import threading

LOCK = threading.Lock()
KINDS = ('bill', 'reminder', 'invoice')
MAX_AGE_DAYS = 120                  # a document older than this is history, not a bill to pay
OVERDUE_DAYS = 60                   # due more than this long ago: never suggested
READS_PER_REFRESH = 20
REF_KEYS = ('fi', 'iban', 'account', 'mobilepay', 'invoice_no')
DAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')

# Danish payment slips: +71<000000012345678 +12345678<  (card type 01/04/15/71/73/75, payment id, creditor number)
FI_RE = re.compile(r'\+?\s*(01|04|15|71|73|75)\s*<\s*(\d{0,19})\s*\+\s*(\d{8})\s*<')
IBAN_RE = re.compile(r'\b([A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?)\b')
ACCOUNT_RE = re.compile(r'reg\.?\s*(?:nr\.?|no\.?)?\s*[:.]?\s*(\d{4})\b[^\n\d]{1,30}?(?:konto|kontonr\.?|account)\s*(?:nr\.?|no\.?)?\s*[:.]?\s*(\d{6,10})\b', re.I)
MOBILEPAY_RE = re.compile(r'mobile\s?pay\s*(?:myshop|box)?\s*(?:nr\.?|nummer|number|no\.?)?\s*[:.]?\s*(\d{4,8})\b', re.I)
INVOICE_RE = re.compile(r'(?:faktura\s*(?:nr|nummer)|invoice\s*(?:no|number|#))\.?\s*[:.#]?\s*([A-Z0-9][A-Z0-9-]{2,24})\b', re.I)


class Bad(Exception):
    pass


def iban_ok(s):
    s = re.sub(r'\s', '', str(s or '')).upper()
    if not re.fullmatch(r'[A-Z]{2}\d{2}[A-Z0-9]{10,30}', s):
        return False
    n = ''.join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(n) % 97 == 1


def references(text):
    """Payment details found by rules in a bill's text: {'fi', 'iban', 'account', 'mobilepay', 'invoice_no'} (only the
    ones present). Never a link."""
    t = str(text or '')[:200000]
    out = {}
    m = FI_RE.search(t)
    if m:
        out['fi'] = '+%s<%s +%s<' % (m.group(1), m.group(2), m.group(3))
    for m in IBAN_RE.finditer(t):
        if iban_ok(m.group(1)):
            s = re.sub(r'\s', '', m.group(1))
            out['iban'] = ' '.join(s[i:i + 4] for i in range(0, len(s), 4))
            break
    m = ACCOUNT_RE.search(t)
    if m:
        out['account'] = '%s %s' % (m.group(1), m.group(2))
    m = MOBILEPAY_RE.search(t)
    if m:
        out['mobilepay'] = m.group(1)
    m = INVOICE_RE.search(t)
    if m and re.search(r'\d', m.group(1)):
        out['invoice_no'] = m.group(1)
    return out


def clean_reference(r):
    if not isinstance(r, dict):
        return {}
    return {k: re.sub(r'[^\w +<-]', '', str(r[k]))[:60].strip() for k in REF_KEYS if r.get(k)}


def fmt_amount(amount, currency):
    """1.245,00 DKK – exact, in the currency of the bill (never converted)."""
    if amount is None:
        return ''
    s = '{:,.2f}'.format(float(amount)).replace(',', 'X').replace('.', ',').replace('X', '.')
    return ('%s %s' % (s, currency or '')).strip()


def _day(s):
    try:
        return datetime.date.fromisoformat(str(s or '')[:10])
    except ValueError:
        return None


def _num(v):
    if v is None or v == '':
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    s = str(v).strip().replace(' ', '')
    if re.fullmatch(r'-?\d{1,3}(\.\d{3})*(,\d{1,2})?', s) or re.fullmatch(r'-?\d+(,\d{1,2})?', s):
        s = s.replace('.', '').replace(',', '.')
    elif re.fullmatch(r'-?\d{1,3}(,\d{3})*(\.\d{1,2})?', s):
        s = s.replace(',', '')
    try:
        return round(float(s), 2)
    except ValueError:
        raise Bad('the amount is not a number – type e.g. 650,00 or 1.234,56')


FIRST_NOTE = 'First bill from this sender – check the details with them before you pay'


def mail_risk(raw, known=frozenset(), safe=frozenset()):
    """None when a bill mail may become a card; else why not: 'missing' (not on the Mac mini – can't be checked),
    'scam' (the scam check flagged it) or 'auth' (a failed sender check)."""
    import email
    import email.policy
    import safety
    if not raw:
        return 'missing'
    try:
        if safety.check_mail(raw, known, safe)[0]:
            return 'scam'
        if safety.sender_checks(email.message_from_bytes(raw, policy=email.policy.default))['failed']:
            return 'auth'
    except Exception:
        return 'scam'                # a mail that can't even be checked is never a bill card
    return None


def sender_of(doc):
    m = re.search(r'[\w.+%\'-]+@[\w-]+(?:\.[\w-]+)+', str(doc.get('from') or ''))
    return m.group(0).lower() if m else ''


def sender_domain(doc):
    """The sender's organisation domain (mail.acme.example → acme.example)."""
    import safety
    addr = sender_of(doc)
    return safety._base(addr.rsplit('@', 1)[-1]) if '@' in addr else ''


def _earlier(mid, doc, docs):
    d = str(doc.get('date') or '')
    return [o for oid, o in docs.items() if oid != mid and str(o.get('date') or '9999') < d]


def first_time(mid, doc, docs, known=frozenset()):
    """A first bill from this sender: no earlier Receipts document from the same sender DOMAIN, and the address isn't
    in Contacts. The same payee name is not enough – anyone can write "Acme Power" in a From line."""
    addr, dom = sender_of(doc), sender_domain(doc)
    if addr and addr in known:
        return False
    return not (dom and any(sender_domain(o) == dom for o in _earlier(mid, doc, docs)))


def sender_differs(mid, doc, docs):
    """Earlier bills or receipts of this payee came from other domains, and none from this one."""
    vk, dom = doc.get('vendor_key'), sender_domain(doc)
    doms = {sender_domain(o) for o in _earlier(mid, doc, docs) if vk and o.get('vendor_key') == vk} - {''}
    return bool(doms) and dom not in doms


def _creditor(fi):
    m = re.search(r'\+(\d{8})<\s*$', str(fi or ''))
    return m.group(1) if m else ''


def _norm_details(ref):
    ref = ref or {}
    return {'iban': re.sub(r'\s', '', str(ref.get('iban') or '')).upper(), 'account': re.sub(r'\D', '', str(ref.get('account') or '')),
            'fi_creditor': _creditor(ref.get('fi'))}


def details_differ(ref, last):
    """The new bill's IBAN, account or FI creditor number differs from the payee's last ones (only where both have one)."""
    if not last:
        return False
    new = _norm_details(ref)
    return any(new[k] and last.get(k) and new[k] != last[k] for k in ('iban', 'account', 'fi_creditor'))


def is_candidate(doc, today):
    if doc.get('hidden') or doc.get('paid') or doc.get('kind') not in KINDS:
        return False
    if doc.get('kind') == 'invoice' and not doc.get('due'):
        return False                 # an invoice without a due date is usually paid already (a card invoice)
    d, due = _day(doc.get('date')), _day(doc.get('due'))
    if d and (today - d).days > MAX_AGE_DAYS:
        return False
    if due and (today - due).days > OVERDUE_DAYS:
        return False
    return bool(d or due)


def text_of_mail(raw, pdf_text=None, max_pdfs=3):
    """The plain text of a mail (all text parts) plus the text of its PDFs (pdf_text(bytes) → str, on the Mac mini)."""
    import email
    import email.policy
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception:
        return ''
    parts, pdfs = [], 0
    for p in msg.walk():
        ct = p.get_content_type()
        try:
            if ct in ('text/plain', 'text/html') and not p.get_filename():
                t = p.get_content()
                if ct == 'text/html':
                    t = re.sub(r'<[^>]+>', ' ', re.sub(r'(?is)<(script|style).*?</\1>', ' ', t))
                parts.append(t)
            elif pdf_text and pdfs < max_pdfs and (ct == 'application/pdf' or str(p.get_filename() or '').lower().endswith('.pdf')):
                pdfs += 1
                parts.append(pdf_text(p.get_payload(decode=True) or b''))
        except Exception:
            continue
    return '\n'.join(x for x in parts if x)


class Bills:
    def __init__(self, state_dir):
        self.file = os.path.join(state_dir, 'bills.json')

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        if not isinstance(d, dict) or not isinstance(d.get('docs'), dict):
            d = {'docs': {}}
        d.setdefault('last_line', None)
        return d

    def _save(self, d):
        tmp = self.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)

    def refs(self, task_ids=None):
        r = self.load().get('refs') or {}
        return {k: v for k, v in r.items() if task_ids is None or k in task_ids}

    def set_ref(self, task_id, ref):
        """A bill To do's payment details – kept here, never on the To do. Empty removes them."""
        ref = clean_reference(ref)
        with LOCK:
            d = self.load()
            d.setdefault('refs', {})
            if ref:
                d['refs'][str(task_id)] = ref
            else:
                d['refs'].pop(str(task_id), None)
            self._save(d)
        return ref

    def take_refs(self, tasks):
        """Move payment details still on bill To dos (from before they moved here) into refs; True if any moved."""
        moved = False
        for t in tasks:
            b = t.get('bill') if t.get('type') == 'bill' else None
            if isinstance(b, dict) and 'reference' in b:
                ref = b.pop('reference')
                if ref:
                    self.set_ref(t.get('id'), ref)
                moved = True
        return moved

    def refresh(self, docs, today=None, read_text=None, skip=lambda mid, doc: False):
        """New candidates become suggestions; references are read (at most READS_PER_REFRESH a time) for suggested and
        added bills. read_text(mid) → the mail's text or ''. skip(mid, doc) → a reason or None: a private contact, a mail
        the scam check or the sender checks flag ('scam' / 'auth': blocked for good), or a mail not on the Mac mini."""
        today = today or datetime.date.today()
        reads = 0
        with LOCK:
            d = self.load()
            for mid, doc in docs.items():
                e = d['docs'].get(mid)
                if e is None:
                    if not is_candidate(doc, today):
                        continue
                    why = skip(mid, doc)
                    if why in ('scam', 'auth'):
                        d['docs'][mid] = {'status': 'blocked', 'why': why}      # never a card, never read again
                    if why:
                        continue
                    e = d['docs'][mid] = {'status': 'suggested', 'added': today.isoformat()}
                if e['status'] in ('suggested', 'added') and not e.get('read') and read_text and reads < READS_PER_REFRESH:
                    reads += 1
                    e['read'] = today.isoformat()
                    if not skip(mid, doc):
                        try:
                            e['reference'] = clean_reference(references(read_text(mid)))
                        except Exception:
                            e['reference'] = {}
            reads += self._seed(d, docs, read_text, skip, READS_PER_REFRESH - reads)
            self._save(d)
            return d

    @staticmethod
    def _seed(d, docs, read_text, skip, budget):
        """A payee's payment details from their EARLIER bill mails, so "details differ" works from the first bill
        Axella suggests: for each payee with a suggested bill and nothing kept yet, the newest earlier bill, invoice or
        reminder that passes the same checks (skip) is read once. Returns the number of mails read."""
        if not read_text or budget <= 0:
            return 0
        payees, tried, n = d.setdefault('payees', {}), d.setdefault('seed_tried', {}), 0
        for mid, e in list(d['docs'].items()):
            doc = docs.get(mid) or {}
            vk = doc.get('vendor_key')
            if e.get('status') != 'suggested' or not vk or vk in payees or tried.get(vk) or n >= budget:
                continue
            tried[vk] = True
            # history only: never another bill that is itself waiting (or was blocked) – that is what's being checked
            older = sorted((o for o in _earlier(mid, doc, docs) if o.get('vendor_key') == vk and o.get('kind') in KINDS
                            and o.get('message_id') not in d['docs']),
                           key=lambda o: str(o.get('date') or ''), reverse=True)
            for o in older[:3]:
                oid = o.get('message_id')
                if not oid or n >= budget or skip(oid, o):
                    continue
                n += 1
                try:
                    det = _norm_details(references(read_text(oid)))
                except Exception:
                    continue
                if any(det.values()):
                    payees[vk] = dict(det, at=str(o.get('date') or '')[:10], seeded=True)
                    break
        return n

    def card(self, mid, doc, e, docs=None, known=frozenset(), payees=None):
        first = first_time(mid, doc, docs or {}, known)
        differ = details_differ(e.get('reference'), (payees or {}).get(doc.get('vendor_key') or ''))
        other = sender_differs(mid, doc, docs or {})
        return {'first_time': first, 'details_differ': differ, 'sender_differs': other, 'reference_hidden': first or differ or other,
                'vendor_key': doc.get('vendor_key'), 'id': mid, 'payee': doc.get('vendor') or '', 'amount': doc.get('amount'), 'currency': doc.get('currency'),
                'due': doc.get('due'), 'kind': doc.get('kind'), 'date': doc.get('date'), 'reference': e.get('reference') or {},
                'account': doc.get('account'), 'message_id': doc.get('message_id') or mid, 'deep_link': doc.get('deep_link'),
                'subject': doc.get('subject'), 'attachments': list(doc.get('attachments') or [])[:6], 'ctx': doc.get('ctx')}

    def suggestions(self, docs, today=None, known=frozenset()):
        """The suggested cards. known: e-mail addresses in Contacts (a known sender is never a "first bill")."""
        today = today or datetime.date.today()
        d = self.load()
        out = []
        for mid, e in d['docs'].items():
            doc = docs.get(mid)
            if e.get('status') == 'suggested' and doc and is_candidate(doc, today):
                out.append(self.card(mid, doc, e, docs, known, d.get('payees')))
        out.sort(key=lambda c: (c.get('due') or '9999', c.get('date') or ''))
        return out

    def task_for(self, card, edits=None):
        """The To do for a confirmed bill card (with your edits): text, due, type and the bill object."""
        e = edits or {}
        payee = str(e.get('payee', card.get('payee')) or '').strip()[:80] or 'Bill'
        amount = _num(e['amount']) if 'amount' in e else card.get('amount')
        currency = str(e.get('currency', card.get('currency')) or '').strip().upper() or None
        if currency and not re.fullmatch(r'[A-Z]{3}', currency):
            raise Bad('the currency is three letters, e.g. DKK')
        due = e.get('due', card.get('due')) or None
        if due and not _day(due):
            raise Bad('bad due date')
        # a first bill or changed details: nothing prefilled – only what you chose to show and keep
        ref = clean_reference(e['reference']) if 'reference' in e else {} if card.get('reference_hidden') else card.get('reference') or {}
        text = ('Pay %s %s' % (payee, fmt_amount(amount, currency))).strip() if amount is not None else 'Pay ' + payee
        bill = {'payee': payee, 'amount': amount, 'currency': currency, 'reference': ref, 'document': card['id'],
                'account': card.get('account'), 'message_id': card.get('message_id'), 'subject': str(card.get('subject') or '')[:200],
                'attachments': card.get('attachments') or [], 'vendor_key': card.get('vendor_key')}
        if card.get('first_time'):
            bill['first_time'] = True
        if card.get('sender_differs'):
            bill['sender_differs'] = True
        if card.get('details_differ') or details_differ(ref, self.load().get('payees', {}).get(card.get('vendor_key') or '')):
            bill['details_differ'] = True
        return {'text': text[:500], 'due': str(due)[:10] if due else None, 'type': 'bill', 'bill': bill,
                'ref': {'kind': 'bill', 'document': card['id'], 'deep_link': card.get('deep_link')},
                'ctx': card.get('ctx') if card.get('ctx') in ('work', 'private') else None}

    def remember(self, vendor_key, ref, today=None):
        """The payee's last payment details (IBAN, account, FI creditor) – what the next bill is compared with."""
        n = _norm_details(ref)
        if not vendor_key or not any(n.values()):
            return
        with LOCK:
            d = self.load()
            old = d.setdefault('payees', {}).get(vendor_key) or {}
            d['payees'][vendor_key] = {k: n[k] or old.get(k, '') for k in n} | {'at': (today or datetime.date.today()).isoformat()}
            self._save(d)

    def set(self, mid, **kw):
        with LOCK:
            d = self.load()
            e = d['docs'].get(mid)
            if e is None:
                raise Bad('this bill is not waiting any more')
            e.update(kw)
            self._save(d)
            return e

    def find_looks_paid(self, docs, tasks):
        """A receipt from the same payee, for the same amount and currency, after the bill: "Looks paid"."""
        open_tasks = {t.get('id'): t for t in tasks if t.get('type') == 'bill' and t.get('status') != 'done'}
        with LOCK:
            d = self.load()
            changed = False
            for mid, e in d['docs'].items():
                t = open_tasks.get(e.get('task_id'))
                if e.get('status') != 'added' or not t or e.get('looks_paid') or e.get('looks_paid_ignored'):
                    continue
                bill = docs.get(mid) or {}
                b = t.get('bill') or {}
                amt, cur = b.get('amount'), b.get('currency')
                if amt is None:
                    continue
                for oid, o in docs.items():
                    if oid == mid or o.get('kind') != 'receipt' or o.get('vendor_key') != bill.get('vendor_key'):
                        continue
                    if (o.get('currency') or cur) != cur or o.get('amount') is None or abs(float(o['amount']) - float(amt)) > max(0.01, abs(float(amt)) * 0.005):
                        continue
                    if str(o.get('date') or '') >= str(bill.get('date') or ''):
                        e['looks_paid'] = oid
                        changed = True
                        break
            if changed:
                self._save(d)
            return [{'id': mid, 'task_id': e['task_id'], 'receipt': e['looks_paid']} for mid, e in d['docs'].items()
                    if e.get('status') == 'added' and e.get('looks_paid') and e.get('task_id') in open_tasks]


def due_soon(tasks, today, worlds=None, days=7):
    """Open bills due within `days` (and overdue ones), for the digest line and the week wrap."""
    out = []
    for t in tasks:
        if t.get('type') != 'bill' or t.get('status') == 'done':
            continue
        if worlds and t.get('ctx') in ('work', 'private') and t['ctx'] not in worlds:
            continue
        due = _day(t.get('due'))
        if due and due <= today + datetime.timedelta(days=days):
            b = t.get('bill') or {}
            out.append({'task_id': t.get('id'), 'payee': b.get('payee') or t.get('text'), 'amount': b.get('amount'),
                        'currency': b.get('currency'), 'due': due.isoformat(), 'overdue': due < today})
    out.sort(key=lambda x: x['due'])
    return out


def digest_line(bills, today):
    """"2 bills due this week: Acme Power 1.245,00 DKK (Thu), Lee Plumbing 3.410,00 DKK (Mon)." – overdue first."""
    def one(b):
        due = _day(b['due'])
        when = 'today' if due == today else DAYS[due.weekday()] if due > today else 'since ' + DAYS[due.weekday()] if (today - due).days < 7 else 'since ' + due.strftime('%d %b').lstrip('0')
        amt = fmt_amount(b.get('amount'), b.get('currency'))
        return '%s%s (%s)' % (b['payee'], ' ' + amt if amt else '', when)
    over = [b for b in bills if b['overdue']]
    soon = [b for b in bills if not b['overdue']]
    parts = []
    if over:
        parts.append('%d bill%s overdue: %s' % (len(over), '' if len(over) == 1 else 's', ', '.join(one(b) for b in over[:4])))
    if soon:
        parts.append('%d bill%s due this week: %s' % (len(soon), '' if len(soon) == 1 else 's', ', '.join(one(b) for b in soon[:4])))
    return ('. '.join(parts) + '.') if parts else ''


def add_to_digest(bills_obj, digests_dir, name, tasks_fn, today=None):
    """One line in a morning digest (05:00–09:59) for bills due within a week and overdue ones, at most one a day,
    only the digest's world(s). Deterministic, through digestfile.update."""
    import digestfile
    from recurring import add_spoken
    if not re.match(r'^\d{4}-\d{2}-\d{2}-0[5-9]\d\d\.json$', name):
        return None
    today = today or _day(name[:10]) or datetime.date.today()
    if bills_obj.load().get('last_line') == today.isoformat():
        return None
    done = {}

    def change(dg):
        if not isinstance(dg, dict) or not isinstance(dg.get('items'), list) or dg.get('bills_line') is not None:
            return False, None
        sc = dg.get('scope') if isinstance(dg.get('scope'), list) and dg.get('scope') else None
        due = due_soon(tasks_fn(), today, sc)
        text = digest_line(due, today)
        dg['bills_line'] = len(due)
        if text:
            dg['items'].append({'id': '%s-p3-bills' % name[:-5].replace('-', '')[:12], 'section': 'p3', 'channel': 'bills',
                                'topic': 'Bills', 'headline': text, 'detail': 'In To do → Bills. Axella never pays – tick a bill when it is paid.',
                                'link': 'bills', 'first_seen': dg.get('generated') or ''})
            add_spoken(digests_dir, name, dg, text)
        done['n'] = len(due)
        return True, len(due)
    res = digestfile.update(os.path.join(digests_dir, name), change)
    if 'n' in done:
        with LOCK:
            d = bills_obj.load()
            d['last_line'] = today.isoformat()
            bills_obj._save(d)
    return res
