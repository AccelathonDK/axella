#!/usr/bin/env python3
"""Safety (setup/safety.py): the scam check and "Always hold". Invented brands, senders and numbers only – the real
brand table is swapped for a made-up one, so no real company's domain appears here.
Run: python3 setup/tests/test_safety.py"""
import json
import os
import re
import sys
import tempfile
from email.message import EmailMessage

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import safety as S  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


ok(len(S.BRANDS) >= 10, 'the built-in table names the brands scams usually pretend to be')
# a made-up world: Acme Post (acmepost.example), Acme Bank (acmebank.example), the Tax Office (tax.example)
S.BRANDS = [(re.compile(a, re.I), re.compile(r'(^|\.)(%s)$' % b, re.I)) for a, b in
            [(r'acme ?post', r'acmepost\.example'), (r'acme ?bank', r'acmebank\.example'), (r'tax office', r'tax\.example')]]


def mail(frm, subject, text='', html=None, auth='spf=pass dkim=pass dmarc=pass', reply_to=None):
    m = EmailMessage()
    m['From'], m['To'], m['Subject'] = frm, 'alex@example.com', subject
    if auth:
        m['Authentication-Results'] = 'mx.example.com; ' + auth
    if reply_to:
        m['Reply-To'] = reply_to
    m.set_content(text or 'Hello.')
    if html:
        m.add_alternative(html, subtype='html')
    return m.as_bytes()


# ---- scams (fictionalised patterns)
SCAMS = [
    ('fake parcel, look-alike domain + urgent', mail('Acme Post <service@acmepost-levering.example>', 'Your parcel is waiting',
                                                     'Pay a customs fee within 24 hours: https://acmepost-levering.example/pay')),
    ('brand in the name, other domain, failed checks', mail('Acme Bank <security@notify-mail.example>', 'Unusual sign-in',
                                                            'Verify your account now.', auth='spf=fail dkim=none dmarc=fail')),
    ('link shows one address, goes to another', mail('Tax Office <noreply@tax-refund.example>', 'You have a tax refund',
                                                     html='<p>Claim it at <a href="http://198.51.100.7/claim">www.tax.example/refund</a></p>')),
    ('punycode domain + shortened link', mail('Support <help@xn--acmbank-9ya.example>', 'Konto spærret',
                                              'Bekræft dine oplysninger: https://bit.ly/3abcde')),
]
for label, raw in SCAMS:
    level, codes = S.check_mail(raw)
    ok(level == 'scam' and codes, 'scam: %s (%s)' % (label, ','.join(codes)))

# ---- medium: one strong signal, or two weak ones
level, codes = S.check_mail(mail('Acme Post <info@shipping-news.example>', 'Acme Post newsletter', 'Our autumn offers.'))
ok(level == 'check' and codes == ['brand'], 'a brand name from another domain alone: "Check before you click"')
level, codes = S.check_mail(mail('Sam Rivera <sam@acme.example>', 'Acme Bank meeting on Friday', 'See you there.'))
ok(level is None, 'a brand in an ordinary subject is not a claim')
level, codes = S.check_mail(mail('Robin <robin@example.org>', 'Invoice', 'Payment failed – update your billing details.',
                                 reply_to='billing@other.example'))
ok(level == 'check' and set(codes) == {'reply_to', 'urgent'}, 'Reply-To elsewhere + urgent wording: "Check before you click"')

# ---- legitimate mails from the bank, the post and the tax office are not flagged
LEGIT = [
    ('the bank', mail('Acme Bank <kundeservice@acmebank.example>', 'Ny besked i din netbank',
                      html='<p>Log ind på <a href="https://www.acmebank.example/login">acmebank.example</a> for at læse den.</p>')),
    ('the post', mail('Acme Post <noreply@track.acmepost.example>', 'Your parcel is on its way',
                      'Track it: https://acmepost.example/track/5550001')),
    ('the tax office', mail('Tax Office <noreply@tax.example>', 'Your annual statement is ready', 'Log in at https://tax.example')),
    ('a newsletter with tracking links', mail('Acme Shop <news@acme-shop.example>', 'Autumn sale',
                                              html='<a href="https://click.acme-shop.example/x">See the offers</a>')),
    ('a person', mail('Lee Chen <lee@acme.example>', 'Thursday review', 'Can we move it to Friday?')),
]
for label, raw in LEGIT:
    level, codes = S.check_mail(raw)
    ok(level is None, 'legitimate: %s is not flagged (%s)' % (label, ','.join(codes) or 'no signals'))

# someone you know, really from them: not flagged even with a strong-looking signal; a sender marked safe: never
raw = mail('Kim at Acme Bank <kim@example.net>', 'Lunch?', 'Free on Friday?')
ok(S.check_mail(raw)[0] == 'check' and S.check_mail(raw, known={'kim@example.net'})[0] is None, 'a known contact is not flagged')
ok(S.check_mail(SCAMS[0][1], safe={'service@acmepost-levering.example'})[0] is None, 'a sender you marked safe is not flagged')
ok(S.check_mail(SCAMS[1][1], known={'security@notify-mail.example'})[0] == 'scam', '… but failed sender checks still are')

# a sender marked safe whose mail fails the sender checks: still a scam (someone pretending to be them)
fake = mail('Kim Example <kim@example.net>', 'Lunch?', 'Free on Friday?', auth='spf=fail dkim=fail dmarc=fail')
lv, cs = S.check_mail(fake, safe={'kim@example.net'})
ok(lv == 'scam' and cs == ['safe_auth_fail'] and 'marked safe' in S.TEXT['safe_auth_fail'], 'marked safe, but failed sender checks → scam, with its own reason')
ok(S.check_mail(mail('Kim Example <kim@example.net>', 'Lunch?', 'Free?'), safe={'kim@example.net'})[0] is None, '… and passing ones stay unflagged')

# ---- sender checks: only your own provider's verdict can say "pass"; any header can say "fail"
import email as _email  # noqa: E402
S.PROVIDERS = ['mail-provider.example']          # an invented mail provider
TOP = ('Authentication-Results: mx01.mail-provider.example; %s\n'
       'Received: from out.sender.example by mx01.mail-provider.example with ESMTPS\n')
FAKE = ('Received: from attacker.example by relay.example\n'
        'Authentication-Results: mx01.mail-provider.example; spf=pass dkim=pass header.d=example.net; dmarc=pass header.from=example.net\n')
BODY = 'From: Kim Example <kim@example.net>\nTo: alex@example.com\nSubject: Lunch?\n\nFree on Friday?\n'
real_fail = (TOP % 'spf=fail; dkim=fail header.d=example.net; dmarc=fail header.from=example.net' + FAKE + BODY).encode()
real_pass = (TOP % 'spf=pass; dkim=pass header.d=example.net; dmarc=pass header.from=example.net' + BODY).encode()
only_fake = (FAKE + BODY).encode()
chk = S.sender_checks(_email.message_from_bytes(real_fail))
ok(chk['failed'] and not chk['passed'], 'a fake pass header below a real fail: still failed, no pass counted')
ok(S.check_mail(real_fail)[0] is not None and 'auth_fail' in S.check_mail(real_fail)[1], '… and the mail is flagged')
fake_dmarc_fail = (TOP % 'spf=pass; dkim=pass header.d=example.net; dmarc=pass header.from=example.net' +
                   'Authentication-Results: x.example; dmarc=fail header.from=example.net\n' + BODY).encode()
ok(S.sender_checks(_email.message_from_bytes(fake_dmarc_fail))['failed'], 'a fail header added to the mail still counts (a fake can add a fail, never remove one)')
ok(S.check_mail(real_fail, safe={'kim@example.net'}) == ('scam', ['safe_auth_fail']), '… also for a sender marked safe')
ok(S.sender_checks(_email.message_from_bytes(real_pass)) == {'failed': False, 'passed': {'example.net'}}, 'a real pass from the provider\'s own header counts')
ok(S.sender_checks(_email.message_from_bytes(only_fake))['passed'] == set(), 'a pass header that came with the mail does not count')
ok(S.sender_checks(_email.message_from_bytes(('Authentication-Results: mx.other.example; dkim=pass header.d=example.net\n'
                                              'Received: from a by mx.other.example\n' + BODY).encode()))['passed'] == set(),
   'a pass from a server that is not your provider does not count')
odd = ('Authentication-Results: mx01.mail-provider.example; spf=pass dkim=pass header.d=example.net\n'
       'Authentication-Results: x.example; spf=softfail\n'
       'Received: from out.sender.example by mx01.mail-provider.example\n' + BODY).encode()
ok(not S.sender_checks(_email.message_from_bytes(odd))['failed'], 'an SPF softfail from another server, with your provider\'s DKIM pass, is not a failure… ')
ok(S.sender_checks(_email.message_from_bytes(('Authentication-Results: x.example; spf=softfail\n' + BODY).encode()))['failed'],
   '… but a softfail without any DKIM pass is')

# iCloud's layout: its own hops on top (internal host names without a dot), then its verdicts, then the inbound hop
ICL = ('Received: from relay by p00-mail-providermta-01 with ESMTPS\n'
       'Received: from out.sender.example by p00-mail-providermta-02 with ESMTPS\n'
       'Authentication-Results: dmarc.mail-provider.example; dmarc=pass header.from=example.net\n'
       'Authentication-Results: dkim-verifier.mail-provider.example; dkim=pass header.d=example.net\n'
       'Authentication-Results: spf.mail-provider.example; spf=pass smtp.mailfrom=example.net\n'
       'Received: from out.sender.example by out.sender.example\n')
ok(S.sender_checks(_email.message_from_bytes((ICL + BODY).encode()))['passed'] == {'example.net'}, 'iCloud layout: the provider\'s verdicts below its own hops count')
second = ICL.replace('Received: from out.sender.example by out.sender.example\n',
                     'Authentication-Results: dmarc.mail-provider.example; dmarc=pass header.from=acme.example\n'
                     'Received: from out.sender.example by out.sender.example\n')
ok(S.sender_checks(_email.message_from_bytes((second + BODY).encode()))['passed'] == {'example.net'},
   'only the provider\'s first DMARC verdict counts – a second "pass" further down is ignored')
plain_hops = ICL.replace('p00-mail-providermta-01', 'st43p00im-gw10061701').replace('p00-mail-providermta-02', 'st43p00im-gw10061702')
ok(S.sender_checks(_email.message_from_bytes((plain_hops + BODY).encode()))['passed'] == {'example.net'},
   'iCloud\'s internal hops have no dot and need not carry its name')
first_hop_other = 'Received: from a by relay.example\n' + ICL
ok(S.sender_checks(_email.message_from_bytes((first_hop_other + BODY).encode()))['passed'] == set(),
   'nothing counts when the top Received is not your provider\'s')

# a domain with no DMARC record, a forged dot-less Received line and a fake dkim=pass named after the provider
ATTACK = ('Received: from relay by p00-mail-providermta-01 with ESMTPS\n'
          'Received: from mx.attacker.example by p00-mail-providermta-02 with ESMTPS\n'
          'Authentication-Results: dmarc.mail-provider.example; dmarc=none header.from=example.net\n'
          'Authentication-Results: dkim-verifier.mail-provider.example; dkim=none\n'
          'Authentication-Results: spf.mail-provider.example; spf=softfail smtp.mailfrom=example.net\n'
          'Received: from x by forgedhost with SMTP\n'
          'Authentication-Results: dkim-verifier.mail-provider.example; dkim=pass header.d=example.net\n')
chk = S.sender_checks(_email.message_from_bytes((ATTACK + BODY).encode()))
ok(chk['failed'] and not chk['passed'], 'no DMARC record + forged dot-less Received + fake dkim=pass: still failed, no pass')
ok(S.check_mail((ATTACK + BODY).encode())[0] is not None, '… and the mail stays flagged')
no_dkim = ATTACK.replace('Authentication-Results: dkim-verifier.mail-provider.example; dkim=none\n', '')
ok(S.sender_checks(_email.message_from_bytes((no_dkim + BODY).encode()))['failed'],
   '… also when the provider wrote no DKIM verdict at all (the forged Received ends its block)')
no_hop = no_dkim.replace('Received: from x by forgedhost with SMTP\n', '')
ok(S.sender_checks(_email.message_from_bytes((no_hop + BODY).encode()))['failed'],
   '… and without the forged Received: a fake verdict after the provider\'s SPF verdict is outside its group')
dkim_other = ATTACK.replace('dkim=none\n', 'dkim=pass header.d=other.example\n', 1)
ok(S.sender_checks(_email.message_from_bytes((dkim_other + BODY).encode()))['failed'], 'a provider DKIM pass for another domain does not excuse the softfail')
real_dkim = ATTACK.replace('dkim=none\n', 'dkim=pass header.d=example.net\n', 1)
ok(not S.sender_checks(_email.message_from_bytes((real_dkim + BODY).encode()))['failed'], 'the provider\'s own DKIM pass for the From domain does')

# ---- a huge or hostile mail can't slow the check down (linear link search, capped input)
import time  # noqa: E402
t0 = time.time()
lv, cs = S.check_mail(mail('Acme Shop <news@acme-shop.example>', 'Hi', 'a.' * 100000))
t1 = time.time()
long_text = '.'.join(['ab'] * 3000) + '!'
S.check_mail(mail('Acme Shop <news@acme-shop.example>', 'Hi', html='<a href="https://acme-shop.example/x">%s</a>' % long_text))
t2 = time.time()
ok(t1 - t0 < 1.0, 'a 200 KB "a.a.a…" body is checked in under 1 s (%.2f s)' % (t1 - t0))
ok(t2 - t1 < 1.0, 'a long dotted link text is checked in under 1 s (%.2f s)' % (t2 - t1))
ok(S.find_links('see https://acme.example/a, or acmepost.example/p and www.acme-shop.com/x.') ==
   ['https://acme.example/a', 'www.acme-shop.com/x'], 'links in text: http(s) and bare host/path with a common TLD')

# ---- SMS
ok(S.check_sms('+45 00 00 00 09', 'Acme Post: your parcel is waiting, pay here https://acmepost-dk.example/p')[0] == 'scam',
   'SMS: unknown number, brand and link → scam')
ok(S.check_sms('+45 00 00 00 09', 'See this https://example.org/x')[0] == 'check', 'SMS: unknown number with a link → check')
ok(S.check_sms('+45 00 00 00 01', 'Running late, see https://example.org/map', known_numbers={'00000001'})[0] is None,
   'SMS: a number in your contacts is not flagged')
ok(S.check_sms('+45 00 00 00 09', 'Hi, is this still Alex?')[0] is None, 'SMS: no link, no brand, nothing urgent → not flagged')

# ---- the digest pass
tmp = tempfile.mkdtemp()
dg, st = os.path.join(tmp, 'digests'), os.path.join(tmp, 'state')
os.makedirs(dg)
os.makedirs(st)
RAW = {'scam1@x': SCAMS[0][1], 'ok1@x': LEGIT[4][1]}
digest = {'title': 'Morning', 'spoken': 'Good morning.', 'items': [
    {'id': 'a1', 'section': 'p0', 'channel': 'mail', 'message_id': 'scam1@x', 'headline': 'Parcel waiting',
     'from': {'name': 'Acme Post', 'address': 'service@acmepost-levering.example'}, 'draft': {'text': 'Thanks!'}},
    {'id': 'a2', 'section': 'p2', 'channel': 'mail', 'message_id': 'ok1@x', 'headline': 'Thursday review',
     'from': {'name': 'Lee Chen', 'address': 'lee@acme.example'}, 'draft': {'text': 'Friday works.'}},
    {'id': 'a3', 'section': 'p3', 'channel': 'sms', 'headline': 'Acme Post: parcel held, pay https://acmepost-dk.example/p',
     'from': {'name': '+45 00 00 00 09', 'address': '+45 00 00 00 09'}},
    {'id': 'a4', 'section': 'p3', 'channel': 'mail', 'message_id': 'news1@x', 'headline': 'Weekly offers',
     'from': {'name': 'Acme Shop', 'address': 'news@acme-shop.example'}},
    {'id': 'a5', 'section': 'cal', 'channel': 'calendar', 'headline': 'Dinner with Jamie'},
]}
name = '2027-01-04-0730.json'
json.dump(digest, open(os.path.join(dg, name), 'w'))
saf = S.Safety(st, dg, lambda mid: RAW.get(mid), lambda: ({'lee@acme.example'}, set()), lambda: {'news@acme-shop.example'})
ok(saf.scan_digest(name) == 2, 'the pass flags the scam mail and the scam SMS')
d = json.load(open(os.path.join(dg, name)))
by = {i['id']: i for i in d['items']}
ok(by['a1']['safety']['level'] == 'scam' and by['a1']['section'] == 'p3' and by['a1']['safety']['was'] == 'p0'
   and 'draft' not in by['a1'], 'a flagged mail: out of the urgent section, its draft removed')
ok(by['a1']['safety']['signals'] and all(s['text'] for s in by['a1']['safety']['signals']), '"Why flagged" lists concrete signals')
ok('safety' not in by['a2'] and by['a2']['draft'], 'a normal mail keeps its draft and section')
ok(by['a3']['safety']['level'] == 'scam', 'the SMS is flagged')
ok('a4' not in by and d['held'] == 1, 'an "Always hold" sender is taken out of the digest')
ok('a5' in by, 'calendar items are untouched')
ok(d['scam_held'] == 2 and 'possible scam' in d['spoken'], 'the spoken digest gets one calm line')
ok(saf.scan_digest(name) is None, 'each digest is checked once')

# flagged items reach Search and Ask
ok(saf.flag_of({'message_id': 'scam1@x'})['level'] == 'scam' and saf.flag_of({'message_id': 'ok1@x'}) is None, 'Search: a hit knows it is flagged')
res = {'answer': 'x', 'actions': [
    {'title': 'Reply', 'steps': [{'action': 'compose', 'payload': {'to': 'service@acmepost-levering.example'}}]},
    {'title': 'Snooze', 'steps': [{'action': 'snooze', 'payload': {'item_id': 'a1'}}]},
    {'title': 'Done', 'steps': [{'action': 'done', 'payload': {'item_id': 'a2'}}]}]}
res['actions'].append({'title': 'Mail them', 'steps': [{'action': 'compose', 'payload': {'to': ['lee@acme.example', 'Acme Post <service@acmepost-levering.example>']}}]})
out = saf.filter_ask(res)
res['actions'].pop()
ok([c['title'] for c in out['actions']] == ['Done'] and out['safety_removed'] == 3, 'Ask: no action card for a flagged item or sender (also when "to" is a list)')

# Mark safe
saf.action('safety_mark_safe', {'sender': 'service@acmepost-levering.example'})
ok(saf.flag_of({'message_id': 'scam1@x'}) is None, 'Mark safe: the sender is no longer flagged')
ok('safety' not in {i['id']: i for i in json.load(open(os.path.join(dg, name)))['items']}['a1'], '… and the label leaves its items in the digests')
ok(len(saf.filter_ask(res)['actions']) == 3, '… and Ask may suggest cards for it again')
try:
    saf.action('safety_mark_safe', {})
    ok(False, 'Mark safe needs a sender')
except S.Bad:
    ok(True, 'Mark safe needs a sender')

# ---- noise cleanup in Newsletters (subscriptions.py): the monthly "never opened" suggestion and Always hold
import datetime  # noqa: E402
from subscriptions import Subscriptions  # noqa: E402
sub = Subscriptions(st, osa=None)
now = datetime.datetime(2027, 3, 15, 12, 0)
recent, old_at = '2027-03-10T09:00', '2026-10-01T09:00'
sub._save({'senders': {
    'news@acme-shop.example': {'address': 'news@acme-shop.example', 'name': 'Acme Shop', 'domain': 'acme-shop.example',
                               'count': 23, 'unread': 23, 'first_at': '2026-12-20T08:00', 'last_at': recent, 'status': 'active'},
    'offers@acmebank.example': {'address': 'offers@acmebank.example', 'name': 'Acme Bank', 'domain': 'acmebank.example',
                                'count': 9, 'unread': 9, 'last_at': recent, 'status': 'active'},
    'digest@example.org': {'address': 'digest@example.org', 'name': 'Read sometimes', 'domain': 'example.org',
                           'count': 10, 'unread': 4, 'last_at': recent, 'status': 'active'},
    'old@example.net': {'address': 'old@example.net', 'name': 'Stopped', 'domain': 'example.net',
                        'count': 12, 'unread': 12, 'last_at': old_at, 'status': 'active'},
    'kept@example.net': {'address': 'kept@example.net', 'name': 'Kept', 'domain': 'example.net',
                         'count': 12, 'unread': 12, 'last_at': recent, 'status': 'kept'}}})
q = sub.quiet(lambda dom: 'bank' in dom, now=now)
ok([x['address'] for x in q['senders']] == ['news@acme-shop.example'] and q['senders'][0]['count'] == 23,
   'never opened: only a sender you never read, still sending – not a bank, not one you read or kept')
sub.action('senders_quiet_dismiss', {})
ok(sub.quiet(lambda dom: False, now=datetime.datetime.now())['dismissed'], '"Not now" hides this month\'s suggestion')
sub.action('sender_hold', {'address': 'news@acme-shop.example'})
ok(sub.held() == {'news@acme-shop.example'} and 'news@acme-shop.example' not in [x['address'] for x in sub.quiet(lambda dom: False, now=now)['senders']],
   'Always hold: the sender is held and leaves the suggestion')
sub.action('sender_hold', {'address': 'jamie@example.org', 'name': 'Jamie'})
ok('jamie@example.org' in sub.held(), 'Always hold works for any sender, not only bulk mail')
sub.action('sender_hold', {'address': 'jamie@example.org', 'hold': False})
ok('jamie@example.org' not in sub.load()['senders'], '… and switching it off forgets a sender that was only held')
try:
    sub.action('sender_hold', {'address': 'not an address'})
    ok(False, 'Always hold needs an address')
except Exception:
    ok(True, 'Always hold needs an address')

print('%d failed' % fails if fails else 'all passed')
sys.exit(1 if fails else 0)
