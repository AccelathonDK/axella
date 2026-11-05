#!/usr/bin/env python3
"""Trips v2, steps 3–5 (setup/trips.py): the calendar event and its bookkeeping, the Today card, updates (applied when
untouched, Apply / Ignore when you edited), check-in opening (the airline's mail, a learnt window, or an estimate),
the digest line and pushes near departure. Invented trips, places and references only.
Run: python3 setup/tests/test_trips_v2b.py"""
import datetime
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import trips as T  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def bk(key, kind, title, start, end=None, **x):
    b = {'key': key, 'kind': kind, 'status': 'booked', 'title': title, 'start': start, 'end': end or start, 'place': '', 'ref': '',
         'provider': '', 'travellers': ['Alex Example'], 'confidence': 'read',
         'source': {'account': 'iCloud', 'message_id': 'm-' + key, 'subject': title, 'date': '2027-02-01'}}
    b.update(x)
    b['source'].setdefault('address', 'bookings@%s.example' % str(b.get('provider') or 'unknown').lower().replace(' ', '-'))
    return b


# what axella-actions.py checks for real (scam check, sender checks, same domain as the booking's mail) – here the domain
# alone, and a mail marked "_flagged" fails
TRUST = lambda u, x: (T.mail_domain(u.get('source')) == T.mail_domain(x.get('source')) and not (u.get('source') or {}).get('_flagged'),
                      T.mail_domain(u.get('source')))


CET = datetime.timezone(datetime.timedelta(hours=2))
NOW = datetime.datetime(2027, 3, 1, 7, 0, tzinfo=CET)          # the morning of the way out
tmp = tempfile.mkdtemp()
st = T.Trips(tmp)
A = {'id': 'trA', 'title': 'Lakeby, Mar 2027', 'auto_title': False, 'ctx': 'private', 'created': '2027-01-01T10:00:00+01:00', 'bookings': [
    bk('a1', 'flight', 'AX 101 · Homeport → Lakeby', '2027-03-01T10:40:00+02:00', '2027-03-01T13:10:00+03:00', ref='QX7KLM', number='AX101', provider='Acme Air',
       address='Homeport T3', ticket=0),
    bk('a2', 'hotel', 'Lakeby Lodge', '2027-03-01T15:00:00+03:00', '2027-03-04T11:00:00+03:00', ref='LL-2231', provider='Lakeby Lodge'),
    bk('a3', 'flight', 'AX 205 · Lakeby → Homeport', '2027-03-04T13:00:00+03:00', '2027-03-04T14:00:00+02:00', ref='QX7KLM', number='AX205', provider='Acme Air'),
    bk('a4', 'ticket', 'Boat tour', '2027-03-02T00:00:00+03:00', ref='BT-1', status='cancelled', own_status=True)]}
W = {'id': 'trW', 'title': 'Acme workshop', 'auto_title': False, 'ctx': 'work', 'created': '2027-01-01T10:00:00+01:00', 'bookings': [
    bk('w1', 'train', 'Train · Homeport → Kimtown', '2027-03-20T08:00:00+02:00', '2027-03-20T10:00:00+02:00', ref='TR-77', number='IC 42', provider='Robin Rail')]}
for t_ in (A, W):
    T._span(t_)
json.dump({'trips': [A, W], 'suggested': []}, open(os.path.join(tmp, 'trips.json'), 'w'))
trip = lambda i: next(x for x in st.load()['trips'] if x['id'] == i)
bkg = lambda i, k: next(x for x in trip(i)['bookings'] if x['key'] == k)

# ---- the calendar event
ev = T.cal_event(trip('trA'), bkg('trA', 'a1'), 'Home', 'https://axella.example/axella')
ok(ev['start'] == '2027-03-01T10:40:00+02:00' and ev['end'] == '2027-03-01T13:10:00+03:00' and not ev['all_day'],
   'calendar: local times keep their own offsets (two zones)')
ok('Booking reference: QX7KLM' in ev['notes'] and 'Flight AX101' in ev['notes'] and 'Trip in Axella: Lakeby, Mar 2027 – https://axella.example/axella' in ev['notes'],
   '… with the reference and a way back to the trip')
ev2 = T.cal_event(trip('trA'), dict(bkg('trA', 'a2'), start='2027-03-01T00:00:00+03:00', end='2027-03-04T00:00:00+03:00'), 'Home')
ok(ev2['all_day'] and ev2['start'] == '2027-03-01T00:00:00' and ev2['end'] == '2027-03-04T23:59:00', 'dates without times: an all-day event')
t, bs, choice = st.cal_targets('trA')
ok([b['key'] for b in bs] == ['a1', 'a2', 'a3'], 'cancelled items never go in the calendar')
st.set_cal('trA', 'a1', {'id': 'ev-1', 'calendar': 'Home', 'start': ev['start']}, 'private', 'Home')
ok(bkg('trA', 'a1')['cal']['id'] == 'ev-1' and st.load()['cal_choice'] == {'private': 'Home'}, 'the event is remembered, and the calendar per world')
ok([b['key'] for b in st.cal_targets('trA')[1]] == ['a2', 'a3'], '… so it isn\'t added twice')

# ---- the Today card
c = T.today_card(st.load(), NOW)
ok(c and c['mode'] == 'travel' and c['next']['key'] == 'a1' and c['next']['ref'] == 'QX7KLM' and c['next']['address'] == 'Homeport T3',
   'travel day: the next item, with reference and address')
ok(c['next']['ticket'] == {'account': 'iCloud', 'message_id': 'm-a1', 'n': 0}, '… and its ticket in one tap')
ok(c['next']['checkin'] == {'at': '2027-02-28T10:40+02:00', 'estimated': True, 'hours': 24}, 'check-in: estimated, 24 h before (no mail, nothing learnt)')
ok(T.today_card(st.load(), datetime.datetime(2027, 2, 28, 18, 0, tzinfo=CET))['mode'] == 'eve', 'the evening before: the card')
ok(T.today_card(st.load(), datetime.datetime(2027, 2, 28, 12, 0, tzinfo=CET)) is None, 'not earlier that day')
dur = T.today_card(st.load(), datetime.datetime(2027, 3, 2, 9, 0, tzinfo=CET))
ok(dur and dur['mode'] == 'during' and all(i['key'] != 'a4' for i in dur['day']) and dur['next']['key'] == 'a2',
   'during the trip: the day\'s plan in local time – a cancelled item never shows')
ok(T.today_card(st.load(), datetime.datetime(2027, 3, 10, 9, 0, tzinfo=CET)) is None, 'no card on other days')

# ---- updates: untouched → applied and noted
d = st.load()
upd = bk('u1', 'flight', 'AX 101', '2027-03-01T11:15:00+02:00', '2027-03-01T13:45:00+03:00', ref='qx7 klm', number='AX 101', provider='Acme Air', status='changed')
ok(T.apply_update(d, upd, NOW, TRUST) == 'applied', 'a time change for an untouched booking, from the booking\'s own sender, is applied')
st._save(d)
b = bkg('trA', 'a1')
ok(b['start'] == '2027-03-01T11:15:00+02:00' and b['updated']['by'] == 'acme-air.example' and b['updated']['was']['start'] == '2027-03-01T10:40:00+02:00',
   '… and noted with the sender\'s domain (never a display name) and the old time')
ok(b['cal_stale'] == 'changed', '… and its calendar event is offered an update (never changed silently)')
d = st.load()
ok(T.apply_update(d, upd, NOW, TRUST) == 'same', 'the same update mail is applied once')
ok(T.apply_update(d, dict(upd, ref='OTHER'), NOW, TRUST) is None, 'another reference: not this booking')

# ---- edited by you → Apply / Ignore
st.action('trip_booking_edit', {'id': 'trA', 'key': 'a3', 'day': '2027-03-04', 'time': '14:00'})
d = st.load()
upd2 = bk('u2', 'flight', 'AX 205', '2027-03-04T15:30:00+03:00', ref='QX7KLM', number='AX205', provider='Acme Air', status='changed')
ok(T.apply_update(d, upd2, NOW, TRUST) == 'pending', 'a booking you edited: the update waits')
st._save(d)
b = bkg('trA', 'a3')
ok(b['start'].startswith('2027-03-04T14:00') and b['pending']['now']['start'] == '2027-03-04T15:30:00+03:00', '… your time stays until you choose')
r = st.action('trip_update_ignore', {'id': 'trA', 'key': 'a3'})
ok('pending' not in bkg('trA', 'a3') and bkg('trA', 'a3')['start'].startswith('2027-03-04T14:00'), 'Ignore: your edit stays')
d = st.load()
ok(T.apply_update(d, upd2, NOW, TRUST) == 'same', '… and that update doesn\'t come back')
st.action('trip_undo', {'token': r['undo']})
st.action('trip_update_apply', {'id': 'trA', 'key': 'a3'})
ok(bkg('trA', 'a3')['start'] == '2027-03-04T15:30:00+03:00' and not bkg('trA', 'a3').get('edited'), 'Apply (after undoing Ignore): the provider\'s time')

# ---- a cancellation read by Claude from a new mail goes to its booking, not into the suggestions
T.take_read(st, [dict(bk('c9', 'hotel', 'Lakeby Lodge', '2027-03-01T15:00:00+03:00', ref='LL-2231', provider='Lakeby Lodge'), status='cancelled',
                      source={'account': 'iCloud', 'message_id': 'm-cancel', 'subject': 'Cancelled', 'date': '2027-02-27',
                              'address': 'res@mail.lakeby-lodge.example'})], [], datetime.date(2027, 2, 27), trust=TRUST)
ok(bkg('trA', 'a2')['status'] == 'cancelled' and not st.load()['suggested'], 'a cancellation mail: the booking is cancelled, nothing new suggested')

# ---- the watch: newer data mails and check-in mails (rules only)
older = bk('x1', 'train', 'IC 42', '2027-03-20T09:00:00+02:00', ref='TR-77', number='IC42', confidence='data',
           source={'message_id': 'm-old', 'date': '2027-01-10', 'address': 'tickets@robin-rail.example'})
ok(st.watch([older], now=NOW, trust=TRUST) == 0 and bkg('trW', 'w1')['start'] == '2027-03-20T08:00:00+02:00', 'an older mail never changes a booking')
newer = dict(older, source={'message_id': 'm-new', 'date': '2027-03-02', 'address': 'tickets@robin-rail.example'})
ok(st.watch([newer], now=NOW, trust=TRUST) == 1 and bkg('trW', 'w1')['start'] == '2027-03-20T09:00:00+02:00', 'a newer mail\'s own booking data with a new time: applied')
mail_at = datetime.datetime(2027, 3, 18, 8, 0, tzinfo=CET)
ok(st.watch([], [{'text': 'Check-in is now open for booking QX7KLM', 'at': datetime.datetime(2027, 3, 3, 13, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=3))),
                  'provider': 'Acme Air', 'mail': {'address': 'checkin@mail.acme-air.example', 'message_id': 'm-ci'}}], now=NOW, trust=TRUST) == 1,
   'a "check-in is open" mail from the airline naming the booking is taken')
b3 = bkg('trA', 'a3')
ok(b3['checkin'] == {'at': '2027-03-03T13:00+03:00', 'estimated': False}, '… the real opening time, not an estimate')
ok(st.load()['checkin_windows'] == {'acmeair': 26}, '… and Acme Air\'s window is kept as data (hours before departure)')
d = st.load()
other = bk('z1', 'flight', 'AX 300', '2027-04-01T10:00:00+02:00', number='AX300', provider='Acme Air')
ok(T.checkin_of(d, other) == {'at': '2027-03-31T08:00+02:00', 'estimated': True, 'hours': 26}, 'the next Acme Air flight: estimated from the learnt window')

# ---- digest line and pushes
d = st.load()
lines, marks = T.alert_lines(d, NOW, ctx_of=lambda t: t.get('ctx'), worlds=['private'])
ok(any(l.startswith('AX101: new time') for l in lines) and any('Lakeby Lodge was cancelled' in l for l in lines)
   and not any('IC42' in l or 'IC 42' in l for l in lines), 'the digest: changes and cancellations of the digest\'s world only')
T.mark_reported(d, marks)
ok(not [l for l in T.alert_lines(d, NOW, ctx_of=lambda t: t.get('ctx'), worlds=['private'])[0] if 'new time' in l or 'cancelled' in l], 'each one is reported once')
ci, _ = T.alert_lines(d, datetime.datetime(2027, 3, 3, 9, 0, tzinfo=CET), ctx_of=lambda t: t.get('ctx'))
ok(any(l.startswith('Check-in for AX205 opens today') and 'estimated' not in l for l in ci), 'check-in opening within 30 h is in the digest')
far = T.push_due(d, datetime.datetime(2027, 2, 1, 9, 0, tzinfo=CET))
ok(far == [], 'no push a month before departure')
due = T.push_due(d, datetime.datetime(2027, 3, 3, 13, 5, tzinfo=datetime.timezone(datetime.timedelta(hours=3))))
ok(any(k == 'checkin' and 'AX205' in txt for k, txt, _ in due), 'a push when check-in opens, within 48 h of departure')
T.mark_pushed(d, [m for _, _, m in due])
ok(T.push_due(d, datetime.datetime(2027, 3, 3, 13, 10, tzinfo=datetime.timezone(datetime.timedelta(hours=3)))) == [], 'each push once')
ok(all(k != 'checkin' or 'Boat' not in txt for k, txt, _ in due), 'nothing for a cancelled item')

# ---- another sender: never applied by itself, never pushed (the review's rule)
d = st.load()
x_ = bk('s1', 'flight', 'AX 205', '2027-03-04T15:30:00+03:00', ref='QX7KLM', number='AX205', status='cancelled',
        source={'message_id': 'm-stranger', 'date': '2027-03-02', 'address': 'alerts@acme-air-rebooking.example'})
ok(T.apply_update(d, x_, NOW, TRUST) == 'pending', 'a stranger\'s cancellation is not applied – it waits (Apply / Ignore)')
pend = next(b for t in d['trips'] for b in t['bookings'] if b['key'] == 'a3')['pending']
ok(pend['other_sender'] and pend['by'] == 'acme-air-rebooking.example' and pend['provider'] == 'Acme Air',
   '… "From another sender than the booking – check with Acme Air", shown by its domain')
ok(next(b for t in d['trips'] for b in t['bookings'] if b['key'] == 'a3')['status'] != 'cancelled', '… the booking stays as it was')
strangers = {a['id'] for a in d['alerts'] if a.get('untrusted')}
ok(strangers and not [m for k, txt, m in T.push_due(d, datetime.datetime(2027, 3, 4, 9, 0, tzinfo=CET)) if m[0] == 'alert' and m[1] in strangers],
   '… and no push for it')
lines, _ = T.alert_lines(d, NOW, ctx_of=lambda t: t.get('ctx'))
ok(any('from another sender than the booking: check with Acme Air' in l for l in lines), 'the digest says it is from another sender')
d = st.load()
ok(T.learn_checkin(d, 'Check-in is open for QX7KLM', datetime.datetime(2027, 3, 3, 13, 0, tzinfo=CET), '', TRUST,
                   {'address': 'x@other-airline.example'}) == 0, 'a "check-in is open" mail from another sender is not taken')

print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
