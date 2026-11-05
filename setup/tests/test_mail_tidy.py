#!/usr/bin/env python3
"""Keep Mail tidy (setup/mail_tidy.py, axella-actions.py): what you handle in Axella is read in Mail.
Opening, filing, Done, Delete and a reply mark the mail read; Undo marks it unread again; only Mail and only the owner's
own taps; a private contact's mail is never touched; marks are batched in the job queue; a mail Mail can't find is
skipped quietly. Mail (AppleScript) is stubbed. Fictional cast. Run: python3 setup/tests/test_mail_tidy.py"""
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
import mail_tidy  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


class Log:
    def __init__(self):
        self.lines = []

    def write(self, s):
        self.lines.append(s)


# ---------- 1. the batcher on its own ----------
calls, queued = [], []


def osa(script, *args, timeout=60, tries=1):
    calls.append(args)
    return '\n'.join('missing' if 'gone' in args[i + 2] else 'ok' for i in range(0, len(args), 3))


log = Log()
private = {'<p1@example.com>'}
t = mail_tidy.Tidy(osa, 'on findMessage(a, m)\nend findMessage\n', lambda acc, mid: mid not in private, lambda: queued.append(1), log)
ok(t.mark('Acme', '<m1@example.com>') and t.mark('Acme', '<m2@example.com>') and t.mark('Acme', '<m1@example.com>', False),
   'marks are accepted')
ok(len(queued) == 1, 'three marks, one job in the queue (batched)')
ok(not t.mark('', '<m3@example.com>') and not t.mark('Acme', 'bad id with spaces'), 'no account or a bad Message-ID: not queued')
r = t.run()
ok(len(calls) == 1 and calls[0] == ('read', 'Acme', '<m2@example.com>', 'unread', 'Acme', '<m1@example.com>'),
   'one AppleScript call for the batch; the last tap on a mail wins (m1: unread)')
ok(r == {'marked': 2, 'missing': 0, 'skipped': 0, 'failed': 0}, 'counts only: 2 marked')
ok('findMessage' in t.script and 'set read status of m to (st is "read")' in t.script and 'argv' in t.script,
   'the script finds the mail by Message-ID and sets read status – user data only as argv')
calls.clear(); queued.clear()
for i in range(25):
    t.mark('Acme', '<b%d@example.com>' % i)
t.run()
ok(len(calls[0]) == 3 * mail_tidy.BATCH and len(queued) == 2, '25 marks: 20 in the first batch, the rest queued again')
t.run()
ok(len(calls) == 2 and len(calls[1]) == 15, '… and the last 5 in the next')
calls.clear()
t.mark('Acme', '<p1@example.com>')
r = t.run()
ok(not calls and r['skipped'] == 1, "a private contact's mail is never touched (checked when the batch runs)")
t.mark('Acme', '<gone@example.com>')
r = t.run()
ok(r['missing'] == 1 and any('not found' in x for x in log.lines) and not any('gone@' in x for x in log.lines),
   'a mail Mail can\'t find: skipped quietly, a count in the log (no address)')
t2 = mail_tidy.Tidy(lambda *a, **k: (_ for _ in ()).throw(RuntimeError('Mail did not answer')), '', lambda a, m: True, lambda: None, log)
t2.mark('Acme', '<m9@example.com>')
ok(t2.run()['failed'] == 1, 'Mail not answering: nothing raised, counted as not marked')

# ---------- 2. the actions ----------
d = tempfile.mkdtemp()
A.LOG_FILE = os.path.join(d, 'actions.log')
A.STATE_FILE = os.path.join(d, 'state.json')
A.SENT_FILE = os.path.join(d, 'sent.json')
A.DRAFTS_FILE = os.path.join(d, 'drafts.json')
A.FILING_FILE = os.path.join(d, 'filing.json')
A.LEARN = A._learned.Learned(d)
A.config = lambda: {'accounts': {'Acme': {'kind': 'work', 'address': 'alex@acme.example', 'folders': ['Clients/Acme']}}}
A.owner_logins = lambda: {'alex@example.com'}
OWN = 'alex@example.com'
marks, jobs = [], []


def a_osa(script, *args, timeout=60, tries=1):
    if 'set read status' in script:
        marks.append(args)
        return 'ok\n' * (len(args) // 3)
    if 'reply m with opening window' in script:
        return 'sent\x1flee@example.com'
    if 'set bodyTxt to content of m' in script:
        raise RuntimeError('no preview in the test')
    return 'moved'


A.osa = a_osa
A.TIDY = mail_tidy.Tidy(a_osa, A.FIND_MESSAGE, A._tidy_allowed, lambda: jobs.append('mail_mark'))
files = {'<m1@acme.example>': '/x/m1.emlx', '<m2@acme.example>': '/x/m2.emlx', '<m3@acme.example>': '/x/m3.emlx',
         '<p@acme.example>': '/x/p.emlx'}
A.mailsearch.path_for_mid = lambda mid: files.get(mid)
A.mailsearch.addresses_of = lambda path: ['robin.private@example.org'] if path == '/x/p.emlx' else ['lee@example.com']
A.mail_privacy = lambda addrs: (any('private' in a for a in addrs), None)
A.live_folders = lambda acc, fresh=False: []


def run(action, **p):
    p.setdefault('_login', OWN)
    return A.do_action(action, p)


def drain():
    marks.clear()
    while jobs:
        jobs.pop()
        A.TIDY.run()
    return list(marks)


run('done', item_id='i1', account='Acme', message_id='<m1@acme.example>', channel='mail', title='x')
ok(drain() == [('read', 'Acme', '<m1@acme.example>')], 'Done: the mail is marked read in Mail')
ok(json.load(open(A.STATE_FILE))['i1']['status'] == 'done', '… and Done is recorded as before (not moved, not archived)')
run('undo', item_id='i1', account='Acme', message_id='<m1@acme.example>', channel='mail')
ok(drain() == [('unread', 'Acme', '<m1@acme.example>')], 'Undo: unread again')
run('snooze', item_id='i2', until='2030-01-01T06:00:00', title='x')
run('undo', item_id='i2', account='Acme', message_id='<m2@acme.example>', channel='mail')
ok(drain() == [], 'Undo of a Later (never marked read): read state left alone')
run('file', item_id='i3', account='Acme', message_id='<m2@acme.example>', folder='Clients/Acme', channel='mail')
ok(drain() == [('read', 'Acme', '<m2@acme.example>')], 'Filed: moved, and read')
run('trash', item_id='i4', account='Acme', message_id='<m3@acme.example>', channel='mail')
ok(drain() == [('read', 'Acme', '<m3@acme.example>')], 'Delete (to Trash): read as well')
run('trash_batch', items=[{'item_id': 'b1', 'account': 'Acme', 'message_id': '<m1@acme.example>'},
                          {'item_id': 'b2', 'account': 'Acme', 'message_id': '<m2@acme.example>'}])
ok(drain() == [('read', 'Acme', '<m1@acme.example>', 'read', 'Acme', '<m2@acme.example>')], 'Filing suggestions → Delete: each mail read, in one batch (one AppleScript call)')
run('reply_send', confirm='send', account='Acme', text='Thanks, Lee', message_id='<m1@acme.example>', expect_to='lee@example.com',
    item_id='i5', title='Re: plan', sender='lee@example.com', channel='mail')
ok(drain() == [('read', 'Acme', '<m1@acme.example>')], 'A reply sent from Axella: the mail answered is read')
run('reply_send', confirm='send', account='Acme', text='Later reply', message_id='<m2@acme.example>', expect_to='lee@example.com',
    item_id='i6', title='Re: later', _login='scheduled', channel='mail')
ok(drain() == [('read', 'Acme', '<m2@acme.example>')], 'Send later, when it goes: the mail answered is read')
run('mail_seen', account='Acme', message_id='<m3@acme.example>')
ok(drain() == [('read', 'Acme', '<m3@acme.example>')], "Opened in Axella's reader: read")
tok = A.mailsearch._token({'path': '/x/m2.emlx', 'account': 'Acme', 'mid': '<m2@acme.example>'})
run('mail_seen', file=tok)
ok(drain() == [('read', 'Acme', '<m2@acme.example>')], "a mail found by Search, opened in the reader: read")
ok('mail_seen' in A.QUIET, 'opening a mail adds no line to the activity log')
run('mail_seen', account='Acme', message_id='<p@acme.example>')
ok(drain() == [], "a private contact's mail stays as it was")
run('mail_seen', account='Acme', message_id='<notondisk@acme.example>')
ok(drain() == [], "a mail whose file can't be found is not touched (fails closed)")
run('done', item_id='w1', account='Acme', message_id='<m1@acme.example>', channel='whatsapp', title='chat')
run('done', item_id='w2', account='Acme', message_id='<m1@acme.example>', channel='imessage', title='chat')
ok(drain() == [], 'iMessage, WhatsApp and Signal are never marked read (no read receipt)')
run('done', item_id='s1', account='Acme', message_id='<m1@acme.example>', channel='mail', title='x', _login='sam@example.com')
ok(drain() == [], "someone else on the access list: Mail's read state is left alone")
run('file', item_id='a1', account='Acme', message_id='<m1@acme.example>', folder='Clients/Acme', _login='axella')
ok(drain() == [], 'Axella filing by itself (a learned rule) is not your tap: read state left alone')
run('mail_seen', account='Private', message_id='<m1@acme.example>')
ok(drain() == [], 'an account that is not configured: nothing')
log_lines = open(A.LOG_FILE).read().count('"mail_mark"') if os.path.exists(A.LOG_FILE) else 0
ok(log_lines == 0, 'the marks add no activity-log lines of their own')
src = open(os.path.join(HERE, 'scheduler.py'), encoding='utf-8').read()
ok("'mail_update_read_state'" in src, "the Claude runs still can't change read state (never list)")
src = open(os.path.join(HERE, 'axella-actions.py'), encoding='utf-8').read()
ok("if action == 'mail_mark':" in src and "TIDY.run()" in src and "do_action('mail_mark'" not in src,
   'mail_mark is an internal job only – not an action a POST can call')
try:
    A.do_action('mail_mark', {'_login': OWN})
    ok(False, 'POST mail_mark is refused')
except A.Bad:
    ok(True, 'POST mail_mark is refused (unknown action)')

print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
