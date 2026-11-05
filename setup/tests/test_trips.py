#!/usr/bin/env python3
"""Trips scan: booking confirmations in mail (schema.org data, or a travel sender's reference and dates) → upcoming
bookings only → suggested trips you confirm; dismissed ones never come back; removing a trip keeps it restorable.
Mails are built here; fictional cast and places. Run: python3 setup/tests/test_trips.py"""
import datetime
import json
import os
import sys
import tempfile
import time
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import trips as T  # noqa: E402

fails = 0
# a cancellation from the booking's own (checked) sender – what axella-actions.py's _trip_update_trust decides for real
OWN = lambda u, x: (True, 'airline.example')


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def mail(subject, frm, html=None, text=None):
    m = EmailMessage()
    m['Subject'], m['From'], m['To'] = subject, frm, 'alex@example.com'
    m.set_content(text or 'See the HTML version.')
    if html:
        m.add_alternative(html, subtype='html')
    return m.as_bytes()


def ld(obj):
    return '<html><head><script type="application/ld+json">%s</script></head><body><p>Thanks for booking</p></body></html>' % json.dumps(obj)


today = datetime.date(2026, 11, 5)
flight = {'@context': 'http://schema.org', '@type': 'FlightReservation', 'reservationNumber': 'ABC123',
          'underName': {'@type': 'Person', 'name': 'Alex Example'},
          'reservationFor': {'@type': 'Flight', 'flightNumber': '1415', 'airline': {'@type': 'Airline', 'name': 'Acme Air', 'iataCode': 'AA'},
                             'departureAirport': {'@type': 'Airport', 'name': 'Copenhagen', 'iataCode': 'CPH'},
                             'departureTime': '2027-10-10T10:40:00+02:00',
                             'arrivalAirport': {'@type': 'Airport', 'name': 'Lisbon', 'iataCode': 'LIS', 'address': {'addressLocality': 'Lisbon'}},
                             'arrivalTime': '2027-10-10T21:15:00+01:00'}}
hotel = {'@context': 'http://schema.org', '@type': 'LodgingReservation', 'reservationNumber': 'H-77881',
         'checkinTime': '2027-10-11T15:00:00+01:00', 'checkoutTime': '2027-10-15T11:00:00+01:00',
         'reservationFor': {'@type': 'LodgingBusiness', 'name': 'Acme Quinta', 'address': {'addressLocality': 'Douro'}}}
ferry = {'@type': 'BoatReservation', 'reservationNumber': 'Z9', 'reservationFor': {'@type': 'BoatTrip',
         'departureBoatTerminal': {'name': 'Setubal'}, 'arrivalBoatTerminal': {'name': 'Troia', 'address': {'addressLocality': 'Troia'}},
         'departureTime': '2027-10-16T09:00:00+01:00', 'arrivalTime': '2027-10-16T11:00:00+01:00'}}
past = dict(flight, reservationNumber='OLD1', reservationFor=dict(flight['reservationFor'], departureTime='2025-06-01T08:00:00+02:00',
                                                                    arrivalTime='2025-06-01T12:00:00+02:00'))
weekend = {'@type': 'EventReservation', 'reservationNumber': 'T-5', 'reservationFor': {'@type': 'Event', 'name': 'Acme Jazz Night',
           'startDate': '2026-12-12T20:00:00+01:00', 'location': {'name': 'Acme Hall', 'address': {'addressLocality': 'Aarhus'}}}}

# ---- reading a mail
b = T.bookings_in(mail('Your flight to Lisbon', 'Acme Air <noreply@acme-air.example>', ld(flight)), 'Your flight to Lisbon', 'noreply@acme-air.example', today)
ok(len(b) == 1 and b[0]['kind'] == 'flight' and b[0]['ref'] == 'ABC123' and b[0]['place'] == 'Lisbon' and b[0]['travellers'] == ['Alex Example'],
   'schema.org flight: kind, reference, destination and travellers')
ok(b[0]['title'] == 'Flight AA 1415 · Copenhagen → Lisbon' and b[0]['start'].startswith('2027-10-10T10:40'), '… title and local departure time')
g = T.bookings_in(mail('Itinerary', 'x@acme-tours.example', ld({'@graph': [hotel, ferry]})), 'Itinerary', 'x@acme-tours.example', today)
ok([x['kind'] for x in g] == ['hotel', 'ferry'] and g[0]['place'] == 'Douro' and g[0]['end'].startswith('2027-10-15'), 'several reservations in one mail (@graph)')
txt = T.bookings_in(mail('Booking confirmation', 'Hotel Bookings <noreply@hotels.example>', text='Booking number: 5550003333\nCheck-in: 20 March 2027\nCheck-out: 23 March 2027\nAcme Hotel, Odense'),
                    'Booking confirmation', 'noreply@hotels.example', today)
ok(len(txt) == 1 and txt[0]['confidence'] == 'check' and txt[0]['ref'] == '5550003333' and txt[0]['start'].startswith('2027-03-20') and txt[0]['end'].startswith('2027-03-23'),
   'a travel sender without schema.org: reference and dates from the text, marked "check this"')
ok(T.bookings_in(mail('Order confirmation', 'shop@acme-shop.example', text='Order number: 55667788 – delivery 20 March 2027'),
                 'Order confirmation', 'shop@acme-shop.example', today) == [], 'a shop order is not a booking')
ok(T.looks_like_booking('Din rejse til Porto', 'x@example.org') and T.looks_like_booking('Your flight details', 'x@example.org')
   and not T.looks_like_booking('Lunch?', 'lee@acme.example'), 'candidates: booking words in the subject (EN/DA)')
ok(not T.looks_like_booking('Hi', 'news@acme-air.example'), 'who sent it decides nothing: an airline\'s "Hi" is not a candidate')
ok(not any(hasattr(T, n) for n in ('TRAVEL_DOMAINS', 'FLIGHT_DOMAINS', 'HOTEL_DOMAINS', 'PROVIDERS')), 'no lists of airlines, hotels or companies in the code')

# ---- mails without schema.org data (fix after the first live scan)
sent = datetime.date(2026, 10, 1)
b, why = T.from_text('Din booking er bekræftet - Copenhagen til Berlin, 18 nov - 22 nov', 'no-reply@acme-air.example', 'Bookingreference: ABC12D\nFly AX 1, afgang 07:10',
                     today, sent, 'Acme Air')
ok(b and b['kind'] == 'flight' and b['title'] == 'Flight · Copenhagen → Berlin' and b['place'] == 'Berlin' and b['ref'] == 'ABC12D'
   and b['start'][:10] == '2026-11-18' and b['end'][:10] == '2026-11-22', 'a flight: route, dates without a year, reference – not the word "Confirmation"')
b, _ = T.from_text('Reservationsbekræftelse — Acme Inn Odense', 'noreply@acme-inn.example', 'Reservationsnummer: 5550001111\nHotel check-in 26.09.2027, check-out 27.09.2027',
                   today, sent, 'Acme Inn')
ok(b and b['kind'] == 'hotel' and b['title'] == 'Acme Inn Odense' and b['place'] == 'Odense' and b['end'][:10] == '2027-09-27',
   'a hotel that is not on the travel list: booking words + hotel words, name and town from the subject')
b, _ = T.from_text('Your Dec-02-2026 Confirmation #5550002222', 'reply@acme-hotels.example', 'Arrival Dec 2, 2026  Departure Dec 3, 2026', today, sent, 'Acme Hotels')
ok(b and b['start'][:10] == '2026-12-02' and b['end'][:10] == '2026-12-03' and b['ref'] == '5550002222', 'one date in the subject, the end date from the text')
_, why = T.from_text('Order confirmation', 'shop@acme-shop.example', 'Order number 55667788 delivery 20 March 2027', today, sent)
ok(why == 'not travel', 'a shop order is still not a booking')
_, why = T.from_text('Your trip to Odense', 'noreply@hotels.example', 'Thanks for staying with us in March 2026', today, sent)
ok(why in ('no dates', 'already over', 'not travel'), 'a mail about a stay that is over gives no booking')

# ---- grouping, upcoming only
all_b = []
for o in (flight, hotel, ferry, past, weekend):
    x = T.from_reservation(o)
    x['source'] = {'account': 'iCloud', 'message_id': 'm-' + x['ref']}
    x['key'] = T.key_of(x)
    all_b.append(x)
trips = T.group(all_b, today)
ok(len(trips) == 2, 'two trips: the weekend and the October journey; a flight over a year ago is left out')
jul = trips[1]
ok(len(jul['bookings']) == 3 and jul['title'] == 'Lisbon, Douro and more, Oct 2027', 'the October trip: flight, camp and ferry as one, named after its places')
ok(trips[0]['title'] == 'Aarhus, Dec 2026', '… and the jazz night on its own')

# ---- suggestions you confirm
d = tempfile.mkdtemp()
st = T.Trips(d)
v = st.merge_scan(all_b, today)
ok(len(v['suggested']) == 2 and not v['trips'], 'a scan suggests – nothing becomes a trip by itself')
sid = next(t['id'] for t in v['suggested'] if 'Oct' in t['title'])
r = st.action('trip_confirm', {'id': sid, 'title': 'Lisbon and Porto'})
view = st.view(today)
ok(view['trips'][0]['title'] == 'Lisbon and Porto' and len(view['trips'][0]['bookings']) == 3 and len(view['suggested']) == 1,
   'Confirm: yours, with your name for it')
wid = view['suggested'][0]['id']
st.action('trip_dismiss', {'id': wid})
st.merge_scan(all_b, today)
ok(st.view(today)['suggested'] == [], 'Not a trip: never suggested again; a confirmed trip\'s bookings are not suggested twice')
extra = dict(T.from_reservation(dict(hotel, reservationNumber='H-2', checkinTime='2027-10-16T14:00:00+01:00', checkoutTime='2027-10-20T10:00:00+01:00',
                                     reservationFor={'@type': 'LodgingBusiness', 'name': 'Beach House', 'address': {'addressLocality': 'Troia'}})),
             source={'account': 'iCloud', 'message_id': 'm-h2'})
extra['key'] = T.key_of(extra)
st.merge_scan(all_b + [extra], today)
t = st.view(today)['trips'][0]
ok(len(t.get('new', [])) == 1 and len(t['bookings']) == 3, 'a new booking inside a confirmed trip is offered, not added by itself')
st.action('trip_apply_new', {'id': t['id']})
t = st.view(today)['trips'][0]
ok(len(t['bookings']) == 4 and t['end'].startswith('2027-10-20') and not t['new'], '… Add puts it in and moves the end date')
st.action('trip_remove', {'id': t['id']})
ok(st.view(today)['trips'] == [], 'Remove: off the list')
st.action('trip_restore', {'backup': t['id']})
ok(st.view(today)['trips'][0]['id'] == t['id'], '… and Restore (activity log) brings it back')
ok(st.view(datetime.date(2027, 11, 1))['trips'] == [] and st.view(datetime.date(2027, 11, 1))['past'], 'after the trip: under past trips')
ok(oct(os.stat(st.file).st_mode)[-3:] == '600', 'state/trips.json is readable by the owner only')

# ---- a second scan reads better: the same mail updates its booking in a confirmed trip, no duplicates
st2 = T.Trips(tempfile.mkdtemp())
old = dict(T.from_text('Din booking er bekræftet - Copenhagen til Vienna, 16 dec - 18 dec', 'no-reply@acme-air.example', 'Fly AX 7, afgang 06:45', today, sent)[0] or {})
old.update(title='Din booking er bekræftet', start='2026-12-18T00:00+01:00', end='2026-12-18T00:00+01:00', source={'message_id': 'sas-1@x'})
old['key'] = T.key_of(old, 0)
st2.merge_scan([old], today)
tid = st2.view(today)['suggested'][0]['id']
st2.action('trip_confirm', {'id': tid, 'title': 'Vienna'})
better = dict(old, title='Flight · Copenhagen → Vienna', start='2026-12-16T00:00+01:00', place='Vienna')
better['key'] = T.key_of(better, 0)
st2.merge_scan([better], today)
v2 = st2.view(today)
ok(len(v2['trips']) == 1 and v2['trips'][0]['bookings'][0]['title'] == 'Flight · Copenhagen → Vienna' and v2['trips'][0]['start'].startswith('2026-12-16')
   and v2['suggested'] == [], 'rescan: the confirmed trip\'s booking is updated from the same mail, not suggested twice')
st2.merge_scan([dict(better, key='other-key')], today)
ok(st2.view(today)['suggested'] == [], '… also when its key changed')

st3 = T.Trips(tempfile.mkdtemp())
st3.merge_scan([dict(old, place='', provider='Acme Air')], today)
st3.action('trip_confirm', {'id': st3.view(today)['suggested'][0]['id']})
before = st3.view(today)['trips'][0]['title']
st3.merge_scan([better], today)
ok(before != 'Vienna, Dec 2026' and st3.view(today)['trips'][0]['title'] == 'Vienna, Dec 2026', 'a name you didn\'t change follows the better reading ("Vienna", not the airline)')
# ---- the Berlin/Vienna mix-up (5 Nov): only bookings inside a trip's own dates are offered to it, one by one
st4 = T.Trips(tempfile.mkdtemp())
def bk(mid, kind, title, start, end=None, place=''):
    b = {'kind': kind, 'title': title, 'start': start + 'T00:00+01:00', 'end': (end or start) + 'T00:00+01:00', 'place': place,
         'ref': mid.upper(), 'provider': '', 'travellers': [], 'confidence': 'check', 'source': {'message_id': mid + '@x'}}
    b['key'] = T.key_of(b, 0)
    return b
lon = bk('lon', 'flight', 'Flight · Copenhagen → Berlin', '2026-11-18', '2026-11-22', 'Berlin')
st4.merge_scan([lon], today)
st4.action('trip_confirm', {'id': st4.view(today)['suggested'][0]['id']})
dinner = bk('din', 'restaurant', 'Table at Acme Grill', '2026-11-21')
zrh = bk('vie', 'flight', 'Flight · Copenhagen → Vienna', '2026-12-16', '2026-12-18', 'Vienna')
long_ = bk('long', 'booking', 'Reservations', '2026-11-20', '2026-12-18')      # a booking stretched over weeks
st4.merge_scan([lon, dinner, zrh, long_], today)
v4 = st4.view(today)
new = [b['ref'] for b in v4['trips'][0]['new']]
ok('DIN' in new and 'VIE' not in new, 'a dinner inside the Berlin dates is offered to Berlin; the Vienna flight is not')
ok(any('VIE' in [b['ref'] for b in t['bookings']] for t in v4['suggested']), '… Vienna is a suggestion of its own')
tid = v4['trips'][0]['id']
st4.action('trip_not_part', {'id': tid, 'keys': [long_['key']]})
st4.merge_scan([lon, dinner, zrh, long_], today)
ok('LONG' not in [b['ref'] for b in st4.view(today)['trips'][0]['new']], '"Not part of this trip": never offered to it again')
st4.action('trip_apply_new', {'id': tid, 'keys': [dinner['key']]})
ok([b['ref'] for b in st4.view(today)['trips'][0]['bookings']] == ['LON', 'DIN'], 'Add takes only the bookings you picked')
b, _ = T.from_text('Your reservation at Acme Grill', 'hello@acme-grill.example', 'Booking reference: R12345. Table for 2 on 21/11/2026. '
                   'Gift cards valid until 31/12/2026. Applicable to Acme Circle members.', today, sent)
ok(b and b['end'][:10] == b['start'][:10] == '2026-11-21' and '→' not in b['title'], 'a table is one day; a stray date or "applicable to" in the text is not a route')
# ---- mails the scan couldn't read: put in a trip by hand, or "Not travel"
st5 = T.Trips(tempfile.mkdtemp())
mails = [{'account': 'iCloud', 'message_id': 'et-%d@x' % i, 'subject': 'Electronic ticket %d' % i, 'date': '2026-10-10T09:00:00+02:00',
          'from': 'Acme Air', 'why': 'no dates'} for i in range(3)]
st5.set_unsorted(mails)
ok(len(st5.view(today)['unsorted']) == 3, 'unread travel mails are kept on the Trips page')
r = st5.action('trip_mail_new', {'message_id': 'et-0@x', 'trip_title': 'Lisbon and Porto', 'date': '2027-09-26', 'kind': 'flight',
                                 'title': 'Flight to Lisbon'})
t = st5.view(today)['trips'][0]
ok(t['title'] == 'Lisbon and Porto' and t['bookings'][0]['start'].startswith('2027-09-26') and t['bookings'][0]['confidence'] == 'manual',
   'New trip from a mail: your name, on the day you give')
st5.action('trip_mail_add', {'id': r['id'], 'message_id': 'et-1@x', 'date': '2027-10-10', 'kind': 'flight', 'title': 'Flight home'})
t = st5.view(today)['trips'][0]
ok(len(t['bookings']) == 2 and t['end'].startswith('2027-10-10'), 'Add to trip: the trip grows to the new day')
nt = st5.action('trip_mail_not_travel', {'message_id': 'et-2@x'})
ok(st5.view(today)['unsorted'] == [], 'Not travel: off the list')
st5.set_unsorted(mails)
ok(st5.view(today)['unsorted'] == [], '… and a new scan doesn\'t bring placed or "not travel" mails back')
st5.action('trip_undismiss', {'keys': nt['keys']})
ok([m['message_id'] for m in st5.view(today)['unsorted']] == ['et-2@x'], 'Undo "Not travel": back on the list')
try:
    st5.action('trip_mail_add', {'id': r['id'], 'message_id': 'et-2@x', 'date': 'soon'})
    ok(False, 'a mail without a day is refused')
except T.Bad:
    ok(True, 'a mail without a day is refused')
st5.action('trip_mail_add', {'id': r['id'], 'message_id': 'found-1@x', 'date': '2027-09-27', 'kind': 'hotel', 'title': 'Wine estate',
                             'mail': {'account': 'iCloud', 'message_id': 'found-1@x', 'subject': 'Your stay', 'from': 'Acme Camp'}})
ok(any(b['source']['message_id'] == 'found-1@x' for b in st5.view(today)['trips'][0]['bookings']), '"Add a mail…": a mail found by search goes in the trip')
try:
    st5.action('trip_mail_add', {'id': r['id'], 'message_id': 'found-1@x', 'date': '2027-09-27', 'mail': {'account': 'iCloud', 'message_id': 'found-1@x'}})
    ok(False, 'the same mail twice is refused')
except T.Bad:
    ok(True, 'the same mail twice is refused')
# ---- into a trip you already have: from a suggestion, between trips; a removed trip can be brought back
st6 = T.Trips(tempfile.mkdtemp())
portugal = bk('ke1', 'flight', 'Flight · Copenhagen → Lisbon', '2027-09-26', place='Lisbon')
st6.merge_scan([portugal], today)
st6.action('trip_confirm', {'id': st6.view(today)['suggested'][0]['id'], 'title': 'Portugal'})
camp = bk('camp', 'hotel', 'Stay · Acme Camp', '2027-10-06', '2027-10-08')
beach = bk('beach', 'hotel', 'Stay · Acme Beach', '2027-10-07', '2027-10-09')
st6.merge_scan([portugal, camp, beach], today)
v6 = st6.view(today)
kid = v6['trips'][0]['id']
st6.action('trip_suggest_add', {'id': v6['suggested'][0]['id'], 'to': kid, 'bookings': [camp['key']]})
v6 = st6.view(today)
ok([b['ref'] for b in v6['trips'][0]['bookings']] == ['KE1', 'CAMP'] and [b['ref'] for s_ in v6['suggested'] for b in s_['bookings']] == ['BEACH'],
   'a ticked booking from a suggestion goes into an existing trip; the rest stay suggested')
st6.action('trip_confirm', {'id': v6['suggested'][0]['id'], 'title': 'Beach'})
bid = next(t['id'] for t in st6.view(today)['trips'] if t['title'] == 'Beach')
st6.action('trip_move_booking', {'id': bid, 'key': beach['key'], 'to': kid})
v6 = st6.view(today)
ok(len(v6['trips']) == 1 and len(v6['trips'][0]['bookings']) == 3 and v6['removed'] == [],
   'moving a trip\'s last booking elsewhere: one trip with all three, the empty one gone (not under "removed")')
st6.action('trip_move_booking', {'id': kid, 'key': beach['key'], 'to': bid})
v6 = st6.view(today)
ok(sorted(t['title'] for t in v6['trips']) == ['Beach', 'Portugal'] and [b['ref'] for t in v6['trips'] if t['title'] == 'Beach' for b in t['bookings']] == ['BEACH'],
   '… and Undo brings the emptied trip back with its booking')
st6.action('trip_move_booking', {'id': bid, 'key': beach['key'], 'to': kid})
st6.merge_scan([portugal, camp, beach], today)
ok(st6.view(today)['suggested'] == [], '… and nothing is suggested twice')
st6.action('trip_remove', {'id': kid})
ok(st6.view(today)['trips'] == [] and st6.view(today)['removed'][0]['title'] == 'Portugal', 'a removed trip is listed under "removed"')
st6.action('trip_restore', {'id': kid})
ok(st6.view(today)['trips'][0]['title'] == 'Portugal' and len(st6.view(today)['trips'][0]['bookings']) == 3, '… and Restore brings it back whole')
# ---- Remove a trip (filed wrongly): its bookings come back as suggestions at once, and on every rescan
st7 = T.Trips(tempfile.mkdtemp())
stay = bk('stay7', 'hotel', 'Stay · Acme Lodge', '2027-09-30', '2027-10-01')
st7.merge_scan([stay], today)
t7 = st7.action('trip_confirm', {'id': st7.view(today)['suggested'][0]['id']})['id']
st7.action('trip_remove', {'id': t7})
ok([b['ref'] for s_ in st7.view(today)['suggested'] for b in s_['bookings']] == ['STAY7'], 'Remove: the booking is a suggestion again right away')
st7.merge_scan([stay], today)
ok([b['ref'] for s_ in st7.view(today)['suggested'] for b in s_['bookings']] == ['STAY7'], '… and a rescan keeps suggesting it (once)')
d7 = st7.load(); d7['dismissed'] = [stay['key'], 'm:stay7@x']; st7._save(d7)          # removed before this fix
st7.merge_scan([stay], today)
ok(len(st7.view(today)['suggested']) == 1, 'a trip removed with the old rule: its booking comes back on the next scan')
st7.action('trip_restore', {'id': t7})
ok(st7.view(today)['suggested'] == [] and len(st7.view(today)['trips']) == 1, 'Restore: back in the trip, not also suggested')
# ---- removed, then its booking refiled into another trip by hand: it leaves "Removed trips" on its own
st9 = T.Trips(tempfile.mkdtemp())
s9 = bk('stay9', 'hotel', 'Stay', '2027-09-30', '2027-10-01')
f9 = bk('fl9', 'flight', 'Flight · Copenhagen → Lisbon', '2027-09-26', '2027-09-26')
st9.merge_scan([s9, f9], today)
for sg in st9.view(today)['suggested']:
    st9.action('trip_confirm', {'id': sg['id']})
ts9 = st9.view(today)['trips']
one = next(t for t in ts9 if t['bookings'][0]['key'] == s9['key'])
other = next(t for t in ts9 if t['id'] != one['id'])
st9.action('trip_remove', {'id': one['id']})
ok(len(st9.view(today)['removed']) == 1, 'a removed trip is listed under "Removed trips"')
sg9 = st9.view(today)['suggested'][0]
st9.action('trip_suggest_add', {'id': sg9['id'], 'to': other['id']})
ok(st9.view(today)['removed'] == [], '… and once its booking is filed into another trip, it is no longer listed there')
d9 = st9.load(); d9['removed'] = [dict(one, bookings=[dict(s9, key='other-key')])]; st9._save(d9)
ok(st9.view(today)['removed'] == [], '… also when Claude has since read the same mail (other key, same mail)')
# ---- what Claude read (trip-read.md): checked, then the real legs replace a mail put in a trip by hand
st8 = T.Trips(tempfile.mkdtemp())
st8.set_unsorted([{'account': 'iCloud', 'message_id': 'ax@x', 'subject': 'E-Documents for ALEX EXAMPLE', 'date': '2026-10-10', 'from': 'Acme Airways'},
                  {'account': 'iCloud', 'message_id': 'quote@x', 'subject': 'Quote request: Acme Camp', 'date': '2026-10-24', 'from': 'Acme Camp'},
                  {'account': 'iCloud', 'message_id': 'old@x', 'subject': 'We hope you enjoyed your stay', 'date': '2025-08-04', 'from': 'Acme Inn'}])
k = st8.action('trip_mail_new', {'message_id': 'ax@x', 'trip_title': 'Portugal', 'date': '2027-09-26', 'kind': 'flight', 'title': 'E-Documents'})['id']
asked = [{'account': 'iCloud', 'message_id': m, 'subject': 'S'} for m in ('ax@x', 'quote@x', 'old@x')]
result = {'bookings': [
    {'message_id': 'ax@x', 'kind': 'flight', 'status': 'booked', 'title': 'AX 101 Copenhagen → Lisbon', 'start': '2027-09-26T10:40:00+02:00',
     'end': '2027-09-26T21:15:00+01:00', 'from': 'CPH', 'to': 'LIS', 'place': 'Lisbon', 'ref': 'ABC123', 'provider': 'Acme Airways',
     'number': 'AX 101', 'travellers': ['ALEX EXAMPLE'], 'ticket': 0},
    {'message_id': 'ax@x', 'kind': 'flight', 'status': 'booked', 'title': 'AX 100 Lisbon → Copenhagen', 'start': '2027-10-12T23:50:00+01:00',
     'end': '2027-10-13T07:30:00+02:00', 'place': 'Copenhagen', 'ref': 'ABC123'},
    {'message_id': 'quote@x', 'kind': 'hotel', 'status': 'quote', 'title': 'Acme Camp – quote requested', 'start': '2027-09-28', 'end': '2027-10-01'},
    {'message_id': 'not-asked@x', 'kind': 'hotel', 'status': 'booked', 'title': 'Injected', 'start': '2027-09-28'},
    {'message_id': 'ax@x', 'kind': 'spaceship', 'status': 'booked', 'title': 'Bad date', 'start': 'next summer'}],
    'none': [{'message_id': 'old@x', 'reason': 'a past stay'}]}
bs, none = T.clean_read(result, asked)
ok(len(bs) == 3 and all(b['source']['message_id'] in ('ax@x', 'quote@x') for b in bs), 'only mails that were asked for, with real dates – the rest is dropped')
T.take_read(st8, bs, none, today)
v8 = st8.view(today)
t8 = v8['trips'][0]
ok([b['title'] for b in t8['bookings']] == ['AX 101 Copenhagen → Lisbon', 'AX 100 Lisbon → Copenhagen']
   and t8['start'].startswith('2027-09-26T10:40') and t8['end'].startswith('2027-10-13'), 'the hand-placed mail becomes its real flights, out and home, with times')
ok(t8['bookings'][0]['travellers'] == ['ALEX EXAMPLE'] and t8['bookings'][0]['ticket'] == 0, '… with travellers and which attachment is the ticket')
ok([q['title'] for q in v8['quotes']] == ['Acme Camp – quote requested'] and not v8['suggested'], 'a quote is kept as planning, not suggested as a booking')
ok(v8['unsorted'] == [], 'read mails leave "To sort" (the past stay with its reason)')
cancel = [dict(bs[0], status='cancelled', title='Cancelled', source={'message_id': 'cx@x'})]
T.take_read(st8, cancel, [], today, trust=OWN)
ok(st8.view(today)['trips'][0]['bookings'][0].get('status') == 'cancelled', 'a cancellation marks the booking with the same reference')
# ---- duplicates: the rules' "Copenhagen → Vienna, 16–18 Dec" and Claude's AX 601 / AX 602 from the e-ticket
st10 = T.Trips(tempfile.mkdtemp())
rule = dict(bk('conf10', 'flight', 'Flight · Copenhagen → Vienna', '2026-12-16', '2026-12-18'), place='Vienna', ref='')
st10.merge_scan([rule], today)
z = st10.action('trip_confirm', {'id': st10.view(today)['suggested'][0]['id']})['id']
leg = lambda n, a, b_, at, to: {'kind': 'flight', 'status': 'booked', 'title': 'AX %s %s → %s' % (n, a, b_), 'start': at, 'end': at,
                                'from': a, 'to': b_, 'place': b_, 'ref': 'ACME10', 'provider': 'Acme Air', 'number': 'AX ' + n,
                                'travellers': ['ALEX EXAMPLE'], 'confidence': 'read', 'source': {'message_id': 'tkt10@x'}}
out = [leg('601', 'Copenhagen', 'Vienna', '2026-12-16T07:55:00+01:00', '')]
out[0]['key'] = T.key_of(out[0], 0)
d10 = st10.load(); d10['trips'][0]['bookings'].append(out[0]); st10._save(d10)
ok(len(st10.view(today)['trips'][0]['bookings']) == 2, 'only the outbound leg read: the rules\' return booking stays (its way back is not covered)')
back = leg('602', 'Vienna', 'Copenhagen', '2026-12-18T10:25:00+01:00', '')
back['key'] = T.key_of(back, 1)
d10 = st10.load(); d10['trips'][0]['bookings'].append(back); st10._save(d10)
t10 = st10.view(today)['trips'][0]
ok([b['number'] for b in t10['bookings']] == ['AX 601', 'AX 602'] and len(t10['voided']) == 1, 'both legs read: the rules\' duplicate is voided on its own')
st10.action('trip_unvoid', {'id': z, 'key': rule['key']})
t10 = st10.view(today)['trips'][0]
ok(len(t10['bookings']) == 3 and not t10['voided'], 'Restore under Voided: it is back, and stays (it is yours now)')
st10.action('trip_void', {'id': z, 'key': rule['key']})
t10 = st10.view(today)['trips'][0]
ok(len(t10['bookings']) == 2 and t10['voided'][0]['voided'] == 'you', 'Void on a booking: off the trip, under Voided')
st10.merge_scan([rule], today)
ok(len(st10.view(today)['trips'][0]['bookings']) == 2 and st10.view(today)['suggested'] == [], '… and a rescan does not bring it back')
try:
    st6b = T.Trips(tempfile.mkdtemp()); st6b.merge_scan([rule], today)
    z6 = st6b.action('trip_confirm', {'id': st6b.view(today)['suggested'][0]['id']})['id']
    st6b.action('trip_void', {'id': z6, 'key': rule['key']}); ok(False, 'the only booking: Void says remove the trip instead')
except T.Bad:
    ok(len(st6b.view(today)['trips'][0]['bookings']) == 1, 'the only booking: Void says remove the trip instead')
ok(not T.same_booking(dict(rule, title='Flight · Copenhagen → Berlin', place='Berlin'), out[0]), 'another route the same day is not a duplicate')
h1 = dict(bk('h1', 'hotel', 'Stay', '2027-09-30', '2027-10-01'), ref=''); h2 = dict(bk('h2', 'hotel', 'Acme Lodge', '2027-09-30', '2027-10-01'), confidence='read')
ok(T.same_booking(h1, h2) and not T.same_booking(h1, dict(h2, end='2027-10-03')), 'a stay without a reference: same nights is a duplicate, other nights are not')
st11 = T.Trips(tempfile.mkdtemp()); st11.merge_scan([rule], today)
z11 = st11.action('trip_confirm', {'id': st11.view(today)['suggested'][0]['id']})['id']
a1 = dict(out[0], travellers=['ALEX EXAMPLE'], key='a1'); a2 = dict(out[0], travellers=['SAM EXAMPLE'], key='a2', source={'message_id': 'tkt11@x'})
d11 = st11.load(); d11['trips'][0]['bookings'] += [a1, a2]; st11._save(d11)
t11 = st11.view(today)['trips'][0]
ok([b['travellers'] for b in t11['bookings'] if b.get('number') == 'AX 601'] == [['ALEX EXAMPLE', 'SAM EXAMPLE']], 'the same flight on two e-tickets: one booking with both travellers')
# ---- each traveller's own e-ticket: one booking, everyone on it, every ticket openable; read mails stay out of To sort
st12 = T.Trips(tempfile.mkdtemp()); st12.merge_scan([rule], today)
st12.action('trip_confirm', {'id': st12.view(today)['suggested'][0]['id']})
e1 = dict(out[0], travellers=['ALEX EXAMPLE'], key='e1', ticket=0, source={'account': 'iCloud', 'message_id': 'e1@x'})
e2 = dict(out[0], travellers=['SAM EXAMPLE'], key='e2', ticket=1, source={'account': 'iCloud', 'message_id': 'e2@x'})
d12 = st12.load(); d12['trips'][0]['bookings'] += [e1, e2]; d12['read_none'] = [{'message_id': 'nb@x', 'reason': 'a newsletter', 'v': 2}]; st12._save(d12)
f12 = [b for b in st12.view(today)['trips'][0]['bookings'] if b.get('number') == 'AX 601'][0]
ok(f12['travellers'] == ['ALEX EXAMPLE', 'SAM EXAMPLE'] and f12['tickets'] == [{'account': 'iCloud', 'message_id': 'e2@x', 'ticket': 1, 'travellers': ['SAM EXAMPLE']}],
   'the second traveller\'s e-ticket joins the booking, and its ticket is kept')
st12.set_unsorted([{'message_id': m, 'subject': 'S'} for m in ('e1@x', 'e2@x', 'nb@x', 'fresh@x')])
ok([u['message_id'] for u in st12.view(today)['unsorted']] == ['fresh@x'], 'a rescan does not put mails back in To sort that are in a trip, joined, or already read by Claude')
# ---- a mail Claude could not open was not read: it stays in To sort, and so does one an older run gave up on
st13 = T.Trips(tempfile.mkdtemp())
st13.set_unsorted([{'account': 'iCloud', 'message_id': 'ax2@x', 'subject': 'E-Documents for SAM EXAMPLE'}])
T.take_read(st13, [], [{'message_id': 'ax2@x', 'reason': 'could not be opened'}], today)
ok([u['message_id'] for u in st13.view(today)['unsorted']] == ['ax2@x'] and not st13.load()['read_none'], 'could not be opened: still in To sort, not counted as read')
d13 = st13.load(); d13['read_none'] = [{'message_id': 'ax2@x', 'reason': 'Could not be opened (sender in request is only a display name)'}]; st13._save(d13)
st13.set_unsorted([{'account': 'iCloud', 'message_id': 'ax2@x', 'subject': 'E-Documents for SAM EXAMPLE'}])
ok([u['message_id'] for u in st13.view(today)['unsorted']] == ['ax2@x'], '… and an older run\'s "could not be opened" does not keep it out of To sort')
# ---- edit a booking's day and time (a wrong date typed by hand): the place's offset kept, the trip's dates follow
st14 = T.Trips(tempfile.mkdtemp())
jz = dict(bk('jazz', 'restaurant', 'Order Confirmation - Acme Jazz Club', '2026-11-18'), start='2026-11-18T00:00:00+00:00', end='2026-11-18T00:00:00+00:00')
fl = bk('fl14', 'flight', 'Flight · Copenhagen → Berlin', '2026-11-18', '2026-11-22', 'Berlin')
st14.merge_scan([jz, fl], today)
z14 = st14.action('trip_confirm', {'id': st14.view(today)['suggested'][0]['id']})['id']
st14.action('trip_booking_edit', {'id': z14, 'key': jz['key'], 'name': 'Acme Jazz Club', 'day': '2026-11-20', 'time': '19:30'})
b14 = [b for b in st14.view(today)['trips'][0]['bookings'] if b['key'] == jz['key']][0]
ok(b14['title'] == 'Acme Jazz Club' and b14['start'] == '2026-11-20T19:30:00+00:00' and b14['end'] == b14['start'] and b14['confidence'] == 'manual',
   'Edit: name, day and time, in the place\'s own offset; no longer "check"')
st14.action('trip_booking_edit', {'id': z14, 'key': fl['key'], 'day': '2026-11-18', 'until': '2026-11-23'})
ok(st14.view(today)['trips'][0]['end'].startswith('2026-11-23'), '… the trip\'s dates follow the bookings')
try:
    st14.action('trip_booking_edit', {'id': z14, 'key': fl['key'], 'day': '2026-11-24', 'until': '2026-11-23'}); ok(False, 'an end before the start is refused')
except T.Bad:
    ok(True, 'an end before the start is refused')
st14.merge_scan([jz, fl], today)
ok([b for b in st14.view(today)['trips'][0]['bookings'] if b['key'] == jz['key']][0]['start'].startswith('2026-11-20T19:30'), '… and a rescan doesn\'t change it back')
# ---- names: where you go, not home; work or private
nm = T.name_of([dict(fl, place='Berlin'), dict(fl, title='AX 1 Berlin → Copenhagen', start='2026-11-22T18:40:00+00:00', place='Copenhagen', **{'from': 'Berlin', 'to': 'Copenhagen'})])
ok(nm[0] == 'Berlin, Nov 2026', 'a trip is named after where you go, not the city you fly home to: ' + nm[0])
st14.action('trip_ctx', {'id': z14, 'ctx': 'work'})
ok(st14.view(today)['trips'][0]['ctx'] == 'work', 'a trip can be marked work (or private)')
# ---- the last 12 months too: a past trip is suggested under Past, one over a year ago is not
st15 = T.Trips(tempfile.mkdtemp())
ny = bk('ny15', 'flight', 'Flight · Copenhagen → Boston', '2026-10-21', '2026-10-24', 'Boston')
old15 = bk('old15', 'flight', 'Flight · Copenhagen → Rome', '2025-09-01', '2025-09-04', 'Rome')
st15.merge_scan([ny, old15], today)
v15 = st15.view(today)
ok(v15['suggested'] == [] and [t['title'] for t in v15['past_suggested']] == ['Boston, Oct 2026'], 'a trip that ended last week is suggested under Past; one over a year ago is not')
st15.action('trip_confirm', {'id': v15['past_suggested'][0]['id']})
ok([t['title'] for t in st15.view(today)['past']] == ['Boston, Oct 2026'], '… confirmed, it is a past trip')
ok(T.from_text('Your booking ACME16', 'no-reply@acme-air.example', 'Flight 21 Oct 2026 Copenhagen', today, today)[1] != 'already over', 'the rules read a booking from last week')
st14.action('trip_booking_edit', {'id': z14, 'key': jz['key'], 'kind': 'ticket'})
ok([b for b in st14.view(today)['trips'][0]['bookings'] if b['key'] == jz['key']][0]['kind'] == 'ticket', 'Edit: the kind of booking too (a jazz club: Ticket, not Table)')
try:
    st14.action('trip_booking_edit', {'id': z14, 'key': jz['key'], 'kind': 'spaceship'}); ok(False, 'an unknown kind is refused')
except T.Bad:
    ok(True, 'an unknown kind is refused')
# ---- a forwarded e-ticket: its "Date:" header is when it was sent, not the trip; a rescan keeps what Claude read
fwd = 'From: no-reply@acme-air.example\nDate: Thursday, 15 October 2026 at 09.10\nSubject: Electronic Ticket Itinerary - Booking reference ACME16\n\nYour flight 21 Oct 2026 Copenhagen - Boston, return 24 Oct 2026.'
b16, why16 = T.from_text('FW: Electronic Ticket Itinerary and Receipt - Booking reference ACME16', '', fwd, today, datetime.date(2026, 10, 15))
ok(b16 and b16['start'].startswith('2026-10-21'), 'a forwarded ticket: the trip\'s date, not the forward\'s "Date:" line (%s)' % (b16 or {}).get('start'))
st16 = T.Trips(tempfile.mkdtemp())
rb = dict(bk('fw16', 'flight', 'Flight · Copenhagen → Boston', '2026-10-15'), key='fw16-0')
st16.merge_scan([rb], today)
rd = dict(rb, key='fw16-r', title='AX 915 Copenhagen → Boston', start='2026-10-21T09:35:00+01:00', end='2026-10-21T11:50:00-04:00', confidence='read', status='booked')
T.take_read(st16, [rd], [], today)
ok([b['title'] for x in st16.view(today)['past_suggested'] for b in x['bookings']] == ['AX 915 Copenhagen → Boston'], 'Claude\'s reading replaces the rules\' copy in a suggestion')
st16.merge_scan([rb], today)
ok([b['title'] for x in st16.view(today)['past_suggested'] for b in x['bookings']] == ['AX 915 Copenhagen → Boston'], '… and a rescan keeps it (the rules\' copy does not come back)')
d16 = st16.load(); d16['read_none'] = [{'message_id': 'x@x', 'reason': 'AX 915 / AX 916 has already ended'}, {'message_id': 'y@x', 'reason': 'ended over a year ago', 'v': 2}]; st16._save(d16)
ok([n['message_id'] for n in st16.load()['read_none']] == ['y@x'], 'an older run\'s "it has ended" (upcoming only then) no longer keeps a mail out')
# ==== review fixes (dev request "Trips: review fixes and Scan since"), invented data ====
# 2: two rooms on the same nights with different references are not duplicates
r1 = dict(bk('rm1', 'hotel', 'Acme Lodge', '2027-03-10', '2027-03-12'), ref='ROOM1', confidence='read')
r2 = dict(bk('rm2', 'hotel', 'Stay', '2027-03-10', '2027-03-12'), ref='ROOM2')
ok(not T.same_booking(r2, r1), 'two stays on the same nights with different references are not duplicates')
f1 = dict(bk('pa', 'flight', 'Flight · Copenhagen → Berlin', '2027-03-10'), ref='PNR1')
f2 = dict(bk('pb', 'flight', 'Flight · Copenhagen → Berlin', '2027-03-10'), ref='PNR2', confidence='read')
ok(not T.same_booking(f1, f2), 'two flights on the same route and day with different references are not duplicates')
# 1: a reading that finds only a quote leaves the trip its booking (never empty), and scans keep working
st20 = T.Trips(tempfile.mkdtemp())
st20.set_unsorted([{'account': 'iCloud', 'message_id': 'q20@x', 'subject': 'Your enquiry'}])
z20 = st20.action('trip_mail_new', {'message_id': 'q20@x', 'trip_title': 'Acme Valley', 'date': '2027-04-02', 'kind': 'hotel', 'title': 'Acme Lodge'})['id']
T.take_read(st20, [{'message_id': 'q20@x', 'kind': 'hotel', 'status': 'quote', 'title': 'Acme Lodge – quote', 'start': '2027-04-02', 'end': '2027-04-05',
                    'source': {'message_id': 'q20@x'}, 'key': 'q20-0', 'confidence': 'read', 'travellers': [], 'place': '', 'ref': '', 'provider': ''}], [], today)
t20 = st20.view(today)['trips'][0]
ok(len(t20['bookings']) == 1 and t20['planning'], 'a reading that finds only a quote: the trip keeps its booking, the quote goes to Planning')
try:
    st20.merge_scan([], today); ok(True, '… and a later scan works')
except Exception as e:
    ok(False, '… and a later scan works (%s)' % e)
d20 = st20.load(); d20['trips'][0]['bookings'] = []; st20._save(d20)
try:
    st20.merge_scan([], today); st20.view(today); ok(True, 'even a trip with no bookings left does not stop a scan')
except Exception as e:
    ok(False, 'even a trip with no bookings left does not stop a scan (%s)' % e)
# 3: a cancellation marks only the leg it names, and a rescan keeps it
st21 = T.Trips(tempfile.mkdtemp())
o21 = dict(bk('l21', 'flight', 'Flight · Copenhagen → Oslo', '2027-05-01'), ref='PNR21', number='AX 11', confidence='read')
b21 = dict(bk('l21', 'flight', 'Flight · Oslo → Copenhagen', '2027-05-04'), ref='PNR21', number='AX 12', confidence='read', key='l21-1')
st21.merge_scan([o21, b21], today)
z21 = st21.action('trip_confirm', {'id': st21.view(today)['suggested'][0]['id']})['id']
T.take_read(st21, [dict(b21, status='cancelled', source={'message_id': 'cx21@x'}, key='cx21-0')], [], today, trust=OWN)
ok([b.get('status') for b in st21.view(today)['trips'][0]['bookings']] == [None, 'cancelled'], 'a cancelled leg: only that leg, not every booking with the reference')
c21 = dict(bk('c21', 'flight', 'Flight · Copenhagen → Oslo', '2027-05-01'), ref='PNR9')
st21b = T.Trips(tempfile.mkdtemp()); st21b.merge_scan([c21], today)
st21b.action('trip_confirm', {'id': st21b.view(today)['suggested'][0]['id']})
d21 = st21b.load(); d21['trips'][0]['bookings'][0]['status'] = 'cancelled'; st21b._save(d21)
st21b.merge_scan([c21], today)
ok(st21b.view(today)['trips'][0]['bookings'][0].get('status') == 'cancelled', '… and a rescan keeps a cancelled booking cancelled')
# 4: Restore under Voided for a booking Claude read: it stays
st22 = T.Trips(tempfile.mkdtemp()); st22.merge_scan([rule], today)
z22 = st22.action('trip_confirm', {'id': st22.view(today)['suggested'][0]['id']})['id']
e1b = dict(out[0], key='v1', source={'account': 'iCloud', 'message_id': 'v1@x'}); e2b = dict(out[0], key='v2', source={'account': 'iCloud', 'message_id': 'v2@x'})
d22 = st22.load(); d22['trips'][0]['bookings'] += [e1b, e2b]; st22._save(d22)
st22.action('trip_unvoid', {'id': z22, 'key': 'v2'})
t22 = st22.view(today)['trips'][0]
ok('v2' in [b['key'] for b in t22['bookings']] and not any(b['key'] == 'v2' for b in t22.get('voided', [])), 'Restore under Voided: a booking Claude read stays restored')
# 5: your name and kind survive a reading of the same mail; a removed trip's hand-made booking survives a rescan
st23 = T.Trips(tempfile.mkdtemp())
st23.set_unsorted([{'account': 'iCloud', 'message_id': 'h23@x', 'subject': 'Booking'}])
z23 = st23.action('trip_mail_new', {'message_id': 'h23@x', 'trip_title': 'Oslo', 'date': '2027-06-02', 'kind': 'hotel', 'title': 'Stay'})['id']
k23 = st23.view(today)['trips'][0]['bookings'][0]['key']
st23.action('trip_booking_edit', {'id': z23, 'key': k23, 'name': 'Acme Fjord Hotel', 'kind': 'hotel'})
T.take_read(st23, [{'message_id': 'h23@x', 'kind': 'booking', 'status': 'booked', 'title': 'Reservation 4711', 'start': '2027-06-02', 'end': '2027-06-04',
                    'source': {'message_id': 'h23@x'}, 'key': 'h23-r', 'confidence': 'read', 'travellers': [], 'place': 'Oslo', 'ref': 'R4711', 'provider': ''}], [], today)
b23 = st23.view(today)['trips'][0]['bookings'][0]
ok(b23['title'] == 'Acme Fjord Hotel' and b23['ref'] == 'R4711', 'your own name survives a reading of the same mail (and the reading adds the reference)')
st23.action('trip_remove', {'id': z23})
st23.merge_scan([], today)
ok(any(b['ref'] == 'R4711' for x in st23.view(today)['suggested'] for b in x['bookings']), 'a removed trip\'s read booking is still suggested after a rescan')
# 7: Undo of "Not a trip" brings the suggestion back
st24 = T.Trips(tempfile.mkdtemp()); st24.merge_scan([dict(bk('n24', 'flight', 'Flight · Copenhagen → Boston', '2027-02-01'))], today)
sg24 = st24.view(today)['suggested'][0]
keys24 = st24.action('trip_dismiss', {'id': sg24['id']})['keys']
st24.action('trip_undismiss', {'keys': keys24})
ok([x['id'] for x in st24.view(today)['suggested']] == [sg24['id']], 'Undo of "Not a trip" brings the suggestion back')
st24.merge_scan([dict(bk('n24', 'flight', 'Flight · Copenhagen → Boston', '2027-02-01'))], today)
ok(len(st24.view(today)['suggested']) == 1, '… and it is suggested on the next scan too')

# 8: a time in local time follows summer time; a place's own offset is kept
os.environ['TZ'] = 'Europe/Copenhagen'; time.tzset()
ok(T._when_of('2027-07-10', '10:00', '2026-11-18T00:00:00+01:00') == '2027-07-10T10:00:00+02:00', 'a local time in July gets summer time (+02:00)')
ok(T._when_of('2027-07-10', '10:00', '2026-11-18T09:00:00-05:00') == '2027-07-10T10:00:00-05:00', 'a time in another zone keeps that zone')
# 11: "+0200" without a colon keeps its time (Python 3.9)
ok(T.parse_when('2027-03-10T10:40:00+0200').hour == 10, 'a time with "+0200" keeps its time')
# B: scan since a date you pick
ok(T.from_text('Your booking ACME30', 'no-reply@acme-air.example', 'Flight 10 Mar 2025 Copenhagen', today, datetime.date(2025, 3, 1), since=datetime.date(2025, 1, 1))[1] != 'already over',
   'since a date you pick: a booking from before the 12 months is read')
st25 = T.Trips(tempfile.mkdtemp())
d25 = st25.load(); d25['since'] = '2025-01-01'; st25._save(d25)
st25.merge_scan([bk('old25', 'flight', 'Flight · Copenhagen → Oslo', '2025-03-10', '2025-03-12', 'Oslo')], today)
ok([x['title'] for x in st25.view(today)['past_suggested']] == ['Oslo, Mar 2025'], '… and its trip is suggested under Past')
st26 = T.Trips(tempfile.mkdtemp())
st26.merge_scan([dict(bk('w1', 'flight', 'Flight · Copenhagen → Oslo', '2027-05-01'), place='Oslo'),
                 dict(bk('w2', 'flight', 'Flight · Oslo → Copenhagen', '2027-05-04'), place='Copenhagen'),
                 dict(bk('w3', 'flight', 'Flight · Copenhagen → Berlin', '2027-05-20'), place='Berlin')], today)
ok(sorted(len(x['bookings']) for x in st26.view(today)['suggested']) == [1, 2], 'a flight out on Saturday and home on Tuesday are one trip; a later trip is its own')
st26.action('trip_confirm', {'id': next(x['id'] for x in st26.view(today)['suggested'] if len(x['bookings']) == 2)})
z26 = st26.view(today)['trips'][0]['id']
d26 = st26.load(); d26['trips'][0]['not_part'] = ['kx', 'ky']; st26._save(d26)
st26.action('trip_part_again', {'id': z26, 'keys': ['kx']})
ok(st26.load()['trips'][0]['not_part'] == ['ky'], 'Undo of "not part of this trip"')
# ---- answers from the older reading instructions don't count: the mail is back in To sort (dev request "re-read old readings")
st27 = T.Trips(tempfile.mkdtemp())
d27 = st27.load(); d27['read_none'] = [{'message_id': 'sam-ticket@x', 'reason': "Sam Example's e-ticket for the same flights"},
                                       {'message_id': 'news@x', 'reason': 'a newsletter', 'v': 2}]; st27._save(d27)
st27.set_unsorted([{'account': 'iCloud', 'message_id': m, 'subject': 'S'} for m in ('sam-ticket@x', 'news@x')])
ok([u['message_id'] for u in st27.view(today)['unsorted']] == ['sam-ticket@x'], 'an answer from the older instructions: back in To sort; a current one stays out')
# ---- airline "E-Documents" mails are found (dev request "e-documents"), invented subjects and senders
ok(T.looks_like_booking('Acme Air E-Documents for ALEX EXAMPLE for travel on 11SEP', 'noreply@acme-air.example'), 'an airline "E-Documents … for travel on" mail is a booking candidate')
ok(T.looks_like_booking('Your travel documents', 'x@example.org') and T.looks_like_booking('Electronic Ticket Receipt', 'x@example.org'), '"travel documents" and "electronic ticket" too')
ok(not T.looks_like_booking('Our autumn newsletter', 'news@acme.example'), 'an ordinary newsletter is not')
# ---- a booking-word mail whose details are only in its PDF goes to To sort (for Claude), not out as "not travel"
from email.message import EmailMessage as _EM
_m = _EM(); _m['Subject'] = 'Acme Air E-Documents for ALEX EXAMPLE for travel on 11SEP'; _m['From'] = 'Acme Air <noreply@acme-air.example>'
_m.set_content('Please find your documents attached.'); _m.add_attachment(b'%PDF-1.4 x', maintype='application', subtype='pdf', filename='eticket.pdf')
_why = []
ok(T.bookings_in(_m.as_bytes(), _m['Subject'], 'noreply@acme-air.example', today, why=_why) == [] and _why == [T.IN_PDF], 'details only in the PDF: "details in its PDF", not "not travel"')
_n = _EM(); _n['Subject'] = 'Your order confirmation'; _n.set_content('Thanks for your order.')
_why = []; T.bookings_in(_n.as_bytes(), _n['Subject'], 'shop@acme-shop.example', today, why=_why)
ok(_why == ['not travel'], 'a shop order without a PDF stays "not travel"')
# ---- another traveller's e-ticket, read later: joined onto the trip's flight with its own ticket, not dropped
st28 = T.Trips(tempfile.mkdtemp())
own = dict(out[0], key='own1', travellers=['ALEX EXAMPLE'], ticket=0, source={'account': 'iCloud', 'message_id': 'alex-et@x'})
st28.merge_scan([own], today)
z28 = st28.action('trip_confirm', {'id': st28.view(today)['suggested'][0]['id']})['id']
sam = dict(out[0], key='sam1', travellers=['SAM EXAMPLE'], ticket=0, status='booked', source={'account': 'iCloud', 'message_id': 'sam-et@x'})
T.take_read(st28, [sam], [], today)
f28 = st28.view(today)['trips'][0]['bookings'][0]
ok(f28['travellers'] == ['ALEX EXAMPLE', 'SAM EXAMPLE'] and [x['message_id'] for x in f28.get('tickets', [])] == ['sam-et@x'] and not st28.view(today)['trips'][0].get('new'),
   'another traveller\'s e-ticket read later: joined onto the flight with its own ticket, nothing to Add')
# ---- one person however the ticket prints the name
ok(T.person_key('Sam Example') == T.person_key('EXAMPLE SAM MSTR (CHD)') != T.person_key('Kim Example'), 'Sam Example and "EXAMPLE SAM MSTR (CHD)" are one person')
ok(T.add_people(['Alex Example', 'Sam Example'], ['EXAMPLE SAM MSTR (CHD)', 'Kim Example']) == ['Alex Example', 'Sam Example', 'Kim Example'], '… so a joined ticket doesn\'t add the name twice')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
