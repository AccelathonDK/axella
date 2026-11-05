"""Report a problem – saved at home first, sent only on a separate tap (docs/REPORTS.md).

Every report is saved in reports/<id>/ on the Mac mini (not in git, not readable by Claude runs):
  report.json   – what the user wrote, the class, the route, the action trail, the errors, the metadata, the status
  render.png    – the privacy render: the screen's layout with every content string replaced (made in the browser)
  full.png      – developer mode only: the real screen

Two modes ("reports" in setup/actions-config.json):
  developer – the owner's own instance: the full report stays in reports/ for the development thread to read.
              Nothing goes out. Also shows the triage of community reports (when "triage_token" is set up).
  community – the default: "Send" posts the ANONYMISED payload (payload(), an allow-list) to the intake
              (axella.dev/api/report by default). The same allow-list is checked again by the intake.

What may leave is decided here by an allow-list – never by scrubbing what's there:
  class, text (the user's own words, checked before send), route, trail (action names), errors (templates, own code
  frames), meta (version, commit, OS, Mac model, RAM tier, connector types, theme, locale), render (privacy PNG),
  install (a random, rotatable token for rate limiting – not tied to the person), reply (optional, separate).
"""
import base64
import datetime
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import urllib.error
import urllib.request

CLASSES = ('critical', 'annoying', 'cosmetic', 'missing')
CONNECTORS = ('mail', 'imessage', 'whatsapp', 'signal', 'calendar', 'calls', 'linkedin')
META_KEYS = ('app_version', 'commit', 'os', 'os_version', 'mac_model', 'ram_tier', 'connectors', 'theme', 'locale')
TRAIL_ITEM = re.compile(r'^[a-z][a-z0-9_]{0,30}:[a-z0-9_.-]{1,40}$')
ROUTE = re.compile(r'^[a-z][a-z0-9_:-]{0,39}$')
FRAME = re.compile(r'^[\w$.<>\[\] -]{0,80}\(?(assets/)?index-[\w-]+\.js:\d+:\d+\)?$|^[\w$.<> -]{1,80}$')
MAX_TEXT, MAX_RENDER = 4000, 1_500_000
INTAKE_RENDER = 400_000            # intake/src/schema.js MAX_RENDER
LOCK = threading.Lock()


class Bad(Exception):
    pass


def _now():
    return datetime.datetime.now().astimezone()


# ---------- values out of messages: an error is sent as a template ----------
_VALUES = [
    (re.compile(r'https?://\S+'), '{url}'),
    (re.compile(r'[\w.+-]+@[\w-]+(\.[\w-]+)+'), '{email}'),
    (re.compile(r'(/Users|/home|/private|/var|~)/\S*'), '{path}'),
    (re.compile(r'"[^"]*"|“[^”]*”|\'[^\']*\'|‘[^’]*’'), '{text}'),
    (re.compile(r'\+?\d[\d\s().-]{5,}\d'), '{number}'),
    (re.compile(r'\b\d+\b'), '{n}'),
    (re.compile(r'\b[0-9a-f]{12,}\b', re.I), '{id}'),
]


def template(msg):
    """'Failed to parse message from "Lee Chen" (id 1234)' → 'Failed to parse message from {text} (id {n})'."""
    t = str(msg or '')[:500]
    for rx, rep in _VALUES:
        t = rx.sub(rep, t)
    # words that look like names (two capitalised words in a row) are values too
    t = re.sub(r'\b[A-ZÆØÅÄÖÜ][a-zæøåäöüé]+ [A-ZÆØÅÄÖÜ][a-zæøåäöüé]+\b', '{name}', t)
    return t[:300]


# ---------- the allow-list: the only shape that ever leaves ----------
def payload(report, install, include_render=True, reply=None):
    """The anonymised payload of a saved report. Raises Bad if anything doesn't fit the allow-list."""
    cls = report.get('class')
    if cls not in CLASSES:
        raise Bad('pick a class')
    text = str(report.get('text') or '').strip()
    if not text:
        raise Bad('say what happened')
    route = str(report.get('route') or 'unknown')
    if not ROUTE.match(route):
        route = 'unknown'
    trail = [t for t in (report.get('trail') or []) if isinstance(t, str) and TRAIL_ITEM.match(t)][-30:]
    errors = []
    for e in (report.get('errors') or [])[-20:]:
        if not isinstance(e, dict):
            continue
        frames = [f for f in (e.get('frames') or []) if isinstance(f, str) and FRAME.match(f)][:8]
        errors.append({'message': template(e.get('message')), 'frames': frames, 'source': 'server' if e.get('source') == 'server' else 'app'})
    m = report.get('meta') or {}
    meta = {}
    for k in META_KEYS:
        v = m.get(k)
        if k == 'connectors':
            meta[k] = sorted({c for c in (v or []) if c in CONNECTORS})
        elif isinstance(v, str) and re.match(r'^[\w .,+()/:-]{0,60}$', v) and not re.search(r'/Users|@|\\', v):
            meta[k] = v
        else:
            meta[k] = None
    out = {'v': 1, 'class': cls, 'text': text[:MAX_TEXT], 'route': route, 'trail': trail, 'errors': errors, 'meta': meta,
           'render': None, 'install': install}
    if include_render and report.get('_render_b64'):
        if len(report['_render_b64']) > MAX_RENDER * 4 // 3 + 100:
            raise Bad('the privacy render is too large')
        # the intake takes renders up to 400 kB (layout only); a bigger one is left out, the report still goes
        if len(report['_render_b64']) <= INTAKE_RENDER * 4 // 3 + 100:
            out['render'] = report['_render_b64']
    if reply:
        if not re.match(r'^[^@\s<>"]{1,64}@[\w-]+(\.[\w-]+)+$', reply) or len(reply) > 120:
            raise Bad('the reply address looks wrong')
        out['reply'] = reply
    return out


def check_text(text, names):
    """Spans in the user's text that look personal: e-mail, phone, card/IBAN-like numbers, personal URLs, and names
    from the owner's own contacts. The user decides – this only highlights."""
    text = str(text or '')
    flags = []

    def add(m, kind):
        flags.append({'start': m.start(), 'end': m.end(), 'kind': kind, 'text': m.group(0)[:80]})
    for m in re.finditer(r'[\w.+-]+@[\w-]+(\.[\w-]+)+', text):
        add(m, 'email')
    for m in re.finditer(r'\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}\b', text):
        add(m, 'iban')
    for m in re.finditer(r'\b(?:\d[ -]?){13,19}\b', text):
        add(m, 'card or account number')
    for m in re.finditer(r'(?<![\w-])\+?\d[\d ().-]{6,}\d', text):
        if not any(f['start'] <= m.start() < f['end'] for f in flags):
            add(m, 'phone number')
    for m in re.finditer(r'https?://[^\s/]+/\S+', text):
        add(m, 'link with a path')
    low = text.lower()
    for n in sorted({n.strip() for n in names if n and len(n.strip()) >= 3}, key=len, reverse=True):
        for part in [n] + [p for p in n.split() if len(p) >= 4]:
            i = 0
            while True:
                i = low.find(part.lower(), i)
                if i < 0:
                    break
                j = i + len(part)
                edge = (i == 0 or not text[i - 1].isalnum()) and (j >= len(text) or not text[j].isalnum())
                if edge and not any(f['start'] <= i < f['end'] for f in flags):
                    flags.append({'start': i, 'end': j, 'kind': 'name from your contacts', 'text': text[i:j]})
                i = j
    return sorted(flags, key=lambda f: f['start'])


def suggest_class(text):
    t = str(text or '').lower()
    if re.search(r'\b(crash\w*|lost|gone|data|won.?t (open|load|start)|can.?t (open|log|send)|error|broken|nothing works|blank|stuck|sent to the wrong)\b', t):
        return 'critical'
    if re.search(r'\b(would be (nice|great|useful)|could you add|please add|missing|wish|feature|support for|i want|i.?d like|option to)\b', t):
        return 'missing'
    if re.search(r'\b(colou?r|align\w*|spacing|typo|font|icon|overlap\w*|wrap\w*|pixel|looks? (odd|off|wrong))\b', t):
        return 'cosmetic'
    return 'annoying'


class Reports:
    def __init__(self, base, state_dir, config):
        self.base, self.state_dir, self.config = base, state_dir, config
        self.dir = os.path.join(base, 'reports')

    # ---------- settings ----------
    def settings(self):
        c = (self.config() or {}).get('reports') or {}
        return {'mode': 'developer' if c.get('mode') == 'developer' else 'community',
                'intake': c.get('intake') or 'https://axella.dev/api/report',
                'triage': bool(self._secret('report-triage-token'))}

    def _secret(self, name):
        try:
            with open(os.path.join(self.state_dir, name), encoding='utf-8') as f:
                return f.read().strip()
        except OSError:
            return ''

    def install_token(self, rotate=False):
        p = os.path.join(self.state_dir, 'report-install-token')
        t = '' if rotate else self._secret('report-install-token')
        if not t:
            t = secrets.token_hex(16)
            with open(p, 'w', encoding='utf-8') as f:
                f.write(t)
            os.chmod(p, 0o600)
        return t

    # ---------- what the Mac mini adds (allow-listed values only) ----------
    def context(self, accounts, extra_connectors=()):
        def sh(*a):
            try:
                return subprocess.run(a, capture_output=True, text=True, timeout=5).stdout.strip()
            except Exception:
                return ''
        mem = sh('/usr/sbin/sysctl', '-n', 'hw.memsize')
        gb = int(mem) / 2**30 if mem.isdigit() else 0
        tier = '' if not gb else '8 GB' if gb <= 8 else '16 GB' if gb <= 16 else '24 GB' if gb <= 24 else '32+ GB'
        conns = set(extra_connectors)
        if accounts:
            conns |= {'mail', 'calendar'}
        return {'mac_model': re.sub(r'[^\w,]', '', sh('/usr/sbin/sysctl', '-n', 'hw.model'))[:30] or None,
                'ram_tier': tier or None,
                'os_version': re.sub(r'[^\d.]', '', sh('/usr/bin/sw_vers', '-productVersion'))[:12] or None,
                'commit': re.sub(r'[^0-9a-f]', '', sh('/usr/bin/git', '-C', self.base, 'rev-parse', '--short', 'HEAD'))[:12] or None,
                'connectors': sorted(c for c in conns if c in CONNECTORS)}

    def server_errors(self, log_file, hours=24):
        """Errors the action service logged lately, as templates (action + message without values)."""
        out, cut = [], (_now() - datetime.timedelta(hours=hours)).isoformat()
        try:
            with open(log_file, encoding='utf-8', errors='replace') as f:
                lines = f.readlines()[-3000:]
        except OSError:
            return out
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            r = str(e.get('result') or '')
            if (e.get('at') or '') >= cut and r.startswith(('error', 'rejected')):
                out.append({'message': '%s: %s' % (re.sub(r'[^a-z_]', '', str(e.get('action') or ''))[:30], template(r)),
                            'frames': [], 'source': 'server'})
        seen, uniq = set(), []
        for e in reversed(out):
            if e['message'] not in seen:
                seen.add(e['message'])
                uniq.append(e)
        return uniq[:10]

    # ---------- the local store ----------
    def _path(self, rid, *f):
        if not re.match(r'^r\d{14}[0-9a-f]{4}$', str(rid or '')):
            raise Bad('bad report id')
        return os.path.join(self.dir, rid, *f)

    def save(self, p):
        """A new report (or an edit of a draft). Always saved before anything can be sent."""
        cls = p.get('class') if p.get('class') in CLASSES else None
        text = str(p.get('text') or '').strip()[:MAX_TEXT]
        if not text:
            raise Bad('say what happened')
        rid = p.get('id') or ('r' + _now().strftime('%Y%m%d%H%M%S') + secrets.token_hex(2))
        d = self._path(rid)
        with LOCK:
            os.makedirs(self.dir, exist_ok=True)
            os.chmod(self.dir, 0o700)
            os.makedirs(d, exist_ok=True)
            old = self._read(rid) or {}
            rep = {**old, 'id': rid, 'at': old.get('at') or _now().isoformat(timespec='seconds'), 'class': cls,
                   'suggested': p.get('suggested') if p.get('suggested') in CLASSES else old.get('suggested'),
                   'text': text, 'route': str(p.get('route') or old.get('route') or '')[:40],
                   'trail': [str(t)[:80] for t in (p.get('trail') or old.get('trail') or [])][-40:],
                   'errors': [e for e in (p.get('errors') or old.get('errors') or []) if isinstance(e, dict)][-30:],
                   'meta': p.get('meta') if isinstance(p.get('meta'), dict) else old.get('meta') or {},
                   'include_render': p.get('include_render', old.get('include_render', True)) is not False,
                   'status': old.get('status') or 'kept', 'mode': self.settings()['mode']}
            for key, name in (('render', 'render.png'), ('full', 'full.png')):
                if p.get(key):
                    if key == 'full' and rep['mode'] != 'developer':
                        continue                            # the real screen is only kept in developer mode
                    data = self._png(p[key])
                    with open(os.path.join(d, name), 'wb') as f:
                        f.write(data)
            rep['has_render'] = os.path.exists(os.path.join(d, 'render.png'))
            rep['has_full'] = os.path.exists(os.path.join(d, 'full.png'))
            self._write(rid, rep)
        return rep

    @staticmethod
    def _png(data_url):
        m = re.match(r'^data:image/png;base64,([A-Za-z0-9+/=]+)$', str(data_url or ''))
        if not m:
            raise Bad('the render must be a PNG')
        data = base64.b64decode(m.group(1))
        if len(data) > MAX_RENDER * 3 or data[:8] != b'\x89PNG\r\n\x1a\n':
            raise Bad('the render is not a usable PNG')
        return data

    def _read(self, rid):
        try:
            with open(self._path(rid, 'report.json'), encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _write(self, rid, rep):
        p = self._path(rid, 'report.json')
        with open(p + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
        os.chmod(p + '.tmp', 0o600)
        os.replace(p + '.tmp', p)

    def list(self):
        out = []
        if os.path.isdir(self.dir):
            for rid in sorted(os.listdir(self.dir), reverse=True):
                if rid.startswith('r'):
                    r = self._read(rid)
                    if r:
                        out.append({k: r.get(k) for k in ('id', 'at', 'class', 'text', 'route', 'status', 'mode', 'has_render',
                                                          'has_full', 'sent_at', 'code', 'status_url', 'issue_url', 'remote_status')})
        return out[:200]

    def get(self, rid):
        r = self._read(rid)
        if not r:
            raise Bad('no such report')
        return r

    def image(self, rid, kind):
        p = self._path(rid, 'full.png' if kind == 'full' else 'render.png')
        with open(p, 'rb') as f:
            return f.read()

    def discard(self, rid):
        """Moved to reports/_discarded/ – never deleted."""
        src = self._path(rid)
        if not os.path.isdir(src):
            raise Bad('no such report')
        dst = os.path.join(self.dir, '_discarded')
        os.makedirs(dst, exist_ok=True)
        shutil.move(src, os.path.join(dst, rid))
        return {'id': rid, 'status': 'discarded'}

    def preview(self, rid, reply=None):
        """Exactly what Send would post – shown in full before the tap."""
        r = self.get(rid)
        if r.get('include_render', True) and r.get('has_render'):
            r['_render_b64'] = base64.b64encode(self.image(rid, 'render')).decode()
        pl = payload(r, '<install token>', r.get('include_render', True), reply)
        if pl.get('render'):
            pl['render'] = '<privacy render, %d KB>' % (len(pl['render']) * 3 // 4 // 1024)
        return pl

    def send(self, rid, reply=None, post=None):
        """Developer mode: the full report already is in reports/ – marked sent. Community: the anonymised payload is
        posted to the intake; its code and status link are kept on the report."""
        r = self.get(rid)
        s = self.settings()
        if s['mode'] == 'developer':
            r.update(status='sent', sent_at=_now().isoformat(timespec='seconds'), sent_to='reports/ (developer mode)')
            self._write(rid, r)
            return r
        if r.get('include_render', True) and r.get('has_render'):
            r['_render_b64'] = base64.b64encode(self.image(rid, 'render')).decode()
        body = json.dumps(payload(r, self.install_token(), r.get('include_render', True), reply)).encode()
        r.pop('_render_b64', None)
        res = (post or _post)(s['intake'], body)
        if not res.get('ok'):
            raise Bad('the intake said: %s' % str(res.get('error') or 'no answer')[:200])
        r.update(status='sent', sent_at=_now().isoformat(timespec='seconds'), code=res.get('code'),
                 status_url=res.get('status_url'), remote_status='new')
        self._write(rid, r)
        return r

    def refresh_status(self, rid, get=None):
        """Ask the intake how a sent report is doing (new / approved – with the issue link – / merged / discarded)."""
        r = self.get(rid)
        if not r.get('code'):
            return r
        url = self.settings()['intake'].rstrip('/') + '/status/' + re.sub(r'[^\w-]', '', r['code'])
        res = (get or _get)(url)
        if res.get('ok'):
            r['remote_status'] = res.get('status')
            if res.get('issue_url'):
                r.update(issue_url=res['issue_url'], status='promoted')
            self._write(rid, r)
        return r

    # ---------- a zip to hand to Claude: one folder per report with report.md and its pictures ----------
    def zip(self, ids=None, community=None):
        """ids: report ids (None = all kept/sent ones). community: triage items (dicts) with their render bytes under
        '_png'. Returns the zip as bytes."""
        import io
        import zipfile
        buf = io.BytesIO()
        index = ['# Axella reports', '', 'One folder per report: `report.md` (what happened, kind, screen, last actions, '
                 'errors, versions) and its pictures. `render.png` is the privacy render (layout only, every text replaced); '
                 '`screen.png` – only in developer mode – is the real screen.', '']
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            mine = [r for r in self.list() if ids is None or r['id'] in ids]
            for row in mine:
                r = self.get(row['id'])
                folder = '%s-%s' % (r['id'], r.get('class') or 'report')
                z.writestr(folder + '/report.md', self.markdown(r))
                for kind, name in (('render', 'render.png'), ('full', 'screen.png')):
                    if r.get('has_' + ('render' if kind == 'render' else 'full')):
                        z.writestr(folder + '/' + name, self.image(r['id'], kind))
                index.append('- `%s/` – %s · %s' % (folder, (r.get('class') or '').upper(), _one_line(r.get('text'))))
            for c in community or []:
                folder = 'community/%s-%s' % (str(c.get('id'))[:8], c.get('class') or 'report')
                z.writestr(folder + '/report.md', self.markdown({**c, 'at': c.get('created'), 'mode': 'community'}))
                if c.get('_png'):
                    z.writestr(folder + '/render.png', c['_png'])
                index.append('- `%s/` – community · %s · %s' % (folder, (c.get('class') or '').upper(), _one_line(c.get('text'))))
            if len(index) == 4:
                index.append('_No reports._')
            z.writestr('README.md', '\n'.join(index) + '\n')
        return buf.getvalue()

    @staticmethod
    def markdown(r):
        meta = r.get('meta') or {}
        lines = ['# %s – %s' % ((r.get('class') or 'report').capitalize(), _one_line(r.get('text'), 80)), '',
                 '- **When:** %s' % (r.get('at') or '–'), '- **Screen:** `%s`' % (r.get('route') or '–'),
                 '- **Status:** %s%s' % (r.get('status') or '–', (' – ' + r['issue_url']) if r.get('issue_url') else ''),
                 '- **Mode:** %s' % (r.get('mode') or '–'), '', '## What happened', '', str(r.get('text') or '').strip(), '']
        if meta:
            lines += ['## Versions and setup', '', '| | |', '|---|---|']
            lines += ['| %s | %s |' % (k, ', '.join(v) if isinstance(v, list) else (v if v not in (None, '') else '–')) for k, v in meta.items()]
            lines += ['']
        if r.get('trail'):
            lines += ['## Last actions (oldest first)', ''] + ['- `%s`' % t for t in r['trail']] + ['']
        if r.get('errors'):
            lines += ['## Errors', '']
            for e in r['errors']:
                lines.append('- %s: `%s`' % (e.get('source') or 'app', e.get('message')))
                lines += ['  - `%s`' % f for f in e.get('frames') or []]
            lines += ['']
        pics = [x for x, k in (('render.png', 'has_render'), ('screen.png', 'has_full')) if r.get(k)]
        if pics:
            lines += ['## Pictures', ''] + ['- `%s`' % p for p in pics] + ['']
        return '\n'.join(lines)

    # ---------- triage of community reports (the maintainer's own instance, developer mode) ----------
    def triage(self, method, path, body=None, req=None):
        tok = self._secret('report-triage-token')
        if self.settings()['mode'] != 'developer' or not tok:
            raise Bad('triage is only on the maintainer\'s own Axella (developer mode with a triage token)')
        if not re.match(r'^(|/[\w-]+(/(render|act))?)$', path):
            raise Bad('bad triage path')
        base = self.settings()['intake'].rstrip('/')
        base = base[:-len('/report')] if base.endswith('/report') else base
        return (req or _request)(method, base + '/triage' + path, body, tok)


def _one_line(t, n=100):
    t = ' '.join(str(t or '').split())
    return t if len(t) <= n else t[:n - 1] + '…'


def _request(method, url, body=None, token=None, timeout=20):
    if not url.startswith('https://'):
        raise Bad('the intake must be https')
    headers = {'Content-Type': 'application/json', 'User-Agent': 'Axella-reports/1'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(5_000_000)
            ctype = r.headers.get('Content-Type') or ''
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read(20000))
        except ValueError:
            return {'ok': False, 'error': 'HTTP %d' % e.code}
    except (urllib.error.URLError, OSError) as e:
        return {'ok': False, 'error': 'not reachable (%s)' % str(e)[:80]}
    if ctype.startswith('image/png'):
        return {'ok': True, 'png': data}
    try:
        return json.loads(data)
    except ValueError:
        return {'ok': False, 'error': 'not JSON'}


def _post(url, body):
    if not url.startswith('https://'):
        raise Bad('the intake must be https')
    req = urllib.request.Request(url, data=body, method='POST', headers={'Content-Type': 'application/json',
                                                                         'User-Agent': 'Axella-reports/1'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read(100000))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read(20000))
        except ValueError:
            return {'ok': False, 'error': 'HTTP %d' % e.code}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {'ok': False, 'error': 'not reachable (%s)' % str(e)[:80]}


def _get(url):
    return _request('GET', url)
