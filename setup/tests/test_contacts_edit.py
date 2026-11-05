#!/usr/bin/env python3
"""Editing contacts (owner only): checked fields reach AppleScript as argv only, a full copy (vCard + fields) is kept
before a delete and Restore brings the contact back; the cached list changes at once. A fake Contacts – fictional
people. Run: python3 setup/tests/test_contacts_edit.py"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import contacts_book as CB  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


calls = []


def osa(script, *args, timeout=0):
    calls.append((script, args))
    if any('\x00' in str(a) for a in args):            # like the real osascript call: argv can't carry a NUL
        raise ValueError('embedded null byte')
    if script is CB.ADD_SCRIPT:
        return 'ABCDEF12-3456:ABPerson'
    if script is CB.UPDATE_SCRIPT:
        return 'ok'
    if script is CB.VCARD_SCRIPT:
        return 'BEGIN:VCARD\nFN:Lee Chen\nEND:VCARD'
    if script is CB.DELETE_SCRIPT:
        return 'deleted'
    return ''


st = tempfile.mkdtemp()
b = CB.Book(st, osa, None, lambda: [], lambda: [])
bk = os.path.join(st, 'deleted', 'contacts')
r = CB.edit(b, 'contact_add', {'first': 'Lee', 'last': 'Chen', 'company': 'Client B',
                               'phones': [{'label': 'mobile', 'value': '00 00 00 01'}], 'emails': [{'label': 'work', 'value': 'Lee@ClientB.example'}]}, bk)
script, args = calls[-1]
ok(r['id'] == 'ABCDEF12-3456:ABPerson' and r['name'] == 'Lee Chen', 'added')
ok(args[:3] == ('Lee', 'Chen', 'Client B') and args[3] == 'mobile\x1c+4500000001' and args[4] == 'work\x1clee@clientb.example',
   'values go as argv, phone normalised, e-mail lower-case')
ok('Lee' not in script and 'Client B' not in script, 'nothing of the contact inside the script text')
ok(any(x.get('id') == r['id'] for x in b._load()['people']), 'the cached list has the new contact at once')
for bad, why in (({'first': ''}, 'no name'), ({'first': 'Lee', 'phones': [{'value': 'abc'}]}, 'bad phone'),
                 ({'first': 'Lee', 'emails': [{'value': 'not-mail'}]}, 'bad e-mail'), ({'first': 'Lee<script>'}, 'markup in a name')):
    try:
        CB.edit(b, 'contact_add', bad, bk)
        ok(False, 'refused: ' + why)
    except CB.EditError:
        ok(True, 'refused: ' + why)
try:
    CB.edit(b, 'contact_update', {'id': 'x; do shell script', 'first': 'Lee'}, bk)
    ok(False, 'odd id refused')
except CB.EditError:
    ok(True, 'odd id refused')
CB.edit(b, 'contact_update', {'id': r['id'], 'first': 'Lee', 'last': 'Chen-Example', 'phones': [], 'emails': [{'value': 'lee@clientb.example'}]}, bk)
ok(next(x for x in b._load()['people'] if x['id'] == r['id'])['name'] == 'Lee Chen-Example', 'updated')
n = len(calls)
d = CB.edit(b, 'contact_delete', {'id': r['id']}, bk)
order = [c[0] for c in calls[n:]]
ok(order == [CB.VCARD_SCRIPT, CB.DELETE_SCRIPT], 'a copy first, then the delete')
ok(os.path.isfile(os.path.join(bk, d['backup'] + '.vcf')) and oct(os.stat(os.path.join(bk, d['backup'] + '.json')).st_mode)[-3:] == '600',
   'vCard and fields kept, chmod 600')
ok(not any(x.get('id') == r['id'] for x in b._load()['people']), 'gone from the list')
osa_fail = lambda s, *a, timeout=0: '' if s is CB.VCARD_SCRIPT else 'deleted'
b2 = CB.Book(st, osa_fail, None, lambda: [], lambda: [])
try:
    CB.edit(b2, 'contact_delete', {'id': r['id']}, bk)
    ok(False, 'no copy → no delete')
except CB.EditError:
    ok(True, 'no copy → no delete')
rr = CB.edit(b, 'contact_restore', {'backup': d['backup']}, bk)
ok(calls[-1][0] is CB.ADD_SCRIPT and calls[-1][1][:2] == ('Lee', 'Chen-Example') and rr['vcard'].endswith('.vcf'), 'restore re-creates the fields; the full vCard is there too')
# an update sends only what changed – what Axella hasn't read on the card is never removed
old = {'first': 'Lee', 'last': 'Chen', 'company': '', 'phones': ['+4500000001'], 'phone_labels': ['mobile'],
       'emails': ['lee@clientb.example'], 'email_labels': ['work']}
c = CB.clean_person({'first': 'Lee', 'last': 'Chen', 'phones': [{'label': 'mobile', 'value': '+4500000001'}],
                     'emails': [{'label': 'work', 'value': 'lee@clientb.example'}], 'birthday': '--03-07'})
a = CB._update_args(old, c)
ok(a[:7] == ('\x1f', '\x1f', '\x1f', '', '', '', '') and a[7] == '1604-3-7', 'only the birthday changed: nothing else is sent to Contacts')
c = CB.clean_person({'first': 'Lee', 'last': 'Chen', 'phones': [{'label': 'mobile', 'value': '+4500000001'}], 'emails': []})
ok(CB._update_args(old, c)[4] == 'lee@clientb.example', 'an e-mail you removed in the form is removed')
c = CB.clean_person({'first': 'Lee', 'last': 'Chen', 'phones': [{'label': 'work', 'value': '+4500000001'}],
                     'emails': [{'label': 'work', 'value': 'lee@clientb.example'}, {'label': 'home', 'value': 'lee@example.org'}]})
a = CB._update_args(old, c)
ok(a[3] == '4500000001' and 'work' in a[5] and a[4] == '' and 'lee@example.org' in a[6], 'a new label: that number goes and comes back; a new e-mail is added')
ok('repeat while (count of emails' not in CB.UPDATE_SCRIPT, 'the update never wipes all e-mails or phones of a card')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
