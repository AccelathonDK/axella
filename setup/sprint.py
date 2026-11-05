"""Reply sprint: the quick replies that are ready, one after another, in a few minutes. Rules only – no AI, no new
drafts, nothing is sent from here. Every Send in the sprint is the dashboard's ordinary reply_send (send_id, the
hourly brake, the Sent record, the activity log) on its own tap.

  why_not(item, max_words)     → None for a quick reply, else the reason it's left out
  pick(items, state, debt, …)  → the quick replies, in sprint order: people you owe an answer first (longest waiting),
                                 then urgency (P1, P2, still open), then age (oldest first)
  seconds(item)                → 30–60 s for one reply, from the length of the message note and the draft
  view(items, …)               → {items, count, seconds, minutes, show}

Quick = an Axella draft (mode reply) under max_words words, on a mail in P1, P2 or Still open, not handled, snoozed
or waiting in Send later, not scam-flagged, not to a no-reply address, and not left out by the caller (a private or
hidden contact, a protected workplace's mail).
"""
import datetime
import re

SECTIONS = ('p1', 'p2', 'open')
RANK = {'p1': 0, 'p2': 1, 'open': 2}
MAX_WORDS = 80
MIN_CARD = 3
# the same pattern as axella-actions NO_REPLY and web/src/lib/data.ts isNoReply
NO_REPLY = re.compile(r'^(?:[^@]*[-+._])?(no-?reply|no_reply|do-?not-?reply|do_not_reply|mailer-daemon|postmaster|bounces?|notifications?)(?:[-+._][^@]*)?@', re.I)


def words(text):
    return len(re.findall(r'\S+', str(text or '')))


def sender(it):
    return str(((it.get('from') or {}) if isinstance(it.get('from'), dict) else {}).get('address') or '').strip().lower()


def addresses(it):
    """The sender and the draft's To – what the left-out rules look at."""
    out = [sender(it)]
    d = it.get('draft') if isinstance(it.get('draft'), dict) else {}
    out += [a.strip().lower() for a in re.split(r'[,;\s]+', str(d.get('to') or '')) if '@' in a]
    return [a for a in dict.fromkeys(out) if a]


def why_not(it, max_words=MAX_WORDS):
    if not isinstance(it, dict) or not it.get('id'):
        return 'not an item'
    if it.get('section') not in SECTIONS:
        return 'section'
    if it.get('channel') != 'mail' or not it.get('message_id') or not it.get('account'):
        return 'not a mail'
    if it.get('readonly') or it.get('found'):
        return 'read only'
    if it.get('safety'):
        return 'flagged'
    d = it.get('draft')
    if not isinstance(d, dict) or d.get('mode') != 'reply' or not str(d.get('text') or '').strip():
        return 'no draft'
    if words(d.get('text')) >= max_words:
        return 'long'
    if not sender(it) or NO_REPLY.search(sender(it)):
        return 'no reply'
    return None


def _when(s):
    try:
        d = datetime.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except ValueError:
        return None
    return d if d.tzinfo else d.astimezone()


def handled(st, now=None):
    """Done (sent, filed, done without reply) or snoozed until later."""
    if not isinstance(st, dict):
        return False
    if st.get('status') == 'done':
        return True
    if st.get('status') == 'snoozed':
        u = _when(st.get('until'))
        return bool(u and u > (now or datetime.datetime.now().astimezone()))
    return False


def pick(items, state=None, debt=(), scheduled=(), left_out=None, now=None, max_words=MAX_WORDS):
    state = state or {}
    sched = {str(x) for x in scheduled if x}
    owed = {}
    for x in debt or []:
        w = str(x.get('who') or '').strip().lower()
        if w:
            owed[w] = max(owed.get(w, 0), int(x.get('days') or 0))
    out, seen = [], set()
    for it in items or []:
        if why_not(it, max_words):
            continue
        iid = str(it['id'])
        if iid in seen or iid in sched or handled(state.get(iid), now):
            continue
        if left_out and left_out(it):
            continue
        seen.add(iid)
        out.append(it)

    def key(it):
        d = owed.get(sender(it))
        return (0 if d is not None else 1, -(d or 0), RANK[it['section']], str(it.get('first_seen') or '~'))
    out.sort(key=key)
    return out


def seconds(it):
    """About 30 s to read and send a short one, up to 60 s for a longer message or draft."""
    d = it.get('draft') if isinstance(it.get('draft'), dict) else {}
    n = words(d.get('text')) + words(it.get('detail')) + words(it.get('summary'))
    return 30 + min(30, n // 3)


def view(items, state=None, debt=(), scheduled=(), left_out=None, now=None, max_words=MAX_WORDS, min_card=MIN_CARD):
    q = pick(items, state, debt, scheduled, left_out, now, max_words)
    owed = {str(x.get('who') or '').strip().lower() for x in debt or []}
    total = sum(seconds(i) for i in q)
    return {'items': [dict(i, sprint={'seconds': seconds(i), 'owed': sender(i) in owed}) for i in q],
            'count': len(q), 'seconds': total, 'minutes': max(1, int(round(total / 60.0))) if q else 0,
            'show': len(q) >= min_card, 'min': min_card, 'max_words': max_words}
