#!/usr/bin/env python3
"""The Contacts page's address book: parsing what Contacts returns, phone normalisation, Hidden left out, Private
marked, VIPs as favourites, mail correspondents added. Fictional data, no Contacts app.
Run: python3 setup/tests/test_contacts_book.py"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import contacts_book as CB  # noqa: E402
import privacy  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


US, GS, RS = '\x1f', '\x1d', '\x1e'
out = RS.join([
    'Lee Chen' + US + '+45 00 00 00 01' + GS + '00000001' + GS + US + 'Lee@ClientB.example' + GS,
    'Sam Rivera' + US + '0045 00000002' + GS + US + '',
    'Robin Example' + US + '' + US + 'robin@acme.example' + GS,
    'Kim Example' + US + '+45 00 00 00 04' + GS + US + '',
    'No Numbers' + US + '' + US + 'not an address' + GS]) + RS
people = CB.parse(out)
ok([p['name'] for p in people] == ['Lee Chen', 'Sam Rivera', 'Robin Example', 'Kim Example'], 'parsed; a person without number or address dropped')
ok(people[0]['phones'] == ['+4500000001'] and people[0]['emails'] == ['lee@clientb.example'], 'phones normalised and de-duplicated, e-mail lower-case')
ok(people[1]['phones'] == ['+4500000002'], '00 45 … → +45 …')

st = tempfile.mkdtemp()
json.dump({'defaults': {}, 'contacts': [
    {'id': 'c1', 'name': 'Sam Rivera', 'ids': ['+4500000002'], 'levels': {'whatsapp': 'hidden'}},
    {'id': 'c2', 'name': 'Kim Example', 'ids': ['+4500000004'], 'levels': {'signal': 'private'}}]}, open(os.path.join(st, 'privacy.json'), 'w'))
b = CB.Book(st, lambda s, timeout=0: out, privacy.Privacy(st), lambda: [{'name': 'Lee Chen'}],
            lambda: [{'address': 'jamie@example.com', 'name': 'Jamie'}, {'address': 'lee@clientb.example', 'name': 'Lee'}])
b.refresh()
ok(oct(os.stat(b.file).st_mode)[-3:] == '600', 'the cache is chmod 600')
ov = b.overview()
names = {p['name']: p for p in ov['people']}
ok('Sam Rivera' not in names, 'Hidden (on any app) is left out')
ok(names['Kim Example']['private'] is True and names['Lee Chen']['private'] is False, 'Private marked')
ok(names['Lee Chen']['vip'] is True and not names['Robin Example']['vip'], 'VIPs are the favourites')
ok(names.get('Jamie', {}).get('emails') == ['jamie@example.com'] and sum(1 for p in ov['people'] if 'lee@clientb.example' in p['emails']) == 1,
   'mail correspondents added once, not twice')
# someone you mail with whose name is already in Contacts: on that card, not a second entry (fix: a birthday saved on
# the mail-only entry made a duplicate contact)
out2 = ('Anna Keller' + US + '+45 00 00 00 07' + GS + US + US + 'id-anna-0007' + US + 'Anna' + US + 'Keller' + US + '' + US + '' + RS)
b2 = CB.Book(tempfile.mkdtemp(), lambda s, timeout=0: out2, None, lambda: [],
             lambda: [{'address': 'anna.k@example.org', 'name': 'Anna  Keller'}, {'address': 'jamie@example.com', 'name': 'Jamie'}])
b2.refresh()
ov2 = b2.overview()
annas = [p for p in ov2['people'] if p['name'].startswith('Anna')]
ok(len(annas) == 1 and annas[0]['id'] == 'id-anna-0007' and annas[0]['mail_only'] == ['anna.k@example.org'] and annas[0]['emails'] == [],
   'a mail address with the same name goes on the Contacts card as "from your mail" – one Anna, not two')
ok(any(p['name'] == 'Jamie' and p.get('source') == 'mail' for p in ov2['people']), 'someone not in Contacts is still listed on their own')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
