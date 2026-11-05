"""Axella projects: small notes, links and documents per project (state/projects.json + state/project-files/).

Used by axella-actions.py. Projects are created by the owner on the dashboard, or suggested by Claude
(status "suggested", source "Claude") and then accepted or dismissed by the owner.

projects.json:
  {"projects": [{"id": "p-summer-2027", "name": "Summer 2027", "tag": "summer2027", "color": "#0d6efd",
                 "status": "active|suggested|archived", "source": "Dashboard|Claude", "why": "...",
                 "created": iso, "keywords": ["..."], "senders": ["a@example.com"],
                 "notes": [{"id", "text", "created"}], "links": [{"id", "url", "title", "created"}],
                 "files": [{"id", "name", "type", "size", "uploaded"}],
                 "items": [{"digest", "item_id", "headline", "added"}],      # pinned by the owner
                 "hidden_items": ["item id", ...]}]}                         # "not this project"
"""
import datetime
import json
import os
import re
import secrets
import threading

LOCK = threading.Lock()
MAX_UPLOAD = 25 * 1024 * 1024
UPLOAD_TYPES = {
    'application/pdf': '.pdf', 'image/png': '.png', 'image/jpeg': '.jpg', 'image/heic': '.heic',
    'image/webp': '.webp', 'text/plain': '.txt', 'text/calendar': '.ics',
    'application/vnd.apple.pkpass': '.pkpass',
}
COLORS = ['#0d6efd', '#6f42c1', '#d63384', '#fd7e14', '#198754', '#20c997', '#0aa2c0', '#6c757d']


class Bad(Exception):
    pass


def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def _id(prefix):
    return prefix + datetime.datetime.now().strftime('%Y%m%d%H%M%S') + secrets.token_hex(3)


def _slug(s):
    return re.sub(r'[^a-z0-9]+', '', s.lower())[:40]


class Projects:
    def __init__(self, state_dir):
        self.file = os.path.join(state_dir, 'projects.json')
        self.dir = os.path.join(state_dir, 'project-files')

    # ---------- storage ----------
    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            d = {}
        d.setdefault('projects', [])
        return d

    def _save(self, d):
        tmp = self.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.file)

    def _get(self, d, pid):
        p = next((x for x in d['projects'] if x.get('id') == pid), None)
        if not p:
            raise Bad('project not found')
        return p

    @staticmethod
    def _text(p, key, limit):
        v = p.get(key)
        if not isinstance(v, str) or not v.strip():
            raise Bad(f'missing {key}')
        if len(v) > limit:
            raise Bad(f'{key} too long')
        return v.strip()

    # ---------- actions (JSON) ----------
    def action(self, action, p):
        with LOCK:
            d = self.load()
            if action == 'project_add':
                name = self._text(p, 'name', 80)
                tag = _slug(p.get('tag') or name)
                if not tag:
                    raise Bad('bad name')
                if any(x.get('tag') == tag and x.get('status') != 'archived' for x in d['projects']):
                    raise Bad('a project with that tag exists')
                pr = {'id': 'p-' + tag, 'name': name, 'tag': tag,
                      'color': p.get('color') if p.get('color') in COLORS else COLORS[len(d['projects']) % len(COLORS)],
                      'status': 'active', 'source': 'Dashboard', 'created': _now(),
                      'keywords': [k.strip() for k in (p.get('keywords') or [name]) if isinstance(k, str) and k.strip()][:20],
                      'senders': [], 'notes': [], 'links': [], 'files': [], 'items': [], 'hidden_items': []}
                if any(x['id'] == pr['id'] for x in d['projects']):
                    pr['id'] += '-' + secrets.token_hex(2)
                d['projects'].append(pr)
                self._save(d)
                return pr['id']

            if action == 'project_reorder':          # sidebar drag & drop: full list of ids in the new order
                ids = p.get('ids')
                if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or len(ids) > 200:
                    raise Bad('bad ids')
                pos = {pid: n for n, pid in enumerate(ids)}
                for x in d['projects']:
                    if x['id'] in pos:
                        x['order'] = pos[x['id']]
                self._save(d)
                return 'reordered'

            pr = self._get(d, self._text(p, 'id', 100))
            for k in ('notes', 'links', 'files', 'items', 'hidden_items', 'keywords', 'senders'):
                pr.setdefault(k, [])

            if action == 'project_update':
                if 'name' in p:
                    pr['name'] = self._text(p, 'name', 80)
                if 'color' in p and p['color'] in COLORS:
                    pr['color'] = p['color']
                if 'status' in p:
                    if p['status'] not in ('active', 'archived'):
                        raise Bad('bad status')
                    if p['status'] == 'active' and pr.get('status') != 'active' and any(
                            x is not pr and x.get('status') == 'active' and x.get('tag') == pr.get('tag') for x in d['projects']):
                        raise Bad('another active project already uses #%s – rename or archive that one first' % pr.get('tag'))
                    if p['status'] == 'archived' and pr.get('status') != 'archived':
                        pr['archived'] = _now()          # shown in Projects → Archived
                    pr['status'] = p['status']
                    if p['status'] == 'active':
                        pr['accepted'] = pr.get('accepted') or _now()
                        pr.pop('archived', None)
                if 'keywords' in p and isinstance(p['keywords'], list):
                    pr['keywords'] = [k.strip() for k in p['keywords'] if isinstance(k, str) and k.strip()][:20]
                if 'ctx' in p:                         # work / private / null (= decide by workplace name)
                    if p['ctx'] not in ('work', 'private', None):
                        raise Bad('ctx must be work or private')
                    if p['ctx']:
                        pr['ctx'] = p['ctx']
                    else:
                        pr.pop('ctx', None)
            elif action == 'project_dismiss':          # a suggestion the owner doesn't want
                if pr.get('status') != 'suggested':
                    raise Bad('only suggestions can be dismissed')
                pr['status'] = 'dismissed'
                pr['dismissed'] = _now()
            elif action == 'project_sender_add':      # "Add <sender> to this project's matches?" (Scan mail)
                m = str(p.get('match') or '').strip().lower()[:200]
                if not re.match(r'^([^@\s<>,;"]+@)?[a-z0-9.-]+\.[a-z]{2,}$', m):
                    raise Bad('an address or a domain')
                if m not in pr['senders']:
                    pr['senders'] = (pr['senders'] + [m])[-50:]
            elif action == 'project_note_add':
                pr['notes'].append({'id': _id('n'), 'text': self._text(p, 'text', 5000), 'created': _now()})
            elif action == 'project_link_add':
                url = self._text(p, 'url', 2000)
                if not re.match(r'^https?://', url):
                    raise Bad('links must start with http:// or https://')
                pr['links'].append({'id': _id('l'), 'url': url, 'title': (p.get('title') or '').strip()[:200], 'created': _now()})
            elif action == 'project_item_add':
                ref = {'digest': str(p.get('digest') or '')[:80], 'item_id': self._text(p, 'item_id', 200),
                       'headline': str(p.get('headline') or '')[:300], 'added': _now()}
                pr['items'] = [i for i in pr['items'] if i.get('item_id') != ref['item_id']] + [ref]
                pr['hidden_items'] = [i for i in pr['hidden_items'] if i != ref['item_id']]
            elif action == 'project_item_remove':
                iid = self._text(p, 'item_id', 200)
                pr['items'] = [i for i in pr['items'] if i.get('item_id') != iid]
                if iid not in pr['hidden_items']:
                    pr['hidden_items'].append(iid)
            elif action in ('project_note_delete', 'project_link_delete', 'project_file_delete'):
                key = {'project_note_delete': 'notes', 'project_link_delete': 'links', 'project_file_delete': 'files'}[action]
                eid = self._text(p, 'entry', 100)
                e = next((x for x in pr[key] if x.get('id') == eid), None)
                if not e:
                    raise Bad('not found')
                pr[key].remove(e)
                if key == 'files':
                    # keep the bytes in a .deleted folder – never a hard delete from the dashboard
                    src = self._path(pr['id'], e)
                    if os.path.exists(src):
                        bin_dir = os.path.join(self.dir, '.deleted')
                        os.makedirs(bin_dir, exist_ok=True)
                        os.replace(src, os.path.join(bin_dir, os.path.basename(src)))
            elif action == 'project_delete':
                pr['status'], pr['archived'] = 'archived', _now()
            else:
                raise Bad('unknown action')
            self._save(d)
            return action

    # ---------- files ----------
    def _path(self, pid, entry):
        ext = UPLOAD_TYPES.get(entry.get('type'), '.bin')
        safe_pid = re.sub(r'[^a-zA-Z0-9_-]', '', pid)
        safe_fid = re.sub(r'[^a-zA-Z0-9_-]', '', entry['id'])
        return os.path.join(self.dir, safe_pid, safe_fid + ext)

    def upload(self, pid, name, ctype, data):
        ctype = (ctype or '').split(';')[0].strip().lower()
        if ctype not in UPLOAD_TYPES:
            raise Bad('file type not allowed (PDF, images, text, .ics, wallet passes)')
        if not data or len(data) > MAX_UPLOAD:
            raise Bad('file empty or larger than 25 MB')
        if ctype == 'application/pdf' and not data.startswith(b'%PDF'):
            raise Bad('not a PDF')
        name = re.sub(r'[\x00-\x1f/\\]', '_', (name or 'file').strip())[:150] or 'file'
        with LOCK:
            d = self.load()
            pr = self._get(d, pid)
            pr.setdefault('files', [])
            e = {'id': _id('f'), 'name': name, 'type': ctype, 'size': len(data), 'uploaded': _now()}
            path = self._path(pr['id'], e)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'wb') as f:
                f.write(data)
            os.chmod(path, 0o600)
            pr['files'].append(e)
            self._save(d)
            return e['id']

    def read_file(self, pid, fid):
        d = self.load()
        pr = self._get(d, pid)
        e = next((x for x in pr.get('files', []) if x.get('id') == fid), None)
        if not e:
            raise Bad('not found')
        path = self._path(pr['id'], e)
        with open(path, 'rb') as f:
            return e, f.read()
