"""Axella document register: receipts, invoices and bills per vendor (state/documents.json).

Sources (all read by a thread in axella-actions.py, nothing else writes the register):
  - folder watch: every 10 min the receipt folders in Mail (actions-config.json "document_folders") are listed;
    new messages get a skeleton entry (sender, subject, date) marked "needs_details" – also mail you move there by hand
  - digest sidecars: any item with a "document" object, and a top-level "documents" list that the runs use to
    complete entries marked needs_details (AXELLA.md "Receipts and invoices")
  - state/documents-import*.json: one-off backfill files written by the import run; renamed to *.done after merging
Corrections from the dashboard are kept ("manual" fields are never overwritten) and teach Axella per vendor:
vendor_rules[vendor_key] = {"project": …, "kind": …} is used to pre-fill new documents of that vendor.

Register shape:
  {"documents": {<message_id>: {"message_id", "account", "mailbox", "date", "vendor", "vendor_key", "kind",
                 "amount", "currency", "due", "project", "subject", "from", "attachments", "deep_link",
                 "source", "added", "manual": [field, …]}},
   "vendor_rules": {<vendor_key>: {"project": id|null, "kind": str|null, "count": n, "updated": iso}}}
"""
import datetime
import glob
import json
import os
import re
import sys
import threading
import time

LOCK = threading.Lock()
KINDS = ('receipt', 'invoice', 'bill', 'reminder', 'credit', 'order', 'other')
FIELDS = ('account', 'mailbox', 'date', 'vendor', 'kind', 'amount', 'currency', 'due', 'project', 'subject', 'from',
          'attachments', 'deep_link', 'paid', 'needs_details')

# AppleScript: id|sender|subject|yyyy-m-d h:m for every message of one folder (argv: account, folder path a/b)
FOLDER_SCRIPT = '''
on run argv
  set accName to item 1 of argv
  set AppleScript's text item delimiters to "/"
  set parts to text items of (item 2 of argv)
  set AppleScript's text item delimiters to ""
  set out to ""
  tell application "Mail"
    set mb to mailbox (item 1 of parts) of account accName
    if (count of parts) > 1 then
      repeat with i from 2 to (count of parts)
        set mb to mailbox (item i of parts) of mb
      end repeat
    end if
    repeat with m in (every message of mb)
      set d to date received of m
      set ds to ((year of d) as text) & "-" & ((month of d as integer) as text) & "-" & ((day of d) as text) & " " & ((hours of d) as text) & ":" & ((minutes of d) as text)
      set out to out & (message id of m) & (ASCII character 31) & (sender of m) & (ASCII character 31) & (subject of m) & (ASCII character 31) & ds & (ASCII character 30)
    end repeat
  end tell
  return out
end run
'''


class Bad(Exception):
    pass


def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def vendor_key(name):
    return re.sub(r'[^a-z0-9]+', '', (name or '').lower())[:60]


def _num(v):
    if v is None or v == '':
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return round(f, 2) if f == f and abs(f) < 1e12 else None   # no NaN / infinity
    s = str(v).strip().replace(' ', '').replace(' ', '')
    # "1.234,56" (Danish) or "1,234.56" (English)
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.') if s.rfind(',') > s.rfind('.') else s.replace(',', '')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        f = round(float(re.sub(r'[^0-9.\-]', '', s)), 2)
    except ValueError:
        return None
    return f if f == f and abs(f) < 1e12 else None


class Documents:
    def __init__(self, state_dir, digests_dir):
        self.state_dir = state_dir
        self.digests_dir = digests_dir
        self.file = os.path.join(state_dir, 'documents.json')
        self.seen_file = os.path.join(state_dir, 'documents-seen.json')
        self.lock = LOCK

    def save(self, d):
        self._save(d)

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            d = {}
        d.setdefault('documents', {})
        d.setdefault('vendor_rules', {})
        return d

    def _save(self, d):
        tmp = self.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)

    # ---------- merge ----------
    def _upsert(self, d, doc, source):
        mid = (doc.get('message_id') or '').strip()
        if not mid:
            return False
        cur = d['documents'].get(mid, {'message_id': mid, 'added': _now(), 'manual': []})
        manual = set(cur.get('manual', []))
        for k in FIELDS:
            if k in doc and doc[k] not in (None, '') and k not in manual:
                cur[k] = doc[k]
        cur['amount'] = _num(cur.get('amount'))
        if cur.get('kind') not in KINDS:
            cur['kind'] = 'other' if cur.get('kind') else 'receipt'
        cur['vendor'] = (cur.get('vendor') or cur.get('from') or 'Unknown').strip()[:80]
        cur['vendor_key'] = vendor_key(cur['vendor'])
        rule = d['vendor_rules'].get(cur['vendor_key'])
        if rule and 'project' not in manual and rule.get('project') is not None and not doc.get('project'):
            cur['project'] = rule['project']          # learned from earlier corrections
        cur['source'] = cur.get('source') or source
        d['documents'][mid] = cur
        return True

    def ingest_once(self):
        """Merge new digest sidecars and import files. Returns number of documents added/updated."""
        with LOCK:
            d = self.load()
            try:
                with open(self.seen_file, encoding='utf-8') as f:
                    seen = set(json.load(f))
            except (FileNotFoundError, json.JSONDecodeError):
                seen = set()
            n = 0
            for path in sorted(glob.glob(os.path.join(self.digests_dir, '*.json'))):
                name = os.path.basename(path)
                if name in seen:
                    continue
                try:
                    with open(path, encoding='utf-8') as f:
                        items = json.load(f).get('items', [])
                except (OSError, json.JSONDecodeError):
                    continue                              # still being written – next round
                try:
                    with open(path, encoding='utf-8') as f:
                        extra = json.load(f).get('documents') or []
                except (OSError, json.JSONDecodeError):
                    extra = []
                for doc in extra:
                    if isinstance(doc, dict):
                        n += self._upsert(d, {**doc, 'needs_details': False}, 'digest:' + name)
                for it in items:
                    doc = it.get('document')
                    if isinstance(doc, dict):
                        doc = {**doc, 'message_id': it.get('message_id') or doc.get('message_id'),
                               'account': it.get('account'), 'deep_link': it.get('deep_link'),
                               'subject': it.get('subject') or doc.get('subject'),
                               'from': (it.get('from') or {}).get('address') or doc.get('from')}
                        n += self._upsert(d, {**doc, 'needs_details': False}, 'digest:' + name)
                seen.add(name)
            for path in sorted(glob.glob(os.path.join(self.state_dir, 'documents-import*.json'))):
                try:
                    with open(path, encoding='utf-8') as f:
                        docs = json.load(f)
                    docs = docs.get('documents', docs) if isinstance(docs, dict) else docs
                    for doc in docs:
                        if isinstance(doc, dict):
                            n += self._upsert(d, {**doc, 'needs_details': False}, 'import')
                    os.replace(path, path[:-5] + '.done-' + datetime.datetime.now().strftime('%Y%m%d%H%M') + '.json.txt')
                except (OSError, json.JSONDecodeError, TypeError):
                    continue
            if n:
                self._save(d)
            with open(self.seen_file, 'w', encoding='utf-8') as f:
                json.dump(sorted(seen), f)
            return n

    def scan_folders(self, osa, folders):
        """List the watched Mail folders; add skeleton entries for messages not in the register yet."""
        n = 0
        for account, folder in folders:
            out = osa(FOLDER_SCRIPT, account, folder, timeout=120)
            rows = [r.split('\x1f') for r in out.split('\x1e') if r.strip()]
            with LOCK:
                d = self.load()
                for r in rows:
                    if len(r) < 4:
                        continue
                    mid, sender, subject, ds = (x.strip() for x in r[:4])
                    if not mid:
                        continue
                    cur = d['documents'].get(mid)
                    if cur:
                        if cur.get('mailbox') != folder and 'mailbox' not in cur.get('manual', []):
                            cur['mailbox'] = folder           # moved between watched folders
                            n += 1
                        continue
                    try:
                        y, mo, rest = ds.split('-', 2)
                        dd, hm = rest.split(' ')
                        h, mi = hm.split(':')
                        date = f'{int(y):04d}-{int(mo):02d}-{int(dd):02d}T{int(h):02d}:{int(mi):02d}'
                    except ValueError:
                        date = None
                    name = re.sub(r'\s*<[^>]+>\s*$', '', sender).strip().strip('"') or sender
                    addr = (re.search(r'<([^>]+)>', sender) or [None, sender])[1]
                    n += self._upsert(d, {'message_id': mid, 'account': account, 'mailbox': folder, 'date': date,
                                          'vendor': name, 'subject': subject, 'from': addr, 'needs_details': True,
                                          'deep_link': 'message://%3C' + mid + '%3E'}, 'folder:' + folder)
                if n:
                    self._save(d)
        return n

    def run(self, osa=None, folders=(), log=sys.stderr, every=60, scan_every=600):
        last_scan = 0
        while True:
            try:
                n = self.ingest_once()
                if osa and folders and time.time() - last_scan > scan_every:
                    last_scan = time.time()
                    n += self.scan_folders(osa, folders)
                if n:
                    log.write(f'{_now()} documents: merged {n}\n')
            except Exception as e:
                log.write(f'documents: {str(e)[:200]}\n')
            time.sleep(every)

    # ---------- dashboard ----------
    def action(self, action, p):
        with LOCK:
            d = self.load()
            if action == 'document_set':
                mid = (p.get('message_id') or '').strip()
                doc = d['documents'].get(mid)
                if not doc:
                    raise Bad('document not found')
                changed = []
                for k in ('vendor', 'kind', 'project', 'currency', 'due', 'paid'):
                    if k in p:
                        v = p[k]
                        if k == 'kind' and v not in KINDS:
                            raise Bad('bad kind')
                        if isinstance(v, str):
                            v = v.strip()[:80] or None
                        doc[k] = v
                        changed.append(k)
                if 'amount' in p:
                    amt = _num(p['amount'])
                    if amt is None and p['amount'] not in (None, ''):
                        raise Bad('the amount is not a number – type e.g. 650,00 or 1.234,56')
                    doc['amount'] = amt
                    changed.append('amount')
                if 'ctx' in p:                       # work / private – the owner's call (None = decide automatically)
                    if p['ctx'] not in ('work', 'private', None):
                        raise Bad('bad ctx')
                    doc['ctx'] = p['ctx']
                    changed.append('ctx')
                doc['vendor_key'] = vendor_key(doc.get('vendor'))
                doc['manual'] = sorted(set(doc.get('manual', [])) | set(changed))
                if 'project' in changed or 'kind' in changed or 'ctx' in changed:
                    # learn: this vendor goes to this project / is this kind
                    r = d['vendor_rules'].setdefault(doc['vendor_key'], {'project': None, 'kind': None, 'count': 0})
                    if 'project' in changed:
                        r['project'] = doc.get('project')
                    if 'kind' in changed:
                        r['kind'] = doc.get('kind')
                    if 'ctx' in changed and p.get('apply_to_vendor'):
                        r['ctx'] = doc.get('ctx')
                    r['count'] = r.get('count', 0) + 1
                    r['updated'] = _now()
                    if p.get('apply_to_vendor'):
                        for other in d['documents'].values():
                            if other['vendor_key'] != doc['vendor_key'] or other is doc:
                                continue
                            if 'project' in changed and 'project' not in other.get('manual', []):
                                other['project'] = doc.get('project')
                            if 'ctx' in changed:
                                other.pop('ctx', None)       # the vendor rule decides for the others
                self._save(d)
                return 'saved'
            if action == 'document_hide':
                mid = (p.get('message_id') or '').strip()
                if mid in d['documents']:
                    d['documents'][mid]['hidden'] = bool(p.get('hidden', True))
                    self._save(d)
                return 'saved'
            raise Bad('unknown action')
