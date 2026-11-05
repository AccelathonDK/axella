import { useEffect, useRef, useState } from 'react'
import { ChevronRight, Loader2 } from '@/components/ax-icons'
import { Card } from '@/components/ui/card'
import { useApp } from '@/lib/app'
import { dayKey, dayLabel, isRegular, listEntries, parseName } from '@/lib/data'
import { cn, isoDate } from '@/lib/utils'

/* Older digests: days 8–30 still sit in digests/, anything older is in digests/archive/YYYY-MM/ (moved by the Mac mini) */
export function ArchiveView() {
  const { ax, go } = useApp()
  const [months, setMonths] = useState<string[] | null>(null)
  const [month, setMonth] = useState<string | null>(null)
  const [list, setList] = useState<string[] | null>(null)
  const picked = useRef(false)
  const from = new Date(); from.setDate(from.getDate() - 6)
  const recentFrom = isoDate(from)
  const loose = ax.names.filter(n => isRegular(n) && dayKey(n) < recentFrom)         // older than the picker, not yet archived

  useEffect(() => {
    listEntries('digests/archive/').then(e => {
      const fromArchive = e.filter(h => /^\d{4}-\d{2}\/$/.test(h)).map(h => h.slice(0, 7))
      const all = [...new Set([...loose.map(n => n.slice(0, 7)), ...fromArchive])].sort().reverse()
      setMonths(all); setMonth(m => (picked.current && m) || all[0] || null)
    })
  }, [ax.names.length])

  useEffect(() => {
    if (!month) { setList([]); return }
    setList(null)
    listEntries(`digests/archive/${month}/`).then(e => {
      const archived = e.filter(h => /^\d{4}-\d{2}-\d{2}-\d{4}.*\.md$/.test(h) && isRegular(h)).map(h => `archive/${month}/${h}`)
      setList([...loose.filter(n => n.startsWith(month)), ...archived].sort((a, b) => b.split('/').pop()!.localeCompare(a.split('/').pop()!)))
    })
  }, [month, ax.names.length])

  const open = async (n: string) => { await ax.select(n); go({ kind: 'briefing' }) }
  const groups: [string, string[]][] = []
  ;(list || []).forEach(n => { const k = dayKey(n), g = groups.find(x => x[0] === k); g ? g[1].push(n) : groups.push([k, [n]]) })
  const monthLabel = (m: string) => new Date(m + '-01T00:00').toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })

  return (
    <div className="space-y-4">
      <div><h1 className="text-xl font-semibold tracking-tight">Older digests</h1>
        <p className="text-muted-foreground text-sm">The digest picker shows the last 7 days. Older digests are kept here by month – nothing is deleted.</p></div>
      {months === null ? <div className="text-muted-foreground flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" />Loading…</div>
        : !months.length ? <p className="text-muted-foreground text-sm">No older digests yet.</p>
        : <>
          <div className="flex flex-wrap gap-1.5">
            {months.map(m => <button key={m} onClick={() => { picked.current = true; setMonth(m) }} className={cn('rounded-md border px-3 py-1 text-sm font-medium',
              m === month ? 'bg-primary text-primary-foreground border-primary' : 'bg-card hover:bg-accent')}>{monthLabel(m)}</button>)}
          </div>
          {list === null ? <div className="text-muted-foreground flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" />Loading…</div>
            : !list.length ? <p className="text-muted-foreground text-sm">No digests in {month && monthLabel(month)}.</p>
            : <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {groups.map(([k, names]) => <Card key={k} className="p-0">
                <div className="text-muted-foreground border-b px-4 py-2 text-xs font-semibold tracking-wide uppercase">{dayLabel(k)}</div>
                <div className="divide-y">
                  {names.map(n => { const m = parseName(n); return (
                    <button key={n} onClick={() => open(n)} className="hover:bg-accent/60 flex w-full items-center gap-2 px-4 py-2.5 text-left text-[14.5px]">
                      <span className="font-medium tabular-nums">{m.date?.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}</span>
                      <span className="text-muted-foreground">{m.kind === 'Week ahead' ? 'Week ahead' : m.date && m.date.getHours() < 10 ? 'Morning' : m.date && m.date.getHours() < 13 ? 'Midday' : 'Afternoon'}</span>
                      <ChevronRight className="text-muted-foreground ml-auto size-4" />
                    </button>) })}
                </div>
              </Card>)}
            </div>}
        </>}
    </div>
  )
}
