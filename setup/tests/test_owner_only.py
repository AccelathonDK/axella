#!/usr/bin/env python3
"""Changing contacts and the calendar is for the owner's own login only: "owner": {"logins": [...]} in
actions-config.json, else the first login on the dashboard's access list. Fictional logins.
Run: python3 setup/tests/test_owner_only.py"""
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

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


A.ACCESS_FILE = os.path.join(tempfile.mkdtemp(), 'access.json')
json.dump({'paths': {'/axella/': ['owner@example.com', 'sam@example.com']}}, open(A.ACCESS_FILE, 'w'))
A.config = lambda: {}
ok(A.owner_logins() == {'owner@example.com'}, 'no setting: the first login on the access list')
A.config = lambda: {'owner': {'logins': ['alex@example.com', 'alex.phone@example.com']}}
ok(A.owner_logins() == {'alex@example.com', 'alex.phone@example.com'}, 'owner.logins wins')
json.dump({'paths': {'/axella/': []}}, open(A.ACCESS_FILE, 'w'))
A.config = lambda: {}
ok(A.owner_logins() == set(), 'nobody on the list: nobody is owner (fail closed)')
ok({'contact_add', 'contact_delete', 'cal_update', 'cal_delete', 'cal_restore'} <= A.OWNER_ONLY, 'edits are owner-only actions')
ok({a for a in A.OWNER_ONLY if not a.startswith(('meeting_', 'birthday_', 'trip_', 'project_', 'renewal_', 'block_settings', 'block_never', 'block_not_now', 'away_', 'backup_', 'teach_', 'rule_', 'suggest_', 'calm_setup_', 'note_', 'plan_')) and a not in ('person_note', 'keep_set')} <= A.SLOW_ACTIONS,
   '… contacts and calendar run in the background queue')
ok({'person_note', 'keep_set'} <= A.OWNER_ONLY, 'People notes and keep in touch: owner only')
ok('birthday_show' in A.OWNER_ONLY, '"Show birthday": owner only')
ok(set(A.PLAN_ACTIONS) <= A.OWNER_ONLY and 'plan_hold' in A.SLOW_ACTIONS, 'Targets, people on a project and the day plan: owner only; Hold runs in the background')
ok({'trip_scan', 'trip_confirm', 'trip_remove'} <= A.OWNER_ONLY, 'trips: owner only')
ok(A.PROJECT_MAIL_ACTIONS <= A.OWNER_ONLY, 'Projects → Scan mail, To sort, Read with Claude: owner only')
ok({'meeting_add', 'meeting_update', 'meeting_delete', 'meeting_assist', 'meeting_upload', 'meeting_url_add'} <= A.OWNER_ONLY, 'meeting prep is owner-only')

# a meeting with a protected workplace: its transcript stays on the Mac mini
cfgf = os.path.join(tempfile.mkdtemp(), 'cfg.json')
json.dump({'workplaces': [{'id': 'acme', 'name': 'Acme', 'domains': ['acme.example'], 'protected': True}],
           'calendars': [{'name': 'Calendar', 'kind': 'work', 'workplace': 'acme'}, {'name': 'Home', 'kind': 'private'}]}, open(cfgf, 'w'))
A.profile.CONFIG = cfgf
ok(A.meeting_protected({'attendees': [{'email': 'lee@acme.example'}]}), 'protected: an attendee from the workplace domain')
ok(A.meeting_protected({'attendees': [], 'event': {'calendar': 'Calendar'}}), 'protected: the workplace calendar')
ok(not A.meeting_protected({'attendees': [{'email': 'robin@home.example'}], 'event': {'calendar': 'Home'}}), 'a private meeting is not protected')
ok(A.meeting_ai({'attendees': [{'email': 'lee@acme.example'}]}) == (True, 'own'), 'protected meeting: your own text only by default')
ok(A.meeting_ai({'attendees': [{'email': 'lee@acme.example'}], 'ai': 'all'}) == (True, 'all'), '… or everything, when you choose it')
ok(A.meeting_ai({'attendees': [{'email': 'robin@home.example'}], 'ai': 'none'}) == (False, 'all'), 'an ordinary meeting is not limited')
A.MEET = A.Meetings(tempfile.mkdtemp(), tempfile.mkdtemp())
A.MEET.set_ai_default('acme', 'none')
ok(A.meeting_ai({'attendees': [{'email': 'lee@acme.example'}]}) == (True, 'none'), 'the workplace default applies to a new meeting')
ok(A.meeting_ai({'attendees': [{'email': 'lee@acme.example'}], 'ai': 'all'}) == (True, 'all'), '… and the meeting\'s own choice wins')
ok(A.meeting_workplaces({'attendees': [{'email': 'x@sub.acme.example'}]}) == ['acme'], 'a subdomain counts as the workplace')
ok('meeting_ai_default' in A.OWNER_ONLY, 'changing the default: owner only')
ok({'meeting_transcript_upload', 'meeting_transcript_paste', 'meeting_transcribe'} <= A.OWNER_ONLY, 'recordings and transcripts: owner only')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
