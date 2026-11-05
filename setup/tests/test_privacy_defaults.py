#!/usr/bin/env python3
"""Privacy defaults never move people on the list: changing an app's default (or a new default in the code) must not
make a private contact readable. Fictional data. Run: python3 setup/tests/test_privacy_defaults.py"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import privacy as P  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


d = tempfile.mkdtemp()
f = os.path.join(d, 'privacy.json')
json.dump({'defaults': {'signal': 'private'}, 'contacts': [
    {'id': 'c1', 'name': 'Jamie Example', 'ids': ['+4500000003'], 'levels': {}},                 # "Default" everywhere
    {'id': 'c2', 'name': 'Kim Example', 'ids': ['+4500000004'], 'levels': {'signal': 'normal'}}]}, open(f, 'w'))
pv = P.Privacy(d)
ok(pv.level('signal', '+45 00 00 00 03') == 'private', 'Jamie follows the Signal default: private')
pv.set({'defaults': {'signal': 'normal'}})
ok(pv.level('signal', '+4500000003') == 'private', 'Signal default → Normal: Jamie stays private')
ok(pv.level('signal', '+4500000004') == 'normal', 'Kim keeps her own Normal')
ok(pv.level('signal', '+4500000009') == 'normal', 'people not on the list follow the new default')
ok(json.load(open(f))['contacts'][0]['levels'] == {'signal': 'private'}, 'what Jamie had is written out')
ok(pv.level('whatsapp', '+4500000003') == 'normal', 'other apps unchanged')

d2 = tempfile.mkdtemp()
json.dump({'contacts': [{'id': 'c1', 'name': 'Jamie Example', 'ids': ['+4500000003'], 'levels': {}}]}, open(os.path.join(d2, 'privacy.json'), 'w'))
ok(P.Privacy(d2).level('signal', '+4500000003') == 'private', 'an older file without a Signal default keeps Signal private')
ok(P.Privacy(tempfile.mkdtemp()).load()['defaults']['signal'] == 'normal', 'a new install: Signal Normal by default')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
