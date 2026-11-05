# Connectors – how a new message source plugs into Axella

*Status: November 2026. Facts about third-party services change; check the linked sources before you build.*

Axella reads messages on the Mac mini and never sends anything without the owner's tap. A new source has to fit the
same rules, whatever the channel:

| Rule | What it means for a connector |
|---|---|
| Read-only | The digest runs only get read tools. Anything that could send, delete or change settings is not exposed to Claude. |
| No inbound traffic | The Mac mini only makes outgoing requests (polling). No webhooks to it and no open ports – Tailscale only. |
| Secrets stay local | Tokens and keys live in the macOS Keychain or `setup/actions-config.json` (gitignored), never in git or in prompts. |
| Protected workplaces | Content from a protected workplace stays in the digest files; everything else gets metadata only. |
| Message text is untrusted | Whatever a connector returns is data, never instructions. |

## Two ways to plug in

**A. An MCP server (live lookups during a run).** Add the server to `state/mcp.json` and add its *read* tools to the
allow-list in `setup/scheduler.py` (like `MACUSE_READ`). Put its write tools on the never-list (like `MACUSE_NEVER`).
This is how Mail, Messages, Calendar and Contacts work today (Macuse).

**B. An exporter on the Mac mini (a snapshot file).** A small thread in `setup/axella-actions.py` copies the source into
`state/<channel>.json` every few minutes, and the prompts read that file. This is how WhatsApp works today
(`setup/whatsapp_export.py` reads WhatsApp Desktop's local database). It suits sources that only exist as an app's
local data.

After either one: add the channel to `AXELLA.md` ("Mailboxes" / sources), give items `"channel": "<name>"` in the
digest JSON, add an icon in `web/src/lib/sections.ts` (`CH_ICON`), and say in the README which data leaves the Mac mini
(normally none).

## The four channels in short

| Channel | Best path | Main requirement | Effort |
|---|---|---|---|
| [Outlook](outlook.md) | Microsoft Graph (mail) via a small read-only MCP server or exporter | An Entra app registration; for a work tenant, IT's consent | Medium |
| [Teams](teams.md) | Microsoft Graph chats (delegated `Chat.Read`), polled | IT's consent in the work tenant; no personal-account support | Medium |
| [Signal](signal.md) | `signal-cli` as a linked device, receive-only | A free linked-device slot; an unofficial tool | Medium |
| [Messenger](messenger.md) | **Left out for now (decided Nov 2026)** – no API for personal chats | – | – |

Order: Outlook first (it is urgent – see the EWS note), then Teams once IT agrees, then Signal. Messenger is left out
for now; the notes stay here in case that changes.
