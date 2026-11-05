import { useEffect, useState } from 'react'
import { Card } from '@/components/ui/card'
import { get } from '@/lib/api'
import { cn } from '@/lib/utils'

/* Insights → Your calm (setup/calm.py): this month against last month. No scores, ranks or streaks – just what
   Axella can honestly count, each with one calm two-bar comparison. */

interface Month {
  month: string; held: number; broke_through: number; digests: number; read: number; listened: number
  reply_minutes: { work: number | null; private: number | null }; replies: { work: number; private: number }
  work_outside_hours: number; missed: number; drafts_sent: number; drafts_light: number; promises_due: number; promises_kept: number
}
interface CalmData { this: Month; last: Month; work_hours?: { days: number[]; from: string; to: string } }

const monthName = (m: string) => new Date(m + '-15T12:00').toLocaleDateString('en-GB', { month: 'long' })
const dur = (m: number | null) => m == null ? '–' : m < 60 ? `${m} min` : m < 48 * 60 ? `${Math.round(m / 6) / 10} h`.replace('.0 h', ' h') : `${Math.round(m / 1440)} days`
const pct = (a: number, b: number) => b ? `${Math.round(a / b * 100)}%` : '–'

export function YourCalm() {
  const [c, setC] = useState<CalmData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { get<CalmData>('calm').then(setC).catch(e => setErr(e.message)) }, [])
  if (err) return null
  if (!c) return null
  const t = c.this, l = c.last
  const tiles: { key: string; label: string; value: string; sub: string; bars: [number, number]; lowGood?: boolean }[] = [
    { key: 'held', label: 'Messages held for a digest', value: String(t.held), sub: `${t.broke_through} broke through as urgent`, bars: [t.held, l.held] },
    { key: 'through', label: 'Broke through as urgent', value: String(t.broke_through), sub: 'pushed at once by the urgent checks', bars: [t.broke_through, l.broke_through], lowGood: true },
    { key: 'digests', label: 'Digests read', value: `${t.read} of ${t.digests}`, sub: `${t.listened} listened to`, bars: [t.read, l.read] },
    { key: 'reply', label: 'Median reply time', value: dur(t.reply_minutes.work ?? t.reply_minutes.private),
      sub: `work ${dur(t.reply_minutes.work)} · private ${dur(t.reply_minutes.private)} · replies sent from Axella`,
      bars: [t.reply_minutes.work ?? t.reply_minutes.private ?? 0, l.reply_minutes.work ?? l.reply_minutes.private ?? 0], lowGood: true },
    { key: 'outside', label: 'Work outside work hours', value: String(t.work_outside_hours),
      sub: c.work_hours ? `work hours ${c.work_hours.from}–${c.work_hours.to}, aiming for zero` : 'aiming for zero', bars: [t.work_outside_hours, l.work_outside_hours], lowGood: true },
    { key: 'missed', label: 'Should have reached me', value: String(t.missed), sub: t.missed ? 'you marked them in an item’s ⋯ menu' : 'nothing missed', bars: [t.missed, l.missed], lowGood: true },
    { key: 'drafts', label: 'Drafts sent as written', value: pct(t.drafts_light, t.drafts_sent), sub: `${t.drafts_light} of ${t.drafts_sent} with little or no editing`, bars: [t.drafts_light, l.drafts_light] },
    { key: 'promises', label: 'Promises kept on time', value: t.promises_due ? `${t.promises_kept} of ${t.promises_due}` : '–', sub: 'promises due this month', bars: [t.promises_kept, l.promises_kept] },
  ]
  return <section className="space-y-2" data-your-calm="">
    <div className="flex items-baseline justify-between gap-2">
      <h2 className="text-base font-semibold">Your calm</h2>
      <span className="text-muted-foreground text-xs">{monthName(t.month)} so far, against {monthName(l.month)}</span>
    </div>
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {tiles.map(x => <Card key={x.key} className="p-3" data-calm={x.key}>
        <div className="text-muted-foreground text-xs font-medium tracking-wide uppercase">{x.label}</div>
        <div className="mt-1 font-mono text-lg font-medium tabular-nums">{x.value}</div>
        <div className="text-ink-3 mt-0.5 text-[12px] leading-snug">{x.sub}</div>
        <TwoBars a={x.bars[0]} b={x.bars[1]} labels={[monthName(t.month).slice(0, 3), monthName(l.month).slice(0, 3)]} />
      </Card>)}
    </div>
    <p className="text-muted-foreground text-xs">Counted on the Mac mini from what Axella keeps anyway – digests, the activity log, your To do list. Never from what anyone wrote.</p>
  </section>
}

function TwoBars({ a, b, labels }: { a: number; b: number; labels: [string, string] }) {
  const max = Math.max(1, a, b)
  return <div className="mt-2 space-y-1" aria-hidden>
    {([[a, labels[0], true], [b, labels[1], false]] as [number, string, boolean][]).map(([v, l, now]) =>
      <div key={l} className="flex items-center gap-2">
        <span className="text-ink-3 w-7 font-mono text-[10px]">{l}</span>
        <span className="bg-bg-2 h-1.5 flex-1 overflow-hidden rounded-full"><span className={cn('block h-full rounded-full', now ? 'bg-fjord' : 'bg-line-strong')} style={{ width: `${Math.round(v / max * 100)}%` }} /></span>
      </div>)}
  </div>
}
