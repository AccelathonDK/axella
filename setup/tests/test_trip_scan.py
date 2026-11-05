#!/usr/bin/env python3
"""Trip scan through the action service (axella-actions.py trip_scan): booking mails are read on the Mac mini,
a private contact's and a protected workplace's mail are never read, and the result is suggestions only.
Mail is stubbed; fictional cast. Run: python3 setup/tests/test_trip_scan.py"""
import importlib.util
import json
import os
import sys
import tempfile
from email.message import EmailMessage

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
import trips  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def mail(ref, when, frm):
    m = EmailMessage()
    m['Subject'], m['From'] = 'Booking confirmation', frm
    m.set_content('x')
    m.add_alternative('<script type="application/ld+json">%s</script>' % json.dumps(
        {'@type': 'LodgingReservation', 'reservationNumber': ref, 'checkinTime': when, 'checkoutTime': when,
         'reservationFor': {'name': 'Acme Inn', 'address': {'addressLocality': 'Odense'}}}), subtype='html')
    return m.as_bytes()


box = {'p1': ('iCloud', 'noreply@hotels.example', mail('R1', '2099-05-01T15:00:00+02:00', 'noreply@hotels.example')),
       'p2': ('iCloud', 'anna@private.example', mail('R2', '2099-05-02T15:00:00+02:00', 'anna@private.example')),
       'p3': ('Acme', 'travel@acme.example', mail('R3', '2099-05-03T15:00:00+02:00', 'travel@acme.example'))}
read = []
A.TRIPS = trips.Trips(tempfile.mkdtemp())
A.mail_accounts = lambda: {'a1': 'iCloud', 'a2': 'Acme'}
asked_days = []
A.mailsearch.booking_candidates = lambda accounts, match, limit=400, days=548: asked_days.append(days) or [
    {'path': k, 'account': v[0], 'message_id': k + '@x', 'subject': 'Booking confirmation', 'from_name': '', 'from_address': v[1], 'date': None}
    for k, v in box.items()]
A.mailsearch.addresses_of = lambda p: [box[p][1]]
A.mailsearch._raw = lambda p: read.append(p) or box[p][2]
A.mail_privacy = lambda addrs: ('private', None) if 'anna@private.example' in addrs else (None, None)
A.profile.is_protected = lambda acc=None, addr=None, cfg=None: acc == 'Acme'
A.LOG_FILE = os.path.join(tempfile.mkdtemp(), 'actions.log')
A.trip_scan()
v = A.TRIPS.view()
refs = [b['ref'] for t in v['suggested'] for b in t['bookings']]
ok(refs == ['R1'], 'the booking is suggested')
ok(read == ['p1'], 'a private contact\'s and a protected workplace\'s mail are never read')
ok(v['trips'] == [] and v['scan']['skipped'] == 2 and v['scan']['running'] is False, 'suggestions only; the scan reports what it left out')
ok(v['suggested'][0]['bookings'][0]['source']['message_id'] == 'p1@x', 'each booking links to its source mail')
# an e-ticket mail whose details are only in its PDF lands in To sort, ready for Read with Claude
from email.message import EmailMessage as _EM
_m = _EM(); _m['Subject'] = 'Acme Air E-Documents for ALEX EXAMPLE for travel on 11SEP'; _m['From'] = 'noreply@acme-air.example'
_m.set_content('Your documents are attached.'); _m.add_attachment(b'%PDF-1.4 x', maintype='application', subtype='pdf', filename='eticket.pdf')
box['p4'] = ('iCloud', 'noreply@acme-air.example', _m.as_bytes())
A.mailsearch.booking_candidates = lambda accounts, match, limit=400, days=548: asked_days.append(days) or [
    {'path': 'p4', 'account': 'iCloud', 'message_id': 'p4@x', 'subject': _m['Subject'], 'from_name': '', 'from_address': 'noreply@acme-air.example', 'date': None}]
A.trip_scan()
ok([u['message_id'] for u in A.TRIPS.view()['unsorted']] == ['p4@x'], 'an e-ticket mail with its details in the PDF is in To sort')
# "Add a mail…" from search: a private contact's mail is refused, a protected workplace keeps no subject
A.config = lambda: {'accounts': {'iCloud': {'kind': 'private'}, 'Acme': {'kind': 'work'}}}
A.meeting_mail_addresses = lambda frm, mid, strict=False: ['anna@private.example'] if mid == 'priv@x' else ['travel@acme.example']
tid = A.TRIPS.action('trip_mail_new', {'message_id': 'p1@x', 'trip_title': 'Odense', 'date': '2099-05-01',
                                       'mail': {'account': 'iCloud', 'message_id': 'p1@x', 'subject': 'Booking'}})['id']
try:
    A.do_action('trip_mail_add', {'id': tid, 'message_id': 'priv@x', 'date': '2099-05-01', 'mail': {'account': 'iCloud', 'message_id': 'priv@x'}})
    ok(False, 'a private contact\'s mail can\'t be added')
except A.Bad:
    ok(True, 'a private contact\'s mail can\'t be added')
A.do_action('trip_mail_add', {'id': tid, 'message_id': 'w1@x', 'date': '2099-05-02', 'title': 'Work trip hotel',
                              'mail': {'account': 'Acme', 'message_id': 'w1@x', 'subject': 'Secret project offsite'}})
raw = open(A.TRIPS.file).read()
ok('Secret project' not in raw and 'Work trip hotel' in raw, 'a protected workplace\'s mail: its subject is not stored, your title is')
# "Read with Claude": only mails the Trips page lists, never a private or protected one; one run is queued
A.TRIPS = trips.Trips(tempfile.mkdtemp())
A.TRIPS.set_unsorted([{'account': 'iCloud', 'message_id': 'ok@x', 'subject': 'E-ticket'}, {'account': 'iCloud', 'message_id': 'priv@x', 'subject': 'x'},
                      {'account': 'Acme', 'message_id': 'w1@x', 'subject': 'Offsite'}])
asked = []
A.RUNNER.trip_read_request = lambda mails: asked.extend(mails) or 'trX'
A.RUNNER.trip_read_busy = lambda: False
r = A.do_action('trip_read', {'message_ids': ['ok@x', 'priv@x', 'w1@x', 'unknown@x']})
ok([m['message_id'] for m in asked] == ['ok@x'] and r['mails'] == 1, 'only the listed, non-private, non-protected mail is sent to the reading run')

A.mailsearch.path_for_mid = lambda mid: '/x/' + mid
A.mailsearch.sender_of = lambda path: ('tickets@acme-air.example', '2026-10-10T18:02:00+02:00')
asked.clear(); A.do_action('trip_read', {'message_ids': ['ok@x']})
ok(asked[0]['sender'] == 'tickets@acme-air.example' and asked[0]['date'].startswith('2026-10-10T18:02'),
   'the run gets the From address and the date received – what Mail finds a message by, not the display name')
A.meeting_mail_addresses = lambda frm, mid, strict=False: [] if strict else ['travel@acme.example']
try:
    A.do_action('trip_read', {'message_ids': ['ok@x']}); ok(False, 'a mail whose file is not found is not sent (fails closed)')
except A.Bad:
    ok(True, 'a mail whose file is not found is not sent (fails closed)')
# "Scan since": the date you pick decides how far back the scan reads; refused beyond 18 months or in the future
import datetime as _dt
A.threading.Thread = lambda target, daemon=True: type('T', (), {'start': lambda self: target()})()
asked_days.clear()
since = (_dt.date.today() - _dt.timedelta(days=100)).isoformat()
r = A.do_action('trip_scan', {'since': since})
ok(r.get('since') == since and asked_days == [101] and A.TRIPS.view()['since'] == since, 'Scan since a date: the scan reads from that day (101 days) and remembers it')
for bad in ('2001-01-01', (_dt.date.today() + _dt.timedelta(days=3)).isoformat(), 'soon'):
    try:
        A.do_action('trip_scan', {'since': bad}); ok(False, 'a date out of range is refused: ' + bad)
    except A.Bad:
        ok(True, 'a date out of range is refused: ' + bad)
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
