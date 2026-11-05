#!/usr/bin/env python3
"""LIVE check of what reply debt assumes about Mail's own index – run on the Mac mini, in Terminal:

    cd ~/dev/own/home-server/axella && /usr/bin/python3 setup/live-checks/mail_index_live.py

Reply debt counts a thread only when you were in To, not only Cc. It reads that from the Envelope Index
(recipients.type: 0 = To, 1 = Cc, 2 = Bcc). This check takes up to 25 received mails of each type that have one of
your addresses, opens their headers on disk and checks that the address really is in the To (or Cc) header.
Read-only. It prints counts only – no subjects, names or addresses. Terminal needs Full Disk Access to read Mail's
folder (System Settings → Privacy & Security); without it the check says so. Exit code 0 = the assumption holds.
"""
import email.policy
import email.utils
import json
import os
import sqlite3
import sys
from email.parser import BytesHeaderParser
from urllib.parse import quote

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import mailsearch as MS  # noqa: E402

try:
    cfg = json.load(open(os.path.join(HERE, 'actions-config.json'), encoding='utf-8'))
except (OSError, ValueError):
    print('FAIL – setup/actions-config.json could not be read')
    sys.exit(1)
own = {str(a.get('address') or '').lower() for a in cfg.get('accounts', {}).values() if isinstance(a, dict) and a.get('address')}
path = MS._envelope()
if not path or not own:
    print('FAIL – %s' % ('no Envelope Index found (Full Disk Access for Terminal?)' if not path else 'no account addresses in actions-config.json'))
    sys.exit(1)
try:
    db = sqlite3.connect('file:%s?mode=ro' % quote(path), uri=True, timeout=5)
    rc = MS._cols(db, 'recipients')
except sqlite3.Error as e:
    print('FAIL – the index could not be opened (%s) – give Terminal Full Disk Access' % str(e)[:80])
    sys.exit(1)
if 'type' not in rc:
    print('NOTE – this Mail version has no recipients.type: reply debt counts every thread (no Cc filter). Nothing to check.')
    sys.exit(0)
vdir = os.path.dirname(os.path.dirname(path))
marks = ','.join('?' * len(own))
fails, checked = 0, {}
for typ, header in ((0, 'To'), (1, 'Cc')):
    rows = db.execute('select r.message, mb.url from recipients r join addresses a on a.ROWID = r.address '
                      'join messages m on m.ROWID = r.message join mailboxes mb on mb.ROWID = m.mailbox '
                      'where r.type = ? and lower(a.address) in (%s) order by m.ROWID desc limit 400' % marks,
                      [typ] + sorted(own)).fetchall()
    good = bad = 0
    for rowid, url in rows:
        if good + bad >= 25:
            break
        _, box, base = MS._mailbox(url, vdir)
        if MS.SENT_RE.search(box or ''):
            continue
        p = MS._emlx(base, rowid)
        if not p:
            continue
        try:
            h = BytesHeaderParser(policy=email.policy.compat32).parsebytes(MS._raw(p, headers_only=True))
        except (OSError, ValueError):
            continue
        listed = {a.lower() for _, a in email.utils.getaddresses([MS._dec(h.get(header) or '')])}
        if listed & own:
            good += 1
        else:
            bad += 1
    checked[header] = (good, bad)
    ok = bad == 0 and good > 0
    fails += 0 if ok or good + bad == 0 else 1
    print('  %s   type %d = %s: %d of %d checked mails have your address in the %s header' %
          ('ok  ' if ok else ('n/a ' if good + bad == 0 else 'FAIL'), typ, header, good, good + bad, header))
db.close()
print('PASS' if not fails else 'FAIL – reply debt\'s To/Cc filter reads the index wrongly; tell Axella\'s developer')
sys.exit(1 if fails else 0)
