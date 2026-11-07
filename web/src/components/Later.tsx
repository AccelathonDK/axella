/* What you pushed to Later (GET later – axella-actions.later_view): one quiet line at the bottom of Today, "9 waiting
   for later · next back tomorrow 07:00", that opens the list in place – grouped by when each comes back, with Bring
   back now, Change time and Done. The actions are the ordinary undo / snooze / done; nothing new is stored. */
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { AlarmClock, Check, ChevronRight, Loader2, Undo2 } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { ItemSheet } from '@/components/ItemSheet'
import { LaterMenu } from '@/components/ItemRow'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { CH_ICON, ITEM_ICON } from '@/lib/sections'
import type { Item } from '@/lib/types'
import { cn } from '@/lib/utils'

interface Later { id: string; until: string; title: string; item: Item | null }

const hm = (d: Date) => d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
function dayOf(d: Date, now = new Date()) {
  const a = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  return Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() - a) / 864e5)
}
/** "later today", "tomorrow", "Mon 9 Nov" – the group a time belongs to */
export function laterGroup(d: Date, now = new Date()) {
  const n = dayOf(d, now)
  return n <= 0 ? 'Later today' : n === 1 ? 'Tomorrow' : d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
}
/** "back 17:00", "back tomorrow 07:00", "back Mon 07:00" */
export function backAt(d: Date, now = new Date()) {
  const n = dayOf(d, now)
  return 'back ' + (n <= 0 ? '' : n === 1 ? 'tomorrow ' : n < 7 ? d.toLocaleDateString('en-GB', { weekday: 'short' }) + ' ' : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) + ' ') + hm(d)
}

/* wide screens: under "Open the full briefing" in the right column; narrow ones: at the bottom of Today */
function useWide() {
  const q = '(min-width: 1100px)'
  const [wide, setWide] = useState(() => matchMedia(q).matches)
  useEffect(() => { const m = matchMedia(q); const h = () => setWide(m.matches); m.addEventListener('change', h); return () => m.removeEventListener('change', h) }, [])
  return wide
}

export function LaterLine({ place }: { place: 'side' | 'main' }) {
  const wide = useWide()
  return (place === 'side') === wide ? <LaterInner /> : null
}

function LaterInner() {
  const { ax } = useApp()
  const [list, setList] = useState<Later[] | null>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [sheet, setSheet] = useState<Item | null>(null)
  // a failed answer (the Mac mini busy, a 502 while the page loads) is asked again – 3 s, 10 s, 30 s – not left empty
  const load = useCallback(function ask(attempt = 0): Promise<void> {
    return get<{ items: Later[] }>('later').then(j => setList(Array.isArray(j.items) ? j.items : []))
      .catch(() => { if (attempt < 3) setTimeout(() => ask(attempt + 1), [3000, 10000, 30000][attempt]) })
  }, [])
  // follows Done / Later / Undo anywhere on the page (the handled state changes)
  const snoozedKey = Object.entries(ax.state).filter(([, v]: any) => v?.status === 'snoozed').map(([k, v]: any) => k + v.until).sort().join('|')
  useEffect(() => { if (ax.apiOk) load() }, [ax.apiOk, snoozedKey, load])
  const now = new Date()
  const waiting = (list || []).filter(x => new Date(x.until) > now)
  if (!ax.apiOk || !waiting.length) return null
  const mailRef = (it: Item | null) => it && it.channel === 'mail' && it.account && it.message_id
    ? { account: it.account, message_id: it.message_id, channel: 'mail', sender: (it.from?.address || '').toLowerCase() } : { channel: it?.channel || '' }
  async function run(x: Later, key: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(x.id + key)
    try { await fn(); toast(ok); await ax.refresh(['state']); await load() }
    catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(null) }
  }
  const groups: [string, Later[]][] = []
  for (const x of waiting) {
    const g = laterGroup(new Date(x.until), now)
    const last = groups[groups.length - 1]
    if (last && last[0] === g) last[1].push(x); else groups.push([g, [x]])
  }
  const next = new Date(waiting[0].until)
  return <div className="space-y-2" data-later="">
    {/* the same quiet link as "Open the full briefing" – there when something waits, never in the way */}
    <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open} data-later-line="" title="What you pushed to Later"
      className={cn('text-fjord hover:bg-bg-2 flex w-full items-center justify-center gap-1.5 rounded-md py-2 text-sm font-medium', open && 'bg-bg-2')}>
      <AlarmClock className="size-4 shrink-0" />
      <span>{waiting.length} for later · next {backAt(next, now).replace(/^back /, '')}</span>
      <ChevronRight className={cn('size-4 transition-transform duration-[480ms]', open && 'rotate-90')} />
    </button>
    {open && <div className="ax-reveal bg-card overflow-hidden rounded-lg border" data-later-list="">
      {groups.map(([g, xs]) => <div key={g}>
        <div className="ax-label bg-bg-2/50 px-4 py-1.5">{g}</div>
        <div className="divide-y">
          {xs.map(x => {
            const it = x.item
            const I = (it?.channel && CH_ICON[it.channel]) || (it ? ITEM_ICON[it.section] : null) || AlarmClock
            const title = it?.headline || it?.subject || x.title || 'Item'
            const who = it?.from?.name || it?.from?.address || ''
            const b = (k: string) => busy === x.id + k
            return <div key={x.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5" data-later-item={x.id}>
              <I className="text-ink-3 size-4 shrink-0" />
              <div className="min-w-0 flex-1 basis-48">
                {it ? <button type="button" className="block max-w-full truncate text-left text-[14.5px] font-medium hover:underline" onClick={() => setSheet(it)}>{title}</button>
                  : <div className="truncate text-[14.5px] font-medium">{title}</div>}
                <div className="text-ink-3 text-[12.5px]">{[who, backAt(new Date(x.until), now)].filter(Boolean).join(' · ')}</div>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <Button size="pill" variant="outline" disabled={!!busy} data-later-act="back"
                  onClick={() => run(x, 'back', () => ax.act('undo', { item_id: x.id, ...mailRef(it) }, []), 'Back in Today')}>
                  {b('back') ? <Loader2 className="animate-spin" /> : <Undo2 />}Bring back</Button>
                <LaterMenu label="Change time" full busy={b('time')} disabled={!!busy}
                  onPick={(d, l) => run(x, 'time', () => ax.act('snooze', { item_id: x.id, until: d.toISOString(), title }, []), 'Back ' + l)} />
                <Button size="pill" variant="ghost" disabled={!!busy} data-later-act="done"
                  onClick={() => run(x, 'done', () => ax.act('done', { item_id: x.id, title, ...mailRef(it) }, []), 'Marked as done')}>
                  {b('done') ? <Loader2 className="animate-spin" /> : <Check />}Done</Button>
              </div>
            </div>
          })}
        </div>
      </div>)}
    </div>}
    {/* opened from the Later list = you're on it now: the full actions (Send, Done, Later), not the handled Undo row */}
    {sheet && <ItemSheet it={sheet} handled={false} onClose={() => { setSheet(null); load() }} onCal={() => setSheet(null)} />}
  </div>
}
