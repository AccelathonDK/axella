import { TravelCard } from '@/components/TripsLive'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { RenewalsCard } from '@/components/Renewals'
import { SprintCard } from '@/components/Sprint'
import { WelcomeCard } from '@/components/Welcome'
import { ChevronRight, Loader2, Pause, Play, axi } from '@/components/ax-icons'
import { Card } from '@/components/ui/card'
import { CallRow, TaskRow, taskInCtx } from '@/components/Cards'
import { BriefsCard } from '@/components/Briefings'
import { PrivateCard } from '@/components/Privacy'
import { MeetingsCard } from '@/components/Meetings'
import { PendingInvites } from '@/components/Invite'
import { ScheduledCard } from '@/components/SendLater'
import { CommitmentsCard } from '@/components/Commitments'
import { toggleListen, useListening } from '@/components/Listen'
import { ItemRow } from '@/components/ItemRow'
import { Banners, useBySection } from '@/components/Today'
import { OfflineScreen } from '@/components/Offline'
import { PauseBanner } from '@/components/Settings'
import { PlanToday } from '@/components/Plan'
import { useApp } from '@/lib/app'
import type { Call, Item, Task } from '@/lib/types'
import { cn, isoDate } from '@/lib/utils'
import { WrapCard } from '@/components/Wrap'
import { SuggestionCard } from '@/components/Learn'
import { CalmSetupNudge } from '@/components/CalmSetup'
import { LaterLine } from '@/components/Later'

/* Today = Now + Briefing (the split agreed on the design canvas):
   - Now: one ranked queue of everything that needs the owner – urgent and overdue first, then today's replies, calls,
     tasks due and stale waiting items. Empty when done.
   - Briefing: the calm read – the spoken summary, what's new since you last looked, your day, what waits on others,
     what's left to tidy. The full digest with every section is the Briefing page. */
export const NowIcon = axi('focus')
export const BriefingIcon = axi('summary')

type Entry = { key: string; rank: number; node: ReactNode }

export function useNow() {
  const { ax, inCtx, ctx } = useApp()
  const { by, calls } = useBySection()
  const today = isoDate(new Date())
  return useMemo(() => {
    const open = (i: Item) => !ax.isHandled(i.id)
    const items = (k: string) => (by[k as keyof typeof by] || []).filter(open)
    const urgentCalls = (c: Call) => c.priority === 'p0' || c.from?.tier === 'VIP'
    const openCalls = calls.filter(c => !ax.isHandled(c.id))
    const tasks = ax.apiOk ? ax.tasks.filter(t => t.status !== 'done' && t.due && t.due <= today && inCtxTask(t)) : []
    const now: Entry[] = [
      ...items('p0').map(i => ({ key: i.id, rank: 0, node: <ItemRow key={i.id} it={i} /> })),
      ...openCalls.filter(urgentCalls).map(c => ({ key: c.id, rank: 0, node: <CallRow key={c.id} c={c} /> })),
      ...[...items('p1'), ...items('p2')].filter(i => i.overdue).map(i => ({ key: i.id, rank: 1, node: <ItemRow key={i.id} it={i} /> })),
      ...items('wait').filter(i => i.overdue).map(i => ({ key: i.id, rank: 1, node: <ItemRow key={i.id} it={i} /> })),
    ]
    const later: Entry[] = [
      ...items('p1').filter(i => !i.overdue).map(i => ({ key: i.id, rank: 2, node: <ItemRow key={i.id} it={i} /> })),
      ...openCalls.filter(c => !urgentCalls(c)).map(c => ({ key: c.id, rank: 2, node: <CallRow key={c.id} c={c} /> })),
      ...tasks.map(t => ({ key: t.id, rank: t.due! < today ? 1 : 3, node: <TaskRow key={t.id} t={t} /> })),
      ...items('p2').filter(i => !i.overdue).map(i => ({ key: i.id, rank: 4, node: <ItemRow key={i.id} it={i} /> })),
    ].sort((a, b) => a.rank - b.rank)
    const carried = items('open')
    // mail you answered from Axella that is still in the inbox: kept in reach so it can be filed afterwards
    const answered = (['p0', 'p1', 'p2', 'open', 'wait', 'p3'] as const).flatMap(k => by[k] || [])
      .filter(i => i.channel === 'mail' && !!i.message_id && (ax.state[i.id] as { status?: string; how?: string } | undefined)?.how === 'sent')
    return { now, later, carried, answered, count: now.length + later.length }
    function inCtxTask(t: Task) { return taskInCtx(t, ctx) }
  }, [by, calls, ax.tasks, ax.state, ax.apiOk, today, inCtx, ctx])
}

function Group({ label, n, children, hot }: { label: string; n: number; children: ReactNode; hot?: boolean }) {
  return <Card className="overflow-hidden">
    <div className="flex items-center gap-2 border-b px-4 py-2.5">
      <span className={cn('ax-diamond', hot ? 'text-dawn' : 'text-fjord')} style={{ width: 7, height: 7 }} />
      <span className="ax-label !text-ink">{label}</span>
      <span className="text-ink-3 ml-auto font-mono text-[12px]">{n}</span>
    </div>
    <div className="divide-y">{children}</div>
  </Card>
}

export function NowQueue() {
  const { ax } = useApp()
  const { now, later, carried, answered, count } = useNow()
  const [showCarried, setShowCarried] = useState(false)
  const [showAnswered, setShowAnswered] = useState(false)
  if (!ax.stateReady) return <div className="space-y-4" data-tour="today">   {/* until Done / Later is known – never old items flashing up */}
    <Card className="text-ink-3 flex items-center gap-2 px-4 py-6 text-sm" data-state-wait=""><Loader2 className="size-4 animate-spin" />Checking what you've already handled…</Card>
  </div>
  return <div className="space-y-4" data-tour="today">
    {now.length > 0 && <Group label="Now" n={now.length} hot>{now.map(e => e.node)}</Group>}
    {later.length > 0 && <Group label="Today" n={later.length}>{later.map(e => e.node)}</Group>}
    {!count && <Card className="flex flex-col items-center px-6 py-10 text-center">
      <span className="text-success"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M12 2.5L21.5 12 12 21.5 2.5 12z" /><path d="M8.5 12l2.5 2.5 4.5-4.5" /></svg></span>
      <div className="mt-3 text-lg font-semibold">Nothing needs you right now</div>
      <div className="text-ink-2 mt-1 text-sm">Axella keeps watching and tells you when something can't wait.</div>
    </Card>}
    {carried.length > 0 && <Card className="overflow-hidden">
      <button onClick={() => setShowCarried(!showCarried)} aria-expanded={showCarried}
        className="bg-bg-2/60 hover:bg-bg-2 flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm">
        <span className="ax-label">Still open from earlier</span><span className="text-ink-3 font-mono text-[12px]">{carried.length}</span>
        <span className="text-fjord ml-auto text-[13px] font-medium">{showCarried ? 'Hide' : 'Show'}</span>
      </button>
      {showCarried && <div className="ax-reveal divide-y border-t">{carried.map(i => <ItemRow key={i.id} it={i} />)}</div>}
    </Card>}
    {answered.length > 0 && <Card className="overflow-hidden" data-answered="">
      <button onClick={() => setShowAnswered(!showAnswered)} aria-expanded={showAnswered}
        className="bg-bg-2/60 hover:bg-bg-2 flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm">
        <span className="ax-label">Answered – still in the inbox</span><span className="text-ink-3 font-mono text-[12px]">{answered.length}</span>
        <span className="text-fjord ml-auto text-[13px] font-medium">{showAnswered ? 'Hide' : 'File them'}</span>
      </button>
      {showAnswered && <div className="ax-reveal divide-y border-t">{answered.map(i => <ItemRow key={i.id} it={i} />)}</div>}
    </Card>}
  </div>
}

/* ---------- Briefing ---------- */
const SEEN_KEY = 'ax-last-seen'
/** When the owner last looked (kept per device). Read once per visit; written when the page goes to the background. */
export function useLastSeen() {
  const [prev] = useState<string | null>(() => { try { return localStorage.getItem(SEEN_KEY) } catch { return null } })
  useEffect(() => {
    const save = () => { try { localStorage.setItem(SEEN_KEY, new Date().toISOString()) } catch { /* private mode */ } }
    const h = () => { if (document.hidden) save() }
    document.addEventListener('visibilitychange', h); addEventListener('pagehide', save)
    return () => { document.removeEventListener('visibilitychange', h); removeEventListener('pagehide', save); save() }
  }, [])
  return prev
}

export function Spoken({ text, label }: { text: string; label: string }) {
  const on = useListening()                    // the Listen queue: digest, then unheard briefs (Listen.tsx)
  const toggle = () => toggleListen()
  return (
    <div className="bg-surface-inverse text-on-inverse flex items-center gap-4 rounded-lg p-4">
      <button className="bg-on-inverse text-surface-inverse flex size-11 shrink-0 items-center justify-center rounded-md" onClick={toggle} aria-label={on ? 'Pause' : 'Listen'}>
        {on ? <Pause className="size-5" /> : <Play className="size-5" />}</button>
      <div className="min-w-0"><div className="font-mono text-[11px] font-medium tracking-[.08em] uppercase opacity-75">{label}</div>
        <div className="line-clamp-3 text-[15px] leading-snug">{text}</div></div>
    </div>
  )
}

const hm = (iso?: string) => iso ? new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : ''
const SINCE_LABEL: Record<string, string> = { p0: 'urgent', p1: 'to answer', p2: 'to answer', open: 'carried', p3: 'FYI', cal: 'calendar', wait: 'waiting', file: 'to file' }

export function BriefingSummary({ full = false }: { full?: boolean }) {
  const { ax, go } = useApp()
  const { by, calls } = useBySection()
  const seen = useLastSeen()
  const cur = ax.current
  const all = Object.values(by).flat() as Item[]
  const fresh = seen ? all.filter(i => i.first_seen && i.first_seen > seen && !ax.isHandled(i.id)) : []
  const freshCalls = seen ? calls.filter(c => (c.started || '') > seen) : []
  const kinds: Record<string, number> = {}
  fresh.forEach(i => { const l = SINCE_LABEL[i.section] || i.section; kinds[l] = (kinds[l] || 0) + 1 })
  const cal = (by.cal || []).filter(i => !ax.isHandled(i.id))
  const waiting = (by.wait || []).filter(i => !ax.isHandled(i.id)).length
  const filing = (by.file || []).filter(i => !ax.isHandled(i.id)).length
  if (!cur) return null
  // full briefing on a wide screen: the same two columns as "Everything in this digest" below
  return <div className={cn(full ? 'grid grid-cols-1 items-start gap-3 min-[1100px]:grid-cols-[minmax(0,1.75fr)_minmax(0,1fr)] min-[1100px]:gap-5' : 'space-y-3')}>
    <div className="min-w-0 space-y-3">
    {cur.data.spoken && <Spoken text={cur.data.spoken} label={`Briefing · ${cur.meta.label}`} />}

    <Card className="overflow-hidden">
      <div className="ax-label border-b px-4 py-2.5">{seen ? `Since you looked · ${hm(seen)}` : 'In this briefing'}</div>
      <div className="space-y-2 px-4 py-3 text-sm">
        {seen && !fresh.length && !freshCalls.length && <div className="text-ink-2">Nothing new since you last looked.</div>}
        {freshCalls.map(c => <Line key={c.id}><b className="font-semibold">{c.from?.name || c.from?.number || 'Someone'}</b> called – {c.summary ? c.summary.slice(0, 80) : 'see Now'}</Line>)}
        {fresh.slice(0, 4).map(i => <Line key={i.id}><b className="font-semibold">{(i.headline || i.subject || '').replace(/\*\*/g, '').slice(0, 90)}</b></Line>)}
        {fresh.length > 4 && <Line>{Object.entries(kinds).map(([k, n]) => `${n} ${k}`).join(' · ')}</Line>}
        {!seen && <div className="text-ink-2">{Object.entries(all.filter(i => !ax.isHandled(i.id)).reduce<Record<string, number>>((m, i) => {
          const l = SINCE_LABEL[i.section] || i.section; m[l] = (m[l] || 0) + 1; return m }, {})).map(([k, n]) => `${n} ${k}`).join(' · ') || 'Nothing open in this digest.'}</div>}
      </div>
    </Card>

    </div>
    <div className="min-w-0 space-y-3">
    {cal.length > 0 && <Card className="overflow-hidden">
      <div className="flex items-center border-b px-4 py-2.5"><span className="ax-label">Your day</span>
        <button className="text-fjord ml-auto text-[13px] font-medium" onClick={() => go({ kind: 'briefing' }, 'cal')}>Calendar</button></div>
      <div className="divide-y">{cal.slice(0, 4).map(i => <div key={i.id} className="px-4 py-2.5 text-sm">
        <div className="font-medium">{(i.headline || '').replace(/\*\*/g, '')}</div>
        {i.detail && <div className="text-ink-3 line-clamp-1 text-[13px]">{String(i.detail).replace(/\*\*/g, '')}</div>}
      </div>)}</div>
    </Card>}

    <ScheduledCard />
    <CommitmentsCard />
    <PendingInvites limit={3} />
    <MeetingsCard />
    <PrivateCard />
    <BriefsCard since={(cur.data as { generated?: string }).generated} />

    <div className="grid grid-cols-2 gap-3">
      <Tile label="Waiting on others" n={waiting} onClick={() => go({ kind: 'todo', tab: 'waiting' })} />
      <Tile label="To tidy" n={filing} sub={filing ? `${filing} to file` : 'Mailbox'} onClick={() => go({ kind: 'mailbox', tab: 'filing' })} />
    </div>
    </div>
    {!full && <div className="space-y-1">
      <button onClick={() => go({ kind: 'briefing' })} className="text-fjord hover:bg-bg-2 flex w-full items-center justify-center gap-1 rounded-md py-2 text-sm font-medium">
        Open the full briefing<ChevronRight className="size-4" /></button>
      <LaterLine place="side" />
    </div>}
  </div>
}
const Line = ({ children }: { children: ReactNode }) =>
  <div className="text-ink-2 flex gap-2.5"><span className="ax-diamond text-fjord mt-[7px] shrink-0" style={{ width: 6, height: 6 }} /><span className="min-w-0">{children}</span></div>
function Tile({ label, n, sub, onClick }: { label: string; n: number; sub?: string; onClick: () => void }) {
  return <button onClick={onClick} className="bg-card hover:border-line-strong rounded-lg border px-4 py-3 text-left transition-colors">
    <div className="ax-label">{label}</div>
    <div className={cn('mt-1 text-xl font-semibold tabular-nums', !n && 'text-ink-3')}>{n}</div>
    {sub && <div className="text-ink-3 text-[12px]">{sub}</div>}
  </button>
}

/* ---------- when the next digest comes (scheduler.next_digest via GET schedule): "next digest 15:30, in 4 h" ---------- */
export function nextDigestText(next: { at: string; worlds: string[] } | null | undefined, status: { digests: boolean; urgent: boolean } | undefined, now = new Date()) {
  if (next === undefined) return null
  const paused = status && !status.digests ? 'paused – ' : ''
  const tail = paused && status?.urgent ? ' · urgent still checked' : ''
  if (!next) return paused + 'no digests scheduled' + tail
  const at = new Date(next.at)
  const name = next.worlds.length === 1 ? `next ${next.worlds[0]} digest` : 'next digest'
  const hhmm = at.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  const min = Math.max(1, Math.round((at.getTime() - now.getTime()) / 60000))
  const day0 = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const days = Math.round((new Date(at.getFullYear(), at.getMonth(), at.getDate()).getTime() - day0) / 864e5)
  const when = min < 60 ? `in ${min} min` : days === 0 ? `${hhmm}, in ${Math.round(min / 60)} h` : days === 1 ? `tomorrow ${hhmm}`
    : `${at.toLocaleDateString('en-GB', { weekday: 'short' })} ${hhmm}, in ${days} days`
  return `${paused}${name} ${when}${tail}`
}
function NextDigest() {
  const { ax, go } = useApp()
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick(n => n + 1), 60000); return () => clearInterval(t) }, [])
  const text = ax.schedule ? nextDigestText(ax.schedule.next, ax.schedule.status) : null
  if (!text) return null
  return <> · <button type="button" onClick={() => go({ kind: 'settings', page: 'schedule' })} data-next-digest=""
    className="hover:text-ink uppercase underline-offset-2 hover:underline" title="Settings → Schedule">{text}</button></>
}

/* ---------- the Today page ---------- */
export function NowView() {
  const { ax } = useApp()
  const { count } = useNow()
  const cur = ax.current
  if (!cur) {
    if (!ax.online) return <><TravelCard /><OfflineScreen /></>     // a travel day works without the Mac mini (kept on this device)
    if (ax.error && ax.error !== 'No digests yet') return <OfflineScreen mini />
  }
  const d = new Date()
  return <div className="space-y-4">
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.02em]">{count ? `${count} thing${count > 1 ? 's' : ''} need${count > 1 ? '' : 's'} you` : 'Nothing needs you'}</h1>
      <span className="text-ink-3 font-mono text-[13px] uppercase">{d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })} · {hm(d.toISOString())}<NextDigest /></span>
    </div>
    <Banners />
    <PauseBanner />
    <WelcomeCard />
    <CalmSetupNudge where="today" />
    <WrapCard />
    {!cur?.data.wrap?.headline && <SuggestionCard />}
    <TravelCard />
    <PlanToday />
    <SprintCard />
    <RenewalsCard />
    <div className="grid grid-cols-1 items-start gap-5 min-[1100px]:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
      <NowQueue />
      <div className="max-[1099px]:hidden"><BriefingSummary /></div>
      <div className="space-y-3 min-[1100px]:hidden"><ScheduledCard /><CommitmentsCard /><PendingInvites limit={3} /><MeetingsCard /><PrivateCard /><BriefsCard since={cur && (cur.data as { generated?: string }).generated} /></div>
    </div>
    <LaterLine place="main" />
  </div>
}
