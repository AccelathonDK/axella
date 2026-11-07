/* Trips, part one (feature pack Nov 2026 §5): "Scan mail for upcoming trips" reads the booking confirmations already in
   your mail on the Mac mini (rules only, never Claude), and suggests trips you confirm. A trip shows its bookings day by
   day in each place's own time, each with its booking reference and a link to the mail. Nothing is booked, changed or
   cancelled with any provider. Owner only. setup/trips.py, axella-actions.py trip_scan. */
import { Fragment, useEffect, useState } from 'react'
import { TripPassportWarning } from '@/components/Renewals'
import { TripProjects } from '@/components/ProjectMail'
import { toast } from 'sonner'
import { Check, ChevronRight, Loader2, MoreHorizontal, Pencil, Plus, RotateCw as Refresh, Trash2, Trip as TripIcon, X, Save, Mail, Home, Briefcase } from '@/components/ax-icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { get, post } from '@/lib/api'
import { useApp } from '@/lib/app'
import { cn } from '@/lib/utils'
import { LinkedNotes } from '@/components/Notes'
import { ItemSheet, Lightbox } from '@/components/ItemSheet'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input, NativeSelect } from '@/components/ui/input'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { Item } from '@/lib/types'
import { openCompose } from '@/components/Compose'
import { openMailInAxella, type MailRef } from '@/components/MailReader'
import { BookingLive, CalendarDialog, cacheTrips, ticketUrls, type LBooking } from '@/components/TripsLive'
import { Checklist, ItemDialog, MergeDialog, SplitDialog, TripPlanning, editTrip, type ETrip } from '@/components/TripsEdit'

/** A toast after an action: fixed text, or built from the answer. */
type Msg = string | ((answer: any) => string)

export const TripsIcon = TripIcon
interface Booking { key: string; kind: string; title: string; start: string; end: string; place: string; ref: string; provider: string
  status?: string; notes?: string; address?: string; number?: string; ticket?: number | null
  tickets?: { account?: string; message_id?: string | null; ticket?: number | null; travellers?: string[] }[]
  travellers: string[]; confidence: 'data' | 'check' | 'read' | 'manual'; source?: { account?: string; message_id?: string | null; subject?: string; from?: string }
  by_hand?: boolean; confirmed_by?: string | null; loose?: boolean
  cal?: LBooking['cal']; cal_stale?: LBooking['cal_stale']; pending?: LBooking['pending']; updated?: LBooking['updated']; checkin_view?: LBooking['checkin_view'] }
interface Trip { id: string; title: string; start: string; end: string; places: string[]; bookings: Booking[]; new?: Booking[]
  ctx?: 'work' | 'private' | null; ctx_auto?: 'work' | 'private' | null; voided?: (Booking & { voided?: 'duplicate' | 'you' })[]
  planning_view?: Booking[]; checklist?: ETrip['checklist'] }
interface View { since?: string; suggested: Trip[]; past_suggested?: Trip[]; trips: Trip[]; past: Trip[]; scanned?: string | null; unsorted?: Unread[]
  removed?: { id: string; title: string; start: string; end: string; bookings: number; removed_at?: string }[]
  scan: { running: boolean; error: string | null; found: number | null; read?: number; skipped?: number; unread?: Unread[]
    reading?: string | null; reading_n?: number; read_error?: string | null; last_read?: { bookings: number; none: number; placed: number; at: string } }
  quotes?: Booking[]; cal_choice?: Record<string, string> }
interface Unread { account?: string; message_id?: string | null; subject?: string; date?: string | null; from?: string; why: string }
const WHY: Record<string, string> = { 'no dates': 'no dates found', 'no booking reference': 'no booking reference found', 'could not be read': 'could not be read' }

const KIND: Record<string, string> = { flight: 'Flight', hotel: 'Stay', train: 'Train', car: 'Car', bus: 'Bus', ferry: 'Ferry', transfer: 'Transfer',
  ticket: 'Ticket', restaurant: 'Table', booking: 'Booking' }
/** "2027-09-10T21:15+01:00" → the place's own time, as written in the booking */
const hm = (s: string) => /T(\d\d:\d\d)/.exec(s)?.[1] || ''
const tz = (s: string) => { const m = /([+-]\d\d):?(\d\d)$/.exec(s); return m ? `UTC${m[1].replace(/^([+-])0/, '$1')}${m[2] !== '00' ? ':' + m[2] : ''}` : '' }
const day = (s: string) => new Date(s.slice(0, 10) + 'T12:00:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
/** YYYY-MM-DD of this device's own day (toISOString would give the UTC day – wrong after midnight in Denmark) */
const localDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const span = (t: { start: string; end: string }) => {
  const a = new Date(t.start.slice(0, 10) + 'T12:00:00'), b = new Date(t.end.slice(0, 10) + 'T12:00:00')
  const f = (d: Date, y: boolean) => d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', ...(y ? { year: 'numeric' } : {}) })
  return a.toDateString() === b.toDateString() ? f(a, true) : `${f(a, a.getFullYear() !== b.getFullYear())} – ${f(b, true)}`
}
/** the booking's mail, opened in Axella's own reader (also on the phone) – never Mail's message:// link */
const openMail = openMailInAxella
/** the attachment Claude marked as the ticket / voucher / boarding pass, opened from Mail's file on the Mac mini */
type TicketRef = { account?: string; message_id?: string | null; ticket?: number | null; travellers?: string[] }
/** one person however a mail prints the name: "Sam Example" = "EXAMPLE SAM MSTR (CHD)" (order, case and titles ignored) */
const TITLES = new Set(['mr', 'mrs', 'ms', 'miss', 'mstr', 'master', 'dr', 'chd', 'child', 'inf', 'infant', 'adt', 'adult'])
export const personKey = (n: string) => n.toLowerCase().replace(/[()/.,]/g, ' ').split(/\s+/).filter(w => w && !TITLES.has(w)).sort().join(' ')
/** the travellers, each person once (the first way the name was written is kept) */
export const people = (list: string[] = []) => list.filter((n, i) => list.findIndex(m => personKey(m) === personKey(n)) === i)
/** The booking's own mail and ticket. One mail: "Ticket · Mail" as links. Several (each traveller's own e-ticket mail):
    "Tickets and mails (3)" folds out a list under the line – one row per traveller with their Ticket and Mail. */
function Sources({ b }: { b: Booking }) {
  const [open, setOpen] = useState<string | null>(null)
  const [shown, setShown] = useState(false)
  const extra: TicketRef[] = b.tickets || []
  const others = new Set(extra.flatMap(x => (x.travellers || []).map(personKey)))
  const rows: TicketRef[] = [{ account: b.source?.account, message_id: b.source?.message_id, ticket: b.ticket,
    travellers: people(b.travellers).filter(n => !others.has(personKey(n))) }, ...extra]   // the booking's own mail: whoever isn't on another ticket
    .filter(x => x.message_id && x.account)
  const url = (x: TicketRef) => `api/attachment?account=${encodeURIComponent(x.account!)}&id=${encodeURIComponent(x.message_id!)}&n=${x.ticket! + 1}`
  const hasTicket = (x: TicketRef) => x.ticket !== null && x.ticket !== undefined
  const viewer = open && <Lightbox src={open} name="ticket.pdf" onClose={() => setOpen(null)} />
  const link = 'text-fjord hover:underline'
  if (rows.length <= 1) return <>{rows[0] && hasTicket(rows[0]) && <> · <button className={link} onClick={() => setOpen(url(rows[0]))}>Ticket</button></>}
    <MailButton m={b.source} />{viewer}</>
  const nice = (n: string) => people(b.travellers).find(m => personKey(m) === personKey(n)) || n
  return <> · <button className={link} onClick={() => setShown(!shown)} aria-expanded={shown} data-tickets="">
      Tickets and mails ({rows.length})<ChevronRight className={cn('ml-0.5 inline size-3.5 transition-transform', shown && 'rotate-90')} /></button>
    {shown && <span className="mt-1.5 grid w-fit max-w-full grid-cols-[minmax(0,auto)_auto_auto] items-center gap-x-4 gap-y-0.5" data-ticket-list="">
      {rows.map((x, i) => <Fragment key={i}>
        <span className="text-ink-2 truncate">{people(x.travellers).map(nice).join(', ') || 'Traveller ' + (i + 1)}</span>
        {hasTicket(x) ? <button className={cn(link, 'min-h-8')} onClick={() => setOpen(url(x))}>Ticket</button> : <span />}
        <button className={cn(link, 'min-h-8')} onClick={() => openMail({ account: x.account, message_id: x.message_id })}>Mail</button>
      </Fragment>)}</span>}
    {viewer}</>
}
const MailButton = ({ m }: { m?: MailRef }) => m?.message_id && m.account
  ? <> · <button className="text-fjord hover:underline" onClick={e => { e.preventDefault(); e.stopPropagation(); openMail(m) }}>Mail</button></> : null

export function TripsView() {
  const { ax } = useApp()
  const [v, setV] = useState<View | null>(null)
  const [err, setErr] = useState('')
  const [n, setN] = useState(0)
  const reload = () => setN(x => x + 1)
  const [adding, setAdding] = useState(false)
  useEffect(() => { get<View>('trips').then(x => { setV(x); setErr(''); cacheTrips(ticketUrls(x.trips)) })   // upcoming trips and tickets kept on this device
    .catch(e => { setErr(e.message); if (/owner/i.test(e.message)) cacheTrips(null) }) }, [n])
  useEffect(() => {                                   // while a scan runs: look again every 3 s
    if (!v?.scan.running && !v?.scan.reading) return
    const t = setTimeout(reload, 3000)
    return () => clearTimeout(t)
  }, [v])
  async function act(action: string, body: Record<string, unknown>, msg?: Msg, undo?: { action: string; body: Record<string, unknown> }) {
    try {
      const j = await post(action, body); reload()
      if (msg) toast(typeof msg === 'function' ? msg(j) : msg, undo ? { action: { label: 'Undo', onClick: () => { post(undo.action, undo.body).then(reload).catch(e => toast.error(e.message)) } } } : undefined)
    } catch (e: any) { toast.error(e.message) }
  }
  const [since, setSince] = useState('')
  useEffect(() => { if (v?.since && !since) setSince(v.since) }, [v?.since])  // eslint-disable-line react-hooks/exhaustive-deps
  async function scan() {
    try {
      await post('trip_scan', since ? { since } : {})
      toast(`Scanning your booking mails since ${since ? new Date(since + 'T12:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '12 months ago'} on the Mac mini…`)
      setTimeout(reload, 800)
    } catch (e: any) { toast.error(e.message) }
  }
  const sinceMin = localDay(new Date(Date.now() - 548 * 864e5)), sinceMax = localDay(new Date())
  if (!ax.apiOk && !v) return <p className="text-ink-3 text-sm">Trips need the Mac mini.</p>
  if (err) return <p className="text-ink-3 text-sm">{/owner/i.test(err) ? "Trips are the owner's own." : 'Trips: ' + err}</p>
  const running = !!v?.scan.running
  return <div className="space-y-4" data-trips-view="">
    <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
      <div className="min-w-[16rem] flex-1">
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><TripIcon className="size-5" />Trips</h1>
        <p className="text-muted-foreground text-sm">Your trips – coming up and past ones since the date you scan from – put together from the booking confirmations in your mail. Axella only reads – nothing is booked or changed.</p>
      </div>
      <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
        <Button size="pill" variant="outline" onClick={() => setAdding(true)} data-trip-add-mail="">Add a mail…</Button>
        <label className="text-ink-2 flex items-center gap-1.5 text-[12.5px]">Since
          <Input type="date" className="w-auto" value={since} min={sinceMin} max={sinceMax} onChange={e => setSince(e.target.value)} data-trip-since="" aria-label="Scan booking mails since" /></label>
        <Button size="pill" onClick={scan} disabled={running || (!!since && (since < sinceMin || since > sinceMax))} data-trip-scan="">{running ? <Loader2 className="animate-spin" /> : <Refresh />}{running ? 'Scanning…' : 'Scan mail'}</Button>
      </div>
    </div>
    {v && (v.scan.reading || v.scan.read_error || v.scan.last_read) && <p className={cn('-mt-2 text-[12.5px]', v.scan.read_error ? 'text-dawn' : 'text-ink-2')} data-trip-read-status="">
      {v.scan.reading ? <><Loader2 className="mr-1 inline size-3.5 animate-spin" />Claude is reading {v.scan.reading_n} booking mail{v.scan.reading_n === 1 ? '' : 's'} and their PDF tickets on the Mac mini – a few minutes…</>
        : v.scan.read_error ? 'Reading stopped: ' + v.scan.read_error
        : `Read by Claude: ${v.scan.last_read!.bookings} booking${v.scan.last_read!.bookings === 1 ? '' : 's'} found${v.scan.last_read!.placed ? `, ${v.scan.last_read!.placed} mail${v.scan.last_read!.placed === 1 ? '' : 's'} in your trips updated` : ''}${v.scan.last_read!.none ? `, ${v.scan.last_read!.none} without a booking` : ''}.`}</p>}
    {v && <p className="text-ink-3 -mt-2 text-[12.5px]" data-trip-scan-status="">
      {running ? `Reading booking mails since ${v.since ? new Date(v.since + 'T12:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '12 months ago'} on the Mac mini…`
        : v.scan.error ? <span className="text-dawn">The last scan stopped: {v.scan.error}</span>
        : v.scan.found !== null && v.scan.found !== undefined ? `Last scan: ${v.scan.read || 0} booking mails read, ${v.scan.found} upcoming booking${v.scan.found === 1 ? '' : 's'} to look at${v.scan.skipped ? ` – ${v.scan.skipped} from private contacts or a protected workplace left unread` : ''}.`
        : v.scanned ? `Last scanned ${new Date(v.scanned).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}.`
        : 'Not scanned yet. The scan reads booking confirmations (flights, hotels, trains, ferries, cars, tickets) – private contacts and protected workplaces are left out.'}</p>}
    {!v ? <p className="text-ink-3 text-sm">Loading…</p> : <>
      {v.suggested.length > 0 && <div className="space-y-3">
        <div className="ax-label">Suggested – confirm to keep</div>
        {v.suggested.map(t => <SuggestionFor key={t.id} t={t} trips={v.trips} act={act} />)}
      </div>}
      {(v.trips.length > 0 || v.past.length > 0 || !!v.past_suggested?.length) && <TripList v={v} act={act} reload={reload} />}
      {!v.trips.length && !v.past.length && !v.suggested.length && !v.past_suggested?.length && <Card className="text-ink-3 px-4 py-6 text-center text-sm">No upcoming trips yet. Scan your mail, and confirm the trips Axella finds.</Card>}
      {adding && <AddMail trips={[...v.trips, ...v.past]} onClose={() => setAdding(false)} act={act} />}
      {!!v.quotes?.length && <Planning list={v.quotes} />}
      {!!v.unsorted?.length && <ToSort list={v.unsorted} trips={[...v.trips, ...v.past]} act={act} reading={!!v.scan.reading} />}
      {!!v.removed?.length && <Removed list={v.removed} act={act} />}
    </>}
  </div>
}

function Suggestion({ t, trips, onConfirm, onDismiss, onAdd, onRead }: { t: Trip; trips: Trip[]; onConfirm: (title: string, keys: string[]) => void; onDismiss: () => void; onAdd: (to: string, keys: string[]) => void; onRead?: () => void }) {
  const [keys, setKeys] = useState(() => new Set(t.bookings.map(b => b.key)))
  const [title, setTitle] = useState(t.title)
  const [open, setOpen] = useState(false)
  return <Card className="overflow-hidden" data-trip-suggestion="">
    <div className="flex flex-wrap items-center gap-2 px-4 py-3">
      <span className="min-w-0 flex-1"><span className="block font-medium">{t.title}</span>
        <span className="text-ink-3 font-mono text-[12px]">{span(t)} · {t.bookings.length} booking{t.bookings.length === 1 ? '' : 's'} found</span></span>
      <Button size="pill" variant="ghost" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? 'Hide' : 'Look at it'}<ChevronRight className={cn('transition-transform', open && 'rotate-90')} /></Button>
    </div>
    {open && <div className="space-y-2 border-t px-4 py-3">
      <label className="block text-sm"><span className="mb-1 block font-medium">Name</span><Input value={title} maxLength={120} onChange={e => setTitle(e.target.value)} /></label>
      <div className="divide-y rounded-md border">{t.bookings.map(b => <label key={b.key} className="flex min-h-11 items-start gap-3 px-3 py-2">
        <Checkbox className="mt-1" checked={keys.has(b.key)} onCheckedChange={v => setKeys(s => { const n = new Set(s); v ? n.add(b.key) : n.delete(b.key); return n })} />
        <BookingLine b={b} />
      </label>)}</div>
    </div>}
    <div className="flex flex-wrap gap-2 border-t px-4 py-2.5">
      <Button size="pill" disabled={!keys.size || !title.trim()} onClick={() => onConfirm(title.trim(), [...keys])} data-trip-confirm=""><Check />Confirm as a new trip</Button>
      {trips.length > 0 && <DropdownMenu>
        <DropdownMenuTrigger asChild><Button size="pill" variant="outline" disabled={!keys.size} data-trip-add-to=""><Plus />Add to a trip</Button></DropdownMenuTrigger>
        <DropdownMenuContent align="start">{trips.map(x => <DropdownMenuItem key={x.id} onSelect={() => onAdd(x.id, [...keys])}>{x.title} <span className="text-ink-3 ml-1 font-mono text-[11px]">{span(x)}</span></DropdownMenuItem>)}</DropdownMenuContent>
      </DropdownMenu>}
      {onRead && <Button size="pill" variant="ghost" onClick={onRead} data-trip-read-suggestion="">Read with Claude</Button>}
      <Button size="pill" variant="ghost" onClick={onDismiss}><X />Not a trip</Button>
    </div>
  </Card>
}

function BookingLine({ b }: { b: Booking }) {
  return <span className="min-w-0 flex-1 text-sm">
    <span className="flex flex-wrap items-baseline gap-x-2">
      <span className="text-ink-3 font-mono text-[12px]">{day(b.start)}{hm(b.start) && hm(b.start) !== '00:00' ? ' ' + hm(b.start) : ''}</span>
      <span className="font-medium">{b.title || KIND[b.kind]}</span>
      {b.confidence === 'check' && <Badge variant="secondary" title="Found in the text, not in the booking's own data – check the dates">check</Badge>}
    </span>
    <span className="text-ink-3 block text-[12.5px]">{[KIND[b.kind], b.place, b.provider, b.ref && 'ref ' + b.ref].filter(Boolean).join(' · ')}
      <MailButton m={b.source} /></span>
  </span>
}

function TripCard({ t, act, others = [], reload, calChoice }: { t: Trip; act: (a: string, b: Record<string, unknown>, m?: Msg, u?: { action: string; body: Record<string, unknown> }) => void; others?: Trip[]; reload: () => void; calChoice?: Record<string, string> }) {
  const { ax } = useApp()
  const [calFor, setCalFor] = useState<{ keys?: string[] } | null>(null)
  const slow = async (a: string, body: Record<string, unknown>, msg: string) => { try { await ax.act(a, body, []); toast(msg); reload() } catch (e: any) { toast.error(e.message) } }
  const [renaming, setRenaming] = useState(false)
  const [merging, setMerging] = useState<Trip | null>(null)
  const [splitting, setSplitting] = useState(false)
  const [adding, setAdding] = useState(false)
  const [title, setTitle] = useState(t.title)
  const [armed, setArmed] = useState(false)
  const [addMail, setAddMail] = useState(false)
  type Edit = { key: string; name: string; kind: string; day: string; time: string; until: string; untilTime: string }
  const [naming, setNaming] = useState<Edit | null>(null)   // editing one booking: name, day, time, until
  const edit = (b: Booking): Edit => ({ key: b.key, name: b.title || '', kind: b.kind, day: b.start.slice(0, 10), time: hm(b.start) === '00:00' ? '' : hm(b.start),
    until: (b.end || b.start).slice(0, 10), untilTime: b.end && hm(b.end) !== '00:00' ? hm(b.end) : '' })
  const byDay: [string, Booking[]][] = []
  // a flight booked as a return trip ("18 nov – 22 nov") also shows on its last day, the route turned round
  const legs: Booking[] = t.bookings.flatMap(b => {
    const m = /^Flight · (.+) → (.+)$/.exec(b.title || '')
    // (only the rules' own "Copenhagen → Berlin, 3–7 Mar" – a flight Claude read ends when it lands, maybe the next day)
    return b.kind === 'flight' && (b.confidence === 'check' || b.confidence === 'manual') && b.end && b.end.slice(0, 10) !== b.start.slice(0, 10)
      ? [b, { ...b, key: b.key + '-back', start: b.end, title: m ? `Flight · ${m[2]} → ${m[1]}` : 'Return flight', place: '' }] : [b]
  })
  for (const b of legs.sort((x, y) => x.start.localeCompare(y.start))) {
    const k = b.start.slice(0, 10); const l = byDay[byDay.length - 1]
    if (l && l[0] === k) l[1].push(b); else byDay.push([k, [b]])
  }
  const remove = () => {
    if (!armed) { setArmed(true); setTimeout(() => setArmed(false), 3000); return }
    act('trip_remove', { id: t.id, title: t.title }, `${t.title} removed – Restore from the Activity log`, { action: 'trip_restore', body: { id: t.id } })
  }
  return <Card className="overflow-hidden" data-trip="">
    <div className="flex items-center gap-2 border-b px-4 py-3">
      {renaming ? <form className="flex min-w-0 flex-1 gap-2" onSubmit={e => { e.preventDefault(); act('trip_rename', { id: t.id, title }, 'Renamed'); setRenaming(false) }}>
          <Input value={title} maxLength={120} onChange={e => setTitle(e.target.value)} autoFocus /><Button size="pill" type="submit" disabled={!title.trim()}>Save</Button></form>
        : <span className="min-w-0 flex-1"><span className="flex items-center gap-2 font-semibold">{tctx(t) && <span className="size-2 shrink-0 rounded-full" title={tctx(t) === 'work' ? 'Work trip' : 'Private trip'}
              style={{ background: tctx(t) === 'work' ? 'var(--ax-work)' : 'var(--ax-private)' }} />}{t.title}</span>
            <span className="text-ink-3 font-mono text-[12px]">{span(t)} · {t.bookings.length} booking{t.bookings.length === 1 ? '' : 's'}</span>
            <TripProjects tripId={t.id} /><TripPassportWarning tripId={t.id} /></span>}
      {!renaming && <Button size="pill" variant="outline" onClick={() => printPlan([t], t.title)} data-trip-pdf="" aria-label={'Export ' + t.title + ' as PDF'}><Save /><span className="max-sm:sr-only">PDF</span></Button>}
      {!renaming && <Button size="pill" variant="outline" onClick={() => emailPlan(t)} data-trip-email="" aria-label={'Email the plan for ' + t.title}><Mail /><span className="max-sm:sr-only">Email</span></Button>}
      <DropdownMenu>
        <DropdownMenuTrigger className="text-ink-3 hover:text-ink rounded-md p-2" aria-label="More"><MoreHorizontal className="size-4" /></DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => { setTitle(t.title); setRenaming(true) }}><Pencil />Rename</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => act('trip_ctx', { id: t.id, ctx: tctx(t) === 'work' ? 'private' : 'work', title: t.title }, tctx(t) === 'work' ? 'Now a private trip' : 'Now a work trip')}>
            {tctx(t) === 'work' ? <Home /> : <Briefcase />}{tctx(t) === 'work' ? 'Make it a private trip' : 'Make it a work trip'}</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => act('trip_read', { message_ids: [...new Set(t.bookings.filter(b => b.confidence !== 'read' && b.confidence !== 'data').map(b => b.source?.message_id).filter(Boolean))], title: t.title },
            'Claude is reading this trip\'s booking mails – a few minutes')} disabled={!t.bookings.some(b => b.confidence !== 'read' && b.confidence !== 'data' && b.source?.message_id)}><Check />Read the mails with Claude</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setAddMail(true)}><Plus />Add a mail…</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setAdding(true)} data-trip-add-item=""><Plus />Add an item by hand…</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setCalFor({})} data-trip-cal-open="">Add to calendar…</DropdownMenuItem>
          <DropdownMenuItem disabled={t.bookings.length < 2} onSelect={() => setSplitting(true)} data-trip-split-open="">Split…</DropdownMenuItem>
          {others.map(x => <DropdownMenuItem key={'m' + x.id} onSelect={() => setMerging(x)}>Merge with {x.title}…</DropdownMenuItem>)}
          <DropdownMenuItem onSelect={e => { e.preventDefault(); remove() }} className={cn(armed && 'text-danger')}><Trash2 />{armed ? 'Tap again to remove' : 'Remove trip'}</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
    {t.new && t.new.length > 0 && <NewBookings t={t} act={act} />}
    {addMail && <AddMail trips={[t]} tripId={t.id} onClose={() => setAddMail(false)} act={act} />}
    {merging && <MergeDialog t={t} other={merging} onClose={() => setMerging(null)} reload={reload} />}
    {splitting && <SplitDialog t={t} onClose={() => setSplitting(false)} reload={reload} />}
    {adding && <ItemDialog t={t} onClose={() => setAdding(false)} reload={reload} />}
    {calFor && <CalendarDialog tripId={t.id} title={t.title} world={tctx(t)} keys={calFor.keys} last={calChoice} onClose={() => setCalFor(null)} onDone={reload} />}
    <div className="divide-y">{byDay.map(([d, list]) => <div key={d} className="px-4 py-2.5">
      <div className="text-[13px] font-semibold">{day(d)}</div>
      <div className="mt-1 space-y-2">{list.map(b => <div key={b.key} className="flex gap-3">
        <span className="text-ink-3 w-16 shrink-0 font-mono text-[12px] leading-5">{hm(b.start) && hm(b.start) !== '00:00' ? hm(b.start) : '—'}<span className="block text-[10.5px]">{hm(b.start) !== '00:00' ? tz(b.start) : ''}</span></span>
        <span className={cn('min-w-0 flex-1 text-sm', b.status === 'cancelled' && 'opacity-60')}>{naming?.key === b.key
            ? <form className="space-y-2 rounded-md border p-2" data-booking-edit="" onKeyDown={e => e.key === 'Escape' && setNaming(null)} onSubmit={e => {
                e.preventDefault()
                act('trip_booking_edit', { id: t.id, key: b.key, title: naming.name, name: naming.name, kind: naming.kind, day: naming.day, time: naming.time, until: naming.until, until_time: naming.untilTime }, 'Saved')
                setNaming(null)
              }}>
                <div className="flex gap-2">
                  <NativeSelect className="w-auto shrink-0" aria-label="Kind of booking" value={naming.kind} onChange={e => setNaming({ ...naming, kind: e.target.value })}>
                    {KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</NativeSelect>
                  <Input value={naming.name} maxLength={120} aria-label="Name of the booking" onChange={e => setNaming({ ...naming, name: e.target.value })} autoFocus /></div>
                <div className="grid grid-cols-[3.5rem_minmax(0,1fr)_minmax(0,7rem)] items-center gap-2 text-[12.5px]">
                  <span>{naming.kind === 'hotel' ? 'From' : 'Day'}</span>
                  <Input type="date" className="w-full" aria-label={b.kind === 'hotel' ? 'From' : 'Day'} value={naming.day} onChange={e => setNaming({ ...naming, day: e.target.value, until: shiftDay(naming.until, naming.day, e.target.value) })} />
                  <Input type="time" className="w-full" aria-label="Time (optional)" value={naming.time} onChange={e => setNaming({ ...naming, time: e.target.value })} />
                  <span>{naming.kind === 'hotel' ? 'Until' : 'To'}</span>
                  <Input type="date" className="w-full" aria-label={b.kind === 'hotel' ? 'Until' : 'To'} value={naming.until} min={naming.day} onChange={e => setNaming({ ...naming, until: e.target.value })} />
                  <Input type="time" className="w-full" aria-label="End time (optional)" value={naming.untilTime} onChange={e => setNaming({ ...naming, untilTime: e.target.value })} />
                </div>
                <p className="text-ink-3 text-[12px]">Times are the place's own local time{tz(b.start) ? ` (${tz(b.start)})` : ''}. Leave the time empty if you don't know it.</p>
                <div className="flex gap-2"><Button size="pill" type="submit" disabled={!naming.name.trim() || !naming.day || naming.until < naming.day}>Save</Button>
                  <Button size="pill" variant="ghost" type="button" onClick={() => setNaming(null)}>Cancel</Button></div></form>
            : <span className={cn('font-medium', b.status === 'cancelled' && 'line-through')}>{b.title || KIND[b.kind]}</span>}{b.status === 'cancelled' && <Badge variant="secondary" className="ml-1.5">cancelled</Badge>}{b.confidence === 'check' && <Badge variant="secondary" className="ml-1.5">check</Badge>}
          {(b.notes || b.address) && <span className="text-ink-2 block text-[12.5px]">{[b.notes, b.address].filter(Boolean).join(' · ')}</span>}
          <span className="text-ink-3 block text-[12.5px]">{[KIND[b.kind], b.kind === 'hotel' && b.end ? 'until ' + day(b.end) : '', b.place, b.provider, b.ref && 'ref ' + b.ref, people(b.travellers).join(', ')].filter(Boolean).join(' · ')}
            <Sources b={b} /></span>
          <BookingLive tripId={t.id} b={b} edit={(a, body, msg) => editTrip(a, body, msg, reload)} act={slow} /></span>
        {!b.key.endsWith('-back') && <DropdownMenu>
          <DropdownMenuTrigger className="text-ink-3 hover:text-ink -my-2 grid size-11 shrink-0 place-items-center rounded-md" aria-label={'More for ' + (b.title || 'booking')}><MoreHorizontal className="size-4" /></DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => setNaming(edit(b))}><Pencil />Edit…</DropdownMenuItem>
            {!b.cal && b.status !== 'cancelled' && <DropdownMenuItem onSelect={() => setCalFor({ keys: [b.key] })}>Add to calendar…</DropdownMenuItem>}
            <DropdownMenuItem data-trip-cancel="" onSelect={() => editTrip('trip_cancel', { id: t.id, key: b.key, on: b.status !== 'cancelled', title: b.title },
              b.status === 'cancelled' ? 'Not cancelled any more' : 'Marked cancelled – left out of the calendar, the Today card and alerts', reload)}>
              <X />{b.status === 'cancelled' ? 'Not cancelled' : 'Mark cancelled'}</DropdownMenuItem>
            {b.by_hand && <DropdownMenuItem disabled={t.bookings.length < 2} onSelect={() => editTrip('trip_item_remove', { id: t.id, key: b.key, title: b.title }, 'Removed – Undo, or Restore from the Activity log', reload)}><Trash2 />Remove</DropdownMenuItem>}
            <DropdownMenuItem disabled={t.bookings.length < 2} onSelect={() => act('trip_void', { id: t.id, key: b.key, title: b.title }, 'Voided – Restore under "Voided" in this trip',
              { action: 'trip_unvoid', body: { id: t.id, key: b.key } })}><X />{t.bookings.length < 2 ? 'Void (the only booking – remove the trip)' : 'Void – duplicate or wrong'}</DropdownMenuItem>
            {others.map(x => <DropdownMenuItem key={x.id} onSelect={() => act('trip_move_booking', { id: t.id, key: b.key, to: x.id, title: b.title }, 'Moved to ' + x.title,
              { action: 'trip_move_booking', body: { id: x.id, key: b.key, to: t.id } })}>Move to {x.title}</DropdownMenuItem>)}
          </DropdownMenuContent>
        </DropdownMenu>}
      </div>)}</div>
    </div>)}</div>
    <TripPlanning t={t} reload={reload} />
    <Checklist t={t} reload={reload} />
    <div className="border-t p-3"><LinkedNotes link={{ kind: 'trip', ref: t.id, label: t.title, date: String(t.start || '').slice(0, 10) }} /></div>
    {t.voided && t.voided.length > 0 && <Voided t={t} act={act} />}
  </Card>
}

/** Bookings taken off a trip: by Void, or as a duplicate of a booking Claude read (the same flight or stay). */
function Voided({ t, act }: { t: Trip; act: (a: string, b: Record<string, unknown>, m?: Msg) => void }) {
  const [open, setOpen] = useState(false)
  const list = t.voided || []
  return <div className="border-t" data-trip-voided="">
    <button className="text-ink-3 hover:text-ink flex min-h-11 w-full items-center gap-2 px-4 text-left text-[12.5px]" onClick={() => setOpen(!open)} aria-expanded={open}>
      <span className="flex-1">Voided ({list.length}) – duplicates and bookings you voided</span><ChevronRight className={cn('size-4 transition-transform', open && 'rotate-90')} /></button>
    {open && <div className="divide-y border-t">{list.map(b => <div key={b.key} className="flex items-center gap-2 px-4 py-2 text-sm">
      <span className="min-w-0 flex-1"><span className="text-ink-2 block truncate line-through">{b.title || KIND[b.kind]}</span>
        <span className="text-ink-3 block text-[12px]">{[day(b.start.slice(0, 10)), b.voided === 'duplicate' ? 'same as a booking Claude read' : 'voided by you', b.ref && 'ref ' + b.ref].filter(Boolean).join(' · ')} <MailButton m={b.source} /></span></span>
      <Button size="pill" variant="outline" onClick={() => act('trip_unvoid', { id: t.id, key: b.key, title: b.title }, 'Back in the trip')}>Restore</Button>
    </div>)}</div>}
  </div>
}


/* ---------- Export as PDF: a plain travel plan, printed (the share sheet's "Save as PDF" / "Save to Files") ---------- */
const esc = (x: unknown) => String(x ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!))
export function printPlan(trips: Trip[], heading: string) {
  const row = (b: Booking) => {
    const time = hm(b.start) && hm(b.start) !== '00:00' ? `${hm(b.start)} <small>${esc(tz(b.start))}</small>` : '–'
    const until = b.end && b.end.slice(0, 10) !== b.start.slice(0, 10) ? (b.kind === 'hotel' ? 'until ' : 'to ') + day(b.end) + (b.kind !== 'hotel' && hm(b.end) && hm(b.end) !== '00:00' ? ' ' + hm(b.end) : '') : ''
    const meta = [KIND[b.kind], until, b.place, b.provider, b.ref && 'ref ' + b.ref, people(b.travellers).join(', ')].filter(Boolean).map(esc).join(' · ')
    return `<tr><td class="t">${time}</td><td><b>${esc(b.title || KIND[b.kind])}</b>${b.status === 'cancelled' ? ' <i>(cancelled)</i>' : ''}
      ${b.notes || b.address ? `<div>${esc([b.notes, b.address].filter(Boolean).join(' · '))}</div>` : ''}<div class="m">${meta}</div></td></tr>`
  }
  const trip = (t: Trip) => {
    const days: [string, Booking[]][] = []
    for (const b of [...t.bookings].sort((x, y) => x.start.localeCompare(y.start))) {
      const k = b.start.slice(0, 10); const l = days[days.length - 1]
      if (l && l[0] === k) l[1].push(b); else days.push([k, [b]])
    }
    return `<section><h2>${esc(t.title)}</h2><p class="m">${esc(span(t))} · ${t.bookings.length} booking${t.bookings.length === 1 ? '' : 's'}</p>
      ${days.map(([d, bs]) => `<h3>${esc(day(d))}</h3><table>${bs.map(row).join('')}</table>`).join('')}</section>`
  }
  const el = document.createElement('div')
  el.setAttribute('data-print-doc', '')
  el.className = 'ax-plan'
  el.innerHTML = `<style>.ax-plan{display:none;font:11pt/1.4 system-ui,sans-serif;color:#111;padding:0 4mm}.ax-plan h1{font-size:18pt;margin:0 0 2mm}
    .ax-plan h2{font-size:14pt;margin:8mm 0 1mm;break-after:avoid}.ax-plan h3{font-size:11pt;margin:4mm 0 1mm;border-bottom:1px solid #ccc;break-after:avoid}
    .ax-plan table{width:100%;border-collapse:collapse}.ax-plan td{vertical-align:top;padding:1.5mm 0;break-inside:avoid}.ax-plan td.t{width:22mm;font-variant-numeric:tabular-nums}
    .ax-plan small,.ax-plan .m{color:#555;font-size:9pt}.ax-plan section{break-inside:auto}
    @media print{.ax-plan{display:block}}</style>
    <h1>${esc(heading)}</h1><p class="m">Travel plan from Axella · ${esc(new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }))} · times are local</p>${trips.map(trip).join('')}`
  document.body.appendChild(el)
  const done = () => { el.remove(); window.removeEventListener('afterprint', done) }
  window.addEventListener('afterprint', done)
  setTimeout(() => { window.print(); setTimeout(done, 60e3) }, 50)
}


/** a new first day moves the last day with it (a 2-night stay stays 2 nights) */
const shiftDay = (until: string, from: string, to: string) => {
  const d = (x: string) => new Date(x + 'T12:00:00Z').getTime()
  if (!to || !from || !until) return until || to
  return new Date(d(until) + d(to) - d(from)).toISOString().slice(0, 10)
}
/** The plan as plain text – for "Email" (Axella's composer). */
export function planText(t: Trip) {
  const lines = [t.title, span(t), '']
  let last = ''
  for (const b of [...t.bookings].filter(b => b.status !== 'cancelled').sort((x, y) => x.start.localeCompare(y.start))) {
    const d = b.start.slice(0, 10)
    if (d !== last) { lines.push((last ? '\n' : '') + day(d)); last = d }
    const time = hm(b.start) && hm(b.start) !== '00:00' ? `${hm(b.start)} (${tz(b.start)})` : '–'
    const until = b.kind === 'hotel' && b.end && b.end.slice(0, 10) !== d ? 'until ' + day(b.end) : ''
    lines.push(`  ${time}  ${b.title || KIND[b.kind]}`)
    const meta = [b.notes, b.address, until, b.ref && 'ref ' + b.ref, people(b.travellers).join(', ')].filter(Boolean).join(' · ')
    if (meta) lines.push('         ' + meta)
  }
  lines.push('', 'Times are local. From Axella.')
  return lines.join('\n')
}
/** "Email": Axella's own composer opens with the plan – you pick who it goes to, and nothing is sent until you send it */
export function emailPlan(t: Trip) {
  openCompose({ subject: 'Travel plan: ' + t.title, body: planText(t) })
}


/** a suggested trip with its actions: Confirm, Add to a trip, Not a trip */
function SuggestionFor({ t, trips, act }: { t: Trip; trips: Trip[]; act: (a: string, b: Record<string, unknown>, m?: Msg, u?: { action: string; body: Record<string, unknown> }) => void }) {
  // the mails the rules read but Claude hasn't: reading them gives the real flights, times and travellers
  const unread = [...new Set(t.bookings.filter(b => b.confidence === 'check' && b.source?.message_id).map(b => b.source!.message_id as string))]
  return <Suggestion t={t} trips={trips} onAdd={(to, keys) => act('trip_suggest_add', { id: t.id, to, bookings: keys, title: trips.find(x => x.id === to)?.title || '' }, 'Added to ' + (trips.find(x => x.id === to)?.title || 'the trip'))}
    onConfirm={(title, keys) => act('trip_confirm', { id: t.id, title, bookings: keys }, `${title} is in Trips`)}
    onDismiss={() => act('trip_dismiss', { id: t.id, title: t.title }, 'Not a trip – it won\'t be suggested again', { action: 'trip_undismiss', body: { keys: t.bookings.map(b => b.key) } })}
    onRead={unread.length ? () => act('trip_read', { message_ids: unread, title: t.title }, 'Claude is reading these booking mails – a few minutes') : undefined} />
}

/** work or private: what you set, else the accounts its mails came in */
const tctx = (t: Trip) => t.ctx || t.ctx_auto || null
type When = 'current' | 'upcoming' | 'past'
/** Your trips by when: on now (today between its first and last day), coming, or over – the newest past trips first. */
function TripList({ v, act, reload }: { v: View; act: (a: string, b: Record<string, unknown>, m?: Msg) => void; reload: () => void }) {
  const { ctx } = useApp()
  const today = localDay(new Date())
  const inCtx = (t: Trip) => ctx === 'all' || !tctx(t) || tctx(t) === ctx      // the Work / Private switch at the top
  const groups: Record<When, Trip[]> = {
    current: v.trips.filter(t => t.start.slice(0, 10) <= today && inCtx(t)),
    upcoming: v.trips.filter(t => t.start.slice(0, 10) > today && inCtx(t)),
    past: v.past.filter(inCtx),
  }
  const pastSug = v.past_suggested || []
  const [when, setWhen] = useState<When>(() => groups.current.length ? 'current' : groups.upcoming.length || !(groups.past.length || pastSug.length) ? 'upcoming' : 'past')
  const list = groups[when]
  const label: Record<When, string> = { current: 'Current', upcoming: 'Upcoming', past: 'Past' }
  return <div className="space-y-3" data-trip-list="">
    <ToggleGroup type="single" value={when} onValueChange={(x: string) => x && setWhen(x as When)} aria-label="Which trips">
      {(['current', 'upcoming', 'past'] as When[]).map(w => <ToggleGroupItem key={w} value={w} data-trip-when={w}>{label[w]} ({groups[w].length + (w === 'past' ? pastSug.length : 0)})</ToggleGroupItem>)}
    </ToggleGroup>
    {when === 'past' && pastSug.length > 0 && <div className="space-y-3"><div className="ax-label">Found in your mail – confirm to keep</div>
      {pastSug.map(t => <SuggestionFor key={t.id} t={t} trips={v.past} act={act} />)}</div>}
    {list.length ? list.map(t => <TripCard key={t.id} t={t} act={act} reload={reload} calChoice={v.cal_choice} others={when === 'past' ? [] : v.trips.filter(x => x.id !== t.id)} />)
      : !(when === 'past' && pastSug.length) && <Card className="text-ink-3 px-4 py-6 text-center text-sm">{when === 'current' ? 'No trip on right now.' : when === 'upcoming' ? 'No upcoming trips.' : 'No past trips yet.'}</Card>}
  </div>
}

/** Travel mails Axella couldn't read: each one can be put in a trip by hand (on the day you give), become a new trip, or
    be marked "Void". Nothing stays unsorted for ever. */
function ToSort({ list, trips, act, reading }: { list: Unread[]; trips: Trip[]; act: (a: string, b: Record<string, unknown>, m?: Msg, u?: { action: string; body: Record<string, unknown> }) => void; reading?: boolean }) {
  const [open, setOpen] = useState(true)
  const [placing, setPlacing] = useState<Unread | null>(null)
  return <Card className="overflow-hidden" data-trip-unread="">
    <button className="flex w-full items-center gap-2 px-4 py-2.5 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
      <span className="ax-label flex-1">To sort – travel mails Axella couldn't read ({list.length})</span><ChevronRight className={cn('text-ink-3 size-4 transition-transform', open && 'rotate-90')} /></button>
    {open && <div className="bg-fjord-soft flex flex-wrap items-center gap-2 border-t px-4 py-2 text-[13px]">
      <span className="min-w-0 flex-1">Let Claude read these mails and their PDF tickets – flights with times, stays, passengers. Their content goes to Anthropic for this; it shows under What leaves my home.</span>
      <Button size="pill" disabled={reading} onClick={() => act('trip_read', { message_ids: list.map(u => u.message_id).filter(Boolean), title: list.length + ' mails' }, 'Claude is reading them – the results appear here in a few minutes')} data-trip-read-all="">
        {reading ? <Loader2 className="animate-spin" /> : <Check />}Read all {list.length} with Claude</Button>
    </div>}
    {open && <div className="divide-y border-t">{list.map((u, i) => <div key={u.message_id || i} className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm" data-to-sort="">
      <span className="min-w-0 flex-1"><span className="block truncate">{u.subject || '(no subject)'}</span>
        <span className="text-ink-3 text-[12.5px]">{[u.from, u.date ? new Date(u.date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : ''].filter(Boolean).join(' · ')}<MailButton m={u} /></span></span>
      <Button size="pill" variant="ghost" disabled={reading} onClick={() => act('trip_read', { message_ids: [u.message_id], title: u.subject || '' }, 'Claude is reading it – a minute or two')}>Read with Claude</Button>
      <Button size="pill" variant="outline" onClick={() => setPlacing(u)}><TripIcon />Put in a trip</Button>
      <Button size="pill" variant="ghost" onClick={() => act('trip_mail_not_travel', { message_id: u.message_id, title: u.subject || '' }, 'Void – off the list',
        { action: 'trip_undismiss', body: { keys: ['m:' + u.message_id] } })}><X />Void</Button>
    </div>)}</div>}
    {placing && <PlaceMail u={placing} trips={trips} onClose={() => setPlacing(null)} onDone={(action, body, msg) => { act(action, body, msg); setPlacing(null) }} />}
  </Card>
}

const KINDS: [string, string][] = [['flight', 'Flight'], ['hotel', 'Stay'], ['train', 'Train'], ['ferry', 'Ferry'], ['car', 'Car'], ['transfer', 'Transfer'],
  ['ticket', 'Ticket / tour'], ['restaurant', 'Table'], ['booking', 'Other']]

function PlaceMail({ u, trips, onClose, onDone, tripId, found }: { u: Unread; trips: Trip[]; onClose: () => void; onDone: (a: string, b: Record<string, unknown>, m: string) => void; tripId?: string; found?: boolean }) {
  const [trip, setTrip] = useState(tripId || trips[0]?.id || 'new')
  const [name, setName] = useState('')
  const [date, setDate] = useState(() => trips[0]?.start.slice(0, 10) || '')
  const [end, setEnd] = useState('')
  const [kind, setKind] = useState(/ticket|e-?document|flight|fly/i.test(u.subject || '') ? 'flight' : /hotel|stay|camp|lodge/i.test(u.subject || '') ? 'hotel' : 'booking')
  const [title, setTitle] = useState(u.subject || '')
  const ok = !!date && !!title.trim() && (trip !== 'new' || !!name.trim())
  const save = () => onDone(trip === 'new' ? 'trip_mail_new' : 'trip_mail_add',
    { id: trip === 'new' ? undefined : trip, trip_title: name.trim(), message_id: u.message_id, date, end: end || undefined, kind, title: title.trim(),
      ...(found ? { mail: { account: u.account, message_id: u.message_id, subject: u.subject, date: u.date, from: u.from } } : {}) },
    trip === 'new' ? `${name.trim()} is in Trips` : 'Put in the trip')
  return <Dialog open onOpenChange={o => !o && onClose()}>
    <DialogContent className="sm:w-[min(480px,92vw)]">
      <div className="space-y-3 p-5 text-sm" data-place-mail="">
        <DialogTitle className="text-lg font-semibold">Put in a trip</DialogTitle>
        <p className="text-ink-3 -mt-1 text-[13px]"><span className="block truncate">{u.subject}</span><button className="text-fjord hover:underline" onClick={() => openMail(u)}>Read the mail</button></p>
        <label className="block"><span className="mb-1 block font-medium">Trip</span>
          <NativeSelect value={trip} onChange={e => { setTrip(e.target.value); const t = trips.find(x => x.id === e.target.value); if (t && !date) setDate(t.start.slice(0, 10)) }}>
            {trips.map(t => <option key={t.id} value={t.id}>{t.title} ({span(t)})</option>)}<option value="new">New trip…</option></NativeSelect></label>
        {trip === 'new' && <label className="block"><span className="mb-1 block font-medium">Name of the new trip</span><Input value={name} maxLength={120} placeholder="e.g. Lisbon and Porto" onChange={e => setName(e.target.value)} autoFocus /></label>}
        <div className="grid grid-cols-2 gap-2">
          <label className="block"><span className="mb-1 block font-medium">Day</span><Input type="date" value={date} onChange={e => setDate(e.target.value)} /></label>
          <label className="block"><span className="mb-1 block font-medium">Until <span className="text-ink-3 font-normal">(optional)</span></span><Input type="date" value={end} min={date} onChange={e => setEnd(e.target.value)} /></label>
        </div>
        <div className="grid grid-cols-[8rem_1fr] gap-2">
          <label className="block"><span className="mb-1 block font-medium">Kind</span><NativeSelect value={kind} onChange={e => setKind(e.target.value)}>{KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</NativeSelect></label>
          <label className="block"><span className="mb-1 block font-medium">What</span><Input value={title} maxLength={160} onChange={e => setTitle(e.target.value)} /></label>
        </div>
        <div className="flex justify-end gap-2 pt-1"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={!ok} onClick={save} data-place-save="">Put in the trip</Button></div>
      </div>
    </DialogContent>
  </Dialog>
}

/** Bookings a scan found inside this trip's dates: you pick which belong – nothing is added by itself. */
function NewBookings({ t, act }: { t: Trip; act: (a: string, b: Record<string, unknown>, m?: Msg, u?: { action: string; body: Record<string, unknown> }) => void }) {
  const [keys, setKeys] = useState(() => new Set<string>())
  const list = t.new || []
  return <div className="bg-fjord-soft space-y-2 px-4 py-2.5 text-sm" data-trip-new="">
    <div className="font-medium">{list.length} more booking{list.length === 1 ? '' : 's'} in this trip's dates – part of it?</div>
    <div className="bg-card divide-y rounded-md border">{list.map(b => <label key={b.key} className="flex min-h-11 items-start gap-3 px-3 py-2">
      <Checkbox className="mt-1" checked={keys.has(b.key)} onCheckedChange={v => setKeys(s => { const n = new Set(s); v ? n.add(b.key) : n.delete(b.key); return n })} />
      <BookingLine b={b} />
    </label>)}</div>
    <div className="flex flex-wrap gap-2">
      <Button size="pill" disabled={!keys.size} onClick={() => act('trip_apply_new', { id: t.id, keys: [...keys], title: t.title }, 'Added to the trip')}><Check />Add to this trip</Button>
      <Button size="pill" variant="ghost" disabled={!keys.size} onClick={() => act('trip_not_part', { id: t.id, keys: [...keys], title: t.title }, 'Not offered to this trip again', { action: 'trip_part_again', body: { id: t.id, keys: [...keys] } })}><X />Not part of this trip</Button>
    </div>
  </div>
}

interface Found { private?: boolean; subject: string; from_name?: string; from_address?: string; date?: string; message_id?: string | null; account?: string | null; has_attachments?: boolean }
/** "Add a mail…": search all mail on the Mac mini for a booking the scan didn't find, read it, and put it in a trip. */
export function AddMail({ trips, tripId, onClose, act }: { trips: Trip[]; tripId?: string; onClose: () => void; act: (a: string, b: Record<string, unknown>, m?: Msg) => void }) {
  const [q, setQ] = useState('')
  const [res, setRes] = useState<{ items: Found[]; error?: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [pick, setPick] = useState<Unread | null>(null)
  async function search(e?: React.FormEvent) {
    e?.preventDefault()
    if (q.trim().length < 2) return
    setBusy(true)
    try { setRes(await get<{ items: Found[]; error?: string }>('mail_search?q=' + encodeURIComponent(q.trim()) + '&limit=40')) }
    catch (x: any) { setRes({ items: [], error: x.message }) } finally { setBusy(false) }
  }
  if (pick) return <PlaceMail u={pick} trips={trips} tripId={tripId} found onClose={() => setPick(null)} onDone={(a, b, m) => { act(a, b, m); onClose() }} />
  return <Dialog open onOpenChange={o => !o && onClose()}>
    <DialogContent className="max-h-[85dvh] overflow-y-auto sm:w-[min(560px,94vw)]">
      <div className="space-y-3 p-5 text-sm" data-add-mail="">
        <DialogTitle className="text-lg font-semibold">Add a mail to a trip</DialogTitle>
        <p className="text-ink-3 -mt-1 text-[13px]">Search all mail on the Mac mini – a confirmation, an e-ticket, a voucher. Mail with a private contact can't be added.</p>
        <form onSubmit={search} className="flex gap-2"><Input value={q} onChange={e => setQ(e.target.value)} placeholder="e.g. Acme Air, booking reference, hotel name" autoFocus />
          <Button type="submit" disabled={busy || q.trim().length < 2}>{busy ? <Loader2 className="animate-spin" /> : null}Search</Button></form>
        {res?.error && <p className="text-dawn text-[13px]">{res.error}</p>}
        {res && !res.error && !res.items.length && <p className="text-ink-3 text-[13px]">Nothing found.</p>}
        {!!res?.items.length && <div className="divide-y rounded-md border">{res.items.map((f, i) => {
          const u: Unread = { account: f.account || undefined, message_id: f.message_id, subject: f.subject, date: f.date, from: f.from_name || f.from_address, why: '' }
          const can = !f.private && !!f.message_id && !!f.account
          return <div key={(f.message_id || '') + i} className="flex items-center gap-2 px-3 py-2" data-found="">
            <span className="min-w-0 flex-1"><span className="block truncate">{f.private ? 'A mail with a private contact' : f.subject || '(no subject)'}</span>
              <span className="text-ink-3 text-[12.5px]">{[f.private ? '' : u.from, f.date ? new Date(f.date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '', f.has_attachments ? 'attachment' : ''].filter(Boolean).join(' · ')}{can && <MailButton m={u} />}</span></span>
            {can && <Button size="pill" variant="outline" onClick={() => setPick(u)}>Add</Button>}
          </div>
        })}</div>}
      </div>
    </DialogContent>
  </Dialog>
}

/** Trips you removed (or that were emptied by moving their bookings): kept 50, Restore puts them back. */
function Removed({ list, act }: { list: NonNullable<View['removed']>; act: (a: string, b: Record<string, unknown>, m?: Msg) => void }) {
  const [open, setOpen] = useState(false)
  return <Card className="overflow-hidden" data-trips-removed="">
    <button className="flex w-full items-center gap-2 px-4 py-2.5 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
      <span className="ax-label flex-1">Removed trips ({list.length})</span><ChevronRight className={cn('text-ink-3 size-4 transition-transform', open && 'rotate-90')} /></button>
    {open && <div className="divide-y border-t">{list.map(r => <div key={r.id} className="flex items-center gap-2 px-4 py-2 text-sm">
      <span className="min-w-0 flex-1"><span className="block truncate">{r.title}</span>
        <span className="text-ink-3 font-mono text-[12px]">{span(r)} · {r.bookings} booking{r.bookings === 1 ? '' : 's'}</span></span>
      <Button size="pill" variant="outline" onClick={() => act('trip_restore', { id: r.id, title: r.title }, j => j.note ? `${r.title}: its booking${r.bookings === 1 ? ' is' : 's are'} ${j.note} – nothing to restore` : r.title + ' is back')}>Restore</Button>
    </div>)}</div>}
  </Card>
}

/** Quotes and enquiries Claude found (a hotel's price offer): planning, not bookings. */
function Planning({ list }: { list: Booking[] }) {
  return <Card className="overflow-hidden" data-trip-planning="">
    <div className="ax-label border-b px-4 py-2.5">Planning – quotes and enquiries</div>
    <div className="divide-y">{list.map(q => <div key={q.key} className="px-4 py-2 text-sm"><BookingLine b={q} /></div>)}</div>
  </Card>
}
