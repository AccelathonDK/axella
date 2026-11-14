#!/usr/bin/env python3
"""What Axella handles (setup/features.py): the registry covers every action, route and scheduler task (or they are
core), the 8 cards and their features, first-start defaults (an install in use keeps everything; a new one gets the
default cards), per-person rules, dependencies, card switches, delete/restore/expiry, the run prompt note and denied
paths, Claude use per card, the guided setup's progress, and the scheduler skipping a switched-off feature's run.
Invented logins. Run: python3 setup/tests/test_features.py"""
import json
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import features as F  # noqa: E402
import scheduler  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def bad(fn, label):
    try:
        fn()
    except F.Bad:
        return ok(True, label)
    ok(False, label + ' (no error)')


print('The registry covers everything')
src = open(os.path.join(HERE, 'axella-actions.py'), encoding='utf-8').read()
acts, pres = set(), set()
for m in re.finditer(r"action\s*==\s*'([a-z0-9_]+)'", src):
    acts.add(m.group(1))
for m in re.finditer(r"action\s+in\s+\(([^)]*)\)", src):
    acts |= set(re.findall(r"'([a-z0-9_]+)'", m.group(1)))
for m in re.finditer(r"action\.startswith\(\(?([^)]*)\)", src):
    pres |= set(re.findall(r"'([a-z0-9_]+)'", m.group(1)))
for name in ('PLAN_ACTIONS', 'PROJECT_MAIL_ACTIONS', 'FEATURE_ACTIONS'):
    m = re.search(name + r"\s*=\s*[\(\{]([^)}]*)[\)\}]", src)
    acts |= set(re.findall(r"'([a-z0-9_]+)'", m.group(1)))
g = src[src.index('    def do_GET'):src.index('    def do_POST')]
gets = set(re.findall(r"\ba\s*==\s*'([a-z0-9_]+)'", g))
for m in re.finditer(r"\ba\s+in\s+\(([^)]*)\)", g):
    gets |= set(re.findall(r"'([a-z0-9_]+)'", m.group(1)))
lost_a = sorted(a for a in acts if F.feature_of_action(a) is None and a not in F.CORE_ACTIONS and not a.startswith(F.CORE_PREFIXES))
lost_p = sorted(p for p in pres if F.feature_of_action(p + 'x') is None and not (p + 'x').startswith(F.CORE_PREFIXES))
lost_g = sorted(x for x in gets if F.feature_of_get(x) is None and x not in F.CORE_GETS)
ok(len(acts) > 150 and not lost_a, 'every POST action belongs to a feature or core (%d actions)%s' % (len(acts), ' – missing: %s' % lost_a if lost_a else ''))
ok(not lost_p, 'every action prefix too' + (' – missing: %s' % lost_p if lost_p else ''))
ok(len(gets) > 80 and not lost_g, 'every GET route too (%d)%s' % (len(gets), ' – missing: %s' % lost_g if lost_g else ''))
lost_t = [t for t in scheduler.TASKS if F.feature_of_task(t) is None and t not in F.CORE_TASKS]
ok(not lost_t, 'every scheduler task belongs to a feature or core' + (' – missing: %s' % lost_t if lost_t else ''))
ok(not (set(F.CORE_ACTIONS) & {a for f in F.FEATURES for a in f.get('actions') or []}), 'nothing is both core and a feature')
ok([c['id'] for c in F.CARDS] == ['messages', 'calendar', 'projects', 'trips', 'money', 'briefs', 'voice'], 'the 7 cards in order')
ok(all(f['card'] in F.CARD_IDS for f in F.FEATURES) and all(F.features_of(c) for c in F.CARD_IDS), 'every feature on a card, every card has features')
ok(all(n in F.BY_ID for f in F.FEATURES for n in f.get('needs') or []), 'dependencies name real features')
ok(F.BY_ID['subscriptions']['needs'] == ['receipts'] and F.BY_ID['renewals']['needs'] == ['receipts'] and 'meeting_prep' in F.BY_ID['meeting_recordings']['needs']
   and 'projects' in F.BY_ID['plan']['needs'] and 'to_answer' in F.BY_ID['reply_sprint']['needs'] and 'to_answer' in F.BY_ID['back_from_away']['needs'],
   'the dependencies from the request')
for a, f in (('meeting_record_chunk', 'meeting_recordings'), ('meeting_add', 'meeting_prep'), ('meeting_service_connect', 'invites'),
             ('project_mail_scan', 'project_mail'), ('project_target_add', 'targets'), ('project_add', 'projects'), ('trip_scan', 'trips'),
             ('briefing_run', 'topic_briefs'), ('bill_add', 'bills'), ('away_catchup', 'back_from_away'),
             ('task_add', None), ('reply_send', None), ('cal_invite_send', 'invites'), ('cal_add', None)):
    ok(F.feature_of_action(a) == f, '%s → %s' % (a, f or 'core'))
ok(F.feature_of_get('briefs') == 'topic_briefs' and F.feature_of_action('briefing_run', {'id': 'x'}) == 'topic_briefs', 'briefs belong to Topic briefs')
ok(F.feature_of_task('briefing') == 'topic_briefs' and F.feature_of_task('trip-read') == 'trips'
   and F.feature_of_task('transcribe') == 'meeting_recordings' and F.feature_of_task('digest-morning') is None, 'scheduler tasks')


def install(with_data):
    d = tempfile.mkdtemp(prefix='axtest-feat-')
    st = os.path.join(d, 'state')
    os.makedirs(st)
    if with_data:
        open(os.path.join(st, 'tasks.json'), 'w').write('[{"id": "t1", "text": "Call Robin"}]')
    return F.Features(st, d), d


print('First start')
fe, base = install(True)
d = fe.load()
ok(not d['new_install'] and d['owner']['off'] == [], 'an install in use: everything stays on')
fn, base_n = install(False)
dn = fn.load()
on = {f for f in F.BY_ID if f not in dn['owner']['off']}
ok(dn['new_install'] and {'to_answer', 'filing', 'meeting_prep', 'projects', 'plan'} <= on, 'a new install: the default cards on')
ok(not on & {'trips', 'receipts', 'topic_briefs', 'spoken_digest', 'mail_tidy', 'send_later', 'meeting_recordings'},
   '… Trips, Money, briefs, Voice off, and the quieter ones (keep mail tidy, send later, recordings) too')
v = fn.view('owner@example.com', True)
ok(v['setup']['needed'] and not v['setup']['review'], 'a new install asks the guided setup')
v = fe.view('owner@example.com', True)
ok(not v['setup']['needed'] and v['setup']['review'], 'an install in use gets the "Review what Axella handles" card instead')
open(fe.path, 'w').write('{broken')
ok(fe.is_on('trips') and fe.view('owner@example.com', True)['broken'], 'an unreadable file: everything on …')
bad(lambda: fe.set('trips', False, 'owner@example.com', True), '… and changes are refused')
fe, base = install(True)

print('Per person')
O, S = 'owner@example.com', 'sam@example.com'
fe.set('trips', False, O, True)
ok(not fe.is_on('trips', S, False) and not fe.owner_on('trips'), 'the owner switches Trips off: off for everyone, background too')
bad(lambda: fe.set('trips', True, S, False), "someone else can't switch on what the owner has off")
ok(fe.view(S, False)['features']['trips']['owner_off'], '… it shows "switched off by the owner"')
fe.set('birthdays', False, S, False)
ok(not fe.is_on('birthdays', S, False) and fe.is_on('birthdays', O, True) and fe.owner_on('birthdays'), 'Sam switches Birthdays off for Sam only – the owner and background unchanged')
fe.set('trips', True, O, True)
ok(fe.is_on('trips', S, False) and fe.on_since('trips'), 'on again: for everyone, with its on-since time')

print('Dependencies')
r = fe.set('receipts', False, O, True)
ok(r.get('confirm') == 'Subscriptions and store items and Renewals also go off – they need Receipts and bookkeeping. Continue?',
   'switching Receipts off asks first: Subscriptions and Renewals need it')
ok(fe.is_on('receipts'), '… nothing changed before the answer')
r = fe.set('receipts', False, O, True, confirm=True)
ok(set(r['changed']) == {'receipts', 'subscriptions', 'renewals'} and not fe.is_on('renewals'), 'confirmed: all three off')
r = fe.set('renewals', True, O, True)
ok('needs Receipts and bookkeeping' in r['confirm'], 'switching Renewals on asks to switch Receipts on too')
fe.set('renewals', True, O, True, confirm=True)
ok(fe.is_on('receipts') and fe.is_on('renewals') and not fe.is_on('subscriptions'), '… both on, Subscriptions stays as it was')

print('Cards')
r = fe.set_card('projects', False, O, True)
ok(r.get('changed') and all(not fe.is_on(f) for f in F.features_of('projects')), 'a card off: all its features off')
r = fe.set_card('projects', True, O, True, features=['projects', 'plan'])
ok(fe.is_on('projects') and fe.is_on('plan') and not fe.is_on('targets'), 'on with the features picked in its mini-setup')
fe.mark_set_up('voice', False)
fe.set_card('voice', True, O, True)
c = next(x for x in fe.view(O, True)['cards'] if x['id'] == 'voice')
ok(c['on'] and c['not_set_up'] and c['n_on'] >= 1, '"Not set up yet" while its setup was skipped')
fe.mark_set_up('voice', True)
ok(not next(x for x in fe.view(O, True)['cards'] if x['id'] == 'voice')['not_set_up'], '… gone once set up')
r = fe.set_card('calendar', False, S, False)
ok(fe.owner_on('meeting_prep') and not fe.is_on('meeting_prep', S, False), "Sam's card switch is Sam's only")

print('Delete and restore (owner only, while off)')
os.makedirs(os.path.join(base, 'state', 'meetings', 'm1'))
open(os.path.join(base, 'state', 'meetings', 'm1', 'prep.json'), 'w').write('{"title": "Planning with Kim"}')
bad(lambda: fe.delete_data('calendar'), 'not while the card is on')
fe.set_card('calendar', False, O, True, confirm=True)
r = fe.delete_data('calendar')
ok(r['moved'] == ['state/meetings'] and not os.path.exists(os.path.join(base, 'state', 'meetings')), 'moved out, never deleted')
os.makedirs(os.path.join(base, 'state', 'meetings'))
open(os.path.join(base, 'state', 'meetings', 'new.json'), 'w').write('{}')
r2 = fe.restore_data(r['backup'])
ok(os.path.exists(os.path.join(base, 'state', 'meetings', 'm1', 'prep.json')) and
   any(n.startswith('meetings.since-') for n in os.listdir(os.path.join(base, 'state'))), 'restore: back in place, anything written since set aside')
bad(lambda: fe.restore_data('../../etc'), 'a bad backup id is refused')
r = fe.delete_data('calendar')
old = os.path.join(base, 'state', 'deleted', 'features', r['backup'])
os.utime(old, (time.time() - 91 * 86400,) * 2)
ok(fe.prune_deleted() == [r['backup']] and os.path.isdir(os.path.join(base, 'state', 'deleted', 'features', '_expired', r['backup'])), 'after 90 days: moved to _expired/')

print('What Claude runs leave out')
note = fe.prompt_note()
ok('Meeting prep' in note and 'Trips' not in note, 'the note names what the owner switched off')
paths = fe.denied_paths()
ok('state/meetings/**' in paths and 'state/calendar-invites.json' in paths, '… and its data is denied to the runs')

print('Claude use per card')
now = '2026-11-10T08:00:00+01:00'
runs = [{'task': 'digest-morning', 'started': now, 'status': 'ok'}] * 40 + [{'task': 'briefing', 'briefing': 'topic', 'started': now, 'status': 'ok'}] * 3 + \
       [{'task': 'trip-read', 'started': '2026-01-01T00:00:00+01:00', 'status': 'ok'}]
u = F.Features.claude_use(runs, '2026-10-11T00:00:00+01:00')
ok(u == {'messages': 'moderate', 'briefs': 'light'}, 'from the last 30 days of runs (older ones left out)')
ok(next(c for c in fe.view(O, True, u)['cards'] if c['id'] == 'voice')['claude'] == 'light', 'no runs yet: the default word')

print('Guided setup progress')
fe.setup_save(O, {'step': 'cards', 'chosen': ['messages', 'voice', 'nonsense']})
ok(fe.view(O, True)['setup']['progress']['chosen'] == ['messages', 'voice'], 'saved per person, unknown cards dropped')
bad(lambda: fe.setup_save(O, {'step': '../x'}), 'an unknown step is refused')
fe.setup_save(O, {'done': True})
ok(not fe.view(O, True)['setup']['review'], 'done: no review card any more')
fe.review_set(S, 'later')
ok(fe.load()['review'][S] == 'later', '"Later" is remembered')

print('The scheduler skips a switched-off feature')
sd = tempfile.mkdtemp(prefix='axtest-sched-')
os.makedirs(os.path.join(sd, 'state'))
sch = scheduler.Scheduler(sd, os.path.join(sd, 'state'), None, lambda *a, **k: None)
fs = F.Features(os.path.join(sd, 'state'), sd)
fs.load()
fs.set('trips', False, O, True)
sch.features = fs
sch._run({'task': 'trip-read', 'trigger': 'manual', 'attempt': 1, 'ref': 'tr1', 'not_before': 0})
run = sch._load_runs()['runs'][-1]
ok(run['status'] == 'skipped' and run['reason'] == 'skipped – feature off (Trips)', 'Runs shows "skipped – feature off (Trips)" – never started')
ok('Trips' in fs.prompt_note(), 'the digest prompt note names it')

print()
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
