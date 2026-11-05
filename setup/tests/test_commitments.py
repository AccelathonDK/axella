#!/usr/bin/env python3
"""Promises and reply debt (setup/commitments.py): found by rules, in English and Danish, never brought back once
dismissed; reply debt counts only real people over their world's threshold. Fictional cast.
Run: python3 setup/tests/test_commitments.py"""
import datetime
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import commitments as C  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


wed = datetime.datetime(2026, 11, 4, 15, 0).astimezone()
d = lambda s: [(f['sentence'], f['due'] and f['due'].isoformat()) for f in C.find(s, wed)]
ok(d("Thanks. I'll send the revised quote Friday.\n\nOn Tue Lee wrote:\n> I'll call you tomorrow") == [("I'll send the revised quote Friday.", '2026-11-06')],
   'English, with the weekday; the quoted mail below is not yours')
ok(d('Hej Kim, jeg vender tilbage i morgen med en pris.')[0][1] == '2026-11-05', 'Danish: "jeg vender tilbage i morgen"')
ok(d('Jeg sender kontrakten inden ugen er omme.')[0][1] == '2026-11-06', 'Danish: "inden ugen er omme" = Friday')
ok(d('Let me check with the team and get back to you next week.')[0][1] == '2026-11-09', '"next week" = Monday')
ok(d('I will have it ready by 12 Nov.')[0][1] == '2026-11-12', 'a date')
ok(d("I'll forward the invoice later today.")[0][1] == '2026-11-04', '"later today"')
ok(d('Vi ringer dig på mandag.')[0][1] == '2026-11-09', 'Danish weekday')
ok(d("I'll look into it.")[0][1] is None, 'a promise without a date has no due date')
for s in ('Could I send it later?', "I'll be out of office until Monday.", 'Thanks, sounds good!', 'Skal jeg sende den?',
          'Can you send it tomorrow?', 'Hope you have a nice weekend.'):
    ok(d(s) == [], 'not a promise: ' + s)
ok(C.summary("I'll send the quote Friday", 'Lee') == 'You promised Lee: "I\'ll send the quote Friday."', 'the card text')
ok(C.attributed_text(b'xxNSString\x01\x94\x84\x01+\x0bI\'ll call u') == "I'll call u", 'iMessage text from attributedBody')

st = tempfile.mkdtemp()
P = C.Promises(st)
item = {'key': 'k1', 'sentence': "I'll send the revised quote Friday.", 'text': 'You promised Lee', 'due': '2026-11-06',
        'person': {'name': 'Lee Chen', 'address': 'lee@acme.example'}, 'world': 'work',
        'source': {'kind': 'mail', 'account': 'Acme', 'message_id': 'm1', 'at': '2026-11-04T15:00:00+01:00'}}
ok(P.merge([item], wed) == 1 and P.merge([item], wed) == 0, 'a promise is suggested once')
pid = P.suggestions()[0]['id']
P.set(pid, status='dismissed')
ok(P.merge([item], wed) == 0 and not P.suggestions(), 'a dismissed promise never comes back')
item2 = dict(item, key='k2', sentence="I'll send the revised quote Friday.")
P.merge([item2], wed)
p2 = next(x for x in P.load()['items'] if x['key'] == 'k2')['id']
P.set(p2, status='added', task_id='t1')
P.mark_fulfilled([{'person': 'lee@acme.example', 'at': '2026-11-03T10:00:00+01:00', 'text': 'the quote', 'attachment': True}])
ok(not P.looks_done(), 'a message from before the promise does not count')
P.mark_fulfilled([{'person': 'kim@example.org', 'at': '2026-11-05T10:00:00+01:00', 'text': 'revised quote', 'attachment': True}])
ok(not P.looks_done(), 'a message to someone else does not count')
P.mark_fulfilled([{'person': 'lee@acme.example', 'at': '2026-11-05T10:00:00+01:00', 'text': 'Here you go', 'attachment': True}])
ok(len(P.looks_done()) == 1, 'a later mail to Lee with an attachment: "Looks done"')

# fix round 7: a promise without a date fades after 14 days; one with a date stays
P3 = C.Promises(tempfile.mkdtemp())
vague = dict(item, key='k9', sentence="I'll let you know.", due=None, source=dict(item['source'], at='2026-11-04T15:00:00+01:00'))
dated = dict(item, key='k10', due='2026-11-30', source=dict(item['source'], at='2026-11-04T15:00:00+01:00'))
P3.merge([vague, dated], wed)
at = lambda days: (datetime.datetime(2026, 11, 4, 16, 0) + datetime.timedelta(days=days)).astimezone()
ok(sorted(x['key'] for x in P3.suggestions(at(7))) == ['k10', 'k9'], 'a vague promise is on the list for the first two weeks')
ok([x['key'] for x in P3.suggestions(at(15))] == ['k10'], '… and gone after 14 days; one with a due date stays')
P3.merge([vague], at(16))
ok([x['key'] for x in P3.suggestions(at(16))] == ['k10'], '… and it does not come back on the next scan')

today = datetime.date(2026, 11, 9)                                   # a Monday
t = lambda who, world, days_ago, **kw: dict({'who': who, 'name': who, 'world': world, 'channel': 'mail', 'ever_out': True,
                                             'last_in': (datetime.datetime(2026, 11, 9, 9, 0) - datetime.timedelta(days=days_ago)).astimezone(), 'last_out': None}, **kw)
debt = C.reply_debt([t('lee@acme.example', 'work', 7), t('sam@acme.example', 'work', 2), t('kim@example.org', 'private', 6),
                     t('robin@example.org', 'private', 3), t('news@shop.example', 'private', 9, automated=True),
                     t('anna@example.org', 'private', 9, private=True), t('stranger@example.org', 'private', 9, ever_out=False),
                     t('jamie@example.org', 'private', 9, last_out=datetime.datetime(2026, 11, 8).astimezone()),
                     t('alex@example.org', 'private', 9)], {'alex@example.org'}, today)
ok([x['who'] for x in debt] == ['lee@acme.example', 'kim@example.org'],
   'reply debt: work after 3 working days, private after 5 days; never automated, private, strangers, answered or "never"')
# ---- fix round 7, P2-1: only real asks from real people, at most 21 days back
debt = C.reply_debt([t('lee@acme.example', 'work', 30),                                     # a month-old thread
                     t('post@kommune.example', 'private', 9), t('info@acme.example', 'work', 8),  # role mailboxes
                     t('sagsbehandler@example-kommune.dk', 'private', 9, institution=True),     # an authority
                     t('sam@rivera.example', 'work', 8, direct=False),                          # you were only on Cc
                     t('robin@example.org', 'private', 9, thanks=True),                         # "Tak!"
                     t('kim.example@example.org', 'private', 9, direct=True),                   # a direct question
                     t('jamie@example.org', 'private', 20)], set(), today)
ok([x['who'] for x in debt] == ['jamie@example.org', 'kim.example@example.org'],
   'reply debt: not over 21 days, not role or authority addresses, not Cc only, not "thanks" – a direct ask still counts')
ok(all('@' not in x['name'] for x in debt) and debt[1]['name'] == 'Kim Example', 'reply debt shows a name, never an address')
ok([x['who'] for x in C.reply_debt([t('lee@acme.example', 'work', 30)], set(), today, max_days=45)] == ['lee@acme.example'],
   'max_days is configurable')
ok(C.just_thanks('Tak!') and C.just_thanks('Hej Alex,\n\nMange tak for det!\n\nVenlig hilsen\nLee Chen') and C.just_thanks('Thanks Alex 👍'),
   '"Tak!" / "Mange tak for det" / "Thanks Alex" are just thanks')
ok(not C.just_thanks('Tak. Kan du sende tilbuddet i morgen?') and not C.just_thanks('Thanks for the call. Here are the notes and next steps.')
   and not C.just_thanks('Thanks!\nWhen can we meet?'), 'a thanks with a question or more to say still counts')
ok(C.role_address('post@kommune.example') and C.role_address('kontakt-dk@acme.example') and not C.role_address('lee.chen@acme.example'),
   'role addresses: post@, info@, kontakt@ … but not a person')
# marked done (nothing to answer): hidden until they write again
kim9 = t('kim@example.org', 'private', 9)
mark = {'kim@example.org': kim9['last_in'].isoformat(timespec='minutes')}
ok(C.reply_debt([kim9], set(), today, done=mark) == [], 'marked done: Kim is not owed a reply any more')
ok([x['who'] for x in C.reply_debt([t('kim@example.org', 'private', 6)], set(), today, done=mark)] == ['kim@example.org'],
   '… until Kim writes again')
P4 = C.Promises(tempfile.mkdtemp())
P4.set_done('Kim@Example.org', '2026-11-01T10:00+01:00')
ok(P4.done() == {'kim@example.org': '2026-11-01T10:00+01:00'}, 'done is kept on the Mac mini')
ok(P4.set_done('kim@example.org', '', on=False) == {}, 'and can be undone')
ok(C.working_days_between(datetime.date(2026, 11, 6), datetime.date(2026, 11, 9)) == 1, 'a weekend is not working days')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
