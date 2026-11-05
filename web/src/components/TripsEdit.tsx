/* Trips v2 (setup/trips.py, steps 1–2): merge, split, add an item by hand, planning (quotes → Booked / Replace / Drop)
   and the documents checklist. Every edit answers with an undo token – the toast's Undo and the activity log's Restore
   both use it (trip_undo). The checklist lives in trip-checklists.json on the Mac mini, never in what Claude reads. */
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Check, Plus, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input, NativeSelect } from '@/components/ui/input'
import { post } from '@/lib/api'

export interface EBooking { key: string; kind: string; title: string; start: string; end: string; place?: string; ref?: string; provider?: string
  status?: string; by_hand?: boolean; confirmed_by?: string | null; loose?: boolean; source?: { message_id?: string | null } }
export interface ETrip { id: string; title: string; start: string; end: string; bookings: EBooking[]; planning_view?: EBooking[]
  checklist?: { id: string; text: string; done: boolean; date?: string | null; default?: boolean }[] }

const KINDS: [string, string][] = [['flight', 'Flight'], ['hotel', 'Stay'], ['train', 'Train'], ['ferry', 'Ferry'], ['car', 'Car'],
  ['transfer', 'Transfer'], ['ticket', 'Ticket'], ['restaurant', 'Table'], ['booking', 'Other']]
const d10 = (s: string) => s.slice(0, 10)
const dshort = (s: string) => new Date(d10(s) + 'T12:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })

/** Post an edit; the toast offers Undo with the step's token. */
export async function editTrip(action: string, body: Record<string, unknown>, msg: string, reload: () => void) {
  try {
    const j = await post<{ result?: { undo?: string } } & { undo?: string }>(action, body)
    const tok = (j as any).result?.undo || (j as any).undo
    reload()
    toast(msg, tok ? { duration: 8000, action: { label: 'Undo', onClick: () => post('trip_undo', { token: tok }).then(() => { reload(); toast('Undone') }).catch(e => toast.error(e.message)) } } : undefined)
    return true
  } catch (e: any) { toast.error(e.message); return false }
}

export function MergeDialog({ t, other, onClose, reload }: { t: ETrip; other: ETrip; onClose: () => void; reload: () => void }) {
  const all = [...t.bookings, ...other.bookings.filter(b => !t.bookings.some(x => x.key === b.key))].sort((a, b) => a.start.localeCompare(b.start))
  return <Dialog open onOpenChange={o => !o && onClose()}><DialogContent className="sm:max-w-md" data-trip-merge="">
    <div className="space-y-3 p-5">
      <DialogTitle className="text-lg font-semibold">Merge “{other.title}” into “{t.title}”?</DialogTitle>
      <ul className="max-h-72 space-y-1 overflow-y-auto text-sm">{all.map(b => <li key={b.key} className="flex gap-2">
        <span className="text-ink-3 w-24 shrink-0 font-mono text-[12px]">{dshort(b.start)}</span><span className="min-w-0 flex-1 truncate">{b.title}</span></li>)}</ul>
      <p className="text-ink-3 text-[12.5px]">{all.length} bookings in one trip. Every booking keeps its mail. You can undo this.</p>
      <div className="flex gap-2"><Button size="pill" onClick={async () => { if (await editTrip('trip_merge', { id: t.id, other: other.id }, 'Trips merged', reload)) onClose() }}><Check />Merge</Button>
        <Button size="pill" variant="ghost" onClick={onClose}>Cancel</Button></div>
    </div></DialogContent></Dialog>
}

export function SplitDialog({ t, onClose, reload }: { t: ETrip; onClose: () => void; reload: () => void }) {
  const [keys, setKeys] = useState<Set<string>>(new Set())
  const [at, setAt] = useState('')
  const [name, setName] = useState('')
  const picked = at ? t.bookings.filter(b => d10(b.start) >= at).map(b => b.key) : [...keys]
  const okN = picked.length > 0 && picked.length < t.bookings.length
  return <Dialog open onOpenChange={o => !o && onClose()}><DialogContent className="sm:max-w-md" data-trip-split="">
    <form className="space-y-3 p-5" onSubmit={async e => { e.preventDefault(); if (await editTrip('trip_split', at ? { id: t.id, at, title: name } : { id: t.id, keys: picked, title: name }, 'Split – “' + name + '” is a trip of its own', reload)) onClose() }}>
      <DialogTitle className="text-lg font-semibold">Split “{t.title}”</DialogTitle>
      <p className="text-ink-3 text-[13px]">Pick the bookings for the new trip – or split at a date.</p>
      <ul className="max-h-60 space-y-1 overflow-y-auto">{t.bookings.map(b => <li key={b.key}><label className="flex items-center gap-2 text-sm">
        <Checkbox disabled={!!at} checked={picked.includes(b.key)} onCheckedChange={v => { const n = new Set(keys); if (v) n.add(b.key); else n.delete(b.key); setKeys(n) }} />
        <span className="text-ink-3 w-24 shrink-0 font-mono text-[12px]">{dshort(b.start)}</span><span className="min-w-0 flex-1 truncate">{b.title}</span></label></li>)}</ul>
      <label className="flex items-center gap-2 text-[13px]">Or everything from <Input type="date" className="w-auto" value={at} min={d10(t.start)} max={d10(t.end)} onChange={e => setAt(e.target.value)} />
        {at && <button type="button" className="text-ink-3" aria-label="No date" onClick={() => setAt('')}><X className="size-4" /></button>}</label>
      <Input value={name} maxLength={120} placeholder="Name of the new trip" onChange={e => setName(e.target.value)} aria-label="Name of the new trip" />
      <div className="flex gap-2"><Button size="pill" type="submit" disabled={!okN || !name.trim()}><Check />Split</Button><Button size="pill" variant="ghost" type="button" onClick={onClose}>Cancel</Button></div>
    </form></DialogContent></Dialog>
}

const myZone = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' } catch { return 'UTC' } }
const zones = (): string[] => { try { return (Intl as any).supportedValuesOf('timeZone') } catch { return ['UTC', myZone()] } }

export function ItemDialog({ t, onClose, reload }: { t: ETrip; onClose: () => void; reload: () => void }) {
  const [f, setF] = useState({ kind: 'transfer', title: '', day: d10(t.start), time: '', until: '', untilTime: '', tz: myZone(), place: '', ref: '', travellers: '' })
  const zl = useMemo(zones, [])
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value })
  const when = (dd: string, tt: string) => dd + (tt ? 'T' + tt : '')
  return <Dialog open onOpenChange={o => !o && onClose()}><DialogContent className="sm:max-w-md" data-trip-item-add="">
    <form className="space-y-2.5 p-5 text-sm" onSubmit={async e => { e.preventDefault()
      const body: Record<string, unknown> = { id: t.id, kind: f.kind, title: f.title, start: when(f.day, f.time), tz: f.tz, place: f.place, ref: f.ref,
        travellers: f.travellers.split(',').map(x => x.trim()).filter(Boolean) }
      if (f.until) body.end = when(f.until, f.untilTime)
      if (await editTrip('trip_item_add', body, 'Added to ' + t.title, reload)) onClose() }}>
      <DialogTitle className="text-lg font-semibold">Add an item to “{t.title}”</DialogTitle>
      <div className="flex gap-2"><NativeSelect className="w-auto" aria-label="Kind" value={f.kind} onChange={set('kind')}>{KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</NativeSelect>
        <Input value={f.title} maxLength={160} placeholder="What it is" aria-label="Name" onChange={set('title')} autoFocus /></div>
      <div className="grid grid-cols-[3.5rem_1fr_7rem] items-center gap-2 text-[12.5px]">
        <span>Start</span><Input type="date" value={f.day} onChange={set('day')} aria-label="Start day" /><Input type="time" value={f.time} onChange={set('time')} aria-label="Start time" />
        <span>End</span><Input type="date" value={f.until} min={f.day} onChange={set('until')} aria-label="End day (optional)" /><Input type="time" value={f.untilTime} onChange={set('untilTime')} aria-label="End time" />
      </div>
      <label className="block text-[12.5px]"><span className="text-ink-3">Time zone of the place (local time)</span>
        <Input list="ax-zones" value={f.tz} onChange={set('tz')} aria-label="Time zone" /><datalist id="ax-zones">{zl.map(z => <option key={z} value={z} />)}</datalist></label>
      <div className="grid grid-cols-2 gap-2"><Input value={f.place} maxLength={80} placeholder="Place" aria-label="Place" onChange={set('place')} />
        <Input value={f.ref} maxLength={40} placeholder="Reference" aria-label="Reference" onChange={set('ref')} className="font-mono" /></div>
      <Input value={f.travellers} placeholder="Travellers, comma-separated" aria-label="Travellers" onChange={set('travellers')} />
      <div className="flex gap-2 pt-1"><Button size="pill" type="submit" disabled={!f.title.trim() || !f.day || !f.tz || (!!f.until && f.until < f.day)}><Check />Add</Button>
        <Button size="pill" variant="ghost" type="button" onClick={onClose}>Cancel</Button></div>
    </form></DialogContent></Dialog>
}

/** A trip's planning: quotes and enquiries, never bookings. */
export function TripPlanning({ t, reload }: { t: ETrip; reload: () => void }) {
  const list = t.planning_view || []
  if (!list.length) return null
  return <div className="bg-bg-2/40 space-y-2 border-t px-4 py-3" data-trip-plan="">
    <div className="ax-label">Planning – quotes and enquiries</div>
    {list.map(q => <div key={q.key} className="space-y-1 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-2"><span className="text-ink-3 font-mono text-[12px]">{dshort(q.start)}</span><span>{q.title}</span>
        <span className="text-ink-3 text-[12.5px]">{[q.provider, q.ref && 'ref ' + q.ref].filter(Boolean).join(' · ')}</span></div>
      {q.confirmed_by && <p className="text-fjord text-[12.5px]">The confirmation has arrived.</p>}
      <div className="flex flex-wrap gap-2">
        {q.confirmed_by
          ? <Button size="pill" onClick={() => editTrip('trip_plan_replace', { id: t.id, key: q.key, by: q.confirmed_by, title: q.title }, 'The booking is in, the quote gone', reload)}><Check />Replace with the booking</Button>
          : <Button size="pill" variant="outline" onClick={() => editTrip('trip_plan_booked', { id: t.id, key: q.key, title: q.title }, 'Now a booking in ' + t.title, reload)}><Check />Booked</Button>}
        <Button size="pill" variant="ghost" onClick={() => editTrip('trip_plan_drop', { id: t.id, key: q.key, title: q.title }, 'Dropped', reload)}><X />Drop</Button>
      </div></div>)}
  </div>
}

/** Documents: passports, visa/eTA, insurance, vaccinations, your own items – ticked by you; a date only if you set one. */
export function Checklist({ t, reload }: { t: ETrip; reload: () => void }) {
  const [text, setText] = useState('')
  const items = t.checklist || []
  const act = async (action: string, body: Record<string, unknown>) => { try { await post(action, { id: t.id, ...body }); reload() } catch (e: any) { toast.error(e.message) } }
  return <div className="space-y-1.5 border-t px-4 py-3" data-trip-checklist="">
    <div className="ax-label">Documents</div>
    {items.map(i => <div key={i.id} className="flex items-center gap-2 text-sm">
      <Checkbox checked={i.done} onCheckedChange={v => act('trip_check_set', { item: i.id, done: !!v })} aria-label={i.text} />
      <span className={i.done ? 'text-ink-3 line-through' : ''}>{i.text}</span>
      <Input type="date" className="ml-auto h-8 w-auto text-[12px]" value={i.date || ''} onChange={e => act('trip_check_set', { item: i.id, date: e.target.value || null })} aria-label={'Date for ' + i.text} />
      <button type="button" className="text-ink-3 hover:text-ink" aria-label={'Remove ' + i.text} onClick={() => act('trip_check_remove', { item: i.id })}><X className="size-4" /></button>
    </div>)}
    <form className="flex gap-2 pt-1" onSubmit={e => { e.preventDefault(); if (text.trim()) act('trip_check_add', { text }).then(() => setText('')) }}>
      <Input value={text} maxLength={120} placeholder="Add an item…" onChange={e => setText(e.target.value)} aria-label="Add a checklist item" />
      <Button size="pill" variant="outline" type="submit" disabled={!text.trim()}><Plus />Add</Button></form>
    <p className="text-ink-3 text-[11.5px]">Only you tick these – Axella reads nothing for them. A date only if you give one. Kept on the Mac mini, never sent to Claude.</p>
  </div>
}
