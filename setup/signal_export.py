#!/usr/bin/env python3
"""Signal for Axella – through signal-cli running as a linked device on the Mac mini (receive only).

Set up once (docs/SETUP.md "Signal"): `brew install signal-cli qrencode`, then link the Mac mini from Signal on the
phone (Settings → Linked devices → QR code). The Mac mini then shows up there and can be removed any time. It only
sees messages from the moment it was linked.

Every 2 minutes this collects new messages (`signal-cli receive`) and keeps them here only:
  - attachments are never downloaded, Axella never sends a message or a read receipt, stories are ignored. Signal's
    own delivery receipts ("delivered") do go out when signal-cli receives a message – signal-cli can't turn those
    off; your phone sends the same receipt anyway
  - a linked device CAN send as you: signal-cli's keys (~/.local/share/signal-cli) are kept 0700 here and no Claude run
    may read that folder (scheduler APP_STORES). Removing the Mac mini under Linked devices on the phone is the off switch
  - Private contacts (setup/privacy.py; only the people you list – Signal is Normal by default like every app): the text is dropped before anything is
    written – only who, when and how many – and shows on the dashboard's Private card (state/private-inbox.json)
  - Hidden contacts: dropped completely
  - Normal contacts: state/signal.json, the same shape as whatsapp.json, which the digest runs read
  - disappearing messages are removed when Signal would remove them; everything older than 48 h goes too

Files (chmod 600, not in git): state/signal-store.json (the rolling 48 h store), state/signal.json, state/private-inbox.json
signal-cli keeps its own keys in ~/.local/share/signal-cli – never in this repo.
"""
import datetime
import glob
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), 'state')
STORE = os.path.join(STATE, 'signal-store.json')
KEYS_DIR = os.path.expanduser('~/.local/share/signal-cli')
OUT = os.path.join(STATE, 'signal.json')
WINDOW_HOURS = 48
MAX_MSGS = 25
MAX_TEXT = 1000
CANDIDATES = ['/opt/homebrew/bin/signal-cli', '/usr/local/bin/signal-cli']


def binary():
    for p in CANDIDATES + [shutil.which('signal-cli') or '']:
        if p and os.path.exists(p):
            return p
    return None


def _iso(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).astimezone().isoformat(timespec='seconds')


def _load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def account(cli):
    """The linked account's number (signal-cli listAccounts), or None when not linked yet."""
    try:
        r = subprocess.run([cli, '-o', 'json', 'listAccounts'], capture_output=True, text=True, timeout=60)
        acc = json.loads(r.stdout or '[]')
        if isinstance(acc, list) and acc:
            a = acc[0]
            return a.get('number') if isinstance(a, dict) else str(a)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def receive(cli, acc):
    """New envelopes since the last call (each linked device has its own queue on Signal's server)."""
    cmd = [cli, '-a', acc, '-o', 'json', 'receive', '-t', '5', '--ignore-attachments', '--ignore-stories']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0 and 'Unknown option' in (r.stderr or ''):          # older signal-cli: no --ignore-stories
        r = subprocess.run(cmd[:-1], capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or 'signal-cli failed').strip().splitlines()[-1][:300])
    out = []
    for ln in r.stdout.splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def groups(cli, acc):
    try:
        r = subprocess.run([cli, '-a', acc, '-o', 'json', 'listGroups'], capture_output=True, text=True, timeout=60)
        return {g.get('id'): g.get('name') for g in json.loads(r.stdout or '[]') if isinstance(g, dict)}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def _text(m):
    """The text of a real message, or None. Signal also sends data messages that carry no message at all – a profile
    key after you write to someone, a disappearing-messages timer change, "delete for everyone", group updates,
    reactions. Those are not a message from the other person and must not show up as "1 new"."""
    if m.get('reaction') or m.get('remoteDelete') or m.get('isExpirationUpdate'):
        return None
    t = (m.get('message') or '').strip()
    if not t and m.get('attachments'):
        t = '[attachment]'
    if not t and m.get('sticker'):
        t = '[sticker]'
    if not t and m.get('contacts'):
        t = '[contact]'
    if not t and m.get('payment'):
        t = '[payment]'
    return t[:MAX_TEXT] if t else None


def ingest(store, envelopes, pv, now_ms):
    """Add envelopes to the rolling store. Text is kept only for contacts whose Signal level is "normal"."""
    chats = store.setdefault('chats', {})
    for ev in envelopes:
        e = ev.get('envelope') or {}
        src = e.get('sourceNumber') or e.get('source') or e.get('sourceUuid')
        name = e.get('sourceName')
        dm, sm = e.get('dataMessage'), (e.get('syncMessage') or {})
        sent = sm.get('sentMessage')
        reads = sm.get('readMessages')
        if reads:                                     # you read them on the phone
            for rd in reads:
                for c in chats.values():
                    for m in c['messages']:
                        if not m['from_me'] and m['ts'] <= rd.get('timestamp', 0) and \
                                c['peer'] in (rd.get('sender'), rd.get('senderNumber'), rd.get('senderUuid')):
                            m['read'] = True
            continue
        msg, from_me = (sent, True) if sent else (dm, False)
        if not msg:
            continue
        text = _text(msg)
        if text is None:
            continue
        gid = (msg.get('groupInfo') or {}).get('groupId') or (msg.get('groupV2') or {}).get('id')
        peer = gid or (sent.get('destinationNumber') or sent.get('destination') or sent.get('destinationUuid') if sent else src)
        if not peer:
            continue
        key = ('g:' if gid else 'p:') + str(peer)
        lvl = pv.level('signal', peer)
        if lvl == 'hidden':
            chats.pop(key, None)
            continue
        c = chats.setdefault(key, {'key': key, 'peer': peer, 'group': bool(gid), 'name': None, 'messages': []})
        if not gid and not from_me and name:
            c['name'] = name
        ts = msg.get('timestamp') or e.get('timestamp') or now_ms
        exp = msg.get('expiresInSeconds') or 0
        m = {'ts': ts, 'from_me': from_me, 'read': from_me,
             'sender': None if from_me else (name or src), 'expires': ts + exp * 1000 if exp else None}
        if lvl == 'normal':
            m['text'] = text                          # private: never written
        c['messages'].append(m)
    # prune: 48 h window, disappearing messages, size
    cutoff = now_ms - WINDOW_HOURS * 3600 * 1000
    for k in list(chats):
        c = chats[k]
        c['messages'] = sorted([m for m in c['messages'] if m['ts'] >= cutoff and not (m.get('expires') and m['expires'] <= now_ms)],
                               key=lambda m: m['ts'])[-MAX_MSGS:]
        if not c['messages']:
            del chats[k]
    return store


def outputs(store, pv, group_names):
    """(signal.json data for the digest runs, private-inbox rows for the dashboard)."""
    normal, private = [], []
    for c in store.get('chats', {}).values():
        lvl = pv.level('signal', c['peer'])          # re-checked: a contact made private later disappears at once
        if lvl == 'hidden':
            continue
        msgs = c['messages']
        last = msgs[-1]
        who = pv.contact(c['peer'])
        name = (who or {}).get('name') or (group_names.get(c['peer']) if c['group'] else None) or c.get('name') or c['peer']
        if lvl == 'private':
            waiting = 0
            for m in reversed(msgs):
                if m['from_me']:
                    break
                waiting += 1
            private.append({'channel': 'signal', 'contact': who['id'] if who else None, 'name': name, 'group': c['group'],
                            'unread': sum(1 for m in msgs if not m['from_me'] and not m.get('read')), 'waiting': waiting,
                            'last_at': _iso(last['ts']), 'last_from_me': last['from_me'],
                            'open': 'sgnl://signal.me/#p/' + c['peer'] if not c['group'] and str(c['peer']).startswith('+') else 'sgnl://'})
            continue
        normal.append({'jid': c['peer'], 'phone': c['peer'] if str(c['peer']).startswith('+') else None, 'name': name,
                       'group': c['group'], 'unread': sum(1 for m in msgs if not m['from_me'] and not m.get('read')),
                       'last_at': _iso(last['ts']), 'last_from_me': last['from_me'],
                       'messages': [{'at': _iso(m['ts']), 'from_me': m['from_me'], 'sender': None if m['from_me'] else (m.get('sender') or name),
                                     'text': m.get('text') or '[message]'} for m in msgs if 'text' in m or m['from_me']]})
    normal.sort(key=lambda c: c['last_at'], reverse=True)
    return normal, private


def write():
    sys.path.insert(0, HERE)
    import privacy
    import whatsapp_export
    pv = privacy.Privacy(STATE)
    now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    if pv.broken():
        # privacy.json can't be read: nothing is received or written – messages wait on the Signal server
        return {'generated': now, 'ok': False, 'linked': None, 'chats': [],
                'error': 'privacy settings can\'t be read – nothing exported until they are fixed'}
    cli = binary()
    data = {'generated': now, 'ok': False, 'linked': False, 'account': None, 'window_hours': WINDOW_HOURS, 'chats': []}
    if not cli:
        data['error'] = 'signal-cli is not installed (brew install signal-cli) – see SETUP "Signal"'
        _write(OUT, data)
        return data
    store = _load(STORE, {})
    acc = store.get('account') or account(cli)
    if not acc:
        data['error'] = 'not linked yet – link the Mac mini from Signal on your phone (SETUP "Signal")'
        _write(OUT, data)
        return data
    store['account'] = acc
    try:
        env = receive(cli, acc)
        if time.time() - store.get('groups_at', 0) > 6 * 3600:
            store['group_names'], store['groups_at'] = groups(cli, acc), time.time()
        ingest(store, env, pv, int(time.time() * 1000))
        store['received_at'], store['error'] = now, None
        data.update(ok=True, linked=True, account='…' + acc[-2:])
    except Exception as e:                          # keep the last good store; show the problem in Settings
        store['error'] = str(e)[:300]
        data.update(linked=True, account='…' + acc[-2:], error=store['error'])
    _write(STORE, store)
    data['chats'], private = outputs(store, pv, store.get('group_names') or {})
    data['received_at'] = store.get('received_at')
    _write(OUT, data)
    whatsapp_export.write_private('signal', private, now)
    return data


def status():
    d = _load(OUT, {})
    return {k: d.get(k) for k in ('generated', 'ok', 'linked', 'account', 'error', 'received_at')} | \
        {'installed': bool(binary()), 'chats': len(d.get('chats') or [])}


def protect_keys():
    """signal-cli's folder holds the linked device's keys (unencrypted): only this user may open it."""
    try:
        if os.path.isdir(KEYS_DIR) and os.stat(KEYS_DIR).st_mode & 0o077:
            os.chmod(KEYS_DIR, 0o700)
    except OSError:
        pass


def run(log=sys.stderr, every=120):
    protect_keys()
    while True:
        try:
            d = write()
            if d.get('error') and d.get('linked'):
                log.write('%s signal: %s\n' % (d['generated'], d['error']))
        except Exception as e:
            log.write('signal: %s\n' % str(e)[:300])
        time.sleep(every)


if __name__ == '__main__':
    d = write()
    print('ok:', d['ok'], '| linked:', d['linked'], '| error:', d.get('error'), '| chats (normal):', len(d['chats']))
