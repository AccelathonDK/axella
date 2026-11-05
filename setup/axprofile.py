"""axprofile – who Axella works for, read from setup/actions-config.json (personal, not in git; see actions-config.example.json).

  "owner":      {"name": "Alex Example", "first_name": "Alex", "sign_off": "br Alex"}
  "accounts":   {"<account name exactly as in Mail>": {"label": "iCloud", "kind": "private"|"work",
                  "workplace": "<workplace id, work accounts only>", "address": "...", "folders": [...]}}
  "workplaces": [{"id": "acme", "name": "Acme", "domains": ["acme.com"], "calendar": "Acme",
                  "protected": true}]                 # zero, one or several employers / clients
  "calendars":  [{"name": "<calendar name in Calendar.app>", "label": "...", "kind": "private"|"work",
                  "workplace": "<id, optional>"}]   # plain strings are accepted too

A *protected* workplace keeps its content inside the digest files (AXELLA.md "Workplaces"): the SQLite store keeps
metadata only, spoken digests mention who/what only, and nothing else copies it. Private-only setups simply have no
workplaces and no work accounts.
"""
import json
import os

_BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(_BASE, 'actions-config.json')


def load(cfg=None):
    if cfg is not None:
        return cfg
    try:
        with open(CONFIG, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def owner(cfg=None):
    o = load(cfg).get('owner') or {}
    name = o.get('name') or (load(cfg).get('voice') or {}).get('owner') or ''
    first = o.get('first_name') or (name.split(' ')[0] if name else '')
    return {'name': name, 'first_name': first, 'sign_off': o.get('sign_off') or ('br ' + first if first else '')}


def accounts(cfg=None):
    out = []
    for acc, a in (load(cfg).get('accounts') or {}).items():
        a = a or {}
        out.append({'id': acc, 'label': a.get('label') or acc, 'kind': a.get('kind') or 'private',
                    'workplace': a.get('workplace'), 'address': a.get('address')})
    return out


def workplaces(cfg=None):
    return [{'id': w.get('id'), 'name': w.get('name') or w.get('id'), 'domains': [d.lower() for d in w.get('domains', [])],
             'calendar': w.get('calendar'), 'protected': bool(w.get('protected'))}
            for w in (load(cfg).get('workplaces') or []) if w.get('id')]


def calendars(cfg=None):
    out = []
    for c in load(cfg).get('calendars') or []:
        if isinstance(c, str):
            c = {'name': c}
        if c.get('name'):
            out.append({'name': c['name'], 'label': c.get('label') or c['name'], 'kind': c.get('kind') or 'private',
                        'workplace': c.get('workplace')})
    return out


def calendar_names(cfg=None):
    return [c['name'] for c in calendars(cfg)]


def protected(cfg=None):
    """(accounts, domains) whose content stays in the digest files."""
    cfg = load(cfg)
    wps = {w['id']: w for w in workplaces(cfg) if w['protected']}
    accs = {a['id'] for a in accounts(cfg) if a['workplace'] in wps}
    doms = {d for w in wps.values() for d in w['domains']}
    return accs, doms


def is_protected(account=None, address=None, cfg=None):
    accs, doms = protected(cfg)
    if account and account in accs:
        return True
    addr = (address or '').lower()
    return '@' in addr and any(addr.endswith('@' + d) or addr.endswith('.' + d) for d in doms)


def public(cfg=None):
    """What the dashboard needs – no addresses."""
    cfg = load(cfg)
    o = owner(cfg)
    return {'owner': {'name': o['name'], 'first_name': o['first_name'], 'sign_off': o['sign_off']},
            'accounts': [{k: a[k] for k in ('id', 'label', 'kind', 'workplace')} for a in accounts(cfg)],
            'workplaces': [{k: w[k] for k in ('id', 'name', 'calendar', 'protected')} for w in workplaces(cfg)],
            'calendars': calendars(cfg)}
