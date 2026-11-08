#!/usr/bin/env python3
"""Projects → Scan mail in the action service (axella-actions.py): the left-out rules on real candidate rows (world,
private contacts, protected workplaces, scam), a scan end to end, Add a mail by hand, Read with Claude getting only the
picked, added mails, and Add attachment to Documents. Mail, Contacts and Claude are stubbed; invented data only.
Run: python3 setup/tests/test_project_mail_actions.py"""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
import project_scan as PS  # noqa: E402
import projects as PJ  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


st = tempfile.mkdtemp()
A.PSCAN = PS.ProjectMail(st)
A.PROJ = PJ.Projects(st)
pid = A.PROJ.action('project_add', {'name': 'Acme festival', 'keywords': ['festival']})
A.PROJ.action('project_update', {'id': pid, 'ctx': 'private'})
A.profile.accounts = lambda *a: [{'id': 'iCloud', 'kind': 'private', 'workplace': None}, {'id': 'Work', 'kind': 'work', 'workplace': 'acme'}]
A.profile.workplaces = lambda *a: [{'id': 'acme', 'name': 'Acme', 'domains': ['acme.example'], 'protected': True}]
A.profile.is_protected = lambda account=None, address=None, cfg=None: account == 'Work' or str(address or '').endswith('@acme.example')
A.config = lambda: {'accounts': {'iCloud': {'kind': 'private'}, 'Work': {'kind': 'work'}}}
A.mail_privacy = lambda addrs: (any('anna@' in str(a) for a in addrs), None)
A._known_people = lambda: ([],)
A._safety.check_mail = lambda raw, *a: ('scam' in raw.decode(), None)
ADDR = {}
A.mailsearch.addresses_of = lambda path: ADDR[path]
A.mailsearch._raw = lambda path: (b'scam' if 'scam' in path else b'ok')
A.mail_accounts = lambda: {'1': 'iCloud', '2': 'Work'}
A.log_auto = lambda *a: None


def row(n, subj, addr, acc='iCloud', date='2026-12-10'):
    ADDR['p%d' % n] = [addr]
    return {'path': ('scam%d' if 'scam' in addr else 'p%d') % n, 'account': acc, 'message_id': 'm%d@x' % n, 'subject': subj,
            'from_address': addr, 'from_name': '', 'date': date + 'T10:00:00+01:00'}


ROWS = [row(1, 'Festival plan', 'lee@example.com'), row(2, 'Festival budget', 'kim@acme.example', 'Work'),
        row(3, 'Festival tickets', 'anna@example.com'), row(4, 'Festival prize!', 'scam@example.com'), row(5, 'Festival crew', 'sam@example.net')]
ADDR['scam4'] = ['scam@example.com']
keep = A._project_keep(A._project_of(pid))
ok([r['message_id'] for r in ROWS if keep(r)[0]] == ['m1@x', 'm5@x'], 'left out: the other world, a protected workplace, a private contact, a scam-flagged mail')
ok(keep(ROWS[1])[1] == 'other world' and keep(ROWS[2])[1] == 'private contact' and keep(ROWS[3])[1] == 'flagged', '… each for its reason')
A.mailsearch.booking_candidates = lambda names, match, days, limit: [r for r in ROWS if match(r['subject'], r['from_address'])]
import datetime
A.PSCAN.set_since(pid, (datetime.date.today() - datetime.timedelta(days=500)).isoformat())
A.project_mail_scan(pid)
v = A.project_mail_view(pid)
ok([c['message_id'] for c in v['candidates']] == ['m1@x', 'm5@x'] and v['status']['found'] == 2 and not v['status']['error'], 'a scan end to end: two to sort')

wp = A.PROJ.action('project_add', {'name': 'Acme', 'keywords': ['festival']})
ok(A._project_workplace(A._project_of(wp))['id'] == 'acme' and A._project_world(A._project_of(wp)) == 'work', 'a project named like the workplace belongs to it')
ok(A._project_keep(A._project_of(wp))(ROWS[1])[0], '… so that workplace\'s mail is a candidate there')

A.project_mail_action('project_mail_add', {'id': pid, 'message_id': 'm1@x'})
A.meeting_mail_addresses = lambda sender, mid, strict=False: ['anna@example.com'] if mid == 'm3@x' else ['lee@example.com']
try:
    A.project_mail_action('project_mail_add', {'id': pid, 'mail': {'account': 'iCloud', 'message_id': 'm3@x', 'subject': 'x'}})
    ok(False, 'Add a mail: a private contact\'s mail is refused')
except A.Bad:
    ok(True, 'Add a mail: a private contact\'s mail is refused')
A.project_mail_action('project_mail_add', {'id': pid, 'mail': {'account': 'iCloud', 'message_id': 'm9@x', 'subject': 'Festival map', 'from': 'Robin'}})
A.meeting_mail_addresses = lambda sender, mid, strict=False: ['kim@acme.example']
try:
    A.project_mail_action('project_mail_add', {'id': pid, 'mail': {'account': 'Work', 'message_id': 'm8@x', 'subject': 'Budget'}})
    ok(False, 'Add a mail: a protected workplace\'s mail is refused on another project')
except A.Bad:
    ok(True, 'Add a mail: a protected workplace\'s mail is refused on another project')
A.project_mail_action('project_mail_add', {'id': wp, 'mail': {'account': 'Work', 'message_id': 'm8@x', 'subject': 'Budget'}})
ok('m8@x' in A.PSCAN.entry(wp)['added'], '… and accepted on that workplace\'s own project')
A.meeting_mail_addresses = lambda sender, mid, strict=False: ['anna@example.com'] if mid == 'm3@x' else ['lee@example.com']
ok('m9@x' in A.PSCAN.entry(pid)['added'] and A.PSCAN.entry(pid)['added']['m9@x']['why'] == ['added by hand'], 'Add a mail by hand')

asked = []
A.RUNNER.project_read_busy = lambda: False
A.RUNNER.project_read_request = lambda p_, mails: (asked.extend(mails), 'pr1')[1]
A.mailsearch.sender_of = lambda path: ('lee@example.com', '2026-12-10')
A.mailsearch.path_for_mid = lambda mid: 'p1'
r = A.project_mail_action('project_read', {'id': pid, 'message_ids': ['m1@x', 'm5@x', 'zz@x']})
ok(r['mails'] == 1 and [m['message_id'] for m in asked] == ['m1@x'], 'Read with Claude: only the picked mails that are on the project')
ok(A.PSCAN.entry(pid)['reading'] == 'pr1', '… shown as reading')

up = []
A.PROJ.upload = lambda p_, name, ctype, data: (up.append((p_, name, ctype, data)), {'id': 'f1'})[1]
A.mailsearch.attachment = lambda tok, n: ('plan.pdf', 'application/pdf', b'%PDF-invented')
A.mailsearch._token = lambda d: 'tok'
A.project_mail_action('project_mail_attach', {'id': pid, 'message_id': 'm1@x', 'n': 1})
ok(up and up[0][:3] == (pid, 'plan.pdf', 'application/pdf'), 'Add attachment to Documents')
try:
    A.project_mail_action('project_mail_attach', {'id': pid, 'message_id': 'm5@x', 'n': 1})
    ok(False, 'only from a mail on the project')
except A.Bad:
    ok(True, 'only from a mail on the project')
up.clear()
A.meeting_mail_addresses = lambda sender, mid, strict=False: ['lee@example.com']
A.project_mail_action('project_doc_from_mail', {'id': pid, 'n': 2, 'mail': {'account': 'iCloud', 'message_id': 'm11@x', 'subject': 'Contract', 'from': 'Lee'}})
ok('m11@x' in A.PSCAN.entry(pid)['added'] and up and up[0][:2] == (pid, 'plan.pdf'),
   'Save attachment to project: the mail joins the Mails card, its attachment goes to Documents')
A.meeting_mail_addresses = lambda sender, mid, strict=False: ['anna@example.com']
try:
    A.project_mail_action('project_doc_from_mail', {'id': pid, 'n': 1, 'mail': {'account': 'iCloud', 'message_id': 'm12@x', 'subject': 'x'}})
    ok(False, '… never a mail with a private contact')
except A.Bad:
    ok(True, '… never a mail with a private contact')
ok('project_doc_from_mail' in A.OWNER_ONLY, '… owner only')
seen = {}
_srch = A.mailsearch.search
A.mailsearch.search = lambda q, names, own, limit=40, classify=None, before=None: (seen.update(before=before), [])[1]
A.mail_search('contract', 40, '2024-03-01T10:00:00Z')
T10 = datetime.datetime(2024, 3, 1, 10, tzinfo=datetime.timezone.utc).timestamp()
ok(abs(seen['before'] - T10) < 1, 'search "Show older": before an ISO time (Z works)')
A.mail_search('contract', 40, '2024-03-01')
ok(seen['before'] and seen['before'] < T10, '… or before a date')
ok(A.mail_search('contract', 40, 'soon')['error'] == 'give the date as YYYY-MM-DD', '… a bad date is refused')
A.mailsearch.search = _srch
A.meeting_mail_addresses = lambda sender, mid, strict=False: ['lee@example.com']
A.project_mail_action('project_match_add', {'id': pid, 'match': 'robin@robin-events.example'})
ok('robin@robin-events.example' in A._project_of(pid)['senders'], '"Add to this project\'s matches": the sender is in Matches')
# ---- a protected workplace's mail and Claude: only on its own project, and only with its AI setting "all"
A.profile.workplaces = lambda *a: [{'id': 'acme', 'name': 'Acme', 'domains': ['acme.example'], 'protected': True},
                                   {'id': 'robin', 'name': 'Robin', 'domains': ['robin.example'], 'protected': True}]
A.meeting_mail_addresses = lambda sender, mid, strict=False: ['kim@acme.example'] if mid == 'm8@x' else ['lee@example.com']
asked.clear()
A.MEET.ai_defaults = lambda: {}
try:
    A.project_mail_action('project_read', {'id': wp, 'message_ids': ['m8@x']})
    ok(False, 'its own project, default AI setting: the mail is not read')
except A.Bad as e:
    ok(not asked and '1 mail from Acme stays on the Mac mini (its AI setting)' == str(e), 'its own project, default AI setting: the mail is not read (%s)' % e)
A.MEET.ai_defaults = lambda: {'acme': 'own'}
try:
    A.project_mail_action('project_read', {'id': wp, 'message_ids': ['m8@x']})
    ok(False, '… nor with "own"')
except A.Bad:
    ok(not asked, '… nor with "own"')
A.MEET.ai_defaults = lambda: {'acme': 'all'}
r = A.project_mail_action('project_read', {'id': wp, 'message_ids': ['m8@x']})
ok(r['mails'] == 1 and [m['message_id'] for m in asked] == ['m8@x'] and not r['kept'], 'its own project with "all": it is read')
A.PSCAN.entry(pid)['added']  # the private project
A.PSCAN.merge(pid, [{'account': 'Work', 'message_id': 'm7@x', 'subject': 'Budget', 'address': 'kim@acme.example', 'date': '2026-12-01'}])
asked.clear()
A.meeting_mail_addresses = lambda sender, mid, strict=False: ['kim@acme.example'] if mid in ('m7@x', 'm8@x') else ['lee@example.com']
A.PSCAN.action('project_mail_add', pid, {'message_id': 'm7@x'})
r = A.project_mail_action('project_read', {'id': pid, 'message_ids': ['m1@x', 'm7@x']})
ok([m['message_id'] for m in asked] == ['m1@x'] and r['kept'] == 1 and 'stays on the Mac mini' in r['note'], 'another project: the workplace mail is skipped, with the note')

rb = A.PROJ.action('project_add', {'name': 'Robin', 'keywords': ['robin']})
for to, label in ((pid, 'a private project'), (rb, 'another workplace\'s project')):
    try:
        A.project_mail_action('project_mail_move', {'id': wp, 'message_id': 'm8@x', 'to': to})
        ok(False, 'moving Acme\'s mail to %s: refused' % label)
    except A.Bad:
        ok('m8@x' in A.PSCAN.entry(wp)['added'], 'moving Acme\'s mail to %s: refused' % label)
A.project_mail_action('project_mail_move', {'id': pid, 'message_id': 'm1@x', 'to': rb})
ok('m1@x' in A.PSCAN.entry(rb)['added'], 'an ordinary mail moves freely')

# ---- housekeeping: old readings go after 30 days
import housekeeping as HK
import time as _t
hk = tempfile.mkdtemp()
for sub in ('trips-read', 'project-read'):
    os.makedirs(os.path.join(hk, sub, 'done'))
    for n, age in (('old.json', 31), ('new.json', 2)):
        f = os.path.join(hk, sub, 'done', n)
        open(f, 'w').write('{}')
        os.utime(f, (_t.time() - age * 86400,) * 2)
gone = HK.prune_read_done(hk)
ok(len(gone) == 2 and all(x.endswith('old.json') for x in gone) and os.path.exists(os.path.join(hk, 'project-read', 'done', 'new.json')),
   'housekeeping: finished readings older than 30 days are deleted (Trips and Projects), newer ones kept')

print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
