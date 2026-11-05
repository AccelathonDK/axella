#!/usr/bin/env python3
"""Calendar invitations under the mail's hourly brake (axella-actions.py online_action): each invitation, update or
cancellation counts as one send in state/sent.json; a silent save counts nothing. Stubbed calendar side; invented data.
Run: python3 setup/tests/test_invite_brake.py"""
import importlib.util
import json
import os
import sys
import tempfile
import time

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


class Stub:
    def send(self, p):
        return {'uid': 'U-1', 'calendar': p['calendar'], 'people': [{'email': 'lee@example.com'}, {'email': 'sam@example.net'}]}

    def update(self, p):
        return {'uid': 'U-1', 'calendar': 'Home', 'people': [{'email': 'lee@example.com'}]}

    def cancel(self, p):
        return {'uid': 'U-1', 'title': 'Acme planning'}


A.SENT_FILE = os.path.join(tempfile.mkdtemp(), 'sent.json')
A.ONLINE = Stub()
A.profile.owner = lambda *a, **k: {'name': 'Alex Example'}
A.online_action('cal_invite_send', {'calendar': 'Home', 'title': 'Acme planning', 'confirm': 'send'})
s = json.load(open(A.SENT_FILE))
ok(len(s) == 1 and s[0]['action'] == 'cal_invite_send' and s[0]['to'] == '2 people' and s[0]['key'].startswith('cal_invite:U-1:'),
   'an invitation counts as one send – who as a count, never the addresses')
ok('lee@example.com' not in json.dumps(s), '… no invitee address in sent.json')
A.online_action('cal_invite_update', {'uid': 'U-1', 'title': 'Acme planning', 'confirm': 'save'})
ok(len(json.load(open(A.SENT_FILE))) == 1, 'a silent save counts nothing')
A.online_action('cal_invite_update', {'uid': 'U-1', 'title': 'Acme planning', 'confirm': 'send'})
A.online_action('cal_invite_cancel', {'uid': 'U-1', 'title': 'Acme planning', 'confirm': 'send'})
ok([x['action'] for x in json.load(open(A.SENT_FILE))] == ['cal_invite_send', 'cal_invite_update', 'cal_invite_cancel'], 'Send update and Send cancellation count')
now = time.time()
json.dump([{'at': '', 'ts': now - 60, 'status': 'sent', 'key': 'x%d' % i} for i in range(A.SEND_MAX)], open(A.SENT_FILE, 'w'))
try:
    A.online_action('cal_invite_send', {'calendar': 'Home', 'title': 'Acme planning', 'confirm': 'send'})
    ok(False, 'the hourly brake stops an invitation')
except A.Bad as e:
    ok('in an hour' in str(e), 'the hourly brake stops an invitation')
ok(not any(str(x.get('key')).startswith('invite:') for x in json.load(open(A.SENT_FILE))), 'never mistaken for an invitation answer (invite: keys)')
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
