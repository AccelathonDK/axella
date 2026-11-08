"""Axella scheduler: runs the digests and urgent checks on the Mac mini itself (no cloud scheduler).

Runs inside the action service (axella-actions.py) as two threads:
  - the clock: every 15 s works out which slots are due (state/scheduler.json, edited in Settings),
    applies the pause rules (state/schedule.json), picks up "Run sweep now" requests at once, and queues jobs
  - the worker: runs one job at a time as a headless `claude -p` with the local prompt from setup/local-tasks/,
    a local MCP config (Macuse) and an explicit tool allow-list; hard timeout; retry once after 3 min; push if it
    fails twice

State:
  state/scheduler.json  – slot settings (defaults below = the old cloud schedule)
  state/runs.json       – run ledger: [{id, task, slot, trigger, status, started, ended, reason, usage, summary}]
  state/runs/<id>.log   – readable log of one run (tool calls, errors, final message – never message bodies)
  state/doctor.json     – what the service found on this Mac (claude CLI, login, MCP servers) – written at start

Runs use the owner's Claude subscription through the claude CLI; ANTHROPIC_API_KEY is removed from the environment.
"""
import datetime
import glob
import json
import os
import shutil
import subprocess
import sys
import secrets
import threading
import time

import briefings as briefings_mod
import kb_harvest
import scope as scope_mod
import wrap as wrap_mod
import away as away_mod
import uuid

LOCK = threading.Lock()
WEEK = [0, 1, 2, 3, 4, 5, 6]
WORKDAYS = [0, 1, 2, 3, 4]

DEFAULT = {
    'enabled': False,      # master switch – stays off until the cloud tasks are switched off (never run both)
    'digests': [
        {'id': 'morning', 'label': 'Morning digest', 'task': 'digest-morning', 'time': '07:30', 'days': WEEK, 'enabled': True},
        {'id': 'midday', 'label': 'Midday digest', 'task': 'digest-midday', 'time': '11:30', 'days': WORKDAYS, 'enabled': True},
        {'id': 'afternoon', 'label': 'Afternoon digest', 'task': 'digest-afternoon', 'time': '15:30', 'days': [0, 1, 2, 3], 'enabled': True},
        {'id': 'wrap', 'label': 'Friday work wrap', 'task': 'week-wrap', 'time': '15:30', 'days': [4], 'enabled': True,
         'worlds': ['work']},        # new installations only – add it in Settings → Schedule on an existing one
        {'id': 'week', 'label': 'Sunday week-ahead', 'task': 'week-ahead', 'time': '20:30', 'days': [6], 'enabled': True,
         'worlds': ['private']},     # new installations only – a saved schedule without "worlds" stays work and private
    ],
    'p0': {'enabled': True, 'from': '07:00', 'to': '22:45', 'every': 15, 'days': WORKDAYS},
    'models': {'digest': 'opus', 'p0': 'sonnet', 'compose': 'sonnet'},
}

# task → prompt file, kind, timeout (s)
# files no run may read: the call agent's token, the push keys and subscriptions, the account config
SECRETS = ('state/voice-token', 'state/voice-lookup-key', 'state/report-install-token', 'state/report-triage-token', 'state/pics-senders.json', 'state/vapid.json', 'state/push-subscriptions.json', 'setup/actions-config.json',
           'state/privacy.json', 'state/private-inbox.json', 'state/private-notified.json', 'state/signal-store.json',
           'state/private-calls.json', 'state/private-calls/**', 'state/contacts-book.json', 'state/people-notes.json', 'state/keep-in-touch.json', 'state/bills.json', 'state/trip-checklists.json', 'state/recurring.json', 'state/renewals.json', 'state/blocks.json', 'state/away.json', 'state/backup.json', 'state/export/**', 'pre-restore-*/**', 'state/project-mail.json', 'state/online-meetings.json', 'state/calendar-invites.json',
           'state/deleted/**', 'state/macuse-calendar-tools.json', 'state/meetings/**',
           'state/scheduled.json', 'state/scheduled-files/**', 'state/promises.json', 'notes/**', 'state/planner.json')   # who is private is not for Claude either

# the apps' own message stores – runs see mail and messages only through Macuse (filtered) and the exports
APP_STORES = ('~/Library/Messages/**', '~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/**',
              '~/Library/Containers/net.whatsapp.WhatsApp/**', '~/Library/Containers/desktop.WhatsApp/**',
              '~/.local/share/signal-cli/**', '~/Library/Application Support/Signal/**',
              '~/Library/Mail/V*/MailData/**', '~/Library/Mail/V*/**/Messages/**')

TASKS = {
    'digest-morning': {'kind': 'digest', 'label': 'Morning digest', 'timeout': 25 * 60},
    # a recording transcribed on the Mac mini (whisper.cpp, no Claude): only a line on Runs, never queued or run from here
    'transcribe': {'kind': 'local', 'label': 'Transcription', 'timeout': 4 * 3600},
    'digest-midday': {'kind': 'digest', 'label': 'Midday digest', 'timeout': 25 * 60},
    'digest-afternoon': {'kind': 'digest', 'label': 'Afternoon digest', 'timeout': 25 * 60},
    'week-ahead': {'kind': 'digest', 'label': 'Sunday week-ahead', 'timeout': 30 * 60},
    'week-wrap': {'kind': 'digest', 'label': 'Friday work wrap', 'timeout': 30 * 60},     # afternoon digest + week wrap
    'on-demand': {'kind': 'digest', 'label': 'On-demand sweep', 'timeout': 25 * 60},
    'inbox-rescan': {'kind': 'digest', 'label': 'Inbox re-scan', 'timeout': 40 * 60},   # only on demand (dashboard)
    # the first digest after 2+ days away, instead of that slot's task; or "Catch me up since…" (away.py)
    'return-briefing': {'kind': 'digest', 'label': 'Back-from-away briefing', 'timeout': 40 * 60},
    'p0-check': {'kind': 'p0', 'label': 'Urgent check', 'timeout': 5 * 60},
    'receipts-catchup': {'kind': 'receipts', 'label': 'Receipts catch-up', 'timeout': 45 * 60},
    'compose': {'kind': 'compose', 'label': 'Compose mail', 'timeout': 6 * 60},
    'ask': {'kind': 'ask', 'label': 'Ask Axella', 'timeout': 4 * 60},
    'kb-harvest': {'kind': 'kb', 'label': 'Knowledge harvest', 'timeout': 30 * 60},
    'trip-read': {'kind': 'trips', 'label': 'Trips: read booking mails', 'timeout': 20 * 60},   # on tap (trips.py)   # nightly + scan batches (kb_harvest.py)
    'project-read': {'kind': 'projects', 'label': 'Projects: read picked mails', 'timeout': 20 * 60},   # on tap (project_scan.py)
    'briefing': {'kind': 'briefing', 'label': 'Briefing', 'timeout': 15 * 60},          # web only – briefings.py
    'briefing-personal': {'kind': 'briefing-personal', 'label': 'Briefing: personal note', 'timeout': 6 * 60},   # offline
    'feedback-summary': {'kind': 'feedback', 'label': 'axella.dev feedback summary', 'timeout': 10 * 60},   # Sundays, isolated
}
BRIEF_GRACE = 3 * 3600      # a briefing slot missed (Mac asleep, service down) still runs up to 3 h late
COMPOSE_KEEP_DAYS = 14
DIGEST_GRACE = 20 * 60      # a digest slot missed (service down) still starts up to 20 min late
P0_GRACE = 10 * 60
RETRY_AFTER = 3 * 60
ALERT_REMIND = 6 * 3600          # a problem that is still there gets one reminder this often, no more
ALERT_LOCK = threading.Lock()
KEEP_DAYS = 30         # runs and their logs are kept this long
RUNS_CAP = 3000        # a hard cap on top of the 30 days (≈ 100 runs a day); counts at the cap are shown as "3000+"

# Macuse tools a run may use – read-only. Everything else (send, reply, compose, move, delete, mark read, calendar
# changes, clicking or typing) is not on the list, so the CLI refuses it.
MACUSE_READ = ['mail_search_messages', 'mail_get_messages', 'mail_get_thread', 'mail_get_attachment', 'mail_list_accounts',
               'mail_list_mailboxes', 'calendar_list_calendars', 'calendar_search_events', 'calendar_find_available_times',
               'contacts_search', 'contacts_get_all', 'messages_search_chats', 'messages_get_chat', 'messages_search_messages',
               'computer_use_list_apps', 'computer_use_list_windows', 'computer_use_read_text']
MACUSE_NEVER = ['mail_compose_message', 'mail_reply_message', 'mail_forward_message', 'mail_delete_message',
                'mail_move_message', 'mail_update_read_state', 'mail_open_message', 'messages_send_messages',
                'calendar_create_event', 'calendar_update_event', 'calendar_cancel_event', 'calendar_reschedule_event',
                'calendar_open_event', 'computer_use_click', 'computer_use_type_text', 'computer_use_press_key',
                'computer_use_drag', 'computer_use_scroll', 'computer_use_menu', 'computer_use_dialog', 'computer_use_app',
                'computer_use_window']
WRITES = {   # where each kind of run may write (relative to the Axella folder)
    'digest': ['digests/**'],
    'p0': ['digests/**', 'state/p0-last-check.txt'],
    'receipts': ['state/documents-import-catchup.json'],
    'compose': ['state/compose/**'],
    'ask': ['state/ask/**'],
    'kb': ['state/kb/*.json'],
    'trips': ['state/trips-read/*.json'],
    'projects': ['state/project-read/*.json'],
    'briefing': ['state/briefing/*.json'],
    'briefing-personal': ['state/briefing/*.personal.json'],
    'feedback': [],                 # runs in its own scratch folder (_feedback_workdir); Python copies summary.md back
}
# axella.dev form entries: text and e-mail addresses strangers typed into a public form. Only the Sunday summary run
# sees them (a copy, in its scratch folder); every other run is refused the folder. feedback/summary.md has no addresses.
FEEDBACK_INBOX = 'feedback/inbox/**'


def _now():
    return datetime.datetime.now().astimezone()


def _iso(dt=None):
    return (dt or _now()).isoformat(timespec='seconds')


def _hm(s):
    h, m = str(s).split(':')
    return int(h) * 60 + int(m)


class Bad(Exception):
    pass


def _file_hash(path):
    import hashlib
    try:
        with open(path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


class Scheduler:
    def __init__(self, base, state_dir, schedule, push, log=sys.stderr):
        self.base, self.state_dir, self.sched, self.push, self.log = base, state_dir, schedule, push, log
        self.cfg_file = os.path.join(state_dir, 'scheduler.json')
        self.runs_file = os.path.join(state_dir, 'runs.json')
        self.run_dir = os.path.join(state_dir, 'runs')
        self.prompt_dir = os.path.join(base, 'setup', 'local-tasks')
        self.queue = []                 # [{task, slot, trigger, not_before, attempt, retry_of}]
        self.harvest = None             # kb_harvest.Harvest – set by axella-actions.py
        self.briefings = None           # briefings.Briefings – set by axella-actions.py
        self.wrap_facts = None          # worlds -> the week wrap's facts (wrap.facts) – set by axella-actions.py
        self.away_due = None            # date -> the absence to brief now (away.Away.due) or None – set by axella-actions.py
        self.away_facts = None          # job -> the briefing's facts (away.facts), written before its run – axella-actions.py
        self.learned_note = None        # () -> the "Learned rules" block (learned.Learned.prompt_note) – axella-actions.py
        self.ask_notes = None           # (ask id, login) -> notes copied for this Ask run – none unless the owner asks
        self.ask_notes_done = None      # (ask id, notes read) -> after the run: count it, remove the copy
        self.current = None             # {'run': {...}, 'proc': Popen}
        self.cv = threading.Condition(LOCK)
        os.makedirs(self.run_dir, exist_ok=True)
        # runs still marked "running" from before a restart are handled by recover() – the service calls it at start.
        # Never here: tests import axella-actions.py, and an import must not touch state/runs.json (or a live run).

    def recover(self):
        """At service start: runs that were going when the service stopped are failed, and an interrupted scheduled
        digest is queued again (attempt 2). Writes state/runs.json only when something changed."""
        with LOCK:
            d = self._load_runs()
            changed = False
            for r in d['runs']:
                if r.get('status') == 'running':
                    r.update(status='failed', reason='interrupted – the action service restarted', ended=_iso())
                    changed = True
                    job = self._resume_job(r)
                    if job:                 # a scheduled digest: run it again once the service is up (attempt 2)
                        self.queue.append(job)
                        r['reason'] += ' – running it again'
            if changed:
                self._save_runs(d)

    @staticmethod
    def _resume_job(r, now=None):
        """The retry for a digest the restart interrupted: only a first attempt, started in the last 90 minutes, of a
        digest task – with the same scope and wrap choice (kept on the run as "job")."""
        spec = TASKS.get(r.get('task')) or {}
        if spec.get('kind') != 'digest' or r.get('attempt') != 1 or r.get('trigger') not in ('schedule', 'manual', 'sweep'):
            return None
        try:
            started = datetime.datetime.fromisoformat(str(r.get('started')))
        except ValueError:
            return None
        now = now or datetime.datetime.now(started.tzinfo)
        if not 0 <= (now - started).total_seconds() <= 90 * 60:
            return None
        j = r.get('job') if isinstance(r.get('job'), dict) else {}
        job = {'task': r['task'], 'slot': r.get('slot'), 'label': r.get('label'), 'trigger': 'retry', 'attempt': 2,
               'not_before': time.time() + 60, 'retry_of': r.get('id'), 'why': 'interrupted by a restart'}
        for k in ('worlds', 'mention_other', 'wrap', 'away'):
            if k in j:
                job[k] = j[k]
        return job

    # ---------- settings ----------
    def load(self):
        try:
            with open(self.cfg_file, encoding='utf-8') as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            d = {}
        out = json.loads(json.dumps(DEFAULT))
        if 'enabled' in d:
            out['enabled'] = bool(d['enabled'])
        out['enabled_at'] = d.get('enabled_at')
        if isinstance(d.get('digests'), list) and d['digests']:
            out['digests'] = d['digests']
        for s in out['digests']:                        # world scope per slot (scope.py): missing = both, as before
            s.update(scope_mod.norm_slot(s))
        out['p0'].update({k: v for k, v in (d.get('p0') or {}).items() if k in DEFAULT['p0']})
        out['models'].update({k: v for k, v in (d.get('models') or {}).items() if k in DEFAULT['models']})
        return out

    def _save_cfg(self, d):
        tmp = self.cfg_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.cfg_file)

    # ---------- ledger ----------
    def _load_runs(self):
        try:
            with open(self.runs_file, encoding='utf-8') as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            d = {}
        d.setdefault('runs', [])
        d.setdefault('slots', {})        # slot key → run id / 'skipped: reason'
        return d

    def _save_runs(self, d):
        keep_from = (_now() - datetime.timedelta(days=KEEP_DAYS)).isoformat()
        d['runs'] = [r for r in d['runs'] if (r.get('started') or '') >= keep_from][-RUNS_CAP:]
        cutoff = (_now() - datetime.timedelta(days=8)).strftime('%Y-%m-%d')
        d['slots'] = {k: v for k, v in d['slots'].items() if k.split('@')[1][:10] >= cutoff}
        tmp = '%s.%d-%d.tmp' % (self.runs_file, os.getpid(), threading.get_ident())   # never two writers on one tmp
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.runs_file)

    def note_run(self, task, label, status, summary, started, ended):
        """A line on Runs for work done outside the queue (a transcription): what, how long – never content."""
        rid = _now().strftime('%Y%m%d-%H%M%S-') + task + '-' + secrets.token_hex(2)
        with LOCK:
            d = self._load_runs()
            d['runs'].append({'id': rid, 'task': task, 'label': label, 'slot': None, 'trigger': 'local', 'attempt': 1,
                              'status': 'ok' if status == 'done' else 'failed', 'started': started, 'ended': ended,
                              'reason': None if status == 'done' else str(summary)[:200], 'summary': str(summary)[:200],
                              'usage': None, 'model': None})
            self._save_runs(d)
        return rid

    def _update_run(self, rid, **kw):
        with LOCK:
            d = self._load_runs()
            for r in d['runs']:
                if r['id'] == rid:
                    r.update(kw)
            self._save_runs(d)

    # ---------- which slots exist on a day ----------
    def slots_for(self, day, cfg=None):
        """[(slot_id, task, 'HH:MM', label)] for one date, sorted by time."""
        cfg = cfg or self.load()
        wd, out = day.weekday(), []
        digest_times = set()
        for s in cfg['digests']:
            if s.get('enabled', True) and wd in s.get('days', []) and s.get('task') in TASKS:
                out.append((s['id'], s['task'], s['time'], s.get('label') or TASKS[s['task']]['label']))
                digest_times.add(_hm(s['time']))
        p = cfg['p0']
        if p.get('enabled') and wd in p.get('days', []):
            t, end, step = _hm(p['from']), _hm(p['to']), max(5, int(p.get('every', 15)))
            while t <= end:
                if t not in digest_times:          # the digest at that time covers the check
                    hm = '%02d:%02d' % (t // 60, t % 60)
                    out.append(('p0-' + hm.replace(':', ''), 'p0-check', hm, 'Urgent check'))
                t += step
        return sorted(out, key=lambda x: x[2])

    def next_digest(self, now=None):
        """The next digest that will really run, by the same rules _tick uses: the slots, the schedule's vacation and
        days off at that time (schedule.status), and a work-only slot on a paused work day. {'at', 'label', 'worlds'},
        or None (digests off, or none in the next 31 days). For the line at the top of Today."""
        now = (now or datetime.datetime.now()).replace(second=0, microsecond=0, tzinfo=None)
        cfg = self.load()
        if not cfg.get('enabled'):
            return None
        by_sid = {s['id']: s for s in cfg['digests']}
        for add in range(0, 32):
            day = (now + datetime.timedelta(days=add)).date()
            for sid, task, hm, label in self.slots_for(day, cfg):
                if TASKS[task]['kind'] != 'digest':
                    continue
                at = datetime.datetime.combine(day, datetime.time(_hm(hm) // 60, _hm(hm) % 60))
                if at <= now:
                    continue
                st = self.sched.status(at)
                if not st.get('digests'):
                    continue
                worlds = scope_mod.effective(scope_mod.worlds_of(by_sid.get(sid) or {}), st.get('work_paused'))
                if worlds:
                    return {'at': at.isoformat(timespec='minutes'), 'label': label, 'worlds': worlds}
        return None

    # ---------- the clock ----------
    def clock(self):
        while True:
            try:
                self._tick()
            except Exception as e:
                self.log.write('%s scheduler tick: %s\n' % (_iso(), str(e)[:300]))
            time.sleep(15)

    def _prune_logs(self):
        if time.time() - getattr(self, '_pruned', 0) < 6 * 3600:
            return
        self._pruned = time.time()
        cutoff = time.time() - KEEP_DAYS * 86400
        old = time.time() - COMPOSE_KEEP_DAYS * 86400
        for p in glob.glob(os.path.join(self.state_dir, 'compose', '*.json')) + glob.glob(os.path.join(self.state_dir, 'ask', '*.json')):
            try:
                if os.path.getmtime(p) < old:
                    os.remove(p)
            except OSError:
                pass
        for p in glob.glob(os.path.join(self.run_dir, '*.log')):
            try:
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except OSError:
                pass

    def _tick(self):
        self._prune_logs()
        if self.harvest:                 # merge finished knowledge-harvest results, even while the schedule is off
            try:
                self.harvest.ingest()
            except Exception as e:
                self.log.write('%s kb ingest: %s\n' % (_iso(), str(e)[:300]))
        now = _now()
        cfg = self.load()
        sweep = self.sched.sweep() if cfg['enabled'] else None
        with LOCK:
            d = self._load_runs()
            # 1. "Run sweep now" – start at once, whatever the schedule or pause says (the owner asked for it)
            if cfg['enabled'] and sweep and not sweep.get('fired_at') and not any(j['task'] == 'on-demand' for j in self.queue) and \
                    not (self.current and self.current['run']['task'] == 'on-demand'):
                with open(os.path.join(self.state_dir, 'sweep-fired.json'), 'w', encoding='utf-8') as f:
                    json.dump({'request_at': sweep['at'], 'at': _iso(), 'by': 'scheduler'}, f)
                self.queue.insert(0, {'task': 'on-demand', 'slot': None, 'trigger': 'sweep', 'not_before': 0, 'attempt': 1})
                self.cv.notify_all()
            if not cfg['enabled']:
                self._save_runs(d)
                return
            status = self.sched.status(now.replace(tzinfo=None))
            today = now.date()
            mins = now.hour * 60 + now.minute + now.second / 60
            by_sid = {s['id']: s for s in cfg['digests']}
            for sid, task, hm, label in self.slots_for(today, cfg):
                key = '%s@%s %s' % (sid, today.isoformat(), hm)
                if key in d['slots']:
                    continue
                late = (mins - _hm(hm)) * 60
                kind = TASKS[task]['kind']
                if late < 0:
                    continue
                if cfg.get('enabled_at') and '%s %s' % (today.isoformat(), hm) < cfg['enabled_at'][:16].replace('T', ' '):
                    continue                            # before the Mac mini took over the schedule
                if late > (DIGEST_GRACE if kind == 'digest' else P0_GRACE):
                    d['slots'][key] = 'missed'          # service was down – the guard / next run catches up
                    continue
                if kind == 'digest' and not status['digests'] or kind == 'p0' and not status['urgent']:
                    d['slots'][key] = 'skipped: ' + (status['reason'] or 'paused')
                    continue
                busy_digest = (self.current and TASKS[self.current['run']['task']]['kind'] == 'digest') or \
                    any(TASKS[j['task']]['kind'] == 'digest' for j in self.queue)
                if kind == 'p0' and busy_digest:
                    d['slots'][key] = 'skipped: a digest is running'   # AXELLA.md overlap rule
                    continue
                if kind == 'p0' and (any(j['task'] == 'p0-check' for j in self.queue) or
                                     (self.current and self.current['run']['task'] == 'p0-check')):
                    d['slots'][key] = 'skipped: previous check still running'
                    continue
                why = None
                if kind == 'p0' and not hm.endswith(':00'):
                    new, why = self.anything_new()
                    if not new:
                        d['slots'][key] = 'skipped: nothing new (%s)' % why
                        continue
                worlds = None
                if kind == 'digest' and sid in by_sid:
                    worlds = scope_mod.effective(scope_mod.worlds_of(by_sid[sid]), status.get('work_paused'))
                    if not worlds:
                        d['slots'][key] = 'skipped: ' + (status.get('reason') or 'work digests paused')
                        continue
                d['slots'][key] = 'queued'
                job = {'task': task, 'slot': key, 'label': label, 'trigger': 'schedule', 'not_before': 0, 'attempt': 1, 'why': why}
                if kind == 'digest' and self.away_due and not self._briefing_busy():
                    try:
                        ab = self.away_due(today)
                    except Exception as e:
                        ab = None
                        self.log.write('%s away check: %s\n' % (_iso(), str(e)[:200]))
                    if ab:                      # back from 2+ days away: this slot's digest is the briefing (once)
                        job.update(task='return-briefing', label=TASKS['return-briefing']['label'], away=ab)
                if worlds:
                    job.update(worlds=worlds, mention_other=by_sid[sid].get('mention_other', True),
                               wrap=bool(by_sid[sid].get('wrap', True)))
                if kind == 'digest':        # digests go before waiting checks
                    self.queue.insert(0, job)
                else:
                    self.queue.append(job)
                self.cv.notify_all()
            self._auto_briefings(d, now, status)
            self._auto_receipts(d, now)
            self._auto_feedback_pull(d, now)
            self._auto_feedback_summary(d, now)
            self._auto_kb(d, now)
            self._save_runs(d)

    # ---------- briefings: research/news briefs at their own times ----------
    def _queue_brief(self, bid, name, trigger, slot=None):
        ref = self.briefings.request(bid)
        self.queue.append({'task': 'briefing', 'slot': slot, 'label': 'Briefing: ' + name, 'trigger': trigger,
                           'not_before': 0, 'attempt': 1, 'ref': ref, 'briefing': bid})
        self.cv.notify_all()
        return ref

    def _auto_briefings(self, d, now, status):
        if not self.briefings:
            return
        try:
            mins = now.hour * 60 + now.minute
            for bid, hm, name in self.briefings.slots_for(now.date()):
                key = 'brief-%s@%s %s' % (bid, now.date().isoformat(), hm)
                if key in d['slots']:
                    continue
                late = (mins - _hm(hm)) * 60
                if late < 0:
                    continue
                if late > BRIEF_GRACE:
                    d['slots'][key] = 'missed'
                elif not status['digests']:
                    d['slots'][key] = 'skipped: ' + (status['reason'] or 'paused')     # vacation / days off pause briefs too
                elif any(j.get('briefing') == bid for j in self.queue):
                    d['slots'][key] = 'skipped: already queued'
                else:
                    d['slots'][key] = 'queued'
                    self._queue_brief(bid, name, 'schedule', slot=key)
        except Exception as e:
            self.log.write('%s briefings: %s\n' % (_iso(), str(e)[:300]))

    # ---------- nightly receipts catch-up: only when documents are missing details or an amount ----------
    AUTO_RECEIPTS_AT = '03:10'
    def receipts_todo(self):
        """Message ids the receipts catch-up should look at: entries still waiting for details, and entries without an
        amount that have a PDF (the price is often only there). Each id is tried at most twice, so an unreadable PDF
        doesn't start a run every night."""
        try:
            with open(os.path.join(self.state_dir, 'documents.json'), encoding='utf-8') as f:
                docs = json.load(f).get('documents', {})
        except (FileNotFoundError, json.JSONDecodeError):
            return [], {}
        try:
            with open(os.path.join(self.state_dir, 'receipts-auto.json'), encoding='utf-8') as f:
                tried = json.load(f).get('tried', {})
        except (FileNotFoundError, json.JSONDecodeError):
            tried = {}
        todo = []
        for mid, x in docs.items():
            if x.get('hidden'):
                continue
            pdf = any(str(a).lower().endswith('.pdf') for a in x.get('attachments') or [])
            no_amount = x.get('amount') is None and x.get('kind') in ('receipt', 'invoice', 'bill', 'credit') and \
                'amount' not in (x.get('manual') or [])
            if (x.get('needs_details') or (no_amount and pdf)) and tried.get(mid, 0) < 2:
                todo.append(mid)
        return todo, tried

    def _auto_receipts(self, d, now):
        hm = self.AUTO_RECEIPTS_AT
        key = 'receipts-auto@%s %s' % (now.date().isoformat(), hm)
        late = (now.hour * 60 + now.minute - _hm(hm)) * 60
        if key in d['slots'] or late < 0:
            return
        if late > 6 * 3600:
            d['slots'][key] = 'missed'
            return
        if any(j['task'] == 'receipts-catchup' for j in self.queue) or \
                (self.current and self.current['run']['task'] == 'receipts-catchup'):
            d['slots'][key] = 'skipped: a receipts catch-up is already running'
            return
        todo, tried = self.receipts_todo()
        if not todo:
            d['slots'][key] = 'skipped: nothing to complete'
            return
        for mid in todo:
            tried[mid] = tried.get(mid, 0) + 1
        with open(os.path.join(self.state_dir, 'receipts-auto.json'), 'w', encoding='utf-8') as f:
            json.dump({'tried': tried, 'last': _iso()}, f)
        d['slots'][key] = 'queued'
        self.queue.append({'task': 'receipts-catchup', 'slot': key, 'label': 'Receipts catch-up (nightly)', 'trigger': 'schedule',
                           'not_before': 0, 'attempt': 1, 'why': '%d document(s) to complete' % len(todo)})
        self.cv.notify_all()

    # ---------- axella.dev feedback: nightly pull (plain script) + Sunday summary (Claude, isolated) ----------
    FEEDBACK_PULL_AT = '03:20'
    FEEDBACK_SUMMARY_AT = '20:00'          # Sundays, before the 20:30 week-ahead that carries its one line
    FEEDBACK_SUMMARY_DAY = 6

    def _feedback_state(self, name):
        try:
            with open(os.path.join(self.state_dir, name), encoding='utf-8') as f:
                return json.load(f) or {}
        except (OSError, ValueError):
            return {}

    def _auto_feedback_pull(self, d, now):
        """03:20: setup/feedback_pull.py – outbound, read-only token from the Keychain, no Claude. Runs in its own thread
        (network); the slot shows how it went. The token is never in the log: only the script's own short output is."""
        hm = self.FEEDBACK_PULL_AT
        key = 'feedback-pull@%s %s' % (now.date().isoformat(), hm)
        late = (now.hour * 60 + now.minute - _hm(hm)) * 60
        if key in d['slots'] or late < 0:
            return
        # the script keeps its own record (state/feedback-pull.json) – a pull that ran today counts, even if the slot's
        # result was lost (a restart between the pull and its write-back showed "missed" for a pull that had run)
        last = self._feedback_state('feedback-pull.json').get('last_run') or ''
        try:
            ran = datetime.datetime.fromisoformat(last).astimezone() if last else None
        except ValueError:
            ran = None
        if ran and ran.date() == now.date() and ran >= now.replace(hour=0, minute=0, second=0, microsecond=0):
            d['slots'][key] = 'ok: ran %s' % ran.strftime('%H:%M')
            return
        if late > 6 * 3600:
            d['slots'][key] = 'missed'
            return
        d['slots'][key] = 'running'

        def pull():
            res = self.feedback_pull()
            with LOCK:
                dd = self._load_runs()
                dd['slots'][key] = res
                self._save_runs(dd)
        threading.Thread(target=pull, daemon=True).start()

    def feedback_pull(self):
        script = os.path.join(self.base, 'setup', 'feedback_pull.py')
        if not os.path.exists(script):
            return 'skipped: setup/feedback_pull.py not installed'
        try:
            r = subprocess.run([sys.executable, script], cwd=self.base, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            return 'failed: timed out'
        out = (r.stdout or '').strip().splitlines()[-1:] or (r.stderr or '').strip().splitlines()[-1:] or ['']
        msg = out[0][:120]
        if r.returncode == 0:
            return 'ok: ' + (msg or 'done')
        if r.returncode == 1:                # no export token: this Axella isn't the axella.dev owner's – nothing to pull
            return 'skipped: no export token in the Keychain'
        return 'failed (%s): %s' % ('network' if r.returncode == 2 else 'exit %d' % r.returncode, msg)

    def feedback_new(self):
        """(new?, why) – entries pulled since the last summary? Compares the pull cursor with the cursor the last
        successful summary covered."""
        pulled = self._feedback_state('feedback-pull.json').get('cursor') or 0
        done = self._feedback_state('feedback-summary.json').get('cursor') or 0
        if not glob.glob(os.path.join(self.base, 'feedback', 'inbox', '*.jsonl')):
            return False, 'no feedback pulled yet'
        if pulled and pulled == done:
            return False, 'nothing new since the last summary'
        return True, 'new entries since the last summary (cursor %s → %s)' % (done, pulled)

    def _auto_feedback_summary(self, d, now):
        if now.weekday() != self.FEEDBACK_SUMMARY_DAY:
            return
        hm = self.FEEDBACK_SUMMARY_AT
        key = 'feedback-summary@%s %s' % (now.date().isoformat(), hm)
        late = (now.hour * 60 + now.minute - _hm(hm)) * 60
        if key in d['slots'] or late < 0:
            return
        if late > 3 * 3600:
            d['slots'][key] = 'missed'
            return
        if any(j['task'] == 'feedback-summary' for j in self.queue):
            d['slots'][key] = 'skipped: already queued'
            return
        new, why = self.feedback_new()
        if not new:
            d['slots'][key] = 'skipped: ' + why
            return
        d['slots'][key] = 'queued'
        self.queue.insert(0, {'task': 'feedback-summary', 'slot': key, 'label': 'axella.dev feedback summary', 'trigger': 'schedule',
                           'not_before': 0, 'attempt': 1, 'why': why,
                           'cursor': self._feedback_state('feedback-pull.json').get('cursor') or 0})
        self.cv.notify_all()

    def _feedback_workdir(self):
        """A fresh 0700 folder outside the Axella and home folders with a copy of feedback/inbox and last week's summary –
        all the run can see."""
        import tempfile
        work = os.path.realpath(tempfile.mkdtemp(prefix='axella-feedback-'))
        home, base = os.path.realpath(os.path.expanduser('~')), os.path.realpath(self.base)
        if work.startswith(home + os.sep) or work.startswith(base + os.sep):
            shutil.rmtree(work, ignore_errors=True)
            raise Bad('temporary folder is inside the home folder – feedback summary not started')
        os.chmod(work, 0o700)
        os.makedirs(os.path.join(work, 'feedback', 'inbox'))
        files = []
        for p in sorted(glob.glob(os.path.join(self.base, 'feedback', 'inbox', '*.jsonl'))):
            if os.path.isfile(p) and not os.path.islink(p):
                shutil.copyfile(p, os.path.join(work, 'feedback', 'inbox', os.path.basename(p)))
                files.append('feedback/inbox/' + os.path.basename(p))
        prev = os.path.join(self.base, 'feedback', 'summary.md')
        if os.path.isfile(prev) and not os.path.islink(prev):
            shutil.copy2(prev, os.path.join(work, 'feedback', 'summary.md'))     # keeps its old time: unchanged = not collected
        return work, files

    def _feedback_command(self, prompt, job):
        """Sonnet, no MCP servers, no web, no shell. Read only the copied feedback/ folder, write only feedback/summary.md
        there; reads of the Axella and home folders and every secret are denied outright."""
        claude = self.claude_bin()
        if not claude:
            raise Bad('claude CLI not found on this Mac')
        work, files = self._feedback_workdir()
        if job is not None:
            job['_cwd'], job['_started'] = work, time.time()
            job['_prev_summary'] = _file_hash(os.path.join(work, 'feedback', 'summary.md'))   # last week's, as copied in
            job.setdefault('cursor', self._feedback_state('feedback-pull.json').get('cursor') or 0)   # also for "Run now"
        prompt += ('\n\nThis run: the current folder holds feedback/. The entry files are: %s. '
                   'feedback/summary.md is last week\'s summary if it exists. Read only these; write only feedback/summary.md.'
                   % (', '.join(files) or 'none'))
        allowed = ['Read(/feedback/**)', 'Edit(/feedback/summary.md)', 'Write(/feedback/summary.md)']
        never = ['Glob', 'Grep', 'Bash', 'WebFetch', 'WebSearch', 'NotebookEdit', 'Task', 'TodoWrite'] + self._brief_denies()
        cmd = [claude, '-p', prompt, '--model', 'sonnet', '--output-format', 'stream-json', '--verbose',
               '--strict-mcp-config', '--allowedTools', ','.join(allowed), '--disallowedTools', ','.join(never)]
        return cmd, 'sonnet'

    def _collect_feedback(self, job, w):
        """Copy feedback/summary.md from the scratch folder back – a plain text file under 256 kB only."""
        src = os.path.join(job['_cwd'], 'feedback', 'summary.md')
        try:
            st = os.lstat(src)
        except FileNotFoundError:
            return
        import stat as _st
        if not _st.S_ISREG(st.st_mode) or st.st_size > 256 * 1024:
            w('Summary refused (not a plain file under 256 kB)')
            return
        # unchanged copy of last week's: compared by content – a timestamp can lag time.time() on some file systems
        if job.get('_prev_summary') and _file_hash(src) == job['_prev_summary']:
            return
        dst_dir = os.path.join(self.base, 'feedback')
        os.makedirs(dst_dir, mode=0o700, exist_ok=True)
        shutil.copyfile(src, os.path.join(dst_dir, 'summary.md'))
        os.chmod(os.path.join(dst_dir, 'summary.md'), 0o600)

    def _finish_feedback(self, job, summary):
        """Remember what this summary covered, and keep its one line for the Sunday week-ahead (state/feedback-line.json).
        The line is a summary of public form text: plain, one line, no addresses – checked here, not trusted."""
        import re as _re
        lines = [ln for ln in str(summary or '').splitlines() if ln.strip()]
        line = ' '.join(lines[-1].split()) if lines else ''             # the run ends with the one line
        line = _re.sub(r'[\w.+-]+@[\w-]+(\.[\w-]+)+', '[address]', line)[:240]
        with open(os.path.join(self.state_dir, 'feedback-summary.json'), 'w', encoding='utf-8') as f:
            json.dump({'cursor': job.get('cursor') or 0, 'at': _iso()}, f)
        with open(os.path.join(self.state_dir, 'feedback-line.json'), 'w', encoding='utf-8') as f:
            json.dump({'line': line, 'at': _iso()}, f, ensure_ascii=False)
        return line[:200] or None

    # ---------- knowledge harvest: nightly sent mail + scan batches (kb_harvest.py) ----------
    def _kb_busy(self):
        return any(j['task'] == 'kb-harvest' for j in self.queue) or \
            bool(self.current and self.current['run']['task'] == 'kb-harvest')

    def _queue_kb(self, ref, label, trigger, slot=None, why=None):
        self.queue.append({'task': 'kb-harvest', 'slot': slot, 'label': label, 'trigger': trigger, 'not_before': 0,
                           'attempt': 1, 'ref': ref, 'why': why})
        self.cv.notify_all()

    def _auto_kb(self, d, now):
        h = self.harvest
        if not h:
            return
        try:
            h.ingest()
            refs = {j.get('ref') for j in self.queue if j['task'] == 'kb-harvest'}
            if self.current and self.current['run']['task'] == 'kb-harvest':
                refs.add(self.current['run'].get('ref'))
            h.clear_stale(refs)
            if self._kb_busy():
                return
            # 1. the owner pressed "Run a batch now"
            sid = h.take_now()
            if sid:
                ref = 'kb' + now.strftime('%Y%m%d%H%M%S')
                if h.scan_request(ref, sid):
                    self._queue_kb(ref, 'Knowledge scan (now)', 'manual')
                return
            mins = now.hour * 60 + now.minute
            # 2. nightly sent-mail harvest
            key = 'kb-nightly@%s %s' % (now.date().isoformat(), kb_harvest.NIGHTLY_AT)
            late = mins - _hm(kb_harvest.NIGHTLY_AT)
            if key not in d['slots'] and late >= 0:
                if late > 4 * 60:
                    d['slots'][key] = 'missed'
                else:
                    ref = 'kb' + now.strftime('%Y%m%d%H%M%S')
                    if h.nightly_request(ref):
                        d['slots'][key] = 'queued'
                        self._queue_kb(ref, 'Knowledge harvest (nightly)', 'schedule', slot=key)
                        return
                    d['slots'][key] = 'skipped: switched off'
            # 3. scan batches, at night only
            start, end = (_hm(x) for x in kb_harvest.WINDOW)
            if not (start <= mins < end):
                return
            night = now.date().isoformat()
            if h.batches_tonight(night) >= kb_harvest.MAX_BATCHES:
                return
            if any(TASKS[j['task']]['kind'] in ('digest', 'receipts') for j in self.queue):
                return                                   # let the other night jobs go first
            s = h.next_scan()
            if s:
                ref = 'kb' + now.strftime('%Y%m%d%H%M%S')
                if h.scan_request(ref, s['id'], night=night):
                    self._queue_kb(ref, 'Knowledge scan: ' + (s.get('label') or '')[:40], 'schedule',
                                   why='batch from thread %d' % (s.get('offset') or 0))
        except Exception as e:
            self.log.write('%s kb harvest: %s\n' % (_iso(), str(e)[:300]))

    # ---------- urgent-check pre-filter: only start Claude when something arrived ----------
    def anything_new(self):
        """(True, why) if a message arrived since the last urgent check, or if anything can't be checked (fail-open).
        The :00 check always runs (calendar problems and P0 reminders can't be seen from here)."""
        import sqlite3
        home = os.path.expanduser('~')
        try:
            with open(os.path.join(self.state_dir, 'p0-last-check.txt'), encoding='utf-8') as f:
                raw = f.read()
            ts = raw.split('last_check:', 1)[1].split()[0].strip().replace('Z', '+00:00')
            since = datetime.datetime.fromisoformat(ts)
        except Exception:
            return True, 'no last check time'
        since_unix = since.timestamp()
        counts = {}
        # Mail: Mail's own index (read-only copy of the numbers – Mail itself is not touched)
        try:
            idx = sorted(glob.glob(home + '/Library/Mail/V*/MailData/Envelope Index'))[-1]
            con = sqlite3.connect('file:%s?mode=ro' % idx, uri=True, timeout=5)
            counts['mail'] = con.execute(
                "select count(*) from messages m join mailboxes b on m.mailbox = b.ROWID "
                "where m.date_received > ? and (lower(b.url) like '%/inbox' or lower(b.url) like '%/inbox/%')",
                (int(since_unix),)).fetchone()[0]
            con.close()
        except Exception as e:
            return True, 'mail not checkable: %s' % str(e)[:80]
        # iMessage/SMS: Messages' database (dates are nanoseconds since 2001-01-01)
        try:
            con = sqlite3.connect('file:%s?mode=ro' % (home + '/Library/Messages/chat.db'), uri=True, timeout=5)
            counts['messages'] = con.execute('select count(*) from message where is_from_me = 0 and date > ?',
                                             (int((since_unix - 978307200) * 1e9),)).fetchone()[0]
            con.close()
        except Exception as e:
            return True, 'messages not checkable: %s' % str(e)[:80]
        # WhatsApp: the export file the service writes every 2 minutes
        try:
            with open(os.path.join(self.state_dir, 'whatsapp.json'), encoding='utf-8') as f:
                wa = json.load(f)
            if not wa.get('ok'):
                return True, 'whatsapp export not ok'
            n = 0
            for c in wa.get('chats', []):
                for m in c.get('messages', []):
                    try:
                        if not m.get('from_me') and datetime.datetime.fromisoformat(m['at']) > since:
                            n += 1
                    except Exception:
                        pass
            counts['whatsapp'] = n
        except Exception as e:
            return True, 'whatsapp not checkable: %s' % str(e)[:80]
        # Signal: only chats the owner keeps "normal" are in signal.json – private ones never start a run
        try:
            with open(os.path.join(self.state_dir, 'signal.json'), encoding='utf-8') as f:
                sg = json.load(f)
            if sg.get('linked'):
                counts['signal'] = sum(1 for c in sg.get('chats', []) for m in c.get('messages', [])
                                       if not m.get('from_me') and datetime.datetime.fromisoformat(m['at']) > since)
        except (OSError, ValueError, KeyError):
            pass                                     # not set up: nothing to check
        why = ', '.join('%s %d' % kv for kv in counts.items())
        return sum(counts.values()) > 0, why

    # ---------- the worker ----------
    def worker(self):
        while True:
            with LOCK:
                while True:
                    ready = [j for j in self.queue if j['not_before'] <= time.time()]
                    if ready:
                        job = ready[0]
                        self.queue.remove(job)
                        break
                    self.cv.wait(timeout=10)
            try:
                self._run(job)
            except Exception as e:
                self.log.write('%s scheduler run: %s\n' % (_iso(), str(e)[:300]))

    def _run(self, job):
        task = job['task']
        spec = TASKS[task]
        rid = _now().strftime('%Y%m%d-%H%M%S-') + task
        logp = os.path.join(self.run_dir, rid + '.log')
        run = {'id': rid, 'task': task, 'label': job.get('label') or spec['label'], 'slot': job.get('slot'),
               'trigger': job['trigger'], 'attempt': job['attempt'], 'status': 'running', 'started': _iso(),
               'ended': None, 'reason': None, 'summary': None, 'usage': None, 'model': None, 'ref': job.get('ref'),
               'briefing': job.get('briefing'),
               # what a retry after a restart needs (scope and wrap choice) – no message content
               'job': {k: job[k] for k in ('worlds', 'mention_other', 'wrap', 'away') if k in job}}
        with LOCK:
            d = self._load_runs()
            d['runs'].append(run)
            if job.get('slot'):
                d['slots'][job['slot']] = rid
            self._save_runs(d)
        lf = open(logp, 'a', encoding='utf-8')

        def w(line):
            lf.write('%s  %s\n' % (_now().strftime('%H:%M:%S'), line))
            lf.flush()

        start = time.time()
        status, reason, summary, usage, model = 'failed', None, None, None, None
        try:
            cmd, model = self._command(task, job)
            run['model'] = model
            self._update_run(rid, model=model)
            w('Starting %s (%s, attempt %d, model %s)' % (run['label'], job['trigger'], job['attempt'], model))
            if job.get('why'):
                w('Pre-check: new since last check – ' + job['why'])
            env = {k: v for k, v in os.environ.items() if k not in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN')}
            home = os.path.expanduser('~')
            env['MCP_TIMEOUT'] = '180000'
            env['PATH'] = ':'.join([home + '/.local/bin', home + '/.claude/local', '/opt/homebrew/bin', '/usr/local/bin',
                                    env.get('PATH', '/usr/bin:/bin:/usr/sbin:/sbin')])
            proc = subprocess.Popen(cmd, cwd=job.get('_cwd') or self.base, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, bufsize=1)
            with LOCK:
                self.current = {'run': run, 'proc': proc, 'cancelled': False, 't0': start}
            err_lines = []
            threading.Thread(target=lambda: err_lines.extend(proc.stderr), daemon=True).start()
            killer = threading.Timer(spec['timeout'], self._kill, args=(proc, 'timeout'))
            killer.daemon = True
            killer.start()
            result, stats = None, {}
            for line in proc.stdout:
                ev = self._event(line, w, stats)
                if ev and ev.get('type') == 'result':
                    result = ev
            proc.wait()
            killer.cancel()
            for e in [x for x in err_lines if 'unknown format' not in x][-20:]:   # skip Macuse's schema warnings
                w('stderr: ' + e.rstrip()[:400])
            with LOCK:
                cancelled = self.current and self.current.get('cancelled')
            if job.get('_cwd') and spec['kind'] == 'feedback':
                self._collect_feedback(job, w)
            elif job.get('_cwd'):
                self._collect_brief(job, w)
            if result:
                summary = (result.get('result') or '').strip()[:500] or None
                u = result.get('usage') or {}
                usage = {'input': u.get('input_tokens', 0) + u.get('cache_read_input_tokens', 0) + u.get('cache_creation_input_tokens', 0),
                         'output': u.get('output_tokens', 0), 'turns': result.get('num_turns'),
                         'cost_usd': result.get('total_cost_usd')}
            if spec['kind'] == 'ask' and self.ask_notes_done:
                try:                                    # notes read (a Grep over the folder counts as all of them)
                    nread = stats.get('notes') or set()
                    folder = os.path.join(self.state_dir, 'ask-notes', str(job.get('ref') or ''))
                    total = len([x for x in os.listdir(folder) if x.endswith('.txt')]) if os.path.isdir(folder) else 0
                    n = total if any(x.startswith('*') for x in nread) else len([x for x in nread if x.endswith('.txt')])
                    self.ask_notes_done(job.get('ref'), min(n, total) if total else n)
                except Exception as e:
                    w('Ask notes: %s' % str(e)[:200])
            if cancelled == 'cancel':
                status, reason = 'cancelled', 'cancelled from the dashboard'
            elif cancelled == 'timeout':
                status, reason = 'failed', 'timed out after %d min' % (spec['timeout'] // 60)
            elif proc.returncode != 0 or (result and result.get('is_error')):
                status = 'failed'
                reason = (result or {}).get('subtype') if result and result.get('subtype') != 'success' else None
                reason = reason or ((err_lines[-1].strip()[:200]) if err_lines else 'exit code %s' % proc.returncode)
            elif spec['kind'] in ('digest', 'p0') and not stats.get('macuse_calls'):
                status, reason = 'failed', 'Macuse (Mail/Messages/Calendar) not available – %s tools' % stats.get('macuse_tools', 0)
            elif spec['kind'] == 'briefing' and self.briefings.check(job['ref']):
                status, reason = 'failed', self.briefings.check(job['ref'])
            elif spec['kind'] == 'briefing-personal' and self.briefings.check_personal(job['ref']):
                status, reason = 'failed', self.briefings.check_personal(job['ref'])
            elif not self._wrote_output(spec['kind'], start, job):
                status, reason = 'failed', 'finished but wrote no output file'
                if stats.get('macuse_server') and not stats.get('macuse_tools'):   # e.g. the knowledge harvest: Macuse was the cause
                    reason = 'Macuse (Mail/Messages/Calendar) not available – 0 tools'
            elif self._bad_json(spec['kind'], start, job):
                status, reason = 'failed', self._bad_json(spec['kind'], start, job)
            else:
                status = 'ok'
                if spec['kind'] == 'briefing':
                    br = self.briefings.finish(job['ref'], outbound={'queries': stats.get('queries') or [],
                                                                     'fetched': stats.get('fetched') or []})
                    reason = br['headline'][:200]
                    w('Brief stored: %d item(s)%s; %d query(ies), %d page(s) fetched' % (
                        len(br['items']), ' – nothing new' if br['nothing_new'] else '',
                        len(br['outbound']['queries']), br['outbound']['fetched']))
                    for q in br['outbound']['queries']:
                        w('  searched: ' + q)
                    for u in br['outbound'].get('urls') or []:
                        w('  fetched: ' + u)
                    if br['dropped']:
                        w('Left out (already told or no link): ' + '; '.join(br['dropped'])[:500])
                    if self.briefings.needs_personal(job['ref']) and not br['nothing_new']:
                        with LOCK:
                            self.queue.insert(0, {'task': 'briefing-personal', 'slot': None, 'trigger': 'after brief',
                                                  'label': 'Personal note: ' + br['name'], 'not_before': 0, 'attempt': 1,
                                                  'ref': job['ref'], 'briefing': job.get('briefing')})
                            self.cv.notify_all()
                elif spec['kind'] == 'briefing-personal':
                    self.briefings.finish_personal(job['ref'])
                elif spec['kind'] == 'feedback':
                    reason = self._finish_feedback(job, summary)
                if spec['kind'] == 'digest':
                    out = self._scope_enforce(start, job)
                    if out:
                        w('SCOPE: %d item(s) from the other world taken out – they wait for the next digest that covers it' % out)
                    reason = self._count_check(start)       # a mismatch is shown on the run, the digest stays
                    if reason:
                        w('CHECK: ' + reason)
        except Exception as e:
            reason = str(e)[:300]
            w('ERROR: ' + reason)
        finally:
            with LOCK:
                self.current = None
            if job.get('_cwd'):                         # the run's scratch folder: only request.json/result.json lived there
                shutil.rmtree(job.pop('_cwd'), ignore_errors=True)
        dur = int(time.time() - start)
        w('%s in %dm%02ds%s' % (status.upper(), dur // 60, dur % 60, (' – ' + reason) if reason else ''))
        lf.close()
        self._update_run(rid, status=status, reason=reason, ended=_iso(), summary=summary, usage=usage)
        if status == 'failed' and not job.get('no_retry'):
            if job['attempt'] == 1:
                with LOCK:
                    self.queue.append({**job, 'attempt': 2, 'trigger': 'retry', 'not_before': time.time() + RETRY_AFTER})
                    self.cv.notify_all()
            else:
                self._alert_failed(task, run['label'], reason)
        elif status == 'ok':
            self._alert_ok(task)

    # One push when a problem starts, one reminder if it is still there after ALERT_REMIND, one when it is fixed –
    # not one per failed run. Runs that fail because Macuse is down share one alert. state/run-alerts.json keeps it
    # across restarts: task names, labels, times and the short reason only.
    def _alert_key(self, task, reason):
        return 'macuse' if (reason or '').startswith('Macuse (') else task

    def _alerts(self):
        try:
            with open(os.path.join(self.state_dir, 'run-alerts.json')) as f:
                a = json.load(f)
            return a if isinstance(a, dict) else {}
        except (OSError, ValueError):
            return {}

    def _alerts_save(self, a):
        p = os.path.join(self.state_dir, 'run-alerts.json')
        tmp = p + '.tmp'
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(a, f)
        os.replace(tmp, p)

    def _alert_push(self, msg):
        try:
            self.push(msg)
        except Exception as e:
            self.log.write('%s run-alert push: %s\n' % (_iso(), str(e)[:200]))

    def _alert_failed(self, task, label, reason, now=None):
        now = time.time() if now is None else now
        key = self._alert_key(task, reason)
        with ALERT_LOCK:
            alerts = self._alerts()
            a = alerts.get(key)
            if a:
                a['count'] = a.get('count', 1) + 1
                if task not in a['tasks']:
                    a['tasks'].append(task)
                a['reason'] = (reason or '')[:150]
                if now - a.get('pushed', 0) < ALERT_REMIND:
                    self._alerts_save(alerts)
                    return
                a['pushed'] = now
                title = 'Axella: Macuse still not available' if key == 'macuse' else 'Axella: %s still failing' % label
                body = 'Since %s, %d failed runs – %s' % (time.strftime('%a %H:%M', time.localtime(a['since'])), a['count'],
                                                          a['reason'] or 'see Runs in the dashboard')
            else:
                a = alerts[key] = {'since': now, 'pushed': now, 'count': 1, 'tasks': [task], 'label': label,
                                   'reason': (reason or '')[:150]}
                title = 'Axella: Macuse not available' if key == 'macuse' else 'Axella: %s failed twice' % label
                body = (reason or 'see Runs in the dashboard') + ' – you get one more message when it works again'
            self._alerts_save(alerts)
        self._alert_push({'title': title, 'body': body[:150], 'tag': 'axella-alert-' + key, 'url': '/axella/?v=runs'})

    def _alert_ok(self, task, now=None):
        now = time.time() if now is None else now
        with ALERT_LOCK:
            alerts = self._alerts()
            done = [(k, a) for k, a in alerts.items() if task in (a.get('tasks') or [])]
            if not done:
                return
            for k, _ in done:
                del alerts[k]
            self._alerts_save(alerts)
        for k, a in done:
            self._alert_push({'title': 'Axella: Macuse works again' if k == 'macuse' else 'Axella: %s works again' % a.get('label', k),
                              'body': 'Failed %d run(s) since %s – back to normal.' % (
                                  a.get('count', 1), time.strftime('%a %H:%M', time.localtime(a.get('since', now)))),
                              'tag': 'axella-alert-' + k, 'url': '/axella/?v=runs'})

    def _kill(self, proc, why):
        with LOCK:
            if self.current and self.current['proc'] is proc:
                self.current['cancelled'] = why
        try:
            proc.terminate()
            time.sleep(10)
            if proc.poll() is None:
                proc.kill()
        except OSError:
            pass

    def _bad_json(self, kind, start, job=None):
        """The run's .json output is checked here, in Python – the runs may not run validation commands themselves.
        Returns a short reason when a file written during this run doesn't parse, else None."""
        if kind == 'digest':
            paths = [p for p in glob.glob(os.path.join(self.base, 'digests', '*.json')) if not p.endswith('-p0.json')]
        elif kind in ('compose', 'ask'):
            paths = [os.path.join(self.state_dir, kind, '%s.json' % (job or {}).get('ref'))]
        else:
            return None
        for p in paths:
            try:
                if os.path.getmtime(p) < start - 1:
                    continue
                with open(p, encoding='utf-8') as f:
                    data = json.load(f)
                if kind == 'digest' and not isinstance((data or {}).get('items'), list):
                    return '%s has no "items" list' % os.path.basename(p)
            except FileNotFoundError:
                continue
            except ValueError as e:
                return '%s is not valid JSON (%s)' % (os.path.basename(p), str(e)[:80])
        return None

    def _count_check(self, start):
        """Does the intro's "N still open" / "N to answer" match the items in the digest's .json? (AXELLA.md Carry-over)"""
        import re as _re
        paths = sorted((p for p in glob.glob(os.path.join(self.base, 'digests', '*.json'))
                        if not p.endswith('-p0.json') and os.path.getmtime(p) >= start - 1), key=os.path.getmtime)
        if not paths:
            return None
        try:
            with open(paths[-1], encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            return None
        items, intro = d.get('items') or [], str(d.get('intro') or '')
        # only messages are "to answer" – a calendar note or an (older) "Your tasks" card isn't
        items = [i for i in items if i.get('channel') != 'calendar' and not str(i.get('headline') or '').startswith('Your tasks')]
        have = {'still open': sum(1 for i in items if i.get('section') == 'open'),
                'to answer': sum(1 for i in items if i.get('section') in ('p0', 'p1', 'p2'))}
        words = {'no': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10}
        fresh = sum(1 for i in items if i.get('section') in ('p0', 'p1', 'p2') and not i.get('carried'))
        off = []
        for label, n in have.items():
            m = _re.search(r'\b(\d+|' + '|'.join(words) + r')\s+(new\s+)?' + label, intro, _re.I)
            if m:
                said = int(m.group(1)) if m.group(1).isdigit() else words[m.group(1).lower()]
                if m.group(2) and label == 'to answer':
                    n = fresh                                  # "1 new to answer" = items not carried over
                if said != n:
                    off.append('intro says %d %s%s, the digest has %d' % (said, 'new ' if m.group(2) else '', label, n))
        return ('count check: ' + '; '.join(off)) if off else None

    def _wrote_output(self, kind, start, job=None):
        def newer(paths):
            return any(os.path.getmtime(p) >= start - 1 for p in paths if os.path.exists(p))
        if kind == 'digest':
            return newer([p for p in glob.glob(os.path.join(self.base, 'digests', '*.json')) if not p.endswith('-p0.json')])
        if kind == 'p0':
            return newer([os.path.join(self.state_dir, 'p0-last-check.txt')])
        if kind in ('compose', 'ask'):
            return newer([os.path.join(self.state_dir, kind, '%s.json' % (job or {}).get('ref'))])
        if kind == 'feedback':
            return newer([os.path.join(self.base, 'feedback', 'summary.md')])
        if kind in ('trips', 'projects'):
            ref = (job or {}).get('ref')
            f = {'trips': 'trips-read', 'projects': 'project-read'}[kind]
            return newer([os.path.join(self.state_dir, f, ref + '.json'), os.path.join(self.state_dir, f, 'done', ref + '.json')])
        if kind == 'kb':        # the result may already have been merged (moved to state/kb/done/)
            ref = (job or {}).get('ref')
            return newer([os.path.join(self.state_dir, 'kb', ref + '.json'), os.path.join(self.state_dir, 'kb', 'done', ref + '.json')])
        return True                      # receipts: nothing to do is fine

    # ---------- claude command ----------
    def claude_bin(self):
        home = os.path.expanduser('~')
        for p in [home + '/.local/bin/claude', home + '/.claude/local/claude', '/opt/homebrew/bin/claude',
                  '/usr/local/bin/claude', shutil.which('claude') or '']:
            if p and os.path.exists(p):
                return p
        return None

    def mcp_file(self):
        return os.path.join(self.state_dir, 'mcp.json')

    def _command(self, task, job=None):
        spec = TASKS[task]
        prompt_path = os.path.join(self.prompt_dir, task + '.md')
        if not os.path.exists(prompt_path):
            raise Bad('prompt missing: setup/local-tasks/%s.md' % task)
        with open(prompt_path, encoding='utf-8') as f:
            prompt = f.read().strip()
        if spec['kind'] in ('compose', 'ask', 'kb', 'trips', 'projects'):
            cid, k = (job or {}).get('ref'), {'trips': 'trips-read', 'projects': 'project-read'}.get(spec['kind'], spec['kind'])
            prompt += ('\n\nThis request: read state/%s/%s.request.json and write the result to state/%s/%s.json.'
                       % (k, cid, k, cid))
        if spec['kind'] in ('briefing', 'briefing-personal'):
            return self._brief_command(spec, prompt, (job or {}).get('ref'), job)
        if spec['kind'] == 'digest':
            prompt += self._scope_note(job or {})
            prompt += self._wrap_note(task, job or {})
            prompt += self._away_note(task, job or {})
        if spec['kind'] in ('digest', 'p0'):
            prompt += self._learned_note()
        if spec['kind'] == 'feedback':
            return self._feedback_command(prompt, job)
        claude = self.claude_bin()
        if not claude:
            raise Bad('claude CLI not found on this Mac')
        if not os.path.exists(self.mcp_file()):
            raise Bad('state/mcp.json missing (Macuse MCP config)')
        models = self.load()['models']
        model = models.get(spec['kind']) or (models.get('compose') or 'sonnet' if spec['kind'] in ('ask', 'kb', 'trips', 'projects') else models['digest'])
        # Reading: the Axella folder only ("/" = this folder). The receipts catch-up also opens the PDFs Mail or Macuse
        # saves for it (attachment folders and temporary files) – not the rest of the Mac. Secrets are refused for
        # every kind of run, and so are the message stores themselves (APP_STORES), which would bypass mcp_filter.py.
        # Macuse's mail_get_attachment hands the PDF's text back itself, so no run reads Mail's folders or temporary
        # files (those hold every mail's attachments, private contacts' too, and other runs' scratch files).
        reads = ['Read(/**)']
        allowed = reads + ['Glob', 'Grep', 'Bash(ls:*)', 'Bash(date:*)', 'TodoWrite']
        for p in WRITES[spec['kind']]:
            allowed += ['Edit(/%s)' % p, 'Write(/%s)' % p]
        reading = list(MACUSE_READ)
        if spec['kind'] in ('trips', 'projects'):   # "Read with Claude" only opens the mails you picked: no search, no chats
            reading = ['mail_get_messages', 'mail_get_attachment']
        if self._window_reading_unsafe():           # private chats: no reading of app windows, only the filtered exports
            reading = [t for t in reading if not t.startswith('computer_use_')]
        allowed += ['mcp__macuse__' + t for t in reading]
        never = ['mcp__macuse__' + t for t in MACUSE_NEVER] + ['WebFetch', 'WebSearch', 'Task', 'NotebookEdit']
        never += ['mcp__macuse__' + t for t in MACUSE_READ if t not in reading]
        for secret in SECRETS:                     # relative to this folder and as absolute paths
            never += ['%s(/%s)' % (t, secret) for t in ('Read', 'Grep', 'Glob')]
            never += ['%s(/%s)' % (t, os.path.join(self.base, secret)) for t in ('Read', 'Grep', 'Glob')]
        never += ['Read(~/.ssh/**)', 'Read(~/Library/Keychains/**)', 'Read(~/.aws/**)', 'Read(~/.config/**)', 'Read(~/.claude/**)']
        never += ['Read(%s)' % p for p in APP_STORES]
        never += ['Read(/reports/**)', 'Read(/%s/reports/**)' % self.base]   # problem reports may hold a real screenshot
        if spec['kind'] != 'ask':                  # Notes: only an Ask run reads its own filtered copy of them
            never += ['%s(/state/ask-notes/**)' % t for t in ('Read', 'Grep', 'Glob')] + \
                     ['%s(/%s/state/ask-notes/**)' % (t, self.base) for t in ('Read', 'Grep', 'Glob')]
        never += ['%s(/%s)' % (t, FEEDBACK_INBOX) for t in ('Read', 'Grep', 'Glob')] + \
                 ['%s(/%s/%s)' % (t, self.base, FEEDBACK_INBOX) for t in ('Read', 'Grep', 'Glob')]
        cmd = [claude, '-p', prompt, '--model', model, '--output-format', 'stream-json', '--verbose',
               '--mcp-config', self.run_mcp_file(), '--strict-mcp-config',
               '--allowedTools', ','.join(allowed), '--disallowedTools', ','.join(never)]
        return cmd, model

    def _privacy_strict(self, ch):
        import privacy
        d = privacy.Privacy(self.state_dir).load()
        if d.get('broken'):                              # privacy.json can't be read: strict, filter everything
            return True
        return d['defaults'].get(ch) != 'normal' or any(
            (c.get('levels') or {}).get(ch, (c.get('levels') or {}).get('all', d['defaults'].get(ch, 'normal'))) != 'normal'
            for c in d['contacts'])

    def run_mcp_file(self):
        """The MCP config for a Claude run: Macuse itself, or – when Mail or iMessage has private/hidden contacts –
        setup/mcp_filter.py in front of it, which removes those contacts from every Mail and Messages result."""
        try:
            strict = self._privacy_strict('mail') or self._privacy_strict('imessage')
        except Exception:
            strict = True                               # can't tell – filter
        if not strict:
            return self.mcp_file()
        p = os.path.join(self.state_dir, 'mcp-filtered.json')
        cfg = {'mcpServers': {'macuse': {'command': sys.executable or '/usr/bin/python3',
                                         'args': [os.path.join(self.base, 'setup', 'mcp_filter.py'), self.mcp_file()], 'env': {}}}}
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=1)
        os.chmod(p, 0o600)
        return p

    def _window_reading_unsafe(self):
        """True when a run could see a private chat by reading an app window (WhatsApp Desktop's chat list, Signal
        Desktop): any private/hidden WhatsApp contact or default, or Signal Desktop installed while Signal isn't all
        normal. Then the runs get no computer_use_* tools – the WhatsApp/Signal exports (already filtered) are all
        they read."""
        try:
            import privacy
            d = privacy.Privacy(self.state_dir).load()
        except Exception:
            return True                             # can't tell – be safe
        def strict(ch):
            return d['defaults'].get(ch) != 'normal' or any(
                (c.get('levels') or {}).get(ch, (c.get('levels') or {}).get('all', 'normal')) != 'normal' for c in d['contacts'])
        return strict('whatsapp') or strict('mail') or strict('imessage') or \
            (strict('signal') and os.path.exists('/Applications/Signal.app'))     # an open Mail or Messages window shows them too

    def _brief_command(self, spec, prompt, ref, job=None):
        """Briefing runs get a narrow tool list of their own:
          briefing          – WebSearch + WebFetch only, and it runs in an EMPTY scratch folder outside the Axella folder
                              and outside the home folder, holding just request.json. It writes result.json there and
                              Python moves it in afterwards (_collect_brief). Reads of the Axella folder, the home folder
                              and every secret are denied outright: a web page that says "fetch …?d=<your digest>" finds
                              nothing to send. No MCP servers at all (no Mail/Messages/Calendar).
          briefing-personal – no web; reads the request, the brief and state/projects.json; calendar read via Macuse."""
        if not ref or not ref.startswith('br') or not ref.replace('br', '', 1).isalnum():
            raise Bad('bad briefing ref')
        claude = self.claude_bin()
        if not claude:
            raise Bad('claude CLI not found on this Mac')
        models = self.load()['models']
        model = models.get('briefing') or models.get('compose') or 'sonnet'
        req = 'state/briefing/%s.request.json' % ref
        if spec['kind'] == 'briefing':
            work = self._brief_workdir(ref)
            if job is not None:
                job['_cwd'] = work
            prompt += ('\n\nThis request: read request.json in the current folder and write the result to result.json '
                       'in the current folder (id %s).' % ref)
            allowed = ['Read(/request.json)', 'Edit(/result.json)', 'Write(/result.json)', 'WebSearch', 'WebFetch', 'Bash(date:*)']
            never = ['Glob', 'Grep', 'NotebookEdit', 'Task', 'Bash(curl:*)', 'Bash(wget:*)'] + self._brief_denies()
            cmd = [claude, '-p', prompt, '--model', model, '--output-format', 'stream-json', '--verbose',
                   '--strict-mcp-config', '--allowedTools', ','.join(allowed), '--disallowedTools', ','.join(never)]
            return cmd, model
        if not os.path.exists(self.mcp_file()):
            raise Bad('state/mcp.json missing (Macuse MCP config)')
        prompt += ('\n\nThis request: read %s and state/briefing/%s.json (the brief), and write the note to '
                   'state/briefing/%s.personal.json.' % (req, ref, ref))
        allowed = ['Read(/%s)' % req, 'Read(/state/briefing/%s.json)' % ref, 'Read(/state/projects.json)',
                   'Edit(/state/briefing/br*.personal.json)', 'Write(/state/briefing/br*.personal.json)', 'Bash(date:*)'] + \
                  ['mcp__macuse__' + t for t in ('calendar_list_calendars', 'calendar_search_events', 'calendar_find_available_times')]
        never = ['WebFetch', 'WebSearch', 'Glob', 'Grep', 'NotebookEdit', 'Task'] + ['mcp__macuse__' + t for t in MACUSE_NEVER]
        cmd = [claude, '-p', prompt, '--model', model, '--output-format', 'stream-json', '--verbose',
               '--mcp-config', self.mcp_file(), '--strict-mcp-config',
               '--allowedTools', ','.join(allowed), '--disallowedTools', ','.join(never)]
        return cmd, model

    def _brief_denies(self):
        """Deny rules always win over allow rules: nothing in the Axella folder, the home folder or the usual secret
        places can be read or written by a briefing run, whatever a web page asks for."""
        home = os.path.expanduser('~')
        out = []
        for root in (self.base, home):
            out += ['Read(/%s/**)' % root, 'Edit(/%s/**)' % root, 'Write(/%s/**)' % root]
        out += ['Read(~/**)', 'Read(//Volumes/**)', 'Read(//etc/**)', 'Read(//Library/**)']
        for secret in SECRETS:
            out.append('Read(/%s)' % os.path.join(self.base, secret))
        return out

    def _brief_workdir(self, ref):
        """A fresh 0700 folder outside the Axella and home folders with a copy of the request – all the run can see."""
        import tempfile
        work = os.path.realpath(tempfile.mkdtemp(prefix='axella-brief-'))
        home, base = os.path.realpath(os.path.expanduser('~')), os.path.realpath(self.base)
        if work.startswith(home + os.sep) or work.startswith(base + os.sep):
            shutil.rmtree(work, ignore_errors=True)
            raise Bad('temporary folder is inside the home folder – briefing not started')
        os.chmod(work, 0o700)
        shutil.copyfile(os.path.join(self.state_dir, 'briefing', ref + '.request.json'), os.path.join(work, 'request.json'))
        return work

    def _collect_brief(self, job, w):
        """Move result.json from the scratch folder to state/briefing/<ref>.json – a plain file under 1 MB only."""
        src = os.path.join(job['_cwd'], 'result.json')
        dst = os.path.join(self.state_dir, 'briefing', job['ref'] + '.json')
        try:
            st = os.lstat(src)
        except FileNotFoundError:
            return
        import stat as _st
        if not _st.S_ISREG(st.st_mode) or st.st_size > 1024 * 1024:
            w('Result file refused (not a plain file under 1 MB)')
            return
        shutil.copyfile(src, dst)
        os.chmod(dst, 0o600)

    @staticmethod
    def _event(line, w, stats=None):
        """Turn one stream-json line into a readable log line. Tool results are logged by size only (no message bodies)."""
        line = line.strip()
        if not line:
            return None
        try:
            ev = json.loads(line)
        except ValueError:
            w(line[:300])
            return None
        t = ev.get('type')
        if t == 'system' and ev.get('subtype') == 'init':
            servers = ', '.join('%s: %s' % (s.get('name'), s.get('status')) for s in ev.get('mcp_servers') or []) or 'none'
            mt = [t for t in ev.get('tools') or [] if str(t).startswith('mcp__macuse__')]
            w('Session ready – model %s, MCP %s, %d Macuse tools' % (ev.get('model'), servers, len(mt)))
            if stats is not None:
                stats['macuse_tools'] = len(mt)
                stats['macuse_server'] = any(s.get('name') == 'macuse' for s in ev.get('mcp_servers') or [])
        elif t == 'assistant':
            for c in (ev.get('message') or {}).get('content') or []:
                if c.get('type') == 'text' and c.get('text', '').strip():
                    w('» ' + c['text'].strip().replace('\n', ' ')[:400])
                elif c.get('type') == 'tool_use':
                    inp = c.get('input') or {}
                    if stats is not None and str(c.get('name', '')).startswith('mcp__macuse__'):
                        stats['macuse_calls'] = stats.get('macuse_calls', 0) + 1
                    if stats is not None and c.get('name') == 'WebSearch':      # what actually left: from the tool calls,
                        stats.setdefault('queries', []).append(str(inp.get('query') or '')[:300])   # not the model's own list
                    if stats is not None and c.get('name') == 'WebFetch':
                        stats.setdefault('fetched', []).append(str(inp.get('url') or '')[:500])
                    if stats is not None and c.get('name') in ('Read', 'Grep', 'Glob'):    # Ask: which notes it opened
                        where = str(inp.get('file_path') or inp.get('path') or inp.get('pattern') or '')
                        if 'state/ask-notes/' in where:
                            stats.setdefault('notes', set()).add(where.rsplit('/', 1)[-1] if c.get('name') == 'Read' else '*' + where)
                    if c.get('name') in ('Write', 'Edit'):
                        arg = inp.get('file_path', '')
                    else:
                        arg = json.dumps(inp, ensure_ascii=False)[:200]
                    w('→ %s %s' % (c.get('name', '').replace('mcp__macuse__', 'macuse.'), arg))
        elif t == 'user':
            for c in (ev.get('message') or {}).get('content') or []:
                if isinstance(c, dict) and c.get('type') == 'tool_result':
                    body = c.get('content')
                    size = len(json.dumps(body, ensure_ascii=False)) if body else 0
                    if c.get('is_error'):
                        txt = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
                        w('  ✗ ' + str(txt)[:300])
                    else:
                        w('  ✓ %s chars' % size)
        elif t == 'result':
            w('Result: %s – %s turns, %ss' % (ev.get('subtype'), ev.get('num_turns'), round((ev.get('duration_ms') or 0) / 1000)))
            if ev.get('result'):
                w('Final: ' + str(ev['result']).strip().replace('\n', ' ')[:500])
        return ev

    # ---------- doctor: what's on this Mac ----------
    def doctor(self):
        home = os.path.expanduser('~')
        out = {'at': _iso(), 'claude': self.claude_bin(), 'api_key_set': bool(os.environ.get('ANTHROPIC_API_KEY')),
               'mcp_file': os.path.exists(self.mcp_file()), 'desktop_mcp': {}, 'extensions': []}
        if out['claude']:
            try:
                p = subprocess.run([out['claude'], '--version'], capture_output=True, text=True, timeout=30)
                out['claude_version'] = (p.stdout or p.stderr).strip()[:100]
            except Exception as e:
                out['claude_version'] = 'error: ' + str(e)[:100]
        cfgp = os.path.join(home, 'Library/Application Support/Claude/claude_desktop_config.json')
        try:
            with open(cfgp, encoding='utf-8') as f:
                for name, s in (json.load(f).get('mcpServers') or {}).items():
                    out['desktop_mcp'][name] = {'command': s.get('command'), 'args': s.get('args'),
                                                'env_keys': sorted((s.get('env') or {}).keys())}
        except Exception as e:
            out['desktop_mcp_error'] = str(e)[:200]
        for man in glob.glob(os.path.join(home, 'Library/Application Support/Claude/Claude Extensions/*/manifest.json')):
            try:
                with open(man, encoding='utf-8') as f:
                    m = json.load(f)
                out['extensions'].append({'dir': os.path.dirname(man), 'name': m.get('name'),
                                          'server': (m.get('server') or {}).get('mcp_config')})
            except Exception:
                pass
        for app in ('/Applications/Macuse.app', home + '/Applications/Macuse.app'):
            if os.path.exists(app):
                out['macuse_app'] = app
                out['macuse_bins'] = [p for p in glob.glob(app + '/Contents/MacOS/*') + glob.glob(app + '/Contents/Resources/*')
                                      if os.access(p, os.X_OK) and not os.path.isdir(p)][:20]
        # Macuse for local runs: the Claude desktop extension (node + build/index.js) with its configured binary
        nodes = [p for p in [shutil.which('node') or '', '/opt/homebrew/bin/node', '/usr/local/bin/node',
                             home + '/.volta/bin/node'] + sorted(glob.glob(home + '/.nvm/versions/node/*/bin/node'))[-1:] if p and os.path.exists(p)]
        out['node'] = nodes
        ext = next((e for e in out['extensions'] if 'macuse' in (e.get('name') or '').lower()), None)
        if ext:
            sp = os.path.join(home, 'Library/Application Support/Claude/Claude Extensions Settings', os.path.basename(ext['dir']) + '.json')
            try:
                with open(sp, encoding='utf-8') as f:
                    uc = (json.load(f).get('userConfig') or {})
                out['macuse_user_config'] = {k: v for k, v in uc.items() if 'key' not in k.lower() and 'token' not in k.lower()}
            except Exception as e:
                out['macuse_user_config_error'] = str(e)[:200]
            try:
                with open(os.path.join(ext['dir'], 'build', 'index.js'), encoding='utf-8', errors='replace') as f:
                    js = f.read()
                import re as _re
                out['macuse_index_hints'] = sorted(set(_re.findall(r'(?:spawn|execFile)\([^)]{0,120}\)', js)))[:8]
            except Exception as e:
                out['macuse_index_error'] = str(e)[:200]
            binary = (out.get('macuse_user_config') or {}).get('macuse_binary') or '/Applications/Macuse.app/Contents/MacOS/macuse'
            env = {'MACUSE_BINARY': binary}
            node = nodes[0] if nodes else None
            mac = out.get('macuse_app') and os.path.join(out['macuse_app'], 'Contents/MacOS/macuse')
            if mac and os.path.exists(mac) and not os.path.exists(self.mcp_file()):
                # the extension's index.js only runs `macuse mcp` – talk to the binary directly, no Node needed
                with open(self.mcp_file(), 'w', encoding='utf-8') as f:
                    json.dump({'mcpServers': {'macuse': {'command': mac, 'args': ['mcp'], 'env': {}}}}, f, indent=1)
                out['mcp_file'] = 'created'
            if node and not os.path.exists(self.mcp_file()):
                with open(self.mcp_file(), 'w', encoding='utf-8') as f:
                    json.dump({'mcpServers': {'macuse': {'command': node, 'args': [os.path.join(ext['dir'], 'build', 'index.js')],
                                                         'env': env}}}, f, indent=1)
                out['mcp_file'] = 'created'
        out['mcp_test'] = self.mcp_test()
        try:
            out['pmset'] = subprocess.run(['/usr/bin/pmset', '-g'], capture_output=True, text=True, timeout=10).stdout[-1500:]
        except Exception:
            pass
        with open(os.path.join(self.state_dir, 'doctor.json'), 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        return out

    def mcp_test(self, wait=150):
        """Start the Macuse MCP server like a run would: initialize, list tools (again after a list_changed), time it."""
        try:
            with open(self.mcp_file(), encoding='utf-8') as f:
                c = json.load(f)['mcpServers']['macuse']
        except Exception as e:
            return {'ok': False, 'error': 'no mcp.json: %s' % str(e)[:100]}
        env = {**os.environ, **(c.get('env') or {})}
        t0, events, err = time.time(), [], []
        try:
            p = subprocess.Popen([c['command']] + c.get('args', []), env=env, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        except Exception as e:
            return {'ok': False, 'error': 'start failed: %s' % str(e)[:200]}
        threading.Thread(target=lambda: err.extend(p.stderr), daemon=True).start()
        lists, done = [], threading.Event()

        def send(obj):
            try:
                p.stdin.write(json.dumps(obj) + '\n')
                p.stdin.flush()
            except Exception as e:
                err.append('stdin: %s' % e)

        def rd():
            n = 10
            for ln in p.stdout:
                at = round(time.time() - t0, 1)
                try:
                    m = json.loads(ln)
                except ValueError:
                    events.append((at, 'non-json: ' + ln.strip()[:150]))
                    continue
                if m.get('id') == 1:
                    events.append((at, 'initialize ok'))
                    send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
                    send({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
                elif isinstance(m.get('id'), int) and m['id'] >= 2:
                    tools = [t['name'] for t in (m.get('result') or {}).get('tools', [])]
                    lists.append((at, tools))
                    events.append((at, 'tools/list: %d tools%s' % (len(tools), (' error ' + json.dumps(m.get('error'))[:150]) if m.get('error') else '')))
                    if tools:
                        done.set()
                elif m.get('method'):
                    events.append((at, 'notification ' + m['method']))
                    if m['method'] == 'notifications/tools/list_changed':
                        send({'jsonrpc': '2.0', 'id': n, 'method': 'tools/list'})
                        n += 1
        threading.Thread(target=rd, daemon=True).start()
        send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'axella-doctor', 'version': '1'}}})
        done.wait(wait)
        last = lists[-1][1] if lists else []
        res = {'ok': bool(last), 'seconds': round(time.time() - t0, 1), 'events': ['%5.1fs %s' % e for e in events[:20]],
               'tools': last, 'stderr': [e.rstrip()[:300] for e in err[-15:]], 'exit': p.poll()}
        try:
            p.kill()
        except OSError:
            pass
        return res

    # ---------- dashboard ----------
    def writing_since(self):
        """Start time (epoch) of the digest or P0 run going now, else None – a digest file it wrote isn't finished
        yet (its scope check runs when the run ends), so the push watcher leaves it alone until then."""
        with LOCK:
            cur = self.current
        if cur and TASKS.get(cur['run']['task'], {}).get('kind') in ('digest', 'p0'):
            return cur.get('t0')
        return None

    # ---------- work/private per schedule (scope.py) ----------
    def _digest_slots_on(self, day, cfg=None):
        """[(slot dict, 'HH:MM')] of the digest slots that run on `day` (paused days have none)."""
        cfg = cfg or self.load()
        try:
            st = self.sched.status(datetime.datetime.combine(day, datetime.time(12)))
        except Exception:
            st = {'digests': True}
        if not st.get('digests'):
            return []
        by_sid = {s['id']: s for s in cfg['digests']}
        return [(by_sid[sid], hm) for sid, task, hm, _ in self.slots_for(day, cfg)
                if TASKS[task]['kind'] == 'digest' and sid in by_sid]

    def _work_paused_on(self, day):
        try:
            return bool(self.sched.status(datetime.datetime.combine(day, datetime.time(12))).get('work_paused'))
        except Exception:
            return False

    def _scope_note(self, job, now=None):
        """The scope paragraph for a digest run: its world(s), each world's gather window, the other-world line."""
        now = now or datetime.datetime.now()
        worlds = job.get('worlds') or ['private', 'work']
        since = scope_mod.last_covered(os.path.join(self.base, 'digests'), now)
        nxt = (None, None)
        if scope_mod.is_scoped(worlds):
            other = 'private' if worlds == ['work'] else 'work'
            cfg = self.load()
            nxt = scope_mod.next_covering(lambda day: self._digest_slots_on(day, cfg), other, now, self._work_paused_on)
        return scope_mod.prompt_note(sorted(worlds), job.get('mention_other', True), since, nxt, now)

    def _briefing_busy(self):
        return any(j['task'] == 'return-briefing' for j in self.queue) or \
            bool(self.current and self.current['run']['task'] == 'return-briefing')

    def _learned_note(self):
        """Teach Axella: the rules the owner made on a tap, for the digest and the urgent check (learned.py)."""
        try:
            return self.learned_note() if self.learned_note else ''
        except Exception as e:
            self.log.write('%s learned rules: %s\n' % (_iso(), str(e)[:200]))
            return ''

    def _away_note(self, task, job):
        """The back-from-away briefing: write its facts (away.py) and point the run at them."""
        if task != 'return-briefing':
            return ''
        if not self.away_facts or not isinstance(job.get('away'), dict):
            raise Bad('back-from-away briefing without an absence')
        return away_mod.prompt_note(self.away_facts(job))

    def _wrap_note(self, task, job):
        """The Friday work wrap, and the private wrap in the Sunday week-ahead (unless the slot turned it off): write the
        week's facts (wrap.py) and tell the run to add the "wrap" block."""
        if task != 'week-wrap' and not (task == 'week-ahead' and job.get('wrap', True)):
            return ''
        worlds = sorted(job.get('worlds') or (['work'] if task == 'week-wrap' else ['private', 'work']))
        if self.wrap_facts:
            try:
                wrap_mod.write(self.state_dir, self.wrap_facts(worlds))
            except Exception as e:
                self.log.write('%s week wrap facts: %s\n' % (_iso(), str(e)[:200]))
        return wrap_mod.prompt_note(worlds)

    def _scope_enforce(self, start, job):
        """After a digest run: the newest digest it wrote holds only its world(s) (scope.enforce)."""
        paths = sorted((p for p in glob.glob(os.path.join(self.base, 'digests', '*.json'))
                        if not p.endswith('-p0.json') and os.path.getmtime(p) >= start - 1), key=os.path.getmtime)
        if not paths:
            return 0
        return scope_mod.enforce(paths[-1], job.get('worlds') or ['private', 'work'], self.state_dir)

    def overview(self):
        cfg = self.load()
        now = _now()
        with LOCK:
            d = self._load_runs()
            cur = dict(self.current['run']) if self.current else None
            queue = [{'task': j['task'], 'label': j.get('label') or TASKS[j['task']]['label'], 'trigger': j['trigger'],
                      'not_before': datetime.datetime.fromtimestamp(j['not_before']).astimezone().isoformat(timespec='seconds') if j['not_before'] else None}
                     for j in self.queue]
        by_id = {r['id']: r for r in d['runs']}
        today = []
        for sid, task, hm, label in self.slots_for(now.date(), cfg):
            key = '%s@%s %s' % (sid, now.date().isoformat(), hm)
            v = d['slots'].get(key)
            if not v and cfg.get('enabled_at') and '%s %s' % (now.date().isoformat(), hm) < cfg['enabled_at'][:16].replace('T', ' '):
                v = 'skipped: before the Mac mini took over'
            r = by_id.get(v) if v else None
            today.append({'slot': key, 'time': hm, 'task': task, 'label': label,
                          'status': r['status'] if r else (v.split(':')[0] if v else ('due' if _hm(hm) <= now.hour * 60 + now.minute else 'planned')),
                          'note': (v.split(': ', 1)[1] if v and ': ' in v else None), 'run': r['id'] if r else None})
        for bid, hm, label in (self.briefings.slots_for(now.date()) if self.briefings else []):
            key = 'brief-%s@%s %s' % (bid, now.date().isoformat(), hm)
            v = d['slots'].get(key)
            r = by_id.get(v) if v else None
            today.append({'slot': key, 'time': hm, 'task': 'briefing', 'label': 'Briefing: ' + label,
                          'status': r['status'] if r else (v.split(':')[0] if v else ('due' if _hm(hm) <= now.hour * 60 + now.minute else 'planned')),
                          'note': (v.split(': ', 1)[1] if v and ': ' in v else None), 'run': r['id'] if r else None})
        today.sort(key=lambda x: x['time'])
        return {'config': cfg, 'tasks': {k: v['label'] for k, v in TASKS.items()}, 'current': cur, 'queue': queue,
                'today': today, 'runs': d['runs'][-100:][::-1], 'kept_days': KEEP_DAYS, 'total_runs': len(d['runs']),
                'history_from': (d['runs'][0].get('started') if d['runs'] else None), 'capped': len(d['runs']) >= RUNS_CAP, 'doctor': self._doctor_cached()}

    def _doctor_cached(self):
        try:
            with open(os.path.join(self.state_dir, 'doctor.json'), encoding='utf-8') as f:
                x = json.load(f)
            return {k: x.get(k) for k in ('at', 'claude', 'claude_version', 'api_key_set', 'mcp_file')}
        except (OSError, ValueError):
            return None

    def read_log(self, rid, offset=0):
        if not rid or '/' in rid or '..' in rid:
            raise Bad('bad run id')
        p = os.path.join(self.run_dir, rid + '.log')
        if not os.path.exists(p):
            return {'text': '', 'offset': 0}
        with open(p, encoding='utf-8', errors='replace') as f:
            f.seek(max(0, int(offset)))
            text = f.read(200000)
            return {'text': text, 'offset': f.tell()}

    # ---------- compose assistant ----------
    def compose_request(self, p):
        to = str(p.get('to') or '').strip()
        if '@' not in to or len(to) > 200 or any(c in to for c in '<>"\n'):
            raise Bad('receiver must be one e-mail address')
        if not str(p.get('topic') or '').strip() or not str(p.get('target') or '').strip():
            raise Bad('topic and target are needed')
        import axprofile as profile
        accs = {a['id']: a for a in profile.accounts()}
        acc = accs.get(p.get('account')) or next(iter(accs.values()), {'id': 'iCloud', 'label': 'iCloud', 'kind': 'private', 'workplace': None})
        wp = next((w for w in profile.workplaces() if w['id'] == acc.get('workplace')), None)
        cid = _now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
        req = {'account': acc['id'], 'mailbox': acc['label'], 'kind': acc['kind'], 'workplace': wp['name'] if wp else None,
               'protected': bool(wp and wp['protected']), 'owner': profile.owner(),
'id': cid, 'at': _iso(), 'to': to, 'name': str(p.get('name') or '')[:120],
               'topic': str(p['topic'])[:500], 'target': str(p['target'])[:1000],
               'tone': str(p.get('tone') or 'my usual tone')[:60], 'language': str(p.get('language') or 'auto')[:20],
               'notes': str(p.get('notes') or '')[:2000],
               'revise': p.get('revise') if isinstance(p.get('revise'), dict) else None}
        d = os.path.join(self.state_dir, 'compose')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, cid + '.request.json'), 'w', encoding='utf-8') as f:
            json.dump(req, f, ensure_ascii=False, indent=1)
        with LOCK:
            # The owner is waiting: go before scheduled work in the queue (a run that already started finishes first)
            self.queue.insert(0, {'task': 'compose', 'slot': None, 'trigger': 'manual', 'not_before': 0, 'attempt': 1,
                                  'no_retry': True, 'ref': cid, 'label': 'Compose mail to ' + to})
            self.cv.notify_all()
        return {'id': cid}

    # ---------- Trips: Claude reads booking mails (and their PDF tickets) the owner picked ----------
    def trip_read_request(self, mails):
        """Queue one read-only run over these mails [{account, message_id, subject}] (already checked by the caller: your
        accounts, no private contacts, no protected workplaces). Returns the request id."""
        rid = 'tr' + _now().strftime('%Y%m%d%H%M%S') + uuid.uuid4().hex[:4]
        d = os.path.join(self.state_dir, 'trips-read')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, rid + '.request.json'), 'w', encoding='utf-8') as f:
            json.dump({'id': rid, 'at': _iso(), 'mails': mails[:40]}, f, ensure_ascii=False, indent=1)
        with LOCK:
            self.queue.insert(0, {'task': 'trip-read', 'slot': None, 'trigger': 'manual', 'not_before': 0, 'attempt': 1,
                                  'no_retry': True, 'ref': rid, 'label': 'Trips: read %d booking mail%s' % (len(mails[:40]), '' if len(mails) == 1 else 's')})
            self.cv.notify_all()
        return rid

    def project_read_request(self, pid, mails):
        """Projects → Read with Claude: one read-only run over the picked mails (checked by the caller like Trips)."""
        rid = 'pr' + _now().strftime('%Y%m%d%H%M%S') + uuid.uuid4().hex[:4]
        d = os.path.join(self.state_dir, 'project-read')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, rid + '.request.json'), 'w', encoding='utf-8') as f:
            json.dump({'id': rid, 'at': _iso(), 'project': pid, 'mails': mails[:20]}, f, ensure_ascii=False, indent=1)
        with LOCK:
            self.queue.insert(0, {'task': 'project-read', 'slot': None, 'trigger': 'manual', 'not_before': 0, 'attempt': 1,
                                  'no_retry': True, 'ref': rid, 'label': 'Projects: read %d mail%s' % (len(mails[:20]), '' if len(mails) == 1 else 's')})
            self.cv.notify_all()
        return rid

    def project_read_busy(self):
        return any(j['task'] == 'project-read' for j in self.queue) or bool(self.current and self.current['run']['task'] == 'project-read')

    def trip_read_busy(self):
        return any(j['task'] == 'trip-read' for j in self.queue) or bool(self.current and self.current['run']['task'] == 'trip-read')

    # ---------- Ask Axella (chat panel) ----------
    def ask_request(self, p):
        q = str(p.get('question') or '').strip()
        if not q or len(q) > 1500:
            raise Bad('ask something (max 1500 characters)')
        hist = []
        for h in (p.get('history') if isinstance(p.get('history'), list) else [])[-6:]:
            if isinstance(h, dict):
                hist.append({'q': str(h.get('q') or '')[:1500], 'a': str(h.get('a') or '')[:3000]})
        ctx = p.get('context') if isinstance(p.get('context'), dict) else {}
        import axprofile as profile
        cid = _now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
        n_notes = 0
        if self.ask_notes:
            try:
                n_notes = self.ask_notes(cid, p.get('_login'))     # the owner's Ask only (axella-actions)
            except Exception as e:
                self.log.write('%s ask notes: %s\n' % (_iso(), str(e)[:200]))
        req = {'id': cid, 'at': _iso(), 'question': q, 'history': hist, 'owner': profile.owner(),
               'notes': {'folder': 'state/ask-notes/%s' % cid, 'count': n_notes} if n_notes else None,
               'context': {'view': str(ctx.get('view') or '')[:40], 'project': str(ctx.get('project') or '')[:100],
                           'digest': str(ctx.get('digest') or '')[:120], 'filter': str(ctx.get('filter') or 'all')[:10]}}
        d = os.path.join(self.state_dir, 'ask')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, cid + '.request.json'), 'w', encoding='utf-8') as f:
            json.dump(req, f, ensure_ascii=False, indent=1)
        with LOCK:
            # the owner is waiting: first in the queue (a run that already started finishes first)
            self.queue.insert(0, {'task': 'ask', 'slot': None, 'trigger': 'manual', 'not_before': 0, 'attempt': 1,
                                  'no_retry': True, 'ref': cid, 'label': 'Ask Axella'})
            self.cv.notify_all()
        return {'id': cid}

    def compose_status(self, cid, kind='compose'):
        if not cid or '/' in cid or '..' in cid:
            raise Bad('bad id')
        res = os.path.join(self.state_dir, kind, cid + '.json')
        if os.path.exists(res):
            try:
                with open(res, encoding='utf-8') as f:
                    return {'state': 'done', 'result': json.load(f)}
            except ValueError:
                pass                                  # still being written
        with LOCK:
            cur = self.current['run'] if self.current else None
            pos = next((i for i, j in enumerate(self.queue) if j.get('ref') == cid), None)
        if cur and cur.get('ref') == cid:
            return {'state': 'running', 'run': cur['id']}
        if pos is not None:
            return {'state': 'queued', 'position': pos, 'waiting_for': cur['label'] if cur else None}
        r = next((r for r in self._load_runs()['runs'][::-1] if r.get('ref') == cid), None)
        if r and r['status'] in ('failed', 'cancelled'):
            return {'state': 'failed', 'error': r.get('reason') or r['status'], 'run': r['id']}
        return {'state': 'running' if r else 'unknown'}

    def action(self, action, p):
        if action == 'compose':
            return self.compose_request(p)
        if action == 'ask':
            return self.ask_request(p)
        if action == 'doctor_run':
            d = self.doctor()
            return {k: d.get(k) for k in ('claude', 'claude_version', 'mcp_file', 'node', 'api_key_set')}
        if action == 'run_now':
            task = p.get('task')
            if task not in TASKS or TASKS[task]['kind'] in ('briefing', 'briefing-personal', 'local'):
                raise Bad('unknown task')
            job = {'task': task, 'slot': None, 'trigger': 'manual', 'not_before': 0, 'attempt': 1, 'no_retry': True}
            if task == 'kb-harvest':            # needs its request file, like the nightly one – without it the run has no ref
                if not self.harvest:
                    raise Bad('the knowledge harvest is not available')
                with LOCK:
                    if self._kb_busy():
                        return 'already queued'
                ref = 'kb' + _now().strftime('%Y%m%d%H%M%S')
                if not self.harvest.nightly_request(ref):
                    raise Bad('the knowledge harvest is switched off in Settings')
                job.update(ref=ref, label='Knowledge harvest (now)')
            if task == 'return-briefing':       # "Catch me up since…": only with a checked absence (axella-actions away_catchup)
                ab = p.get('away') if isinstance(p.get('away'), dict) else {}
                a, b = away_mod._day(ab.get('from')), away_mod._day(ab.get('to'))
                if not a or not b or a > b or (b - a).days > away_mod.MAX_LOOKBACK:
                    raise Bad('pick the day you were away from')
                job['away'] = {'from': a.isoformat(), 'to': b.isoformat(), 'days': (b - a).days + 1, 'manual': True}
            with LOCK:
                if any(j['task'] == task for j in self.queue) or (self.current and self.current['run']['task'] == task):
                    return 'already queued'
                self.queue.append(job)
                self.cv.notify_all()
            return 'queued'
        if action == 'briefing_run':
            if not self.briefings:
                raise Bad('briefings not available')
            b = self.briefings.get(str(p.get('id') or ''))
            if not b:
                raise Bad('no such briefing')
            with LOCK:
                if any(j.get('briefing') == b['id'] for j in self.queue) or \
                        (self.current and self.current['run'].get('briefing') == b['id']):
                    return 'already queued'
                self._queue_brief(b['id'], b['name'], 'manual')
            return 'queued'
        if action == 'run_cancel':
            with LOCK:
                cur = self.current
                self.queue = [j for j in self.queue if j['trigger'] != 'retry' or j['task'] != p.get('task')]
            if not cur:
                return 'nothing running'
            threading.Thread(target=self._kill, args=(cur['proc'], 'cancel'), daemon=True).start()
            return 'stopping'
        if action == 'scheduler_set':
            with LOCK:
                d = self.load()
                if 'enabled' in p:
                    if p['enabled'] and not d['enabled']:
                        d['enabled_at'] = _iso()
                    d['enabled'] = bool(p['enabled'])
                if 'digests' in p:
                    out = []
                    for s in p['digests'][:12]:
                        if s.get('task') not in TASKS or TASKS[s['task']]['kind'] != 'digest':
                            raise Bad('bad task')
                        tm = str(s.get('time', ''))
                        if len(tm) != 5 or not (0 <= _hm(tm) < 24 * 60):
                            raise Bad('bad time ' + tm)
                        if 'worlds' in s and not (isinstance(s['worlds'], list) and set(s['worlds']) <= set(scope_mod.WORLDS) and s['worlds']):
                            raise Bad('worlds must be work, private or both')
                        out.append({'id': str(s.get('id') or uuid.uuid4().hex[:6])[:20], 'task': s['task'],
                                    'label': str(s.get('label') or TASKS[s['task']]['label'])[:40], 'time': tm,
                                    'days': sorted({int(x) for x in s.get('days', []) if 0 <= int(x) <= 6}),
                                    'enabled': bool(s.get('enabled', True)), **scope_mod.norm_slot(s),
                                    **({'wrap': bool(s.get('wrap', True))} if s['task'] in ('week-ahead', 'week-wrap') else {})})
                    if len({x['id'] for x in out}) != len(out):
                        raise Bad('two slots have the same id')
                    d['digests'] = out
                if 'p0' in p:
                    q = p['p0']
                    for k in ('from', 'to'):
                        if k in q:
                            _hm(q[k])
                    every = int(q.get('every', d['p0']['every']))
                    if every not in (15, 30, 60):
                        raise Bad('interval must be 15, 30 or 60 min')
                    d['p0'].update({k: q[k] for k in ('enabled', 'from', 'to', 'days') if k in q}, every=every)
                    d['p0']['days'] = sorted({int(x) for x in d['p0']['days']})
                if 'models' in p:
                    for k, v in p['models'].items():
                        if k in d['models'] and v in ('opus', 'sonnet', 'haiku'):
                            d['models'][k] = v
                self._save_cfg(d)
            return 'saved'
        raise Bad('unknown action')
