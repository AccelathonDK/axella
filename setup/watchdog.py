#!/usr/bin/env python3
"""Axella watchdog – runs as a LaunchDaemon (as the owner, UserName in the plist), so it keeps running when nobody is
logged in on the Mac mini, or when another macOS user has the screen.

Every minute it checks:
  session  – does the owner have a login session (their loginwindow process is running)? Mail, Messages, WhatsApp
             and the action service only run inside it.
  actions  – is the action service listening on its port (127.0.0.1:8788 by default)?
and writes state/watchdog.json:  {"at", "session", "actions", "ok", "since", "problem"}.
The web server (also a LaunchDaemon) shows that file as /axella/status.json, so the dashboard can say why it is
paused instead of failing silently.

When something has been down for two checks in a row it sends ONE Web Push to the owner's devices ("Axella is
paused – …"), and one more when everything is back. Web Push is plain HTTPS from Python (pywebpush, the keys in
state/vapid.json), so it needs no login session, no Mail and no extra service. No Claude, no message content.

Run: /usr/bin/python3 setup/watchdog.py        (--once: one check, print it, no push – for testing)
"""
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
STATE = os.path.join(BASE, 'state')
OUT = os.path.join(STATE, 'watchdog.json')
CONFIG = os.path.join(HERE, 'actions-config.json')
ACTIONS_PORT = int(os.environ.get('AXELLA_ACTIONS_PORT', '8788'))
EVERY = 60
CONFIRM = 2                 # checks in a row before a push – a restart of the service doesn't alert
SOURCE_ALERT = 3600         # a source (Mail, WhatsApp, Signal) unreadable this long → one push
STALE = 600                 # the WhatsApp / Signal exports refresh every 2 min: older than 10 min = stopped


def now_iso():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def has_session(uid=None, ps=None):
    """True if this user has a login session: macOS runs one loginwindow process per logged-in GUI session, as that
    user. (launchctl print gui/<uid> isn't usable from a daemon.)"""
    uid = os.getuid() if uid is None else uid
    try:
        out = ps if ps is not None else subprocess.run(['/bin/ps', '-axo', 'uid=,comm='], capture_output=True, text=True,
                                                       timeout=10).stdout
    except Exception:
        return None                                      # can't tell
    for line in out.splitlines():
        u, _, comm = line.strip().partition(' ')
        if u == str(uid) and comm.strip().endswith('/loginwindow'):
            return True
    return False


def port_open(port, host='127.0.0.1'):
    """The action service accepts TCP on its port (it then refuses anything that isn't Tailscale – connecting is all we
    need to know it's alive)."""
    s = socket.socket()
    s.settimeout(3)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def _age(iso):
    try:
        return time.time() - datetime.fromisoformat(str(iso).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError):
        return None


def sources(ps=None):
    """Can Axella read its sources? Only what is set up is checked; states and times only, never content.
    {name: problem or None}"""
    out = {}
    try:
        ps = ps if ps is not None else subprocess.run(['/bin/ps', '-axo', 'uid=,comm='], capture_output=True, text=True, timeout=10).stdout
        out['Mail'] = None if any(l.strip().endswith('/Mail') and l.strip().split(' ')[0] == str(os.getuid()) for l in ps.splitlines()) \
            else 'Apple Mail is not running on the Mac mini'
    except Exception:
        pass
    wa = load(os.path.join(STATE, 'whatsapp.json'), None)
    if wa is not None:
        a = _age(wa.get('generated'))
        out['WhatsApp'] = None if wa.get('ok') and a is not None and a < STALE else \
            ('WhatsApp can\'t be read' if not wa.get('ok') else 'WhatsApp hasn\'t been read for %d min' % ((a or 0) // 60))
    sg = load(os.path.join(STATE, 'signal.json'), None)
    if sg is not None and sg.get('linked'):
        a = _age(sg.get('generated'))
        out['Signal'] = None if not sg.get('error') and a is not None and a < STALE else \
            ('Signal can\'t be read' if sg.get('error') else 'Signal hasn\'t been read for %d min' % ((a or 0) // 60))
    return out


def check():
    session = has_session()
    actions = port_open(ACTIONS_PORT)
    if session is False:
        problem = "Mail and messages are paused – the owner isn't logged in on the Mac mini."
    elif not actions:
        problem = "Axella's service on the Mac mini isn't running."
    else:
        problem = None
    # sources only count while the session and the service run – otherwise the bigger problem says it all
    src = sources() if problem is None else {}
    return {'at': now_iso(), 'session': session, 'actions': actions, 'ok': problem is None, 'problem': problem, 'sources': src}


def write(st):
    os.makedirs(STATE, exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(st, f, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, OUT)


def push(title, body):
    """One Web Push to every subscribed device. Never drops a subscription (the action service owns that file)."""
    try:
        from pywebpush import webpush, WebPushException
        from py_vapid import Vapid
    except ImportError:
        sys.stderr.write('%s watchdog: pywebpush not installed – no push\n' % now_iso())
        return 0
    keys = load(os.path.join(STATE, 'vapid.json'), {})
    subs = load(os.path.join(STATE, 'push-subscriptions.json'), [])
    if not keys.get('private_pem') or not subs:
        return 0
    vapid = Vapid.from_pem(keys['private_pem'].encode())
    contact = load(CONFIG, {}).get('push_contact') or 'mailto:axella@example.com'
    sent = 0
    for sub in subs:
        try:
            webpush(subscription_info=sub['subscription'], data=json.dumps({'title': title, 'body': body, 'url': '/axella/',
                                                                            'tag': 'axella-watchdog'}),
                    vapid_private_key=vapid, vapid_claims={'sub': contact}, ttl=6 * 3600)
            sent += 1
        except WebPushException as e:
            sys.stderr.write('%s watchdog push failed (%s)\n' % (now_iso(), getattr(e.response, 'status_code', None)))
        except Exception as e:
            sys.stderr.write('%s watchdog push failed: %s\n' % (now_iso(), str(e)[:200]))
    return sent


def step(prev, st, send=push):
    """One round: carry "since" and the alert state over, and push on a confirmed change. Returns the new state."""
    st['bad_checks'] = 0 if st['ok'] else (prev.get('bad_checks', 0) + 1)
    st['alerted'] = prev.get('alerted', False)
    same = prev.get('ok') == st['ok'] and prev.get('problem') == st['problem']
    st['since'] = prev.get('since') if same and prev.get('since') else st['at']
    # each source: since when it is unreadable, one push after an hour, one when it is readable again
    old = prev.get('source_state') or {}
    now_s = {}
    for name, problem in (st.get('sources') or {}).items():
        o = old.get(name) or {}
        if problem:
            since = o.get('since') if o.get('problem') else st['at']
            alerted = o.get('alerted', False)
            if not alerted and (_age(since) or 0) >= SOURCE_ALERT:
                send('Axella can\'t read %s' % name, problem + ' since %s. Digests leave it out until it is fixed – see System status.' % since[11:16])
                alerted = True
            now_s[name] = {'problem': problem, 'since': since, 'alerted': alerted}
        else:
            if o.get('alerted'):
                send('Axella reads %s again' % name, '%s is back in your digests.' % name)
            now_s[name] = {'problem': None, 'since': None, 'alerted': False}
    for name, o in old.items():                       # not checked this round (service down): keep what we knew
        now_s.setdefault(name, o)
    st['source_state'] = now_s
    if not st['ok'] and st['bad_checks'] >= CONFIRM and not st['alerted']:
        send('Axella is paused', st['problem'] + ' The dashboard still opens; sending, filing and digests pause until it is back.')
        st['alerted'] = True
    elif st['ok'] and st['alerted']:
        send('Axella is back', 'Mail, messages and digests are running again on the Mac mini.')
        st['alerted'] = False
    return st


def main():
    if '--once' in sys.argv:
        print(json.dumps(check(), indent=1))
        return 0
    prev = load(OUT, {})
    while True:
        try:
            prev = step(prev, check())
            write(prev)
        except Exception as e:
            sys.stderr.write('%s watchdog: %s\n' % (now_iso(), str(e)[:200]))
        time.sleep(EVERY)


if __name__ == '__main__':
    sys.exit(main())
