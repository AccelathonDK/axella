"""Calm setup check (dev request calm-setup-check): three steps that keep the other apps quiet.

1. Banners off for Mail, Messages and WhatsApp on the iPhone – you tick Done.
2. Axella's notifications on – the dashboard checks this itself on each device (the push subscription); nothing stored.
3. An "Axella" Focus – you tick Done.

state/calm-setup.json: when steps 1 and 3 were ticked, and when the Getting started / Today card was dismissed.
Nothing is changed on the iPhone; these are instructions. No reminders: once done or dismissed it never comes back
by itself (Settings → Notifications → Calm setup is always there)."""
import datetime
import json
import os
import threading

STEPS = ('banners', 'focus')
NEW_DAYS = 14            # "a new installation": the first digest is less than two weeks old
LOCK = threading.Lock()


class Bad(Exception):
    pass


class CalmSetup:
    def __init__(self, state_dir, digests_dir):
        self.path = os.path.join(state_dir, 'calm-setup.json')
        self.digests_dir = digests_dir

    def load(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        d = d if isinstance(d, dict) else {}
        done = d.get('done') if isinstance(d.get('done'), dict) else {}
        return {'done': {k: done.get(k) if isinstance(done.get(k), str) else None for k in STEPS},
                'dismissed': d.get('dismissed') if isinstance(d.get('dismissed'), str) else None}

    def new_install(self, now=None):
        now = now or datetime.datetime.now()
        try:
            names = sorted(n for n in os.listdir(self.digests_dir) if n.endswith('.json') and n[:4].isdigit())
        except OSError:
            return True
        if not names:
            return True
        try:
            first = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(self.digests_dir, names[0])))
            day = datetime.datetime.strptime(names[0][:10], '%Y-%m-%d')
            first = min(first, day)
        except (OSError, ValueError):
            return False
        return now - first < datetime.timedelta(days=NEW_DAYS)

    def view(self, now=None):
        return dict(self.load(), new_install=self.new_install(now))

    def action(self, action, p):
        now = datetime.datetime.now().replace(microsecond=0).isoformat()
        with LOCK:
            d = self.load()
            if action == 'calm_setup_step':
                step = p.get('step')
                if step not in STEPS:
                    raise Bad('which step?')
                d['done'][step] = now if p.get('on', True) else None
            elif action == 'calm_setup_dismiss':
                d['dismissed'] = now if p.get('on', True) else None
            else:
                raise Bad('unknown action')
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(d, f, indent=1)
            os.replace(tmp, self.path)
        return d
