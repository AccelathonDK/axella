"""The activity log (account menu → Activity log): everything done from the dashboard and by Axella itself – one line
per action in state/actions.log (titles only, never what was written), plus the Claude runs from the run ledger.
Newest first, at most 1,000, filterable. Lines older than 90 days move to state/actions-archive/YYYY-MM.log (never
deleted)."""
import json
import os
import re

SHOW_MAX = 1000
KEEP_DAYS = 90
TAIL = 8 * 1024 * 1024

TYPES = {
    'mail': ('reply_send', 'mail_send', 'invite_respond', 'invite_dismiss', 'schedule_send', 'schedule_update', 'schedule_cancel', 'schedule_now', 'schedule_sent', 'draft', 'draft_new', 'file', 'trash', 'trash_batch', 'sender_unsubscribe', 'sender_keep', 'sender_hold', 'senders_quiet_dismiss', 'safety_mark_safe', 'safety_unmark_safe', 'recurring_set', 'recurring_seen', 'recurring_scan', 'auto_forward',
             'document_forward', 'pics_sender', 'cleanup_'),
    'tasks': ('task_', 'reminder_', 'promise_', 'replydebt_'),
    'calendar': ('cal_', 'event', 'trip_'),
    'contacts': ('contact_', 'vip_', 'birthday_'),
    'privacy': ('privacy_',),
    'items': ('done', 'undo', 'snooze', 'ctx_set', 'project_', 'should_have_reached'),
    'assistant': ('compose_assist', 'task_suggest', 'compose', 'ask'),
    'notifications': ('push',),
    'reports': ('report_', 'triage_'),
    'meetings': ('meeting_',),
    'settings': ('schedule_set', 'ooo_', 'recipients_set', 'vendor_', 'briefing_', 'sweep_', 'kb_'),
}
LABELS = {
    'reply_send': 'Reply sent', 'invite_respond': 'Invitation answered', 'invite_dismiss': 'Invitation hidden', 'schedule_send': 'Send later set', 'schedule_update': 'Send later changed', 'schedule_cancel': 'Send later cancelled', 'schedule_now': 'Sent now instead of later', 'schedule_sent': 'Sent later', 'promise_add': 'Promise added to To do', 'promise_dismiss': 'Not a promise', 'promise_done': 'Promise kept', 'promise_not_done': 'Promise not done yet', 'replydebt_never': 'Reply debt: never for this person', 'replydebt_done': 'Reply debt: marked done', 'mail_send': 'Mail sent', 'draft': 'Reply saved as draft', 'draft_new': 'Mail saved as draft',
    'file': 'Filed', 'trash': 'Deleted (to Trash)', 'trash_batch': 'Deleted several (to Trash)', 'sender_unsubscribe': 'Unsubscribed', 'sender_keep': 'Kept a sender', 'sender_hold': 'Always hold (or back in digests)', 'senders_quiet_dismiss': 'Never-opened suggestion: not now', 'safety_mark_safe': 'Marked a sender safe', 'safety_unmark_safe': 'Scam check back on for a sender', 'recurring_set': 'Subscription updated', 'recurring_seen': 'Subscription changes seen', 'recurring_scan': 'Subscriptions re-checked',
    'auto_forward': 'Receipt forwarded automatically', 'document_forward': 'Receipt forwarded', 'done': 'Marked done',
    'undo': 'Undone', 'snooze': 'Snoozed', 'should_have_reached': 'Should have reached me (urgent)', 'ctx_set': 'Work/Private changed', 'task_add': 'Task added', 'task_done': 'Task done',
    'task_undo': 'Task reopened', 'task_delete': 'Task deleted', 'task_update': 'Task changed', 'event': 'Event added',
    'cal_add': 'Event added', 'backup_export': 'Backup exported', 'backup_auto': 'Automatic backups', 'backup_run': 'Back up now', 'away_archive': 'Back from away: Archive all', 'away_undo': 'Back from away: Archive all undone', 'away_catchup': 'Catch me up since…', 'block_hold': 'Focus block held', 'block_never': 'No focus suggestion for that day', 'block_not_now': 'Focus suggestion: not now', 'block_settings': 'Protect your blocks: settings', 'renewal_add': 'Renewal added', 'renewal_not': 'Not a renewal', 'renewal_update': 'Renewal changed', 'renewal_snooze': 'Renewal snoozed', 'renewal_let_renew': 'Renewal: let it renew', 'renewal_renewed': 'Renewal: next date', 'renewal_past': 'Renewal moved to Past', 'renewal_delete': 'Renewal deleted', 'renewal_scan': 'Renewals: mail checked', 'renewal_todo': 'Renewal added to To do', 'project_mail_scan': 'Project: mail scanned', 'project_mail_add': 'Project: mail added', 'project_mail_not': 'Project: not this project', 'project_mail_undo_not': 'Project: offered again', 'project_mail_remove': 'Project: mail removed', 'project_mail_undo_remove': 'Project: mail back', 'project_mail_move': 'Project: mail moved to another project', 'project_match_add': 'Project: sender added to matches', 'project_match_dismiss': 'Project: match not added', 'project_trip_link': 'Project linked to a trip', 'project_trip_unlink': 'Project unlinked from a trip', 'project_mail_attach': 'Project: attachment to Documents', 'project_read': 'Project: mails read by Claude', 'project_suggestion_done': 'Project: suggestion handled', 'cal_invite_send': 'Invitations sent', 'cal_invite_update': 'Invitation updated', 'cal_invite_cancel': 'Invitation cancelled', 'meeting_service_connect': 'Meeting service: connecting', 'meeting_service_connected': 'Meeting service connected', 'meeting_service_disconnect': 'Meeting service disconnected', 'meeting_service_default': 'Default meeting service', 'cal_update': 'Event changed', 'cal_delete': 'Event deleted', 'cal_restore': 'Event restored',
    'contact_add': 'Contact added', 'contact_update': 'Contact changed', 'contact_delete': 'Contact deleted',
    'contact_restore': 'Contact restored', 'birthday_show': 'Birthday shown or hidden', 'trip_scan': 'Trip scan', 'trip_confirm': 'Trip confirmed', 'trip_dismiss': 'Not a trip', 'trip_undismiss': 'Trip suggestion back', 'trip_rename': 'Trip renamed', 'trip_apply_new': 'Trip: new bookings added', 'trip_not_part': 'Trip: not part of this trip', 'trip_mail_add': 'Trip: mail added', 'trip_mail_new': 'Trip made from a mail', 'trip_mail_not_travel': 'Trips: mail voided', 'trip_suggest_add': 'Trip: bookings added from a suggestion', 'trip_move_booking': 'Trip: booking moved', 'trip_void': 'Trip: booking voided', 'trip_unvoid': 'Trip: voided booking restored', 'trip_booking_rename': 'Trip: booking renamed', 'trip_booking_edit': 'Trip: booking changed', 'trip_ctx': 'Trip: work or private', 'trip_part_again': 'Trip: may be offered again', 'trip_read': 'Trips: booking mails read by Claude', 'trip_remove': 'Trip removed', 'trip_restore': 'Trip restored', 'trip_undo': 'Trip: step undone', 'trip_merge': 'Trips merged', 'trip_split': 'Trip split', 'trip_item_add': 'Trip: item added by hand', 'trip_item_remove': 'Trip: item removed', 'trip_cancel': 'Trip: item cancelled or back', 'trip_plan_booked': 'Trip: quote booked', 'trip_plan_drop': 'Trip: quote dropped', 'trip_plan_replace': 'Trip: confirmation in place of a quote', 'trip_check_add': 'Trip checklist: item added', 'trip_check_set': 'Trip checklist: item changed', 'trip_check_remove': 'Trip checklist: item removed', 'bill_paid_already': 'Bill: already paid', 'trip_update_apply': 'Trip: update applied', 'trip_update_ignore': 'Trip: update ignored', 'trip_cal_add': 'Trip added to the calendar', 'trip_cal_sync': 'Trip: calendar event updated', 'trip_cal_remove': 'Trip: calendar event removed', 'vip_add': 'Added to VIPs', 'vip_remove': 'Removed from VIPs',
    'vip_update': 'VIP changed', 'privacy_set': 'Privacy settings changed', 'compose_assist': 'Writing assistant',
    'task_suggest': 'Task suggestion', 'compose': 'Mail drafted by Axella', 'ask': 'Asked Axella', 'push': 'Notification',
    'report_send': 'Problem report sent', 'report_save': 'Problem report saved', 'triage_act': 'Community report handled',
    'schedule_set': 'Schedule changed', 'run': 'Claude run',
    'meeting_add': 'Meeting prep started', 'meeting_update': 'Meeting prep changed', 'meeting_delete': 'Meeting prep deleted',
    'meeting_restore': 'Meeting prep restored', 'meeting_upload': 'Material added to a meeting prep',
    'meeting_url_add': 'Web page added to a meeting prep', 'meeting_mail_add': 'Mail added to a meeting prep',
    'meeting_material_update': 'Meeting material changed', 'meeting_material_remove': 'Material removed from a meeting prep',
    'meeting_assist': 'Meeting assistant', 'meeting_transcript_upload': 'Recording or transcript added',
    'meeting_transcript_paste': 'Transcript added', 'meeting_transcribe': 'Recording transcribed again',
    'meeting_ai_default': 'Claude default for workplace meetings changed',
}


def type_of(action):
    a = str(action or '')
    if a == 'run':
        return 'runs'
    for t, prefixes in TYPES.items():
        if any(a == x or (x.endswith('_') and a.startswith(x)) for x in prefixes):
            return t
    return 'other'


def label_of(action):
    a = str(action or '')
    return LABELS.get(a) or a.replace('_', ' ').capitalize()


def _tail(path, size=TAIL):
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - size))
            data = f.read().decode('utf-8', 'replace')
    except OSError:
        return []
    lines = data.split('\n')
    if n > size:
        lines = lines[1:]                               # the first one may be cut
    out = []
    for l in lines:
        try:
            e = json.loads(l)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get('at'):
            out.append(e)
    return out


def entries(log_file, runs, q=None):
    """Newest first, filtered: q = {type, result ('ok'|'error'), who, text, limit}."""
    q = q or {}
    rows = []
    for e in _tail(log_file):
        res = str(e.get('result') or '')
        rows.append({'at': e['at'], 'who': e.get('login') or '-', 'action': e.get('action'), 'type': type_of(e.get('action')),
                     'label': label_of(e.get('action')), 'title': (e.get('title') or e.get('folder') or None),
                     'result': res[:200], 'ok': res.split(':')[0] in ('ok', 'queued', 'already') or res.startswith('sent'),
                     'backup': e.get('backup')})
    for r in runs or []:
        if not r.get('started'):
            continue
        st = str(r.get('status') or '')
        rows.append({'at': r['started'], 'who': 'axella', 'action': 'run', 'type': 'runs', 'label': r.get('label') or 'Claude run',
                     'title': (r.get('trigger') or None), 'result': (st + (': ' + str(r.get('reason'))[:160] if r.get('reason') else '')) or 'ok',
                     'ok': st not in ('failed', 'error'), 'backup': None})
    rows.sort(key=lambda r: str(r['at']), reverse=True)
    # a send is logged when tapped ("queued") and when done: show the tap only if it never finished
    done = {(r['action'], r['title']) for r in rows if r['result'] != 'queued'}
    rows = [r for r in rows if r['result'] != 'queued' or (r['action'], r['title']) not in done]
    t, res, who = q.get('type'), q.get('result'), q.get('who')
    text = str(q.get('text') or '').strip().lower()
    if t:
        rows = [r for r in rows if r['type'] == t]
    if res == 'ok':
        rows = [r for r in rows if r['ok']]
    elif res == 'error':
        rows = [r for r in rows if not r['ok']]
    if who:
        rows = [r for r in rows if r['who'] == who]
    if text:
        rows = [r for r in rows if text in ' '.join(str(r.get(k) or '') for k in ('label', 'title', 'result', 'action')).lower()]
    try:
        limit = max(1, min(int(q.get('limit') or SHOW_MAX), SHOW_MAX))
    except ValueError:
        limit = SHOW_MAX
    whos = sorted({r['who'] for r in rows})
    return {'entries': rows[:limit], 'total': len(rows), 'capped': len(rows) > limit, 'types': sorted(TYPES) + ['runs', 'other'],
            'who': whos, 'keep_days': KEEP_DAYS}


def archive(log_file, archive_dir, lock, now_iso_date, days=KEEP_DAYS):
    """Move lines older than `days` into archive_dir/YYYY-MM.log. Returns how many moved."""
    import datetime
    cutoff = (datetime.date.fromisoformat(now_iso_date) - datetime.timedelta(days=days)).isoformat()
    with lock:
        try:
            with open(log_file, encoding='utf-8') as f:
                lines = f.read().split('\n')
        except OSError:
            return 0
        keep, old = [], {}
        for l in lines:
            if not l.strip():
                continue
            m = re.search(r'"at":\s*"(\d{4}-\d{2}-\d{2})', l)
            if m and m.group(1) < cutoff:
                old.setdefault(m.group(1)[:7], []).append(l)
            else:
                keep.append(l)
        if not old:
            return 0
        os.makedirs(archive_dir, mode=0o700, exist_ok=True)
        for month, ls in old.items():
            with open(os.path.join(archive_dir, month + '.log'), 'a', encoding='utf-8') as f:
                f.write('\n'.join(ls) + '\n')
        tmp = log_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write('\n'.join(keep) + ('\n' if keep else ''))
        os.replace(tmp, log_file)
        return sum(len(v) for v in old.values())
