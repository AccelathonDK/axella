#!/usr/bin/env python3
"""Cleanup keep rules: authorities, banks, lenders, e-signing and your own keep-domains file. Run: python3 setup/tests/test_cleanup_keep.py"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cleanup as C  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


for d in ['skat.dk', 'acmebank.dk', 'example-sparekasse.dk', 'penneo.com', 'acme-realkredit.dk', 'acme-pension.dk', 'claims.acme.com']:
    ok(bool(C.KEEP_DOMAIN.search(d)), 'kept: ' + d)
for d in ['shop.example', 'newsletter.acme.dk']:
    ok(not C.KEEP_DOMAIN.search(d), 'not kept: ' + d)
ok(bool(C.PRO_DOMAIN.search('ey.com')) and not C.PRO_DOMAIN.search('claw.dk'), 'professional domains are label-anchored')
t = tempfile.mkdtemp()
ok(C.local_keep('acme.dk', t) is False, 'no keep-domains file: nothing extra kept')
with open(os.path.join(t, C.KEEP_FILE), 'w') as f:
    f.write('# my insurers\nacme.dk\n@lee-insure.example   # car\n')
ok(C.local_keep('acme.dk', t) and C.local_keep('mail.acme.dk', t), 'own domain and its subdomains kept')
ok(C.local_keep('lee-insure.example', t), '@ prefix and comments allowed')
ok(not C.local_keep('notacme.dk', t), 'a longer name is not a subdomain')
# brand-name institutions (user test 6, item 3): kept without a keep file
e = tempfile.mkdtemp()
for d in ['nykredit.dk', 'totalkredit.dk', 'pfa.dk', 'gjensidige.dk', 'udbetaling.dk', 'mail.nykredit.dk']:
    ok(C.local_keep(d, e), 'built-in: ' + d)
for d in ['notnykredit.dk', 'pfa.dk.example', 'mypfa.dk']:
    ok(not C.local_keep(d, e), 'near miss not kept: ' + d)
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
