"""Private contacts: per contact and per platform, how much Axella – and so Claude – may see.

  normal  – as today: read, summarised, drafts
  private – Axella knows that something arrived (who, which app, when, how many) but never the text. Nothing about
            the chat goes into the files Claude runs read; it appears only on the dashboard's Private card, filled by
            Python. (The owner's "personal VIP".)
  hidden  – ignored completely: not on the dashboard either

Enforced in Python before anything reaches a Claude run – never by asking Claude to skip something:
  - WhatsApp: whatsapp_export.py leaves private and hidden chats out of state/whatsapp.json; private chats go to
    state/private-inbox.json (counts and times only, no text).
  - Signal: signal_export.py drops private text before anything is written; private chats go to private-inbox.json.
  - Mail and iMessage: Claude runs reach them through setup/mcp_filter.py (in front of Macuse), which removes every
    result that involves a private/hidden contact; private_local.py fills the Private card from Mail's index and the
    Messages database without reading any text. App windows (computer_use_*) are off for runs while anything is private.
  - Calls: voice_sync.py writes no calls/<id>.json for a private caller (who and when go to private-inbox.json)
    and keeps nothing of a hidden one.
  - This file and private-inbox.json are on the scheduler's SECRETS list: no Claude run can read who is private.

state/privacy.json (chmod 600, not in git):
  {"defaults": {"mail": "normal", "imessage": "normal", "whatsapp": "normal", "signal": "normal", "calls": "normal"},
   "discreet": false, "discreet_push": false, "notify": true,   (discreet = no names on the dashboard; _push = in notifications)
   "contacts": [{"id", "name", "ids": ["+4500000000", "sam@example.com", "<group id>"], "levels": {"whatsapp": "private", …}}]}
A contact's level for a platform it has no entry for is that platform's default – frozen when the default changes, so
changing a default never moves someone already on the list.
"""
import json
import os
import re
import threading
import uuid

CHANNELS = ('mail', 'imessage', 'whatsapp', 'signal', 'calls')
LEVELS = ('normal', 'private', 'hidden')
ENFORCED = ('whatsapp', 'signal', 'mail', 'imessage', 'calls')            # where the setting already works (grows with steps 2 and 3)
DEFAULTS = {'mail': 'normal', 'imessage': 'normal', 'whatsapp': 'normal', 'signal': 'normal', 'calls': 'normal'}   # only listed people are private
MAX_CONTACTS = 200
LOCK = threading.Lock()


class Bad(Exception):
    pass


def _digits(s):
    return re.sub(r'\D', '', s or '')


def norm(ident):
    """A comparable form: e-mail lower-case; phone/WhatsApp id digits only (country code kept when given)."""
    s = str(ident or '').strip()
    if not s:
        return ''
    if '@' in s and not re.search(r'@(s\.whatsapp\.net|g\.us|lid)$', s, re.I):
        return s.lower()
    head = s.split('@')[0]
    if re.search(r'[A-Za-z]', head):          # a Signal group/user id: compared exactly, never by its digits
        return 'id:' + s if re.match(r'^[A-Za-z0-9+/=_-]{16,}$', s) else ''
    d = _digits(head)
    return d if len(d) >= 6 else ''


def same(a, b):
    """Two normalised ids match – phone numbers also when one is written without the country code."""
    if not a or not b:
        return False
    if a == b:
        return True
    if a.isdigit() and b.isdigit() and min(len(a), len(b)) >= 8:
        return a.endswith(b) or b.endswith(a)
    return False


def contact_level(c, channel, defaults):
    """A listed contact's level on one app: what is set for that app, else for all apps, else that app's default."""
    lv = (c or {}).get('levels') or {}
    for k in (channel, 'all'):
        if lv.get(k) in LEVELS:
            return lv[k]
    return (defaults or {}).get(channel, 'normal')


class Privacy:
    def __init__(self, state_dir):
        self.path = os.path.join(state_dir, 'privacy.json')
        self._cache = (0, None)

    def load(self):
        """The settings. A missing file is a first run: the defaults. A file that is there but can't be read (a typo
        from a hand edit, wrong owner after a restore, a disk error) is BROKEN: then everyone is private on every
        platform (`broken: True`, see strict()), never "nobody is private"."""
        try:
            m = os.path.getmtime(self.path)
        except FileNotFoundError:
            d, m = {}, 0
        except OSError:
            return self.strict()
        else:
            if self._cache[0] == m and self._cache[1]:
                return self._cache[1]
            try:
                with open(self.path, encoding='utf-8') as f:
                    d = json.load(f)
                if not isinstance(d, dict) or not isinstance(d.get('contacts', []), list) \
                        or not isinstance(d.get('defaults', {}), dict):
                    raise ValueError('not a privacy settings object')
            except FileNotFoundError:                    # removed between the two calls: a first run again
                d, m = {}, 0
            except (OSError, ValueError, UnicodeDecodeError):
                return self.strict()
        # a privacy.json from before Signal became Normal by default keeps Signal private until the owner changes it –
        # a new default in the code must never make anyone readable by itself
        legacy = {'signal': 'private'} if m and 'signal' not in (d.get('defaults') or {}) else {}
        d = {'defaults': {**DEFAULTS, **legacy, **{k: v for k, v in (d.get('defaults') or {}).items() if k in CHANNELS and v in LEVELS}},
             'discreet': bool(d.get('discreet')), 'notify': d.get('notify', True) is not False,
             # names in notifications (lock screen) – its own switch; until set it follows "discreet" as before
             'discreet_push': bool(d.get('discreet_push', d.get('discreet'))),
             'contacts': [c for c in d.get('contacts') or [] if isinstance(c, dict)]}
        d['broken'] = False
        self._cache = (m, d)
        return d

    @staticmethod
    def strict():
        """What every reader gets while privacy.json can't be read: all private, no contacts (so nobody is matched as
        Normal either), and the marker – the exporters then write nothing new and the dashboard shows the problem."""
        return {'defaults': {ch: 'private' for ch in CHANNELS}, 'discreet': True, 'notify': True, 'discreet_push': True,
                'contacts': [], 'broken': True}

    def broken(self):
        return bool(self.load().get('broken'))

    def _save(self, d):
        d = {k: v for k, v in d.items() if k != 'broken'}
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        self._cache = (0, None)

    def public(self):
        d = self.load()
        return {**d, 'channels': list(CHANNELS), 'levels': list(LEVELS), 'enforced': list(ENFORCED)}

    # ---------- the question every exporter asks ----------
    def contact(self, ident, name=None):
        n = norm(ident)
        for c in self.load()['contacts']:
            if any(same(n, norm(i)) for i in c.get('ids') or []):
                return c
        return None

    def level(self, channel, ident, name=None):
        d = self.load()
        c = self.contact(ident)
        if c:
            return contact_level(c, channel, d['defaults'])
        return d['defaults'].get(channel, 'normal')

    # ---------- settings ----------
    def set(self, p):
        with LOCK:
            d = self.load()
            if d.get('broken'):                          # saving now would replace the owner's list with "nobody"
                raise Bad('your privacy settings file (state/privacy.json) can\'t be read – fix or restore it first; '
                          'until then everyone is treated as private')
            if isinstance(p.get('defaults'), dict):
                for k, v in p['defaults'].items():
                    if k in CHANNELS and v in LEVELS and v != d['defaults'].get(k):
                        # people on the list keep what they had: a contact that followed the old default gets it
                        # written out, so "Signal: Normal by default" can't quietly make a private contact readable
                        for c in d['contacts']:
                            lv = c.setdefault('levels', {})
                            if k not in lv and 'all' not in lv:
                                lv[k] = d['defaults'].get(k, 'normal')
                        d['defaults'][k] = v
            if 'discreet' in p:
                d['discreet'] = bool(p['discreet'])
            if 'discreet_push' in p:
                d['discreet_push'] = bool(p['discreet_push'])
            if 'notify' in p:                           # a push when a private message arrives (never its text)
                d['notify'] = bool(p['notify'])
            if isinstance(p.get('contact'), dict):
                c = p['contact']
                name = str(c.get('name') or '').strip()[:80]
                ids = []
                for i in c.get('ids') or []:
                    i = str(i).strip()[:120]
                    if norm(i) and i not in ids:
                        ids.append(i)
                if not name or not ids:
                    raise Bad('a private contact needs a name and at least one phone number or e-mail address')
                levels = {k: v for k, v in (c.get('levels') or {}).items() if (k in CHANNELS or k == 'all') and v in LEVELS}
                row = {'id': str(c.get('id') or '') or uuid.uuid4().hex[:8], 'name': name, 'ids': ids[:10], 'levels': levels}
                if any(x['id'] == row['id'] for x in d['contacts']):
                    d['contacts'] = [row if x['id'] == row['id'] else x for x in d['contacts']]
                else:
                    if len(d['contacts']) >= MAX_CONTACTS:
                        raise Bad('too many private contacts')
                    d['contacts'].append(row)
            if p.get('remove'):
                d['contacts'] = [x for x in d['contacts'] if x['id'] != str(p['remove'])]
            self._save(d)
            return self.public()
