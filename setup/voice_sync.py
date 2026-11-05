"""Axella call agent ↔ Mac mini (runs as a thread in the action service).

The call agent lives on Vercel (the axella-voice repo). Nothing on the Mac mini is reachable from outside:
this module only makes outgoing HTTPS requests.

  every 60 s  GET  <voice url>/api/calls   → each finished call is saved as calls/<id>.json (the dashboard's Calls
                                            card reads that folder), pushed to the iPhone, then DELETEd on Vercel
  every 6 h   POST <voice url>/api/config  → greetings + contacts so known callers are recognised and VIPs are
                                            marked; read-only from Contacts + contacts.md. With state/voice-lookup-key
                                            only HMAC(number) + first name + tier leave the Mac (no full names/numbers).
  calls older than 30 days are removed from calls/.

Settings: actions-config.json "voice": {"url": "https://<project>.vercel.app", "quiet_hours": [22, 7]} and
          "owner": {"name": …}
Secrets:  state/voice-token (= AXELLA_SYNC_TOKEN in Vercel) and state/voice-lookup-key (= VOICE_LOOKUP_KEY in Vercel),
          both chmod 600, never in git.
Status:   state/voice-status.json (last sync, last error, contacts sent) – shown in the dashboard later.

Private contacts (Settings → Private contacts, platform "Calls"), enforced here before anything is written – the digest
runs read calls/, so a call that isn't written there never reaches Claude:
  private – no calls/<id>.json: only who and when go to state/private-calls.json and the dashboard's Private card
            (state/private-inbox.json, part "calls"); the summary and transcript are dropped on arrival.
  hidden  – not kept at all, no push; hidden contacts are not sent to the call agent either.
  A saved call from someone made private later is moved out of calls/ into state/private-calls/ (never deleted).
"""
import datetime
import glob
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.request

CONTACTS_SCRIPT = '''
on run
  set US to (ASCII character 31)
  set RS to (ASCII character 30)
  set out to ""
  tell application "Contacts"
    repeat with p in people
      set nm to name of p
      repeat with ph in phones of p
        set out to out & nm & US & (value of ph) & RS
      end repeat
    end repeat
  end tell
  return out
end run
'''


def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


MAX_RESPONSE = 5 * 1024 * 1024
PRIOS = ('p0', 'p1', 'p2', 'p3')
_LINK = re.compile(r'!?\[([^\]]*)\]\([^)]*\)')
_TAG = re.compile(r'<[^>]*>')
_CTRL = re.compile(r'[\x00-\x08\x0b-\x1f\x7f]')


def _text(v, n):
    """Plain text from a call record field: no markdown links/images, no tags, no control characters, capped."""
    if not isinstance(v, str):
        return None
    v = re.sub(r'\s+', ' ', _CTRL.sub(' ', _TAG.sub('', _LINK.sub(r'\1', v)))).strip()
    return v[:n] or None


def _e164(num):
    """'+' + digits when the number has a country code, else None (same rule as the call agent)."""
    d = re.sub(r'\D', '', num or '')
    return '+' + d if (num or '').strip().startswith('+') and len(d) >= 6 else None


def normalise_number(raw):
    """Any way a number may be written – +45 12 34 56 78, 004512345678, 12345678 (Danish, no country code) – as
    '+' + digits; the same rules as the contacts sent to the call agent. None for an empty or withheld number."""
    num = re.sub(r'[^\d+]', '', str(raw or ''))
    if len(num) == 8 and num.isdigit():                 # a Danish number without +45 (checked first: 00 00 00 01 too)
        num = '+45' + num
    elif num.startswith('00'):
        num = '+' + num[2:]
    return _e164(num)


def coerce_call(c):
    """A call record from Vercel, reduced to known fields with the right types. The record is caller-influenced."""
    if not isinstance(c, dict):
        return None
    f = c.get('from') if isinstance(c.get('from'), dict) else {}
    cb = c.get('callback') if isinstance(c.get('callback'), dict) else None
    pr = str(c.get('priority') or '').lower()
    tr = [{'who': 'Caller' if t.get('who') == 'Caller' else 'Axella', 'text': (t.get('text') if isinstance(t.get('text'), str) else '')[:2000]}
          for t in (c.get('transcript') if isinstance(c.get('transcript'), list) else [])[:200] if isinstance(t, dict)]
    dur = c.get('duration_s')
    return {
        'id': str(c.get('id') or ''),
        'started': _text(c.get('started'), 40),
        'duration_s': int(dur) if isinstance(dur, (int, float)) and 0 <= dur < 86400 else None,
        'from': {'name': _text(f.get('name'), 80), 'said_name': _text(f.get('said_name'), 80),
                 'caller_id_match': bool(f.get('caller_id_match', bool(f.get('name')))),
                 'number': _text(f.get('number'), 30), 'tier': 'VIP' if f.get('tier') == 'VIP' else (_text(f.get('tier'), 10))},
        'context': _text(c.get('context'), 80),
        'priority': pr if pr in PRIOS else 'p2',
        'urgent_claimed': bool(c.get('urgent_claimed')), 'urgent_capped': bool(c.get('urgent_capped')),
        'summary': _text(c.get('summary'), 300) or '',
        'callback': ({'by': _text(cb.get('by'), 80), 'number': _text(cb.get('number'), 30), 'other_number': bool(cb.get('other_number'))}
                     if cb else None),
        'sms_draft': _text(c.get('sms_draft'), 320),
        'lang': c.get('lang') if c.get('lang') in ('da-DK', 'en-US') else None,
        'transcript': tr,
    }


def no_message(c):
    """Hung up / said nothing: nothing to act on."""
    return c['priority'] == 'p3' and not any(t['who'] == 'Caller' for t in c['transcript'])


def in_quiet_hours(hours, now=None):
    try:
        start, end = int(hours[0]), int(hours[1])
    except (TypeError, ValueError, IndexError):
        return False
    h = (now or datetime.datetime.now()).hour
    return (start <= h or h < end) if start > end else (start <= h < end)


class VoiceSync:
    def __init__(self, base, state_dir, config, osa, push, log=sys.stderr, away=None, privacy=None):
        self.base, self.state_dir, self.config, self.osa, self.push, self.log = base, state_dir, config, osa, push, log
        self.privacy = privacy                   # privacy.Privacy – who is private or hidden for calls (None: nobody)
        self.away = away or (lambda: None)        # out of office: {'greeting_da', 'greeting_en'} while away, else None
        self.calls_dir = os.path.join(base, 'calls')
        self.status_file = os.path.join(state_dir, 'voice-status.json')
        self.names = {}                          # E.164 → full contact name, from the last contacts read (memory only)
        os.makedirs(self.calls_dir, exist_ok=True)

    # ---------- helpers ----------
    def _secret(self, name):
        try:
            with open(os.path.join(self.state_dir, name), encoding='utf-8') as f:
                return f.read().strip()
        except OSError:
            return ''

    def _settings(self):
        v = self.config().get('voice') or {}
        url = (v.get('url') or '').rstrip('/')
        if url and not url.startswith('https://'):
            raise ValueError('voice.url must start with https:// – the sync token is never sent over plain HTTP')
        return url, self._secret('voice-token'), v

    def _req(self, method, url, token, body=None, timeout=20):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(url, data=data, method=method, headers={
            'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'User-Agent': 'axella-home-server'})
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ValueError('call agent response too large')
            return json.loads(raw.decode() or '{}')

    def _status(self, **kw):
        try:
            with open(self.status_file, encoding='utf-8') as f:
                st = json.load(f)
        except (OSError, ValueError):
            st = {}
        st.update(kw)
        with open(self.status_file, 'w', encoding='utf-8') as f:
            json.dump(st, f, indent=1)

    # ---------- calls ----------
    def fetch_once(self):
        url, token, _ = self._settings()
        if not url or len(token) < 32:
            return 0
        res = self._req('GET', url + '/api/calls', token)
        n = 0
        for raw in (res.get('calls') if isinstance(res.get('calls'), list) else []):
            c = coerce_call(raw)
            if not c:
                continue
            cid = re.sub(r'[^A-Za-z0-9_-]', '', c['id'])[:80]
            if not cid.startswith('call-'):
                continue
            c['id'] = cid
            # the call agent only knows first names: put the contact's full name back from the local list
            e = normalise_number(c['from']['number'])
            if c['from']['caller_id_match'] and e in self.names:
                c['from']['name'] = self.names[e]
            lvl = self._level(c)
            if lvl != 'normal':
                if lvl == 'private':
                    self._private_call(c)
                self._req('DELETE', url + '/api/calls?id=' + urllib.request.quote(cid), token)
                continue                                 # nothing of it in calls/ – the digest runs read that folder
            path = os.path.join(self.calls_dir, cid + '.json')
            if not os.path.exists(path):
                tmp = path + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(c, f, ensure_ascii=False, indent=1)
                os.chmod(tmp, 0o600)
                os.replace(tmp, path)
                n += 1
                self._push_call(cid, c)
            self._req('DELETE', url + '/api/calls?id=' + urllib.request.quote(cid), token)
        self._status(last_sync=_now(), last_error=None, **({'last_call': _now()} if n else {}))
        return n

    # ---------- private contacts ----------
    def _level(self, c):
        if not self.privacy:
            return 'normal'
        try:
            if self.privacy.broken():                    # privacy.json can't be read: every call is private
                return 'private'
        except Exception:
            return 'private'
        raw = (c.get('from') or {}).get('number')
        num = normalise_number(raw)
        digits = re.sub(r'\D', '', str(raw or ''))
        if not num and len(digits) < 6:
            return 'normal'                              # empty or withheld: nobody to match
        try:
            # through privacy.norm/same, which also match a contact saved without the country code; a number we
            # couldn't normalise is still compared by its digits
            return self.privacy.level('calls', num or digits)
        except Exception as e:                           # unreadable privacy file: treat the call as private, not normal
            self.log.write('%s voice privacy: %s\n' % (_now(), str(e)[:200]))
            return 'private'

    def _private_call(self, c):
        """Who and when only, for the Private card – the summary, transcript and call-back details are dropped."""
        path = os.path.join(self.state_dir, 'private-calls.json')
        try:
            with open(path, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        num = normalise_number(c['from']['number']) or re.sub(r'\D', '', str(c['from'].get('number') or ''))
        who = self.privacy.contact(num) if self.privacy else None
        key = (who or {}).get('id') or num
        at = c.get('started') or _now()
        r = d.get(key) or {'channel': 'calls', 'contact': (who or {}).get('id'), 'name': (who or {}).get('name') or num,
                           'group': False, 'calls': []}
        r['calls'] = sorted(set((r.get('calls') or []) + [at]))[-50:]
        r['name'] = (who or {}).get('name') or r.get('name') or num
        d[key] = r
        self._write_private(d, path)

    def _write_private(self, d, path=None):
        path = path or os.path.join(self.state_dir, 'private-calls.json')
        cutoff = (datetime.datetime.now().astimezone() - datetime.timedelta(days=7)).isoformat(timespec='seconds')
        for k in list(d):                                # a week of who-called, no longer
            d[k]['calls'] = [t for t in d[k].get('calls') or [] if t >= cutoff]
            if not d[k]['calls']:
                del d[k]
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        since = (datetime.datetime.now().astimezone() - datetime.timedelta(hours=48)).isoformat(timespec='seconds')
        rows = []
        for r in d.values():
            recent = [t for t in r['calls'] if t >= since]
            rows.append({'channel': 'calls', 'contact': r.get('contact'), 'name': r.get('name'), 'group': False,
                         'unread': len(recent), 'waiting': len(recent), 'last_at': max(r['calls']), 'last_from_me': False,
                         'open': None})
        rows.sort(key=lambda r: r['last_at'], reverse=True)
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import whatsapp_export                       # the shared, locked writer of private-inbox.json
            whatsapp_export.write_private('calls', rows, _now())
        except Exception as e:
            self.log.write('%s voice private inbox: %s\n' % (_now(), str(e)[:200]))

    def scrub(self):
        """A saved call from a caller who is now private or hidden leaves calls/ (moved to state/private-calls/, which no
        run can read – never deleted); a private one is listed on the Private card."""
        if not self.privacy:
            return 0
        n = 0
        for p in glob.glob(os.path.join(self.calls_dir, 'call-*.json')):
            try:
                with open(p, encoding='utf-8') as f:
                    c = json.load(f)
            except (OSError, ValueError):
                continue
            lvl = self._level(c)
            if lvl == 'normal':
                continue
            dest = os.path.join(self.state_dir, 'private-calls')
            os.makedirs(dest, mode=0o700, exist_ok=True)
            os.chmod(dest, 0o700)                        # also when the folder already existed with another mode
            os.replace(p, os.path.join(dest, os.path.basename(p)))
            if lvl == 'private' and isinstance(c.get('from'), dict):
                self._private_call(c)
            n += 1
        return n

    @staticmethod
    def push_text(c):
        """Title + body for the push. Caller ID is unverified: say "matches", never present it as the contact."""
        f = c['from']
        said, contact, number = f.get('said_name'), f.get('name') if f.get('caller_id_match') else None, f.get('number')
        who = said or number or 'unknown caller'
        if contact and (not said or said.split()[0].lower() != contact.split()[0].lower()):
            who += ' (caller ID matches %s)' % contact
        elif contact and said:
            who = contact
        pr = c['priority']
        title = ('⚠ Axella – caller says urgent: ' if pr == 'p0' else '📞 Axella – call: ') + who
        body = re.sub(r'\*\*', '', c['summary'] or 'Message taken – see the dashboard.')
        if (c.get('callback') or {}).get('other_number'):
            body = 'Asks for a call back on another number. ' + body
        return title, body[:180]

    def _push_call(self, cid, c):
        try:
            if no_message(c):
                return                                   # hung up / silent: shown in the Calls card, no push
            v = self.config().get('voice') or {}
            vip = c['from'].get('tier') == 'VIP' and c['from'].get('caller_id_match')
            if c['priority'] in ('p2', 'p3') and not vip and in_quiet_hours(v.get('quiet_hours', [22, 7])):
                return                                   # night: the morning digest and the card have it
            title, body = self.push_text(c)
            self.push({'title': title, 'body': body, 'url': '/axella/', 'tag': 'axella-call-' + cid})
        except Exception as e:
            self.log.write('%s voice push: %s\n' % (_now(), str(e)[:200]))

    def _write_card_config(self, v):
        """calls/config.json – what the dashboard's Call agent card shows. Only facts: no switches that do nothing."""
        try:
            with open(self.status_file, encoding='utf-8') as f:
                st = json.load(f)
        except (OSError, ValueError):
            st = {}
        away = bool(self.away())
        cfg = {'demo': False, 'mode': 'message', 'mode_label': 'taking messages' + (' · away greeting' if away else ''),
               'retention_days': 30, 'away': away,
               'number': v.get('number'),
               'greeting_da': st.get('greeting_da') or v.get('greeting_da'),
               'greeting_en': st.get('greeting_en') or v.get('greeting_en'),
               'last_sync': st.get('last_sync'), 'last_call': st.get('last_call'),
               'contacts': st.get('contacts_sent'), 'vips': st.get('vips'), 'config_pushed': st.get('config_pushed'),
               'lookup': st.get('lookup'),
               'last_error': st.get('last_error'), 'last_error_at': st.get('last_error_at') if st.get('last_error') else None}
        path = os.path.join(self.calls_dir, 'config.json')
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({k: x for k, x in cfg.items() if x is not None}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    def prune(self, days=30):
        cutoff = time.time() - days * 86400
        for p in glob.glob(os.path.join(self.calls_dir, 'call-*.json')):
            try:
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except OSError:
                pass

    # ---------- config / contacts ----------
    def _vips(self):
        """VIPs from contacts.md: (names, numbers). A VIP line with a phone number (+45 00 00 00 00) is matched on that
        number only; a line without one is matched on the name (so two Contacts people with that name are both VIP)."""
        names, numbers, in_vip = set(), set(), False
        try:
            with open(os.path.join(self.base, 'contacts.md'), encoding='utf-8') as f:
                for line in f:
                    if line.startswith('## '):
                        in_vip = line.lower().startswith('## vip')
                    elif in_vip and line.startswith('- '):
                        nums = [_e164(m.group(0)) for m in re.finditer(r'\+\d[\d ]{6,18}\d', line)]
                        nums = [x for x in nums if x]
                        if nums:
                            numbers.update(nums)
                            continue
                        nm = re.split(r'\s+[(–-]\s*|\s+\(', line[2:].strip())[0].strip()
                        if nm:
                            names.add(nm.lower())
        except OSError:
            pass
        return names, numbers

    def push_config(self):
        url, token, v = self._settings()
        if not url or len(token) < 32:
            return None
        vip_names, vip_numbers = self._vips()
        key = self._secret('voice-lookup-key')
        hashed = len(key) >= 32
        if not hashed and self._any_private_caller():
            # plain mode sends full names and numbers to Vercel – never with anyone Private or Hidden for calls
            self.log.write('%s voice contacts: not pushed – plain mode (no state/voice-lookup-key) while someone is '
                           'private or hidden for calls\n' % _now())
            self._status(lookup='refused-plain-private', config_error='Set up state/voice-lookup-key (SETUP §15): '
                         'without it full names and numbers would go to the call agent, private contacts included')
            return None
        contacts, seen, names = [], set(), {}
        try:
            out = self.osa(CONTACTS_SCRIPT, timeout=180)
            for row in out.split('\x1e'):
                parts = row.split('\x1f')
                if len(parts) < 2:
                    continue
                name, e = parts[0].strip(), normalise_number(parts[1])   # 00…, Danish 8 digits without +45
                if not name or not e or e in seen:      # no country code: can't match a caller ID exactly
                    continue
                seen.add(e)
                if self._level({'from': {'number': e}}) == 'hidden':
                    continue                             # hidden: the call agent doesn't learn the name either
                names[e] = name
                tier = 'VIP' if e in vip_numbers or name.lower() in vip_names else 'Known'
                contacts.append(self._contact_entry(key if hashed else None, e, name, tier))
            # private callers who aren't in Contacts: the call agent must still know not to use AI with them
            for e, name in self._private_callers():
                if e not in seen:
                    seen.add(e)
                    contacts.append(self._contact_entry(key if hashed else None, e, name, 'Known'))
        except Exception as e:
            self.log.write('%s voice contacts: %s\n' % (_now(), str(e)[:200]))
            return None                                  # don't overwrite a good list with an empty one
        if not contacts:
            self.log.write('%s voice contacts: Contacts returned no numbers – not pushed\n' % _now())
            return None                                  # e.g. Contacts access revoked: keep the list on Vercel
        import axprofile as profile
        me = profile.owner(self.config())
        body = {'owner': me['name'], 'sign_off': me['sign_off'], 'contacts': contacts}
        greet = self._greetings(v)
        for k in ('greeting_da', 'greeting_en'):
            if greet.get(k):
                body[k] = greet[k]
        res = self._req('POST', url + '/api/config', token, body, timeout=30)
        self.names = names
        self._status(contacts_sent=res.get('contacts'), vips=sum(1 for c in contacts if c['tier'] == 'VIP'),
                     private=sum(1 for c in contacts if c.get('private')), config_error=None,
                     config_pushed=_now(),
                     lookup=('hashed' if res.get('lookup_key') else 'key-missing-on-vercel') if hashed else 'plain',
                     **{k: res[k] for k in ('greeting_da', 'greeting_en') if res.get(k)})
        return res

    def _contact_entry(self, key, e, name, tier):
        """One contact for the call agent. Private for calls → "private": true – the agent answers with a fixed
        recorded message, no AI, no transcript and no summary (axella-voice)."""
        c = ({'h': hmac.new(key.encode(), e.encode(), hashlib.sha256).hexdigest(), 'first': name.split()[0][:40], 'tier': tier}
             if key else {'name': name, 'number': e, 'tier': tier})
        if self._level({'from': {'number': e}}) == 'private':
            c['private'] = True
        return c

    def _any_private_caller(self):
        if not self.privacy:
            return False
        import privacy as _p
        d = self.privacy.load()
        if d.get('broken') or d['defaults'].get('calls', 'normal') != 'normal':
            return True
        return any(_p.contact_level(c, 'calls', d['defaults']) != 'normal' for c in d['contacts'])

    def _private_callers(self):
        """(number, name) of everyone on the privacy list who is Private for calls."""
        if not self.privacy:
            return []
        import privacy as _p
        d = self.privacy.load()
        out = []
        for c in d['contacts']:
            if _p.contact_level(c, 'calls', d['defaults']) != 'private':
                continue
            for i in c.get('ids') or []:
                e = normalise_number(i) if '@' not in str(i) else None
                if e:
                    out.append((e, str(c.get('name') or 'Private')[:80]))
        return out

    def _greetings(self, v=None):
        v = v if v is not None else self._settings()[2]
        away = self.away() or {}
        return {k: away.get(k) or v.get(k) for k in ('greeting_da', 'greeting_en')}

    # ---------- thread ----------
    def run(self, every=60, config_every=6 * 3600):
        last_cfg, last_greet = 0, None
        while True:
            try:
                _, _, v = self._settings()
                if v:
                    self._write_card_config(v)
                greet = json.dumps(self._greetings(v), sort_keys=True)
                # every 6 h, and at once when the greeting changes (out of office starts/ends or is edited)
                if time.time() - last_cfg > config_every or greet != last_greet:
                    if self.push_config() is not None:
                        last_cfg, last_greet = time.time(), greet
                if self.scrub():
                    self.log.write('%s voice: call(s) of private/hidden callers moved out of calls/\n' % _now())
                n = self.fetch_once()
                if n:
                    self.log.write('%s voice: %d new call(s)\n' % (_now(), n))
                self.prune()
            except Exception as e:
                self.log.write('%s voice sync: %s\n' % (_now(), str(e)[:200]))
                try:
                    self._status(last_error=str(e)[:300], last_error_at=_now())
                except OSError:
                    pass
            time.sleep(every)
