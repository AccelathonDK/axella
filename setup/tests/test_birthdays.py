#!/usr/bin/env python3
"""Birthdays: read from Contacts (year 1604 = no year), edited on the contact card (argv only, never cleared by
accident), shown for Favourites and anyone switched on – never a private contact – and written for the morning
digest as first names and ages only. A fake Contacts; fictional people. Run: python3 setup/tests/test_birthdays.py"""
import datetime
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import birthdays as B  # noqa: E402
import contacts_book as CB  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


# ---- reading
ok(B.norm('1984-3-7') == '1984-03-07' and B.norm('1604-12-24') == '--12-24', 'Contacts dates: with a year, and 1604 = no year')
ok(B.norm('2001-2-30') == '' and B.norm('x') == '' and B.norm('--02-29') == '--02-29', 'impossible dates are dropped; 29 Feb without a year is fine')
US, RS, FS, GS = '\x1f', '\x1e', '\x1c', '\x1d'
out = ('Lee Chen' + US + '_$!<Mobile>!$_' + FS + '+45 00 00 00 01' + GS + US + US + 'id-lee-0001' + US + 'Lee' + US + 'Chen' + US + 'Acme' + US + '1984-3-7' + RS +
       'Robin' + US + FS + '+45 00 00 00 02' + GS + US + US + 'id-robin-02' + US + 'Robin' + US + '' + US + '' + US + '' + RS)
people = CB.parse(out)
ok(people[0]['birthday'] == '1984-03-07' and 'birthday' not in people[1], 'the address book carries the birthday when Contacts has one')

# ---- whose, and when
d = tempfile.mkdtemp()
bd = B.Birthdays(d)
cast = [{'id': 'id-lee-0001', 'name': 'Lee Chen', 'first': 'Lee', 'birthday': '1984-03-07', 'vip': True},
        {'id': 'id-robin-02', 'name': 'Robin', 'birthday': '--03-07'},
        {'id': 'id-kim-0003', 'name': 'Kim Example', 'first': 'Kim', 'birthday': '1990-03-07', 'vip': True, 'private': True},
        {'id': 'id-sam-0004', 'name': 'Sam Rivera', 'first': 'Sam', 'birthday': '1992-02-29', 'vip': True},
        {'id': 'id-jamie-05', 'name': 'Jamie', 'birthday': '1980-03-08', 'vip': True}]
day = datetime.date(2026, 3, 7)
ok(bd.due(cast, day) == [{'name': 'Lee', 'turns': 42}], 'on the day: a Favourite, with the age; not a non-Favourite, never a private contact')
bd.set_show('id-robin-02', True)
ok([x['name'] for x in bd.due(cast, day)] == ['Lee', 'Robin'] and bd.due(cast, day)[1]['turns'] is None,
   '"Show birthday" on: Robin too, without an age (no year)')
bd.set_show('id-lee-0001', False)
ok([x['name'] for x in bd.due(cast, day)] == ['Robin'], 'a Favourite switched off is left out')
bd.set_show('id-kim-0003', True)
ok('Kim' not in [x['name'] for x in bd.due(cast, day)], 'a private contact never shows, even switched on')
ok([x['name'] for x in bd.due(cast, datetime.date(2027, 2, 28))] == ['Sam'] and bd.due(cast, datetime.date(2028, 2, 28)) == [],
   '29 February: on 28 February in other years, on the day in a leap year')
ok(bd.due(cast, datetime.date(2026, 3, 9)) == [], 'not the day before or after')

# ---- the file the morning digest reads
w = bd.write_today(cast, day)
f = json.load(open(os.path.join(d, 'birthdays-today.json')))
ok(f == {'date': '2026-03-07', 'people': [{'name': 'Robin', 'turns': None}]} and f == w, 'birthdays-today.json: the date and first names (and ages) only')
ok('1984' not in json.dumps(f) and 'id-' not in json.dumps(f), '… no birth years, ids or addresses')

# ---- editing: argv only, and never cleared by accident
calls = []


def osa(script, *args, timeout=0):
    calls.append((script, args))
    if any('\x00' in str(a) for a in args):            # like the real osascript call: argv can't carry a NUL
        raise ValueError('embedded null byte')
    if script is CB.VCARD_SCRIPT:
        return 'BEGIN:VCARD\nFN:Lee Chen\nEND:VCARD'
    return 'ABCDEF12-3456:ABPerson' if script is CB.ADD_SCRIPT else 'ok'


st = tempfile.mkdtemp()
book = CB.Book(st, osa, None, lambda: [], lambda: [])
with open(book.file, 'w') as fh:
    json.dump({'at': 1, 'people': [dict(cast[0], phones=['+4500000001'], emails=[])]}, fh)
CB.edit(book, 'contact_update', {'id': 'id-lee-0001', 'first': 'Lee', 'last': 'Chen', 'phones': ['+4500000001']}, st)
ok(calls[-1][1][-1] == 'keep', 'a save without the birthday field leaves the birthday in Contacts alone')
ok(calls[-1][1][1] == '\x1f' and calls[-1][1][4:8] == ('', '', '', ''), 'an unchanged name and phone are not touched at all (no e-mail is removed)')
cached = json.load(open(book.file))['people'][0]
ok(cached.get('birthday') == '1984-03-07', '… and the cached card keeps it')
CB.edit(book, 'contact_update', {'id': 'id-lee-0001', 'first': 'Lee', 'last': 'Chen', 'phones': ['+4500000001'], 'birthday': '--12-24'}, st)
ok(calls[-1][1][-1] == '1604-12-24', 'no year → 1604, the way Contacts keeps it')
CB.edit(book, 'contact_update', {'id': 'id-lee-0001', 'first': 'Lee', 'last': 'Chen', 'phones': ['+4500000001'], 'birthday': '1984-03-07'}, st)
ok(calls[-1][1][-1] == '1984-3-7' and '1984' not in calls[-1][0], 'a date reaches AppleScript as argv, never in the script')
CB.edit(book, 'contact_update', {'id': 'id-lee-0001', 'first': 'Lee', 'last': 'Chen', 'phones': ['+4500000001'], 'birthday': ''}, st)
ok(calls[-1][1][-1] == '' and 'birthday' not in json.load(open(book.file))['people'][0], 'an empty birthday removes it')
try:
    CB.edit(book, 'contact_update', {'id': 'id-lee-0001', 'first': 'Lee', 'phones': ['+4500000001'], 'birthday': '1984-02-30'}, st)
    ok(False, 'an impossible date is refused')
except CB.EditError:
    ok(True, 'an impossible date is refused')
CB.edit(book, 'contact_add', {'first': 'Jamie', 'phones': ['+4500000005'], 'birthday': '1980-03-08'}, st)
ok(calls[-1][0] is CB.ADD_SCRIPT and calls[-1][1][-1] == '1980-3-8', 'a new contact can have a birthday')
for name in ('ADD_SCRIPT', 'UPDATE_SCRIPT', 'BOOK_SCRIPT'):
    ok(all(line.count('"') % 2 == 0 for line in getattr(CB, name).splitlines()), name + ': quotes in pairs')

print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
