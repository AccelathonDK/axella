"""The dashboard's Calendar (Agenda and Week): events read from Calendar on the Mac mini through Macuse – the same
read-only calendar tool the digests use, so repeating events come out as real occurrences. Read only: nothing is added,
moved or deleted here (adding an event from a digest item stays where it was).

Shown to the owner only, never handed to a Claude run. Work / Private comes from actions-config.json "calendars"
(kind per calendar); a calendar that isn't listed shows under both filters.
"""
import json
import re
import os
import subprocess
import threading
import time
from datetime import date, datetime, timedelta

MAX_DAYS = 62
PAGE, MAX_PAGES = 100, 15
CACHE_SECS = 60
_cache, _lock = {}, threading.Lock()


class CalendarError(Exception):
    pass


def macuse_command(mcp_file):
    try:
        with open(mcp_file, encoding='utf-8') as f:
            srv = json.load(f)['mcpServers']['macuse']
    except (OSError, ValueError, KeyError):
        raise CalendarError('Macuse is not set up (state/mcp.json) – see SETUP')
    return [srv['command']] + list(srv.get('args') or []), {**os.environ, **(srv.get('env') or {})}


class Mcp:
    """A minimal MCP client over stdio: initialize, then tools/call. One child process per request."""

    def __init__(self, cmd, env, timeout=40):
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  env=env, bufsize=0)
        self.n, self.deadline = 0, time.time() + timeout

    def _send(self, msg):
        self.p.stdin.write((json.dumps(msg) + '\n').encode())
        self.p.stdin.flush()

    def request(self, method, params):
        self.n += 1
        rid = self.n
        self._send({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params})
        while time.time() < self.deadline:
            line = self.p.stdout.readline()
            if not line:
                raise CalendarError('Macuse stopped')
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get('id') == rid:
                if msg.get('error'):
                    raise CalendarError('Macuse: %s' % str(msg['error'].get('message') or msg['error'])[:160])
                return msg.get('result') or {}
        raise CalendarError('Macuse took too long')

    def open(self):
        self.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                    'clientInfo': {'name': 'axella-calendar', 'version': '1'}})
        self._send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        return self

    def close(self):
        try:
            self.p.stdin.close()
            self.p.terminate()
            self.p.wait(timeout=5)
        except Exception:
            try:
                self.p.kill()
            except Exception:
                pass


def _payload(result):
    """The JSON object in a tools/call result (Macuse puts it in a text item, after a resource link)."""
    for c in result.get('content') or []:
        if c.get('type') != 'text':
            continue
        t = c.get('text') or ''
        i = t.find('{')
        while i != -1:
            try:
                return json.loads(t[i:])
            except ValueError:
                i = t.find('{', i + 1)
    sc = result.get('structuredContent')
    if isinstance(sc, dict):
        return sc
    raise CalendarError('unexpected answer from Macuse')


def _clip(s, n):
    s = str(s or '').strip()
    return s[:n] if s else None


def people(attendees):
    """The other attendees as name + e-mail (meeting prep fills its People from these)."""
    out = []
    for a in attendees or []:
        if not isinstance(a, dict) or a.get('is_current_user'):
            continue
        mail = str(a.get('email') or '')
        if not mail and str(a.get('url') or '').lower().startswith('mailto:'):
            mail = str(a['url'])[7:]
        mail = mail.strip().lower()[:200]
        name = _clip(a.get('name') or a.get('display_name'), 120) or mail
        if name or mail:
            out.append({'name': name, 'email': mail if '@' in mail else ''})
    return out[:30]


JOIN_RE = re.compile(r'https://(?:teams\.microsoft\.com/(?:l/meetup-join|meet)/|[\w-]+\.zoom\.us/j/|meet\.google\.com/|'
                     r'[\w-]+\.webex\.com/(?:meet|join)/|whereby\.com/|meet\.jit\.si/|[\w-]+\.my\.webex\.com/|'
                     r'facetime\.apple\.com/join|app\.slack\.com/huddle/)[^\s<>"]+', re.I)


def join_link(e):
    m = JOIN_RE.search(' '.join(str(e.get(k) or '') for k in ('url', 'location', 'notes')))
    return m.group(0)[:500] if m else None


def _addr(a):
    mail = str((a or {}).get('email') or '')
    if not mail and str((a or {}).get('url') or '').lower().startswith('mailto:'):
        mail = str(a['url'])[7:]
    return mail.strip().lower()


def meeting_kind(e, cal_cfg):
    """Why an event is a meeting – 'join' (a Meet/Teams/Zoom … link), 'invite' (someone else organised it),
    'people' (other attendees) – or None.
    A private (family) calendar counts only with a join link – or, when the calendar lists its "family" addresses in
    actions-config, an organizer or attendee outside that list. Without the list, people alone never make a family
    event a meeting (a daily reading with the children, a dinner a partner put in). "meetings": false on a calendar
    never counts; "meetings": true counts like a work calendar."""
    cal_cfg = cal_cfg or {}
    if cal_cfg.get('meetings') is False:
        return None
    if join_link(e):
        return 'join'
    others = [a for a in e.get('attendees') or [] if isinstance(a, dict) and not a.get('is_current_user')]
    org = e.get('organizer') if isinstance(e.get('organizer'), dict) else None
    someone_else = bool(org and org.get('is_current_user') is False and (_addr(org) or org.get('name')))
    if cal_cfg.get('kind') == 'private' and cal_cfg.get('meetings') is not True:
        family = {str(x).strip().lower() for x in cal_cfg.get('family') or [] if x}
        if not family:
            return None
        outside = lambda a: bool(_addr(a)) and _addr(a) not in family
        if someone_else and outside(org):
            return 'invite'
        return 'people' if any(outside(a) for a in others) else None
    if someone_else:
        return 'invite'
    return 'people' if others else None


def shape(e, kinds):
    cal = str(e.get('calendar_title') or '')
    k = kinds.get(cal) or {}
    return {
        'id': str(e.get('id') or '')[:200], 'title': _clip(e.get('title'), 300) or '(no title)',
        'start': e.get('start_date'), 'end': e.get('end_date'), 'all_day': bool(e.get('is_all_day')),
        'location': _clip(e.get('location'), 300), 'notes': _clip(e.get('notes'), 3000), 'url': _clip(e.get('url'), 500),
        'calendar': cal, 'calendar_label': k.get('label') or cal, 'ctx': k.get('kind') if k.get('kind') in ('work', 'private') else None,
        'recurring': bool(e.get('is_recurring')), 'availability': e.get('availability'),
        'attendees': len([a for a in e.get('attendees') or [] if not a.get('is_current_user')]),
        'people': people(e.get('attendees')),
        'deep_link': _clip(e.get('deep_link'), 500) if str(e.get('deep_link') or '').startswith('ical://') else None,
        'status': e.get('status'),
        'meeting': meeting_kind(e, k), 'join': join_link(e),
    }


def invalidate():
    """Forget what was read – after Axella changed the calendar (an event added, moved, an invite accepted)."""
    with _lock:
        _cache.clear()


def events(mcp_file, calendars_cfg, start, end, now=None, client=None, fresh=False):
    """Events from start (inclusive) to end (exclusive), both YYYY-MM-DD, sorted by start. fresh: read Calendar now."""
    try:
        a, b = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError):
        raise CalendarError('dates as YYYY-MM-DD')
    if not a < b or (b - a).days > MAX_DAYS:
        raise CalendarError('at most %d days at a time' % MAX_DAYS)
    key = (start, end)
    with _lock:
        hit = _cache.get(key)
        if hit and not fresh and (now or time.time()) - hit[0] < CACHE_SECS:
            return hit[1]
    kinds = {str(c.get('name')): c for c in calendars_cfg or [] if isinstance(c, dict)}
    tz = datetime.now().astimezone().tzinfo
    s = datetime(a.year, a.month, a.day, tzinfo=tz).isoformat()
    e = datetime(b.year, b.month, b.day, tzinfo=tz).isoformat()
    mcp = client
    if mcp is None:
        cmd, env = macuse_command(mcp_file)
        mcp = Mcp(cmd, env).open()
    out = []
    try:
        for page in range(MAX_PAGES):
            res = mcp.request('tools/call', {'name': 'calendar_search_events', 'arguments': {
                'start_date': s, 'end_date': e, 'limit': PAGE, 'offset': page * PAGE}})
            d = (_payload(res).get('data') or {})
            out += [shape(x, kinds) for x in d.get('events') or [] if isinstance(x, dict)]
            if not (d.get('pagination') or {}).get('has_more'):
                break
    finally:
        if client is None:
            mcp.close()
    seen, uniq = set(), []
    for x in sorted(out, key=lambda x: (str(x['start']), x['title'])):
        k = (x['id'], x['start'])
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    result = {'from': start, 'to': end, 'events': uniq,
              'calendars': sorted({(x['calendar'], x['calendar_label'], x['ctx'] or '') for x in uniq})}
    result['calendars'] = [{'name': n, 'label': l, 'ctx': c or None} for n, l, c in result['calendars']]
    with _lock:
        _cache[key] = (now or time.time(), result)
        for k in [k for k, v in _cache.items() if time.time() - v[0] > 600]:
            _cache.pop(k, None)
    return result


def default_range(today=None):
    t = today or date.today()
    return t.isoformat(), (t + timedelta(days=14)).isoformat()


# ---------- editing (owner only – checked in axella-actions.py): your own events, no invitees ----------
# Through Macuse's calendar tools. Their argument shapes (event reference, scope, reschedule strategy) are read from
# Macuse itself (tools/list) and kept in state/macuse-calendar-tools.json, so a Macuse update can't silently send
# the wrong thing: if a shape isn't understood, editing says so and does nothing.
_schema_cache = {}


def _client(mcp_file):
    cmd, env = macuse_command(mcp_file)
    return Mcp(cmd, env).open()


def tool_schemas(mcp, cache_file=None):
    if _schema_cache.get('at', 0) > time.time() - 6 * 3600:
        return _schema_cache['tools']
    res = mcp.request('tools/list', {})
    tools = {t.get('name'): t.get('inputSchema') or {} for t in res.get('tools') or [] if str(t.get('name', '')).startswith('calendar_')}
    _schema_cache.update(at=time.time(), tools=tools)
    if cache_file:
        try:
            with open(cache_file + '.tmp', 'w', encoding='utf-8') as f:
                json.dump(tools, f, indent=1)
            os.replace(cache_file + '.tmp', cache_file)
        except OSError:
            pass
    return tools


def _defs(schema):
    return schema.get('$defs') or schema.get('definitions') or {}


def _resolve(node, defs):
    seen = 0
    while isinstance(node, dict) and '$ref' in node and seen < 10:
        node = defs.get(node['$ref'].split('/')[-1], {})
        seen += 1
    return node if isinstance(node, dict) else {}


def _variants(node, defs):
    node = _resolve(node, defs)
    for k in ('oneOf', 'anyOf'):
        if k in node:
            return [_resolve(v, defs) for v in node[k]]
    return [node]


def _consts(node, defs):
    out = []
    for v in _variants(node, defs):
        if 'const' in v:
            out.append(v['const'])
        out += list(v.get('enum') or [])
    return [x for x in out if isinstance(x, str)]


def event_ref(schema, eid, start):
    """The "event" argument: an id string, or an object with the id (and the occurrence's start, if asked for)."""
    defs = _defs(schema)
    node = (schema.get('properties') or {}).get('event') or {}
    for v in _variants(node, defs):
        if v.get('type') == 'string':
            return eid
        props = v.get('properties') or {}
        key = next((k for k in ('id', 'event_id', 'identifier') if k in props), None)
        if key:
            ref = {key: eid}
            for k in ('occurrence_date', 'occurrence_start', 'start_date', 'occurrence'):
                if k in props and start:
                    ref[k] = start
                    break
            tkey = next((k for k in ('type', 'by') if k in props), None)
            if tkey:
                c = _consts(props[tkey], defs)
                if c:
                    ref[tkey] = next((x for x in c if 'id' in x.lower()), c[0])
            return ref
    raise CalendarError('this Macuse version names events differently – editing is off until Axella is updated')


def event_scope(schema, which):
    defs = _defs(schema)
    node = (schema.get('properties') or {}).get('scope')
    if not node:
        if which == 'future':
            raise CalendarError('this Macuse version can only change one occurrence')
        return None
    vals = _consts(node, defs)
    want = ('future', 'following', 'all') if which == 'future' else ('this', 'single', 'occurrence', 'only')
    for w in want:
        for v in vals:
            if w in v.lower():
                return v
    raise CalendarError('this Macuse version names "this / future" differently – editing is off until Axella is updated')


def shift_strategy(schema, start, end):
    """Reschedule to an absolute new start/end."""
    defs = _defs(schema)
    node = (schema.get('properties') or {}).get('strategy') or {}
    for v in _variants(node, defs):
        props = v.get('properties') or {}
        sk = next((k for k in ('start_date', 'new_start', 'new_start_date', 'start') if k in props), None)
        ek = next((k for k in ('end_date', 'new_end', 'new_end_date', 'end') if k in props), None)
        if sk:
            out = {sk: start}
            if ek:
                out[ek] = end
            for tk in ('type', 'kind', 'mode', 'strategy'):
                if tk in props:
                    c = _consts(props[tk], defs)
                    if not c:
                        break
                    out[tk] = c[0]
            return out
        # a wrapper object, e.g. {"absolute": {start_date, end_date}}
        for wk, wv in props.items():
            inner = _resolve(wv, defs).get('properties') or {}
            sk = next((k for k in ('start_date', 'new_start', 'start') if k in inner), None)
            if sk:
                ek = next((k for k in ('end_date', 'new_end', 'end') if k in inner), None)
                return {wk: {sk: start, **({ek: end} if ek else {})}}
    raise CalendarError('this Macuse version reschedules differently – editing is off until Axella is updated')


def _call(mcp, name, args):
    res = mcp.request('tools/call', {'name': name, 'arguments': args})
    if res.get('isError'):
        txt = ' '.join(c.get('text', '') for c in res.get('content') or [] if c.get('type') == 'text')
        raise CalendarError('Calendar said: %s' % (txt.strip()[:200] or 'refused'))
    try:
        return _payload(res)
    except CalendarError:
        return {}


def calendars(mcp):
    d = _call(mcp, 'calendar_list_calendars', {}).get('data') or {}
    return [c for c in d.get('calendars') or [] if isinstance(c, dict)]


def find_event(mcp, eid, start):
    s = datetime.fromisoformat(str(start).replace('Z', '+00:00'))
    d = _call(mcp, 'calendar_search_events', {'start_date': (s - timedelta(days=1)).isoformat(),
                                              'end_date': (s + timedelta(days=1)).isoformat(), 'limit': 100}).get('data') or {}
    same = [e for e in d.get('events') or [] if e.get('id') == eid]
    want = _norm_t(start)
    for e in same:                                      # a repeating event: the occurrence that starts then
        if want and _norm_t(e.get('start_date')) == want:
            return e
    if same:
        return same[0]
    raise CalendarError('that event is not in the calendar any more')


def _norm_t(v):
    try:
        return datetime.fromisoformat(str(v).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError):
        return None


def _time(v, what):
    try:
        return datetime.fromisoformat(str(v).replace('Z', '+00:00')).isoformat()
    except (TypeError, ValueError):
        raise CalendarError('the %s time is not a date and time' % what)


def _text(v, n, what):
    v = str(v or '').strip()
    if len(v) > n or any(ord(c) < 32 and c not in '\n\t' for c in v):
        raise CalendarError('the %s can only be plain text (max %d)' % (what, n))
    return v or None


def caps(mcp_file, cache_file=None, client=None):
    """What the Calendar page may offer: editable calendars (by account), and whether Macuse's shapes are understood."""
    mcp = client or _client(mcp_file)
    try:
        tools = tool_schemas(mcp, cache_file)
        problems = []
        for name, test in (('calendar_update_event', lambda s: (event_ref(s, 'x', None), event_scope(s, 'this'), event_scope(s, 'future'))),
                           ('calendar_reschedule_event', lambda s: shift_strategy(s, 'a', 'b')),
                           ('calendar_cancel_event', lambda s: event_ref(s, 'x', None)),
                           ('calendar_create_event', lambda s: s)):
            if name not in tools:
                problems.append(name + ' missing')
                continue
            try:
                test(tools[name])
            except CalendarError as e:
                problems.append(str(e))
        cals = [{'title': c.get('title'), 'id': c.get('id'), 'source': c.get('source'), 'can_modify': bool(c.get('can_modify'))}
                for c in calendars(mcp)]
        return {'can_edit': not problems, 'problems': problems[:3], 'calendars': cals}
    finally:
        if client is None:
            mcp.close()


def edit(mcp_file, calendars_cfg, action, p, backup_dir, client=None, cache_file=None):
    invalidate()
    mcp = client or _client(mcp_file)
    try:
        tools = tool_schemas(mcp, cache_file)
        cals = calendars(mcp)
        by_title = {c.get('title'): c for c in cals}

        def writable(title):
            c = by_title.get(title)
            if not c or not c.get('can_modify'):
                raise CalendarError('that calendar can\'t be changed from here')
            return c

        if action == 'cal_add':
            title = _text(p.get('title'), 300, 'title')
            if not title:
                raise CalendarError('give the event a title')
            cal = writable(str(p.get('calendar') or ''))
            s, e = _time(p.get('start'), 'start'), _time(p.get('end'), 'end')
            if e < s:
                raise CalendarError('the event ends before it starts')
            args = {'title': title, 'start_date': s, 'end_date': e, 'is_all_day': bool(p.get('all_day')),
                    'calendar': cal.get('title'), 'location': _text(p.get('location'), 300, 'place'), 'notes': _text(p.get('notes'), 3000, 'notes')}
            if p.get('url'):                     # an online meeting's join link (made or checked by calendar_online.py)
                import meeting_providers
                try:
                    args['url'] = meeting_providers.check_link(p['url'])
                except meeting_providers.Bad as e:
                    raise CalendarError(str(e))
            d = _call(mcp, 'calendar_create_event', {k: v for k, v in args.items() if v is not None})
            ev = (d.get('data') or {}).get('event') or d.get('data') or {}
            _cache.clear()
            return {'id': ev.get('id'), 'title': title}

        if action == 'cal_restore':
            bid = str(p.get('backup') or '')
            if not re.match(r'^\d{8}-\d{6}-[A-Za-z0-9]{1,16}$', bid):
                raise CalendarError('unknown backup')
            try:
                with open(os.path.join(backup_dir, bid + '.json'), encoding='utf-8') as f:
                    b = json.load(f)
            except (OSError, ValueError):
                raise CalendarError('that backup is gone (kept 90 days)')
            raw = b.get('event') or {}
            cal = by_title.get(raw.get('calendar_title')) or {}
            if not cal.get('can_modify'):
                raise CalendarError('the event\'s calendar can\'t be changed from here any more')
            args = {'title': raw.get('title') or '(no title)', 'start_date': raw.get('start_date'), 'end_date': raw.get('end_date'),
                    'is_all_day': bool(raw.get('is_all_day')), 'calendar': cal.get('title'), 'location': raw.get('location'),
                    'notes': raw.get('notes'), 'url': raw.get('url')}
            if b.get('scope') == 'future' and isinstance(raw.get('recurrence'), dict):
                args['recurrence'] = raw['recurrence']
            d = _call(mcp, 'calendar_create_event', {k: v for k, v in args.items() if v is not None})
            _cache.clear()
            return {'id': ((d.get('data') or {}).get('event') or {}).get('id'), 'title': args['title']}

        eid, start = str(p.get('id') or ''), str(p.get('start') or '')
        if not eid or len(eid) > 200:
            raise CalendarError('unknown event')
        raw = find_event(mcp, eid, start)
        if [a for a in raw.get('attendees') or [] if not a.get('is_current_user')]:
            raise CalendarError('this meeting has other people on it – change it in Calendar, so they are told')
        writable(raw.get('calendar_title'))
        scope = 'future' if p.get('scope') == 'future' else 'this'
        if action == 'cal_delete':
            os.makedirs(backup_dir, mode=0o700, exist_ok=True)
            os.chmod(backup_dir, 0o700)
            bid = time.strftime('%Y%m%d-%H%M%S') + '-' + re.sub(r'[^A-Za-z0-9]', '', eid)[:16]
            with open(os.path.join(backup_dir, bid + '.json'), 'w', encoding='utf-8') as f:
                json.dump({'deleted': time.time(), 'scope': scope, 'event': raw}, f, ensure_ascii=False)
            os.chmod(os.path.join(backup_dir, bid + '.json'), 0o600)
            s = tools['calendar_cancel_event']
            args = {'event': event_ref(s, eid, raw.get('start_date'))}
            if raw.get('is_recurring'):
                args['scope'] = event_scope(s, scope)
            _call(mcp, 'calendar_cancel_event', {k: v for k, v in args.items() if v is not None})
            _cache.clear()
            return {'id': eid, 'title': raw.get('title'), 'backup': bid}

        if action == 'cal_update':
            s = tools['calendar_update_event']
            args = {'event': event_ref(s, eid, raw.get('start_date'))}
            if raw.get('is_recurring'):
                args['scope'] = event_scope(s, scope)
            changed = False
            for k, n, what in (('title', 300, 'title'), ('location', 300, 'place'), ('notes', 3000, 'notes')):
                if k in p:
                    v = _text(p.get(k), n, what)
                    if k == 'title' and not v:
                        raise CalendarError('the event needs a title')
                    args[k] = v if v is not None else ''
                    changed = True
            if 'all_day' in p:
                args['is_all_day'] = bool(p['all_day'])
                changed = True
            if p.get('calendar') and p['calendar'] != raw.get('calendar_title'):
                to = writable(str(p['calendar']))
                frm = by_title.get(raw.get('calendar_title')) or {}
                if to.get('source') != frm.get('source'):
                    raise CalendarError('events can only move between calendars of the same account (%s → %s isn\'t possible)'
                                        % (frm.get('source') or '?', to.get('source') or '?'))
                args['calendar'] = to.get('title')
                changed = True
            if changed:
                _call(mcp, 'calendar_update_event', args)
            if p.get('new_start') and p.get('new_end'):
                ns, ne = _time(p['new_start'], 'start'), _time(p['new_end'], 'end')
                if ne < ns:
                    raise CalendarError('the event ends before it starts')
                rs = tools['calendar_reschedule_event']
                rargs = {'event': event_ref(rs, eid, raw.get('start_date')), 'strategy': shift_strategy(rs, ns, ne)}
                if raw.get('is_recurring'):
                    rargs['scope'] = event_scope(rs, scope)
                _call(mcp, 'calendar_reschedule_event', rargs)
            _cache.clear()
            return {'id': eid, 'title': args.get('title') or raw.get('title')}
        raise CalendarError('unknown action')
    finally:
        if client is None:
            mcp.close()
