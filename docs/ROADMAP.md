# Axella – roadmap / ideas

## Next up – first roll
Prioritised 31 Oct 2026. Status 1 Nov: A, B (as Listen), C, J, F, D and H built. (G) a little later.
The SQLite store (J) is built; Insights (F) and the knowledge base (G) build on it.

1. (H) **UI/UX polish – built 31 Oct–1 Nov 2026**, see Built. Left for later: pull to refresh, loading skeletons,
   rolling counts.
2. (G) **To discuss: knowledge base + automatic AI replies** – a knowledge base Axella can answer from (FAQs, standard
   answers, prices, availability, links, per project/company), and rules for when Axella may reply on its own
   (which senders/channels/topics, which answers, daily cap, log + undo window, always a signature that says it's
   Axella). Changes hard rule 1 ("nothing sent without your tap"), so it needs its own narrow exception like
   receipts forwarding – start as "draft ready, one tap" and only auto-send per rule after a trial period.
   Build order: (1) knowledge base organised by category/tags (e.g. employer, own company, holiday-home rental, private),
   so each auto-reply rule points at a category; (2) then overall training and learning – Axella learns from the
   drafts you edit and send, and from the answers you give, and proposes new knowledge-base entries for approval.

## Later – to prioritise after the first roll
- **Call your own Axella number for the digest** – when the call agent recognises your number, it reads the
  latest spoken digest and answers follow-up questions instead of taking a message.
- **Call agent controls** – mode (message / call back only / off → voicemail), editable greetings, quiet hours,
  callers from protected workplaces summary-only – once the agent has been used for a while.
- **To discuss: more connectors (MCP)** – a general way to plug new sources into Axella, starting with one of
  your own projects. Discuss the foundation: a connector registry in config (per connector: name, MCP
  command/URL, read-only tool allow-list, which digests/checks use it, how items map to channel/sender/project),
  secrets outside git, a doctor test per connector in Runs, and the same untrusted-content and read-only rules as
  Macuse. Decide whether connectors run only inside Claude runs or also feed the pre-check.
- **Slack** – parked: not used at the current workplace.
- **Microsoft Teams (work)** – parked until Microsoft Graph access is discussed with the employer's IT. Macuse has no Teams tools; options: (1) today – Teams' missed-message emails in the work mailbox;
  (2) Macuse screen reading of the Teams window – fragile, and work chats on a home computer need IT's OK;
  (3) Microsoft Graph with IT's approval – the reliable route. Ask IT about Graph access to his own chats and whether
  reading Teams on a home Mac is acceptable at all.

## Built
- Mail cleanup (1 Nov 2026): old mail with no relationship → a "Cleanup" folder per mailbox, chosen mailboxes and
  age (12/24/36 months) in Settings, grouped by sender, keep list, undo. Offline notice + offline app shell (1 Nov 2026).
- Knowledge base step 2a (1 Nov 2026): nightly learning from sent mail (facts, corrections to drafts, outdated flags)
  and mailbox scans (folder/sender/period, answered threads, nightly batches) – all as suggestions to approve.
  Still open from step 2: imports (PDF/Word/text). Then step 3 (URL snapshots), step 4 (auto replies).
- Filing per thread, receipt amounts (type + read from PDFs, nightly catch-up) (1 Nov 2026).
- Ask Axella (1 Nov 2026): a chat panel (menu, top bar; full screen on iPhone) for questions about mail, tasks,
  projects, receipts, calls and knowledge. Answers show their sources; requests to do something come back as action
  cards (done, snooze, file, task, reminder, knowledge, project, new mail) that run only on your tap. Owner-only.
  Later: an outward-facing chat (option B).
- Monthly spend on Receipts (1 Nov 2026): total per month (tap for vendors) or per vendor with a 12-month strip.
- Newsletters grouped by company (1 Nov 2026): one row per company with all its sender addresses, "Unsubscribe all".
- Inbox re-scan (1 Nov 2026): account menu → Re-scan inboxes – one digest run (setup/local-tasks/inbox-rescan.md) that
  looks at every mail still in the inboxes, however old (up to 150 per mailbox): replies drafted for what needs an
  answer, a folder for what's done, newsletters flagged. Nothing is moved or sent; file from the digest.
- Insights follow the All / Work / Private filter (1 Nov 2026), with the same rule as the dashboard (your overrides
  per item, sender and domain first, then the digest's context, then the mailbox).
- Knowledge base, step 1 (1 Nov 2026): menu → Knowledge and a Knowledge card on every project – short facts and
  answers, overall or per project, category, visibility (private / internal / shareable), check-again date, sources.
  "Save as knowledge" on any draft and in New mail. Digest and New mail drafts use active entries that fit the
  recipient and show "Based on …". Files in knowledge/entries (setup/knowledge.py). Spec: Axella project doc
  "knowledge-base-spec". Next: (2) suggestions from sent mail (all mailboxes, the work mailbox treated like the private
  one, entries from it default to internal) and imported documents, (3) web page snapshots + staleness, (4) auto-reply rules.
- Recurring reminders (1 Nov 2026): Settings → Recurring reminders, or the repeat button in To do's add row – every
  N days/weeks/months/years, task on the day or up to 60 days before, optional push; pause, edit, delete. The Mac mini
  (setup/reminders.py, state/reminders.json) adds an ordinary task per occurrence; after downtime only the newest
  missed one. Tasks show "↻ Every month on the 1st".
- Project archive (1 Nov 2026): Archive from the project page, its card in Projects or the sidebar ⋯ (laptop); a dialog
  says what happens (leaves the menu, no new tagging, notes/links/documents/tasks kept), Undo in the toast, and
  Projects → Archived lists them with date and Restore.
- Faster handling (1 Nov 2026): iPhone swipe on items – right Done (Filing: move to the suggested folder), left
  Tomorrow 07:00, long left move to the suggested folder; delete stays two taps. (Laptop keyboard shortcuts were tried and removed again – not needed.)
- Design system applied (31 Oct 2026): Axella design system (Horizon) across the dashboard – tokens, fonts, archive
  icons, bucket cards, quiet badges; sidebar for content only, Settings / Runs / Run sweep now (confirm dialog) and on
  phones Refresh / notifications / theme under the account pill; action animations (approve tick, file/snooze/delete
  slide + collapse into Handled); launch splash (rune draw, once per session); To do grouped by due date with a
  quiet meta line; Call agent card moved to Settings (Today shows only problems).
- Out of office (31 Oct 2026): Settings → Out of office – period, suggested texts (private DA+EN, work internal/
  external), copy + settings links + "mark as set" per mailbox, push the evening before / morning after; the call
  agent switches to an away greeting by itself (setup/ooo.py, state/ooo.json). The mailboxes themselves can't be
  switched from the Mac mini (iCloud: iCloud.com only; Exchange: Mail/Outlook account settings or Graph with IT's OK).
- Insights (31 Oct 2026): menu → Insights – top 3/10 people and topics for this/last week, this/last month, quarter,
  year, with trend vs. the previous period; per person channels and items not marked done; "People" hides
  newsletters/no-reply/service senders and you yourself (actions-config "self"). From state/axella.db (GET insights).
  Not yet: outgoing volume and reply times (needs counts from Sent mail/Messages).
- SQLite store (31 Oct 2026): state/axella.db (setup/store.py) – every 60 s indexes digests (incl. archive), items
  with full-text search, calls, actions.log and runs; files stay the source of truth (delete the db → rebuilt).
  Protected-workplace items metadata only. Digests now add a stable "topic" per item for Insights. API: GET store, search?q=.
  Next steps when needed: move actions/handled items, receipts register and newsletter senders into it.
- Listen to the digest (31 Oct 2026, replaces the Claude-project sync): menu → "Listen to digest" reads
  digests/spoken-digest.md aloud with the device voice; GET /axella/api/spoken gives it as plain text for the iPhone
  Shortcut "Axella digest" (Siri / CarPlay). No Claude scheduled tasks needed.
- Compose assistant (31 Oct 2026): menu → New mail – receiver, topic, target, tone, language, mailbox; a Claude run
  on the Mac mini (setup/local-tasks/compose.md, Sonnet by default) drafts 3 variants from earlier mail with that
  person; edit, rework ("shorter …"), copy or save to Drafts in the right mailbox. Never sent by Axella.
- Old cloud scheduled tasks deleted (31 Oct 2026) after the first local digests ran fine.
- Call agent (30–31 Oct 2026): unanswered calls forwarded to the Twilio number → Vercel (`axella-voice`, fra1) →
  Claude Haiku takes a message in Danish/English with a female ElevenLabs voice, ends with a goodbye; the Mac mini
  pulls calls every 60 s (Calls card + push), sends contacts/VIPs every 6 h; Call agent status card; calls in digests
- Local scheduler on the Mac mini (30 Oct 2026): Claude Code CLI on the subscription, Settings → Schedule, Runs view
  with live logs, retries, failure push, pre-check that skips urgent checks when nothing is new
- Dashboard actions via a background job queue (answers at once, also while a digest runs or the Mac is locked)
- Reply in thread (draft with quote in Drafts), copy draft, open WhatsApp/Messages chat with text prefilled
- Searchable folder picker from Mail's live folder list; learned folder per sender
- Receipts register + Receipts view (folder watch, catch-up, per-vendor learning)
- Forward receipts to the recipients list (manual; auto-forward per vendor after 3 manual forwards)
- Newsletters view with one-click / draft / web-page unsubscribe

## Ideas (not started)

### Marketing senders: overview + unsubscribe *(built – see Newsletters)*
Keep track of who sends marketing/newsletter mail, show an overview, and unsubscribe with one tap.
- **Collect**: every digest run already classifies P4 "noise". Record per sender (address/domain): count per month,
  last seen, mailbox, whether you ever open/reply, and the `List-Unsubscribe` / `List-Unsubscribe-Post` headers
  (read from the message source via Mail). Store in `state/senders.json`.
- **Overview** (dashboard → "Subscriptions"): senders sorted by volume, "never read" badge, last mail, suggested
  action (keep / unsubscribe / auto-file to a folder).
- **Unsubscribe – safe routes only, always on your tap**:
  1. RFC 8058 one-click (`List-Unsubscribe-Post: List-Unsubscribe=One-Click` + https URL) → the action service
     POSTs to that URL. No browser, no tracking pixels.
  2. `mailto:` unsubscribe → saved as a **draft** in Mail for you to send (Axella never sends).
  3. Only a web link → open it on your phone; never auto-click links from the mail body (phishing risk).
  Then mark the sender "unsubscribed" and flag it if mail keeps arriving after 7 days.
- **Optional**: "file all from this sender" rule suggestion, and a monthly push "12 newsletters, 3 never opened".
- **Open questions**: which mailboxes (private only, or work too), and whether Gmail's forwarded
  mail keeps the List-Unsubscribe headers (check).

### Bills, receipts and invoices per vendor *(register, view and forwarding built; export and recurring detection open)*
One place to see every bill, receipt and invoice, grouped by vendor – for bookkeeping, subscriptions and "did I
pay that?".
- **Collect**: digest runs already spot receipts/invoices (they're filed to `Receipts` and company folders). Record
  each one in `state/documents.json`: vendor (normalised: "Apple", "Spotify", "IKEA"), date, amount + currency if
  stated, type (receipt / invoice / bill / reminder), due date, which company it belongs to (private or one of
  your companies), mail message_id and attachment names. PDFs stay in Mail – Axella
  links to them instead of copying them.
- **Overview** (dashboard → "Receipts"): vendors with count, total per month/year and last document; tap a vendor
  for its list with preview/open in Mail. Filters: company, year, unpaid bills (due date passed, no receipt yet).
- **Recurring**: detect subscriptions (same vendor, same amount, monthly/yearly) and show them as a list with the
  monthly total – links nicely with the marketing-senders idea for cancelling things you don't use.
- **Bills due**: optionally a P2 reminder in the digest for bills with a due date in the next 3 days. (No export to
  accounting systems – forwarding the original mail to your bookkeeping recipients covers it.)
- **Not in mail**: receipts that only live in apps/portals (EV charging, train tickets, parking) can't be read – show them
  as a "missing source" note per vendor rather than guessing.
- **Open questions**: which companies/mailboxes count (work outlays → e.g. `Work/Outlays`?).

#### Add-on: forward receipts to bookkeepers / platforms
- **Recipients list** (dashboard → Settings → "Bookkeeping recipients", stored in `state/recipients.json`):
  `[{name, email, company?}]` – e.g. "Bookkeeper – My Company" → the company's receipt inbox address, or a bookkeeper.
  This list is the ONLY place a forward can go – addresses found in mail can never become recipients.
- **On a receipt/invoice item**: a "Forward to…" button with the list (suggested recipient first). One tap forwards the
  original mail with its attachments from the right account, logs it, and tags the document as "sent to <name>".
- **Learning over time**: every choice is remembered per vendor/sender (+ company). After the same choice a few times
  (e.g. 3×, never contradicted) Axella pre-selects it and shows "usually → Bookkeeper – My Company". You can then switch on
  **auto-forward for that vendor** explicitly; from then on new documents from that vendor are forwarded without a tap,
  listed in the digest ("Forwarded 2 receipts to your bookkeeper") with an undo-style "wrong recipient?" note.
  Auto-forward stays off per vendor until you turn it on, and is only possible to recipients in the list.
- **Rule change needed**: today Axella never sends or forwards anything (AXELLA.md hard rule 1). This feature adds
  one narrow exception: forwarding receipts/invoices to whitelisted recipients – on your tap, or automatically only for
  vendors you've enabled. Everything else stays draft-only.
- **Safeguards**: only messages classified as receipt/invoice with an attachment or a clear amount; never mail that
  arrived at a work mailbox unless that vendor is explicitly enabled; a daily cap (e.g. 20 auto-forwards); everything in
  `state/actions.log`.
