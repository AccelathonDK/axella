# How Axella is built

*Last updated 1 Nov 2026: Ask Axella (chat), monthly spend on Receipts, newsletter senders grouped by company, recurring reminders, project archive, iPhone swipes, knowledge base, inbox re-scan; the dashboard follows the Axella design system.*

Axella is a personal message assistant. It reads mail, calendar, iMessage/SMS and WhatsApp on an always-on
Mac mini ("home-server"), writes prioritised digests with drafted replies a few times a day, checks for urgent
messages every 15 minutes, and a private web app (dashboard + iPhone Home Screen app with push) lets you act on
everything with one tap. Calls you don't answer are forwarded to a call agent (Twilio + Vercel + Claude Haiku)
that takes a message in Danish or English; the Mac mini fetches each call and shows it in the dashboard and digests.

**Nothing is sent without your tap.** You write or approve a reply in the item sheet (or New mail), tap Send, confirm, and get a
6-second Undo; then the Mac mini service has Mail send it (`reply_send` in the thread / `mail_send`; payload `confirm:"send"`,
at most 20 an hour, each logged in `state/sent.json`). Claude runs never send. The other, narrow exception: receipts/invoices may be forwarded to the
closed bookkeeping recipients list, by hand or (per vendor, once switched on) automatically, and one-click
newsletter unsubscribes. Both are done by the Mac mini service, never by a Claude run.

Setting it up yourself: [SETUP.md](SETUP.md). Plans and ideas: [ROADMAP.md](ROADMAP.md).

---

## 1. The big picture

```
┌──────────────────────────────── Mac mini "home-server" (always on, UPS) ────────────────────────────────┐
│                                                                                                          │
│  axella-actions.py  (launchd, 127.0.0.1:8788) ── one Python process, many threads                        │
│  ├─ Scheduler ── clock (15 s) ─▶ queue ─▶ worker ─▶  claude -p  (Claude Code CLI, your subscription)   │
│  │                                                   ├─ prompt: setup/local-tasks/<task>.md              │
│  │                                                   ├─ MCP: Macuse (`macuse mcp`) – read-only tools     │
│  │                                                   └─ writes digests/*.md + *.json, p0-last-check.txt   │
│  ├─ Pre-check for urgent checks (Mail index, Messages db, WhatsApp export) – no Claude if nothing is new │
│  ├─ Dashboard API (actions, tasks, projects, receipts, newsletters, settings, runs + logs)               │
│  ├─ Job queue for slow actions (Mail/Calendar via AppleScript)                                          │
│  ├─ Push watcher (new digest → Web Push) · digest guard (missing digest alert)                          │
│  ├─ WhatsApp export (every 2 min) · receipts folder watch (10 min) · newsletter scan (6 h)               │
│  ├─ auto-forward loop (2 min) · housekeeping (archive digests > 30 days, prune run logs > 30 days)      │
│  ├─ recurring reminders (5 min) → tasks · out of office (5 min) · SQLite store (60 s)                   │
│  └─ Voice sync (60 s) ── outgoing HTTPS only ─▶ call agent on Vercel: fetch calls · send contacts (6 h)  │
│                                                                                                          │
│  www-server.py  (launchd, 127.0.0.1:8787) – static dashboard + digest files, per-path access list       │
│                                                                                                          │
│  Apple Mail · Calendar · Contacts · Messages · WhatsApp Desktop · Macuse.app                           │
└───────────────────────────────────────────────▲──────────────────────────────────────────────────────────┘
                                                │  Tailscale Serve – HTTPS inside the tailnet only,
                                                │  identity header on every request, no open ports
                                   iPhone (Home Screen app + push) · laptop browser

  Caller ─▶ your mobile (not answered)    ─▶ forwarded to the Twilio number ─▶ Vercel "axella-voice" (fra1)
            speech ⇄ text by Twilio ConversationRelay (ElevenLabs voice) · Claude Haiku talks · call saved in Upstash Redis
            ◀── the Mac mini's voice sync pulls finished calls every 60 s and deletes them on Vercel
```

Everything that needs your data runs on the Mac mini. There is no cloud scheduler any more and no inbound
exposure; the only network entry is Tailscale Serve inside your tailnet. The call agent is the one part that has to
be reachable from the phone network, so it lives on Vercel and never calls into the Mac mini – the Mac mini pulls.

---

## 2. Components

| Component | File(s) | What it does |
|---|---|---|
| Operating rules | `AXELLA.md`, `contacts.md` (not in git) | The contract every Claude run reads first: priorities P0–P4, contact tiers, folders, file formats, hard rules |
| Profile | `setup/axprofile.py` | Who Axella works for, from `setup/actions-config.json` (not in git): owner, mail accounts (private/work), zero or more workplaces (protected or not), calendars. The dashboard gets it from `GET profile` – nothing personal is built into the code |
| Action service | `setup/axella-actions.py` | Dashboard API + all background threads below. Restarted with `launchctl kickstart` |
| Scheduler | `setup/scheduler.py` | Slots, pause rules, sweep requests, queue, `claude -p` runner, retries, run ledger + logs, setup check |
| Local prompts | `setup/local-tasks/*.md` | One prompt per task: morning/midday/afternoon digest, week-ahead, on-demand sweep, inbox re-scan, urgent check, receipts catch-up, compose, ask (Ask Axella) |
| Pause settings | `setup/schedule.py` | Vacation mode (urgent-only / off), single days off, "Run sweep now" requests |
| Receipts register | `setup/documents.py` | Folder watch of receipt folders, completion by digests, per-vendor learning |
| Subscriptions | `setup/recurring.py`, `setup/app_stores.py` | Regular charges from Receipts, renewal/trial/price mails, and one row per item on an app store's receipt (Apple, Google Play, PayPal – store's own domain, DKIM/DMARC pass); fixed "Manage in …" links; rules only, every 6 h |
| Renewals | `setup/renewals.py` | Things that expire or renew on a date: renewal/expiry mails (EN/DA, genuine senders only) as suggestions, yearly subscriptions linked, entries by hand; lead time per kind, one digest line and a suggested To do card at the lead time, roll-over after the date, the passport/trip check; never document numbers; rules only |
| Protect your blocks | `setup/blocks.py` | Insights → Your time (meeting hours work/private this week vs last, the longest free block per workday, days without one of the minimum length – no scores, no ranks) and, on a busy workday (meetings ≥ half the work hours) with exactly one free block of the minimum length left, one suggestion in the morning digest (today, tomorrow) or Sunday's week-ahead – at most once a day, work world only; Hold it adds one busy event of your own (cal_add, nothing else changes); Not now / Don't suggest for this day; state/blocks.json; rules only |
| Reply sprint | `setup/sprint.py`, `web/src/components/Sprint.tsx` | When 3+ quick replies are ready (an Axella reply draft under 80 words on a P1/P2/Still open mail – never a private or hidden contact, a protected workplace's mail, a flagged item, a no-reply address, or one handled, snoozed or waiting in Send later): a Today card and a To do line with a time estimate; Start opens them one by one in the item sheet, owed replies first, then urgency and age. Each Send is the ordinary reply_send on its own tap (or a swipe right = both taps, same countdown and Undo); Skip, Later, Done without reply; no send-all; GET sprint, owner only; rules only |
| Back-from-away briefing | `setup/away.py`, `setup/local-tasks/return-briefing.md`, `web/src/components/Welcome.tsx` | The first digest slot after an absence of 2+ days (Away, vacation or days off; weekends bridge) runs task `return-briefing` instead, once per absence; or Catch me up since… a date (digest picker). Before the run Python writes `state/return-briefing.json` (the absence, the digests written meanwhile – none: an inbox re-scan of at most 14 days – promises, bills, preps, trips, renewals); the run writes the `away` block (headline, still needs you ≤ 10, coming up) from those digests; after it Python adds "Sorted itself out" (answered or settled, passed events, newsletters/notifications/FYIs, handled calls). Archive all marks them handled in Axella only (nothing in Mail), one Undo per batch (`state/away.json`); no push for the briefing |
| Backup and move | `setup/backup.py`, `tools/restore.sh`, `web/src/components/Backup.tsx` | One `.axbak` file: `age -e -j batchpass` (scrypt passphrase, authenticated; the passphrase on a pipe fd, never argv or env) over tar.gz with `manifest.json` (format, version, date, parts, sha256 per file) and `data/`. Core: state/ (SQLite copied consistently), knowledge/, AXELLA.md, contacts.md, setup/actions-config.json; history optional (digests/, calls/, activity log, recordings); keys and tokens never (`TOKENS`, listed to reconnect). Export → one download within an hour; weekly automatic copy to the owner's folder (passphrase in the Keychain only while on, keep 4, System status, a push after 2 weeks). Restore: everything decrypted and checked first, dry run, the current data moved aside to `pre-restore-<time>/`, paths rewritten, this Mac's own tokens kept, newer formats refused |
| System status sentence | `setup/health.py` | One plain sentence from the status rows (worst first), an analysis per problem (since when – `state/status-since.json` – what it affects, what to do), the short version with a dot in the account menu; rules only |
| Projects → Scan mail | `setup/project_scan.py` | Candidates from Mail's index by the project's Matches (subject, sender, added threads) – rules only; To sort, the Mails card, attachments to Documents, nightly re-scan of active projects, Read with Claude on picked mails (`project-read` task), links to trips |
| Invitees and online meetings | `setup/calendar_online.py`, `setup/calendar_invites.py`, `setup/meeting_providers.py`, `setup/oauth_flow.py` | New event with invitees: iCloud (CalDAV) or Exchange (Graph) sends the invitations; Teams, Meet, Zoom behind one provider interface; OAuth with PKCE, tokens in the Keychain; every send on tap |
| Forwarding | `setup/forwarding.py` | Closed recipients list, manual forward, auto-forward per vendor after 3 manual forwards, daily cap 40 |
| Newsletters | `setup/subscriptions.py` | List-Unsubscribe scan, one-click unsubscribe (RFC 8058), mailto → draft only |
| WhatsApp export | `setup/whatsapp_export.py` | Reads WhatsApp Desktop's database read-only every 2 min → `state/whatsapp.json` |
| Projects | `setup/projects.py` | Projects (= companies for receipts) with notes, links, files, ordering; archive (stops tagging, keeps everything) and restore |
| Knowledge base | `setup/knowledge.py` | Facts and answers for drafts in `knowledge/entries/*.md` (one Markdown file each): overall or per project, category, visibility (private / internal / shareable), status (suggested / active / dismissed), sources, check-again date. Digest and New mail runs Grep these files and record the ids they used (`draft.kb`) |
| Recurring reminders | `setup/reminders.py` | Repeating to-dos (every N days/weeks/months/years, task on the day or up to 60 days before, optional push). Each occurrence becomes an ordinary task (`source: "reminder"`); after downtime only the newest missed one is added |
| Out of office | `setup/ooo.py` | Away period, texts per mailbox, pushes the evening before / morning after, call agent away greeting |
| Digest guard | `setup/digest_guard.py` | Pushes "digest missing" when a scheduled digest is 60 min late (quiet on paused days) |
| Voice sync | `setup/voice_sync.py` | Every 60 s fetches finished calls from the call agent → `calls/*.json` + push; every 6 h sends greetings and Contacts as number fingerprints + first name + VIP tier; writes the Call agent card's status |
| Call agent | repo `axella-voice` (Vercel) | Twilio webhook, live conversation with Claude Haiku, call summary, contact/greeting config – see section 4 |
| Store | `setup/store.py` | SQLite index `state/axella.db`: digests + items (full-text search), calls, actions, runs – refreshed every 60 s from the files; items from protected workplaces metadata only |
| Housekeeping | `setup/housekeeping.py` | Moves digests older than 30 days to `digests/archive/YYYY-MM/` |
| Web server | `../www/www-server.py` (outside repo) | Static files with per-path access list `../www/access.json` |
| Dashboard | `web/` | Vite 6 + React 19 + TypeScript + Tailwind v4, Radix/shadcn-style components, sonner, dnd-kit. Styled with the Axella design system (tokens, Hanken Grotesk + IBM Plex Mono, archive icons in `components/ax-icons.tsx`, motion: rune-draw launch splash, approve/leave animations) |

---

## 3. The scheduler (since 30 Oct 2026)

The schedule runs inside the action service – no Claude cloud tasks.

**Slots** (`state/scheduler.json`, edited in Settings → Schedule; defaults):

| What | When | Model |
|---|---|---|
| Morning digest | 07:30 Mon–Fri | Opus |
| Midday digest | 11:30 Mon–Fri | Opus |
| Afternoon digest | 15:30 Mon–Fri | Opus |
| Sunday week-ahead | 20:30 Sun | Opus |
| Urgent check | every 15 min 07:00–22:45 Mon–Fri (not at a digest time) | Sonnet |
| On-demand sweep | "Run sweep now" – starts within 15 s, any day | Opus |
| Receipts catch-up | by hand from Runs | Opus |
| Compose mail | menu → New mail – goes first in the queue | Sonnet |
| Ask Axella | menu / top bar → Ask Axella – goes first in the queue, ~1 min | Sonnet (compose model) |

**How a slot runs**

1. *Clock* (every 15 s): finds due slots; skips them on paused days (vacation, single days off); a slot missed
   because the service was down still starts up to 20 min (digest) / 10 min (check) late.
2. *Overlap rule*: an urgent check is skipped while a digest runs or is queued – the digest covers it.
3. *Pre-check* (urgent checks at :15/:30/:45): counts new inbox mail (Mail's Envelope Index, read-only), new incoming
   iMessage/SMS (`chat.db`) and new WhatsApp messages (`state/whatsapp.json`) since `state/p0-last-check.txt`.
   Nothing new → slot "skipped: nothing new", Claude is not started. Anything unreadable → the check runs (fail-open).
   The :00 check always runs (calendar problems and P0 reminders can't be seen without Claude).
4. *Worker*: one run at a time. `claude -p <prompt> --model … --output-format stream-json --mcp-config state/mcp.json
   --strict-mcp-config --allowedTools … --disallowedTools …`, working directory = the Axella folder,
   `ANTHROPIC_API_KEY` removed so the run uses your Claude subscription. Hard timeout: digest 25 min,
   week-ahead 30, check 5, receipts 45.
5. *Pass rule*: OK only if the CLI exited cleanly, the run actually used Macuse (digests and checks), and wrote its
   output (a new digest JSON / an updated `p0-last-check.txt`). Otherwise *failed* → one retry after 3 min →
   one push when a problem starts ("failed twice"; Macuse being down is one shared alert for all tasks), quiet while
   it keeps failing, one reminder after 6 hours, one "works again" push when the task next runs OK
   (`state/run-alerts.json`).
6. *Ledger*: `state/runs.json` (status, trigger, model, tokens, summary; kept 30 days) and a readable log per run in
   `state/runs/<id>.log` (tool calls, errors, final message – sizes only for tool results, never message bodies).

**Tools a run may use** – everything else is refused by the CLI:

- Files: Read, Glob, Grep, `Bash(ls|date)`, Write/Edit only in `digests/**` (checks also `state/p0-last-check.txt`,
  receipts catch-up only `state/documents-import-catchup.json`).
- Macuse, read-only: mail search/get/thread/attachment/accounts/mailboxes, calendar list/search/free-times,
  contacts, Messages search/get, window list/read. Send, reply, compose, forward, move, delete, mark-read, calendar
  changes, clicking and typing are explicitly disallowed.

**Macuse connection**: `state/mcp.json` starts `/Applications/Macuse.app/Contents/MacOS/macuse mcp` directly (the
Claude desktop extension only wraps this command in Node). The service writes this file itself and checks the
connection at start ("Re-check setup" in Runs).

---

## 4. The call agent (since 30 Oct 2026)

Calls you don't answer are forwarded by your phone to a Twilio number. A separate repo,
[`axella-voice`](https://github.com/AccelathonDK/axella-voice) (Vercel project, region fra1, https://<project>.vercel.app), answers them.

| Part | What it does |
|---|---|
| `POST /api/voice` | Twilio's webhook. Checks Twilio's signature, looks the caller up in the contact list, picks the language (Danish for +45 numbers, English otherwise) and returns TwiML that opens a ConversationRelay session with greeting, voice and speech recognition |
| `WS /api/relay` | The live conversation. Twilio turns speech into text; Claude Haiku answers in short sentences, streamed back as speech (ElevenLabs voice "Matilda", slightly slowed). Switches Danish ⇄ English when the caller does. Asks 3–4 questions to take a message, never promises anything on your behalf, ends with a goodbye and hangs up. Max 4 min per call |
| Call summary | When the call ends, Claude writes the record: who, context, priority p0–p3 (a callback request is at least p2), summary, callback-by, SMS draft, transcript. Kept in Upstash Redis until fetched; a partial record is saved after every turn so a dropped call is not lost |
| `GET/DELETE /api/calls`, `POST /api/config` | For the Mac mini only (Bearer token `AXELLA_SYNC_TOKEN`): fetch and delete calls; receive greetings and the contact list |

Secrets (`ANTHROPIC_API_KEY` with spending limit, `TWILIO_AUTH_TOKEN`, `AXELLA_SYNC_TOKEN`, `VOICE_LOOKUP_KEY`, Redis
keys) are Vercel environment variables only; the Mac mini keeps its copies in `state/voice-token` and
`state/voice-lookup-key`. Caller ID is treated as unverified: the record keeps the matching contact and the name the
caller gave apart, and the dashboard and push say "caller ID matches" rather than presenting the caller as the contact.

**On the Mac mini** the voice sync saves each call as `calls/call-<id>.json`, pushes "📞 Axella – call: <name>" ("⚠ … caller says
urgent" for p0; no push for hang-ups, none for ordinary calls in quiet hours), and deletes it on Vercel. The dashboard's **Calls** card shows it with Reply by SMS, Book callback, Task and Done;
the **Call agent** card shows status (last check, last call, sync problems), the greetings callers hear and how many
contacts/VIPs are recognised. Digests also list unhandled calls (AXELLA.md "Calls"). Calls are kept 30 days.

---

## 5. Data flows

**Digest** – the run reads AXELLA.md, contacts.md, earlier digests and `state/actions.json` (done/snoozed), gathers
mail (every account in Mail, private and work), sent mail (waiting-for), iMessage/SMS, WhatsApp (`state/whatsapp.json`) and
calendars through Macuse, then writes `digests/YYYY-MM-DD-HHMM.md` (human) + `.json` (dashboard) +
`digests/spoken-digest.md`. The push watcher sees the new JSON and sends "Axella 07:30 · 1 urgent · 3 today".
Open items carry over between digests (`first_seen`, overdue, one-time P0 reminder).

**Urgent check** – same sources, only new items; a P0 writes `digests/…-p0.md/.json` → push "⚠ Axella – urgent".
Already-pushed IDs are kept in `state/p0-last-check.txt` so nothing is pushed twice.

**Dashboard action** – the phone POSTs to `/axella/api/<action>` (JSON + `X-Axella: 1`, Tailscale identity).
Fast actions (done, snooze, undo, tasks, projects, settings) answer at once. Slow ones that drive Mail or Calendar
(reply-in-thread draft, move to folder, trash, calendar event, forward) go to a job queue and answer immediately;
the app polls `job?id=` and shows done / "finishing in the background" / failed. Every action is one JSON line in
`state/actions.log`.

**Reply in thread** – Mail's own `reply` (keeps In-Reply-To/References) with the draft text on top and the original
quoted below, saved to Drafts – you send it from any device. WhatsApp/Messages items open the chat with the text
prefilled (`wa.me` / `sms:`).

**New mail (compose assistant)** – the form posts `compose` → request saved as `state/compose/<id>.request.json`,
a "compose" run is put first in the queue (a run already in progress finishes first) and writes
`state/compose/<id>.json` (subject + 3 variants, context, warnings); the dialog polls `compose?id=`. "Save to Drafts"
is the slow action `draft_new` (Mail outgoing message from the chosen account, saved, never sent). Files kept 14 days.

**Ask Axella (chat)** – the panel posts `ask` {question, last 6 turns, the view/project/digest/Work-Private filter you
had open} → `state/ask/<id>.request.json`, an "ask" run goes first in the queue (`setup/local-tasks/ask.md`, read-only,
aims for ~60 s) and writes `state/ask/<id>.json`: the answer (markdown light), sources (open the item, task, project,
knowledge entry or receipt), up to 3 proposed action cards and follow-up questions; the panel polls `ask?id=`. A card
runs only on your tap, step by step through the ordinary action API, and only these actions: done, snooze, file,
task_add, reminder_add, kb_add, project_item_add, or "compose" (opens New mail prefilled – you start the draft). The
dashboard refuses any other action name ("Axella can't do this from here"), so no send, trash, unsubscribe or
settings change can come from a chat answer. Files kept 14 days.

**Mail cleanup** – `setup/cleanup.py`, no Claude run. Settings → Mail cleanup picks the mailboxes and the age (12, 24 or
36 months). A scan (Sunday 03:40, or "Scan now") lists, through Mail's scripting, the Inbox, Archive and notification
folders of those mailboxes: mail older than the age, not flagged, not replied to; senders the owner wrote to (Sent, last
5 years), contacts, receipt senders, project senders, keep-listed senders and authority/bank/insurer domains are left
out, as are subjects about invoices, contracts, bookings, tickets, warranties, tax, insurance and the like, and mail tied
to a project item or a knowledge entry. The Cleanup page groups the rest by sender; a tap moves a group (or a selection)
into a "Cleanup" folder in the same account, in the background, 40 mails per AppleScript call. Every batch records each
mail's folder, so Undo moves them back. Nothing is deleted. State: `state/cleanup.json`, `state/cleanup-candidates.json`.

**Knowledge harvest** – `setup/kb_harvest.py` + `setup/local-tasks/kb-harvest.md` (read-only run, Sonnet). Every night
at 01:30 the owner's sent mail since the last good run: facts he wrote, facts he corrected in Axella's drafts
(draft vs. sent), and active entries his newer mail contradicts (flagged "may be outdated", not changed). Mailbox
scans: the owner picks a folder / sender / words / period (optionally a project); batches of 40 answered threads, at
most 4 a night between 01:00 and 06:00, progress in `state/kb-harvest.json`, "Run a batch now" from the Knowledge
page. Each run writes `state/kb/<id>.json`; the scheduler's clock merges it into SUGGESTED entries (duplicates add a
source; dismissed ones are not suggested again; work-mailbox facts become employer/internal). Nothing is used until
the owner approves it. A batch that fails 3 times pauses its scan.

**Monthly spend (Receipts)** – computed in the dashboard from `state/documents.json`: receipts, invoices and bills
count, credit notes subtract, payment reminders and order confirmations don't (they would double up). Per month (tap
for the vendors) or per vendor with a 12-month strip; the most common currency is drawn, others are listed below.

**Newsletter groups** – senders are grouped by company (the last two domain labels, three for co.uk-style), so
LinkedIn's many addresses show as one row with "N addresses"; "Unsubscribe all" runs the one-click unsubscribes one
by one and says how many need their own tap (mail/web-page ones).

**Filing** – suggestions come from the digest; you can pick any existing Mail folder (searchable picker fed by
Mail's live folder list). Choosing a different folder than suggested is remembered per sender in
`state/filing-learned.json`, which the next digests use.

**Receipts** – folder watch adds every mail in the receipt folders (also moved there by hand) as "needs details";
digests complete up to 25 per run (vendor, kind, amount, currency, due, project = company); corrections in the
Receipts view teach per-vendor rules; forwards go only to the recipients list.

**Call** – caller → Twilio → Vercel (conversation + summary) → Redis → Mac mini voice sync (≤ 60 s) → `calls/*.json`
+ push → dashboard Calls card and the next digest. Contacts flow the other way every 6 h so known callers are greeted
by name and VIPs are marked.

**Recurring reminder** – Settings → Recurring reminders (or the repeat button in To do's add row) saves a rule in
`state/reminders.json`. Every 5 minutes, and right after a change, the Mac mini adds a task to `state/tasks.json` when an
occurrence is due (or within its lead days), with the occurrence date as due date, and pushes if asked. Digests then
treat it like any task. Pausing stops new tasks; deleting the rule keeps the tasks it made.

**Knowledge** – you add entries on the Knowledge page, a project's Knowledge card, or "Save as knowledge" on a draft or
a new mail. When a run drafts a reply it searches `knowledge/entries` for the topic, sender and project, uses only active
entries whose visibility fits the recipient, copies their facts exactly (translated if needed) and lists the ids in
`draft.kb`; the dashboard shows "Based on …". Entries past their check-again date aren't used and are named in the
digest intro. Next steps (see ROADMAP): suggestions from sent mail and imports, web page snapshots, auto-reply rules.

**Handling items fast** – every item row hands its actions (Done, Tomorrow, file) to the swipe handler. On the iPhone a swipe right is Done (Filing: move to the suggested folder), left is Tomorrow
07:00 and a long left swipe files to the suggested folder; delete is never a swipe. Same actions, same log, same animations as the buttons.

**Newsletters** – a 6-hourly scan of the iCloud inbox collects senders with `List-Unsubscribe` headers; unsubscribe
is one-click POST from the Mac mini (public-IP check), a Mail draft for mailto, or opening the sender's page.

---

## 6. State on the Mac mini (not in git)

| File | Content |
|---|---|
| `digests/*.md, *.json` | Digests and urgent alerts; archived after 30 days, never deleted |
| `digests/spoken-digest.md` | Latest spoken version – menu → Listen to digest, and `api/spoken` (plain text) for the Siri shortcut |
| `state/actions.json` · `actions.log` | Done/snoozed items · every dashboard action |
| `state/scheduler.json` · `runs.json` · `runs/*.log` | Schedule settings · run ledger · run logs |
| `state/schedule.json` · `sweep-fired.json` | Vacation, days off, sweep requests |
| `state/p0-last-check.txt` | Last urgent check + pushed P0 IDs |
| `state/whatsapp.json` | WhatsApp export (48 h window) |
| `state/documents.json` · `recipients.json` | Receipts register · bookkeeping recipients |
| `state/senders.json` | Newsletter senders |
| `state/projects.json` · `project-files/` | Projects and their files |
| `state/tasks.json` · `context-overrides.json` · `filing-learned.json` | To-dos · Work/Private overrides · learned folders |
| `state/reminders.json` | Recurring reminders (rule, next occurrence, last task made) |
| `knowledge/entries/*.md` · `knowledge/.deleted/` | Knowledge base entries · deleted entries (never hard-deleted from the dashboard) |
| `state/kb-harvest.json` · `state/kb/` | Knowledge harvest: nightly "since", scans + progress · run requests/results (14 days) |
| `state/ooo.json` · `state/compose/` · `state/ask/` | Out of office · compose requests and drafts · Ask Axella questions and answers (14 days) |
| `state/push-*.json` · `vapid.json` | Push subscriptions and keys |
| `state/mcp.json` · `doctor.json` | Macuse connection for runs · last setup check |
| `state/axella.db` | SQLite index of digests/items, calls, actions, runs (rebuilt from the files if deleted) |
| `calls/call-*.json` · `calls/config.json` | Calls taken by the call agent (30 days) · Call agent card data |
| `state/voice-token` · `voice-status.json` | Sync token for the call agent (chmod 600) · last sync, last call, contacts sent |

---

## 7. Security model

- **Network**: both services bind 127.0.0.1 and accept a connection only if macOS (`netstat -anv` + `ps`) says Tailscale's
  root network extension opened it; only entry is Tailscale Serve inside the tailnet; every request needs
  the Tailscale login of an allowed user (`www/access.json`) or the Mac itself. No Funnel, no open ports.
- **Claude runs**: read-only by tool allow-list (not only by instruction); message content is treated as untrusted;
  VIP status only on an address/number that matches Contacts; message bodies from protected workplaces never leave the digest files.
- **Ask Axella**: answers come from a read-only run; its action cards are limited to a fixed allow-list in the
  dashboard (no send, trash, unsubscribe or settings) and each needs your tap.
- **Actions**: fixed list; sending only via `reply_send`/`mail_send` on your confirmed tap; no permanent delete ("Delete" = Trash). Forwarding only to the closed recipients
  list. POSTs need a custom header + JSON. User data reaches AppleScript only as arguments.
- **Data at rest**: on the Mac mini only (`chmod 600`), FileVault, Time Machine; the GitHub repo is private and never
  contains `digests/`, `state/`, `calls/` or `contacts.md`.
- **Call agent**: every Twilio request is signature-checked; the Mac mini's endpoints need the sync token; the Mac
  mini only makes outgoing requests. Callers' words are untrusted – the agent only takes messages and can't act.
  Calls leave Vercel once fetched. Spending is capped by the Anthropic key limit and the prepaid Twilio balance.
- **Mac**: stays logged in with a 1-minute screen lock; everything works while locked.

---

## 8. Operating it

| Task | How |
|---|---|
| See what runs / why something failed | Dashboard → Runs (live log, today's slots, last 100 runs, Run now, Re-check setup) |
| Change times, days, models | Dashboard → Settings → Schedule |
| Vacation / day off / sweep now | Settings → Vacation mode / Days off · account menu → Run sweep now |
| Recurring to-dos | Settings → Recurring reminders, or the repeat button when adding a task |
| Archive a project | Project page → Archive, the ⋯ on its card in Projects, or the ⋯ next to it in the sidebar (laptop); restore under Projects → Archived |
| Change behaviour | Edit `AXELLA.md` / `contacts.md`; task-specific steps in `setup/local-tasks/` |
| Update the service | Edit `setup/*.py` → `launchctl kickstart -k gui/$(id -u)/local.axella.actions` (your label) |
| Update the dashboard | `cd web && npm run deploy` |
| Call agent | Dashboard → Call agent card (status); code in `axella-voice`, deploys on `git push`; logs in Vercel → Logs; Twilio balance in the Twilio console |
| Logs | Runs view · `state/actions.log` · `~/Library/Logs/axella/actions.log` and `web.log` (folder 700, agents run with Umask 077) |

Constraints worth knowing: the Mac's Python is `/usr/bin/python3` 3.9 (no 3.10+ syntax); AppleScript reserves words
like `rd`, `before`, `after` – don't use them as variable names; Python needs Full Disk Access for the WhatsApp,
Messages and Mail-index reads.
