#!/usr/bin/env python3
"""Who may change a booking by itself (axella-actions.py _trip_update_trust, Trips v2 review): only a clean mail
(scam check), that passed the sender checks for its sender's domain, from the domain of the mail the booking came
from. Anything else waits for Apply / Ignore and is never pushed. Invented airline, domains and references.
Run: python3 setup/tests/test_trips_trust.py"""
import datetime
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
import safety as S  # noqa: E402
import trips as T  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


S.PROVIDERS = ['mail-provider.example']                      # an invented mail provider (its verdicts count)
A._known_people = lambda: (set(), set())


class Safe:
    def load(self):
        return {'safe': []}

    def _safe_set(self, st):
        return set()


A.SAFETY = Safe()


def mail(frm, auth, subject='Your flight AX205 has been cancelled', body='Booking QX7KLM: flight AX205 is cancelled. We are sorry.'):
    dom = frm.rsplit('@', 1)[-1].rstrip('>')
    return ('Authentication-Results: mx01.mail-provider.example; %s\n'
            'Received: from out.%s by mx01.mail-provider.example with ESMTPS\n'
            'From: %s\nTo: alex@example.com\nSubject: %s\nDate: Tue, 02 Mar 2027 08:00:00 +0100\n\n%s\n' % (auth, dom, frm, subject, body)).encode()


RAW = {
    'm-own': mail('Acme Air <service@mail.acme-air.example>', 'spf=pass; dkim=pass header.d=acme-air.example; dmarc=pass header.from=acme-air.example'),
    'm-stranger': mail('Acme Air <alerts@acme-air-rebooking.example>', 'spf=pass; dkim=pass header.d=acme-air-rebooking.example; dmarc=pass header.from=acme-air-rebooking.example'),
    'm-fail': mail('Acme Air <service@acme-air.example>', 'spf=fail; dkim=fail header.d=acme-air.example; dmarc=fail header.from=acme-air.example'),
    'm-nopass': mail('Acme Air <service@acme-air.example>', 'spf=pass'),
}
A._raw_of_mid = lambda mid: RAW.get(mid)

booking = {'key': 'a3', 'kind': 'flight', 'title': 'AX 205', 'status': 'booked', 'start': '2027-03-04T13:00:00+03:00', 'end': '2027-03-04T14:00:00+02:00',
           'ref': 'QX7KLM', 'number': 'AX205', 'provider': 'Acme Air',
           'source': {'account': 'iCloud', 'message_id': 'm-booking', 'date': '2027-01-10', 'address': 'bookings@acme-air.example'}}


def upd(mid, addr):
    return {'kind': 'flight', 'status': 'cancelled', 'ref': 'QX7KLM', 'number': 'AX205', 'start': booking['start'], 'provider': 'Acme Air',
            'source': {'account': 'iCloud', 'message_id': mid, 'date': '2027-03-02', 'address': addr}}


ok(A._trip_update_trust(upd('m-own', 'service@mail.acme-air.example'), booking) == (True, 'acme-air.example'),
   'the airline\'s own mail, passing DMARC for its domain – the booking\'s domain: trusted')
ok(A._trip_update_trust(upd('m-stranger', 'alerts@acme-air-rebooking.example'), booking) == (False, 'acme-air-rebooking.example'),
   'another domain (even passing its own checks, even named "Acme Air"): not trusted')
ok(A._trip_update_trust(upd('m-fail', 'service@acme-air.example'), booking)[0] is False, 'the right domain but failed sender checks: not trusted')
ok(A._trip_update_trust(upd('m-nopass', 'service@acme-air.example'), booking)[0] is False, 'the right domain but no DMARC pass from the provider: not trusted')
ok(A._trip_update_trust(upd('m-gone', 'service@acme-air.example'), booking)[0] is False, 'a mail that isn\'t on the Mac mini: not trusted')

NOW = datetime.datetime(2027, 3, 3, 9, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))


def fresh():
    t = {'id': 'trA', 'title': 'Lakeby', 'bookings': [dict(booking, source=dict(booking['source']))]}
    T._span(t)
    return {'trips': [t]}


d = fresh()
ok(T.apply_update(d, upd('m-stranger', 'alerts@acme-air-rebooking.example'), NOW, A._trip_update_trust) == 'pending',
   'a stranger\'s cancellation stays pending')
b = d['trips'][0]['bookings'][0]
ok(b['status'] == 'booked' and b['pending']['other_sender'] and b['pending']['by'] == 'acme-air-rebooking.example', '… the booking unchanged, the sender shown by domain')
ok(T.push_due(d, NOW) == [], '… and no push')
d = fresh()
ok(T.apply_update(d, upd('m-own', 'service@mail.acme-air.example'), NOW, A._trip_update_trust) == 'applied',
   'the airline\'s own cancellation (passing DMARC) is applied')
b = d['trips'][0]['bookings'][0]
ok(b['status'] == 'cancelled' and b['updated']['by'] == 'acme-air.example' and not b.get('pending'), '… noted as from acme-air.example')
ok([t for k, t, m in T.push_due(d, NOW) if k == 'alert'] == ['AX205 was cancelled'], '… and pushed (within 48 h of departure)')
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
