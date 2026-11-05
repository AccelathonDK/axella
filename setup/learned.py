"""Teach Axella (dev request teach-axella): feedback on items, rules suggested from your habits, and the rules.

state/learned-rules.json – the rules, made only on a tap (feedback with a reason, or "Make it a rule"), never silently,
  and the suggestion bookkeeping (shown, not now, never). Every rule is listed in Settings → Rules → Learned from you
  and can be removed (and restored).
state/learned-habits.jsonl – your own actions (file, done, reply: who, which account, which folder, when), 60 days, so
  the habit detectors can see what you always do. Rules on the Mac mini only; no Claude, nothing leaves the home.

Kinds of rule: sender, domain or topic word → section (FYI, to answer, urgent); sender → hold, VIP or file to a
folder. Hold, VIP and file-to are applied by the action service (the hold list, contacts.md, the filing memory and
filing by itself); section rules are applied to each new digest here and also go to the digest and urgent-check runs
as a short "Learned rules" block (prompt_note). Your explicit settings always win: a VIP is never lowered, an item the
scam check flagged is never moved, and a rule never reaches a private contact or a protected workplace (their mail
never reaches a digest's items, and the action service never files a protected workplace's mail by itself)."""
import datetime
import json
import os
import re
import threading
import uuid

import digestfile

SECTION_TEXT = {'p0': 'always urgent', 'p1': 'always to answer', 'p3': 'FYI'}
SECTION_PROMPT = {'p0': 'urgent (P0)', 'p1': 'to answer (P1)', 'p3': 'FYI (P3)'}
ADDR = re.compile(r'^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$')
DOMAIN = re.compile(r'^[a-z0-9-]{1,63}(\.[a-z0-9-]{1,63})+$')
TOPIC = re.compile(r"^[^\W_][\w .'&-]{1,38}[^\W_]$", re.U)                     # 3–40: letters, digits, space . ' & -
NAME_BAD = re.compile(r"[^\w .'’&-]", re.U)
FOLDER = re.compile(r'^[^\n\r<>`\x00-\x1f]{1,200}$')
# a domain rule for a mail provider would cover everyone who uses it – a sender rule there instead
FREEMAIL = {'gmail.com', 'googlemail.com', 'icloud.com', 'me.com', 'mac.com', 'outlook.com', 'hotmail.com', 'live.com',
            'msn.com', 'yahoo.com', 'aol.com', 'proton.me', 'protonmail.com', 'gmx.com', 'gmx.net', 'mail.com'}
STOP = {'the', 'and', 'for', 'you', 'your', 'with', 'from', 'this', 'that', 'are', 'was', 'have', 'has', 'not', 'new',
        'fwd', 'our', 'about', 'will', 'can', 'just', 'now', 'today', 'week', 'please', 'reminder', 'update'}
WEEK_MAX = 3            # suggestions shown in any 7 days
LATER_DAYS = 7          # "Not now" comes back at the earliest after this
HABIT_DAYS = 60
MAX_RULES = 200
LOCK = threading.RLock()


class Bad(Exception):
    pass


def _now():
    return datetime.datetime.now().replace(microsecond=0)


def _iso(d):
    return d.isoformat(timespec='seconds')


def _parse(s):
    try:
        d = datetime.datetime.fromisoformat(str(s).replace('Z', '+00:00')[:25])
    except (TypeError, ValueError):
        return None
    return d.astimezone().replace(tzinfo=None) if d.tzinfo else d


def clean_name(s):
    return ' '.join(NAME_BAD.sub(' ', str(s or '')).split())[:60]


def address(s):
    s = str(s or '').strip().lower()
    return s if len(s) <= 200 and ADDR.match(s) else ''


def topic_guess(subject):
    """A topic word to start from in the feedback sheet: the longest word of the subject that isn't a filler."""
    words = [w for w in re.findall(r"[^\W\d_][\w'&-]{2,30}", str(subject or ''), re.U) if w.lower() not in STOP]
    return max(words, key=len).lower() if words else ''


def plain(r):
    """The rule in plain words, as Settings shows it: "Acme newsletters: FYI", "Lee Chen: always to answer"."""
    if r.get('topic'):
        who = 'Mail about “%s”' % r['topic']
    else:
        who = r.get('label') or (('@' + r['domain']) if r.get('domain') else r.get('sender') or '?')
    if r['kind'] == 'section':
        return '%s: %s' % (who, SECTION_TEXT.get(r.get('value'), r.get('value')))
    if r['kind'] == 'hold':
        return '%s: hold' % who
    if r['kind'] == 'vip':
        return '%s: VIP' % who
    if r['kind'] == 'file':
        return '%s: file to %s' % (who, r.get('value'))
    return who


class Learned:
    def __init__(self, state_dir):
        self.path = os.path.join(state_dir, 'learned-rules.json')
        self.habits_path = os.path.join(state_dir, 'learned-habits.jsonl')

    # ---------- storage ----------
    def load(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        d['rules'] = [r for r in d.get('rules') or [] if isinstance(r, dict) and r.get('id') and r.get('kind')]
        d['removed'] = [r for r in d.get('removed') or [] if isinstance(r, dict) and r.get('id')]
        s = d.get('suggest') if isinstance(d.get('suggest'), dict) else {}
        for k, v in (('shown', []), ('never', []), ('done', []), ('later', {}), ('current', None)):
            if not isinstance(s.get(k), type(v)) and v is not None:
                s[k] = v
            s.setdefault(k, v)
        d['suggest'] = s
        return d

    def _save(self, d):
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ---------- rules ----------
    @staticmethod
    def make(kind, sender='', domain='', topic='', value=None, label='', account='', why='', source='feedback', ctx=''):
        """A checked rule (raises Bad). One of sender / domain / topic; domain and topic only for section rules."""
        if kind not in ('section', 'hold', 'vip', 'file'):
            raise Bad('unknown kind of rule')
        sender = address(sender)
        domain = str(domain or '').strip().lower().lstrip('@')
        topic = ' '.join(str(topic or '').lower().split())
        r = {'id': uuid.uuid4().hex[:10], 'kind': kind, 'at': _iso(_now()),
             'source': source if source in ('feedback', 'suggestion') else 'feedback',
             'why': ' '.join(str(why or '').split())[:160], 'label': clean_name(label)}
        if kind == 'section':
            if value not in SECTION_TEXT:
                raise Bad('which section?')
            r['value'] = value
            if sender:
                r['sender'] = sender
            elif domain:
                if not DOMAIN.match(domain) or domain in FREEMAIL:
                    raise Bad('a rule for a whole mail provider would cover everyone – pick this sender instead')
                r['domain'] = domain
            elif topic:
                if not TOPIC.match(topic):
                    raise Bad('a topic is 3–40 letters or digits (spaces . \' & - allowed)')
                r['topic'] = topic
                r['label'] = ''
            else:
                raise Bad('a sender, domain or topic')
            return r
        if not sender:
            raise Bad('which sender?')
        r['sender'] = sender
        if kind == 'file':
            folder = str(value or '').strip()
            if not FOLDER.match(folder) or not account:
                raise Bad('which folder?')
            r['value'], r['account'] = folder, str(account)[:100]
        if kind == 'vip':
            if not r['label']:
                raise Bad('a VIP needs a name')
            r['ctx'] = 'work' if ctx == 'work' else 'private'
        return r

    @staticmethod
    def _key(r):
        return tuple(r.get(k) for k in ('sender', 'domain', 'topic'))

    def add(self, r):
        """Store a rule. One rule per kind for the same sender / domain / topic (a new one replaces it) – so a section
        rule replaces any other section for that match. Returns (rule, the rule it replaced or None)."""
        with LOCK:
            d = self.load()
            old = next((x for x in d['rules'] if x['kind'] == r['kind'] and self._key(x) == self._key(r)), None)
            d['rules'] = [x for x in d['rules'] if not (x['kind'] == r['kind'] and self._key(x) == self._key(r))] + [r]
            d['rules'] = d['rules'][-MAX_RULES:]
            self._save(d)
        return r, old

    def remove(self, rid):
        with LOCK:
            d = self.load()
            r = next((x for x in d['rules'] if x['id'] == rid), None)
            if not r:
                raise Bad('that rule is gone already')
            d['rules'] = [x for x in d['rules'] if x['id'] != rid]
            d['removed'] = (d['removed'] + [dict(r, removed=_iso(_now()))])[-20:]
            self._save(d)
        return r

    def restore(self, rid):
        with LOCK:
            d = self.load()
            r = next((x for x in d['removed'] if x.get('id') == rid), None)
            if not r:
                raise Bad('nothing to restore')
            d['removed'] = [x for x in d['removed'] if x.get('id') != rid]
            r = {k: v for k, v in r.items() if k != 'removed'}
            d['rules'] = [x for x in d['rules'] if not (x['kind'] == r['kind'] and self._key(x) == self._key(r))] + [r]
            self._save(d)
        return r

    def rules(self, kind=None):
        return [r for r in self.load()['rules'] if kind is None or r['kind'] == kind]

    def view(self):
        return {'rules': [dict(r, text=plain(r)) for r in reversed(self.load()['rules'])]}

    # ---------- feedback on an item ----------
    def feedback(self, what, why, item, level='answer'):
        """what: 'not_important' | 'reached'; why: 'sender' | 'topic' | 'once'; item: {address, name, topic}.
        Returns the rule to add, or None for "just this once"."""
        if what not in ('not_important', 'reached') or why not in ('sender', 'topic', 'once'):
            raise Bad('which feedback?')
        if why == 'once':
            return None
        value = 'p3' if what == 'not_important' else ('p0' if level == 'urgent' else 'p1')
        reason = 'You said it isn\'t important' if what == 'not_important' else 'You said it should have reached you'
        if why == 'sender':
            a = address(item.get('address'))
            if not a:
                raise Bad('this item has no sender address – pick the topic instead')
            return self.make('section', sender=a, value=value, label=clean_name(item.get('name')) or a, why=reason)
        return self.make('section', topic=item.get('topic'), value=value, why=reason)

    # ---------- applying section rules to a new digest ----------
    @staticmethod
    def match(it, rules):
        """The rule for this item: a sender rule first, then a domain rule, then a topic word in headline or subject."""
        a = address((it.get('from') or {}).get('address'))
        dom = a.split('@')[1] if a else ''
        text = ' '.join(str(it.get(k) or '') for k in ('headline', 'subject')).lower()
        for r in rules:
            if r.get('sender') and r['sender'] == a:
                return r
        for r in rules:
            if r.get('domain') and dom and (dom == r['domain'] or dom.endswith('.' + r['domain'])):
                return r
        for r in rules:
            if r.get('topic') and re.search(r'(?<!\w)' + re.escape(r['topic']) + r'(?!\w)', text):
                return r
        return None

    def apply_items(self, items, is_vip=lambda it: False):
        """Move items between urgent / to answer / FYI by the section rules. Returns how many moved. Never moved: an
        item the scam check flagged, a VIP's item lowered, an urgent item "raised" to answer, and anything that isn't
        a to-answer / FYI item (carried over, calendar, waiting, filing)."""
        rules = self.rules('section')
        if not rules:
            return 0
        moved = 0
        for it in items:
            if not isinstance(it, dict) or it.get('section') not in ('p0', 'p1', 'p2', 'p3') or it.get('safety'):
                continue
            r = self.match(it, rules)
            if not r:
                continue
            sec, want = it['section'], r['value']
            if sec == want or (want == 'p3' and is_vip(it)) or (want == 'p1' and sec == 'p0'):
                continue
            it['section'] = want
            moved += 1
        return moved

    def file_candidates(self, items, handled=()):
        """Filing suggestions from a sender with a file rule, in the rule's account: [(item, rule)] to file by itself."""
        rules = {r['sender']: r for r in self.rules('file')}
        out = []
        for it in items:
            if not isinstance(it, dict) or it.get('section') != 'file' or it.get('safety') or it.get('id') in handled:
                continue
            r = rules.get(address((it.get('from') or {}).get('address')))
            if r and r.get('account') == it.get('account') and it.get('message_id'):
                out.append((it, r))
        return out

    def apply_to_digest(self, path, is_vip=lambda it: False):
        """A digest's .json: the section rules applied in place, through digestfile.update – the shared lock every
        digest rewrite takes (scam check, scope, the Mac mini's lines), re-read inside it, written only when something
        moved. Returns (moved, items)."""
        def change(d):
            items = d.get('items') if isinstance(d, dict) else None
            if not isinstance(items, list):
                return False, (0, [])
            n = self.apply_items(items, is_vip)
            return n > 0, (n, items)
        return digestfile.update(path, change) or (0, [])

    @staticmethod
    def lower_item(digests_dir, item_id, last=3):
        """"Not important – just this once": this one item to FYI in the newest digest that has it (no rule). Through
        digestfile.update – the shared lock every digest rewrite takes, re-read inside it."""
        try:
            names = sorted(n for n in os.listdir(digests_dir) if n.endswith('.json') and n[:4].isdigit() and not re.search(r'-p0\b', n))
        except OSError:
            return False

        def change(d):
            items = d.get('items') if isinstance(d, dict) else None
            it = next((x for x in items if isinstance(x, dict) and x.get('id') == item_id), None) if isinstance(items, list) else None
            if it is None:
                return False, None                         # not in this digest: look in the one before
            if it.get('section') not in ('p0', 'p1', 'p2') or it.get('safety'):
                return False, False
            it['section'] = 'p3'
            return True, True
        for n in reversed(names[-last:]):
            r = digestfile.update(os.path.join(digests_dir, n), change)
            if r is not None:
                return r
        return False

    def prompt_note(self):
        """The "Learned rules" block for the digest and urgent-check runs: section rules only, in fixed shapes built
        from checked addresses, domains and topic words – never a display name."""
        lines = []
        for r in self.rules('section')[-60:]:
            if r.get('sender') and ADDR.match(r['sender']):
                who = 'mail from %s' % r['sender']
            elif r.get('domain') and DOMAIN.match(r['domain']):
                who = 'mail from anyone @%s' % r['domain']
            elif r.get('topic') and TOPIC.match(r['topic']):
                who = 'mail about "%s"' % r['topic']
            else:
                continue
            if r.get('value') in SECTION_PROMPT:
                lines.append('- %s: %s' % (who, SECTION_PROMPT[r['value']]))
        if not lines:
            return ''
        return ('\n\nLearned rules (the owner made each one on a tap – Settings → Rules → Learned from you). Put matching '
                'items in that section. The owner\'s own settings always win over a learned rule: VIPs, private contacts, '
                'protected workplaces and the scam check work exactly as AXELLA.md says.\n' + '\n'.join(lines))

    # ---------- habits ----------
    def record(self, kind, sender, account='', folder='', first_seen=None, now=None):
        """One of your own actions (file / done / reply on a mail) – who, the account, the folder, when."""
        a = address(sender)
        if kind not in ('file', 'done', 'reply') or not a:
            return False
        now = now or _now()
        e = {'at': _iso(now), 'kind': kind, 'sender': a, 'account': str(account or '')[:100]}
        if folder:
            e['folder'] = str(folder)[:200]
        fs = _parse(first_seen) if first_seen else None
        if fs:
            e['first_seen'] = _iso(fs)
        with LOCK:
            keep = self._habits(now) + [e]
            tmp = self.habits_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in keep[-3000:]))
            os.replace(tmp, self.habits_path)
        return True

    def _habits(self, now=None):
        cut = _iso((now or _now()) - datetime.timedelta(days=HABIT_DAYS))
        out = []
        try:
            with open(self.habits_path, encoding='utf-8') as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(e, dict) and str(e.get('at') or '') >= cut and e.get('sender'):
                        out.append(e)
        except OSError:
            pass
        return out

    def detect(self, now=None, vips=(), names=None, subs=None, newsletters=True):
        """Suggestions from your own habits – rules only. vips: lower-case VIP names and addresses; names: address →
        display name (from the digests); subs: subscriptions.py's senders, for "you unsubscribe from senders like this"
        (only when Newsletters is on)."""
        now = now or _now()
        names = names or {}
        hab = self._habits(now)
        rules = self.load()['rules']

        def has(kind, a):
            return any(r['kind'] == kind and r.get('sender') == a for r in rules)

        def vip(a):
            return a in vips or (clean_name(names.get(a)) or '\x00').lower() in vips

        def nm(a):
            return clean_name(names.get(a)) or a
        out = []
        # 1. filing: the same sender to the same folder 3+ times, and (nearly) always there
        by = {}
        for e in hab:
            if e['kind'] == 'file' and e.get('folder'):
                by.setdefault(e['sender'], []).append((e.get('account', ''), e['folder']))
        for a, xs in sorted(by.items()):
            if has('file', a):
                continue
            best = max(sorted(set(xs)), key=xs.count)
            n = xs.count(best)
            if n >= 3 and n >= 0.8 * len(xs):
                out.append({'key': 'file:%s|%s' % (a, best[1]), 'n': n,
                            'text': 'You always file mail from %s in %s. Make it a rule?' % (nm(a), best[1]),
                            'rule': {'kind': 'file', 'sender': a, 'value': best[1], 'account': best[0], 'label': nm(a)}})
        month = _iso(now - datetime.timedelta(days=30))
        recent = [e for e in hab if e['at'] >= month]
        replied = {e['sender'] for e in recent if e['kind'] == 'reply'}
        # 2. done without replying: 4+ times in 30 days, never a reply in that time
        dn = {}
        for e in recent:
            if e['kind'] == 'done':
                dn[e['sender']] = dn.get(e['sender'], 0) + 1
        for a, n in sorted(dn.items()):
            if n >= 4 and a not in replied and not vip(a) and not has('section', a):
                out.append({'key': 'fyi:' + a, 'n': n, 'text': 'You mark mail from %s done without replying. Put it under FYI?' % nm(a),
                            'rule': {'kind': 'section', 'sender': a, 'value': 'p3', 'label': nm(a)}})
        # 3. fast replies: answered within the hour of arriving, 3+ times in 30 days
        fast, acct = {}, {}
        for e in recent:
            fs, at = _parse(e.get('first_seen')), _parse(e['at'])
            if e['kind'] == 'reply' and fs and at and datetime.timedelta(0) <= at - fs <= datetime.timedelta(hours=1):
                fast[e['sender']] = fast.get(e['sender'], 0) + 1
                acct[e['sender']] = e.get('account', '')
        for a, n in sorted(fast.items()):
            name = clean_name(names.get(a))
            if n >= 3 and name and not vip(a) and not has('vip', a):
                out.append({'key': 'vip:' + a, 'n': n, 'text': 'You always answer %s within the hour. Add %s to VIPs?' % (name, name.split()[0]),
                            'rule': {'kind': 'vip', 'sender': a, 'label': name, 'account': acct.get(a, '')}})
        # 4. unsubscribes: 3+ in 60 days → hold the active bulk sender you get the most from
        if newsletters and isinstance(subs, dict):
            cut = _iso(now - datetime.timedelta(days=HABIT_DAYS))
            unsub = sum(1 for s in subs.values() if isinstance(s, dict) and s.get('status') == 'unsubscribed'
                        and str(s.get('changed_at') or '') >= cut)
            if unsub >= 3:
                cands = [(address(a), s) for a, s in subs.items() if isinstance(s, dict) and s.get('status') == 'active'
                         and not s.get('hold') and not s.get('manual') and (s.get('count') or 0) >= 3]
                cands = [(a, s) for a, s in cands if a and not has('hold', a) and not vip(a)]
                cands.sort(key=lambda x: (-(x[1].get('count') or 0), x[0]))
                for a, s in cands[:3]:
                    name = clean_name(s.get('name')) or a
                    out.append({'key': 'hold:' + a, 'n': s.get('count') or 0, 'text': 'You unsubscribe from senders like this. Hold %s?' % name,
                                'rule': {'kind': 'hold', 'sender': a, 'label': name}})
        return out

    # ---------- the one suggestion card (Today and the week wrap) ----------
    def suggestion(self, candidates, now=None):
        """The current suggestion, or a new one within the limits: one at a time, at most WEEK_MAX shown in any 7
        days, "Never suggest this" never again, "Not now" not before LATER_DAYS."""
        now = now or _now()
        with LOCK:
            d = self.load()
            s = d['suggest']
            if s.get('current'):
                return s['current']
            week = _iso(now - datetime.timedelta(days=7))
            if sum(1 for x in s['shown'] if str(x.get('at') or '') >= week) >= WEEK_MAX:
                return None
            later = {k: v for k, v in s['later'].items() if str(v) > _iso(now)}
            for c in sorted(candidates, key=lambda c: -c.get('n', 0)):
                k = c['key']
                if k in s['never'] or k in s['done'] or k in later:
                    continue
                cur = {'key': k, 'text': c['text'], 'rule': c['rule'], 'at': _iso(now)}
                s['current'], s['later'] = cur, later
                s['shown'] = (s['shown'] + [{'key': k, 'at': _iso(now)}])[-50:]
                self._save(d)
                return cur
        return None

    def respond(self, key, answer, now=None):
        """accept → the rule spec (the caller makes it and does the side effects); later / never → None."""
        if answer not in ('accept', 'later', 'never'):
            raise Bad('which answer?')
        now = now or _now()
        with LOCK:
            d = self.load()
            s = d['suggest']
            cur = s.get('current')
            if not cur or cur.get('key') != key:
                raise Bad('that suggestion is gone')
            s['current'] = None
            if answer == 'later':
                s['later'][key] = _iso(now + datetime.timedelta(days=LATER_DAYS))
            elif answer == 'never':
                s['never'] = (s['never'] + [key])[-500:]
            else:
                s['done'] = (s['done'] + [key])[-500:]
            self._save(d)
        return cur['rule'] if answer == 'accept' else None
