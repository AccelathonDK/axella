/* Settings → What Axella handles (setup/features.py): the 7 cards as rows. On cards show "n of m on" and More opens
   their feature switches; off cards offer "Set up – n min" (that card's mini-setup). Owner-only: delete an area's
   data. Everyone else on the access list only narrows the owner's set ("Switched off by the owner").
   Also: the quiet "This feature is off" page, and the Today cards (review for an install in use, "Not set up yet"). */
import { useEffect, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { ChevronRight, Loader2, Trash2, axi } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { useApp } from '@/lib/app'
import { featAct, useFeatures, type CardInfo, type FeaturesView } from '@/lib/features'
import { cn } from '@/lib/utils'

export const HandlesIcon = axi('one-place')

/** an on/off switch – a real button with role="switch", 52×32 like the sketch */
export function Switch({ on, onChange, label, disabled, ...rest }: { on: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean } & Record<string, unknown>) {
  return <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)} {...rest}
    className={cn('relative h-8 w-[52px] shrink-0 rounded-full transition-colors motion-reduce:transition-none disabled:opacity-50', on ? 'bg-fjord' : 'bg-ink-3')}>
    <span className={cn('bg-card absolute top-1 size-6 rounded-full transition-[left] motion-reduce:transition-none', on ? 'left-6' : 'left-1')} />
  </button>
}

export const Diamond = ({ color, size = 10 }: { color: string; size?: number }) =>
  <span aria-hidden className="ax-diamond shrink-0" style={{ color, width: size, height: size }} />

/** switch a feature or a card, asking first when a dependency changes too */
export function useSwitch() {
  const [busy, setBusy] = useState<string | null>(null)
  const run = async (key: string, action: 'feature_set' | 'card_set', body: Record<string, unknown>, done?: string) => {
    setBusy(key)
    try {
      let r = await featAct<any>(action, body)
      if (r?.confirm) {
        if (!window.confirm(r.confirm)) return null
        r = await featAct<any>(action, { ...body, confirm: true })
      }
      if (done) toast(done)
      return r
    } catch (e: any) { toast.error(e.message); return null } finally { setBusy(null) }
  }
  return { busy, run }
}

export function HandlesSettings() {
  const { ax, go } = useApp()
  const v = useFeatures(ax.apiOk)
  if (v === undefined) return <p className="text-ink-3 text-sm">Loading…</p>
  if (v === null) return <p className="text-ink-3 text-sm">The Mac mini isn't answering.</p>
  return <div className="space-y-3" data-handles="">
    <p className="text-ink-2 text-sm">{v.owner ? 'Others on your access list choose for themselves, within what you have on.'
      : "Your own choices – they only change what you see. What the owner has switched off stays off."}</p>
    {v.broken && <p className="text-dawn text-sm">Axella can't read its feature settings right now – everything stays on and changes wait.</p>}
    {v.cards.map(c => <CardRow key={c.id} c={c} v={v} />)}
    <p className="text-ink-3 text-[13px]">Always included: {v.core}.{' '}
      <button className="text-fjord font-semibold hover:underline" onClick={() => go({ kind: 'setup' })} data-handles-rerun="">Run the guided setup again</button></p>
  </div>
}

function CardRow({ c, v }: { c: CardInfo; v: FeaturesView }) {
  const { go } = useApp()
  const [open, setOpen] = useState(false)
  const { busy, run } = useSwitch()
  const [delBusy, setDelBusy] = useState(false)
  const feats = c.features.map(id => v.features[id])
  if (!c.on) return <section aria-label={c.title} data-handles-card={c.id} className="bg-card flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3">
    <Diamond color={c.color} />
    <span className="flex min-w-48 flex-1 flex-col"><span className="font-semibold">{c.title}</span><span className="text-ink-3 text-[13px]">{c.line}</span></span>
    {c.owner_off ? <span className="text-ink-3 text-[13px]">Switched off by the owner</span>
      : v.owner ? <Button size="sm" variant="outline" onClick={() => go({ kind: 'setup', card: c.id })} data-handles-setup={c.id}>Set up – {c.minutes} min</Button>
      : <Button size="sm" variant="outline" disabled={!!busy} onClick={() => run('c', 'card_set', { card: c.id, on: true }, `${c.title} on`)}>Switch on</Button>}
  </section>
  const del = async () => {
    if (!window.confirm(`Delete the data of ${c.title}? It is moved aside (restorable from the activity log for 90 days) – switch the area off first.`)) return
    setDelBusy(true)
    try { await featAct('feature_data_delete', { card: c.id }); toast(`${c.title}: data moved aside`) } catch (e: any) { toast.error(e.message) } finally { setDelBusy(false) }
  }
  return <section aria-label={c.title} data-handles-card={c.id} className={cn('bg-card space-y-3 rounded-lg border px-4 py-3', open && 'border-fjord border-2')}>
    <div className="flex flex-wrap items-center gap-3">
      <Diamond color={c.color} />
      <span className="min-w-40 flex-1 font-semibold">{c.title}</span>
      {c.not_set_up && <span className="text-ink-3 text-[12.5px]" data-not-set-up="">Not set up yet</span>}
      <span className="text-ink-3 text-[13px]">{c.n_on} of {c.n} on</span>
      <button className="text-fjord min-h-10 px-2 text-sm font-semibold" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Less' : 'More'}</button>
      <Switch on={c.on} label={c.title} disabled={!!busy} onChange={on => run('c', 'card_set', { card: c.id, on }, on ? `${c.title} on` : `${c.title} off – its data is kept`)} data-card-switch={c.id} />
    </div>
    {open && <>
      <ul className="grid gap-x-6 pl-6 sm:grid-cols-2">{feats.map(f => <li key={f.id} className="flex min-h-11 items-center justify-between gap-3 border-t text-sm" data-feature={f.id}>
        <span className="min-w-0"><span>{f.label}</span>{f.owner_off && <span className="text-ink-3 block text-[12px]">Switched off by the owner</span>}</span>
        <Switch on={f.on} label={f.label} disabled={!!busy || f.owner_off || (f.owner_only && !v.owner)}
          onChange={on => run(f.id, 'feature_set', { id: f.id, on }, `${f.label} ${on ? 'on' : 'off'}`)} data-feature-switch={f.id} />
      </li>)}</ul>
      <div className="flex flex-wrap gap-x-5 gap-y-1 pl-6 text-sm">
        {v.owner && <button className="text-fjord font-semibold hover:underline" onClick={() => go({ kind: 'setup', card: c.id })}>Change accounts and choices</button>}
        {v.owner && <button className="text-ink-2 inline-flex items-center gap-1 hover:underline" disabled={delBusy} onClick={del}>
          {delBusy ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}Delete this area's data…</button>}
      </div>
    </>}
  </section>
}

/** a page whose feature is off: quiet, with the way back */
export function FeatureOff({ label, owner_off }: { label: string; owner_off?: boolean }) {
  const { go } = useApp()
  return <div className="bg-card mx-auto mt-6 max-w-xl space-y-2 rounded-lg border p-5 text-sm" data-feature-off="">
    <div className="font-semibold">{label} is off</div>
    <p className="text-ink-2">{owner_off ? 'The owner has switched it off on this Axella.' : 'Its work has stopped and it is hidden. Nothing was deleted – switch it on again and everything is where you left it.'}</p>
    {!owner_off && <button className="text-fjord font-semibold hover:underline" onClick={() => go({ kind: 'settings', page: 'handles' })}>Settings → What Axella handles<ChevronRight className="inline size-4" /></button>}
  </div>
}

/** Today: "Review what Axella handles" (an install in use, once) and "Not set up yet" (a card whose setup was skipped, once) */
export function HandlesToday() {
  const { ax, go } = useApp()
  const v = useFeatures(ax.apiOk)
  const [gone, setGone] = useState(false)
  if (!v || gone) return null
  const later = async () => { setGone(true); try { await featAct('review_set', { what: 'later' }) } catch { /* shows again next time */ } }
  let card: ReactNode = null
  if (v.setup.review || v.setup.first_visit) card = <section className="bg-card flex flex-wrap items-center gap-3 rounded-lg border p-4" data-handles-review="">
    <span className="bg-fjord-soft text-fjord flex size-9 shrink-0 items-center justify-center rounded-md"><HandlesIcon className="size-5" /></span>
    <span className="min-w-48 flex-1"><span className="block font-semibold">Review what Axella handles</span>
      <span className="text-ink-2 block text-[13px]">{v.owner ? 'Axella can do a lot now. Pick what you want help with – everything that is on now is ticked, and nothing changes until you confirm.'
        : 'Pick what you want to see. You can only narrow what the owner has on.'}</span></span>
    <Button size="sm" onClick={() => go({ kind: 'setup' })}>Review</Button>
    <Button size="sm" variant="ghost" onClick={later}>Later</Button>
  </section>
  return <>{card}{v.owner && !card && <NotSetUpOnce cards={v.cards.filter(c => c.not_set_up)} />}</>
}

/* "Not set up yet: Trips" – on Today once per card (remembered on this device), always in Settings */
function NotSetUpOnce({ cards }: { cards: CardInfo[] }) {
  const { go } = useApp()
  const seen = (() => { try { return JSON.parse(localStorage.getItem('ax-not-set-up-seen') || '[]') as string[] } catch { return [] } })()
  const [show] = useState(() => cards.filter(c => !seen.includes(c.id)))
  useEffect(() => {
    if (!show.length) return
    try { localStorage.setItem('ax-not-set-up-seen', JSON.stringify([...new Set([...seen, ...show.map(c => c.id)])])) } catch { /* fine */ }
  }, [])   // eslint-disable-line react-hooks/exhaustive-deps
  if (!show.length) return null
  return <div className="text-ink-2 flex flex-wrap items-center gap-2 text-[13px]" data-handles-not-set-up="">
    Not set up yet: {show.map(c => <button key={c.id} className="text-fjord font-semibold hover:underline" onClick={() => go({ kind: 'setup', card: c.id })}>{c.title}</button>)}
  </div>
}

/** render children only while one of these features is on for me (unknown / offline = on) */
export function On({ f, children }: { f: string | string[]; children: ReactNode }) {
  const { ax } = useApp()
  const v = useFeatures(ax.apiOk)
  const ids = Array.isArray(f) ? f : [f]
  return v && !ids.some(id => !v.features[id] || v.features[id].on) ? null : <>{children}</>
}
