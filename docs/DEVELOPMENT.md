# Developing Axella

The repository layout, what lives outside it, and how to deploy and restart. For the product itself see the [README](../README.md).


A personal message assistant: Claude reads mail, WhatsApp, iMessage/SMS and LinkedIn notifications on the
Mac mini (home-server), writes prioritised digests with drafted replies, and a private dashboard lets you act on them.
**Nothing is sent without your tap** – mail replies are sent from the dashboard on a confirmed tap (reply_send/mail_send), or saved
as a draft in Mail; Messages/WhatsApp open with the draft (exception: receipts to the closed bookkeeping recipients list, and one-click unsubscribes).
The Mac mini runs the schedule itself with Claude Code on your Claude subscription. Unanswered calls go to a call agent
(Twilio + Vercel + Claude Haiku) that takes a message; the Mac mini pulls the calls into the dashboard and digests.

**How it's built:** [docs/ARCHITECTURE.md](ARCHITECTURE.md) · **Setting it up yourself:** [docs/SETUP.md](SETUP.md) ·
**Plans:** [docs/ROADMAP.md](ROADMAP.md)

## Layout

| Path | What |
|---|---|
| `AXELLA.example.md` | Example of `AXELLA.md`, the operating rules every Claude run reads (priorities, folders, digest + JSON format). Your own `AXELLA.md` is not in git |
| `setup/actions-config.example.json` | Example of `setup/actions-config.json` (mailboxes, folders, call agent, your own addresses). Your own copy is not in git |
| `setup/axella-actions.py` | Action service on 127.0.0.1:8788 – dashboard API, job queue for Mail/Calendar actions, Web Push, and the threads below |
| `setup/scheduler.py`, `setup/local-tasks/` | The schedule (Settings → Schedule) and the prompts of every Claude run; ledger + logs in Runs |
| `setup/documents.py`, `forwarding.py`, `subscriptions.py` | Receipts register, forwarding to the recipients list, newsletters |
| `setup/whatsapp_export.py`, `housekeeping.py` | WhatsApp export every 2 min, digest archiving |
| `setup/projects.py` | Projects: notes, links, documents (`state/projects.json`, `state/project-files/`); archive/restore |
| `setup/local-tasks/ask.md` | Ask Axella: the read-only chat run (answer, sources, proposed action cards) |
| `setup/cleanup.py` | Mail cleanup: old mail with no relationship → the account's "Cleanup" folder, undoable |
| `setup/kb_harvest.py` | Knowledge harvest: nightly sent-mail suggestions + mailbox scans → suggested entries |
| `setup/knowledge.py` | Knowledge base: short facts and answers drafts may use, overall or per project (`knowledge/entries/*.md`) |
| `setup/reminders.py` | Recurring reminders: repeating to-dos that add a task to To do on schedule (`state/reminders.json`) |
| `setup/ooo.py`, `setup/store.py` | Out of office (period, texts, call agent away greeting) · SQLite index for search and Insights |
| `setup/voice_sync.py` | Pulls calls from the call agent (repo `axella-voice` on Vercel) into `calls/`, sends contacts every 6 h |
| `setup/digest_guard.py` | Pushes "digest missing" if a scheduled digest is 60 min late |
| `setup/*.plist.template` | launchd agents for the web server and the action service (fill in the paths) |
| `web/` | Dashboard source – Vite + React 19 + TypeScript + Tailwind v4 + shadcn-style components, styled with the Axella design system (Horizon) |

Not in git (see `.gitignore`): your `AXELLA.md`, `contacts.md` and `setup/actions-config.json`, the knowledge base, digests, state (tasks,
handled items, push keys and subscriptions, project files, the SQLite store), call records, and build output.

## Outside this repo

This folder lives at `~/dev/own/home-server/axella/` on the Mac mini, next to the general web root `../www/`:
`www/www-server.py` (static server on 127.0.0.1:8787, launchd `local.axella.web`), `www/access.json`
(who may open which path – the action service reads it too) and `www/axella` → `../axella` (symlink). The web server
blocks `setup/`, `state/`, `web/`, `node_modules/`, hidden files and `.md`/`.json` outside `digests/` and `calls/`.

## Access

Only through Tailscale Serve: `/` → 127.0.0.1:8787, `/axella/api` → 127.0.0.1:8788. Both services bind to localhost, accept
connections only from Tailscale's own process, and require the `Tailscale-User-Login` of an allowed user (or the Mac mini itself, `node:home-server`).

## Deploy the dashboard

    cd web && npm install && npm run deploy

## Restart the action service

    launchctl kickstart -k gui/$(id -u)/local.axella.actions   # your label

Web Push needs `/usr/bin/python3 -m pip install --user pywebpush`.
