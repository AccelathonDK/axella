#!/usr/bin/env python3
"""Protect your blocks in the action service (axella-actions.py): Hold it adds one busy event of your own in the chosen
work calendar through cal_add – nothing else; Not now / Don't suggest for this day; settings. Calendar stubbed; invented.
Run: python3 setup/tests/test_blocks_actions.py"""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
import blocks as B  # noqa: E402
import calendar_view as CV  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


A.BLOCKS = B.Blocks(tempfile.mkdtemp())
A.profile.calendars = lambda *a: [{'name': 'Home', 'kind': 'private'}, {'name': 'Work', 'kind': 'work'}]
calls = []
CV.edit = lambda mcp, cals, action, p, backup, **kw: (calls.append((action, p)), {'id': 'ev1', 'title': p['title']})[1]
try:
    A.block_action('block_settings', {'calendar': 'Home'})
    ok(False, 'held blocks only go to a work calendar')
except A.Bad:
    ok(True, 'held blocks only go to a work calendar')
A.block_action('block_settings', {'calendar': 'Work', 'name': 'Deep work', 'minutes': 120})
r = A.block_action('block_hold', {'date': '2027-03-09', 'start': '12:30', 'end': '14:30'})
ok(len(calls) == 1 and calls[0][0] == 'cal_add' and calls[0][1]['calendar'] == 'Work' and calls[0][1]['title'] == 'Deep work'
   and calls[0][1]['start'].startswith('2027-03-09T12:30:00') and calls[0][1]['end'].startswith('2027-03-09T14:30:00'),
   'Hold it: one event of your own, in the chosen calendar, named as you set')
ok(set(calls[0][1]) == {'title', 'calendar', 'start', 'end', 'notes'}, '… nothing else is sent to the calendar (no invitees, no other event)')
ok('2027-03-09' in A.BLOCKS.load()['shown'], '… and not suggested again for that day')
for bad_ in ({'date': '2027-03-09', 'start': '14:30', 'end': '12:30'}, {'date': 'soon', 'start': '12:30', 'end': '14:30'}):
    try:
        A.block_action('block_hold', bad_)
        ok(False, 'refused: %s' % bad_)
    except A.Bad:
        ok(len(calls) == 1, 'refused: %s' % bad_)
A.block_action('block_never', {'date': '2027-03-10'})
ok('2027-03-10' in A.BLOCKS.load()['never'], 'Don\'t suggest for this day')
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
