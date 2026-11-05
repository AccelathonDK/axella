"""Housekeeping: move digests older than KEEP_DAYS into digests/archive/YYYY-MM/ (a move, never a delete), and keep the
log files from growing without end (trim_logs).

Runs as a thread inside axella-actions.py. Scheduled runs only look back 2 working days (carry-over), the dashboard
picker shows 7 days, and the dashboard's Archive view lists the month folders.
"""
import datetime
import os
import re
import sys
import time

KEEP_DAYS = 30
NAME_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})-\d{4}.*\.(md|json)$')


def prune_locks(digests_dir, days=2):
    """Remove the digest lock files (digestfile.py) no pass has used for `days` days."""
    import time
    cut = time.time() - days * 86400
    for n in os.listdir(digests_dir):
        p = os.path.join(digests_dir, n)
        if n.endswith('.json.lock') and os.path.isfile(p) and os.path.getmtime(p) < cut:
            try:
                os.remove(p)
            except OSError:
                pass


def prune_read_done(state_dir, days=30, now=None):
    """Delete finished Read-with-Claude requests and results (state/trips-read/done/, state/project-read/done/) older
    than `days`: they were taken in long ago, and they hold mail facts a later run could read."""
    cut = (now or time.time()) - days * 86400
    gone = []
    for sub in ('trips-read', 'project-read'):
        d = os.path.join(state_dir or '', sub, 'done')
        if not state_dir or not os.path.isdir(d):
            continue
        for n in os.listdir(d):
            pth = os.path.join(d, n)
            if n.endswith('.json') and os.path.isfile(pth) and not os.path.islink(pth) and os.path.getmtime(pth) < cut:
                try:
                    os.remove(pth)
                    gone.append(pth)
                except OSError:
                    pass
    return gone


def archive_old(digests_dir, today=None, keep_days=KEEP_DAYS):
    """Move old digest files; returns the list of moved names."""
    today = today or datetime.date.today()
    cutoff = today - datetime.timedelta(days=keep_days)
    moved = []
    for n in sorted(os.listdir(digests_dir)):
        m = NAME_RE.match(n)
        if not m:
            continue
        try:
            day = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if day >= cutoff:
            continue
        dest_dir = os.path.join(digests_dir, 'archive', f'{m.group(1)}-{m.group(2)}')
        dest = os.path.join(dest_dir, n)
        if os.path.exists(dest):
            continue            # never overwrite
        os.makedirs(dest_dir, exist_ok=True)
        os.replace(os.path.join(digests_dir, n), dest)
        moved.append(n)
    return moved


LOG_MAX = 5 * 2**20          # a log file bigger than this is trimmed
LOG_KEEP = 2**20             # …keeping its last 1 MB in <name>.1
LOG_DIR = os.path.expanduser('~/Library/Logs/axella')


def trim_logs(state_dir=None, log_dir=LOG_DIR, max_size=LOG_MAX, keep=LOG_KEEP):
    """Service logs (launchd's StandardOutPath, opened in append mode): copy the tail to <name>.1 and truncate in place,
    so the running service keeps writing to the same file. state/actions.log (the action history the store reads):
    renamed to actions.log.1 and started afresh – the store notices the smaller file and reads it from the start.
    Returns the trimmed paths."""
    done = []
    for name in (sorted(os.listdir(log_dir)) if os.path.isdir(log_dir) else []):
        p = os.path.join(log_dir, name)
        if not name.endswith('.log') or not os.path.isfile(p) or os.path.getsize(p) <= max_size:
            continue
        with open(p, 'rb') as f:
            f.seek(-keep, os.SEEK_END)
            tail = f.read()
        tail = tail[tail.find(b'\n') + 1:]                  # start on a whole line
        with open(p + '.1', 'wb') as f:
            f.write(tail)
        os.truncate(p, 0)
        done.append(p)
    if state_dir:
        p = os.path.join(state_dir, 'actions.log')
        if os.path.isfile(p) and os.path.getsize(p) > max_size:
            os.replace(p, p + '.1')
            done.append(p)
    return done


def run(digests_dir, state_dir=None, log=sys.stderr):
    while True:
        try:
            moved = archive_old(digests_dir)
            prune_locks(digests_dir)
            if moved:
                log.write(f'{datetime.datetime.now():%Y-%m-%dT%H:%M:%S} housekeeping: archived {len(moved)} digest files\n')
        except Exception as e:
            log.write(f'housekeeping: {str(e)[:200]}\n')
        try:
            n = len(prune_read_done(state_dir))
            if n:
                log.write(f'{datetime.datetime.now():%Y-%m-%dT%H:%M:%S} housekeeping: removed {n} old readings\n')
        except Exception as e:
            log.write(f'housekeeping readings: {str(e)[:200]}\n')
        try:
            for p in trim_logs(state_dir):
                log.write(f'{datetime.datetime.now():%Y-%m-%dT%H:%M:%S} housekeeping: trimmed {os.path.basename(p)}\n')
        except Exception as e:
            log.write(f'housekeeping logs: {str(e)[:200]}\n')
        time.sleep(3600)
