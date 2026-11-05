#!/usr/bin/env python3
"""Signal export – what counts as a message. Signal also sends data messages without one (a profile key after you
write to someone, a disappearing-messages timer, "delete for everyone", reactions); they must never show as "1 new".
Fictional numbers; signal-cli is not run. Run: python3 setup/tests/test_signal_export.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import signal_export as S  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


class Pv:
    def level(self, ch, peer):
        return 'private'

    def contact(self, peer):
        return {'id': 'c1', 'name': 'Sam Rivera'} if peer == '+4500000002' else None


T = 1_800_000_000_000
sam = '+4500000002'
env = [
    # you write to Sam from the phone (sync) …
    {'envelope': {'sourceNumber': '+4500000001', 'timestamp': T, 'syncMessage': {'sentMessage': {'destinationNumber': sam, 'timestamp': T, 'message': 'Hi Sam'}}}},
    # … and Sam's phone answers with a profile key / timer update – no message
    {'envelope': {'sourceNumber': sam, 'sourceName': 'Sam', 'timestamp': T + 1000, 'dataMessage': {'timestamp': T + 1000, 'profileKey': 'x', 'expiresInSeconds': 0}}},
    {'envelope': {'sourceNumber': sam, 'timestamp': T + 2000, 'dataMessage': {'timestamp': T + 2000, 'isExpirationUpdate': True, 'expiresInSeconds': 3600}}},
    {'envelope': {'sourceNumber': sam, 'timestamp': T + 3000, 'dataMessage': {'timestamp': T + 3000, 'remoteDelete': {'timestamp': T}}}},
    {'envelope': {'sourceNumber': sam, 'timestamp': T + 4000, 'dataMessage': {'timestamp': T + 4000, 'reaction': {'emoji': 'x'}}}},
]
store = S.ingest({}, env, Pv(), T + 5000)
normal, private = S.outputs(store, Pv(), {})
row = private[0] if private else {}
ok(len(store['chats']['p:' + sam]['messages']) == 1, 'only your own message is stored')
ok(row.get('last_from_me') is True and row.get('unread') == 0 and row.get('waiting') == 0, 'no "1 new" after you wrote: %s' % row)

store = S.ingest(store, [{'envelope': {'sourceNumber': sam, 'timestamp': T + 9000, 'dataMessage': {'timestamp': T + 9000, 'message': 'Thanks!'}}},
                         {'envelope': {'sourceNumber': sam, 'timestamp': T + 9500, 'dataMessage': {'timestamp': T + 9500, 'attachments': [{'contentType': 'image/jpeg'}]}}}],
                 Pv(), T + 10000)
_, private = S.outputs(store, Pv(), {})
ok(private[0]['unread'] == 2 and not private[0]['last_from_me'], 'a real answer and a picture still count')
ok(all('text' not in m for m in store['chats']['p:' + sam]['messages']), 'private: no text kept')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
