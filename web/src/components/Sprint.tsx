/* Reply sprint (setup/sprint.py): when 3 or more quick replies are ready – a short Axella draft on a P1, P2 or Still
   open mail, never a private contact, a protected workplace or a flagged item – Today shows a card and To do a line.
   Start opens them one after another in the ordinary item sheet: Send (its own two taps or a swipe right, then the
   countdown with Undo – the same reply_send as everywhere), edit in place, Send later or Later, Skip, Done without
   reply. There is no "send all". Leaving midway keeps what's done; the card shows what's left. No scores, no streaks. */
import { useCallback, useEffect, useState } from 'react'
import * as D from '@radix-ui/react-dialog'
import { Reply, X, Zap } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { ItemSheet } from '@/components/ItemSheet'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import type { Item } from '@/lib/types'

type SItem = Item & { sprint?: { seconds: number; owed: boolean } }
interface SView { items: SItem[]; count: number; seconds: number; minutes: number; show: boolean; min: number; digest: string | null }
const SKIP = 'ax-sprint-skipped', HINT = 'ax-sprint-hint'

function useSprint() {
  const { ax } = useApp()
  const [v, setV] = useState<SView | null>(null)
  const load = useCallback(() => { if (ax.apiOk) get<SView>('sprint').then(r => setV(Array.isArray((r as any).items) ? r : null)).catch(() => setV(null)) }, [ax.apiOk])
  useEffect(() => { load() }, [load, ax.current?.name])
  // something was sent, done or snoozed elsewhere: the count follows (a short pause lets the Mac mini write it)
  const handledN = Object.keys(ax.state || {}).length
  useEffect(() => { const t = setTimeout(load, 800); return () => clearTimeout(t) }, [handledN, load])
  useEffect(() => { const f = () => load(); window.addEventListener('ax-scheduled-changed', f); return () => window.removeEventListener('ax-scheduled-changed', f) }, [load])
  return { v, load }
}

export const sprintLine = (n: number, min: number) => `${n} quick ${n === 1 ? 'reply' : 'replies'} ready · about ${min} minute${min === 1 ? '' : 's'}`

/** Today: the offer. */
export function SprintCard() {
  const { v, load } = useSprint()
  const [open, setOpen] = useState(false)
  if (!v && !open) return null
  return <>
    {v?.show && !open && <section className="bg-card flex flex-wrap items-center gap-3 rounded-lg border p-4" data-sprint-card="">
      <span className="bg-fjord-soft text-fjord flex size-9 shrink-0 items-center justify-center rounded-md"><Zap className="size-[18px]" /></span>
      <div className="min-w-0 flex-1"><div className="font-semibold">{sprintLine(v!.count, v!.minutes)}</div>
        <div className="text-ink-3 text-[13px]">Short drafts, one after another – each one goes only when you tap Send.</div></div>
      <Button size="pill" onClick={() => setOpen(true)}><Reply />Start</Button>
    </section>}
    {open && <SprintScreen items={v?.items || []} onExit={() => { setOpen(false); load() }} />}
  </>
}

/** To do: the same offer as one line. */
export function SprintLine() {
  const { v, load } = useSprint()
  const [open, setOpen] = useState(false)
  if (!v && !open) return null
  return <>
    {v?.show && !open && <div className="bg-card flex items-center gap-2.5 rounded-lg border px-4 py-2.5 text-sm" data-sprint-line="">
      <Zap className="text-fjord size-4 shrink-0" /><span className="min-w-0 flex-1">{sprintLine(v!.count, v!.minutes)}</span>
      <button className="text-fjord font-semibold hover:underline" onClick={() => setOpen(true)}>Start</button></div>}
    {open && <SprintScreen items={v?.items || []} onExit={() => { setOpen(false); load() }} />}
  </>
}

type Tally = { sent: number; later: number; done: number; skipped: number }
const readSkipped = (): string[] => { try { return JSON.parse(sessionStorage.getItem(SKIP) || '[]') } catch { return [] } }

/** One reply at a time in the item sheet; the end says what happened. */
export function SprintScreen({ items, onExit }: { items: SItem[]; onExit: () => void }) {
  const { ax } = useApp()
  // skipped earlier in this tab: still in the sprint, but last
  const [queue] = useState(() => { const sk = new Set(readSkipped()); return [...items.filter(i => !sk.has(i.id)), ...items.filter(i => sk.has(i.id))] })
  const [i, setI] = useState(0)
  const [t, setT] = useState<Tally>({ sent: 0, later: 0, done: 0, skipped: 0 })
  const [hint] = useState(() => { try { const seen = localStorage.getItem(HINT); localStorage.setItem(HINT, '1'); return !seen } catch { return true } })
  const next = (k: keyof Tally) => { setT(x => ({ ...x, [k]: x[k] + 1 })); setI(x => x + 1) }
  const cur = queue[i]
  // handled meanwhile (another tab, the iPhone): passed over, not counted
  useEffect(() => { if (cur && ax.isHandled(cur.id)) setI(x => x + 1) }, [cur?.id])   // eslint-disable-line react-hooks/exhaustive-deps
  if (!cur) return <SprintEnd t={t} onClose={onExit} />
  return <ItemSheet key={cur.id} it={cur} handled={ax.isHandled(cur.id)} onClose={onExit} onCal={() => {}}
    sprint={{ pos: i + 1, total: queue.length, seconds: cur.sprint?.seconds, owed: cur.sprint?.owed, hint: hint && i === 0,
      onSkip: () => { try { sessionStorage.setItem(SKIP, JSON.stringify([...new Set([...readSkipped(), cur.id])].slice(-50))) } catch { /* private mode */ } next('skipped') },
      onHandled: () => { const st = (ax.state || {})[cur.id] as { status?: string; how?: string } | undefined
        next(st?.how === 'sent' ? 'sent' : st?.status === 'snoozed' ? 'later' : 'done') },
      onScheduled: () => next('later') }} />
}

export function sprintSummary(t: Tally) {
  const parts = [t.sent && `${t.sent} sent`, t.later && `${t.later} for later`, t.done && `${t.done} done without reply`, t.skipped && `${t.skipped} skipped`].filter(Boolean)
  if (!t.sent && !t.later && !t.done) return t.skipped ? `${t.skipped} skipped – they're still on Today.` : 'Nothing left to do here.'
  return parts.join(', ') + ' – nice.'
}

function SprintEnd({ t, onClose }: { t: Tally; onClose: () => void }) {
  return <D.Root open onOpenChange={o => !o && onClose()}>
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-[var(--ax-scrim)]" />
      <D.Content aria-describedby={undefined} data-sprint-end="" className="bg-card fixed top-[28%] left-1/2 z-50 w-[min(420px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 sm:top-1/2 rounded-lg border p-5 shadow-float">
        <div className="flex items-start gap-3">
          <D.Title className="flex-1 text-[17px] font-semibold">Reply sprint done</D.Title>
          <D.Close className="text-ink-3 hover:bg-bg-2 -mt-1 -mr-1 flex size-8 items-center justify-center rounded-md" aria-label="Close"><X className="size-4" /></D.Close>
        </div>
        <p className="text-ink-2 mt-2 text-[15px]">{sprintSummary(t)}</p>
        <div className="mt-4 flex justify-end"><Button size="pill" onClick={onClose}>Close</Button></div>
      </D.Content>
    </D.Portal>
  </D.Root>
}
