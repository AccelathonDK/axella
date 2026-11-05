"""System status in one plain sentence (System status page and the account menu), with an analysis per problem.
Rules only, from the rows system_status() already collects and the watchdog's state/watchdog.json. No AI, nothing
leaves the home, no pushes.

  sentence(rows, watchdog, since, now, next_digest) → {"level": ok|warn|down, "text", "short", "problems": [...]}
  Since.track(rows, now) keeps, per part, when it first went bad (state/status-since.json), across checks and restarts.
"""
import datetime
import json
import os
import threading

RANK = {'down': 0, 'warn': 1}
# what a part affects – a fixed map (digests, urgent checks, sending, call agent, push, Listen)
AFFECTS = {
    'session': ('digests', 'urgent', 'sending', 'listen'),
    'actions': ('digests', 'urgent', 'sending', 'push', 'listen'),
    'claude': ('digests', 'listen'),
    'schedule': ('digests', 'listen'),
    'macuse': ('digests', 'urgent', 'sending'),
    'mail': ('digests', 'urgent', 'sending'),
    'imessage': ('digests', 'urgent'),
    'whatsapp': ('digests', 'urgent'),
    'signal': ('digests', 'urgent'),
    'calls': ('calls',),
    'push': ('push',),
    'watchdog': ('push',),
    'web': (),
    'disk': ('digests',),
    'privacy': (),
    'feedback': (),
}
NEXT_DIGEST = {'digests', 'listen'}
SHORT = {'whatsapp': 'WhatsApp', 'imessage': 'Messages', 'mail': 'Mail', 'signal': 'Signal', 'calls': 'the call agent',
         'push': 'notifications', 'claude': 'Claude', 'macuse': 'Macuse', 'schedule': 'the schedule', 'disk': 'disk space',
         'watchdog': 'the watchdog', 'web': 'the web server', 'session': 'your login', 'actions': 'Axella', 'privacy': 'privacy settings',
         'feedback': 'axella.dev feedback'}


def _hm(ts):
    return datetime.datetime.fromtimestamp(ts).strftime('%H:%M')


def _dur(sec):
    m = int(max(0, sec) // 60)
    if m < 60:
        return '%d min' % m
    h, m = divmod(m, 60)
    if h < 48:
        return '%d h %d min' % (h, m) if m else '%d h' % h
    return '%d days' % (h // 24)


def _since_text(ts, now):
    day = datetime.datetime.fromtimestamp(ts).date()
    today = datetime.datetime.fromtimestamp(now).date()
    when = _hm(ts) if day == today else datetime.datetime.fromtimestamp(ts).strftime('%d %b %H:%M').lstrip('0')
    return 'Since %s (%s).' % (when, _dur(now - ts))


def affects_text(cid, next_digest=None):
    a = AFFECTS.get(cid, ())
    out = []
    if 'digests' in a:
        out.append('The next digest%s will miss %s.' % (' (%s)' % next_digest if next_digest else '', SHORT.get(cid, 'it'))
                   if cid in ('whatsapp', 'imessage', 'mail', 'signal') else
                   'The next digest%s won\'t be written.' % (' (%s)' % next_digest if next_digest else ''))
    if 'urgent' in a:
        out.append('Urgent %s won\'t reach you.' % ({'whatsapp': 'WhatsApp messages', 'imessage': 'texts', 'mail': 'mails',
                                                      'signal': 'Signal messages'}.get(cid, 'messages')))
    if 'sending' in a:
        out.append('Replies can\'t be sent.')
    if 'calls' in a:
        out.append('Missed calls won\'t get a message taken.')
    if 'push' in a:
        out.append('Notifications won\'t arrive.')
    if 'listen' in a and 'digests' not in a:
        out.append('Listen has nothing new.')
    return ' '.join(out) or 'Nothing else is affected.'


def _order(p):
    return (RANK.get(p['state'], 9), 0 if NEXT_DIGEST & set(AFFECTS.get(p['id'], ())) else 1, p.get('since') or 0)


def sentence(rows, watchdog=None, since=None, now=None, next_digest=None, off=()):
    """The sentence first, then one block per problem (worst first)."""
    now = now or datetime.datetime.now().timestamp()
    since = since or {}
    w = watchdog or {}
    # Axella itself down: the watchdog's view (the action service may not be answering at all)
    if w and (w.get('session') is False or w.get('actions') is False):
        what = 'you\'re not logged in on the Mac mini' if w.get('session') is False else 'the Axella service isn\'t running'
        t = None
        try:
            t = datetime.datetime.fromisoformat(str(w.get('since') or '')).timestamp()
        except ValueError:
            pass
        text = 'Mail and messages are paused – %s.%s' % (what, ' Since %s.' % _hm(t) if t else '')
        return {'level': 'down', 'text': text, 'short': 'Paused', 'problems': [{
            'id': 'session' if w.get('session') is False else 'actions', 'name': 'Axella', 'state': 'down', 'what': text,
            'since': t, 'since_text': _since_text(t, now) if t else None,
            'affects': affects_text('session' if w.get('session') is False else 'actions', next_digest),
            'fix': 'Log in on the Mac mini (Screen Sharing → Log in as yourself)' if w.get('session') is False else
                   'launchctl kickstart -k gui/$(id -u)/<label>.axella-actions'}]}
    probs = []
    for r in rows:
        if r.get('state') not in RANK or r.get('id') in off:
            continue
        p = dict(r, since=since.get(r['id']))
        p['what'] = '%s: %s' % (r.get('name'), str(r.get('detail') or '').rstrip('.') + '.')
        p['since_text'] = _since_text(p['since'], now) if p['since'] else None
        p['affects'] = affects_text(r['id'], next_digest)
        probs.append(p)
    probs.sort(key=_order)
    checked = 'checked %s' % _hm(now)
    if not probs:
        return {'level': 'ok', 'text': 'Everything works (%s).' % checked, 'short': 'Everything works', 'problems': []}
    level = probs[0]['state']
    if len(probs) == 1:
        p = probs[0]
        lead = '%s%s' % (p.get('name'), (' – ' + str(p.get('detail') or '').rstrip('.')) if p.get('detail') else '')
        text = lead + (' – ' + p['fix'].rstrip('.') if p.get('fix') else '') + '.'
        return {'level': level, 'text': text, 'short': (lambda n: n[:1].upper() + n[1:])(SHORT.get(p['id'], p.get('name')) + ' needs you'), 'problems': probs}
    names = [SHORT.get(p['id'], p.get('name')) for p in probs]
    listed = ' and '.join(names) if len(names) == 2 else ', '.join(names[:3]) + (' and %d more' % (len(names) - 3) if len(names) > 3 else '')
    if len(names) == 3:
        listed = '%s, %s and %s' % tuple(names)
    text = '%d things need you – %s.' % (len(probs), listed)
    return {'level': level, 'text': text[0].upper() + text[1:], 'short': '%d things need you' % len(probs), 'problems': probs}


class Since:
    """When each part first went bad (down or warn), kept across checks and restarts; cleared when it's ok again."""

    def __init__(self, state_dir):
        self.file = os.path.join(state_dir, 'status-since.json')

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        return {k: float(v) for k, v in d.items() if isinstance(v, (int, float))} if isinstance(d, dict) else {}

    def track(self, rows, now=None):
        now = now or datetime.datetime.now().timestamp()
        d = self.load()
        changed = False
        seen = set()
        for r in rows:
            cid = r.get('id')
            if not cid:
                continue
            seen.add(cid)
            bad = r.get('state') in RANK
            if bad and cid not in d:
                d[cid] = now
                changed = True
            elif not bad and cid in d:
                del d[cid]
                changed = True
        for cid in [k for k in d if k not in seen]:
            del d[cid]
            changed = True
        if changed:
            tmp = '%s.%d.%d.tmp' % (self.file, os.getpid(), threading.get_ident())   # one per process and thread
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(d, f)
            os.replace(tmp, self.file)
        return d
