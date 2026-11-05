import { useEffect, useState } from 'react'
import { Pause, Play, Plug } from '@/components/ax-icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { CallAgentAlert, CallsCard, ItemSection, taskInCtx } from '@/components/Cards'
import { BriefingSummary } from '@/components/Now'
import { useApp } from '@/lib/app'
import { OfflineScreen } from '@/components/Offline'
import { PauseBanner } from '@/components/Settings'
import { EXTRA, SECTIONS, SEC } from '@/lib/sections'
import type { Item, SectionKey } from '@/lib/types'
import { ago, cn } from '@/lib/utils'
import { digestScope, scopeLabel } from '@/lib/data'
import { post } from '@/lib/api'
import { WrapCard } from '@/components/Wrap'
import { WelcomeCard } from '@/components/Welcome'

/* Your calm: a digest counts as read once it was shown here (once per digest – the Mac mini keeps the first time) */
const SEEN = new Set<string>()

export const jump = (k: string) => document.getElementById('sec-' + k)?.scrollIntoView({ behavior: 'smooth', block: 'start' })

export function useBySection() {
  const { ax, inCtx } = useApp()
  const by: Partial<Record<SectionKey, Item[]>> = {}
  ax.current?.data.items.filter(inCtx).forEach(i => (by[i.section] ||= []).push(i))
  const openCount = (k: SectionKey) => (by[k] || []).filter(i => !ax.isHandled(i.id)).length
  const calls = ax.calls.filter(inCtx)
  return { by, openCount, calls }
}

/* While the action service doesn't answer: ask the web server what the watchdog saw (status.json) – so the banner can
   say "you're not logged in on the Mac mini" instead of a bare "can't reach". */
type MiniStatus = { problem?: string | null; since?: string | null; sources?: { name: string; problem: string; since: string }[] }
function useMiniStatus(down: boolean) {
  const [st, setSt] = useState<MiniStatus | null>(null)
  useEffect(() => {
    const f = () => fetch('status.json', { cache: 'no-store' }).then(r => r.ok ? r.json() : null).then(setSt).catch(() => setSt(null))
    f(); const t = setInterval(f, down ? 60000 : 300000); return () => clearInterval(t)   // every minute while down, else every 5
  }, [down])
  return st
}

export function Banners() {
  const { ax, go, ctx } = useApp()
  const down = ax.online && !ax.apiOk && !ax.loading
  const scope = digestScope(ax.current?.data)
  const outOfScope = ctx !== 'all' && !scope.includes(ctx)
  const curName = ax.current?.name
  useEffect(() => {
    if (!curName || !ax.apiOk || SEEN.has(curName) || document.visibilityState !== 'visible') return
    SEEN.add(curName)
    post('digest_seen', { name: curName.replace(/\.(md|json)$/, '').split('/').pop() }).catch(() => SEEN.delete(curName))
  }, [curName, ax.apiOk])
  const mini = useMiniStatus(down)
  const since = mini?.since ? new Date(mini.since).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : ''
  return <>
    {!down && (mini?.sources || []).filter(x => x.since && Date.now() - new Date(x.since).getTime() >= 3600000).map(x =>
      <div key={x.name} className="bg-card flex items-center gap-3 rounded-lg border px-3 py-2.5 text-sm" data-source-down={x.name}>
        <span className="bg-dawn text-on-dawn flex size-7 shrink-0 items-center justify-center rounded-sm"><Plug className="size-4" /></span>
        <span>{x.problem} since {new Date(x.since).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })} – digests leave {x.name} out until it is fixed.
          <button className="text-fjord ml-1 font-semibold hover:underline" onClick={() => go({ kind: 'status' })}>System status</button></span></div>)}
    {down && <div className="bg-card flex items-center gap-3 rounded-lg border px-3 py-2.5 text-sm" data-mini-down="">
      <span className="bg-dawn text-on-dawn flex size-7 shrink-0 items-center justify-center rounded-sm"><Plug className="size-4" /></span>
      {mini?.problem
        ? <span>{mini.problem}{since && <span className="text-ink-3"> Since {since}.</span>} You can read what's here; sending, filing and done are paused until it's back – your typed replies are kept.</span>
        : <span>Can't reach your Mac mini – reply buttons still work, but saving drafts, filing and done are paused until it answers. Axella keeps trying.</span>}</div>}
    {outOfScope && <div className="bg-card text-ink-2 rounded-lg border px-3 py-2.5 text-sm" data-scope-empty="">
      This digest covers {scope[0]} only. {ctx === 'work' ? 'Work' : 'Private'} messages come in the next digest that covers {ctx}.</div>}
    {ax.current?.data.fromMd && <div className="bg-card text-ink-2 flex items-center gap-2.5 rounded-lg border px-3 py-2.5 text-sm">
      <span className="text-fjord relative flex size-3 items-center justify-center"><span className="ax-diamond absolute animate-[ax-listen_3.2s_cubic-bezier(.45,0,.55,1)_infinite]" /><span className="ax-diamond" /></span>
      Axella is still finishing this digest – the buttons appear in a moment.</div>}
    {ax.live?.active && <div className="bg-fjord-soft text-ink flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm">
      <span className="text-fjord relative flex size-3 items-center justify-center"><span className="ax-diamond absolute animate-[ax-listen_3.2s_cubic-bezier(.45,0,.55,1)_infinite]" /><span className="ax-diamond" /></span>
      Axella is talking to {ax.live.from?.name || ax.live.from?.number || 'a caller'} now</div>}
  </>
}

export function QuickNav() {
  const { ax, ctx } = useApp()
  const { by, openCount, calls } = useBySection()
  const [active, setActive] = useState<string | null>(null)
  const chips: [string, string, string, number | null][] = [
    ['p0', SEC.p0.short, SEC.p0.color, openCount('p0')],
    ['p1', SEC.p1.short, SEC.p1.color, openCount('p1')],
    ['p2', SEC.p2.short, SEC.p2.color, openCount('p2')],
    ['calls', 'Calls', EXTRA.calls.color, calls.length ? calls.filter(c => !ax.isHandled(c.id)).length : null],
    ['tasks', 'To do', EXTRA.tasks.color, ax.apiOk ? ax.tasks.filter(t => t.status !== 'done' && taskInCtx(t, ctx)).length : null],
    ...(['cal', 'wait', 'open', 'p3', 'file'] as SectionKey[]).map(k => [k, SEC[k].short, SEC[k].color, by[k] ? openCount(k) : null] as [string, string, string, number | null]),
  ]
  useEffect(() => {
    const obs = new IntersectionObserver(es => es.filter(e => e.isIntersecting).forEach(e => setActive((e.target as HTMLElement).dataset.sec || null)), { rootMargin: '-45% 0px -50% 0px' })
    document.querySelectorAll('[data-sec]').forEach(s => obs.observe(s))
    return () => obs.disconnect()
  })
  return (
    <div className="flex flex-wrap gap-1.5 py-2">
      {chips.filter(c => c[3] !== null).map(([k, l, c, n]) => (
        <button key={k} onClick={() => jump(k)} aria-pressed={active === k}
          className={cn('inline-flex h-8 items-center gap-1.5 rounded-md border border-line-strong/70 bg-card px-2.5 text-[13px] font-medium text-ink-2 transition-colors duration-[120ms] hover:text-ink max-[420px]:px-2 max-[420px]:text-xs',
            active === k && 'border-fjord text-ink')}>
          {l}<span className={cn('inline-flex h-5 min-w-5 items-center justify-center rounded-sm px-1 font-mono text-[11px] tabular-nums',
            k === 'p0' && n ? 'bg-dawn text-on-dawn' : n ? 'bg-fjord-soft text-fjord' : 'text-ink-3')}>{n}</span>
        </button>))}
    </div>
  )
}

function Stats() {
  const { ax } = useApp()
  const { openCount, calls } = useBySection()
  const tiles: [string, number, string, string][] = [
    ['Urgent', openCount('p0') + calls.filter(c => c.priority === 'p0' && !ax.isHandled(c.id)).length, SEC.p0.color, 'p0'],
    ['Before noon', openCount('p1'), SEC.p1.color, 'p1'],
    ['End of day', openCount('p2'), SEC.p2.color, 'p2'],
    ['Waiting', openCount('wait'), SEC.wait.color, 'wait'],
  ]
  return (
    <div className="hidden grid-cols-4 gap-3 md:grid">
      {tiles.map(([l, n, c, k]) => {
        const I = SEC[k as SectionKey].icon
        return <button key={k} onClick={() => jump(k)} className="bg-card hover:border-line-strong rounded-lg border p-4 text-left transition-colors">
          <div className="flex items-start justify-between"><div className={cn('font-mono text-3xl leading-none font-medium tabular-nums', !n && 'text-ink-3')}>{n}</div>
            <I className={cn('size-5', k === 'p0' && n ? 'text-dawn' : n ? 'text-fjord' : 'text-ink-3')} /></div>
          <div className="ax-label mt-2">{l}</div>
        </button>
      })}
    </div>
  )
}

export function TodayView() {
  const { ax } = useApp()
  const { by, calls } = useBySection()
  const cur = ax.current
  if (!cur) {
    if (!ax.online) return <OfflineScreen />
    if (ax.error && ax.error !== 'No digests yet') return <OfflineScreen mini />
    return <div className="py-10 text-center"><h1 className="text-xl font-semibold">{ax.error || 'Loading…'}</h1>
      {ax.error && <p className="text-muted-foreground mt-1 text-sm">The first digest appears here after the next scheduled run.</p>}</div>
  }
  const { data, meta } = cur
  const old = meta.date && Date.now() - meta.date.getTime() > 6 * 3600e3
  const main = SECTIONS.filter(d => d.col === 'main' && (by[d.key] || d.always))
  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.02em]">{data.title || (meta.kind === 'Digest' ? 'Briefing' : meta.kind)}</h1>
          <div className="text-ink-2 mt-1 max-w-[90ch] text-[15px]"><span className="font-mono text-[13px]">{meta.label}</span>{scopeLabel(digestScope(data)) && <Badge variant="outline" className="ml-2 py-px align-middle" data-scope-label="">{scopeLabel(digestScope(data))} digest</Badge>}{data.intro ? ' · ' + data.intro : ''}</div>
        </div>
        {meta.date && <span className={cn('shrink-0 font-mono text-[13px]', old ? 'bg-dawn text-on-dawn rounded-sm px-2 py-0.5' : 'text-ink-3')}>{ago(meta.date)}</span>}
      </div>
      <Banners />
      <PauseBanner />
      <WelcomeCard />
      <WrapCard />
      <BriefingSummary full />
      <div className="ax-label pt-2">Everything in this digest</div>
      <div className="grid grid-cols-1 items-start gap-5 min-[1100px]:grid-cols-[minmax(0,1.75fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-4">
          {main.map((d, i) => <div key={d.key} className="space-y-4">
            <ItemSection def={d} items={by[d.key] || []} />
            {i === 0 && calls.length > 0 && <CallsCard calls={calls} />}
          </div>)}
        </div>
        <div className="space-y-4">
          {SECTIONS.filter(d => d.col === 'side' && by[d.key]).map(d => <ItemSection key={d.key} def={d} items={by[d.key]!} />)}
          <CallAgentAlert />
        </div>
      </div>
    </div>
  )
}
