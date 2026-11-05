/* Calendar (sidebar): your calendars from the Mac mini, read only – Agenda (the next 14 days, the phone's default) and
   Week (the laptop's default). The All / Work / Private filter in the header applies; a calendar that isn't marked
   work or private in the settings shows under both. Above it: what today's digest noted about the calendar (conflicts,
   suggestions). Events come from GET calendar (setup/calendar_view.py, via Macuse); nothing is changed from here. */
import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { CalendarDays, ChevronRight, ExternalLink, Pencil, Plus, RotateCw, Trash2 } from '@/components/ax-icons'
import { withUndo } from '@/components/Contacts'
import { useCalendarRefresh } from '@/lib/calendarBus'
import { PrepareButton } from '@/components/Meetings'
import { PendingInvites } from '@/components/Invite'
import { InviteConfirm, InviteStatus, InviteesField, OnlinePicker, myZone, newSendId, useOnline, type InviteRec, type Online, type Person } from '@/components/CalendarInvites'
import { joinLink } from '@/lib/meetings'
import { Input, NativeSelect } from '@/components/ui/input'
import { ItemRow } from '@/components/ItemRow'
import { useBySection } from '@/components/Today'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { IOS, cn, isoDate, store } from '@/lib/utils'

export interface CalEventRow {
  id: string; title: string; start: string; end: string; all_day: boolean; location?: string | null; notes?: string | null
  url?: string | null; calendar: string; calendar_label: string; ctx: 'work' | 'private' | null; recurring: boolean
  attendees: number; deep_link?: string | null; availability?: string | null; people?: { name: string; email: string }[]
}
type Mode = 'agenda' | 'week'
const DAY = 864e5
const addDays = (d: Date, n: number) => { const x = new Date(d); x.setDate(x.getDate() + n); return x }
const startOfDay = (d: Date) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x }
const monday = (d: Date) => { const x = startOfDay(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x }
const hm = (s: string) => new Date(s).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
const dayLabel = (d: Date) => d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
const color = (e: CalEventRow) => e.ctx === 'work' ? 'var(--ax-work)' : e.ctx === 'private' ? 'var(--ax-private)' : 'var(--ax-ink-3)'

function useEvents(from: Date, to: Date) {
  const key = isoDate(from) + '_' + isoDate(to)
  const [d, setD] = useState<{ key: string; events: CalEventRow[] } | null>(null)
  const [err, setErr] = useState('')
  const [n, setN] = useState(0)
  const fresh = useRef(false)
  useCalendarRefresh(f => { fresh.current = f; setN(x => x + 1) })
  useEffect(() => {
    let live = true
    setErr('')
    const f = fresh.current; fresh.current = false
    get<{ events: CalEventRow[] }>(`calendar?from=${isoDate(from)}&to=${isoDate(to)}${f ? '&fresh=1' : ''}`)
      .then(j => { if (live) setD({ key, events: j.events || [] }) }).catch(e => { if (live) setErr(e.message) })
    return () => { live = false }
  }, [key, n])                                            // eslint-disable-line react-hooks/exhaustive-deps
  return { events: d?.key === key ? d.events : null, err, reload: () => { fresh.current = true; setN(x => x + 1) } }
}

/** the days an event covers, in local time (an all-day event's end is the next midnight) */
function onDay(e: CalEventRow, day: Date) {
  const s = new Date(e.start).getTime(), en = new Date(e.end || e.start).getTime(), a = day.getTime(), b = a + DAY
  return e.all_day ? s < b && (en > a || s >= a) : (s < b && en > a) || (s >= a && s < b)
}

/* may this login change events, and in which calendars (GET calendar_caps – asks Macuse once per page load) */
interface Caps { can_edit: boolean; owner: boolean; problems?: string[]; calendars: { title: string; source: string; can_modify: boolean; label: string; ctx: 'work' | 'private' | null }[] }
let capsCache: Promise<Caps> | null = null
const loadCaps = () => (capsCache ||= get<Caps>('calendar_caps').catch(() => ({ can_edit: false, owner: false, calendars: [] })))
function useCaps() {
  const [c, setC] = useState<Caps | null>(null)
  useEffect(() => { loadCaps().then(setC) }, [])
  return c
}
const editableCals = (caps: Caps | null) => caps && caps.owner && caps.can_edit ? caps.calendars.filter(c => c.can_modify) : []

export function CalendarView() {
  const { ax, ctx } = useApp()
  const caps = useCaps()
  const [adding, setAdding] = useState(false)
  const lg = typeof matchMedia !== 'undefined' && matchMedia('(min-width: 1024px)').matches
  const [mode, setMode] = useState<Mode>(() => (store.get('ax-cal-mode', '') as Mode) || (lg ? 'week' : 'agenda'))
  const [anchor, setAnchor] = useState(() => startOfDay(new Date()))
  const [open, setOpen] = useState<CalEventRow | null>(null)
  useEffect(() => { store.set('ax-cal-mode', mode) }, [mode])
  const from = mode === 'week' ? monday(anchor) : anchor
  const to = addDays(from, mode === 'week' ? 7 : 14)
  const { events, err, reload } = useEvents(from, to)
  const shown = useMemo(() => (events || []).filter(e => ctx === 'all' || !e.ctx || e.ctx === ctx), [events, ctx])
  const step = (n: number) => setAnchor(a => addDays(mode === 'week' ? monday(a) : a, n * (mode === 'week' ? 7 : 14)))
  const isNow = mode === 'week' ? monday(new Date()).getTime() === from.getTime() : startOfDay(new Date()).getTime() === from.getTime()
  const title = mode === 'week'
    ? `${from.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })} – ${addDays(to, -1).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}`
    : `${dayLabel(from)} – ${dayLabel(addDays(to, -1))}`
  return <div className="space-y-4" data-calendar-view="">
    <div className="flex flex-wrap items-center gap-2">
      <h1 className="mr-auto flex items-center gap-2 text-xl font-semibold tracking-tight"><CalendarDays className="size-5" />Calendar</h1>
      {ax.apiOk && editableCals(caps).length > 0 && <Button size="pill" onClick={() => setAdding(true)} data-tour="cal-new"><Plus />New event</Button>}
      <span className="bg-bg-2 inline-flex rounded-md border p-0.5 text-[13px]" role="group" aria-label="View">
        {(['agenda', 'week'] as const).map(m => <button key={m} type="button" onClick={() => setMode(m)} aria-pressed={mode === m}
          className={cn('rounded px-2.5 py-1', mode === m ? 'bg-card text-ink font-semibold shadow-sm' : 'text-ink-3 hover:text-ink')}>{m === 'agenda' ? 'Agenda' : 'Week'}</button>)}
      </span>
    </div>
    <DigestNotes />
    <PendingInvites />
    <div className="flex items-center gap-2">
      <Button size="pill" variant="outline" onClick={() => step(-1)} aria-label="Earlier"><ChevronRight className="rotate-180" /></Button>
      <Button size="pill" variant="outline" onClick={() => setAnchor(startOfDay(new Date()))} disabled={isNow}>Today</Button>
      <Button size="pill" variant="outline" onClick={() => step(1)} aria-label="Later"><ChevronRight /></Button>
      <span className="ml-1 text-sm font-medium">{title}</span>
      <button type="button" className="text-ink-3 hover:text-ink ml-auto p-1" onClick={reload} aria-label="Reload"><RotateCw className={cn('size-4', !events && !err && 'animate-spin')} /></button>
    </div>
    {err ? <div className="text-dawn text-sm">{err}{!ax.apiOk && ' – the Mac mini is not answering'}</div>
      : !events ? <div className="text-ink-3 text-sm">Reading your calendars…</div>
      : mode === 'agenda' ? <Agenda from={from} days={14} events={shown} onOpen={setOpen} />
      : <Week from={from} events={shown} onOpen={setOpen} />}
    {open && <EventSheet e={open} caps={caps} onClose={() => setOpen(null)} onChanged={reload} />}
    {adding && <EventForm caps={caps} day={anchor} onClose={() => setAdding(false)} onDone={() => { setAdding(false); reload() }} />}
  </div>
}

/* what today's digest said about the calendar – conflicts, suggested events – collapsed above the calendar */
function DigestNotes() {
  const { ax } = useApp()
  const { by } = useBySection()
  const [show, setShow] = useState(false)
  const notes = (by.cal || []).filter(i => !ax.isHandled(i.id))
  if (!notes.length) return null
  return <div className="bg-card overflow-hidden rounded-lg border" data-cal-notes="">
    <button onClick={() => setShow(!show)} aria-expanded={show} className="bg-bg-2/60 hover:bg-bg-2 flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm">
      <span className="ax-label">From today's digest</span><span className="text-ink-3 font-mono text-[12px]">{notes.length}</span>
      <span className="text-fjord ml-auto text-[13px] font-medium">{show ? 'Hide' : 'Show'}</span>
    </button>
    {show && <div className="ax-reveal divide-y border-t">{notes.map(i => <ItemRow key={i.id} it={i} />)}</div>}
  </div>
}

function Agenda({ from, days, events, onOpen }: { from: Date; days: number; events: CalEventRow[]; onOpen: (e: CalEventRow) => void }) {
  const list = Array.from({ length: days }, (_, i) => addDays(from, i)).map(d => [d, events.filter(e => onDay(e, d))] as const)
  const today = startOfDay(new Date()).getTime()
  if (!events.length) return <div className="bg-card text-ink-3 rounded-lg border px-4 py-6 text-center text-sm">Nothing in these {days} days.</div>
  return <div className="bg-card overflow-hidden rounded-lg border" data-agenda="">
    {list.filter(([, l]) => l.length).map(([d, l]) => <div key={d.getTime()}>
      <div className={cn('bg-bg-2/60 sticky top-0 border-b px-4 py-1.5 text-[13px] font-semibold', d.getTime() === today && 'text-fjord')}>
        {d.getTime() === today ? 'Today · ' : d.getTime() === today + DAY ? 'Tomorrow · ' : ''}{dayLabel(d)}</div>
      <div className="divide-y">{l.map(e => <button key={e.id + e.start} type="button" onClick={() => onOpen(e)}
        className="hover:bg-bg-2 flex min-h-12 w-full items-start gap-3 px-4 py-2 text-left" data-event="">
        <span className="text-ink-2 w-24 shrink-0 font-mono text-[12.5px] leading-6">{e.all_day ? 'All day' : `${hm(e.start)}–${hm(e.end)}`}</span>
        <span className="mt-1.5 size-2.5 shrink-0 rounded-full" style={{ background: color(e) }} aria-hidden />
        <span className="min-w-0 flex-1"><span className="block truncate font-medium">{e.title}</span>
          <span className="text-ink-3 block truncate text-[12.5px]">{[e.location, e.calendar_label].filter(Boolean).join(' · ')}</span></span>
      </button>)}</div>
    </div>)}
  </div>
}

/* a week: all-day row on top, then the hours; overlapping events share the column side by side */
function Week({ from, events, onOpen }: { from: Date; events: CalEventRow[]; onOpen: (e: CalEventRow) => void }) {
  const days = Array.from({ length: 7 }, (_, i) => addDays(from, i))
  const timed = events.filter(e => !e.all_day)
  const hours = timed.flatMap(e => [new Date(e.start).getHours(), new Date(e.end).getHours() + (new Date(e.end).getMinutes() ? 1 : 0)])
  const h0 = Math.min(7, ...hours.filter(h => h >= 0)), h1 = Math.max(20, ...hours.filter(h => h <= 24))
  const PX = 44, today = startOfDay(new Date()).getTime()
  return <div className="bg-card overflow-x-auto rounded-lg border" data-week="">
    <div className="min-w-[720px]">
      <div className="grid grid-cols-[48px_repeat(7,1fr)] border-b">
        <div />
        {days.map(d => <div key={d.getTime()} className={cn('border-l px-2 py-1.5 text-[13px]', d.getTime() === today && 'text-fjord font-semibold')}>{dayLabel(d)}</div>)}
      </div>
      <div className="grid grid-cols-[48px_repeat(7,1fr)] border-b">
        <div className="text-ink-3 px-1 py-1 text-right font-mono text-[11px]">all day</div>
        {days.map(d => <div key={d.getTime()} className="min-h-7 space-y-0.5 border-l p-0.5">
          {events.filter(e => e.all_day && onDay(e, d)).map(e => <button key={e.id + e.start} type="button" onClick={() => onOpen(e)} title={e.title}
            className="block w-full truncate rounded px-1.5 py-0.5 text-left text-[12px] text-white" style={{ background: color(e) }}>{e.title}</button>)}
        </div>)}
      </div>
      <div className="relative grid grid-cols-[48px_repeat(7,1fr)]" style={{ height: (h1 - h0) * PX }}>
        <div className="relative">{Array.from({ length: h1 - h0 }, (_, i) => <div key={i} className="text-ink-3 absolute right-1 font-mono text-[11px]" style={{ top: i * PX - 6 }}>{i ? String(h0 + i).padStart(2, '0') : ''}</div>)}</div>
        {days.map(d => {
          const list = layout(timed.filter(e => onDay(e, d)), d)
          return <div key={d.getTime()} className={cn('relative border-l', d.getTime() === today && 'bg-fjord-soft/30')}>
            {Array.from({ length: h1 - h0 }, (_, i) => <div key={i} className="border-line absolute inset-x-0 border-t" style={{ top: i * PX }} />)}
            {list.map(({ e, top, height, col, cols }) => <button key={e.id + e.start} type="button" onClick={() => onOpen(e)} title={`${hm(e.start)}–${hm(e.end)} ${e.title}`}
              className="absolute overflow-hidden rounded border border-white/40 px-1 py-0.5 text-left text-[11.5px] leading-tight text-white shadow-sm hover:brightness-110" data-event=""
              style={{ top: (top - h0) * PX, height: Math.max(18, height * PX - 2), left: `calc(${(col / cols) * 100}% + 1px)`, width: `calc(${100 / cols}% - 2px)`, background: color(e) }}>
              <span className="block truncate font-medium">{e.title}</span>{height > 0.75 && <span className="block truncate opacity-85">{hm(e.start)}</span>}
            </button>)}
          </div>
        })}
      </div>
    </div>
  </div>
}

/** start/height in hours for one day, plus side-by-side columns for events that overlap */
function layout(list: CalEventRow[], day: Date) {
  const a = day.getTime(), b = a + DAY
  const rows = list.map(e => {
    const s = Math.max(new Date(e.start).getTime(), a), en = Math.min(new Date(e.end || e.start).getTime(), b)
    return { e, s, en: Math.max(en, s + 15 * 60e3), top: (s - a) / 36e5, height: Math.max(0.25, (Math.max(en, s + 15 * 60e3) - s) / 36e5), col: 0, cols: 1 }
  }).sort((x, y) => x.s - y.s || y.en - x.en)
  let group: typeof rows = [], end = 0
  const flush = () => { const n = Math.max(...group.map(r => r.col)) + 1; group.forEach(r => { r.cols = n }); group = [] }
  for (const r of rows) {
    if (group.length && r.s >= end) { flush(); end = 0 }
    const used = new Set(group.filter(g => g.en > r.s).map(g => g.col))
    let c = 0; while (used.has(c)) c++
    r.col = c; group.push(r); end = Math.max(end, r.en)
  }
  if (group.length) flush()
  return rows
}

/* calshow: opens the iPhone's Calendar at that time; ical:// is the Mac's link to the event itself */
const calshow = (iso: string) => 'calshow:' + Math.round((new Date(iso).getTime() - Date.UTC(2001, 0, 1)) / 1000)

function EventSheet({ e, caps, onClose, onChanged }: { e: CalEventRow; caps: Caps | null; onClose: () => void; onChanged: () => void }) {
  const { ax } = useApp()
  const [editing, setEditing] = useState(false)
  const [armed, setArmed] = useState(false)
  const [asking, setAsking] = useState(false)
  const [inviteEdit, setInviteEdit] = useState<InviteRec | null>(null)
  const [byAxella, setByAxella] = useState(false)
  const cals = editableCals(caps)
  const editable = ax.apiOk && !e.attendees && cals.some(c => c.title === e.calendar)
  const s = new Date(e.start), en = new Date(e.end || e.start)
  const same = isoDate(s) === isoDate(addDays(en, e.all_day ? -1 : 0))
  const when = e.all_day ? (same ? dayLabel(s) + ' · all day' : `${dayLabel(s)} – ${dayLabel(addDays(en, -1))} · all day`)
    : same ? `${dayLabel(s)} · ${hm(e.start)}–${hm(e.end)}` : `${dayLabel(s)} ${hm(e.start)} – ${dayLabel(en)} ${hm(e.end)}`
  const open = IOS ? calshow(e.start) : e.deep_link
  // an online meeting's join link (Teams, Zoom, Meet, Webex) from the notes, location or URL – as a button
  const join = useMemo(() => joinLink(e), [e])
  if (editing) return <EventForm caps={caps} e={e} onClose={() => setEditing(false)} onDone={() => { onClose(); onChanged() }} />
  if (inviteEdit) return <EventForm caps={caps} e={e} invite={inviteEdit} onClose={() => setInviteEdit(null)} onDone={() => { onClose(); onChanged() }} />
  function del(scope?: 'this' | 'future') {
    if (e.recurring && !scope) { setAsking(true); return }
    if (!armed && !scope) { setArmed(true); setTimeout(() => setArmed(false), 3000); return }
    onClose()
    withUndo(`Deleting ${e.title}${scope === 'future' ? ' (this and future)' : ''}…`, async () => {
      try { await ax.act('cal_delete', { id: e.id, start: e.start, scope: scope || 'this', title: e.title }, []); toast.success(e.title + ' deleted – Restore from the Activity log for 90 days'); onChanged() }
      catch (x: any) { toast.error('Not deleted: ' + x.message) }
    })
  }
  return <Dialog open onOpenChange={o => { if (!o) onClose() }}>
    <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-md" data-event-sheet="">
      <div className="space-y-3 p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))]">
        <div className="flex items-start gap-2.5 pr-6">
          <span className="mt-2 size-3 shrink-0 rounded-full" style={{ background: color(e) }} aria-hidden />
          <DialogTitle className="text-lg leading-snug font-semibold">{e.title}</DialogTitle>
        </div>
        <div className="text-ink-2 space-y-1 text-sm">
          <div>{when}{e.recurring && <span className="text-ink-3"> · repeats</span>}</div>
          {e.location && <div>{e.location}</div>}
          <div className="text-ink-3">{e.calendar_label}{e.ctx ? ' · ' + (e.ctx === 'work' ? 'Work' : 'Private') : ''}{e.attendees ? ` · ${e.attendees} other${e.attendees === 1 ? '' : 's'} invited` : ''}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          {join && <Button size="pill" asChild><a href={join} target="_blank" rel="noopener noreferrer"><ExternalLink />Join meeting</a></Button>}
          <PrepareButton e={e} onGo={onClose} />
        </div>
        {e.attendees > 0 && ax.apiOk && <InviteStatus e={e} onEdit={setInviteEdit} onFound={setByAxella} onCancelled={() => { onClose(); onChanged() }} />}
        {e.notes && <div className="bg-bg-2/60 max-h-60 overflow-y-auto rounded-md border px-3 py-2 text-[13.5px] leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]">{e.notes.replace(/<https?:\/\/[^>\s]+>/g, '').replace(/_{10,}/g, '———')}</div>}
        {e.url && /^https?:\/\//i.test(e.url) && <a className="text-fjord block truncate text-sm hover:underline" href={e.url} target="_blank" rel="noopener noreferrer">{e.url}</a>}
        {open && <Button size="pill" variant="outline" asChild><a href={open}><ExternalLink />Open in Calendar</a></Button>}
        {editable ? <div className="flex flex-wrap items-center gap-2 border-t pt-3">
            <Button size="pill" variant="outline" onClick={() => setEditing(true)}><Pencil />Edit</Button>
            {!asking ? <Button size="pill" variant="ghost" className={cn('ml-auto', armed && 'text-danger')} onClick={() => del()}><Trash2 />{armed ? 'Tap again to delete' : 'Delete'}</Button>
              : <span className="ml-auto flex items-center gap-1.5 text-[13px]">Delete:
                  <Button size="pill" variant="outline" onClick={() => del('this')}>This event</Button>
                  <Button size="pill" variant="outline" onClick={() => del('future')}>This and future</Button></span>}
          </div>
          : byAxella ? null : <p className="text-ink-3 text-[11.5px]">{e.attendees ? 'A meeting with other people – change it in Calendar, so they are told.' : 'Read only – change it in Calendar.'}</p>}
      </div>
    </DialogContent>
  </Dialog>
}

/* ---------- add / edit an event (owner only, own events, no invitees) ---------- */
const pad = (n: number) => String(n).padStart(2, '0')
const dPart = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const tPart = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`
/** local date + time → ISO 8601 with the local offset (what Calendar expects) */
function localIso(date: string, time: string) {
  const d = new Date(`${date}T${time || '00:00'}`)
  const off = -d.getTimezoneOffset(), sign = off >= 0 ? '+' : '-'
  return `${dPart(d)}T${tPart(d)}:00${sign}${pad(Math.floor(Math.abs(off) / 60))}:${pad(Math.abs(off) % 60)}`
}

function EventForm({ caps, e, day, invite, onClose, onDone }: { caps: Caps | null; e?: CalEventRow; day?: Date; invite?: InviteRec; onClose: () => void; onDone: () => void }) {
  const { ax, ctx } = useApp()
  const online = useOnline()
  const all = editableCals(caps)
  const here = e ? all.find(c => c.title === e.calendar) : null
  // moving: only to calendars of the same account (iCloud Home ↔ iCloud Work), never across accounts
  const cals = e ? all.filter(c => c.source === here?.source) : all
  const s0 = e ? new Date(e.start) : (() => { const d = new Date(day || new Date()); const n = new Date(); d.setHours(n.getHours() + 1, 0, 0, 0); return d })()
  const e0 = e ? new Date(e.end || e.start) : new Date(s0.getTime() + 36e5)
  const [title, setTitle] = useState(e?.title || '')
  const [cal, setCal] = useState(e?.calendar || (cals.find(c => ctx !== 'all' && c.ctx === ctx) || cals[0])?.title || '')
  const [allDay, setAllDay] = useState(!!e?.all_day)
  const [date, setDate] = useState(dPart(s0)), [start, setStart] = useState(tPart(s0))
  const [endDate, setEndDate] = useState(dPart(e?.all_day ? addDays(e0, -1) : e0)), [end, setEnd] = useState(tPart(e0))
  const [location, setLocation] = useState(e?.location || ''), [notes, setNotes] = useState(e?.notes || '')
  const [busy, setBusy] = useState(false), [ask, setAsk] = useState(false)
  // invitees and the online meeting (calendar_online.py): the calendar's own server sends the invitations
  const [people, setPeople] = useState<Person[]>(invite?.people || [])
  const [meet, setMeet] = useState<Online>({ kind: 'none' })
  const [picked, setPicked] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [moveMeeting, setMoveMeeting] = useState(true)
  const [sid, setSid] = useState(newSendId)
  const ocal = online?.calendars.find(c => c.title === cal)
  useEffect(() => {                      // a new event: the calendar's default online meeting, until you pick one
    if (e || picked || !online) return
    setMeet(ocal?.default ? { kind: 'provider', provider: ocal.default } : { kind: 'none' })
  }, [cal, online])                       // eslint-disable-line react-hooks/exhaustive-deps
  const times = () => {
    const ns = allDay ? localIso(date, '00:00') : localIso(date, start)
    const ne = allDay ? localIso(dPart(addDays(new Date(endDate + 'T12:00'), 1)), '00:00') : localIso(endDate, end)
    return [ns, ne] as const
  }
  const whenText = () => { const [ns, ne] = times(); return `${dayLabel(new Date(ns))} ${hm(ns)}–${hm(ne)}` }
  const meetText = () => meet.kind === 'provider' ? (ocal?.services.find(s => s.key === meet.provider)?.offer || '') + ' – made on this tap'
    : meet.kind === 'link' ? 'Join link: ' + meet.url : invite?.join?.join_url ? 'Join link: ' + invite.join.join_url : null
  async function sendInvites() {
    const [ns, ne] = times()
    setBusy(true)
    try {
      await ax.act('cal_invite_send', { calendar: cal, title, start: ns, end: ne, tz: myZone(), attendees: people, location, notes,
        online: meet, send_id: sid, confirm: 'send' }, [])
      capsCache = null
      toast.success(`Invitation sent to ${people.length} ${people.length === 1 ? 'person' : 'people'}`)
      onDone()
    } catch (x: any) { toast.error('Not sent: ' + x.message); setConfirming(false) } finally { setBusy(false) }
  }
  async function sendUpdate(tell: boolean) {
    const [ns, ne] = times()
    setBusy(true)
    try {
      await ax.act('cal_invite_update', { uid: invite!.uid, title, start: ns, end: ne, tz: myZone(), attendees: people, location, notes,
        move_meeting: !!invite!.meeting && moveMeeting, send_id: sid, confirm: tell ? 'send' : 'save' }, [])
      toast.success(tell ? 'Update sent' : 'Saved – the people were not told')
      onDone()
    } catch (x: any) { toast.error('Not saved: ' + x.message); setConfirming(false); setSid(newSendId()) } finally { setBusy(false) }
  }
  async function save(scope?: 'this' | 'future') {
    if (invite) { if (!people.length) { toast.error('An invitation needs someone – cancel the meeting instead'); return } setConfirming(true); return }
    if (!e && people.length) {
      if (allDay) { toast.error("An all-day event can't have invitees from here"); return }
      if (!ocal?.path) { toast.error(ocal?.why || "This calendar can't send invitations from here"); return }
      setConfirming(true); return
    }
    if (e?.recurring && !scope) { setAsk(true); return }
    const [ns, ne] = times()
    if (new Date(ne) < new Date(ns)) { toast.error('The event ends before it starts'); return }
    setBusy(true)
    try {
      if (!e) await ax.act('cal_add', { title, calendar: cal, start: ns, end: ne, all_day: allDay, location, notes,
        ...(meet.kind !== 'none' ? { online: meet, send_id: sid, tz: myZone() } : {}) }, [])
      else {
        const moved = new Date(ns).getTime() !== new Date(e.start).getTime() || new Date(ne).getTime() !== new Date(e.end).getTime()
        await ax.act('cal_update', { id: e.id, start: e.start, scope: scope || 'this', title, location, notes, all_day: allDay,
          ...(cal !== e.calendar ? { calendar: cal } : {}), ...(moved ? { new_start: ns, new_end: ne } : {}) }, [])
      }
      capsCache = null
      toast.success(e ? title + ' saved' : title + ' added to ' + (all.find(c => c.title === cal)?.label || cal))
      onDone()
    } catch (x: any) { toast.error('Not saved: ' + x.message) } finally { setBusy(false) }
  }
  if (confirming) return <Dialog open onOpenChange={o => { if (!o) onClose() }}>
    <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-md" data-event-form=""><div className="p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] text-sm">
      <DialogTitle className="sr-only">{invite ? 'Send update' : 'Send invites'}</DialogTitle>
      {invite ? <InviteConfirm people={people} from={invite.from} title={title} when={whenText()} zone={myZone()} online={meetText()} busy={busy}
          verb="Send update" onSend={() => sendUpdate(true)} onBack={() => setConfirming(false)}
          alt={invite.silent_save ? { label: 'Save without telling them', onClick: () => sendUpdate(false) } : undefined} />
        : <InviteConfirm people={people} from={ocal?.from || ''} title={title} when={whenText()} zone={myZone()} online={meetText()} busy={busy}
          onSend={sendInvites} onBack={() => setConfirming(false)} />}
    </div></DialogContent>
  </Dialog>
  return <Dialog open onOpenChange={o => { if (!o) onClose() }}>
    <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-md" data-event-form="">
      <form onSubmit={ev => { ev.preventDefault(); save() }} className="space-y-3 p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] text-sm">
        <DialogTitle className="text-lg font-semibold">{e ? 'Edit event' : 'New event'}</DialogTitle>
        <label className="block"><span className="mb-1 block font-medium">Title</span><Input value={title} maxLength={300} required autoFocus onChange={x => setTitle(x.target.value)} /></label>
        <label className="block"><span className="mb-1 block font-medium">Calendar</span>
          <NativeSelect value={cal} disabled={!!invite} onChange={x => setCal(x.target.value)}>
            {cals.map(c => <option key={c.title} value={c.title}>{c.label}{c.ctx ? ` (${c.ctx === 'work' ? 'Work' : 'Private'})` : ''}</option>)}</NativeSelect>
          {e && all.length > cals.length && <span className="text-ink-3 mt-1 block text-[12px]">Only calendars of the same account ({here?.source}) – an event can't move between accounts.</span>}
        </label>
        {!invite && <label className="flex items-center gap-2"><input type="checkbox" checked={allDay} onChange={x => setAllDay(x.target.checked)} />All day</label>}
        <div className="grid grid-cols-2 gap-2">
          <label className="block"><span className="mb-1 block font-medium">Starts</span><Input type="date" value={date} required onChange={x => { setDate(x.target.value); if (x.target.value > endDate) setEndDate(x.target.value) }} /></label>
          {!allDay ? <label className="block"><span className="mb-1 block font-medium">&nbsp;</span><Input type="time" value={start} required onChange={x => setStart(x.target.value)} /></label> : <span />}
          <label className="block"><span className="mb-1 block font-medium">Ends</span><Input type="date" value={endDate} required onChange={x => setEndDate(x.target.value)} /></label>
          {!allDay ? <label className="block"><span className="mb-1 block font-medium">&nbsp;</span><Input type="time" value={end} required onChange={x => setEnd(x.target.value)} /></label> : <span />}
        </div>
        <label className="block"><span className="mb-1 block font-medium">Place</span><Input value={location} maxLength={300} onChange={x => setLocation(x.target.value)} /></label>
        <label className="block"><span className="mb-1 block font-medium">Notes</span>
          <textarea rows={3} maxLength={3000} value={notes} onChange={x => setNotes(x.target.value)}
            className="border-line-strong bg-card focus-visible:ring-ring/30 w-full rounded-md border px-2.5 py-1.5 text-[16px] outline-none focus-visible:ring-2 sm:text-sm" /></label>
        {(!e || invite) && !allDay && (ocal?.path || invite
          ? <InviteesField value={people} onChange={setPeople} />
          : <p className="text-ink-3 text-[12px]">No invitees from this calendar{ocal?.why ? ' – ' + ocal.why : ''}. For meetings with other people, use Calendar so they get the invite.</p>)}
        {(!e || invite) && ocal?.path && people.length > 0 && <p className="text-ink-3 -mt-1 text-[12px]">Invites go from {invite?.from || ocal.from} – nothing is sent until you tap Send invites.</p>}
        {!e && !allDay && <OnlinePicker cal={ocal} value={meet} onChange={m => { setMeet(m); setPicked(true) }} />}
        {invite?.meeting && <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={moveMeeting} onChange={x => setMoveMeeting(x.target.checked)} />Also move the online meeting's time</label>}
        <div className="flex flex-wrap justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          {!ask ? <Button type="submit" disabled={busy || !title.trim() || !cal || (meet.kind === 'link' && !meet.url.trim())}>{invite ? 'Next…' : e ? 'Save' : people.length ? 'Next…' : 'Add event'}</Button>
            : <><span className="self-center text-[13px]">Repeating event – change:</span>
                <Button type="button" variant="outline" disabled={busy} onClick={() => save('this')}>This event</Button>
                <Button type="button" disabled={busy} onClick={() => save('future')}>This and future</Button></>}
        </div>
      </form>
    </DialogContent>
  </Dialog>
}
