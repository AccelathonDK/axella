#!/usr/bin/env python3
"""Projects → Scan mail (setup/project_scan.py): matching by the project's Matches, the left-out rules, offered once,
Not this project, the nightly re-scan, the sender suggestion and the trip link. Invented projects, people and mails only.
Run: python3 setup/tests/test_project_scan.py"""
import datetime
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import project_scan as PS  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


TODAY = datetime.date(2027, 3, 20)
PROJ = {'id': 'p-acmefest', 'name': 'Acme festival', 'tag': 'acmefest', 'status': 'active', 'keywords': ['festival', 'stage plan'],
        'senders': ['robin@robin-events.example', 'kim-venues.example']}


def mail(n, subject, addr, date, name=''):
    return {'account': 'iCloud', 'message_id': 'm%d@x' % n, 'subject': subject, 'from_address': addr, 'from_name': name, 'date': date + 'T10:00:00+01:00'}


MAILS = [mail(1, 'Festival line-up draft', 'lee@example.com', '2027-03-10'),
         mail(2, 'Re: Stage plan v2', 'sam@example.net', '2027-03-01'),
         mail(3, 'Invoice 12', 'robin@robin-events.example', '2027-02-11'),
         mail(4, 'Hall booking', 'booking@kim-venues.example', '2027-01-15'),
         mail(5, '[acmefest] crew list', 'jamie@example.org', '2026-12-20'),
         mail(6, 'Your weekly newsletter', 'news@example.com', '2027-03-12'),
         mail(7, 'Festivalplan', 'x@example.com', '2027-03-12'),           # a word inside another word doesn't count
         mail(8, 'Festival sale!', 'scam@example.com', '2027-03-11'),
         mail(9, 'Festival old', 'lee@example.com', '2026-05-01'),         # before Scan since
         mail(10, 'Private: festival tickets', 'anna@example.com', '2027-03-05')]

m = PS.Matcher(PROJ)
ok(m('Festival line-up', 'lee@example.com') == ['keyword: festival'], 'a keyword in the subject (whole word)')
ok(m('x', 'robin@robin-events.example') == ['sender: robin@robin-events.example'], 'a sender address')
ok(m('x', 'booking@kim-venues.example') == ['domain: kim-venues.example'], 'a sender domain')
ok(m('[acmefest] crew', 'a@example.org') == ['tag: acmefest'], 'the tag')
ok(m('Festivalplan', 'a@example.org') == [] and m('Newsletter', 'news@example.com') == [], 'not part of another word, not unrelated mail')
ok(m('x', 'a@b.example', mid='m99@x') == [] and PS.Matcher(PROJ, ['m99@x'])('x', 'a@b.example', 'm99@x') == ['shown in a digest'],
   'a mail shown in the project from a digest')
ok(PS._thread('Re: SV: [Acme] Stage plan  v2') == 'stage plan v2' and PS._thread('Fwd: Hall booking') == 'hall booking', 'the thread key')


def keep(c):
    if c['from_address'] == 'anna@example.com':
        return False, 'private contact'
    if c['from_address'] == 'scam@example.com':
        return False, 'scam'
    return True, None


since = PS.since_of({}, TODAY)
ok(since == TODAY - datetime.timedelta(days=183), 'Scan since: 6 months back by default')
found = PS.scan(PROJ, MAILS, m, keep, TODAY, since)
ok([c['message_id'] for c in found] == ['m1@x', 'm2@x', 'm3@x', 'm4@x', 'm5@x'],
   'tag, keywords, sender and domain since the date – and only those (%s)' % [c['message_id'] for c in found])
ok(found[1]['why'] == ['keyword: stage plan'] and found[1]['thread'] == 'stage plan v2', 'why each one matched')
ok(not any(c['message_id'] in ('m8@x', 'm10@x') for c in found), 'a private contact and a scam-flagged mail are never candidates')
ok(set(found[0]) == {'account', 'message_id', 'subject', 'from', 'address', 'date', 'why', 'thread'}, 'only what the row shows is kept')

st = tempfile.mkdtemp()
S = PS.ProjectMail(st)
ok(S.merge(PROJ['id'], found) == 5 and S.merge(PROJ['id'], found) == 0, 'a mail is offered once')
S.action('project_mail_add', PROJ['id'], {'message_id': 'm1@x'})
S.action('project_mail_not', PROJ['id'], {'message_id': 'm2@x'})
ok(S.merge(PROJ['id'], found) == 0 and 'm2@x' not in S.entry(PROJ['id'])['candidates'], 'Not this project: never offered again')
S.action('project_mail_undo_not', PROJ['id'], {'message_id': 'm2@x'})
ok('m2@x' in S.entry(PROJ['id'])['candidates'], '… with Undo')
S.action('project_mail_add', PROJ['id'], {'message_id': 'm2@x'})
v = S.view(PROJ)
ok(v['added'] == 2 and [t['thread'] for t in v['threads']] == ['festival line-up draft', 'stage plan v2'], 'the Mails card: newest first, by thread')
S.action('project_mail_remove', PROJ['id'], {'message_id': 'm1@x'})
ok(S.view(PROJ)['added'] == 1, 'Remove from project')
S.action('project_mail_undo_remove', PROJ['id'], {'message_id': 'm1@x'})
ok(S.view(PROJ)['added'] == 2, '… with Undo')
S.action('project_mail_move', PROJ['id'], {'message_id': 'm5@x'}, other_pid='p-other')
ok('m5@x' in S.entry('p-other')['added'] and 'm5@x' in S.entry(PROJ['id'])['not'], 'Add to another project…: there, and not offered here again')
th = PS.ProjectMail(st).matcher(PROJ)
ok(th('Re: Festival line-up draft', 'z@example.com') == ['keyword: festival'] and th('RE: stage plan v2', 'z@example.com'),
   'later mails in an added thread match')
ok(PS.Matcher({'id': 'x', 'tag': 'zz'}, threads={'quarterly review'})('Re: Quarterly review', 'q@example.com') == ['same thread as an added mail'],
   '… even without a keyword')
ok(oct(os.stat(S.file).st_mode & 0o777) == '0o600', 'project-mail.json is private (600)')
ok(PS.ProjectMail(st).view(PROJ)['added'] == 2, 'added mails stay across restarts')

# ---- learn from what you add
for n, a in ((20, 'alex.k@lodge-example.example'), (21, 'alex.k@lodge-example.example'), (22, 'desk@lodge-example.example')):
    S.merge(PROJ['id'], [{'message_id': 'm%d@x' % n, 'subject': 'Rooms', 'address': a, 'date': '2027-03-0%d' % (n - 19)}])
    S.action('project_mail_add', PROJ['id'], {'message_id': 'm%d@x' % n})
sg = S.suggest_matches(PROJ)
ok(sg and sg[0] == {'match': 'alex.k@lodge-example.example', 'mails': 2} and {'match': 'lodge-example.example', 'mails': 3} in sg,
   'a sender (and domain) several added mails share is offered as a match')
ok(not any(s['match'] == 'robin@robin-events.example' for s in sg), 'not one already in Matches')
S.action('project_match_dismiss', PROJ['id'], {'match': 'alex.k@lodge-example.example'})
ok(not any(s['match'] == 'alex.k@lodge-example.example' for s in S.suggest_matches(PROJ)), 'dismissed: not offered again')

# ---- the nightly re-scan
calls = []


def run_scan(p, since_):
    calls.append((p['id'], since_))
    return [{'message_id': 'm30@x', 'subject': 'Festival update', 'address': 'lee@example.com', 'date': '2027-03-19'}]


archived = dict(PROJ, id='p-old', status='archived')
never = dict(PROJ, id='p-new')
r = PS.nightly([PROJ, archived, never], S, run_scan, TODAY)
ok(r == {PROJ['id']: 1} and calls[0][0] == PROJ['id'], 'nightly: active, already scanned projects only – archived skipped')
ok(calls[0][1] <= datetime.date.fromisoformat(S.entry(PROJ['id'])['last_scan'][:10]), '… from the last scan on')
ok(PS.nightly([PROJ], S, run_scan, TODAY) == {PROJ['id']: 0}, '… and new mails only')

# ---- Scan since
try:
    S.set_since(PROJ['id'], '2025-01-01', TODAY)
    ok(False, 'more than 18 months back is refused')
except PS.Bad:
    ok(True, 'more than 18 months back is refused')
ok(S.set_since(PROJ['id'], '2026-12-01', TODAY) == datetime.date(2026, 12, 1) and PS.since_of(S.entry(PROJ['id']), TODAY) == datetime.date(2026, 12, 1),
   'a date you pick')

# ---- link to a trip
trips = [{'id': 't-1', 'title': 'Robin trip', 'status': 'confirmed', 'bookings': [{'source': {'message_id': 'm2@x'}}]},
         {'id': 't-2', 'title': 'Other', 'status': 'confirmed', 'bookings': [{'source': {'message_id': 'zz@x'}}]},
         {'id': 't-3', 'title': 'Maybe', 'status': 'suggested', 'bookings': [{'source': {'message_id': 'm1@x'}}]}]
ok(S.trip_suggestions(PROJ, trips) == [{'id': 't-1', 'title': 'Robin trip'}], 'Link to trip: a confirmed trip whose booking mail is on the project')
S.action('project_trip_link', PROJ['id'], {'trip': 't-1'})
ok(S.view(PROJ)['trips'] == ['t-1'] and S.trip_suggestions(PROJ, trips) == [], 'linked (and not offered again)')
S.action('project_trip_unlink', PROJ['id'], {'trip': 't-1'})
ok(S.view(PROJ)['trips'] == [], 'unlinked')

# ---- Read with Claude: only cards for the picked mails
asked = [{'message_id': 'm1@x'}, {'message_id': 'm2@x'}]
res = {'tasks': [{'message_id': 'm1@x', 'text': 'Send the stage plan', 'due': '2027-03-25'}, {'message_id': 'zz@x', 'text': 'not picked'}],
       'notes': [{'message_id': 'm2@x', 'text': 'Load-in from 08:00'}],
       'dates': [{'message_id': 'm2@x', 'title': 'Sound check', 'date': '2027-04-02', 'time': '15:00'}, {'message_id': 'm1@x', 'title': 'x', 'date': 'soon'}]}
cards = PS.clean_read(res, asked)
ok([c['kind'] for c in cards] == ['task', 'note', 'date'] and cards[0]['due'] == '2027-03-25' and cards[2]['time'] == '15:00',
   'task, note and date cards – only from the picked mails, valid dates only')
S.set_suggestions(PROJ['id'], cards, 'pr2027abc')
v = S.view(PROJ)
ok(len(v['suggestions']) == 3 and all(c.get('id') for c in v['suggestions']), 'the cards wait on the project (nothing added by itself)')
S.suggestion_done(PROJ['id'], v['suggestions'][0]['id'])
ok(len(S.view(PROJ)['suggestions']) == 2, 'a card goes once it is added or dismissed')

print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
