"""Work/private per schedule: a world scope per digest slot (dev request "Work/private per schedule").

A slot in Settings → Schedule (state/scheduler.json "digests") may carry
    "worlds": ["work"] | ["private"] | ["work", "private"]   (missing = both – existing schedules behave as before)
    "mention_other": true|false                                (the one count line about the other world; default on)
A scoped digest covers only its world(s). The other world waits for the next digest that covers it – it is gathered
from the last digest that covered it, so nothing is lost between scoped digests. Urgent (P0) items from the other
world still break through (the P0 checks are never scoped). This module is pure: the scheduler calls it to build the
run's scope note and, after the run, to make sure the digest holds only its world (enforce).
Python 3.9.
"""
import datetime
import json
import os
import re

WORLDS = ('work', 'private')
LABEL = {('work',): 'Work', ('private',): 'Private', ('private', 'work'): 'Work and private'}
NAME_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(?:-week)?\.json$')


def worlds_of(slot):
    """The slot's worlds, sorted; anything missing or unknown = both."""
    w = slot.get('worlds') if isinstance(slot, dict) else None
    out = sorted({x for x in (w or []) if x in WORLDS})
    return out or ['private', 'work']


def norm_slot(slot):
    """worlds + mention_other in their stored form (called when Settings saves a slot)."""
    return {'worlds': worlds_of(slot), 'mention_other': bool(slot.get('mention_other', True)) if isinstance(slot, dict) else True}


def effective(worlds, work_paused=False):
    """The worlds a slot covers today: a day off from work ("Pause work digests only") takes work out."""
    return [w for w in worlds if not (work_paused and w == 'work')]


def is_scoped(worlds):
    return sorted(worlds) != ['private', 'work']


def label(worlds):
    return LABEL.get(tuple(sorted(worlds)), 'Work and private')


def digest_worlds(d):
    """The worlds a digest covers (its top-level "scope"; none = both, as every digest before this feature)."""
    s = d.get('scope') if isinstance(d, dict) else None
    s = sorted({x for x in (s or []) if x in WORLDS})
    return s or ['private', 'work']


def _when(name):
    m = NAME_RE.match(name)
    if not m:
        return None
    y, mo, d, h, mi = (int(x) for x in m.groups())
    return datetime.datetime(y, mo, d, h, mi)


def last_covered(digests_dir, now=None, days=7):
    """{world: datetime of the newest digest (not P0, not a trial) that covered it} – the start of each world's
    gather window, so a world skipped by a scoped digest is picked up by the next one that covers it."""
    now = now or datetime.datetime.now()
    out = {}
    try:
        names = sorted((n for n in os.listdir(digests_dir) if NAME_RE.match(n)), reverse=True)
    except OSError:
        return out
    for n in names:
        t = _when(n)
        if not t or t > now or t < now - datetime.timedelta(days=days):
            continue
        try:
            with open(os.path.join(digests_dir, n), encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        for w in digest_worlds(d):
            out.setdefault(w, t)
        if len(out) == 2:
            break
    return out


def next_covering(slots_on, world, now, work_paused_on=lambda day: False, days=8):
    """(label, datetime) of the next digest slot that covers `world`, from slots_on(date) → [(slot dict, 'HH:MM')]."""
    for k in range(days):
        day = (now + datetime.timedelta(days=k)).date()
        for slot, hm in sorted(slots_on(day), key=lambda x: x[1]):
            h, m = (int(x) for x in hm.split(':'))
            at = datetime.datetime.combine(day, datetime.time(h, m))
            if at <= now:
                continue
            if world in effective(worlds_of(slot), work_paused_on(day)):
                return slot.get('label') or 'the next digest', at
    return None, None


def when_text(at, now):
    if not at:
        return 'the next digest that covers it'
    if at.date() == now.date():
        return ('this evening' if at.hour >= 17 else 'this afternoon' if at.hour >= 12 else 'later today') + ' (%s)' % at.strftime('%H:%M')
    if at.date() == now.date() + datetime.timedelta(days=1):
        return 'tomorrow %s' % at.strftime('%H:%M')
    return at.strftime('%A %H:%M')


def prompt_note(worlds, mention_other, since, next_other, now):
    """The scope paragraph added to a digest run's prompt (AXELLA.md "Digest scope" holds the rules)."""
    if not is_scoped(worlds):
        win = ', '.join('%s since %s' % (w, since[w].strftime('%Y-%m-%d %H:%M')) for w in WORLDS if w in since)
        return ('\n\nDigest scope for this run: work and private (both). Follow AXELLA.md "Digest scope".' +
                (' Gather window per world (the last digest that covered it): %s.' % win if win else ''))
    w = worlds[0]
    other = 'private' if w == 'work' else 'work'
    lines = ['', '', 'Digest scope for this run: %s ONLY. Follow AXELLA.md "Digest scope":' % w.upper(),
             '- items, drafts, calendar, To do lines and the spoken version cover %s only; set top-level "scope": ["%s"] in the .json;' % (w, w),
             '- open the spoken version and the intro with "Your %s digest." ;' % w,
             '- %s items are NOT reported and NOT carried here – they wait for the next digest that covers %s; never treat them as handled;' % (other, other),
             '- urgent (P0) %s items are the exception: include them, with "world": "%s" on the item;' % (other, other)]
    if w in since:
        lines.append('- gather %s since %s (the last digest that covered %s).' % (w, since[w].strftime('%Y-%m-%d %H:%M'), w))
    if mention_other:
        lab, at = next_other
        lines.append('- add ONE line to the intro and the spoken version with the COUNT of new %s messages only, never names or '
                     'content, e.g. "3 %s messages are waiting for %s." (omit it when there are none);' % (other, other, when_text(at, now)))
    else:
        lines.append('- do not mention the %s world at all (the owner turned that line off for this slot).' % other)
    return '\n'.join(lines)


def _overrides(state_dir):
    try:
        with open(os.path.join(state_dir, 'context-overrides.json'), encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def world_of(it, ov):
    """Like the dashboard's ctxOf: your corrections (item > sender > domain), then the run's "context"; unsure = private."""
    sk = str(((it.get('from') or {}).get('address') or (it.get('from') or {}).get('number') or '')).strip().lower().replace(' ', '')
    dom = sk.split('@')[1] if '@' in sk else ''
    for key, kind in ((str(it.get('id', '')).lower(), 'item'), (sk, 'sender'), (dom, 'domain')):
        v = (ov.get(kind) or {}).get(key) if key else None
        if v in WORLDS:
            return v
    return it.get('context') if it.get('context') in WORLDS else 'private'


def neutral_spoken(d, worlds):
    """A spoken version built from the kept items only (counts, no names) – used when the run's own spoken text
    can't be trusted because it ignored the scope."""
    items = [i for i in d.get('items') or [] if isinstance(i, dict)]
    ans = sum(1 for i in items if i.get('section') in ('p0', 'p1', 'p2') and not i.get('world'))
    urgent = sum(1 for i in items if i.get('world'))
    parts = ['Your %s digest.' % ('work' if worlds == ['work'] else 'private')]
    parts.append('%s to answer.' % (ans if ans else 'Nothing'))
    if urgent:
        parts.append('%d urgent %s message%s.' % (urgent, 'private' if worlds == ['work'] else 'work', '' if urgent == 1 else 's'))
    parts.append('Open Axella for the details.')
    return ' '.join(parts)


def replace_spoken(digests_dir, name, text):
    """spoken-digest.md (what Listen and Siri read), when it was written by the same run as this digest."""
    md = os.path.join(digests_dir, 'spoken-digest.md')
    try:
        if abs(os.path.getmtime(md) - os.path.getmtime(os.path.join(digests_dir, name))) < 20 * 60:
            tmp = md + '.scope.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write(text + '\n')
            os.replace(tmp, md)
    except OSError:
        pass


def enforce(path, worlds, state_dir):
    """After a scoped run: the digest holds only its world(s), plus urgent items from the other world (marked with
    "world"). Other-world items are taken out, never marked handled – the next covering digest gathers them. When
    anything had to be taken out, the run ignored its scope, so its spoken text is replaced by a neutral one built
    from the kept items (it might name the other world's messages). Through digestfile.update (locked, re-read,
    atomic). Returns the number taken out (0 for a digest covering both)."""
    import digestfile
    worlds = sorted(worlds)

    def change(d):
        if not isinstance(d, dict) or not isinstance(d.get('items'), list):
            return False, 0
        changed = d.get('scope') != worlds
        d['scope'] = worlds
        out = 0
        if is_scoped(worlds):
            ov, keep = _overrides(state_dir), []
            for it in d['items']:
                if not isinstance(it, dict):
                    continue
                w = world_of(it, ov)
                if w in worlds:
                    keep.append(it)
                elif it.get('section') == 'p0':
                    it['world'] = w
                    keep.append(it)
                else:
                    out += 1
            if out:
                d['items'] = keep
                d['spoken'] = neutral_spoken(d, worlds)
                d['spoken_replaced'] = 'scope'
                changed = True
        return changed, out

    out = digestfile.update(path, change) or 0
    if out:
        with open(path, encoding='utf-8') as f:
            spoken = json.load(f).get('spoken') or ''
        replace_spoken(os.path.dirname(path), os.path.basename(path), spoken)
    return out
