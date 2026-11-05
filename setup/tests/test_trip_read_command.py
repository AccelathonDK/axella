"""The "Read with Claude" run for Trips (scheduler kind "trips"): it may only open mails and their attachments, write
its one result file, and read nothing outside the Axella folder – not Mail's folders, not temporary files (security
review 6). Fictional data; no Claude call. Run: python3 setup/tests/test_trip_read_command.py"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scheduler as S  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


base = tempfile.mkdtemp(prefix='axtr-')
state = os.path.join(base, 'state')
os.makedirs(os.path.join(state, 'runs'))
os.makedirs(os.path.join(base, 'setup', 'local-tasks'))
for t in ('trip-read', 'receipts-catchup'):
    open(os.path.join(base, 'setup', 'local-tasks', t + '.md'), 'w').write('# Task\n')
open(os.path.join(state, 'mcp.json'), 'w').write('{}')


class Sched:
    def sweep(self):
        return None

    def status(self, *_):
        return {'digests': True, 'urgent': True, 'reason': None}


s = S.Scheduler(base, state, Sched(), None, log=open(os.devnull, 'w'))
s.claude_bin = lambda: '/x/claude'
rid = s.trip_read_request([{'account': 'iCloud', 'message_id': 'e1@acme-air.example', 'subject': 'E-ticket',
                            'sender': 'tickets@acme-air.example', 'date': '2026-10-10T18:02:00+02:00'}])
job = next(j for j in s.queue if j['task'] == 'trip-read')
cmd, _ = s._command('trip-read', job)
allowed = cmd[cmd.index('--allowedTools') + 1].split(',')
never = cmd[cmd.index('--disallowedTools') + 1]
mac = sorted(a for a in allowed if a.startswith('mcp__macuse__'))
ok(mac == ['mcp__macuse__mail_get_attachment', 'mcp__macuse__mail_get_messages'], 'only the two tools that open a mail and its attachments: %s' % mac)
ok('mcp__macuse__mail_search_messages' in never and 'mcp__macuse__messages_get_chat' in never and 'mcp__macuse__contacts_get_all' in never,
   'searching mail, chats and contacts is refused')
ok(not any(x in ','.join(allowed) for x in ('Library/Mail', '//tmp', 'var/folders')), 'no reading of Mail\'s folders or temporary files')
ok('Write(/state/trips-read/*.json)' in allowed and not any(a.startswith('Bash(') and a not in ('Bash(ls:*)', 'Bash(date:*)') for a in allowed),
   'it writes its result file only')
ok('mcp__macuse__mail_compose_message' in never and 'WebFetch' in never, 'no sending, no web')
rjob = {'task': 'receipts-catchup'}
rcmd, _ = s._command('receipts-catchup', rjob)
ok(not any(x in rcmd[rcmd.index('--allowedTools') + 1] for x in ('Library/Mail', '//tmp', 'var/folders')), 'the receipts catch-up does not read them either')
prompt = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'local-tasks', 'trip-read.md'), encoding='utf-8').read()
ok('only what ITS OWN mail' in prompt and 'never copy names, ticket numbers' in prompt and 'is NOT a duplicate' in prompt,
   'the instructions: each booking only from its own mail; another traveller\'s e-ticket is not a duplicate')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
