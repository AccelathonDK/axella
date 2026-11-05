# Facebook Messenger

*Status: November 2026.*

**Decision (Nov 2026): Messenger is left out of Axella for now.** These notes are kept in case that changes.

The weakest of the four. Meta offers **no API for personal Messenger chats**, and the native Messenger apps for Mac and
Windows were retired in December 2025 (users were moved to messenger.com / facebook.com). Personal chats are
end-to-end encrypted by default.

## Paths

### 1. Screen reading of messenger.com (stop-gap)
- **How:** keep messenger.com open in a browser on the Mac mini and let a run read the chat list and open chats with
  Macuse (`computer_use_read_text`) or a browser automation.
- **Requirements:** a logged-in Meta session in that browser; for encrypted chats on the web, Messenger's secure
  storage PIN set up so history is available there.
- **Cons:** fragile (Meta changes the page often), slow, only what the page shows; logins expire. Meta may also treat
  automated browsing as suspicious.

### 2. Meta's "Download your information" (history, not live)
- **How:** request an export of Messenger data (JSON) in Meta's Accounts Center, drop it in a folder, and an import
  run reads it – useful for the knowledge harvest, not for daily digests.
- **Requirements:** a manual request each time; exports take from minutes to days.

### 3. Messenger Platform API – only for Pages
The official API (Graph API `/me/messages`, webhooks) is for a **Facebook Page or business** talking to customers,
not for a person's own chats. It needs a Page, a Meta app and webhooks to a public endpoint – which Axella doesn't
allow. Only relevant if a business Page's inbox should be included later (e.g. a holiday-rental Page), and then via a
small relay outside the Mac mini.

### 4. Unofficial clients and bridges
Libraries and Matrix bridges that log in as you do exist, but they break Meta's terms and risk the account being
blocked. Not recommended.

## Recommendation
Leave Messenger out of the daily digests for now. If it matters: use path 1 as a clearly-labelled stop-gap, or ask
the important contacts to move to Signal, iMessage or WhatsApp, which Axella already reads or can read.

## Sources
- [Meta to shut down Messenger desktop apps (TechCrunch)](https://techcrunch.com/2025/10/16/meta-to-shut-down-messenger-desktop-apps-for-mac-and-windows/)
- [Shutdown on 15 Dec 2025, users redirected to the web (CyberInsider)](https://cyberinsider.com/meta-to-shut-down-messenger-desktop-apps-on-december-15-redirects-users-to-web/)
