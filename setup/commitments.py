"""Commitments and follow-through (feature pack Nov 2026 §1a, §1b) – found locally, by rules, never by Claude.

Promises: what you promised in your own sent mail and outgoing messages (iMessage/SMS, WhatsApp, Signal) – "I'll send
it Friday", "jeg vender tilbage i morgen". Each becomes a suggested card (Add to To do / Edit / Not a promise); nothing
is added without your tap. When a later message to the same person looks like it fulfils the promise, "Looks done –
tick it off?". Private and hidden contacts are never scanned.

Reply debt: people who wrote to you and haven't had an answer for longer than the threshold of their world (work: 3
working days, private: 5 days), at most max_days (21) back. Only real people – someone you have written to yourself –
never no-reply, automated or role senders (info@, post@ …), never authorities, banks or insurers (the cleanup keep
lists), never private or hidden contacts, never someone you set to "Never for this person". Only real asks: their
last message was to you directly (not Cc) and wasn't just a "thanks / tak".

state/promises.json: {"items": [{id, key, text, sentence, due, person: {name, address}, world, source: {kind, account,
  message_id, chat, at}, status: suggested|added|dismissed|done, task_id, looks_done, created}], "scanned": iso}
state/reply-debt-never.json: ["address or handle", ...]
Python 3.9.
"""
import datetime
import hashlib
import json
import os
import re
import threading

LOCK = threading.Lock()
WINDOW_DAYS = 14
KEEP_DAYS = 90
NO_DUE_DAYS = 14                  # a promise without a date: off the list after two weeks

# ---------- finding a promise ----------
VERBS_EN = (r"send|call|ring|phone|text|e-?mail|mail|write|reply|answer|get back|come back|revert|follow up|share|forward|"
            r"check|look into|look at|confirm|update|prepare|book|pay|deliver|order|arrange|sort|fix|finish|review|sign|"
            r"let you know|get you|have it|have that|have the|bring|drop by|pick up|transfer|invoice|organi[sz]e|schedule|set up|ping|"
            r"come by|be in touch|reach out|circle back")
EN = re.compile(r"\b(?:i(?:'| wi)ll|i will|i shall|i'm going to|i am going to|i promise to|let me|i can (?:send|get|have))\s+"
                r"(?:also |just |quickly |definitely |try to |make sure to |make sure i )?(?:" + VERBS_EN + r")\b", re.I)
VERBS_DA = (r"sende[rs]?|sender|ringe[rs]?|ringer|skrive[rs]?|skriver|vende[rs]? tilbage|vender tilbage|melde[rs]? tilbage|"
            r"melder tilbage|kigge[rs]? på|kigger på|tjekke[rs]?|tjekker|undersøge[rs]?|undersøger|bekræfte[rs]?|bekræfter|"
            r"følge[rs]? op|følger op|give[rs]? (?:dig |jer )?besked|giver (?:dig |jer )?besked|ordne[rs]?|ordner|booke[rs]?|booker|"
            r"betale[rs]?|betaler|lave[rs]?|laver|sørge[rs]? for|sørger for|svare[rs]?|svarer|komme[rs]? forbi|kommer forbi|"
            r"videresende[rs]?|videresender|fikse[rs]?|fikser|overføre[rs]?|overfører|bestille[rs]?|bestiller|aftale[rs]?|aftaler")
DA = re.compile(r"\b(?:jeg|vi)\s+(?:vil|skal|kan|lover at|lover)?\s*(?:lige |også |hurtigt |gerne |nok )?(?:" + VERBS_DA + r")\b|"
                r"\blad mig\s+(?:lige )?(?:" + VERBS_DA + r"|tjekke|kigge|vende tilbage)\b", re.I)
NOT_PROMISE = re.compile(r"\b(?:if|hvis|maybe|måske|could i|can i\b(?! send)|shall i|skal jeg\b|kan jeg\b|vil du|would you|"
                         r"did you|have you|hope|håber|wish|ville ønske|i'll be (?:out|away|off)|out of office|ikke på kontoret)\b", re.I)
QUOTE_START = re.compile(r"^(?:on .{5,120} wrote:|den .{5,120} skrev .{0,80}:|.{0,120} skrev:|-----original message-----|"
                         r"-{2,} ?(?:forwarded|videresendt) .*|from: .+|fra: .+|sent from my .+|sendt fra min .+|>)", re.I)

WEEKDAYS = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6,
            'mandag': 0, 'tirsdag': 1, 'onsdag': 2, 'torsdag': 3, 'fredag': 4, 'lørdag': 5, 'søndag': 6,
            'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4}
MONTHS = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'maj': 5, 'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'okt': 10,
          'nov': 11, 'dec': 12}


def own_text(body):
    """Your own words only: everything up to the quoted message or the signature-ish lines."""
    out = []
    for line in str(body or '').replace('\r\n', '\n').split('\n'):
        t = line.strip()
        if QUOTE_START.match(t):
            break
        out.append(line)
    return '\n'.join(out).strip()[:6000]


def sentences(text):
    t = re.sub(r'\s+', ' ', text)
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+|\s*\n\s*', text) if s.strip()] if '\n' in text else \
        [s.strip() for s in re.split(r'(?<=[.!?])\s+', t) if s.strip()]


def due_date(s, sent):
    """The date a sentence names, relative to when it was sent – or None. Danish and English."""
    low = s.lower()
    d = sent.date() if isinstance(sent, datetime.datetime) else sent
    if re.search(r'\b(today|later today|this (?:afternoon|evening|morning)|tonight|i dag|senere i dag|i eftermiddag|i aften|i formiddag)\b', low):
        return d
    if re.search(r'\b(i overmorgen|day after tomorrow)\b', low):
        return d + datetime.timedelta(days=2)
    if re.search(r'\b(tomorrow|i morgen|imorgen|tmrw)\b', low):
        return d + datetime.timedelta(days=1)
    m = re.search(r'\b(?:in|om) (\d{1,2}|two|three|a couple of|to|tre) (?:days|dage)\b', low)
    if m:
        n = {'two': 2, 'three': 3, 'a couple of': 2, 'to': 2, 'tre': 3}.get(m.group(1)) or int(m.group(1))
        return d + datetime.timedelta(days=n)
    if re.search(r'\b(end of (?:the )?week|by the weekend|before the weekend|inden ugen er omme|sidst på ugen|i løbet af ugen|inden weekenden|this week|denne uge|i denne uge)\b', low):
        return d + datetime.timedelta(days=(4 - d.weekday()) % 7)
    if re.search(r'\b(next week|næste uge|i næste uge|early next week|først i næste uge|start of next week)\b', low):
        return d + datetime.timedelta(days=7 - d.weekday())
    m = re.search(r'\b(\d{1,2})(?:\.|st|nd|rd|th)?\s*(?:of\s+)?(jan|feb|mar|apr|maj|may|jun|jul|aug|sep|okt|oct|nov|dec)[a-z]*\b', low) or \
        re.search(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b', low)
    if m:
        a, b = m.groups()
        day, mon = (int(a), MONTHS[b[:3]]) if a.isdigit() else (int(b), MONTHS[a[:3]])
        try:
            x = datetime.date(d.year, mon, day)
            return x if x >= d - datetime.timedelta(days=1) else datetime.date(d.year + 1, mon, day)
        except ValueError:
            return None
    m = re.search(r'\b(\d{1,2})[/.](\d{1,2})\b(?![/.]\d)', low)
    if m and int(m.group(2)) <= 12:
        try:
            x = datetime.date(d.year, int(m.group(2)), int(m.group(1)))
            return x if x >= d - datetime.timedelta(days=1) else datetime.date(d.year + 1, x.month, x.day)
        except ValueError:
            pass
    m = re.search(r'\b(?:on |by |before |på |til |inden |senest )?(?:next |på )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mandag|tirsdag|onsdag|torsdag|fredag|lørdag|søndag)\b', low)
    if m:
        wd = WEEKDAYS[m.group(1)]
        ahead = (wd - d.weekday()) % 7 or 7
        return d + datetime.timedelta(days=ahead)
    return None


def find(text, sent):
    """Promises in your own words: [{'sentence', 'due'}] – at most three per message."""
    out = []
    for s in sentences(own_text(text)):
        if len(s) < 8 or len(s) > 400 or s.endswith('?'):
            continue
        if not (EN.search(s) or DA.search(s)) or NOT_PROMISE.search(s):
            continue
        out.append({'sentence': s[:300], 'due': due_date(s, sent)})
        if len(out) >= 3:
            break
    return out


def summary(sentence, name):
    """'You promised Lee: "I'll send the revised quote Friday."'"""
    return 'You promised %s: "%s"' % (name or 'them', sentence.strip().rstrip('.') + '.')


def key_of(kind, ref, sentence):
    return hashlib.sha1(('%s|%s|%s' % (kind, ref, re.sub(r'\W+', ' ', sentence.lower()).strip())).encode()).hexdigest()[:20]


# ---------- iMessage text (newer macOS keeps it in attributedBody) ----------
def attributed_text(blob):
    if not blob:
        return None
    try:
        t = bytes(blob).split(b'NSString', 1)[1][5:]
        if t[0] == 0x81:
            n, t = int.from_bytes(t[1:3], 'little'), t[3:]
        elif t[0] == 0x82:
            n, t = int.from_bytes(t[1:4], 'little'), t[4:]
        else:
            n, t = t[0], t[1:]
        return t[:n].decode('utf-8', 'replace')
    except Exception:
        return None


# ---------- the store ----------
class Promises:
    def __init__(self, state_dir):
        self.file = os.path.join(state_dir, 'promises.json')
        self.never_file = os.path.join(state_dir, 'reply-debt-never.json')
        self.done_file = os.path.join(state_dir, 'reply-debt-done.json')    # {who: their last message you marked done}

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        if not isinstance(d, dict) or not isinstance(d.get('items'), list):
            d = {'items': []}
        return d

    def _save(self, d):
        tmp = self.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)

    def merge(self, found, now=None):
        """Add new suggestions; never bring back one you dismissed or already have. Old suggestions fade after 90 days."""
        now = now or datetime.datetime.now().astimezone()
        with LOCK:
            d = self.load()
            have = {x['key'] for x in d['items']}
            n = 0
            for f in found:
                if f['key'] in have:
                    continue
                have.add(f['key'])
                d['items'].append(dict(f, id='pr' + f['key'][:12], status='suggested', created=now.isoformat(timespec='seconds')))
                n += 1
            cut = (now - datetime.timedelta(days=KEEP_DAYS)).isoformat()
            # keep the keys of old dismissed ones (so they never come back), drop old untouched suggestions
            d['items'] = [x for x in d['items'] if x['status'] != 'suggested' or x.get('created', '') >= cut]
            d['scanned'] = now.isoformat(timespec='seconds')
            self._save(d)
        return n

    def suggestions(self, now=None):
        """Suggested promises to show. One without a due date fades after NO_DUE_DAYS (14) from when you made it – a
        vague "I'll let you know" doesn't stay on Today for ever; its key is kept, so it never comes back."""
        now = now or datetime.datetime.now().astimezone()
        cut = (now - datetime.timedelta(days=NO_DUE_DAYS)).isoformat()
        return [x for x in self.load()['items'] if x['status'] == 'suggested'
                and (x.get('due') or ((x.get('source') or {}).get('at') or x.get('created') or '') >= cut)]

    def looks_done(self):
        return [x for x in self.load()['items'] if x['status'] == 'added' and x.get('looks_done')]

    def set(self, pid, **kw):
        with LOCK:
            d = self.load()
            x = next((y for y in d['items'] if y['id'] == pid), None)
            if not x:
                raise ValueError('promise not found')
            x.update(kw)
            self._save(d)
            return x

    def mark_fulfilled(self, outgoing):
        """outgoing: [{'person': address, 'at': iso, 'text', 'attachment': bool, 'ref'}]. An added promise whose person got a
        later message with an attachment or with the promise's key words → looks_done."""
        with LOCK:
            d = self.load()
            n = 0
            for x in d['items']:
                if x['status'] != 'added' or x.get('looks_done'):
                    continue
                words = {w for w in re.findall(r'[a-zæøå]{5,}', x['sentence'].lower())
                         if w not in ('send', 'sende', 'sender', 'tomorrow', 'morgen', 'friday', 'fredag', 'about', 'there', 'their', 'which', 'would')}
                for o in outgoing:
                    if o['person'] != (x.get('person') or {}).get('address') or o['at'] <= x['source']['at']:
                        continue
                    t = (o.get('text') or '').lower()
                    if (o.get('attachment') and re.search(r'\b(send|sende|sender|forward|attach|vedhæft|share|quote|tilbud|file|fil)', x['sentence'], re.I)) \
                            or (len(words) >= 1 and sum(1 for w in words if w in t) >= max(1, min(2, len(words)))):
                        x['looks_done'] = {'at': o['at'], 'ref': o.get('ref')}
                        n += 1
                        break
            if n:
                self._save(d)
            return n

    # ---------- reply debt: who you never answer ----------
    def never(self):
        try:
            with open(self.never_file, encoding='utf-8') as f:
                v = json.load(f)
            return set(v) if isinstance(v, list) else set()
        except (OSError, ValueError):
            return set()

    def done(self):
        try:
            with open(self.done_file, encoding='utf-8') as f:
                v = json.load(f)
            return v if isinstance(v, dict) else {}
        except (OSError, ValueError):
            return {}

    def set_done(self, who, last_in, on=True):
        """Done / nothing to answer for this one: hidden until they write again (a message after last_in)."""
        with LOCK:
            d = self.done()
            k = str(who).lower()[:200]
            if on:
                d[k] = str(last_in or '')[:40]
            else:
                d.pop(k, None)
            if len(d) > 2000:
                d = dict(sorted(d.items(), key=lambda kv: kv[1])[-2000:])
            with open(self.done_file, 'w', encoding='utf-8') as f:
                json.dump(d, f)
        return d

    def set_never(self, who, on=True):
        with LOCK:
            s = self.never()
            (s.add if on else s.discard)(str(who).lower()[:200])
            with open(self.never_file, 'w', encoding='utf-8') as f:
                json.dump(sorted(s), f)
        return sorted(s)


def working_days_between(a, b):
    """Whole working days (Mon–Fri) from date a to date b."""
    n, d = 0, a
    while d < b:
        d += datetime.timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


# Role and organisation mailboxes – not a person who is waiting for you (fix round 7, P2-1)
ROLE_RE = re.compile(r'^(?:post|postmaster|info|kontakt|contact|support|service|kundeservice|customerservice|hello|hej|mail|'
                     r'office|kontor|admin|administration|sales|salg|booking|reception|team|hr|jobs?|karriere|career|'
                     r'faktura|invoices?|billing|accounts?|regnskab|bogholderi|ordre|orders?|webshop|shop|press|presse|'
                     r'newsletter|nyhedsbrev|help|hjaelp|hjælp|sekretariat|secretariat|borgerservice|digitalpost|sikkerpost|'
                     r'dpo|privacy|gdpr|legal|compliance|members?|medlem(?:sservice)?|events?|marketing|noreply|no-reply)'
                     r'(?:[-._+][^@]*)?@', re.I)
_THX = (r'(?:mange |tusind |1000 )?(?:tak|thanks?|thank you|thx|ty|cheers|perfekt|perfect|super|great|fint|fedt|dejligt|godt|'
        r'ok|okay|okey|modtaget|received|got it|noted|forstået|understood|👍|🙏|❤️|😊)')
_TAIL = (r'(?:for (?:det(?: hele)?|it|that|your help|the help|hjælpen|nu|i dag|today)|so much|a lot|mange gange|igen|again|'
         r'skal du have|du|you|all|alle|very much|meget|(?-i:[A-ZÆØÅ][a-zæøå]+))')      # … or a first name
THANKS_RE = re.compile(r'^' + _THX + r'(?:[ ,!.:]*(?:' + _THX + r'|' + _TAIL + r'))*[ !.,:)❤️👍🙏😊]*$', re.I)
CLOSING_RE = re.compile(r'^(?:mvh|vh|venlig hilsen|med venlig hilsen|hilsen|kh|kærlig hilsen|best|best regards|regards|'
                        r'kind regards|br|cheers|/)\b', re.I)


def role_address(addr):
    """post@, info@, kontakt@, support@ … – a shared mailbox, not a person."""
    return bool(ROLE_RE.match(str(addr or '').strip().lower()))


def just_thanks(text):
    """True when someone's last message is only a "thanks / tak" (and a greeting or a name) – nothing to answer."""
    own = own_text(text)
    lines = [ln.strip() for ln in own.split('\n') if ln.strip()]
    # drop a closing like "Mvh / Best, Lee" and everything under it, or a lone signature name
    cut = next((i for i, ln in enumerate(lines) if i and CLOSING_RE.match(ln)), None)
    if cut is not None:
        lines = lines[:cut]
    elif len(lines) > 1 and re.match(r'^[A-ZÆØÅ][\w.-]*(?: [A-ZÆØÅ][\w.-]*)?$', lines[-1]):
        lines = lines[:-1]
    body = re.sub(r'^(?:hej|hi|hello|hey|kære|dear)\b[^,!\n]{0,30}[,!]?\s*', '', ' '.join(lines), flags=re.I).strip()
    if not body or '?' in body or len(body) > 80:
        return False
    return bool(THANKS_RE.match(body))


def display_name(name, who):
    """A name to show – never a bare address: the contact or header name, else the address's local part as words."""
    n = str(name or '').strip().strip('"\'')
    if n and '@' not in n and not re.match(r'^\+?[\d ()-]{6,}$', n):
        return n
    w = str(who or n)
    if '@' in w:
        local = re.sub(r'\d+', '', w.split('@')[0])
        words = [x for x in re.split(r'[._+-]+', local) if x]
        return ' '.join(x[:1].upper() + x[1:] for x in words) or w.split('@')[1].split('.')[0].title()
    return n or w


def _ts(v):
    try:
        d = v if isinstance(v, datetime.datetime) else datetime.datetime.fromisoformat(str(v))
        return d.timestamp() if d.tzinfo else d.astimezone().timestamp()
    except (TypeError, ValueError):
        return None


def reply_debt(threads, never, today, work_days=3, private_days=5, max_days=21, done=None):
    """threads: [{'who': key (address/handle), 'name', 'world': 'work'|'private', 'last_in': datetime, 'last_out': datetime|None,
    'ever_out': bool, 'automated': bool, 'private': bool, 'institution': bool, 'direct': bool|None, 'thanks': bool,
    'channel', 'ref'}] → the people you owe an answer, longest first. Only real asks: their last message was to you
    directly (not Cc), isn't just a thanks, is at most max_days old, and isn't from an institution or a role mailbox.
    done: {who: last_in iso} you marked done – skipped until a later message from them."""
    out = []
    for t in threads:
        if t.get('private') or t.get('automated') or not t.get('ever_out') or t['who'] in never:
            continue
        if t.get('institution') or (t.get('channel', 'mail') == 'mail' and role_address(t['who'])):
            continue
        if t.get('direct') is False or t.get('thanks'):
            continue
        mark = (done or {}).get(str(t['who']).lower())
        if mark and _ts(mark) is not None and _ts(t['last_in']) is not None and _ts(t['last_in']) <= _ts(mark) + 60:
            continue                                   # you marked it done; it comes back only when they write again
        if t.get('last_out') and t['last_out'] >= t['last_in']:
            continue
        li = t['last_in'].date() if isinstance(t['last_in'], datetime.datetime) else t['last_in']
        if t['world'] == 'work':
            age = working_days_between(li, today)
            if age < work_days:
                continue
        else:
            age = (today - li).days
            if age < private_days:
                continue
        if (today - li).days > max_days:                # months-old threads are almost never owed – they drop off
            continue
        out.append(dict(t, days=(today - li).days, name=display_name(t.get('name'), t['who'])))
    out.sort(key=lambda x: -x['days'])
    return out
