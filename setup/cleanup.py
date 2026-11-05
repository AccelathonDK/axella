"""Mail cleanup – finds old mail with no relationship and no historical value, and moves it (on the owner's tap) to a
"Cleanup" folder in the same account. Nothing is deleted; every move can be undone.

Scan (weekly at night, or "Scan now"): for each mailbox the owner switched on in Settings, the Inbox, Archive and
notification folders are listed through Mail's scripting (no Claude run). A mail is a candidate only when ALL hold:
  - older than the chosen age (12, 24 or 36 months), not flagged, not replied to;
  - the sender is not someone the owner wrote to (Sent), not in contacts.md, not a receipt sender, not a project sender,
    not on the keep list, and not an authority/bank/insurer domain;
  - the subject is not about invoices, contracts, bookings, tickets, warranties, taxes, insurance and the like;
  - the mail is not tied to a project item or a knowledge entry.
Candidates are grouped by sender. Moves run one batch at a time in the background; each batch is logged with where every
mail came from, so Undo moves them back.

Files: state/cleanup.json (settings, keep list, last scan, batches), state/cleanup-candidates.json (the scan result).
"""
import datetime
import glob
import json
import os
import re
import threading
import time

LOCK = threading.Lock()
US, RS = '\x1f', '\x1e'
AGES = (12, 24, 36)
FOLDER = 'Cleanup'
SCAN_AT = (6, '03:40')          # weekly: Sunday 03:40
NEVER_RE = re.compile(r'^(sent( messages| items| mail)?|sendt|sendte( elementer| beskeder)?|gesendet(e elemente)?|drafts?|kladder|'
                      r'entwürfe|trash|deleted( items| messages)?|papirkurv|slettede( elementer)?|junk|spam|uønsket( mail)?|'
                      r'outbox|udbakke|cleanup|notes|noter|templates?|skabeloner|conversation history|sync issues.*)$', re.I)
FOLDER_RE = re.compile(r'^(inbox|archive|arkiv|archived|notifications?|notifikationer|meddelelser|newsletters?|nyhedsbreve|all mail|alle mails)$', re.I)
KEEP_SUBJECT = re.compile(
    r'faktura|invoice|rechnung|kvittering|receipt|quittung|ordre|order|bestilling|booking|reservation|billet|ticket|'
    r'boarding|kontrakt|contract|vertrag|aftale|agreement|garanti|warranty|skat|tax|steuer|forsikring|insurance|'
    r'versicherung|police|lejekontrakt|lease|pension|løn|payslip|lønseddel|e-boks|mitid|nemid|password|adgangskode|'
    r'certificate|certifikat|diploma|eksamen|exam|retur|refund|credit note|kreditnota|udbetaling|payout|settlement|'
    # tax, accounts and company papers
    r'selvangivelse|årsopgørelse|regnskab|annual report|\bcvr\b|\bse-?nr|\bvat\b|\bmoms\b|'
    # deals and property: closing a sale, share purchase, deeds
    r'\bclosing\b|(?-i:\bSPA\b)|share purchase|due diligence|term sheet|købsaftale|skøde|\bkøb af\b|\bsalg af\b|tinglysning|'
    # claims, cases and collection
    r'inkasso|rykker|betalingspåmindelse|payment reminder|skade(s?nr|s?nummer|anmeldelse)|\bskade\b|\bclaim\b|sags-?nr|sagsnummer|\bsag\b|case (no|number)', re.I)
KEEP_DOMAIN = re.compile(r'(^|\.)(skat\.dk|sktst\.dk|skattestyrelsen\.dk|virk\.dk|erst\.dk|tinglysning\.dk|borger\.dk|e-boks\.(dk|com)|mitid\.dk|nemid\.nu|sundhed\.dk|politi\.dk|'
                         r'[a-z0-9-]*kommune\.dk|[a-z0-9-]*bank[a-z0-9-]*\.[a-z]+|[a-z0-9-]*(sparekasse|andelskasse|pengeinstitut)[a-z0-9-]*\.[a-z]+|docusign\.(net|com)|penneo\.com|scrive\.com|esignatur\.dk|adobesign\.com|echosign\.com|(claims?|skade)[a-z0-9-]*\.([a-z0-9-]+\.)*[a-z]+|[a-z0-9-]*forsikring[a-z0-9-]*\.[a-z]+|'
                         r'[a-z0-9-]*insurance[a-z0-9-]*\.[a-z]+|[a-z0-9-]*(realkredit|kreditforening|pension)[a-z0-9-]*\.[a-z]+|gov\.[a-z]+|[a-z]+\.gov|admin\.ch|ch\.ch)$', re.I)
# lawyers, accountants and auditors – their mail is almost always worth keeping
PRO_DOMAIN = re.compile(r'advokat|lawfirm|lawyers?|legal|revision|revisor|accountants?|auditors?\b|assurance|versicherung|'
                        r'forsikring|insurance|deloitte|kpmg|grantthornton|(^|[.-])(law|audit|pwc|bdo|ey)([.-]|$)|-law\.', re.I)

# Your own additions – a local insurer or bank the built-in list doesn't know (e.g. acme.dk): one domain per line in
# state/cleanup-keep-domains.txt (# comments allowed). A sender's domain or any subdomain of it is always kept.
KEEP_FILE = 'cleanup-keep-domains.txt'
_local = {'mtime': None, 'set': frozenset()}


# Institutions whose domain says nothing generic: Danish banks, mortgage lenders, pension funds, insurers and public
# bodies. Kept like the generic rules above; the owner's own keep file (below) adds to this list.
BUILTIN_KEEP = frozenset('''
danskebank.dk danskebank.com nordea.dk nordea.com jyskebank.dk sydbank.dk sparnord.dk al-bank.dk landbobanken.dk
vestjyskbank.dk jutlander.dk djurslandsbank.dk nordfynsbank.dk merkur.dk handelsbanken.dk coopbank.dk lunar.app
saxobank.com ekspresbank.dk
nykredit.dk totalkredit.dk brf.dk dlr.dk
pfa.dk pka.dk velliv.dk danica.dk atp.dk lpp.dk
tryg.dk topdanmark.dk almbrand.dk gjensidige.dk codan.dk if.dk lb.dk alka.dk runa.dk privatsikring.dk
udbetaling.dk su.dk domstol.dk digst.dk nemlog-in.dk lifeindenmark.dk dst.dk
datatilsynet.dk ankestyrelsen.dk ombudsmanden.dk forbrug.dk kfst.dk naevneneshus.dk sikkerhedsstyrelsen.dk fstyr.dk
'''.split())


def _domain_in(d, keys):
    d = str(d or '').lower().rstrip('.')
    return any(d == k or d.endswith('.' + k) for k in keys)


def local_keep(domain, state_dir):
    """Kept by the built-in list of named institutions or the owner's own state/cleanup-keep-domains.txt (a domain
    and all its sub-domains; a longer name that merely ends the same way, like not<domain>, is not kept)."""
    if _domain_in(domain, BUILTIN_KEEP):
        return True
    path = os.path.join(state_dir, KEEP_FILE)
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return False
    if mt != _local['mtime']:
        try:
            with open(path, encoding='utf-8') as f:
                lines = [l.split('#', 1)[0].strip().lower().lstrip('@').rstrip('.') for l in f]
            _local['set'], _local['mtime'] = frozenset(l for l in lines if l), mt
        except OSError:
            return False
    return _domain_in(domain, _local['set'])


# AppleScript: the folders of one account (name paths a/b), one per line
FOLDERS_SCRIPT = '''
on walk(mbs, prefix)
  set out to ""
  tell application "Mail"
    repeat with mb in mbs
      set p to prefix & (name of mb)
      set out to out & p & linefeed
      try
        set out to out & my walk(every mailbox of mb, p & "/")
      end try
    end repeat
  end tell
  return out
end walk
on run argv
  tell application "Mail" to set top to every mailbox of account (item 1 of argv)
  return my walk(top, "")
end run
'''

# AppleScript: every message of one folder older than N days, not flagged – fetched in bulk (fast):
# id, sender, subject, yyyy-m-d, replied (1/0), size
LIST_SCRIPT = '''
on run argv
  set accName to item 1 of argv
  set AppleScript's text item delimiters to "/"
  set parts to text items of (item 2 of argv)
  set AppleScript's text item delimiters to ""
  set cutoff to (current date) - ((item 3 of argv) as integer) * days
  set US to (ASCII character 31)
  set RS to (ASCII character 30)
  set out to ""
  tell application "Mail"
    set mb to mailbox (item 1 of parts) of account accName
    if (count of parts) > 1 then
      repeat with i from 2 to (count of parts)
        set mb to mailbox (item i of parts) of mb
      end repeat
    end if
    set ref_ to (a reference to (every message of mb whose date received < cutoff and flagged status is false))
    set ids to message id of ref_
    if (count of ids) is 0 then return ""
    set snds to sender of ref_
    set subs to subject of ref_
    set dts to date received of ref_
    set reps to was replied to of ref_
    set szs to message size of ref_
  end tell
  repeat with i from 1 to count of ids
    set d to item i of dts
    set ds to ((year of d) as text) & "-" & ((month of d as integer) as text) & "-" & ((day of d) as text)
    set r to "0"
    if item i of reps then set r to "1"
    set out to out & (item i of ids) & US & (item i of snds) & US & (item i of subs) & US & ds & US & r & US & ((item i of szs) as text) & RS
  end repeat
  return out
end run
'''

# AppleScript: addresses the owner wrote to (To/Cc of the Sent folder, last N days)
SENT_SCRIPT = '''
on run argv
  set accName to item 1 of argv
  set sinceDate to (current date) - ((item 2 of argv) as integer) * days
  set out to ""
  tell application "Mail"
    set sb to missing value
    repeat with nm in {"Sent Messages", "Sent Items", "Sent", "Sendte elementer", "Sendt", "Sendte beskeder", "Gesendete Elemente", "Gesendet"}
      try
        set sb to mailbox (nm as text) of account accName
        exit repeat
      end try
    end repeat
    if sb is missing value then return ""
    set ms to (a reference to (every message of sb whose date sent > sinceDate))
    try
      set tos to address of every to recipient of ms
      repeat with l in tos
        repeat with a in l
          set out to out & a & linefeed
        end repeat
      end repeat
    end try
    try
      set ccs to address of every cc recipient of ms
      repeat with l in ccs
        repeat with a in l
          set out to out & a & linefeed
        end repeat
      end repeat
    end try
  end tell
  return out
end run
'''

# AppleScript: move messages (by message id) from one folder to another of the same account; creates the target
# folder at the top of the account if it is missing. argv: account, from path, to path, id1, id2, …
MOVE_SCRIPT = '''
on boxOf(accName, p)
  tell application "Mail"
    set AppleScript's text item delimiters to "/"
    set parts to text items of p
    set AppleScript's text item delimiters to ""
    set mb to mailbox (item 1 of parts) of account accName
    if (count of parts) > 1 then
      repeat with i from 2 to (count of parts)
        set mb to mailbox (item i of parts) of mb
      end repeat
    end if
    return mb
  end tell
end boxOf
on run argv
  set accName to item 1 of argv
  tell application "Mail"
    if (item 3 of argv) is "Cleanup" then
      if not (exists mailbox "Cleanup" of account accName) then make new mailbox with properties {name:"Cleanup"} at account accName
    end if
  end tell
  set src to my boxOf(accName, item 2 of argv)
  set dst to my boxOf(accName, item 3 of argv)
  set n to 0
  tell application "Mail"
    repeat with i from 4 to count of argv
      try
        set ms to (every message of src whose message id is (item i of argv))
        if (count of ms) > 0 then
          move item 1 of ms to dst
          set n to n + 1
        end if
      end try
    end repeat
  end tell
  return n as text
end run
'''


class Bad(Exception):
    pass


def _now():
    return datetime.datetime.now().astimezone()


def _iso(dt=None):
    return (dt or _now()).isoformat(timespec='seconds')


def _addr(sender):
    m = re.search(r'<([^>]+)>', sender or '')
    return (m.group(1) if m else (sender or '')).strip().lower()


def _name(sender):
    n = re.sub(r'\s*<[^>]+>\s*', '', sender or '').strip().strip('"')
    return n or _addr(sender)


def _domain(addr):
    return addr.split('@', 1)[1] if '@' in addr else ''


class Cleanup:
    def __init__(self, base, state_dir, osa, accounts, log=None):
        """osa(script, *args, timeout=…) runs AppleScript; accounts() → {account id: {kind, …}} (actions-config)."""
        self.base, self.state_dir, self.osa, self.accounts, self.log = base, state_dir, osa, accounts, log
        self.file = os.path.join(state_dir, 'cleanup.json')
        self.cand_file = os.path.join(state_dir, 'cleanup-candidates.json')
        self.queue = []                  # batches waiting to move/undo
        self.cv = threading.Condition(LOCK)
        self.scanning = False

    # ---------- state ----------
    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            d = {}
        d.setdefault('accounts', [])
        d.setdefault('age_months', 24)
        d.setdefault('all_folders', True)         # own folders and subfolders too (Sent, Trash, receipts … never)
        d.setdefault('include_filed', False)      # mail you filed into your own folders is kept unless you opt in
        d.setdefault('keep', [])           # sender addresses or "@domain"
        d.setdefault('batches', [])
        d.setdefault('scan', None)
        return d

    def _save(self, d):
        tmp = self.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.file)

    def candidates(self):
        try:
            with open(self.cand_file, encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {'groups': [], 'at': None}

    def _still_candidate(self, g, d, prot_senders=frozenset(), prot_mids=frozenset()):
        """The stored scan may be older than today's rules: apply the CURRENT ones again before anything is shown or
        moved – keep list, protected senders, authority / professional domains, keep-worthy subjects (the group's
        example subjects) and mail filed into your own folders. Returns the mails that may still go."""
        keep = set(d['keep'])
        if g['sender'] in keep or ('@' + g['domain']) in keep or g['sender'] in prot_senders:
            return []
        if KEEP_DOMAIN.search(g['domain'] or '') or PRO_DOMAIN.search(g['domain'] or '') or local_keep(g['domain'], self.state_dir):
            return []
        if any(KEEP_SUBJECT.search(x or '') for x in g.get('examples', [])):
            return []
        moved = {mid for b in d['batches'] if b.get('status') == 'done' for mid in b.get('ids', [])}
        out = []
        for m in g['ids']:
            folder = m.get('folder') or ''
            filed = folder.upper() != 'INBOX' and not FOLDER_RE.match(folder.split('/')[-1])
            if m['id'] in moved or m['id'] in prot_mids or (filed and not d.get('include_filed')):
                continue
            out.append(m)
        return out

    def status(self):
        with LOCK:
            d = self.load()
        c = self.candidates()
        prot_senders, prot_mids = self._protected()
        groups = []
        for g in c.get('groups', []):
            ids = self._still_candidate(g, d, prot_senders, prot_mids)
            if ids:
                groups.append({**{k: v for k, v in g.items() if k != 'ids'}, 'count': len(ids),
                               'size': sum(m.get('size', 0) for m in ids)})
        groups.sort(key=lambda g: -g['count'])
        return {'settings': {'accounts': d['accounts'], 'age_months': d['age_months'], 'keep': d['keep'], 'all_folders': d['all_folders'],
                             'include_filed': d.get('include_filed', False)},
                'scan': d['scan'], 'scanning': self.scanning, 'groups': groups[:300],
                'total': sum(g['count'] for g in groups), 'size': sum(g['size'] for g in groups),
                'batches': [{k: v for k, v in b.items() if k not in ('ids', 'items')} for b in d['batches'][-20:]][::-1],
                'folder': FOLDER, 'ages': list(AGES)}

    # ---------- what may never be cleaned up ----------
    def _protected(self):
        def j(name, default):
            try:
                with open(os.path.join(self.state_dir, name), encoding='utf-8') as f:
                    return json.load(f)
            except (OSError, ValueError):
                return default
        senders, mids = set(), set()
        for doc in (j('documents.json', {}).get('documents') or {}).values():
            if doc.get('from'):
                senders.add(_addr(doc['from']))
            mids.add(doc.get('message_id'))
        pj = j('projects.json', {})
        for p in (pj.get('projects') if isinstance(pj, dict) else pj) or []:
            for s in p.get('senders') or []:
                senders.add(str(s).lower())
            for it in p.get('items') or []:
                if it.get('message_id'):
                    mids.add(it['message_id'])
        try:
            with open(os.path.join(self.base, 'contacts.md'), encoding='utf-8') as f:
                senders |= {a.lower() for a in re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', f.read())}
        except OSError:
            pass
        for p in glob.glob(os.path.join(self.base, 'knowledge', 'entries', '*.md')):
            try:
                with open(p, encoding='utf-8') as f:
                    mids |= set(re.findall(r'"ref":\s*"([^"]+)"', f.read()))
            except OSError:
                pass
        return senders, mids

    def _doc_folders(self, acc):
        try:
            with open(os.path.join(self.state_dir, 'documents.json'), encoding='utf-8') as f:
                docs = (json.load(f).get('documents') or {}).values()
            return {x.get('mailbox') for x in docs if x.get('account') == acc and x.get('mailbox')}
        except (OSError, ValueError):
            return set()

    # ---------- scan ----------
    def scan(self):
        with LOCK:
            if self.scanning:
                return 'already scanning'
            self.scanning = True
            d = self.load()
        try:
            accs, age = [a for a in d['accounts'] if a in self.accounts()], int(d['age_months'])
            days = int(age * 30.44)
            keep, (prot_senders, prot_mids) = set(d['keep']), self._protected()
            groups, folders_seen, errors, stats = {}, 0, [], []
            sent_known = {}
            for acc in accs:
                try:
                    wrote = {a.strip().lower() for a in self.osa(SENT_SCRIPT, acc, 5 * 365, timeout=600).splitlines() if '@' in a}
                except Exception as e:
                    wrote = set()
                    errors.append('%s Sent: %s' % (acc, str(e)[:120]))
                sent_known[acc] = len(wrote)
                try:
                    paths = [p.strip() for p in self.osa(FOLDERS_SCRIPT, acc, timeout=120).splitlines() if p.strip()]
                except Exception as e:
                    errors.append('%s folders: %s' % (acc, str(e)[:120]))
                    continue
                doc_folders = self._doc_folders(acc)
                if d.get('all_folders'):        # every folder except Sent/Drafts/Trash/Junk/…, receipt folders and Cleanup
                    paths = [p for p in paths if not any(NEVER_RE.match(x) for x in p.split('/')) and p not in doc_folders]
                else:
                    paths = [p for p in paths if FOLDER_RE.match(p.split('/')[-1])]
                paths = paths or ['INBOX']
                if not any(p.upper() == 'INBOX' for p in paths):
                    paths.insert(0, 'INBOX')
                for path in paths:
                    try:
                        out = self.osa(LIST_SCRIPT, acc, path, days, timeout=900)
                    except Exception as e:
                        errors.append('%s/%s: %s' % (acc, path, str(e)[:120]))
                        continue
                    folders_seen += 1
                    # a folder you named yourself (not Inbox/Archive/notifications): filing it there says it matters
                    filed = path.upper() != 'INBOX' and not FOLDER_RE.match(path.split('/')[-1])
                    fs = {'account': acc, 'folder': path, 'old': 0, 'candidates': 0, 'kept': {}}
                    stats.append(fs)
                    for rec in out.split(RS):
                        f = rec.split(US)
                        if len(f) < 6 or not f[0].strip():
                            continue
                        mid, sender, subject, date, replied, size = f[0].strip(), f[1], f[2], f[3], f[4], f[5]
                        a = _addr(sender)
                        dom = _domain(a)
                        fs['old'] += 1
                        why = ('replied' if replied == '1' else 'no sender' if not a else 'you wrote to them' if a in wrote
                               else 'contact, receipt or project sender' if a in prot_senders
                               else 'keep list' if a in keep or ('@' + dom) in keep else 'project or knowledge mail' if mid in prot_mids
                               else 'authority, bank or insurer' if KEEP_DOMAIN.search(dom) or local_keep(dom, self.state_dir)
                               else 'lawyer, accountant or insurer' if PRO_DOMAIN.search(dom)
                               else 'you filed it in your own folder' if filed and not d.get('include_filed')
                               else 'subject worth keeping' if KEEP_SUBJECT.search(subject or '') else None)
                        if why:
                            fs['kept'][why] = fs['kept'].get(why, 0) + 1
                            continue
                        fs['candidates'] += 1
                        g = groups.setdefault((acc, a), {'account': acc, 'sender': a, 'name': _name(sender), 'domain': dom,
                                                         'ids': [], 'examples': [], 'oldest': date, 'newest': date,
                                                         'folders': []})
                        g['ids'].append({'id': mid, 'folder': path, 'size': int(size or 0) if str(size).isdigit() else 0})
                        if len(g['examples']) < 3 and subject and subject not in g['examples']:
                            g['examples'].append(subject[:120])
                        if path not in g['folders']:
                            g['folders'].append(path)
                        dk = tuple(int(x) for x in date.split('-'))
                        if dk < tuple(int(x) for x in g['oldest'].split('-')):
                            g['oldest'] = date
                        if dk > tuple(int(x) for x in g['newest'].split('-')):
                            g['newest'] = date
            noreply = re.compile(r'no-?reply|notifications?|mailer|news(letter)?|info@|marketing|updates?@|hello@', re.I)
            out = []
            for g in groups.values():
                g['kind'] = 'automated' if noreply.search(g['sender']) else 'other'
                g['key'] = g['account'] + '|' + g['sender']
                out.append(g)
            tmp = self.cand_file + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({'at': _iso(), 'groups': out}, f, ensure_ascii=False)
            os.replace(tmp, self.cand_file)
            with LOCK:
                d = self.load()
                d['scan'] = {'at': _iso(), 'accounts': accs, 'age_months': age, 'folders': folders_seen,
                             'mails': sum(len(g['ids']) for g in out), 'errors': errors[:10], 'folders_detail': stats,
                             'sent_known': sent_known}
                self._save(d)
            return 'scanned'
        finally:
            with LOCK:
                self.scanning = False

    # ---------- moving (background, one batch at a time) ----------
    def _items_for(self, keys):
        c = self.candidates()
        with LOCK:
            d = self.load()
        # the scan may be days old: today's rules and protections decide what may still move
        prot_senders, prot_mids = self._protected()
        items = []
        for g in c.get('groups', []):
            if g['key'] in keys:
                items += [{'account': g['account'], 'id': m['id'], 'folder': m['folder']} for m in self._still_candidate(g, d, prot_senders, prot_mids)]
        return items

    def run(self, log=None, every=60):
        """Worker thread: moves/undoes queued batches; weekly scan at night."""
        last_scan_day = None
        while True:
            try:
                now = _now()
                if now.weekday() == SCAN_AT[0] and now.strftime('%H:%M') >= SCAN_AT[1] and now.hour < 6 and last_scan_day != now.date():
                    last_scan_day = now.date()
                    if self.load()['accounts']:
                        self.scan()
                with LOCK:
                    bid = self.queue.pop(0) if self.queue else None
                    if not bid:
                        self.cv.wait(timeout=every)
                if bid:
                    self._do_batch(bid)
            except Exception as e:
                if self.log:
                    self.log.write('%s cleanup: %s\n' % (_iso(), str(e)[:300]))
                time.sleep(5)

    def _do_batch(self, bid):
        with LOCK:
            d = self.load()
            b = next((x for x in d['batches'] if x['id'] == bid), None)
            if not b:
                return
            b['status'] = 'running'
            self._save(d)
        undo = b['kind'] == 'undo'
        by = {}
        for it in b['items']:
            src, dst = (FOLDER, it['folder']) if undo else (it['folder'], FOLDER)
            by.setdefault((it['account'], src, dst), []).append(it['id'])
        n, err = 0, None
        for (acc, src, dst), ids in by.items():
            for i in range(0, len(ids), 40):
                try:
                    n += int(self.osa(MOVE_SCRIPT, acc, src, dst, *ids[i:i + 40], timeout=600) or 0)
                except Exception as e:
                    err = str(e)[:200]
                with LOCK:
                    d = self.load()
                    x = next((y for y in d['batches'] if y['id'] == bid), None)
                    if x:
                        x['moved'] = n
                        self._save(d)
        with LOCK:
            d = self.load()
            x = next((y for y in d['batches'] if y['id'] == bid), None)
            if x:
                x.update(status='done' if not err else ('done' if n else 'failed'), ended=_iso(), moved=n, error=err)
                if undo:
                    orig = next((y for y in d['batches'] if y['id'] == x.get('undo_of')), None)
                    if orig:
                        orig['status'] = 'undone'
                self._save(d)

    # ---------- dashboard actions ----------
    def action(self, action, p):
        if action == 'cleanup_scan':
            with LOCK:
                if self.scanning:
                    return 'already scanning'
                if not self.load()['accounts']:
                    raise Bad('choose the mailboxes in Settings first')
            threading.Thread(target=self.scan, daemon=True).start()
            return 'scan started'
        with LOCK:
            d = self.load()
            if action == 'cleanup_settings':
                if 'accounts' in p:
                    accs = p['accounts']
                    if not isinstance(accs, list) or not all(isinstance(a, str) and a in self.accounts() for a in accs):
                        raise Bad('unknown mailbox')
                    d['accounts'] = accs
                if 'all_folders' in p:
                    d['all_folders'] = bool(p['all_folders'])
                if 'include_filed' in p:
                    d['include_filed'] = bool(p['include_filed'])
                if 'age_months' in p:
                    if p['age_months'] not in AGES:
                        raise Bad('age must be 12, 24 or 36 months')
                    d['age_months'] = p['age_months']
                self._save(d)
                return 'saved'
            if action in ('cleanup_keep', 'cleanup_unkeep'):
                k = str(p.get('sender') or '').strip().lower()[:200]
                if not re.match(r'^@?[\w.+-]*@?[\w-]+\.[\w.-]+$', k):
                    raise Bad('bad sender')
                if action == 'cleanup_keep' and k not in d['keep']:
                    d['keep'].append(k)
                elif action == 'cleanup_unkeep' and k in d['keep']:
                    d['keep'].remove(k)
                self._save(d)
                return 'saved'
        if action == 'cleanup_move':
            keys = p.get('keys')
            if not isinstance(keys, list) or not keys or not all(isinstance(k, str) and '|' in k and len(k) < 400 for k in keys):
                raise Bad('nothing chosen')
            items = self._items_for(set(keys))
            if not items:
                raise Bad('nothing left to move')
            with LOCK:
                d = self.load()
                if any(b['status'] in ('queued', 'running') for b in d['batches']):
                    raise Bad('a move is still running – wait for it to finish')
                bid = 'b' + _now().strftime('%Y%m%d%H%M%S')
                names = sorted({k.split('|', 1)[1] for k in keys})
                d['batches'].append({'id': bid, 'kind': 'move', 'status': 'queued', 'created': _iso(), 'count': len(items),
                                     'moved': 0, 'label': names[0] + (' +%d more' % (len(names) - 1) if len(names) > 1 else ''),
                                     'ids': [i['id'] for i in items], 'items': items})
                d['batches'] = d['batches'][-100:]
                self._save(d)
                self.queue.append(bid)
                self.cv.notify_all()
            return bid
        if action == 'cleanup_undo':
            with LOCK:
                d = self.load()
                b = next((x for x in d['batches'] if x['id'] == p.get('id')), None)
                if not b or b['kind'] != 'move' or b['status'] != 'done':
                    raise Bad('this batch can\'t be undone')
                if any(x['status'] in ('queued', 'running') for x in d['batches']):
                    raise Bad('a move is still running – wait for it to finish')
                bid = 'u' + _now().strftime('%Y%m%d%H%M%S')
                d['batches'].append({'id': bid, 'kind': 'undo', 'undo_of': b['id'], 'status': 'queued', 'created': _iso(),
                                     'count': b['count'], 'moved': 0, 'label': 'Undo: ' + b['label'], 'ids': [],
                                     'items': b['items']})
                self._save(d)
                self.queue.append(bid)
                self.cv.notify_all()
            return bid
        raise Bad('unknown action')
