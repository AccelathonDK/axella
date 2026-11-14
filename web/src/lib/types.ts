export type SectionKey = 'p0' | 'p1' | 'p2' | 'open' | 'p3' | 'cal' | 'wait' | 'file'
export type Ctx = 'work' | 'private'
export interface Person { name?: string; address?: string; number?: string; tier?: string }
export interface CalEvent { calendar: string; title: string; start: string; end: string; location?: string }
export interface Item {
  id: string; section: SectionKey; channel?: string; account?: string
  headline?: string; detail?: string; summary?: string; subject?: string
  from?: Person; message_id?: string; deep_link?: string; file_to?: string
  draft?: { mode?: string; to?: string; subject?: string; text?: string; kb?: string[] }
  event?: CalEvent; context?: string; readonly?: boolean; project?: string | string[]
  found?: string; found_in?: string; date?: string   // a mail found by Search (token for the Mac mini), where it is, when
  first_seen?: string; in_calendar?: boolean; carried?: boolean; overdue?: boolean; reminder?: boolean
  /** set by the Mac mini's local scam check (setup/safety.py): no draft, never urgent, links never opened */
  safety?: Safety
  /** a page this item belongs to (the Mac mini's own items, e.g. "subscriptions") */
  link?: string
  /** with link "person": the People page to open (the keep-in-touch line) */
  person?: string
  /** an urgent item from the other world in a scoped digest (it broke through) */
  world?: 'work' | 'private'
}
export interface Safety { level: 'scam' | 'check'; label: string; signals: { code: string; text: string }[]; was?: string; draft_removed?: boolean }
export interface DigestData { title?: string; intro?: string; spoken?: string; kind?: string; items: Item[]; fromMd?: boolean; scam_held?: number; held?: number
  /** the worlds this digest covers (Settings → Schedule, per slot); missing = both */
  scope?: ('work' | 'private')[]
  /** the week wrap (Friday work wrap, Sunday week-ahead) – AXELLA.md "Week wrap" */
  wrap?: { headline?: string; still_open?: WrapLine[]; next_week?: WrapLine[]; calm?: string }
  /** the back-from-away briefing (setup/away.py, local-tasks/return-briefing.md): the run writes headline, still and
      coming; the Mac mini adds "sorted" (grouped from the digests written while away) and the absence */
  away?: AwayBlock }
export interface AwayGroup { key: string; label: string; count: number; items: { id: string; headline?: string; who?: string; section?: string }[] }
export interface AwayBlock { headline?: string; still?: WrapLine[]; still_total?: number; coming?: WrapLine[]; arrived?: number
  absence?: { from?: string; to?: string; days?: number; manual?: boolean }; sorted?: { groups: AwayGroup[]; count: number } }
export interface WrapLine { text: string; item_id?: string; task_id?: string; event?: Record<string, unknown> }
export interface DigestMeta { date?: Date; kind?: string; label: string }
export interface Digest { name: string; meta: DigestMeta; data: DigestData }
export interface Task {
  id: string; text: string; due?: string | null; status?: string; source?: string; reminder?: string
  /** optional Work / Private – unset shows under both filters */
  ctx?: 'work' | 'private' | null
  /** longer description: context, links, what "done" means – also handed to Claude with "Open in Claude" */
  notes?: string
  ref?: { deep_link?: string | null; [k: string]: unknown }
  /** a bill (setup/bills.py): the same To do, with payee, exact amount and payment reference */
  type?: 'bill'; bill?: Bill
}
export interface BillRef { fi?: string; iban?: string; account?: string; mobilepay?: string; invoice_no?: string }
/** the payment details are not on the To do (Claude runs read tasks.json) – GET bills "refs" has them per task */
export interface Bill { payee: string; amount: number | null; currency?: string | null; document?: string
  account?: string; message_id?: string; subject?: string; attachments?: string[]
  /** warnings that stay on the To do: a first bill from this sender, or payment details that differ from earlier bills */
  first_time?: boolean; details_differ?: boolean; sender_differs?: boolean }
export interface Call {
  id: string; priority?: string; started?: string; duration_s?: number; demo?: boolean
  /** name = the contact whose number matches caller ID (unverified), said_name = what the caller said */
  from?: Person & { said_name?: string | null; caller_id_match?: boolean }; context?: string; summary?: string; sms_draft?: string
  urgent_claimed?: boolean; urgent_capped?: boolean
  callback?: { by?: string | null; number?: string | null; other_number?: boolean }; callback_event?: CalEvent
  transcript?: { who: string; text: string }[]
}
export interface CallConfig {
  demo?: boolean; mode?: string; mode_label?: string; greeting_da?: string; greeting_en?: string
  quiet_hours?: string; retention_days?: number
  number?: string; last_sync?: string; last_call?: string; contacts?: number; vips?: number; config_pushed?: string
  last_error?: string; last_error_at?: string; lookup?: 'hashed' | 'plain' | 'key-missing-on-vercel'
}
export type ItemState = Record<string, { status: string; until?: string }>
export interface Overrides { sender: Record<string, Ctx>; domain: Record<string, Ctx>; item: Record<string, Ctx> }
export interface Project {
  id: string; name: string; tag: string; color?: string; status: 'active' | 'suggested' | 'archived' | 'dismissed'; ctx?: 'work' | 'private'
  source?: string; why?: string; created?: string; accepted?: string; archived?: string; keywords?: string[]; senders?: string[]
  notes?: { id: string; text: string; created: string }[]
  links?: { id: string; url: string; title?: string; created: string }[]
  files?: { id: string; name: string; type: string; size: number; uploaded: string }[]
  items?: { digest?: string; item_id: string; headline?: string; added?: string }[]
  hidden_items?: string[]
  order?: number
}
export interface ScheduleSettings {
  vacation: { on: boolean; mode: 'urgent' | 'off'; from: string | null; until: string | null }
  days: number[]; urgent_on_days_off: boolean; off_dates: string[]
  /** a day off = a day off from work: Work-only digests pause, private ones run */
  off_work_only?: boolean
  sweep_request: { at: string; by: string; worlds?: ('work' | 'private')[] } | null
  /** "In an hour": the one-off sweep the owner asked for from the offer on Today */
  sweep_later?: { at: string; asked: string; by: string } | null
  /** "Offer a sweep outside digest hours" and the kinds of gap it is not offered in (day-5 = Saturdays, evening, …) */
  sweep_offer?: { on: boolean; off_kinds: string[] }
}
export interface ScheduleInfo {
  schedule: ScheduleSettings
  status: { digests: boolean; urgent: boolean; reason: string | null; vacation_until: string | null; work_paused?: boolean }
  sweep: { at: string; by: string; fired_at: string | null } | null
  later?: { at: string; asked: string; by: string } | null
  wait: string
  /** the next digest that will really run (scheduler.next_digest) – the line at the top of Today; null = none scheduled */
  next?: { at: string; label: string; worlds: ('work' | 'private')[] } | null
}
export interface Doc {
  message_id: string; account?: string; mailbox?: string; date?: string | null; vendor: string; vendor_key: string
  kind: 'receipt' | 'invoice' | 'bill' | 'reminder' | 'credit' | 'order' | 'other'; amount?: number | null; currency?: string | null
  due?: string | null; project?: string | null; subject?: string; from?: string; attachments?: string[]; deep_link?: string
  needs_details?: boolean; manual?: string[]; hidden?: boolean; paid?: boolean; ctx?: 'work' | 'private' | null
  sent?: { to: string; name: string; id: string; at: string; how: string }[]; suggest_to?: string | null
}
export interface Recipient { id: string; name: string; email: string; project?: string | null }
export interface VendorRule { project?: string | null; kind?: string | null; ctx?: 'work' | 'private' | null; count?: number; forward?: Record<string, number>; auto_forward?: { recipient: string; since: string } }
export interface Sender {
  address: string; name: string; domain: string; count: number; unread: number; first_at?: string; last_at?: string
  subjects: string[]; accounts?: string[]; unsub?: { https: string | null; mailto: string | null; one_click: boolean }
  status: 'active' | 'unsubscribed' | 'kept'; changed_at?: string; method?: string; after_unsub?: number; latest_id?: string; account?: string
  /** Always hold: kept out of the digests (safety.py); manual = held from a digest item, not a bulk sender */
  hold?: boolean; manual?: boolean
}
/** the monthly "never opened" suggestion (subscriptions.py quiet) */
export interface QuietSuggestion { month: string; dismissed: boolean; senders: { address: string; name: string; count: number; since?: string }[] }

/* Briefings (setup/briefings.py) */
export interface Briefing {
  id: string; name: string; kind: 'research' | 'news'; prompt: string; sources: string[]; days: number[]; time: string
  length: number; language: 'en' | 'da'; voice: boolean; personal: boolean; enabled: boolean
  next_run?: string | null; latest?: Brief | null
}
export interface BriefItem { title: string; summary: string; url: string; source: string; published?: string | null }
export interface Brief {
  id: string; briefing: string; name: string; kind: string; at: string; run: string; headline: string; nothing_new: boolean
  items: BriefItem[]; spoken: string; personal_note?: string | null; language?: string
  outbound?: { provider: string; queries: string[]; urls?: string[]; fetched: number }; dropped?: string[]
}
