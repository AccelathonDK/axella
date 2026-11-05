"""Week wrap (feature pack §7): the Friday 15:30 work wrap (task "week-wrap") and the private wrap folded into the
Sunday week-ahead (decided 6 Nov). Before such a run the Mac mini writes state/week-wrap.json – the week's facts the
run cannot see itself, counts and times only where possible – and the run writes the "wrap" block into its digest
(AXELLA.md "Week wrap"). Python 3.9.

state/week-wrap.json:
  {"worlds", "week": {"from", "to"}, "next_week": {"from", "to"}, "handled", "arrived", "missed",
   "tasks": {"overdue", "due_next_week"}, "promises_due_next_week": [{"text", "due", "task_id"}],
   "bills_due_next_week": [{"payee", "amount", "currency", "due", "task_id"}] (open bills due by the end of next week),
   "preps_next_week": [{"start", "event_id"}], "birthdays_next_week": [{"day", "name", "turns"}] (private only),
   "trips_next_week": [{"title", "start", "end"}], "calm_line"}
"""
import datetime
import json
import os

HANDLED = ('done', 'file', 'trash', 'reply_send', 'sms_send', 'draft', 'mail_send')
FILE = 'week-wrap.json'


def week_of(today):
    a = today - datetime.timedelta(days=today.weekday())
    return a, today


def next_week(today):
    a = today + datetime.timedelta(days=7 - today.weekday())
    return a, a + datetime.timedelta(days=6)


def _day(s):
    try:
        return datetime.date.fromisoformat(str(s or '')[:10])
    except ValueError:
        return None


def facts(worlds, today, store, state_dir, preps=(), people=(), birthdays=None, trips=None, calm_line=''):
    """The week's facts for a wrap covering `worlds` (['work'], ['private'] or both)."""
    worlds = sorted(worlds)
    wa, wb = week_of(today)
    na, nb = next_week(today)
    world = store._world()
    with store._db() as db:
        rows = [dict(r) for r in db.execute(
            "SELECT id, account, context, from_address addr, message_id, digest FROM items WHERE section NOT IN ('file', 'cal') "
            "AND substr(generated,1,10) BETWEEN ? AND ?", (wa.isoformat(), wb.isoformat())).fetchall()]
        seen = {r[0]: (r[1], r[2], r[3]) for r in db.execute(
            "SELECT id, MAX(account), MAX(context), MAX(from_address) FROM items GROUP BY id").fetchall()}
        acts = [dict(r) for r in db.execute(
            "SELECT at, action, result, item FROM actions WHERE substr(at,1,10) BETWEEN ? AND ? AND item IS NOT NULL",
            (wa.isoformat(), wb.isoformat())).fetchall()]
    in_w = lambda i, acc, ctx, addr: world(i, addr, ctx, acc) in worlds
    arrived = {r['message_id'] or r['id'] for r in rows if in_w(r['id'], r['account'], r['context'], r['addr'])}
    ok = lambda r: str(r.get('result') or '').split(':')[0] in ('ok', 'done', 'already') or str(r.get('result') or '').startswith('sent')
    handled = {a['item'] for a in acts if a['action'] in HANDLED and ok(a) and a['item'] in seen and in_w(a['item'], *seen[a['item']])}
    missed = {a['item'] for a in acts if a['action'] == 'should_have_reached' and a['item'] in seen and in_w(a['item'], *seen[a['item']])}
    try:
        with open(os.path.join(state_dir, 'tasks.json'), encoding='utf-8') as f:
            tasks = [t for t in json.load(f) if isinstance(t, dict) and t.get('status') != 'done']
    except (OSError, ValueError):
        tasks = []
    tasks = [t for t in tasks if t.get('ctx') in (None, '') or t.get('ctx') in worlds]
    due = lambda t: _day(t.get('due'))
    out = {
        'worlds': worlds, 'week': {'from': wa.isoformat(), 'to': wb.isoformat()}, 'next_week': {'from': na.isoformat(), 'to': nb.isoformat()},
        'handled': len(handled), 'arrived': len(arrived), 'missed': len(missed),
        'tasks': {'overdue': sum(1 for t in tasks if due(t) and due(t) < today),
                  'due_next_week': sum(1 for t in tasks if due(t) and na <= due(t) <= nb)},
        'promises_due_next_week': [{'text': str(t.get('text') or '')[:120], 'due': str(t.get('due'))[:10], 'task_id': t.get('id')}
                                   for t in tasks if (t.get('ref') or {}).get('kind') == 'promise' and due(t) and today <= due(t) <= nb][:10],
        'preps_next_week': sorted(({'start': p.get('start'), 'event_id': (p.get('event') or {}).get('id')} for p in preps
                                   if _day(p.get('start')) and na <= _day(p.get('start')) <= nb and (p.get('ctx') or 'work') in worlds),
                                  key=lambda x: str(x['start']))[:40],
        'bills_due_next_week': [{'payee': str((t.get('bill') or {}).get('payee') or t.get('text') or '')[:80],
                                 'amount': (t.get('bill') or {}).get('amount'), 'currency': (t.get('bill') or {}).get('currency'),
                                 'due': str(t.get('due'))[:10], 'task_id': t.get('id')}
                                for t in tasks if t.get('type') == 'bill' and due(t) and due(t) <= nb][:10],
        'calm_line': calm_line,
    }
    if 'private' in worlds and birthdays is not None:
        bd = []
        for k in range(7):
            day = na + datetime.timedelta(days=k)
            for b in birthdays.due(people, day):
                bd.append({'day': day.isoformat(), 'name': b['name'], 'turns': b.get('turns')})
        out['birthdays_next_week'] = bd[:10]
    if trips is not None:
        tr = []
        for t in trips:
            s, e = _day(t.get('start')), _day(t.get('end') or t.get('start'))
            if s and e and s <= nb and e >= na and (t.get('ctx') or 'private') in worlds:
                tr.append({'title': str(t.get('title') or '')[:80], 'start': s.isoformat(), 'end': e.isoformat()})
        out['trips_next_week'] = tr[:5]
    return out


def write(state_dir, data):
    tmp = os.path.join(state_dir, FILE + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(state_dir, FILE))


def prompt_note(worlds):
    who = 'work' if worlds == ['work'] else 'private' if worlds == ['private'] else 'work and private'
    return ('\n\nThis run also writes the WEEK WRAP for %s (AXELLA.md "Week wrap"): read state/week-wrap.json (the Mac mini '
            'wrote it just now) and add the top-level "wrap" block to the .json; the spoken version opens with the wrap '
            '(its headline first) and the whole spoken version stays under 90 seconds.' % who)
