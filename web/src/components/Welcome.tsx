/* Back-from-away briefing (setup/away.py, setup/local-tasks/return-briefing.md): the first digest after 2+ days away.
   Welcome back + what still needs you (at most 10 lines, "and N more"), coming up this week, and "Sorted itself out"
   in groups with Archive all – handled in Axella only, nothing moves in Mail, one Undo for the whole batch. Each group
   opens, and an item can be kept back first. "Catch me up since…" (digest picker) asks for one for a chosen date. */
import { useState } from 'react'
import { toast } from 'sonner'
import { Archive, ChevronDown, ChevronRight, Palmtree } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useApp } from '@/lib/app'
import type { AwayGroup, WrapLine } from '@/lib/types'
import { cn, isoDate } from '@/lib/utils'

const LABEL: Record<string, [string, string]> = {
  answered: ['thread was answered or settled', 'threads were answered or settled'], events: ['event has passed', 'events have passed'],
  bulk: ['newsletter, notification or FYI', 'newsletters, notifications and FYIs'], calls: ['call with a message already handled', 'calls with messages already handled'] }
const label = (g: AwayGroup, n: number) => LABEL[g.key] ? LABEL[g.key][n === 1 ? 0 : 1] : g.label
const jsonName = (n?: string) => (n || '').replace(/^.*\//, '').replace(/\.md$/, '.json')

export function WelcomeCard() {
  const { ax, go } = useApp()
  const cur = ax.current, w = cur?.data.away
  const [open, setOpen] = useState<string | null>(null)
  const [keep, setKeep] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  if (!w || !w.headline) return null
  const groups = (w.sorted?.groups || []).map(g => ({ ...g, left: g.items.filter(i => !ax.isHandled(i.id)) }))
  const left = groups.reduce((n, g) => n + g.left.filter(i => !keep.has(i.id)).length, 0)
  const jump = (l: WrapLine) => {
    if (l.item_id) {
      const el = document.querySelector(`[data-item-row="${CSS.escape(String(l.item_id))}"]`)
      if (el) { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); el.classList.add('ax-flash'); setTimeout(() => el.classList.remove('ax-flash'), 1600); return }
      return go({ kind: 'briefing' })
    }
    if (l.task_id) return go({ kind: 'todo', tab: 'tasks' })
  }
  async function archiveAll() {
    setBusy(true)
    try {
      const r: any = await ax.act('away_archive', { digest: jsonName(cur?.name), keep: [...keep], title: 'Archive all' }, ['state'])
      const { batch, count } = r?.result || {}
      toast.success(`${count} handled in Axella – nothing moved in Mail`, { duration: 12000,
        action: { label: 'Undo', onClick: () => { ax.act('away_undo', { batch, title: 'Undo Archive all' }, ['state']).then(() => toast('Back as they were'), (e: any) => toast.error(e.message)) } } })
    } catch (e: any) { toast.error('Not archived: ' + e.message) } finally { setBusy(false) }
  }
  const more = (w.still_total || 0) - (w.still?.length || 0)
  return <Card className="space-y-4 p-4" data-welcome="">
    <div className="flex items-start gap-3">
      <span className="bg-fjord-soft text-fjord flex size-9 shrink-0 items-center justify-center rounded-md"><Palmtree className="size-[18px]" /></span>
      <div className="min-w-0"><div className="ax-label">Back from away{w.absence?.from ? ` · ${fmt(w.absence.from)}–${fmt(w.absence.to)}` : ''}</div>
        <div className="mt-1 text-[17px] leading-snug font-semibold">{w.headline}</div></div>
    </div>
    <Lines title="Still needs you" lines={w.still} onPick={jump} />
    {more > 0 && <button className="text-fjord -mt-2 text-[13px] font-semibold hover:underline" onClick={() => go({ kind: 'briefing' })}>and {more} more</button>}
    <Lines title="Coming up this week" lines={w.coming} onPick={jump} />
    {groups.length > 0 && <div data-sorted="">
      <div className="ax-label mb-1">Sorted itself out</div>
      <div className="divide-y rounded-md border">
        {groups.map(g => <Group key={g.key} g={g} n={g.left.length} open={open === g.key} onToggle={() => setOpen(o => o === g.key ? null : g.key)}
          keep={keep} onKeep={id => setKeep(k => { const x = new Set(k); x.has(id) ? x.delete(id) : x.add(id); return x })} />)}
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-3">
        <Button size="pill" disabled={busy || !left} onClick={archiveAll} data-archive-all=""><Archive />{left ? `Archive all ${left}` : keep.size ? 'Nothing else to archive' : 'All handled'}</Button>
        <span className="text-ink-3 text-[12.5px]">Marks them handled in Axella. Nothing is moved or deleted in Mail.</span>
      </div>
    </div>}
  </Card>
}

function Group({ g, n, open, onToggle, keep, onKeep }: { g: AwayGroup & { left: AwayGroup['items'] }; n: number; open: boolean; onToggle: () => void; keep: Set<string>; onKeep: (id: string) => void }) {
  const kept = g.left.filter(i => keep.has(i.id)).length
  return <div>
    <button type="button" onClick={onToggle} aria-expanded={open} className="hover:bg-bg-2 flex w-full items-center gap-2 px-3 py-2 text-left text-sm">
      {open ? <ChevronDown className="text-ink-3 size-4" /> : <ChevronRight className="text-ink-3 size-4" />}
      <span className={cn('min-w-0 flex-1', !n && 'text-ink-3')}><b className="font-semibold tabular-nums">{n}</b> {label(g, n)}{kept ? ` · ${kept} kept back` : ''}</span>
    </button>
    {open && <ul className="max-h-72 space-y-0.5 overflow-y-auto px-3 pb-2 pl-9 text-[13.5px]">
      {g.left.map(i => <li key={i.id} className="flex items-center gap-2">
        <label className="flex min-w-0 flex-1 items-center gap-2">
          <input type="checkbox" checked={keep.has(i.id)} onChange={() => onKeep(i.id)} aria-label={'Keep back: ' + (i.headline || '')} />
          <span className={cn('min-w-0 truncate', keep.has(i.id) && 'text-ink-3')}>{i.headline || '(no subject)'}{i.who ? <span className="text-ink-3"> · {i.who}</span> : null}</span>
        </label>
      </li>)}
      {!g.left.length && <li className="text-ink-3">All handled.</li>}
      {g.left.length > 0 && <li className="text-ink-3 pt-1 text-[12px]">Tick one to keep it back – it stays open.</li>}
    </ul>}
  </div>
}

function Lines({ title, lines, onPick }: { title: string; lines?: WrapLine[]; onPick: (l: WrapLine) => void }) {
  if (!lines?.length) return null
  return <div>
    <div className="ax-label mb-1">{title}</div>
    <ul className="space-y-1 text-[14.5px]">{lines.map((l, i) => <li key={i}>{l.item_id || l.task_id
      ? <button type="button" onClick={() => onPick(l)} className="text-left hover:underline decoration-muted-foreground/50 underline-offset-2">{l.text}</button>
      : l.text}</li>)}</ul>
  </div>
}

const fmt = (s?: string) => { const d = s ? new Date(s + 'T12:00') : null; return d && !isNaN(d.getTime()) ? d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : '' }

/** Digest picker → "Catch me up since…": a briefing for an absence Axella didn't know about. */
export function CatchUpDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { ax } = useApp()
  const y = new Date(); y.setDate(y.getDate() - 1)
  const def = new Date(); def.setDate(def.getDate() - 7)
  const [since, setSince] = useState(isoDate(def))
  const [busy, setBusy] = useState(false)
  async function go() {
    setBusy(true)
    try {
      const r: any = await ax.act('away_catchup', { since, title: 'Catch me up since ' + since }, [])
      toast(r?.result === 'already queued' ? 'A catch-up is already on its way' : 'Catch-up queued – it shows up as a new digest in 10–30 minutes')
      onClose()
    } catch (e: any) { toast.error('Not queued: ' + e.message) } finally { setBusy(false) }
  }
  return <Dialog open={open} onOpenChange={o => !o && onClose()}>
    <DialogContent className="sm:w-[min(440px,92vw)]">
      <form className="space-y-3 p-5" onSubmit={e => { e.preventDefault(); go() }} data-catchup="">
        <DialogTitle className="text-lg font-semibold">Catch me up since…</DialogTitle>
        <p className="text-ink-2 text-sm">One calm briefing of what still needs you since that day – the rest grouped as sorted itself out, with Archive all. Nothing is moved or sent.</p>
        <Input type="date" value={since} max={isoDate(y)} onChange={e => setSince(e.target.value)} aria-label="Since" />
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy || !ax.apiOk || !since || since > isoDate(y)}><Palmtree />Catch me up</Button></div>
      </form>
    </DialogContent>
  </Dialog>
}
