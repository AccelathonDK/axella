#!/usr/bin/env python3
"""A bill To do in state/tasks.json carries no payment details (Claude runs read that file) – they live in
state/bills.json. Ticking a bill marks its Receipts entry paid. Invented data only.
Run: python3 setup/tests/test_bills_tasks.py"""
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
import bills  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


tmp = tempfile.mkdtemp()
A.TASKS_FILE = os.path.join(tmp, 'tasks.json')
A.BILLS = bills.Bills(tmp)
paid = []


class Docs:
    def action(self, action, p):
        paid.append((p['message_id'], p['paid']))


A.DOCS = Docs()
card = {'id': 'm1', 'payee': 'Acme Power', 'amount': 1245.0, 'currency': 'DKK', 'due': '2027-03-17', 'reference': {'iban': 'DK67 1234 5678 9012 34'},
        'account': 'iCloud', 'message_id': 'm1', 'attachments': []}
t = A.BILLS.task_for(card)
tid = A.task_action('task_add', dict(t, source='bill'))
raw = open(A.TASKS_FILE).read()
ok('DK67' not in raw and 'reference' not in raw, 'tasks.json has no payment details')
ok(A.BILLS.refs({tid}) == {tid: {'iban': 'DK67 1234 5678 9012 34'}}, 'they are in bills.json, under the task')
saved = json.loads(raw)[0]
ok(saved['type'] == 'bill' and saved['bill']['payee'] == 'Acme Power' and saved['bill']['amount'] == 1245.0, 'the To do keeps payee and amount')
A.task_action('task_update', {'id': tid, 'bill': {'reference': {'mobilepay': '54321'}}})
ok('54321' not in open(A.TASKS_FILE).read() and A.BILLS.refs({tid})[tid] == {'mobilepay': '54321'}, 'editing the details changes bills.json only')
A.task_action('task_done', {'id': tid})
ok(paid and paid[-1][0] == 'm1' and paid[-1][1], 'ticking the bill marks the Receipts entry paid')
A.task_action('task_undo', {'id': tid})
ok(paid[-1] == ('m1', None), 'unticking clears it')
A.task_action('task_delete', {'id': tid})
ok(A.BILLS.refs() == {}, 'deleting the To do deletes its details')
# "Already paid" on a suggested bill: no To do, the Receipts entry marked paid, and it doesn't come back
import datetime  # noqa: E402
DOC = {'message_id': 'm5', 'vendor': 'Acme Water', 'vendor_key': 'acmewater', 'kind': 'bill', 'amount': 300.0, 'currency': 'DKK',
       'date': datetime.date.today().isoformat(), 'due': (datetime.date.today() + datetime.timedelta(days=9)).isoformat()}


class Docs2(Docs):
    def load(self):
        return {'documents': {'m5': dict(DOC, paid=None)} if not paid or paid[-1][0] != 'm5' else {'m5': dict(DOC, paid=paid[-1][1])}}


A.DOCS = Docs2()
A._known_people = lambda: (set(), set())
A.BILLS.refresh(A.DOCS.load()['documents'], skip=lambda m, d: None)
n_tasks = len(json.load(open(A.TASKS_FILE)))
A.bill_action('bill_paid_already', {'id': 'm5'})
ok(paid[-1][0] == 'm5' and paid[-1][1] and len(json.load(open(A.TASKS_FILE))) == n_tasks, 'Already paid: the Receipts entry is paid, no To do made')
ok(A.BILLS.load()['docs']['m5']['status'] == 'paid' and not A.BILLS.suggestions(A.DOCS.load()['documents']), '… and the card is gone for good')
try:
    A.bill_action('bill_paid_already', {'id': 'm5'})
    ok(False, 'a second tap is refused')
except A.Bad:
    ok(True, 'a second tap is refused')

print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
