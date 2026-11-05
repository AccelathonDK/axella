/* Protect your blocks (setup/blocks.py): Insights → Your time (meeting hours, the longest free block per workday – no
   scores, no ranks, no streaks), the digest's one suggestion with Hold it / Not now / Don't suggest for this day, and
   the settings in Settings → Calendar. Hold it adds one busy event of your own; nothing else in the calendar changes. */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { CalendarCheck, CalendarClock, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input, NativeSelect } from '@/components/ui/input'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import type { Item } from '@/lib/types'
import { cn } from '@/lib/utils'

interface Week { week: string; meeting_hours: { work: number; private: number }; days: { date: string; longest: number }[]; no_block: string[] }
interface BView { settings: { minutes: number; calendar: string | null; name: string }; calendars: string[]; hours: { from: string; to: string; days: number[] }
  this_week: Week; last_week: Week; error?: string | null }

const LEN: Record<number, string> = { 60: '1 hour', 90: '1½ hours', 120: '2 hours', 180: '3 hours' }
const hrs = (m: number) => m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ' ' + (m % 60) + ' min' : ''}` : `${m} min`
const wd = (s: string) => new Date(s + 'T12:00').toLocaleDateString('en-GB', { weekday: 'short' })

function useBlocks() {
  const [v, setV] = useState<BView | null>(null)
  const load = () => get<BView>('blocks').then(r => setV((r as any).settings ? r : null)).catch(() => setV(null))
  useEffect(() => { load() }, [])
  return { v, load }
}

/** On the digest item: Hold it, Not now, Don't suggest for this day. */
export function FocusButtons({ it }: { it: Item }) {
  const { ax } = useApp()
  const f = (it as any).focus as { date: string; start: string; end: string } | undefined
  const [busy, setBusy] = useState(false)
  if (!f) return null
  async function run(action: string, msg: string) {
    setBusy(true)
    try { await ax.act(action, { ...f, title: 'Focus' }, []); await ax.act('done', { item_id: it.id, title: it.headline || 'Focus' }, []); toast(msg) }
    catch (e: any) { toast.error(e.message) } finally { setBusy(false) }
  }
  return <span className="contents" data-focus-buttons="">
    <Button size="pill" disabled={busy} onClick={() => run('block_hold', `Held ${f.start}–${f.end} – delete it in Calendar any time`)}><CalendarCheck />Hold it</Button>
    <Button size="pill" variant="outline" disabled={busy} onClick={() => run('block_not_now', 'Not now')}>Not now</Button>
    <Button size="pill" variant="ghost" disabled={busy} onClick={() => run('block_never', 'Not suggested for that day again')}><X />Don't suggest for this day</Button>
  </span>
}

/** Insights → Your time: this week vs last, the longest free block per workday. */
export function YourTimeCard() {
  const { v } = useBlocks()
  if (!v) return null
  const t = v.this_week, l = v.last_week, min = v.settings.minutes
  const max = Math.max(60, ...t.days.map(d => d.longest))
  return <Card className="space-y-3 p-4" data-your-time="">
    <div className="flex items-center gap-2"><CalendarClock className="text-ink-3 size-4" /><span className="ax-label">Your time</span>
      <span className="text-ink-3 ml-auto text-[12px]">Work hours {v.hours.from}–{v.hours.to}</span></div>
    {v.error && <p className="text-ink-3 text-[13px]">{v.error}</p>}
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <Tile label="In meetings · work" value={`${t.meeting_hours.work} h`} sub={`last week ${l.meeting_hours.work} h`} />
      <Tile label="In meetings · private" value={`${t.meeting_hours.private} h`} sub={`last week ${l.meeting_hours.private} h`} />
      <Tile label={`Days without ${LEN[min] || hrs(min)} free`} value={String(t.no_block.length)} sub={`last week ${l.no_block.length}`} />
    </div>
    <div>
      <div className="text-ink-3 mb-1.5 text-[12px]">Longest free block per workday, this week</div>
      <div className="flex items-end gap-2" style={{ height: 72 }}>{t.days.map(d => <div key={d.date} className="flex flex-1 flex-col items-center gap-1">
        <div className={cn('w-full rounded-t', d.longest >= min ? 'bg-[var(--ax-success)]/60' : 'bg-dawn/50')} style={{ height: Math.max(3, 52 * d.longest / max) }} title={hrs(d.longest)} />
        <span className="text-ink-3 font-mono text-[11px]">{wd(d.date)}</span></div>)}</div>
    </div>
  </Card>
}

function Tile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return <div className="rounded-md border p-3"><div className="text-ink-3 text-[11.5px] font-medium tracking-wide uppercase">{label}</div>
    <div className="mt-1 font-mono text-lg tabular-nums">{value}</div><div className="text-ink-3 text-[12px]">{sub}</div></div>
}

/** Settings → Calendar: block length, which calendar gets held blocks, the event's name. */
export function BlocksSettingsCard() {
  const { ax } = useApp()
  const { v, load } = useBlocks()
  const [name, setName] = useState('')
  useEffect(() => { if (v) setName(v.settings.name) }, [v])
  if (!v) return null
  const save = (body: Record<string, unknown>) => ax.act('block_settings', body, []).then(() => { toast('Saved'); load() }).catch((e: any) => toast.error(e.message))
  return <div className="bg-card divide-y overflow-hidden rounded-lg border" data-blocks-settings="">
    <div className="px-4 py-2.5"><div className="font-semibold">Protect your blocks</div>
      <div className="text-ink-3 text-[12.5px]">On a busy workday with one free block left, the morning digest (or Sunday's week-ahead) may suggest holding it – at most once a day, work only. Work hours {v.hours.from}–{v.hours.to}.</div></div>
    <div className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
      <label className="flex items-center gap-2">Minimum block
        <NativeSelect className="h-8 w-32 text-xs" value={String(v.settings.minutes)} onChange={e => save({ minutes: Number(e.target.value) })}>
          {[60, 90, 120, 180].map(m => <option key={m} value={m}>{LEN[m]}</option>)}</NativeSelect></label>
      <label className="flex items-center gap-2">Held blocks go to
        <NativeSelect className="h-8 w-40 text-xs" value={v.settings.calendar || ''} onChange={e => save({ calendar: e.target.value || null })}>
          <option value="">{v.calendars[0] ? v.calendars[0] + ' (first work calendar)' : 'No work calendar'}</option>
          {v.calendars.map(c => <option key={c} value={c}>{c}</option>)}</NativeSelect></label>
      <label className="flex items-center gap-2">Named
        <Input className="h-8 w-36 text-xs" value={name} maxLength={60} onChange={e => setName(e.target.value)} onBlur={() => name !== v.settings.name && save({ name })} /></label>
    </div>
  </div>
}
