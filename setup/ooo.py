"""Out of office (state/ooo.json) – one place for the away period, the texts and the call agent's away greeting.

Mail servers keep their own auto-replies, and none of them can be switched from the Mac mini: iCloud's auto-reply
lives only in iCloud.com settings, Exchange automatic replies only in Mail's/Outlook's account settings (or Microsoft
Graph, which needs the employer's IT). So Axella keeps the dates and one text per mailbox (work mailboxes: one for
colleagues and one for outsiders), hands the owner the text + the right settings page, and remembers what was marked
as set. The servers then send the replies themselves.

What Axella does by itself:
  - the call agent uses the away greeting while the period is active (voice_sync picks it up within a minute)
  - push the evening before the start if a mailbox isn't marked as set, and the morning after the end as a reminder
    to check that the replies are off (only for mailboxes marked as set)
Shape (mailboxes = the accounts in actions-config.json):
  {"from": "YYYY-MM-DD"|null, "until": "YYYY-MM-DD"|null,
   "mailboxes": {"<account>": {"text": str, "internal": str, "external": str, "applied": iso|null}},
   "voice": {"on": bool, "da": str, "en": str},
   "reminded": {"<key>": iso}}
"""
import datetime
import json
import os
import re
import sys
import threading
import time

LOCK = threading.Lock()
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
DEFAULT = {'from': None, 'until': None, 'mailboxes': {}, 'voice': {'on': True, 'da': '', 'en': ''}, 'reminded': {}}
BOX = {'text': '', 'internal': '', 'external': '', 'applied': None}


class Bad(Exception):
    pass


def _iso():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


class OutOfOffice:
    def __init__(self, state_dir, push, log=sys.stderr, config=None):
        self.file = os.path.join(state_dir, 'ooo.json')
        self.push, self.log = push, log
        self.config = config or (lambda: None)

    def _accounts(self):
        import axprofile
        return axprofile.accounts(self.config())

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        out = json.loads(json.dumps(DEFAULT))
        for k in ('from', 'until'):
            out[k] = d.get(k)
        out['voice'].update({x: v for x, v in (d.get('voice') or {}).items() if x in DEFAULT['voice']})
        out['reminded'] = d.get('reminded') or {}
        boxes = d.get('mailboxes') or {}
        for a in self._accounts():                         # one entry per configured mailbox
            out['mailboxes'][a['id']] = {**BOX, **{k: v for k, v in (boxes.get(a['id']) or {}).items() if k in BOX}}
        return out

    def _save(self, d):
        tmp = self.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.file)

    def active(self, today=None):
        d = self.load()
        t = (today or datetime.date.today()).isoformat()
        return bool(d['from'] and d['until'] and d['from'] <= t <= d['until'])

    def voice_greetings(self):
        """Away greetings for the call agent while the period is active, else None (normal greetings)."""
        d = self.load()
        if not self.active() or not d['voice']['on'] or not (d['voice']['da'] or d['voice']['en']):
            return None
        return {'greeting_da': d['voice']['da'] or None, 'greeting_en': d['voice']['en'] or None}

    def status(self):
        d = self.load()
        accs = self._accounts()
        return {**{k: v for k, v in d.items() if k != 'reminded'}, 'active': self.active(),
                'accounts': [{k: a[k] for k in ('id', 'label', 'kind', 'workplace')} for a in accs]}

    def action(self, action, p):
        with LOCK:
            d = self.load()
            if action == 'ooo_set':
                for k in ('from', 'until'):
                    if k in p:
                        v = p[k] or None
                        if v and not DATE.match(str(v)):
                            raise Bad('dates must be YYYY-MM-DD')
                        if d[k] != v:
                            d['reminded'] = {}               # new period: reminders start over
                            for b in d['mailboxes'].values():
                                b['applied'] = None
                        d[k] = v
                if d['from'] and d['until'] and d['until'] < d['from']:
                    raise Bad('the period ends before it starts')
                for acc, box in (p.get('mailboxes') or {}).items():
                    if acc in d['mailboxes'] and isinstance(box, dict):
                        for k in ('text', 'internal', 'external'):
                            if k in box:
                                d['mailboxes'][acc][k] = str(box[k] or '')[:4000]
                for k, v in (p.get('voice') or {}).items():
                    if k == 'on':
                        d['voice']['on'] = bool(v)
                    elif k in ('da', 'en'):
                        d['voice'][k] = str(v or '')[:500]
            elif action == 'ooo_applied':
                acc = p.get('account')
                if acc not in d['mailboxes']:
                    raise Bad('unknown mailbox')
                d['mailboxes'][acc]['applied'] = _iso() if p.get('set', True) else None
            elif action == 'ooo_clear':
                keep = {a: {**BOX, **{k: b[k] for k in ('text', 'internal', 'external')}} for a, b in d['mailboxes'].items()}
                d = json.loads(json.dumps(DEFAULT)) | {'mailboxes': keep, 'voice': d['voice']}
            else:
                raise Bad('unknown action')
            self._save(d)
        return self.status()

    # ---------- reminders ----------
    def _remind(self, key, title, body):
        with LOCK:
            d = self.load()
            if d['reminded'].get(key):
                return
            d['reminded'][key] = _iso()
            self._save(d)
        try:
            self.push({'title': title, 'body': body, 'url': '/axella/?v=settings#sec-ooo', 'tag': 'axella-ooo'})
        except Exception as e:
            self.log.write('%s ooo push: %s\n' % (_iso(), str(e)[:200]))

    def tick(self, now=None):
        now = now or datetime.datetime.now()
        d = self.load()
        if not d['from'] or not d['until']:
            return
        start = datetime.date.fromisoformat(d['from'])
        end = datetime.date.fromisoformat(d['until'])
        labels = {a['id']: a['label'] for a in self._accounts()}
        missing = [labels.get(k, k) for k, b in d['mailboxes'].items() if not b['applied']]
        if missing and (start - datetime.timedelta(days=1) == now.date() and now.hour >= 18 or start == now.date() and now.hour >= 7):
            self._remind('start:' + d['from'], 'Axella – out of office starts %s' % start.strftime('%a %-d %b'),
                         'Not marked as set yet: %s. Open Settings → Out of office to copy the text.' % ', '.join(missing))
        done = [labels.get(k, k) for k, b in d['mailboxes'].items() if b['applied']]
        if done and now.date() == end + datetime.timedelta(days=1) and now.hour >= 8:
            self._remind('end:' + d['until'], 'Axella – welcome back',
                         'Check that the out-of-office replies are off: %s.' % ', '.join(done))

    def run(self, every=300):
        while True:
            try:
                self.tick()
            except Exception as e:
                self.log.write('%s ooo: %s\n' % (_iso(), str(e)[:200]))
            time.sleep(every)
