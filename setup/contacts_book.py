"""Contacts page and the New message picker: your address book from macOS Contacts on the Mac mini, plus people you
mail with. Names, phone numbers, e-mail addresses and birthdays only.

- Read with AppleScript (Contacts app), kept in state/contacts-book.json (chmod 600, on the scheduler's SECRETS list –
  no Claude run reads it) and refreshed in the background when older than 6 hours.
- Private contacts (Settings → Private contacts) are marked, so the dashboard offers no AI for them; Hidden ones are
  left out completely.
- Favourites are the VIPs (contacts.md), matched by name – the same list the digests and the call agent use.
Nothing here sends anything: the dashboard opens Mail (the composer), Messages, WhatsApp or Signal on your own device.
"""
import json
import os
import re
import threading
import time

BOOK_SCRIPT = '''
on run
  set US to (ASCII character 31)
  set GS to (ASCII character 29)
  set FS to (ASCII character 28)
  set RS to (ASCII character 30)
  set out to ""
  tell application "Contacts"
    repeat with p in people
      set nm to name of p
      set fn to ""
      set ln to ""
      set org to ""
      try
        set fn to first name of p
      end try
      try
        set ln to last name of p
      end try
      try
        set org to organization of p
      end try
      if fn is missing value then set fn to ""
      if ln is missing value then set ln to ""
      if org is missing value then set org to ""
      set ph to ""
      repeat with x in phones of p
        set lb to ""
        try
          set lb to label of x
        end try
        if lb is missing value then set lb to ""
        set ph to ph & lb & FS & (value of x) & GS
      end repeat
      set em to ""
      repeat with x in emails of p
        set lb to ""
        try
          set lb to label of x
        end try
        if lb is missing value then set lb to ""
        set em to em & lb & FS & (value of x) & GS
      end repeat
      set bd to ""
      try
        set d to birth date of p
        if d is not missing value then set bd to ((year of d) as text) & "-" & ((month of d as integer) as text) & "-" & ((day of d) as text)
      end try
      set out to out & nm & US & ph & US & em & US & (id of p) & US & fn & US & ln & US & org & US & bd & RS
    end repeat
  end tell
  return out
end run
'''

MAX_AGE = 6 * 3600
MAIL_RE = re.compile(r'^[A-Za-z0-9._%+\'-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$')


def phone(raw):
    """'+' + digits; a Danish number without +45 gets it, 00… becomes +… (as for the call agent). None if not a number."""
    num = re.sub(r'[^\d+]', '', str(raw or ''))
    if len(num) == 8 and num.isdigit():
        num = '+45' + num
    elif num.startswith('00'):
        num = '+' + num[2:]
    d = re.sub(r'\D', '', num)
    return '+' + d if num.startswith('+') and 6 <= len(d) <= 15 else None


LABELS = ('mobile', 'iphone', 'home', 'work', 'main', 'other')


def label(raw):
    """Contacts' own labels ("_$!<Mobile>!$_") as plain words; anything unknown is "other"."""
    t = re.sub(r'^_\$!<(.*)>!\$_$', r'\1', str(raw or '')).strip().lower()
    return t if t in LABELS else ('other' if t else '')


def _split(field):
    """'label<FS>value<GS>…' (new script) or 'value<GS>…' (older cache) → [(label, value)]."""
    out = []
    for x in str(field or '').split('\x1d'):
        if not x.strip():
            continue
        lb, sep, val = x.partition('\x1c')
        out.append((label(lb), val) if sep else ('', lb))
    return out


def parse(out):
    people = []
    for row in str(out or '').split('\x1e'):
        parts = row.split('\x1f')
        if len(parts) < 3:
            continue
        name = ' '.join(parts[0].split())[:80]
        phones, emails, pl, el = [], [], [], []
        for lb, x in _split(parts[1]):
            p = phone(x)
            if p and p not in phones:
                phones.append(p); pl.append(lb)
        for lb, x in _split(parts[2]):
            e = x.strip().lower()
            if MAIL_RE.match(e) and e not in emails:
                emails.append(e); el.append(lb)
        if name and (phones or emails):
            p = {'name': name, 'phones': phones[:6], 'emails': emails[:6]}
            if len(parts) >= 7:
                p.update(id=parts[3].strip()[:120], first=parts[4].strip()[:60], last=parts[5].strip()[:60],
                         company=parts[6].strip()[:80], phone_labels=pl[:6], email_labels=el[:6])
            if len(parts) >= 8:
                import birthdays as _bd
                b = _bd.norm(parts[7])
                if b:
                    p['birthday'] = b
            people.append(p)
    return people


class Book:
    def __init__(self, state_dir, osa, privacy, vips, correspondents, log=None):
        self.file = os.path.join(state_dir, 'contacts-book.json')
        self.osa, self.privacy, self.vips, self.correspondents, self.log = osa, privacy, vips, correspondents, log
        self.lock = threading.Lock()
        self.refreshing = False

    def _load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def refresh(self):
        """Read Contacts now (can take a minute on a big address book). Keeps the old list if Contacts gives nothing."""
        try:
            people = parse(self.osa(BOOK_SCRIPT, timeout=180))
            if people:
                tmp = self.file + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump({'at': time.time(), 'people': people}, f, ensure_ascii=False)
                os.chmod(tmp, 0o600)
                os.replace(tmp, self.file)
        except Exception as e:
            if self.log:
                self.log.write('contacts book: %s\n' % str(e)[:200])
        finally:
            self.refreshing = False

    def _kick(self, d):
        if self.refreshing or time.time() - (d.get('at') or 0) < MAX_AGE:
            return
        with self.lock:
            if self.refreshing:
                return
            self.refreshing = True
        threading.Thread(target=self.refresh, daemon=True).start()

    def _level(self, ids):
        """'hidden' / 'private' / 'normal' for a person, from Settings → Private contacts (strictest of their ids)."""
        if not self.privacy:
            return 'normal'
        try:
            d = self.privacy.load()
            if d.get('broken'):
                return 'private'
            import privacy as _p
            levels = set()
            for i in ids:
                c = self.privacy.contact(i)
                if c:
                    levels.update(_p.contact_level(c, ch, d['defaults']) for ch in _p.CHANNELS)
            return 'hidden' if 'hidden' in levels else 'private' if 'private' in levels else 'normal'
        except Exception:
            return 'private'

    def overview(self, refresh=False):
        d = self._load()
        if refresh:
            d = dict(d, at=0)
        self._kick(d)
        people = [dict(p) for p in d.get('people') or []]
        # people you mail with who aren't in Contacts – an address whose name matches someone in Contacts goes on that
        # card ("from your mail", with Add to this contact) instead of the same person twice in the list
        known = {e for p in people for e in p['emails']}
        by_name = {}
        for p in people:
            if p.get('id'):
                by_name.setdefault(' '.join(str(p.get('name') or '').lower().split()), []).append(p)
        for c in self.correspondents() or []:
            a = str(c.get('address') or '').lower()
            if not MAIL_RE.match(a) or a in known:
                continue
            nm = (c.get('name') or a)[:80]
            same = by_name.get(' '.join(nm.lower().split())) or []
            if len(same) == 1:
                same[0].setdefault('mail_only', []).append(a)
            else:
                people.append({'name': nm, 'phones': [], 'emails': [a], 'source': 'mail'})
            known.add(a)
        vip_names = {str(v.get('name') or '').lower() for v in self.vips() or []}
        out = []
        for p in people:
            if p.get('mail_only'):
                p['mail_only'] = [a for a in p['mail_only'] if self._level([a]) != 'hidden'][:6]
            lvl = self._level(p['phones'] + p['emails'] + p.get('mail_only', []))
            if lvl == 'hidden':
                continue
            p['private'] = lvl == 'private'
            p['vip'] = p['name'].lower() in vip_names
            out.append(p)
        out.sort(key=lambda p: p['name'].lower())
        return {'people': out, 'at': d.get('at'), 'refreshing': self.refreshing, 'from_contacts': bool(d.get('people'))}


# ---------- editing (owner only, checked in axella-actions.py): name, company, phones, e-mails ----------
# All values reach AppleScript as argv, never inside the script text. Phones/e-mails as one string:
# "label<FS>value<GS>label<FS>value…".
_AS_SET = '''
on splitText(t, d)
  set AppleScript's text item delimiters to d
  set parts to text items of t
  set AppleScript's text item delimiters to ""
  return parts
end splitText
on setBirthday(p, s)
  -- s: "keep" (leave it), "" (no birthday) or "Y-M-D" (year 1604 = no year, as Contacts keeps it)
  if s is "keep" then return
  tell application "Contacts"
    if s is "" then
      try
        set birth date of p to missing value
      on error
        try
          delete birth date of p
        end try
      end try
    else
      set kv to my splitText(s, "-")
      set d to current date
      set day of d to 1
      set year of d to ((item 1 of kv) as integer)
      set month of d to ((item 2 of kv) as integer)
      set day of d to ((item 3 of kv) as integer)
      set time of d to 12 * hours
      set birth date of p to d
    end if
  end tell
end setBirthday
on fill(p, phoneList, mailList)
  set GS to (ASCII character 29)
  set FS to (ASCII character 28)
  tell application "Contacts"
    if phoneList is not "" then
      repeat with x in my splitText(phoneList, GS)
        if (x as text) is not "" then
          set kv to my splitText(x as text, FS)
          make new phone at end of phones of p with properties {label:(item 1 of kv), value:(item 2 of kv)}
        end if
      end repeat
    end if
    if mailList is not "" then
      repeat with x in my splitText(mailList, GS)
        if (x as text) is not "" then
          set kv to my splitText(x as text, FS)
          make new email at end of emails of p with properties {label:(item 1 of kv), value:(item 2 of kv)}
        end if
      end repeat
    end if
  end tell
end fill
'''

ADD_SCRIPT = _AS_SET + '''
on run argv
  tell application "Contacts"
    set p to make new person with properties {first name:(item 1 of argv), last name:(item 2 of argv), organization:(item 3 of argv)}
  end tell
  my fill(p, item 4 of argv, item 5 of argv)
  my setBirthday(p, item 6 of argv)
  tell application "Contacts"
    save
    return id of p
  end tell
end run
'''

# An update changes only what you changed in the form: names when they differ, phones/e-mails you removed are deleted
# (matched on digits / lower case), new ones are added – anything on the card Axella doesn't know about stays.
# argv: id, first, last, company ("\x1f" = leave), remove-phones (digits, GS-separated), remove-mails, add-phones,
# add-mails (label<FS>value<GS>…), birthday ("keep" = leave)
UPDATE_SCRIPT = _AS_SET + '''
on digitsOf(t)
  set out to ""
  repeat with ch in (characters of (t as text))
    if "0123456789" contains (ch as text) then set out to out & (ch as text)
  end repeat
  return out
end digitsOf
on inList(v, lst)
  repeat with x in lst
    if (x as text) is v then return true
  end repeat
  return false
end inList
on run argv
  set GS to (ASCII character 29)
  set KEEP to (ASCII character 31)
  set rmPhones to my splitText(item 5 of argv, GS)
  set rmMails to my splitText(item 6 of argv, GS)
  tell application "Contacts"
    set p to person id (item 1 of argv)
    if (item 2 of argv) is not KEEP then set first name of p to (item 2 of argv)
    if (item 3 of argv) is not KEEP then set last name of p to (item 3 of argv)
    if (item 4 of argv) is not KEEP then set organization of p to (item 4 of argv)
    if (item 5 of argv) is not "" then
      repeat with i from (count of phones of p) to 1 by -1
        set d to my digitsOf(value of phone i of p)
        if my inList(d, rmPhones) then delete phone i of p
      end repeat
    end if
    if (item 6 of argv) is not "" then
      repeat with i from (count of emails of p) to 1 by -1
        set e to (value of email i of p) as text
        ignoring case
          if my inList(e, rmMails) then delete email i of p
        end ignoring
      end repeat
    end if
  end tell
  my fill(p, item 7 of argv, item 8 of argv)
  my setBirthday(p, item 9 of argv)
  tell application "Contacts"
    save
    return "ok"
  end tell
end run
'''

VCARD_SCRIPT = '''
on run argv
  tell application "Contacts"
    return vcard of (person id (item 1 of argv))
  end tell
end run
'''

DELETE_SCRIPT = '''
on run argv
  tell application "Contacts"
    delete (person id (item 1 of argv))
    save
    return "deleted"
  end tell
end run
'''

ID_RE = re.compile(r'^[A-Za-z0-9:_-]{8,120}$')
NAME_RE = re.compile(r'^[^\x00-\x1f\x7f<>]{0,60}$')


class EditError(Exception):
    pass


def clean_person(p):
    """The editable fields, checked: first/last/company plain text, phones and e-mails with labels."""
    first, last = ' '.join(str(p.get('first') or '').split()), ' '.join(str(p.get('last') or '').split())
    company = ' '.join(str(p.get('company') or '').split())
    if not (first or last or company):
        raise EditError('give a name or a company')
    for v, what in ((first, 'first name'), (last, 'last name'), (company, 'company')):
        if not NAME_RE.match(v) or len(v) > (80 if what == 'company' else 60):
            raise EditError('the %s can only be plain text (max %d)' % (what, 80 if what == 'company' else 60))
    phones, emails = [], []
    for x in (p.get('phones') or [])[:6]:
        n = phone((x or {}).get('value') if isinstance(x, dict) else x)
        if not n:
            raise EditError('%s is not a phone number' % str((x or {}).get('value') if isinstance(x, dict) else x)[:30])
        lb = label((x or {}).get('label') if isinstance(x, dict) else '') or 'mobile'
        if n not in [v for _, v in phones]:
            phones.append((lb, n))
    for x in (p.get('emails') or [])[:6]:
        e = str((x or {}).get('value') if isinstance(x, dict) else x or '').strip().lower()
        if not MAIL_RE.match(e):
            raise EditError('%s is not an e-mail address' % e[:60])
        lb = label((x or {}).get('label') if isinstance(x, dict) else '') or 'home'
        if e not in [v for _, v in emails]:
            emails.append((lb, e))
    # birthday: 'YYYY-MM-DD', '--MM-DD' (no year) or '' (none); not given = leave it as it is in Contacts
    bday = 'keep'
    if 'birthday' in p:
        import birthdays as _bd
        raw = str(p.get('birthday') or '').strip()
        bday = _bd.norm(raw) if raw else ''
        if raw and not bday:
            raise EditError('the birthday must be a real date (day and month, year optional)')
    return {'first': first, 'last': last, 'company': company, 'phones': phones, 'emails': emails, 'birthday': bday}


def _as_bday(b):
    """'YYYY-MM-DD' / '--MM-DD' / '' / 'keep' → what the AppleScript takes (no year = 1604, as Contacts keeps it)."""
    if b in ('', 'keep'):
        return b
    import birthdays as _bd
    y, mo, d = _bd.parts(b)
    return '%d-%d-%d' % (y or 1604, mo, d)


def _pairs(lst):
    return '\x1d'.join('%s\x1c%s' % (lb, v) for lb, v in lst)


def _as_person(pid, c, old=None):
    name = ' '.join(x for x in (c['first'], c['last']) if x) or c['company']
    out = {'id': pid, 'name': name, 'first': c['first'], 'last': c['last'], 'company': c['company'],
           'phones': [v for _, v in c['phones']], 'phone_labels': [lb for lb, _ in c['phones']],
           'emails': [v for _, v in c['emails']], 'email_labels': [lb for lb, _ in c['emails']]}
    b = (old or {}).get('birthday') if c.get('birthday', 'keep') == 'keep' else c.get('birthday')
    if b:
        out['birthday'] = b
    return out


def _patch(book, pid, person):
    """Change the cached list at once (a full re-read of Contacts can take a minute)."""
    with book.lock:
        d = book._load()
        people = [x for x in d.get('people') or [] if x.get('id') != pid]
        if person and (person['phones'] or person['emails']):
            people.append(person)
        d['people'] = people
        tmp = book.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, book.file)


def _update_args(old, c):
    """What changed between the card Axella read (old) and the form (c) – only that is sent to Contacts."""
    keep = '\x1f'                                   # "leave it" (argv can't carry a NUL; names can't hold \x1f)
    first = c['first'] if c['first'] != (old.get('first') or '') else keep
    last = c['last'] if c['last'] != (old.get('last') or '') else keep
    company = c['company'] if c['company'] != (old.get('company') or '') else keep
    op = list(zip(old.get('phone_labels') or [''] * len(old.get('phones') or []), old.get('phones') or []))
    oe = list(zip(old.get('email_labels') or [''] * len(old.get('emails') or []), old.get('emails') or []))
    digits = lambda v: re.sub(r'\D', '', v)
    new_p, new_e = set(c['phones']), set(c['emails'])
    rm_p = [digits(v) for lb, v in op if (lb or 'mobile', v) not in new_p and (lb, v) not in new_p]
    rm_e = [v for lb, v in oe if (lb or 'home', v) not in new_e and (lb, v) not in new_e]
    old_pv, old_ev = {(lb or 'mobile', v) for lb, v in op} | set(op), {(lb or 'home', v) for lb, v in oe} | set(oe)
    add_p = [(lb, v) for lb, v in c['phones'] if (lb, v) not in old_pv]
    add_e = [(lb, v) for lb, v in c['emails'] if (lb, v) not in old_ev]
    # a label change on a kept number: it goes and comes back with the new label
    for lb, v in add_p:
        if digits(v) not in rm_p and any(x == v for _, x in op):
            rm_p.append(digits(v))
    for lb, v in add_e:
        if v not in rm_e and any(x == v for _, x in oe):
            rm_e.append(v)
    return (first, last, company, '\x1d'.join(rm_p), '\x1d'.join(rm_e), _pairs(add_p), _pairs(add_e), _as_bday(c['birthday']))


def edit(book, action, p, backup_dir):
    """contact_add / contact_update / contact_delete / contact_restore. Returns a small result for the log."""
    if action == 'contact_add':
        c = clean_person(p)
        pid = str(book.osa(ADD_SCRIPT, c['first'], c['last'], c['company'], _pairs(c['phones']), _pairs(c['emails']),
                           _as_bday('' if c['birthday'] == 'keep' else c['birthday']), timeout=60)).strip()
        if not ID_RE.match(pid):
            raise EditError('Contacts did not confirm the new contact')
        _patch(book, pid, _as_person(pid, c))
        return {'id': pid, 'name': _as_person(pid, c)['name']}
    if action == 'contact_restore':
        bid = str(p.get('backup') or '')
        if not re.match(r'^\d{8}-\d{6}-[A-Za-z0-9]{1,16}$', bid):
            raise EditError('unknown backup')
        try:
            with open(os.path.join(backup_dir, bid + '.json'), encoding='utf-8') as f:
                b = json.load(f)
        except (OSError, ValueError):
            raise EditError('that backup is gone (kept 90 days)')
        per = b.get('person') or {}
        c = clean_person({'first': per.get('first') or per.get('name'), 'last': per.get('last'), 'company': per.get('company'),
                          'phones': [{'label': lb, 'value': v} for lb, v in zip(per.get('phone_labels') or [''] * 9, per.get('phones') or [])],
                          'emails': [{'label': lb, 'value': v} for lb, v in zip(per.get('email_labels') or [''] * 9, per.get('emails') or [])],
                          'birthday': per.get('birthday') or ''})
        nid = str(book.osa(ADD_SCRIPT, c['first'], c['last'], c['company'], _pairs(c['phones']), _pairs(c['emails']),
                           _as_bday(c['birthday']), timeout=60)).strip()
        if not ID_RE.match(nid):
            raise EditError('Contacts did not confirm the restore')
        _patch(book, nid, _as_person(nid, c))
        return {'id': nid, 'name': _as_person(nid, c)['name'], 'vcard': bid + '.vcf'}
    pid = str(p.get('id') or '')
    if not ID_RE.match(pid):
        raise EditError('unknown contact')
    if action == 'contact_update':
        c = clean_person(p)
        old = next((x for x in book._load().get('people') or [] if x.get('id') == pid), None)
        if old is None:
            raise EditError('Axella has not read this contact yet – Refresh, then try again')
        # a copy of the whole card first (kept 90 days in the backups, like a delete)
        vcard = str(book.osa(VCARD_SCRIPT, pid, timeout=30) or '')
        if 'BEGIN:VCARD' not in vcard:
            raise EditError('could not make a copy of the contact first – nothing was changed')
        os.makedirs(backup_dir, mode=0o700, exist_ok=True)
        bid = time.strftime('%Y%m%d-%H%M%S') + '-edit-' + re.sub(r'[^A-Za-z0-9]', '', pid)[:12]
        with open(os.path.join(backup_dir, bid + '.vcf'), 'w', encoding='utf-8') as f:
            f.write(vcard)
        os.chmod(os.path.join(backup_dir, bid + '.vcf'), 0o600)
        args = _update_args(old, c)
        if str(book.osa(UPDATE_SCRIPT, pid, *args, timeout=60)).strip() != 'ok':
            raise EditError('Contacts did not confirm the change')
        _patch(book, pid, _as_person(pid, c, old))
        return {'id': pid, 'name': _as_person(pid, c)['name']}
    if action == 'contact_delete':
        # a full copy first (the vCard: everything, also what Axella doesn't edit) – the delete only happens once it is saved
        vcard = str(book.osa(VCARD_SCRIPT, pid, timeout=30) or '')
        if 'BEGIN:VCARD' not in vcard:
            raise EditError('could not make a copy of the contact first – nothing was deleted')
        cur = next((x for x in book._load().get('people') or [] if x.get('id') == pid), {})
        os.makedirs(backup_dir, mode=0o700, exist_ok=True)
        os.chmod(backup_dir, 0o700)
        bid = time.strftime('%Y%m%d-%H%M%S') + '-' + re.sub(r'[^A-Za-z0-9]', '', pid)[:16]
        with open(os.path.join(backup_dir, bid + '.vcf'), 'w', encoding='utf-8') as f:
            f.write(vcard)
        with open(os.path.join(backup_dir, bid + '.json'), 'w', encoding='utf-8') as f:
            json.dump({'id': pid, 'deleted': time.time(), 'person': cur}, f, ensure_ascii=False)
        for x in (bid + '.vcf', bid + '.json'):
            os.chmod(os.path.join(backup_dir, x), 0o600)
        if str(book.osa(DELETE_SCRIPT, pid, timeout=30)).strip() != 'deleted':
            raise EditError('Contacts did not confirm the delete')
        _patch(book, pid, None)
        return {'id': pid, 'name': cur.get('name') or '', 'backup': bid}
    raise EditError('unknown action')


def prune_backups(backup_dir, days=90):
    """Backups older than 90 days go to backup_dir/_expired (moved, not deleted)."""
    cutoff = time.time() - days * 86400
    try:
        names = os.listdir(backup_dir)
    except OSError:
        return 0
    n = 0
    for x in names:
        p = os.path.join(backup_dir, x)
        if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
            os.makedirs(os.path.join(backup_dir, '_expired'), mode=0o700, exist_ok=True)
            os.replace(p, os.path.join(backup_dir, '_expired', x))
            n += 1
    return n
