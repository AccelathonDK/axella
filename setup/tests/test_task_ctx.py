#!/usr/bin/env python3
"""Tasks can be marked Work or Private – optional. Only 'work' / 'private' are stored; anything else clears it.
Fictional data. Run: python3 setup/tests/test_task_ctx.py"""
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


A.TASKS_FILE = os.path.join(tempfile.mkdtemp(), 'tasks.json')
tasks = lambda: {t['id']: t for t in json.load(open(A.TASKS_FILE))}
a = A.task_action('task_add', {'text': 'Send the Acme quote', 'ctx': 'work'})
b = A.task_action('task_add', {'text': 'Book the dentist'})
c = A.task_action('task_add', {'text': 'Odd', 'ctx': 'secret'})
t = tasks()
ok(t[a].get('ctx') == 'work', 'added as Work')
ok('ctx' not in t[b], 'no ctx: unset (shows under both filters)')
ok('ctx' not in t[c], 'an unknown value is not stored')
A.task_action('task_update', {'id': b, 'ctx': 'private'})
ok(tasks()[b].get('ctx') == 'private', 'changed to Private')
A.task_action('task_update', {'id': b, 'ctx': None})
ok('ctx' not in tasks()[b], 'cleared again ("Either")')
A.task_action('task_update', {'id': a, 'due': '2026-11-10'})
ok(tasks()[a].get('ctx') == 'work', 'other edits leave it alone')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
