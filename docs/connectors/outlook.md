# Outlook / Microsoft 365 mail

*Status: November 2026.*

## Why this one is urgent

Axella reads mail through Apple Mail (Macuse). Apple Mail on macOS talks to **Exchange Online** accounts through
**Exchange Web Services (EWS)**, and Microsoft is switching EWS off:

- **From 1 Oct 2026** EWS is disabled tenant by tenant, unless the tenant's admin has allow-listed it.
- **On 1 Apr 2027** EWS is removed for good, with no exceptions.
- On-premises Exchange Server is not affected.
- Apple's Graph-based replacement in Mail is announced for "a future update to macOS 27", with no firm date.

So a work mailbox on Exchange Online can stop syncing in Apple Mail at any moment (if IT has not allow-listed EWS), and
by April 2027 at the latest. Ask IT which state the tenant is in. iCloud, Gmail and IMAP accounts are not affected.

## Paths

### 1. Microsoft Graph (recommended)
A small read-only connector on the Mac mini that reads mail through Graph.

- **How:** poll `GET /me/mailFolders/inbox/messages/delta` (and `sentitems` for the knowledge harvest) every few
  minutes. Delta queries return only what changed, so polling is cheap. No webhooks are needed, which keeps the
  "no inbound traffic" rule.
- **Form:** an MCP server with read tools (search, get message, get thread, list folders) for live lookups, or an
  exporter that writes `state/outlook.json`. Moving and drafting would be separate, tap-only actions in
  `axella-actions.py`, like the Apple Mail ones today.
- **Requirements:**
  - An app registration in Microsoft Entra ID (the tenant's, for a work account; a personal app works for
    outlook.com accounts).
  - Delegated permissions: `Mail.Read` (read), `Mail.ReadWrite` only if Axella should move mail or save drafts, and
    `offline_access` for a refresh token. **Never `Mail.Send`**.
  - Sign-in once with the device-code flow (no redirect server needed), refresh token kept in the macOS Keychain.
  - For a work tenant: IT must allow user consent or grant admin consent. Conditional Access may require a compliant
    device – ask before building.
- **Pros:** future-proof, fast, works with the Mac locked. **Cons:** needs IT's OK for the work mailbox; a second path
  next to Apple Mail.

### 2. Claude's Microsoft 365 connector
Anthropic's connector searches Outlook, Teams, SharePoint and OneDrive (read-only by default).

- **Requirements:** a Microsoft Entra tenant on a Business plan (no personal Microsoft accounts) and a Global
  Administrator's one-time consent. Available on all Claude plans.
- **Limit:** it lives in the Claude apps, not in the Mac mini's scheduled `claude -p` runs, so the digests can't use it
  as-is. Useful for ad-hoc questions, not as Axella's source.

### 3. Stay on Apple Mail
- Fine for on-premises Exchange, iCloud, Gmail and IMAP.
- For Exchange Online: only until the tenant disables EWS (April 2027 at the latest), or later with Apple's
  Graph-based Mail if it ships in time. IMAP is often switched off in work tenants.

### 4. New Outlook for Mac + screen reading
- New Outlook has no AppleScript support, so only screen reading (Macuse `computer_use_read_text`) is left. Fragile and
  slow – a stop-gap at most.

## Recommendation
Build path 1 for the work mailbox before the tenant switches EWS off: one read-only connector with delta polling,
`Mail.Read` + `offline_access` (plus `Mail.ReadWrite` only for moving and drafts), token in the Keychain. Ask IT first:
(1) is EWS still allowed for the tenant, (2) may a personal app registration get delegated Mail access, (3) any
Conditional Access rules for the Mac mini.

## Sources
- [EWS retirement update (MC1227454)](https://mc.merill.net/message/MC1227454)
- [Apple Mail's Exchange accounts and the EWS shutdown](https://macos-tahoe.com/blog/apple-mail-exchange-accounts-ews-shutdown-october-2026-guide/)
- [Microsoft 365 connector for Claude – setup](https://support.claude.com/en/articles/12542951)
