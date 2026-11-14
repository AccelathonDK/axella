#!/usr/bin/env python3
"""Bills as a To do type (setup/bills.py): suggested cards from the Receipts register, payment references read by
rules, the To do it becomes, "Looks paid", and the one morning-digest line. Invented data only.
Run: python3 setup/tests/test_bills.py"""
import datetime
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import bills as B  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


TODAY = datetime.date(2027, 3, 15)      # a Monday
tmp = tempfile.mkdtemp()
state = os.path.join(tmp, 'state')
digests = os.path.join(tmp, 'digests')
os.makedirs(state)
os.makedirs(digests)

TEXT = '''Invoice no. AC-20417
Acme Power – your electricity bill
Amount due 1.245,00 DKK, due 17 June.
Pay with the slip: +71< 123456789012345 +12345678<
or by bank: Reg. nr. 1234 Konto 1234567890
IBAN DK67 1234 5678 9012 34 · MobilePay Box 12345
Questions? https://pay.example.com/acme'''
r = B.references(TEXT)
ok(r == {'fi': '+71<123456789012345 +12345678<', 'iban': 'DK67 1234 5678 9012 34', 'account': '1234 1234567890',
         'mobilepay': '12345', 'invoice_no': 'AC-20417'}, 'references: FI slip, IBAN, reg/account, MobilePay, invoice number')
ok('iban' not in B.references('IBAN DK68 1234 5678 9012 34'), 'an IBAN with a wrong check digit is ignored')
ok(not any('http' in v for v in r.values()), 'never a link')
ok(B.references('Fakturanummer: 2027-118') == {'invoice_no': '2027-118'}, 'Danish invoice number')
ok(B.fmt_amount(1245, 'DKK') == '1.245,00 DKK' and B.fmt_amount(3410.5, 'EUR') == '3.410,50 EUR', 'amounts exact, in their own currency')

docs = {
    'm1': {'message_id': 'm1', 'vendor': 'Acme Power', 'vendor_key': 'acmepower', 'kind': 'invoice', 'amount': 1245.0, 'currency': 'DKK',
           'due': '2027-03-18', 'date': '2027-03-02', 'account': 'iCloud', 'deep_link': 'message://%3cm1%3e', 'attachments': ['invoice.pdf']},
    'm2': {'message_id': 'm2', 'vendor': 'Lee Plumbing', 'vendor_key': 'leeplumbing', 'kind': 'bill', 'amount': 3410.0, 'currency': 'DKK',
           'due': '2027-03-22', 'date': '2027-03-11', 'account': 'iCloud'},
    'm3': {'message_id': 'm3', 'vendor': 'Acme Shop', 'kind': 'invoice', 'amount': 99.0, 'currency': 'DKK', 'date': '2027-03-06'},   # no due: card invoice
    'm4': {'message_id': 'm4', 'vendor': 'Kim Books', 'kind': 'receipt', 'amount': 120.0, 'currency': 'DKK', 'date': '2027-03-06'},
    'm5': {'message_id': 'm5', 'vendor': 'Old Co', 'kind': 'bill', 'amount': 50.0, 'currency': 'DKK', 'date': '2026-11-05', 'due': '2026-11-20'},
    'm6': {'message_id': 'm6', 'vendor': 'Paid Co', 'kind': 'bill', 'amount': 50.0, 'currency': 'DKK', 'date': '2027-03-06', 'due': '2027-03-21', 'paid': '2027-03-07'},
    'm7': {'message_id': 'm7', 'vendor': 'Robin Insurance', 'kind': 'reminder', 'amount': 800.0, 'currency': 'EUR', 'date': '2027-03-03', 'due': '2027-03-10'},
    'm8': {'message_id': 'm8', 'vendor': 'Sam Rivera', 'kind': 'bill', 'amount': 10.0, 'currency': 'DKK', 'date': '2027-03-03', 'due': '2027-03-31'},
}
reads = []


def read_text(mid):
    reads.append(mid)
    return TEXT if mid == 'm1' else ''


bl = B.Bills(state)
bl.refresh(docs, TODAY, read_text, skip=lambda mid, doc: mid == 'm8')      # m8: a private contact
sug = bl.suggestions(docs, TODAY)
ok([c['id'] for c in sug] == ['m7', 'm1', 'm2'], 'suggested: bills, reminders and invoices with a due date – not receipts, card invoices, old, paid or private')
ok('m8' not in reads and sorted(reads) == ['m1', 'm2', 'm7'], 'the mail is read only for suggested bills, never for a private contact')
c1 = next(c for c in sug if c['id'] == 'm1')
ok(c1['reference']['fi'].startswith('+71<') and c1['payee'] == 'Acme Power' and c1['attachments'] == ['invoice.pdf'], 'the card: payee, amount, due, reference, PDF')
PRIV = lambda mid, doc: mid == 'm8'
bl.refresh(docs, TODAY, read_text, skip=PRIV)
ok(len(reads) == 3, 'a mail is read once')

t = bl.task_for(c1)
ok(t['text'] == 'Pay Acme Power 1.245,00 DKK' and t['due'] == '2027-03-18' and t['type'] == 'bill' and t['bill']['document'] == 'm1'
   and t['ref']['kind'] == 'bill', 'the To do: text, due, type bill, the bill object and its source')
t2 = bl.task_for(c1, {'amount': '1.300,50', 'currency': 'eur', 'reference': {'fi': '+71<1 +2<', 'x': 'y'}})
ok(t2['bill']['amount'] == 1300.5 and t2['bill']['currency'] == 'EUR' and set(t2['bill']['reference']) == {'fi'}, 'your edits: amount, currency, reference (unknown keys dropped)')
for bad in ({'amount': 'lots'}, {'currency': 'kroner'}, {'due': '17/6'}):
    try:
        bl.task_for(c1, bad)
        ok(False, 'refused: %s' % bad)
    except B.Bad:
        ok(True, 'refused: %s' % bad)

bl.set('m1', status='added', task_id='t1')
bl.set('m7', status='dismissed')
ok([c['id'] for c in bl.suggestions(docs, TODAY)] == ['m2'], 'added and Not a bill leave the suggestions')
bl.refresh(docs, TODAY, read_text, skip=PRIV)
ok(bl.load()['docs']['m7']['status'] == 'dismissed', 'Not a bill never comes back')

tasks = [{'id': 't1', 'type': 'bill', 'status': 'open', 'due': '2027-03-18', 'text': 'Pay Acme Power', 'bill': {'payee': 'Acme Power', 'amount': 1245.0, 'currency': 'DKK'}},
         {'id': 't2', 'type': 'bill', 'status': 'open', 'due': '2027-03-12', 'ctx': 'private', 'text': 'Pay Robin Insurance', 'bill': {'payee': 'Robin Insurance', 'amount': 800.0, 'currency': 'EUR'}},
         {'id': 't3', 'type': 'bill', 'status': 'open', 'due': '2027-03-31', 'text': 'Pay later', 'bill': {'payee': 'Later', 'amount': 1.0}},
         {'id': 't4', 'type': 'bill', 'status': 'done', 'due': '2027-03-16', 'bill': {'payee': 'Done'}},
         {'id': 't5', 'status': 'open', 'due': '2027-03-16', 'text': 'Not a bill'},
         {'id': 't6', 'type': 'bill', 'status': 'open', 'due': '2027-03-19', 'ctx': 'work', 'text': 'Pay Acme Cloud', 'bill': {'payee': 'Acme Cloud', 'amount': 20.0, 'currency': 'USD'}}]
ok(bl.find_looks_paid(docs, tasks) == [], 'no receipt yet: not paid')
docs['m9'] = {'message_id': 'm9', 'vendor': 'Acme Power', 'vendor_key': 'acmepower', 'kind': 'receipt', 'amount': 1245.0, 'currency': 'DKK', 'date': '2027-03-13'}
docs['m10'] = {'message_id': 'm10', 'vendor': 'Acme Power', 'vendor_key': 'acmepower', 'kind': 'receipt', 'amount': 99.0, 'currency': 'DKK', 'date': '2027-03-13'}
ok(bl.find_looks_paid(docs, tasks) == [{'id': 'm1', 'task_id': 't1', 'receipt': 'm9'}], 'a receipt from the payee for the same amount: Looks paid')

due = B.due_soon(tasks, TODAY)
ok([b['task_id'] for b in due] == ['t2', 't1', 't6'], 'due within a week and overdue, open bills only, soonest first')
ok([b['task_id'] for b in B.due_soon(tasks, TODAY, ['private'])] == ['t2', 't1'], 'a private digest leaves work bills out')
line = B.digest_line(due, TODAY)
ok(line == '1 bill overdue: Robin Insurance 800,00 EUR (since Fri). 2 bills due this week: Acme Power 1.245,00 DKK (Thu), Acme Cloud 20,00 USD (Fri).',
   'the digest line: overdue first, exact amounts, weekday')
ok(B.digest_line([], TODAY) == '', 'nothing due: no line')


def dg(name, scope=None):
    d = {'generated': name[:10] + 'T07:30:00', 'items': [], 'spoken': 'Good morning.'}
    if scope:
        d['scope'] = scope
    json.dump(d, open(os.path.join(digests, name), 'w'))


dg('2027-03-15-1230.json')
dg('2027-03-15-0730.json', ['private'])
dg('2027-03-15-0830.json')
ok(B.add_to_digest(bl, digests, '2027-03-15-1230.json', lambda: tasks, TODAY) is None, 'not in a midday digest')
ok(B.add_to_digest(bl, digests, '2027-03-15-0730.json', lambda: tasks, TODAY) == 2, 'the morning digest gets the line (its world only)')
d = json.load(open(os.path.join(digests, '2027-03-15-0730.json')))
ok(len(d['items']) == 1 and 'Acme Cloud' not in d['items'][0]['headline'] and d['items'][0]['link'] == 'bills' and 'Robin Insurance' in d['spoken'],
   'one p3 line linked to Bills, in the spoken version too')
ok(B.add_to_digest(bl, digests, '2027-03-15-0830.json', lambda: tasks, TODAY) is None, 'at most one line a day')
dg('2027-03-16-0730.json')
B.add_to_digest(bl, digests, '2027-03-16-0730.json', lambda: tasks, datetime.date(2027, 3, 16))
B.add_to_digest(bl, digests, '2027-03-16-0730.json', lambda: tasks, datetime.date(2027, 3, 16))
ok(len(json.load(open(os.path.join(digests, '2027-03-16-0730.json')))['items']) == 1, 'never twice in one digest')

ok(B.is_candidate(dict(docs['m2'], hidden=True), TODAY) is False, 'a hidden document is never a bill')

# ---- safety (security review, 6 Nov): first-time senders, changed payment details, scam-checked mail
st2 = os.path.join(tmp, 'state2')
os.makedirs(st2)
b2 = B.Bills(st2)
D2 = {
    'n1': {'message_id': 'n1', 'vendor': 'Kim Repairs', 'vendor_key': 'kimrepairs', 'kind': 'bill', 'amount': 600.0, 'currency': 'DKK',
           'due': '2027-03-25', 'date': '2027-03-10', 'from': 'Kim Repairs <billing@kim-repairs.example>'},
    'n2': {'message_id': 'n2', 'vendor': 'Acme Power', 'vendor_key': 'acmepower', 'kind': 'invoice', 'amount': 1245.0, 'currency': 'DKK',
           'due': '2027-03-20', 'date': '2027-03-08', 'from': 'Acme Power <invoice@acme-power.example>'},
    'n0': {'message_id': 'n0', 'vendor': 'Acme Power', 'vendor_key': 'acmepower', 'kind': 'receipt', 'amount': 1245.0, 'currency': 'DKK',
           'date': '2027-02-08', 'paid': '2027-02-09', 'from': 'Acme Power <invoice@acme-power.example>'},
    'n3': {'message_id': 'n3', 'vendor': 'Lee Plumbing', 'vendor_key': 'leeplumbing', 'kind': 'bill', 'amount': 300.0, 'currency': 'DKK',
           'due': '2027-03-28', 'date': '2027-03-12', 'from': 'Lee <lee@lee-plumbing.example>'},
    'n4': {'message_id': 'n4', 'vendor': 'Acme Bank Support', 'vendor_key': 'acmebanksupport', 'kind': 'bill', 'amount': 4999.0, 'currency': 'DKK',
           'due': '2027-03-18', 'date': '2027-03-13', 'from': 'Acme Bank <pay@acme-bank-secure.example>'},
    'n5': {'message_id': 'n5', 'vendor': 'Robin Hosting', 'vendor_key': 'robinhosting', 'kind': 'bill', 'amount': 99.0, 'currency': 'DKK',
           'due': '2027-03-30', 'date': '2027-03-13', 'from': 'Robin Hosting <bill@robin-hosting.example>'},
}
NEW_IBAN = 'IBAN DK67 1234 5678 9012 34'
TEXTS = {'n1': 'Pay to IBAN DK67 1234 5678 9012 34', 'n2': NEW_IBAN, 'n3': 'MobilePay Box 54321', 'n4': NEW_IBAN, 'n5': ''}
GOOD = (b'From: Kim Repairs <billing@kim-repairs.example>\r\nTo: alex@example.com\r\nSubject: Invoice 118\r\n'
        b'Authentication-Results: mx.icloud.com; dmarc=pass header.from=kim-repairs.example\r\n\r\nYour invoice is attached.\r\n')
FAKE = (b'From: Acme Bank <pay@acme-bank-secure.example>\r\nTo: alex@example.com\r\nSubject: Payment overdue\r\n'
        b'Authentication-Results: mx.icloud.com; spf=fail smtp.mailfrom=acme-bank-secure.example; dmarc=fail header.from=acme-bank-secure.example\r\n\r\n'
        b'Pay now to avoid closure.\r\n')
RAW = {'n1': GOOD, 'n2': GOOD, 'n3': GOOD, 'n4': FAKE}            # n5: not on the Mac mini
ok(B.mail_risk(GOOD) is None and B.mail_risk(FAKE) in ('scam', 'auth') and B.mail_risk(None) == 'missing', 'mail_risk: clean, failed sender check, missing')
read2 = []
b2.remember('acmepower', {'iban': 'DK50 1111 2222 3333 44'}, datetime.date(2027, 2, 9))     # Acme Power's earlier details
b2.refresh(D2, TODAY, lambda m: (read2.append(m), TEXTS[m])[1], skip=lambda m, doc: B.mail_risk(RAW.get(m)))
cards = {c['id']: c for c in b2.suggestions(D2, TODAY, known={'lee@lee-plumbing.example'})}
ok('n4' not in cards and b2.load()['docs']['n4']['status'] == 'blocked' and 'n4' not in read2,
   'a scam-flagged mail that was never in a digest: no card, never read, blocked for good')
ok('n5' not in cards and 'n5' not in b2.load()['docs'], 'a mail that can\'t be checked (not on the Mac mini): no card, tried again later')
c = cards['n1']
ok(c['first_time'] and c['reference_hidden'] and not c['details_differ'], 'a first-time sender: the note, details hidden')
tk = b2.task_for(c)
ok(tk['bill']['reference'] == {} and tk['bill'].get('first_time'), '… and no details on the To do unless you showed and kept them')
ok(b2.task_for(c, {'reference': c['reference']})['bill']['reference'].get('iban') == 'DK67 1234 5678 9012 34', '… after Show payment details, they go on the To do')
ok(not cards['n3']['first_time'], 'a sender in Contacts is not a first-time sender')
c2 = cards['n2']
ok(not c2['first_time'] and c2['details_differ'] and c2['reference_hidden'], 'a known payee with a new IBAN: the warning, details not prefilled')
t2b = b2.task_for(c2)
ok(t2b['bill'].get('details_differ') and t2b['bill']['reference'] == {}, '… and the warning stays on the To do')
b2.remember('acmepower', {'iban': 'DK67 1234 5678 9012 34'})
c2b = next(x for x in b2.suggestions(D2, TODAY) if x['id'] == 'n2')
ok(not c2b['details_differ'] and not c2b['reference_hidden'] and b2.task_for(c2b)['bill']['reference'].get('iban'), 'the same details as last time: prefilled, no warning')
ok(B.details_differ({'fi': '+71<111 +12345678<'}, {'fi_creditor': '87654321'}) and not B.details_differ({'fi': '+71<222 +12345678<'}, {'fi_creditor': '12345678'}),
   'FI: the creditor number counts, not the payment id')
ok(B.details_differ({'account': '1234 1234567890'}, {'account': '12340000000001'}), 'a changed bank account counts')

# ---- a look-alike payee (rebuilt with invented data): the same payee name from another domain, with new details
st3 = os.path.join(tmp, 'state3')
os.makedirs(st3)
b3 = B.Bills(st3)
D3 = {
    'o1': {'message_id': 'o1', 'vendor': 'Acme Power', 'vendor_key': 'acmepower', 'kind': 'invoice', 'amount': 410.0, 'currency': 'DKK',
           'due': '2027-01-20', 'date': '2027-01-05', 'paid': '2027-01-18', 'from': 'Acme Power <invoice@mail.acme-power.example>'},
    'o2': {'message_id': 'o2', 'vendor': 'Acme Power', 'vendor_key': 'acmepower', 'kind': 'invoice', 'amount': 395.0, 'currency': 'DKK',
           'due': '2027-02-20', 'date': '2027-02-05', 'paid': '2027-02-17', 'from': 'Acme Power <invoice@mail.acme-power.example>'},
    'x1': {'message_id': 'x1', 'vendor': 'Acme Power', 'vendor_key': 'acmepower', 'kind': 'bill', 'amount': 2890.0, 'currency': 'DKK',
           'due': '2027-03-17', 'date': '2027-03-13', 'from': 'Acme Power <payments@acme-power-billing.example>'},
    'g1': {'message_id': 'g1', 'vendor': 'Acme Power', 'vendor_key': 'acmepower', 'kind': 'invoice', 'amount': 402.0, 'currency': 'DKK',
           'due': '2027-03-20', 'date': '2027-03-05', 'from': 'Acme Power <invoice@acme-power.example>'},
}
T3 = {'o1': 'IBAN DK50 1111 2222 3333 44', 'o2': 'Pay to IBAN DK67 1234 5678 9012 34 by the due date',
      'x1': 'Urgent: pay to IBAN GB32 ACME 1234 5612 3456 78 today', 'g1': 'IBAN DK67 1234 5678 9012 34'}
read3 = []
b3.refresh(D3, TODAY, lambda m: (read3.append(m), T3[m])[1], skip=lambda m, doc: None)
ok(b3.load()['payees']['acmepower']['iban'] == 'DK6712345678901234' and read3.count('o2') == 1 and 'o1' not in read3,
   'seeded: the payee\'s details from its newest earlier bill mail, read once')
c3 = {c['id']: c for c in b3.suggestions(D3, TODAY)}
x = c3['x1']
ok(x['first_time'] and x['sender_differs'] and x['details_differ'] and x['reference_hidden'],
   'look-alike payee from another domain with a new IBAN: first bill, another address, details differ – all shown')
tx = b3.task_for(x)
ok(tx['bill']['reference'] == {} and tx['bill'].get('sender_differs') and tx['bill'].get('details_differ') and tx['bill'].get('first_time'),
   '… nothing prefilled on the To do, and the warnings stay on it')
g = c3['g1']
ok(not g['first_time'] and not g['sender_differs'] and not g['details_differ'] and not g['reference_hidden'] and g['reference'].get('iban'),
   'the real payee (same domain, sub-domain or not, same IBAN): no warning, details prefilled')
ok(B.first_time('z', {'vendor_key': 'acmepower', 'date': '2027-03-14', 'from': 'x@acme-other.example'}, {k: v for k, v in D3.items() if k != 'x1'}),
   'the same payee name alone never makes a sender known')
ok(not B.sender_differs('z', {'vendor_key': 'newco', 'date': '2027-03-14', 'from': 'a@newco.example'}, D3), 'a payee with no earlier documents: no "another address" warning')

# ---- payment details live in bills.json, never on the To do (Claude runs read tasks.json)
ok(b3.set_ref('t7', {'iban': 'DK67 1234 5678 9012 34', 'x': 'y'}) == {'iban': 'DK67 1234 5678 9012 34'} and b3.refs({'t7'}) == {'t7': {'iban': 'DK67 1234 5678 9012 34'}},
   'a bill To do\'s payment details are kept in bills.json, keyed by the task')
b3.set_ref('t7', None)
ok(b3.refs() == {}, '… and removed again')
old = [{'id': 't8', 'type': 'bill', 'bill': {'payee': 'Acme Power', 'reference': {'fi': '+71<123 +12345678<'}}}, {'id': 't9', 'text': 'Not a bill'}]
ok(b3.take_refs(old) and 'reference' not in old[0]['bill'] and b3.refs({'t8'})['t8']['fi'] == '+71<123 +12345678<',
   'details still on an older To do move to bills.json and leave the To do')
ok(not b3.take_refs(old), '… once')
ok(oct(os.stat(os.path.join(st3, 'bills.json')).st_mode & 0o777) == '0o600', 'bills.json is readable by the owner only')
import scheduler  # noqa: E402
ok('state/bills.json' in scheduler.SECRETS, 'bills.json is on the SECRETS list (no Claude run reads it)')

# the same bill twice: a pro forma and its invoice (or a copy in a reply) – one To do, no second card
D4 = {
    'pf': {'message_id': 'pf', 'vendor': 'Northwind Freight', 'vendor_key': 'northwindfreight', 'kind': 'invoice', 'amount': 1500.5, 'currency': 'USD',
           'due': '2027-03-04', 'date': '2027-03-04', 'account': 'iCloud', 'attachments': ['Pro forma 12345.pdf']},
    'inv': {'message_id': 'inv', 'vendor': 'Northwind Freight', 'vendor_key': 'northwindfreight', 'kind': 'invoice', 'amount': 1500.5, 'currency': 'USD',
            'due': '2027-03-20', 'date': '2027-03-06', 'account': 'iCloud', 'attachments': ['Tax invoice 12345.pdf']},
    'next': {'message_id': 'next', 'vendor': 'Northwind Freight', 'vendor_key': 'northwindfreight', 'kind': 'invoice', 'amount': 1500.5, 'currency': 'USD',
             'due': '2027-04-19', 'date': '2027-04-05', 'account': 'iCloud'},
    'other': {'message_id': 'other', 'vendor': 'Northwind Freight', 'vendor_key': 'northwindfreight', 'kind': 'invoice', 'amount': 1501.5, 'currency': 'USD',
              'due': '2027-03-20', 'date': '2027-03-06', 'account': 'iCloud'},
    'rem': {'message_id': 'rem', 'vendor': 'Northwind Freight', 'vendor_key': 'northwindfreight', 'kind': 'reminder', 'amount': 1500.5, 'currency': 'USD',
            'due': '2027-03-22', 'date': '2027-03-15', 'account': 'iCloud'},
}
st4 = os.path.join(tmp, 'st4')
os.makedirs(st4)
b4 = B.Bills(st4)
b4.refresh(D4, TODAY, None)
tasks4 = [{'id': 't40', 'type': 'bill', 'status': 'open', 'text': 'Pay Northwind Freight 1.500,50 USD',
           'bill': {'payee': 'Northwind Freight', 'amount': 1500.5, 'currency': 'USD', 'document': 'pf', 'vendor_key': 'northwindfreight'}}]
b4.set('pf', status='added', task_id='t40')
ids = sorted(c['id'] for c in b4.suggestions(D4, TODAY, tasks=tasks4))
ok('inv' not in ids and 'rem' not in ids, 'the invoice after its pro forma (same payee, amount, currency, due 16 days apart) is no second card')
ok('next' in ids and 'other' in ids, "… but next month's bill for the same amount, and a different amount, are cards")
ok('inv' in [c['id'] for c in b4.suggestions(D4, TODAY)], 'without the To do list (as before) it would be a card')
tasks4[0]['status'] = 'done'
ids = sorted(c['id'] for c in b4.suggestions(D4, TODAY, tasks=tasks4))
ok('inv' not in ids and 'rem' in ids, 'paid: the copy stays hidden, a reminder shows – worth a look after paying')
ok(not B.same_bill({'vendor_key': 'x', 'amount': 5.0, 'currency': 'DKK'}, {'vendor_key': 'x', 'amount': 5.0, 'currency': 'DKK'}),
   'no dates to compare: better a card than a hidden bill')

print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
