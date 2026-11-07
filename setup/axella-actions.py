#!/usr/bin/env python3
"""Axella action service (runs on the Mac mini, localhost only, behind Tailscale Serve).

Fixed list of actions, nothing else:
  POST draft   – save a threaded reply as a DRAFT in Mail (never sends)
  GET  vips / POST vip_add, vip_remove, vip_update – the VIP lists in contacts.md (## VIP … sections; the call agent reads them too)
  POST outbox_upload (raw body) – an attachment for the next send, kept in state/outbox at most 24 h
  POST reply_send, mail_send – SEND a reply in the thread / a new mail, ONLY on the owner's confirmed tap
       (payload confirm:"send", at most SEND_MAX per hour, every send logged in state/sent.json)
  POST file    – move a message to an allowed folder
  POST trash   – move a message to the account's Trash (recoverable; never a permanent delete)
  POST event   – create a calendar event (only on the owner's tap)
  POST done    – mark a dashboard item as handled
  POST snooze  – hide an item until a given time
  POST undo    – clear done/snoozed for an item
  GET  state   – handled/snoozed items, for the dashboard
  GET  health  – liveness check
  GET  senders / POST sender_unsubscribe, sender_keep, sender_hold, senders_quiet_dismiss – newsletters (subscriptions.py)
  POST safety_mark_safe, safety_unmark_safe – the scam check (safety.py)
  GET  recurring / POST recurring_set, recurring_seen, recurring_scan – the Subscriptions overview (recurring.py; app store items: app_stores.py)
  GET  calm / POST digest_seen, should_have_reached – Insights → Your calm (calm.py)
  GET  person, keep_in_touch / POST person_note, keep_set – the People page and keep in touch (people.py, owner only)
  GET  bills / POST bill_add, bill_dismiss, bill_looks_paid – bills as a To do type (bills.py)
  POST recipients_set, document_forward, vendor_auto_forward – forward receipts to the recipients list ONLY (forwarding.py)
  GET  documents / POST document_set, document_hide – receipts & invoices per vendor (documents.py)
  GET  schedule / POST schedule_set, sweep_request, sweep_cancel – vacation mode, days off, on-demand sweep (schedule.py)
  GET  attachment – one attachment of a mail (saved by Mail to a temp folder, served, deleted)
  GET  message – read-only preview of one mail (subject, sender, body text, attachment names)
  GET  projects, project_file / POST project_* and project_upload – notes, links, documents per project (projects.py)
  GET  tasks / POST task_add, task_done, task_undo, task_delete, task_update (due/text) – the owner's to-do list (state/tasks.json)
  GET  reminders / POST reminder_add, reminder_update, reminder_delete – recurring reminders that add tasks (reminders.py)
  GET  ask?id= / POST ask – Ask Axella chat: a short read-only Claude run answers (scheduler.py, local-tasks/ask.md)
  GET  knowledge, knowledge_search / POST kb_add, kb_update, kb_delete – knowledge base entries (knowledge.py)
  GET  cleanup / POST cleanup_settings, cleanup_scan, cleanup_move, cleanup_undo, cleanup_keep, cleanup_unkeep
       – mail cleanup: old mail with no relationship → the account's "Cleanup" folder, undoable (cleanup.py)
  GET  kb_harvest / POST kb_scan_add, kb_scan_pause, kb_scan_resume, kb_scan_cancel, kb_scan_remove, kb_scan_now, kb_nightly
       – knowledge harvest: nightly sent-mail suggestions + mailbox scans (kb_harvest.py, local-tasks/kb-harvest.md)

Security:
  - binds to 127.0.0.1 only; reachable solely through Tailscale Serve, and every connection must come from Tailscale's
    own process (checked with netstat + ps), so other users and programs on the Mac can't connect and fake its headers
  - every request must carry the Tailscale-User-Login header that Tailscale Serve adds
    and be allowed for /axella/ in home-server/www/access.json (same rule as the dashboard)
  - POSTs must send header X-Axella: 1 and a JSON body (blocks cross-site form posts)
  - AppleScript gets all user data as argv, never pasted into script text
  - NO permanent-delete action. Mail is sent only by reply_send / mail_send on the owner's confirmed tap in the
    dashboard (never by a Claude run, never on a schedule). Other outgoing mail: forwarding receipts to the fixed recipients list
    (state/recipients.json, set in the dashboard) on the owner's tap or per-vendor auto-forward he switched on, and
    RFC 8058 one-click unsubscribe POSTs on his tap. Unsubscribe-by-mail only creates a draft.
"""
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)                       # .../axella
STATE_DIR = os.path.join(BASE, 'state')
STATE_FILE = os.path.join(STATE_DIR, 'actions.json')
LOG_FILE = os.path.join(STATE_DIR, 'actions.log')
SENT_FILE = os.path.join(STATE_DIR, 'sent.json')       # every mail sent from the dashboard (who, when, what it answered)
OUTBOX_DIR = os.path.join(STATE_DIR, 'outbox')        # attachments uploaded for a mail you're about to send (cleared after 24 h)
OUTBOX_MAX = 200 * 2**20                                # all pending attachments together
SEND_MAX = 20                                            # sends per hour – a brake, not a quota
TASKS_FILE = os.path.join(STATE_DIR, 'tasks.json')
CTX_FILE = os.path.join(STATE_DIR, 'context-overrides.json')
DRAFTS_FILE = os.path.join(STATE_DIR, 'drafts.json')            # replies saved to Drafts from the dashboard (item → draft id)
FILING_FILE = os.path.join(STATE_DIR, 'filing-learned.json')     # sender → folder the owner chose instead of the suggestion
DIGESTS_DIR = os.path.join(BASE, 'digests')
PUSH_SUBS_FILE = os.path.join(STATE_DIR, 'push-subscriptions.json')
PUSH_LAST_FILE = os.path.join(STATE_DIR, 'push-last.json')
VAPID_FILE = os.path.join(STATE_DIR, 'vapid.json')
# Web Push contact (VAPID "sub"): actions-config.json "push_contact"
CONFIG_FILE = os.path.join(HERE, 'actions-config.json')
ACCESS_FILE = os.path.join(os.path.dirname(BASE), 'www', 'access.json')
PORT = int(os.environ.get('AXELLA_ACTIONS_PORT', '8788'))
LOCK = threading.Lock()
sys.path.insert(0, HERE)
import audio  # noqa: E402  (Listen: macOS say → m4a)
import mailsearch  # noqa: E402  (search all mail with Spotlight, read found .emlx files)
from projects import Projects, Bad as ProjectBad  # noqa: E402
PROJ = Projects(STATE_DIR)
import project_scan as _pscan  # noqa: E402  (Projects → Scan mail: rules only, To sort, the Mails card)
PSCAN = _pscan.ProjectMail(STATE_DIR)
from schedule import Schedule, Bad as ScheduleBad  # noqa: E402
from store import Store  # noqa: E402
import axprofile as profile  # noqa: E402
from ooo import OutOfOffice, Bad as OooBad  # noqa: E402
SCHED = Schedule(STATE_DIR)
from documents import Documents, Bad as DocumentsBad  # noqa: E402
DOCS = Documents(STATE_DIR, DIGESTS_DIR)

os.makedirs(STATE_DIR, exist_ok=True)


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def load_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def spoken_digest():
    """(plain text, mtime) of digests/spoken-digest.md without markdown – what Listen and Siri read."""
    import re as _re
    p = os.path.join(DIGESTS_DIR, 'spoken-digest.md')
    try:
        with open(p, encoding='utf-8') as f:
            raw = f.read()
        mtime = os.path.getmtime(p)
    except OSError:
        return 'There is no spoken digest yet.', 0
    lines = []
    for ln in raw.splitlines():
        ln = _re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', ln)          # [text](link) -> text
        ln = _re.sub(r'^#+\s*', '', ln).replace('**', '').replace('__', '').replace('`', '')
        ln = _re.sub(r'^\s*[-*]\s+', '', ln).strip()
        if ln:
            lines.append(ln if ln[-1] in '.!?:' else ln + '.')
    text = '\n'.join(lines)
    age = (time.time() - mtime) / 3600
    if age > 12:
        text = 'Note: this digest is %d hours old.\n' % round(age) + text
    return text, mtime


def listen_segments():
    """The Listen queue: the spoken digest, then the briefs of the last 36 hours that are set to be heard – each
    brief as an opening line plus one segment per item, so next/previous on the lock screen skips one item."""
    import datetime as _dt
    import re as _re
    text, mtime = spoken_digest()
    segs = [{'id': 'digest-%d' % int(mtime), 'kind': 'digest', 'title': 'Spoken digest', 'album': 'Axella digest', 'text': text}]
    on = {b['id']: b.get('voice', True) for b in BRIEF.load()['briefings']}
    since = (_dt.datetime.now().astimezone() - _dt.timedelta(hours=36)).isoformat(timespec='seconds')
    for br in sorted(BRIEF.recent(since, 20), key=lambda x: x.get('at') or ''):
        if not on.get(br.get('briefing'), True):
            continue
        key = 'b-%s-%s' % (br['briefing'], br['id'])
        lang = br.get('language') if br.get('language') in ('da', 'en') else None
        clean = lambda t: _re.sub(r'https?://\S+', '', str(t or '')).strip()
        head = clean(br['headline']).rstrip('.')
        opening = (head if head.lower().startswith(br['name'].lower()) else
                   ('Dit %s-brief. ' if lang == 'da' else 'Your %s brief. ') % br['name'] + head) + '.'
        if br.get('nothing_new'):
            segs.append({'id': key + '-0', 'kind': 'brief', 'brief': key, 'title': br['name'], 'album': 'Axella briefing',
                         'text': opening, 'lang': lang})
            continue
        segs.append({'id': key + '-0', 'kind': 'brief', 'brief': key, 'title': br['name'], 'album': 'Axella briefing',
                     'text': opening, 'lang': lang})
        for i, it in enumerate(br.get('items') or [], 1):
            src = ('Kilde: %s.' if lang == 'da' else 'Source: %s.') % it.get('source') if it.get('source') else ''
            segs.append({'id': '%s-%d' % (key, i), 'kind': 'brief', 'brief': key, 'title': clean(it.get('title'))[:120],
                         'album': br['name'], 'lang': lang,
                         'text': '%s. %s %s' % (clean(it.get('title')).rstrip('.'), clean(it.get('summary')), src)})
        if br.get('personal_note'):
            segs.append({'id': key + '-p', 'kind': 'brief', 'brief': key, 'title': 'For you', 'album': br['name'],
                         'text': clean(br['personal_note']), 'lang': lang})
    return segs


WA_FILE = os.path.join(STATE_DIR, 'whatsapp.json')


def chat_preview(address, name, limit=15, channel='whatsapp'):
    """The last messages of one WhatsApp chat, from the read-only export (state/whatsapp.json, refreshed every 2 min,
    covers the last 48 h). Matched on the number / group id, then on the chat name. Nothing is opened or marked read."""
    d = load_json(os.path.join(STATE_DIR, 'signal.json') if channel == 'signal' else WA_FILE, {})
    digits = re.sub(r'\D', '', (address or '').split('@')[0])
    chats = d.get('chats') or []
    c = next((c for c in chats if digits and re.sub(r'\D', '', (c.get('jid') or '').split('@')[0]) == digits), None)
    if not c and (name or '').strip():
        n = name.strip().lower()
        c = next((c for c in chats if (c.get('name') or '').strip().lower() == n), None)
    out = {'generated': d.get('generated'), 'window_hours': d.get('window_hours'), 'export_ok': bool(d.get('ok')),
           'export_error': d.get('error') if not d.get('ok') else None, 'chat': None}
    if c:
        out['chat'] = {'name': c.get('name'), 'group': bool(c.get('group')), 'last_at': c.get('last_at'),
                       'messages': [{'at': m.get('at'), 'from_me': bool(m.get('from_me')), 'sender': m.get('sender'),
                                     'text': str(m.get('text') or '')[:1000],
                                     **({'media': m['media']['id']} if isinstance(m.get('media'), dict) else {})}
                                    for m in (c.get('messages') or [])[-limit:]]}
    return out


PAGE_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Axella</title><style>
:root{color-scheme:light dark;--bg:#f4f5f7;--card:#fff;--ink:#16181d;--ink2:#5b616e;--line:#e2e4e9;--fjord:#2f6fae}
@media (prefers-color-scheme:dark){:root{--bg:#141518;--card:#1d1f24;--ink:#eceef2;--ink2:#9aa1ad;--line:#2c2f36;--fjord:#7fb2e5}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,system-ui,sans-serif;padding:24px;box-sizing:border-box}
.c{max-width:440px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:28px 28px 24px}
.m{display:flex;gap:10px;align-items:center;font:600 13px/1 ui-monospace,monospace;letter-spacing:.12em;color:var(--ink2);margin-bottom:18px}
h1{font-size:19px;margin:0 0 8px;letter-spacing:-.01em}p{margin:0 0 20px;color:var(--ink2)}
a,button{font:inherit;font-weight:600;color:var(--fjord);background:none;border:0;padding:0;cursor:pointer;text-decoration:none}
</style></head><body><div class="c"><div class="m"><svg width="18" height="18" viewBox="0 0 100 100" aria-hidden="true"><clipPath id="r"><rect width="100" height="75.5"/></clipPath><path clip-path="url(#r)" d="M71 79.5 33 41.5 50 24.5 67 41.5 29 79.5" fill="none" stroke="currentColor" stroke-width="11"/></svg>AXELLA</div>
<h1>%(title)s</h1><p>%(text)s</p><button onclick="history.length>1?history.back():window.close()">Back to Axella</button></div></body></html>"""


def _attachment_reason(e):
    t = str(e)
    if 'downloaded' in t or 'not found' in t.lower() or 'Message not found' in t:
        return ("Mail on the Mac mini doesn't have this attachment, and couldn't fetch it from the server. "
                "Open the message in Mail once – it downloads the attachment – and try again.")
    if 'expired' in t:
        return 'This search result has expired. Search again and open the attachment from there.'
    return 'Something went wrong while fetching it from Mail: ' + t[:200]


_MAIL_ACC = {'at': 0, 'map': {}}


def mail_accounts():
    """Mail's account id → account name, for the accounts Axella is set up for (cached for an hour)."""
    import time
    if time.time() - _MAIL_ACC['at'] > 3600 or not _MAIL_ACC['map']:
        allowed = set(config().get('accounts', {}))
        m = {}
        for line in osa(mailsearch.ACCOUNTS_SCRIPT, timeout=30).splitlines():
            i, _, n = line.partition('\t')
            if i.strip() and n.strip() in allowed:
                m[i.strip()] = n.strip()
        _MAIL_ACC.update(at=time.time(), map=m)
    return _MAIL_ACC['map']


def report_action(action, p):
    if action == 'report_save':
        return REPORTS.save(p)
    if action == 'report_check':
        return {'flags': reports_mod.check_text(p.get('text'), report_names()), 'suggested': reports_mod.suggest_class(p.get('text'))}
    if action == 'report_preview':
        return REPORTS.preview(str(p.get('id') or ''), (p.get('reply') or '').strip() or None)
    if action == 'report_send':
        return REPORTS.send(str(p.get('id') or ''), (p.get('reply') or '').strip() or None)
    if action == 'report_status':
        return REPORTS.refresh_status(str(p.get('id') or ''))
    if action == 'report_discard':
        return REPORTS.discard(str(p.get('id') or ''))
    if action == 'report_rotate':
        REPORTS.install_token(rotate=True)
        return {'rotated': True}
    if action == 'triage_act':
        rid = re.sub(r'[^\w-]', '', str(p.get('id') or ''))
        body = {k: p.get(k) for k in ('action', 'title', 'text', 'class', 'into') if p.get(k) is not None}
        res = REPORTS.triage('POST', '/' + rid + '/act', body)
        if not isinstance(res, dict) or not res.get('ok'):          # the intake's error (e.g. what GitHub said) – never a silent "ok"
            raise Bad(str((res or {}).get('error') if isinstance(res, dict) else 'no answer from the intake')[:200] or 'the intake refused')
        return res
    raise Bad('unknown report action')


PICS_FILE = os.path.join(STATE_DIR, 'pics-senders.json')


def _sender_of(text):
    m = re.search(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', text or '')
    return m.group(0).lower() if m else ''


def pics_always(addr):
    """Senders whose pictures load without asking ("Always for this sender") – off for everyone else."""
    return bool(addr) and addr.lower() in load_json(PICS_FILE, [])


def pics_sender_set(addr, on):
    addr = _sender_of(addr)
    if not addr:
        raise Bad('no sender address')
    with LOCK:
        lst = [a for a in load_json(PICS_FILE, []) if a != addr]
        if on:
            lst.append(addr)
        with open(PICS_FILE + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(lst[-500:], f, indent=1)
        os.replace(PICS_FILE + '.tmp', PICS_FILE)
    return {'address': addr, 'always': on}


def meeting_mail_addresses(sender, mid, strict=False):
    """Every address of a mail used as meeting material: the stored From plus From/To/Cc/Reply-To/Sender from the mail
    file. strict: the mail file must be found (else []), so a caller that hands the body to Claude fails closed."""
    addrs = re.findall(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', str(sender or ''))
    try:
        path = mailsearch.path_for_mid(str(mid or '')[:500])
        found = mailsearch.addresses_of(path) if path else []
    except Exception:
        found = []
    if strict and not found:
        return []
    return addrs + found


def mail_privacy(addresses):
    """(level, name) for a message: 'hidden' if any address belongs to a contact hidden on Mail, else 'private' if
    any is private there, else (None, None). Same matching as the exporters (privacy.norm)."""
    level, name = None, None
    for a in addresses or []:
        lv = PRIV.level('mail', a)
        if lv == 'hidden':
            return 'hidden', None
        if lv == 'private' and not level:
            c = PRIV.contact(a)
            level, name = 'private', (None if PRIV.load().get('discreet') else (c or {}).get('name'))
    return level, name


def task_suggest(p):
    """Task from a mail: read the mail here (configured accounts only, private/hidden contacts refused) and let a
    tool-less Claude run propose title, details and a due date (task_suggest.py). Nothing is saved – the owner edits
    the proposal and adds it with task_add."""
    import task_suggest as ts
    try:
        if p.get('file'):
            try:
                mail = mailsearch.read(str(p['file'])[:500])
            except mailsearch.NotDownloaded as nd:          # not on disk: ask Mail for it
                if not (nd.account and nd.mid):
                    raise
                p = {'account': nd.account, 'message_id': nd.mid}
                mail = dict(message_preview(nd.account, nd.mid))
            addrs = re.findall(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', mail.get('from') or '')
            try:
                addrs += mailsearch.addresses_of(mailsearch._entry(str(p['file'])[:500]))
            except Exception:
                pass
        else:
            account, mid = str(p.get('account') or ''), str(p.get('message_id') or '')
            mail = dict(message_preview(account, mid))
            addrs = re.findall(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', mail.get('from') or '')
            try:
                addrs += mailsearch.addresses_of(mailsearch.path_for_mid(mid))
            except Exception:
                pass
    except mailsearch.SearchError as e:
        raise Bad(str(e))
    if mail_privacy(addrs)[0]:
        raise Bad('This mail involves a private contact – Axella doesn\'t read it.')
    models = RUNNER.load().get('models') or {}
    try:
        return ts.suggest(mail, profile.owner().get('first_name') or 'the owner', model=models.get('task') or models.get('compose') or 'sonnet')
    except ts.SuggestError as e:
        raise Bad(str(e))


def compose_assist(p):
    """The reply box's writing assistant (compose_assist.py): the mail being answered is read here with the same checks
    as for showing it (configured accounts, private/hidden contacts refused); a tool-less Claude call returns text."""
    import compose_assist as ca
    mail = {}
    if p.get('message_id'):
        account, mid = str(p.get('account') or ''), str(p.get('message_id') or '')[:500]
        mail = dict(message_preview(account, mid))
        addrs = re.findall(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', mail.get('from') or '')
        try:
            addrs += mailsearch.addresses_of(mailsearch.path_for_mid(mid))
        except Exception:
            pass
        if mail_privacy(addrs)[0]:
            raise Bad('This mail involves a private contact – Axella doesn\'t read it.')
    elif p.get('to'):                                  # a new mail you write yourself: no AI for a private contact
        to = str(p.get('to') or '').strip().lower()[:200]
        if mail_privacy([to])[0]:
            raise Bad('This is a private contact – the writing assistant stays off for them.')
    models = RUNNER.load().get('models') or {}
    try:
        return ca.assist(p, mail, profile.owner(), model=models.get('compose') or 'sonnet')
    except ca.AssistError as e:
        raise Bad(str(e))


def _latest_digest_items(section):
    """Items of one section in the newest regular digest (the Waiting list for meeting prep)."""
    try:
        names = sorted(f for f in os.listdir(DIGESTS_DIR) if f.endswith('.json') and not re.search(r'-p0\b', f))
    except OSError:
        return []
    for f in reversed(names[-3:]):
        d = load_json(os.path.join(DIGESTS_DIR, f), {})
        if isinstance(d, dict) and d.get('items'):
            return [i for i in d['items'] if isinstance(i, dict) and i.get('section') == section]
    return []


def meeting_ai(prep, with_source=False):
    """(protected, mode): mode is what may go to Claude for this meeting – 'all' for an ordinary meeting; for one with a
    protected workplace the choice on the prep, else the workplace's default (Meetings page), else 'own' (your own
    goals, points and notes only)."""
    import meetings
    wps = meeting_workplaces(prep)
    mode, source = meetings.effective_ai(prep, wps, MEET.ai_defaults())
    return (bool(wps), mode, source, wps) if with_source else (bool(wps), mode)


def meeting_context(mid, for_claude=False):
    """People, recent mail, open tasks and waiting items around one meeting – gathered here, private contacts left out,
    protected-workplace mail as who/when/subject only (meetings.gather)."""
    import meetings
    prep = MEET.get(mid)
    shielded, mode = meeting_ai(prep)
    return meetings.gather(
        prep, level=lambda addrs: mail_privacy(addrs)[0], protected=lambda acc, addr: profile.is_protected(acc, addr),
        search=lambda q: mail_search(q, limit=6).get('items') or [], preview=message_preview,
        tasks=load_json(TASKS_FILE, []), waiting=_latest_digest_items('wait'), others=MEET.load()['preps'],
        max_mails=3 if for_claude else 0, read_protected=for_claude and mode == 'all')


def meeting_workplaces(prep):
    """The protected workplaces in a meeting – by an attendee's domain or the workplace's calendar (AXELLA.md rule 4)."""
    out = []
    cal = ((prep.get('event') or {}).get('calendar') or '')
    cals = {c['name']: c.get('workplace') for c in profile.calendars()}
    for w in profile.workplaces():
        if not w['protected']:
            continue
        mails = [str(a.get('email') or '').lower() for a in prep.get('attendees') or []]
        if (any('@' in m and any(m.endswith('@' + d) or m.endswith('.' + d) for d in w['domains']) for m in mails)
                or (cal and (cal == w.get('calendar') or cals.get(cal) == w['id']))):
            out.append(w['id'])
    return out


def meeting_protected(prep):
    return bool(meeting_workplaces(prep))


def transcriber():
    """whisper.cpp on the Mac mini; each transcription is a line on Runs (length, model, duration – never the text)."""
    import meetings
    return meetings.Transcriber(config().get('meetings') or {},
                                note=lambda status, summary, started, ended: RUNNER.note_run('transcribe', 'Transcription', status, summary, started, ended))


def _project_text(pid, kind, ref):
    """A project's note, link or document for a meeting prep ("Add from project…"): read from the project each time,
    so the project keeps the original. None when it isn't there (any more)."""
    import meetings
    try:
        pr = next((x for x in PROJ.load().get('projects', []) if x.get('id') == pid), None)
    except Exception:
        pr = None
    if not pr:
        return None
    if kind == 'note':
        n = next((x for x in pr.get('notes') or [] if x.get('id') == ref), None)
        return n.get('text') if n else None
    if kind == 'link':
        n = next((x for x in pr.get('links') or [] if x.get('id') == ref), None)
        return ('%s\n%s' % (n.get('title') or '', n.get('url') or '')).strip() if n else None
    e = next((x for x in pr.get('files') or [] if x.get('id') == ref), None)
    if not e:
        return None
    ext = {'application/pdf': '.pdf', 'text/plain': '.txt', 'text/markdown': '.md',
           'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx'}.get(e.get('type'))
    return meetings.file_text(PROJ._path(pr['id'], e), ext) if ext else ''


def meeting_action(action, p):
    import meetings
    import task_suggest as _ts
    try:
        if action == 'meeting_ai_default':
            if p.get('workplace') not in {w['id'] for w in profile.workplaces() if w['protected']}:
                raise Bad('not a protected workplace')
            return MEET.set_ai_default(p.get('workplace'), p.get('ai'))
        if action == 'meeting_transcript_paste':
            return MEET.paste_transcript(p.get('id'), p.get('text'), p.get('name') or 'Transcript')
        if action == 'meeting_transcribe':
            return MEET.retranscribe(p.get('id'), p.get('material'), transcriber())
        if action == 'meeting_record_finish':
            return MEET.record_finish(p.get('id'), p.get('rec'), p.get('name'), transcriber())
        if action == 'meeting_record_drop':
            return MEET.record_drop(p.get('id'), p.get('rec'))
        if action == 'meeting_speakers':
            p['_owner'] = profile.owner().get('name') or profile.owner().get('first_name') or ''
        if action == 'meeting_url_add':
            r = MEET.add_url(p.get('id'), p.get('url'))
            tally('meeting_pages')
            return r
        if action == 'meeting_assist':
            prep = MEET.get(p.get('id'))
            prot, mode = meeting_ai(prep)
            if mode == 'none':
                raise Bad('Claude is off for this meeting – change it under "Claude and this meeting" on the prep.')
            ctx = meeting_context(prep['id'], for_claude=True)
            mats = []
            shielded = prot and mode != 'all'
            open_all = prot and mode == 'all'
            for x in prep.get('materials') or []:
                if x.get('kind') == 'transcript':
                    if x.get('status') != 'ready':
                        continue
                    mats.append(dict(x, protected=shielded, text='' if shielded else MEET.material_text(prep['id'], x['id'], meetings.MAX_TRANSCRIPT)))
                    continue
                if open_all:
                    x = dict(x, protected=False)       # the owner chose to let Claude read this meeting's material
                t = '' if x.get('protected') else MEET.material_text(prep['id'], x['id'])
                if x.get('kind') == 'mail' and not x.get('protected'):
                    # Re-check every address on the mail (From, To, Cc, Reply-To, Sender) now: a contact made private
                    # since the mail was added keeps it from Claude. If the mail file can't be found, Claude gets nothing.
                    t = ''
                    try:
                        addrs = meeting_mail_addresses(x.get('from'), x.get('message_id'), strict=True)
                        if addrs and not mail_privacy(addrs)[0]:
                            t = (message_preview(x.get('account'), x.get('message_id')) or {}).get('body') or ''
                    except Exception:
                        t = ''
                mats.append(dict(x, text=t))
            kind = str(p.get('kind') or '')
            target = next((x for x in mats if x['id'] == p.get('material')), None) if kind == 'summary' else None
            if kind == 'summary' and not target:
                raise Bad('pick a material to summarise')
            if target:
                mats = [target]
            prompt = meetings.build_prompt(prep, ctx, mats, kind, owner=profile.owner().get('first_name') or 'the owner',
                                           question=p.get('question') or '', material=target)
            models = RUNNER.load().get('models') or {}
            return meetings.assist(prompt, _ts.claude_bin(), model=models.get('meeting') or models.get('compose') or 'sonnet')
        if isinstance(p.get('mail'), dict):          # a mail as material: never one that involves a private contact
            addrs = meeting_mail_addresses(p['mail'].get('from'), p['mail'].get('message_id'))
            if mail_privacy(addrs)[0]:
                raise Bad('This mail involves a private contact – Axella doesn\'t use it.')
        return MEET.action(action, p, protected=lambda acc, addr: profile.is_protected(acc, addr))
    except meetings.Bad as e:
        raise Bad(str(e))


def invite_load(account, mid):
    """The invitation (.ics) in one message, read on the Mac mini – configured accounts only, never a hidden contact's."""
    import invites
    if account not in config().get('accounts', {}):
        raise Bad('account not allowed')
    mid = str(mid or '')[:500]
    path = mailsearch.path_for_mid(mid) if mid else None
    rp = mailsearch._inside(path) if path else None
    if not rp:
        raise Bad("Mail hasn't got this message on the Mac mini yet – open it in Mail once, then try again")
    try:
        addrs = mailsearch.addresses_of(rp)
    except Exception:
        addrs = []
    if mail_privacy(addrs)[0] == 'hidden':
        raise Bad('not available')
    raw = mailsearch._raw(rp)
    ics = invites.ics_from_message(raw) or invites.ics_from_attachments(rp)
    if not ics:
        raise Bad('no calendar invitation in this mail')
    try:
        ev = invites.parse(ics)
    except invites.Bad as e:
        raise Bad(str(e))
    try:
        import email as _em
        import email.policy as _emp
        h = _em.message_from_bytes(raw, policy=_emp.compat32)
        ev['mail_from'] = (_em.utils.parseaddr(mailsearch._dec(h.get('From') or ''))[1] or '').lower()
    except Exception:
        ev['mail_from'] = ''
    return ev


def _domain(addr):
    return str(addr or '').rsplit('@', 1)[-1].strip().lower().rstrip('.') if '@' in str(addr or '') else ''


def invite_check(ev):
    """Whom the answer goes to, against the mail it came in (security review 5): a no-reply organizer can't be
    answered; an organizer on another domain than the mail's From is shown as a warning on the sheet."""
    org = ((ev.get('organizer') or {}).get('email') or '').lower()
    frm = str(ev.get('mail_from') or '').lower()
    od, fd = _domain(org), _domain(frm)
    same = bool(od and fd) and (od == fd or od.endswith('.' + fd) or fd.endswith('.' + od))
    return {'organizer_domain': od, 'mail_domain': fd, 'mismatch': bool(od and fd and not same),
            'no_reply': bool(org and NO_REPLY.match(org))}


def own_addresses():
    return [str(a.get('address') or '').lower() for a in config().get('accounts', {}).values() if isinstance(a, dict) and a.get('address')]


INVITES_DISMISSED = os.path.join(STATE_DIR, 'invites-dismissed.json')
_PENDING = {'at': 0, 'data': None}


def pending_invites(fresh=False, now=None):
    """Invitations in your mail that are still waiting for an answer: a request (not a cancellation) for a meeting that
    hasn't ended, not answered from Axella, not dismissed, and not in any calendar yet. Read on the Mac mini only –
    hidden contacts left out. Two minutes' cache; cleared when you answer, dismiss or change the calendar."""
    import invites
    import calendar_view
    t = now or time.time()
    if not fresh and _PENDING['data'] is not None and t - _PENDING['at'] < 120:
        return _PENDING['data']
    try:
        names = mail_accounts()
    except Exception:
        names = {}
    cands = mailsearch.invite_candidates(names) if names else []
    answered = {str(x['key'])[len('invite:'):].rsplit(':', 1)[0] for x in load_json(SENT_FILE, [])
                if str(x.get('key', '')).startswith('invite:') and x.get('status') != 'failed'}
    dismissed = set(load_json(INVITES_DISMISSED, []))
    own = own_addresses()
    by_uid, cancelled = {}, set()
    for c in cands:
        try:
            addrs = mailsearch.addresses_of(c['path'])
        except Exception:
            addrs = [c.get('from_address')]
        if mail_privacy(addrs)[0] == 'hidden':
            continue
        try:
            ics = invites.ics_from_message(mailsearch._raw(c['path'])) or invites.ics_from_attachments(c['path'])
            ev = invites.parse(ics) if ics else None
        except Exception:
            ev = None
        if not ev:
            continue
        if ev['method'] == 'CANCEL' or ev.get('status') == 'CANCELLED':
            cancelled.add(ev['uid'])
            continue
        if ev['method'] != 'REQUEST':
            continue
        pub = invites.public(ev, own)
        if pub['me'] and pub['me']['partstat'] != 'NEEDS-ACTION':
            continue
        old = by_uid.get(ev['uid'])
        if old and old['_seq'] >= ev.get('sequence', 0):
            continue
        by_uid[ev['uid']] = dict(pub, _seq=ev.get('sequence', 0), account=c['account'], message_id=c['message_id'],
                                 subject=c['subject'], date=c['date'],
                                 from_name=c['from_name'], from_address=c['from_address'])
    now_dt = datetime.datetime.now().astimezone()
    out = []
    for uid, x in by_uid.items():
        if uid in cancelled or uid[:200] in answered or uid in dismissed or not x.get('message_id'):
            continue
        try:
            end = datetime.datetime.fromisoformat(x['end']) if not x['all_day'] else datetime.datetime.fromisoformat(x['end'] + 'T00:00').astimezone()
        except ValueError:
            continue
        if end < now_dt:
            continue
        out.append(x)
    # already in a calendar (accepted somewhere else, or added by hand): not waiting any more
    if out:
        try:
            d0 = min(x['start'][:10] for x in out)
            d1 = (datetime.date.fromisoformat(max(x['start'][:10] for x in out)) + datetime.timedelta(days=1)).isoformat()
            if (datetime.date.fromisoformat(d1) - datetime.date.fromisoformat(d0)).days <= calendar_view.MAX_DAYS:
                evs = calendar_view.events(RUNNER.mcp_file(), config().get('calendars') or [], d0, d1).get('events') or []
                out = [x for x in out if not invite_in_calendar(x, evs)]
        except Exception:
            pass
    for x in out:
        x.pop('_seq', None)
        x.pop('description', None)
        x.pop('raw_start', None)
    out.sort(key=lambda x: x['start'])
    data = {'invites': out[:30], 'checked': len(cands)}
    _PENDING.update(at=t, data=data)
    return data


def _title_key(t):
    return re.sub(r'\s+', ' ', str(t or '')).strip().casefold()


def invite_in_calendar(x, evs):
    """Is this invitation's meeting already in a calendar (accepted somewhere else, or added by hand)? Same title, and
    the same start – for an all-day meeting the same day."""
    k = _title_key(x['summary'])
    for e in evs or []:
        if _title_key(e.get('title')) != k:
            continue
        if x['all_day']:
            if e.get('all_day') and str(e.get('start') or '')[:10] == x['start'][:10]:
                return True
            continue
        try:
            s0 = datetime.datetime.fromisoformat(str(e.get('start')).replace('Z', '+00:00'))
            if abs((s0 - datetime.datetime.fromisoformat(x['start'])).total_seconds()) < 60:
                return True
        except ValueError:
            continue
    return False


def invite_dismiss(p):
    uid = str(p.get('uid') or '')[:300]
    if not uid:
        raise Bad('missing uid')
    with LOCK:
        d = load_json(INVITES_DISMISSED, [])
        if uid not in d:
            d.append(uid)
        with open(INVITES_DISMISSED, 'w', encoding='utf-8') as f:
            json.dump(d[-500:], f)
    _PENDING['data'] = None
    return {'dismissed': uid}


# ---------- commitments: promises and reply debt (feature pack §1a/§1b) – local rules only ----------
import commitments as _commit  # noqa: E402
PROM = _commit.Promises(STATE_DIR)
_COMMIT = {'at': 0, 'debt': [], 'seen': set(), 'error': None}


def _digits(s):
    return re.sub(r'\D', '', str(s or ''))[-8:]


def _people_names():
    """phone tail / e-mail → name from the Contacts cache (no Contacts call here)."""
    out = {}
    try:
        for p in BOOK._load().get('people') or []:
            for e in p.get('emails') or []:
                out[str(e).lower()] = p.get('name')
            for ph in p.get('phones') or []:
                if _digits(ph):
                    out[_digits(ph)] = p.get('name')
    except Exception:
        pass
    return out


def _world_of(account, addr):
    acc = (config().get('accounts') or {}).get(account) or {}
    if acc.get('kind') == 'work' or profile.is_protected(account, addr):
        return 'work'
    try:
        if any(addr.endswith('@' + d) for w in profile.workplaces() for d in w['domains']):
            return 'work'
    except Exception:
        pass
    return 'private'


def _imessage_rows(days):
    """(handle, from_me, epoch, text) from Messages' own database, read-only – your sent and received texts."""
    import sqlite3
    from urllib.parse import quote
    chat = os.path.expanduser('~/Library/Messages/chat.db')
    if not os.access(chat, os.R_OK):
        return []
    db = sqlite3.connect('file:%s?mode=ro' % quote(chat), uri=True, timeout=5)
    try:
        since = time.time() - days * 86400 - 978307200
        q = 'select h.id, m.is_from_me, m.date, m.text, m.attributedBody from message m join handle h on h.ROWID = m.handle_id where m.date > ? order by m.date'
        rows = db.execute(q, (int(since * 1e9),)).fetchall() or db.execute(q, (int(since),)).fetchall()
    finally:
        db.close()
    out = []
    for h, me, date, text, blob in rows:
        ts = (date / 1e9 if date > 1e12 else date) + 978307200
        out.append((h, bool(me), ts, text if text else _commit.attributed_text(blob)))
    return out


def reply_debt_institution(addr):
    """An authority, bank, insurer or municipality (the cleanup keep lists, incl. your own keep-domains file)."""
    import cleanup
    dom = str(addr or '').rsplit('@', 1)[-1].lower()
    return bool(dom and (cleanup.KEEP_DOMAIN.search(dom) or cleanup.local_keep(dom, STATE_DIR)))


def scan_commitments(now=None):
    """Every 15 minutes: promises in what you sent (mail, iMessage, WhatsApp, Signal) and who you owe a reply."""
    now = now or datetime.datetime.now().astimezone()
    own = set(own_addresses())
    names = _people_names()
    try:
        accounts = mail_accounts()
    except Exception:
        accounts = {}
    rows = mailsearch.correspondence(accounts, own, days=120) if accounts else []
    found, outgoing, threads = [], [], {}
    win = time.time() - _commit.WINDOW_DAYS * 86400
    read = 0
    for r in rows:
        if r['dir'] == 'out':
            to = [a for _, a in r['to'] if a and a not in own]
            if not to:
                continue
            lvl = mail_privacy(to)[0]
            for a in to:                                   # reply debt: you wrote to them
                t = threads.setdefault(('mail', a), {'who': a, 'name': names.get(a) or next((c for c, x in r['to'] if x == a and c), a),
                                                       'channel': 'mail', 'last_in': None, 'last_out': None, 'ever_out': False})
                t['ever_out'] = True
                t['last_out'] = max(t['last_out'] or 0, r['date'])
            if lvl or r['date'] < win or r['rowid'] in _COMMIT['seen'] or read >= 150:
                continue
            _COMMIT['seen'].add(r['rowid'])
            read += 1
            text, att = mailsearch.message_text(r)
            at = datetime.datetime.fromtimestamp(r['date']).astimezone()
            person = {'name': names.get(to[0]) or next((c for c, x in r['to'] if x == to[0] and c), '') or to[0], 'address': to[0]}
            outgoing.append({'person': to[0], 'at': at.isoformat(timespec='seconds'), 'text': text, 'attachment': att, 'ref': r.get('mid')})
            # a protected workplace (AXELLA.md rule 4): its words stay in Mail – the card says who and when only
            prot = any(profile.is_protected(r['account'], a) for a in to)
            for f in _commit.find(text, at):
                found.append({'key': _commit.key_of('mail', r.get('mid') or r['rowid'], f['sentence']),
                              'sentence': '' if prot else f['sentence'], 'protected': prot,
                              'text': ('You promised something to %s on %s – open the mail' % (person['name'], at.strftime('%a %d %b').replace(' 0', ' ')))
                              if prot else _commit.summary(f['sentence'], person['name'].split(' ')[0]),
                              'due': None if prot else (f['due'].isoformat() if f['due'] else None),
                              'person': person, 'world': _world_of(r['account'], to[0]),
                              'source': {'kind': 'mail', 'account': r['account'], 'message_id': r.get('mid'), 'subject': '' if prot else r['subject'][:200],
                                         'at': at.isoformat(timespec='seconds')}})
        else:
            a = r['addr']
            if not a or a in own:
                continue
            t = threads.setdefault(('mail', a), {'who': a, 'name': names.get(a) or r['name'] or a, 'channel': 'mail',
                                                 'last_in': None, 'last_out': None, 'ever_out': False})
            if not t['last_in'] or r['date'] > t['last_in']:
                t['last_in'], t['account'], t['mid'], t['direct'], t['_row'] = r['date'], r['account'], r.get('mid'), r.get('direct'), r
                t['subject'] = '' if profile.is_protected(r['account'], a) else r['subject']     # protected: who and when only
    # iMessage / SMS
    try:
        for h, me, ts, text in _imessage_rows(30):
            if PRIV.level('imessage', h) in ('private', 'hidden'):
                continue
            key = _digits(h) or h.lower()
            nm = names.get(key) or names.get(h.lower()) or h
            t = threads.setdefault(('imessage', key), {'who': h, 'name': nm, 'channel': 'imessage', 'last_in': None, 'last_out': None, 'ever_out': False})
            if me:
                t['ever_out'] = True
                t['last_out'] = max(t['last_out'] or 0, ts)
                if ts >= win and text:
                    at = datetime.datetime.fromtimestamp(ts).astimezone()
                    outgoing.append({'person': h, 'at': at.isoformat(timespec='seconds'), 'text': text, 'attachment': False})
                    for f in _commit.find(text, at):
                        found.append({'key': _commit.key_of('imessage', h + str(int(ts)), f['sentence']), 'sentence': f['sentence'],
                                      'text': _commit.summary(f['sentence'], nm.split(' ')[0]), 'due': f['due'].isoformat() if f['due'] else None,
                                      'person': {'name': nm, 'address': h}, 'world': 'private',
                                      'source': {'kind': 'imessage', 'chat': h, 'at': at.isoformat(timespec='seconds')}})
            elif ts >= (t['last_in'] or 0):
                t['last_in'], t['_text'] = ts, text or ''
    except Exception as e:
        _COMMIT['error'] = 'Messages: %s' % str(e)[:120]
    # WhatsApp and Signal: the exports already leave private contacts out (48 hours of messages)
    for kind, fname in (('whatsapp', WA_FILE), ('signal', os.path.join(STATE_DIR, 'signal.json'))):
        for c in (load_json(fname, {}) or {}).get('chats') or []:
            who = c.get('phone') or c.get('jid') or c.get('name') or ''
            if not who or PRIV.level(kind, who) in ('private', 'hidden'):
                continue
            nm = c.get('name') or who
            for m in c.get('messages') or []:
                if not m.get('from_me') or not m.get('text'):
                    continue
                try:
                    at = datetime.datetime.fromisoformat(str(m['at']))
                except (KeyError, ValueError):
                    continue
                outgoing.append({'person': who, 'at': at.isoformat(timespec='seconds'), 'text': m['text'], 'attachment': False})
                for f in _commit.find(m['text'], at):
                    found.append({'key': _commit.key_of(kind, who + str(m.get('at')), f['sentence']), 'sentence': f['sentence'],
                                  'text': _commit.summary(f['sentence'], nm.split(' ')[0]), 'due': f['due'].isoformat() if f['due'] else None,
                                  'person': {'name': nm, 'address': who}, 'world': 'private', 'source': {'kind': kind, 'chat': who, 'at': at.isoformat(timespec='seconds')}})
    PROM.merge(found, now)
    PROM.mark_fulfilled(outgoing)
    # reply debt
    th = []
    for (ch, k), t in threads.items():
        if not t['last_in']:
            continue
        who = t['who']
        private = (mail_privacy([who])[0] if ch == 'mail' else PRIV.level('imessage', who)) in ('private', 'hidden')
        th.append(dict(t, last_in=datetime.datetime.fromtimestamp(t['last_in']).astimezone(),
                       last_out=datetime.datetime.fromtimestamp(t['last_out']).astimezone() if t['last_out'] else None,
                       automated=bool(ch == 'mail' and NO_REPLY.match(who)), private=private,
                       institution=bool(ch == 'mail' and reply_debt_institution(who)),
                       world=_world_of(t.get('account'), who) if ch == 'mail' else 'private'))
    # People / keep in touch: the last time you and each address or number were in touch, any direction (times only)
    import people as _pl
    last = {}
    for (ch, k), t in threads.items():
        ts, kk = max(t['last_in'] or 0, t['last_out'] or 0), _pl._key(t['who'])
        if ts and kk:
            iso = datetime.datetime.fromtimestamp(ts).astimezone().isoformat(timespec='seconds')
            if iso > last.setdefault(kk, {}).get(ch, ''):
                last[kk][ch] = iso
    for kind, fname in (('whatsapp', WA_FILE), ('signal', os.path.join(STATE_DIR, 'signal.json'))):
        for c in (load_json(fname, {}) or {}).get('chats') or []:
            kk = _pl._key(c.get('phone') or c.get('jid') or '')
            ats = [str(m.get('at') or '') for m in c.get('messages') or [] if isinstance(m, dict)]
            if kk and ats and max(ats) > last.setdefault(kk, {}).get(kind, ''):
                last[kk][kind] = max(ats)
    _COMMIT['last'] = last
    cfg = config().get('reply_debt') or {}
    args = (PROM.never(), now.date(), int(cfg.get('work_days') or 3), int(cfg.get('private_days') or 5), int(cfg.get('max_days') or 21),
            PROM.done())
    debt = _commit.reply_debt(th, *args)
    # only real asks: their last message isn't just a "thanks / tak" – read here for the few that are left, never stored
    thx = _COMMIT.setdefault('thanks', {})
    for x in debt[:60]:
        k = (x['channel'], x['who'], x['last_in'].isoformat())
        if k not in thx:
            try:
                thx[k] = _commit.just_thanks(x.get('_text') if x['channel'] != 'mail' else mailsearch.message_text(x['_row'])[0])
            except Exception:
                thx[k] = False
        x['thanks'] = thx[k]
    if len(thx) > 2000:
        thx.clear()
    debt = _commit.reply_debt([x for x in debt if not x.get('thanks')], *args)
    _COMMIT.update(at=time.time(), debt=[{k: x.get(k) for k in ('who', 'name', 'channel', 'world', 'days', 'subject', 'account', 'mid')}
                                         | {'last_in': x['last_in'].isoformat(timespec='minutes')} for x in debt[:30]], error=None)
    return {'found': len(found), 'debt': len(debt)}


def _commit_loop():
    time.sleep(60)
    while True:
        try:
            scan_commitments()
        except Exception as e:
            _COMMIT['error'] = str(e)[:200]
            sys.stderr.write('commitments: %s\n' % str(e)[:200])
        time.sleep(900)


def commitments_view():
    pr = PROM.load()
    sug = sorted(PROM.suggestions(), key=lambda x: (x.get('due') or '9999', x['created']))
    return {'promises': sug[:30], 'looks_done': [x for x in pr['items'] if x['status'] == 'added' and x.get('looks_done')][:20],
            'reply_debt': _COMMIT['debt'], 'scanned': pr.get('scanned'), 'error': _COMMIT['error']}


def promise_action(action, p):
    pid = str(p.get('id') or '')
    try:
        if action == 'promise_add':
            x = next((y for y in PROM.load()['items'] if y['id'] == pid), None)
            if not x or x['status'] not in ('suggested',):
                raise Bad('this promise is not waiting any more')
            text = str(p.get('text') or (('%s: follow up on your promise' % x['person']['name']) if x.get('protected') else x['text']))[:500].strip()
            due = p.get('due') if 'due' in p else x.get('due')
            src = x['source']
            where = 'mail' if src['kind'] == 'mail' else {'imessage': 'Messages', 'whatsapp': 'WhatsApp', 'signal': 'Signal'}.get(src['kind'], src['kind'])
            notes = ('Promised to %s (%s, %s) – protected workplace: the words stay in Mail' % (x['person']['name'], where, src['at'][:10])
                     if x.get('protected') or not x.get('sentence') else 'Promised to %s (%s, %s): "%s"' % (x['person']['name'], where, src['at'][:10], x['sentence']))
            tid = task_action('task_add', {'text': text, 'due': due or None, 'source': 'promise', 'notes': notes,
                                           'ctx': x.get('world') if x.get('world') in ('work', 'private') else None,
                                           'ref': {'kind': 'promise', 'promise_id': pid, 'person': x['person'], 'source': src}})
            PROM.set(pid, status='added', task_id=tid)
            p['title'] = text[:80]
            return {'task_id': tid}
        if action == 'promise_dismiss':
            PROM.set(pid, status='dismissed')
            return {'id': pid}
        if action == 'promise_done':                     # "Looks done – tick it off": the To do is ticked too
            x = PROM.set(pid, status='done', looks_done=None)
            if x.get('task_id'):
                try:
                    task_action('task_done', {'id': x['task_id']})
                except Bad:
                    pass
            return {'id': pid}
        if action == 'promise_not_done':
            PROM.set(pid, looks_done=None, looks_done_ignored=True)
            return {'id': pid}
        if action == 'replydebt_done':
            # done / nothing to answer for this one – it comes back only when they write again
            who = str(p.get('who') or '').strip().lower()
            if not who:
                raise Bad('missing who')
            on = bool(p.get('on', True))
            cur = next((x for x in _COMMIT['debt'] if str(x.get('who') or '').lower() == who), None)
            last = str(p.get('last_in') or (cur or {}).get('last_in') or '')
            if on and not last:
                raise Bad('missing last_in')
            PROM.set_done(who, last, on)
            if on:
                _COMMIT['debt'] = [x for x in _COMMIT['debt'] if str(x.get('who') or '').lower() != who]
            else:
                _COMMIT['at'] = 0                           # undo: the next scan brings it back
            return {'who': who}
        if action == 'replydebt_never':
            who = str(p.get('who') or '').strip().lower()
            if not who:
                raise Bad('missing who')
            PROM.set_never(who, bool(p.get('on', True)))
            _COMMIT['debt'] = [x for x in _COMMIT['debt'] if str(x.get('who') or '').lower() != who] if p.get('on', True) else _COMMIT['debt']
            return {'who': who}
    except ValueError as e:
        raise Bad(str(e))
    raise Bad('unknown action')


def schedule_action(action, p):
    """Send later: the tap on a time is the approval; the mail goes through the normal send path at that time."""
    try:
        if action == 'schedule_send':
            a, pl = str(p.get('action') or ''), p.get('payload') if isinstance(p.get('payload'), dict) else {}
            if a not in ('mail_send', 'reply_send'):
                raise Bad('only mails and replies can be sent later')
            if pl.get('account') not in config().get('accounts', {}):
                raise Bad('account not allowed')
            if a == 'mail_send':
                to = str(pl.get('to') or '').strip()
                if '@' not in to or any(c in to for c in ' <>",;\n') or NO_REPLY.match(to):
                    raise Bad('one real e-mail address on To')
                if not str(pl.get('subject') or '').strip():
                    raise Bad('add a subject')
            elif not pl.get('message_id'):
                raise Bad('the mail to answer is missing')
            else:
                recipients(pl)                        # the To / Cc / Bcc lists, checked now – not only at send time
            p['title'] = 'Send later: ' + str(pl.get('title') or pl.get('subject') or '')[:60]
            return SCHED_SEND.add(a, pl, p.get('at'), p.get('_login', ''))
        if action == 'schedule_update':
            return SCHED_SEND.update(str(p.get('id') or ''), {k: p[k] for k in ('at', 'text', 'subject') if k in p})
        if action == 'schedule_cancel':
            return SCHED_SEND.cancel(str(p.get('id') or ''))
        return SCHED_SEND.send_now(str(p.get('id') or ''), checked=bool(p.get('checked_sent')))
    except _scheduled_mod.Bad as e:
        raise Bad(str(e))


UNSURE_RE = re.compile(r"didn.t confirm|did not confirm|did not answer|may have sent|did not finish|check Sent", re.I)


def send_id_forget(sid):
    """Drop a send_id's record – only for a try that definitely sent nothing (refused), or one the owner checked in Sent."""
    with LOCK:
        d = send_ids_load()
        if d.pop(sid, None) is not None:
            send_ids_save(d)


def scheduled_send_via_queue(action, payload, login, checked=False):
    """One due mail, through the same send_id guard and job queue as a tap (one Mail conversation at a time). The mail
    keeps its send_id for every try: one that went is never sent again. Raises scheduled.Unknown when Mail may have sent."""
    sid = payload.get('send_id')
    for attempt in range(2):
        try:
            repeat, _ = send_id_accept(action, payload, login or 'scheduled')
        except Bad as e:
            msg = str(e)
            if msg.startswith('not sent:') and attempt == 0:      # the last try was refused before anything went: try again
                send_id_forget(sid)
                continue
            if 'restarted before it finished' in msg:
                if checked and attempt == 0:                      # the owner checked Sent: it isn't there
                    send_id_forget(sid)
                    continue
                raise _scheduled_mod.Unknown(msg)
            raise
        if repeat is not None and repeat.get('job') and attempt == 0:
            j = JOBS.get(repeat['job']) or {}
            if j.get('state') == 'error' and not UNSURE_RE.search(j.get('error') or ''):
                send_id_forget(sid)                               # that try was refused: nothing went
                continue
            if j.get('state') == 'error':
                if checked:
                    send_id_forget(sid)
                    continue
                raise _scheduled_mod.Unknown(j.get('error') or 'check Sent in Mail')
        break
    if repeat is not None:
        if repeat.get('already_sent'):
            return {'status': 'sent', 'repeat': True}
        j = JOBS.get(repeat.get('job') or '') or {}
        if j.get('state') == 'ok':
            return {'status': 'sent', 'repeat': True}
        jid = repeat.get('job')                                   # still running from before: follow that one
    else:
        jid = queue_job(action, payload, login or 'scheduled')
        send_id_update(sid, job=jid)
    for _ in range(600):
        j = JOBS.get(jid) or {}
        if j.get('state') == 'ok':
            return j.get('result')
        if j.get('state') == 'error':
            err = j.get('error') or 'failed'
            if UNSURE_RE.search(err):
                send_id_update(sid, state='unknown', error=err[:200])   # not "error": a retry must ask you to check Sent
                raise _scheduled_mod.Unknown(err)
            raise Bad(err)
        time.sleep(1)
    send_id_update(sid, state='unknown')
    raise _scheduled_mod.Unknown('Mail did not finish in 10 minutes – check Sent in Mail')


def _scheduled_loop():
    """Every 30 s: send what is due. After the Mac mini was off, it sends what it missed and notes how late."""
    SCHED_SEND.recover()
    while True:
        try:
            def note(x, status, err, late):
                t = x.get('title') or ''
                log_auto('schedule_sent', ('%s%s' % (t, ' (%d min late)' % late if late >= 2 else ''))[:80],
                         'ok' if status == 'sent' else '%s: %s' % (status, err or ''))
            def missed(x):
                push_send({'title': 'Not sent – it was late', 'body': 'Send later: "%s" missed its time. Send it now or pick a new time.'
                           % (x.get('title') or 'your mail')[:60] if not PRIV.load().get('discreet_push') else
                           'A mail you scheduled missed its time – send now or reschedule?', 'url': '/axella/', 'tag': 'axella-scheduled'})
                log_auto('schedule_sent', (x.get('title') or '')[:80], 'missed: more than an hour late – not sent')
            SCHED_SEND.run_due(lambda a, pl, ck: scheduled_send_via_queue(a, pl, '', ck), log=note, notify=missed)
        except Exception as e:
            sys.stderr.write('scheduled sends: %s\n' % str(e)[:200])
        time.sleep(30)


def invite_view(account, mid):
    """GET invite: what the Accept sheet shows – the meeting, who asked, your answer so far, where it would go."""
    import invites
    ev = invite_load(account, mid)
    out = invites.public(ev, own_addresses())
    acc = config().get('accounts', {}).get(account) or {}
    cals = profile.calendars()
    kind = acc.get('kind') or 'private'
    out['from_address'] = (out['me'] or {}).get('email') or acc.get('address')
    out['calendars'] = [{'name': c['name'], 'label': c['label'], 'kind': c['kind']} for c in cals]
    out['calendar'] = next((c['name'] for c in cals if c['kind'] == kind), cals[0]['name'] if cals else None)
    out['in_calendar'] = False
    out['check'] = invite_check(ev)
    try:
        import calendar_view
        day = out['start'][:10]
        nxt = (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat()
        evs = calendar_view.events(RUNNER.mcp_file(), config().get('calendars') or [], day, nxt).get('events') or []
        out['in_calendar'] = invite_in_calendar(out, evs)
    except Exception:
        pass
    return out


def invite_respond(p):
    """Accept / Maybe / Decline: the standard reply (iCalendar METHOD:REPLY) to the organizer through Mail – only after
    the owner's second tap and the undo time – and, on Accept or Maybe, the meeting in the chosen calendar."""
    import invites
    import tempfile
    if p.get('confirm') != 'send':
        raise Bad('send needs your confirmation')
    require(p, 'account', 'message_id', 'response')
    resp = str(p['response'])
    if resp not in invites.PARTSTAT:
        raise Bad('accepted, tentative or declined')
    ev = invite_load(p['account'], p['message_id'])
    if ev['method'] == 'CANCEL' or ev.get('status') == 'CANCELLED':
        raise Bad('this meeting was cancelled – there is nothing to answer')
    org = (ev.get('organizer') or {}).get('email') or ''
    if '@' not in org or any(c in org for c in ' <>",;\n'):
        raise Bad('the invite has no organizer address to answer')
    if NO_REPLY.match(org.lower()):
        raise Bad('the organizer is a no-reply address – an answer would go nowhere; answer in Calendar or on the organizer\'s page')
    acc = config()['accounts'][p['account']]
    me = invites.me_in(ev, own_addresses())
    me_email = (me or {}).get('email') or acc.get('address') or ''
    if not me_email:
        raise Bad('no address for this account in actions-config.json')
    owner = profile.owner()
    cal = p.get('calendar') if resp != 'declined' else None
    if cal and cal not in profile.calendar_names():
        raise Bad('calendar not allowed')
    now = time.time()
    key = 'invite:' + ev['uid'][:200] + ':' + resp
    with LOCK:
        sent = load_json(SENT_FILE, [])
        if len([x for x in sent if now - _sent_ts(x) < 3600]) >= SEND_MAX:
            raise Bad(f'more than {SEND_MAX} mails in an hour – wait a little, or answer in Calendar')
        last = next((x for x in reversed(sent) if x.get('key') == key and now - _sent_ts(x) < 600 and x.get('status') != 'failed'), None)
        if last and not p.get('force'):
            raise Bad('this answer was sent a few minutes ago already')
    tmp = tempfile.mkdtemp(prefix='ax-invite-', dir=OUTBOX_DIR if os.path.isdir(OUTBOX_DIR) else None)
    os.chmod(tmp, 0o700)
    path = os.path.join(tmp, 'invite.ics')
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(invites.reply_ics(ev, me_email, owner.get('name') or '', resp))
    status = 'unknown'
    err = None
    try:
        res = osa(SEND_NEW_SCRIPT, p['account'], org, invites.reply_subject(ev, resp),
                  invites.reply_text(ev, owner.get('name') or '', resp), me_email, path, timeout=150)
        status = 'sent' if res == 'sent' else 'unknown'
    except RuntimeError as e:
        if 'did not answer' not in str(e):       # Mail refused before sending: nothing went out
            status, err = 'failed', e
    finally:
        with LOCK:
            sent = load_json(SENT_FILE, [])
            sent.append({'at': now_iso(), 'ts': time.time(), 'status': status, 'key': key, 'action': 'invite_respond',
                         'account': p['account'], 'to': org, 'reply_to': p['message_id'],
                         'subject': invites.reply_subject(ev, resp)[:200], 'item_id': p.get('item_id'), 'attachments': ['invite.ics']})
            with open(SENT_FILE, 'w', encoding='utf-8') as f:
                json.dump(sent[-1000:], f, ensure_ascii=False, indent=1)
        import shutil as _sh
        _sh.rmtree(tmp, ignore_errors=True)
    if err is not None:
        raise Bad('Mail could not send the answer – nothing was sent (%s)' % str(err)[-160:])
    if status != 'sent':
        raise Bad('Mail did not confirm sending – check Sent in Mail before trying again')
    added = None
    if cal:
        pub = invites.public(ev, own_addresses())
        if ev.get('all_day'):
            added = 'all-day – add it in Calendar'
        elif p.get('in_calendar'):
            added = 'already in the calendar'
        else:
            notes = 'Accepted in Axella · invitation from %s' % (ev['organizer'].get('name') or org)
            if pub['url']:
                notes += '\n' + pub['url']
            if ev.get('description'):
                notes += '\n\n' + ev['description'][:2000]
            try:
                osa(EVENT_SCRIPT, cal, ev['summary'][:300], ev.get('location') or '', notes, *parts(pub['start']), *parts(pub['end']))
                added = cal
                import calendar_view
                calendar_view.invalidate()
            except Exception as e:
                added = 'not added: %s' % str(e)[:120]
    if p.get('item_id'):
        set_state(p['item_id'], {'status': 'done', 'at': now_iso(), 'title': p.get('title', ''), 'how': 'invite:' + resp})
    # the digest's calendar note about the same meeting ("… not in the calendar") is handled too
    handled = []
    try:
        t0 = datetime.datetime.fromisoformat(invites.public(ev, [])['start'])
        for it in _latest_digest_items('cal'):
            e = it.get('event') if isinstance(it.get('event'), dict) else {}
            try:
                same = abs((datetime.datetime.fromisoformat(str(e.get('start'))).astimezone() - t0.astimezone()).total_seconds()) < 60
            except (TypeError, ValueError):
                same = False
            if it.get('id') and it.get('id') != p.get('item_id') and same:
                set_state(it['id'], {'status': 'done', 'at': now_iso(), 'title': ev['summary'][:80], 'how': 'invite:' + resp})
                handled.append(it['id'])
    except Exception:
        pass
    return {'status': 'sent', 'to': org, 'response': resp, 'calendar': added, 'handled': handled}


STARTED_AT = time.time()


def plural(n, one, many=None):
    """'1 chat', '4 chats' – never 'chat(s)'."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 0
    return '%d %s' % (n, one if n == 1 else (many or one + 's'))


DIGEST_TASKS = ('digest-', 'week-ahead', 'on-demand', 'return-briefing')


def latest_digest(runs):
    """The newest digest run, whatever order the list is in (the ledger is oldest-first, the overview newest-first)."""
    ds = [r for r in runs or [] if str(r.get('task', '')).startswith(DIGEST_TASKS) and r.get('started')]
    return max(ds, key=lambda r: str(r.get('started'))) if ds else None


def overdue_digests(today, now, grace_min=45):
    """Today's scheduled digest slots that are past (plus a grace period) and still haven't run."""
    out = []
    for t in today or []:
        if not str(t.get('task', '')).startswith(DIGEST_TASKS) or t.get('status') not in ('due', 'planned'):
            continue
        try:
            h, m = (int(x) for x in str(t.get('time')).split(':'))
        except ValueError:
            continue
        if now.hour * 60 + now.minute >= h * 60 + m + grace_min:
            out.append(t)
    return out


def system_status():
    """Settings → System status: is every part of Axella running? Only states, times and counts – no content.
    state: ok · warn (works, but look) · down (not working) · off (not set up) · unknown."""
    import shutil as _sh
    now = time.time()
    out = []

    def add(group, cid, name, state, detail, fix=None, at=None):
        out.append({'group': group, 'id': cid, 'name': name, 'state': state, 'detail': detail, 'fix': fix, 'at': at})

    def age(ts):
        return None if ts is None else max(0, now - ts)

    def iso_ts(v):
        try:
            return datetime.datetime.fromisoformat(str(v).replace('Z', '+00:00')).timestamp()
        except (TypeError, ValueError):
            return None

    def ago(sec):
        if sec is None:
            return 'never'
        return 'just now' if sec < 90 else '%d min ago' % (sec // 60) if sec < 5400 else '%d h ago' % (sec // 3600) if sec < 172800 else '%d days ago' % (sec // 86400)

    # --- the Mac mini itself
    up = now - STARTED_AT
    add('Mac mini', 'actions', 'Axella service', 'ok', 'Running for %s' % (ago(up).replace(' ago', '') if up >= 90 else 'a minute'),
        at=datetime.datetime.fromtimestamp(STARTED_AT).astimezone().isoformat(timespec='seconds'))
    w = load_json(os.path.join(STATE_DIR, 'watchdog.json'), None)
    if not w:
        add('Mac mini', 'watchdog', 'Watchdog', 'off', 'Not installed – no push if Axella stops, and no reason shown on the dashboard',
            'Run setup/install-daemons.sh (SETUP.md, section 6)')
    elif (age(iso_ts(w.get('at'))) or 0) > 180:
        add('Mac mini', 'watchdog', 'Watchdog', 'down', 'Last check %s' % ago(age(iso_ts(w.get('at')))), 'sudo launchctl kickstart -k system/<label>.watchdog', w.get('at'))
    else:
        add('Mac mini', 'watchdog', 'Watchdog', 'ok', 'Checks every minute; pushes when Axella pauses', at=w.get('at'))
    add('Mac mini', 'session', 'Your login session', 'ok' if (w or {}).get('session') is not False else 'down',
        'Logged in – Mail, Messages and the digests can run' if (w or {}).get('session') is not False else 'Not logged in',
        'Log in on the Mac mini (Screen Sharing → Log in as yourself)')
    def _runs_www(pth):
        try:
            with open(pth, 'rb') as f:
                return b'www-server.py' in f.read(20000)
        except OSError:
            return False
    daemon = any(_runs_www(x) for x in glob.glob('/Library/LaunchDaemons/*.plist'))
    add('Mac mini', 'web', 'Web server', 'ok' if daemon else 'warn',
        'Runs without your login – the page always opens' if daemon else 'Runs in your login session – the page shows 502 when you are logged out',
        None if daemon else 'Run setup/install-daemons.sh (SETUP.md, section 6)')
    try:
        bst, bdet = BACKUP_AUTO.health()
        add('Mac mini', 'backup', 'Backup', bst, bdet, None if bst == 'ok' else 'Settings → System → Backup')
    except Exception:
        pass
    try:
        du = _sh.disk_usage(os.path.expanduser('~'))
        free = du.free / 1e9
        add('Mac mini', 'disk', 'Disk space', 'ok' if free > 20 else 'warn' if free > 5 else 'down', '%.0f GB free' % free,
            None if free > 20 else 'Free some space – Mail keeps a full copy of every mailbox')
    except OSError:
        pass

    # --- Claude runs
    doc = load_json(os.path.join(STATE_DIR, 'doctor.json'), {})
    if not doc.get('claude'):
        add('Claude', 'claude', 'Claude Code', 'down', 'The claude command was not found', 'Install Claude Code and sign in (SETUP §9)')
    elif doc.get('api_key_set'):
        add('Claude', 'claude', 'Claude Code', 'warn', 'ANTHROPIC_API_KEY is set – runs would bill the API, not your subscription', 'Remove the key from the service environment')
    else:
        add('Claude', 'claude', 'Claude Code', 'ok', str(doc.get('claude_version') or 'found')[:60])
    add('Claude', 'macuse', 'Macuse (Mail, Calendar, Contacts, Messages)', 'ok' if doc.get('mcp_file') else 'down',
        'Connected for each run' if doc.get('mcp_file') else 'state/mcp.json missing', None if doc.get('mcp_file') else 'Runs → Re-check setup')
    try:
        ov = RUNNER.overview()
        cfg = ov.get('config') or {}
        runs = ov.get('runs') or []
        last = latest_digest(runs)
        late = overdue_digests(ov.get('today') or [], datetime.datetime.now())
        today = datetime.date.today().isoformat()
        failed = [r for r in runs if r.get('status') == 'failed' and str(r.get('started', ''))[:10] == today]
        if not cfg.get('enabled'):
            add('Claude', 'schedule', 'Schedule', 'off', 'The Mac mini does not run the schedule', 'Settings → Schedule: "Mac mini runs the schedule"')
        else:
            st = SCHED.status()
            paused = not st.get('digests')
            cur = ov.get('current')
            detail = ('Running now: %s' % cur.get('label')) if cur else ('Paused – %s' % st.get('reason')) if paused else 'On'
            if last:
                detail += ' · last digest %s (%s)' % (ago(age(iso_ts(last.get('ended') or last.get('started')))), last.get('status'))
            if late and not cur and not paused:
                detail += ' · the %s digest hasn\'t run' % late[-1]['time']
            add('Claude', 'schedule', 'Schedule',
                'warn' if failed or (last and last.get('status') == 'failed') or (late and not cur and not paused) else 'ok', detail,
                ('%s failed today – see Runs and logs' % plural(len(failed), 'run')) if failed
                else ('Overdue – see Runs and logs, or Run now there') if late and not cur and not paused else None,
                last and last.get('ended'))
    except Exception as e:
        add('Claude', 'schedule', 'Schedule', 'unknown', str(e)[:120])

    # --- sources
    if PRIV.broken():
        add('Sources', 'privacy', 'Privacy settings', 'down',
            "state/privacy.json can't be read – everyone is treated as private and WhatsApp, Signal and the Private card "
            "pause until it is fixed", 'Fix the file (a typo, or its owner/permissions after a restore) or restore it from a backup')
    else:
        add('Sources', 'privacy', 'Privacy settings', 'ok', 'Readable')
    try:
        mail_up = subprocess.run(['/usr/bin/pgrep', '-x', 'Mail'], capture_output=True, timeout=5).returncode == 0
    except Exception:
        mail_up = None
    add('Sources', 'mail', 'Apple Mail', 'ok' if mail_up else 'down' if mail_up is False else 'unknown',
        'Running' if mail_up else 'Not running – Axella can\'t file, send or save drafts', None if mail_up else 'Open Mail on the Mac mini')
    chat = os.path.expanduser('~/Library/Messages/chat.db')
    if os.path.exists(chat):
        add('Sources', 'imessage', 'Messages (iMessage/SMS)', 'ok' if os.access(chat, os.R_OK) else 'down',
            'Readable' if os.access(chat, os.R_OK) else 'No access to the Messages database', None if os.access(chat, os.R_OK) else 'Full Disk Access for Python (SETUP §3)')
    wa = load_json(WA_FILE, None)
    if wa is None:
        add('Sources', 'whatsapp', 'WhatsApp', 'off', 'Not set up')
    else:
        a = age(iso_ts(wa.get('generated')))
        add('Sources', 'whatsapp', 'WhatsApp', 'ok' if wa.get('ok') and (a or 0) < 600 else 'down',
            ('Updated %s · %s' % (ago(a), plural(len(wa.get('chats') or []), 'chat'))) if wa.get('ok') else (str(wa.get('error') or 'not readable')[:120]),
            None if wa.get('ok') else 'WhatsApp Desktop logged in; Full Disk Access for Python', wa.get('generated'))
    try:
        import signal_export
        sg = signal_export.status()
        if not sg.get('installed'):
            add('Sources', 'signal', 'Signal', 'off', 'Not set up (optional, SETUP §16)')
        elif not sg.get('linked'):
            add('Sources', 'signal', 'Signal', 'down', 'Not linked', 'Signal on the phone → Linked devices (SETUP §16)')
        else:
            a = age(iso_ts(sg.get('generated')))
            add('Sources', 'signal', 'Signal', 'warn' if sg.get('error') else 'ok' if (a or 0) < 600 else 'down',
                str(sg.get('error'))[:120] if sg.get('error') else 'Checked %s · %s' % (ago(a), plural(sg.get('chats') or 0, 'chat')), at=sg.get('generated'))
    except Exception as e:
        add('Sources', 'signal', 'Signal', 'unknown', str(e)[:120])
    vc = (config().get('voice') or {})
    if not vc.get('url'):
        add('Sources', 'calls', 'Call agent', 'off', 'Not set up (optional, SETUP §15)')
    else:
        cc = load_json(os.path.join(BASE, 'calls', 'config.json'), {})
        a = age(iso_ts(cc.get('last_sync')))
        add('Sources', 'calls', 'Call agent', 'down' if cc.get('last_error') else 'ok' if (a or 1e9) < 900 else 'warn',
            str(cc.get('last_error'))[:120] if cc.get('last_error') else 'Last check %s' % ago(a), at=cc.get('last_sync'))

    # --- getting things to you
    try:
        import pywebpush  # noqa: F401
        lib = True
    except ImportError:
        lib = False
    subs = load_json(PUSH_SUBS_FILE, [])
    add('Delivery', 'push', 'Notifications', 'ok' if lib and subs else 'warn' if lib else 'down',
        ('%s subscribed' % plural(len(subs), 'device')) if lib else 'pywebpush not installed',
        None if lib and subs else 'Turn on notifications in the menu' if lib else 'pip install --user pywebpush (SETUP §4)')
    fb = None
    try:
        slots = RUNNER._load_runs().get('slots') or {}
        keys = sorted(k for k in slots if k.startswith('feedback-pull@'))
        fb = slots[keys[-1]] if keys else None
    except Exception:
        pass
    if fb and not str(fb).startswith(('ok', 'running', 'queued', 'skipped')):
        # the slot says missed/failed, but the pull's own record may show a later good run (a lost write-back, or the
        # next night's pull): trust a pull in the last 26 hours
        try:
            st = load_json(os.path.join(STATE_DIR, 'feedback-pull.json'), {})
            ran = datetime.datetime.fromisoformat(str(st.get('last_run'))).astimezone() if st.get('last_run') else None
            if ran and (datetime.datetime.now().astimezone() - ran).total_seconds() < 26 * 3600:
                fb = 'ok: %s, %s new' % (ran.strftime('%a %H:%M'), st.get('last_new', 0))
        except (ValueError, TypeError):
            pass
    if fb and not str(fb).startswith('skipped: no export token'):
        add('Delivery', 'feedback', 'axella.dev feedback', 'ok' if str(fb).startswith(('ok', 'running', 'queued')) else 'warn', 'Last pull: %s' % str(fb)[:80])
    rank = {'down': 0, 'warn': 1, 'unknown': 2, 'off': 3, 'ok': 4}
    worst = min((rank[c['state']] for c in out if c['state'] != 'off'), default=4)
    # one plain sentence first (health.py): worst first, since when, what it affects – rules only
    sentence = None
    try:
        import health as _health
        since = _health.Since(STATE_DIR).track(out, now)
        sentence = _health.sentence(out, w if (w or {}).get('session') is False else None, since, now, _next_digest_label())
    except Exception as e:
        sys.stderr.write('status sentence: %s\n' % str(e)[:200])
    return {'at': now_iso(), 'overall': {0: 'down', 1: 'warn', 2: 'warn', 4: 'ok'}.get(worst, 'ok'), 'components': out, 'sentence': sentence}


def _next_digest_label(now=None):
    """'16:30' (today) or 'Mon 07:30' – the next scheduled digest, for "the next digest (…) will miss WhatsApp"."""
    now = now or datetime.datetime.now()
    try:
        cfg = RUNNER.load()
        if not cfg.get('enabled'):
            return None
        for add in range(0, 8):
            day = (now + datetime.timedelta(days=add)).date()
            for sid, task, hm, label in RUNNER.slots_for(day, cfg):
                if task == 'p0-check':
                    continue
                at = datetime.datetime.combine(day, datetime.time(int(hm[:2]), int(hm[3:5])))
                if at > now:
                    return hm if add == 0 else at.strftime('%a ') + hm
    except Exception:
        return None
    return None


TALLY_FILE = os.path.join(STATE_DIR, 'outbound-tally.json')   # {day: {kind: n}} – counts only, 40 days


def tally(kind, n=1):
    """Count something that leaves the Mac mini and isn't recorded elsewhere (picture-proxy fetches)."""
    day = datetime.date.today().isoformat()
    with LOCK:
        d = load_json(TALLY_FILE, {})
        if not isinstance(d, dict):
            d = {}
        d.setdefault(day, {})[kind] = d.get(day, {}).get(kind, 0) + n
        keep = sorted(d)[-40:]
        d = {k: d[k] for k in keep}
        with open(TALLY_FILE + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(d, f)
        os.replace(TALLY_FILE + '.tmp', TALLY_FILE)


def tally_sum(kind, since_day):
    d = load_json(TALLY_FILE, {})
    return sum((v or {}).get(kind, 0) for k, v in (d.items() if isinstance(d, dict) else []) if k >= since_day)


def outbound(days=7):
    """Settings → Privacy → What leaves my home: everything that went out of the Mac mini in the last days, from the
    records Axella keeps anyway (run ledger, briefs, the action log, the call agent's status). Counts, times, search
    queries and web addresses – never message content."""
    cutoff = datetime.datetime.now().astimezone() - datetime.timedelta(days=days)
    since = cutoff.isoformat(timespec='seconds')
    # Claude runs: what they read goes to Anthropic to be answered
    import scheduler as _sch
    ledger = RUNNER._load_runs()['runs']
    runs = [r for r in ledger if (r.get('started') or '') >= since and r.get('status') not in ('skipped',)]
    history_from = ledger[0].get('started') if ledger else None
    by = {}
    for r in runs:
        # one row per kind of run, by its task's own label – never the run's label, which may name a recipient
        task = str(r.get('task') or '')
        k = 'Briefings' if task.startswith('brief') else (_sch.TASKS.get(task) or {}).get('label') or 'Other runs'
        e = by.setdefault(k, {'count': 0, 'failed': 0})
        e['count'] += 1
        e['failed'] += r.get('status') == 'failed'
    # the action log: what you tapped that sends something, and the small assistant calls
    acts = {}
    try:
        with open(LOG_FILE, encoding='utf-8') as f:
            f.seek(max(0, os.path.getsize(LOG_FILE) - 4 * 1024 * 1024))
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if (e.get('at') or '') >= since and str(e.get('result') or '').split(':')[0] == 'ok':
                    acts[e.get('action')] = acts.get(e.get('action'), 0) + 1
    except OSError:
        pass
    assist = acts.get('compose_assist', 0) + acts.get('task_suggest', 0)
    claude = sorted(({'what': k, **v} for k, v in by.items()), key=lambda x: -x['count'])
    if assist:
        claude.append({'what': 'Writing assistant and task suggestions', 'count': assist})
    # briefings: the searches and pages, from the runs' actual tool calls
    briefs = []
    for br in BRIEF.recent(since, limit=200):
        o = br.get('outbound') or {}
        briefs.append({'name': br.get('name'), 'at': br.get('at'), 'queries': o.get('queries') or [], 'urls': o.get('urls') or [],
                       'fetched': o.get('fetched') or 0})
    # the call agent (Vercel)
    vs = load_json(os.path.join(STATE_DIR, 'voice-status.json'), {})
    voice = None
    if (config().get('voice') or {}).get('url'):
        n_calls = 0
        for pth in glob.glob(os.path.join(BASE, 'calls', 'call-*.json')):
            try:
                n_calls += os.path.getmtime(pth) >= cutoff.timestamp()
            except OSError:
                pass
        voice = {'contacts_sent': vs.get('contacts_sent'), 'config_pushed': vs.get('config_pushed'), 'lookup': vs.get('lookup'),
                 'private': vs.get('private'),
                 'calls_fetched': n_calls, 'last_sync': vs.get('last_sync')}
    # reports sent to the developer
    reports = [r for r in REPORTS.list() if (r.get('sent_at') or '') >= since]
    pics = load_json(PICS_FILE, [])
    # receipts forwarded to your bookkeeping – by hand and automatically (recorded on each document)
    fw = [x for doc in (DOCS.load().get('documents') or {}).values() for x in doc.get('sent') or [] if (x.get('at') or '') >= since]
    sg = load_json(os.path.join(STATE_DIR, 'signal.json'), {})
    return {'days': days, 'since': since,
            'claude': {'runs': len(runs), 'by': claude, 'capped': len(ledger) >= _sch.RUNS_CAP,
                       'history_from': history_from if history_from and history_from > since else None},
            'web': {'briefs': briefs, 'queries': sum(len(b['queries']) for b in briefs), 'pages': sum(b['fetched'] for b in briefs)},
            'mail': {'sent': acts.get('reply_send', 0) + acts.get('mail_send', 0), 'sms': acts.get('sms_send', 0),
                     'forwarded': len(fw), 'forwarded_auto': sum(1 for x in fw if x.get('how') == 'auto'),
                     'unsubscribed': acts.get('sender_unsubscribe', 0)},
            'voice': voice,
            'signal': {'linked': bool(sg.get('linked'))},
            'push': {'devices': len(load_json(PUSH_SUBS_FILE, [])), 'discreet': bool(PRIV.load().get('discreet_push'))},
            'reports': {'sent': len(reports)},
            'pictures': {'senders': len(pics) if isinstance(pics, list) else 0,
                         'fetched': tally_sum('pictures', cutoff.date().isoformat())},
            'meetings': {'pages': tally_sum('meeting_pages', cutoff.date().isoformat()),
                         'assist': acts.get('meeting_assist', 0)},
            'meeting_services': {k: tally_sum('svc:' + k, cutoff.date().isoformat()) for k in ('teams', 'google_meet', 'zoom', 'icloud')},
            'invites': {'sent': acts.get('cal_invite_send', 0), 'updated': acts.get('cal_invite_update', 0),
                        'cancelled': acts.get('cal_invite_cancel', 0)},
            'notes': {'read': tally_sum('notes_read', cutoff.date().isoformat()),
                      'asks': tally_sum('notes_asks', cutoff.date().isoformat())}}


def mail_search(q, limit=40):
    accs = config().get('accounts', {})
    own = [a.get('address') for a in accs.values() if isinstance(a, dict)]
    try:
        names = mail_accounts()
    except Exception:
        names = {}                                   # Mail not answering: results still show, without reply
    if not names:
        return {'items': [], 'error': "Mail on the Mac mini isn't answering – try again in a moment"}
    try:
        found = mailsearch.search(q, names, own, limit=limit, classify=mail_privacy)
        for f in found:
            flag = SAFETY.flag_of({'message_id': f.get('message_id')}) if isinstance(f, dict) and f.get('message_id') else None
            if flag:
                f['safety'] = flag
        return {'items': found}
    except mailsearch.SearchError as e:
        return {'items': [], 'error': str(e)}
    except Exception as e:                           # never drop the connection on an odd file
        return {'items': [], 'error': 'search failed: ' + str(e)[:200]}


def chat_media(pk):
    """(content type, bytes) of a WhatsApp photo listed in the export – looked up by message id, never by a path from
    the request, and only inside WhatsApp's own folder. HEIC is converted to JPEG for browsers that can't show it."""
    import whatsapp_export
    d = load_json(WA_FILE, {})
    path = next((m['media']['path'] for c in d.get('chats') or [] for m in c.get('messages') or []
                 if isinstance(m.get('media'), dict) and str(m['media'].get('id')) == str(pk)), None)
    root = os.path.realpath(whatsapp_export.WA_DIR)
    real = os.path.realpath(path) if path else ''
    if not real.startswith(root + os.sep) or not real.lower().endswith(whatsapp_export.IMAGE_EXT) or not os.path.isfile(real):
        raise Bad('photo not available on the Mac mini')
    if os.path.getsize(real) > 15 * 2**20:
        raise Bad('photo too large to preview')
    ext = os.path.splitext(real)[1].lower()
    if ext == '.heic':
        import tempfile
        with tempfile.TemporaryDirectory(prefix='axella-wa-') as t:
            out = os.path.join(t, 'p.jpg')
            subprocess.run(['/usr/bin/sips', '-s', 'format', 'jpeg', '-Z', '1600', real, '--out', out], capture_output=True, timeout=20, check=True)
            with open(out, 'rb') as f:
                return 'image/jpeg', f.read()
    with open(real, 'rb') as f:
        return {'.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif'}.get(ext, 'image/jpeg'), f.read()


def config():
    return load_json(CONFIG_FILE, {})


# the same pattern as web/src/lib/data.ts isNoReply: "noreply", "payments-noreply", "do_not_reply", "bounces+1" …
NO_REPLY = re.compile(r'^(?:[^@]*[-+._])?(no-?reply|no_reply|do-?not-?reply|do_not_reply|mailer-daemon|postmaster|bounces?|notifications?)(?:[-+._][^@]*)?@', re.I)
SENDS = ('reply_send', 'mail_send', 'invite_respond', 'cal_invite_send', 'cal_invite_update', 'cal_invite_cancel', 'schedule_send', 'schedule_update', 'draft', 'draft_new', 'sms_send', 'compose', 'ask', 'report_save', 'report_check',
         'report_send', 'report_preview', 'triage_act', 'task_suggest', 'compose_assist', 'note_save', 'note_todo')


LOG_LOCK = threading.Lock()                           # appends and the 90-day archiving never interleave


_MEET_LOGGED = {}


TRASH_BATCH_MAX = 200


QUIET = ('digest_seen', 'mail_seen')                 # bookkeeping only (Your calm, Keep Mail tidy) – not worth a log line


def log(login, action, payload, result):
    if action in QUIET:
        return
    if action == 'meeting_update' and result == 'ok':     # autosave: one line per prep per 10 minutes is enough
        k, t = str(payload.get('id')), time.time()
        if t - _MEET_LOGGED.get(k, 0) < 600:
            return
        _MEET_LOGGED[k] = t
    # what someone wrote (a reply, a mail, a question) never goes into the log – its title, at most 80 characters
    title = payload.get('title') if action in SENDS else (payload.get('title') or payload.get('text'))
    entry = {'at': now_iso(), 'login': login, 'action': action, 'result': result,
             'item': payload.get('item_id'), 'message_id': payload.get('message_id'),
             'folder': payload.get('folder'), 'title': (str(title)[:80] if title else None)}
    if payload.get('_items'):                          # a batch (trash_batch): the item ids, one log line for all
        entry['items'] = [str(i)[:200] for i in payload['_items']][:TRASH_BATCH_MAX]
    if payload.get('_backup'):                         # a deleted contact/event: its copy, for Restore in the activity log
        entry['backup'] = str(payload['_backup'])[:60]
    if action == 'reply_send' and payload.get('item_id') and str(result).split(':')[0] in ('ok', 'sent'):
        try:                                           # Your calm: how much the draft was changed – a word, never the text
            b = edit_bucket(_draft_of(payload['item_id']), payload.get('text'))
            if b:
                entry['edit'] = b
        except Exception:
            pass
    with LOG_LOCK, open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def log_auto(action, title=None, result='ok'):
    """Something Axella did by itself (an automatic receipt forward, a notification) – in the same log, as "axella"."""
    try:
        log('axella', action, {'title': title}, result)
    except Exception:
        pass


def set_state(item_id, value):
    with LOCK:
        state = load_json(STATE_FILE, {})
        if value is None:
            state.pop(item_id, None)
        else:
            state[item_id] = value
        tmp = STATE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_FILE)


def osa(script, *args, timeout=60, tries=1):
    """Run AppleScript with user data passed only as argv. tries>1 only for read-only scripts (a retried move/draft
    could act twice)."""
    for attempt in range(tries):
        try:
            p = subprocess.run(['/usr/bin/osascript', '-e', script, *[str(a) for a in args]],
                               capture_output=True, text=True, timeout=timeout)
            break
        except subprocess.TimeoutExpired:
            if attempt + 1 == tries:
                raise RuntimeError(f'Mail/Calendar did not answer within {timeout} s – Mail may be busy '
                                   'syncing or showing a dialog on the Mac mini; try again in a few minutes.')
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip() or 'AppleScript failed')
    return p.stdout.strip()


FIND_MESSAGE = '''
on findMessage(accName, mid)
  tell application "Mail"
    -- 1. the account's own inbox (fast, where almost everything is)
    repeat with boxName in {"INBOX", "Inbox"}
      try
        set ms to (every message of mailbox (boxName as text) of account accName whose message id is mid)
        if (count of ms) > 0 then return item 1 of ms
      end try
    end repeat
    -- 2. every other folder of that account (slow fallback, e.g. already filed or in Trash)
    repeat with mb in (every mailbox of account accName)
      try
        set ms to (every message of mb whose message id is mid)
        if (count of ms) > 0 then return item 1 of ms
      end try
    end repeat
  end tell
  error "Message not found in Mail"
end findMessage
'''

DRAFT_NEW_SCRIPT = '''
on run argv
  set accName to item 1 of argv
  set toAddr to item 2 of argv
  set subj to item 3 of argv
  set bodyText to item 4 of argv
  tell application "Mail"
    set fromAddr to item 1 of (email addresses of account accName)
    set fromName to ""
    try
      set fromName to full name of account accName
    end try
    set nBefore to 0
    try
      set nBefore to count of (every message of drafts mailbox whose subject is subj)
    end try
    set msg to make new outgoing message with properties {subject:subj, content:bodyText, visible:true}
    tell msg to make new to recipient at end of to recipients with properties {address:toAddr}
    -- Mail puts an empty line above the text (room for the signature): take it out again
    try
      repeat 3 times
        set c to (content of msg) as text
        if c starts with (ASCII character 10) or c starts with (ASCII character 13) then
          delete character 1 of content of msg
        else
          exit repeat
        end if
      end repeat
    end try
    if fromName is "" then
      set sender of msg to fromAddr
    else
      set sender of msg to fromName & " <" & fromAddr & ">"
    end if
    delay 1
    save msg
    delay 1
    repeat with w in (every window)
      try
        if name of w is subj then close w saving yes
      end try
    end repeat
    delay 2
    set nAfter to nBefore
    repeat 5 times
      try
        set nAfter to count of (every message of drafts mailbox whose subject is subj)
      end try
      if nAfter > nBefore then exit repeat
      delay 1
    end repeat
    if nAfter > nBefore then return "saved"
    return "unconfirmed"
  end tell
end run
'''


def compose_contacts():
    """Addresses for the compose form: everyone who appeared in digests in the last 120 days, most frequent first."""
    cutoff = time.time() - 120 * 86400
    seen = {}
    for p in glob.glob(os.path.join(DIGESTS_DIR, '*.json')):
        try:
            if os.path.getmtime(p) < cutoff:
                continue
            with open(p, encoding='utf-8') as f:
                items = (json.load(f) or {}).get('items') or []
        except (OSError, ValueError):
            continue
        for it in items:
            fr = it.get('from') or {}
            for name, addr in ((fr.get('name'), fr.get('address')), (None, (it.get('draft') or {}).get('to'))):
                addr = str(addr or '').strip().lower()
                if '@' not in addr or ' ' in addr or len(addr) > 120:
                    continue
                e = seen.setdefault(addr, {'address': addr, 'name': '', 'count': 0, 'account': it.get('account')})
                e['count'] += 1
                if name and not e['name']:
                    e['name'] = str(name)[:80]
    return sorted(seen.values(), key=lambda e: -e['count'])[:300]


RCPT_RE = re.compile(r'^[A-Za-z0-9._%+\'-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$')
RCPT_MAX = 30


def own_addresses():
    cfg = config()
    own = {str(a.get('address') or '').lower() for a in (cfg.get('accounts') or {}).values() if isinstance(a, dict)}
    own |= {str(x).lower() for x in ((cfg.get('self') or {}).get('addresses') or []) if '@' in str(x)}
    return {a for a in own if a}


def recipients(p):
    """The composer's To / Cc / Bcc, checked: plain addresses only, no duplicates, at most 30 in all, To not empty and
    no no-reply address on To. None when the request has no recipient lists (the older one-address reply)."""
    if not isinstance(p.get('to'), list):
        return None
    out, seen = [], set()
    for k in ('to', 'cc', 'bcc'):
        lst = []
        for a in (p.get(k) or []) if isinstance(p.get(k) or [], list) else []:
            a = str(a).strip()
            if not RCPT_RE.match(a) or len(a) > 120:
                raise Bad('"%s" is not an e-mail address' % a[:60])
            if a.lower() in seen:
                continue
            seen.add(a.lower())
            lst.append(a)
        out.append(lst)
    to, cc, bcc = out
    if not to:
        raise Bad('add someone on To')
    if len(seen) > RCPT_MAX:
        raise Bad('more than %d recipients – send this one from Mail' % RCPT_MAX)
    bad = next((a for a in to if NO_REPLY.match(a.lower())), None)
    if bad:
        raise Bad('%s is a no-reply address – nobody reads mail sent to it' % bad)
    return to, cc, bcc


def new_recipients(v, most=20):
    """The addresses of a new mail's To or Cc: comma- or semicolon-separated, each a plain address (no name, no
    brackets), never a no-reply address, at most 20, each once."""
    out = []
    for a in re.split(r'[,;\n]', str(v or '')):
        a = a.strip()
        if not a:
            continue
        if '@' not in a or any(c in a for c in ' <>"\t') or len(a) > 200:
            raise Bad('%s is not an e-mail address' % a[:60])
        if NO_REPLY.match(a):
            raise Bad('%s is a no-reply address – nobody reads mail sent to it' % a)
        if a.lower() not in [x.lower() for x in out]:
            out.append(a)
    if len(out) > most:
        raise Bad('at most %d recipients' % most)
    return out


def rcpt_arg(lst):
    return '\x1e'.join(lst)


def rcpt_expected(to, cc, bcc):
    """The read-back string the AppleScript compares with (readRecipients' format)."""
    return ''.join(['to:%s\x1e' % a for a in to] + ['cc:%s\x1e' % a for a in cc] + ['bcc:%s\x1e' % a for a in bcc])


def reply_info(account, mid):
    """Who a reply goes to, from the mail's own headers: Reply-To (else From) on To, and – for reply all – everyone
    else on To/Cc, without your own addresses. Private contacts: refused, as for the message itself."""
    import email.utils
    from email.parser import BytesHeaderParser
    from email import policy as _policy
    if account not in config().get('accounts', {}):
        raise Bad('account not allowed')
    path = mailsearch.path_for_mid(mid)
    rp = mailsearch._inside(path) if path else None
    if not rp:
        raise Bad("Mail hasn't got this message on disk – the reply goes to the sender")
    h = BytesHeaderParser(policy=_policy.compat32).parsebytes(mailsearch._raw(rp, headers_only=True))
    dec = mailsearch._dec
    get = lambda k: email.utils.getaddresses([dec(h.get(k))]) if h.get(k) else []
    if mail_privacy([a for _, a in get('From') + get('Reply-To') + get('To') + get('Cc')])[0]:
        raise Bad('This mail involves a private contact – open it in Mail.')
    own = own_addresses()
    person = lambda n, a: {'name': ' '.join(str(n or '').split())[:80], 'address': a.strip()}
    target = [person(n, a) for n, a in (get('Reply-To') or get('From')) if a and RCPT_RE.match(a.strip())]
    taken = {t['address'].lower() for t in target} | own
    others = []
    for n, a in get('To') + get('Cc'):
        if a and RCPT_RE.match(a.strip()) and a.lower() not in taken:
            taken.add(a.lower())
            others.append(person(n, a))
    return {'to': target, 'cc': others[:RCPT_MAX], 'subject': dec(h.get('Subject'))[:300],
            'reply_to_differs': bool(get('Reply-To')) and {a.lower() for _, a in get('Reply-To')} != {a.lower() for _, a in get('From')}}


# Explicit recipients (the composer's To / Cc / Bcc): lists arrive as one argument, addresses separated by ASCII 30.
# The script empties what Mail pre-filled, adds exactly these, and reads them back – Python compares before anything
# is sent. Names are never passed: an address only.
RECIPIENTS_AS = '''
on splitList(s)
  if s is "" then return {}
  set AppleScript's text item delimiters to (ASCII character 30)
  set xs to text items of s
  set AppleScript's text item delimiters to ""
  return xs
end splitList

on setRecipients(r, toS, ccS, bccS)
  tell application "Mail"
    try
      delete every to recipient of r
    end try
    try
      delete every cc recipient of r
    end try
    try
      delete every bcc recipient of r
    end try
    repeat with a in my splitList(toS)
      make new to recipient at end of to recipients of r with properties {address:(a as text)}
    end repeat
    repeat with a in my splitList(ccS)
      make new cc recipient at end of cc recipients of r with properties {address:(a as text)}
    end repeat
    repeat with a in my splitList(bccS)
      make new bcc recipient at end of bcc recipients of r with properties {address:(a as text)}
    end repeat
  end tell
end setRecipients

on readRecipients(r)
  set out to ""
  tell application "Mail"
    repeat with t in (to recipients of r)
      set out to out & "to:" & (address of t) & (ASCII character 30)
    end repeat
    repeat with t in (cc recipients of r)
      set out to out & "cc:" & (address of t) & (ASCII character 30)
    end repeat
    repeat with t in (bcc recipients of r)
      set out to out & "bcc:" & (address of t) & (ASCII character 30)
    end repeat
  end tell
  return out
end readRecipients
'''

# The owner confirmed Send in the composer with these To/Cc/Bcc: Mail replies in the thread (In-Reply-To kept), with
# exactly those recipients. The script reads them back and only sends when they equal what was confirmed (argv 7);
# otherwise it closes the reply unsent. argv: account, message id, text, to, cc, bcc, expected, files…
SEND_REPLY_TO_SCRIPT = FIND_MESSAGE + RECIPIENTS_AS + '''
on run argv
  set m to my findMessage(item 1 of argv, item 2 of argv)
  set bodyText to item 3 of argv
  set atts to {}
  repeat with i from 8 to (count of argv)
    set end of atts to (POSIX file (item i of argv))
  end repeat
  tell application "Mail"
    set r to reply m with opening window
    delay 1
  end tell
  my setRecipients(r, item 4 of argv, item 5 of argv, item 6 of argv)
  delay 0.5
  set got to my readRecipients(r)
  if got is not (item 7 of argv) then
    tell application "Mail"
      try
        set subj to subject of r
        repeat with w in (every window)
          try
            if name of w is subj then close w saving no
          end try
        end repeat
      end try
    end tell
    return "mismatch" & (ASCII character 31) & got
  end if
  tell application "Mail"
    delay 1
    set content of r to bodyText
    delay 0.5
    try
      repeat 3 times
        set c to (content of r) as text
        if c starts with (ASCII character 10) or c starts with (ASCII character 13) then
          delete character 1 of content of r
        else
          exit repeat
        end if
      end repeat
    end try
    repeat with a in atts
      tell content of r to make new attachment with properties {file name:(contents of a)} at after last paragraph
      delay 1
    end repeat
    delay 0.5
    set ok to send r
  end tell
  if ok then return "sent" & (ASCII character 31) & got
  return "failed"
end run
'''

DRAFT_SCRIPT = FIND_MESSAGE + RECIPIENTS_AS + '''
on run argv
  set accName to item 1 of argv
  set mid to item 2 of argv
  set bodyText to item 3 of argv
  set toS to ""
  set ccS to ""
  set bccS to ""
  if (count of argv) > 5 then
    set toS to item 4 of argv
    set ccS to item 5 of argv
    set bccS to item 6 of argv
  end if
  set m to my findMessage(accName, mid)
  tell application "Mail"
    set subj to subject of m
    if subj does not start with "Re:" and subj does not start with "SV:" and subj does not start with "AW:" then set subj to "Re: " & subj
    -- the bare subject: Exchange may save the reply without "Re:"/"SV:", so match on what's left
    set baseSubj to subject of m
    try
    repeat 4 times
      set hit to false
      repeat with pfx in {"Re: ", "SV: ", "AW: ", "VS: ", "Fwd: ", "FW: "}
        if baseSubj starts with (pfx as text) then
          set baseSubj to text ((length of (pfx as text)) + 1) thru -1 of baseSubj
          set hit to true
        end if
      end repeat
      if not hit then exit repeat
    end repeat
    end try
    if baseSubj is "" then set baseSubj to subj
    set nBefore to 0
    try
      set nBefore to count of (every message of drafts mailbox whose subject contains baseSubj)
    end try
    -- Mail's own reply keeps In-Reply-To/References, so the answer lands in the same thread
    set r to reply m with opening window
    delay 2
    if toS is not "" then my setRecipients(r, toS, ccS, bccS)
    set content of r to bodyText
    delay 0.5
    -- Mail puts an empty line above the text (room for the signature): take it out again
    try
      repeat 3 times
        set c to (content of r) as text
        if c starts with (ASCII character 10) or c starts with (ASCII character 13) then
          delete character 1 of content of r
        else
          exit repeat
        end if
      end repeat
    end try
    save r
    delay 1
    -- close only compose windows for this subject (never the main viewer)
    repeat with w in (every window)
      try
        if name of w is subj or name of w is (subject of r) then close w saving yes
      end try
    end repeat
    delay 2
    set nAfter to nBefore
    repeat 5 times
      try
        set nAfter to count of (every message of drafts mailbox whose subject contains baseSubj)
      end try
      if nAfter > nBefore then exit repeat
      delay 1
    end repeat
  end tell
  -- the newest draft with this subject: its Message-ID lets the dashboard open it in Mail (message:// link)
  set did to ""
  try
    tell application "Mail"
      set ds to (every message of drafts mailbox whose subject contains baseSubj)
      set newest to missing value
      repeat with d in ds
        if newest is missing value then
          set newest to d
        else if (id of d) > (id of newest) then
          set newest to d
        end if
      end repeat
      if newest is not missing value then set did to message id of newest
    end tell
  end try
  if nAfter > nBefore then return "saved" & (ASCII character 31) & did
  return "unverified" & (ASCII character 31) & did
end run
'''

# The owner wrote/approved the text and confirmed "Send" in the dashboard – Mail sends it from his account.
SEND_REPLY_SCRIPT = FIND_MESSAGE + '''
on run argv
  set m to my findMessage(item 1 of argv, item 2 of argv)
  set bodyText to item 3 of argv
  set expected to item 4 of argv
  set atts to {}
  repeat with i from 5 to (count of argv)
    set end of atts to (POSIX file (item i of argv))
  end repeat
  tell application "Mail"
    set r to reply m with opening window
    delay 1
    -- who Mail will really send to (Reply-To wins over From): stop if it isn't who the owner confirmed
    set toList to ""
    try
      repeat with t in (to recipients of r)
        set toList to toList & (address of t) & " "
      end repeat
    end try
    set ok to false
    set AppleScript's text item delimiters to " "
    set addrs to text items of toList
    set AppleScript's text item delimiters to ""
    set n to 0
    repeat with a in addrs
      if (a as text) is not "" then
        set n to n + 1
        if (a as text) is equal to expected then set ok to true
      end if
    end repeat
    if not ok or n is not 1 then
      try
        set subj to subject of r
        repeat with w in (every window)
          try
            if name of w is subj then close w saving no
          end try
        end repeat
      end try
      return "mismatch" & (ASCII character 31) & toList
    end if
    delay 2
    set content of r to bodyText
    delay 0.5
    try
      repeat 3 times
        set c to (content of r) as text
        if c starts with (ASCII character 10) or c starts with (ASCII character 13) then
          delete character 1 of content of r
        else
          exit repeat
        end if
      end repeat
    end try
    repeat with a in atts
      tell content of r to make new attachment with properties {file name:(contents of a)} at after last paragraph
      delay 1
    end repeat
    delay 0.5
    set ok to send r
  end tell
  if ok then return "sent" & (ASCII character 31) & toList
  return "failed"
end run
'''

SEND_NEW_SCRIPT = '''
on run argv
  set accName to item 1 of argv
  set toAddr to item 2 of argv
  set subj to item 3 of argv
  set bodyText to item 4 of argv
  set fromAddr to item 5 of argv
  set atts to {}
  repeat with i from 6 to (count of argv)
    set end of atts to (POSIX file (item i of argv))
  end repeat
  tell application "Mail"
    -- the address from actions-config.json; Mail's own list only when that is empty (iCloud accounts may list none)
    if fromAddr is "" then
      set addrs to email addresses of account accName
      if (count of addrs) is 0 then error "Mail lists no address for this account - add its address in actions-config.json"
      set fromAddr to item 1 of addrs
    end if
    set fromName to ""
    try
      set fromName to full name of account accName
    end try
    set msg to make new outgoing message with properties {subject:subj, content:bodyText, visible:true}
    tell msg to make new to recipient at end of to recipients with properties {address:toAddr}
    try
      repeat 3 times
        set c to (content of msg) as text
        if c starts with (ASCII character 10) or c starts with (ASCII character 13) then
          delete character 1 of content of msg
        else
          exit repeat
        end if
      end repeat
    end try
    if fromName is "" then
      set sender of msg to fromAddr
    else
      set sender of msg to fromName & " <" & fromAddr & ">"
    end if
    repeat with a in atts
      tell content of msg to make new attachment with properties {file name:(contents of a)} at after last paragraph
      delay 1
    end repeat
    delay 1
    set ok to send msg
  end tell
  if ok then return "sent"
  return "failed"
end run
'''

# A new mail to several people (To and Cc), on your confirmed tap: the recipients are set, read back and compared with
# what you confirmed (argv 7) before Mail sends; a mismatch closes it unsent. argv: account, to, cc, subject, text,
# from address, expected, files…
SEND_NEW_MULTI_SCRIPT = RECIPIENTS_AS + '''
on run argv
  set accName to item 1 of argv
  set subj to item 4 of argv
  set bodyText to item 5 of argv
  set fromAddr to item 6 of argv
  set atts to {}
  repeat with i from 8 to (count of argv)
    set end of atts to (POSIX file (item i of argv))
  end repeat
  tell application "Mail"
    if fromAddr is "" then
      set addrs to email addresses of account accName
      if (count of addrs) is 0 then error "Mail lists no address for this account - add its address in actions-config.json"
      set fromAddr to item 1 of addrs
    end if
    set fromName to ""
    try
      set fromName to full name of account accName
    end try
    set msg to make new outgoing message with properties {subject:subj, content:bodyText, visible:true}
  end tell
  my setRecipients(msg, item 2 of argv, item 3 of argv, "")
  delay 0.5
  set got to my readRecipients(msg)
  if got is not (item 7 of argv) then
    tell application "Mail"
      try
        close (every window whose name is subj) saving no
      end try
    end tell
    return "mismatch" & (ASCII character 31) & got
  end if
  tell application "Mail"
    if fromName is "" then
      set sender of msg to fromAddr
    else
      set sender of msg to fromName & " <" & fromAddr & ">"
    end if
    repeat with a in atts
      tell content of msg to make new attachment with properties {file name:(contents of a)} at after last paragraph
      delay 1
    end repeat
    delay 1
    set ok to send msg
  end tell
  if ok then return "sent"
  return "failed"
end run
'''

FILE_SCRIPT = FIND_MESSAGE + '''
on run argv
  set accName to item 1 of argv
  set mid to item 2 of argv
  set folderPath to item 3 of argv
  set m to my findMessage(accName, mid)
  tell application "Mail"
    set AppleScript's text item delimiters to "/"
    set parts to text items of folderPath
    set AppleScript's text item delimiters to ""
    set target to mailbox (item 1 of parts) of account accName
    if (count of parts) > 1 then
      repeat with i from 2 to (count of parts)
        set target to mailbox (item i of parts) of target
      end repeat
    end if
    move m to target
  end tell
  return "moved"
end run
'''

TRASH_SCRIPT = FIND_MESSAGE + '''
on run argv
  set accName to item 1 of argv
  set mid to item 2 of argv
  set m to my findMessage(accName, mid)
  tell application "Mail"
    delete m
  end tell
  return "moved to trash"
end run
'''

PREVIEW_SCRIPT = FIND_MESSAGE + '''
on run argv
  set m to my findMessage(item 1 of argv, item 2 of argv)
  set RS to (ASCII character 30)
  tell application "Mail"
    set subj to subject of m
    set snd to sender of m
    set dt to ""
    try
      set dt to (date sent of m) as string
    end try
    set att to ""
    try
      repeat with a in (every mail attachment of m)
        set att to att & (name of a) & linefeed
      end repeat
    end try
    set mbx to ""
    try
      set mbx to name of (mailbox of m)
    end try
    set bodyTxt to content of m
  end tell
  return subj & RS & snd & RS & dt & RS & mbx & RS & att & RS & bodyTxt
end run
'''

_PREVIEW_CACHE = {}


def message_preview(account, mid):
    """Read-only: subject, sender, date, mailbox, attachment names and plain-text body of one message."""
    import time
    if account not in config().get('accounts', {}):
        raise Bad('account not allowed')
    if not mid or len(mid) > 500:
        raise Bad('bad message id')
    hit = _PREVIEW_CACHE.get((account, mid))
    if hit and time.time() - hit[1] < 600:
        return hit[0]
    out = osa(PREVIEW_SCRIPT, account, mid, timeout=60, tries=2)
    parts = (out.split('\x1e') + [''] * 6)[:6]
    subj, sender, dt, mbx, att, body = parts[0], parts[1], parts[2], parts[3], parts[4], '\x1e'.join(out.split('\x1e')[5:])
    body = body.replace('\r\n', '\n').replace('\r', '\n').strip()
    res = {'subject': subj, 'from': sender, 'date': dt, 'mailbox': mbx,
           'attachments': [a for a in att.split('\n') if a.strip()],
           'body': body[:20000], 'truncated': len(body) > 20000}
    _PREVIEW_CACHE[(account, mid)] = (res, time.time())
    if len(_PREVIEW_CACHE) > 200:
        _PREVIEW_CACHE.clear()
    return res


FORWARD_SCRIPT = FIND_MESSAGE + '''
on run argv
  set m to my findMessage(item 1 of argv, item 2 of argv)
  tell application "Mail"
    set f to forward m with opening window
    delay 1.5
    tell f
      make new to recipient at end of to recipients with properties {name:(item 4 of argv), address:(item 3 of argv)}
    end tell
    delay 0.5
    send f
  end tell
  return "forwarded"
end run
'''


def mail_forward(account, message_id, address, name):
    """Forward one message with its attachments – ONLY called by forwarding.py for recipients in state/recipients.json."""
    if account not in config().get('accounts', {}):
        raise Bad('account not allowed')
    return osa(FORWARD_SCRIPT, account, message_id, address, name, timeout=120)


ATTACHMENT_SCRIPT = FIND_MESSAGE + '''
on run argv
  set m to my findMessage(item 1 of argv, item 2 of argv)
  tell application "Mail"
    set a to mail attachment ((item 3 of argv) as integer) of m
    -- a fixed file name: the attachment's own name comes from the sender and never becomes part of a path
    set dest to (item 4 of argv) & "attachment"
    save a in POSIX file dest
    set nm to name of a
  end tell
  return dest & (ASCII character 31) & nm
end run
'''
ATT_TYPES = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
             '.gif': 'image/gif', '.heic': 'image/heic', '.txt': 'text/plain', '.csv': 'text/csv'}


def attachment_file(account, mid, index):
    """Let Mail save attachment #index (1-based) to a private temp folder Mail may write to (~/Downloads/.axella-tmp),
    read it, delete it. Returns (name, content_type, bytes)."""
    import shutil, secrets as _s
    if account not in config().get('accounts', {}):
        raise Bad('account not allowed')
    base = os.path.expanduser('~/Downloads/.axella-tmp/' + _s.token_hex(6) + '/')
    os.makedirs(base, exist_ok=True)
    try:
        path, _, raw_name = osa(ATTACHMENT_SCRIPT, account, mid, str(int(index)), base, timeout=90, tries=2).partition('\x1f')
        if os.path.realpath(path) != os.path.realpath(os.path.join(base, 'attachment')):
            raise Bad('attachment was not saved where expected')
        with open(path, 'rb') as f:
            data = f.read()
        # the sender's file name: only for the download header – no path parts, no control characters
        name = re.sub(r'[\x00-\x1f/\\:"]', '_', os.path.basename(raw_name.strip().replace('\\', '/')))[:150].strip('. ') or 'attachment'
        ctype = ATT_TYPES.get(os.path.splitext(name)[1].lower(), 'application/octet-stream')
        return name, ctype, data
    finally:
        shutil.rmtree(base, ignore_errors=True)


EVENT_SCRIPT = '''
on mkDate(y, mo, d, h, mi)
  set dt to current date
  set day of dt to 1
  set year of dt to y
  set month of dt to mo
  set day of dt to d
  set hours of dt to h
  set minutes of dt to mi
  set seconds of dt to 0
  return dt
end mkDate
on run argv
  set calName to item 1 of argv
  set ttl to item 2 of argv
  set loc to item 3 of argv
  set notesText to item 4 of argv
  set sd to my mkDate((item 5 of argv) as integer, (item 6 of argv) as integer, (item 7 of argv) as integer, (item 8 of argv) as integer, (item 9 of argv) as integer)
  set ed to my mkDate((item 10 of argv) as integer, (item 11 of argv) as integer, (item 12 of argv) as integer, (item 13 of argv) as integer, (item 14 of argv) as integer)
  tell application "Calendar"
    tell calendar calName
      make new event with properties {summary:ttl, start date:sd, end date:ed, location:loc, description:notesText}
    end tell
  end tell
  return "created"
end run
'''


def parts(iso):
    d = datetime.datetime.fromisoformat(iso)
    return [d.year, d.month, d.day, d.hour, d.minute]


TAILSCALE_BIN = '/Applications/Tailscale.app/Contents/MacOS/Tailscale'
_WHOIS_CACHE = {}


import socket as _socket
_LOCAL = {'at': 0, 'ips': set()}


def _local_ips():
    """IP addresses on this Mac's own interfaces (incl. its Tailscale 100.x / fd7a: address)."""
    import subprocess as _sp, time as _t, re as _re
    if _t.time() - _LOCAL['at'] > 300:
        try:
            out = _sp.run(['/sbin/ifconfig'], capture_output=True, text=True, timeout=5).stdout
            _LOCAL['ips'] = set(_re.findall(r'inet6? ([0-9a-fA-F:.]+)', out)) | {'127.0.0.1', '::1'}
        except Exception:
            _LOCAL['ips'] = {'127.0.0.1', '::1'}
        _LOCAL['at'] = _t.time()
    return _LOCAL['ips']


def tailnet_login(headers):
    """Who is asking? Prefer Tailscale-User-Login; otherwise ask Tailscale who owns the
    source address that Tailscale Serve put in X-Forwarded-For. None = not a tailnet user."""
    import subprocess as _sp, time as _t, json as _j
    login = headers.get('Tailscale-User-Login', '')
    if login:
        return login
    ip = (headers.get('X-Forwarded-For', '') or '').split(',')[-1].strip()   # Serve appends the real client: take the last
    if not ip:
        return None
    if ip in _local_ips():
        # request from this Mac itself (tagged node, no user): the Tailscale CLI can't be used from launchd here
        return 'node:' + _socket.gethostname().split('.')[0]
    hit = _WHOIS_CACHE.get(ip)
    if hit and _t.time() - hit[1] < 300:
        return hit[0]
    try:
        out = _sp.run([TAILSCALE_BIN, 'whois', '--json', ip], capture_output=True, text=True, timeout=5)
        data = _j.loads(out.stdout) if out.returncode == 0 else {}
        node = data.get('Node') or {}
        login = (data.get('UserProfile') or {}).get('LoginName') or None
        if node.get('Tags') or login == 'tagged-devices':
            # tagged devices (e.g. the Mac mini itself, tag:server) have no user: identify the machine
            name = node.get('ComputedName') or (node.get('Name') or '').split('.')[0]
            login = 'node:' + name if name else None
    except Exception:
        login = None
    _WHOIS_CACHE[ip] = (login, _t.time())
    return login


MAILBOXES_SCRIPT = '''
on run argv
  set US to (ASCII character 31)
  set RS to (ASCII character 30)
  set out to ""
  tell application "Mail"
    repeat with m in (every mailbox of account (item 1 of argv))
      set kids to ""
      try
        repeat with k in (mailboxes of m)
          set kids to kids & US & (name of k)
        end repeat
      end try
      set out to out & (name of m) & kids & RS
    end repeat
  end tell
  return out
end run
'''
_FOLDER_CACHE = {}
_SKIP_FOLDERS = ('inbox', 'trash', 'deleted messages', 'deleted items', 'junk', 'junk e-mail', 'spam', 'sent', 'sent messages',
                 'sent items', 'drafts', 'outbox', 'notes', 'conversation history', 'sync issues', 'rss feeds')


def live_folders(account, fresh=False):
    """Folders that exist in Mail for one account (cached 2 min; fresh=True skips the cache) – plus the configured
    ones. Read-only."""
    import time
    hit = _FOLDER_CACHE.get(account)
    if hit and not fresh and time.time() - hit[1] < 120:
        return hit[0]
    base = list(config().get('accounts', {}).get(account, {}).get('folders', []))
    try:
        out = osa(MAILBOXES_SCRIPT, account, timeout=60, tries=2)
        rows = [r.split('\x1f') for r in out.split('\x1e') if r.strip()]
        parent = {}
        for r in rows:                     # Mail lists every folder flat, each with its direct children
            for k in r[1:]:
                parent[k.strip()] = r[0].strip()

        def path(n, depth=0):
            return n if n not in parent or depth > 8 else path(parent[n], depth + 1) + '/' + n
        names = [path(r[0].strip()) for r in rows if r[0].strip()]
        names = [n for n in names if n.split('/')[0].lower() not in _SKIP_FOLDERS and not (n.startswith('@') and '.' in n.split('/')[0])]   # imported accounts, e.g. '@old-employer.com/…'
        res = base + sorted({n for n in names if n not in base}, key=str.lower)
    except Exception as e:
        sys.stderr.write('folders %s: %s\n' % (account, str(e)[:200]))
        return base                      # Mail busy – configured list only, try again next time
    _FOLDER_CACHE[account] = (res, time.time())
    return res


class Bad(Exception):
    pass


def save_tasks(tasks):
    tmp = TASKS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=1)
    os.replace(tmp, TASKS_FILE)


def _task_notes(v):
    """A task's details: plain text, at most 4000 characters (background, links, what "done" means)."""
    if v is None:
        return ''
    if not isinstance(v, str):
        raise Bad('notes must be text')
    v = v.replace('\r\n', '\n').strip()
    if len(v) > 4000:
        raise Bad('details too long (max 4000 characters)')
    return v


def task_action(action, p):
    with LOCK:
        tasks = load_json(TASKS_FILE, [])
        if action == 'task_add':
            require(p, 'text')
            if len(p['text']) > 500:
                raise Bad('text too long')
            due = p.get('due') or None
            if due:
                datetime.date.fromisoformat(due)
            t = {'id': datetime.datetime.now().strftime('t%Y%m%d%H%M%S%f'), 'text': p['text'].strip(), 'due': due,
                 'status': 'open', 'created': now_iso(), 'source': p.get('source', 'dashboard'),
                 'ref': p.get('ref') if isinstance(p.get('ref'), dict) else None}
            if isinstance(p.get('reminder'), str) and p['reminder'][:1] == 'r':
                t['reminder'] = p['reminder'][:40]      # made by a recurring reminder (reminders.py)
            notes = _task_notes(p.get('notes'))
            if notes:
                t['notes'] = notes
            if p.get('ctx') in ('work', 'private'):    # optional: Work or Private (unset = shows under both)
                t['ctx'] = p['ctx']
            if p.get('type') == 'bill':                # a bill (bills.py): the same To do, with payee and amount
                t['type'], t['bill'] = 'bill', _bill_fields(p.get('bill'))
                if isinstance(p.get('bill'), dict) and p['bill'].get('reference'):
                    BILLS.set_ref(t['id'], p['bill']['reference'])    # the payment details: bills.json, never tasks.json
            tasks.append(t)
            save_tasks(tasks)
            return t['id']
        require(p, 'id')
        t = next((x for x in tasks if x.get('id') == p['id']), None)
        if not t:
            raise Bad('task not found')
        if action == 'task_done':
            t['status'], t['done'] = 'done', now_iso()
            _bill_paid(t, True)                         # a bill ticked = paid: its Receipts entry is marked paid too
        elif action == 'task_undo':
            t['status'] = 'open'; t.pop('done', None)
            _bill_paid(t, False)
        elif action == 'task_delete':
            tasks.remove(t)
            if t.get('type') == 'bill':
                BILLS.set_ref(t['id'], None)
        elif action == 'task_update':
            if 'due' in p:
                due = p.get('due') or None
                if due:
                    datetime.date.fromisoformat(due)
                t['due'] = due
            if isinstance(p.get('text'), str) and p['text'].strip():
                if len(p['text']) > 500:
                    raise Bad('text too long')
                t['text'] = p['text'].strip()
            if 'ctx' in p:                      # 'work' / 'private'; anything else (None, '') clears it
                if p.get('ctx') in ('work', 'private'):
                    t['ctx'] = p['ctx']
                else:
                    t.pop('ctx', None)
            if t.get('type') == 'bill' and isinstance(p.get('bill'), dict):     # edit payee, amount, currency, reference
                t['bill'] = _bill_fields(dict(t.get('bill') or {}, **p['bill']))
                if 'reference' in p['bill']:
                    BILLS.set_ref(t['id'], p['bill']['reference'])
            if 'notes' in p:                    # empty removes them
                notes = _task_notes(p.get('notes'))
                if notes:
                    t['notes'] = notes
                else:
                    t.pop('notes', None)
        else:
            raise Bad('unknown action')
        save_tasks(tasks)
        return action


import bills as _bills  # noqa: E402  (bills as a To do type – rules only, on the Mac mini)
BILLS = _bills.Bills(STATE_DIR)


def _bill_fields(b):
    """The bill object on a To do, cleaned: only these keys, short strings, an exact amount, a three-letter currency."""
    b = b if isinstance(b, dict) else {}
    try:
        amount = _bills._num(b.get('amount'))
    except _bills.Bad as e:
        raise Bad(str(e))
    cur = str(b.get('currency') or '').strip().upper() or None
    if cur and not re.fullmatch(r'[A-Z]{3}', cur):
        raise Bad('the currency is three letters, e.g. DKK')
    out = {'payee': str(b.get('payee') or '').strip()[:80], 'amount': amount, 'currency': cur}   # no reference: see bills.py
    for k, n in (('document', 500), ('account', 80), ('message_id', 500), ('subject', 200)):
        if b.get(k):
            out[k] = str(b[k])[:n]
    if isinstance(b.get('attachments'), list):
        out['attachments'] = [str(a)[:200] for a in b['attachments'][:6]]
    if b.get('vendor_key'):
        out['vendor_key'] = str(b['vendor_key'])[:80]
    for k in ('first_time', 'details_differ', 'sender_differs'):     # the warnings stay on the To do
        if b.get(k):
            out[k] = True
    return out


def _bill_paid(t, on):
    doc = (t.get('bill') or {}).get('document') if t.get('type') == 'bill' else None
    if not doc:
        return
    try:
        DOCS.action('document_set', {'message_id': doc, 'paid': datetime.date.today().isoformat() if on else None})
    except Exception:
        pass                                           # the document may be gone from the register – the To do still counts


CONTACTS_FILE = os.path.join(BASE, 'contacts.md')



def _sent_ts(x):
    """Epoch seconds of a sent.json entry (older entries only have the ISO "at")."""
    if isinstance(x.get('ts'), (int, float)):
        return x['ts']
    try:
        return datetime.datetime.fromisoformat(str(x.get('at'))).timestamp()
    except ValueError:
        return 0


def outbox_save(name, data):
    """One attachment for a mail about to be sent → state/outbox/<id>/<name>. Old uploads (24 h) are cleared."""
    import re, shutil, uuid
    if len(data) > 20 * 1024 * 1024:
        raise Bad('file larger than 20 MB')
    name = re.sub(r'[^\w .,()+-]', '_', os.path.basename(name or 'file'))[:120].strip()
    if not name.strip('.'):
        name = 'file'                              # "." / ".." would be a folder, not a file
    outbox_prune()
    used = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(OUTBOX_DIR) for f in fs)
    if used + len(data) > OUTBOX_MAX:
        raise Bad('the outbox is full (%d MB) – send or remove the attachments you added, or wait a day' % (OUTBOX_MAX // 2**20))
    fid = uuid.uuid4().hex
    os.makedirs(os.path.join(OUTBOX_DIR, fid))
    with open(os.path.join(OUTBOX_DIR, fid, name), 'wb') as f:
        f.write(data)
    return fid + '/' + name


def outbox_prune(max_age=86400):
    """Remove uploads older than a day (also run by housekeeping, not only on the next upload)."""
    import shutil
    os.makedirs(OUTBOX_DIR, exist_ok=True)
    cut = time.time() - max_age
    for d in os.listdir(OUTBOX_DIR):
        dp = os.path.join(OUTBOX_DIR, d)
        if os.path.isdir(dp) and os.path.getmtime(dp) < cut:
            shutil.rmtree(dp, ignore_errors=True)


def outbox_paths(ids):
    """The uploaded files a send refers to – only ever inside state/outbox."""
    if not ids:
        return []
    if not isinstance(ids, list) or len(ids) > 10:
        raise Bad('at most 10 attachments')
    root, out, total = os.path.realpath(OUTBOX_DIR), [], 0
    for i in ids:
        pth = os.path.realpath(os.path.join(OUTBOX_DIR, str(i)))
        if not pth.startswith(root + os.sep) or not os.path.isfile(pth):
            raise Bad('attachment missing – add it again')
        total += os.path.getsize(pth)
        out.append(pth)
    if total > 25 * 1024 * 1024:
        raise Bad('attachments larger than 25 MB in all')
    return out


def outbox_clear(paths):
    import shutil
    for pth in paths:
        shutil.rmtree(os.path.dirname(pth), ignore_errors=True)


def _vip_sections(lines):
    """[(index of '## VIP…' heading, title, is_work)] – the work list is the one naming a workplace or 'work'."""
    out = []
    try:
        words = ['work', 'job'] + [str(w.get('name') or w.get('id') or '').lower() for w in profile.workplaces()]
    except Exception:
        words = ['work', 'job']
    for i, l in enumerate(lines):
        if l.lower().startswith('## vip'):
            t = l[2:].strip()
            out.append((i, t, any(w and w in t.lower() for w in words)))
    return out


def _vip_name(line):
    import re
    return re.split(r'\s+[(–-]\s*|\s+\(', line[2:].strip())[0].strip()


def _vip_detail(line):
    """What follows the name on a VIP line ("(partner)", "sam@acme.example (manager)"), without the leading " – "."""
    rest = line[2:].strip()[len(_vip_name(line)):].strip()
    return re.sub(r'^[–-]\s*', '', rest)[:200]


def vips_list(full=False):
    try:
        lines = open(CONTACTS_FILE, encoding='utf-8').read().split('\n')
    except OSError:
        return ([], []) if full else []
    out, cur = [], None
    for l in lines:
        if l.startswith('## '):
            cur = l[2:].strip() if l.lower().startswith('## vip') else None
        elif cur and l.startswith('- '):
            out.append({'name': _vip_name(l), 'list': cur, 'detail': _vip_detail(l)} if full else {'name': _vip_name(l), 'list': cur})
    if not full:
        return out
    return out, [{'title': t, 'work': w} for _, t, w in _vip_sections(lines)]


VIP_NAME_RE = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ .'’-]){0,59}$")          # letters, spaces and . ' ’ - only
VIP_MAIL_RE = re.compile(r'^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$')
VIP_PHONE_RE = re.compile(r'^\+?[0-9][0-9 ]{5,19}$')
VIP_NOTE_RE = re.compile(r'^[^\n\r#`<>\[\]{}*_|\\]{0,160}$')      # one plain line: no headings, links, markup or code


def _vip_line(name, addr='', note='', detail=None):
    """The one shape the dashboard writes: "- Name – address (note)", "- Name (note)" or "- Name – detail"."""
    if detail is not None:
        detail = ' '.join(str(detail).split())
        if not VIP_NOTE_RE.match(detail):
            raise Bad('details can only be one plain line (no # ` < > [ ] { } * _ |), max 160')
        return '- ' + name + ((' ' + detail if detail.startswith('(') else ' – ' + detail) if detail else '')
    note = ' '.join(str(note or '').split()).strip('() ')
    if note and not VIP_NOTE_RE.match(note):
        raise Bad('a note can only be one plain line (no # ` < > [ ] { } * _ |), max 160')
    return '- ' + name + (' – ' + addr if addr else '') + (' (' + note + ')' if note else '')


def vip_action(action, p):
    """contacts.md is read as rules by every Claude run, and a VIP's name comes from a sender's display name – so only
    a plain name and a checked address or phone number are ever written, in one fixed shape: "- Name – address"."""
    require(p, 'name')
    name = ' '.join(str(p['name']).split())
    if not VIP_NAME_RE.match(name):
        raise Bad('a VIP name can only have letters, spaces and . \' - (max 60) – add this one in contacts.md yourself')
    new_name = ' '.join(str(p.get('new_name') or name).split())
    if action == 'vip_update' and not VIP_NAME_RE.match(new_name):
        raise Bad('a VIP name can only have letters, spaces and . \' - (max 60)')
    with LOCK:
        try:
            lines = open(CONTACTS_FILE, encoding='utf-8').read().split('\n')
        except OSError:
            lines = ['# Axella – contact tiers', '']
        secs = _vip_sections(lines)
        have = [i for i, l in enumerate(lines) if l.startswith('- ') and _vip_name(l).lower() == name.lower()
                and any(h < i and all(not x.startswith('## ') for x in lines[h + 1:i]) for h, _, _ in secs)]
        target = next((x for x in secs if x[1] == p.get('list')), None) if p.get('list') else None
        if p.get('list') and not target:
            raise Bad('no such VIP list in contacts.md')
        if action == 'vip_remove':
            if not have:
                raise Bad('not on the VIP list')
            for i in reversed(have):
                del lines[i]
        elif action == 'vip_update':                 # Settings → VIPs: rename, change the details, or move to another list
            if len(have) != 1:
                raise Bad('not on the VIP list' if not have else 'this name is on the VIP lists twice – edit contacts.md yourself')
            i = have[0]
            if new_name.lower() != name.lower() and any(_vip_name(lines[j]).lower() == new_name.lower() for j in range(len(lines))
                                                        if lines[j].startswith('- ') and any(h < j and all(not x.startswith('## ') for x in lines[h + 1:j]) for h, _, _ in secs)):
                raise Bad(new_name + ' is already a VIP')
            entry = _vip_line(new_name, detail=p.get('detail') if 'detail' in p else _vip_detail(lines[i]))
            own = next(h for h, _, _ in reversed(secs) if h < i)
            if not target or target[0] == own:
                lines[i] = entry
            else:
                del lines[i]
                secs = _vip_sections(lines)
                target = next(x for x in secs if x[1] == p.get('list'))
                j = target[0] + 1
                while j < len(lines) and not lines[j].startswith('## '):
                    j += 1
                while j > target[0] + 1 and not lines[j - 1].strip():
                    j -= 1
                lines.insert(j, entry)
        else:
            if have:
                return 'already'
            work = p.get('ctx') == 'work'
            sec = target or next((x for x in secs if x[2] == work), None) or (secs[0] if secs else None)
            addr = str(p.get('address') or '').strip()
            if addr and not (VIP_MAIL_RE.match(addr) or VIP_PHONE_RE.match(addr)):
                if p.get('strict'):
                    raise Bad('that is not an e-mail address or a phone number')
                addr = ''                            # not a plain address or number (e.g. a group id): leave it out
            entry = _vip_line(name, addr, p.get('note') or '')
            if not sec:
                lines += ['', '## VIP', entry]
            else:
                j = sec[0] + 1                       # after the last line of that section
                while j < len(lines) and not lines[j].startswith('## '):
                    j += 1
                k = j
                while k > sec[0] + 1 and not lines[k - 1].strip():
                    k -= 1
                lines.insert(k, entry)
        tmp = CONTACTS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        os.replace(tmp, CONTACTS_FILE)
    return action


def require(payload, *keys):
    for k in keys:
        v = payload.get(k)
        if not isinstance(v, str) or not v.strip():
            raise Bad(f'missing {k}')
        if len(v) > 20000:
            raise Bad(f'{k} too long')


def ctx_action(p):
    kind, key, value = p.get('kind'), (p.get('key') or '').strip().lower(), p.get('value')
    if kind not in ('sender', 'domain', 'item') or not key or len(key) > 200:
        raise Bad('bad key')
    if value not in ('work', 'private', None):
        raise Bad('bad value')
    with LOCK:
        data = load_json(CTX_FILE, {'sender': {}, 'domain': {}, 'item': {}, 'log': []})
        for k in ('sender', 'domain', 'item'):
            data.setdefault(k, {})
        data.setdefault('log', [])
        if value is None:
            data[kind].pop(key, None)
        else:
            data[kind][key] = value
        data['log'].append({'at': now_iso(), 'kind': kind, 'key': key, 'value': value,
                            'was': p.get('was'), 'label': (p.get('label') or '')[:200]})
        data['log'] = data['log'][-500:]
        tmp = CTX_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, CTX_FILE)
    return 'saved'


# ---------------------------------------------------------------- Web Push
# Needs: /usr/bin/python3 -m pip install --user pywebpush   (keys are generated on first use)

def _b64url(b):
    import base64
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode()


def vapid_keys():
    data = load_json(VAPID_FILE, None)
    if data:
        return data
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    data = {'private_pem': pem, 'public_key': _b64url(pub)}
    with open(VAPID_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    os.chmod(VAPID_FILE, 0o600)
    return data


def push_send(payload):
    """Send payload to every subscription; drop subscriptions the push service says are gone."""
    from pywebpush import webpush, WebPushException
    from py_vapid import Vapid
    keys = vapid_keys()
    vapid = Vapid.from_pem(keys['private_pem'].encode())   # pywebpush's string form wants raw DER, not PEM
    with LOCK:
        subs = load_json(PUSH_SUBS_FILE, [])
    keep, sent = [], 0
    for sub in subs:
        try:
            webpush(subscription_info=sub['subscription'], data=json.dumps(payload),
                    vapid_private_key=vapid, vapid_claims={'sub': config().get('push_contact') or 'mailto:axella@example.com'}, ttl=3600)
            sent += 1
            keep.append(sub)
        except WebPushException as e:
            code = getattr(e.response, 'status_code', None)
            if code not in (404, 410):
                keep.append(sub)
            sys.stderr.write('%s push failed (%s): %s\n' % (now_iso(), code, str(e)[:200]))
    if len(keep) != len(subs):
        with LOCK:
            with open(PUSH_SUBS_FILE, 'w', encoding='utf-8') as f:
                json.dump(keep, f, indent=1)
    # the activity log gets the kind of notification only – never its text (names, summaries)
    tag = str(payload.get('tag') or '')
    kind = next((v for k, v in PUSH_KINDS if tag.startswith(k)), 'notification')
    log_auto('push', '%s → %s' % (kind, plural(sent, 'device')), 'ok' if sent else 'error: no device reached')
    return sent


PUSH_KINDS = (('axella-private', 'private message'), ('axella-call', 'call'), ('axella-watchdog', 'Axella paused/back'),
              ('axella-test', 'test'), ('axella-privacy', 'privacy settings'), ('axella-p0', 'urgent'), ('axella-digest', 'digest'),
              ('axella-run', 'run failed'), ('axella-missing', 'digest missing'), ('axella-ooo', 'out of office'),
              ('axella-reminder', 'reminder'), ('axella-brief', 'briefing'), ('axella-scheduled', 'send later missed'), ('axella-', 'digest'))


def digest_payload(name):
    """Push title/body for a new digest. Leaves out items already Done/snoozed on the dashboard; overdue counted on its own."""
    d = load_json(os.path.join(DIGESTS_DIR, name), {})
    state = load_json(STATE_FILE, {})
    now = datetime.datetime.now().astimezone()

    def handled(i):
        st = state.get(str(i.get('id'))) or {}
        if st.get('status') == 'done':
            return True
        if st.get('status') == 'snoozed':
            try:
                return datetime.datetime.fromisoformat(st.get('until', '').replace('Z', '+00:00')) > now
            except ValueError:
                return False
        return False

    items = [i for i in d.get('items', []) if not handled(i)]
    # urgent items an earlier P0 check already pushed today (same id or same mail) are not "new" in this digest
    pushed_ids, pushed_mids = set(), set()
    if not name.endswith('-p0.json'):
        for n in os.listdir(DIGESTS_DIR):
            if n.endswith('-p0.json') and n[:10] == name[:10]:
                for i in load_json(os.path.join(DIGESTS_DIR, n), {}).get('items', []):
                    pushed_ids.add(str(i.get('id')))
                    if i.get('message_id'):
                        pushed_mids.add(i['message_id'])
    already = lambda i: str(i.get('id')) in pushed_ids or (i.get('message_id') and i['message_id'] in pushed_mids)
    overdue = [i for i in items if i.get('overdue') and i.get('section') in ('p1', 'p2', 'open')]
    cnt = lambda sec: sum(1 for i in items if i.get('section') == sec and not i.get('overdue'))
    stem = name[:-5]
    hhmm = stem[11:13] + ':' + stem[13:15] if len(stem) >= 15 else ''
    kind = d.get('kind', 'digest')
    p0 = [i for i in items if i.get('section') == 'p0' and not already(i)]
    p0_old = sum(1 for i in items if i.get('section') == 'p0' and already(i))
    if p0:
        first = p0[0].get('headline', '') or f'{len(p0)} urgent'
        more = f' (+{len(p0) - 1} more)' if len(p0) > 1 else ''
        title, body = '⚠ Axella – urgent', first + more
    elif kind == 'p0':
        return None                      # urgent alert already handled on the dashboard – stay quiet
    elif kind == 'week':
        title = 'Axella – week ahead'
        parts = [f'{len(overdue)} overdue' if overdue else '', f"{cnt('open')} still open" if cnt('open') else '',
                 f"{cnt('wait')} waiting" if cnt('wait') else '', f"{cnt('cal')} calendar notes" if cnt('cal') else '']
        body = ' · '.join(p for p in parts if p) or 'A quiet week ahead'
    else:
        title = f'Axella {hhmm}'.strip()
        parts = [f'{p0_old} urgent' if p0_old else '', f'{len(overdue)} overdue' if overdue else '',
                 f"{cnt('p1')} before noon" if cnt('p1') else '', f"{cnt('p2')} today" if cnt('p2') else '',
                 f"{cnt('open')} still open" if cnt('open') else '', f"{cnt('wait')} waiting" if cnt('wait') else '']
        body = ' · '.join(p for p in parts if p) or 'Nothing needs you right now'
    return {'title': title, 'body': body, 'url': '/axella/?d=' + stem + '.md', 'tag': 'axella-' + stem,
            'badge': badge_count(items, handled)}


def badge_count(items, handled):
    """The number on the Home Screen icon – what the dashboard's title counts: replies (urgent, before noon, today),
    overdue waiting-for, open calls and tasks due today or overdue. The dashboard corrects it whenever it is open."""
    n = sum(1 for i in items if i.get('section') in ('p0', 'p1', 'p2'))
    n += sum(1 for i in items if i.get('section') == 'wait' and i.get('overdue'))
    today = datetime.date.today().isoformat()
    try:
        n += sum(1 for t in load_json(TASKS_FILE, []) if isinstance(t, dict) and t.get('status') != 'done'
                 and t.get('due') and str(t['due']) <= today)
    except Exception:
        pass
    calls = os.path.join(BASE, 'calls')
    try:
        for f in os.listdir(calls):
            if f.endswith('.json') and f not in ('config.json', 'live.json'):
                c = load_json(os.path.join(calls, f), {})
                if isinstance(c, dict) and c.get('id') and not handled(c):
                    n += 1
    except OSError:
        pass
    return min(n, 999)


def push_watcher():
    """Every 30 s: notify once per new digest .json (ignores _trial/ and anything older than the last one sent)."""
    import time
    while True:
        try:
            busy = RUNNER.writing_since()

            def unfinished(n):
                """Written by the digest or P0 run still going (its scope check comes at the end), or modified in
                the last 10 s: not yet – the scope check runs first, then the scam check, then the push."""
                try:
                    mt = os.path.getmtime(os.path.join(DIGESTS_DIR, n))
                except OSError:
                    return True
                return bool(busy and mt >= busy - 1) or time.time() - mt < 10
            try:
                SAFETY.scan_new(skip=unfinished)   # scam check + Always hold, before a digest is pushed or shown
            except Exception as e:
                sys.stderr.write('%s safety: %s\n' % (now_iso(), str(e)[:200]))
            last = load_json(PUSH_LAST_FILE, {}).get('name')
            names = sorted(n for n in os.listdir(DIGESTS_DIR) if n.endswith('.json') and n[:4].isdigit())
            if names:
                newest = names[-1]
                if last is None:
                    last = newest          # first start: don't notify for old digests
                    with open(PUSH_LAST_FILE, 'w') as f:
                        json.dump({'name': last, 'at': now_iso()}, f)
                for n in [n for n in names if n > last]:
                    if unfinished(n):
                        break              # next round, once its run has ended (and the scope check has run)
                    try:
                        SAFETY.scan_digest(n)
                    except Exception as e:
                        sys.stderr.write('%s safety: %s\n' % (now_iso(), str(e)[:200]))
                    try:
                        _learn_digest(n)           # Teach Axella: your section rules, and filing by your file rules
                    except Exception as e:
                        sys.stderr.write('%s learned rules: %s\n' % (now_iso(), str(e)[:200]))
                    try:
                        RECUR.add_to_digest(n)     # one quiet line in the morning digest for new subscription changes
                    except Exception as e:
                        sys.stderr.write('%s recurring: %s\n' % (now_iso(), str(e)[:200]))
                    try:
                        BLOCKS.add_to_digest(DIGESTS_DIR, n, _block_events, _work_hours())   # at most one "hold a free block?"
                    except Exception as e:
                        sys.stderr.write('%s blocks line: %s\n' % (now_iso(), str(e)[:200]))
                    try:
                        RENEW.add_to_digest(DIGESTS_DIR, n)   # one line when a renewal reaches its lead time
                    except Exception as e:
                        sys.stderr.write('%s renewals line: %s\n' % (now_iso(), str(e)[:200]))
                    try:
                        _bills.add_to_digest(BILLS, DIGESTS_DIR, n, lambda: load_json(TASKS_FILE, []))   # bills due this week
                    except Exception as e:
                        sys.stderr.write('%s bills: %s\n' % (now_iso(), str(e)[:200]))
                    try:
                        _trips_to_digest(n)        # trip changes, cancellations, check-in opening (each once)
                    except Exception as e:
                        sys.stderr.write('%s trips line: %s\n' % (now_iso(), str(e)[:200]))
                    try:
                        PEOPLE.add_to_digest(DIGESTS_DIR, n, _keep_due)   # at most one keep-in-touch line, private world
                    except Exception as e:
                        sys.stderr.write('%s keep in touch: %s\n' % (now_iso(), str(e)[:200]))
                    briefing = False
                    try:
                        briefing = AWAY.add_to_digest(DIGESTS_DIR, n, lambda: load_json(STATE_FILE, {}))   # "Sorted itself out"
                    except Exception as e:
                        sys.stderr.write('%s away briefing: %s\n' % (now_iso(), str(e)[:200]))
                    payload = None if briefing else digest_payload(n)   # calm: no push for the briefing itself
                    if payload and load_json(PUSH_SUBS_FILE, []):
                        push_send(payload)
                    with open(PUSH_LAST_FILE, 'w') as f:
                        json.dump({'name': n, 'at': now_iso()}, f)
        except ImportError:
            pass                           # pywebpush not installed yet
        except Exception as e:
            sys.stderr.write('%s push watcher: %s\n' % (now_iso(), str(e)[:200]))
        time.sleep(30)


PRIVATE_SEEN_FILE = os.path.join(STATE_DIR, 'private-notified.json')
CH_NAME = {'signal': 'Signal', 'whatsapp': 'WhatsApp', 'imessage': 'iMessage', 'mail': 'Mail', 'calls': 'the call agent'}


def private_payloads(inbox, seen, discreet):
    """Pushes for private chats with something new since the last push: who and where only – Axella never has the
    text. Returns (payloads, updated seen)."""
    out, now_seen = [], dict(seen)
    for ch, part in (inbox or {}).items():
        for r in (part or {}).get('chats') or []:
            key = '%s:%s' % (ch, r.get('contact') or r.get('name'))
            last = r.get('last_at') or ''
            if not last or last <= seen.get(key, ''):
                continue
            now_seen[key] = last
            if r.get('last_from_me') or not (r.get('unread') or r.get('waiting')):
                continue                                # you wrote last, or already read on the phone
            n = r.get('unread') or r.get('waiting') or 1
            where = CH_NAME.get(ch, ch)
            out.append({'title': 'Private message' if discreet else '🔒 ' + (r.get('name') or 'Private contact'),
                        'body': ('%d new private message%s on %s' % (n, '' if n == 1 else 's', where)) if discreet
                                else '%d new on %s – not read by Axella' % (n, where),
                        'url': '/axella/', 'tag': 'axella-private-' + re.sub(r'[^\w-]', '', key)[:60]})
    return out, now_seen


PRIVACY_ALERT = {'broken': False, 'sent': False}


def private_watcher():
    """Every 30 s: a push for a new message from a private contact (state/private-inbox.json, filled by the exporters).
    The first round after a start only remembers what is there. Off with Settings → Private contacts → Notify me."""
    import time
    first = True
    while True:
        try:
            broken = PRIV.broken()
            if broken != PRIVACY_ALERT['broken']:           # one push when privacy.json becomes unreadable, one when fixed
                PRIVACY_ALERT['broken'] = broken
                if broken or PRIVACY_ALERT['sent']:
                    PRIVACY_ALERT['sent'] = broken
                    if load_json(PUSH_SUBS_FILE, []):
                        push_send({'title': "Axella can't read your privacy settings" if broken else 'Privacy settings readable again',
                                   'body': ('Everyone is treated as private until state/privacy.json is fixed – see System status.'
                                            if broken else 'Private contacts work as set again.'),
                                   'url': '/axella/?v=status', 'tag': 'axella-privacy'})
            inbox = load_json(os.path.join(STATE_DIR, 'private-inbox.json'), {})
            seen = load_json(PRIVATE_SEEN_FILE, {})
            payloads, seen2 = private_payloads(inbox, seen, PRIV.load().get('discreet_push'))
            if seen2 != seen:
                with open(PRIVATE_SEEN_FILE + '.tmp', 'w', encoding='utf-8') as f:
                    json.dump(seen2, f)
                os.chmod(PRIVATE_SEEN_FILE + '.tmp', 0o600)
                os.replace(PRIVATE_SEEN_FILE + '.tmp', PRIVATE_SEEN_FILE)
            if payloads and not (first and not seen) and PRIV.load().get('notify') and load_json(PUSH_SUBS_FILE, []):
                for pl in payloads[:5]:
                    push_send(pl)
        except ImportError:
            pass                                        # pywebpush not installed yet
        except Exception as e:
            sys.stderr.write('%s private watcher: %s\n' % (now_iso(), str(e)[:200]))
        first = False
        time.sleep(30)


def push_action(action, p):
    if action == 'push_subscribe':
        sub = p.get('subscription')
        if not isinstance(sub, dict) or not str(sub.get('endpoint', '')).startswith('https://'):
            raise Bad('bad subscription')
        with LOCK:
            subs = [s for s in load_json(PUSH_SUBS_FILE, []) if s['subscription'].get('endpoint') != sub['endpoint']]
            subs.append({'subscription': sub, 'device': (p.get('device') or '')[:80], 'at': now_iso()})
            with open(PUSH_SUBS_FILE, 'w', encoding='utf-8') as f:
                json.dump(subs, f, indent=1)
            os.chmod(PUSH_SUBS_FILE, 0o600)
        return 'subscribed'
    if action == 'push_unsubscribe':
        ep = p.get('endpoint', '')
        with LOCK:
            subs = [s for s in load_json(PUSH_SUBS_FILE, []) if s['subscription'].get('endpoint') != ep]
            with open(PUSH_SUBS_FILE, 'w', encoding='utf-8') as f:
                json.dump(subs, f, indent=1)
        return 'unsubscribed'
    if action == 'push_test':
        n = push_send({'title': 'Axella', 'body': 'Test notification – tap to open the dashboard', 'url': '/axella/', 'tag': 'axella-test'})
        return 'sent to %s' % plural(n, 'device')
    raise Bad('unknown action')


def do_action(action, p):
    if action.startswith(('report_', 'triage_')):
        try:
            return report_action(action, p)
        except reports_mod.Bad as e:
            raise Bad(str(e))
    if action == 'pics_sender':
        return pics_sender_set(p.get('address'), bool(p.get('on')))
    if action == 'privacy_set':
        try:
            return PRIV.set(p)
        except PrivacyBad as e:
            raise Bad(str(e))
    if action in ('briefing_save', 'briefing_delete'):
        try:
            return BRIEF.save(p) if action == 'briefing_save' else BRIEF.delete(str(p.get('id') or ''))
        except BriefingsBad as e:
            raise Bad(str(e))
    if action in ('run_now', 'run_cancel', 'scheduler_set', 'doctor_run', 'compose', 'ask', 'briefing_run'):
        try:
            return RUNNER.action(action, p)
        except RunnerBad as e:
            raise Bad(str(e))
    if action.startswith('push_'):
        try:
            return push_action(action, p)
        except ImportError as e:
            raise Bad('push library missing on the Mac mini (%s, python %s)' % (e, sys.version.split()[0]))
    if action == 'ctx_set':
        return ctx_action(p)
    if action == 'task_suggest':
        return task_suggest(p)
    if action == 'compose_assist':
        return compose_assist(p)
    if action.startswith('meeting_'):
        return meeting_action(action, p)
    if action == 'invite_respond':
        try:
            return invite_respond(p)
        finally:
            _PENDING['data'] = None
    if action == 'invite_dismiss':
        return invite_dismiss(p)
    if action.startswith('promise_') or action in ('replydebt_never', 'replydebt_done'):
        return promise_action(action, p)
    if action in ('schedule_send', 'schedule_update', 'schedule_cancel', 'schedule_now'):
        return schedule_action(action, p)
    if action == 'trip_scan':
        if TRIPS.status.get('running'):
            return {'running': True}
        since = None
        if p.get('since'):                                 # "Scan since": a date you pick, at most 18 months back
            try:
                since = datetime.date.fromisoformat(str(p['since'])[:10])
            except ValueError:
                raise Bad('give the date as YYYY-MM-DD')
            if since > datetime.date.today() or (datetime.date.today() - since).days > trips.SCAN_DAYS:
                raise Bad('a date in the last 18 months')
            TRIPS.set_since(since)
        threading.Thread(target=trip_scan, daemon=True).start()
        return {'started': True, 'since': since.isoformat() if since else None}
    if action in ('trip_mail_add', 'trip_mail_new', 'trip_item_add') and isinstance(p.get('mail'), dict):
        # a mail picked with "Add a mail…": one of your accounts, never a private contact's; a protected workplace's
        # mail keeps only who and when (your own title for it)
        m = p['mail']
        if m.get('account') not in config().get('accounts', {}):
            raise Bad('account not allowed')
        addrs = meeting_mail_addresses(m.get('from'), m.get('message_id'))
        if mail_privacy(addrs)[0]:
            raise Bad('This mail involves a private contact – Axella doesn\'t use it.')
        if any(profile.is_protected(m['account'], a) for a in addrs if a):
            m['subject'] = ''
    if action == 'trip_read':
        # Claude reads the booking mails you picked (and their PDF tickets) – only mails Axella already lists on the
        # Trips page, never a private contact's or a protected workplace's; one read-only run, on your tap
        want = [str(x)[:500] for x in (p.get('message_ids') or []) if x][:40]
        if not want:
            raise Bad('pick the mails to read')
        if RUNNER.trip_read_busy():
            raise Bad('Axella is already reading booking mails – a moment')
        d = TRIPS.load()
        known = {}
        for m in d['unsorted']:
            known[m.get('message_id')] = m
        for t in d['trips'] + d['suggested']:
            for b in t['bookings'] + t.get('new', []):
                if (b.get('source') or {}).get('message_id'):
                    known.setdefault(b['source']['message_id'], b['source'])
        mails = []
        for mid in want:
            m = known.get(mid)
            if not m or m.get('account') not in config().get('accounts', {}):
                continue
            addrs = meeting_mail_addresses(m.get('from'), mid, strict=True)    # the mail file must be found: fails closed
            if not addrs or mail_privacy(addrs)[0] or any(profile.is_protected(m['account'], a) for a in addrs if a):
                continue
            try:
                sender, when = mailsearch.sender_of(mailsearch.path_for_mid(mid))
            except Exception:
                sender, when = '', ''
            # Macuse finds a mail by subject + sender ADDRESS + date received – a display name ("ACME AIR") finds nothing
            mails.append({'account': m['account'], 'message_id': mid, 'subject': str(m.get('subject') or '')[:200],
                          'sender': sender, 'date': when or m.get('date'), 'from': m.get('from')})
        if not mails:
            raise Bad('none of these mails can be read here')
        rid = RUNNER.trip_read_request(mails)
        TRIPS.status.update(reading=rid, reading_n=len(mails), read_error=None)
        return {'id': rid, 'mails': len(mails)}
    if action in ('trip_cal_add', 'trip_cal_sync', 'trip_cal_remove'):
        return trip_calendar(action, p)
    if action.startswith('trip_check_'):              # the documents checklist: trip-checklists.json (SECRETS)
        p['title'] = 'Trip checklist'                  # the item's text never goes into the activity log
        try:
            return TRIP_CHECKS.action(action, p, {t['id'] for t in TRIPS.load()['trips']})
        except trips.Bad as e:
            raise Bad(str(e))
    if action.startswith('trip_'):
        try:
            r = TRIPS.action(action, p)
        except trips.Bad as e:
            raise Bad(str(e))
        if r.get('backup'):
            p['_backup'] = r['backup']                     # Restore in the activity log
        p.setdefault('title', r.get('title') or '')
        return r
    if action == 'birthday_show':
        # "Show birthday" on a contact card: on/off for this person (Favourites are on unless switched off)
        cid = str(p.get('id') or '')
        if cid not in {x.get('id') for x in BOOK.overview()['people'] if x.get('id')}:
            raise Bad('unknown contact')
        BDAY.set_show(cid, bool(p.get('on')))
        BDAY.write_today(BOOK.overview()['people'])
        return {'id': cid, 'on': bool(p.get('on'))}
    if action.startswith('contact_'):
        import contacts_book as _cb
        try:
            return _cb.edit(BOOK, action, p, os.path.join(BACKUP_DIR, 'contacts'))
        except _cb.EditError as e:
            raise Bad(str(e))
    if action in ('meeting_service_connect', 'meeting_service_disconnect', 'meeting_service_default',
                  'cal_invite_send', 'cal_invite_update', 'cal_invite_cancel'):
        return online_action(action, p)
    if action == 'cal_add' and (p.get('online') or {}).get('kind') not in (None, 'none'):
        try:                                       # no invitees, but an online meeting: made on this tap, its link on the event
            join = ONLINE.add_meeting(p)
        except _oauth.Bad as e:
            raise Bad(str(e))
        if join:
            p['url'] = join['join_url']
            info = ['Join: ' + join['join_url']] + (['Passcode: %s' % join['passcode']] if join.get('passcode') else [])
            p['notes'] = '\n'.join(info) + ('\n\n' + str(p.get('notes') or '') if p.get('notes') else '')
    if action.startswith('cal_'):
        import calendar_view as _cv
        _PENDING['data'] = None
        try:
            return _cv.edit(RUNNER.mcp_file(), config().get('calendars') or [], action, p, os.path.join(BACKUP_DIR, 'events'),
                            cache_file=os.path.join(STATE_DIR, 'macuse-calendar-tools.json'))
        except _cv.CalendarError as e:
            raise Bad(str(e))
    if action in ('recipients_set', 'document_forward', 'vendor_auto_forward'):
        try:
            return FWD.action(action, p)
        except (ForwardBad, DocumentsBad) as e:
            raise Bad(str(e))
    if action in ('sender_unsubscribe', 'sender_keep', 'sender_hold', 'senders_quiet_dismiss'):
        try:
            return SUBS.action(action, p)
        except SubsBad as e:
            raise Bad(str(e))
    if action in ('recurring_set', 'recurring_seen'):
        try:
            return RECUR.action(action, p)
        except _recurring.Bad as e:
            raise Bad(str(e))
    if action == 'recurring_scan':
        _RECUR_KICK.set()
        return {'message': 'Checking Receipts and your mail for subscriptions – a minute or two'}
    if action in ('safety_mark_safe', 'safety_unmark_safe'):
        try:
            return SAFETY.action(action, p)
        except _safety.Bad as e:
            raise Bad(str(e))
    if action in ('document_set', 'document_hide'):
        try:
            return DOCS.action(action, p)
        except DocumentsBad as e:
            raise Bad(str(e))
    if action in ('schedule_set', 'sweep_request', 'sweep_cancel'):
        try:
            return SCHED.action(action, p, p.get('_login', ''))
        except (ScheduleBad, ValueError) as e:
            raise Bad(str(e))
    if action in PROJECT_MAIL_ACTIONS:
        return project_mail_action(action, p)
    if action.startswith('renewal_'):
        return renewal_action(action, p)
    if action.startswith('backup_'):
        return backup_action(action, p)
    if action.startswith('away_'):
        return away_action(action, p)
    if action.startswith('block_'):
        return block_action(action, p)
    if action.startswith('project_'):
        try:
            return PROJ.action(action, p)
        except ProjectBad as e:
            raise Bad(str(e))
    if action.startswith('ooo_'):
        try:
            return OOO.action(action, p)
        except OooBad as e:
            raise Bad(str(e))
    if action.startswith('task_'):
        return task_action(action, p)
    if action in ('vip_add', 'vip_remove', 'vip_update'):
        return vip_action(action, p)
    if action.startswith('kb_scan_') or action == 'kb_nightly':
        try:
            return HARVEST.action(action, p)
        except HarvestBad as e:
            raise Bad(str(e))
    if action.startswith('kb_'):
        try:
            return KB.action(action, p)
        except KnowledgeBad as e:
            raise Bad(str(e))
    if action.startswith('cleanup_'):
        try:
            return CLEAN.action(action, p)
        except CleanupBad as e:
            raise Bad(str(e))
    if action.startswith('reminder_'):
        try:
            return REM.action(action, p)
        except RemindersBad as e:
            raise Bad(str(e))
    cfg = config()
    accounts = cfg.get('accounts', {})
    if action in ('reply_send', 'mail_send'):
        if p.get('confirm') != 'send':
            raise Bad('send needs your confirmation')
        require(p, 'account', 'text')
        if p['account'] not in accounts:
            raise Bad('account not allowed')
        text = p['text'].strip()
        if len(text) > 20000:
            raise Bad('text too long')
        import hashlib
        rc = recipients(p) if action == 'reply_send' else None
        if action == 'reply_send' and rc:
            require(p, 'message_id')
            expect = ', '.join(rc[0] + rc[1] + rc[2])
            key = 'item:' + str(p.get('item_id') or p['message_id'])
        elif action == 'reply_send':
            require(p, 'message_id', 'expect_to')
            expect = str(p['expect_to']).strip().lower()
            if NO_REPLY.match(expect):
                raise Bad('%s is a no-reply address – nobody reads replies to it' % expect)
            key = 'item:' + str(p.get('item_id') or p['message_id'])
        else:
            require(p, 'to', 'subject')
            # one address – or several (To, and Cc), comma-separated: a meeting follow-up to everyone who was there
            tos, ccs = new_recipients(p.get('to')), new_recipients(p.get('cc') or '')
            multi = len(tos) > 1 or bool(ccs)
            to = ', '.join(tos)
            key = 'new:' + hashlib.sha1((to.lower() + '|' + ', '.join(ccs).lower() + '|' + str(p['subject']).strip()).encode()).hexdigest()[:16]
        now = time.time()
        with LOCK:
            sent = load_json(SENT_FILE, [])
            if len([x for x in sent if now - _sent_ts(x) < 3600]) >= SEND_MAX:
                raise Bad(f'more than {SEND_MAX} mails in an hour – wait a little, or send from Mail')
            # the same reply twice within 10 minutes only on purpose ("send again" in the dashboard)
            last = next((x for x in reversed(sent) if x.get('key') == key and now - _sent_ts(x) < 600), None)
            if last and not p.get('force'):
                raise Bad('already sent %s ago%s – tap "Send again" if you really want a second one'
                          % (plural(max(1, int((now - _sent_ts(last)) // 60)), 'minute'), '' if last.get('status', 'sent') == 'sent'
                             else ' (Mail didn\'t confirm it – check Sent first)'))
        files = outbox_paths(p.get('attachments'))

        def record(status, to):
            with LOCK:
                sent = load_json(SENT_FILE, [])
                sent.append({'at': now_iso(), 'ts': time.time(), 'status': status, 'key': key, 'action': action,
                             'account': p['account'], 'to': to, 'reply_to': p.get('message_id'),
                             'subject': str(p.get('subject') or p.get('title') or '')[:200],
                             'item_id': p.get('item_id'), 'attachments': [os.path.basename(f) for f in files]})
                with open(SENT_FILE, 'w', encoding='utf-8') as f:
                    json.dump(sent[-1000:], f, ensure_ascii=False, indent=1)
        try:
            if action == 'reply_send':
                try:                               # quote the original under the answer, like Mail does
                    pv = message_preview(p['account'], p['message_id'])
                    lines = pv['body'].split('\n')[:300]
                    text += f"\n\nOn {pv['date']}, {pv['from']} wrote:\n\n" + '\n'.join('> ' + l if l else '>' for l in lines)
                except Exception:
                    pass
                if rc:                             # the composer's To / Cc / Bcc, set and checked in Mail before sending
                    res, _, got = osa(SEND_REPLY_TO_SCRIPT, p['account'], p['message_id'], text, rcpt_arg(rc[0]), rcpt_arg(rc[1]),
                                      rcpt_arg(rc[2]), rcpt_expected(*rc), *files, timeout=120 + 10 * len(files)).partition('\x1f')
                    if res == 'mismatch':
                        raise Bad('Mail didn\'t take the recipients as confirmed – nothing was sent. Try again, or send from Mail.')
                    to = expect
                else:
                    res, _, to = osa(SEND_REPLY_SCRIPT, p['account'], p['message_id'], text, expect, *files,
                                     timeout=120 + 10 * len(files)).partition('\x1f')
                    to = to.strip()
                    if res == 'mismatch':              # Reply-To points somewhere else: nothing was sent
                        raise Bad('replies to this mail go to %s, not %s – check before sending'
                                  % (to or 'another address', expect))
            elif multi:                            # several recipients: set, read back and compared before Mail sends
                res = osa(SEND_NEW_MULTI_SCRIPT, p['account'], rcpt_arg(tos), rcpt_arg(ccs), str(p['subject'])[:300], text,
                          str((accounts.get(p['account']) or {}).get('address') or ''), rcpt_expected(tos, ccs, []), *files,
                          timeout=120 + 10 * len(files))
                if str(res).startswith('mismatch'):
                    record('not sent', to)
                    raise Bad('Mail didn\'t take the recipients as given – nothing was sent')
            else:
                res = osa(SEND_NEW_SCRIPT, p['account'], to, str(p['subject'])[:300], text,
                          str((accounts.get(p['account']) or {}).get('address') or ''), *files,
                          timeout=120 + 10 * len(files))
        except RuntimeError as e:
            if 'did not answer' in str(e):         # Mail may still have sent it: count it, and say so
                record('unknown', expect if action == 'reply_send' else to)
                raise Bad('Mail didn\'t confirm in time – it may have sent anyway. Check Sent in Mail before sending again.')
            raise
        if res != 'sent':
            record('unknown', to)
            raise Bad('Mail did not confirm sending – check Sent in Mail before trying again')
        outbox_clear(files)
        record('sent', to)
        if action == 'reply_send':
            _tidy(p)                                   # Keep Mail tidy: the mail you answered is read in Mail
            _habit('reply', p, p.get('sender'))
        with LOCK:
            dr = load_json(DRAFTS_FILE, {})
            if p.get('item_id') in dr:
                dr[p['item_id']]['sent'] = now_iso()
                with open(DRAFTS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(dr, f, ensure_ascii=False, indent=1)
        if p.get('item_id'):                           # answered → handled
            set_state(p['item_id'], {'status': 'done', 'at': now_iso(), 'title': p.get('title', ''), 'how': 'sent'})
        return {'status': 'sent', 'to': to}
    if action == 'draft_new':
        require(p, 'account', 'to', 'subject', 'text')
        if p['account'] not in accounts:
            raise Bad('account not allowed')
        to = str(p['to']).strip()
        if '@' not in to or any(c in to for c in ' <>",;\n'):
            raise Bad('one e-mail address only')
        res = osa(DRAFT_NEW_SCRIPT, p['account'], to, str(p['subject'])[:300], str(p['text']).strip(), timeout=120)
        if res != 'saved':
            raise Bad('Mail did not confirm the draft – check Drafts in a minute, or try again')
        return res
    if action == 'draft':
        require(p, 'account', 'message_id', 'text')
        if p['account'] not in accounts:
            raise Bad('account not allowed')
        text = p['text'].strip()
        try:                                   # quote the original under the answer, like Mail does
            pv = message_preview(p['account'], p['message_id'])
            lines = pv['body'].split('\n')[:300]
            text += f"\n\nOn {pv['date']}, {pv['from']} wrote:\n\n" + '\n'.join('> ' + l if l else '>' for l in lines)
        except Exception:
            pass
        rc = recipients(p)
        extra = [rcpt_arg(rc[0]), rcpt_arg(rc[1]), rcpt_arg(rc[2])] if rc else []
        res, _, did = osa(DRAFT_SCRIPT, p['account'], p['message_id'], text, *extra, timeout=120).partition('\x1f')
        if res == 'saved':
            # remember the saved draft: "Open in Mail" now, "still unsent?" later
            with LOCK:
                dr = load_json(DRAFTS_FILE, {})
                dr[str(p.get('item_id') or p['message_id'])[:200]] = {
                    'draft_id': did.strip(), 'account': p['account'], 'reply_to': p['message_id'],
                    'title': str(p.get('title') or '')[:200], 'saved': now_iso()}
                dr = dict(sorted(dr.items(), key=lambda kv: kv[1].get('saved', ''))[-300:])
                with open(DRAFTS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(dr, f, ensure_ascii=False, indent=1)
            return {'status': 'saved', 'draft_id': did.strip()}
        if res != 'saved':
            raise Bad('Mail did not confirm the draft – check Drafts in a minute, or try again')
        return res
    if action == 'file':
        require(p, 'account', 'message_id', 'folder')
        if p['account'] not in accounts:
            raise Bad('account not allowed')
        allowed = accounts.get(p['account'], {}).get('folders', [])
        if p['folder'] not in allowed and p['folder'] not in live_folders(p['account']):
            raise Bad('folder not allowed')
        res = osa(FILE_SCRIPT, p['account'], p['message_id'], p['folder'], timeout=120)
        if p.get('item_id'):
            set_state(p['item_id'], {'status': 'done', 'at': now_iso(), 'how': 'filed:' + p['folder']})
        _tidy(p)                                       # Keep Mail tidy: moved, and read
        _habit('file', p, p.get('from'), folder=p['folder'])
        if p.get('suggested') and p['suggested'] != p['folder'] and p.get('from'):
            # The owner picked another folder than suggested – remember it per sender for the next digests
            with LOCK:
                fl = load_json(FILING_FILE, {})
                fl[str(p['from']).lower()[:200]] = {'folder': p['folder'], 'account': p['account'],
                                                     'instead_of': p['suggested'], 'at': now_iso()}
                with open(FILING_FILE, 'w', encoding='utf-8') as f:
                    json.dump(fl, f, ensure_ascii=False, indent=1)
        return res
    if action == 'trash':
        # Mail's delete moves the message to the account's Trash / Deleted Items – recoverable, never permanent
        require(p, 'account', 'message_id')
        if p['account'] not in accounts:
            raise Bad('account not allowed')
        res = osa(TRASH_SCRIPT, p['account'], p['message_id'], timeout=120)
        if p.get('item_id'):
            set_state(p['item_id'], {'status': 'done', 'at': now_iso(), 'how': 'trash'})
        _tidy(p)                                       # Keep Mail tidy: in Trash, and read
        return res
    if action == 'trash_batch':
        # Filing suggestions → Delete: one job, at most TRASH_BATCH_MAX mails, one line in the activity log
        items = p.get('items')
        if not isinstance(items, list) or not items:
            raise Bad('nothing to delete')
        if len(items) > TRASH_BATCH_MAX:
            raise Bad('at most %d at a time' % TRASH_BATCH_MAX)
        for x in items:
            if not isinstance(x, dict) or not x.get('account') or not x.get('message_id'):
                raise Bad('each mail needs account and message_id')
            if x['account'] not in accounts:
                raise Bad('account not allowed')
        moved, failed = [], 0
        for x in items:
            try:
                osa(TRASH_SCRIPT, x['account'], str(x['message_id'])[:500], timeout=120)
            except Exception:
                failed += 1
                continue
            _tidy({'_login': p.get('_login'), 'account': x['account'], 'message_id': str(x['message_id'])[:500]})
            if x.get('item_id'):
                set_state(str(x['item_id'])[:200], {'status': 'done', 'at': now_iso(), 'how': 'trash'})
                moved.append(str(x['item_id'])[:200])
            else:
                moved.append(None)
        p['title'] = 'Moved %d of %d mails to Trash' % (len(moved), len(items)) if failed else 'Moved %d mails to Trash' % len(moved)
        p['_items'] = [i for i in moved if i]          # ids only, for the reports' "handled" count – no subjects
        return {'moved': len(moved), 'failed': failed}
    if action == 'event':
        require(p, 'calendar', 'title', 'start', 'end')
        if p['calendar'] not in profile.calendar_names(cfg):
            raise Bad('calendar not allowed')
        args = [p['calendar'], p['title'], p.get('location', ''), p.get('notes', 'Created from Axella')]
        res = osa(EVENT_SCRIPT, *args, *parts(p['start']), *parts(p['end']))
        import calendar_view
        calendar_view.invalidate()
        _PENDING['data'] = None
        if p.get('item_id'):
            set_state(p['item_id'], {'status': 'done', 'at': now_iso(), 'how': 'event'})
        return res
    if action == 'digest_seen':                       # the dashboard opened this digest (Your calm: digests read)
        _calm.mark_read(STATE_DIR, str(p.get('name') or ''), 'seen')
        return 'ok'
    if action == 'mail_seen':                         # Keep Mail tidy: opened in Axella's reader → read in Mail
        acc, mid = p.get('account'), p.get('message_id')
        if p.get('file'):                              # a mail found by Search: its account and id from the search token
            e = mailsearch._TOK.get(str(p['file'])[:100]) or {}
            acc, mid = e.get('account'), e.get('mid')
        _tidy({'_login': p.get('_login'), 'account': acc, 'message_id': mid})
        return 'ok'
    if action == 'should_have_reached':               # Your calm: "nothing missed" – this one should have been urgent
        require(p, 'item_id')
        r = _teach('reached', p)                       # Teach Axella: this sender or topic reaches you next time
        return {'message': 'Noted – it counts under "Nothing missed" in Insights', 'rule': r}
    if action == 'teach_not_important':               # Teach Axella: lower this one, or this sender / topic from now on
        require(p, 'item_id')
        if (p.get('why') or 'once') == 'once':
            lowered = _learned.Learned.lower_item(DIGESTS_DIR, str(p['item_id'])[:200])
            return {'message': 'Moved to FYI – just this once' if lowered else 'Noted – just this once', 'rule': None}
        return {'message': 'Noted', 'rule': _teach('not_important', p)}
    if action in ('note_save', 'note_keep', 'note_delete', 'note_restore', 'note_todo'):   # Notes (owner only)
        return note_action(action, p)
    if action in ('rule_remove', 'rule_restore'):     # Settings → Rules → Learned from you
        try:
            rid = str(p.get('id') or '')[:20]
            r = LEARN.remove(rid) if action == 'rule_remove' else LEARN.restore(rid)
        except _learned.Bad as e:
            raise Bad(str(e))
        try:
            _learn_side(r, action == 'rule_restore')
        except Exception as e:
            if action == 'rule_restore':
                LEARN.remove(r['id'])
            raise Bad('rule %s, but: %s' % ('removed' if action == 'rule_remove' else 'not restored', str(e)[:200]))
        p['title'] = _learned.plain(r)
        return {'id': r['id'], 'text': _learned.plain(r)}
    if action in ('suggest_accept', 'suggest_later', 'suggest_never'):   # the suggestion card (Today, the week wrap)
        try:
            spec = LEARN.respond(str(p.get('key') or '')[:300], action.split('_', 1)[1])
        except _learned.Bad as e:
            raise Bad(str(e))
        if not spec:
            return {'message': 'Not now – maybe in a week' if action == 'suggest_later' else 'Won\'t suggest this again'}
        try:
            r = LEARN.make(spec['kind'], sender=spec.get('sender'), value=spec.get('value'), label=spec.get('label'),
                           account=spec.get('account'), why='Suggested from your habits', source='suggestion',
                           ctx=_world_of(spec.get('account'), spec.get('sender') or ''))
        except _learned.Bad as e:
            raise Bad(str(e))
        _learn_side(r, True)
        LEARN.add(r)
        _learn_newest()
        p['title'] = _learned.plain(r)
        return {'message': 'Rule made: ' + _learned.plain(r), 'rule': dict(r, text=_learned.plain(r))}
    if action in ('calm_setup_step', 'calm_setup_dismiss'):   # Settings → Notifications → Calm setup
        try:
            return CALM_SETUP.action(action, p)
        except _calm_setup.Bad as e:
            raise Bad(str(e))
    if action in ('person_note', 'keep_set'):         # People: your note, keep in touch (owner only – OWNER_ONLY)
        return people_action(action, p)
    if action in ('bill_add', 'bill_dismiss', 'bill_looks_paid', 'bill_paid_already'):
        return bill_action(action, p)
    if action == 'done':
        require(p, 'item_id')
        set_state(p['item_id'], {'status': 'done', 'at': now_iso(), 'title': p.get('title', '')})
        _tidy(p)                                       # Keep Mail tidy: read in Mail – not moved, not archived
        _habit('done', p, p.get('sender'))
        return 'done'
    if action == 'snooze':
        require(p, 'item_id', 'until')
        # browsers send '…T06:00:00.000Z'; Python 3.9's fromisoformat doesn't accept the 'Z'
        p['until'] = p['until'].strip().replace('Z', '+00:00')
        datetime.datetime.fromisoformat(p['until'])
        set_state(p['item_id'], {'status': 'snoozed', 'until': p['until'], 'at': now_iso(), 'title': p.get('title', '')})
        return 'snoozed'
    if action == 'undo':
        require(p, 'item_id')
        was = load_json(STATE_FILE, {}).get(p['item_id']) or {}
        set_state(p['item_id'], None)
        if was.get('status') == 'done':                # Keep Mail tidy: what Done / Move / Delete / a reply marked read
            _tidy(p, read=False)
        return 'undone'
    raise Bad('unknown action')


def _tidy(p, read=True):
    """Keep Mail tidy: the owner's own tap on a mail (or a Send later the owner set) → read, or unread on Undo, in
    Mail – collected and run in the background by the job queue (mail_tidy.py). Only Mail: chats are never marked."""
    try:
        if p.get('_login') not in owner_logins() and p.get('_login') != 'scheduled':
            return
        if (p.get('channel') or 'mail') != 'mail':
            return
        acc, mid = p.get('account'), p.get('message_id')
        if acc in (config().get('accounts') or {}) and mid:
            TIDY.mark(acc, str(mid)[:500], read)
    except Exception as e:
        sys.stderr.write('%s mail tidy: %s\n' % (now_iso(), str(e)[:200]))


def _tidy_allowed(account, mid):
    """A mark may run: one of your accounts, and the mail's file is found and has no private or hidden contact."""
    if account not in (config().get('accounts') or {}):
        return False
    path = mailsearch.path_for_mid(mid)
    return bool(path) and not mail_privacy(mailsearch.addresses_of(path))[0]


def _habit(kind, p, sender, folder=''):
    """Teach Axella: one of the owner's own actions on a mail, for the habit detectors (never Axella's own)."""
    try:
        if p.get('_login') in owner_logins() and (p.get('channel') or 'mail') == 'mail':
            LEARN.record(kind, sender, p.get('account'), folder=folder, first_seen=p.get('first_seen'))
    except Exception as e:
        sys.stderr.write('%s habits: %s\n' % (now_iso(), str(e)[:200]))


def _vip_keys():
    """Lower-case VIP names and the addresses on their lines – a learned rule never lowers a VIP."""
    keys = set()
    try:
        for v in vips_list(full=True)[0]:
            keys.add(v['name'].lower())
            keys.update(a.lower() for a in re.findall(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', v.get('detail') or ''))
    except Exception:
        pass
    return keys


def _teach(what, p):
    """Feedback with a reason ("this sender" / "this topic") makes a rule; "just this once" makes none."""
    why = p.get('why') or 'once'
    if why == 'once':
        return None
    if p.get('_login') not in owner_logins():
        raise Bad('Only the owner can teach Axella a rule')
    try:
        r = LEARN.feedback(what, why, {'address': p.get('address'), 'name': p.get('name'), 'topic': p.get('topic')},
                           'urgent' if p.get('level') == 'urgent' else 'answer')
    except _learned.Bad as e:
        raise Bad(str(e))
    LEARN.add(r)
    _learn_newest()
    return dict(r, text=_learned.plain(r))


def _learn_side(r, on):
    """A rule's own effect outside learned-rules.json: hold → the Newsletters hold list, VIP → contacts.md, file-to →
    the filing memory the digest runs read. Section rules have none (the digest pass and the runs' block use them)."""
    if r['kind'] == 'hold':
        SUBS.action('sender_hold', {'address': r['sender'], 'name': r.get('label') or '', 'hold': on})
    elif r['kind'] == 'vip':
        try:
            vip_action('vip_add' if on else 'vip_remove', {'name': r['label'], 'address': r['sender'], 'ctx': r.get('ctx')})
        except Bad:
            if on:
                raise
    elif r['kind'] == 'file':
        with LOCK:
            fl = load_json(FILING_FILE, {})
            if on:
                fl[r['sender']] = {'folder': r['value'], 'account': r.get('account'), 'at': now_iso(), 'rule': r['id']}
            elif (fl.get(r['sender']) or {}).get('rule') == r['id']:
                fl.pop(r['sender'], None)
            with open(FILING_FILE, 'w', encoding='utf-8') as f:
                json.dump(fl, f, ensure_ascii=False, indent=1)


def _learn_digest(name):
    """A new digest (push watcher): your section rules applied, and filing suggestions from a sender with a file rule
    filed by themselves through the job queue – never a private contact's or a protected workplace's mail."""
    if re.search(r'-p0\b', name):
        return
    keys = _vip_keys()
    is_vip = lambda it: str((it.get('from') or {}).get('name') or '').lower() in keys or \
        str((it.get('from') or {}).get('address') or '').lower() in keys
    _, items = LEARN.apply_to_digest(os.path.join(DIGESTS_DIR, name), is_vip)
    handled = load_json(STATE_FILE, {})
    queued = {(j.get('_payload') or {}).get('item_id') for j in JOBS.values() if j['action'] == 'file' and j['state'] in ('queued', 'running')}
    for it, r in LEARN.file_candidates(items, handled):
        addrs = [a for a in meeting_mail_addresses((it.get('from') or {}).get('address'), it['message_id'], strict=True) if a]
        if it['id'] in queued or not addrs or mail_privacy(addrs)[0] or _is_protected_mail(it.get('account'), addrs):
            continue
        if not _learn_sender_ok(it['message_id'], r['sender']):
            continue                                   # stays a filing suggestion for your tap
        queue_job('file', {'item_id': it['id'], 'account': it['account'], 'message_id': it['message_id'], 'folder': r['value'],
                           'title': 'Filed by your rule – ' + _learned.plain(r), '_login': 'axella'}, 'axella')


def _learn_sender_ok(mid, sender):
    """Filing by itself: the mail file's own From is the rule's sender (not just what the run wrote), and no sender
    check (SPF / DMARC) failed. Anything else – no file, another From, a failed check – fails closed."""
    import email as _em
    import email.policy  # noqa: F401
    import email.utils  # noqa: F401
    try:
        raw = _raw_of_mid(mid)
        if not raw:
            return False
        msg = _em.message_from_bytes(raw, policy=_em.policy.default)
        frm = _em.utils.parseaddr(str(msg.get('From', ''))[:1000])[1].strip().lower()
        return frm == sender and not _safety.sender_checks(msg)['failed']
    except Exception:
        return False


def _learn_newest():
    """A rule just made: also apply it to the digest Today shows now (no filing by itself here)."""
    try:
        name, _ = _sprint_digest()
        if name:
            keys = _vip_keys()
            LEARN.apply_to_digest(os.path.join(DIGESTS_DIR, name),
                                  lambda it: str((it.get('from') or {}).get('name') or '').lower() in keys or
                                  str((it.get('from') or {}).get('address') or '').lower() in keys)
    except Exception as e:
        sys.stderr.write('%s learned rules: %s\n' % (now_iso(), str(e)[:200]))


def _digest_names():
    """address → display name from the last digests' items (for the suggestion texts)."""
    out = {}
    try:
        names = sorted(n for n in os.listdir(DIGESTS_DIR) if n.endswith('.json') and n[:4].isdigit())[-20:]
    except OSError:
        return out
    for n in names:
        d = load_json(os.path.join(DIGESTS_DIR, n), {})
        for it in (d.get('items') or []) if isinstance(d, dict) else []:
            f = it.get('from') if isinstance(it, dict) else None
            if isinstance(f, dict) and f.get('address') and f.get('name'):
                out[str(f['address']).lower()] = str(f['name'])
    return out


def learn_view():
    """Settings → Rules, and the one suggestion card – found by rules here from your own actions."""
    try:
        cands = LEARN.detect(vips=_vip_keys(), names=_digest_names(), subs=SUBS.load().get('senders') or {})
        sug = LEARN.suggestion(cands)
    except Exception as e:
        sys.stderr.write('%s learned suggestions: %s\n' % (now_iso(), str(e)[:200]))
        sug = None
    return dict(LEARN.view(), suggestion={'key': sug['key'], 'text': sug['text']} if sug else None)


from forwarding import Forwarding, Bad as ForwardBad  # noqa: E402
from subscriptions import Subscriptions, Bad as SubsBad  # noqa: E402
FWD = Forwarding(STATE_DIR, DOCS, mail_forward)
SUBS = Subscriptions(STATE_DIR, osa)


import schedule as _schedule_mod  # noqa: E402
from scheduler import Scheduler, Bad as RunnerBad  # noqa: E402
RUNNER = Scheduler(BASE, STATE_DIR, SCHED, push_send)
STORE = Store(BASE, STATE_DIR)
OOO = None   # set at start (needs push_send)
from reminders import Reminders, Bad as RemindersBad  # noqa: E402
from knowledge import Knowledge, Bad as KnowledgeBad  # noqa: E402
KB = Knowledge(BASE)      # knowledge/entries/*.md – read by the digest and compose runs too
from kb_harvest import Harvest, Bad as HarvestBad  # noqa: E402
HARVEST = Harvest(BASE, STATE_DIR, KB, log=sys.stderr)   # suggestions from mail – merged by the scheduler's clock
RUNNER.harvest = HARVEST
from briefings import Briefings, Bad as BriefingsBad  # noqa: E402
from privacy import Privacy, Bad as PrivacyBad  # noqa: E402
PRIV = Privacy(STATE_DIR)    # private contacts (state/privacy.json) – read here and by the exporters, never by Claude runs
from contacts_book import Book  # noqa: E402
# the Contacts page / New message: your address book (state/contacts-book.json), people you mail with, VIPs as favourites
BOOK = Book(STATE_DIR, osa, PRIV, vips_list,
            lambda: [c for c in compose_contacts() if not NO_REPLY.match(c.get('address') or '')], log=sys.stderr)
import trips  # noqa: E402  (Trips: "Scan mail for upcoming trips" – booking confirmations → suggested trips)
TRIPS = trips.Trips(STATE_DIR)
TRIP_CHECKS = trips.Checklists(STATE_DIR)            # the documents checklist per trip – SECRETS, ticked by you only

import safety as _safety  # noqa: E402  (scam check + Always hold on every new digest – local rules only)
if isinstance(config().get('mail_providers'), list) and config()['mail_providers']:
    _safety.PROVIDERS = [str(x).strip().lower() for x in config()['mail_providers'] if str(x).strip()][:30]   # whose "pass" counts


def _raw_of_mid(mid):
    """A mail's own source from Mail's store, for the scam check (headers and HTML – read here, never sent anywhere)."""
    path = mailsearch.path_for_mid(mid)
    return mailsearch._raw(path) if path else None


def _known_people():
    """(e-mail addresses, last 8 digits of phone numbers) in your address book – the scam check trusts these."""
    mails, phones = set(), set()
    for person in (load_json(os.path.join(STATE_DIR, 'contacts-book.json'), {}) or {}).get('people') or []:
        for e in person.get('emails') or []:
            mails.add(str(e).strip().lower())
        for ph in person.get('phones') or []:
            dg = re.sub(r'\D', '', str(ph))
            if len(dg) >= 8:
                phones.add(dg[-8:])
    return mails, phones


def _protected_domain(dom):
    """Authorities, banks, insurers, lawyers … (the mail cleanup keep-list): never suggested as noise."""
    import cleanup as _cl
    dom = str(dom or '').lower()
    return bool(_cl.KEEP_DOMAIN.search(dom) or _cl.PRO_DOMAIN.search(dom) or _cl.local_keep(dom, STATE_DIR))


SAFETY = _safety.Safety(STATE_DIR, DIGESTS_DIR, _raw_of_mid, _known_people, SUBS.held, log=sys.stderr)

import calm as _calm  # noqa: E402  (Insights → Your calm: calm in numbers)


def _newest_digest():
    try:
        names = sorted(n for n in os.listdir(DIGESTS_DIR) if n.endswith('.json') and n[:4].isdigit() and '-p0' not in n)
    except OSError:
        return None
    return names[-1][:-5] if names else None


def _draft_of(item_id, last=40):
    """Axella's own draft for an item, from the recent digests (for the send's edit bucket – the text stays here)."""
    try:
        names = sorted((n for n in os.listdir(DIGESTS_DIR) if n.endswith('.json') and n[:4].isdigit()), reverse=True)[:last]
    except OSError:
        return None
    for n in names:
        for it in (load_json(os.path.join(DIGESTS_DIR, n), {}) or {}).get('items') or []:
            if isinstance(it, dict) and str(it.get('id')) == str(item_id):
                t = (it.get('draft') or {}).get('text')
                if t:
                    return t
    return None


def edit_bucket(draft, sent):
    """How much you changed Axella's draft before sending: none / little / much (only this word is logged)."""
    import difflib
    if not draft or sent is None:
        return None
    a, b = ' '.join(str(draft).split()), ' '.join(str(sent).split())
    r = difflib.SequenceMatcher(None, a, b).ratio() if a != b else 1.0
    return 'none' if r >= 0.97 else 'little' if r >= 0.75 else 'much'


import recurring as _recurring  # noqa: E402  (Subscriptions overview: regular charges + renewal/trial/price mails)
import app_stores as _app_stores  # noqa: E402  (Subscriptions: the line items on an app store's receipts)
RECUR = _recurring.Recurring(STATE_DIR, DIGESTS_DIR, log=sys.stderr)
_RECUR_KICK = threading.Event()


def _recurring_notices(days=120, limit=150):
    """Renewal, trial and price-change mails from Mail's index, read here by rules. Private and hidden contacts and
    mails the scam check flags are left out; only the parsed facts are kept, never the text."""
    try:
        names = mail_accounts()
    except Exception:
        return []
    seen = set(RECUR.load()['notices'])
    out = []
    for c in mailsearch.booking_candidates(names, lambda subj, addr: bool(_recurring.NOTICE_SUBJ.search(subj or '')), days=days, limit=limit):
        mid = c.get('message_id')
        if not mid or mid in seen or mail_privacy([c.get('from_address')])[0]:
            continue
        try:
            raw = mailsearch._raw(c['path'])
            if _safety.check_mail(raw, *_known_people()[:1])[0]:
                continue
            n = _recurring.read_notice(raw)
        except Exception:
            continue
        if n:
            n.update(message_id=mid, account=c.get('account'))
            out.append(n)
    return out


def _store_receipts(days=400, limit=200):
    """App store receipts and renewal mails (app_stores.py): the line items, read here by rules. Only the store's own
    domain (the parser also needs DKIM/DMARC to pass for it); private and hidden senders and mails the scam check flags
    are left out. Only the parsed items are kept, never the text."""
    try:
        names = mail_accounts()
    except Exception:
        return []
    seen = set(RECUR.load().get('store_receipts') or {})
    out = []
    for c in mailsearch.booking_candidates(names, _app_stores.is_candidate, days=days, limit=limit):
        mid = c.get('message_id')
        if not mid or mid in seen or mail_privacy([c.get('from_address')])[0]:
            continue
        try:
            raw = mailsearch._raw(c['path'])
            if _safety.check_mail(raw, *_known_people()[:1])[0]:
                continue
            r = _app_stores.parse_receipt(raw)
        except Exception:
            continue
        if r:
            r['message_id'] = mid
            out.append(r)
    return out


import renewals as _renewals  # noqa: E402  (Receipts → Renewals: things that expire or renew on a date)
RENEW = _renewals.Renewals(STATE_DIR)
_RENEW_KICK = threading.Event()


def _renewal_mails(days=180, limit=200):
    """Renewal and expiry mails from Mail's index, read here by rules (genuine senders only – renewals.read_mail checks
    DKIM/DMARC). Private and hidden contacts and scam-flagged mail are left out; only the parsed facts are kept."""
    try:
        names = mail_accounts()
    except Exception:
        return []
    d = RENEW.load()
    seen = set(d['suggestions']) | set(d['dismissed'])
    out = []
    for c in mailsearch.booking_candidates(names, lambda subj, addr: bool(_renewals.SUBJECT.search(subj or '')), days=days, limit=limit):
        mid = c.get('message_id')
        if not mid or mid in seen:
            continue
        try:
            addrs = mailsearch.addresses_of(c['path'])
        except Exception:
            addrs = [c.get('from_address')]
        if mail_privacy(addrs)[0]:
            continue
        try:
            raw = mailsearch._raw(c['path'])
            if _safety.check_mail(raw, *_known_people()[:1])[0]:
                continue
            r = _renewals.read_mail(raw)
        except Exception:
            continue
        if r:
            r.update(message_id=mid, account=c.get('account'))
            out.append(r)
    return out


def _renewals_loop():
    """Every 12 hours (or when asked): renewal and expiry mails → suggestions; a known subscription's sender is left out."""
    time.sleep(150)
    while True:
        try:
            known = {dom for s in RECUR.load().get('subs', {}).values() for dom in s.get('domains') or []}
            RENEW.suggest(_renewal_mails(), known)
        except Exception as e:
            sys.stderr.write('%s renewals: %s\n' % (now_iso(), str(e)[:200]))
        _RENEW_KICK.wait(12 * 3600)
        _RENEW_KICK.clear()


def renewals_view():
    subs = [s for s in RECUR.view().get('subs') or [] if s.get('interval') == 'yearly' and s.get('status') == 'active' and not s.get('gone')]
    try:
        trips_all = TRIPS.load()['trips']
    except Exception:
        trips_all = []
    v = RENEW.view(datetime.date.today(), subs, trips_all)
    v['cards'] = RENEW.cards()
    return v


def renewal_action(action, p):
    try:
        if action == 'renewal_scan':
            _RENEW_KICK.set()
            return {'started': True}
        if action == 'renewal_todo':                       # the card's Add to To do: a task with the date as its due date
            e = RENEW.load()['items'].get(str(p.get('id') or ''))
            if not e:
                raise Bad('unknown renewal')
            tid = task_action('task_add', {'text': '%s – %s %s' % (e['name'], 'renews' if e.get('auto_renews') else 'due', e['date']),
                                           'due': e['date'], 'source': 'renewal', 'ref': {'kind': 'renewal', 'id': e['id']},
                                           **({'ctx': e['ctx']} if e.get('ctx') else {})})
            p['title'] = e['name']
            return RENEW.action('renewal_task', {'id': e['id'], 'task_id': tid})
        r = RENEW.action(action, p)
        p['title'] = (r or {}).get('name') if isinstance(r, dict) else 'Renewal'
        return r
    except _renewals.Bad as e:
        raise Bad(str(e))
    except (TypeError, ValueError):
        raise Bad('check the cost and the lead time')


import blocks as _blocks  # noqa: E402  (Protect your blocks: Your time, and one suggestion to hold a free block)
BLOCKS = _blocks.Blocks(STATE_DIR)


def _work_hours():
    h = config().get('work_hours')
    return h if isinstance(h, dict) and h.get('from') and h.get('to') else _blocks.WORK_HOURS


def _block_events(a, b):
    """The calendar's events from a to b (dates) through the same reader as the Calendar page."""
    import calendar_view
    return calendar_view.events(RUNNER.mcp_file(), config().get('calendars') or [], a.isoformat(), b.isoformat())['events']


def _block_calendars():
    return [c['name'] for c in profile.calendars() if c.get('kind') == 'work']


def blocks_view():
    today = datetime.date.today()
    mon = today - datetime.timedelta(days=today.weekday())
    d = BLOCKS.load()
    try:
        ev = _block_events(mon - datetime.timedelta(days=7), mon + datetime.timedelta(days=7))
        err = None
    except Exception as e:
        ev, err = [], str(e)[:160]
    m = d['settings']['minutes']
    return {'settings': d['settings'], 'calendars': _block_calendars(), 'hours': _work_hours(), 'error': err,
            'this_week': _blocks.your_time(ev, mon, m, _work_hours()), 'last_week': _blocks.your_time(ev, mon - datetime.timedelta(days=7), m, _work_hours())}


def block_action(action, p):
    try:
        if action == 'block_settings':
            p['title'] = 'Protect your blocks'
            return BLOCKS.settings(p, _block_calendars())
        day = str(p.get('date') or '')[:10]
        if not _blocks._dt(day + 'T00:00:00'):
            raise Bad('which day?')
        if action == 'block_never':
            BLOCKS.mark(day, 'never')
            return {'never': day}
        if action == 'block_not_now':
            BLOCKS.mark(day, 'shown')
            return {'ok': True}
        if action == 'block_hold':
            # one busy event of your own, through cal_add (its backup and undo) – nothing else in the calendar changes
            st = BLOCKS.load()['settings']
            cals = list(_block_calendars())
            cal = st.get('calendar') if st.get('calendar') in cals else next(iter(cals), None)
            if not cal:
                raise Bad('pick a calendar for held blocks in Settings → Calendar')
            s, e = str(p.get('start') or ''), str(p.get('end') or '')
            if not re.match(r'^\d\d:\d\d$', s) or not re.match(r'^\d\d:\d\d$', e) or e <= s:
                raise Bad('a start and an end time')
            import calendar_view as _cv
            off = datetime.datetime.fromisoformat(day + 'T' + s).astimezone().strftime('%z')   # that day's offset (summer/winter time)
            off = off[:3] + ':' + off[3:]
            p['title'] = st.get('name') or 'Focus'
            r = _cv.edit(RUNNER.mcp_file(), config().get('calendars') or [], 'cal_add',
                         {'title': st.get('name') or 'Focus', 'calendar': cal, 'start': '%sT%s:00%s' % (day, s, off), 'end': '%sT%s:00%s' % (day, e, off),
                          'notes': 'Held by Axella – your own time to work.'}, os.path.join(BACKUP_DIR, 'events'),
                         cache_file=os.path.join(STATE_DIR, 'macuse-calendar-tools.json'))
            BLOCKS.mark(day, 'shown')
            return dict(r or {}, calendar=cal)
    except _blocks.Bad as e:
        raise Bad(str(e))
    except (TypeError, ValueError):
        raise Bad('check the block length')
    except Exception as e:
        if e.__class__.__name__ == 'CalendarError':
            raise Bad(str(e))
        raise
    raise Bad('unknown action')


import sprint as _sprint  # noqa: E402  (Reply sprint: the quick replies that are ready, one after another)


def _sprint_digest():
    """(name, items) of the newest regular digest with items – what Today shows."""
    try:
        names = sorted(f for f in os.listdir(DIGESTS_DIR) if f.endswith('.json') and not re.search(r'-p0\b', f))
    except OSError:
        return None, []
    for f in reversed(names[-3:]):
        d = load_json(os.path.join(DIGESTS_DIR, f), {})
        if isinstance(d, dict) and isinstance(d.get('items'), list) and d['items']:
            return f, [i for i in d['items'] if isinstance(i, dict)]
    return None, []


def _sprint_left_out(it):
    """A private or hidden contact, or a protected workplace's mail: never in a sprint."""
    addrs = _sprint.addresses(it)
    return bool(mail_privacy(addrs)[0]) or _is_protected_mail(it.get('account'), addrs)


def sprint_view():
    """Reply sprint (Today card, To do line, the sprint screen): the quick replies ready now, in order, with a time
    estimate. Rules only; nothing is drafted or sent here – each Send is the ordinary reply_send on its own tap."""
    name, items = _sprint_digest()
    waiting = [x.get('item_id') for x in SCHED_SEND.list() if x.get('status') in ('scheduled', 'sending')]
    v = _sprint.view(items, load_json(STATE_FILE, {}), _COMMIT.get('debt') or [], waiting, _sprint_left_out)
    return dict(v, digest=name)


import notes as _notes  # noqa: E402  (Notes: Axella's own notes, linked to people, projects, trips, preps and threads)
NOTES = _notes.Notes(BASE, os.path.join(STATE_DIR, 'deleted', 'notes'))


def _note_keys(m):
    """Every identity a note is linked to (people, mail and chat senders)."""
    return {k for l in m.get('links') or [] for k in l.get('keys') or []}


def note_readable(m):
    """May Ask Axella read this note? Never one linked to a private or hidden contact; one linked to a protected
    workplace only when that workplace's Claude setting (Meetings page) isn't "none" – a note is your own text, so
    "own" allows it, as for a meeting prep. Fails closed."""
    import meetings as _mt
    keys = sorted(_note_keys(m))
    if keys and mail_privacy(keys)[0]:
        return False
    defaults = MEET.ai_defaults()
    wps = set()
    for k in keys:
        if '@' in k:
            for w in profile.workplaces():
                if w.get('protected') and any(k.endswith('@' + d) or k.endswith('.' + d) for d in w['domains']):
                    wps.add(w['id'])
    accs = {a['id']: a for a in profile.accounts()}
    for l in m.get('links') or []:
        a = accs.get(l.get('account') or '')
        if a and a.get('workplace') and any(w['id'] == a['workplace'] and w.get('protected') for w in profile.workplaces()):
            wps.add(a['workplace'])
        if l['kind'] == 'meeting':
            prep = MEET.get(l['ref']) if hasattr(MEET, 'get') else None
            if prep:
                if meeting_ai(prep)[1] == 'none':
                    return False
    for w in wps:
        mode = _mt.effective_ai({}, [w], defaults)[0]
        if mode == 'none':
            return False
    return True


def _ask_notes(cid, login=None):
    """Ask Axella: the notes it may read, copied for this one run (state/ask-notes/<id>/) – removed when it ends.
    Only when the owner asks: anyone else on the access list can use Ask, but never gets an answer from your notes."""
    _ask_notes_sweep()
    if login not in owner_logins() or not re.match(r'^[\w-]{1,80}$', str(cid or '')):
        return 0
    return NOTES.export_for_ask(os.path.join(STATE_DIR, 'ask-notes', cid), note_readable)


def _ask_notes_sweep(max_age=3600):
    """A copy left behind by an Ask run that crashed: removed after an hour (at start: all of them, nothing runs yet)."""
    import time as _time
    root = os.path.join(STATE_DIR, 'ask-notes')
    try:
        for n in os.listdir(root):
            p = os.path.join(root, n)
            if os.path.isdir(p) and _time.time() - os.path.getmtime(p) >= max_age:
                NOTES.drop_export(p)
    except OSError:
        pass


def _ask_notes_done(cid, read):
    """After an Ask run: how many notes it read (from its own tool log) – What leaves my home – and the copy gone."""
    if read:
        tally('notes_read', read)
        tally('notes_asks', 1)
    if re.match(r'^[\w-]{1,80}$', str(cid or '')):
        NOTES.drop_export(os.path.join(STATE_DIR, 'ask-notes', cid))


def note_chips(name=None):
    """The quiet "Your note" chips for the digest Today shows – matched here, never written into the digest."""
    if name and not re.match(r'^[\w-]+\.json$', name):
        raise Bad('bad digest name')
    if not name:
        name, items = _sprint_digest()
    else:
        d = load_json(os.path.join(DIGESTS_DIR, name), {})
        items = d.get('items') if isinstance(d, dict) else []
    today = datetime.date.today().isoformat()
    preps = [(x.get('id'), str(x.get('start') or '')[:10]) for x in (MEET.load().get('preps') or []) if isinstance(x, dict)]
    trips_ = [(t.get('id'), str(t.get('start') or '')[:10]) for t in (TRIPS.load().get('trips') or []) if isinstance(t, dict)]
    return NOTES.chips(items or [], datetime.date.today(), preps, trips_)


def note_action(action, p):
    try:
        if action == 'note_save':
            r = NOTES.save(p)
            p['title'] = r.get('title') or 'Note'
            return r
        if action == 'note_keep':
            return NOTES.keep(str(p.get('id') or ''), p.get('item_id'))
        if action == 'note_delete':
            r = NOTES.delete(str(p.get('id') or ''))
            p['title'], p['_backup'] = r.get('title') or 'Note', r['backup']
            return r
        if action == 'note_restore':
            r = NOTES.restore(str(p.get('backup') or ''))
            p['title'] = r.get('title') or 'Note'
            return r
        if action == 'note_todo':
            nid = str(p.get('id') or '')
            n = NOTES.view(nid)
            text = ' '.join(str(p.get('text') or n.get('title') or '').split())[:500]
            if not text:
                raise Bad('which line?')
            p['title'] = text[:80]
            tid = task_action('task_add', {'text': text, 'source': 'note', 'ref': {'note': nid, 'title': n.get('title')},
                                           'ctx': n.get('ctx')})
            return {'task': tid}
    except _notes.Bad as e:
        raise Bad(str(e))
    raise Bad('unknown action')


def _until(v):
    """A snooze's "until" as a naive local datetime (the browser sends UTC with an offset), or None."""
    try:
        d = datetime.datetime.fromisoformat(str(v or '').strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return d.astimezone().replace(tzinfo=None) if d.tzinfo else d


def later_view(now=None):
    """What you pushed to Later and when it comes back (the line at the bottom of Today): the snoozed items in
    state/actions.json that haven't come back yet, each with its item from the newest digest that has it (None when
    that digest is gone – the title it was pushed under is kept). Read-only: the items are what the digests show."""
    now = now or datetime.datetime.now()
    want = {}
    for k, v in load_json(STATE_FILE, {}).items():
        u = _until(v.get('until')) if isinstance(v, dict) and v.get('status') == 'snoozed' else None
        if u and u > now:
            want[k] = (u, v)
    found = {}
    try:
        names = sorted((n for n in os.listdir(DIGESTS_DIR) if n.endswith('.json') and n[:4].isdigit()), reverse=True)
    except OSError:
        names = []
    for n in names:
        if len(found) == len(want):
            break
        d = load_json(os.path.join(DIGESTS_DIR, n), {})
        for it in (d.get('items') or []) if isinstance(d, dict) else []:
            if isinstance(it, dict) and it.get('id') in want and it['id'] not in found:
                found[it['id']] = it
    out = [{'id': k, 'until': u.isoformat(timespec='minutes'), 'title': str(v.get('title') or '')[:200], 'item': found.get(k)}
           for k, (u, v) in want.items()]
    return {'items': sorted(out, key=lambda x: (x['until'], x['id']))}


import away as _away  # noqa: E402  (Back-from-away briefing: the first digest after 2+ days away)
AWAY = _away.Away(STATE_DIR)
import learned as _learned  # noqa: E402  (Teach Axella: feedback, rules suggested from your habits, Settings → Rules)
LEARN = _learned.Learned(STATE_DIR)
RUNNER.learned_note = lambda: LEARN.prompt_note()
RUNNER.ask_notes, RUNNER.ask_notes_done = (lambda cid, login=None: _ask_notes(cid, login)), (lambda cid, n: _ask_notes_done(cid, n))   # the "Learned rules" block for the digest and urgent-check runs
import calm_setup as _calm_setup  # noqa: E402  (Calm setup: Settings → Notifications, three steps)
CALM_SETUP = _calm_setup.CalmSetup(STATE_DIR, DIGESTS_DIR)


def _is_away_day(day):
    """Away (Settings → Away) covers the day, or the schedule paused digests that day (vacation, a day off)."""
    o = OOO.load() if OOO else {}
    f, u = _away._day(o.get('from')), _away._day(o.get('until'))
    if f and f <= day and (not u or day <= u):
        return True
    try:
        return not SCHED.status(datetime.datetime.combine(day, datetime.time(12)))['digests']
    except Exception:
        return False


def _is_bridge_day(day):
    """No digest slot on that weekday at all (a weekend): it joins two away days but isn't one."""
    return not any(task != 'p0-check' for _sid, task, _hm, _lb in RUNNER.slots_for(day))


def _away_facts(job):
    ab = job['away']
    try:
        preps = MEET.overview()
    except Exception:
        preps = []
    try:
        trips = TRIPS.load()['trips']
    except Exception:
        trips = []
    try:
        ren = renewals_view().get('rows') or []
    except Exception:
        ren = []
    f = _away.facts(ab, job.get('worlds') or ['private', 'work'], DIGESTS_DIR, load_json(STATE_FILE, {}), load_json(TASKS_FILE, []),
                    datetime.date.today(), preps=preps, trips=trips, renewals=ren, manual=ab.get('manual'))
    AWAY.write_facts(f)
    return f


def _away_due(today):
    """The absence to brief at this slot – marked briefed as it is queued (its one retry keeps it), so it comes once."""
    ab = AWAY.due(today, _is_away_day, _is_bridge_day)
    if ab:
        AWAY.mark_briefed(ab)
    return ab


RUNNER.away_due = _away_due
RUNNER.away_facts = _away_facts
DIGEST_NAME = re.compile(r'^\d{4}-\d{2}-\d{2}-\d{4}\.json$')


def away_action(action, p):
    """Archive all (the "Sorted itself out" groups, minus what you kept back) – handled in Axella only, nothing moves
    in Mail – with one Undo for the batch; "Catch me up since…" a date."""
    if action == 'away_catchup':
        since = _away._day(p.get('since'))
        today = datetime.date.today()
        if not since or since >= today:
            raise Bad('pick a day before today')
        if (today - since).days > _away.MAX_LOOKBACK:
            raise Bad('at most %d days back' % _away.MAX_LOOKBACK)
        p['title'] = 'Catch me up since ' + since.isoformat()
        try:
            return RUNNER.action('run_now', {'task': 'return-briefing', 'away': {'from': since.isoformat(), 'to': (today - datetime.timedelta(days=1)).isoformat()}})
        except RunnerBad as e:
            raise Bad(str(e))
    if action == 'away_archive':
        name = str(p.get('digest') or '')
        if not DIGEST_NAME.match(name):
            raise Bad('which briefing?')
        dg = load_json(os.path.join(DIGESTS_DIR, name), {})
        if not isinstance(dg, dict) or not isinstance(dg.get('away'), dict):
            raise Bad('not a back-from-away briefing')
        if (dg['away'].get('sorted_by') != 'axella' or not AWAY.stored_ids(name)
                or dg['away'].get('sorted_hash') != _away.ids_hash(AWAY.stored_ids(name))):
            raise Bad('this briefing has no list of its own yet – try again in a minute')
        keep = [str(x)[:200] for x in p.get('keep') or []][:2000]
        with LOCK:
            state = load_json(STATE_FILE, {})
            ids = [i for i in AWAY.group_ids(name, keep) if not _away.handled(state.get(i))]
            if not ids:
                raise Bad('nothing left to archive')
            bid = AWAY.archive(name, ids)
            at = now_iso()
            for i in ids:
                state[i] = {'status': 'done', 'at': at, 'how': 'away:' + bid}
            tmp = STATE_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=1)
            os.replace(tmp, STATE_FILE)
        p['title'] = 'Archive all: %d items handled in Axella (nothing moved in Mail)' % len(ids)
        p['_items'] = ids[:TRASH_BATCH_MAX]
        return {'batch': bid, 'count': len(ids)}
    if action == 'away_undo':
        try:
            b = AWAY.take_batch(p.get('batch'))
        except _away.Bad as e:
            raise Bad(str(e))
        tag = 'away:' + str(p.get('batch'))
        with LOCK:
            state = load_json(STATE_FILE, {})
            back = [i for i in b['ids'] if (state.get(i) or {}).get('how') == tag]   # not one you handled yourself since
            for i in back:
                state.pop(i, None)
            tmp = STATE_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=1)
            os.replace(tmp, STATE_FILE)
        p['title'] = 'Undo Archive all: %d items back' % len(back)
        return {'count': len(back)}
    raise Bad('unknown action')


import backup as _backup  # noqa: E402  (Backup and move: one encrypted file, weekly copies to your folder, restore)
import shutil as _shutil  # noqa: E402
import uuid as _uuid  # noqa: E402
import oauth_flow as _kc_mod  # noqa: E402  (its Keychain helper: values go in through `security -i`, never argv)
EXPORT_DIR = os.path.join(STATE_DIR, 'export')       # Export backup: waits here for its one download, at most an hour
EXPORT_ID = re.compile(r'^[0-9a-f]{24}$')


def _axella_version():
    try:
        with open(os.path.join(BASE, 'web', 'package.json'), encoding='utf-8') as f:
            return str(json.load(f).get('version') or '')
    except (OSError, ValueError):
        return ''


BACKUP_AUTO = _backup.Auto(STATE_DIR, BASE, _kc_mod.Keychain(), version=_axella_version(), push=lambda pl: push_send(pl))


def _prune_exports(max_age=3600):
    try:
        for n in os.listdir(EXPORT_DIR):
            p = os.path.join(EXPORT_DIR, n)
            if time.time() - os.path.getmtime(p) > max_age:
                os.remove(p)
    except OSError:
        pass


def backup_view():
    return {'age': bool(_backup.age_bin()), 'auto': BACKUP_AUTO.status(), 'reconnect': [t for _k, t in _backup.RECONNECT],
            'left_out': list(_backup.TOKENS), 'min_pass': _backup.MIN_PASS, 'keep': _backup.KEEP}


def backup_action(action, p):
    """Export backup (one encrypted file to download), automatic weekly backups to your folder, Back up now.
    The passphrase is taken out of the request at once – never logged, never stored (automatic: Keychain only)."""
    pw, again = p.pop('passphrase', None), p.pop('again', None)
    try:
        if action == 'backup_export':
            _backup.check_passphrase(pw, again)
            hist = bool(p.get('history'))
            os.makedirs(EXPORT_DIR, mode=0o700, exist_ok=True)
            _prune_exports()
            eid = _uuid.uuid4().hex[:24]
            name = 'axella-backup-%s%s' % (datetime.date.today().isoformat(), _backup.SUFFIX)
            m = _backup.build(BASE, os.path.join(EXPORT_DIR, eid + _backup.SUFFIX), pw, history=hist, version=_axella_version())
            with open(os.path.join(EXPORT_DIR, eid + '.json'), 'w', encoding='utf-8') as f:
                json.dump({'name': name}, f)
            p['title'] = 'Backup exported' + (' with history' if hist else '')
            return {'id': eid, 'name': name, 'size': m['size'], 'files': len(m['files']), 'left_out': m['left_out'], 'history': hist}
        if action == 'backup_auto':
            st = BACKUP_AUTO.settings({k: p[k] for k in ('on', 'folder', 'history') if k in p} | ({'passphrase': pw, 'again': again} if pw else {}))
            p['title'] = 'Automatic backups ' + ('on' if st['on'] else 'off')
            return st
        if action == 'backup_run':
            p['title'] = 'Back up now'
            r = BACKUP_AUTO.run(force=True) or {}
            if r.get('last_error'):
                raise Bad(r['last_error'])
            return BACKUP_AUTO.status()
    except (_backup.Bad, _kc_mod.Bad) as e:
        raise Bad(str(e))
    finally:
        pw = again = None
    raise Bad('unknown action')


def _backup_loop():
    """Every 30 minutes: the weekly automatic backup when it's due, the 2-week warning, old exports cleared."""
    time.sleep(300)
    while True:
        try:
            BACKUP_AUTO.run()
            BACKUP_AUTO.warn()
        except Exception as e:
            sys.stderr.write('%s backup: %s\n' % (now_iso(), str(e)[:200]))
        _prune_exports()
        time.sleep(1800)


def _recurring_loop():
    """Every 6 hours (or when asked): rebuild the Subscriptions overview from Receipts, the notice mails and the
    app stores' receipts."""
    time.sleep(90)
    while True:
        try:
            RECUR.refresh(DOCS.load().get('documents') or {}, _recurring_notices(), receipts=_store_receipts())
        except Exception as e:
            sys.stderr.write('%s recurring: %s\n' % (now_iso(), str(e)[:200]))
        _RECUR_KICK.wait(6 * 3600)
        _RECUR_KICK.clear()


def _flagged_token(tok):
    """A mail opened from a Search hit (file=<token>): is its Message-ID flagged by the scam check?"""
    import email as _email
    e = mailsearch._TOK.get(str(tok or '')) or {}
    mid = e.get('mid')
    if not mid:
        try:
            head = _email.message_from_bytes(mailsearch._raw(mailsearch._entry(tok), headers_only=True))
            mid = str(head.get('Message-ID') or '')
        except Exception:
            return False
    mid = str(mid).strip()
    return bool(mid and (SAFETY.flag_of({'message_id': mid}) or SAFETY.flag_of({'message_id': mid.strip('<>')})
                         or SAFETY.flag_of({'message_id': '<%s>' % mid.strip('<>')})))


# ---------- Projects → Scan mail (project_scan.py) ----------
PROJECT_MAIL_ACTIONS = {'project_mail_scan', 'project_mail_add', 'project_mail_not', 'project_mail_undo_not', 'project_mail_remove',
                        'project_mail_undo_remove', 'project_mail_move', 'project_match_add', 'project_match_dismiss',
                        'project_trip_link', 'project_trip_unlink', 'project_mail_attach', 'project_read', 'project_suggestion_done'}
_PSCAN_NIGHT = {}


def _project_of(pid):
    p = next((x for x in PROJ.load()['projects'] if x.get('id') == pid), None)
    if not p:
        raise Bad('unknown project')
    return p


def _project_workplace(p):
    """The workplace a project belongs to (its id, tag or name is the workplace's id or name), or None."""
    names = {str(p.get(k) or '').lower() for k in ('tag', 'name')} | {str(p.get('id') or '')[2:].lower()}
    return next((w for w in profile.workplaces() if {str(w.get('id') or '').lower(), str(w.get('name') or '').lower()} & names - {''}), None)


def _project_world(p):
    return p.get('ctx') if p.get('ctx') in ('work', 'private') else ('work' if _project_workplace(p) else None)


def _wp_owns(wp, account, addrs):
    """True when a protected workplace's mail belongs to this (protected) workplace: its account, or one of its domains."""
    if not (wp and wp.get('protected')):
        return False
    acc = next((x for x in profile.accounts() if x['id'] == account), {})
    return acc.get('workplace') == wp['id'] or any(str(a).rsplit('@', 1)[-1].lower() in wp['domains'] for a in addrs if a)


def _is_protected_mail(account, addrs):
    return bool(profile.is_protected(account, None)) or any(profile.is_protected(account, a) for a in addrs if a)


def _project_keep(p):
    """The left-out rules for a project's candidates: the project's world, private and hidden contacts, a protected
    workplace's mail (unless the project belongs to that workplace), and mail the scam check flags."""
    wp, world = _project_workplace(p), _project_world(p)
    accs = {a['id']: a for a in profile.accounts()}

    def keep(c):
        acc = accs.get(c.get('account')) or {}
        if world and acc.get('kind') and acc['kind'] != world:
            return False, 'other world'
        try:
            addrs = mailsearch.addresses_of(c['path'])
        except Exception:
            addrs = [c.get('from_address')]
        if mail_privacy(addrs)[0]:
            return False, 'private contact'
        if _is_protected_mail(c.get('account'), addrs) and not _wp_owns(wp, c.get('account'), addrs):
            return False, 'protected workplace'
        try:
            if _safety.check_mail(mailsearch._raw(c['path']), *_known_people()[:1])[0]:
                return False, 'flagged'
        except Exception:
            return False, 'unreadable'
        return True, None
    return keep


def project_mail_scan(pid, since=None, nightly=False):
    """Scan mail for one project: Mail's index (subject and sender), the project's Matches, the left-out rules; new
    candidates wait in To sort. Never Claude. Runs in the background; PSCAN.status[pid] says how it went."""
    st = PSCAN.status.setdefault(pid, {})
    st.update(running=True, error=None, found=None)
    try:
        p = _project_of(pid)
        today = datetime.date.today()
        since = since or _pscan.since_of(PSCAN.entry(pid), today)
        m = PSCAN.matcher(p)
        if not m.any():
            raise Bad('give the project a keyword or a sender first')
        cands = mailsearch.booking_candidates(mail_accounts(), lambda subj, addr: bool(m(subj, addr)),
                                              days=min(_pscan.SCAN_DAYS, (today - since).days + 1), limit=600)
        found = _pscan.scan(p, cands, m, _project_keep(p), today, since)
        st['found'] = PSCAN.merge(pid, found)
        if not nightly:
            log_auto('project_mail_scan', 'Projects: %d new mails to sort' % st['found'])
    except Exception as e:
        st['error'] = str(e)[:200]
        sys.stderr.write('project scan: %s\n' % str(e)[:200])
    finally:
        st['running'] = False


def _project_scan_loop():
    """The nightly re-scan (about 03:00): active projects you scanned before, from the last scan on, rules only. New
    candidates wait in To sort – no digest line, no push."""
    time.sleep(300)
    while True:
        try:
            now = datetime.datetime.now()
            if now.hour == 3 and _PSCAN_NIGHT.get('day') != now.date():
                _PSCAN_NIGHT['day'] = now.date()
                for p in PROJ.load()['projects']:
                    last = PSCAN.entry(p['id']).get('last_scan') if p.get('status') == 'active' else None
                    if last:
                        project_mail_scan(p['id'], datetime.date.fromisoformat(last[:10]) - datetime.timedelta(days=1), nightly=True)
        except Exception as e:
            sys.stderr.write('project scan loop: %s\n' % str(e)[:200])
        time.sleep(600)


def _mail_checked(account, mid):
    """A mail picked by hand (Add a mail…): one of your accounts, never a private contact's – the mail file must be found."""
    if account not in config().get('accounts', {}):
        raise Bad('account not allowed')
    addrs = meeting_mail_addresses('', mid, strict=True)
    if not addrs or mail_privacy(addrs)[0]:
        raise Bad('this mail can\'t be added here (a private contact, or not on the Mac mini)')
    return addrs


def project_mail_action(action, p):
    pid = str(p.get('id') or '')[:100]
    pr = _project_of(pid)
    p['title'] = pr.get('name')                         # the log line names the project, never a mail
    try:
        if action == 'project_mail_scan':
            if PSCAN.status.get(pid, {}).get('running'):
                return {'running': True}
            since = PSCAN.set_since(pid, p['since']) if p.get('since') else None
            threading.Thread(target=project_mail_scan, args=(pid, since), daemon=True).start()
            return {'started': True}
        if action == 'project_mail_add' and isinstance(p.get('mail'), dict):
            mail = p['mail']
            mid = str(mail.get('message_id') or '')[:300]
            addrs = _mail_checked(str(mail.get('account') or ''), mid)
            if _is_protected_mail(mail.get('account'), addrs) and not _wp_owns(_project_workplace(pr), mail.get('account'), addrs):
                raise Bad('a protected workplace\'s mail goes only to that workplace\'s project')
            p = dict(p, message_id=mid, mail={'account': mail.get('account'), 'message_id': mid, 'subject': str(mail.get('subject') or '')[:200],
                                              'from': str(mail.get('from') or '')[:120], 'address': '', 'date': mail.get('date'), 'why': ['added by hand']})
        if action == 'project_match_add':
            PROJ.action('project_sender_add', {'id': pid, 'match': p.get('match')})
            return PSCAN.action('project_match_dismiss', pid, p)   # offered once: now it's in Matches
        if action == 'project_mail_move':
            to = _project_of(str(p.get('to') or ''))
            e = PSCAN.entry(pid)
            mid = str(p.get('message_id') or '')[:300]
            rec = e['candidates'].get(mid) or e['added'].get(mid) or {}
            addrs = meeting_mail_addresses(rec.get('address') or rec.get('from'), mid)
            if _is_protected_mail(rec.get('account'), addrs) and not _wp_owns(_project_workplace(to), rec.get('account'), addrs):
                raise Bad('a protected workplace\'s mail can only move to that workplace\'s own project')
            return PSCAN.action(action, pid, p, other_pid=to['id'])
        if action == 'project_suggestion_done':
            return PSCAN.suggestion_done(pid, str(p.get('sid') or ''))
        if action == 'project_mail_attach':
            return project_mail_attach(pid, p)
        if action == 'project_read':
            return project_read(pid, pr, p)
        return PSCAN.action(action, pid, p)
    except _pscan.Bad as e:
        raise Bad(str(e))


def project_mail_attach(pid, p):
    """Add attachment to Documents: one attachment of a mail on the project's Mails card, copied into its Documents."""
    mid = str(p.get('message_id') or '')[:500]
    rec = PSCAN.entry(pid)['added'].get(mid)
    if not rec:
        raise Bad('add the mail to the project first')
    _mail_checked(rec.get('account'), mid)
    n = str(int(p.get('n') or 1))
    try:
        rp = mailsearch.path_for_mid(mid)
        if not rp:
            raise mailsearch.NotDownloaded(rec['account'], mid)
        name, ctype, data = mailsearch.attachment(mailsearch._token({'path': rp, 'account': rec['account'], 'mid': mid}), n)
    except mailsearch.NotDownloaded:
        name, ctype, data = attachment_file(rec['account'], mid, n)
    from projects import Bad as ProjectsBad
    try:
        return PROJ.upload(pid, name, ctype, data)
    except ProjectsBad as e:
        raise Bad(str(e))


def project_read(pid, pr, p):
    """Read with Claude: only mails on this project's Mails card that you picked; never a private contact's, and a
    protected workplace's only for that workplace's project. One read-only run; the cards wait for your tap."""
    want = [str(x)[:500] for x in (p.get('message_ids') or []) if x][:20]
    if not want:
        raise Bad('pick the mails to read')
    if RUNNER.project_read_busy():
        raise Bad('Axella is already reading mails for a project – a moment')
    added = PSCAN.entry(pid)['added']
    wp = _project_workplace(pr)
    wp_all = bool(wp) and MEET.ai_defaults().get(wp['id']) == 'all'   # the workplace's AI setting (Meetings)
    mails, kept = [], 0
    for mid in want:
        m = added.get(mid)
        if not m or m.get('account') not in config().get('accounts', {}):
            continue
        addrs = meeting_mail_addresses(m.get('from'), mid, strict=True)
        if not addrs or mail_privacy(addrs)[0]:
            continue
        if _is_protected_mail(m['account'], addrs):
            # a protected workplace's mail goes to Claude only on that workplace's own project, and only when the
            # workplace's AI setting is "all" – otherwise it stays on the Mac mini
            if not (_wp_owns(wp, m['account'], addrs) and wp_all):
                kept += 1
                continue
        try:
            sender, when = mailsearch.sender_of(mailsearch.path_for_mid(mid))
        except Exception:
            sender, when = '', ''
        mails.append({'account': m['account'], 'message_id': mid, 'subject': str(m.get('subject') or '')[:200],
                      'sender': sender, 'date': when or m.get('date')})
    note = None
    if kept:
        name = (wp or {}).get('name') or 'a protected workplace'
        note = '%d mail%s from %s stay%s on the Mac mini (its AI setting)' % (kept, '' if kept == 1 else 's', name, 's' if kept == 1 else '')
    if not mails:
        raise Bad(note or 'none of these mails can be read here')
    rid = RUNNER.project_read_request(pid, mails)
    PSCAN.set_reading(pid, rid)
    return {'id': rid, 'mails': len(mails), 'kept': kept, 'note': note}


def project_read_ingest():
    """Finished readings (state/project-read/<id>.json) → suggestion cards on the project; files to done/."""
    folder = os.path.join(STATE_DIR, 'project-read')
    for req in glob.glob(os.path.join(folder, '*.request.json')):
        rid = os.path.basename(req)[:-len('.request.json')]
        res = os.path.join(folder, rid + '.json')
        rq = load_json(req, {}) or {}
        if not os.path.exists(res):
            if not RUNNER.project_read_busy() and time.time() - os.path.getmtime(req) > 120 and rq.get('project'):
                PSCAN.set_suggestions(rq['project'], [], rid)          # ended without a result: stop "Reading…"
                os.makedirs(os.path.join(folder, 'done'), exist_ok=True)
                os.replace(req, os.path.join(folder, 'done', os.path.basename(req)))
            continue
        try:
            cards = _pscan.clean_read(load_json(res, {}), rq.get('mails') or [])
            n = PSCAN.set_suggestions(str(rq.get('project') or ''), cards, rid)
            log_auto('project_read', 'Projects: %d suggestions from %d mails' % (n, len(rq.get('mails') or [])))
        except Exception as e:
            sys.stderr.write('project read ingest: %s\n' % str(e)[:200])
        os.makedirs(os.path.join(folder, 'done'), exist_ok=True)
        for f in (req, res):
            try:
                os.replace(f, os.path.join(folder, 'done', os.path.basename(f)))
            except OSError:
                pass


def _project_read_loop():
    while True:
        try:
            project_read_ingest()
        except Exception as e:
            sys.stderr.write('project read ingest: %s\n' % str(e)[:200])
        time.sleep(15)


def project_mail_view(pid):
    p = _project_of(pid)
    v = PSCAN.view(p)
    v['status'] = dict(PSCAN.status.get(pid) or {})
    v['since_default'] = _pscan.since_of(PSCAN.entry(pid), datetime.date.today()).isoformat()
    try:
        trips_all = TRIPS.load()['trips']
    except Exception:
        trips_all = []
    v['trip_offers'] = PSCAN.trip_suggestions(p, trips_all)
    linked = []
    for t in trips_all:
        if t.get('id') in v['trips']:
            nxt = next((b for b in sorted(t.get('bookings') or [], key=lambda b: str(b.get('start') or ''))
                        if str(b.get('start') or '') >= datetime.datetime.now().astimezone().isoformat() and b.get('status') != 'cancelled'), None)
            linked.append({'id': t['id'], 'title': t.get('title'), 'start': t.get('start'), 'end': t.get('end'),
                           'bookings': len(t.get('bookings') or []), 'next': {'title': nxt.get('title'), 'start': nxt.get('start')} if nxt else None})
    v['linked_trips'] = linked
    return v


def trip_read_ingest():
    """Take in finished Claude readings (state/trips-read/<id>.json): checked against their request, then into the
    trips; the files move to state/trips-read/done/."""
    folder = os.path.join(STATE_DIR, 'trips-read')
    for req in glob.glob(os.path.join(folder, '*.request.json')):
        rid = os.path.basename(req)[:-len('.request.json')]
        res = os.path.join(folder, rid + '.json')
        if not os.path.exists(res):
            if TRIPS.status.get('reading') == rid and not RUNNER.trip_read_busy() and time.time() - os.path.getmtime(req) > 120:
                TRIPS.status.update(reading=None, read_error='the reading run ended without a result – see Runs and logs')
            continue
        try:
            asked = (load_json(req, {}) or {}).get('mails') or []
            bookings, none = trips.clean_read(load_json(res, {}), asked)
            r = trips.take_read(TRIPS, bookings, none, trust=_trip_update_trust)
            TRIPS.status.update(reading=None, read_error=None, last_read=dict(r, at=now_iso()))
            log_auto('trip_read', 'Trips: %d bookings read from %d mails' % (r['bookings'], len(asked)))
        except Exception as e:
            TRIPS.status.update(reading=None, read_error=str(e)[:200])
        os.makedirs(os.path.join(folder, 'done'), exist_ok=True)
        for f in (req, res):
            try:
                os.replace(f, os.path.join(folder, 'done', os.path.basename(f)))
            except OSError:
                pass


def _trip_read_loop():
    while True:
        try:
            trip_read_ingest()
        except Exception as e:
            sys.stderr.write('trip read ingest: %s\n' % str(e)[:200])
        time.sleep(15)


def _trip_world(t):
    kinds = {n: (a.get('kind') if isinstance(a, dict) else None) for n, a in (config().get('accounts') or {}).items()}
    if t.get('ctx') in ('work', 'private'):
        return t['ctx']
    ks = {kinds.get((b.get('source') or {}).get('account')) for b in t.get('bookings') or []} - {None}
    return next(iter(ks)) if len(ks) == 1 and next(iter(ks)) in ('work', 'private') else None


def trip_calendar(action, p):
    """Trips → Calendar, on your tap only (Trips v2 §3): per trip or per item into the calendar you pick (the last one
    per world is remembered); a changed or cancelled booking's event is updated or removed only when you tap it."""
    import calendar_view as _cv
    tid = str(p.get('id') or '')
    d = TRIPS.load()
    t = next((x for x in d['trips'] if x['id'] == tid), None)
    if not t:
        raise Bad('unknown trip')
    world = _trip_world(t)
    link = str(config().get('dashboard_url') or '').strip()
    link = (link.rstrip('/') + '/?v=trips') if re.match(r'^https://[\w.-]+(:\d+)?(/[\w./-]*)?$', link) else ''

    def cal(act, body):
        _PENDING['data'] = None
        try:
            return _cv.edit(RUNNER.mcp_file(), config().get('calendars') or [], act, body, os.path.join(BACKUP_DIR, 'events'),
                            cache_file=os.path.join(STATE_DIR, 'macuse-calendar-tools.json'))
        except _cv.CalendarError as e:
            raise Bad(str(e))
    try:
        if action == 'trip_cal_add':
            calname = str(p.get('calendar') or '')[:120]
            if not calname:
                raise Bad('pick a calendar')
            _, bs, _ = TRIPS.cal_targets(tid, p.get('keys') if isinstance(p.get('keys'), list) else None)
            if not bs:
                raise Bad('nothing to add – everything is in the calendar already (cancelled items never go in)')
            n = 0
            for b in bs[:40]:
                ev = trips.cal_event(t, b, calname, link)
                r = cal('cal_add', ev)
                TRIPS.set_cal(tid, b['key'], {'id': r.get('id'), 'calendar': calname, 'start': ev['start'], 'end': ev['end']}, world, calname)
                n += 1
            p['title'] = '%s: %d in %s' % (t['title'][:50], n, calname[:20])
            return {'added': n, 'calendar': calname}
        b = next((x for x in t['bookings'] if x['key'] == p.get('key')), None)
        if not b or not b.get('cal'):
            raise Bad('that booking is not in the calendar')
        c = b['cal']
        if action == 'trip_cal_remove' or b.get('status') == 'cancelled':
            r = cal('cal_delete', {'id': c.get('id'), 'start': c.get('start'), 'title': b.get('title')})
            TRIPS.set_cal(tid, b['key'], None)
            p['_backup'] = r.get('backup')              # Restore in the activity log (the calendar's own backup)
            p['title'] = (b.get('title') or '')[:80]
            return {'removed': True, 'backup': r.get('backup')}
        ev = trips.cal_event(t, b, c.get('calendar'), link)
        cal('cal_update', {'id': c.get('id'), 'start': c.get('start'), 'title': ev['title'], 'notes': ev['notes'],
                           'new_start': ev['start'], 'new_end': ev['end']})
        TRIPS.set_cal(tid, b['key'], dict(c, start=ev['start'], end=ev['end']))
        p['title'] = (b.get('title') or '')[:80]
        return {'updated': True}
    except trips.Bad as e:
        raise Bad(str(e))


def _trip_update_trust(b, x):
    """May this update (b, from a mail) change booking x by itself? (ok, the update sender's domain). Only when the
    update's mail is clean (the scam check), passed the sender checks for its sender's domain, and that domain is the
    domain of the mail the booking came from. A booking from before addresses were kept: its mail's sender is looked up."""
    import email as _em
    import email.policy  # noqa: F401
    src = b.get('source') or {}
    dom = trips.mail_domain(src)
    xsrc = dict(x.get('source') or {})
    if not xsrc.get('address') and xsrc.get('message_id'):
        try:
            xsrc['address'] = mailsearch.sender_of(mailsearch.path_for_mid(xsrc['message_id']))[0].lower()
        except Exception:
            pass
    if not dom or dom != trips.mail_domain(xsrc):
        return False, dom
    raw = _raw_of_mid(src.get('message_id')) if src.get('message_id') else None
    if not raw:
        return False, dom
    try:
        safe = SAFETY._safe_set(SAFETY.load())
    except Exception:
        safe = set()
    if _bills.mail_risk(raw, _known_people()[0], safe):
        return False, dom                                # flagged by the scam check, or a failed sender check
    try:
        msg = _em.message_from_bytes(raw, policy=_em.policy.default)
        frm = trips._addr(msg.get('From'))
        if trips.mail_domain({'address': frm}) != dom or dom not in _safety.sender_checks(msg)['passed']:
            return False, dom                            # the provider's own DMARC pass, for this very domain
    except Exception:
        return False, dom
    return True, dom


def trip_watch(now=None):
    """Every 30 min while a trip is near (14 days): the last 3 days of booking-looking mail, by rules only – updates
    (a cancellation, a new time in a newer mail) and "check-in is open" mails. Private contacts' and protected
    workplaces' mail are left out, as in the scan. Nothing is suggested from here; To sort is left alone."""
    now = now or datetime.datetime.now().astimezone()
    d = TRIPS.load()
    near = any(trips.parse_when(b.get('start')) and now - datetime.timedelta(days=1) <= trips.parse_when(b['start']) <= now + datetime.timedelta(days=14)
               for t in d['trips'] for b in t['bookings'])
    if not near:
        return 0
    cands = mailsearch.booking_candidates(mail_accounts(), trips.looks_like_booking, limit=60, days=3)
    found, chk = [], []
    for c in cands:
        try:
            addrs = mailsearch.addresses_of(c['path'])
        except Exception:
            addrs = [c.get('from_address')]
        if mail_privacy(addrs)[0] or any(profile.is_protected(c['account'], a) for a in addrs if a):
            continue
        try:
            raw = mailsearch._raw(c['path'])
            src = {'account': c['account'], 'message_id': c['message_id'], 'subject': c['subject'][:200], 'date': c['date'],
                   'from': c.get('from_name') or c.get('from_address') or '', 'address': str(c.get('from_address') or '').lower()[:200]}
            for n, b in enumerate(trips.bookings_in(raw, c['subject'], c['from_address'], now.date(), from_name=c.get('from_name') or '')):
                if b.get('confidence') == 'data':
                    b['source'] = dict(src)
                    b['key'] = trips.key_of(b, n)
                    found.append(b)
            if trips.CHECKIN_RE.search(c['subject'] or ''):
                at = trips.parse_when(c.get('date'))
                if at:
                    chk.append({'text': c['subject'] + '\n' + trips._html_and_text(raw)[1][:50000], 'at': at, 'provider': c.get('from_name') or '',
                                'mail': src})
        except Exception:
            continue
    return TRIPS.watch(found, chk, now, _trip_update_trust)


def _trips_to_digest(name):
    """The trip line in a regular digest: changes, cancellations and check-in opening soon (Trips v2 §5) – each once."""
    import digestfile
    from recurring import add_spoken
    if not re.match(r'^\d{4}-\d{2}-\d{2}-\d{4}\.json$', name):
        return None
    path = os.path.join(DIGESTS_DIR, name)

    def change(dg):
        if not isinstance(dg, dict) or not isinstance(dg.get('items'), list) or dg.get('trips_line') is not None:
            return False, None
        sc = dg.get('scope') if isinstance(dg.get('scope'), list) and dg.get('scope') else None
        lines = TRIPS.alerts(ctx_of=_trip_world, worlds=sc, mark=True)
        if re.match(r'^\d{4}-\d{2}-\d{2}-0[5-9]\d\d\.json$', name):
            # dated checklist items (only ones you gave a date) due within 3 days – the count only: the items' own words
            # stay in trip-checklists.json, which no Claude run reads (this digest is read by later runs)
            live = [t for t in TRIPS.load()['trips'] if not sc or _trip_world(t) not in ('work', 'private') or _trip_world(t) in sc]
            per = {}
            for x in TRIP_CHECKS.due(live, datetime.date.today(), days=3):
                per[x['trip_title']] = per.get(x['trip_title'], 0) + 1
            lines += ['%d checklist item%s for %s due soon' % (n, '' if n == 1 else 's', tt) for tt, n in per.items()]
        dg['trips_line'] = len(lines)
        if lines:
            text = '. '.join(lines[:4]) + '.'
            dg['items'].append({'id': '%s-p2-trips' % name[:-5].replace('-', '')[:12], 'section': 'p2', 'channel': 'trips', 'topic': 'Trips',
                                'headline': text, 'detail': 'In Trips. Nothing is changed with the airline or hotel.', 'link': 'trips',
                                'first_seen': dg.get('generated') or ''})
            add_spoken(DIGESTS_DIR, name, dg, text)
        return True, len(lines)
    return digestfile.update(path, change)


def _trip_watch_loop():
    """The watch every 30 min; pushes every 5 min (within 48 h of departure, urgency rules and Discreet push)."""
    time.sleep(120)
    last = 0
    while True:
        try:
            if time.time() - last > 1800:
                last = time.time()
                trip_watch()
            due = TRIPS.pushes()
            if due and SCHED.status().get('urgent') and load_json(PUSH_SUBS_FILE, []):
                discreet = PRIV.load().get('discreet_push')
                for kind, text, mark in due[:5]:
                    push_send({'title': 'Axella · Trips', 'body': 'A trip update – open Trips' if discreet else text[:150],
                               'tag': 'axella-trip-' + str(mark[1])[:20], 'url': '/axella/?v=trips'})
                TRIPS.pushes(mark=[m for _, _, m in due[:5]])
        except Exception as e:
            sys.stderr.write('trip watch: %s\n' % str(e)[:200])
        time.sleep(300)


def trip_scan():
    """Read the booking-looking mails of the last 18 months on the Mac mini (rules only, never Claude) and turn the
    upcoming bookings into suggested trips. Private and hidden contacts' mail and a protected workplace's mail are left
    out. Runs in the background; TRIPS.status says how it went."""
    st = TRIPS.status
    st.update(running=True, error=None, found=None, read=0, skipped=0, unread=[])
    try:
        today = datetime.date.today()
        since = trips.since_of(TRIPS.load(), today)
        cands = mailsearch.booking_candidates(mail_accounts(), trips.looks_like_booking, limit=trips.MAX_MAILS,
                                              days=min(trips.SCAN_DAYS, (today - since).days + 1))
        found = []
        own = {a.lower() for a in own_addresses()}
        for c in cands:
            if str(c.get('from_address') or '').lower() in own:   # a booking he forwarded himself: his name is not the hotel
                c = dict(c, from_address='', from_name='')
            try:
                addrs = mailsearch.addresses_of(c['path'])
            except Exception:
                addrs = [c.get('from_address')]
            if mail_privacy(addrs)[0] or any(profile.is_protected(c['account'], a) for a in addrs if a):
                st['skipped'] += 1
                continue
            why = []
            try:
                sent = datetime.date.fromisoformat(str(c.get('date') or '')[:10]) if c.get('date') else None
            except ValueError:
                sent = None
            try:
                bs = trips.bookings_in(mailsearch._raw(c['path']), c['subject'], c['from_address'], today, sent=sent,
                                       from_name=c.get('from_name') or '', why=why, since=since)
            except Exception:
                bs, why = [], ['could not be read']
            st['read'] += 1
            src = {'account': c['account'], 'message_id': c['message_id'], 'subject': c['subject'][:200], 'date': c['date'],
                   'from': c.get('from_name') or c.get('from_address') or '', 'address': str(c.get('from_address') or '').lower()[:200]}
            if not bs and why and why[0] not in ('already over', 'not travel'):
                st['unread'].append(dict(src, why=why[0]))     # looked like a booking, but not understood: shown on Trips
            for n, b in enumerate(bs):
                b['source'] = dict(src)
                b['key'] = trips.key_of(b, n)
                found.append(b)
        uniq = {}
        for b in found:
            uniq.setdefault(b['key'], b)
        d = TRIPS.merge_scan(list(uniq.values()), today)
        st['found'] = len([b for t in d['suggested'] for b in t['bookings']])
        st['unread'] = sorted(st['unread'], key=lambda x: str(x.get('date') or ''), reverse=True)[:100]
        TRIPS.set_unsorted(st['unread'])
        log_auto('trip_scan', 'Trip scan: %d mails read, %d upcoming bookings suggested' % (st['read'], st['found']))
    except Exception as e:
        st['error'] = str(e)[:200]
        sys.stderr.write('trip scan: %s\n' % str(e)[:200])
    finally:
        st['running'] = False


import birthdays  # noqa: E402  (birthdays from Contacts: Favourites + your switches, one line in the morning digest)
BDAY = birthdays.Birthdays(STATE_DIR)


def contacts_overview(refresh=False):
    """The Contacts page: the book, each person marked whether their birthday shows."""
    v = BOOK.overview(refresh=refresh)
    st = BDAY.settings()
    import people as _pp
    keep = _pp.People(STATE_DIR).keep()                # keep in touch (people.py) – the rhythm on each card
    for p in v['people']:
        if p.get('id'):
            p['birthday_shown'] = BDAY.shown(p, st)
        k = keep.get(_pp.pid_of(p))
        if k:
            p['keep'] = k['every']
    return v


def _birthday_loop():
    """Every 15 min: state/birthdays-today.json for the morning digest (first names and age only)."""
    time.sleep(30)
    while True:
        try:
            BDAY.write_today(BOOK.overview()['people'])
        except Exception as e:
            sys.stderr.write('birthdays: %s\n' % str(e)[:200])
        time.sleep(900)
import reports as reports_mod  # noqa: E402  (Report a problem – reports/, never readable by Claude runs)
REPORTS = reports_mod.Reports(BASE, STATE_DIR, config)


def report_names():
    """Names the text check looks for: private contacts, contacts.md, and the people in the last 90 days' digests."""
    names = {c.get('name') for c in PRIV.load()['contacts']}
    try:
        with open(CONTACTS_FILE, encoding='utf-8') as f:
            for line in f:
                m = re.match(r'^\s*[-*]\s+([^–\-(+\d][^–(+\d]{2,60})', line)
                if m:
                    names.add(m.group(1).strip())
    except OSError:
        pass
    try:
        db = STORE._db()
        try:
            for (n,) in db.execute("SELECT DISTINCT from_name FROM items WHERE from_name IS NOT NULL AND generated > date('now','-90 day') LIMIT 2000"):
                names.add(n)
        finally:
            db.close()
    except Exception:
        pass
    return [n for n in names if n and not re.search(r'@|\d{4}', n)]


def report_connectors():
    out = []
    try:
        if load_json(os.path.join(STATE_DIR, 'whatsapp.json'), {}).get('ok'):
            out.append('whatsapp')
    except Exception:
        pass
    try:
        import signal_export
        if signal_export.status().get('linked'):
            out.append('signal')
    except Exception:
        pass
    if os.path.exists(os.path.expanduser('~/Library/Messages/chat.db')):
        out.append('imessage')
    if (config().get('voice') or {}).get('url'):
        out.append('calls')
    return out
BRIEF = Briefings(STATE_DIR)   # research/news briefs (state/briefings.json, state/briefs/)
RUNNER.briefings = BRIEF
from cleanup import Cleanup, Bad as CleanupBad  # noqa: E402
CLEAN = Cleanup(BASE, STATE_DIR, osa, lambda: config().get('accounts', {}), log=sys.stderr)   # mail cleanup (Settings)
# recurring reminders add ordinary tasks (source "reminder") through the same locked path as the dashboard
REM = Reminders(STATE_DIR, lambda text, due, rid: task_action('task_add', {'text': text, 'due': due, 'source': 'reminder', 'reminder': rid}))
_schedule_mod.IMMEDIATE = lambda: RUNNER.load()['enabled']


# ---------- slow actions run in the background: a tap answers at once, Mail/Calendar work happens after ----------
import queue as _queue  # noqa: E402
SLOW_ACTIONS = {'draft', 'draft_new', 'reply_send', 'mail_send', 'invite_respond', 'file', 'trash', 'trash_batch', 'event', 'document_forward',
                'cal_invite_send', 'cal_invite_update', 'cal_invite_cancel', 'block_hold',
                'contact_add', 'contact_update', 'contact_delete', 'contact_restore',
                'cal_add', 'cal_update', 'cal_delete', 'cal_restore', 'trip_cal_add', 'trip_cal_sync', 'trip_cal_remove'}
# changing contacts and the calendar: the owner's own login only – anyone else on the access list reads
OWNER_ONLY = {'note_save', 'note_keep', 'note_delete', 'note_restore', 'note_todo', 'teach_not_important', 'rule_remove', 'rule_restore', 'suggest_accept', 'suggest_later', 'suggest_never',
              'calm_setup_step', 'calm_setup_dismiss', 'backup_export', 'backup_auto', 'backup_run', 'away_archive', 'away_undo', 'away_catchup', 'block_settings', 'block_never', 'block_not_now', 'block_hold', 'renewal_add', 'renewal_not', 'renewal_update', 'renewal_snooze', 'renewal_let_renew', 'renewal_renewed', 'renewal_past',
              'renewal_delete', 'renewal_scan', 'renewal_todo', 'contact_add', 'contact_update', 'contact_delete', 'contact_restore', 'cal_add', 'cal_update', 'cal_delete', 'cal_restore',
              'project_mail_scan', 'project_mail_add', 'project_mail_not', 'project_mail_undo_not', 'project_mail_remove',
              'project_mail_undo_remove', 'project_mail_move', 'project_match_add', 'project_match_dismiss', 'project_trip_link',
              'project_trip_unlink', 'project_mail_attach', 'project_read', 'project_suggestion_done',
              'cal_invite_send', 'cal_invite_update', 'cal_invite_cancel', 'meeting_service_connect', 'meeting_service_disconnect',
              'meeting_service_default',
              'meeting_add', 'meeting_update', 'meeting_delete', 'meeting_restore', 'meeting_url_add', 'meeting_mail_add',
              'meeting_material_update', 'meeting_material_remove', 'meeting_assist', 'meeting_upload',
              'meeting_transcript_upload', 'meeting_transcript_paste', 'meeting_transcribe', 'meeting_ai_default',
              'meeting_record_chunk', 'meeting_record_finish', 'meeting_record_drop', 'meeting_speakers', 'meeting_project_add', 'meeting_point_outcome', 'birthday_show', 'person_note', 'keep_set',
              'trip_scan', 'trip_confirm', 'trip_dismiss', 'trip_undismiss', 'trip_rename', 'trip_apply_new', 'trip_not_part', 'trip_remove', 'trip_restore',
              'trip_mail_add', 'trip_mail_new', 'trip_mail_not_travel', 'trip_suggest_add', 'trip_move_booking', 'trip_read',
              'trip_void', 'trip_unvoid', 'trip_booking_rename', 'trip_booking_edit', 'trip_ctx', 'trip_part_again',
              'trip_undo', 'trip_merge', 'trip_split', 'trip_item_add', 'trip_item_remove', 'trip_cancel', 'trip_plan_booked',
              'trip_plan_drop', 'trip_plan_replace', 'trip_check_add', 'trip_check_set', 'trip_check_remove',
              'trip_update_apply', 'trip_update_ignore', 'trip_cal_add', 'trip_cal_sync', 'trip_cal_remove'}
BACKUP_DIR = os.path.join(STATE_DIR, 'deleted')       # copies of deleted contacts, events and meeting preps, 90 days
from meetings import Meetings  # noqa: E402  (meeting prep – owner only, reads too)
import scheduled as _scheduled_mod  # noqa: E402  (Send later)
SCHED_SEND = _scheduled_mod.Scheduled(STATE_DIR, OUTBOX_DIR)
MEET = Meetings(STATE_DIR, os.path.join(BACKUP_DIR, 'meetings'))
import oauth_flow as _oauth  # noqa: E402  (Calendar: signing in to Teams, Meet and Zoom – tokens in the Keychain)
import meeting_providers as _mprov  # noqa: E402  (Calendar: online meetings, one interface for every service)
import calendar_invites as _cinv  # noqa: E402  (Calendar: invitees – iCloud CalDAV and Microsoft Graph send them)
import calendar_online as _conline  # noqa: E402  (Calendar: which calendar can do what, and the taps)


def _svc_note(provider, action):
    tally('svc:' + str(provider)[:20])                 # What leaves my home: one count per call to a meeting service


OAUTH = _oauth.OAuth(note=_svc_note)
MSERV = _mprov.Services(STATE_DIR, OAUTH, note=_svc_note)
INVITES = _cinv.Invites(STATE_DIR, _cinv.CalDav(OAUTH.kc, note=_svc_note), _cinv.Graph(OAUTH, note=_svc_note))
_MAC_CALS = {'at': 0, 'cals': []}


def _macuse_cals():
    """The calendars Macuse can change (title, account, can_modify) – asked at most every 5 minutes."""
    import calendar_view
    if time.time() - _MAC_CALS['at'] > 300:
        try:
            c = calendar_view.caps(RUNNER.mcp_file(), os.path.join(STATE_DIR, 'macuse-calendar-tools.json'))
            _MAC_CALS.update(at=time.time(), cals=c.get('calendars') or [])
        except Exception:
            return _MAC_CALS['cals']
    return _MAC_CALS['cals']


ONLINE = _conline.Online(MSERV, INVITES, lambda: profile.calendars(), lambda: profile.workplaces(),
                         lambda: config().get('accounts') or {}, _macuse_cals, lambda: own_addresses(),
                         lambda: str(config().get('dashboard_url') or '').strip() or None)


def _oauth_redirect(host):
    base = str(config().get('dashboard_url') or '').strip().rstrip('/')
    if not base:
        h = str(host or '').strip().lower()
        if not re.match(r'^[a-z0-9-]+\.[a-z0-9-]+\.ts\.net$', h):
            raise Bad('set "dashboard_url" in actions-config.json to your dashboard\'s https Tailscale address')
        base = 'https://%s/axella' % h
    if not base.startswith('https://'):
        raise Bad('"dashboard_url" must be the https Tailscale address')
    return base + '/api/oauth_callback'


def _who_connected(provider):
    """After Connect: the account a service is connected with (to show it, and for protected workplaces)."""
    try:
        tok = OAUTH.access_token(provider)
        url = {'teams': 'https://graph.microsoft.com/v1.0/me?$select=mail,userPrincipalName',
               'zoom': 'https://api.zoom.us/v2/users/me'}.get(provider)
        if not url:
            return
        _svc_note(provider, 'who')
        st, out = _oauth.http('GET', url, headers={'Authorization': 'Bearer ' + tok})
        if st == 200:
            OAUTH.set_account(provider, out.get('mail') or out.get('userPrincipalName') or out.get('email'))
    except _oauth.Bad:
        pass


def online_action(action, p):
    """Calendar → invitees and online meetings. Sending always needs its confirm word (calendar_online.py)."""
    try:
        if action == 'meeting_service_connect':
            p['title'] = 'Connect a meeting service'
            return {'url': OAUTH.start(str(p.get('provider') or ''), _oauth_redirect(p.get('_host')))}
        if action == 'meeting_service_disconnect':
            p['title'] = 'Disconnect a meeting service'
            return OAUTH.disconnect(str(p.get('provider') or ''))
        if action == 'meeting_service_default':
            p['title'] = 'Default meeting service'
            if p.get('calendar') not in profile.calendar_names() and p.get('calendar') not in [c.get('title') for c in _macuse_cals()]:
                raise Bad('unknown calendar')
            return {'defaults': MSERV.set_default(p['calendar'], p.get('provider'))}
        p['_owner_name'] = (profile.owner() or {}).get('name') or None
        if action in ('cal_invite_send', 'cal_invite_update', 'cal_invite_cancel'):
            # the same hourly brake as mail: each invitation, update or cancellation counts as one send
            now = time.time()
            with LOCK:
                if len([x for x in load_json(SENT_FILE, []) if now - _sent_ts(x) < 3600]) >= SEND_MAX:
                    raise Bad('more than %d sends in an hour – wait a little, or use Calendar' % SEND_MAX)
            res = {'cal_invite_send': ONLINE.send, 'cal_invite_update': ONLINE.update, 'cal_invite_cancel': ONLINE.cancel}[action](p)
            if action != 'cal_invite_update' or p.get('confirm') == 'send':      # a silent save tells no one
                n = len((res or {}).get('people') or []) if action != 'cal_invite_cancel' else None
                with LOCK:
                    sent = load_json(SENT_FILE, [])
                    sent.append({'at': now_iso(), 'ts': time.time(), 'status': 'sent', 'action': action,
                                 'key': 'cal_invite:%s:%d' % (str((res or {}).get('uid') or '')[:200], int(now)),
                                 'account': str(p.get('calendar') or (res or {}).get('calendar') or '')[:100],
                                 'to': ('%d people' % n) if n is not None else 'the invited people',
                                 'subject': str(p.get('title') or '')[:200]})
                    with open(SENT_FILE, 'w', encoding='utf-8') as f:
                        json.dump(sent[-1000:], f, ensure_ascii=False, indent=1)
            return res
    except _oauth.Bad as e:
        raise Bad(str(e))
    raise Bad('unknown action')
MEET.project_text = _project_text    # "Add from project…" reads the project's own copy


def _wrap_facts(worlds):
    """The week wrap's facts (wrap.py) for a Friday work wrap or the Sunday week-ahead."""
    import wrap as _wrap
    try:
        people = BOOK.overview()['people']
    except Exception:
        people = []
    try:
        trips = TRIPS.view().get('trips') or []
    except Exception:
        trips = []
    try:
        line = _calm.one_line(_calm.calm(STORE, STATE_DIR, hours=config().get('work_hours') if isinstance(config().get('work_hours'), dict) else None))
    except Exception:
        line = ''
    return _wrap.facts(worlds, datetime.date.today(), STORE, STATE_DIR, preps=MEET.overview(), people=people,
                       birthdays=BDAY, trips=trips, calm_line=line)


RUNNER.wrap_facts = _wrap_facts

import people as _people  # noqa: E402  (People page and keep in touch – local only, never sent to Claude)
PEOPLE = _people.People(STATE_DIR)
BDAY.keep = lambda: set(PEOPLE.keep())               # keep-in-touch people join the birthday scope


def _person(pid):
    ppl = BOOK.overview()['people']
    p = _people.find(ppl, pid)
    if not p:                                        # "Open person" from an item: their address or number
        k = _people._key(pid)
        p = next((x for x in ppl if k and k in _people.keys_of(x)), None)
    if not p:
        raise Bad('Not in your Contacts or mail yet')
    return p, ppl


def _digest_items_newest():
    """All items of the newest regular digest (open between you: to answer, waiting)."""
    n = _newest_digest()
    d = load_json(os.path.join(DIGESTS_DIR, n + '.json'), {}) if n else {}
    return [i for i in (d.get('items') or []) if isinstance(i, dict)] if isinstance(d, dict) else []


def _people_index():
    idx = _people.Index(STORE)
    idx.extra = _COMMIT.get('last') or {}
    return idx


def person_view(pid):
    p, ppl = _person(pid)
    pid = _people.pid_of(p)
    unique = _people._name_key(p.get('name')) not in _people.ambiguous_names(ppl)
    return _people.view(p, STORE, _people_index(), _digest_items_newest(), _COMMIT['debt'], PROM.load()['items'],
                        load_json(TASKS_FILE, []), MEET.overview(), note=PEOPLE.notes().get(pid), keep=PEOPLE.keep().get(pid),
                        unique_name=unique)


def keep_view():
    """Keep in touch for the Contacts page: who is on it, and who is due (no message text, only times)."""
    ppl = BOOK.overview()['people']
    due = {x['id']: x for x in PEOPLE.due(ppl, _people_index())} if _COMMIT['at'] else {}
    out = []
    for pid, k in PEOPLE.keep().items():
        p = _people.find(ppl, pid)
        if p:
            out.append({'id': pid, 'name': p.get('name'), 'every': k['every'], 'due': pid in due,
                        'days': due[pid]['days'] if pid in due else None, 'last': due[pid]['last'] if pid in due else None})
    out.sort(key=lambda x: (not x['due'], -(x['days'] or 0), str(x['name']).lower()))
    return {'people': out, 'rhythms': {str(k): v for k, v in _people.RHYTHMS.items()}}


def people_action(action, p):
    try:
        person, _ = _person(p.get('id'))
        pid = _people.pid_of(person)
        if action == 'person_note':
            p['title'] = 'Note on a person'          # the note itself never goes into the activity log
            PEOPLE.set_note(pid, p.get('text'))
            return 'saved'
        every = p.get('every')
        PEOPLE.set_keep(pid, every)
        p['title'] = 'Keep in touch: ' + (_people.RHYTHMS.get(int(every)) if every else 'off')
        try:
            BDAY.write_today(BOOK.overview()['people'])
        except Exception:
            pass
        return 'saved'
    except _people.Bad as e:
        raise Bad(str(e))


def _bill_pdf_text(data):
    import tempfile
    import meetings
    if not data or len(data) > 15 * 1024 * 1024:
        return ''
    fd, path = tempfile.mkstemp(suffix='.pdf')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        return meetings.file_text(path, '.pdf')
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _bill_text(mid):
    """A bill's own text and PDFs, read here by rules for its payment reference – never sent anywhere, never stored."""
    raw = _raw_of_mid(mid)
    return _bills.text_of_mail(raw, _bill_pdf_text) if raw else ''


def _bill_skip(mid, doc):
    """Why a document can't be a bill card (None = it can): a private or hidden sender ('private'), a mail flagged in a
    digest, by the scam check run on the mail itself or by a failed sender check ('scam' / 'auth' – blocked for good,
    also when the mail was never in a digest), or a mail that isn't on the Mac mini to check ('missing')."""
    addrs = re.findall(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', str(doc.get('from') or ''))
    if addrs and mail_privacy(addrs)[0]:
        return 'private'
    try:
        if SAFETY.flag_of({'message_id': mid}):
            return 'scam'
    except Exception:
        return 'scam'
    try:
        safe = SAFETY._safe_set(SAFETY.load())
    except Exception:
        safe = set()
    return _bills.mail_risk(_raw_of_mid(mid), _known_people()[0], safe)


def bills_view():
    docs = DOCS.load().get('documents') or {}
    tasks = load_json(TASKS_FILE, [])
    open_bills = {t.get('id') for t in tasks if t.get('type') == 'bill'}
    return {'suggestions': BILLS.suggestions(docs, known=_known_people()[0]), 'looks_paid': BILLS.find_looks_paid(docs, tasks),
            'refs': BILLS.refs(open_bills)}                     # each bill To do's payment details (not in tasks.json)


def bill_action(action, p):
    mid = str(p.get('id') or '')
    try:
        if action == 'bill_add':
            card = next((c for c in BILLS.suggestions(DOCS.load().get('documents') or {}, known=_known_people()[0]) if c['id'] == mid), None)
            if not card:
                raise Bad('this bill is not waiting any more')
            t = BILLS.task_for(card, p.get('edits') if isinstance(p.get('edits'), dict) else None)
            ref = t['bill'].get('reference') or {}
            tid = task_action('task_add', dict(t, source='bill'))           # the reference goes to bills.json there
            BILLS.set(mid, status='added', task_id=tid)
            BILLS.remember(card.get('vendor_key'), ref)                      # what the next bill is compared with
            p['title'] = t['text'][:80]
            return {'task_id': tid}
        if action == 'bill_paid_already':              # already paid: no To do; the Receipts entry is marked paid
            if not any(c['id'] == mid for c in BILLS.suggestions(DOCS.load().get('documents') or {})):
                raise Bad('this bill is not waiting any more')
            BILLS.set(mid, status='paid')
            try:
                DOCS.action('document_set', {'message_id': mid, 'paid': datetime.date.today().isoformat()})
            except Exception:
                pass
            p['title'] = 'Bill already paid'
            return {'id': mid}
        if action == 'bill_dismiss':                   # Not a bill – it never comes back
            BILLS.set(mid, status='dismissed')
            p['title'] = 'Not a bill'
            return {'id': mid}
        e = BILLS.set(mid)                             # bill_looks_paid: on = tick it off, off = it isn't paid
        if p.get('on', True):
            task_action('task_done', {'id': e.get('task_id')})
            p['title'] = 'Bill paid'
        else:
            BILLS.set(mid, looks_paid=None, looks_paid_ignored=True)
            p['title'] = 'Bill not paid yet'
        return {'id': mid}
    except _bills.Bad as e:
        raise Bad(str(e))


def _bills_loop():
    """Every 10 min: new bill cards from the Receipts register, payment references, "Looks paid"."""
    time.sleep(90)
    try:                                               # payment details still on To dos: move them to bills.json
        with LOCK:
            tasks = load_json(TASKS_FILE, [])
            if BILLS.take_refs(tasks):
                save_tasks(tasks)
    except Exception as e:
        sys.stderr.write('bills: %s\n' % str(e)[:200])
    while True:
        try:
            docs = DOCS.load().get('documents') or {}
            BILLS.refresh(docs, read_text=_bill_text, skip=_bill_skip)
            BILLS.find_looks_paid(docs, load_json(TASKS_FILE, []))
        except Exception as e:
            sys.stderr.write('bills: %s\n' % str(e)[:200])
        time.sleep(600)


def _keep_due():
    if not _COMMIT['at']:                             # the first scan (Mail, Messages …) hasn't run yet: no line rather than a wrong one
        return []
    return PEOPLE.due(BOOK.overview()['people'], _people_index())


def owner_logins():
    """actions-config.json "owner": {"logins": [...]} – else the first login on the dashboard's access list."""
    own = [str(x).strip() for x in ((config().get('owner') or {}).get('logins') or []) if str(x).strip()]
    if own:
        return set(own)
    acc = load_json(ACCESS_FILE, {})
    lst = acc.get('paths', {}).get('/axella/', acc.get('default', [])) or []
    return {lst[0]} if lst else set()
JOBS, JOBQ = {}, _queue.Queue()

# Sends are idempotent end to end: the dashboard makes a send_id (UUID) at the second tap and keeps it with a reply that
# waits in its outbox. The first POST with a send_id is accepted and remembered here for 48 h; any repeat – a lost
# response, a re-send from the outbox hours later, "force" or not – gets the earlier outcome and never a second mail.
SEND_IDS_FILE = os.path.join(STATE_DIR, 'send-ids.json')
SEND_ID_RE = re.compile(r'^[0-9a-fA-F-]{16,64}$')
SEND_ID_KEEP = 48 * 3600


def send_ids_load():
    d = load_json(SEND_IDS_FILE, {})
    if not isinstance(d, dict):
        d = {}
    now = time.time()
    return {k: v for k, v in d.items() if isinstance(v, dict) and now - (v.get('ts') or 0) < SEND_ID_KEEP}


def send_ids_save(d):
    tmp = SEND_IDS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, SEND_IDS_FILE)


def send_id_update(sid, **kw):
    if not sid:
        return
    with LOCK:
        d = send_ids_load()
        if sid in d:
            d[sid].update(kw)
            send_ids_save(d)


def send_id_status(sid):
    """What happened to the send with this id: None if the Mac mini never got it."""
    if not SEND_ID_RE.match(str(sid or '')):
        raise Bad('bad send_id')
    with LOCK:
        rec = send_ids_load().get(sid)
    if not rec:
        return None
    j = JOBS.get(rec.get('job') or '')
    state = j['state'] if j else rec.get('state')
    return {'state': state, 'job': rec.get('job') if j else None, 'at': rec.get('at'),
            'error': (j or {}).get('error') or rec.get('error')}


def send_id_accept(action, payload, login):
    """(response, None) for a repeat of an accepted send_id – the earlier outcome – or (None, sid) for a new one."""
    sid = payload.get('send_id')
    if sid is None:
        return None, None
    if not SEND_ID_RE.match(str(sid)):
        raise Bad('bad send_id')
    with LOCK:
        d = send_ids_load()
        rec = d.get(sid)
        if not rec:
            d[sid] = {'ts': time.time(), 'at': now_iso(), 'action': action, 'state': 'queued', 'job': None}
            send_ids_save(d)
            return None, sid
    log(login, action, payload, 'repeat of send %s: not sent again' % str(sid)[:12])
    j = JOBS.get(rec.get('job') or '')
    if j:                                              # still known here: the dashboard follows the same job
        return {'queued': True, 'job': j['id'], 'ahead': 0, 'repeat': True}, None
    if rec.get('state') == 'ok':
        return {'already_sent': True, 'repeat': True, 'at': rec.get('at')}, None
    if rec.get('state') == 'error':
        raise Bad('not sent: %s' % (rec.get('error') or 'it failed'))
    raise Bad('this send was accepted at %s, but Axella restarted before it finished – check Sent in Mail before '
              'sending it again' % str(rec.get('at') or '')[11:16])


def job_worker():
    """One at a time – Mail and Calendar don't like being driven in parallel."""
    while True:
        jid = JOBQ.get()
        job = JOBS.get(jid)
        if not job:
            continue
        job['state'], job['started'] = 'running', now_iso()
        p, login, action = job.pop('_payload'), job['login'], job['action']
        if action == 'mail_mark':                  # Keep Mail tidy: a batch of read / unread marks – no log line of its own
            try:
                job['result'], job['state'] = TIDY.run(), 'ok'
            except Exception as e:
                job['state'], job['error'] = 'error', str(e)[:300]
                sys.stderr.write('%s mail tidy: %s\n' % (now_iso(), str(e)[:200]))
            job['ended'] = now_iso()
            continue
        p.setdefault('_login', login)              # a Send later job: "scheduled"
        try:
            job['result'] = do_action(action, p)
            job['state'] = 'ok'
            if isinstance(job['result'], dict) and job['result'].get('backup'):
                p['_backup'] = job['result']['backup']
            log(login, action, p, 'ok')
        except Exception as e:      # Bad, AppleScript error or timeout
            job['state'], job['error'] = 'error', str(e)[:300]
            log(login, action, p, 'error: ' + str(e)[:300])
        job['ended'] = now_iso()
        try:
            send_id_update(p.get('send_id'), state=job['state'], error=job.get('error'))
        except Exception as e:
            sys.stderr.write('%s send_id: %s\n' % (now_iso(), str(e)[:200]))
        if len(JOBS) > 300:
            for k in sorted(JOBS, key=lambda k: JOBS[k]['created'])[:100]:
                JOBS.pop(k, None)


def queue_job(action, payload, login):
    import uuid
    if action in ('reply_send', 'mail_send', 'invite_respond'):   # a double tap / second tab: one send per item in the queue
        same = payload.get('item_id') or (payload.get('to'), payload.get('subject'))
        for j in JOBS.values():
            pj = j.get('_payload') or {}
            if j['action'] == action and j['state'] in ('queued', 'running') and (pj.get('item_id') or (pj.get('to'), pj.get('subject'))) == same:
                return j['id']
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {'id': jid, 'action': action, 'login': login, 'state': 'queued', 'created': now_iso(),
                 'title': payload.get('title'), '_payload': payload}
    JOBQ.put(jid)
    return jid


import mail_tidy as _mail_tidy  # noqa: E402  (Keep Mail tidy: handled in Axella means read in Mail)
TIDY = _mail_tidy.Tidy(osa, FIND_MESSAGE, _tidy_allowed, lambda: queue_job('mail_mark', {}, 'axella'))


class Handler(BaseHTTPRequestHandler):
    server_version = 'AxellaActions/1'

    def _send_text(self, code, text):
        body = text.encode()
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _login(self):
        login = tailnet_login(self.headers)
        if not login:
            return None
        # The Mac itself (a tagged node, "node:<name>") never gets the API: any program on the Mac can reach the
        # tailnet URL, so a node login proves nothing about who is asking. Nothing in Axella calls the API locally.
        if login.startswith('node:'):
            return None
        acc = load_json(ACCESS_FILE, {})
        allowed = acc.get('paths', {}).get('/axella/', acc.get('default', []))
        if not allowed or login not in allowed:              # fail closed: a missing or empty list lets nobody in
            return None
        return login

    def _action(self):
        return self.path.split('?')[0].rstrip('/').split('/')[-1]

    def do_GET(self):
        login = self._login()
        if not login:
            return self._send(403, {'ok': False, 'error': 'not allowed'})
        a = self._action()
        if a == 'health':
            return self._send(200, {'ok': True, 'login': login})
        if a == 'state':
            return self._send(200, {'ok': True, 'state': load_json(STATE_FILE, {})})
        if a == 'vapid':
            try:
                return self._send(200, {'ok': True, 'public_key': vapid_keys()['public_key']})
            except ImportError as e:
                return self._send(200, {'ok': False, 'error': 'push library missing on the Mac mini (%s, %s %s)' % (e, sys.executable, sys.version.split()[0])})
        if a == 'overrides':
            return self._send(200, {'ok': True, 'overrides': load_json(CTX_FILE, {'sender': {}, 'domain': {}, 'item': {}})})
        if a == 'tasks':
            return self._send(200, {'ok': True, 'tasks': load_json(TASKS_FILE, [])})
        if a == 'reminders':
            return self._send(200, {'ok': True, **REM.status()})
        if a == 'calendar':                               # the Calendar page (Agenda / Week) – read only, via Macuse
            from urllib.parse import parse_qs, urlparse
            import calendar_view
            q = parse_qs(urlparse(self.path).query)
            d0, d1 = calendar_view.default_range()
            try:
                res = calendar_view.events(RUNNER.mcp_file(), config().get('calendars') or [],
                                           q.get('from', [d0])[0], q.get('to', [d1])[0], fresh=q.get('fresh', ['0'])[0] == '1')
            except calendar_view.CalendarError as e:
                return self._send(400, {'ok': False, 'error': str(e)})
            except Exception as e:                        # Macuse missing / not answering
                return self._send(500, {'ok': False, 'error': 'Calendar could not be read: %s' % str(e)[:160]})
            return self._send(200, {'ok': True, **res})
        if a == 'activity':                               # account menu → Activity log: titles only, never content
            from urllib.parse import parse_qs, urlparse
            import activity
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            return self._send(200, {'ok': True, **activity.entries(LOG_FILE, RUNNER._load_runs()['runs'], q), 'owner': login in owner_logins()})
        if a == 'oauth_callback':                         # the sign-in coming back from Teams / Meet / Zoom
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            g = lambda k: (q.get(k) or [''])[0][:4000]
            if login not in owner_logins():
                return self._send_text(403, 'Only the owner can connect meeting services.')
            try:
                prov = OAUTH.callback(g('state'), g('code'), g('error') or None, g('error_description') or None)
                _who_connected(prov)
                log(login, 'meeting_service_connected', {'title': _oauth.PROVIDERS[prov]['label']}, 'ok')
                where = '../?v=settings&s=calendar&connected=' + prov
            except _oauth.Bad as e:
                log(login, 'meeting_service_connected', {'title': 'Meeting service'}, 'rejected: ' + str(e)[:100])
                from urllib.parse import quote
                where = '../?v=settings&s=calendar&connect_error=' + quote(str(e)[:200])
            self.send_response(302)
            self.send_header('Location', where)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if a in ('meeting_services', 'cal_invite_for'):
            if login not in owner_logins():
                return self._send(403, {'ok': False, 'error': 'Only the owner can see this'})
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                if a == 'meeting_services':
                    return self._send(200, {'ok': True, 'calendars': ONLINE.calendars(), 'icloud': INVITES.caldav.configured(),
                                            'services': [dict(OAUTH.status(k), key=k, revoke_page=v['revoke_page'],
                                                              capabilities=MSERV.provider(k).capabilities())
                                                         for k, v in _oauth.PROVIDERS.items()],
                                            'defaults': MSERV.load()['defaults']})
                ev = {k: (q.get(k) or [''])[0][:500] for k in ('calendar', 'title', 'start', 'url')}
                return self._send(200, {'ok': True, 'invite': ONLINE.for_event(ev)})
            except (_oauth.Bad, Bad) as e:
                return self._send(200, {'ok': False, 'error': str(e)})
        if a == 'calendar_caps':                          # may the Calendar page offer editing, and in which calendars
            import calendar_view
            try:
                c = calendar_view.caps(RUNNER.mcp_file(), os.path.join(STATE_DIR, 'macuse-calendar-tools.json'))
            except Exception as e:
                c = {'can_edit': False, 'problems': [str(e)[:160]], 'calendars': []}
            kinds = {str(x.get('name')): x for x in config().get('calendars') or [] if isinstance(x, dict)}
            for x in c.get('calendars') or []:
                k = kinds.get(x.get('title')) or {}
                x['label'], x['ctx'] = k.get('label') or x.get('title'), k.get('kind') if k.get('kind') in ('work', 'private') else None
            return self._send(200, {'ok': True, **c, 'owner': login in owner_logins()})
        if a == 'trip_today':                             # the Today card on travel days: the owner's own
            if login not in owner_logins():
                return self._send(403, {'ok': False, 'error': 'Trips are the owner\'s own'})
            return self._send(200, {'ok': True, 'card': TRIPS.today()})
        if a == 'trips':                                  # suggested and confirmed trips: the owner's own
            if login not in owner_logins():
                return self._send(403, {'ok': False, 'error': 'Trips are the owner\'s own'})
            v = TRIPS.view()
            kinds = {n: (a.get('kind') if isinstance(a, dict) else None) for n, a in (config().get('accounts') or {}).items()}
            for t in v['trips'] + v['past'] + v['suggested']:
                # work or private: what you set, else the accounts its mails came in (all work → work, all private → private)
                ks = {kinds.get((b.get('source') or {}).get('account')) for b in t['bookings']} - {None}
                t['ctx_auto'] = next(iter(ks)) if len(ks) == 1 and next(iter(ks)) in ('work', 'private') else None
            for t in v['trips'] + v['past']:
                t['checklist'] = TRIP_CHECKS.of(t['id'])       # from trip-checklists.json (never in trips.json)
            return self._send(200, {'ok': True, **v})
        if a in ('meetings', 'meeting', 'meeting_context', 'meeting_file', 'meeting_text', 'meeting_caps'):   # meeting prep: the owner's own, reads too
            from urllib.parse import parse_qs, urlparse, quote
            import meetings
            if login not in owner_logins():
                return self._send(403, {'ok': False, 'error': 'Meeting preps are the owner\'s own'})
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            try:
                if a == 'meetings':
                    return self._send(200, {'ok': True, 'preps': MEET.overview()})
                if a == 'meeting':
                    m = MEET.get(q.get('id'))
                    prot, mode, source, wps = meeting_ai(m, with_source=True)
                    names = {w['id']: w['name'] for w in profile.workplaces()}
                    return self._send(200, {'ok': True, 'prep': m, 'agenda': meetings.agenda_text(m), 'protected': prot, 'ai': mode,
                                            'ai_source': source, 'workplaces': [names.get(w, w) for w in wps]})
                if a == 'meeting_context':
                    return self._send(200, {'ok': True, **meeting_context(q.get('id'))})
                if a == 'meeting_caps':                   # transcription (whisper.cpp) and the workplace defaults
                    ds = MEET.ai_defaults()
                    return self._send(200, {'ok': True, **transcriber().status(), 'workplaces': [
                        {'id': w['id'], 'name': w['name'], 'ai': ds.get(w['id'])} for w in profile.workplaces() if w['protected']]})
                if a == 'meeting_text':                   # a transcript's text, to read on the prep
                    m = MEET.get(q.get('id'))
                    x = next((y for y in m.get('materials') or [] if y.get('id') == q.get('a') and y.get('kind') == 'transcript'), None)
                    if not x:
                        raise meetings.Bad('not found')
                    return self._send(200, {'ok': True, 'text': MEET.material_text(m['id'], x['id'], meetings.MAX_TRANSCRIPT),
                                            'labels': meetings.speakers_of(MEET._raw_text(m['id'], x['id'])),   # for Rename speakers
                                            'protected': meeting_protected(m)})
                x, data = MEET.read_file(q.get('id'), q.get('a'))
            except (meetings.Bad, Bad) as e:
                return self._send(404, {'ok': False, 'error': str(e)})
            except OSError:
                return self._send(404, {'ok': False, 'error': 'not found'})
            self.send_response(200)
            self.send_header('Content-Type', x.get('type') or 'application/octet-stream')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Disposition', "inline; filename*=UTF-8''" + quote(x['name']))
            self.send_header('Cache-Control', 'private, no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)
            return
        if a == 'commitments':                            # promises to confirm, "looks done", and who you owe a reply
            from urllib.parse import parse_qs, urlparse
            if parse_qs(urlparse(self.path).query).get('fresh', ['0'])[0] == '1' or not _COMMIT['at']:
                try:
                    scan_commitments()
                except Exception as e:
                    _COMMIT['error'] = str(e)[:200]
            return self._send(200, {'ok': True, **commitments_view()})
        if a == 'scheduled':                              # Send later: what waits, and what went lately (no mail text)
            return self._send(200, {'ok': True, 'scheduled': SCHED_SEND.list()})
        if a == 'scheduled_text':
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                return self._send(200, {'ok': True, **SCHED_SEND.text(q.get('id', [''])[0])})
            except _scheduled_mod.Bad as e:
                return self._send(404, {'ok': False, 'error': str(e)})
        if a == 'invites_pending':                        # invitations in your mail still waiting for an answer
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                return self._send(200, {'ok': True, **pending_invites(fresh=q.get('fresh', ['0'])[0] == '1')})
            except Exception as e:
                return self._send(200, {'ok': True, 'invites': [], 'error': str(e)[:160]})
        if a == 'invite':                                 # the invitation in one mail (Accept / Maybe / Decline sheet)
            from urllib.parse import parse_qs, urlparse
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            try:
                return self._send(200, {'ok': True, 'invite': invite_view(q.get('account', ''), q.get('message_id', ''))})
            except Bad as e:
                return self._send(400, {'ok': False, 'error': str(e)})
            except Exception as e:
                return self._send(500, {'ok': False, 'error': 'the invite could not be read: %s' % str(e)[:160]})
        if a == 'contacts':                               # the Contacts page: names, numbers, addresses – never sent anywhere
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self._send(200, {'ok': True, **contacts_overview(refresh=q.get('refresh', ['0'])[0] == '1'), 'owner': login in owner_logins()})
        if a == 'vips':
            vl, lists = vips_list(full=True)
            return self._send(200, {'ok': True, 'vips': vl, 'lists': lists})
        if a == 'drafts':
            return self._send(200, {'ok': True, 'drafts': load_json(DRAFTS_FILE, {})})
        if a == 'cleanup':
            return self._send(200, {'ok': True, **CLEAN.status()})
        if a == 'kb_harvest':
            return self._send(200, {'ok': True, **HARVEST.status()})
        if a in ('knowledge', 'knowledge_search'):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            proj = q.get('project', [''])[0][:100] or None
            if a == 'knowledge':
                return self._send(200, {'ok': True, **KB.status(proj)})
            return self._send(200, {'ok': True, **KB.search(q.get('q', [''])[0][:300], proj)})
        if a == 'projects':
            return self._send(200, {'ok': True, 'projects': PROJ.load()['projects']})
        if a in ('project_mail', 'project_links_for_trip'):
            if login not in owner_logins():
                return self._send(403, {'ok': False, 'error': 'Only the owner can see this'})
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                if a == 'project_mail':
                    return self._send(200, {'ok': True, **project_mail_view(q.get('id', [''])[0][:100])})
                tid = q.get('trip', [''])[0][:100]
                ps = {x['id']: x for x in PROJ.load()['projects']}
                return self._send(200, {'ok': True, 'projects': [{'id': pid, 'name': ps[pid].get('name')} for pid, e in PSCAN.load()['projects'].items()
                                                                  if tid in (e.get('trips') or []) and pid in ps]})
            except Bad as e:
                return self._send(200, {'ok': False, 'error': str(e)})
        if a == 'bills':
            return self._send(200, {'ok': True, **bills_view()})
        if a == 'sprint':                                 # Reply sprint: the quick replies that are ready
            if login not in owner_logins():
                return self._send(403, {'ok': False, 'error': 'Only the owner can see this'})
            return self._send(200, {'ok': True, **sprint_view()})
        if a == 'backup':
            if login not in owner_logins():
                return self._send(403, {'ok': False, 'error': 'Only the owner can see this'})
            return self._send(200, {'ok': True, **backup_view()})
        if a in ('notes', 'note', 'note_chips'):             # Notes: owner only, like meeting preps
            if login not in owner_logins():
                return self._send(403, {'ok': False, 'error': 'Only the owner can see notes'})
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                if a == 'note':
                    return self._send(200, {'ok': True, 'note': NOTES.view(q.get('id', [''])[0][:20])})
                if a == 'note_chips':
                    return self._send(200, {'ok': True, **note_chips(q.get('digest', [''])[0][:120] or None)})
                kind = q.get('kind', [''])[0] or None
                return self._send(200, {'ok': True, 'notes': NOTES.list(q.get('q', [''])[0][:200], kind if kind in _notes.KINDS else None,
                                                                        q.get('ref', [None])[0])})
            except (_notes.Bad, Bad) as e:
                return self._send(400, {'ok': False, 'error': str(e)})
        if a == 'later':                                  # what you pushed to Later (Today, the bottom line)
            return self._send(200, {'ok': True, **later_view()})
        if a == 'learn':                                  # Teach Axella: Settings → Rules, and the one suggestion card
            if login not in owner_logins():
                return self._send(403, {'ok': False, 'error': 'Only the owner can see this'})
            return self._send(200, {'ok': True, **learn_view()})
        if a == 'calm_setup':                             # Settings → Notifications → Calm setup (steps 1 and 3; 2 is per device)
            return self._send(200, {'ok': True, **CALM_SETUP.view()})
        if a == 'backup_download':                       # Export backup: the one file, once, then it's gone
            if login not in owner_logins():
                return self._send(403, {'ok': False, 'error': 'Only the owner can download a backup'})
            from urllib.parse import parse_qs, urlparse
            eid = parse_qs(urlparse(self.path).query).get('id', [''])[0]
            fp, mp = os.path.join(EXPORT_DIR, eid + _backup.SUFFIX), os.path.join(EXPORT_DIR, eid + '.json')
            if not EXPORT_ID.match(eid) or not os.path.isfile(fp):
                return self._send(404, {'ok': False, 'error': 'That backup is gone – export it again'})
            name = load_json(mp, {}).get('name') or 'axella-backup' + _backup.SUFFIX
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(os.path.getsize(fp)))
            self.send_header('Content-Disposition', 'attachment; filename="%s"' % re.sub(r'[^\w.-]', '', name))
            self.send_header('Cache-Control', 'private, no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            with open(fp, 'rb') as f:
                _shutil.copyfileobj(f, self.wfile)
            for x in (fp, mp):
                try:
                    os.remove(x)
                except OSError:
                    pass
            return
        if a == 'blocks':
            if login not in owner_logins():
                return self._send(403, {'ok': False, 'error': 'Only the owner can see this'})
            return self._send(200, {'ok': True, **blocks_view()})
        if a == 'renewals':
            if login not in owner_logins():
                return self._send(403, {'ok': False, 'error': 'Only the owner can see this'})
            return self._send(200, {'ok': True, **renewals_view()})
        if a == 'recurring':
            return self._send(200, {'ok': True, **RECUR.view()})
        if a == 'documents':
            d = DOCS.load()
            docs = list(d['documents'].values())
            for doc in docs:
                doc['suggest_to'] = FWD.suggestion(d, doc)
            return self._send(200, {'ok': True, 'documents': docs, 'vendor_rules': d['vendor_rules'],
                                    'recipients': FWD.load()['recipients']})
        if a == 'senders':
            d = SUBS.load()
            senders = [{k: v for k, v in s.items() if k != 'ids'} for s in d['senders'].values()]
            return self._send(200, {'ok': True, 'senders': senders, 'last_scan': d.get('last_scan'), 'days': d.get('scanned_days'),
                                    'quiet': SUBS.quiet(_protected_domain), 'safe': SAFETY.load()['safe'],
                                    'status': load_json(os.path.join(STATE_DIR, 'senders-status.json'), None)})
        if a == 'folders':
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            want, fresh = q.get('account', [None])[0], q.get('fresh', ['0'])[0] == '1'
            accs = [want] if want in config().get('accounts', {}) else list(config().get('accounts', {}))
            return self._send(200, {'ok': True, 'folders': {k: live_folders(k, fresh) for k in accs}})
        if a == 'send_status':                            # the outbox asks before it sends a waiting reply by itself
            from urllib.parse import parse_qs, urlparse
            try:
                st = send_id_status(parse_qs(urlparse(self.path).query).get('send_id', [''])[0])
            except Bad as e:
                return self._send(400, {'ok': False, 'error': str(e)})
            return self._send(200, {'ok': True, 'known': st is not None, **(st or {})})
        if a == 'job':
            from urllib.parse import parse_qs, urlparse
            j = JOBS.get(parse_qs(urlparse(self.path).query).get('id', [''])[0])
            if not j:
                return self._send(404, {'ok': False, 'error': 'unknown job'})
            return self._send(200, {'ok': True, 'job': {k: v for k, v in j.items() if not k.startswith('_')}})
        if a == 'runs':
            off = os.path.join(STATE_DIR, 'peer-check.off')
            return self._send(200, {'ok': True, **RUNNER.overview(),
                                    'peer_check_off': os.path.exists(off) and time.time() - os.path.getmtime(off) < 86400})
        if a in ('compose', 'ask'):
            from urllib.parse import parse_qs, urlparse
            try:
                st = RUNNER.compose_status(parse_qs(urlparse(self.path).query).get('id', [''])[0], a)
                if a == 'ask' and st.get('state') == 'done':
                    st['result'] = SAFETY.filter_ask(st.get('result'))
                return self._send(200, {'ok': True, **st})
            except RunnerBad as e:
                return self._send(400, {'ok': False, 'error': str(e)})
        if a == 'spoken':
            # plain text for the Siri shortcut "Axella digest": the spoken digest, then today's briefs
            text, _ = spoken_digest()
            briefs = [g for g in listen_segments() if g['kind'] == 'brief']
            if briefs:
                text += '\n' + '\n'.join(g['text'] for g in briefs)
            try:
                _calm.mark_read(STATE_DIR, _newest_digest(), 'listened')
            except Exception:
                pass
            return self._send_text(200, text)
        if a == 'listen':
            return self._send(200, {'ok': True, 'audio': audio.available(), 'segments': listen_segments()})
        if a == 'audio':                                  # one Listen segment as sound (m4a), with byte ranges for iOS
            from urllib.parse import parse_qs, urlparse
            sid = parse_qs(urlparse(self.path).query).get('seg', [''])[0]
            seg = next((g for g in listen_segments() if g['id'] == sid), None)
            if not seg:
                return self._send(404, {'ok': False, 'error': 'not in the Listen queue any more'})
            try:
                path = audio.render(STATE_DIR, seg['text'], seg.get('lang'))
            except audio.AudioError as e:
                return self._send(503, {'ok': False, 'error': str(e)})
            if seg.get('kind') == 'digest':
                try:
                    _calm.mark_read(STATE_DIR, _newest_digest(), 'listened')
                except Exception:
                    pass
            return self._send_file_range(path, 'audio/mp4')
        if a == 'profile':
            return self._send(200, {'ok': True, **profile.public(config())})
        if a == 'ooo':
            return self._send(200, {'ok': True, **OOO.status()})
        if a == 'store':
            return self._send(200, {'ok': True, **STORE.status()})
        if a in ('person', 'keep_in_touch'):           # the People page: owner only, never sent anywhere
            from urllib.parse import parse_qs, urlparse
            if login not in owner_logins():
                return self._send(403, {'ok': False, 'error': 'only the owner'})
            if a == 'keep_in_touch':
                return self._send(200, {'ok': True, **keep_view()})
            try:
                return self._send(200, {'ok': True, **person_view(parse_qs(urlparse(self.path).query).get('id', [''])[0])})
            except Bad as e:
                return self._send(404, {'ok': False, 'error': str(e)})
        if a == 'calm':
            from urllib.parse import parse_qs, urlparse
            month = parse_qs(urlparse(self.path).query).get('month', [''])[0] or None
            if month and not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', month):
                return self._send(400, {'ok': False, 'error': 'bad month'})
            hours = config().get('work_hours') if isinstance(config().get('work_hours'), dict) else None
            return self._send(200, {'ok': True, **_calm.calm(STORE, STATE_DIR, month, hours)})
        if a == 'insights':
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            per = q.get('period', ['week'])[0]
            if per not in ('week', 'lastweek', 'month', 'lastmonth', 'quarter', 'year'):
                return self._send(400, {'ok': False, 'error': 'bad period'})
            try:
                lim = int(q.get('limit', ['10'])[0])
            except ValueError:
                lim = 10
            ctx = q.get('ctx', ['all'])[0]
            if ctx not in ('all', 'work', 'private'):
                return self._send(400, {'ok': False, 'error': 'bad ctx'})
            return self._send(200, {'ok': True, **STORE.insights(per, lim, q.get('people', ['1'])[0] != '0', ctx)})
        if a == 'search':
            from urllib.parse import parse_qs, urlparse
            hits = STORE.search(parse_qs(urlparse(self.path).query).get('q', [''])[0])
            for h in hits:
                f = SAFETY.flag_of(h) if isinstance(h, dict) else None
                if f:
                    h['safety'] = f
            return self._send(200, {'ok': True, 'items': hits})
        if a == 'compose_contacts':
            return self._send(200, {'ok': True, 'contacts': compose_contacts()})
        if a == 'system_status':
            return self._send(200, {'ok': True, **system_status()})
        if a == 'outbound':
            return self._send(200, {'ok': True, **outbound()})
        if a == 'reply_info':
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                return self._send(200, {'ok': True, **reply_info(q.get('account', [''])[0], q.get('id', [''])[0][:500])})
            except Bad as e:
                return self._send(400, {'ok': False, 'error': str(e)})
            except Exception as e:
                return self._send(500, {'ok': False, 'error': str(e)[:200]})
        if a == 'run_log':
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                return self._send(200, {'ok': True, **RUNNER.read_log(q.get('id', [''])[0], q.get('offset', ['0'])[0])})
            except (RunnerBad, ValueError) as e:
                return self._send(400, {'ok': False, 'error': str(e)})
        if a == 'schedule':
            try:
                nxt = RUNNER.next_digest()                # the line at the top of Today: "next digest 15:30, in 4 h"
            except Exception as e:
                sys.stderr.write('%s next digest: %s\n' % (now_iso(), str(e)[:200]))
                nxt = None
            return self._send(200, {'ok': True, 'schedule': SCHED.load(), 'status': SCHED.status(),
                                    'sweep': SCHED.sweep(), 'wait': SCHED.wait_text(general=True), 'next': nxt})
        if a == 'attachment':
            from urllib.parse import parse_qs, urlparse, quote
            q = parse_qs(urlparse(self.path).query)
            try:
                if q.get('file'):
                    try:
                        name, ctype, data = mailsearch.attachment(q['file'][0], q.get('n', ['1'])[0])
                    except mailsearch.NotDownloaded as nd:
                        name, ctype, data = attachment_file(nd.account, nd.mid, q.get('n', ['1'])[0])
                else:
                    try:
                        addrs = mailsearch.addresses_of(mailsearch.path_for_mid(q.get('id', [''])[0]))
                    except Exception:
                        addrs = []
                    if mail_privacy(addrs)[0]:
                        raise Bad('this mail involves a private contact – open it in Mail')
                    acc0, mid0 = q.get('account', [''])[0], q.get('id', [''])[0][:500]
                    try:                                   # Mail's own file first (instant); else ask Mail for it
                        rp0 = mailsearch.path_for_mid(mid0) if acc0 in config().get('accounts', {}) else None
                        if not rp0:
                            raise mailsearch.NotDownloaded(acc0, mid0)
                        name, ctype, data = mailsearch.attachment(mailsearch._token({'path': rp0, 'account': acc0, 'mid': mid0}), q.get('n', ['1'])[0])
                    except mailsearch.NotDownloaded:
                        name, ctype, data = attachment_file(acc0, mid0, q.get('n', ['1'])[0])
            except Exception as e:
                if 'text/html' in (self.headers.get('Accept') or ''):    # opened as a page (a tap on the chip)
                    return self._page(404, "Couldn't open the attachment", _attachment_reason(e))
                return self._send(404, {'ok': False, 'error': str(e)[:300]})
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            disp = 'inline' if ctype in ('application/pdf', 'text/plain') or ctype.startswith('image/') else 'attachment'
            self.send_header('Content-Disposition', disp + "; filename*=UTF-8''" + quote(name))
            self.send_header('Cache-Control', 'private, no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)
            return
        if a == 'img':                                    # picture proxy for "Load pictures" (signed links only)
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                ctype, data = mailsearch.fetch_image(q.get('u', [''])[0], q.get('k', [''])[0])
            except mailsearch.SearchError as e:
                return self._send(404, {'ok': False, 'error': str(e)})
            try:
                tally('pictures')                         # each fetch is a request from your home connection
            except Exception:
                pass
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'private, max-age=86400')
            self.send_header('Content-Security-Policy', "default-src 'none'; sandbox")
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)
            return
        if a == 'reports_zip':                            # Download for Claude: report.md + pictures per report
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                ids = [x for x in q.get('ids', [''])[0].split(',') if x] or None
                community = None
                if q.get('community', ['0'])[0] == '1':
                    community = REPORTS.triage('GET', '').get('reports') or []
                    for c in community:
                        res = REPORTS.triage('GET', '/' + re.sub(r'[^\w-]', '', str(c.get('id'))) + '/render')
                        c['_png'] = res.get('png')
                data = REPORTS.zip(ids, community)
            except (reports_mod.Bad, OSError) as e:
                return self._send(400, {'ok': False, 'error': str(e)[:200]})
            name = 'axella-reports-%s.zip' % datetime.datetime.now().strftime('%Y%m%d-%H%M')
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Disposition', 'attachment; filename="%s"' % name)
            self.send_header('Cache-Control', 'private, no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)
            return
        if a in ('reports', 'report', 'report_context', 'report_img', 'triage_list', 'triage_render'):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                if a == 'reports':
                    return self._send(200, {'ok': True, 'reports': REPORTS.list(), **REPORTS.settings()})
                if a == 'report':
                    r = REPORTS.get(q.get('id', [''])[0])
                    return self._send(200, {'ok': True, 'report': r})
                if a == 'report_context':                  # what the Mac mini adds to a report (allow-listed values only)
                    return self._send(200, {'ok': True, 'meta': REPORTS.context(config().get('accounts'), report_connectors()),
                                            'errors': REPORTS.server_errors(LOG_FILE), **REPORTS.settings()})
                if a == 'report_img':
                    data = REPORTS.image(q.get('id', [''])[0], q.get('kind', ['render'])[0])
                elif a == 'triage_list':
                    return self._send(200, REPORTS.triage('GET', ''))
                else:                                      # triage_render: a community report's privacy render
                    res = REPORTS.triage('GET', '/' + re.sub(r'[^\w-]', '', q.get('id', [''])[0]) + '/render')
                    if not res.get('png'):
                        return self._send(404, {'ok': False, 'error': res.get('error') or 'no render'})
                    data = res['png']
            except (reports_mod.Bad, OSError) as e:
                return self._send(404, {'ok': False, 'error': str(e)[:200]})
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'private, no-store')
            self.send_header('Content-Security-Policy', "default-src 'none'; sandbox")
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)
            return
        if a == 'privacy':
            import signal_export
            return self._send(200, {'ok': True, **PRIV.public(), 'signal': signal_export.status()})
        if a == 'private_inbox':                          # the Private card: who wrote, where, how many – never text
            d = load_json(os.path.join(STATE_DIR, 'private-inbox.json'), {})
            rows = [r for ch in d.values() if isinstance(ch, dict) for r in ch.get('chats') or []]
            rows.sort(key=lambda r: r.get('last_at') or '', reverse=True)
            return self._send(200, {'ok': True, 'discreet': PRIV.load()['discreet'], 'chats': rows})
        if a == 'briefings':
            return self._send(200, {'ok': True, **BRIEF.overview()})
        if a == 'briefs':                                 # older briefs of one briefing, or the newest across all since a time
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                if q.get('id'):
                    return self._send(200, {'ok': True, 'briefs': BRIEF.briefs(q['id'][0])})
                return self._send(200, {'ok': True, 'briefs': BRIEF.recent(q.get('since', [None])[0])})
            except BriefingsBad as e:
                return self._send(400, {'ok': False, 'error': str(e)})
        if a == 'mail_search':
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query)
            try:
                lim = max(10, min(200, int(qs.get('limit', ['40'])[0])))
            except ValueError:
                lim = 40
            return self._send(200, {'ok': True, **mail_search(qs.get('q', [''])[0], lim)})
        if a == 'message':
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            pics = q.get('pics', ['0'])[0] == '1'          # "Load pictures": links via the picture proxy
            # flagged as a possible scam: the Mac mini fetches nothing from it, not even pictures
            nopics = bool(q.get('id') and SAFETY.flag_of({'message_id': q['id'][0][:500]})) or \
                bool(q.get('file') and _flagged_token(q['file'][0]))
            pics = pics and not nopics
            try:
                if q.get('file'):
                    try:
                        res = mailsearch.read(q['file'][0], pics)
                        always = pics_always(_sender_of(res.get('from'))) and not nopics
                        if always and not pics:
                            res = mailsearch.read(q['file'][0], True)
                        res['remote'] = bool(res.pop('remote_pics', False))
                        res.update(pics=pics or always, pics_always=always)
                        return self._send(200, {'ok': True, 'message': res})
                    except mailsearch.NotDownloaded as nd:      # not on disk: ask Mail for it
                        if not (nd.account and nd.mid):
                            raise
                        return self._send(200, {'ok': True, 'message': message_preview(nd.account, nd.mid)})
                # on disk (nearly always): read Mail's own file here – instant, no AppleScript search through every
                # mailbox (that could take minutes for an older mail and looked like a hang)
                acc0, mid0 = q.get('account', [''])[0], q.get('id', [''])[0][:500]
                try:
                    rp0 = mailsearch.path_for_mid(mid0) if acc0 in config().get('accounts', {}) else None
                except Exception:
                    rp0 = None
                if rp0:
                    if mail_privacy(mailsearch.addresses_of(rp0))[0]:
                        return self._send(403, {'ok': False, 'error': 'This mail involves a private contact – open it in Mail.'})
                    tok = mailsearch._token({'path': rp0, 'account': acc0, 'mid': mid0})
                    res = mailsearch.read(tok, pics)
                    always = pics_always(_sender_of(res.get('from'))) and not nopics
                    if always and not pics:
                        res = mailsearch.read(tok, True)
                    res['remote'] = bool(res.pop('remote_pics', False))
                    res.update(pics=pics or always, pics_always=always, file=tok)
                    return self._send(200, {'ok': True, 'message': res})
                res = dict(message_preview(q.get('account', [''])[0], q.get('id', [''])[0]))
                try:
                    path = mailsearch.path_for_mid(q.get('id', [''])[0])
                except Exception:
                    path = None
                addrs = re.findall(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', res.get('from') or '')
                try:
                    addrs += mailsearch.addresses_of(path)
                except Exception:
                    pass
                if mail_privacy(addrs)[0]:                 # private or hidden contact: never shown in Axella
                    return self._send(403, {'ok': False, 'error': 'This mail involves a private contact – open it in Mail.'})
                always = pics_always(_sender_of(res.get('from'))) and not nopics
                pics = pics or always
                try:                                       # the formatted version, straight from Mail's file
                    res['html'], res['remote'] = mailsearch.html_and_remote(path, pics) if path else (None, False)
                except Exception:
                    res['html'], res['remote'] = None, False
                res.update(pics=pics, pics_always=always)
                return self._send(200, {'ok': True, 'message': res})
            except mailsearch.SearchError as e:
                return self._send(404, {'ok': False, 'error': str(e)})
            except Bad as e:
                return self._send(400, {'ok': False, 'error': str(e)})
            except Exception as e:
                return self._send(500, {'ok': False, 'error': str(e)[:300]})
        if a == 'chat_media':
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                ctype, data = chat_media(q.get('id', [''])[0])
            except Bad as e:
                return self._send(404, {'ok': False, 'error': str(e)})
            except Exception as e:
                return self._send(500, {'ok': False, 'error': str(e)[:200]})
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'private, max-age=3600')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)
            return
        if a == 'chat':
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self._send(200, {'ok': True, **chat_preview(q.get('address', [''])[0], q.get('name', [''])[0],
                                                               channel='signal' if q.get('channel', [''])[0] == 'signal' else 'whatsapp')})
        if a == 'project_file':
            from urllib.parse import parse_qs, urlparse, quote
            q = parse_qs(urlparse(self.path).query)
            try:
                e, data = PROJ.read_file(q.get('p', [''])[0], q.get('f', [''])[0])
            except (ProjectBad, OSError):
                return self._send(404, {'ok': False, 'error': 'not found'})
            self.send_response(200)
            self.send_header('Content-Type', e['type'])
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Disposition', "inline; filename*=UTF-8''" + quote(e['name']))
            self.send_header('Cache-Control', 'private, no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)
            return
        return self._send(404, {'ok': False, 'error': 'not found'})

    def do_POST(self):
        login = self._login()
        if not login or self.headers.get('X-Axella') != '1':
            log(login or '-', self._action(), {}, 'rejected: not allowed (no Tailscale login or missing header)')
            return self._send(403, {'ok': False, 'error': 'not allowed'})
        if self._action() == 'outbox_upload':
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                n = int(self.headers.get('Content-Length', '0'))
                if n > 20 * 1024 * 1024:
                    raise Bad('file larger than 20 MB')
                fid = outbox_save(q.get('name', ['file'])[0], self.rfile.read(n))
                return self._send(200, {'ok': True, 'result': fid})
            except (ValueError, Bad) as e:
                return self._send(400, {'ok': False, 'error': str(e)})
        if self._action() == 'meeting_record_chunk':
            # one chunk of a recording in progress (uploaded as it is recorded, so a lost connection loses nothing); owner only
            from urllib.parse import parse_qs, urlparse
            import meetings
            q = parse_qs(urlparse(self.path).query)
            if login not in owner_logins():
                return self._send(403, {'ok': False, 'error': 'Meeting preps are the owner\'s own'})
            try:
                n = int(self.headers.get('Content-Length', '0'))
                r = MEET.record_chunk(q.get('id', [''])[0], q.get('rec', [''])[0], int(q.get('seq', ['-1'])[0]),
                                      self.headers.get('Content-Type', ''), self.rfile.read, n)
                return self._send(200, {'ok': True, 'result': r})
            except (ValueError, meetings.Bad) as e:
                return self._send(400, {'ok': False, 'error': str(e)})
        if self._action() == 'meeting_transcript_upload':
            # a recording or a transcript, streamed to disk (an hour of audio is large); owner only
            from urllib.parse import parse_qs, urlparse
            import meetings
            q = parse_qs(urlparse(self.path).query)
            if login not in owner_logins():
                log(login, 'meeting_transcript_upload', {}, 'rejected: owner only')
                return self._send(403, {'ok': False, 'error': 'Meeting preps are the owner\'s own'})
            try:
                n = int(self.headers.get('Content-Length', '0'))
                r = MEET.add_transcript(q.get('id', [''])[0], q.get('name', ['recording'])[0], self.headers.get('Content-Type', ''),
                                        self.rfile.read, n, transcriber())
                log(login, 'meeting_transcript_upload', {'item_id': q.get('id', [''])[0], 'title': q.get('name', [''])[0]}, 'ok')
                return self._send(200, {'ok': True, 'result': r})
            except (ValueError, meetings.Bad) as e:
                return self._send(400, {'ok': False, 'error': str(e)})
        if self._action() == 'meeting_upload':
            # raw file body; prep id + filename in the query string – owner only
            from urllib.parse import parse_qs, urlparse
            import meetings
            q = parse_qs(urlparse(self.path).query)
            if login not in owner_logins():
                log(login, 'meeting_upload', {}, 'rejected: owner only')
                return self._send(403, {'ok': False, 'error': 'Meeting preps are the owner\'s own'})
            try:
                n = int(self.headers.get('Content-Length', '0'))
                if n > meetings.MAX_UPLOAD:
                    raise meetings.Bad('file larger than 25 MB')
                r = MEET.upload(q.get('id', [''])[0], q.get('name', ['file'])[0], self.headers.get('Content-Type', ''), self.rfile.read(n))
                log(login, 'meeting_upload', {'item_id': q.get('id', [''])[0], 'title': q.get('name', [''])[0]}, 'ok')
                return self._send(200, {'ok': True, 'result': r})
            except (ValueError, meetings.Bad) as e:
                return self._send(400, {'ok': False, 'error': str(e)})
        if self._action() == 'project_upload':
            # raw file body (PDF, image, …); project id + filename in the query string
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                n = int(self.headers.get('Content-Length', '0'))
                if n > 25 * 1024 * 1024:
                    raise ProjectBad('file larger than 25 MB')
                fid = PROJ.upload(q.get('p', [''])[0], q.get('name', ['file'])[0], self.headers.get('Content-Type', ''), self.rfile.read(n))
                log(login, 'project_upload', {'item_id': q.get('p', [''])[0], 'title': q.get('name', [''])[0]}, 'ok')
                return self._send(200, {'ok': True, 'result': fid})
            except (ValueError, ProjectBad) as e:
                return self._send(400, {'ok': False, 'error': str(e)})
        if 'application/json' not in self.headers.get('Content-Type', ''):
            log(login, self._action(), {}, 'rejected: json only')
            return self._send(415, {'ok': False, 'error': 'json only'})
        try:
            n = int(self.headers.get('Content-Length', '0'))
            if n > (12_000_000 if self._action() == 'report_save' else 100000):   # a report carries its screen renders
                raise Bad('body too large')
            payload = json.loads(self.rfile.read(n) or b'{}')
            if not isinstance(payload, dict):
                raise Bad('bad body')
        except (ValueError, Bad) as e:
            log(login, self._action(), {}, 'rejected: ' + str(e)[:100])
            return self._send(400, {'ok': False, 'error': str(e)})
        action = self._action()
        if action in OWNER_ONLY and login not in owner_logins():
            log(login, action, {}, 'rejected: owner only')
            return self._send(403, {'ok': False, 'error': 'Only the owner can do this from here'})
        if action == 'meeting_service_connect':
            payload['_host'] = self.headers.get('Host')
        if action in ('reply_send', 'mail_send', 'invite_respond', 'cal_invite_send', 'cal_invite_update', 'cal_invite_cancel'):
            if action.startswith('cal_invite_') and not payload.get('send_id'):
                return self._send(400, {'ok': False, 'error': 'missing send_id'})
            try:
                repeat, sid = send_id_accept(action, payload, login)
            except Bad as e:
                return self._send(400, {'ok': False, 'error': str(e)})
            if repeat is not None:
                return self._send(200, {'ok': True, 'result': repeat})
        if action in SLOW_ACTIONS:
            payload['_login'] = login
            jid = queue_job(action, payload, login)
            if action in ('reply_send', 'mail_send', 'invite_respond', 'cal_invite_send', 'cal_invite_update', 'cal_invite_cancel') and payload.get('send_id'):
                send_id_update(payload['send_id'], job=jid)
            if action in ('reply_send', 'mail_send', 'invite_respond'):   # the tap itself, so a send that never finishes still shows up
                log(login, action, payload, 'queued')
            return self._send(200, {'ok': True, 'result': {'queued': True, 'job': jid, 'ahead': JOBQ.qsize() - 1}})
        try:
            payload['_login'] = login
            result = do_action(action, payload)
            log(login, action, payload, 'ok')
            return self._send(200, {'ok': True, 'result': result})
        except Bad as e:
            log(login, action, payload, 'rejected: ' + str(e))
            return self._send(400, {'ok': False, 'error': str(e)})
        except Exception as e:  # AppleScript or timeout
            log(login, action, payload, 'error: ' + str(e)[:300])
            return self._send(500, {'ok': False, 'error': str(e)[:300]})

    def _send_file_range(self, path, ctype):
        """Serve a file with HTTP byte ranges – iOS only plays (and seeks) audio served that way."""
        size = os.path.getsize(path)
        rng = self.headers.get('Range') or ''
        m = re.match(r'bytes=(\d*)-(\d*)$', rng.strip())
        start, end = 0, size - 1
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header('Content-Range', 'bytes */%d' % size)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            self.send_response(206)
            self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, size))
        else:
            self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Cache-Control', 'private, max-age=86400')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        with open(path, 'rb') as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(65536, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def _page(self, code, title, text):
        """A small page in Axella's look for links opened in their own tab (attachments) – instead of raw JSON."""
        from html import escape
        body = (PAGE_HTML % {'title': escape(title), 'text': escape(text)}).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'")
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def log_request(self, code='-', size='-'):
        # the dashboard polls every minute: successful reads aren't logged (actions are, and every error is)
        c = getattr(code, 'value', code)
        if self.command in ('GET', 'HEAD') and isinstance(c, int) and c < 400:
            return
        super().log_request(code, size)

    def log_message(self, fmt, *args):
        sys.stderr.write('%s %s\n' % (now_iso(), fmt % args))


# ---------- only Tailscale Serve may connect (security review item 2) ----------
# Both services listen on 127.0.0.1, where any program on the Mac could connect and send Tailscale's identity headers
# itself. So every new connection is checked: macOS' `netstat -anv` names the process that owns the other end, and
# only Tailscale's network extension (a root process under /Library/SystemExtensions/) is let in. Another user or a
# script can't run as root, so it can't pass. Fails closed. (Unix sockets would be cleaner, but the sandboxed
# Tailscale app can't proxy to them – tested 1 Nov 2026, HTTP 502.)
import re as _re_peer
import subprocess as _sp_peer
import threading as _th_peer
import time as _t_peer

_PEER = {'lock': _th_peer.Lock(), 'map': {}, 'at': 0.0}
_NETSTAT_RE = _re_peer.compile(r'^tcp4\s+\d+\s+\d+\s+127\.0\.0\.1\.(\d+)\s+127\.0\.0\.1\.(\d+)\s+ESTABLISHED\s+\d+\s+\d+\s+\d+\s+\d+\s+(.+?):(\d+)\s')
_TS_PATHS = ('/Library/SystemExtensions/', '/Applications/Tailscale.app/')


def _netstat_map():
    """{(client port, server port): pid} for every established 127.0.0.1 connection."""
    out = _sp_peer.run(['/usr/sbin/netstat', '-anv', '-p', 'tcp'], capture_output=True, text=True, timeout=5).stdout
    m = {}
    for line in out.splitlines():
        r = _NETSTAT_RE.match(line)
        if r:
            m[(int(r.group(1)), int(r.group(2)))] = int(r.group(4))
    return m


def _is_tailscale(pid):
    """Asked fresh for every connection (no cache): a PID can be reused after Tailscale restarts."""
    out = _sp_peer.run(['/bin/ps', '-o', 'uid=,comm=', '-p', str(pid)], capture_output=True, text=True, timeout=5).stdout.strip()
    uid, _, comm = out.partition(' ')
    return uid.strip() == '0' and 'io.tailscale.ipn' in comm and comm.strip().startswith(_TS_PATHS)


def peer_is_tailscale(client_port, server_port, state_dir=None):
    """True only if the program on the other end of this 127.0.0.1 connection is Tailscale.
    The owner lookup always comes from a netstat snapshot taken AFTER this connection was accepted – an older
    snapshot could still list a closed Tailscale connection whose source port a local program has since reused."""
    if os.environ.get('AXELLA_PEER_CHECK') == '0':            # tests on other systems only
        return True
    if state_dir:
        off = os.path.join(state_dir, 'peer-check.off')
        try:
            if _t_peer.time() - os.path.getmtime(off) < 86400:
                sys.stderr.write('peer check OFF (state/peer-check.off) – any local program can connect\n')
                return True
            sys.stderr.write('ignoring state/peer-check.off: older than 24 h\n')
        except OSError:
            pass
    key = (int(client_port), int(server_port))
    accepted = _t_peer.time()
    try:
        for attempt in range(3):
            with _PEER['lock']:
                if _PEER['at'] < accepted:                     # only a snapshot newer than this connection counts
                    _PEER['map'], _PEER['at'] = _netstat_map(), _t_peer.time()
                pid = _PEER['map'].get(key)
            if pid is not None:
                ok = _is_tailscale(pid)
                if not ok:
                    sys.stderr.write(f'refused 127.0.0.1:{client_port} → {server_port}: process {pid} is not Tailscale\n')
                return ok
            _t_peer.sleep(0.03)
            accepted = _t_peer.time()                          # next try: a fresh snapshot again
        sys.stderr.write(f'refused 127.0.0.1:{client_port} → {server_port}: owner not found\n')
    except Exception as e:
        sys.stderr.write(f'refused 127.0.0.1:{client_port} → {server_port}: peer check failed: {str(e)[:200]}\n')
    return False


class TailscaleOnlyServer(ThreadingHTTPServer):
    state_dir = None
    # A page load opens 15+ connections at once. With the default backlog of 5, and the peer check (netstat + ps)
    # run one connection after another on the accept loop, the rest were reset – Tailscale Serve answered 502, and
    # cards like Later, Meetings or Renewals stayed empty.
    request_queue_size = 64

    def verify_request(self, request, client_address):
        return True        # the peer check runs in the connection's own thread – process_request_thread below

    def process_request_thread(self, request, client_address):
        """The peer check for one connection, in its own thread: connections that arrive together share one netstat
        snapshot taken after they were accepted, instead of queueing on the accept loop. A refused connection is
        closed before a byte of it is read, as before; an error in the check refuses (fails closed)."""
        try:
            ok = peer_is_tailscale(client_address[1], self.server_address[1], self.state_dir)
        except Exception:
            ok = False
        if not ok:
            self.shutdown_request(request)
            return
        super().process_request_thread(request, client_address)


if __name__ == '__main__':
    threading.Thread(target=push_watcher, daemon=True).start()
    import digest_guard
    threading.Thread(target=digest_guard.run, daemon=True, args=(
        DIGESTS_DIR, os.path.join(STATE_DIR, 'digest-guard.json'), push_send,
        lambda: bool(load_json(PUSH_SUBS_FILE, [])) and SCHED.status()['digests'])).start()   # no alert on paused days
    import whatsapp_export
    threading.Thread(target=whatsapp_export.run, daemon=True).start()   # state/whatsapp.json every 2 min
    import signal_export
    threading.Thread(target=signal_export.run, daemon=True).start()     # state/signal.json every 2 min (signal-cli)
    import private_local
    threading.Thread(target=private_local.run, daemon=True).start()     # Private card for Mail/iMessage (no text read)
    threading.Thread(target=DOCS.run, daemon=True, kwargs={   # receipts/invoices register + folder watch
        'osa': osa, 'folders': [tuple(x) for x in config().get('document_folders', [])]}).start()
    def _auto_forward_loop():
        import time
        while True:
            try:
                FWD.auto_once(sys.stderr, audit=log_auto)
            except Exception as e:
                sys.stderr.write('auto-forward: %s\n' % str(e)[:200])
            try:
                outbox_prune()                     # attachments nobody sent: gone after a day
            except Exception:
                pass
            time.sleep(120)
    threading.Thread(target=_auto_forward_loop, daemon=True).start()

    _ask_notes_sweep(0)                            # at start nothing runs yet: no Ask copy may stay
    def _housekeeping_loop():
        """Once a day: activity log lines older than 90 days → state/actions-archive/; backups of deleted contacts and
        events older than 90 days → state/deleted/*/_expired/. Moved, never deleted."""
        import time
        import activity
        import contacts_book
        while True:
            try:
                activity.archive(LOG_FILE, os.path.join(STATE_DIR, 'actions-archive'), LOG_LOCK, datetime.date.today().isoformat())
                for sub in ('contacts', 'events'):
                    contacts_book.prune_backups(os.path.join(BACKUP_DIR, sub))
                import meetings
                meetings.prune_backups(os.path.join(BACKUP_DIR, 'meetings'))
                _ask_notes_sweep()                     # Ask copies left behind by a crashed run
            except Exception as e:
                sys.stderr.write('housekeeping: %s\n' % str(e)[:200])
            time.sleep(86400)
    threading.Thread(target=_housekeeping_loop, daemon=True).start()
    threading.Thread(target=_scheduled_loop, daemon=True).start()
    threading.Thread(target=_commit_loop, daemon=True).start()
    threading.Thread(target=_birthday_loop, daemon=True).start()
    threading.Thread(target=_bills_loop, daemon=True).start()
    threading.Thread(target=_trip_watch_loop, daemon=True).start()   # Trips v2: updates, check-in, pushes near departure
    threading.Thread(target=_recurring_loop, daemon=True).start()
    threading.Thread(target=_backup_loop, daemon=True).start()        # Backup and move: the weekly automatic copy
    threading.Thread(target=_renewals_loop, daemon=True).start()      # Renewals: renewal and expiry mails → suggestions     # Subscriptions overview (recurring.py)
    threading.Thread(target=_trip_read_loop, daemon=True).start()
    threading.Thread(target=_project_read_loop, daemon=True).start()   # Claude's project readings → suggestion cards
    threading.Thread(target=_project_scan_loop, daemon=True).start()   # Projects → Scan mail: the nightly re-scan     # Claude's trip readings → trips    # state/birthdays-today.json for the morning digest
    threading.Thread(target=SUBS.run, daemon=True, args=([tuple(x) for x in config().get('newsletter_folders', [])],)).start()
    import housekeeping
    threading.Thread(target=housekeeping.run, daemon=True, args=(DIGESTS_DIR, STATE_DIR)).start()
    from voice_sync import VoiceSync
    OOO = OutOfOffice(STATE_DIR, push_send, config=config)
    threading.Thread(target=OOO.run, daemon=True).start()          # out-of-office reminders
    REM.push = push_send
    threading.Thread(target=CLEAN.run, daemon=True).start()        # mail cleanup: weekly scan + background moves
    threading.Thread(target=REM.run, daemon=True).start()          # recurring reminders → tasks (state/reminders.json)
    VOICE = VoiceSync(BASE, STATE_DIR, config, osa, push_send, away=OOO.voice_greetings, privacy=PRIV)
    threading.Thread(target=VOICE.run, daemon=True).start()        # call agent on Vercel → calls/ + push
    threading.Thread(target=private_watcher, daemon=True).start()   # push for a new private message (who/where only)
    threading.Thread(target=job_worker, daemon=True).start()        # slow dashboard actions (Mail/Calendar)
    threading.Thread(target=RUNNER.doctor, daemon=True).start()     # state/doctor.json: claude CLI, MCP servers
    RUNNER.recover()                                                  # runs a restart interrupted (a digest runs again)
    threading.Thread(target=RUNNER.clock, daemon=True).start()      # local scheduler (state/scheduler.json)
    threading.Thread(target=RUNNER.worker, daemon=True).start()
    threading.Thread(target=STORE.run, daemon=True).start()        # state/axella.db – SQLite index of digests, calls, actions, runs
    os.umask(0o077)                                # files the service writes from now on: this user only
    TailscaleOnlyServer.state_dir = STATE_DIR
    TailscaleOnlyServer(('127.0.0.1', PORT), Handler).serve_forever()
