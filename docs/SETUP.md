# Setting up Axella in your own environment

Axella is a personal message assistant: Claude reads your mail, calendar, iMessage/SMS, WhatsApp and – optionally –
Signal (receive only, section 16) on an always-on Mac, writes prioritised digests with drafted replies a few times a day, checks for urgent messages
every 15 minutes (the Mac runs the schedule itself), and a private web app (dashboard + iPhone Home Screen app with push) lets you act on them.

**Nothing is sent without your tap.** Mail replies are written and sent from the dashboard (tap Send, confirm, 6 s to undo) or saved
as a draft in Mail; Messages/WhatsApp replies open the app with the draft. The only exceptions are forwarding receipts to your finance platform's receipt
inbox (only addresses on your own recipients list) and one-click newsletter unsubscribes – both done by the Mac's service, never by Claude. "Delete" moves mail to Trash. Calendar events are only created when you tap the button.

This guide assumes you are comfortable with Terminal, git and npm. Plan an hour.

**Minimum Mac:** a Mac with Apple silicon (M1 or later), 16 GB memory, 256 GB storage, macOS 15 or later. Choose
512 GB if your mailboxes are large (Apple Mail keeps a full local copy). 32 GB+ keeps local models an option later.

The code is open source: [github.com/AccelathonDK/axella](https://github.com/AccelathonDK/axella). Your own
configuration (`AXELLA.md`, `contacts.md`, `state/` …) never goes into it – section 11 says where it can live.

---

## 1. How it fits together

Full description: [ARCHITECTURE.md](ARCHITECTURE.md).

```
┌──────────────────────────── Mac (always on) ────────────────────────────┐
│ axella-actions.py (127.0.0.1:8788) – one service, many threads          │
│  ├─ scheduler ──▶ claude -p (Claude Code CLI, your subscription)        │
│  │                 + Macuse MCP (read-only) ──▶ Mail · Calendar ·        │
│  │                 Contacts · Messages; WhatsApp via state/whatsapp.json │
│  │                 writes digests/*.md + *.json                          │
│  ├─ dashboard API · job queue for Mail/Calendar actions · Web Push      │
│  └─ WhatsApp export · receipts · newsletters · forwarding · guard       │
│ www-server.py (127.0.0.1:8787) – static dashboard + digests             │
└──────────────▲──────────────────────────────────────────────────────────┘
               │ Tailscale Serve (HTTPS, tailnet only, identity header)
         iPhone Home Screen app (push) · laptop browser
```

| Part | Where | What it does |
|---|---|---|
| `AXELLA.md` | repo | The operating rules every Claude run reads first: priorities, folders, file formats |
| `contacts.md` | repo folder, **not in git** | Contact tiers (VIP / Known / Machines) |
| `setup/scheduler.py` + `setup/local-tasks/` | repo | The schedule and the prompts of every run (digests, urgent checks, sweep, receipts) |
| `setup/axella-actions.py` | Mac, launchd | Dashboard API, scheduler, push, WhatsApp export, receipts, newsletters, forwarding |
| `www/www-server.py` | Mac, launchd | Static web root with per-path access control (template in `setup/www-template/`) |
| `web/` | repo | Dashboard source (Vite + React + TypeScript + Tailwind, shadcn-style components) |
| Tailscale Serve | Mac | The only way in: HTTPS on your tailnet, nothing exposed to the internet |

What a run produces: every digest is a Markdown file plus a JSON data file the dashboard renders.
Example: [examples/digest.example.json](../examples/digest.example.json) (made-up data).

<!-- example: digest.example.json -->

## 2. What you need

**Minimal setup:** a Mac, Claude Code, Macuse, Apple Mail/Calendar/Contacts, Tailscale, Python and Node.js – that gives
you digests, urgent checks, the dashboard and replies by mail. Everything marked *optional* below can be added later.

- **A Mac that stays on** (a Mac mini is ideal) – see *Minimum Mac* above – logged in as your own user.
- **Claude** (Pro/Max subscription) and **Claude Code** (the `claude` command) on that Mac, signed in with your
  account – the runs use your subscription. Do **not** set `ANTHROPIC_API_KEY` for the service.
  The Claude desktop app is optional (handy for chatting with Claude about Axella).
- **[macuse](https://macuse.app)** (paid licence) – the MCP server that lets Claude read Mail, Calendar,
  Contacts, Messages and app windows. Install the app; Axella starts it as `macuse mcp` for each run.
- **Apple Mail** with your accounts added (iCloud, Gmail, Outlook.com, Microsoft 365…), **Calendar**, **Contacts**. You can keep
  Outlook or any other mail app as your daily app – see *Use Outlook or another mail app?* below.
- *Optional:* **WhatsApp Desktop** (Mac App Store version, bundle `net.whatsapp.WhatsApp`), logged in – for WhatsApp in
  the digests.
- **Tailscale** on the Mac and on your phone/laptop, same tailnet.
- **Python 3.9+** – the Command Line Tools Python (`/usr/bin/python3`) is fine. `xcode-select --install` if missing.
- **Node.js 20+** (only to build the dashboard).
- *Optional:* an **iPhone** (iOS 16.4+) for the Home Screen app and push.
- *Optional:* **Signal** – receive only, through signal-cli (section 16).
- *Optional:* the **call agent** for unanswered calls – Twilio, Vercel and an Anthropic API key (section 15).
- *Not yet:* Slack, Microsoft Teams and other chat apps aren't supported; see [connectors](connectors/README.md) for
  what is planned.


### Use Outlook or another mail app?

Axella reads mail through **Apple Mail on the Mac mini** – that is what Macuse can read. You don't have to switch:
keep Outlook (or Gmail, Spark, anything) on your laptop and phone, and add the same accounts to Apple Mail on the
Mac mini, which only Axella uses. Everything Axella does happens on the mail server, so it shows up in your own app:

- replies Axella saves for you land in the account's **Drafts** folder – open and send them from Outlook;
- filing moves the message to a server folder you see in Outlook; "Delete" uses the account's own Trash.

| Account | Add it on the Mac mini | Check |
|---|---|---|
| Outlook.com / Hotmail / Live (personal) | System Settings → Internet Accounts → add your Microsoft account | Send yourself a test mail; it should appear in Apple Mail within minutes |
| Microsoft 365 (work or school) | Internet Accounts → Microsoft Exchange – **only with your IT's OK** | Read the warning below first |
| Gmail / Google Workspace | Internet Accounts → Google | Labels show as folders |
| Other IMAP mail | Mail → Add Account → Other Mail Account | |

**Microsoft 365 – check before you rely on it.** Microsoft has been switching off Exchange Web Services (EWS) in
Exchange Online since 1 October 2026. Apple Mail on macOS uses EWS for Exchange accounts, and there are reports of
Microsoft 365 mailboxes no longer syncing in Mail on the Mac until Apple ships its update to Microsoft Graph. Add the
account, send it a test mail and make sure it arrives in Apple Mail. If it doesn't, ask your IT whether IMAP with
modern sign-in is allowed for your mailbox. Many organisations also allow only Outlook as a mail app, and some don't
want work mail on a home computer at all – ask first, and mark the workplace `"protected": true` (section 5).

**Calendars** follow the same rule: add the account's calendars to Apple Calendar on the Mac mini.

Reading Outlook or Microsoft 365 directly – without Apple Mail – isn't supported today. A Microsoft Graph connector
is on the roadmap.

---

## 3. Prepare the Mac

1. **Mail**: add all accounts. Create your folder structure (topic folders, `Archive`, `Receipts`, `Notifications`…)
   in each account. No server-side rules are needed – Axella suggests filing, you approve.
   After creating folders, quit and reopen Mail once so they sync.
2. **Calendar/Contacts**: add the accounts. Make sure the people you'll mark as VIP are in Contacts **with the
   email address / phone number they actually use** – VIP status is only granted on an address/number match.
3. **Energy**: System Settings → Energy → *Prevent automatic sleeping when the display is off* → on.
4. **Screen lock**: Axella works while the Mac is locked (mail is read from Mail's index, actions talk to Mail via
   AppleScript, WhatsApp is read from its database). A short auto-lock is fine and recommended.
   With FileVault on you must log in once after every restart before Axella works again.
5. **Don't fast-user-switch to another macOS user** for long: while another user is in front, your session runs in
   the background and Mail can become slow to answer.

### Permissions (System Settings → Privacy & Security)

| Permission | Grant to | Why |
|---|---|---|
| Full Disk Access | macuse | Mail index, Messages `chat.db` |
| Accessibility | macuse | Reading app windows (fallback only) |
| Full Disk Access | **Terminal** | Setup/testing (WhatsApp database) |
| Full Disk Access | **`/usr/bin/python3`** and **`/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app`** | The action service reads Mail's index (search, mail previews), Messages' `chat.db` (the urgent check only starts Claude when something arrived) and WhatsApp's database. Add both: macOS checks the binary that actually runs. Use **+**, then **⌘⇧G** to paste a path. |
| Automation → Mail, Calendar | Python / osascript | Asked the first time you tap an action – click **Allow** (be at the Mac or on Screen Sharing for the first action). |
| Automation → Contacts | Python | Optional, call agent only: looks up callers' names and tiers. Asked at the first sync – click **Allow**. |
| The prompts Claude Code shows on first run | Claude Code (the dialog names it `2.1.x` or similar) | Asked during the first runs (section 9): allow **Mail, Contacts and Calendar**; deny anything unrelated (e.g. Chrome, Photos). |

Find your Python with `/usr/bin/python3 -c "import sys; print(sys.executable)"` if the paths differ.

**Full Disk Access for Python is broad.** It applies to *every* script run with the system Python, not just Axella.
Use this Mac user only for Axella, and don't install other Python tools for it. (A small helper app with its own
permission, so only that app gets access, is on the roadmap.)

---

## 4. Get the code

```
mkdir -p ~/dev/own/home-server && cd ~/dev/own/home-server
git clone https://github.com/AccelathonDK/axella.git axella
mkdir -p axella/digests axella/state axella/calls
```

Layout: `axella/` is the repo; `www/` sits next to it (it's general web-root plumbing, not part of the repo):

```
cp -R axella/setup/www-template www
ln -s ../axella www/axella
```

Install the push library for the system Python:

```
/usr/bin/python3 -m pip install --user --upgrade pip
/usr/bin/python3 -m pip install --user pywebpush
/usr/bin/python3 -c "import pywebpush, cryptography; print('ok')"
```

---

## 5. Make it yours

Everything personal lives in files that are **not in git**. The repo has examples – copy them and make them yours:

```
cp AXELLA.example.md AXELLA.md
cp contacts.example.md contacts.md
cp setup/actions-config.example.json setup/actions-config.json
```
Plus `www/access.json`, copied with the web root in step 4. `.gitignore` keeps all of them out of the repo.
The examples describe a made-up owner, Alex Example, with a private iCloud account and a work account at "Acme".

### `AXELLA.md` – the rules (from `AXELLA.example.md`)
Keep every `##` section (the runs and the dashboard depend on the formats), but rewrite:
- **Hard rules**: your name, your work mailbox(es), what may never leave the digest (rule 4 is about an employer's data).
- **Mailboxes**: account names *exactly as Mail shows them*, addresses.
- **Folder structure**: your folders per account.
- **Schedule / Calendars**: your times and calendar names.
- **Work / private**: which senders/topics are work.
- Leave **Digest file format**, **Dashboard data file**, **Carry-over**, **Projects**, **Handled items**, **To-do list**,
  **Calendar suggestions** and **WhatsApp** as they are unless you also change the dashboard.

Example: [AXELLA.example.md](../AXELLA.example.md)

<!-- example: AXELLA.example.md -->

### `contacts.md` – contact tiers (from `contacts.example.md`)
Who is VIP (starts at P1, never below P2), who is a machine (P4, filed silently). Everyone in Contacts or earlier
correspondence is Known (P2). Axella never changes this list itself.

If you get mail from a public web form – for example `feedback@axella.dev`, the axella.dev feedback form – put that
address under **Machines**, never under VIP. Anyone on the internet can fill in a form, so the text (and the Reply-To)
is untrusted: as a machine it is filed at low priority, and the runs never act on its content.

Example: [contacts.example.md](../contacts.example.md)

<!-- example: contacts.example.md -->

### `setup/actions-config.json` – who you are and what the dashboard may do (from `actions-config.example.json`)
- **owner**: your name, first name and sign-off – used by drafts, the call agent and the dashboard.
- **accounts**: every Mail account *exactly as Mail names it*, with a label, `"kind": "private"` or `"work"`, the
  address, and your main folders (`"Parent/Child"` for subfolders – the folder picker also lists every other folder
  Mail has). Work accounts point at a workplace.
- **workplaces**: zero, one or several employers/clients – name, mail domains, own calendar (optional), and
  `"protected": true` if their content must stay in the digest files (no copies, spoken digest who/what only,
  metadata only in the SQLite store). **Private-only**: no work accounts and `"workplaces": []`.
- **calendars**: the calendars events may be created in, with a label and kind (and workplace for an employer's own).
- **self**: your own addresses and numbers, so Insights leaves you out.
Keep the same owner, mailboxes and workplaces in `AXELLA.md` ("Owner", "Mailboxes", "Workplaces") – the Claude runs
read that file, the service and dashboard read this one.

Example: [setup/actions-config.example.json](../setup/actions-config.example.json)

<!-- example: actions-config.example.json -->

### `www/access.json` – who may open the dashboard
Your Tailscale login (an email). Copied from `setup/www-template/access.json` in step 4 – replace the placeholder:
```json
{
  "default": ["you@example.com"],
  "paths": {
    "/axella/": ["you@example.com"]
  }
}
```
An empty or missing list lets **nobody** in. The Mac itself (`node:<hostname>`) is never allowed, even if listed: any
program on the Mac can open the tailnet URL, so a request from the Mac proves nothing about who is asking.

The prompts in `setup/local-tasks/*.md` read the owner, mailboxes and workplaces from `AXELLA.md` – no personal wording in them. Set the Web Push contact
as `"push_contact": "mailto:you@example.com"` in `setup/actions-config.json`.

---

## 6. Run the two services (launchd)

The launchd agents are templates. Pick your own labels (the examples use `local.axella.actions` and `local.axella.web`),
fill in the paths and load them. The log folder is created with mode `700`, so the logs stay private to your user:

```
cd ~/dev/own/home-server/axella/setup
mkdir -p -m 700 ~/Library/Logs/axella
sed -e "s#__AXELLA_DIR__#$HOME/dev/own/home-server/axella#" -e "s#__LOG_DIR__#$HOME/Library/Logs/axella#" \
    axella-actions.plist.template > ~/Library/LaunchAgents/local.axella.actions.plist
sed -e "s#__WWW_DIR__#$HOME/dev/own/home-server/www#" -e "s#__LOG_DIR__#$HOME/Library/Logs/axella#" \
    home-server-web.plist.template > ~/Library/LaunchAgents/local.axella.web.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.axella.web.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.axella.actions.plist
```

Restart after any change to `setup/*.py`:
```
launchctl kickstart -k gui/$(id -u)/local.axella.actions
launchctl kickstart -k gui/$(id -u)/local.axella.web
```
Logs: `~/Library/Logs/axella/actions.log`, `~/Library/Logs/axella/web.log`, and `axella/state/actions.log` (every action,
one JSON line). Logs can quote subjects and names, so they are kept out of `/tmp`, where other users on the Mac could read
them. The agents set `Umask` 077, so every file the services create is readable by you only.

Both services bind to **127.0.0.1 only**, and every connection must come from **Tailscale itself**: the service asks
macOS (`netstat -anv`, then `ps`) which program opened it, and lets in only Tailscale's network extension – a root
process under `/Library/SystemExtensions/`. Another user or a script on the Mac can't run as root, so it can't connect
and fake the Tailscale login headers. That is why the login that Serve adds to each request can be trusted. (Unix
sockets would be simpler, but the Tailscale app from tailscale.com can't proxy to them on macOS.)

---

### Keep it running when other users log in

Both services above are LaunchAgents: they live inside your login session. If you log out – or another macOS user
takes the Mac without you staying logged in – they stop and the dashboard shows a 502. Three things keep Axella up:

1. **Stay logged in.** System Settings → Users & Groups → *Automatically log in as* you (needs FileVault off; with
   FileVault on, log in once after every restart). Energy: *Prevent automatic sleeping when the display is off* and
   *Start up automatically after a power failure* on. Another user connects with Screen Sharing → **Log in as
   yourself** (their own session next to yours) or Fast User Switching – never by logging you out.
2. **The web server as a LaunchDaemon** (runs as you from boot, needs no session): the page always loads, and when
   the action service is down it says why instead of a 502.
3. **The watchdog** (`setup/watchdog.py`, also a LaunchDaemon as you): checks your session and the action service
   every minute, shows the reason on the dashboard and sends one push when Axella pauses and one when it is back.

Install both with one script (it finds your web LaunchAgent, moves it to `~/Library/LaunchAgents-disabled/` – never
deleted – and asks for your password once):

```
cd ~/dev/own/home-server/axella
setup/install-daemons.sh
```

Dashboard → account menu → **System status** then shows Web server and Watchdog as OK. After a change to `www-server.py` or `watchdog.py`, the script prints the `sudo launchctl kickstart` line to use. The action service stays a LaunchAgent – it drives Mail and Messages, which need your session.

---

## 7. Expose it on your tailnet (Tailscale Serve)

`TS` is the command-line tool inside the Tailscale app (App Store or standalone download). If you installed the
`tailscale` command itself, use `TS=tailscale` instead.

```
TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale
$TS serve --bg http://127.0.0.1:8787
$TS serve --bg --set-path /axella/api http://127.0.0.1:8788
$TS serve status
```
The dashboard is then at `https://<mac-name>.<tailnet>.ts.net/axella/`. The action service only looks at the last
path segment (`…/api/state`, `…/api/file`), so it works whether or not Serve strips the `/axella/api` prefix.
Never use `tailscale funnel` – Axella must not be reachable from the internet.

Check: from a device on the tailnet, `https://<mac>.<tailnet>.ts.net/axella/` loads; from anywhere else it doesn't.

---

## 8. Build and deploy the dashboard

```
cd ~/dev/own/home-server/axella/web
npm install
npm run deploy
```
`npm run deploy` builds the dashboard (TypeScript, Vite), then copies `index.html`, `assets/`, `icons/`, `sw.js` and the
manifest into `axella/`. Build output is git-ignored; re-run `npm run deploy` after pulling changes.


---

## 9. Claude: sign in and switch on the schedule

The Mac runs the schedule itself (`setup/scheduler.py` inside the action service). No Claude cloud tasks are needed.

1. Install Claude Code and sign in **with your subscription** in Terminal: run `claude`, complete the login, choose
   "trust this folder" for the axella folder, then `/exit`. Check `echo $ANTHROPIC_API_KEY` is empty.
2. Restart the action service. At start it checks the Mac and writes `state/doctor.json` (claude found, version,
   API key not set) and `state/mcp.json` (Macuse started as `/Applications/Macuse.app/Contents/MacOS/macuse mcp`).
3. Dashboard → **Runs**: no red "Setup not complete" box; tap **Re-check setup** to test the Macuse connection.
4. **Run now → Urgent check**. The log must show `MCP macuse: connected, N Macuse tools`, then Macuse calls, and end
   with `No P0.` (green "done"). macOS may ask once for permissions for `2.1.x` (Claude Code) – allow Mail,
   Contacts, Calendar; deny anything unrelated (e.g. Chrome).
5. Dashboard → **Settings → Schedule**: switch **"Mac mini runs the schedule"** on. Adjust times, days and models
   (defaults: digests 07:30/11:30/15:30 Mon–Fri on Opus, Sunday week-ahead 20:30, urgent checks every 15 min
   07:00–22:45 Mon–Fri on Sonnet).
6. Optional: an iPhone Shortcut "Axella digest" for Siri/CarPlay – Get Contents of URL
   `https://<mac>.<tailnet>.ts.net/axella/api/spoken` → Speak Text. The iPhone must be on the tailnet.

If you previously used Claude cloud scheduled tasks for Axella: switch them off **before** turning the local schedule
on – never run both.

## 10. iPhone: Home Screen app and push

1. In Safari open `https://<mac>.<tailnet>.ts.net/axella/` → Share → **Add to Home Screen**.
2. Open Axella **from the Home Screen icon**, open the ☰ menu → **Turn on notifications** → Allow.
   A test push arrives within seconds.
3. Every new digest now pushes ("Axella 15:30 · 1 overdue · 2 today"), urgent items push as "⚠ Axella – urgent",
   and a digest that's more than an hour late pushes "digest missing".

If you change the app icon, delete and re-add the Home Screen app, then turn notifications on again.

**Trips offline:** when the owner opens Trips, the phone keeps a copy of the upcoming trips, the travel-day card and
their ticket PDFs in the browser's own storage, so they work without a connection. The copy is trimmed to upcoming
trips every time Trips is opened, so a past or removed trip's tickets stay on the phone until the next time you open
Trips with a connection. Other logins never get the copy. To clear it at once: Settings → Safari → Advanced → Website
Data (or remove the Home Screen app). Optional: `"dashboard_url": "https://<mac>.<tailnet>.ts.net/axella"` in
`setup/actions-config.json` puts a link back to the trip in the calendar events Trips adds.

---

## 11. Verify

- [ ] `https://<mac>…/axella/api/health` returns `{"ok": true, "login": "<you>"}` from your phone.
- [ ] `/usr/bin/python3 setup/whatsapp_export.py --print` shows `ok: True` and your recent chats; and
      `state/whatsapp.json` refreshes every 2 minutes (shows `"ok": true`) once the service runs.
- [ ] Runs → Run now → **On-demand sweep**: `digests/<date>-<time>.md` and `.json` appear, the dashboard shows them,
      and a push arrives. The run is green in Runs.
- [ ] At the next quarter-hour with nothing new, the urgent-check slot turns grey "skipped: nothing new".
- [ ] Tap **Reply in thread** on a mail item → a reply with the original quoted appears in Drafts (not sent).
- [ ] **Move to …** on a filing suggestion works – also with the Mac locked for 5 minutes.
- [ ] Remove Full Disk Access from **Terminal** (System Settings → Privacy & Security → Full Disk Access). It was only
      needed for testing; the service has its own.
- [ ] `git status` shows none of your personal files (`AXELLA.md`, `contacts.md`, `setup/actions-config.json`,
      `digests/`, `state/`, `calls/`). If you want them under version control, use a separate **private** repo,
      never a fork of the public one.

---

## 12. Day-to-day

| Task | How |
|---|---|
| Vacation, days off, run a sweep now | Dashboard → Settings / account menu (top right) → Run sweep now (starts within 15 s) |
| Repeating to-dos (rent, renewals, birthdays) | Settings → Recurring reminders, or the repeat button when adding a task |
| Keep standard answers for drafts | Knowledge (menu) or a project's Knowledge card; "Save as knowledge" on a draft |
| Back up, or move to a new Mac | Settings → System → Backup (export, or weekly to your folder); restore with `tools/restore.sh` (section 18) |
| Back after days away | The first digest after 2+ days away (Away, vacation, days off) is a "Welcome back" briefing – Archive all lets go of what sorted itself out (Axella only, nothing moves in Mail; Undo in the toast). Didn't set Away? Digest picker → Catch me up since… |
| Clear short replies fast | Today → "N quick replies ready" → Start: one reply at a time – Send (two taps, or swipe right on the iPhone), Skip (swipe left), Later, Done without reply |
| Protect a free block on a busy day | Morning digest → Hold it (adds one busy "Focus" event to your work calendar; delete it in Calendar any time). Length, calendar and name: Settings → Calendar → Protect your blocks |
| Archive a finished project | Project page → Archive (restore under Projects → Archived) |
| Old mail stuck in the inbox | Account menu → Re-scan inboxes (a full digest over everything still in the inboxes) |
| Handle items fast | iPhone: swipe right = Done, left = Tomorrow, far left = file |
| Times, days, models of the runs | Dashboard → Settings → Schedule (state/scheduler.json) |
| What ran, why it failed | Dashboard → Runs (live log, today's slots, last 100 runs, kept 30 days) |
| Change priorities, folders, tone | Edit `AXELLA.md` / `contacts.md` – the next run picks it up |
| Change what a run does | Edit the prompt in `setup/local-tasks/` – the next run uses it |
| Update the dashboard | `cd web && npm run deploy` |
| Update the service | edit `setup/*.py`, then `launchctl kickstart -k …axella-actions` |
| Old digests | moved to `digests/archive/YYYY-MM/` after 30 days (never deleted) |
| Back up | Settings → System → Backup (section 18); Time Machine of the Mac covers `digests/` and `state/` too (not in git) |

---

## 13. Security model (what protects what)

- **Network**: services listen on 127.0.0.1 and accept connections only from Tailscale's own process (checked per
  connection), so other users and programs on the Mac can't reach them. The only way in is Tailscale Serve inside your
  tailnet, and every request must carry the Tailscale login of an allowed user (`www/access.json`). No Funnel, no open ports.
- **Actions**: a fixed list (draft, file, trash, event, done/snooze, tasks, projects, push, receipt forward,
  unsubscribe). Sending only on your confirmed tap (reply_send/mail_send); no permanent delete; forwarding only to the closed recipients list. POSTs need a custom header + JSON (blocks cross-site form posts).
  User data reaches AppleScript only as arguments, never pasted into script text.
- **Claude runs**: read-only by tool allow-list (send/move/delete/click tools are refused by the CLI); message content is treated as untrusted (instructions inside messages
  are flagged, never followed); VIP status only on a verified address/number.
- **Data at rest**: digests, state, WhatsApp summary and project files stay on the Mac (`chmod 600`, not in git).
  FileVault protects them when the Mac is off. Keep your own copy of the repo **private** if you commit `AXELLA.md` or other
  personal files to it.
- **What leaves the Mac**: each Claude run sends what it reads to Anthropic, through your Claude subscription, to write
  the digest. Push notifications travel end-to-end encrypted through Apple's push service. Tailscale's servers set up the
  connection but can't read the traffic. The optional call agent (section 15) runs on Twilio and Vercel, and the Mac
  sends it your contacts' names and numbers so it can recognise callers. Receipt forwarding and unsubscribes go out only on
  your tap, or for vendors you switched auto-forward on for.

---

## 14. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Digest says "WhatsApp summary unavailable (No access…)" | Python lacks Full Disk Access – add both Python paths (section 3), restart the service |
| Digest said "WhatsApp window closed" | Old behaviour – WhatsApp is now read from its database; check `state/whatsapp.json` |
| Actions fail: "Mail/Calendar did not answer …" | Mail busy (syncing after sleep/new device sign-in) or showing a dialog. Open Screen Sharing, check Mail, try again |
| Push: "pywebpush not installed / push library missing" | `pip install --user pywebpush` for **/usr/bin/python3**, then restart the service |
| No push for a new digest | `state/push-last.json` should name the newest `.json`; iPhone: Settings → Notifications → Axella |
| "Digest missing" push | Open Runs: the slot shows failed/missed with the reason and log |
| Run log: `MCP macuse: failed` / 0 Macuse tools | Runs → Re-check setup; check `state/mcp.json` points at `…/Macuse.app/Contents/MacOS/macuse` with `mcp` |
| Runs: "Setup not complete" | `claude` not found, `state/mcp.json` missing, or `ANTHROPIC_API_KEY` set for the service |
| AppleScript "syntax error: Expected expression but found …" | A reserved word used as a variable name (`rd`, `before`, `after`…) |
| GitHub shows a stranger as commit author | Your git `user.email` is a placeholder – use your own `<id>+<user>@users.noreply.github.com` |
| Dashboard 403 | Your Tailscale login isn't in `www/access.json` |
| Dashboard shows 502, or "Mail and messages are paused – the owner isn't logged in" | Your login session is gone (logged out, or another user took the Mac). Check over SSH: `who`, then `launchctl print gui/$(id -u) >/dev/null 2>&1 && echo "session OK" \|\| echo "no session"`, `launchctl list \| grep axella`, `/Applications/Tailscale.app/Contents/MacOS/Tailscale serve status`. No session: log in with Screen Sharing → *Log in as yourself* – the agents start by themselves. Session OK but a service is down: `launchctl kickstart -k gui/$(id -u)/<label>`. `kickstart` over SSH fails with error 125 when there is no session – log in first. See *Keep it running when other users log in* (section 6) |
| Dashboard doesn't load, log says `refused 127.0.0.1:… process … is not Tailscale` | Something other than Tailscale tried to connect – expected for `curl` on the Mac. If it's every request, Tailscale's process path changed: check `ps -o uid=,comm= -p <pid>`, or run `setup/peer-test.sh` and reload the dashboard – it shows which program connects. Emergency only: `touch axella/state/peer-check.off` and restart (lets any local program in – remove it again) |
| Microsoft 365 mail stops arriving in Apple Mail | Exchange Web Services is being switched off for Exchange Online – see *Use Outlook or another mail app?* in section 2 |

## 15. Optional: the call agent (unanswered calls take a message)

The call agent is a separate repo, [`AccelathonDK/axella-voice`](https://github.com/AccelathonDK/axella-voice), hosted on Vercel because Twilio must reach it from the
internet – the Mac mini stays closed and only pulls. Cost: a Twilio number + per-minute usage (prepaid balance), Claude
Haiku via an Anthropic API key (prepaid credits, set a monthly limit); Vercel Hobby and Upstash Redis free tiers are
enough for a personal line.

1. **Twilio**: buy a number in your country (for Denmark a regulatory bundle is needed), block international outgoing
   calls under Voice geo permissions, and note the Account SID / **Auth Token** (Console → Account info – not an API key).
   Keep auto-recharge off and add a usage alert (Monitor → Usage triggers), so a flood of calls can't run up a bill.
2. **Anthropic**: create an API key (e.g. `axella-voice`) with a monthly spend limit.
3. **Vercel**: import your fork of `axella-voice` from GitHub (install the Vercel GitHub app on your own account only),
   region fra1. Add Upstash Redis from the Marketplace (it adds `KV_REST_API_URL` / `KV_REST_API_TOKEN`). Environment
   variables: `ANTHROPIC_API_KEY`, `TWILIO_AUTH_TOKEN`, `AXELLA_SYNC_TOKEN` and `VOICE_LOOKUP_KEY` – two different long
   random strings (`openssl rand -hex 32` each). Node.js version 22 (Settings → General). Deploy.
4. **Twilio webhook**: the number's "A call comes in" → Webhook, `https://<project>.vercel.app/api/voice`, HTTP POST.
5. **Mac mini**: put the same two secrets in `state/voice-token` (the sync token) and `state/voice-lookup-key` (the
   lookup key) without echoing them (`read -s t; printf %s "$t" > state/voice-token; chmod 600 state/voice-token`, the
   same for the lookup key), add `"voice": {"url": "https://<project>.vercel.app", "number": "<twilio number>"}` to
   `setup/actions-config.json` (the name callers hear comes from `"owner"`), and restart the action service. Allow
   Contacts access for Python when macOS asks. With the lookup key, only a fingerprint of each number plus the first
   name and tier leave the Mac; the Call agent card in Settings says which form is in use. Optional:
   `"quiet_hours": [22, 7]` in `"voice"` (the default) – no push for ordinary calls at night, VIPs and urgent calls still
   push. A VIP line in `contacts.md` with a phone number (`- Kim Example – +45 00 00 00 00`) is matched on that number
   only; without one, on the name.
6. **Phone**: set "forward when not answered / busy / unreachable" to the Twilio number (for Danish operators usually
   `**61*<number>#`, `**67*<number>#`, `**62*<number>#`).
7. **Test**: call the Twilio number directly. Within a minute the call appears in the Calls card with a push, and the
   Call agent card shows a recent "Last check".

Limits built into the call agent: 3 answered calls per number per hour (VIPs exempt) and 30 in total, a
"still there?" after 20 s of silence and goodbye after 45 s, calls cut at 4 minutes, and one urgent push per number per
day. Calls over a limit get a busy signal and aren't answered. The deployment URL is easy to guess – that's fine, every
endpoint checks a Twilio signature or the sync token.

Rotating the secrets (e.g. twice a year, or at once if Vercel or the Mac mini may have leaked them): phone numbers
are a small space, so a leaked `VOICE_LOOKUP_KEY` lets anyone turn the fingerprints back into numbers. Make two new
strings (`openssl rand -hex 32`), set them as `AXELLA_SYNC_TOKEN` and `VOICE_LOOKUP_KEY` in Vercel (Production), put
the same into `state/voice-token` and `state/voice-lookup-key` as in step 5, redeploy on Vercel and restart the action
service – the next sync pushes fingerprints made with the new key. Never print either value in the call agent's logs.

Troubleshooting: Call agent card amber → see the error line (401 = sync token differs between Vercel and
`state/voice-token`). "Lookup key … not on Vercel" → add `VOICE_LOOKUP_KEY` in Vercel and redeploy. Calls answered but nothing arrives → Vercel → Logs for `/api/relay`. Caller hears an error
right away → Twilio Console → Monitor → Errors (often a signature check failing because the webhook URL differs).

## 16. Optional: Signal (receive only)

Axella reads Signal through signal-cli, linked to your account like a desktop app. Axella only receives – it never
sends a message or a read receipt – skips attachments and stories, and only sees messages from the moment it is linked.
Signal's own delivery receipts ("delivered") do go out when signal-cli receives a message; signal-cli can't switch
those off, and your phone sends the same receipt anyway.

**A linked device can send as you.** signal-cli's keys are unencrypted on the Mac mini, so treat it like a logged-in
Signal Desktop: Axella keeps the folder `0700` and no Claude run may read it. Removing "Axella (Mac mini)" under
Linked devices on the phone is the off switch. Like every app, Signal is **Normal** by default: chats are read for
your digests. Mark the people whose messages should stay out as **Private** (Settings → Privacy) – Axella then only
shows *that* a message arrived – or Hidden. To keep all of Signal out, set the Signal default to Private.

The Signal app (Signal Desktop) is not needed. If it is installed on the Mac mini while anyone on Signal is private,
Axella's runs get no app-window reading tools at all.

```
brew install signal-cli qrencode
signal-cli link -n "Axella (Mac mini)" > /tmp/signal-link.txt &
sleep 8
head -1 /tmp/signal-link.txt | qrencode -t ansiutf8
```
On the phone: Signal → Settings → Linked devices → **+** → scan the code. Wait until the `signal-cli link` job ends
(`jobs` shows nothing), then remove `/tmp/signal-link.txt` and restart the action service. Settings → Private contacts
shows "Signal: connected". To stop: remove "Axella (Mac mini)" under Linked devices on the phone.
signal-cli keeps its keys in `~/.local/share/signal-cli` (never in this repo); check with `ls -ld ~/.local/share/signal-cli`
that it shows `drwx------`.

## 17. Optional: invitees and online meetings (Calendar → New event)

New event can invite people and add a fresh online meeting. **The calendar's own server sends the invitations**, so people get a real invitation with Accept / Decline and their answers show on the event:

- an **iCloud** calendar → iCloud sends them (CalDAV, with an app-specific password);
- a **work (Microsoft 365)** calendar → Exchange sends them (Microsoft Graph, through your Teams connection).

Online meetings come from the services you connect: **Microsoft Teams** (work or school accounts only), **Google Meet** and **Zoom**. You can also paste a link (FaceTime, Webex …). Only the meeting's title and time go to a service. Nothing is sent before you tap Send invites / Send update / Send cancellation.

Each installation uses **its own app registrations**; Axella ships no shared keys and has no cloud. Client ids, secrets, the iCloud password and the sign-ins are kept in the Mac mini's **Keychain** – never in a file. You enter them in Terminal with `tools/meeting-services.py`; it prints only whether something is set up.

**First, the redirect address.** Set `"dashboard_url"` in `setup/actions-config.json` to your dashboard's https Tailscale address, e.g. `"https://<mac>.<tailnet>.ts.net/axella"`. Every service sends you back to `https://<mac>.<tailnet>.ts.net/axella/api/oauth_callback` – register exactly that address with each one.

### iCloud invites
1. At https://account.apple.com → Sign-In and Security → App-Specific Passwords, make one named "Axella invites".
2. `cd ~/dev/own/home-server/axella && python3 tools/meeting-services.py icloud` – your Apple Account address and that password.

### Microsoft Teams (and invites from the work calendar)
1. https://entra.microsoft.com → App registrations → New registration. Name "Axella". Supported accounts: *Accounts in any organizational directory* (or only your work tenant). Redirect URI: platform **Web**, the address above.
2. Certificates & secrets → New client secret (24 months). Copy the value.
3. API permissions → Microsoft Graph → Delegated: `User.Read`, `Calendars.ReadWrite`, `OnlineMeetings.ReadWrite`, `offline_access`.
4. `python3 tools/meeting-services.py teams` – the Application (client) id, the secret, and `organizations` (or your tenant id).
5. Settings → Calendar → Microsoft Teams → **Connect**, sign in with your work account.

If the sign-in says an administrator has to approve the app, Teams shows *Waiting for your IT*. Send your IT this (fill in the client id) – you send it yourself:

> I'd like to use a small personal assistant app that I run on my own computer to create Teams meetings and send meeting invitations from my own calendar. Could you approve it for my account? App: Axella (registered by me), client id: <id>. Delegated permissions, for my account only: Calendars.ReadWrite (create, change and cancel my own events and their invitations), OnlineMeetings.ReadWrite (Teams meetings with the lobby on), offline_access (stay signed in), User.Read (my name and address). It doesn't read mail, files or anyone else's calendar, and acts only when I tap.

### Google Meet
1. https://console.cloud.google.com → a new project → APIs & Services → enable the **Google Meet REST API**.
2. OAuth consent screen: External, add yourself as a test user, then **Publish app** (in Testing, Google ends the sign-in after 7 days; a personal app with few users needs no review – you click past "unverified app" once).
3. Credentials → Create OAuth client ID → **Web application**, the redirect address above. Scope used: `meetings.space.created` only.
4. `python3 tools/meeting-services.py google_meet`, then Connect in Settings → Calendar.

A Meet link has no time and can't be deleted (it stops working after a year unused); Axella makes one for trusted people only (others knock).

### Zoom
1. https://marketplace.zoom.us → Develop → Build App → **General App**, user-managed. Redirect URL and allow list: the address above.
2. Scopes: `meeting:write:meeting`, `meeting:update:meeting`, `meeting:delete:meeting`. You don't need to publish it – it works for your own account.
3. `python3 tools/meeting-services.py zoom`, then Connect.

Zoom meetings get a passcode and the waiting room.

**Disconnect** in Settings removes the sign-in from the Keychain; also remove Axella's access on the service's own page (the link opens). `python3 tools/meeting-services.py remove <name>` removes the app registration too.

---

## 18. Backup and move to a new Mac mini

Everything Axella has learned – settings, privacy choices, VIPs, To dos, projects, trips, meeting preps, promises,
subscriptions, knowledge, `AXELLA.md`, `contacts.md` and the account config – goes into one encrypted file. Keys and
tokens never do: they belong to one Mac and are made again after a restore.

**Once:** install the encryption tool, version 1.3 or later (its `batchpass` plugin lets Axella pass the passphrase
without a terminal):

```bash
brew install age
age --version
```

**Export:** Settings → System → Backup → Export backup. Choose a passphrase (at least 10 characters, asked twice,
never stored). Tick *Include history* for digests, calls, the activity log and recordings. Download the file
`axella-backup-<date>.axbak` – one download, within an hour. Without the passphrase the backup can't be opened.

**Weekly, automatically (optional):** in the same card, pick a folder on the Mac mini – an external disk
(`/Volumes/…`), a NAS share, or an iCloud Drive folder (then Apple keeps a copy in iCloud: your choice; the file is
encrypted). The passphrase is kept in the Keychain while this is on. The last 4 are kept. A failed backup shows on
System status, and there's one push after two weeks without a good one. Axella never uploads a backup anywhere itself.

**Restore** (a new Mac mini, or the same one):

1. Install Axella as in this guide up to the service (sections 1–6), and `brew install age`.
2. Stop the service if it's running (`launchctl bootout gui/$(id -u)/<label>`; the script tells you the label).
3. Copy the backup file to the Mac, then in the Axella folder:

```bash
cd ~/dev/own/home-server/axella
tools/restore.sh ~/Downloads/axella-backup-2027-03-15.axbak
tools/restore.sh ~/Downloads/axella-backup-2027-03-15.axbak --apply
```

The first command is a dry run: what's in the backup and what would be replaced – nothing changes. `--apply` asks
for the passphrase and "yes", moves the current data aside to `pre-restore-<time>/` (never deleted), puts the
backup in place and rewrites paths for this Mac (a new home folder or user name). A wrong passphrase or a changed
file stops before anything moves. A backup from a newer Axella is refused – update Axella first.

4. Start the service again (section 6) and open Settings → System status. Reconnect what the restore lists: Mail
   accounts, Messages and Full Disk Access, WhatsApp export, Signal linking, the call agent's token in Vercel, push on
   each device, meeting services, Macuse, the Claude login, Report a problem, automatic backups.
