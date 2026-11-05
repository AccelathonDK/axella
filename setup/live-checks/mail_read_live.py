#!/usr/bin/env python3
"""LIVE check of Axella's mail reader (Trips, Receipts, the item sheet) – run on the Mac mini, in Terminal:

    cd ~/dev/own/home-server/axella && /usr/bin/python3 setup/live-checks/mail_read_live.py

Takes the 10 newest received mails that Mail has on disk, finds each by its Message-ID the way the reader does
(path_for_mid), reads it from Mail's own file, opens its first attachment, and reads the From address and date that
Trips' "Read with Claude" gives Macuse to find the mail. Read-only. Prints timings and counts
only – no subjects, names or text. Terminal needs Full Disk Access to read Mail's folder. Exit code 0 = every mail
was found and read in under 2 seconds.
"""
import os
import sqlite3
import sys
import time
from urllib.parse import quote

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import mailsearch as MS  # noqa: E402

path = MS._envelope()
if not path:
    print('FAIL – no Envelope Index found (Full Disk Access for Terminal?)')
    sys.exit(1)
db = sqlite3.connect('file:%s?mode=ro' % quote(path), uri=True, timeout=5)
rows = db.execute('select g.message_id_header, mb.url from messages m join message_global_data g on g.ROWID = m.global_message_id '
                  'join mailboxes mb on mb.ROWID = m.mailbox where g.message_id_header is not null order by m.ROWID desc limit 200').fetchall()
db.close()
fails = done = 0
for mid, url in rows:
    if done >= 10:
        break
    box = MS._mailbox(url, '')[1] or ''
    if MS.SENT_RE.search(box) or 'trash' in box.lower() or 'junk' in box.lower():
        continue
    t0 = time.time()
    rp = MS.path_for_mid(mid)
    if not rp:
        continue                                    # not on disk – the reader asks Mail for those
    # an account name like the reader's, so an attachment that isn't on disk says "ask Mail" as it does there
    tok = MS._token({'path': rp, 'account': 'livecheck', 'mid': mid})
    try:
        res = MS.read(tok)
        n_att = len(res['attachments'])
        att = ''
        if n_att:
            try:
                name, ctype, data = MS.attachment(tok, 1)
                att = ', attachment 1: %s, %d kB' % (ctype, len(data) // 1024)
            except MS.NotDownloaded:
                att = ', attachment 1 not on disk yet – the reader asks Mail for it (as designed)'
        sender, when = MS.sender_of(rp)                # what Trips' "Read with Claude" hands Macuse to find the mail
        ms = (time.time() - t0) * 1000
        ok = ms < 2000 and (res['body'] or res['html']) and '@' in sender and len(when) >= 19
        done += 1
        fails += 0 if ok else 1
        print('  %s   mail %d: read in %d ms, %d chars of text, %s, %d attachment(s)%s, sender address %s, date %s' % (
            'ok  ' if ok else 'FAIL', done, ms, len(res['body']), 'formatted' if res['html'] else 'plain', n_att, att,
            'found' if '@' in sender else 'MISSING', 'found' if len(when) >= 19 else 'MISSING'))
    except Exception as e:
        done += 1
        fails += 1
        print('  FAIL   mail %d: %s' % (done, str(e)[:120]))
if not done:
    print('FAIL – no received mail found on disk')
    sys.exit(1)
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
