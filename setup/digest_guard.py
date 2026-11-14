"""Missing-digest alert: if a scheduled digest hasn't appeared 60 minutes after its slot, push one warning.

Runs as a thread inside axella-actions.py. Which digests are due comes from the scheduler itself
(Scheduler.due_digests – the slots, days and times in Settings → Schedule, vacation, days off and a paused work day),
so the alert never warns about a slot that isn't set up for that day.
The urgent check is deliberately not watched: it only writes a file when something is urgent.
"""
import datetime
import json
import os
import sys
import time

GRACE = datetime.timedelta(minutes=60)     # runs start ~10 min late and can take 30 min
WINDOW = datetime.timedelta(hours=4)       # don't warn about slots older than this (e.g. after a restart)
EARLY = datetime.timedelta(minutes=15)     # a digest written up to 15 min before the slot still counts


def slots(now, due):
    """Today's due slots that are ready for checking now: (key, label, slot time). due(date) -> [(id, 'HH:MM', label)]."""
    for _sid, hm, label in due(now.date()):
        h, m = map(int, hm.split(':'))
        at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if at + GRACE <= now < at + WINDOW:
            yield f'{at:%Y-%m-%d} {hm}', label, at


def digest_since(digests_dir, since):
    """Any real (non-P0, non-trial) digest written since `since`?"""
    try:
        names = os.listdir(digests_dir)
    except FileNotFoundError:
        return False
    for n in names:
        if not n[:4].isdigit() or not (n.endswith('.md') or n.endswith('.json')) or '-p0' in n:
            continue
        try:
            if datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(digests_dir, n))) >= since:
                return True
        except OSError:
            pass
    return False


def check(now, digests_dir, state_file, send, due):
    """One pass. Returns the slot keys alerted in this pass."""
    try:
        with open(state_file, encoding='utf-8') as f:
            st = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        st = {}
    done = set(st.get('alerted', []))
    fired = []
    for key, label, at in slots(now, due):
        if key in done or digest_since(digests_dir, at - EARLY):
            continue
        send({'title': f'⚠ Axella – {at:%H:%M} digest missing',
              'body': f'{label} hasn\'t arrived 1 hour after {at:%H:%M}. See Runs in Axella.',
              'tag': 'axella-missing', 'url': '/axella/'})
        done.add(key)
        fired.append(key)
    if fired:
        keep = sorted(done)[-50:]
        with open(state_file + '.tmp', 'w', encoding='utf-8') as f:
            json.dump({'alerted': keep}, f)
        os.replace(state_file + '.tmp', state_file)
    return fired


def run(digests_dir, state_file, send, has_subscribers, due, log=sys.stderr):
    while True:
        try:
            if has_subscribers():
                for k in check(datetime.datetime.now(), digests_dir, state_file, send, due):
                    log.write(f'{datetime.datetime.now():%Y-%m-%dT%H:%M:%S} digest guard: alerted {k}\n')
        except ImportError:
            pass
        except Exception as e:
            log.write(f'digest guard: {str(e)[:200]}\n')
        time.sleep(60)
