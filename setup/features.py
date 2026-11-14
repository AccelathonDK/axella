"""What Axella handles – Features on/off and the guided setup (dev requests claude/dev-request-features-on-off.md and
claude/dev-request-guided-setup.md).

A registry of every optional feature: the 7 cards people see ("Messages and people", "Voice", …), the features behind
each card's More, and for each feature the POST actions, GET routes, scheduler tasks, threads and data paths it owns.
Anything not in the registry is core (Today, the written digest, Ask Axella, To do, Notes, Settings, …) and always on.

Per person (decided 5 Nov):
  * the owner's switches are the installation's: a feature the owner has off is off for everyone, and its background
    work stops (runs are skipped – "skipped – feature off", threads idle, prompts leave it out, its data paths are
    denied to Claude runs);
  * anyone else on the access list can switch features off for themselves only – never on what the owner has off.
Data is kept when a feature is off. Deleting an area's data is owner-only, moves the files to
state/deleted/features/<backup>/ (restorable, with anything written since set aside), and expires after 90 days.

state/features.json:
  {"v": 1, "owner": {"off": [ids], "on_since": {id: iso}}, "people": {login: {"off": [ids]}},
   "setup": {login: {"step", "chosen", "skipped", "done", "at"}}, "not_set_up": [card ids], "review": {login: "done"|"later"},
   "new_install": bool}
Python 3.9."""
import datetime
import glob
import json
import os
import re
import shutil
import threading
import time
import uuid

LOCK = threading.RLock()
KEEP_DAYS = 90


class Bad(Exception):
    pass


# ---- the 7 cards --------------------------------------------------------------------------------------------------
CARDS = [
    {'id': 'messages', 'title': 'Messages and people', 'color': 'var(--ax-project-1)', 'default': True, 'minutes': 3,
     'line': "Reads your mail and messages, tells you what needs an answer, keeps your promises and the people you're in touch with in view.",
     'needs': 'Mail, Messages, Contacts', 'claude_default': 'moderate'},
    {'id': 'calendar', 'title': 'Calendar and meetings', 'color': 'var(--ax-project-2)', 'default': True, 'minutes': 2,
     'line': 'Prepares your meetings, sends invites with a Teams, Meet or Zoom link, and protects your focus time.',
     'needs': 'Calendar, optional meeting service', 'claude_default': 'light'},
    {'id': 'projects', 'title': 'Projects and planning', 'color': 'var(--ax-project-7)', 'default': True, 'minutes': 2,
     'line': "Gathers each project's mail, people and targets, and suggests what to work on today.",
     'needs': 'Mail, Calendar', 'claude_default': 'light'},
    {'id': 'trips', 'title': 'Trips', 'color': 'var(--ax-project-4)', 'default': False, 'minutes': 2,
     'line': 'Finds bookings in your mail and builds each trip with times, places and documents.',
     'needs': 'Mail', 'claude_default': 'light'},
    {'id': 'money', 'title': 'Money at home', 'color': 'var(--ax-project-3)', 'default': False, 'minutes': 3,
     'line': 'Collects receipts, keeps bills, subscriptions and renewals in view so nothing renews by surprise.',
     'needs': 'Mail, optional receipts folder', 'claude_default': 'light'},
    {'id': 'briefs', 'title': 'Topic briefs and knowledge', 'color': 'var(--ax-project-5)', 'default': False, 'minutes': 2,
     'line': 'Follows topics you care about on the web and keeps a knowledge base Axella can answer from.',
     'needs': 'Web search', 'claude_default': 'moderate'},
    {'id': 'voice', 'title': 'Voice', 'color': 'var(--ax-project-6)', 'default': False, 'minutes': 5,
     'line': 'Listen to your digest, and let the call agent answer calls you miss and take a message.',
     'needs': 'A voice; for calls a phone number', 'claude_default': 'light'},
]
CARD_IDS = [c['id'] for c in CARDS]

# ---- the features (order within a card = order of the list) ------------------------------------------------------
# actions: exact POST action names · prefixes: POST action prefixes · gets: GET routes · tasks: scheduler tasks ·
# threads: background loops that idle while off · data: paths under the Axella folder · needs: other features ·
# new: on by default on a new install (when its card is chosen) · prompt: what a digest run leaves out while it is off
FEATURES = [
    # Messages and people
    {'id': 'to_answer', 'card': 'messages', 'label': 'To answer and promises', 'new': True,
     'desc': 'What needs an answer, and the promises you made and were made to you.',
     'prefixes': ['promise_'], 'gets': ['commitments'], 'threads': ['commitments'], 'data': ['state/promises.json'],
     'prompt': 'promises (what you promised and were promised)'},
    {'id': 'reply_debt', 'card': 'messages', 'label': 'Reply debt', 'new': True, 'desc': 'People who have waited a long time for an answer.',
     'actions': ['replydebt_never', 'replydebt_done'], 'data': ['state/reply-debt-never.json', 'state/reply-debt-done.json'],
     'prompt': 'reply debt (how long people have waited for an answer)'},
    {'id': 'reply_sprint', 'card': 'messages', 'label': 'Reply sprint', 'new': False, 'needs': ['to_answer'],
     'desc': 'Answer the waiting ones in one short session.', 'gets': ['sprint']},
    {'id': 'send_later', 'card': 'messages', 'label': 'Send later', 'new': False, 'desc': 'Write now, send at a time you pick.',
     'actions': ['schedule_send', 'schedule_update', 'schedule_cancel', 'schedule_now'], 'gets': ['scheduled', 'scheduled_text'],
     'threads': ['scheduled'], 'data': ['state/scheduled.json', 'state/scheduled-files']},
    {'id': 'back_from_away', 'card': 'messages', 'label': 'Away and back from away', 'new': False, 'needs': ['to_answer'],
     'desc': 'An automatic reply while you are out, and a catch-up briefing when you are back.',
     'prefixes': ['away_', 'ooo_'], 'gets': ['ooo'], 'tasks': ['return-briefing'], 'data': ['state/away.json', 'state/ooo.json']},
    {'id': 'scam_check', 'card': 'messages', 'label': 'Scam check', 'new': True, 'desc': 'Flags mail and messages that look like fraud.',
     'actions': ['safety_mark_safe', 'safety_unmark_safe'], 'threads': ['safety'], 'data': ['state/safety.json'],
     'prompt': 'scam warnings'},
    {'id': 'filing', 'card': 'messages', 'label': 'Newsletters and filing', 'new': True,
     'desc': 'Suggests where mail belongs, and keeps newsletters out of the way.',
     'actions': ['file', 'sender_unsubscribe', 'sender_keep', 'sender_hold', 'senders_quiet_dismiss'], 'gets': ['senders', 'folders'],
     'threads': ['newsletters'], 'data': ['state/senders.json', 'state/senders-status.json', 'state/filing-learned.json'],
     'prompt': 'filing suggestions (the "file" section) and newsletter sorting'},
    {'id': 'mail_tidy', 'card': 'messages', 'label': 'Keep mail tidy', 'new': False, 'desc': 'Suggests old mail to clean up – only moved when you approve.',
     'prefixes': ['cleanup_'], 'actions': ['mail_seen'], 'gets': ['cleanup'], 'threads': ['cleanup'],
     'data': ['state/cleanup.json', 'state/cleanup-candidates.json']},
    {'id': 'people', 'card': 'messages', 'label': 'People and keep in touch', 'new': True,
     'desc': 'A page per person, and a nudge when you have not been in touch for a while.',
     'actions': ['person_note', 'keep_set'], 'gets': ['person', 'keep_in_touch'], 'threads': ['keep_in_touch'],
     'data': ['state/people-notes.json', 'state/keep-in-touch.json']},
    {'id': 'birthdays', 'card': 'messages', 'label': 'Birthdays', 'new': True, 'desc': 'Birthdays from your contacts, the day before.',
     'actions': ['birthday_show'], 'threads': ['birthdays'], 'data': ['state/birthdays.json', 'state/birthdays-today.json']},
    # Calendar and meetings
    {'id': 'meeting_prep', 'card': 'calendar', 'label': 'Meeting prep', 'new': True, 'desc': 'A prep page per meeting with what Axella knows.',
     'prefixes': ['meeting_'], 'gets': ['meetings', 'meeting', 'meeting_context', 'meeting_file', 'meeting_text', 'meeting_caps'],
     'data': ['state/meetings']},
    {'id': 'meeting_recordings', 'card': 'calendar', 'label': 'Meeting recordings', 'new': False, 'needs': ['meeting_prep'],
     'desc': 'Record or upload a meeting and get a transcript – on this Mac (whisper.cpp).',
     'actions': ['meeting_record_chunk', 'meeting_record_finish', 'meeting_record_drop', 'meeting_transcript_upload',
                 'meeting_transcript_paste', 'meeting_transcribe', 'meeting_speakers', 'meeting_ai_default'], 'tasks': ['transcribe']},
    {'id': 'invites', 'card': 'calendar', 'label': 'Invites and online meetings', 'new': True,
     'desc': 'Answer invitations, and send your own with a Teams, Meet or Zoom link.',
     'actions': ['cal_invite_send', 'cal_invite_update', 'cal_invite_cancel', 'meeting_service_connect', 'meeting_service_disconnect',
                 'meeting_service_default', 'invite_respond', 'invite_dismiss'],
     'gets': ['invites_pending', 'invite', 'meeting_services', 'cal_invite_for', 'calendar_caps'],
     'data': ['state/calendar-invites.json', 'state/online-meetings.json', 'state/invites-dismissed.json']},
    {'id': 'blocks', 'card': 'calendar', 'label': 'Protect your blocks', 'new': False, 'desc': 'Suggests holding free time for focus.',
     'prefixes': ['block_'], 'gets': ['blocks'], 'data': ['state/blocks.json']},
    # Projects and planning
    {'id': 'projects', 'card': 'projects', 'label': 'Projects', 'new': True, 'desc': "A page per project with its mail, documents and notes.",
     'prefixes': ['project_'], 'gets': ['projects', 'project_file', 'project_links_for_trip'], 'data': ['state/projects.json', 'state/project-files'],
     'prompt': 'project tags'},
    {'id': 'project_mail', 'card': 'projects', 'label': 'Project mail scan', 'new': True, 'needs': ['projects'],
     'desc': "Finds a project's mail and suggests what belongs to it.",
     'actions': ['project_doc_from_mail', 'project_mail_scan', 'project_mail_add', 'project_mail_not', 'project_mail_undo_not',
                 'project_mail_remove', 'project_mail_undo_remove', 'project_mail_move', 'project_match_add', 'project_match_dismiss',
                 'project_trip_link', 'project_trip_unlink', 'project_mail_attach', 'project_read', 'project_suggestion_done'],
     'gets': ['project_mail'], 'tasks': ['project-read'], 'threads': ['project_mail'], 'data': ['state/project-mail.json', 'state/project-read']},
    {'id': 'project_states', 'card': 'projects', 'label': 'Project states and people', 'new': True, 'needs': ['projects'],
     'desc': 'Active, waiting, paused or running – and who is on each project.',
     'actions': ['project_state', 'project_person_add', 'project_person_update', 'project_person_remove', 'project_person_not'],
     'data': ['state/planner.json']},
    {'id': 'targets', 'card': 'projects', 'label': 'Targets', 'new': True, 'needs': ['projects'], 'desc': 'Dates and goals per project, with steps.',
     'actions': ['project_target_add', 'project_target_update', 'project_target_delete', 'project_target_signal_not',
                 'project_entry_add', 'project_entry_update', 'project_entry_delete', 'project_entry_reorder']},
    {'id': 'plan', 'card': 'projects', 'label': 'Now · Next · Later', 'new': True, 'needs': ['projects'],
     'desc': 'The morning focus question and a day plan in your real free time.',
     'actions': ['plan_settings', 'plan_focus', 'plan_none', 'plan_item', 'plan_swap', 'plan_suggestion', 'plan_heads_up', 'plan_check', 'plan_hold'],
     'gets': ['plan', 'plan_week', 'project_plan'], 'threads': ['plan_digest']},
    # Trips
    {'id': 'trips', 'card': 'trips', 'label': 'Trips', 'new': True, 'desc': 'Trip scan, trip pages and travel documents.',
     'prefixes': ['trip_'], 'gets': ['trips', 'trip_today'], 'tasks': ['trip-read'], 'threads': ['trips'],
     'data': ['state/trips.json', 'state/trips-read', 'state/trip-checklists.json'], 'prompt': 'trips'},
    # Money at home
    {'id': 'receipts', 'card': 'money', 'label': 'Receipts and bookkeeping', 'new': True,
     'desc': 'Collects receipts and invoices, and forwards them to your bookkeeping when you say so.',
     'actions': ['recipients_set', 'document_forward', 'vendor_auto_forward', 'document_set', 'document_hide'], 'gets': ['documents'],
     'tasks': ['receipts-catchup'], 'threads': ['documents', 'auto_forward'],
     'data': ['state/documents.json', 'state/documents-seen.json', 'state/recipients.json', 'state/receipts-auto.json'],
     'prompt': 'receipts and invoices'},
    {'id': 'bills', 'card': 'money', 'label': 'Bills', 'new': True, 'desc': 'Bills due this week.',
     'prefixes': ['bill_'], 'gets': ['bills'], 'threads': ['bills'], 'data': ['state/bills.json'], 'prompt': 'bills'},
    {'id': 'subscriptions', 'card': 'money', 'label': 'Subscriptions and store items', 'new': True, 'needs': ['receipts'],
     'desc': 'What you pay for every month or year, and what you bought in the app stores.',
     'actions': ['recurring_set', 'recurring_seen', 'recurring_scan'], 'gets': ['recurring', 'store'], 'threads': ['recurring'],
     'data': ['state/recurring.json']},
    {'id': 'renewals', 'card': 'money', 'label': 'Renewals', 'new': True, 'needs': ['receipts'], 'desc': 'Insurance and contracts before they renew.',
     'prefixes': ['renewal_'], 'gets': ['renewals'], 'threads': ['renewals'], 'data': ['state/renewals.json']},
    # Topic briefs and knowledge
    {'id': 'topic_briefs', 'card': 'briefs', 'label': 'Topic briefs', 'new': True, 'desc': 'Research and news on topics you pick, on your schedule.',
     'actions': ['briefing_save', 'briefing_delete', 'briefing_run'], 'gets': ['briefings', 'briefs'],
     'tasks': ['briefing', 'briefing-personal'], 'data': ['state/briefs', 'state/briefing']},
    {'id': 'knowledge', 'card': 'briefs', 'label': 'Knowledge base', 'new': True, 'desc': 'What Axella learned from your mail and files, to answer from.',
     'prefixes': ['kb_'], 'gets': ['kb_harvest', 'knowledge', 'knowledge_search'], 'tasks': ['kb-harvest'],
     'data': ['knowledge', 'state/kb', 'state/kb-harvest.json']},
    # Voice
    {'id': 'spoken_digest', 'card': 'voice', 'label': 'Spoken digest', 'new': True, 'desc': 'Listen to your digest and briefs.',
     'gets': ['spoken', 'listen', 'audio'], 'data': ['state/audio']},
    {'id': 'call_agent', 'card': 'voice', 'label': 'Call agent', 'new': False,
     'desc': "Answers calls you miss and takes a message (it needs a phone number of its own).",
     'threads': ['voice_sync'], 'data': ['calls', 'state/voice-status.json'], 'prompt': 'calls'},
]
BY_ID = {f['id']: f for f in FEATURES}
# Core – always on, no switch. Every POST action, prefix and GET route in axella-actions.py is either here or in a
# feature above (setup/tests/test_features.py checks it, so a new action has to be placed somewhere).
CORE_ACTIONS = {'setup_sources_save', 'ask', 'backup_auto', 'backup_export', 'backup_run', 'cal_add', 'calm_setup_dismiss', 'calm_setup_step', 'card_set', 'compose',
                'compose_assist', 'ctx_set', 'digest_seen', 'doctor_run', 'done', 'draft', 'draft_new', 'event', 'feature_data_delete',
                'feature_data_restore', 'feature_set', 'mail_mark', 'mail_send', 'note_delete', 'note_keep', 'note_restore', 'note_save',
                'note_todo', 'pics_sender', 'privacy_set', 'push_subscribe', 'push_test', 'push_unsubscribe', 'reply_send', 'report_check',
                'report_discard', 'report_preview', 'report_rotate', 'report_save', 'report_send', 'report_status', 'review_set',
                'rule_remove', 'rule_restore', 'run_cancel', 'run_now', 'schedule_set', 'scheduler_set', 'setup_about', 'setup_card',
                'setup_save', 'should_have_reached', 'snooze', 'suggest_accept', 'suggest_later', 'suggest_never', 'sweep_cancel',
                'sweep_request', 'sweep_offer', 'sweep_later_cancel', 'task_add', 'task_delete', 'task_done', 'task_suggest', 'task_undo', 'task_update', 'teach_not_important',
                'trash', 'trash_batch', 'triage_act', 'undo', 'vip_add', 'vip_remove', 'vip_update'}
CORE_PREFIXES = ('backup_', 'cal_', 'contact_', 'push_', 'reminder_', 'report_', 'task_', 'triage_')
CORE_GETS = {'setup_sources', 'sweep_offer', 'activity', 'ask', 'attachment', 'backup', 'backup_download', 'calendar', 'calm', 'calm_setup', 'chat', 'chat_media', 'compose',
             'compose_contacts', 'contacts', 'drafts', 'features', 'health', 'img', 'insights', 'job', 'later', 'learn', 'mail_search',
             'message', 'note', 'note_chips', 'notes', 'oauth_callback', 'outbound', 'overrides', 'privacy', 'private_inbox', 'profile',
             'reminders', 'reply_info', 'report', 'report_context', 'report_img', 'reports', 'reports_zip', 'run_log', 'runs', 'schedule',
             'search', 'send_status', 'state', 'system_status', 'tasks', 'triage_list', 'triage_render', 'vapid', 'vips'}
# scheduler tasks that are core (the written digest, the urgent check, Ask, compose, …)
CORE_TASKS = {'digest-morning', 'digest-midday', 'digest-afternoon', 'week-ahead', 'week-wrap', 'on-demand', 'inbox-rescan', 'p0-check',
              'compose', 'ask', 'feedback-summary'}
CORE_LABEL = ('Today, the morning digest, Ask Axella, To do and Waiting, Notes, the week wrap and calm in numbers, Teach Axella, '
              'backup and move, the setup check, system status, the work/private split, Settings and Report a problem')


def card_of(fid):
    return BY_ID[fid]['card']


def features_of(card):
    return [f['id'] for f in FEATURES if f['card'] == card]


# ---- which feature owns an action or a route ------------------------------------------------------------------------
def feature_of_action(action, p=None):
    """The feature a POST action belongs to, or None (core). Exact names win over prefixes; the longest prefix wins."""
    a = str(action or '')
    for f in FEATURES:
        if a in (f.get('actions') or ()):
            return f['id']
    best, n = None, 0
    for f in FEATURES:
        for pre in f.get('prefixes') or ():
            if a.startswith(pre) and len(pre) > n:
                best, n = f['id'], len(pre)
    return best


def feature_of_get(route, q=None):
    r = str(route or '')
    for f in FEATURES:
        if r in (f.get('gets') or ()):
            return f['id']
    return None


def feature_of_task(task, job=None):
    for f in FEATURES:
        if task in (f.get('tasks') or ()):
            return f['id']
    return None


def _now():
    return datetime.datetime.now().astimezone()


def _iso(t=None):
    return (t or _now()).isoformat(timespec='seconds')


class Features:
    def __init__(self, state_dir, base=None):
        self.state_dir = state_dir
        self.base = base or os.path.dirname(os.path.abspath(state_dir))
        self.path = os.path.join(state_dir, 'features.json')
        self.broken = False

    # -- state
    def _has_data(self):
        """An installation in use: digests, a finished run or tasks already there. (Not the action log or empty files – a
        new install's own service writes those within minutes of its first start.)"""
        if glob.glob(os.path.join(self.base, 'digests', '*.json')):
            return True
        for rel, test in (('state/runs.json', lambda d: any((r or {}).get('status') == 'ok' for r in (d or {}).get('runs') or [])),
                          ('state/tasks.json', lambda d: isinstance(d, list) and len(d) > 0)):
            try:
                with open(os.path.join(self.base, rel), encoding='utf-8') as f:
                    if test(json.load(f)):
                        return True
            except (OSError, ValueError):
                pass
        return False

    def load(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                d = json.load(f)
            if not isinstance(d, dict) or not isinstance(d.get('owner'), dict):
                raise ValueError('shape')
            self.broken = False
        except FileNotFoundError:
            d = self._first()
            self._save(d)
        except (OSError, ValueError):
            self.broken = True                         # can't read it: everything on, changes refused
            return {'v': 1, 'owner': {'off': [], 'on_since': {}}, 'people': {}, 'setup': {}, 'not_set_up': [], 'review': {},
                    'new_install': False}
        for k, v in (('people', {}), ('setup', {}), ('not_set_up', []), ('review', {})):
            d.setdefault(k, v)
        d['owner'].setdefault('off', [])
        d['owner'].setdefault('on_since', {})
        return d

    def _first(self):
        """First start. An installation already in use keeps everything on; a new one starts with the default cards'
        default features and asks the guided setup."""
        if self._has_data():
            return {'v': 1, 'owner': {'off': [], 'on_since': {}}, 'people': {}, 'setup': {}, 'not_set_up': [], 'review': {},
                    'new_install': False}
        on_cards = {c['id'] for c in CARDS if c['default']}
        off = [f['id'] for f in FEATURES if f['card'] not in on_cards or not f['new']]
        return {'v': 1, 'owner': {'off': off, 'on_since': {}}, 'people': {}, 'setup': {}, 'not_set_up': [], 'review': {},
                'new_install': True}

    def _save(self, d):
        if self.broken:
            raise Bad("Axella can't read its feature settings right now – nothing was changed")
        os.makedirs(self.state_dir, exist_ok=True)
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # -- questions
    def owner_on(self, fid, d=None):
        """The installation's switch – what background work follows."""
        if fid not in BY_ID:
            return True
        d = d or self.load()
        return fid not in d['owner']['off']

    def is_on(self, fid, login=None, owner=True, d=None):
        if fid is None or fid not in BY_ID:
            return True
        d = d or self.load()
        if fid in d['owner']['off']:
            return False
        if owner or not login:
            return True
        return fid not in ((d['people'].get(login) or {}).get('off') or [])

    def on_since(self, fid):
        return self.load()['owner']['on_since'].get(fid)

    def off_label(self, fid):
        return BY_ID[fid]['label'] if fid in BY_ID else fid

    # -- changes
    def dependency_check(self, fid, on, d, who_off):
        """→ (also, message): features that change with this one, and the plain question to ask first."""
        if on:
            need = [n for n in self._needs(fid) if n in who_off]
            if need:
                return need, '%s needs %s – switch %s on too?' % (BY_ID[fid]['label'], _and([BY_ID[n]['label'] for n in need]),
                                                                  'it' if len(need) == 1 else 'them')
            return [], None
        dep = [f['id'] for f in FEATURES if fid in self._needs(f['id']) and f['id'] not in who_off]
        if dep:
            return dep, '%s also go%s off – %s %s. Continue?' % (_and([BY_ID[x]['label'] for x in dep]), 'es' if len(dep) == 1 else '',
                                                                 'it needs' if len(dep) == 1 else 'they need', BY_ID[fid]['label'])
        return [], None

    @staticmethod
    def _needs(fid):
        out, todo = [], list(BY_ID[fid].get('needs') or [])
        while todo:
            n = todo.pop(0)
            if n not in out:
                out.append(n)
                todo += BY_ID[n].get('needs') or []
        return out

    def set(self, fid, on, login, owner, confirm=False):
        """Switch one feature for the owner (the installation) or for one other person. Returns the change, or
        {'confirm': text, 'also': [...]} when a dependency must be accepted first."""
        if fid not in BY_ID:
            raise Bad('unknown feature')
        if BY_ID[fid].get('owner_only') and not owner:
            raise Bad('%s is the owner\'s own' % BY_ID[fid]['label'])
        with LOCK:
            d = self.load()
            if owner:
                cur = set(d['owner']['off'])
            else:
                if on and fid in d['owner']['off']:
                    raise Bad('%s is switched off by the owner' % BY_ID[fid]['label'])
                cur = set((d['people'].get(login) or {}).get('off') or []) | set(d['owner']['off'])
            also, msg = self.dependency_check(fid, on, d, cur)
            if also and not confirm:
                return {'confirm': msg, 'also': also}
            if not owner and on:
                also = [a for a in also if a not in d['owner']['off']]
                blocked = [a for a in self._needs(fid) if a in d['owner']['off']]
                if blocked:
                    raise Bad('%s needs %s, which the owner has switched off' % (BY_ID[fid]['label'], _and([BY_ID[b]['label'] for b in blocked])))
            change = [fid] + also
            if owner:
                off = set(d['owner']['off'])
                for x in change:
                    if on:
                        off.discard(x)
                        d['owner']['on_since'][x] = _iso()
                    else:
                        off.add(x)
                d['owner']['off'] = sorted(off)
            else:
                p = d['people'].setdefault(login, {'off': []})
                off = set(p.get('off') or [])
                for x in change:
                    (off.discard if on else off.add)(x)
                p['off'] = sorted(off)
            self._save(d)
            return {'changed': change, 'on': bool(on)}

    def set_card(self, card, on, login, owner, features=None, confirm=False):
        """A whole card: off switches all its features off; on switches on the given features (default: the card's
        defaults, or all when none is on by default)."""
        if card not in CARD_IDS:
            raise Bad('unknown card')
        ids = features_of(card)
        if on:
            pick = [f for f in (features or [x for x in ids if BY_ID[x].get('new')] or ids) if f in ids]
        else:
            pick = ids
        if not owner:
            pick = [f for f in pick if not BY_ID[f].get('owner_only')]
        # dependencies across cards (on: what they need elsewhere; off: what elsewhere needs them)
        d = self.load()
        cur = set(d['owner']['off']) if owner else set((d['people'].get(login) or {}).get('off') or []) | set(d['owner']['off'])
        outside = []
        for f in pick:
            also, _ = self.dependency_check(f, on, d, cur)
            outside += [a for a in also if a not in ids and a not in outside]
        if outside and not confirm:
            return {'confirm': ('This also switches on %s.' if on else '%s also go%s off.') % (
                _and([BY_ID[x]['label'] for x in outside]), '' if on or len(outside) > 1 else 'es') + ' Continue?', 'also': outside}
        out = []
        for f in pick + outside:
            if on and not owner and f in d['owner']['off']:
                continue
            r = self.set(f, on, login, owner, confirm=True)
            out += r.get('changed') or []
        if owner and not on:
            self.mark_set_up(card, True)                 # off: no "Not set up yet" for it any more
        return {'changed': sorted(set(out)), 'on': bool(on)}

    def mark_set_up(self, card, done=True):
        with LOCK:
            d = self.load()
            s = set(d['not_set_up'])
            (s.discard if done else s.add)(card)
            d['not_set_up'] = sorted(s)
            self._save(d)

    # -- the view for one person
    def view(self, login, owner, claude_use=None):
        d = self.load()
        mine = set((d['people'].get(login) or {}).get('off') or [])
        feats = {}
        for f in FEATURES:
            oo = f['id'] in d['owner']['off']
            feats[f['id']] = {'id': f['id'], 'card': f['card'], 'label': f['label'], 'desc': f['desc'], 'needs': f.get('needs') or [],
                              'on': not oo and (owner or f['id'] not in mine), 'owner_off': oo and not owner,
                              'owner_only': bool(f.get('owner_only'))}
        cards = []
        for c in CARDS:
            ids = features_of(c['id'])
            n_on = sum(1 for i in ids if feats[i]['on'])
            cards.append(dict(c, features=ids, n_on=n_on, n=len(ids), on=n_on > 0,
                              owner_off=not owner and all(i in d['owner']['off'] for i in ids),
                              not_set_up=c['id'] in d['not_set_up'] and n_on > 0,
                              claude=(claude_use or {}).get(c['id']) or c['claude_default'],
                              includes=' · '.join(BY_ID[i]['label'] for i in ids)))
        st = d['setup'].get(login) or {}
        needed = owner and d.get('new_install') and not st.get('done')
        return {'features': feats, 'cards': cards, 'core': CORE_LABEL, 'owner': owner, 'broken': self.broken,
                'setup': {'needed': bool(needed), 'progress': st or None, 'first_visit': (not owner) and not st.get('done'),
                          'review': (owner and not d.get('new_install') and not st.get('done') and d['review'].get(login) not in ('done', 'later'))}}

    # -- the guided setup's progress, per person
    def setup_save(self, login, p):
        with LOCK:
            d = self.load()
            st = d['setup'].setdefault(login, {})
            if p.get('step') is not None:
                step = str(p['step'])[:40]
                if not re.match(r'^(about|cards|card:[a-z]+|summary|done)$', step):
                    raise Bad('unknown step')
                st['step'] = step
            if isinstance(p.get('chosen'), list):
                st['chosen'] = [c for c in p['chosen'] if c in CARD_IDS]
            if isinstance(p.get('skipped'), list):
                st['skipped'] = [c for c in p['skipped'] if c in CARD_IDS]
            if p.get('done'):
                st['done'] = True
                st['step'] = 'done'
            st['at'] = _iso()
            self._save(d)
            return st

    def review_set(self, login, what):
        if what not in ('done', 'later'):
            raise Bad('done or later')
        with LOCK:
            d = self.load()
            d['review'][login] = what
            self._save(d)

    # -- what a Claude run must leave out
    def prompt_note(self):
        d = self.load()
        off = [BY_ID[f] for f in d['owner']['off'] if f in BY_ID]
        if not off:
            return ''
        leave = [f['prompt'] for f in off if f.get('prompt')]
        txt = '\n\nSwitched off by the owner (Settings → What Axella handles): %s.' % ', '.join(f['label'] for f in off)
        if leave:
            txt += ' Leave these out of everything you write – the JSON digest, the written digest and the spoken digest: %s.' % '; '.join(leave)
        return txt

    def denied_paths(self):
        d = self.load()
        out = []
        for fid in d['owner']['off']:
            for p in (BY_ID.get(fid) or {}).get('data') or []:
                out.append(p + ('/**' if not os.path.splitext(p)[1] else ''))
        return out

    # -- Claude use per card, from the last 30 days of runs
    @staticmethod
    def claude_use(runs, since_iso):
        kind = {'digest': 'messages', 'p0': 'messages', 'briefing': 'briefs', 'briefing-personal': 'briefs', 'kb': 'briefs',
                'trips': 'trips', 'projects': 'projects', 'receipts': 'money'}
        import scheduler as _sch
        n = {}
        for r in runs:
            if (r.get('started') or '') < since_iso or r.get('status') in ('skipped',):
                continue
            k = (_sch.TASKS.get(r.get('task')) or {}).get('kind')
            c = kind.get(k)
            if c:
                n[c] = n.get(c, 0) + 1
        return {c: ('none yet' if not v else 'light' if v < 30 else 'moderate' if v < 120 else 'more') for c, v in n.items()} or None

    # -- delete and restore an area's data (owner only)
    def _paths(self, card):
        out = []
        for fid in features_of(card):
            out += BY_ID[fid].get('data') or []
        return out

    def delete_data(self, card):
        if card not in CARD_IDS:
            raise Bad('unknown card')
        d = self.load()
        if any(f not in d['owner']['off'] for f in features_of(card)):
            raise Bad('switch %s off first – its data is only deleted while it is off' % next(c['title'] for c in CARDS if c['id'] == card))
        bid = '%s-%s-%s' % (card, _now().strftime('%Y%m%d-%H%M%S'), uuid.uuid4().hex[:4])
        root = os.path.join(self.state_dir, 'deleted', 'features', bid)
        moved = []
        for rel in self._paths(card):
            src = os.path.join(self.base, rel)
            if os.path.lexists(src):
                dst = os.path.join(root, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                moved.append(rel)
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, 'manifest.json'), 'w', encoding='utf-8') as f:
            json.dump({'card': card, 'at': _iso(), 'paths': moved}, f, indent=1)
        return {'backup': bid, 'moved': moved}

    def restore_data(self, bid):
        if not re.match(r'^[a-z]+-\d{8}-\d{6}-[0-9a-f]{4}$', str(bid or '')):
            raise Bad('bad backup id')
        root = os.path.join(self.state_dir, 'deleted', 'features', bid)
        try:
            with open(os.path.join(root, 'manifest.json'), encoding='utf-8') as f:
                m = json.load(f)
        except (OSError, ValueError):
            raise Bad('that backup is gone')
        stamp = _now().strftime('%Y%m%d-%H%M%S')
        back = []
        for rel in m.get('paths') or []:
            if '..' in rel.split('/') or rel.startswith('/'):
                continue
            src, dst = os.path.join(root, rel), os.path.join(self.base, rel)
            if not os.path.lexists(src):
                continue
            if os.path.lexists(dst):                   # written since the delete: set aside, never lost
                shutil.move(dst, dst + '.since-' + stamp)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            back.append(rel)
        shutil.rmtree(root, ignore_errors=True)
        return {'restored': back}

    def prune_deleted(self, now=None):
        root = os.path.join(self.state_dir, 'deleted', 'features')
        if not os.path.isdir(root):
            return []
        cut = (now or time.time()) - KEEP_DAYS * 86400
        out = []
        for n in os.listdir(root):
            p = os.path.join(root, n)
            if n == '_expired' or not os.path.isdir(p):
                continue
            if os.path.getmtime(p) < cut:
                os.makedirs(os.path.join(root, '_expired'), exist_ok=True)
                shutil.move(p, os.path.join(root, '_expired', n))   # moved, never deleted
                out.append(n)
        return out


def _and(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ', '.join(xs[:-1]) + ' and ' + xs[-1]
