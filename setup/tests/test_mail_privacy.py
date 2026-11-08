#!/usr/bin/env python3
"""Mail search and private contacts (security review 3, P2-2) – fictional data, Mail's index is not opened.
Run: python3 setup/tests/test_mail_privacy.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mailsearch as M  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def row(tok, acc, addrs, subj):
    M._TOK[tok] = {'path': None}
    return {'token': tok, 'subject': subj, 'from_name': 'x', 'from_address': addrs[0], 'from_me': False, 'to': '',
            'date': '2026-11-0%sT10:00:00+01:00' % tok[-1], 'message_id': tok, 'account': acc, 'mailbox': 'INBOX',
            'has_attachments': None, '_addrs': addrs}


M.search_index = lambda words, names, own, limit, before=None: [
    row('t1', 'iCloud', ['lee@clientb.example'], 'Report'),
    row('t2', 'iCloud', ['sam@acme.example', 'kim@private.example'], 'SECRET plans'),     # private in Cc
    row('t3', 'iCloud', ['robin@hidden.example'], 'Hidden thing'),
    row('t4', None, ['lee@clientb.example'], 'Other account')]
M.search_spotlight = lambda words, names, own, limit, **k: []
LEVEL = {'kim@private.example': 'private', 'robin@hidden.example': 'hidden'}


def classify(addrs):
    lv = [LEVEL.get(a) for a in addrs]
    return ('hidden', None) if 'hidden' in lv else ('private', 'Kim') if 'private' in lv else (None, None)


r = M.search('plans', {}, (), classify=classify)
subj = [x['subject'] for x in r]
ok('Report' in subj, 'normal mail is listed')
ok('Hidden thing' not in subj and 't3' not in M._TOK, 'hidden contact: not listed, no token')
p = [x for x in r if x.get('private')]
ok(len(p) == 1 and p[0]['token'] is None and p[0]['subject'] == '' and 't2' not in M._TOK and p[0]['from_name'] == 'Kim',
   'private contact (only in Cc): who and when, no subject, no token')
ok('Other account' not in subj and 't4' not in M._TOK, 'accounts Axella is not set up for are left out')
ok(all('_addrs' not in x for x in r), 'addresses are not sent to the browser')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
