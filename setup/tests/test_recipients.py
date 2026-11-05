#!/usr/bin/env python3
"""The composer's To / Cc / Bcc on the Mac mini side: address checks, limits, the read-back string the AppleScript
compares with, and reply-all from a mail's headers without your own addresses. Fictional data; Mail is not used.
Run: python3 setup/tests/test_recipients.py"""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def bad(p):
    try:
        A.recipients(p)
        return False
    except A.Bad:
        return True


ok(A.recipients({'to': 'lee@clientb.example'}) is None, 'no lists: the older one-address reply')
to, cc, bcc = A.recipients({'to': ['Lee@ClientB.example'], 'cc': ['sam@acme.example', 'lee@clientb.example'], 'bcc': []})
ok(to == ['Lee@ClientB.example'] and cc == ['sam@acme.example'] and bcc == [], 'duplicates across To/Cc dropped')
ok(bad({'to': []}), 'To cannot be empty')
ok(bad({'to': ['Lee Chen <lee@clientb.example>']}), 'names or angle brackets are refused – addresses only')
ok(bad({'to': ['lee@clientb.example', 'x@y.example\nBcc: z@evil.example']}), 'no header injection')
ok(bad({'to': ['noreply@shop.example']}), 'no-reply on To refused')
ok(not bad({'to': ['lee@clientb.example'], 'cc': ['notifications@shop.example']}), 'a notifications address on Cc is allowed')
ok(bad({'to': ['a%d@x.example' % i for i in range(31)]}), 'at most 30 recipients')
ok(A.rcpt_expected(['a@x.example'], ['b@x.example'], ['c@x.example']) == 'to:a@x.example\x1ecc:b@x.example\x1ebcc:c@x.example\x1e',
   'read-back string in the script\'s format')

# reply all from headers – a fake .emlx found through the index
d = tempfile.mkdtemp()
p = os.path.join(d, '1.emlx')
hdr = (b'From: Lee Chen <lee@clientb.example>\r\nReply-To: Lee Chen <lee@clientb.example>\r\n'
       b'To: Alex Example <you@icloud.com>, Sam Rivera <sam@acme.example>\r\nCc: kim@private.example\r\nSubject: Plans\r\n\r\nbody\r\n')
open(p, 'wb').write(str(len(hdr)).encode() + b'\n' + hdr)
A.mailsearch.path_for_mid = lambda mid: p
A.mailsearch._inside = lambda x: x
A.config = lambda: {'accounts': {'iCloud': {'address': 'you@icloud.com'}}, 'self': {'addresses': []}}
A.mail_privacy = lambda addrs: (None, None)
info = A.reply_info('iCloud', 'm1')
ok([x['address'] for x in info['to']] == ['lee@clientb.example'], 'To: the sender (Reply-To)')
ok([x['address'] for x in info['cc']] == ['sam@acme.example', 'kim@private.example'], 'Cc: everyone else, without you: %s' % info['cc'])
A.mail_privacy = lambda addrs: ('private', None)
try:
    A.reply_info('iCloud', 'm1'); ok(False, 'private contact refused')
except A.Bad:
    ok(True, 'private contact refused')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
