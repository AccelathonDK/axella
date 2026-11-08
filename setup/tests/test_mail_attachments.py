#!/usr/bin/env python3
"""Attachments of a mail read from disk (setup/mailsearch.py): a PDF Apple Mail sent inline inside
multipart/alternative → multipart/mixed is listed and can be read; a big attachment Mail keeps next to the mailbox
(…/Attachments/<id>/<n>/<file>, only headers in the .partial.emlx) is read from there. Invented mail.
Run: python3 setup/tests/test_mail_attachments.py"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import mailsearch as M  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


root = tempfile.mkdtemp()
M.MAIL_DIR = root
msgs = os.path.join(root, 'V10', 'acc', 'Sent Messages.mbox', 'x', 'Data', 'Messages')
os.makedirs(msgs)
nested = ('From: Alex Example <alex@example.com>\r\nTo: Lee Chen <lee@example.com>\r\nSubject: Re: the contract\r\n'
          'Message-ID: <c1@example.com>\r\nMIME-Version: 1.0\r\nContent-Type: multipart/alternative; boundary="A"\r\n\r\n'
          '--A\r\nContent-Type: text/plain\r\n\r\nSigned version attached.\r\n'
          '--A\r\nContent-Type: multipart/mixed; boundary="M"\r\n\r\n'
          '--M\r\nContent-Type: text/html\r\n\r\n<p>Signed version attached.</p>\r\n'
          '--M\r\nContent-Type: application/pdf; name="Contract signed.pdf"\r\nContent-Disposition: inline; filename="Contract signed.pdf"\r\n'
          'Content-Transfer-Encoding: base64\r\n\r\nJVBERi1pbnZlbnRlZA==\r\n'
          '--M\r\nContent-Type: text/html\r\n\r\n<p>Br, Alex</p>\r\n--M--\r\n--A--\r\n').encode()


def emlx(name, raw):
    p = os.path.join(msgs, name)
    with open(p, 'wb') as f:
        f.write(b'%d\n' % len(raw) + raw + b'<?xml version="1.0"?><plist/>')
    return p


p1 = emlx('101.emlx', nested)
t1 = M._token({'path': p1, 'account': 'iCloud', 'mid': 'c1@example.com'})
ok(M.read(t1)['attachments'] == ['Contract signed.pdf'], 'an inline PDF inside alternative → mixed is listed')
ok(M.attachment(t1, 1) == ('Contract signed.pdf', 'application/pdf', b'%PDF-invented'), '… and can be read')

partial = nested.replace(b'JVBERi1pbnZlbnRlZA==\r\n', b'\r\n')
p2 = emlx('102.partial.emlx', partial)
att = os.path.join(os.path.dirname(msgs), 'Attachments', '102', '2')
os.makedirs(att)
with open(os.path.join(att, 'Contract signed.pdf'), 'wb') as f:
    f.write(b'%PDF-kept-outside')
t2 = M._token({'path': p2, 'account': 'iCloud', 'mid': 'c2@example.com'})
ok(M.attachment(t2, 1)[2] == b'%PDF-kept-outside', 'a big attachment Mail keeps outside the .partial.emlx is read from there')
os.remove(os.path.join(att, 'Contract signed.pdf'))
try:
    M.attachment(t2, 1)
    ok(False, 'not on disk at all: Mail is asked to fetch it')
except M.NotDownloaded:
    ok(True, 'not on disk at all: Mail is asked to fetch it')

import sqlite3  # noqa: E402
db = sqlite3.connect(':memory:')
ok(M._has_att(db, 101) is None, 'an index without an attachments table: unknown (the dashboard offers to look)')
db.execute('create table attachments (message integer, name text)')
db.execute("insert into attachments values (101, 'Contract signed.pdf')")
ok(M._has_att(db, 101) is True and M._has_att(db, 102) is False, "Mail's attachments table: has / has none")

print('all ok' if not fails else '%d failed' % fails)
sys.exit(1 if fails else 0)
