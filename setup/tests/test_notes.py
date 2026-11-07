#!/usr/bin/env python3
"""Notes (setup/notes.py, axella-actions.py, scheduler.py): storage and the index, links, the "Remind me when they
write" chips (person identities, thread, meeting day, trip start; one chip per item), the deny list for runs, the Ask
rules (private contact, protected workplace), owner only, Make a To do, delete and restore, backup. Invented data.
Run: python3 setup/tests/test_notes.py"""
import datetime
import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
import notes as N  # noqa: E402
import scheduler  # noqa: E402
import backup  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def bad(fn, label):
    try:
        fn()
        ok(False, label)
    except (N.Bad, A.Bad):
        ok(True, label)


d = tempfile.mkdtemp()
st = N.Notes(d, os.path.join(d, 'state', 'deleted', 'notes'))

# ---------- 1. storage and the index ----------
lee = {'kind': 'person', 'ref': 'c-lee', 'label': 'Lee Chen', 'keys': ['Lee@Acme.example', '+45 00 00 00 01']}
n1 = st.save({'text': 'Ask Lee about the delivery date\nand the price for 200 units', 'links': [lee]})
ok(n1['id'].startswith('n') and n1['title'] == 'Ask Lee about the delivery date', 'a new note: the first line is its title')
ok(open(os.path.join(d, 'notes', n1['id'] + '.txt')).read().startswith('Ask Lee'), 'plain text, one file per note')
idx = json.load(open(os.path.join(d, 'notes', 'index.json')))
ok(n1['id'] in idx['notes'] and 'text' not in idx['notes'][n1['id']], 'the index holds the rest, never the text')
ok(oct(os.stat(os.path.join(d, 'notes', n1['id'] + '.txt')).st_mode)[-3:] == '600', 'files are readable by the owner only (600)')
ok(n1['links'][0]['keys'] == ['+4500000001', 'lee@acme.example'], 'a person link keeps every identity (address, number)')
bad(lambda: st.save({'text': '   '}), 'an empty new note is refused')
bad(lambda: st.save({'text': 'x', 'links': [{'kind': 'shoe', 'ref': '1'}]}), 'an unknown kind of link is refused')
bad(lambda: st.save({'id': '../../x', 'text': 'x'}), 'a bad id is refused')
n2 = st.save({'text': 'Packing list\nSunscreen', 'links': [{'kind': 'trip', 'ref': 't1', 'label': 'Lisbon'}]})
n3 = st.save({'text': 'Pinned thought'})
st.save({'id': n3['id'], 'pinned': True})
ls = st.list()
ok(ls[0]['id'] == n3['id'] and {x['id'] for x in ls} == {n1['id'], n2['id'], n3['id']}, 'the list: pinned first, then the newest')
ok([x['id'] for x in st.list('sunscreen')] == [n2['id']], 'search finds a word in the text')
ok([x['id'] for x in st.list(kind='person', ref='c-lee')] == [n1['id']], 'a page lists the notes linked to it')
st.save({'id': n2['id'], 'ctx': 'private'})
ok(st.view(n2['id'])['ctx'] == 'private', 'Work / Private set by hand')

# ---------- 2. the chips ----------
T = datetime.date(2030, 3, 14)
st.save({'id': n1['id'], 'remind': True})
start = st.view(n1['id'])['remind_from']
later = (datetime.datetime.fromisoformat(start) + datetime.timedelta(minutes=5)).isoformat()
before = (datetime.datetime.fromisoformat(start) - datetime.timedelta(days=1)).isoformat()
items = [{'id': 'i1', 'section': 'p1', 'first_seen': later, 'from': {'address': 'lee@acme.example'}, 'subject': 'Re: Quote v2'},
         {'id': 'i2', 'section': 'p1', 'first_seen': before, 'from': {'address': 'lee@acme.example'}},
         {'id': 'i3', 'section': 'p2', 'first_seen': later, 'channel': 'whatsapp', 'from': {'address': '+45 00 00 00 01'}},
         {'id': 'i4', 'section': 'p2', 'first_seen': later, 'from': {'address': 'kim@example.net'}, 'subject': 'Lunch'}]
c = st.chips(items, T)
ok(set(c['items']) == {'i1', 'i3'}, 'the linked person writes (mail or WhatsApp, any identity) → a chip; older mail and others → none')
ok(c['items']['i1']['title'] == 'Ask Lee about the delivery date' and c['items']['i1']['more'] == 0, 'the chip shows the note\'s title')
n4 = st.save({'text': 'Second note about Lee', 'links': [lee], 'remind': True})
c = st.chips(items, T)
ok(c['items']['i1']['id'] == n4['id'] and c['items']['i1']['more'] == 1, 'at most one chip per item: the newest note, and "1 more"')
st.keep(n4['id'], 'i1')
ok(st.chips(items, T)['items']['i1']['id'] == n1['id'], 'Keep: that note not again on this item; the reminder stays')
st.save({'id': n4['id'], 'remind': False})
st.save({'id': n1['id'], 'remind': False})
ok(not st.chips(items, T)['items'], 'Done (remind off): no chips')
thread = {'kind': 'mail', 'ref': '<q1@acme.example>', 'label': 'Quote v2', 'account': 'Acme', 'thread': 'Quote v2'}
n5 = st.save({'text': 'Check the VAT line', 'links': [thread], 'remind': True})
t_items = [{'id': 't1', 'section': 'p1', 'first_seen': later, 'account': 'Acme', 'subject': 'RE: Quote v2', 'message_id': '<q2@acme.example>',
            'from': {'address': 'sam@example.org'}},
           {'id': 't0', 'section': 'p1', 'first_seen': later, 'account': 'Acme', 'subject': 'Quote v2', 'message_id': '<q1@acme.example>'},
           {'id': 't2', 'section': 'p1', 'first_seen': later, 'account': 'Other', 'subject': 'Quote v2', 'message_id': '<x@y>'}]
ok(set(st.chips(t_items, T)['items']) == {'t1'}, 'the linked thread gets a new message → a chip (not the linked mail itself, not another account)')
st.save({'id': n5['id'], 'remind': False})
n6 = st.save({'text': 'Bring the slides', 'links': [{'kind': 'meeting', 'ref': 'm1', 'label': 'Review'}], 'remind': True})
n7 = st.save({'text': 'Passport!', 'links': [{'kind': 'trip', 'ref': 'tr1', 'label': 'Lisbon'}], 'remind': True})
c = st.chips([], T, meetings=[('m1', '2030-03-14'), ('m2', '2030-03-14')], trips=[('tr1', '2030-03-14'), ('tr2', '2030-03-15')])
ok(set(c['meetings']) == {'m1'} and c['meetings']['m1']['id'] == n6['id'], 'a linked meeting today → a chip on the meeting')
ok(set(c['trips']) == {'tr1'}, 'a linked trip starting today → a chip on the trip')
ok(not st.chips([], T, meetings=[('m1', '2030-03-15')])['meetings'], 'not on another day')

# ---------- 3. delete and restore ----------
r = st.delete(n3['id'])
ok(n3['id'] not in st.load()['notes'] and not os.path.exists(os.path.join(d, 'notes', n3['id'] + '.txt')), 'Delete: gone')
ok(os.path.exists(os.path.join(d, 'state', 'deleted', 'notes', r['backup'] + '.json')), '… a copy kept for 90 days')
back = st.restore(r['backup'])
ok(back['id'] == n3['id'] and back['text'] == 'Pinned thought' and back['pinned'], 'Restore brings the note back as it was')
bad(lambda: st.restore(r['backup']), 'a copy restores once')
bad(lambda: st.restore('../x'), 'a bad copy id is refused')

# ---------- 4. through the action service ----------
A.NOTES = N.Notes(d, os.path.join(d, 'state', 'deleted', 'notes'))
A.TASKS_FILE = os.path.join(d, 'tasks.json')
A.LOG_FILE = os.path.join(d, 'actions.log')
A.owner_logins = lambda: {'alex@example.com'}
r = A.do_action('note_save', {'_login': 'alex@example.com', 'text': 'Call the bank\nabout the card', 'links': [lee]})
ok(r['title'] == 'Call the bank', 'note_save makes the note')
t = A.do_action('note_todo', {'_login': 'alex@example.com', 'id': r['id'], 'text': 'about the card'})
task = next(x for x in json.load(open(A.TASKS_FILE)) if x['id'] == t['task'])
ok(task['text'] == 'about the card' and task['ref'] == {'note': r['id'], 'title': 'Call the bank'}, 'Make a To do from a line: a task linked back to the note')
p = {'_login': 'alex@example.com', 'id': r['id']}
A.do_action('note_delete', p)
ok(p.get('_backup') and p['title'] == 'Call the bank', 'note_delete leaves a Restore for the activity log, titled by the note')
A.do_action('note_restore', {'_login': 'alex@example.com', 'backup': p['_backup']})
ok(r['id'] in A.NOTES.load()['notes'], 'note_restore from the activity log')
ok({'note_save', 'note_keep', 'note_delete', 'note_restore', 'note_todo'} <= A.OWNER_ONLY, 'every note action is owner only')
ok('note_save' in A.SENDS and 'note_todo' in A.SENDS, "a note's text never goes into the activity log (only its title)")
src = open(os.path.join(HERE, 'axella-actions.py'), encoding='utf-8').read()
ok("if a in ('notes', 'note', 'note_chips'):" in src and "Only the owner can see notes" in src, 'GET notes / note / note_chips: owner only')

# ---------- 5. Ask: what it may read ----------
A.mail_privacy = lambda addrs: (any('robin.private' in a for a in addrs), None)
A.profile.workplaces = lambda cfg=None: [{'id': 'acme', 'name': 'Acme', 'domains': ['acme.example'], 'calendar': None, 'protected': True}]
A.profile.accounts = lambda cfg=None: [{'id': 'Acme', 'label': 'Acme', 'kind': 'work', 'workplace': 'acme', 'address': 'alex@acme.example'}]
modes = {}
A.MEET.ai_defaults = lambda: dict(modes)
plain = {'links': [{'kind': 'person', 'ref': 'k', 'keys': ['kim@example.net']}]}
priv = {'links': [{'kind': 'person', 'ref': 'r', 'keys': ['robin.private@example.org']}]}
prot = {'links': [{'kind': 'person', 'ref': 'l', 'keys': ['lee@acme.example']}]}
prot_mail = {'links': [{'kind': 'mail', 'ref': '<x@y>', 'account': 'Acme', 'keys': []}]}
ok(A.note_readable(plain) and A.note_readable({'links': []}), 'an ordinary note: Ask may read it')
ok(not A.note_readable(priv), 'a note linked to a private or hidden contact: never')
ok(A.note_readable(prot), 'a protected workplace with no setting: "own" – your own note may go')
modes['acme'] = 'none'
ok(not A.note_readable(prot) and not A.note_readable(prot_mail), '… its Claude setting "none": not readable (person or mail on its account)')
modes['acme'] = 'all'
ok(A.note_readable(prot), '… "all": readable')
A.STATE_DIR = os.path.join(d, 'state')
A.NOTES = N.Notes(d, os.path.join(d, 'state', 'deleted', 'notes'))
for nid in list(A.NOTES.load()['notes']):
    A.NOTES.delete(nid)
A.NOTES.save({'text': 'ordinary', 'links': plain['links']})
A.NOTES.save({'text': 'private one', 'links': priv['links']})
n = A._ask_notes('20300314-090000-abc123', 'alex@example.com')
folder = os.path.join(d, 'state', 'ask-notes', '20300314-090000-abc123')
ok(n == 1 and len(os.listdir(folder)) == 1 and 'private one' not in open(os.path.join(folder, os.listdir(folder)[0])).read(),
   'the Ask run gets a copy of only the notes it may read')
tallies = []
A.tally = lambda kind, n=1: tallies.append((kind, n))
A._ask_notes_done('20300314-090000-abc123', 1)
ok(not os.path.exists(folder) and ('notes_read', 1) in tallies and ('notes_asks', 1) in tallies,
   'after the run: counted for What leaves my home, and the copy is gone')
ok(A._ask_notes('../../x', 'alex@example.com') == 0, 'a bad Ask id: nothing copied')
ok(A._ask_notes('20300314-090100-def456', 'sam@example.com') == 0 and not os.path.exists(os.path.join(d, 'state', 'ask-notes', '20300314-090100-def456')),
   'someone else on the access list asks: no copy of your notes at all')
old_copy = os.path.join(d, 'state', 'ask-notes', 'crashed')
os.makedirs(old_copy)
os.utime(old_copy, (0, 0))
fresh = os.path.join(d, 'state', 'ask-notes', 'running')
os.makedirs(fresh)
A._ask_notes_sweep()
ok(not os.path.exists(old_copy) and os.path.exists(fresh), "a copy left by a crashed run goes after an hour; a running Ask's copy stays")
A._ask_notes_sweep(0)
ok(not os.path.exists(fresh), '… and at start, none stays')
sch_src = open(os.path.join(HERE, 'axella-actions.py'), encoding='utf-8').read()
ok("_ask_notes_sweep(0)" in sch_src and "                _ask_notes_sweep()" in sch_src, 'swept at start and by housekeeping, and before each Ask')

# ---------- 6. the runs ----------
ok('notes/**' in scheduler.SECRETS, 'no run may read notes/ (on the secrets list for every kind of run)')
src = open(os.path.join(HERE, 'scheduler.py'), encoding='utf-8').read()
ok("if spec['kind'] != 'ask':" in src and "Read', 'Grep', 'Glob')] + \\" in src and 'state/ask-notes/**' in src,
   'only the Ask run may read its own copy (state/ask-notes/)')
sd = tempfile.mkdtemp()
os.makedirs(os.path.join(sd, 'setup', 'local-tasks'))
for t in ('digest-morning', 'ask', 'compose', 'p0-check'):
    shutil.copy(os.path.join(HERE, 'local-tasks', t + '.md'), os.path.join(sd, 'setup', 'local-tasks', t + '.md'))
os.makedirs(os.path.join(sd, 'state'))
open(os.path.join(sd, 'state', 'mcp.json'), 'w').write('{}')


class Sched:
    def status(self, now=None):
        return {'digests': True, 'urgent': True, 'reason': None}


R = scheduler.Scheduler(sd, os.path.join(sd, 'state'), Sched(), lambda *a: None)
R.claude_bin = lambda: '/usr/bin/true'
cmds = {}
for task in ('digest-morning', 'ask', 'compose', 'p0-check'):
    try:
        cmd = R._command(task, {'ref': 'x1'} if task in ('ask', 'compose') else {})[0]
        cmds[task] = cmd[cmd.index('--disallowedTools') + 1]
    except Exception as e:
        cmds[task] = 'ERR ' + str(e)
ok(all('Read(/notes/**)' in v for v in cmds.values()), 'digest, urgent check, compose and Ask runs are all refused notes/ (%s)'
   % ', '.join(k for k, v in cmds.items() if 'Read(/notes/**)' not in v))
ok(all('Read(/state/ask-notes/**)' in cmds[t] for t in ('digest-morning', 'compose', 'p0-check')) and 'Read(/state/ask-notes/**)' not in cmds['ask'],
   'the Ask copy is refused to every other run, and open to the Ask run')
ok("'notes': {'folder': 'state/ask-notes/%s' % cid" in src and 'notes' in open(os.path.join(HERE, 'local-tasks', 'ask.md')).read(),
   'the Ask request names its notes folder, and the Ask prompt says how to use it')

reqs = []
R.ask_notes = lambda cid, login=None: (reqs.append(login), 2 if login == 'alex@example.com' else 0)[1]
for who in ('alex@example.com', 'sam@example.com'):
    r = R.ask_request({'question': 'what do my notes say about the quote?', '_login': who})
    req = json.load(open(os.path.join(sd, 'state', 'ask', r['id'] + '.request.json')))
    if who == 'alex@example.com':
        ok(req['notes'] == {'folder': 'state/ask-notes/' + r['id'], 'count': 2}, "the owner's Ask names its notes folder")
    else:
        ok(req['notes'] is None, 'an Ask from anyone else: notes null')
ok(reqs == ['alex@example.com', 'sam@example.com'], 'ask_request passes the asking login on')

# ---------- 7. backup, git ----------
ok('notes' in backup.CORE and 'state/ask-notes' in backup.SKIP_DIRS, 'notes/ is in every backup (the one-run Ask copy is not)')
root = os.path.dirname(HERE)
ok('notes/' in open(os.path.join(root, '.gitignore')).read().split('\n'), 'notes/ is never in git (.gitignore)')
ok('notes/|' in open(os.path.join(root, 'tools', 'release-check.sh')).read(), '… and on the release check\'s never-commit list')

print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
