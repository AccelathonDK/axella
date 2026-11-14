/* The sweep offered outside digest hours (setup/sweep_offer.py): one quiet row at the top of Today when the owner is
   here, the schedule has a gap and something new has arrived. Now · In an hour · Dismiss – never a push, never a sweep
   without a tap. "Is the owner here" is decided on this device: the page is visible and focused and there was input in
   the last minute; only then is the Mac mini asked (owner only – everyone else gets 403 once and never asks again). */
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Radar, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { SwipeHint, useRowSwipe } from '@/components/ItemRow'
import { Unreachable, get } from '@/lib/api'
import { useApp } from '@/lib/app'
import type { RowApi } from '@/lib/rows'

interface Offer { show: boolean; why?: string; gap?: string; kind?: string; count?: number; text?: string; ask_stop?: boolean; stop_text?: string | null }

const ACTIVE_MS = 60e3
const DAYS = ['Mondays', 'Tuesdays', 'Wednesdays', 'Thursdays', 'Fridays', 'Saturdays', 'Sundays']
/** how Settings names a kind of gap ("Not on Saturdays") – the same words as sweep_offer.kind_text */
export function offerKindText(k: string) {
  if (k.startsWith('day-')) return 'on ' + (DAYS[Number(k.slice(4))] || k)
  return ({ evening: 'in the evening', morning: 'in the morning', daytime: 'between digests' } as Record<string, string>)[k] || k
}
const hhmm = (iso: string) => new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })

/** true while the owner is plainly here: visible, focused, input in the last 60 s */
function usePresent() {
  const last = useRef(Date.now())
  const [present, setPresent] = useState(() => document.visibilityState === 'visible' && document.hasFocus())
  useEffect(() => {
    const check = () => setPresent(document.visibilityState === 'visible' && document.hasFocus() && Date.now() - last.current < ACTIVE_MS)
    const input = () => { last.current = Date.now(); check() }
    const evs = ['pointerdown', 'keydown', 'touchstart', 'wheel', 'scroll'] as const
    evs.forEach(e => addEventListener(e, input, { passive: true, capture: true }))
    document.addEventListener('visibilitychange', check); addEventListener('focus', check); addEventListener('blur', check)
    const t = setInterval(check, 5000)
    return () => {
      evs.forEach(e => removeEventListener(e, input, { capture: true } as EventListenerOptions))
      document.removeEventListener('visibilitychange', check); removeEventListener('focus', check); removeEventListener('blur', check); clearInterval(t)
    }
  }, [])
  return present
}

let notOwner = false
export function SweepOfferRow() {
  const { ax } = useApp()
  const present = usePresent()
  const [o, setO] = useState<Offer | null>(null)
  const [note, setNote] = useState<{ text: string; undo?: boolean } | null>(null)
  const [busy, setBusy] = useState(false)
  const api = useRef<RowApi>({})
  const sw = useRowSwipe(api)

  useEffect(() => {
    if (!present || !ax.apiOk || notOwner) return
    let live = true
    const load = () => get<Offer>('sweep_offer').then(j => { if (live) setO(j) },
      e => { if (!(e instanceof Unreachable)) notOwner = /owner|403/i.test(String(e.message)) || notOwner; if (live) setO(null) })
    load()
    const t = setInterval(load, 60e3)                       // the count follows; a digest that ran makes the row go
    return () => { live = false; clearInterval(t) }
  }, [present, ax.apiOk, ax.current?.meta.date?.getTime()])

  async function act(a: 'now' | 'later' | 'dismiss' | 'stop' | 'keep') {
    if (!o?.gap) return
    setBusy(true)
    try {
      const r = await ax.act<{ result: any }>('sweep_offer', { act: a, gap: o.gap }, ['schedule'])
      if (a === 'now') { setNote({ text: 'Sweeping… the digest is on its way.' }); setTimeout(() => setNote(null), 6000) }
      if (a === 'later') { setNote({ text: `Sweep at ${hhmm(r.result.at)}.`, undo: true }); setTimeout(() => setNote(n => n?.undo ? null : n), 6000) }
      if (a === 'stop') toast(r.result.text)
      setO(a === 'keep' ? { ...o, ask_stop: false } : null)
    } catch (e: any) { toast.error('Failed: ' + e.message); setO(null) }
    finally { setBusy(false) }
  }
  async function undo() {
    setNote(null)
    try { await ax.act('sweep_offer', { act: 'undo' }, ['schedule']); toast('Sweep cancelled') } catch (e: any) { toast.error('Failed: ' + e.message) }
  }
  api.current = o?.show && !o.ask_stop ? { dismiss: () => act('dismiss') } : {}

  const row = 'bg-surface border-line text-ink-2 flex min-h-11 flex-wrap items-center gap-x-2.5 gap-y-1 rounded-lg border px-3 py-1.5 text-sm'
  const btns = 'flex items-center gap-1 max-sm:w-full max-sm:pl-[26px]'      // phone: the buttons on their own line, under the text
  if (note) return <div className={row} data-sweep-offer="note" role="status">
    <Radar className="text-ink-3 size-4 shrink-0" /><span className="flex-1">{note.text}</span>
    {note.undo && <Button size="pill" variant="ghost" onClick={undo}>Undo</Button>}
  </div>
  if (!o?.show) return null
  return <div className="relative overflow-hidden rounded-lg" data-sweep-offer={o.kind}>
    {sw.hint && <SwipeHint h={sw.hint} dx={sw.dx} />}
    <div className={row + ' relative touch-pan-y'} style={sw.style} {...sw.handlers}>
      <Radar className="text-ink-3 size-4 shrink-0" />
      {o.ask_stop ? <>
        <span className="min-w-0 flex-1" data-sweep-offer-text="">{o.stop_text}</span>
        <div className={btns}>
          <Button size="pill" variant="outline" disabled={busy} onClick={() => act('stop')}>Stop</Button>
          <Button size="pill" variant="ghost" disabled={busy} onClick={() => act('keep')}>Keep offering</Button></div>
      </> : <>
        <span className="min-w-0 flex-1" data-sweep-offer-text="">{o.text}</span>
        <div className={btns}>
          <Button size="pill" variant="approve" disabled={busy} onClick={() => act('now')}>Now</Button>
          <Button size="pill" variant="ghost" disabled={busy} onClick={() => act('later')}>In an hour</Button>
          <Button size="icon-pill" variant="ghost" disabled={busy} aria-label="Dismiss" className="max-sm:ml-auto" onClick={() => act('dismiss')}><X /></Button></div>
      </>}
    </div>
  </div>
}
