#!/usr/bin/env python3
"""Subscriptions overview (setup/recurring.py): regular charges from the Receipts register, and renewal / trial /
price mails. Invented vendors, amounts and dates only. Run: python3 setup/tests/test_recurring.py"""
import datetime
import json
import os
import sys
import tempfile
from email.message import EmailMessage

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import recurring as R  # noqa: E402
import safety as SF  # noqa: E402
SF.PROVIDERS = ['mail-provider.example']          # an invented mail provider

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


TODAY = datetime.date(2027, 3, 20)


def doc(mid, vendor, date, amount, cur='DKK', kind='receipt', **kw):
    return dict({'message_id': mid, 'vendor': vendor, 'vendor_key': R.vendor_key(vendor), 'date': date, 'amount': amount,
                 'currency': cur, 'kind': kind, 'from': 'billing@%s.example' % R.vendor_key(vendor)}, **kw)


docs = {}
for i, (d, a) in enumerate([('2026-10-05', 99.0), ('2026-11-05', 99.0), ('2026-12-05', 99.0), ('2027-01-05', 99.0),
                            ('2027-02-05', 99.0), ('2027-03-05', 119.0)]):
    docs['s%d' % i] = doc('s%d@x' % i, 'Acme Stream', d, a)
for i, d in enumerate(['2024-04-01', '2025-04-02', '2026-03-30']):
    docs['y%d' % i] = doc('y%d@x' % i, 'Acme Cloud', d, 59.0, 'EUR', kind='invoice')
for i, d in enumerate(['2026-12-01', '2027-01-14', '2027-03-02']):     # irregular – a shop, not a subscription
    docs['o%d' % i] = doc('o%d@x' % i, 'Acme Shop', d, 250.0 + i * 120)
for i, d in enumerate(['2026-11-10', '2026-12-10']):                    # only two – not enough yet
    docs['t%d' % i] = doc('t%d@x' % i, 'Acme Gym', d, 300.0)
docs['ord'] = doc('ord@x', 'Acme Stream', '2027-03-06', 99.0, kind='order')
for i, d in enumerate(['2026-09-01', '2026-10-01', '2026-11-01']):    # stopped in November
    docs['q%d' % i] = doc('q%d@x' % i, 'Acme News', d, 49.0)

found = R.detect(docs, TODAY)
ok(set(found) == {'acmestream:DKK', 'acmecloud:EUR', 'acmenews:DKK'}, 'detected: monthly and yearly; not an irregular shop, not two charges (%s)' % sorted(found))
s = found['acmestream:DKK']
ok(s['interval'] == 'monthly' and s['amount'] == 119.0 and s['monthly'] == 119.0 and s['next'] == '2027-04-05', 'monthly: amount, monthly equivalent, next renewal')
c = found['acmecloud:EUR']
ok(c['interval'] == 'yearly' and c['monthly'] == round(59 / 12, 2) and c['first_seen'] == '2024-04-01', 'yearly: monthly equivalent and first seen')
ok(s['count'] == 6, 'an order confirmation is not a charge')

# ---- numbers, dates and the notice mails
ok(R._num('1.245,00') == 1245.0 and R._num('1,245.00') == 1245.0 and R._num('139,00') == 139.0 and R._num('9.99') == 9.99,
   'amounts in Danish and English notation')
ok(R.amounts_in('From 99 kr. to DKK 119,00 per month, or €9.99') == [(99.0, 'DKK'), (119.0, 'DKK'), (9.99, 'EUR')], 'amounts with their currency')
sent = datetime.date(2027, 3, 18)
ok(R.dates_in('Your trial ends in 3 days', sent) == [datetime.date(2027, 3, 21)], '"in 3 days" from the mail date')
ok(R.dates_in('renews on 5 April 2027, then 05.05.2027', sent) == [datetime.date(2027, 4, 5), datetime.date(2027, 5, 5)], 'dates, day first')
ok(R.dates_in('fornyes 2. januar', sent) == [datetime.date(2028, 1, 2)], 'a Danish date without a year: the next one')


def mail(frm, subject, text, html=None, date='Thu, 18 Mar 2027 10:00:00 +0100', auth=None):
    m = EmailMessage()
    m['From'], m['To'], m['Subject'], m['Date'] = frm, 'alex@example.com', subject, date
    if auth:                      # as your provider writes them: its verdict above its own Received line
        m['Authentication-Results'] = 'mx01.mail-provider.example; ' + auth
        m['Received'] = 'from out.sender.example by mx01.mail-provider.example with ESMTPS'
    m.set_content(text)
    if html:
        m.add_alternative(html, subtype='html')
    return m.as_bytes()


trial = R.read_notice(mail('Acme Learn <hello@acme-learn.example>', 'Your free trial ends soon',
                           'Your free trial ends in 3 days. After that it is 89 DKK per month.',
                           html='<p>Your free trial ends in 3 days.</p><a href="https://www.acme-learn.example/account/billing">Manage subscription</a>'
                                '<a href="https://tracker.example/click">Read more</a>'))
ok(trial['kind'] == 'trial' and trial['date'] == '2027-03-21' and trial['amount'] == 89.0 and trial['interval'] == 'monthly',
   'trial mail: kind, end date, price and interval')
ok(trial['vendor'] == 'Acme Learn' and trial['account_link'] == 'https://www.acme-learn.example/account/billing',
   'trial mail: vendor, and only the vendor\'s own account link')
price = R.read_notice(mail('Acme Stream <noreply@acmestream.example>', 'Prisændring på dit abonnement',
                           'Vi hæver prisen fra 119 kr. til 139 kr. om måneden fra 1. maj 2027.'))
ok(price['kind'] == 'price' and price['old_amount'] == 119.0 and price['amount'] == 139.0 and price['date'] == '2027-05-01',
   'price mail (Danish): from, to and from when')
renew = R.read_notice(mail('Billing <billing@acme-vpn.example>', 'Your subscription will renew',
                           'Your annual plan renews automatically on 2 April 2027 for USD 48.00.'))
ok(renew['kind'] == 'renewal' and renew['vendor'] == 'Acme Vpn' and renew['interval'] == 'yearly' and renew['amount'] == 48.0,
   'renewal mail: a generic sender name gives the vendor from the domain')
ok(R.read_notice(mail('Acme Shop <news@acme-shop.example>', 'Your subscription to our newsletter', 'Thanks for signing up!')) is None,
   'a newsletter "subscription" is not a notice')

# ---- the register + notices together
tmp = tempfile.mkdtemp()
dg = os.path.join(tmp, 'digests')
os.makedirs(dg)
rc = R.Recurring(tmp, dg)
v = rc.refresh(docs, [], TODAY)
ok(all(c['seen'] for c in v['changes']), 'the very first build notes nothing as new')
notices = [dict(trial, message_id='tr@x'), dict(price, message_id='pr@x'), dict(renew, message_id='rn@x')]
rc.refresh(docs, notices, TODAY)
view = rc.view()
ids = {x['id'] for x in view['subs']}
ok('acmelearn:DKK' in ids and 'acmevpn:USD' in ids, 'one renewal or trial mail is enough to list a subscription')
ok(not next(x for x in view['subs'] if x['id'] == 'acmelearn:DKK').get('account_link'), 'a subscription known from mail alone shows no account link')
ok(next(x for x in view['subs'] if x['id'] == 'acmevpn:USD')['vendor'] == 'Acme Vpn', 'a mail-only subscription is named by its domain, not the display name')
kinds = sorted(c['kind'] for c in view['changes'])
ok(kinds == ['new', 'new', 'price_up', 'trial'], 'changes: two new, the price change and the trial (%s)' % kinds)
ok(view['totals']['DKK']['count'] == 3 and view['totals']['DKK']['month'] == round(119 + 49 + 89, 2), 'totals per currency, never converted')
ok('EUR' in view['totals'] and 'USD' in view['totals'], '… one total per currency')
ok(view['totals']['EUR']['year'] == 59.0, 'a yearly charge counts exactly once a year (not 12 × the rounded month)')
before = len(rc.load()['changes'])
rc.refresh(docs, notices, TODAY)
ok(len(rc.load()['changes']) == before and len([c for c in rc.load()['changes'] if c['kind'] == 'price_up']) == 2,
   'each price change is noted once (the 99 → 119 receipt and the mail about 139)')
ok(next(x for x in view['subs'] if x['id'] == 'acmenews:DKK')['quiet'], 'not seen for a while: marked possibly cancelled')

# ---- Open account page: only from the Receipts vendor's own domain, and only when the mail passed DKIM/DMARC
LINK_HTML = '<a href="https://acmestream.example/account">Manage your subscription</a>'
own = R.read_notice(mail('Acme Stream <billing@acmestream.example>', 'Your subscription renews soon', 'Your plan renews on 5 April 2027.',
                         html=LINK_HTML, auth='dkim=pass header.d=acmestream.example; dmarc=pass header.from=acmestream.example'))
ok(own['auth_ok'] and own['account_link'] == 'https://acmestream.example/account', 'a renewal mail that passed DKIM: auth ok, link read')
unsigned = R.read_notice(mail('Acme Stream <billing@acmestream.example>', 'Your subscription renews soon', 'Your plan renews on 5 April 2027.', html=LINK_HTML))
ok(not unsigned['auth_ok'], 'no Authentication-Results: not trusted')
other = R.read_notice(mail('Acme Stream <billing@acmestream.example>', 'Your subscription renews soon', 'Your plan renews on 5 April 2027.',
                           html=LINK_HTML, auth='dkim=pass header.d=other.example; dmarc=fail header.from=acmestream.example'))
ok(not other['auth_ok'], 'DKIM passed for another domain: not trusted')
fake = R.read_notice(mail('Acme Stream <billing@acme-stream-deals.example>', 'Your subscription will renew', 'Your plan renews on 5 April 2027 for 119 DKK per month.',
                          html='<a href="https://acme-stream-deals.example/account">Manage subscription</a>',
                          auth='dkim=pass header.d=acme-stream-deals.example; dmarc=pass header.from=acme-stream-deals.example'))
for label, n, want in (('signed, own domain', own, 'https://acmestream.example/account'), ('unsigned', unsigned, None)):
    t2 = tempfile.mkdtemp()
    r2 = R.Recurring(t2, None)
    r2.refresh(docs, [dict(n, message_id='n@x')], TODAY)
    got = {x['id']: x for x in r2.view()['subs']}['acmestream:DKK'].get('account_link')
    ok(got == want, 'Receipts vendor + %s mail → account link %s' % (label, 'shown' if want else 'not shown'))
t3 = tempfile.mkdtemp()
r3 = R.Recurring(t3, None)
r3.refresh(docs, [dict(fake, message_id='f@x')], TODAY)
subs3 = {x['id']: x for x in r3.view()['subs']}
ok(not subs3['acmestream:DKK'].get('account_link') and subs3['acmestream:DKK']['next'] == found['acmestream:DKK']['next'],
   'a mail that only uses the vendor\'s display name is not matched to it (no link, no new renewal date)')
ok(all(x['vendor'] != 'Acme Stream' for k, x in subs3.items() if k != 'acmestream:DKK') and not any(x.get('account_link') for x in subs3.values()),
   '… it is listed under its own domain word, without a link')

# a forged "pass" inside the mail (below the provider's Received) doesn't count – and the provider's fail wins
forged = mail('Acme Stream <billing@acmestream.example>', 'Your subscription renews soon', 'Your plan renews on 5 April 2027.', html=LINK_HTML,
              auth='dkim=fail header.d=acmestream.example; dmarc=fail header.from=acmestream.example')
forged = forged.replace(b'with ESMTPS', b'with ESMTPS\nReceived: from attacker.example by relay.example\n'
                        b'Authentication-Results: mx01.mail-provider.example; dkim=pass header.d=acmestream.example; dmarc=pass header.from=acmestream.example', 1)
fn = R.read_notice(forged)
ok(not fn['auth_ok'], 'a forged pass header below a real fail: not trusted')
t4 = tempfile.mkdtemp()
r4 = R.Recurring(t4, None)
r4.refresh(docs, [dict(fn, message_id='fg@x')], TODAY)
ok(not {x['id']: x for x in r4.view()['subs']}['acmestream:DKK'].get('account_link'), '… and the link check rejects that mail')

# ---- actions
rc.action('recurring_set', {'id': 'acmenews:DKK', 'status': 'cancelled'})
rc.action('recurring_set', {'id': 'acmestream:DKK', 'ctx': 'private', 'company': '  Acme  Holding ', 'project': 'p-kitchen'})
rc.refresh(docs, notices, TODAY)
s = {x['id']: x for x in rc.view()['subs']}
ok(s['acmenews:DKK']['status'] == 'cancelled' and s['acmestream:DKK']['company'] == 'Acme Holding' and s['acmestream:DKK']['ctx'] == 'private'
   and s['acmestream:DKK']['project'] == 'p-kitchen', 'your choices survive a rebuild')
ok(rc.view()['totals']['DKK']['count'] == 2, 'a cancelled subscription leaves the totals')
for bad in ({'id': 'nope', 'status': 'active'}, {'id': 'acmestream:DKK', 'status': 'paused'}, {'id': 'acmestream:DKK', 'ctx': 'office'}):
    try:
        rc.action('recurring_set', bad)
        ok(False, 'refused: %s' % bad)
    except R.Bad:
        ok(True, 'refused: %s' % bad)

# ---- the morning digest line (deterministic)
name = '2027-03-20-0731.json'
json.dump({'title': 'Morning', 'spoken': 'Good morning.', 'generated': '2027-03-20T07:31:00+01:00', 'items': []}, open(os.path.join(dg, name), 'w'))
open(os.path.join(dg, 'spoken-digest.md'), 'w').write('Good morning.\n')
ok(rc.add_to_digest(name) == 3, 'the morning digest gets the new changes (at most three)')
d = json.load(open(os.path.join(dg, name)))
it = d['items'][-1]
ok(it['section'] == 'p3' and it['channel'] == 'subscriptions' and 'Subscriptions' in it['headline'] and 'draft' not in it, 'one quiet FYI item, no draft')
ok('price is changing' in d['spoken'] and 'price is changing' in open(os.path.join(dg, 'spoken-digest.md')).read(), 'and one spoken sentence, in Listen too')
ok(rc.add_to_digest(name) == 0, 'once per digest')
json.dump({'items': []}, open(os.path.join(dg, '2027-03-21-0731.json'), 'w'))
ok(rc.add_to_digest('2027-03-21-0731.json') == 1, 'the rest comes the next morning')
ok(rc.add_to_digest('2027-03-21-1531.json') == 0, 'never in the afternoon digest')
rc.action('recurring_seen', {})
ok(rc.view()['changes'] == [], 'Seen clears the change list')

print('%d failed' % fails if fails else 'all passed')
sys.exit(1 if fails else 0)
