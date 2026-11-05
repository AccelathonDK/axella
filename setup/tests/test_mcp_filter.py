#!/usr/bin/env python3
"""Unit tests for setup/mcp_filter.py (security review 3, P2-1) – fictional data only, nothing is read from Mail,
Messages or the calendar. Run: python3 setup/tests/test_mcp_filter.py"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import mcp_filter as F  # noqa: E402
import privacy  # noqa: E402

fails = 0


def ok(cond, label):
    global fails
    print(('  ok   ' if cond else '  FAIL ') + label)
    fails += 0 if cond else 1


st = tempfile.mkdtemp()
with open(os.path.join(st, 'privacy.json'), 'w') as f:
    json.dump({'defaults': {'mail': 'normal', 'imessage': 'normal'},
               'contacts': [{'id': 'k1', 'name': 'Kim Example', 'ids': ['kim@private.example', '+45 00 00 00 07'],
                             'levels': {'mail': 'private', 'imessage': 'private'}}]}, f)
pv = privacy.Privacy(st)
mail, msgs, cal = F.Matcher(pv, 'mail'), F.Matcher(pv, 'imessage'), F.Matcher(pv, 'calendar')
SECRET = 'SECRET BODY'


def clean(out):
    return SECRET not in out and 'kim@private.example' not in out


# the three shapes from the review
a = F.filter_text(json.dumps({'from': 'Lee <lee@clientb.example>', 'cc': ['kim@private.example'], 'subject': 'Plans', 'body': SECRET}), mail)
ok(a == F.GONE, 'a single message with the contact only in cc is removed whole')
b = F.filter_text(json.dumps({'results': ['From: kim@private.example\n' + SECRET, 'From: lee@clientb.example\nhello']}), mail)
ok(clean(b) and 'hello' in b, 'a list of strings: the string that mentions them is dropped, the rest stays')
c = F.filter_text('From: kim@private.example\nSubject: x\n\n' + SECRET + ' paragraph', mail)
ok(c == F.GONE, 'plain text that mentions them anywhere is withheld entirely')

# shapes like Macuse's: a list of messages, a thread wrapper, a chat
lst = F.filter_text(json.dumps([{'id': 1, 'from': 'kim@private.example', 'subject': 'Hi', 'body': SECRET},
                                {'id': 2, 'from': 'lee@clientb.example', 'subject': 'Report', 'body': 'fine'}]), mail)
ok(clean(lst) and 'Report' in lst, 'mail_get_messages-like list: their mail gone, others kept')
thr = json.loads(F.filter_text(json.dumps({'messages': [{'from': 'lee@clientb.example', 'body': 'fine'},
                                                        {'from': 'Lee', 'to': ['kim@private.example'], 'body': SECRET}],
                                           'count': 2, 'next_cursor': 'abc'}), mail))
ok(thr['count'] == 1 and len(thr['messages']) == 1 and SECRET not in json.dumps(thr), 'thread wrapper kept, count fixed, their mail gone')
chat = F.filter_text(json.dumps({'chat': {'participants': ['+4500000007'], 'messages': [{'text': SECRET}]}}), msgs)
ok(SECRET not in chat, 'messages_get_chat: a chat with their number is removed')
byname = F.filter_text(json.dumps([{'sender': 'Kim Example', 'text': SECRET}, {'sender': 'Sam Rivera', 'text': 'ok'}]), msgs)
ok(SECRET not in byname and 'ok' in byname, 'iMessage by contact name')
spaced = F.filter_text('Call from +45 00 00 00 07 – ' + SECRET, msgs)
ok(spaced == F.GONE, 'phone number written with spaces')
nested = F.filter_text(json.dumps({'mailbox': 'INBOX', 'items': [{'id': 3, 'meta': {'reply_to': 'kim@private.example'}, 'body': SECRET}]}), mail)
ok(SECRET not in nested, 'nested mention inside a message')
ev = F.filter_text(json.dumps({'events': [{'title': 'Lunch', 'attendees': ['kim@private.example'], 'notes': SECRET},
                                          {'title': 'Standup', 'attendees': ['lee@clientb.example']}]}), cal)
ok(SECRET not in ev and 'Standup' in ev, 'calendar: their invite gone, other events kept')
lists = F.filter_text(json.dumps({'headers': [{'name': 'Cc', 'value': 'kim@private.example'}], 'parts': [{'text': SECRET}]}), mail)
ok(lists == F.GONE, 'a message made only of lists (headers/parts) is removed whole')
untouched = json.dumps({'messages': [{'from': 'lee@clientb.example', 'body': 'fine'}]})
ok(F.filter_text(untouched, mail) == untouched, 'results without them pass unchanged')

r = F.filter_result('mail_get_messages', {'content': [{'type': 'text', 'text': 'From: kim@private.example\n' + SECRET},
                                                      {'type': 'image', 'data': 'x'}],
                                          'structuredContent': {'from': 'kim@private.example', 'body': SECRET}}, pv)
ok(SECRET not in json.dumps(r) and all(c['type'] == 'text' for c in r['content']), 'filter_result: text, images and structuredContent')
ok(F.filter_result('contacts_search', {'content': [{'type': 'text', 'text': 'x'}]}, pv)['content'][0]['text'] == 'x', 'other tools untouched')

print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
