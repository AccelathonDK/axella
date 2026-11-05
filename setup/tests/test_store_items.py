#!/usr/bin/env python3
"""Subscriptions – store items (setup/app_stores.py, recurring.py): one subscription per item on an app store's receipt,
grouped under the store; the store's own page as a fixed link; "<store> – other" for charges without item lines.
Invented apps, plans, amounts and dates only; the receipt layouts are rebuilt by hand, not copied from any mail.
Run: python3 setup/tests/test_store_items.py"""
import datetime
import json
import os
import sys
import tempfile
from email.message import EmailMessage

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import recurring as R  # noqa: E402
import app_stores as S  # noqa: E402
import safety as SF  # noqa: E402
SF.PROVIDERS = ['mail-provider.example']          # an invented mail provider

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


# The rules are the same for every store; the tests use an invented store with Apple's rule set, so no real address
# is written here. Apple's own entry is checked below (its domain and its fixed page).
ok(S.STORES['apple']['domain'] == 'apple.com' and S.STORES['apple']['manage'] == 'https://apps.apple.com/account/subscriptions'
   and S.STORES['google_play']['domain'] == 'google.com' and S.STORES['paypal']['domain'] == 'paypal.com', 'the stores: their own domains and fixed pages')
S.STORES['apple'] = dict(S.STORES['apple'], domain='acme-store.example')


PASS = 'dkim=pass header.d=mail.acme-store.example; dmarc=pass header.from=mail.acme-store.example'


def mail(frm, subject, html, date, auth=PASS):
    m = EmailMessage()
    m['From'], m['To'], m['Subject'], m['Date'] = frm, 'alex@example.com', subject, date
    if auth:
        m['Authentication-Results'] = 'mx01.mail-provider.example; ' + auth
        m['Received'] = 'from out.sender.example by mx01.mail-provider.example with ESMTPS'
    m.set_content('See the HTML part.')
    m.add_alternative(html, subtype='html')
    return m.as_bytes()


def receipt(items, day, lang='en', total=True, link=''):
    """An invented store receipt: a header block, a section heading, one table row per item, then the totals."""
    en = lang == 'en'
    rows = ''.join('<tr><td><b>%s</b><br>%s%s<br>%s</td><td>kr %s</td></tr>' % (
        n, p, ('<br>' + r) if r else '', 'Report a Problem' if en else 'Rapportér et problem', ('%.2f' % a).replace('.', ','))
        for n, p, r, a in items)
    s = sum(a for _, _, _, a in items)
    tot = ('<tr><td>Subtotal</td><td>kr %s</td></tr><tr><td>%s</td><td>kr %s</td></tr><tr><td>%s</td><td>kr %s</td></tr>' % (
        ('%.2f' % s).replace('.', ','), 'VAT' if en else 'Moms', ('%.2f' % (s * 0.2)).replace('.', ','),
        'Total' if en else 'I alt', ('%.2f' % s).replace('.', ','))) if total else ''
    return ('<html><head><style>td{font:12px sans-serif}</style></head><body><table>'
            '<tr><td>%s</td></tr><tr><td>alex@example.com</td></tr><tr><td>%s</td></tr><tr><td>Visa •••• 0000</td></tr>'
            '<tr><td>%s</td></tr><tr><td>%s</td></tr><tr><td>%s</td></tr><tr><td>MZZ0EXAMPLE</td></tr>'
            '<tr><td>App Store</td></tr>%s%s</table>%s</body></html>') % (
        'APPLE ID' if en else 'APPLE-ID', 'BILLED TO' if en else 'FAKTURERET TIL', 'DATE' if en else 'DATO', day,
        'ORDER ID' if en else 'ORDRE-ID', rows, tot, link)


APPLE = 'Apple <no_reply@mail.acme-store.example>'
NOTES = ('Acme Notes Pro', 'Pro Monthly (Monthly)', 'Renews 3 %s 2027', 59.0)
RADIO = ('Robin Radio Family', 'Family plan (Monthly)', 'Renews 3 %s 2027', 89.0)
MAPS = ('Kim Maps Plus', 'Plus (Yearly)', 'Renews 3 January 2028', 249.0)
PUZZLE = ('Sam Puzzle Pack', 'In-app purchase', '', 25.0)


def item(t, month=None, amount=None):
    n, p, r, a = t
    return (n, p, r % month if '%s' in r else r, a if amount is None else amount)


# ---- parsing one receipt (English)
r1 = S.parse_receipt(mail(APPLE, 'Your receipt from Apple.', receipt([item(NOTES, 'February'), item(RADIO, 'February'), MAPS], '3 Jan 2027'),
                          'Sun, 03 Jan 2027 10:00:00 +0100'))
names = [i['name'] for i in r1['items']]
ok(r1['store'] == 'apple' and r1['auth_ok'] and names == ['Acme Notes Pro', 'Robin Radio Family', 'Kim Maps Plus'], 'three items read (%s)' % names)
n1 = r1['items'][0]
ok(n1['plan'] == 'Pro Monthly (Monthly)' and n1['amount'] == 59.0 and n1['currency'] == 'DKK' and n1['interval'] == 'monthly'
   and n1['renews'] == '2027-02-03' and n1['kind'] == 'subscription', 'an item: plan, price, currency, interval, renewal date')
ok(r1['items'][2]['interval'] == 'yearly' and r1['items'][2]['renews'] == '2028-01-03', 'a yearly item')
ok(r1['total'] == 397.0 and r1['subtotal'] == 397.0 and S.itemised(r1), 'the totals are read, not taken as items; the items add up')
ok(not any(i['name'] in ('APPLE ID', 'App Store', 'Subtotal', 'VAT', 'Total') or 'example.com' in i['name'] or 'MZZ0' in i['name']
           for i in r1['items']), 'header, heading and total lines are layout, not items')

# ---- Danish
rda = S.parse_receipt(mail(APPLE, 'Din kvittering fra Apple.', receipt([('Acme Notes Pro', 'Pro (Månedligt)', 'Fornyes 3. februar 2027', 59.0),
                                                                            ('Kim Maps Plus', 'Plus (Årligt)', 'Fornyes 3. januar 2028', 249.0)],
                                                                           '3. jan. 2027', lang='da'), 'Sun, 03 Jan 2027 10:00:00 +0100'))
ok([(i['name'], i['interval'], i['renews']) for i in rda['items']] == [('Acme Notes Pro', 'monthly', '2027-02-03'), ('Kim Maps Plus', 'yearly', '2028-01-03')]
   and rda['total'] == 308.0 and S.itemised(rda), 'a Danish receipt: items, intervals, renewal dates, "I alt"')

# ---- a layout with the VAT under the price and the total on the "paid with" line (rebuilt by hand, invented)
def receipt2(name, plan, renews, price, vat, extra=''):
    cells = ['Kvittering', '3. jan. 2027', 'Alex Example', 'MZZ0EXAMPLE', 'Ordre-id', '100000000001', 'Dokument', '200000000002',
             'Apple-konto', 'alex@example.com', name, plan, renews, 'kr %s' % price, 'Inkl. moms kr %s' % vat,
             'Faktureret til', 'Alex Example', 'Examplevej 1', '0000 Exampleby', 'Danmark', 'Subtotal', 'kr %s' % price, 'Moms',
             'kr %s' % vat, 'Mastercard •••• 0000', 'kr %s' % price, extra or 'Fornyes automatisk', 'Tak', 'Hej',
             'Administrer abonnementer', 'Se', 'Rapporter et problem', 'Se', 'Kontakt', 'Alle rettigheder forbeholdes']
    return '<html><body><table>%s</table></body></html>' % ''.join('<tr><td>%s</td></tr>' % c for c in cells)


r2 = S.parse_receipt(mail(APPLE, 'Din kvittering fra Apple.', receipt2('Robin Radio Family', 'Familie (månedligt)', 'Fornyes 3. februar 2027',
                                                                         '89,00', '17,80'), 'Sun, 03 Jan 2027 10:00:00 +0100'))
ok([(i['name'], i['kind'], i['interval'], i['amount']) for i in r2['items']] == [('Robin Radio Family', 'subscription', 'monthly', 89.0)],
   '"Inkl. moms kr …" under the price is not an item (%s)' % [i['name'] for i in r2['items']])
ok(r2['total'] == 89.0 and r2['subtotal'] == 89.0 and S.itemised(r2), 'the total from the "paid with" card line; the item adds up')

# ---- a one-off purchase on the same receipt
rp = S.parse_receipt(mail(APPLE, 'Your receipt from Apple.', receipt([item(NOTES, 'March'), PUZZLE], '3 Feb 2027'), 'Wed, 03 Feb 2027 10:00:00 +0100'))
ok([i['kind'] for i in rp['items']] == ['subscription', 'purchase'], 'a one-off in-app purchase is a purchase')

# ---- only genuine store mail
look = S.parse_receipt(mail('Apple <no_reply@apple-receipts.example>', 'Your receipt from Apple.', receipt([MAPS], '3 Jan 2027'),
                            'Sun, 03 Jan 2027 10:00:00 +0100', auth='dkim=pass header.d=apple-receipts.example; dmarc=pass header.from=apple-receipts.example'))
ok(look is None, 'a look-alike "Apple" from another domain is not a store mail')
ok(not S.is_candidate('Your receipt from Apple.', 'no_reply@apple-receipts.example') and S.is_candidate('Your receipt from Apple.', 'no_reply@mail.acme-store.example'),
   'candidates by the sender\'s own domain, never the display name')
fail = S.parse_receipt(mail(APPLE, 'Your receipt from Apple.', receipt([MAPS], '3 Jan 2027'), 'Sun, 03 Jan 2027 10:00:00 +0100',
                            auth='dkim=fail header.d=mail.acme-store.example; dmarc=fail header.from=mail.acme-store.example'))
none = S.parse_receipt(mail(APPLE, 'Your receipt from Apple.', receipt([MAPS], '3 Jan 2027'), 'Sun, 03 Jan 2027 10:00:00 +0100', auth=None))
ok(not fail['auth_ok'] and not fail['items'] and not none['auth_ok'] and not none['items'], 'from the store\'s domain but DKIM/DMARC failed or missing: no items')
part = dict(r1, items=r1['items'][:2])
ok(not S.itemised(part), 'a receipt read only in part is not itemised (nothing counted twice)')
ok(S.clean('Acme‮Notes\x07 Pro' + 'x' * 200)[:14] == 'Acme Notes Pro' and len(S.clean('y' * 500)) == 80, 'names: one line, no control or direction characters, capped')

# ---- three months of receipts → three subscriptions under Apple
tmp = tempfile.mkdtemp()
RC = R.Recurring(tmp)


def doc(mid, date, amount, frm='no_reply@mail.acme-store.example', vendor='Apple'):
    return {'message_id': mid, 'vendor': vendor, 'vendor_key': R.vendor_key(vendor), 'date': date, 'amount': amount,
            'currency': 'DKK', 'kind': 'receipt', 'from': frm}


def rec(mid, items, day, sent):
    r = S.parse_receipt(mail(APPLE, 'Your receipt from Apple.', receipt(items, day), sent))
    r['message_id'] = mid
    return r


recs = [rec('a1@x', [item(NOTES, 'February'), item(RADIO, 'February'), MAPS], '3 Jan 2027', 'Sun, 03 Jan 2027 10:00:00 +0100'),
        rec('a2@x', [item(NOTES, 'March'), item(RADIO, 'March'), PUZZLE], '3 Feb 2027', 'Wed, 03 Feb 2027 10:00:00 +0100'),
        rec('a3@x', [item(NOTES, 'April', 69.0), item(RADIO, 'April')], '3 Mar 2027', 'Wed, 03 Mar 2027 10:00:00 +0100')]
docs = {r['message_id']: doc(r['message_id'], r['sent'], r['total']) for r in recs}
# old charges from before the itemised receipts (total only) – the old one Apple row
for i, dd in enumerate(['2026-10-03', '2026-11-03', '2026-12-03']):
    docs['old%d@x' % i] = doc('old%d@x' % i, dd, 148.0)
docs['other@x'] = doc('other@x', '2027-02-10', 120.0, frm='billing@acmestream.example', vendor='Acme Stream')

RC.refresh({k: v for k, v in docs.items() if k.startswith('old')}, today=datetime.date(2026, 12, 20))
before = RC.view()
ok([s['id'] for s in before['subs']] == ['apple:DKK'] and before['subs'][0]['store'] == 'apple'
   and before['subs'][0]['manage'] == 'https://apps.apple.com/account/subscriptions', 'no item lines yet: one Apple row as today, with Apple\'s own page')
RC.action('recurring_set', {'id': 'apple:DKK', 'ctx': 'private', 'company': 'Acme'})

RC.refresh(docs, receipts=recs, today=datetime.date(2027, 3, 10))
v = RC.view()
subs = {s['id']: s for s in v['subs']}
items = {k: s for k, s in subs.items() if s.get('source') == 'store'}
ok(set(items) == {'store:apple:acmenotespro', 'store:apple:robinradiofamily', 'store:apple:kimmapsplus'}, 'three subscriptions under Apple (%s)' % sorted(items))
ok('store:apple:sampuzzlepack' not in subs, 'the one-off purchase is not a subscription')
np_, rr, km = items['store:apple:acmenotespro'], items['store:apple:robinradiofamily'], items['store:apple:kimmapsplus']
ok(np_['interval'] == 'monthly' and np_['amount'] == 69.0 and np_['next'] == '2027-04-03' and np_['count'] == 3 and np_['first_seen'] == '2027-01-03',
   'monthly item: amount, next date, charges, first seen')
ok(rr['monthly'] == 89.0 and km['interval'] == 'yearly' and km['next'] == '2028-01-03' and km['monthly'] == round(249 / 12, 2), 'yearly item: next date and monthly share')
ok(all(s['manage'] == 'https://apps.apple.com/account/subscriptions' and s['store_name'] == 'Apple' for s in items.values()), 'Manage in Apple: the fixed page')
ok(all(s.get('ctx') == 'private' and s.get('company') == 'Acme' for s in items.values()), 'the old Apple row\'s tags are the defaults for the items')
ok('apple:DKK' not in subs, 'the old one-row Apple is replaced by the group')
oth = subs.get('store:apple:other:DKK')
ok(oth and oth['vendor'] == 'Apple – other' and oth['superseded'] and oth['store_other'], '"Apple – other" for the charges without item lines')
g = v['stores']['apple']
ok(g['count'] == 3 and g['month'] == {'DKK': round(69 + 89 + 249 / 12, 2)}, 'the group: 3 subscriptions, its total per month')
apple_month = sum(s['monthly'] for s in v['subs'] if s.get('store') == 'apple' and s.get('status') == 'active' and not s.get('superseded') and not s.get('gone'))
ok(round(apple_month, 2) == g['month']['DKK'] and v['totals']['DKK']['count'] == 3, 'totals count the items, not "other" from before them (count %s)' % v['totals']['DKK']['count'])
ch = [c for c in v['changes'] if c['sub'] == 'store:apple:acmenotespro' and c['kind'] == 'price_up']
ok(len(ch) == 1 and 'Acme Notes Pro price went up to 69 DKK/month' == ch[0]['text'], 'a price change on one item is flagged on that item')
ok(not [c for c in v['changes'] if c['kind'] == 'new' and c['sub'].startswith('store:') and not c.get('seen')],
   'the first itemised receipts announce nothing as "new" (they were the Apple row)')
RC.refresh(docs, receipts=recs, today=datetime.date(2027, 3, 11))
ok(len([c for c in RC.load()['changes'] if c['sub'] == 'store:apple:acmenotespro' and c['kind'] == 'price_up']) == 1, '… once')
lines = RC.digest_lines(datetime.date(2027, 3, 11))
ok(lines == ['Apple: 1 subscription change'], 'the digest and Listen get "<store>: N subscription changes" – never the item name (%s)' % lines)

# ---- totals the same before and after grouping
T = R.Recurring(tempfile.mkdtemp())
two = [rec('t%d@x' % i, [item(NOTES, m), item(RADIO, m)], '3 %s 2027' % d, 'Wed, 03 %s 2027 10:00:00 +0100' % d[:3])
       for i, (d, m) in enumerate([('January', 'February'), ('February', 'March'), ('March', 'April')])]
tdocs = {r['message_id']: doc(r['message_id'], r['sent'], r['total']) for r in two}
T.refresh(tdocs, today=datetime.date(2027, 3, 10))
b = T.view()['totals']['DKK']['month']
T.refresh(tdocs, receipts=two, today=datetime.date(2027, 3, 10))
a = T.view()
ok(b == 148.0 and a['totals']['DKK']['month'] == 148.0 and a['totals']['DKK']['count'] == 2, 'totals: %s before, %s after grouping' % (b, a['totals']['DKK']['month']))

# ---- "Apple – other" is dropped once three months are fully itemised
RC.refresh(docs, receipts=recs, today=datetime.date(2027, 4, 10))
ok('store:apple:other:DKK' not in RC.load()['subs'], '… three months itemised, no charge without items since: "Apple – other" is gone for good')
K = R.Recurring(tempfile.mkdtemp())
kd = dict(docs, **{'loose@x': doc('loose@x', '2027-02-20', 148.0)})
K.refresh(kd, receipts=recs, today=datetime.date(2027, 4, 10))
ko = K.load()['subs'].get('store:apple:other:DKK')
ok(ko and not ko['superseded'], 'a charge without item lines after itemising began keeps "other" – and counts it')

# ---- notices and group tags
tags = RC.action('recurring_set', {'id': 'store:apple', 'project': 'p-acme'})
ok(tags['tags']['project'] == 'p-acme' and RC.load()['store_tags']['apple']['project'] == 'p-acme', 'the group\'s tags: the default for new items')
try:
    RC.action('recurring_set', {'id': 'store:nostore', 'ctx': 'work'})
    ok(False, 'an unknown store is refused')
except R.Bad:
    ok(True, 'an unknown store is refused')
trial = rec('tr@x', [('Jamie Fit', 'Monthly', 'Free trial ends 20 March 2027', 0.0)], '12 Mar 2027', 'Fri, 12 Mar 2027 10:00:00 +0100')
trial['total'] = trial['subtotal'] = None
RC.refresh(docs, receipts=[trial], today=datetime.date(2027, 3, 14))
jf = RC.load()['subs'].get('store:apple:jamiefit')
ok(jf and jf['trial_ends'] == '2027-03-20' and jf.get('project') == 'p-acme', 'a free trial on a store item, with the group\'s project')
ok(any(c['sub'] == 'store:apple:jamiefit' and c['kind'] == 'trial' and c['text'] == 'Your free trial of Jamie Fit ends on Saturday'
       for c in RC.load()['changes']), '… and its "trial ends" change, on that item')
RC.refresh(docs, notices=[{'message_id': 'n1@x', 'kind': 'renewal', 'domain': 'acme-store.example', 'amount': 999.0, 'currency': 'DKK', 'date': '2027-04-01',
                           'sent': '2027-03-12', 'account_link': 'https://acme-store.example/evil', 'auth_ok': True}], today=datetime.date(2027, 3, 14))
ok(not any(s.get('account_link') or s.get('amount') == 999.0 for s in RC.load()['subs'].values()),
   'a generic notice from the store\'s domain adds no row and no link (the items come from the receipts)')
ok(json.load(open(RC.file))['subs']['store:apple:acmenotespro']['manage'] == 'https://apps.apple.com/account/subscriptions', 'stored with the fixed link only')

print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
