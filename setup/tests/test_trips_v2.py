#!/usr/bin/env python3
"""Trips v2, steps 1–2 (setup/trips.py): merge, split, items added by hand (local time in their own zone), cancelled
items, undo for every step, planning (quotes → Booked / Replace / Drop) and the documents checklist kept out of
trips.json. Invented trips, places and references only. Run: python3 setup/tests/test_trips_v2.py"""
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


def bad(fn, label):
    try:
        fn()
        ok(False, label)
    except T.Bad:
        ok(True, label)


def bk(key, kind, title, start, end=None, ref='', provider='', mid=None):
    return {'key': key, 'kind': kind, 'status': 'booked', 'title': title, 'start': start, 'end': end or start, 'place': '', 'ref': ref,
            'provider': provider, 'travellers': ['Alex Example'], 'confidence': 'read',
            'source': {'account': 'iCloud', 'message_id': mid or ('m-' + key), 'subject': title, 'date': start[:10]}}


tmp = tempfile.mkdtemp()
st = T.Trips(tmp)
A = {'id': 'trA', 'title': 'Nordhavn and Lakeby, Jun 2027', 'auto_title': False, 'created': '2027-01-01T10:00:00+01:00',
     'bookings': [bk('a1', 'flight', 'AX 101 · Homeport → Lakeby', '2027-06-01T10:40:00+02:00', '2027-06-01T12:10:00+03:00', 'QX7KLM', 'Acme Air'),
                  bk('a2', 'hotel', 'Lakeby Lodge', '2027-06-01T15:00:00+03:00', '2027-06-04T11:00:00+03:00', 'LL-2231', 'Lakeby Lodge'),
                  bk('a3', 'flight', 'AX 205 · Lakeby → Nordhavn', '2027-06-04T13:00:00+03:00', '2027-06-04T14:00:00+02:00', 'QX7KLM', 'Acme Air'),
                  bk('a4', 'hotel', 'Nordhavn Inn', '2027-06-04T15:00:00+02:00', '2027-06-06T11:00:00+02:00', 'NI-77', 'Nordhavn Inn')]}
B = {'id': 'trB', 'title': 'Robin\'s wedding', 'auto_title': False, 'created': '2027-01-02T10:00:00+01:00',
     'bookings': [bk('b1', 'ticket', 'Wedding dinner', '2027-06-06T18:00:00+02:00', ref='W-1', provider='Robin Events')]}
for t_ in (A, B):
    T._span(t_)
json.dump({'trips': [A, B], 'suggested': [], 'quotes': [
    {**bk('q1', 'car', 'Car quote – Nordhavn', '2027-06-04T16:00:00+02:00', '2027-06-06T10:00:00+02:00', 'CQ-55', 'Kim Cars'), 'status': 'quote'},
    {**bk('q9', 'car', 'Car quote – far away', '2027-09-01T16:00:00+02:00', ref='CQ-99', provider='Kim Cars'), 'status': 'quote'}]},
          open(os.path.join(tmp, 'trips.json'), 'w'))
trip = lambda i: next((x for x in st.load()['trips'] if x['id'] == i), None)

# ---- merge
r = st.action('trip_merge', {'id': 'trA', 'other': 'trB'})
ok(trip('trB') is None and len(trip('trA')['bookings']) == 5 and trip('trA')['end'].startswith('2027-06-06T18'),
   'merge: the other trip\'s bookings join, the span grows, the other trip is gone')
ok(all(b['source'].get('message_id') for b in trip('trA')['bookings']), 'merge: every booking keeps its source')
st.action('trip_undo', {'token': r['undo']})
ok(len(trip('trA')['bookings']) == 4 and trip('trB') and len(trip('trB')['bookings']) == 1, 'merge undone: both trips as they were')
bad(lambda: st.action('trip_undo', {'token': r['undo']}), 'an undo step is used once')
bad(lambda: st.action('trip_merge', {'id': 'trA', 'other': 'trA'}), 'merge needs another trip')

# ---- split
r = st.action('trip_split', {'id': 'trA', 'at': '2027-06-04', 'title': 'Nordhavn, Jun 2027'})
nid = r['id']
ok([b['key'] for b in trip('trA')['bookings']] == ['a1', 'a2'] and [b['key'] for b in trip(nid)['bookings']] == ['a3', 'a4'],
   'split at a date: the bookings from that day on become the new trip')
ok(trip(nid)['title'] == 'Nordhavn, Jun 2027', '… with the name you gave')
st.action('trip_undo', {'backup': r['backup']})          # Restore from the activity log uses the same token
ok(trip(nid) is None and len(trip('trA')['bookings']) == 4, 'split undone (also from the activity log)')
r = st.action('trip_split', {'id': 'trA', 'keys': ['a2'], 'title': 'Just the lodge'})
ok([b['key'] for b in trip(r['id'])['bookings']] == ['a2'], 'split by picked bookings')
st.action('trip_undo', {'token': r['undo']})
bad(lambda: st.action('trip_split', {'id': 'trA', 'keys': ['a1', 'a2', 'a3', 'a4'], 'title': 'All'}), 'split leaves at least one booking')
bad(lambda: st.action('trip_split', {'id': 'trA', 'keys': ['a1']}), 'split needs a name')

# ---- undo only while the trip is unchanged since
r1 = st.action('trip_cancel', {'id': 'trA', 'key': 'a4'})
st.action('trip_rename', {'id': 'trA', 'title': 'Renamed later'})
bad(lambda: st.action('trip_undo', {'token': r1['undo']}), 'an undo is refused once the trip changed again (never clobbers later edits)')
ok(next(b for b in trip('trA')['bookings'] if b['key'] == 'a4')['status'] == 'cancelled', 'cancelled: the item stays, marked cancelled')
st.action('trip_cancel', {'id': 'trA', 'key': 'a4', 'on': False})
ok(next(b for b in trip('trA')['bookings'] if b['key'] == 'a4')['status'] == 'booked', 'and back again')

# ---- an item by hand, in its own zone
r = st.action('trip_item_add', {'id': 'trA', 'kind': 'transfer', 'title': 'Taxi to the lodge', 'start': '2027-06-01T12:40',
                                'end': '2027-06-01T13:20', 'tz': 'Europe/Helsinki', 'place': 'Lakeby airport', 'ref': 'TX-9',
                                'travellers': ['Alex Example', 'Robin']})
b = next(x for x in trip('trA')['bookings'] if x['key'] == r['key'])
ok(b['start'] == '2027-06-01T12:40:00+03:00' and b['end'] == '2027-06-01T13:20:00+03:00' and b['tz'] == 'Europe/Helsinki',
   'by hand: local time with the zone\'s own offset on that day (summer time)')
ok(b['by_hand'] and b['confidence'] == 'manual' and b['source'] == {} and b['travellers'] == ['Alex Example', 'Robin'], '… marked as yours, no mail needed')
w = T.zoned('2027-01-15T09:00', 'Europe/Helsinki')
ok(w == '2027-01-15T09:00:00+02:00', 'winter time in the same zone')
bad(lambda: T.zoned('2027-01-15T09:00', '../../etc/passwd'), 'a zone name that is a path is refused')
bad(lambda: st.action('trip_item_add', {'id': 'trA', 'title': 'Back to front', 'start': '2027-06-02T10:00', 'end': '2027-06-02T09:00', 'tz': 'UTC'}),
    'an item that ends before it starts is refused')
bad(lambda: st.action('trip_item_add', {'id': 'trA', 'title': '', 'start': '2027-06-02T10:00', 'tz': 'UTC'}), 'an item needs a name')
r2 = st.action('trip_item_remove', {'id': 'trA', 'key': r['key']})
ok(all(x['key'] != r['key'] for x in trip('trA')['bookings']), 'an item added by hand can be removed')
st.action('trip_undo', {'token': r2['undo']})
ok(any(x['key'] == r['key'] for x in trip('trA')['bookings']), '… and restored')
bad(lambda: st.action('trip_item_remove', {'id': 'trA', 'key': 'a1'}), 'a booking from a mail is never removed (void it instead)')
mailed = st.action('trip_item_add', {'id': 'trA', 'title': 'Boat trip', 'start': '2027-06-02', 'tz': 'Europe/Helsinki',
                                     'mail': {'account': 'iCloud', 'message_id': 'm-boat', 'subject': 'Your boat trip'}})
ok(next(x for x in trip('trA')['bookings'] if x['key'] == mailed['key'])['source']['message_id'] == 'm-boat', 'by hand, with the mail it came in')

# ---- planning
v = st.view(datetime.date(2027, 5, 1))
pl = next(t for t in v['trips'] if t['id'] == 'trA')['planning_view']
ok([q['key'] for q in pl] == ['q1'], 'planning: a quote whose dates fall in the trip shows under it – never as a booking')
ok(all(b['key'] != 'q1' for b in trip('trA')['bookings']), '… and is not one of its bookings')
d = st.load()
conf = bk('c1', 'car', 'Car booked – Nordhavn', '2027-06-04T16:00:00+02:00', ref='CQ-55', provider='Kim Cars')
next(t for t in d['trips'] if t['id'] == 'trA')['new'] = [conf]
st._save(d)
pl = next(t for t in st.view(datetime.date(2027, 5, 1))['trips'] if t['id'] == 'trA')['planning_view']
ok(pl[0]['confirmed_by'] == 'c1', 'the confirmation arrived (same reference): offered in place of the quote')
r = st.action('trip_plan_replace', {'id': 'trA', 'key': 'q1', 'by': 'c1'})
ok(any(x['key'] == 'c1' for x in trip('trA')['bookings']) and not st.load()['quotes'][0]['key'] == 'q1'
   and not next(t for t in st.view(datetime.date(2027, 5, 1))['trips'] if t['id'] == 'trA')['planning_view'], 'Replace: the booking in, the quote gone')
st.action('trip_undo', {'token': r['undo']})
ok(any(q['key'] == 'q1' for q in st.load()['quotes']) and all(x['key'] != 'c1' for x in trip('trA')['bookings']), 'Replace undone: the quote is back')
r = st.action('trip_plan_booked', {'id': 'trA', 'key': 'q1'})
ok(next(x for x in trip('trA')['bookings'] if x['key'] == 'q1')['status'] == 'booked', 'Booked: the quote becomes a booking (marked yours)')
st.action('trip_undo', {'token': r['undo']})
st.action('trip_plan_drop', {'id': 'trA', 'key': 'q1'})
ok(not next(t for t in st.view(datetime.date(2027, 5, 1))['trips'] if t['id'] == 'trA')['planning_view'], 'Drop: gone, and not offered again')

# ---- the checklist: out of trips.json
ck = T.Checklists(tmp)
ok([x['id'] for x in ck.of('trA')] == ['passport', 'visa', 'insurance', 'vaccinations'] and not any(x['done'] for x in ck.of('trA')),
   'checklist: the defaults, nothing ticked – you tick them yourself')
ck.action('trip_check_set', {'id': 'trA', 'item': 'passport', 'done': True}, {'trA'})
r = ck.action('trip_check_add', {'id': 'trA', 'text': 'Adapter plugs'}, {'trA'})
new = r['checklist'][-1]['id']
ck.action('trip_check_set', {'id': 'trA', 'item': new, 'date': '2027-05-25'}, {'trA'})
ok(ck.of('trA')[0]['done'] and ck.of('trA')[-1]['text'] == 'Adapter plugs', 'tick an item, add your own')
ok(ck.due([trip('trA')], datetime.date(2027, 5, 20)) == [{'trip': 'trA', 'trip_title': trip('trA')['title'], 'item': new, 'text': 'Adapter plugs', 'date': '2027-05-25'}]
   and ck.due([trip('trA')], datetime.date(2027, 5, 1)) == [], 'only an item you gave a date is ever due')
ck.action('trip_check_remove', {'id': 'trA', 'item': 'vaccinations'}, {'trA'})
ok('vaccinations' not in [x['id'] for x in ck.of('trA')], 'remove an item')
bad(lambda: ck.action('trip_check_add', {'id': 'trZ', 'text': 'x'}, {'trA'}), 'only for your own trips')
raw = open(os.path.join(tmp, 'trips.json')).read()
ok('Adapter plugs' not in raw and 'Passports' not in raw, 'the checklist is not in trips.json (Claude runs read that file)')
ok(oct(os.stat(os.path.join(tmp, 'trip-checklists.json')).st_mode & 0o777) == '0o600', 'the checklist file is readable by the owner only')
import scheduler  # noqa: E402
ok('state/trip-checklists.json' in scheduler.SECRETS, 'and it is on the SECRETS list')

# ---- a cancellation you made survives the mail being read again
d = st.load()
t0 = next(t for t in d['trips'] if t['id'] == 'trA')
for x in t0['bookings']:
    if x['key'] == 'a2':
        x['status'], x['own_status'] = 'cancelled', True
st._save(d)
T.take_read(st, [dict(bk('a2', 'hotel', 'Lakeby Lodge (read again)', '2027-06-01T15:00:00+03:00', ref='LL-2231'), status='booked', key='zz')], [])
ok(next(x for x in trip('trA')['bookings'] if x['source'].get('message_id') == 'm-a2')['status'] == 'cancelled', 'your "cancelled" survives a new reading of the mail')

print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
