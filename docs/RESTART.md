# After a restart – what starts by itself, and what you need to do

Axella runs on an always-on Mac. This page explains what happens when that Mac restarts – after an update, a crash or a
power cut – and how to set it up so Axella comes back with as little help from you as possible.

Short version: **the Mac starts by itself, the web page and the watchdog come up at once, and Axella itself starts when
you are logged in.** With FileVault on (recommended) you log in once after every restart; Axella tells you when.

## What runs where

| Part | Runs as | Starts | Needs your login? |
|------|---------|--------|-------------------|
| **Web server** (`www-server.py`) – serves the dashboard over Tailscale | LaunchDaemon, as you | At boot | No |
| **Watchdog** (`setup/watchdog.py`) – checks every minute, pushes when Axella pauses or a source can't be read | LaunchDaemon, as you | At boot | No |
| **Action service** (`setup/axella-actions.py`) – digests, urgent checks, sending, search, WhatsApp, Signal | LaunchAgent | At login | **Yes** |
| **Mail, Messages, WhatsApp, Macuse** | Apps in your session | At login (Login Items) | Yes |

The action service needs your login session because it reads Mail's index and Messages, talks to Mail through
AppleScript and reads WhatsApp's database – all of which only exist while you are logged in.

The two LaunchDaemons are installed with `setup/install-daemons.sh` (see [SETUP.md](SETUP.md), section 6,
"Keep it running when other users log in").

## What happens after a restart

1. The Mac starts by itself (if *Start up automatically after a power failure* is on).
2. The web server and the watchdog start at boot. The dashboard opens and says Axella is waiting for you to log in.
   The watchdog sends one push: Axella has paused.
3. You log in once – on the Mac, or through Screen Sharing. (With FileVault on, macOS can't log in for you.)
4. The action service and the apps in Login Items start. The watchdog sends one push when Axella is back.
5. The next urgent check and the next scheduled digest run as usual. Nothing is lost: mail and messages that arrived
   while Axella was paused are read by the next run.

## One-time setup

### 1. Start after a power failure, never sleep

```bash
sudo pmset -a autorestart 1
sudo pmset -a sleep 0
```

Or: System Settings → Energy → *Start up automatically after a power failure* on, and *Prevent automatic sleeping
when the display is off* on. Check with `pmset -g | grep -E "autorestart|sleep "` – you want `autorestart 1` and
`sleep 0`.

### 2. FileVault and automatic login – choose one

| | FileVault on (recommended) | FileVault off + automatic login |
|---|---|---|
| After a restart | Log in once | Comes back fully by itself |
| If the Mac is stolen | Disk is encrypted – your mail and messages are safe | Anyone can read the disk |

The Mac holds all your mail, messages and call transcripts, so keeping FileVault on is the safer choice. The watchdog's
push tells you when a login is needed. Check with `fdesetup status`.

### 3. Login Items

System Settings → General → Login Items & Extensions → *Open at Login*:

| App | Why | |
|-----|-----|---|
| **WhatsApp** | Axella reads WhatsApp's database, which only updates while the app runs | Required |
| **Tailscale** | The dashboard is reachable only through your tailnet (also turn on "Launch at login" in the app) | Required (app version) |
| **Macuse** | Claude's runs read Mail, Calendar, Contacts and Messages through it | Recommended |
| **Mail** | Axella starts it when needed; open from the start, new mail is fetched and indexed straight away | Recommended |

Not needed at login: Messages (iMessage/SMS sync without the app), Signal (Axella uses `signal-cli`), the Claude
desktop app (runs use the Claude Code CLI).

### 4. Check the services

```bash
launchctl list | grep -i axella
sudo launchctl list | grep -iE "web|watchdog"
```

You should see the action service in the first list, and the web server and watchdog in the second. The labels
depend on your setup (`local.axella.actions`, `local.axella.web` and `local.axella.watchdog` by default). The
dashboard shows the same under **Account menu → System status**.

## Restarting a service – the right way

Always restart through launchd, never by starting a script by hand. A process started from a terminal or by an
agent doesn't belong to launchd, so it isn't restarted if it crashes, and it doesn't stop cleanly.

```bash
launchctl kickstart -k gui/$(id -u)/local.axella.actions
sudo launchctl kickstart -k system/local.axella.web
sudo launchctl kickstart -k system/local.axella.watchdog
```

Use your own labels if they differ (see step 4).

**Full Disk Access is only picked up when a process starts.** After granting it (System Settings → Privacy & Security
→ Full Disk Access), restart the action service. Until then WhatsApp and Mail search stay unreadable, even though the
switch is on.

## Test it once

At a calm moment, restart the Mac (Apple menu → Restart) and check:

1. Before you log in: the dashboard opens and says Axella is waiting for your login; a push arrives.
2. After you log in: System status shows every part as OK within a few minutes, and a push says Axella is back.
3. Search finds mail and the WhatsApp chat preview shows messages.

## Troubleshooting

| What you see | What to do |
|--------------|-----------|
| Dashboard doesn't load at all | Tailscale isn't running on the Mac or your device – open it, check you're logged in |
| Dashboard says Axella is paused | Log in on the Mac (FileVault), or check `launchctl list` for the action service |
| WhatsApp or mail search unreadable after a restart | Check Full Disk Access for Python (SETUP.md, Permissions), then restart the action service |
| WhatsApp is quiet in the digests | WhatsApp isn't running – open it and add it to Login Items |
| No push after a restart | The watchdog isn't installed – run `setup/install-daemons.sh` |
