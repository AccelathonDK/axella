#!/usr/bin/env python3
"""System status in one sentence (setup/health.py): the sentence and its order, "since" across checks and restarts,
the affects map, and the watchdog's view when Axella itself is down. Invented times only.
Run: python3 setup/tests/test_health.py"""
import datetime
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import health as H  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


NOW = datetime.datetime(2027, 3, 4, 14, 0).timestamp()
OK = [{'id': 'mail', 'name': 'Apple Mail', 'state': 'ok'}, {'id': 'whatsapp', 'name': 'WhatsApp', 'state': 'ok'},
      {'id': 'calls', 'name': 'Call agent', 'state': 'ok'}, {'id': 'web', 'name': 'Web server', 'state': 'ok'}]
s = H.sentence(OK, {}, {}, NOW)
ok(s['level'] == 'ok' and s['text'] == 'Everything works (checked 14:00).' and not s['problems'], 'all good: "Everything works." with the check time')

wa = [dict(r) for r in OK]
wa[1].update(state='down', detail="hasn't synced for 3 hours", fix='open WhatsApp on the Mac mini')
since = {'whatsapp': NOW - 3 * 3600 - 600}
s = H.sentence(wa, {}, since, NOW, next_digest='16:30')
ok(s['text'] == "WhatsApp – hasn't synced for 3 hours – open WhatsApp on the Mac mini." and s['level'] == 'down', 'one problem: named, with what to do')
p = s['problems'][0]
ok(p['since_text'] == 'Since 10:50 (3 h 10 min).', 'the analysis: since when')
ok(p['affects'] == 'The next digest (16:30) will miss WhatsApp. Urgent WhatsApp messages won\'t reach you.', '… and what it affects')
ok(s['short'] == 'WhatsApp needs you', 'the short sentence for the account menu')

many = [dict(r) for r in OK]
many[2].update(state='warn', detail='last sync 2 h ago')
many[1].update(state='down', detail='stopped')
many[3].update(state='warn', detail='runs in your login session')
s = H.sentence(many, {}, {}, NOW)
ok(s['text'] == '3 things need you – WhatsApp, the call agent and the web server.', 'several: counted and named')
ok([x['id'] for x in s['problems']] == ['whatsapp', 'calls', 'web'], 'worst first: down before warn, the next digest before the rest')
two = [dict(r) for r in OK]
two[2].update(state='warn')
two[0].update(state='warn')
ok([x['id'] for x in H.sentence(two, {}, {}, NOW)['problems']] == ['mail', 'calls'], 'among warnings, what affects the next digest first')
ok(H.sentence(two, {}, {}, NOW, off={'calls'})['text'].startswith('Apple Mail'), 'a part of a feature that is off is left out')

w = {'session': False, 'actions': True, 'since': datetime.datetime(2027, 3, 4, 13, 58).astimezone().isoformat()}
s = H.sentence(OK, w, {}, NOW)
ok(s['text'] == "Mail and messages are paused – you're not logged in on the Mac mini. Since 13:58." and s['level'] == 'down',
   'Axella itself down: from the watchdog')
ok(H.sentence(OK, {'session': True, 'actions': False}, {}, NOW)['text'].startswith("Mail and messages are paused – the Axella service isn't running"),
   '… the service not running')

st = tempfile.mkdtemp()
S = H.Since(st)
d = S.track(wa, NOW - 600)
ok(d == {'whatsapp': NOW - 600}, 'since: from the first bad check')
d = H.Since(st).track(wa, NOW)
ok(d == {'whatsapp': NOW - 600}, '… kept across checks and restarts')
d = S.track(OK, NOW + 60)
ok(d == {}, '… cleared when it works again')
ok(S.track(wa, NOW + 120) == {'whatsapp': NOW + 120}, '… and starts again from the next bad check')
ok(H.affects_text('web') == 'Nothing else is affected.' and 'Notifications' in H.affects_text('push'), 'the affects map')
ok(H._since_text(NOW - 2 * 86400, NOW).startswith('Since 2 Mar'), 'since an earlier day shows the date')

print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
