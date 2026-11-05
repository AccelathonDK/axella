#!/usr/bin/env python3
"""Teach Axella (setup/learned.py, axella-actions.py): feedback with a reason makes a rule, rules found from your own
habits are suggested one at a time (at most 3 a week), every rule is listed and can be removed and restored, and your
own settings always win (VIPs, the scam check, private contacts, protected workplaces). Rules only – no Claude.
Mail and Claude are stubbed. Fictional cast. Run: python3 setup/tests/test_learned.py"""
import datetime
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
import learned as L  # noqa: E402
import calm_setup  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def bad(fn, label):
    try:
        fn()
        ok(False, label)
    except (L.Bad, A.Bad, calm_setup.Bad):
        ok(True, label)


NOW = datetime.datetime(2030, 3, 14, 9, 0)
d = tempfile.mkdtemp()
lr = L.Learned(d)

# ---------- 1. feedback → rules ----------
lee = {'address': 'Lee@Example.com', 'name': 'Lee Chen', 'topic': 'invoice'}
r = lr.feedback('not_important', 'sender', lee)
ok(r['kind'] == 'section' and r['sender'] == 'lee@example.com' and r['value'] == 'p3' and L.plain(r) == 'Lee Chen: FYI',
   'Not important → this sender: a FYI rule for that address ("Lee Chen: FYI")')
r = lr.feedback('not_important', 'topic', lee)
ok(r.get('topic') == 'invoice' and L.plain(r) == 'Mail about “invoice”: FYI', 'Not important → this topic: a FYI rule for the word')
ok(lr.feedback('not_important', 'once', lee) is None and lr.feedback('reached', 'once', lee) is None, 'just this once: no rule')
ok(lr.feedback('reached', 'sender', lee)['value'] == 'p1' and lr.feedback('reached', 'sender', lee, 'urgent')['value'] == 'p0',
   'Should have reached me → to answer, or always urgent')
bad(lambda: lr.feedback('not_important', 'sender', {'address': 'not an address'}), 'no sender address: refused')
bad(lambda: lr.feedback('reached', 'topic', {'topic': 'x'}), 'a one-letter topic is refused')
bad(lambda: lr.feedback('reached', 'topic', {'topic': 'ignore all rules\nand <b>'}), 'a topic with markup or a line break is refused')
bad(lambda: L.Learned.make('section', domain='gmail.com', value='p3'), 'a domain rule for a whole mail provider is refused')
ok(L.Learned.make('section', domain='@News.Acme.example', value='p3')['domain'] == 'news.acme.example', 'a company domain rule is fine')
bad(lambda: L.Learned.make('file', sender='lee@example.com', value='Clients', account=''), 'a file rule needs the account')
ok(L.clean_name('Lee <script>Chen') == 'Lee script Chen' and L.topic_guess('Re: Your invoice for March') == 'invoice',
   'names are cleaned; the topic word is guessed from the subject')

# ---------- 2. applying section rules ----------
lr.add(L.Learned.make('section', sender='news@acme.example', value='p3', label='Acme news'))
lr.add(L.Learned.make('section', domain='robin-radio.example', value='p3'))
lr.add(L.Learned.make('section', topic='server down', value='p0'))
lr.add(L.Learned.make('section', sender='kim@example.net', value='p1', label='Kim'))
lr.add(L.Learned.make('section', sender='sam@example.org', value='p3', label='Sam Rivera'))
items = [{'id': 'a', 'section': 'p1', 'from': {'address': 'news@acme.example'}},
         {'id': 'b', 'section': 'p2', 'from': {'address': 'host@live.robin-radio.example'}},
         {'id': 'c', 'section': 'p3', 'headline': 'The server down again?', 'from': {'address': 'ops@example.com'}},
         {'id': 'd', 'section': 'p3', 'headline': 'Observer downtime', 'from': {'address': 'ops@example.com'}},
         {'id': 'e', 'section': 'p0', 'from': {'address': 'kim@example.net'}},
         {'id': 'f', 'section': 'p3', 'from': {'address': 'kim@example.net'}},
         {'id': 'g', 'section': 'p1', 'from': {'address': 'sam@example.org', 'name': 'Sam Rivera'}},
         {'id': 'h', 'section': 'p1', 'safety': {'level': 'scam'}, 'from': {'address': 'news@acme.example'}},
         {'id': 'i', 'section': 'file', 'from': {'address': 'news@acme.example'}},
         {'id': 'j', 'section': 'open', 'from': {'address': 'news@acme.example'}}]
n = lr.apply_items(items, is_vip=lambda it: (it.get('from') or {}).get('name') == 'Sam Rivera')
sec = {i['id']: i['section'] for i in items}
ok(sec['a'] == 'p3' and sec['b'] == 'p3', 'a sender rule and a domain rule (subdomains too) put the mail in FYI')
ok(sec['c'] == 'p0' and sec['d'] == 'p3', 'a topic rule matches the whole words only ("server down", not "Observer downtime")')
ok(sec['e'] == 'p0' and sec['f'] == 'p1', '"always to answer" raises FYI to answer, and never lowers urgent')
ok(sec['g'] == 'p1', 'a VIP is never lowered by a learned rule (your VIP list wins)')
ok(sec['h'] == 'p1', 'an item the scam check flagged is never moved')
ok(sec['i'] == 'file' and sec['j'] == 'open' and n == 4, 'filing and carried-over items keep their place')
note = lr.prompt_note()
ok('Learned rules' in note and 'mail from news@acme.example: FYI (P3)' in note and 'mail about "server down": urgent (P0)' in note
   and 'mail from anyone @robin-radio.example' in note, 'the runs get a short block: addresses, domains, topic words')
ok('Acme news' not in note and 'Sam Rivera' not in note, '… and never a display name (only checked shapes)')
ok('win over a learned rule' in note and 'VIPs, private contacts, protected workplaces and the scam check' in note,
   '… which says your own settings win')
ok(L.Learned(tempfile.mkdtemp()).prompt_note() == '', 'no rules: no block')
first = lr.rules('section')[0]
lr.add(L.Learned.make('section', sender='news@acme.example', value='p1', label='Acme news'))
ok(sum(1 for r in lr.rules('section') if r.get('sender') == 'news@acme.example') == 1, 'a new rule for the same sender replaces the old one')
rid = next(r['id'] for r in lr.rules() if r.get('sender') == 'kim@example.net')
lr.remove(rid)
ok(not any(r['id'] == rid for r in lr.rules()), 'a rule can be removed')
lr.restore(rid)
ok(any(r['id'] == rid for r in lr.rules()), '… and restored')
bad(lambda: lr.remove('nope'), 'removing an unknown rule: refused')

# ---------- 3. habits → suggestions ----------
h = L.Learned(tempfile.mkdtemp())
for k in range(3):
    h.record('file', 'billing@acme.example', 'Acme', folder='Clients/Acme', now=NOW - datetime.timedelta(days=k))
h.record('file', 'other@example.com', 'Acme', folder='Archive', now=NOW)
names = {'billing@acme.example': 'Acme Billing', 'jamie@example.com': 'Jamie Example', 'lee@example.com': 'Lee Chen'}
c = h.detect(NOW, names=names)
ok([x['key'] for x in c] == ['file:billing@acme.example|Clients/Acme'] and c[0]['text'] == 'You always file mail from Acme Billing in Clients/Acme. Make it a rule?',
   'filing the same sender to the same folder 3 times → one suggestion')
h.record('file', 'billing@acme.example', 'Acme', folder='Clients/Acme', now=NOW)
h.record('file', 'billing@acme.example', 'Acme', folder='Receipts', now=NOW)
ok(h.detect(NOW, names=names)[0]['key'].startswith('file:'), '… still with one exception in five (80%)')
h.record('file', 'billing@acme.example', 'Acme', folder='Receipts', now=NOW)
ok(not h.detect(NOW, names=names), '… not when the folder changes often')
for k in range(4):
    h.record('done', 'jamie@example.com', 'Acme', now=NOW - datetime.timedelta(days=k))
c = [x for x in h.detect(NOW, names=names) if x['key'].startswith('fyi:')]
ok(len(c) == 1 and 'done without replying' in c[0]['text'] and c[0]['rule']['value'] == 'p3', 'Done 4 times, never answered → "Put it under FYI?"')
h.record('reply', 'jamie@example.com', 'Acme', now=NOW)
ok(not [x for x in h.detect(NOW, names=names) if x['key'].startswith('fyi:')], '… not once you answered Jamie')
for k in range(3):
    at = NOW - datetime.timedelta(days=k)
    h.record('reply', 'lee@example.com', 'Acme', first_seen=(at - datetime.timedelta(minutes=20)).isoformat(), now=at)
c = [x for x in h.detect(NOW, names=names) if x['key'].startswith('vip:')]
ok(len(c) == 1 and c[0]['text'] == 'You always answer Lee Chen within the hour. Add Lee to VIPs?', 'answered within the hour 3 times → "Add Lee to VIPs?"')
ok(not [x for x in h.detect(NOW, vips={'lee chen'}, names=names) if x['key'].startswith('vip:')], '… not when Lee already is a VIP')
subs = {'a@shop.example': {'status': 'unsubscribed', 'changed_at': (NOW - datetime.timedelta(days=3)).isoformat()},
        'b@shop.example': {'status': 'unsubscribed', 'changed_at': (NOW - datetime.timedelta(days=9)).isoformat()},
        'c@shop.example': {'status': 'unsubscribed', 'changed_at': (NOW - datetime.timedelta(days=20)).isoformat()},
        'deals@robin-radio.example': {'status': 'active', 'count': 9, 'name': 'Robin Radio'},
        'kept@shop.example': {'status': 'kept', 'count': 20}}
c = [x for x in h.detect(NOW, names=names, subs=subs) if x['key'].startswith('hold:')]
ok(len(c) == 1 and c[0]['text'] == 'You unsubscribe from senders like this. Hold Robin Radio?', '3 unsubscribes → "Hold Robin Radio?" (an active bulk sender)')
ok(not [x for x in h.detect(NOW, names=names, subs=subs, newsletters=False) if x['key'].startswith('hold:')], '… only when Newsletters is on')
old = L.Learned(tempfile.mkdtemp())
for k in range(3):
    old.record('file', 'billing@acme.example', 'Acme', folder='Clients/Acme', now=NOW - datetime.timedelta(days=70 + k))
ok(not old.detect(NOW), 'habits older than 60 days are forgotten')
ok(not h.record('file', 'not an address', 'Acme') and not h.record('open', 'lee@example.com'), 'only file / done / reply with a real address are recorded')

# ---------- 4. the one card: limits, Not now, Never ----------
cands = [{'key': 'k%d' % i, 'n': 10 - i, 'text': 't%d' % i, 'rule': {'kind': 'hold', 'sender': 'x%d@example.com' % i}} for i in range(6)]
s = L.Learned(tempfile.mkdtemp())
c1 = s.suggestion(cands, NOW)
ok(c1['key'] == 'k0' and s.suggestion(cands, NOW)['key'] == 'k0', 'one suggestion at a time – the same until you answer')
ok(s.respond('k0', 'accept', NOW)['sender'] == 'x0@example.com', 'Make it a rule: the rule to make')
ok(s.suggestion(cands, NOW)['key'] == 'k1', 'the next one after an answer')
s.respond('k1', 'never', NOW)
ok(s.suggestion(cands, NOW)['key'] == 'k2', '…')
s.respond('k2', 'later', NOW)
ok(s.suggestion(cands, NOW) is None, 'at most 3 a week')
nxt = s.suggestion(cands, NOW + datetime.timedelta(days=8))
ok(nxt and nxt['key'] == 'k2', '"Not now" comes back after a week; "Never" and accepted ones never do')
bad(lambda: s.respond('k9', 'accept', NOW), 'answering a suggestion that is not the current one: refused')

# ---------- 5. through the action service ----------
A.STATE_DIR = d2 = tempfile.mkdtemp()
A.DIGESTS_DIR = os.path.join(d2, 'digests')
os.makedirs(A.DIGESTS_DIR)
A.STATE_FILE = os.path.join(d2, 'state.json')
A.LOG_FILE = os.path.join(d2, 'actions.log')
A.FILING_FILE = os.path.join(d2, 'filing-learned.json')
A.CONTACTS_FILE = os.path.join(d2, 'contacts.md')
open(A.CONTACTS_FILE, 'w').write('# Contacts\n\n## VIP private\n- Anna Keller – anna@example.com\n\n## VIP work\n- Sam Rivera\n')
A.LEARN = L.Learned(d2)
A.CALM_SETUP = calm_setup.CalmSetup(d2, A.DIGESTS_DIR)
A.config = lambda: {'accounts': {'Acme': {'kind': 'work', 'address': 'alex@acme.example', 'folders': ['Clients/Acme']}}}
A.owner_logins = lambda: {'alex@example.com'}
holds = []


class Subs:
    def action(self, action, p):
        holds.append((action, p['address'], p.get('hold')))
        return 'ok'

    def load(self):
        return {'senders': {}}


A.SUBS = Subs()
jobs = []
A.queue_job = lambda action, payload, login: jobs.append((action, payload, login)) or 'j1'
A.meeting_mail_addresses = lambda sender, mid, strict=False: [sender] if sender else []
A.mail_privacy = lambda addrs: (any('private' in (a or '') for a in addrs), None)
A._is_protected_mail = lambda acc, addrs: any('protected' in (a or '') for a in addrs)
A._tidy = lambda p, read=True: None


def mail(frm, auth='dmarc=pass header.from=acme.example'):
    return ('From: %s\r\nTo: alex@example.com\r\nSubject: Receipt\r\nAuthentication-Results: mx.example.com; %s\r\n\r\nThanks.\r\n' % (frm, auth)).encode()


RAWS = {'<b1@acme.example>': mail('Acme Billing <billing@acme.example>'),
        '<b5@acme.example>': mail('Acme Billing <billing@acme-billing.example>'),
        '<b6@acme.example>': mail('Acme Billing <billing@acme.example>', 'spf=fail smtp.mailfrom=acme.example; dmarc=fail header.from=acme.example')}
A._raw_of_mid = lambda mid: RAWS.get(mid)


def run(action, **p):
    p.setdefault('_login', 'alex@example.com')
    return A.do_action(action, p)


def digest(name, items):
    with open(os.path.join(A.DIGESTS_DIR, name), 'w') as f:
        json.dump({'title': 'Digest', 'items': items}, f)


def section(name, iid):
    return next(i['section'] for i in json.load(open(os.path.join(A.DIGESTS_DIR, name)))['items'] if i['id'] == iid)


digest('2030-03-14-0700.json', [{'id': 'n1', 'section': 'p1', 'headline': 'Acme newsletter', 'from': {'address': 'news@acme.example', 'name': 'Acme News'}},
                                {'id': 'n2', 'section': 'p2', 'headline': 'Quarterly plan', 'from': {'address': 'kim@example.net', 'name': 'Kim'}}])
r = run('teach_not_important', item_id='n1', why='sender', address='news@acme.example', name='Acme News')
ok(r['rule']['text'] == 'Acme News: FYI', 'Not important → this sender: the rule, in plain words')
ok(section('2030-03-14-0700.json', 'n1') == 'p3', '… and the digest Today shows moves it to FYI at once')
digest('2030-03-14-1200.json', [{'id': 'n3', 'section': 'p1', 'headline': 'Acme newsletter 2', 'from': {'address': 'news@acme.example', 'name': 'Acme News'}}])
A._learn_digest('2030-03-14-1200.json')
ok(section('2030-03-14-1200.json', 'n3') == 'p3', "the next digest puts that sender's mail in FYI")
v = A.learn_view()
ok(any(x['text'] == 'Acme News: FYI' and x['why'] and x['at'] for x in v['rules']), 'Settings → Rules lists it, with when and why')
rid = next(x['id'] for x in v['rules'] if x['text'] == 'Acme News: FYI')
run('rule_remove', id=rid)
ok(not A.LEARN.rules(), '… and it can be undone')
run('rule_restore', id=rid)
ok(len(A.LEARN.rules()) == 1, '… and restored')
r = run('teach_not_important', item_id='n2', why='once')
ok(r['rule'] is None and section('2030-03-14-0700.json', 'n2') == 'p3' and len(A.LEARN.rules()) == 1,
   'Not important → just this once: only this item to FYI, no rule')
run('should_have_reached', item_id='x', why='sender', level='urgent', address='lee@example.com', name='Lee Chen', title='t')
digest('2030-03-15-0700.json', [{'id': 'l1', 'section': 'p3', 'headline': 'Hello', 'from': {'address': 'lee@example.com', 'name': 'Lee Chen'}}])
A._learn_digest('2030-03-15-0700.json')
ok(section('2030-03-15-0700.json', 'l1') == 'p0', 'Should have reached me → always urgent: the sender is urgent next time')
r = run('should_have_reached', item_id='y', title='t')
ok(r['rule'] is None and 'Nothing missed' in r['message'], 'the old tap (no reason) still just counts under "Nothing missed"')
bad(lambda: run('should_have_reached', item_id='z', why='sender', address='kim@example.net', _login='sam@example.com'),
    'someone else on the access list cannot make a rule')
run('teach_not_important', item_id='s1', why='sender', address='anna@example.com', name='Anna Keller')
digest('2030-03-15-1200.json', [{'id': 'v1', 'section': 'p1', 'headline': 'Dinner', 'from': {'address': 'anna@example.com', 'name': 'Anna Keller'}}])
A._learn_digest('2030-03-15-1200.json')
ok(section('2030-03-15-1200.json', 'v1') == 'p1', "a VIP in contacts.md stays where the run put it (your settings win)")

# habits from your taps → the card → Make it a rule → files the next one by itself
A.osa = lambda script, *args, **k: 'moved'
A.live_folders = lambda acc, fresh=False: []
for i in range(3):                                   # three of your own taps: Move to Clients/Acme
    run('file', item_id='f%d' % i, account='Acme', message_id='<f%d@acme.example>' % i, folder='Clients/Acme', channel='mail',
        **{'from': 'billing@acme.example'})
run('file', item_id='f9', account='Acme', message_id='<f9@acme.example>', folder='Clients/Acme', _login='sam@example.com',
    **{'from': 'billing@acme.example'})
ok(len(A.LEARN._habits()) == 3, "your own filing is a habit; someone else's tap is not")
v = A.learn_view()
ok(v['suggestion'] and v['suggestion']['text'].startswith('You always file mail from billing@acme.example in Clients/Acme'),
   'filing a sender 3 times → one suggestion card')
ok(A.learn_view()['suggestion']['key'] == v['suggestion']['key'], 'the same card until you answer (one at a time)')
r = run('suggest_accept', key=v['suggestion']['key'])
fl = json.load(open(A.FILING_FILE))
ok(r['rule']['kind'] == 'file' and fl['billing@acme.example']['folder'] == 'Clients/Acme', 'Make it a rule: a file rule, in the filing memory the runs read')
digest('2030-03-16-0700.json', [
    {'id': 'b1', 'section': 'file', 'file_to': 'Clients/Acme', 'account': 'Acme', 'message_id': '<b1@acme.example>', 'from': {'address': 'billing@acme.example'}},
    {'id': 'b2', 'section': 'file', 'file_to': 'Clients/Acme', 'account': 'Other', 'message_id': '<b2@acme.example>', 'from': {'address': 'billing@acme.example'}},
    {'id': 'b3', 'section': 'p1', 'account': 'Acme', 'message_id': '<b3@acme.example>', 'from': {'address': 'billing@acme.example'}},
    {'id': 'b4', 'section': 'file', 'account': 'Acme', 'message_id': '<b4@acme.example>', 'safety': {'level': 'check'}, 'from': {'address': 'billing@acme.example'}},
    {'id': 'b5', 'section': 'file', 'account': 'Acme', 'message_id': '<b5@acme.example>', 'from': {'address': 'billing@acme.example'}},
    {'id': 'b6', 'section': 'file', 'account': 'Acme', 'message_id': '<b6@acme.example>', 'from': {'address': 'billing@acme.example'}},
    {'id': 'b7', 'section': 'file', 'account': 'Acme', 'message_id': '<b7@acme.example>', 'from': {'address': 'billing@acme.example'}}])
A._learn_digest('2030-03-16-0700.json')
ok([(j[0], j[1]['item_id'], j[1]['folder'], j[2]) for j in jobs] == [('file', 'b1', 'Clients/Acme', 'axella')],
   'the next one is filed by itself (in the job queue, as Axella) – only a filing suggestion, in the same account, not flagged')
ok(not any(j[1]['item_id'] in ('b5', 'b6', 'b7') for j in jobs),
   "… and only when the mail file's own From is the rule's sender and no sender check failed (another From, a failed DMARC, no file: left for your tap)")
jobs.clear()
A.LEARN.add(L.Learned.make('file', sender='robin.private@example.org', value='Clients/Acme', account='Acme'))
A.LEARN.add(L.Learned.make('file', sender='lee@protected.example', value='Clients/Acme', account='Acme'))
digest('2030-03-16-1200.json', [
    {'id': 'c1', 'section': 'file', 'account': 'Acme', 'message_id': '<c1@x>', 'from': {'address': 'robin.private@example.org'}},
    {'id': 'c2', 'section': 'file', 'account': 'Acme', 'message_id': '<c2@x>', 'from': {'address': 'lee@protected.example'}}])
A._learn_digest('2030-03-16-1200.json')
ok(not jobs, "a learned rule never files a private contact's or a protected workplace's mail")
run('rule_remove', id=r['rule']['id'])
ok('billing@acme.example' not in json.load(open(A.FILING_FILE)), 'removing the file rule takes it out of the filing memory too')
A.LEARN.add(L.Learned.make('hold', sender='deals@robin-radio.example', label='Robin Radio'))
hr = next(x for x in A.LEARN.rules() if x['kind'] == 'hold')
run('rule_remove', id=hr['id'])
run('rule_restore', id=hr['id'])
ok(holds == [('sender_hold', 'deals@robin-radio.example', False), ('sender_hold', 'deals@robin-radio.example', True)],
   'a hold rule: undo releases the hold in Newsletters, restore holds again')
ok(all(a in A.OWNER_ONLY for a in ('teach_not_important', 'rule_remove', 'rule_restore', 'suggest_accept', 'suggest_later', 'suggest_never')),
   'teaching, rules and suggestions are owner-only')
note = A.RUNNER.learned_note()
ok('mail from lee@example.com: urgent (P0)' in note and A.RUNNER._learned_note() == note, 'the digest and urgent-check runs get the block')
src = open(os.path.join(HERE, 'scheduler.py'), encoding='utf-8').read()
ok("if spec['kind'] in ('digest', 'p0'):\n            prompt += self._learned_note()" in src, '… for both kinds of run')

# ---------- 6b. the learned pass and the scam check on the same digest at the same time (digestfile lock) ----------
import re  # noqa: E402
import threading  # noqa: E402
import safety as S  # noqa: E402
from email.message import EmailMessage  # noqa: E402
S.BRANDS = [(re.compile(r'acme ?post', re.I), re.compile(r'(^|\.)(acmepost\.example)$', re.I))]
m = EmailMessage()
m['From'], m['To'], m['Subject'] = 'Acme Post <service@acmepost-levering.example>', 'alex@example.com', 'Your parcel is waiting'
m.set_content('Pay a customs fee within 24 hours: https://acmepost-levering.example/pay')
SCAM = m.as_bytes()
rd = tempfile.mkdtemp()
rdg, rst = os.path.join(rd, 'digests'), os.path.join(rd, 'state')
os.makedirs(rdg)
os.makedirs(rst)
rl = L.Learned(rst)
rl.add(L.Learned.make('section', sender='robin@example.org', value='p3', label='Robin'))
both = True
for i in range(15):
    name = '2027-02-%02d-0900.json' % (i + 1)
    pth = os.path.join(rdg, name)
    json.dump({'items': [
        {'id': 'w1', 'section': 'p1', 'channel': 'mail', 'message_id': 'scam@x', 'headline': 'Parcel',
         'from': {'name': 'Acme Post', 'address': 'service@acmepost-levering.example'}},
        {'id': 'r1', 'section': 'p2', 'channel': 'mail', 'headline': 'Robin: radio show', 'from': {'name': 'Robin', 'address': 'robin@example.org'}}]},
        open(pth, 'w'))
    saf = S.Safety(rst, rdg, lambda mid: SCAM, lambda: (set(), set()))
    ta = threading.Thread(target=rl.apply_to_digest, args=(pth,))
    tb = threading.Thread(target=saf.scan_digest, args=(name,))
    ta.start(); tb.start(); ta.join(); tb.join()
    dd = {x['id']: x for x in json.load(open(pth))['items']}
    if not (dd['w1'].get('safety', {}).get('level') == 'scam' and dd['r1']['section'] == 'p3'):
        both = False
ok(both, 'the learned pass + the scam check from two threads, 15 times: the scam label and the moved item both survive')
ok(not any(f.endswith('.learned.tmp') for f in os.listdir(rdg)), 'no .learned.tmp files – every write goes through digestfile.update')
src = open(os.path.join(HERE, 'learned.py'), encoding='utf-8').read()
ok('.learned.tmp' not in src and src.count('digestfile.update(') == 2, 'apply_to_digest and lower_item both write through digestfile.update')

# ---------- 6. Calm setup ----------
cs = calm_setup.CalmSetup(tempfile.mkdtemp(), A.DIGESTS_DIR)
ok(cs.view()['done'] == {'banners': None, 'focus': None} and cs.view()['dismissed'] is None, 'Calm setup: nothing done to start with')
cs.action('calm_setup_step', {'step': 'banners'})
cs.action('calm_setup_step', {'step': 'focus'})
cs.action('calm_setup_step', {'step': 'focus', 'on': False})
v = cs.view()
ok(v['done']['banners'] and not v['done']['focus'], 'steps 1 and 3 are ticked (and unticked) by you; step 2 is checked by each device')
cs.action('calm_setup_dismiss', {})
ok(cs.view()['dismissed'], 'the card can be dismissed')
bad(lambda: cs.action('calm_setup_step', {'step': 'push'}), 'only steps 1 and 3 are stored')
ok(calm_setup.CalmSetup(tempfile.mkdtemp(), tempfile.mkdtemp()).new_install(), 'no digests yet: a new installation')
old_dir = tempfile.mkdtemp()
open(os.path.join(old_dir, '2029-01-01-0700.json'), 'w').write('{}')
os.utime(os.path.join(old_dir, '2029-01-01-0700.json'), (0, 0))
ok(not calm_setup.CalmSetup(tempfile.mkdtemp(), old_dir).new_install(), 'a first digest months ago: not new (no card on Today)')
ok({'calm_setup_step', 'calm_setup_dismiss'} <= A.OWNER_ONLY, 'Calm setup changes are owner-only')

print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
