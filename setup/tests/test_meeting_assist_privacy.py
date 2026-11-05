#!/usr/bin/env python3
"""Meeting prep, "Ask Claude" (axella-actions.py meeting_assist): a mail added as material is re-checked on every
address it has (From, To, Cc, Reply-To, Sender), not only From. A private contact in Cc keeps the mail's words from
Claude; so does a mail whose file can't be found. Mail, Claude and the meeting store are stubbed. Fictional cast.
Run: python3 setup/tests/test_meeting_assist_privacy.py"""
import importlib.util
import os
import sys

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


BODY = 'Draft terms for the Acme renewal'
PREP = {'id': 'm1', 'title': 'Acme renewal', 'materials': [
    {'id': 'x1', 'kind': 'mail', 'account': 'Acme', 'message_id': '<a@acme.example>', 'from': 'Lee Chen <lee@acme.example>'}]}
FILES = {}                        # message id → addresses in the mail file (None = not on disk)
PRIVATE = {'sam@rivera.example'}


class FakeMeet:
    def get(self, mid):
        return PREP

    def material_text(self, *a, **k):
        return ''


seen = {}
A.MEET = FakeMeet()
A.meeting_ai = lambda prep, with_source=False: (False, 'auto')
A.meeting_context = lambda mid, for_claude=False: {}
A.message_preview = lambda acc, mid: {'body': BODY}
A.mailsearch.path_for_mid = lambda mid: ('/m/' + mid) if FILES.get(mid) is not None else None
A.mailsearch.addresses_of = lambda path: FILES[path[3:]]
A.mail_privacy = lambda addrs: (('private', None) if any(a.lower() in PRIVATE for a in addrs) else (None, None))
A.RUNNER.load = lambda: {}
import task_suggest  # noqa: E402
import meetings  # noqa: E402
task_suggest.claude_bin = lambda: 'claude'
meetings.build_prompt = lambda prep, ctx, mats, kind, **k: seen.__setitem__('mats', mats) or 'prompt'
meetings.assist = lambda prompt, binary, model=None: {'text': 'ok'}


def ask():
    seen.clear()
    A.meeting_action('meeting_assist', {'id': 'm1', 'kind': 'question', 'question': 'What is open?'})
    return next(x for x in seen['mats'] if x['id'] == 'x1')['text']


FILES['<a@acme.example>'] = ['lee@acme.example', 'alex@example.com']
ok(ask() == BODY, 'a mail with no private contact on it: Claude gets the words')

FILES['<a@acme.example>'] = ['lee@acme.example', 'alex@example.com', 'sam@rivera.example']
ok(ask() == '', 'a private contact in Cc (From is fine): Claude gets nothing')

FILES['<a@acme.example>'] = None
ok(ask() == '', 'the mail file cannot be found: Claude gets nothing (fails closed)')

FILES['<a@acme.example>'] = ['lee@acme.example']
PRIVATE.add('lee@acme.example')
ok(ask() == '', 'a sender made private after the mail was added: Claude gets nothing')

print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
