#!/usr/bin/env python3
"""People view and keep in touch (setup/people.py, birthdays.py): one person across streams, private contacts as
metadata only, open between you, meetings, the keep-in-touch rhythm and its one digest line. Invented data only.
Run: python3 setup/tests/test_people.py"""
import datetime
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import people as P  # noqa: E402
import birthdays as B  # noqa: E402
from store import Store  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


TODAY = datetime.date(2027, 5, 20)
tmp = tempfile.mkdtemp()
state = os.path.join(tmp, 'state')
digests = os.path.join(tmp, 'digests')
os.makedirs(state)
os.makedirs(digests)
st = Store(tmp, state)
st.init()
st._world = lambda: (lambda item_id, addr, context, account: context or 'private')

ALEX = {'id': 'C1:ABPerson', 'name': 'Alex Example', 'first': 'Alex', 'company': 'Acme', 'emails': ['alex@example.com'],
        'phones': [{'label': 'mobile', 'value': '+45 00 00 00 01'}], 'birthday': '1990-05-21'}
KIM = {'id': 'C2:ABPerson', 'name': 'Kim Rivera', 'first': 'Kim', 'emails': ['kim@example.org'], 'phones': [], 'private': True}
SAM = {'id': 'C3:ABPerson', 'name': 'Sam Rivera', 'first': 'Sam', 'emails': ['sam@example.net'], 'phones': []}
JAMIE = {'name': 'Jamie', 'emails': ['jamie@example.org'], 'phones': [], 'source': 'mail'}
PEOPLE = [ALEX, KIM, SAM, JAMIE]

rows = [  # digest, id, generated, section, channel, account, context, from_name, from_address, subject, headline, detail, first_seen
    ('2027-05-19-0730', 'a1', '2027-05-19T07:30:00', 'p1', 'mail', 'iCloud', 'work', 'Alex Example', 'Alex@Example.com', 'Quote for the shed', 'Alex asks for the quote', 'Wants it by Friday.', '2027-05-19T07:30:00'),
    ('2027-05-18-0730', 'a2', '2027-05-18T07:30:00', 'p2', 'imessage', None, 'private', 'Alex Example', '+4500000001', None, 'Alex: dinner Saturday?', 'Asks about Saturday.', '2027-05-18T07:30:00'),
    ('2027-05-12-0730', 'a3', '2027-05-12T07:30:00', 'p3', 'whatsapp', None, 'private', 'Alex Example', '0045 00 00 00 01', None, 'Alex sent a photo', 'A photo of the lake.', '2027-05-12T07:30:00'),
    ('2027-05-10-0730', 'a4', '2027-05-10T07:30:00', 'p2', 'whatsapp', None, 'private', 'Alex Example', '', None, 'Alex: see you', 'Short note.', '2027-05-10T07:30:00'),
    ('2027-05-19-0730', 'k1', '2027-05-19T07:30:00', 'p1', 'mail', 'iCloud', 'private', 'Kim Rivera', 'kim@example.org', 'Secret plans', 'Kim about the plans', 'Every detail.', '2027-05-19T07:30:00'),
    ('2027-03-01-0730', 's1', '2027-03-01T07:30:00', 'p2', 'mail', 'iCloud', 'private', 'Sam Rivera', 'sam@example.net', 'Spring', 'Sam says hi', 'Hi.', '2027-03-01T07:30:00'),
    ('2027-05-19-0730', 'f1', '2027-05-19T07:30:00', 'file', 'mail', 'iCloud', 'work', 'Alex Example', 'alex@example.com', 'Filing', 'File it', '', '2027-05-19T07:30:00'),
]
with st._db() as db:
    for r in rows:
        db.execute('INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', r[:12] + ('m-' + r[1], None, None, r[12], 0, 0, 0))
    db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?)', ('c1', '2027-05-15T12:00:00', 300, 'Alex', '+45 00000001', 'known', 'p2', 'private', 'x', 'en'))
    for at, act, res, item in (('2027-05-18T09:00:00', 'reply_send', 'sent', 'a2'), ('2027-05-19T08:00:00', 'done', 'done', 'x9'),
                               ('2027-05-19T09:00:00', 'reply_send', 'error: offline', 'a1')):
        db.execute('INSERT INTO actions VALUES (?,?,?,?,?,?,?,?)', (at, 'owner', act, res, item, None, None, None))

idx = P.Index(st, today=TODAY)
dup = P.ambiguous_names(PEOPLE)
items = idx.items_of(ALEX)
ok(sorted(r['id'] for r in items) == ['a1', 'a2', 'a3', 'a4'], 'one person: mail, iMessage and WhatsApp (any number format) and a full-name match')
ok('f1' not in [r['id'] for r in items], 'filing suggestions are not contact')
last = idx.last_contact(ALEX)
ok(set(last) == {'mail', 'imessage', 'whatsapp', 'call'} and last['imessage'] == '2027-05-18T09:00:00', 'last contact per channel – your reply from Axella counts, a failed one does not')
ok(sorted(r['id'] for r in P.Index(st, today=TODAY).items_of(ALEX, unique_name=False)) == ['a1', 'a2', 'a3'], 'a shared name never matches a message without an address')
ix2 = P.Index(st, today=TODAY)
ix2.extra = {'sam@example.net': {'mail': '2027-05-02T10:00:00'}, '+4500000001': {'signal': '2027-05-19T21:00:00'}}
ok(ix2.last_contact(SAM) == {'mail': '2027-05-02T10:00:00'} and ix2.last_contact(ALEX)['signal'] == '2027-05-19T21:00:00',
   'last contact also from Mail\'s index and the chat exports (mail you wrote in Mail counts)')

digest_items = [
    {'id': 'a1', 'section': 'p1', 'channel': 'mail', 'headline': 'Alex asks for the quote', 'from': {'name': 'Alex Example', 'address': 'alex@example.com'}},
    {'id': 'w1', 'section': 'wait', 'channel': 'mail', 'headline': 'Waiting for the drawings', 'from': {'name': 'Alex Example', 'address': 'alex@example.com'}},
    {'id': 'x9', 'section': 'p2', 'channel': 'mail', 'headline': 'Already handled', 'from': {'address': 'alex@example.com'}},
    {'id': 'k1', 'section': 'p1', 'channel': 'mail', 'headline': 'Kim about the plans', 'from': {'address': 'kim@example.org'}},
    {'id': 'o1', 'section': 'p1', 'channel': 'mail', 'headline': 'Someone else', 'from': {'address': 'lee@example.com'}},
]
promises = [{'id': 'pr1', 'status': 'suggested', 'text': 'Send Alex the quote', 'due': '2027-05-21', 'person': {'name': 'Alex', 'address': 'alex@example.com'}},
            {'id': 'pr2', 'status': 'added', 'protected': True, 'text': 'hidden words', 'task_id': 't1', 'person': {'address': 'alex@example.com'}},
            {'id': 'pr3', 'status': 'dismissed', 'text': 'Not one', 'person': {'address': 'alex@example.com'}}]
tasks = [{'id': 't1', 'text': 'Alex: follow up', 'status': 'open', 'ref': {'kind': 'promise', 'person': {'address': 'alex@example.com'}}},
         {'id': 't2', 'text': 'Call Alex back', 'status': 'open', 'ref': {'kind': 'promise', 'person': {'address': '+45 00 00 00 01'}}}]
preps = [{'id': 'm1', 'title': 'Shed planning', 'start': '2027-05-25T10:00', 'attendees': [{'name': 'Alex', 'email': 'ALEX@example.com'}]},
         {'id': 'm2', 'title': 'Kick-off', 'start': '2027-04-02T10:00', 'attendees': [{'name': 'Alex', 'email': 'alex@example.com'}]},
         {'id': 'm3', 'title': 'Other', 'start': '2027-05-26T10:00', 'attendees': [{'name': 'Lee', 'email': 'lee@example.com'}]}]
debt = [{'who': 'alex@example.com', 'days': 6, 'channel': 'mail'}, {'who': 'lee@example.com', 'days': 9}]
v = P.view(ALEX, st, idx, digest_items, debt, promises, tasks, preps, note={'text': 'Likes sailing'}, keep={'every': 30}, today=TODAY)
ok([x['id'] for x in v['open']['to_answer']] == ['a1'] and [x['id'] for x in v['open']['waiting']] == ['w1'], 'open: to answer and waiting – handled items and other people left out')
ok(v['open']['reply_owed'] == [{'days': 6, 'channel': 'mail'}], 'open: the reply you owe')
ok([(x['id'], x['text']) for x in v['open']['promises']] == [('pr1', 'Send Alex the quote'), ('pr2', None), (None, 'Call Alex back')],
   'open: your promises – a protected one without its words, a dismissed one gone, a promise To do by phone')
ok([m['id'] for m in v['meetings']['upcoming']] == ['m1'] and [m['id'] for m in v['meetings']['past']] == ['m2'], 'meetings: upcoming and past preps they are invited to')
ok(v['world'] == 'private' and v['note'] == {'text': 'Likes sailing'} and v['in_contacts'], 'header: the world from their items; your note')
tl = v['timeline']
ok([e['at'] for e in tl] == sorted([e['at'] for e in tl], reverse=True) and {e['dir'] for e in tl} == {'in', 'out', 'call'}, 'timeline: newest first, with your replies and calls')
ok(any(e.get('title') == 'Quote for the shed' for e in tl), 'timeline: titles for an ordinary contact')

vk = P.view(KIM, st, idx, digest_items, [], [], [], [], today=TODAY)
ok(vk['private'] and vk['timeline'] and all('title' not in e and 'snippet' not in e for e in vk['timeline']), 'private contact: timeline is metadata only')
ok(vk['open']['to_answer'] and all('title' not in x for x in vk['open']['to_answer']), 'private contact: open items without titles')
ok('Secret' not in json.dumps(vk) and 'Every detail' not in json.dumps(vk), 'private contact: no subject or snippet anywhere in the page data')

ok(P.pid_of(JAMIE) == 'mail:jamie@example.org' and P.find(PEOPLE, 'mail:jamie@example.org') is JAMIE, 'a mail-only correspondent has a stable id')
ok(P.span(10) == '10 days' and P.span(35) == 'five weeks' and P.span(100) == 'three months' and P.span(800) == 'over a year', 'how long, in words')
ok(P.line('Robin', 35) == "It's been five weeks since you spoke to Robin.", 'the digest line')

pp = P.People(state)
for bad in ('', 'a b', '<x>', 'a' * 200):
    try:
        pp.set_keep(bad, 30)
        ok(False, 'bad id refused: %r' % bad[:10])
    except P.Bad:
        ok(True, 'bad id refused: %r' % bad[:10])
try:
    pp.set_keep('C3:ABPerson', 7)
    ok(False, 'only 14, 30 or 91 days')
except P.Bad:
    ok(True, 'only 14, 30 or 91 days')
pp.set_keep('C3:ABPerson', 30, today=datetime.date(2027, 4, 1))      # Sam: last spoke 1 Mar, added 1 Apr
pp.set_keep('C2:ABPerson', 14, today=datetime.date(2027, 4, 1))      # Kim: private
pp.set_keep('C1:ABPerson', 14, today=datetime.date(2027, 4, 1))      # Alex: in touch yesterday
due = pp.due(PEOPLE, idx, TODAY)
ok([x['id'] for x in due] == ['C3:ABPerson'] and due[0]['days'] == 49, 'due: the rhythm counts from adding when the last contact is older; recent contact is not due')
ok(pp.due(PEOPLE, ix2, TODAY) == [], '… and a mail sent from Mail itself 18 days ago means Sam is not due')
kim_due = {'id': 'C2:ABPerson', 'name': 'Kim', 'days': 60, 'every': 14, 'private': True, 'mentioned': None}
ok(pp.pick_line([kim_due] + due, TODAY)['id'] == 'C3:ABPerson', 'the line never names a private contact')
pp.set_keep('C1:ABPerson', None)
ok('C1:ABPerson' not in pp.keep(), 'remove from keep in touch')

pp.set_note('C3:ABPerson', 'x' * 3000)
ok(len(pp.notes()['C3:ABPerson']['text']) == P.NOTE_MAX, 'a note is capped')
pp.set_note('C3:ABPerson', '  ')
ok('C3:ABPerson' not in pp.notes(), 'an empty note removes it')


def dg(name, scope=None):
    d = {'generated': name[:10] + 'T07:30:00', 'items': [], 'spoken': 'Good morning.'}
    if scope:
        d['scope'] = scope
    json.dump(d, open(os.path.join(digests, name), 'w'))


calls = []


def due_fn():
    calls.append(1)
    return pp.due(PEOPLE, idx, TODAY)


dg('2027-05-20-0730.json', ['work'])
dg('2027-05-20-0830.json', ['private'])
dg('2027-05-20-1530.json')
ok(pp.add_to_digest(digests, '2027-05-20-0730.json', due_fn, TODAY) is None and not json.load(open(os.path.join(digests, '2027-05-20-0730.json')))['items'],
   'a work-only digest gets no keep-in-touch line')
ok(pp.add_to_digest(digests, '2027-05-20-0830.json', due_fn, TODAY) == 'C3:ABPerson', 'a private digest gets the line')
d = json.load(open(os.path.join(digests, '2027-05-20-0830.json')))
ok(len(d['items']) == 1 and d['items'][0]['headline'] == "It's been seven weeks since you spoke to Sam." and d['items'][0]['person'] == 'C3:ABPerson'
   and 'Sam' in d['spoken'], 'one discreet p3 line, linked to the person, in the spoken version too')
pp.add_to_digest(digests, '2027-05-20-0830.json', due_fn, TODAY)
ok(len(json.load(open(os.path.join(digests, '2027-05-20-0830.json')))['items']) == 1, 'never more than one line per digest')
n = len(calls)
ok(pp.add_to_digest(digests, '2027-05-20-1530.json', due_fn, TODAY) is None and len(calls) == n, 'at most one line a day (nothing computed)')
ok(pp.add_to_digest(digests, '2027-05-20-0830-p0.json', due_fn, TODAY) is None, 'never in an urgent digest')
dg('2027-05-23-0730.json')
ok(pp.add_to_digest(digests, '2027-05-23-0730.json', due_fn, datetime.date(2027, 5, 23)) is None, 'the same person at most once a week')
dg('2027-05-28-0730.json')
ok(pp.add_to_digest(digests, '2027-05-28-0730.json', due_fn, datetime.date(2027, 5, 28)) == 'C3:ABPerson', '… and again after a week without contact')

bd = B.Birthdays(state)
bd.keep = lambda: {'C3:ABPerson'}
ok(bd.shown(SAM) and not bd.shown(ALEX) and bd.shown(dict(ALEX, vip=True)), 'birthdays: keep-in-touch people and Favourites by default')
bd.set_show('C3:ABPerson', False)
ok(not bd.shown(SAM), 'birthdays: your switch wins over keep in touch')
bd.keep = lambda: {'C2:ABPerson'}
ok(not bd.shown(KIM), 'birthdays: never a private contact')

import scheduler  # noqa: E402
ok({'state/people-notes.json', 'state/keep-in-touch.json'} <= set(scheduler.SECRETS), 'notes and keep in touch are on the SECRETS list (no Claude run reads them)')
ok(oct(os.stat(os.path.join(state, 'people-notes.json')).st_mode & 0o777) == '0o600', 'the notes file is readable by the owner only')

print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
