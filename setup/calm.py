"""Calm in numbers (feature pack §8): Insights → "Your calm", this month against last month.

Honest about what Axella can know – every number comes from records it keeps anyway, never from message content:
  - held vs broke through: messages that waited for a digest, against the ones a P0 check pushed at once;
  - digests delivered, read (opened in the dashboard) and listened to (Listen or the Siri shortcut);
  - median reply time per world: from a message's first report to your reply sent from Axella;
  - work items surfaced outside work hours (aiming for zero; actions-config.json "work_hours");
  - nothing missed: items you marked "This should have reached me";
  - drafts sent with little or no editing (the send records only a bucket: none / little / much – never the text);
  - promises kept on time: promise tasks done by their due date.
Reads state/axella.db (store.py), state/actions.log, state/digest-reads.json and state/tasks.json. Python 3.9.
"""
import datetime
import json
import os
import statistics

READS = 'digest-reads.json'
WORK_HOURS = {'days': [0, 1, 2, 3, 4], 'from': '08:00', 'to': '17:00'}
REPLIES = ('reply_send', 'sms_send')


def month_range(month):
    """'2027-03' → ('2027-03-01', '2027-03-31')."""
    y, m = (int(x) for x in month.split('-'))
    first = datetime.date(y, m, 1)
    nxt = datetime.date(y + (m == 12), m % 12 + 1, 1)
    return first.isoformat(), (nxt - datetime.timedelta(days=1)).isoformat()


def prev_month(month):
    y, m = (int(x) for x in month.split('-'))
    return '%04d-%02d' % (y - (m == 1), (m - 2) % 12 + 1)


def mark_read(state_dir, name, how, now=None):
    """Remember that a digest was opened ('seen') or heard ('listened') – first time only."""
    if how not in ('seen', 'listened') or not name or '/' in name or len(name) > 60:
        return False
    path = os.path.join(state_dir, READS)
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    e = d.setdefault(name, {})
    if e.get(how):
        return False
    e[how] = (now or datetime.datetime.now().astimezone()).isoformat(timespec='seconds')
    d = dict(sorted(d.items())[-800:])
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f)
    os.replace(tmp, path)
    return True


def _hm(s):
    h, m = (int(x) for x in str(s).split(':'))
    return h * 60 + m


def outside(gen, hours):
    """Is this ISO local time outside your work hours?"""
    try:
        t = datetime.datetime.fromisoformat(str(gen)[:19])
    except ValueError:
        return False
    if t.weekday() not in hours.get('days', WORK_HOURS['days']):
        return True
    m = t.hour * 60 + t.minute
    return not (_hm(hours.get('from', WORK_HOURS['from'])) <= m < _hm(hours.get('to', WORK_HOURS['to'])))


def _log(state_dir, a, b):
    """The actions in [a, b] from state/actions.log (the newest 8 MB)."""
    path = os.path.join(state_dir, 'actions.log')
    out = []
    try:
        with open(path, encoding='utf-8') as f:
            f.seek(max(0, os.path.getsize(path) - 8 * 1024 * 1024))
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if a <= str(e.get('at') or '')[:10] <= b:
                    out.append(e)
    except OSError:
        pass
    return out


def _ok(e):
    r = str(e.get('result') or '')
    return r.split(':')[0] in ('ok', 'already') or r.startswith('sent')


def measure(store, state_dir, month, hours=None):
    """The numbers for one calendar month."""
    hours = hours or WORK_HOURS
    a, b = month_range(month)
    world = store._world()
    with store._db() as db:
        rows = [dict(r) for r in db.execute(
            "SELECT digest, id, generated, section, account, context, from_address addr, message_id, first_seen FROM items "
            "WHERE section NOT IN ('file') AND substr(generated,1,10) BETWEEN ? AND ?", (a, b)).fetchall()]
        digests = [r[0] for r in db.execute(
            "SELECT name FROM digests WHERE name NOT LIKE '%-p0' AND substr(generated,1,10) BETWEEN ? AND ?", (a, b)).fetchall()]
        first = {}
        for r in db.execute("SELECT id, MIN(first_seen) f, MAX(context) c, MAX(account) acc, MAX(from_address) addr FROM items "
                            "WHERE first_seen IS NOT NULL GROUP BY id").fetchall():
            first[r[0]] = (r[1], r[2], r[3], r[4])
    msg = [r for r in rows if r['section'] != 'cal']
    key = lambda r: r['message_id'] or r['id']
    pushed = {key(r) for r in msg if str(r['digest']).endswith('-p0')}
    held = {key(r) for r in msg if not str(r['digest']).endswith('-p0')} - pushed
    work_out = {key(r) for r in msg if not str(r['digest']).endswith('-p0') and outside(r['generated'], hours)
                and world(r['id'], r['addr'], r['context'], r['account']) == 'work'}
    try:
        with open(os.path.join(state_dir, READS), encoding='utf-8') as f:
            reads = json.load(f)
    except (OSError, ValueError):
        reads = {}
    log = _log(state_dir, a, b)
    waits = {'work': [], 'private': []}
    for e in log:
        if e.get('action') in REPLIES and _ok(e) and e.get('item') in first and first[e['item']][0]:
            f, c, acc, addr = first[e['item']]
            try:
                mins = (datetime.datetime.fromisoformat(str(e['at'])[:19]) - datetime.datetime.fromisoformat(str(f)[:19])).total_seconds() / 60
            except ValueError:
                continue
            if mins >= 0:
                waits[world(e['item'], addr, c, acc)].append(mins)
    sent = [e for e in log if e.get('action') == 'reply_send' and _ok(e) and e.get('edit')]
    light = sum(1 for e in sent if e.get('edit') in ('none', 'little'))
    try:
        with open(os.path.join(state_dir, 'tasks.json'), encoding='utf-8') as f:
            tasks = json.load(f)
    except (OSError, ValueError):
        tasks = []
    prom = [t for t in tasks if isinstance(t, dict) and (t.get('ref') or {}).get('kind') == 'promise' and t.get('due')
            and a <= str(t['due'])[:10] <= b]
    kept = [t for t in prom if t.get('status') == 'done' and str(t.get('done') or '9')[:10] <= str(t['due'])[:10]]
    return {
        'month': month,
        'held': len(held), 'broke_through': len(pushed),
        'digests': len(digests), 'read': sum(1 for n in digests if (reads.get(n) or {}).get('seen')),
        'listened': sum(1 for n in digests if (reads.get(n) or {}).get('listened')),
        'reply_minutes': {w: (round(statistics.median(v)) if v else None) for w, v in waits.items()},
        'replies': {w: len(v) for w, v in waits.items()},
        'work_outside_hours': len(work_out),
        'missed': sum(1 for e in log if e.get('action') == 'should_have_reached' and _ok(e)),
        'drafts_sent': len(sent), 'drafts_light': light,
        'promises_due': len(prom), 'promises_kept': len(kept),
    }


def calm(store, state_dir, month=None, hours=None, today=None):
    month = month or (today or datetime.date.today()).strftime('%Y-%m')
    return {'this': measure(store, state_dir, month, hours), 'last': measure(store, state_dir, prev_month(month), hours),
            'work_hours': hours or WORK_HOURS}


def one_line(c):
    """The week wrap's line of calm in numbers (counts only)."""
    t = c['this']
    parts = ['%d messages waited for a digest, %d broke through' % (t['held'], t['broke_through'])]
    if t['work_outside_hours'] == 0:
        parts.append('no work outside work hours')
    if t['missed'] == 0:
        parts.append('nothing missed')
    return 'This month so far: ' + ', '.join(parts) + '.'
