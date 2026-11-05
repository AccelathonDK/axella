import { useEffect, useState } from 'react'
import { ArrowDownRight, ArrowUpRight, BarChart3, Loader2, Minus } from '@/components/ax-icons'
import { YourTimeCard } from '@/components/Blocks'
import { Card } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { cn, store } from '@/lib/utils'
import { hasProtected } from '@/lib/profile'
import { YourCalm } from '@/components/Calm'

interface Person { address: string; name: string; count: number; prev: number | null; open: number; channels: Record<string, number> }
interface Topic { topic: string; count: number; prev: number | null; people: number }
interface Data {
  period: string; from: string; to: string; prev_from: string; prev_to: string; since?: string; topics_since?: string
  compare?: boolean; prev_partial?: boolean
  totals: { items: number; items_prev: number; calls: number; people: number; handled: number }
  people: Person[]; topics: Topic[]
}
const PERIODS: [string, string][] = [['week', 'This week'], ['lastweek', 'Last week'], ['month', 'This month'], ['lastmonth', 'Last month'], ['quarter', 'Quarter'], ['year', 'Year']]
const CH: Record<string, string> = { mail: 'Mail', imessage: 'iMessage', sms: 'SMS', whatsapp: 'WhatsApp', call: 'Calls', calendar: 'Calendar', slack: 'Slack', other: 'Other' }
const d = (s?: string) => s ? new Date(s + 'T12:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : '–'

export function InsightsView() {
  const { ax, ctx } = useApp()
  const [period, setPeriod] = useState<string>(() => store.get('ax-ins-period', 'week'))
  const [limit, setLimit] = useState<number>(() => +store.get('ax-ins-limit', '10') || 10)
  const [people, setPeople] = useState<boolean>(() => store.get('ax-ins-people', '1') === '1')
  const [data, setData] = useState<Data | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    store.set('ax-ins-period', period); store.set('ax-ins-limit', String(limit)); store.set('ax-ins-people', people ? '1' : '0')
    setErr(null)
    get<Data>(`insights?period=${period}&limit=${limit}&people=${people ? 1 : 0}&ctx=${ctx}`).then(setData).catch(e => setErr(e.message))
  }, [period, limit, people, ctx])

  // topics fall back to the project id when a digest had no topic – show the project's name
  const topicName = (t: string) => ax.projects.find(p => p.id === t)?.name || t
  const prevLabel = data ? `${d(data.prev_from)} – ${d(data.prev_to)}` : ''

  return (
    <div className="space-y-4">
      <div><h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><BarChart3 className="size-5" />Insights</h1>
        <p className="text-muted-foreground text-sm">Who and what takes your time – counted from the digests (each message once, however often it was carried over) and calls.</p></div>

      {ax.apiOk && <YourCalm />}
      {ax.apiOk && <YourTimeCard />}

      <div className="flex flex-wrap items-center gap-2">
        <ToggleGroup type="single" value={period} onValueChange={v => v && setPeriod(v)} className="flex-wrap">
          {PERIODS.map(([v, l]) => <ToggleGroupItem key={v} value={v}>{l}</ToggleGroupItem>)}
        </ToggleGroup>
        <ToggleGroup type="single" value={String(limit)} onValueChange={v => v && setLimit(+v)}>
          <ToggleGroupItem value="3">Top 3</ToggleGroupItem><ToggleGroupItem value="10">Top 10</ToggleGroupItem>
        </ToggleGroup>
        <ToggleGroup type="single" value={people ? 'people' : 'all'} onValueChange={v => v && setPeople(v === 'people')}>
          <ToggleGroupItem value="people">People</ToggleGroupItem><ToggleGroupItem value="all">Incl. services</ToggleGroupItem>
        </ToggleGroup>
      </div>

      {err ? <Card className="text-muted-foreground p-4 text-sm">Couldn’t load insights: {err}</Card>
        : !data ? <div className="text-muted-foreground flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" />Loading…</div>
        : <>
          <div className="text-muted-foreground text-xs">{ctx !== 'all' && <span className="text-fjord font-medium">{ctx === 'work' ? 'Work only' : 'Private only'} · </span>}{d(data.from)} – {d(data.to)}{data.compare === false ? ' · no comparison yet – history starts ' + d(data.since || data.from) : ' · compared with ' + prevLabel + (data.prev_partial ? ' (from ' + d(data.since) + ')' : '')}</div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Messages" value={data.totals.items} prev={data.compare === false ? undefined : data.totals.items_prev} />
            <Stat label="People" value={data.totals.people} />
            <Stat label="Calls" value={data.totals.calls} />
            <Stat label="Handled in Axella" value={data.totals.handled} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Ranked title="People" empty="No messages from people in this period."
              rows={data.people.map(p => ({ key: p.address, label: p.name || p.address, sub: Object.entries(p.channels).sort((a, b) => b[1] - a[1]).map(([c, n]) => `${CH[c] || c} ${n}`).join(' · ') + (p.open ? ` · ${p.open} not marked done` : ''), title: p.address, count: p.count, prev: p.prev }))} prevLabel={prevLabel} />
            <Ranked title="Topics" empty={data.topics_since ? 'No topics in this period.' : 'Topics are recorded from the next digest on.'}
              rows={data.topics.map(t => ({ key: t.topic, label: topicName(t.topic), sub: `${t.people} ${t.people === 1 ? 'person' : 'people'}`, title: t.topic, count: t.count, prev: t.prev }))} prevLabel={prevLabel} />
          </div>
          <p className="text-muted-foreground text-xs">History since {d(data.since)}{data.topics_since ? ` · topics since ${d(data.topics_since)}` : ''}. {hasProtected() ? 'Protected workplaces count by sender only. ' : ''} “People” leaves out newsletters, no-reply and service senders.</p>
        </>}
    </div>
  )
}

function Stat({ label, value, prev }: { label: string; value: number; prev?: number }) {
  return <Card className="p-3"><div className="text-muted-foreground text-xs font-medium tracking-wide uppercase">{label}</div>
    <div className="mt-1 flex items-baseline gap-2"><span className="text-lg font-semibold tabular-nums">{value}</span>{prev !== undefined && <Trend v={value} p={prev} />}</div></Card>
}

function Trend({ v, p }: { v: number; p: number }) {
  if (!p) return <span className="text-muted-foreground text-xs">{v ? 'new' : ''}</span>
  const pct = Math.round((v - p) / p * 100)
  const I = pct > 0 ? ArrowUpRight : pct < 0 ? ArrowDownRight : Minus
  return <span className="text-muted-foreground inline-flex items-center gap-0.5 text-xs tabular-nums"><I className="size-3.5" />{pct > 0 ? '+' : ''}{pct}%</span>
}

function Ranked({ title, rows, empty, prevLabel }: { title: string; empty: string; prevLabel: string
  rows: { key: string; label: string; sub: string; title: string; count: number; prev: number | null }[] }) {
  const max = Math.max(1, ...rows.map(r => r.count))
  return (
    <Card className="overflow-hidden">
      <div className="border-b px-4 py-2.5 text-sm font-semibold">{title}</div>
      {!rows.length ? <div className="text-muted-foreground p-4 text-sm">{empty}</div>
        : <ol className="divide-y">{rows.map((r, i) => (
          <li key={r.key} className="group px-4 py-2.5" title={`${r.title}\n${r.count} this period` + (r.prev == null ? '' : ` · ${r.prev} in ${prevLabel}`)}>
            <div className="flex items-baseline gap-3">
              <span className="text-muted-foreground w-5 shrink-0 text-right text-xs tabular-nums">{i + 1}</span>
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{r.label}</span>
              <span className="text-sm font-semibold tabular-nums">{r.count}</span>
              <span className="w-14 shrink-0 text-right">{r.prev != null && <Trend v={r.count} p={r.prev} />}</span>
            </div>
            <div className="mt-1.5 ml-8 flex items-center gap-3">
              {/* one hue, magnitude only; 4px rounded end anchored at the left baseline */}
              <div className="bg-bg-2 h-1.5 flex-1 overflow-hidden rounded-sm">
                <div className={cn('bg-fjord h-full rounded-r-sm transition-[width] duration-[480ms]', 'group-hover:bg-fjord/80')} style={{ width: `${r.count / max * 100}%` }} />
              </div>
            </div>
            <div className="text-muted-foreground mt-1 ml-8 truncate text-xs">{r.sub}</div>
          </li>))}</ol>}
    </Card>
  )
}
