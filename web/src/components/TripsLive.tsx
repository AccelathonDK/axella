/* Trips v2, steps 3–5 (setup/trips.py): Add to calendar (on tap, kept in step only when you tap), a booking's live notes
   (an update waiting for Apply / Ignore, "Updated from …", check-in opening – estimated or the airline's own word,
   the calendar event that needs updating or removing), the Today card on travel days, and the offline copy of your
   upcoming trips and tickets on this device (owner only – the cache is cleared when a trip is past or removed, and on
   any other login). */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { CalendarPlus, Check, Copy, ExternalLink, Trip as TripIcon, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { NativeSelect } from '@/components/ui/input'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { cn } from '@/lib/utils'

export interface LBooking { key: string; kind: string; title: string; start: string; end: string; status?: string; number?: string; ref?: string
  place?: string; address?: string; provider?: string
  cal?: { id?: string; calendar?: string } | null; cal_stale?: 'changed' | 'cancelled'
  pending?: { by?: string; was?: Record<string, string>; now?: Record<string, string>; other_sender?: boolean; provider?: string } | null
  updated?: { by?: string; at?: string; was?: Record<string, string> } | null
  checkin_view?: { at: string; estimated: boolean } | null
  ticket?: number | null; tickets?: { account?: string; message_id?: string | null; ticket?: number | null }[]; source?: { account?: string; message_id?: string | null } }
interface Cal { title: string; source: string; can_modify: boolean; label: string; ctx: 'work' | 'private' | null }

const hm = (s?: string) => /T(\d\d:\d\d)/.exec(s || '')?.[1] || ''
const dayhm = (s?: string) => s ? `${new Date(s.slice(0, 10) + 'T12:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })} ${hm(s)}` : ''
const ticketUrl = (t: { account?: string; message_id: string; n: number }) => `api/attachment?account=${encodeURIComponent(t.account || 'iCloud')}&id=${encodeURIComponent(t.message_id)}&n=${t.n + 1}`

/** Add a trip (or one item) to a calendar you pick; the last pick per world is offered first. */
export function CalendarDialog({ tripId, title, world, keys, last, onClose, onDone }: { tripId: string; title: string; world?: string | null; keys?: string[]
  last?: Record<string, string>; onClose: () => void; onDone: () => void }) {
  const { ax } = useApp()
  const [cals, setCals] = useState<Cal[] | null>(null)
  const [pick, setPick] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    get<{ calendars: Cal[]; can_edit: boolean; owner: boolean }>('calendar_caps').then(c => {
      const list = c.owner && c.can_edit ? c.calendars.filter(x => x.can_modify) : []
      setCals(list)
      const want = (world && last?.[world]) || list.find(x => world && x.ctx === world)?.title || list[0]?.title || ''
      setPick(list.some(x => x.title === want) ? want : list[0]?.title || '')
    }).catch(() => setCals([]))
  }, [world, last])
  async function add() {
    setBusy(true)
    try {
      const r = await ax.act('trip_cal_add', { id: tripId, calendar: pick, title, ...(keys ? { keys } : {}) }, [])
      const n = (r as any)?.result?.added
      toast(`${n ?? 'Items'} added to ${pick}`); onDone(); onClose()
    } catch (e: any) { toast.error(e.message) } finally { setBusy(false) }
  }
  return <Dialog open onOpenChange={o => !o && onClose()}><DialogContent className="sm:max-w-sm" data-trip-cal="">
    <div className="space-y-3 p-5">
      <DialogTitle className="text-lg font-semibold">{keys ? 'Add this to the calendar' : `Add “${title}” to the calendar`}</DialogTitle>
      {cals === null ? <p className="text-ink-3 text-sm">Loading calendars…</p> : !cals.length ? <p className="text-ink-3 text-sm">No calendar can be changed from here.</p> :
        <NativeSelect aria-label="Calendar" value={pick} onChange={e => setPick(e.target.value)}>{cals.map(c => <option key={c.title} value={c.title}>{c.label || c.title}</option>)}</NativeSelect>}
      <p className="text-ink-3 text-[12.5px]">Each item in its own local time, with its booking reference. Cancelled items stay out. When a booking changes, Axella offers to update the event – it never changes it by itself.</p>
      <div className="flex gap-2"><Button size="pill" disabled={!pick || busy || !ax.apiOk} onClick={add}><CalendarPlus />Add</Button><Button size="pill" variant="ghost" onClick={onClose}>Cancel</Button></div>
    </div></DialogContent></Dialog>
}

/** Under a booking: an update waiting (Apply / Ignore), "Updated from …", check-in opening, the calendar to fix. */
export function BookingLive({ tripId, b, edit, act }: { tripId: string; b: LBooking; edit: (a: string, body: Record<string, unknown>, msg: string) => void
  act: (a: string, body: Record<string, unknown>, msg: string) => void }) {
  const p = b.pending, u = b.updated, c = b.checkin_view
  const ch = (x?: Record<string, string>, y?: Record<string, string>) => x?.status === 'cancelled' || y?.status === 'cancelled' ? 'cancelled'
    : `${x?.start ? 'departure ' + hm(x.start) : ''} → ${y?.start ? hm(y.start) + (y.start.slice(0, 10) !== x?.start?.slice(0, 10) ? ' (' + dayhm(y.start).split(' ').slice(0, 3).join(' ') + ')' : '') : ''}`
  if (!p && !u && !c && !b.cal_stale && !b.cal) return null
  return <span className="mt-1 block space-y-1 text-[12.5px]" data-booking-live="">
    {p && <span className="bg-dawn/10 block rounded-md px-2 py-1.5" data-trip-pending="">Update from {p.by}: {ch(p.was, p.now)} – {p.other_sender
        ? <b className="font-medium">From another sender than the booking – check with {p.provider || b.provider || 'them'} before you apply it.</b>
        : 'you edited this booking, so it waits for you.'}
      <span className="mt-1 flex gap-2"><Button size="pill" onClick={() => edit('trip_update_apply', { id: tripId, key: b.key, title: b.title }, 'Update applied')}><Check />Apply</Button>
        <Button size="pill" variant="ghost" onClick={() => edit('trip_update_ignore', { id: tripId, key: b.key, title: b.title }, 'Kept your version')}><X />Ignore</Button></span></span>}
    {u && !p && <span className="text-ink-3 block" data-trip-updated="">Updated from {u.by}, {u.at ? new Date(u.at).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''}{u.was?.start ? ` – was ${hm(u.was.start)}` : ''}</span>}
    {c && b.status !== 'cancelled' && <span className="text-ink-2 block" data-trip-checkin="">Check-in opens {dayhm(c.at)}{c.estimated ? ' (estimated)' : ''}</span>}
    {b.cal_stale && <span className="flex flex-wrap items-center gap-2" data-trip-cal-stale="">
      <span className="text-dawn">{b.cal_stale === 'cancelled' ? 'Cancelled – still in your calendar.' : 'Changed – your calendar has the old time.'}</span>
      <Button size="pill" variant="outline" onClick={() => act(b.cal_stale === 'cancelled' ? 'trip_cal_remove' : 'trip_cal_sync', { id: tripId, key: b.key, title: b.title },
        b.cal_stale === 'cancelled' ? 'Removed from the calendar – Restore from the Activity log' : 'Calendar updated')}>{b.cal_stale === 'cancelled' ? 'Remove from calendar' : 'Update in calendar'}</Button></span>}
    {b.cal && !b.cal_stale && <span className="text-ink-3 block">In {b.cal.calendar}</span>}
  </span>
}

/* ---------- offline: the owner's upcoming trips and their tickets on this device ---------- */
export function cacheTrips(urls: string[] | null) {
  try {
    const sw = navigator.serviceWorker?.controller
    if (!sw) return
    sw.postMessage(urls ? { type: 'axella-trips-cache', urls: ['api/trips', 'api/trip_today', ...urls] } : { type: 'axella-trips-clear' })
  } catch { /* no service worker */ }
}
export function ticketUrls(trips: { end: string; bookings: LBooking[] }[]) {
  const today = new Date().toISOString().slice(0, 10)
  const out: string[] = []
  for (const t of trips) {
    if (t.end.slice(0, 10) < today) continue
    for (const b of t.bookings) {
      if (b.status === 'cancelled') continue
      for (const x of b.tickets || []) if (x.message_id && x.ticket != null) out.push(ticketUrl({ account: x.account, message_id: x.message_id, n: x.ticket }))
      if (b.ticket != null && b.source?.message_id) out.push(ticketUrl({ account: b.source.account, message_id: b.source.message_id, n: b.ticket }))
    }
  }
  return [...new Set(out)].slice(0, 60)
}

interface CardItem { key: string; kind: string; title: string; start: string; end: string; place?: string; address?: string; ref?: string; number?: string; provider?: string
  checkin?: { at: string; estimated: boolean } | null; ticket?: { account?: string; message_id: string; n: number } }
interface TodayCard { trip: { id: string; title: string }; mode: 'travel' | 'eve' | 'during'; next: CardItem; day: CardItem[] }

/** The Today card on a travel day (and the evening before), or the day's plan during a trip – works offline too. */
export function TravelCard() {
  const { go } = useApp()
  const [c, setC] = useState<TodayCard | null>(null)
  useEffect(() => { get<{ card: TodayCard | null }>('trip_today').then(r => setC(r.card)).catch(() => {}) }, [])
  if (!c) return null
  const n = c.next
  const open = n.checkin && new Date(n.checkin.at).getTime() <= Date.now()
  const where = n.address || n.place
  return <Card className="space-y-2 p-4" data-travel-card="">
    <div className="flex items-center gap-2"><TripIcon className="text-ink-3 size-4" /><span className="ax-label">{c.mode === 'during' ? 'Today on ' + c.trip.title : c.mode === 'eve' ? 'Tomorrow' : 'Travel day'}</span></div>
    <div className="text-[17px] font-semibold leading-snug">{[n.number || n.title, hm(n.start), where].filter(Boolean).join(' · ')}
      {n.checkin && <span className={cn('ml-2 text-[13px] font-normal', open ? 'text-fjord' : 'text-ink-3')}>{open ? 'check-in open' : 'check-in ' + dayhm(n.checkin.at)}{n.checkin.estimated ? ' (estimated)' : ''}</span>}</div>
    {n.number && n.title && <div className="text-ink-3 text-[13px]">{n.title}{n.provider ? ' · ' + n.provider : ''}</div>}
    <div className="flex flex-wrap gap-2">
      {n.ref && <Button size="pill" variant="outline" onClick={() => navigator.clipboard.writeText(n.ref!).then(() => toast('Reference copied'), () => {})}><Copy /><span className="font-mono">{n.ref}</span></Button>}
      {where && <Button size="pill" variant="outline" asChild><a href={'https://maps.apple.com/?q=' + encodeURIComponent(where)} target="_blank" rel="noopener noreferrer"><ExternalLink />Maps</a></Button>}
      {n.ticket && <Button size="pill" asChild><a href={ticketUrl(n.ticket)} target="_blank" rel="noopener noreferrer">Ticket</a></Button>}
      <Button size="pill" variant="ghost" onClick={() => go({ kind: 'trips' })}>Trip</Button>
    </div>
    {c.day.length > 0 && <ul className="divide-y border-t pt-1 text-sm">{c.day.map(i => <li key={i.key} className="flex gap-3 py-1.5">
      <span className="text-ink-3 w-12 shrink-0 font-mono text-[12px]">{hm(i.start) !== '00:00' ? hm(i.start) : '—'}</span><span className="min-w-0 flex-1 truncate">{i.title}</span></li>)}</ul>}
  </Card>
}
