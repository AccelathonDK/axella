"""Newsletters & marketing: who sends bulk mail, how much, do you read it – and unsubscribe on your tap.

Deterministic, no AI needed: any mail carrying a List-Unsubscribe header is bulk mail. Every few hours the Mac mini
scans the folders in actions-config.json "newsletter_folders" (iCloud INBOX, Notifications, Archive …) and keeps
state/senders.json:
  {"senders": {<address>: {"address", "name", "domain", "ids": [...], "count", "unread", "first_at", "last_at",
               "subjects": [...], "unsub": {"https": url|null, "mailto": addr|null, "one_click": bool},
               "status": "active|unsubscribed|kept", "changed_at", "method", "after_unsub": n}},
   "last_scan": iso, "scanned_days": n}

Noise cleanup: quiet() is the monthly "never opened" suggestion; sender_hold sets Always hold (the digest pass in
safety.py keeps that sender's mail out of digests); senders_quiet_dismiss hides this month's suggestion.

Unsubscribe – only on the owner's tap, only via the headers (never links from the mail body):
  1. RFC 8058 one-click (List-Unsubscribe-Post) → the Mac mini POSTs "List-Unsubscribe=One-Click" to the https URL
  2. mailto → a DRAFT in Mail for the owner to send (Axella never sends it)
  3. https only → the dashboard opens the link for the owner
"""
import datetime
import ipaddress
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request

LOCK = threading.Lock()
US, RS = '\x1f', '\x1e'

SCAN_SCRIPT = '''
on run argv
  set accName to item 1 of argv
  set AppleScript's text item delimiters to "/"
  set parts to text items of (item 2 of argv)
  set AppleScript's text item delimiters to ""
  set cutoff to (current date) - ((item 3 of argv) as integer) * days
  set upto to (current date) - ((item 4 of argv) as integer) * days
  set US to (ASCII character 31)
  set RS to (ASCII character 30)
  set out to ""
  tell application "Mail"
    set mb to mailbox (item 1 of parts) of account accName
    if (count of parts) > 1 then
      repeat with i from 2 to (count of parts)
        set mb to mailbox (item i of parts) of mb
      end repeat
    end if
    repeat with m in (every message of mb whose date received > cutoff and date received is less than or equal to upto)
      set hdrs to ""
      try
        set hdrs to all headers of m
      end try
      if hdrs contains "List-Unsubscribe" or hdrs contains "list-unsubscribe" then
        set d to date received of m
        set dateStr to ((year of d) as text) & "-" & ((month of d as integer) as text) & "-" & ((day of d) as text) & " " & ((hours of d) as text) & ":" & ((minutes of d) as text)
        set readFlag to "0"
        if read status of m then set readFlag to "1"
        set out to out & (message id of m) & US & (sender of m) & US & (subject of m) & US & dateStr & US & readFlag & US & hdrs & RS
      end if
    end repeat
  end tell
  return out
end run
'''

DRAFT_SCRIPT = '''
on run argv
  tell application "Mail"
    set msg to make new outgoing message with properties {subject:(item 2 of argv), content:(item 3 of argv), visible:false}
    tell msg to make new to recipient at end of to recipients with properties {address:(item 1 of argv)}
    if (count of argv) > 3 and (item 4 of argv) is not "" then
      try
        set sender of msg to (item 1 of (email addresses of account (item 4 of argv)))
      end try
    end if
    save msg
  end tell
  return "draft saved"
end run
'''


def _hdr(raw, name):
    """Value of one header (unfolded) from Mail's 'all headers' text."""
    m = re.search(r'^' + re.escape(name) + r':[ \t]*(.*(?:\r?\n[ \t].*)*)', raw, re.I | re.M)
    return re.sub(r'\s*\r?\n[ \t]+', ' ', m.group(1)).strip() if m else ''


class Bad(Exception):
    pass


def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def parse_unsub(value, post):
    urls = re.findall(r'<([^>]+)>', value or '') or [u.strip() for u in (value or '').split(',') if u.strip()]
    https = next((u for u in urls if u.lower().startswith('https://')), None)
    mailto = next((u for u in urls if u.lower().startswith('mailto:')), None)
    return {'https': https, 'mailto': mailto, 'one_click': bool(https and 'one-click' in (post or '').lower())}


def _public_host(url):
    host = urllib.parse.urlparse(url).hostname or ''
    try:
        infos = socket.getaddrinfo(host, 443)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


class Subscriptions:
    def __init__(self, state_dir, osa):
        self.state_dir = state_dir
        self.file = os.path.join(state_dir, 'senders.json')
        self.osa = osa

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            d = {}
        d.setdefault('senders', {})
        return d

    def _save(self, d):
        tmp = self.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)

    def _status(self, state, msg):
        try:
            with open(os.path.join(self.state_dir, 'senders-status.json'), 'w', encoding='utf-8') as f:
                json.dump({'at': _now(), 'state': state, 'message': msg}, f)
        except OSError:
            pass

    # ---------- scan ----------
    def scan(self, folders, full_days=90, recent_days=3, chunk=2):
        """Scan each folder in 2-day windows (newest first), saving after each window so a slow Mail never loses
        the whole scan. A folder gets the full 90 days once (tracked per folder, so newly added mailboxes are
        back-filled), then only the last few days. One failing folder doesn't stop the others."""
        added, errors = 0, []
        for account, folder in folders:
            key = account + '/' + folder
            done = self.load().get('scanned', {}).get(key, 0)
            days = full_days if done < full_days else recent_days
            try:
                for start in range(0, days, chunk):
                    added += self._scan_window(account, folder, min(start + chunk, days), start)
            except Exception as e:
                errors.append('%s: %s' % (key, str(e)[:120]))
                continue
            with LOCK:
                d = self.load()
                d.setdefault('scanned', {})[key] = max(d.get('scanned', {}).get(key, 0), days)
                self._save(d)
        if errors:
            raise RuntimeError('; '.join(errors) + (' (%d new bulk mails from the other folders)' % added))
        return added

    def _scan_window(self, account, folder, older, newer):
        added = 0
        if True:
            out = self.osa(SCAN_SCRIPT, account, folder, str(older), str(newer), timeout=600)
            rows = [r.split(US) for r in out.split(RS) if r.strip()]
            with LOCK:
                d = self.load()
                for r in rows:
                    if len(r) < 6:
                        continue
                    mid, sender, subject, ds, rd = (x.strip() for x in r[:5])
                    lu, lp = _hdr(r[5], 'list-unsubscribe'), _hdr(r[5], 'list-unsubscribe-post')
                    if not lu:
                        continue
                    addr = ((re.search(r'<([^>]+)>', sender) or [None, sender])[1] or '').strip().lower()
                    if not addr or '@' not in addr:
                        continue
                    name = re.sub(r'\s*<[^>]+>\s*$', '', sender).strip().strip('"') or addr
                    try:
                        y, mo, rest = ds.split('-', 2); dd, hm = rest.split(' '); h, mi = hm.split(':')
                        at = f'{int(y):04d}-{int(mo):02d}-{int(dd):02d}T{int(h):02d}:{int(mi):02d}'
                    except ValueError:
                        at = None
                    s = d['senders'].setdefault(addr, {'address': addr, 'name': name, 'domain': addr.split('@')[1],
                                                       'ids': [], 'count': 0, 'unread': 0, 'first_at': at, 'last_at': at,
                                                       'subjects': [], 'status': 'active', 'after_unsub': 0})
                    if mid in s['ids']:
                        continue
                    s['ids'] = (s['ids'] + [mid])[-300:]
                    s['count'] += 1
                    s['unread'] += 0 if rd == '1' else 1
                    s['name'] = name or s['name']
                    if at:
                        s['first_at'] = min(filter(None, [s.get('first_at'), at]))
                        s['last_at'] = max(filter(None, [s.get('last_at'), at]))
                        if s['status'] == 'unsubscribed' and at > (s.get('changed_at') or '')[:16] and \
                                at > (datetime.datetime.fromisoformat(s['changed_at']) + datetime.timedelta(days=7)).strftime('%Y-%m-%dT%H:%M'):
                            s['after_unsub'] += 1             # still sending a week after unsubscribing
                    s['subjects'] = ([subject] + [x for x in s['subjects'] if x != subject])[:3]
                    s['unsub'] = parse_unsub(lu, lp)
                    s['latest_id'] = mid if not s.get('latest_at') or (at or '') >= s.get('latest_at', '') else s.get('latest_id')
                    s['latest_at'] = max(filter(None, [s.get('latest_at'), at])) if at else s.get('latest_at')
                    s['account'] = account
                    s['accounts'] = sorted(set(s.get('accounts', []) + [account]))
                    added += 1
                d['last_scan'] = _now()
                d['scanned_days'] = max(d.get('scanned_days', 0), older)
                self._save(d)
        return added

    def run(self, folders, log=sys.stderr, every=6 * 3600):
        while True:
            wait = every
            try:
                n = self.scan(folders)
                log.write(f'{_now()} subscriptions: {n} new bulk mails\n')
                self._status('ok', f'{n} new bulk mails')
            except Exception as e:
                log.write(f'subscriptions scan: {str(e)[:200]}\n')
                self._status('error', str(e)[:300])
                wait = 1800                              # Mail busy – try again in 30 min
            time.sleep(wait)

    # ---------- dashboard ----------
    # ---------- noise cleanup: "never opened" and Always hold ----------
    def held(self):
        """Addresses set to Always hold – the digest pass (safety.py) keeps their mail out of digests."""
        return {a for a, s in self.load()['senders'].items() if s.get('hold')}

    def quiet(self, protected=lambda dom: False, now=None, min_count=6, days=90):
        """The monthly suggestion: bulk senders you never opened – at least min_count mails in the last `days`, none read
        when Axella saw them – never for authorities, banks or insurers (protected(domain), the cleanup keep-list).
        {"month", "dismissed", "senders": [{"address", "name", "count", "since"}]}"""
        now = now or datetime.datetime.now()
        month = now.strftime('%Y-%m')
        cut = (now - datetime.timedelta(days=days)).strftime('%Y-%m-%dT%H:%M')
        d = self.load()
        out = []
        for a, s in d['senders'].items():
            if s.get('status') != 'active' or s.get('hold') or s.get('manual'):
                continue
            if (s.get('count') or 0) < min_count or s.get('unread') != s.get('count') or (s.get('last_at') or '') < cut:
                continue
            if protected(s.get('domain') or a.split('@')[-1]):
                continue
            out.append({'address': a, 'name': s.get('name') or a, 'count': s['count'], 'since': s.get('first_at')})
        out.sort(key=lambda x: -x['count'])
        return {'month': month, 'dismissed': d.get('quiet_dismissed') == month, 'senders': out[:20]}

    def action(self, action, p):
        with LOCK:
            d = self.load()
            if action == 'senders_quiet_dismiss':          # "not now" for this month's suggestion
                d['quiet_dismissed'] = datetime.datetime.now().strftime('%Y-%m')
                self._save(d)
                return 'saved'
            addr = str(p.get('address', '')).strip().lower()
            if action == 'sender_hold':
                if not re.fullmatch(r'[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+', addr) or len(addr) > 200:
                    raise Bad('which sender?')
                s = d['senders'].get(addr)
                if s is None:                                # not a bulk sender: remember just the hold
                    if not p.get('hold', True):
                        return 'saved'
                    s = d['senders'][addr] = {'address': addr, 'name': str(p.get('name') or addr)[:120],
                                              'domain': addr.split('@')[1], 'ids': [], 'count': 0, 'unread': 0,
                                              'subjects': [], 'status': 'active', 'after_unsub': 0, 'manual': True}
                s['hold'] = bool(p.get('hold', True))
                s['changed_at'] = _now()
                if not s['hold'] and s.get('manual'):
                    del d['senders'][addr]
                self._save(d)
                return {'message': 'Always held – this sender stays out of your digests' if s['hold'] else 'Back in your digests'}
            s = d['senders'].get(addr)
            if not s:
                raise Bad('unknown sender')
            if action == 'sender_keep':
                s['status'] = 'kept' if p.get('keep', True) else 'active'
                s['changed_at'] = _now()
                self._save(d)
                return 'saved'
            if action != 'sender_unsubscribe':
                raise Bad('unknown action')
            u = s.get('unsub') or {}
            if u.get('one_click') and u.get('https'):
                if not _public_host(u['https']):
                    raise Bad('unsubscribe URL points to a private address – not followed')
                req = urllib.request.Request(u['https'], data=b'List-Unsubscribe=One-Click', method='POST',
                                             headers={'Content-Type': 'application/x-www-form-urlencoded',
                                                      'User-Agent': 'Axella unsubscribe (RFC 8058)'})
                with urllib.request.urlopen(req, timeout=15) as r:
                    code = r.status
                if code >= 400:
                    raise Bad(f'sender answered HTTP {code}')
                s.update(status='unsubscribed', method='one-click', changed_at=_now(), after_unsub=0)
                self._save(d)
                return {'method': 'one-click', 'message': f"Unsubscribed from {s['name']}"}
            if u.get('mailto'):
                m = urllib.parse.urlparse(u['mailto'])
                q = urllib.parse.parse_qs(m.query)
                self.osa(DRAFT_SCRIPT, urllib.parse.unquote(m.path), (q.get('subject') or ['unsubscribe'])[0],
                         (q.get('body') or ['unsubscribe'])[0], s.get('account') or '', timeout=60)
                s.update(status='unsubscribed', method='mailto-draft', changed_at=_now(), after_unsub=0)
                self._save(d)
                return {'method': 'mailto', 'message': f"Unsubscribe mail for {s['name']} saved as a draft in Mail – send it from there"}
            if u.get('https'):
                s.update(status='unsubscribed', method='link', changed_at=_now(), after_unsub=0)
                self._save(d)
                return {'method': 'link', 'url': u['https'], 'message': 'Opening the unsubscribe page'}
            raise Bad('this sender has no unsubscribe option in its headers')
