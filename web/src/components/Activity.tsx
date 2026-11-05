/* Activity log (account menu): everything done from the dashboard and by Axella itself – replies, filing, tasks,
   contacts, calendar, privacy, notifications, automatic receipt forwards and Claude runs. Titles only, never what was
   written. The newest 1,000, filterable; older than 90 days moves to an archive on the Mac mini. A deleted contact or
   event can be restored from here for 90 days (owner only). GET activity – setup/activity.py. */
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Activity as ActivityIcon, RotateCw, Search as SearchIcon, Undo2 } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Input, NativeSelect } from '@/components/ui/input'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { cn } from '@/lib/utils'

interface Entry { at: string; who: string; action: string; type: string; label: string; title?: string | null; result: string; ok: boolean; backup?: string | null }
interface Log { entries: Entry[]; total: number; capped: boolean; types: string[]; who: string[]; keep_days: number; owner?: boolean }
const TYPE_LABEL: Record<string, string> = { mail: 'Mail', tasks: 'Tasks', calendar: 'Calendar', contacts: 'Contacts', privacy: 'Privacy', items: 'Items',
  assistant: 'Assistant', meetings: 'Meetings', notifications: 'Notifications', reports: 'Reports', settings: 'Settings', runs: 'Claude runs', other: 'Other' }

export function ActivityView() {
  const { ax } = useApp()
  const [f, setF] = useState({ type: '', result: '', who: '', text: '' })
  const [d, setD] = useState<Log | null>(null)
  const [err, setErr] = useState('')
  const [n, setN] = useState(0)
  const [busy, setBusy] = useState<string | null>(null)
  useEffect(() => {
    const q = new URLSearchParams(Object.entries(f).filter(([, v]) => v) as [string, string][])
    const t = setTimeout(() => get<Log>('activity?' + q).then(j => { setD(j); setErr('') }).catch(e => setErr(e.message)), f.text ? 250 : 0)
    return () => clearTimeout(t)
  }, [f, n])
  const days = useMemo(() => {
    const g: [string, Entry[]][] = []
    for (const e of d?.entries || []) {
      const k = new Date(e.at).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })
      const last = g[g.length - 1]
      if (last && last[0] === k) last[1].push(e); else g.push([k, [e]])
    }
    return g
  }, [d])
  async function restore(e: Entry) {
    const action = e.action === 'contact_delete' ? 'contact_restore' : e.action === 'meeting_delete' ? 'meeting_restore' : e.action === 'trip_remove' ? 'trip_restore' : e.action.startsWith('trip_cal_') ? 'cal_restore' : e.action.startsWith('trip_') ? 'trip_undo' : 'cal_restore'
    setBusy(e.backup!)
    try { await ax.act(action, { backup: e.backup, title: e.title || '' }, []); toast.success((e.title || 'It') + ' is back'); setN(x => x + 1) }
    catch (x: any) { toast.error('Not restored: ' + x.message) } finally { setBusy(null) }
  }
  return <div className="space-y-4" data-activity-view="">
    <div className="flex items-start gap-3">
      <div className="min-w-0 flex-1">
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><ActivityIcon className="size-5" />Activity log</h1>
        <p className="text-muted-foreground text-sm">Everything done from the dashboard and by Axella itself – titles only, never what was written. The newest 1,000; older than {d?.keep_days || 90} days is archived on the Mac mini.</p>
      </div>
      <Button size="pill" variant="outline" onClick={() => setN(x => x + 1)}><RotateCw />Refresh</Button>
    </div>
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-[1fr_150px_150px_180px]">
      <label className="relative col-span-2 block sm:col-span-1">
        <SearchIcon className="text-ink-3 pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
        <Input value={f.text} onChange={e => setF({ ...f, text: e.target.value })} placeholder="Search" aria-label="Search the log" className="pl-9" />
      </label>
      <NativeSelect aria-label="Type" value={f.type} onChange={e => setF({ ...f, type: e.target.value })}>
        <option value="">All types</option>{(d?.types || Object.keys(TYPE_LABEL)).map(t => <option key={t} value={t}>{TYPE_LABEL[t] || t}</option>)}</NativeSelect>
      <NativeSelect aria-label="Result" value={f.result} onChange={e => setF({ ...f, result: e.target.value })}>
        <option value="">All results</option><option value="ok">Done</option><option value="error">Refused / failed</option></NativeSelect>
      <NativeSelect aria-label="Who" value={f.who} onChange={e => setF({ ...f, who: e.target.value })}>
        <option value="">Everyone</option>{(d?.who || []).map(w => <option key={w} value={w}>{w === 'axella' ? 'Axella itself' : w}</option>)}</NativeSelect>
    </div>
    {err && <div className="text-dawn text-sm">{err}</div>}
    {!d && !err && <div className="text-ink-3 text-sm">Loading…</div>}
    {d && <div className="text-ink-3 text-[12.5px]">{d.capped ? `Showing the newest 1,000 of ${d.total.toLocaleString('en-GB')}` : `${d.total} ${d.total === 1 ? 'entry' : 'entries'}`}</div>}
    {days.map(([day, list]) => <section key={day} className="bg-card overflow-hidden rounded-lg border">
      <div className="bg-bg-2/60 border-b px-4 py-1.5 text-[13px] font-semibold">{day}</div>
      <div className="divide-y">{list.map((e, i) => <div key={i} className="flex items-start gap-3 px-4 py-2 text-sm" data-activity-row="">
        <span className="text-ink-3 w-11 shrink-0 font-mono text-[12px] leading-6">{new Date(e.at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}</span>
        <span className="min-w-0 flex-1">
          <span className="block"><span className="font-medium">{e.label}</span>{e.title && <span className="text-ink-2"> · {e.title}</span>}</span>
          <span className="text-ink-3 block truncate text-[12.5px]">
            <span className="bg-bg-2 rounded px-1 py-px font-mono text-[11px]">{TYPE_LABEL[e.type] || e.type}</span>
            {' · '}{e.who === 'axella' ? 'Axella itself' : e.who}
            {!e.ok && <span className="text-dawn"> · {e.result}</span>}</span>
        </span>
        {e.backup && e.ok && d?.owner && ax.apiOk && <Button size="pill" variant="outline" disabled={busy === e.backup} onClick={() => restore(e)}
          className={cn('shrink-0')}><Undo2 />Restore</Button>}
      </div>)}</div>
    </section>)}
  </div>
}
