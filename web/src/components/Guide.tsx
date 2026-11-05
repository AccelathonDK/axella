import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Activity, Archive, Briefcase, ChevronRight, FolderKanban, Headphones, ListTodo, MailPlus, Newspaper, Phone, Receipt,
  ShieldCheck, Inbox, Briefing as BriefingIcon, Lock, Search as SearchIcon, Calendar as CalendarIcon, Meeting as MeetingIcon, Trip as TripIcon, UserCircle, Palmtree, Reply, Moon, Sparkles, axi } from '@/components/ax-icons'
import { AskIcon, openAsk } from '@/components/Ask'
import { ReportIcon, openReport } from '@/components/Report'
import { openCompose } from '@/components/Compose'
import { Rune } from '@/components/icons'
import { openTour } from '@/components/Tour'
import { CalmSetupNudge } from '@/components/CalmSetup'
import { KnowledgeIcon } from '@/components/Knowledge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { useApp, type View } from '@/lib/app'
import { cn } from '@/lib/utils'

/* Getting started (account menu): a short tour of what Axella does, grouped by how you use it.
   Each part has an "Open" that takes you there. Opened from the account menu via openGuide(). */
export const GuideIcon = axi('info')
const Insights = axi('insights')
export const openGuide = () => window.dispatchEvent(new Event('ax-guide'))

type Part = { id: string; icon: any; title: string; lines: ReactNode[]; open?: { label: string; view?: View; section?: string; run?: () => void } }
// the topics with a Show me tour (components/Tour.tsx TOURS)
const SHOW_ME: Record<string, string> = { sprint: 'sprint', trips: 'trips', meetings: 'meetings', calendar: 'invites', projects: 'project-mails', backup: 'backup' }
const CHAPTERS: { title: string; parts: Part[] }[] = [
  { title: 'Every day', parts: [
    { id: 'now', icon: axi('focus'), title: 'Today and Briefing', open: { label: 'Today', view: { kind: 'today' } }, lines: [
      <><b className="font-medium">Today</b> is one list of everything that needs you – urgent and overdue first, then today's replies, calls and tasks due. It is empty when you're done.</>,
      <><b className="font-medium">Briefing</b> is the calm read: the spoken summary, what's new since you last looked, your day, and what waits on others. The Briefing page has the full digest.</>,
      'On the phone, Today, Briefing, Ask and To do are the tabs at the bottom; More opens the menu. + at the top starts a new mail, task, reminder or knowledge entry (on the laptop: + New, next to your account).',
    ] },
    { id: 'digests', icon: Inbox, title: 'Your digests', open: { label: 'Briefing', view: { kind: 'briefing' } }, lines: [
      'Axella reads your mailboxes, messages, WhatsApp and calendar on the Mac mini and writes a digest several times a day, plus a week-ahead on Sunday evening. The times are set under Settings → Schedule, with days off and vacation; Runs and logs shows how each run went.',
      'Between digests it checks for urgent things every 15 minutes and sends a push if something can\'t wait. Turn on notifications with the bell.',
      'Pick an earlier digest with the date picker at the top; older ones are under Older digests.',
      <>The Friday afternoon work wrap and the Sunday week-ahead open with a <b className="font-medium">Week wrap</b> card: a headline, what's still open and next week – each line jumps to its item, task or event.</>,
    ] },
    { id: 'away', icon: Palmtree, title: 'Back from away', open: { label: 'Briefing', view: { kind: 'briefing' } }, lines: [
      <>After 2 or more days away (Away, vacation or days off – a weekend in between counts), the first digest is a <b className="font-medium">Welcome back</b> briefing: what still needs you (at most 10 lines), what's coming up this week, and what sorted itself out while you were gone.</>,
      <><b className="font-medium">Archive all</b> marks the sorted-out groups handled in Axella, with one Undo – nothing is moved or deleted in Mail. Open a group to keep an item back first. Urgent items and anything the briefing still shows are never archived this way.</>,
      'Away without telling Axella? The digest picker → Catch me up since… makes one for the date you choose.',
    ] },
    { id: 'triage', icon: axi('approve'), title: 'Working through a digest', lines: [
      <><b className="font-medium">Done</b> clears an item. <b className="font-medium">Later</b> brings it back when you choose – later today, this evening, tomorrow, Monday or a date you pick.</>,
      <>Tap an item's title to open it: one place with Axella's note, your reply, the mail itself (for WhatsApp and Messages: Axella's summary), and who and what it relates to – the person, projects and calendar.</>,
      'Filing suggestions move a mail – or a whole thread – to the folder Axella suggests, or to any other folder. Tick several (or Select all) to file or delete them together – Delete moves them to Trash, at most 200 at a time, with 6 seconds to undo.',
      'On the iPhone: swipe right for Done (or Move in Filing), left for tomorrow 07:00, far left to move to the suggested folder.',
      <>What you handle in Axella is <b className="font-medium">read in Mail</b> too: opening a mail here, filing it, Done, Delete and a reply mark it read – Done doesn't move it. Undo marks it unread again. Messages, WhatsApp and Signal are never marked read (that would tell the other person).</>,
      'The ⋯ menu has the rest: add as task, add to calendar, tag a project, Work/Private, add to VIPs, save as knowledge, delete (to Trash). On a thread it also shows all its mails, marks them all done or opens the thread in Mail.',
      'Pictures in a mail stay blocked until you tap Load pictures – or Always for this sender. Tap a picture or image attachment to see it large.',
      <><b className="font-medium">Possible scam</b> or <b className="font-medium">Check before you click</b>: the Mac mini's own scam check labels mails and texts that pretend to be someone else, hide where a link goes or press you to pay or verify. A flagged item has no draft and no reply buttons, and opens as plain text. Why flagged shows the signals, with Move to Junk, Block number and Mark safe.</>,
    ] },
    { id: 'teach', icon: Sparkles, title: 'Teaching Axella', open: { label: 'Rules', view: { kind: 'settings', page: 'rules' } }, lines: [
      <>⋯ → <b className="font-medium">Not important…</b> or <b className="font-medium">This should have reached me…</b> asks why: this sender, this kind of mail, or just this once. The first two make a rule – the next digests sort that sender or topic for you.</>,
      'Now and then Axella notices something you always do – filing a sender in the same folder, marking mail done without replying, answering someone within the hour, unsubscribing – and suggests a rule on Today: one card at a time, at most 3 a week. Make it a rule, Not now, or Never suggest this.',
      'Settings → Rules lists every rule in plain words, with when and why – remove one and it stops. Your own settings always win: VIPs, private contacts, protected workplaces and the scam check.',
    ] },
    { id: 'reply', icon: axi('draft'), title: 'Replying and sending', lines: [
      <><b className="font-medium">Reply</b> opens the item with Axella's draft in the editor – change what you like. Where Axella left a choice in [ … ], tap the option that's true, or Edit the [ … ] part – Send stays off until then. WhatsApp and Messages drafts work the same way.</>,
      'What you type is kept if you close the item, and Done on an edited, unsent reply asks first.',
      'To and Cc are filled in as reply all – remove anyone, add people or a Bcc. Assistant (under the reply) improves, shortens, changes the tone, fixes spelling, translates or drafts the reply, on the selected text or all of it; it only suggests – Replace or Insert, and it never changes who the mail goes to.',
      <>Attach files with <b className="font-medium">Attach</b> or by dropping them on the reply. Tick "Remind me if no answer" to get a follow-up task in a few days.</>,
      <><b className="font-medium">Send</b> asks once more ("Tap again to send to Sam"), then counts down 6 seconds – tap it again to undo. Your Mac mini's Mail sends it in the same thread – Mail itself can stay in the background.</>,
      <><b className="font-medium">Later</b>, next to Send, sends at a time you choose – Tomorrow 08:00, Monday 08:00 or Pick a time…. The mail waits on the Mac mini; the Scheduled card on Today lets you change it, send it now or cancel it. If the Mac mini was off and the time is more than an hour past, nothing goes by itself – you get one notification to send it now or pick a new time.</>,
      'Prefer Mail? ⋯ → Save as draft in Mail instead. WhatsApp and Messages replies open the app with the text ready; for a WhatsApp group you pick the group, and the text is copied too.',
    ] },
    { id: 'sprint', icon: Reply, title: 'Reply sprint', open: { label: 'Today', view: { kind: 'today' } }, lines: [
      <>With 3 or more quick replies ready – Axella's short drafts (under 80 words) – Today shows <b className="font-medium">"5 quick replies ready · about 4 minutes"</b>, with Start. They open one after another: people waiting on you first.</>,
      'Each one is the ordinary reply: edit it, Send (its own two taps and the 6 seconds to undo), Later, Skip, or Done without reply. On the iPhone: swipe right to send (the same countdown), left to skip. There is no send-all.',
      'Private contacts, protected workplaces and flagged mail are never in a sprint. Leave halfway and the card shows what\'s left.',
    ] },
    { id: 'ctx', icon: Briefcase, title: 'Work and private', lines: [
      'The All / Work / Private switch at the top filters everything – digests, receipts and insights.',
      'An item in the wrong place? ⋯ → Move to Work/Private – for a sender, Axella remembers it from then on.',
      'VIPs count as important in digests and urgent checks, and the call agent marks their calls. Axella suggests people you write with often; tap Add to VIPs, or use ⋯ on any item from that person. Settings → VIPs lists them all – add, edit, move or remove.',
    ] },
    { id: 'todo', icon: ListTodo, title: 'To do and waiting', open: { label: 'To do', view: { kind: 'todo' } }, lines: [
      'Two tabs: My tasks, and Waiting on others – what you asked for and haven\'t had an answer to.',
      'Add tasks with a due date; they are grouped as Overdue, Today, This week and Later. Move one with its calendar button – today, tomorrow, Monday, in a week, a date, or no date.',
      'Tasks also come from digests, Ask Axella, and "Remind me if no answer" when you send a reply. On a mail, ⋯ → Add as task lets Axella read it and propose the task, its details and a due date when the mail gives one – change anything before you add it.',
      'Open a task to add details – background, links, what done looks like. ✦ Open in Claude hands the task and its details to Claude.',
      'Recurring reminders (rent, insurance, birthdays) are set under Settings → Reminders and turn into tasks by themselves.',
      <><b className="font-medium">Bills</b>: invoices and reminders from Receipts are suggested at the top – Add to To do, Edit or Not a bill. The Bills filter lists them; open one for the payment details, each with Copy. A first bill from a sender, another address or changed details hides them behind a warning. Ticking it off marks it paid. Axella never pays.</>,
    ] },
    { id: 'promises', icon: axi('approve'), title: 'Your promises and replies you owe', open: { label: 'Today', view: { kind: 'today' } }, lines: [
      <><b className="font-medium">Promises:</b> when you write "I'll send it Friday" or "jeg vender tilbage i morgen" in a mail or message, a card offers Add to To do, Edit or Not a promise – nothing is added without your tap. When a later message looks like you kept it: "Looks done – tick it off?". A promise without a date leaves the list after 14 days.</>,
      <><b className="font-medium">You owe N replies:</b> people you write with who asked you something directly and haven't had an answer – work after 3 working days, private after 5, at most 21 days back. Never authorities, shared mailboxes (info@, post@ …), no-reply senders or a plain "thanks". × next to a name: never for this person.</>,
      'Found on the Mac mini by rules, never by Claude. Private contacts are never read; for a protected workplace the card says only who and when.',
    ] },
    { id: 'calendar', icon: CalendarIcon, title: 'Calendar and invitations', open: { label: 'Calendar', view: { kind: 'calendar' } }, lines: [
      'Calendar shows your calendars from the Mac mini – Agenda for the next 14 days, or Week – with the All / Work / Private filter, and what the digest noted (conflicts, suggestions).',
      'New event adds one, and your own events without other people can be changed or deleted – owner only (a deleted event can be restored from the Activity log for 90 days).',
      <><b className="font-medium">Invitees</b> on New event sends real invitations from the calendar's own server (iCloud or your work account) – add a Teams, Meet or Zoom link, or paste one. You see who, from where and when before Send invites. The event shows each person's answer; Change… sends an update and Cancel the meeting a cancellation. Services are connected under Settings → Calendar.</>,
      <><b className="font-medium">Protect your blocks</b>: on a busy workday with only one free block left, the morning digest may suggest holding it – Hold it adds one busy "Focus" event of your own; nothing else changes. Length and calendar: Settings → Calendar.</>,
      <><b className="font-medium">Invitations waiting for your answer</b> (on Today, Calendar and Meetings): open one for Accept, Maybe or Decline. Axella sends the organizer the standard calendar answer through Mail – the same second tap and 6 seconds to undo as any send – and on Accept or Maybe puts it in the calendar you pick.</>,
      'The sheet warns when the organizer is on another domain than the mail came from, and a no-reply organizer can\'t be answered from Axella.',
    ] },
  ] },
  { title: 'Get more done', parts: [
    { id: 'ask', icon: AskIcon, title: 'Ask Axella', open: { label: 'Ask', run: () => openAsk() }, lines: [
      'Ask about your mail, tasks, projects, calls, receipts and knowledge: "What did Sam say about access?", "What\'s still open for the kitchen project?"',
      'When you ask it to do something, it suggests action cards (snooze, done, task, reminder …) – nothing happens until you tap one.',
    ] },
    { id: 'compose', icon: MailPlus, title: 'New mail', open: { label: 'Write', run: () => openCompose() }, lines: [
      'Tell Axella who and what; it drafts three versions in your tone from earlier mail and your knowledge. Pick one, edit, attach files, and Send – or save it to Drafts in Mail.',
    ] },
    { id: 'meetings', icon: MeetingIcon, title: 'Meetings', open: { label: 'Meetings', view: { kind: 'meetings' } }, lines: [
      'Meetings lists what\'s coming in the next 14 days – events with other people, a join link (Meet, Teams, Zoom …) or an invitation; a repeating meeting is one row – and how far each prep is. Today shows meetings in the next 48 hours that have no prep yet.',
      <><b className="font-medium">Prepare</b> opens one prep per meeting: goals, points to discuss, background, notes, materials (files, mails, web pages) and the people – with your recent mail, open tasks and earlier meetings with them. It saves as you type, and reads as a document to print, download or mail as an agenda.</>,
      'The assistant works on this meeting only and proposes cards you add with a tap. During or after the meeting: Record in Axella on the phone or the Mac, or upload a recording – it is transcribed on the Mac mini and never leaves your home – or paste a transcript, then Find outcomes (decisions, tasks, follow-ups) and a follow-up mail for you to check and send.',
      'Meeting preps are the owner\'s own. For a protected workplace you choose what Claude may read – My own text only, Everything or Nothing – per meeting, with a default per workplace on the Meetings page.',
    ] },
    { id: 'trips', icon: TripIcon, title: 'Trips', open: { label: 'Trips', view: { kind: 'trips' } }, lines: [
      <><b className="font-medium">Scan mail for upcoming trips</b> reads the booking confirmations already in your mail – flights, hotels, trains, ferries, cars, tickets – on the Mac mini, by rules, never by Claude. Trips ahead, and past ones since the date next to Scan mail (12 months back unless you pick another day, up to 18 months; under Past); private contacts and protected workplaces are left out.</>,
      'Bookings close in time become one suggested trip ("Lisbon and Porto, Oct 2027 – 7 bookings"): untick what doesn\'t belong, name it, Confirm – or Not a trip. Nothing becomes a trip by itself.',
      'A trip shows its bookings day by day in each place\'s own time, with the booking reference and a link to the mail. A later scan offers new bookings for it ("Add"). Axella never books, changes or cancels anything.',
      '"Read with Claude" reads the booking mails the rules couldn\'t, and their PDF tickets – flight numbers, times, seats, travellers. Their content goes to Anthropic for this and shows under What leaves my home. Tickets open inside Axella.',
      'Each booking\'s ⋯ has Edit (kind, name, dates and times), Move to another trip and Void (a duplicate or a wrong booking). When Claude has read a flight or stay, the rules\' copy of it goes under "Voided" in the trip by itself – with Restore, like anything you void.',
      'On a travel day Today shows the trip – times, references and tickets, also when the Mac mini is out of reach. Add to calendar per booking; a changed booking waits for Apply or Ignore, and check-in opening is noted. A passport that runs out too soon for a trip is flagged.',
      'Current, Upcoming and Past pick which trips you see; the Work / Private switch at the top works here too (a trip\'s ⋯: Make it a work or private trip). PDF on a trip prints it as a travel plan (on the iPhone: Share → Save to Files); Email opens a new mail in Axella with the plan – you choose who it goes to, and nothing is sent until you send it.',
    ] },
    { id: 'contacts', icon: UserCircle, title: 'Contacts', open: { label: 'Contacts', view: { kind: 'contacts' } }, lines: [
      'Your address book from the Mac mini, with Favourites (your VIPs) on top. A contact opens with Message, Mail, WhatsApp, Signal and Call – each opens the app on the device you\'re holding; nothing is sent from here.',
      'New contact, Edit and Delete (owner only) change macOS Contacts itself; a deleted contact can be restored from the Activity log for 90 days.',
      <>A contact's <b className="font-medium">Open page</b> shows last in touch per channel, what's open between you, meetings, your own note and a timeline. Set <b className="font-medium">Keep in touch</b> (every 2 weeks, month or quarter): when it's been too long, one quiet line in a private digest says so – Draft a note writes a short check-in, sent only when you tap Send.</>,
      'Birthdays: set one with Edit (day and month, the year if you like) – it is saved in Contacts. A Favourite\'s birthday gets one line in the morning digest on the day; switch "Show in the morning digest" on for anyone else, or off for a Favourite. Never for a private contact.',
    ] },
    { id: 'search', icon: SearchIcon, title: 'Search', open: { label: 'Search', view: { kind: 'search' } }, lines: [
      <>Press <b className="font-medium">/</b> (or the magnifier) to search Axella's own history – every digest item, call and task – as you type.</>,
      '"Search all mail" looks through every mail on the Mac mini, also mail from before Axella. A found mail opens like any item: read it as in Mail, open attachments and pictures, and reply. Mail involving a private contact shows only who and when.',
    ] },
    { id: 'projects', icon: FolderKanban, title: 'Projects', open: { label: 'Projects', view: { kind: 'projects' } }, lines: [
      'A project collects mails, notes, links and files around one thing. Axella tags new mail to active projects by itself.',
      <>The <b className="font-medium">Mails</b> card on a project: Scan mail since a date finds mails by its tag, keywords in the subject and its senders, with why each matched – Add, or Not this project. Tick mails and Read with Claude suggests tasks, notes and dates you add with a tap. A project can link to a trip.</>,
      'Finished? Archive it – everything is kept and can be restored.',
    ] },
    { id: 'knowledge', icon: KnowledgeIcon, title: 'Knowledge', open: { label: 'Knowledge', view: { kind: 'knowledge' } }, lines: [
      'Short facts and standard answers your drafts may use – prices, times, terms. Drafts show "Based on …" when they used one.',
      'Every night Axella learns from your sent mail and suggests new entries; nothing is used until you approve it. Mailbox scans dig through older mail.',
    ] },
    { id: 'briefings', icon: BriefingIcon, title: 'Topic briefs', open: { label: 'Topic briefs', view: { kind: 'briefings' } }, lines: [
      'Research and news on your schedule – for example a Monday brief on a topic you follow, or what\'s on this weekend. Each brief is a headline and 3–5 items with a short summary and a link to the source.',
      'Nothing you\'ve already been told comes back, and when nothing new has happened the brief says so in one line. New briefs show up as a quiet card on Today.',
      'Only the search queries leave your home: the research run can\'t see your mail, messages or calendar. "Use my calendar" adds a note like "You\'re free Saturday afternoon" afterwards, on the Mac mini, without web access. Each brief shows what left your home.',
      'Add, edit, pause or run one now on the Topic briefs page (at most 8). (Not to be confused with Briefing – the digest itself.)',
    ] },
    { id: 'listen', icon: Headphones, title: 'Listen and calls', lines: [
      'Listen (the headphones at the top) reads the briefing aloud – also from the car with the Siri shortcut "Axella digest".',
      <>Calls you don't answer go to the call agent (Settings → Calls), which takes a message; a call to return shows up in <b className="font-medium">Today</b>, and every call is in the Briefing.</>,
    ] },
  ] },
  { title: 'Keep things tidy', parts: [
    { id: 'receipts', icon: Receipt, title: 'Receipts', open: { label: 'Receipts', view: { kind: 'receipts' } }, lines: [
      'Receipts and invoices from your receipt folders, per vendor, with monthly spend and a Work/Private split.',
      'Forward to your bookkeeping in one tap – only to the recipients under Settings → Bookkeeping. Missing amounts are read from the PDFs every night – or tap "+ Amount".',
      <><b className="font-medium">Subscriptions</b>: what you pay again and again – from your receipts, App Store and Google Play receipts, and renewal, trial and price mails – with totals per month and year. A new one, a price change or a trial ending gets one quiet line in the morning digest. Keep, Mark cancelled or Not a subscription; Axella never cancels or pays.</>,
      <><b className="font-medium">Renewals</b>: what expires or renews on a date – passport, driving licence, insurance, domains, yearly plans – found in genuine mail or added by hand. At its lead time it shows on Today with Add to To do. Document numbers are never stored.</>,
    ] },
    { id: 'newsletters', icon: Newspaper, title: 'Mailbox: filing, newsletters, cleanup', open: { label: 'Mailbox', view: { kind: 'mailbox' } }, lines: [
      'Filing suggestions, newsletters and cleanup live together under Mailbox – one place to keep the mailbox tidy.',
      'Everyone sending you marketing, grouped by company. Unsubscribe in one tap – Axella only uses the sender\'s official unsubscribe.',
      'Once a month Axella suggests senders you never open. Always hold keeps a sender out of your digests (also from any item\'s ⋯ menu); the Held tab lists them, with undo.',
    ] },
    { id: 'cleanup', icon: Archive, title: 'Cleanup', open: { label: 'Cleanup', view: { kind: 'mailbox', tab: 'cleanup' } }, lines: [
      'Old mail with no relationship – never answered, from no one you know – can go to a "Cleanup" folder in the same mailbox. Choose mailboxes and age under Settings → Mailbox.',
      'Nothing is deleted, and every move can be undone.',
    ] },
    { id: 'insights', icon: Insights, title: 'Insights', open: { label: 'Insights', view: { kind: 'insights' } }, lines: [
      'Who writes to you most, what is still open with them, and which topics take your time – compared with the period before once there is enough history.',
      <><b className="font-medium">Your calm</b>: messages held for a digest against what broke through, digests read and listened to, reply times, work outside work hours. <b className="font-medium">Your time</b>: hours in meetings and the longest free block per workday. No scores, no streaks.</>,
    ] },
  ] },
  { title: 'Behind the scenes', parts: [
    { id: 'settings', icon: Activity, title: 'Settings and runs', open: { label: 'Settings', view: { kind: 'settings' } }, lines: [
      'Settings is an overview with one page per area – Schedule, Calendar, Away, Calls, Privacy, VIPs, Reminders, Mailbox, Bookkeeping, Reports, Notifications, Rules, Appearance and System – each with a line on what it does and its current state.',
      'The dot on your account button says when something needs you; the account menu shows it in one sentence, and System status has the details and how to fix each one.',
      'The small ? in the bottom-right corner of a page starts that page\'s tour; Settings → Appearance turns it off on this device.',
      'Settings → System shows versions and the Mac mini, with Runs and logs for every run. In the account menu: Run sweep now makes an extra digest; Re-scan inboxes looks at all old mail still in your inboxes.',
    ] },
    { id: 'calm-setup', icon: Moon, title: 'Calm setup', open: { label: 'Calm setup', view: { kind: 'settings', page: 'notifications' } }, lines: [
      'Three steps, about two minutes, so Axella is the one voice: turn off banners for Mail, Messages and WhatsApp on the iPhone, allow Axella\'s notifications (Axella checks this one itself), and make an “Axella” Focus that lets your VIPs through.',
      'Settings → Notifications always has it. Axella changes nothing on the iPhone – these are steps you follow, and it never reminds you.',
    ] },
    { id: 'backup', icon: Archive, title: 'Backup and moving', open: { label: 'Backup', view: { kind: 'settings', page: 'system' } }, lines: [
      <>Settings → System → <b className="font-medium">Export backup</b>: one encrypted file with everything Axella has learned – a passphrase you choose, never stored. Include history adds digests, calls and recordings.</>,
      'Weekly automatic backups go to a folder you pick (a disk, a NAS or iCloud Drive), keeping the last 4. Keys and tokens are never in a backup – after a restore you reconnect them; tools/restore.sh shows what it would change first and never deletes anything.',
    ] },
    { id: 'activity', icon: axi('runs'), title: 'Activity log', open: { label: 'Activity log', view: { kind: 'activity' } }, lines: [
      'In the account menu: everything done from the dashboard and by Axella itself – replies, scheduled sends, invitations, filing, tasks, contacts, calendar, privacy, notifications and Claude runs. Titles only, never what was written.',
      'Filter by type, who or result. A deleted contact, event or meeting prep can be restored from here for 90 days.',
    ] },
    { id: 'private', icon: Lock, title: 'Private contacts and Signal', open: { label: 'Privacy', view: { kind: 'settings', page: 'privacy' } }, lines: [
      <>Per contact and per app (Mail, iMessage, WhatsApp, Signal): <b className="font-medium">Normal</b> – read and summarised; <b className="font-medium">Private</b> – Axella only knows that something arrived; <b className="font-medium">Hidden</b> – ignored. Private and hidden are enforced on the Mac mini before any Claude run sees anything.</>,
      'A private message shows on a Private card on Today (who, where, how many – never the text), and you get a notification unless you turn "Notify me" off. "Discreet dashboard" leaves the names off the card, and the notifications have their own switch for that.',
      'Signal comes in through a linked device on the Mac mini (receive only, see SETUP). Like every app, Signal is Normal by default – only the people you mark Private (or Hidden) are kept out of your digests.',
    ] },
    { id: 'report', icon: ReportIcon, title: 'Report a problem', open: { label: 'Report a problem', run: () => setTimeout(openReport, 200) }, lines: [
      <>Press <b className="font-medium">⌘B</b> / <b className="font-medium">Ctrl+B</b> anywhere (on the phone: the account menu, or a long press on the Axella mark). Say what happened or what's missing; Axella suggests Critical, Annoying, Cosmetic or Missing.</>,
      'It is saved on the Mac mini first (Settings → Reports). Sending is a separate tap after you have seen exactly what leaves: the layout of the screen with every text replaced, action names, error templates and the app version – never your messages. What you type is checked for names, addresses and numbers.',
      'Download for Claude in Settings → Reports gives a zip with a report.md and the pictures per report, ready to hand to Claude.',
    ] },
    { id: 'rules', icon: ShieldCheck, title: 'The house rules', lines: [
      'Nothing is sent without your tap: a mail goes only when you tap Send, confirm, and let the 6 seconds run out – or, with Later, at the time you picked. Axella\'s own runs never send. The only other exceptions: receipts to your own recipients list, and one-click unsubscribes.',
      'Every mail and invitation sent from Axella is logged on the Mac mini, and there is a brake of 20 an hour.',
      'Everything runs on your Mac mini and is reached only through Tailscale. When you are offline, Axella says so and picks up again by itself.',
    ] },
  ] },
]

// the newest parts, as a row at the top that jumps to them (keep it short; drop old entries as new ones arrive)
const NEW: [string, string][] = [['calm-setup', 'Calm setup'], ['teach', 'Teaching Axella'], ['triage', 'Read in Mail'], ['sprint', 'Reply sprint'],
  ['away', 'Back from away'], ['backup', 'Backup'], ['receipts', 'Renewals']]

export function GuideHost() {
  const [open, setOpen] = useState(false)
  useEffect(() => { const h = () => setOpen(true); window.addEventListener('ax-guide', h); return () => window.removeEventListener('ax-guide', h) }, [])
  return open ? <Guide onClose={() => setOpen(false)} /> : null
}

function Guide({ onClose }: { onClose: () => void }) {
  const { go } = useApp()
  const box = useRef<HTMLDivElement>(null)
  function openPart(o: NonNullable<Part['open']>) {
    onClose()
    if (o.run) { setTimeout(o.run, 150); return }
    if (o.view) go(o.view)
    if (o.section) setTimeout(() => document.getElementById('sec-' + o.section)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 350)
  }
  const jump = (i: number) => box.current?.querySelector(`[data-ch="${i}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  const jumpPart = (id: string) => {
    const el = box.current?.querySelector(`[data-part="${id}"]`)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' }); el.classList.add('ax-flash'); setTimeout(() => el.classList.remove('ax-flash'), 1600)
  }
  return <Dialog open onOpenChange={o => !o && onClose()}>
    <DialogContent className="sm:max-w-2xl">
      <div className="border-b px-5 py-4 pr-12">
        <DialogTitle className="flex items-center gap-2.5 text-lg font-semibold tracking-tight"><Rune size={20} />Getting started</DialogTitle>
        <div className="text-ink-2 mt-0.5 text-sm">Axella reads everything, sorts it, and drafts – you decide. Here is what it can do and where to find it.</div>
        <Button size="pill" className="mt-3" onClick={() => { onClose(); setTimeout(openTour, 200) }} data-take-tour=""><ChevronRight />Take the tour</Button>
        <CalmSetupNudge where="guide" onOpen={onClose} />
        <div className="mt-3 flex flex-wrap gap-1.5">
          {CHAPTERS.map((c, i) => <button key={c.title} onClick={() => jump(i)}
            className="text-ink-2 hover:border-line-strong hover:text-ink rounded-md border px-2.5 py-1 text-[13px]">{c.title}</button>)}
        </div>
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[13px]" data-guide-new="">
          <span className="text-ink-3 mr-0.5">New this week:</span>
          {NEW.map(([id, label]) => <button key={id} onClick={() => jumpPart(id)} className="bg-fjord-soft text-fjord rounded-md px-2 py-0.5 font-medium hover:underline">{label}</button>)}
        </div>
      </div>
      <div ref={box} className="flex-1 overflow-y-auto px-5 pb-6">
        {CHAPTERS.map((c, i) => <section key={c.title} data-ch={i} className="scroll-mt-2 pt-5">
          <div className="ax-label mb-2">{c.title}</div>
          <div className="divide-y rounded-lg border">
            {c.parts.map(p => <div key={p.id} data-part={p.id} className="flex scroll-mt-4 gap-3 px-4 py-3.5">
              <span className="bg-fjord-soft text-fjord flex size-9 shrink-0 items-center justify-center rounded-md"><p.icon className="size-[18px]" /></span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <div className="flex-1 text-[15px] font-semibold">{p.title}</div>
                  {SHOW_ME[p.id] && <Button size="pill" variant="outline" className="h-7" onClick={() => { onClose(); setTimeout(() => openTour(SHOW_ME[p.id]), 200) }} data-show-me={SHOW_ME[p.id]}>Show me</Button>}
                  {p.open && <Button size="pill" variant="ghost" className="text-fjord -mr-2 h-7" onClick={() => openPart(p.open!)}>{p.open.label}<ChevronRight /></Button>}
                </div>
                <ul className={cn('text-ink-2 mt-1 space-y-1 text-sm leading-relaxed')}>
                  {p.lines.map((l, j) => <li key={j} className="flex gap-2"><span className="ax-diamond text-ink-3 mt-[7px] shrink-0" style={{ width: 5, height: 5 }} /><span>{l}</span></li>)}
                </ul>
              </div>
            </div>)}
          </div>
        </section>)}
        <p className="text-ink-3 mt-6 text-center font-mono text-[11px] tracking-[.08em] uppercase">Your attention, on your terms.</p>
      </div>
    </DialogContent>
  </Dialog>
}
