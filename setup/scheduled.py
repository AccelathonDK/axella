"""Send later: a reply or a new mail you approved with "Send at…" waits on the Mac mini and goes out at that time,
through the same send path as Send (axella-actions.py mail_send / reply_send – checks, the hourly brake, the Sent
record). Feature pack Nov 2026 §1c.

state/scheduled.json: [{"id", "action": "mail_send|reply_send", "payload": {...}, "at": iso, "created": iso,
  "status": "scheduled|sending|sent|failed|cancelled|unknown|missed", "sent_at", "late_min", "error", "title", "to", "login",
  "send_id": one per mail, kept for every try – the Mac mini's send_id guard never sends the same id twice,
  "checked": the owner confirmed Sent doesn't have it (only then is an "unknown" one tried again)}]
A mail more than an hour past its time (Mac mini off or asleep, service down) becomes "missed" with one notification –
"send now or reschedule?" – and is never sent by itself.
state/scheduled-files/<id>/<n>/<name> – attachments, kept here (not in the 24-hour outbox) until the mail goes.

The tap on a time is the approval. Nothing is sent twice: an item is marked "sending" on disk before Mail is asked,
and one found "sending" after a restart becomes "unknown" (check Sent) – never sent again by itself.
Python 3.9.
"""
import datetime
import json
import os
import shutil
import threading
import uuid

LOCK = threading.Lock()
ACTIONS = ('mail_send', 'reply_send')
KEEP = ('account', 'to', 'subject', 'text', 'message_id', 'item_id', 'title', 'expect_to', 'to_list', 'cc', 'bcc',
        'cc_list', 'bcc_list', 'attachments')                # never 'force': a scheduled mail never overrides the repeat guard
LATE_MIN = 60                                           # more than an hour past its time: "missed", never sent by itself
MAX_AHEAD_DAYS = 60
KEEP_DONE_DAYS = 14


class Bad(Exception):
    pass


class Unknown(Exception):
    """Mail may or may not have sent it (a timeout, "did not answer", no outcome in time) – check Sent."""


def _now():
    return datetime.datetime.now().astimezone()


def _parse(at):
    try:
        d = datetime.datetime.fromisoformat(str(at).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        raise Bad('a time like 2026-11-09T08:00')
    return d if d.tzinfo else d.astimezone()


class Scheduled:
    def __init__(self, state_dir, outbox_dir):
        self.file = os.path.join(state_dir, 'scheduled.json')
        self.files = os.path.join(state_dir, 'scheduled-files')
        self.outbox = outbox_dir

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = []
        return d if isinstance(d, list) else []

    def _save(self, d):
        tmp = self.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)

    def list(self, now=None):
        """What the dashboard shows: everything waiting, plus what went (or failed) in the last 14 days. No mail text."""
        cut = (now or _now()) - datetime.timedelta(days=KEEP_DONE_DAYS)
        out = []
        for x in self.load():
            if x['status'] not in ('scheduled', 'sending') and _parse(x.get('sent_at') or x['at']) < cut:
                continue
            out.append({k: x.get(k) for k in ('id', 'action', 'at', 'created', 'status', 'sent_at', 'late_min', 'error', 'title', 'to')}
                       | {'subject': x['payload'].get('subject') or x.get('title'), 'attachments': len(x['payload'].get('attachments') or []),
                          'item_id': x['payload'].get('item_id')})
        out.sort(key=lambda x: x['at'])
        return out

    def get(self, sid):
        x = next((y for y in self.load() if y['id'] == sid), None)
        if not x:
            raise Bad('not found')
        return x

    def text(self, sid):
        x = self.get(sid)
        return {'text': x['payload'].get('text') or '', 'subject': x['payload'].get('subject') or ''}

    # ---------- add / change ----------
    def add(self, action, payload, at, login, now=None):
        if action not in ACTIONS:
            raise Bad('only mails and replies can be sent later')
        if not isinstance(payload, dict) or not str(payload.get('text') or '').strip():
            raise Bad('nothing to send')
        when = _parse(at)
        now = now or _now()
        if when < now + datetime.timedelta(seconds=50):
            raise Bad('pick a time at least a minute from now – or just send it')
        if when > now + datetime.timedelta(days=MAX_AHEAD_DAYS):
            raise Bad('at most %d days ahead' % MAX_AHEAD_DAYS)
        p = {k: payload[k] for k in KEEP if k in payload}
        sid = 's' + uuid.uuid4().hex[:16]
        p['attachments'] = self._keep_files(sid, payload.get('attachments') or [])
        x = {'id': sid, 'action': action, 'payload': p, 'at': when.isoformat(timespec='minutes'), 'created': now.isoformat(timespec='seconds'),
             'status': 'scheduled', 'send_id': uuid.uuid4().hex, 'title': str(payload.get('title') or payload.get('subject') or '')[:200],
             'to': (', '.join(map(str, payload['to'])) if isinstance(payload.get('to'), list) else str(payload.get('to') or payload.get('expect_to') or ''))[:300],
             'login': login}
        with LOCK:
            d = self.load()
            d.append(x)
            self._save(d)
        return {'id': sid, 'at': x['at']}

    def _keep_files(self, sid, ids):
        """Move the uploads out of the 24-hour outbox into scheduled-files/<id>/ (ids stay 'n/name')."""
        if not ids:
            return []
        if not isinstance(ids, list) or len(ids) > 10:
            raise Bad('at most 10 attachments')
        root, out = os.path.realpath(self.outbox), []
        for n, i in enumerate(ids):
            src = os.path.realpath(os.path.join(self.outbox, str(i)))
            if not src.startswith(root + os.sep) or not os.path.isfile(src):
                raise Bad('attachment missing – add it again')
            dst = os.path.join(self.files, sid, str(n))
            os.makedirs(dst, mode=0o700, exist_ok=True)
            shutil.move(src, os.path.join(dst, os.path.basename(src)))
            shutil.rmtree(os.path.dirname(src), ignore_errors=True)
            out.append('%d/%s' % (n, os.path.basename(src)))
        return out

    def _back_to_outbox(self, sid, kept):
        """For the send: copies in the outbox (the send path only takes outbox ids). The originals stay until it went."""
        out = []
        for k in kept or []:
            src = os.path.join(self.files, sid, k)
            fid = uuid.uuid4().hex
            os.makedirs(os.path.join(self.outbox, fid))
            shutil.copy2(src, os.path.join(self.outbox, fid, os.path.basename(src)))
            out.append(fid + '/' + os.path.basename(src))
        return out

    def update(self, sid, p, now=None):
        with LOCK:
            d = self.load()
            x = next((y for y in d if y['id'] == sid), None)
            if not x:
                raise Bad('not found')
            if x['status'] not in ('scheduled', 'missed'):
                raise Bad('it has already gone' if x['status'] in ('sent', 'sending') else 'it is not waiting any more')
            if x['status'] == 'missed' and 'at' not in p:
                raise Bad('pick a new time for it')
            if 'at' in p:
                when = _parse(p['at'])
                n = now or _now()
                if when < n + datetime.timedelta(seconds=50) or when > n + datetime.timedelta(days=MAX_AHEAD_DAYS):
                    raise Bad('pick a time between a minute and %d days from now' % MAX_AHEAD_DAYS)
                x['at'] = when.isoformat(timespec='minutes')
                x['status'], x['error'], x['now'] = 'scheduled', None, False
            if 'text' in p:
                if not str(p['text']).strip():
                    raise Bad('the text is empty')
                x['payload']['text'] = str(p['text'])[:100000]
            if 'subject' in p and x['action'] == 'mail_send':
                if not str(p['subject']).strip():
                    raise Bad('the subject is empty')
                x['payload']['subject'] = x['title'] = str(p['subject'])[:300]
            self._save(d)
        return {'id': sid, 'at': x['at']}

    def cancel(self, sid):
        with LOCK:
            d = self.load()
            x = next((y for y in d if y['id'] == sid), None)
            if not x:
                raise Bad('not found')
            if x['status'] not in ('scheduled', 'missed', 'failed'):
                raise Bad('it has already gone' if x['status'] in ('sent', 'sending') else 'it is not waiting any more')
            x['status'], x['sent_at'] = 'cancelled', _now().isoformat(timespec='seconds')
            self._save(d)
        shutil.rmtree(os.path.join(self.files, sid), ignore_errors=True)   # uploads of a mail that won't be sent, like the outbox
        return {'id': sid, 'status': 'cancelled'}

    def send_now(self, sid, checked=False, now=None):
        """Send now / Try again, on your tap. An "unknown" one only after you confirmed Sent doesn't have it; every try
        keeps the mail's send_id, so a send that did go is never repeated."""
        with LOCK:
            d = self.load()
            x = next((y for y in d if y['id'] == sid), None)
            if not x or x['status'] not in ('scheduled', 'failed', 'unknown', 'missed'):
                raise Bad('it is not waiting any more')
            if x['status'] == 'unknown' and not checked:
                raise Bad('check Sent in Mail first – it may have gone already')
            x['checked'] = bool(checked) if x['status'] == 'unknown' else False
            x['at'] = (now or _now()).isoformat(timespec='minutes')
            x['now'], x['status'], x['error'] = True, 'scheduled', None
            self._save(d)
        return {'id': sid}

    # ---------- the clock ----------
    def recover(self):
        """At start: anything left "sending" was interrupted – Mail may or may not have sent it. Never resend by itself."""
        with LOCK:
            d = self.load()
            n = 0
            for x in d:
                if x['status'] == 'sending':
                    x['status'], x['error'] = 'unknown', 'the Mac mini restarted while sending – check Sent in Mail'
                    n += 1
            if n:
                self._save(d)
        return n

    def due(self, now=None):
        now = now or _now()
        return [x for x in self.load() if x['status'] == 'scheduled' and _parse(x['at']) <= now]

    def mark_missed(self, now=None, notify=None):
        """More than an hour past its time (and not "send now"): missed – one notification, never sent by itself."""
        now = now or _now()
        out = []
        with LOCK:
            d = self.load()
            for x in d:
                if x['status'] == 'scheduled' and not x.get('now') and _parse(x['at']) < now - datetime.timedelta(minutes=LATE_MIN):
                    x['status'], x['error'] = 'missed', 'not sent – it was more than an hour late (the Mac mini was off or asleep)'
                    out.append(dict(x))
            if out:
                self._save(d)
        for x in out:
            if notify:
                try:
                    notify(x)
                except Exception:
                    pass
        return out

    def run_due(self, send, log=None, now=None, notify=None):
        """Send everything due, one by one. send(action, payload, checked) is the normal send path: it raises Bad when it
        refused (nothing went) and Unknown when Mail may have sent it."""
        done = []
        self.mark_missed(now, notify)
        for x in self.due(now):
            with LOCK:
                d = self.load()
                cur = next((y for y in d if y['id'] == x['id']), None)
                if not cur or cur['status'] != 'scheduled':
                    continue
                cur['status'] = 'sending'
                self._save(d)
            p = dict(x['payload'], confirm='send', send_id=x.get('send_id') or uuid.uuid5(uuid.NAMESPACE_URL, x['id']).hex)
            try:
                p['attachments'] = self._back_to_outbox(x['id'], x['payload'].get('attachments'))
                res = send(x['action'], p, bool(cur.get('checked')))
                status, err = ('sent', None) if isinstance(res, dict) and (res.get('status') == 'sent' or res.get('already_sent')) \
                    else ('unknown', 'Mail did not confirm – check Sent in Mail')
            except Unknown as e:
                status, err = 'unknown', (str(e) or 'Mail did not confirm – check Sent in Mail')[:300]
            except Exception as e:
                status, err = 'failed', str(e)[:300]
            t = now or _now()
            late = int((t - _parse(x['at'])).total_seconds() // 60)
            with LOCK:
                d = self.load()
                cur = next((y for y in d if y['id'] == x['id']), None)
                if cur:
                    cur.update(status=status, error=err, sent_at=t.isoformat(timespec='seconds'), checked=False,
                               late_min=late if late >= 2 and not cur.get('now') else 0)
                    self._save(d)
            if status == 'sent':
                shutil.rmtree(os.path.join(self.files, x['id']), ignore_errors=True)
            if log:
                log(x, status, err, late)
            done.append((x['id'], status))
        return done
