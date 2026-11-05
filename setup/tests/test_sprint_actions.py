#!/usr/bin/env python3
"""Reply sprint in the action service (axella-actions.py): GET sprint reads the newest digest and leaves out private
and hidden contacts, a protected workplace's mail, handled items and replies waiting in Send later; reply debt goes
first. Privacy, workplaces and Send later stubbed; invented data. Run: python3 setup/tests/test_sprint_actions.py"""
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


def item(iid, who, acc='Work', sec='p2'):
    return {'id': iid, 'section': sec, 'channel': 'mail', 'account': acc, 'message_id': '<%s@example.com>' % iid,
            'from': {'name': 'Alex Example', 'address': who}, 'headline': 'A question', 'first_seen': '2027-03-09T07:30:00',
            'draft': {'mode': 'reply', 'to': who, 'text': 'Yes – Thursday at 10 is fine. Best, Alex'}}


d = tempfile.mkdtemp()
A.DIGESTS_DIR = d
A.STATE_FILE = os.path.join(d, 'actions.json')
json.dump({'items': [item('old', 'kim@example.org')]}, open(os.path.join(d, '2027-03-08-0730.json'), 'w'))
json.dump({'items': [item('a', 'lee@example.com'), item('b', 'sam@example.org'), item('priv', 'robin@example.net'),
                     item('hid', 'jamie@example.net'), item('prot', 'anna@acme.example', acc='Acme'), item('done', 'lee@example.com'),
                     item('later', 'lee@example.com'), item('c', 'kim@example.org', sec='p1')]},
          open(os.path.join(d, '2027-03-09-0730.json'), 'w'))
json.dump({'items': [{'id': 'u', 'section': 'p0'}]}, open(os.path.join(d, '2027-03-09-1000-p0.json'), 'w'))
json.dump({'done': {'status': 'done', 'how': 'sent'}}, open(A.STATE_FILE, 'w'))


class Priv:
    def level(self, ch, a):
        return {'robin@example.net': 'private', 'jamie@example.net': 'hidden'}.get(a)

    def contact(self, a):
        return {'name': 'Robin'}

    def load(self):
        return {}


class Sched:
    def list(self):
        return [{'item_id': 'later', 'status': 'scheduled'}, {'item_id': 'a', 'status': 'sent'}]


A.PRIV = Priv()
A.SCHED_SEND = Sched()
A.profile.is_protected = lambda acc, addr: acc == 'Acme'
A._COMMIT['debt'] = [{'who': 'sam@example.org', 'days': 5}]
v = A.sprint_view()
ids = [i['id'] for i in v['items']]
ok(v['digest'] == '2027-03-09-0730.json', 'the newest regular digest (not an urgent one)')
ok('priv' not in ids and 'hid' not in ids, 'private and hidden contacts never appear')
ok('prot' not in ids, 'a protected workplace\'s mail never appears')
ok('done' not in ids and 'later' not in ids and 'a' in ids, 'sent and waiting-in-Send-later replies are left out (a send that already went is not)')
ok(ids == ['b', 'c', 'a'], 'the person you owe goes first, then P1, then P2 (%s)' % ids)
ok(v['count'] == 3 and v['show'] and v['minutes'] >= 1, 'three ready: the card shows, about %d min' % v['minutes'])
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
