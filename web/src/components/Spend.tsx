import { useMemo, useState } from 'react'
import { ChevronRight } from '@/components/ax-icons'
import { Card } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { Doc } from '@/lib/types'
import { cn } from '@/lib/utils'

/* Monthly spend on the Receipts page: total per month (tap a month for its vendors) or per vendor with a 12-month strip.
   Counts receipts, invoices and bills; credit notes subtract; reminders and order confirmations don't count (they'd double
   up the bill). Amounts are summed per currency – the main currency is drawn, others are noted. */
const counts = (d: Doc) => d.amount != null && d.kind !== 'reminder' && d.kind !== 'order' && !!d.date
const signed = (d: Doc) => (d.kind === 'credit' ? -1 : 1) * (d.amount || 0)
const fmt = (n: number, cur: string, dec = 0) => n.toLocaleString('da-DK', { minimumFractionDigits: dec, maximumFractionDigits: dec }) + ' ' + cur
const mLabel = (k: string, long = false) => new Date(k + '-15T12:00').toLocaleDateString('en-GB', long ? { month: 'long', year: 'numeric' } : { month: 'short' })

export function MonthlySpend({ docs, year, vendorName }: { docs: Doc[]; year: string; vendorName: (key: string) => string }) {
  const [mode, setMode] = useState<'month' | 'vendor'>('month')
  const [open, setOpen] = useState<string | null>(null)
  const data = useMemo(() => {
    const ds = docs.filter(counts)
    const byCur: Record<string, number> = {}
    ds.forEach(d => { byCur[d.currency || '?'] = (byCur[d.currency || '?'] || 0) + 1 })
    const cur = Object.entries(byCur).sort((a, b) => b[1] - a[1])[0]?.[0] || 'DKK'
    const main = ds.filter(d => (d.currency || '?') === cur)
    const other = ds.filter(d => (d.currency || '?') !== cur)
    // the months shown: the chosen year, or the last 12 months with documents
    let months: string[]
    if (year !== 'all') months = Array.from({ length: 12 }, (_, i) => `${year}-${String(i + 1).padStart(2, '0')}`)
    else {
      const last = main.map(d => d.date!.slice(0, 7)).sort().pop() || new Date().toISOString().slice(0, 7)
      const [y, m] = last.split('-').map(Number)
      months = Array.from({ length: 12 }, (_, i) => { const dt = new Date(y, m - 1 - (11 - i), 15); return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}` })
    }
    const now = new Date().toISOString().slice(0, 7)
    months = months.filter(k => k <= now)
    const perMonth = months.map(k => {
      const list = main.filter(d => d.date!.startsWith(k))
      const v: Record<string, { key: string; sum: number; n: number }> = {}
      list.forEach(d => { const e = v[d.vendor_key] ||= { key: d.vendor_key, sum: 0, n: 0 }; e.sum += signed(d); e.n++ })
      return { k, sum: list.reduce((s, d) => s + signed(d), 0), n: list.length, vendors: Object.values(v).sort((a, b) => b.sum - a.sum) }
    })
    const vend: Record<string, { key: string; sum: number; n: number; months: Record<string, number>; counts: Record<string, number> }> = {}
    main.filter(d => months.includes(d.date!.slice(0, 7))).forEach(d => {
      const e = vend[d.vendor_key] ||= { key: d.vendor_key, sum: 0, n: 0, months: {}, counts: {} }
      const k = d.date!.slice(0, 7)
      e.sum += signed(d); e.n++; e.months[k] = (e.months[k] || 0) + signed(d); e.counts[k] = (e.counts[k] || 0) + 1
    })
    const vendors = Object.values(vend).sort((a, b) => b.sum - a.sum)
    const otherCur: Record<string, number> = {}
    other.filter(d => months.includes(d.date!.slice(0, 7))).forEach(d => { otherCur[d.currency || '?'] = (otherCur[d.currency || '?'] || 0) + signed(d) })
    const total = perMonth.reduce((s, m) => s + m.sum, 0)
    const active = perMonth.filter(m => m.n).length
    return { cur, months, perMonth, vendors, otherCur, total, avg: active ? total / active : 0 }
  }, [docs, year])

  if (!data.perMonth.some(m => m.n)) return null
  const max = Math.max(1, ...data.perMonth.map(m => m.sum))
  const vmax = Math.max(1, ...data.vendors.map(v => Math.max(0, ...Object.values(v.months))))
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-3">
        <div className="min-w-0 flex-1 basis-[15rem]">
          <div className="text-[15px] font-semibold">Monthly spend</div>
          <div className="text-ink-3 font-mono text-[12px]">{fmt(data.total, data.cur)} · avg {fmt(data.avg, data.cur)}/mo{year === 'all' ? ' · last 12 months' : ' · ' + year}</div>
        </div>
        <ToggleGroup type="single" value={mode} onValueChange={v => v && setMode(v as typeof mode)} aria-label="Show">
          <ToggleGroupItem value="month">Per month</ToggleGroupItem><ToggleGroupItem value="vendor">Per vendor</ToggleGroupItem>
        </ToggleGroup>
      </div>

      {mode === 'month' ? <ol className="divide-y">
        {data.perMonth.slice().reverse().map(m => <li key={m.k}>
          <button disabled={!m.n} onClick={() => setOpen(open === m.k ? null : m.k)} aria-expanded={open === m.k}
            className="hover:bg-bg-2/50 flex w-full items-center gap-3 px-4 py-2.5 text-left disabled:hover:bg-transparent">
            <span className="w-16 shrink-0 text-sm font-medium">{mLabel(m.k)}<span className="text-ink-3 block font-mono text-[11px] font-normal">{m.k.slice(0, 4)}</span></span>
            <span className="bg-bg-2 h-2 min-w-0 flex-1 overflow-hidden rounded-sm">
              <span className="bg-fjord block h-full rounded-r-sm transition-[width] duration-[480ms]" style={{ width: `${Math.max(0, m.sum) / max * 100}%` }} /></span>
            <span className="w-28 shrink-0 text-right font-mono text-[13px] tabular-nums">{m.n ? fmt(m.sum, data.cur) : '–'}</span>
            <span className="text-ink-3 w-10 shrink-0 text-right font-mono text-[12px] tabular-nums max-sm:hidden">{m.n || ''}</span>
            <ChevronRight className={cn('text-ink-3 size-4 shrink-0 transition-transform duration-[220ms]', open === m.k && 'rotate-90', !m.n && 'invisible')} />
          </button>
          {open === m.k && <ul className="ax-reveal bg-bg-2/40 border-t px-4 py-1.5">
            {m.vendors.map(v => <li key={v.key} className="flex items-center gap-3 py-1 text-sm">
              <span className="min-w-0 flex-1 truncate pl-16">{vendorName(v.key)}{v.n > 1 && <span className="text-ink-3 font-mono text-[12px]"> ×{v.n}</span>}</span>
              <span className="font-mono text-[13px] tabular-nums">{fmt(v.sum, data.cur, 2)}</span><span className="w-[calc(2.5rem+28px)] shrink-0 max-sm:w-4" />
            </li>)}
          </ul>}
        </li>)}
      </ol>
      : <ol className="divide-y">
        {data.vendors.map(v => { const vm = Math.max(1, ...Object.values(v.months)); const isOpen = open === 'v:' + v.key
          return <li key={v.key}>
          <button onClick={() => setOpen(isOpen ? null : 'v:' + v.key)} aria-expanded={isOpen}
            className="hover:bg-bg-2/50 flex w-full items-center gap-3 px-4 py-2.5 text-left">
            <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{vendorName(v.key)}</span>
              <span className="text-ink-3 block truncate font-mono text-[12px]">{v.n}× · avg {Math.round(v.sum / Math.max(1, Object.keys(v.months).length)).toLocaleString('da-DK')}/mo</span></span>
            {/* 12-month strip: one bar per month, same scale for every vendor */}
            <span className="flex h-7 shrink-0 items-end gap-[2px] max-[340px]:hidden sm:gap-[3px]" aria-hidden>
              {data.months.map(k => <span key={k} title={`${mLabel(k)}: ${fmt(v.months[k] || 0, data.cur)}`}
                className={cn('w-1 rounded-t-[1px] sm:w-1.5', v.months[k] ? 'bg-fjord' : 'bg-line')} style={{ height: v.months[k] ? `${Math.max(12, Math.max(0, v.months[k]) / vmax * 100)}%` : '2px' }} />)}
            </span>
            <span className="w-20 shrink-0 text-right font-mono text-[13px] tabular-nums sm:w-24">{fmt(v.sum, data.cur)}</span>
            <ChevronRight className={cn('text-ink-3 size-4 shrink-0 transition-transform duration-[220ms]', isOpen && 'rotate-90')} />
          </button>
          {/* the vendor month by month (newest first), bars scaled to this vendor's own biggest month */}
          {isOpen && <ul className="ax-reveal bg-bg-2/40 border-t px-4 py-1.5">
            {data.months.slice().reverse().map(k => <li key={k} className={cn('flex items-center gap-3 py-1 text-sm', !v.months[k] && 'text-ink-3')}>
              <span className="w-20 shrink-0">{mLabel(k)} <span className="text-ink-3 font-mono text-[11px]">{k.slice(2, 4)}</span></span>
              <span className="bg-bg-2 h-1.5 min-w-0 flex-1 overflow-hidden rounded-sm">
                <span className="bg-fjord block h-full rounded-r-sm" style={{ width: `${Math.max(0, v.months[k] || 0) / vm * 100}%` }} /></span>
              <span className="text-ink-3 w-8 shrink-0 text-right font-mono text-[12px] tabular-nums">{v.counts[k] ? '×' + v.counts[k] : ''}</span>
              <span className="w-24 shrink-0 text-right font-mono text-[13px] tabular-nums">{v.months[k] ? fmt(v.months[k], data.cur, 2) : '–'}</span>
              <span className="w-4 shrink-0" />
            </li>)}
          </ul>}
        </li> })}
      </ol>}
      {Object.keys(data.otherCur).length > 0 && <div className="text-ink-3 border-t px-4 py-2 text-xs">
        Also in other currencies (not in the bars): {Object.entries(data.otherCur).map(([c, n]) => fmt(n, c, 2)).join(' · ')}</div>}
    </Card>
  )
}
