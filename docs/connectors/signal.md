# Signal

*Status: November 2026.*

Signal has no official API for reading your own messages. Every path is either an unofficial client or reading the
desktop app's local data. Signal is end-to-end encrypted, so messages only exist on your devices – Axella must be one
of them, or read one of them.

## Paths

### 1. `signal-cli` as a linked device (recommended)
`signal-cli` is an open-source command-line Signal client. Linked like Signal Desktop, it receives every new message
on the Mac mini.

- **How:**
  1. Install `signal-cli` (needs Java) on the Mac mini.
  2. Run `signal-cli link -n "Axella"` and scan the QR code from the phone (Settings → Linked devices).
  3. Run it as a daemon with JSON-RPC on localhost (or `receive` on a timer). A small exporter writes
     `state/signal.json`.
- **Requirements:**
  - A free linked-device slot (Signal allows a few).
  - The daemon must run regularly. Signal keeps undelivered messages on its servers only for a limited time.
  - Only messages from the moment of linking – no old history.
- **Read-only by design:** the exporter only calls `receive` and never exposes `send` to Claude. Note that receiving
  can send delivery receipts; read receipts are only sent when explicitly asked for, which Axella never does.
- **Risks:** unofficial – Signal can change its protocol and break it until `signal-cli` catches up. The link gives
  the Mac mini full access to new messages, so the device's security matters (FileVault, screen lock – already in place).

### 2. Read Signal Desktop's local database
Signal Desktop on the Mac mini keeps an encrypted SQLite (SQLCipher) database. Since 2024 its key is protected by
Electron safeStorage, i.e. the macOS Keychain.

- **How:** like the WhatsApp exporter – copy the database, open it with the key from the Keychain, read new messages.
- **Requirements:** Signal Desktop installed and linked on the Mac mini; Keychain access for the exporter (a one-time
  "Allow" prompt); a SQLCipher library.
- **Pros:** includes history synced at link time; no extra client. **Cons:** breaks when Signal changes its schema; the
  Keychain prompt needs the logged-in session.

### 3. Screen reading of Signal Desktop
Macuse on the Signal window. Fragile – a stop-gap only.

## Recommendation
Path 1 for new messages (clean, receive-only, no history). Add path 2 later only if older history is wanted. Keep the
Signal content under the same rules as Messages: summaries in digests, no copies elsewhere.

## Sources
- [signal-cli (AsamK) – project and docs](https://github.com/AsamK/signal-cli)
- [Signal Desktop: protecting the database key with Electron safeStorage](https://github.com/signalapp/Signal-Desktop/pull/6849)
