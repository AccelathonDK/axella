#!/usr/bin/env python3
"""Renewals (setup/renewals.py): renewal and expiry mails (EN/DA, genuine only), lead times per kind, the
document-number guard, linking yearly subscriptions, the passport and trip check, the digest line, the To do card and
roll-over. Invented names, domains, amounts and dates only. Run: python3 setup/tests/test_renewals.py"""
import datetime
import os
import sys
import tempfile
from email.message import EmailMessage

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import renewals as RN  # noqa: E402
import safety as SF  # noqa: E402
SF.PROVIDERS = ['mail-provider.example']

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def bad(fn, label, word=''):
    try:
        fn()
        ok(False, label)
    except RN.Bad as e:
        ok(word.lower() in str(e).lower(), label + ('' if word.lower() in str(e).lower() else ' (said: %s)' % e))


def mail(frm, subject, text, auth=True, date='Thu, 04 Mar 2027 10:00:00 +0100'):
    m = EmailMessage()
    m['From'], m['To'], m['Subject'], m['Date'] = frm, 'alex@example.com', subject, date
    dom = frm.rsplit('@', 1)[-1].strip('>')
    if auth:
        m['Authentication-Results'] = 'mx01.mail-provider.example; dkim=pass header.d=%s; dmarc=pass header.from=%s' % (dom, dom)
        m['Received'] = 'from out.sender.example by mx01.mail-provider.example with ESMTPS'
    m.set_content(text)
    return m.as_bytes()


TODAY = datetime.date(2027, 3, 4)
d1 = RN.read_mail(mail('Acme Domains <billing@acme-domains.example>', 'Your domain expires soon',
                       'Your domain acme-notes.example expires on 2 April 2027. Renew now for 89 DKK.'))
ok(d1 and d1['kind'] == 'domain' and d1['date'] == '2027-04-02' and d1['cost'] == 89.0 and d1['currency'] == 'DKK', 'EN: a domain expiry, its date and price')
ok(d1['name'] == 'Acme-Domains domain' or d1['name'].endswith('domain'), 'the name is the sender\'s domain word, never text from the mail (%s)' % d1['name'])
d2 = RN.read_mail(mail('Robin Forsikring <kundeservice@robin-forsikring.example>', 'Din forsikring fornyes',
                       'Din bilforsikring fornyes automatisk den 1. maj 2027. Pris 2.940,00 kr. om året.'))
ok(d2 and d2['kind'] == 'insurance' and d2['date'] == '2027-05-01' and d2['cost'] == 2940.0 and d2['auto_renews'], 'DA: insurance renewing automatically')
ok(RN.read_mail(mail('Acme Domains <billing@acme-domains.example>', 'Your domain expires soon', 'expires on 2 April 2027', auth=False)) is None,
   'not genuine (no DKIM/DMARC pass): nothing')
ok(RN.read_mail(mail('News <news@example.com>', 'Our spring newsletter', 'Hello')) is None, 'not a renewal: nothing')

st = tempfile.mkdtemp()
S = RN.Renewals(st)
n = S.suggest([dict(d1, message_id='m1@x'), dict(d2, message_id='m2@x'), dict(d1, message_id='m3@x', domain='acmestream.example')],
              known_domains={'acmestream.example'})
ok(n == 2 and set(S.load()['suggestions']) == {'m1@x', 'm2@x'}, 'suggestions – a known subscription\'s sender left out')
ok(S.suggest([dict(d1, message_id='m1@x')]) == 0, 'a mail is offered once')
e = S.action('renewal_add', {'message_id': 'm2@x', 'name': 'Car insurance', 'kind': 'insurance', 'date': '2027-05-01', 'cost': 2940, 'currency': 'DKK',
                              'auto_renews': True, 'ctx': 'private'}, TODAY)
ok(e['lead_days'] == 42 and e['source'] == 'mail' and 'm2@x' not in S.load()['suggestions'], 'Add: on the timeline, with insurance\'s 6 weeks lead time')
S.action('renewal_not', {'message_id': 'm1@x'})
ok(not S.load()['suggestions'] and S.suggest([dict(d1, message_id='m1@x')]) == 0, 'Not a renewal: never offered again')

for k, days in (('passport', 183), ('id_card', 183), ('driving_licence', 91), ('insurance', 42), ('domain', 30), ('membership', 30),
                ('account', 30), ('agreement', 30), ('vehicle_inspection', 42)):
    ok(RN.KINDS[k][1] == days, 'lead time %s: %d days' % (k, days))
bad(lambda: S.action('renewal_add', {'name': 'Passport AB1234567', 'kind': 'passport', 'date': '2027-12-01'}), 'a passport-number-like name is refused', 'document')
bad(lambda: S.action('renewal_add', {'name': 'Passport', 'kind': 'passport', 'date': '2027-12-01', 'notes': 'no. 123456789'}), '… and a note', 'document')
bad(lambda: S.action('renewal_add', {'name': 'Policy 0000-1111-2222', 'kind': 'insurance', 'date': '2027-12-01'}), 'a policy number', 'never stores')
pp = S.action('renewal_add', {'name': 'Passport', 'kind': 'passport', 'date': '2027-10-20', 'ctx': 'private'}, TODAY)
ok(pp['lead_days'] == 183 and 'number' not in str(sorted(pp)), 'a passport: no field for its number')

yearly = [{'id': 'acmecloud:EUR', 'vendor': 'Acme Cloud', 'next': '2027-08-01', 'amount': 59.0, 'currency': 'EUR', 'interval': 'yearly'}]
trips = [{'id': 't1', 'title': 'Robin trip', 'status': 'confirmed', 'end': '2027-08-15'}, {'id': 't2', 'title': 'Later', 'status': 'suggested', 'end': '2027-09-01'}]
v = S.view(TODAY, yearly, trips)
sub = [r for r in v['rows'] if r.get('linked')]
ok(len(sub) == 1 and sub[0]['date'] == '2027-08-01' and sub[0]['state'] == 'linked', 'a yearly subscription is on the timeline once, linked')
ok(len([r for r in v['rows'] if not r.get('linked')]) == 2, '… and not copied into the renewals')
w = v['trip_warnings']
ok(len(w) == 1 and w[0]['trip'] == 't1' and w[0]['months'] == 2 and 'many countries require 6' in w[0]['text'],
   'the passport and trip check (%s)' % (w[0]['text'] if w else w))

ins = S.load()['items'][e['id']]
ok(S.state_of(ins, TODAY) == 'waiting' and S.digest_line(TODAY) is None, 'before the lead time: nothing in the digest')
LEAD = datetime.date(2027, 3, 21)
ok(S.state_of(ins, LEAD) == 'lead' and [c['id'] for c in S.cards(LEAD)] == [e['id']], 'at the lead time: a suggested To do card')
line = S.digest_line(LEAD)
ok(line == 'Car insurance renews 1 May – 2940 DKK last time. Compare before 17 Apr?', 'one digest line (%s)' % line)
ok(S.digest_line(LEAD) is None, '… once')
S.action('renewal_snooze', {'id': e['id'], 'for': 'week'}, LEAD)
ok(S.cards(LEAD) == [] and S.cards(LEAD + datetime.timedelta(days=8)) != [], 'Snooze a week')
S.action('renewal_task', {'id': e['id'], 'task_id': 't20270321'}, LEAD)
ok(S.cards(LEAD + datetime.timedelta(days=8)) == [], 'Add to To do: the card goes, the task is linked')
AFTER = datetime.date(2027, 5, 2)
ok(S.state_of(S.load()['items'][e['id']], AFTER) == 'after', 'after the date: asks "Renewed?"')
r2 = S.action('renewal_renewed', {'id': e['id']}, AFTER)
ok(r2['date'] == '2028-05-01' and not r2.get('task_id') and S.state_of(r2, AFTER) == 'waiting', 'Renewed: the next date a year on')
S.action('renewal_renewed', {'id': e['id'], 'next': '2028-06-15'}, AFTER)
ok(S.load()['items'][e['id']]['date'] == '2028-06-15', '… or the date you give')
bad(lambda: S.action('renewal_renewed', {'id': pp['id']}, AFTER), 'a one-off (passport) has no automatic next date', 'next date')
S.action('renewal_past', {'id': pp['id']}, AFTER)
ok([r['id'] for r in S.view(AFTER)['past']] == [pp['id']], 'a one-off is moved to Past')
dm = S.action('renewal_add', {'name': 'Notes domain', 'kind': 'domain', 'date': '2027-04-02', 'ctx': 'work'}, TODAY)
ok(S.digest_line(datetime.date(2027, 3, 5), ['private']) is None and S.digest_line(datetime.date(2027, 3, 5), ['work']) == 'Notes domain is due 2 Apr.',
   'a work renewal only in a digest that covers work')
ok(oct(os.stat(S.file).st_mode & 0o777) == '0o600', 'renewals.json is private (600)')
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
