"""Briefings: research and news briefs on the owner's schedule (dev request claude/dev-request-briefings.md, step 1).

A briefing is a topic + schedule. At its time the scheduler queues a "briefing" run: a headless Claude run that may
ONLY search and read the web (WebSearch / WebFetch) and write one result file – no Mail, Messages, Calendar or other
files. Web pages are untrusted data, so that run has nothing of the owner's to leak or act on. When the briefing uses
personal context, a second, offline run ("briefing-personal") reads the finished brief plus the calendar/projects and
adds a short personal note – it has no web access, so nothing personal can end up in a search query.

Python does the rest: checks the result, drops anything the briefing already told (same link, or nearly the same
headline, over its last runs), keeps at most `length` items, makes sure the spoken text has no links, and stores it.

Files (all in state/, never in git):
  briefings.json                       – the briefings (seeded with two the first time)
  briefing/<ref>.request.json          – what one run is asked to do (no personal data)
  briefing/<ref>.json                  – the run's result
  briefing/<ref>.personal.json         – the offline personal note (only when personal context is on)
  briefs/<briefing id>/<YYYY-MM-DD-HHMMSS>.json – stored briefs, newest last
"""
import datetime
import glob
import json
import os
import re
import threading
import uuid
from urllib.parse import urlparse

MAX_BRIEFINGS = 8
MAX_ITEMS = 8
DEDUPE_RUNS = 4             # "no item repeats a story from the previous 4 runs"
KEEP_BRIEFS = 60            # per briefing
LOCK = threading.Lock()
DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

SEED = [
    {'id': 'sports-tech', 'name': 'Sports technology', 'kind': 'research',
     'prompt': 'What happened this week in sports technology: timing and tracking, race and event tech, wearables, '
               'athlete data, fan and broadcast tech. Prefer news from companies and events over opinion pieces.',
     'sources': [], 'days': [0], 'time': '07:30', 'length': 5, 'language': 'en', 'voice': True,
     'personal': False, 'enabled': True},
    {'id': 'city-weekend', 'name': 'Example City this weekend', 'kind': 'research',
     'prompt': "What's on in Example City this coming weekend (Friday evening to Sunday): concerts, exhibitions, "
               'markets, food, sport and family-friendly things. Include where and when.',
     'sources': [], 'days': [4], 'time': '15:30', 'length': 5, 'language': 'en', 'voice': True,
     'personal': True, 'enabled': True},
]


class Bad(Exception):
    pass


def _now():
    return datetime.datetime.now().astimezone()


def _iso(dt=None):
    return (dt or _now()).isoformat(timespec='seconds')


def _hm(s):
    h, m = str(s).split(':')
    h, m = int(h), int(m)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError
    return h * 60 + m


def _norm_url(u):
    try:
        p = urlparse(str(u or '').strip())
    except ValueError:
        return ''
    host = (p.hostname or '').lower()
    if host.startswith('www.'):
        host = host[4:]
    path = re.sub(r'/(index\.html?|amp)?$', '', p.path or '')
    return host + path


_STOP = set('the a an of in on at to for and or is are was were with from by as it its this that these those new '
            'den det de en et og i på til for med af er var som har kan vil om fra ved'.split())


def _words(t):
    return {w for w in re.findall(r'[a-z0-9æøåäöüé]+', str(t or '').lower()) if len(w) > 2 and w not in _STOP}


def _similar(a, b):
    wa, wb = _words(a), _words(b)
    if len(wa) < 3 or len(wb) < 3:
        return False
    return len(wa & wb) / len(wa | wb) >= 0.55


class Briefings:
    def __init__(self, state_dir):
        self.state_dir = state_dir
        self.cfg_file = os.path.join(state_dir, 'briefings.json')
        self.req_dir = os.path.join(state_dir, 'briefing')
        self.brief_dir = os.path.join(state_dir, 'briefs')

    # ---------- configuration ----------
    def load(self):
        try:
            with open(self.cfg_file, encoding='utf-8') as f:
                d = json.load(f)
            if isinstance(d.get('briefings'), list):
                return d
        except (OSError, ValueError):
            pass
        d = {'briefings': [dict(b) for b in SEED]}
        self._save(d)
        return d

    def _save(self, d):
        tmp = self.cfg_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.cfg_file)

    def get(self, bid):
        return next((b for b in self.load()['briefings'] if b['id'] == bid), None)

    @staticmethod
    def clean(p, old=None):
        b = dict(old or {})
        name = str(p.get('name', b.get('name', ''))).strip()[:60]
        prompt = str(p.get('prompt', b.get('prompt', ''))).strip()[:1500]
        if not name or not prompt:
            raise Bad('a briefing needs a name and what to look for')
        kind = p.get('kind', b.get('kind', 'research'))
        if kind not in ('research', 'news'):
            raise Bad('kind must be research or news')
        tm = str(p.get('time', b.get('time', '07:30')))
        try:
            _hm(tm)
        except (ValueError, TypeError):
            raise Bad('time must be HH:MM')
        days = sorted({int(x) for x in p.get('days', b.get('days', [0])) if str(x).isdigit() and 0 <= int(x) <= 6})
        if not days:
            raise Bad('pick at least one day')
        sources = []
        for s in (p.get('sources', b.get('sources', [])) or [])[:12]:
            s = str(s).strip()[:200]
            if s and not re.search(r'[\s<>"]', s):
                sources.append(s)
        try:
            length = max(3, min(MAX_ITEMS, int(p.get('length', b.get('length', 5)))))
        except (ValueError, TypeError):
            length = 5
        lang = p.get('language', b.get('language', 'en'))
        b.update({'name': name, 'kind': kind, 'prompt': prompt, 'sources': sources, 'days': days, 'time': tm,
                  'length': length, 'language': lang if lang in ('en', 'da') else 'en',
                  'voice': bool(p.get('voice', b.get('voice', True))), 'personal': bool(p.get('personal', b.get('personal', False))),
                  'enabled': bool(p.get('enabled', b.get('enabled', True)))})
        return b

    def save(self, p):
        with LOCK:
            d = self.load()
            bid = str(p.get('id') or '')
            old = next((b for b in d['briefings'] if b['id'] == bid), None) if bid else None
            b = self.clean(p, old)
            if not old:
                if len(d['briefings']) >= MAX_BRIEFINGS:
                    raise Bad('at most %d briefings – Axella is not a news app' % MAX_BRIEFINGS)
                slug = re.sub(r'[^a-z0-9]+', '-', b['name'].lower()).strip('-')[:24] or 'brief'
                b['id'] = slug if not any(x['id'] == slug for x in d['briefings']) else slug + '-' + uuid.uuid4().hex[:4]
                d['briefings'].append(b)
            else:
                d['briefings'] = [b if x['id'] == bid else x for x in d['briefings']]
            self._save(d)
            return b

    def delete(self, bid):
        """Removes the briefing from the list; its stored briefs stay in state/briefs/<id>/ (nothing is thrown away)."""
        with LOCK:
            d = self.load()
            n = len(d['briefings'])
            d['briefings'] = [b for b in d['briefings'] if b['id'] != bid]
            if len(d['briefings']) == n:
                raise Bad('no such briefing')
            self._save(d)
        return 'deleted'

    # ---------- schedule ----------
    def slots_for(self, day):
        """[(briefing id, 'HH:MM', name)] due on this date."""
        return [(b['id'], b['time'], b['name']) for b in self.load()['briefings']
                if b.get('enabled') and day.weekday() in b.get('days', [])]

    def next_run(self, b, now=None):
        if not b.get('enabled'):
            return None
        now = now or _now()
        for i in range(8):
            day = (now + datetime.timedelta(days=i)).date()
            if day.weekday() in b['days']:
                t = datetime.datetime.combine(day, datetime.time(*divmod(_hm(b['time']), 60))).astimezone()
                if t > now:
                    return _iso(t)
        return None

    # ---------- briefs ----------
    def briefs(self, bid, limit=20):
        if not re.match(r'^[a-z0-9-]{1,40}$', bid or ''):
            raise Bad('bad briefing id')
        out = []
        for p in sorted(glob.glob(os.path.join(self.brief_dir, bid, '*.json')))[-limit:][::-1]:
            try:
                with open(p, encoding='utf-8') as f:
                    out.append(json.load(f))
            except (OSError, ValueError):
                pass
        return out

    def overview(self):
        d = self.load()
        out = []
        for b in d['briefings']:
            latest = self.briefs(b['id'], 1)
            out.append({**b, 'next_run': self.next_run(b), 'latest': latest[0] if latest else None})
        return {'briefings': out, 'max': MAX_BRIEFINGS}

    def recent(self, since=None, limit=10):
        """Briefs that arrived after `since` (ISO), newest first – for the Today card and the Listen queue."""
        out = []
        for p in glob.glob(os.path.join(self.brief_dir, '*', '*.json')):
            try:
                with open(p, encoding='utf-8') as f:
                    br = json.load(f)
            except (OSError, ValueError):
                continue
            if not since or (br.get('at') or '') > since:
                out.append(br)
        return sorted(out, key=lambda x: x.get('at') or '', reverse=True)[:limit]

    # ---------- a run ----------
    def request(self, bid):
        """Write the request for one run. Only the topic, sources, language, length and what was already told go in –
        nothing personal (that is added later, offline). Returns the ref."""
        b = self.get(bid)
        if not b:
            raise Bad('no such briefing')
        told = []
        for br in self.briefs(bid, DEDUPE_RUNS):
            for it in br.get('items') or []:
                told.append({'title': it.get('title'), 'url': it.get('url')})
        ref = 'br' + _now().strftime('%Y%m%d%H%M%S') + uuid.uuid4().hex[:4]
        os.makedirs(self.req_dir, exist_ok=True)
        last = self.briefs(bid, 1)
        req = {'id': ref, 'briefing': bid, 'at': _iso(), 'name': b['name'], 'kind': b['kind'], 'prompt': b['prompt'],
               'sources': b['sources'], 'length': b['length'], 'language': b['language'],
               'since': last[0]['at'] if last else None, 'already_told': told[:60]}
        with open(os.path.join(self.req_dir, ref + '.request.json'), 'w', encoding='utf-8') as f:
            json.dump(req, f, ensure_ascii=False, indent=1)
        return ref

    def _read(self, name):
        with open(os.path.join(self.req_dir, name), encoding='utf-8') as f:
            return json.load(f)

    def check(self, ref):
        """None when the run's result is usable, else a short reason (shown on the run)."""
        try:
            r = self._read(ref + '.json')
        except FileNotFoundError:
            return 'finished but wrote no brief'
        except ValueError as e:
            return 'the brief is not valid JSON (%s)' % str(e)[:80]
        if not isinstance(r.get('items'), list):
            return 'the brief has no "items" list'
        return None

    def finish(self, ref, personal=False, outbound=None):
        """Store the brief: drop repeats and anything without a working link, cap the length, keep links out of the
        spoken text. Returns the stored brief."""
        req = self._read(ref + '.request.json')
        r = self._read(ref + '.json')
        b = self.get(req['briefing']) or {'name': req['name'], 'length': req['length'], 'personal': False}
        told = [it for br in self.briefs(req['briefing'], DEDUPE_RUNS) for it in br.get('items') or []]
        seen_urls = {_norm_url(t.get('url')) for t in told} - {''}
        items, dropped = [], []
        for it in r.get('items') or []:
            if not isinstance(it, dict):
                continue
            url = str(it.get('url') or '').strip()
            title = str(it.get('title') or '').strip()[:200]
            if not title or not re.match(r'^https?://[^\s<>"]+$', url):
                dropped.append(title or '(no title)')
                continue
            if _norm_url(url) in seen_urls or any(_similar(title, t.get('title')) for t in told + items):
                dropped.append(title)
                continue
            src = str(it.get('source') or urlparse(url).hostname or '').replace('www.', '')[:60]
            items.append({'title': title, 'summary': str(it.get('summary') or '').strip()[:600], 'url': url,
                          'source': src, 'published': str(it.get('published') or '')[:30] or None})
            seen_urls.add(_norm_url(url))
            if len(items) >= max(3, min(MAX_ITEMS, int(b.get('length') or 5))):
                break
        nothing = not items
        headline = str(r.get('headline') or '').strip()[:200]
        if nothing:
            headline = '%s: nothing new %s' % (req['name'], 'since the last brief' if req.get('since') else 'right now')
        spoken = str(r.get('spoken') or '').strip()
        if nothing or not spoken:
            spoken = headline + '.' if nothing else headline + '. ' + ' '.join('%s. %s Source: %s.' % (i['title'], i['summary'], i['source']) for i in items)
        spoken = re.sub(r'https?://\S+|www\.\S+', '', spoken)                     # never read links aloud
        spoken = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', spoken).replace('**', '').strip()[:6000]
        at = _now()
        brief = {'id': at.strftime('%Y-%m-%d-%H%M%S'), 'briefing': req['briefing'], 'name': req['name'], 'kind': req['kind'],
                 'at': _iso(at), 'run': ref, 'headline': headline, 'nothing_new': nothing, 'items': items,
                 'spoken': spoken, 'personal_note': None, 'language': req.get('language', 'en'),
                 # what left this Mac, taken from the run's actual tool calls (scheduler) – never the model's own list
                 'outbound': {'provider': 'Claude web search',
                              'queries': [str(q)[:200] for q in (outbound or {}).get('queries') or []][:50],
                              # web addresses from the run's tool calls (model-controlled): http(s) only
                              'urls': [str(u)[:300] for u in (outbound or {}).get('fetched') or []
                                       if re.match(r'^https?://[^\s<>"]+$', str(u))][:50],
                              'fetched': len((outbound or {}).get('fetched') or [])},
                 'dropped': dropped[:20]}
        self._store(brief)
        return brief

    def _store(self, brief):
        d = os.path.join(self.brief_dir, brief['briefing'])
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, brief['id'] + '.json')
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(brief, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
        olds = sorted(glob.glob(os.path.join(d, '*.json')))[:-KEEP_BRIEFS]
        arch = os.path.join(self.brief_dir, '_archive', brief['briefing'])
        for o in olds:                                  # moved, not deleted
            os.makedirs(arch, exist_ok=True)
            os.replace(o, os.path.join(arch, os.path.basename(o)))

    def needs_personal(self, ref):
        req = self._read(ref + '.request.json')
        b = self.get(req['briefing'])
        return bool(b and b.get('personal'))

    def check_personal(self, ref):
        try:
            p = self._read(ref + '.personal.json')
        except FileNotFoundError:
            return 'finished but wrote no personal note'
        except ValueError as e:
            return 'the personal note is not valid JSON (%s)' % str(e)[:80]
        return None if isinstance(p, dict) else 'the personal note is not an object'

    def finish_personal(self, ref):
        """Add the offline personal note to the brief that run `ref` stored."""
        p = self._read(ref + '.personal.json')
        note = re.sub(r'https?://\S+', '', str(p.get('note') or '')).strip()[:400] or None
        req = self._read(ref + '.request.json')
        for path in sorted(glob.glob(os.path.join(self.brief_dir, req['briefing'], '*.json')))[::-1]:
            with open(path, encoding='utf-8') as f:
                br = json.load(f)
            if br.get('run') == ref:
                br['personal_note'] = note
                if note and br.get('spoken'):
                    br['spoken'] = br['spoken'].rstrip() + ' ' + note
                tmp = path + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(br, f, ensure_ascii=False, indent=1)
                os.replace(tmp, path)
                return br
        return None
