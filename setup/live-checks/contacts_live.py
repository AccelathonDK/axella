#!/usr/bin/env python3
"""LIVE check of Axella's contact editing against the real Contacts app – run on the Mac mini, in Terminal:

    cd ~/dev/own/home-server/axella && /usr/bin/python3 setup/live-checks/contacts_live.py

It drives Contacts through the same AppleScripts the action service uses (contacts_book.py), on ONE throwaway contact it
creates itself ("Axella Livecheck", company "Acme", +45 00 00 00 99, axella.livecheck@example.com), and reads the card
back from Contacts after every step. It never reads, prints or changes any other contact. At the end the test contact
is deleted (a vCard copy goes to a temporary folder first) – also when a step fails.

The first run may ask to let Terminal control Contacts: allow it. Exit code 0 = every step passed.
Python 3.9.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import contacts_book as CB  # noqa: E402

READ_ONE = '''
on run argv
  set US to (ASCII character 31)
  set GS to (ASCII character 29)
  set FS to (ASCII character 28)
  tell application "Contacts"
    set p to person id (item 1 of argv)
    set ph to ""
    repeat with x in phones of p
      set ph to ph & (label of x) & FS & (value of x) & GS
    end repeat
    set em to ""
    repeat with x in emails of p
      set em to em & (label of x) & FS & (value of x) & GS
    end repeat
    set bd to ""
    try
      set d to birth date of p
      if d is not missing value then set bd to ((year of d) as text) & "-" & ((month of d as integer) as text) & "-" & ((day of d) as text)
    end try
    set fn to ""
    try
      set fn to first name of p
    end try
    if fn is missing value then set fn to ""
    return fn & US & ph & US & em & US & bd
  end tell
end run
'''
EXISTS = '''
on run argv
  tell application "Contacts"
    try
      set p to person id (item 1 of argv)
      return "yes"
    on error
      return "no"
    end try
  end tell
end run
'''
SNEAK_MAIL = '''
on run argv
  tell application "Contacts"
    set p to person id (item 1 of argv)
    make new email at end of emails of p with properties {label:"other", value:(item 2 of argv)}
    save
    return "ok"
  end tell
end run
'''
LABEL = CB.label


def osa(script, *args, timeout=60):
    if any('\x00' in str(a) for a in args):
        raise ValueError('embedded null byte')
    p = subprocess.run(['/usr/bin/osascript', '-e', script, *[str(a) for a in args]], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[:300])
    return p.stdout.strip()


def card(pid):
    fn, ph, em, bd = (osa(READ_ONE, pid).split('\x1f') + ['', '', '', ''])[:4]
    pairs = lambda f: [(LABEL(x.split('\x1c')[0]), x.split('\x1c')[1]) for x in f.split('\x1d') if '\x1c' in x]
    return {'first': fn, 'phones': [(lb, CB.phone(v)) for lb, v in pairs(ph)], 'emails': [(lb, v.lower()) for lb, v in pairs(em)],
            'birthday': bd}


fails = 0


def ok(c, label, got=None):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label + ('' if c or got is None else '   → Contacts has: %s' % (got,)))
    fails += 0 if c else 1


tmp = tempfile.mkdtemp(prefix='axella-livecheck-')
os.chmod(tmp, 0o700)
book = CB.Book(tmp, osa, None, lambda: [], lambda: [])     # its own cache in a temporary folder, not state/
backups = os.path.join(tmp, 'backups')
pid = None
base = {'first': 'Axella', 'last': 'Livecheck', 'company': 'Acme'}
PH, M1, M2, M3 = '+4500000099', 'axella.livecheck@example.com', 'axella.livecheck2@example.com', 'axella.livecheck3@example.com'
try:
    # 1. add
    r = CB.edit(book, 'contact_add', dict(base, phones=[{'label': 'mobile', 'value': PH}], emails=[{'label': 'home', 'value': M1}]), backups)
    pid = r['id']
    c = card(pid)
    ok(c['phones'] == [('mobile', PH)] and c['emails'] == [('home', M1)] and c['birthday'] == '', '1. a new contact: phone, e-mail, no birthday', c)

    form = lambda **kw: dict(base, id=pid, phones=[{'label': lb, 'value': v} for lb, v in kw.get('phones', [('mobile', PH)])],
                             emails=[{'label': lb, 'value': v} for lb, v in kw.get('emails', [('home', M1)])], **kw.get('extra', {}))

    # 2. birthday with a year – nothing else touched
    CB.edit(book, 'contact_update', form(extra={'birthday': '1980-03-07'}), backups)
    c = card(pid)
    ok(c['birthday'] == '1980-3-7' and c['phones'] == [('mobile', PH)] and c['emails'] == [('home', M1)], '2. birthday 7 March 1980; phone and e-mail kept', c)

    # 3. an e-mail Axella doesn't know about (added in Contacts itself) survives a birthday-only save
    osa(SNEAK_MAIL, pid, M3)
    CB.edit(book, 'contact_update', form(extra={'birthday': '--12-24'}), backups)
    c = card(pid)
    ok(c['birthday'] == '1604-12-24', '3a. birthday without a year (24 December)', c)
    ok(('other', M3) in c['emails'] and ('home', M1) in c['emails'], '3b. an e-mail only Contacts knows is still on the card', c)

    # 4. add an e-mail, change the phone's label
    CB.edit(book, 'contact_update', form(phones=[('work', PH)], emails=[('home', M1), ('work', M2)]), backups)
    c = card(pid)
    ok(c['phones'] == [('work', PH)], '4a. the phone\'s label changed to work – one number, not two', c)
    ok(('work', M2) in c['emails'] and ('home', M1) in c['emails'] and ('other', M3) in c['emails'], '4b. a second e-mail added, the others kept', c)
    ok(c['birthday'] == '1604-12-24', '4c. the birthday is left alone when the form doesn\'t change it', c)

    # 5. remove an e-mail in the form
    CB.edit(book, 'contact_update', form(phones=[('work', PH)], emails=[('work', M2)]), backups)
    c = card(pid)
    ok(('home', M1) not in c['emails'] and ('work', M2) in c['emails'], '5. an e-mail removed in the form is removed in Contacts', c)

    # 6. rename and remove the birthday
    CB.edit(book, 'contact_update', dict(form(phones=[('work', PH)], emails=[('work', M2)], extra={'birthday': ''}), first='Axella2'), backups)
    c = card(pid)
    ok(c['first'] == 'Axella2' and c['birthday'] == '', '6. first name changed, birthday removed', c)

    # 7. delete: a copy first, then gone
    r = CB.edit(book, 'contact_delete', {'id': pid}, backups)
    ok(os.path.isfile(os.path.join(backups, r['backup'] + '.vcf')) and osa(EXISTS, pid) == 'no', '7. delete: vCard copy kept, the contact is gone')
    pid = None
except Exception as e:
    fails += 1
    print('  FAIL stopped: %s' % str(e)[:300])
finally:
    if pid:
        try:
            vc = osa(CB.VCARD_SCRIPT, pid)
            with open(os.path.join(tmp, 'leftover.vcf'), 'w', encoding='utf-8') as f:
                f.write(vc)
            osa(CB.DELETE_SCRIPT, pid)
            print('  (the test contact was removed; its copy is in %s)' % tmp)
        except Exception as e:
            print('  ! could not remove the test contact "Axella Livecheck" – delete it in Contacts (%s)' % str(e)[:120])
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
