"""Safety: the scam and phishing check, and "Always hold" (dev request "feature pack, part 2", §6 of the feature pack).

Local rules only – no AI, nothing leaves the Mac mini. A digest written by a run is checked here once
(axella-actions.py push_watcher, before anything is pushed):
  - mail items: the message's own headers and HTML from Mail's store (mailsearch.path_for_mid) – sender checks
    (Authentication-Results), display name vs domain, look-alike domains, Reply-To, links whose text shows another
    address than they go to, shortened links, links to bare IP addresses, urgent "verify / pay" wording;
  - SMS / iMessage items: a number not in your address book, with a link, urgent wording or a brand name.
Two levels: "scam" (Possible scam – high confidence) and "check" (Check before you click – medium).
A flagged item gets item["safety"] = {"level", "label", "signals": [{"code", "text"}], "v"}; its draft is removed and
it is never left in an urgent section (p0/p1/p2 → p3, the old section kept in safety["was"]). Links are never opened.
Items from senders set to "Always hold" (Newsletters) are taken out of the digest (counted in d["held"]).

state/safety.json: {"flagged": {<key>: {...}}, "safe": [<address or number>], "checked": {<digest name>: v}}
  key = "mid:<Message-ID>" or "item:<digest>/<item id>"
Python 3.9.
"""
import datetime
import email
import email.policy
import email.utils
import html.parser
import ipaddress
import json
import os
import re
import threading
import urllib.parse

V = 1
LOCK = threading.Lock()

TEXT = {
    'auth_fail': 'The mail failed the sender checks (SPF/DKIM/DMARC) – it may not come from who it says',
    'brand': 'The sender name or subject uses a known brand, but the mail comes from another domain',
    'lookalike': 'The sender or a link uses a look-alike domain (a brand name with extra words, digits or odd letters)',
    'name_address': 'The sender name shows another e-mail address or domain than the one it was sent from',
    'reply_to': 'Replies would go to another domain than the sender',
    'link_text': 'A link shows one address but goes to another',
    'shortener': 'A shortened link hides where it goes',
    'ip_link': 'A link goes to a bare IP address',
    'urgent': 'Urgent wording about payment, a parcel, a blocked account or "verify your details"',
    'sms_unknown_link': 'A text from a number not in your contacts, with a link',
    'sms_unknown_brand': 'A text from a number not in your contacts, using a known brand name',
    'safe_auth_fail': 'From a sender you marked safe, but it failed the sender checks',
}
STRONG = {'auth_fail', 'brand', 'lookalike', 'link_text', 'ip_link'}
LABEL = {'scam': 'Possible scam', 'check': 'Check before you click'}

# Brands that scam mails pretend to be (public organisations and services – nobody's own data): name → their domains.
BRANDS = [
    (r'post ?nord', r'postnord\.(dk|se|no|fi|com)'), (r'\bmit ?id\b', r'mitid\.dk|nets\.eu|signicat\.com'),
    (r'\bskat\b|skattestyrelsen', r'skat\.dk|sktst\.dk|skattestyrelsen\.dk'), (r'\be-?boks\b', r'e-boks\.(dk|com)'),
    (r'netflix', r'netflix\.com'), (r'\bdhl\b', r'dhl\.(com|dk|de)'), (r'\bgls\b', r'gls-?(group|denmark|pakkeshop)?\.(com|dk|eu)'),
    (r'\bdao\b', r'dao\.as'), (r'paypal', r'paypal\.(com|dk)'), (r'mobile ?pay', r'mobilepay\.(dk|fi)|vippsmobilepay\.com'),
    (r'\bapple\b|\bicloud\b', r'apple\.com|icloud\.com'), (r'microsoft|\boutlook\b|office ?365', r'microsoft\.com|office\.com|outlook\.com'),
    (r'danske ?bank', r'danskebank\.(dk|com)'), (r'\bnordea\b', r'nordea\.(dk|com)'),
]
BRANDS = [(re.compile(a, re.I), re.compile(r'(^|\.)(%s)$' % b, re.I)) for a, b in BRANDS]
SHORTENERS = re.compile(r'^(bit\.ly|tinyurl\.com|t\.co|is\.gd|cutt\.ly|rb\.gy|shorturl\.at|ow\.ly|s\.id|t\.ly|tiny\.cc|'
                        r'rebrand\.ly|buff\.ly|goo\.gl|qrco\.de)$', re.I)
URGENT = re.compile(
    r'verify your (account|identity|details)|confirm your (account|identity|details|payment)|account (is |has been )?'
    r'(suspended|locked|blocked|on hold)|unusual (sign-?in|activity)|payment (failed|declined)|update (your )?(payment|'
    r'billing|card) (details|information|method)|your (parcel|package|shipment) (is )?(waiting|on hold|held)|customs (fee|'
    r'charge)|redelivery fee|within (24|48) hours|refund (is )?(waiting|pending|available)|you have (a )?(tax )?refund|'
    r'bekræft (din|dine) (konto|oplysninger|identitet|betaling)|konto (er )?(spærret|lukket|suspenderet)|'
    r'opdater (dine )?(betalings|kort)?oplysninger|pakke (venter|er tilbageholdt)|betal (told|gebyr|fragt)|'
    r'tilbagebetaling|penge til gode|inden for 24 timer|log ind for at undgå', re.I)
MAX_SCAN = 50000                     # characters of text and of HTML a check looks at (a huge mail can't slow it down)
MAX_LINK_TEXT = 300
TOKEN_RE = re.compile(r'[^\s<>"\')\]]+')        # whole tokens first – linear – then the host is checked in Python
HOST_RE = re.compile(r'[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63}){1,10}')
TLDS = {'com', 'dk', 'net', 'org', 'info', 'xyz', 'top', 'shop', 'online', 'site', 'click', 'link', 'live', 'app', 'io',
        'me', 'ly', 'gd', 'co', 'cc', 'at'}


def _host_of_token(tok):
    """'acme.example/x' or 'https://acme.example/x' → 'acme.example' when it looks like a host, else ''."""
    t = tok.lower()
    for pre in ('https://', 'http://'):
        if t.startswith(pre):
            t = t[len(pre):]
            break
    h = t.split('/', 1)[0].split('?', 1)[0].split('#', 1)[0].rstrip('.,;:!?').split('@')[-1].split(':')[0]
    return h if len(h) <= 253 and HOST_RE.fullmatch(h) else ''


def find_links(text):
    """Links in plain text: http(s):// tokens, and bare "host.tld/path" tokens with a common TLD. Linear time."""
    out = []
    for tok in TOKEN_RE.findall(str(text or '')[:MAX_SCAN]):
        low = tok.lower()
        if low.startswith(('http://', 'https://')):
            out.append(tok.rstrip('.,;:!?'))
        elif '/' in tok:
            h = _host_of_token(tok)
            if h and h.rsplit('.', 1)[-1] in TLDS:
                out.append(tok.rstrip('.,;:!?'))
    return out


def _shown_domain(text):
    """The address a link's text shows ("www.acme.example/refund"), or ''. Linear; at most 300 characters."""
    for tok in str(text or '')[:MAX_LINK_TEXT].lower().split():
        h = _host_of_token(tok)
        if h and h.rsplit('.', 1)[-1].isalpha() and len(h.rsplit('.', 1)[-1]) >= 2:
            return h
    return ''
AUTH_RE = re.compile(r'\b(spf|dkim|dmarc)\s*=\s*(\w+)', re.I)
# Your own mail providers: only their Authentication-Results can say "pass" (actions-config.json "mail_providers"
# replaces this list). Anyone can put a header in a mail; a fake one can add a failure, never remove one.
PROVIDERS = ['icloud.com', 'me.com', 'mac.com', 'apple.com', 'google.com', 'gmail.com', 'googlemail.com', 'outlook.com',
             'office365.com', 'microsoft.com', 'hotmail.com']


def _is_provider(host, providers=None):
    h = str(host or '').lower().strip().rstrip('.')
    return bool(h) and any(h == p or h.endswith('.' + p) for p in (providers or PROVIDERS))


def _provider_hop(received, providers=None, strict=False):
    """A Received line written by your provider, read from the top of the mail: its "by" host is a provider domain,
    or – only at the very top, before the provider's verdicts (strict=False) – an internal host name without a dot
    (iCloud writes its own hops that way). Once the provider's verdicts have started, a dot-less name no longer
    extends the block: a Received line the mail brought along is easy to forge."""
    m = re.search(r'\bby\s+([a-z0-9.-]{1,253})', received, re.I)
    if not m:
        return False
    host = m.group(1).lower().rstrip('.')
    return _is_provider(host, providers) or (not strict and '.' not in host)


def _first_verdict(v, method):
    """(result, domain) of the first `method=` result in one Authentication-Results header – domain = header.d for
    dkim, header.from for dmarc."""
    key = 'header.d' if method == 'dkim' else 'header.from'
    body = v.split(';', 1)[1] if ';' in v else ''
    m = re.search(r'\b%s\s*=\s*(\w+)' % method, body, re.I)
    if not m:
        return None, ''
    rest = body[m.end():]
    nxt = re.search(r'\b(spf|dkim|dmarc)\s*=', rest, re.I)          # this result's own properties only
    rest = rest[:nxt.start()] if nxt else rest
    d = re.search(r'%s\s*=\s*@?([a-z0-9.-]{1,253})' % re.escape(key), rest, re.I)
    return m.group(1).lower(), (_base(d.group(1)) if d else '')


def sender_checks(msg, providers=None):
    """The sender checks (SPF/DKIM/DMARC) of one mail: {"failed": bool, "passed": {base domain}}.
    - The provider's own verdicts: Authentication-Results whose authserv-id is one of your providers, inside the
      provider's block at the top of the mail, up to and including its SPF verdict (its last one). The block runs from the top while the Received lines are the
      provider's hops (a provider domain; or a host name without a dot, but only before its verdicts start) and ends at
      the first Received from anywhere else. Of those, only the FIRST dmarc= and the FIRST dkim= result count – the
      provider writes its verdicts before anything the mail brought along, so a forged one further down never counts.
    - passed: the From domain when the provider's first DMARC verdict is pass for it (header.from).
    - failed: ANY Authentication-Results header says dmarc=fail, or spf=fail/softfail – unless that same header, or the
      provider's own first DKIM verdict for the From domain (header.d), says dkim=pass. A header added by the sender
      can add a failure but never hide one.
      Checked against the real layout of iCloud and Gmail mail (tools/auth-header-layout.py, positions only)."""
    items = [(str(k).lower(), ' '.join(str(v).split())[:3000]) for k, v in list(msg.raw_items())[:400]]
    frm = _base(email.utils.parseaddr(str(msg.get('From', ''))[:1000])[1].rsplit('@', 1)[-1].lower())
    limit, hop, verdicts_started = len(items), False, False
    for i, (k, v) in enumerate(items):
        if k == 'authentication-results' and hop:
            verdicts_started = True
        elif k == 'received':
            if _provider_hop(v, providers, strict=verdicts_started):
                hop = True
            else:
                limit = i
                break
    verdicts, passed, dkim_ok, dmarc_seen, dkim_seen, spf_seen = [], set(), False, False, False, False
    for i, (k, v) in enumerate(items):
        if k != 'authentication-results':
            continue
        res = {}
        for x, y in AUTH_RE.findall(v):
            res.setdefault(x.lower(), set()).add(y.lower())
        verdicts.append(res)
        ident = v.split(';', 1)[0].strip().split(' ')[0] if v else ''
        # the provider's verdict group ends with its SPF verdict (iCloud writes it last; Gmail all in one header):
        # anything after that came with the mail
        if spf_seen or not (hop and i < limit and _is_provider(ident, providers)):
            continue
        spf_seen = 'spf' in res
        if 'dmarc' in res and not dmarc_seen:          # the provider's own DMARC verdict: the first one only
            dmarc_seen = True
            r, d = _first_verdict(v, 'dmarc')
            if r == 'pass' and d:
                passed.add(d)
        if 'dkim' in res and not dkim_seen:            # … and its own DKIM verdict, likewise, for the From domain only
            dkim_seen = True
            r, d = _first_verdict(v, 'dkim')
            dkim_ok = r == 'pass' and bool(d) and d == frm
    failed = any('fail' in r.get('dmarc', ()) or (r.get('spf', set()) & {'fail', 'softfail'} and 'pass' not in r.get('dkim', ())
                                                  and not dkim_ok) for r in verdicts)
    return {'failed': failed, 'passed': passed}
LEET = {'0': 'o', '1': 'l', '3': 'e', '4': 'a', '5': 's'}


def _dom(addr):
    a = str(addr or '').strip().lower().rstrip('>')
    return a.rsplit('@', 1)[1] if '@' in a else ''


def _host(url):
    u = url if '://' in url else 'http://' + url
    try:
        return (urllib.parse.urlparse(u).hostname or '').lower().rstrip('.')
    except ValueError:
        return ''


def _base(d):
    """mail.acme.example → acme.example, shop.example.co.uk → example.co.uk (close enough for "same organisation")."""
    p = [x for x in str(d or '').lower().split('.') if x]
    if len(p) >= 3 and len(p[-1]) == 2 and p[-2] in ('co', 'com', 'org', 'net', 'gov', 'ac'):
        return '.'.join(p[-3:])
    return '.'.join(p[-2:])


def _is_ip(h):
    try:
        ipaddress.ip_address(h.strip('[]'))
        return True
    except ValueError:
        return False


def _brand_claimed(text):
    return [dom for name, dom in BRANDS if name.search(text or '')]


def _lookalike(host):
    """A punycode (xn--) domain, or a brand name inside a domain that isn't the brand's own ("postnord-levering.example")."""
    if not host or _is_ip(host):
        return False
    if 'xn--' in host:
        return True
    plain = re.sub(r'[01345]', lambda m: LEET[m.group(0)], host).replace('-', ' ').replace('.', ' ')
    return any(name.search(plain) and not dom.search(host) for name, dom in BRANDS)


class _Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self._href, self._text = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self._href, self._text = dict(attrs).get('href') or '', []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self._href is not None:
            self.links.append((self._href, ' '.join(self._text).strip()))
            self._href = None


def _parts(msg):
    text, htm = [], []
    for p in msg.walk():
        if p.is_multipart():
            continue
        ct = p.get_content_type()
        if ct in ('text/plain', 'text/html'):
            try:
                body = p.get_content()
            except Exception:
                body = (p.get_payload(decode=True) or b'').decode('utf-8', 'ignore')
            (text if ct == 'text/plain' else htm).append(str(body)[:MAX_SCAN])
    return '\n'.join(text)[:MAX_SCAN], '\n'.join(htm)[:MAX_SCAN]


def _verdict(codes):
    codes = set(codes)
    strong = codes & STRONG
    if len(strong) >= 2 or (strong and codes & {'urgent', 'shortener'}):
        return 'scam'
    if strong or len(codes) >= 2:
        return 'check'
    return None


def check_mail(raw, known=frozenset(), safe=frozenset()):
    """(level | None, [codes]) for one mail (RFC 822 bytes). known / safe: lower-case e-mail addresses."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    name, addr = email.utils.parseaddr(str(msg.get('From', ''))[:1000])
    name, addr = name[:MAX_LINK_TEXT], addr.lower()
    failed = sender_checks(msg)['failed']
    if addr in safe:                    # marked safe – but a mail that only pretends to be from them is still caught
        return ('scam', ['safe_auth_fail']) if failed else (None, [])
    sdom = _dom(addr)
    subject = str(msg.get('Subject', ''))
    sig = []
    if failed:
        sig.append('auth_fail')
    text, htm = _parts(msg)
    urgent = bool(URGENT.search(subject[:1000] + '\n' + text + '\n' + re.sub(r'<[^>]{0,2000}>', ' ', htm)))
    # a brand in the sender's name, or in the subject of an urgent mail ("Microsoft Teams meeting" alone is not a claim)
    claimed = _brand_claimed(name) + (_brand_claimed(subject) if urgent else [])
    if claimed and sdom and not any(d.search(sdom) for d in claimed):
        sig.append('brand')
    if _lookalike(sdom):
        sig.append('lookalike')
    shown = re.findall(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\b[\w-]+\.(?:com|dk|net|org)\b', name, re.I)
    if shown and sdom and not any(_base(_dom(x) or x) == _base(sdom) for x in shown):
        sig.append('name_address')
    _, rto = email.utils.parseaddr(str(msg.get('Reply-To', '')))
    if rto and sdom and _base(_dom(rto)) != _base(sdom):
        sig.append('reply_to')
    p = _Links()
    try:
        p.feed(htm)
    except Exception:
        pass
    hrefs = [h[:2000] for h, _ in p.links if h.lower().startswith(('http://', 'https://'))] + find_links(text)
    for href, shown_text in p.links:
        h = _host(href[:2000])
        shown = _shown_domain(shown_text)
        if h and shown and _base(shown) != _base(h):
            sig.append('link_text')
            break
    hosts = {_host(h) for h in hrefs} - {''}
    if any(SHORTENERS.match(h) for h in hosts):
        sig.append('shortener')
    if any(_is_ip(h) for h in hosts):
        sig.append('ip_link')
    if 'lookalike' not in sig and any(_lookalike(h) for h in hosts):
        sig.append('lookalike')
    if urgent:
        sig.append('urgent')
    sig = list(dict.fromkeys(sig))
    level = _verdict(sig)
    if level and addr in known and 'auth_fail' not in sig:
        level = None                                   # someone you know, and the mail really is from them
    return level, sig


def _digits(n):
    return re.sub(r'\D', '', str(n or ''))[-8:]


def check_sms(number, text, known_numbers=frozenset(), safe=frozenset()):
    """(level | None, [codes]) for a text message: number = the sender, text = what the digest shows of it."""
    d = _digits(number)
    if not d or d in known_numbers or d in safe:
        return None, []
    sig = []
    links = find_links(text)
    hosts = {_host(x) for x in links} - {''}
    if links:
        sig.append('sms_unknown_link')
    if _brand_claimed(text):
        sig.append('sms_unknown_brand')
    if URGENT.search(text or ''):
        sig.append('urgent')
    if any(SHORTENERS.match(h) for h in hosts):
        sig.append('shortener')
    if any(_lookalike(h) for h in hosts):
        sig.append('lookalike')
    if any(_is_ip(h) for h in hosts):
        sig.append('ip_link')
    codes = set(sig)
    if 'sms_unknown_link' in codes and codes & {'urgent', 'sms_unknown_brand', 'lookalike', 'ip_link', 'shortener'}:
        return 'scam', sig
    if 'sms_unknown_link' in codes or len(codes) >= 2:
        return 'check', sig
    return None, sig


SMS_CHANNELS = ('sms', 'imessage', 'messages')
URGENT_SECTIONS = ('p0', 'p1', 'p2')


class Bad(Exception):
    pass


class Safety:
    def __init__(self, state_dir, digests_dir, raw_of, known, held=lambda: (), log=None):
        """raw_of(message_id) → RFC 822 bytes or None; known() → (set of e-mail addresses, set of last-8 phone digits);
        held() → addresses set to "Always hold"."""
        self.file = os.path.join(state_dir, 'safety.json')
        self.digests = digests_dir
        self.raw_of, self.known, self.held, self.log = raw_of, known, held, log

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        d.setdefault('flagged', {})
        d.setdefault('safe', [])
        d.setdefault('checked', {})
        return d

    def _save(self, d):
        d['checked'] = dict(sorted(d['checked'].items())[-400:])
        d['flagged'] = dict(sorted(d['flagged'].items(), key=lambda kv: kv[1].get('at', ''))[-2000:])
        tmp = self.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.file)

    @staticmethod
    def signals(codes):
        return [{'code': c, 'text': TEXT.get(c, c)} for c in codes]

    def _safe_set(self, st):
        s = {str(x).lower() for x in st['safe']}
        return s | {_digits(x) for x in s if _digits(x) and '@' not in x}

    def check_item(self, it, known, safe):
        ch = str(it.get('channel') or '').lower()
        frm = it.get('from') or {}
        if ch == 'mail' and it.get('message_id'):
            try:
                raw = self.raw_of(it['message_id'])
            except Exception:
                raw = None
            return check_mail(raw, known[0], safe) if raw else (None, [])
        if ch in SMS_CHANNELS:
            text = ' '.join(str(it.get(k) or '') for k in ('headline', 'subject', 'detail', 'summary'))
            return check_sms(frm.get('address') or frm.get('number') or '', text, known[1], safe)
        return None, []

    def scan_digest(self, name):
        """Check one digest once (idempotent). Returns the number of flagged items, or None if nothing was done.
        The digest file is changed through digestfile.update (locked, re-read, atomic)."""
        import digestfile
        path = os.path.join(self.digests, name)
        with LOCK:
            st = self.load()
            if st['checked'].get(name, 0) >= V:
                return None
            try:
                known = self.known()
            except Exception:
                known = (set(), set())
            safe = self._safe_set(st)
            try:
                held = {str(x).lower() for x in (self.held() or ())}
            except Exception:
                held = set()

            def change(d):
                if not isinstance(d, dict) or not isinstance(d.get('items'), list):
                    return False, None
                keep, n_flag, n_held = [], 0, 0
                for it in d['items']:
                    if not isinstance(it, dict):
                        keep.append(it)
                        continue
                    addr = str((it.get('from') or {}).get('address') or '').lower()
                    if addr and addr in held and it.get('section') not in ('cal', 'wait', 'open'):
                        n_held += 1
                        continue
                    level, codes = self.check_item(it, known, safe)
                    if level:
                        n_flag += 1
                        sf = {'level': level, 'label': LABEL[level], 'signals': self.signals(codes), 'v': V}
                        if it.get('section') in URGENT_SECTIONS:
                            sf['was'] = it['section']
                            it['section'] = 'p3'
                        if it.get('draft'):
                            it.pop('draft', None)
                            sf['draft_removed'] = True
                        it['safety'] = sf
                        key = 'mid:' + str(it['message_id']) if it.get('message_id') else 'item:%s/%s' % (name, it.get('id'))
                        st['flagged'][key] = {'level': level, 'codes': codes, 'sender': addr, 'digest': name,
                                              'item_id': str(it.get('id')), 'message_id': it.get('message_id'),
                                              'channel': it.get('channel'),
                                              'at': datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
                    keep.append(it)
                if not (n_flag or n_held):
                    return False, 0
                d['items'] = keep
                if n_held:
                    d['held'] = d.get('held', 0) + n_held
                if n_flag:
                    d['scam_held'] = n_flag
                    line = '%d message%s held as a possible scam – open %s in Axella to see why.' % (
                        n_flag, '' if n_flag == 1 else 's', 'it' if n_flag == 1 else 'them')
                    from recurring import add_spoken     # the JSON's spoken text and Listen's spoken-digest.md
                    add_spoken(self.digests, name, d, line)
                return True, n_flag

            n = digestfile.update(path, change)
            if n is None:                              # unreadable (still being written) – try again next round
                return None
            st['checked'][name] = V
            self._save(st)
            return n or 0

    def scan_new(self, last=6, skip=lambda name: False):
        """Check the newest digests that haven't been checked yet (the push watcher calls this before pushing);
        skip(name) = a digest still being written by its run, left for a later round."""
        try:
            names = sorted(n for n in os.listdir(self.digests) if n.endswith('.json') and n[:4].isdigit())
        except OSError:
            return
        done = self.load()['checked']
        for n in names[-last:]:
            if done.get(n, 0) < V and not skip(n):
                self.scan_digest(n)

    # ---- lookups for Ask, Search and the dashboard
    def flag_of(self, it):
        """The safety note for an item found anywhere (a Search hit, an Ask answer) – or None."""
        st = self.load()
        v = st['flagged'].get('mid:' + str(it.get('message_id'))) if it.get('message_id') else None
        if v is None and it.get('id') is not None:
            v = next((x for x in st['flagged'].values() if x.get('item_id') == str(it['id'])
                      and (not it.get('digest') or x.get('digest') == it.get('digest'))), None)
        if not v or (v.get('sender') and v['sender'] in self._safe_set(st)):
            return None
        return {'level': v['level'], 'label': LABEL[v['level']], 'signals': self.signals(v.get('codes') or []), 'v': V}

    def filter_ask(self, result):
        """Ask Axella's action cards: none that touch a flagged item or write to a flagged sender."""
        if not isinstance(result, dict) or not isinstance(result.get('actions'), list):
            return result
        st = self.load()
        safe = self._safe_set(st)
        live = [v for v in st['flagged'].values() if v.get('sender') not in safe]
        mids = {v.get('message_id') for v in live if v.get('message_id')}
        ids = {v.get('item_id') for v in live if v.get('item_id')}
        senders = {v.get('sender') for v in live if v.get('sender')}

        def bad(step):
            p = step.get('payload') if isinstance(step.get('payload'), dict) else step
            to = p.get('to')
            tos = to if isinstance(to, (list, tuple)) else re.split(r'[,;]', str(to or ''))
            tos = {email.utils.parseaddr(str(x))[1].lower() or str(x).strip().lower() for x in tos}
            return str(p.get('item_id') or '') in ids or p.get('message_id') in mids or bool(tos & senders)

        out = []
        for card in result['actions']:
            steps = card.get('steps') if isinstance(card, dict) and isinstance(card.get('steps'), list) else [card]
            if not any(bad(s) for s in steps if isinstance(s, dict)):
                out.append(card)
        if len(out) != len(result['actions']):
            result = dict(result, actions=out, safety_removed=len(result['actions']) - len(out))
        return result

    def _unlabel(self, who, last=60):
        """Take the label off this sender's items in the recent digests (a removed draft stays removed)."""
        import digestfile
        dg = _digits(who) if '@' not in who else ''
        try:
            names = sorted(x for x in os.listdir(self.digests) if x.endswith('.json') and x[:4].isdigit())[-last:]
        except OSError:
            return 0

        def change(d):
            hit = 0
            for it in d.get('items') or [] if isinstance(d, dict) else []:
                if not isinstance(it, dict) or 'safety' not in it:
                    continue
                a = str((it.get('from') or {}).get('address') or '').strip().lower()
                if a == who or (dg and _digits(a) == dg):
                    it.pop('safety', None)
                    hit += 1
            return bool(hit), hit
        return sum(digestfile.update(os.path.join(self.digests, n), change) or 0 for n in names)

    def action(self, action, p):
        with LOCK:
            st = self.load()
            who = str(p.get('sender') or '').strip().lower()
            if not who or len(who) > 200:
                raise Bad('which sender?')
            if action == 'safety_mark_safe':
                if who not in st['safe']:
                    st['safe'].append(who)
                self._save(st)
                n = self._unlabel(who)
                return {'message': 'Marked safe – messages from this sender are not flagged again', 'unlabelled': n}
            if action == 'safety_unmark_safe':
                st['safe'] = [x for x in st['safe'] if x != who]
                self._save(st)
                return {'message': 'Flags are back on for this sender'}
            raise Bad('unknown action')
