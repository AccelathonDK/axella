# Microsoft Teams

*Status: November 2026.*

Teams chats live in Microsoft 365, not on the Mac. There is no local database worth reading, and the Teams app has no
scripting interface. The only solid path is Microsoft Graph, which needs the employer's IT on board.

## Paths

### 1. Microsoft Graph, delegated (recommended)
- **What:** read the owner's own 1:1 and group chats (and, if wanted, channel messages in his teams).
- **How:** poll on the Mac mini:
  - `GET /me/chats` and `GET /chats/{id}/messages` (newest first, stop at the last seen message) for chats;
  - `GET /teams/{id}/channels/{id}/messages/delta` for channels.
  Change notifications (webhooks) would need a public endpoint – not allowed for Axella – so polling every few minutes
  it is.
- **Requirements:**
  - An app registration in the **work tenant's** Microsoft Entra ID (or IT's approval of a personal one).
  - Delegated permissions: `Chat.Read` (own chats), optionally `ChannelMessage.Read.All` (channels – needs admin
    consent), `User.Read`, `offline_access`. **Not `Chat.ReadWrite` / `ChatMessage.Send`** – Axella doesn't send.
  - Admin or user consent, depending on the tenant's consent policy; most companies require admin approval.
  - Device-code sign-in once, refresh token in the macOS Keychain.
  - Teams with a personal Microsoft account (Teams free) is **not** covered by these Graph chat APIs.
- **Avoid:** application permissions like `Chat.Read.All` (all chats of all users) – far more than Axella needs, and
  IT should refuse it.

### 2. Claude's Microsoft 365 connector
Reads Teams chats and channel messages (read-only by default; write tools are optional and need extra admin approval).
Needs a Business-plan tenant and a Global Administrator's consent. Like for Outlook, it serves the Claude apps, not the
Mac mini's scheduled runs.

### 3. Screen reading of the Teams app
Macuse `computer_use_read_text` on the Teams window. Fragile (layout changes, only what is on screen), and work chats
read on a home computer usually need IT's OK anyway. A stop-gap at most.

## Before building – ask IT
1. May a delegated app read the owner's own chats (`Chat.Read`), and who grants consent?
2. Are channel messages wanted, and is admin consent for `ChannelMessage.Read.All` possible?
3. Any Conditional Access / compliant-device rules for the Mac mini?
4. Data handling: chats stay on the Mac mini, digests summarise; message bodies from a protected workplace are not
   copied elsewhere (see the README rules).

## Sources
- [Chat.Read.All (application) – what it allows](https://graphpermissions.merill.net/permission/Chat.Read.All)
- [Chat.Read.WhereInstalled](https://graphpermissions.merill.net/permission/Chat.Read.WhereInstalled)
- [Microsoft 365 connector for Claude – setup](https://support.claude.com/en/articles/12542951)
