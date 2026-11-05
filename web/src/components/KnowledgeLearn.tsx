import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Check, Loader2, Mail, Pause, Play, Plus, Search, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input, NativeSelect } from '@/components/ui/input'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { loadKnowledge, useKnowledge } from '@/lib/knowledge'
import { profile } from '@/lib/profile'
import { cn, isoDate } from '@/lib/utils'

/* How Axella learns (setup/kb_harvest.py): every night it reads your sent mail and proposes facts; scans work through
   a part of the mailbox you choose, a batch at a time at night. Everything lands in Suggested for you to approve. */
interface Scan {
  id: string; label: string; mailbox?: string | null; account?: string | null; sender?: string | null; query?: string | null
  start?: string | null; end?: string | null; project?: string | null
  status: 'queued' | 'running' | 'paused' | 'done' | 'cancelled'; created: string; threads_done: number; suggestions: number
  total?: number | null; pending?: { rid: string } | null; note?: string | null; last?: string | null
}
interface HState {
  nightly: { enabled: boolean; since?: string | null; last?: string | null; last_result?: string | null; pending?: object | null }
  scans: Scan[]; suggested: number; outdated: number; batch: number; max_batches: number; window: [string, string]; nightly_at: string
}

const when = (d?: string | null) => d ? new Date(d).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''
const STATUS: Record<Scan['status'], string> = { queued: 'waiting for tonight', running: 'in progress', paused: 'paused', done: 'finished', cancelled: 'cancelled' }

export function LearningCard({ onReview }: { onReview: () => void }) {
  const { ax } = useApp()
  const [h, setH] = useState<HState | null>(null)
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const kb = useKnowledge()
  const waiting = (kb || []).filter(e => e.status === 'suggested').length
  const load = () => get<HState>('kb_harvest').then(setH).catch(() => {})
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t) }, [])
  async function act(action: string, p: object, msg: string) {
    setBusy(action + JSON.stringify(p))
    try { await ax.act(action, p, []); toast(msg); await load(); loadKnowledge(true) } catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(null) }
  }
  if (!h) return null
  const live = h.scans.filter(s => s.status !== 'done' && s.status !== 'cancelled')
  const old = h.scans.filter(s => s.status === 'done' || s.status === 'cancelled').slice(-3).reverse()
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-3">
        <div className="min-w-0 flex-1 basis-[16rem]">
          <div className="text-[15px] font-semibold">How Axella learns</div>
          <div className="text-ink-3 text-[13px]">Everything it finds lands in Suggested – nothing is used until you approve it</div>
        </div>
        {waiting > 0 && <Button size="pill" onClick={onReview}><Check />Review {waiting} suggestion{waiting > 1 ? 's' : ''}</Button>}
      </div>
      <div className="flex items-start gap-3 px-4 py-3">
        <Mail className="text-ink-2 mt-0.5 size-4 shrink-0" />
        <div className="min-w-0 flex-1 text-sm">
          <div className="font-medium">Every night from your sent mail</div>
          <div className="text-ink-3 text-[13px]">
            {h.nightly.enabled ? <>At {h.nightly_at}: facts you wrote, your corrections to Axella's drafts, and entries your newer mail contradicts.</> : 'Switched off.'}
            {h.nightly.last && <> Last run {when(h.nightly.last)}{h.nightly.last_result ? ' – ' + h.nightly.last_result : ''}.</>}
            {h.nightly.last_result === 'failed' && <> The last run failed – the next one covers the same mail.</>}
          </div>
        </div>
        <label className="text-ink-2 flex shrink-0 items-center gap-2 text-[13px]">
          <Checkbox checked={h.nightly.enabled} disabled={!!busy} onCheckedChange={v => act('kb_nightly', { enabled: !!v }, v ? 'Nightly learning on' : 'Nightly learning off')} />On</label>
      </div>
      <div className="border-t">
        <div className="flex flex-wrap items-center gap-2 px-4 pt-3 pb-1.5">
          <Search className="text-ink-2 size-4" /><span className="text-sm font-medium">Mailbox scans</span>
          <span className="text-ink-3 text-[12px]">{h.batch} threads a batch · up to {h.max_batches} batches a night ({h.window[0]}–{h.window[1]}) · only threads you answered</span>
          <Button size="pill" variant="outline" className="ml-auto" onClick={() => setAdding(true)}><Plus />New scan</Button>
        </div>
        {!live.length && !old.length && <div className="text-ink-3 px-4 pb-3 text-[13px]">Pick a folder, a sender or a period – e.g. a project folder, or your sent mail of the last year – and Axella works through it at night.</div>}
        {[...live, ...old].map(s => {
          const pct = s.total ? Math.min(100, Math.round(s.threads_done / s.total * 100)) : null
          return <div key={s.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t px-4 py-2.5 first:border-t-0">
            <div className="min-w-0 flex-1 basis-[15rem]">
              <div className="truncate text-sm font-medium">{s.label}</div>
              <div className="text-ink-3 font-mono text-[12px]">
                {s.threads_done}{s.total ? ' of ' + s.total : ''} threads · {s.suggestions} suggestion{s.suggestions === 1 ? '' : 's'} · {s.pending ? 'running now' : STATUS[s.status]}
                {s.start || s.end ? ` · ${s.start || '…'} → ${s.end || 'now'}` : ''}</div>
              {pct != null && s.status !== 'cancelled' && <div className="bg-bg-2 mt-1.5 h-1.5 overflow-hidden rounded-sm">
                <div className={cn('h-full rounded-r-sm transition-[width] duration-[480ms]', s.status === 'done' ? 'bg-success' : 'bg-fjord')} style={{ width: pct + '%' }} /></div>}
              {s.note && <div className="text-ink-2 mt-1 text-[12px]">{s.note}</div>}
            </div>
            {(s.status === 'queued' || s.status === 'running') && !s.pending && <>
              <Button size="pill" variant="outline" disabled={!!busy} onClick={() => act('kb_scan_now', { id: s.id }, 'A batch starts in a moment – see Runs')}><Play />Run a batch now</Button>
              <Button size="icon-pill" variant="ghost" title="Pause" disabled={!!busy} onClick={() => act('kb_scan_pause', { id: s.id }, 'Scan paused')}><Pause /></Button></>}
            {s.pending && <Loader2 className="text-fjord size-4 animate-spin" />}
            {s.status === 'paused' && <Button size="pill" variant="outline" disabled={!!busy} onClick={() => act('kb_scan_resume', { id: s.id }, 'Scan continues tonight')}><Play />Resume</Button>}
            {s.status !== 'done' && s.status !== 'cancelled'
              ? <Button size="icon-pill" variant="ghost" title="Cancel the scan (suggestions so far stay)" disabled={!!busy} onClick={() => act('kb_scan_cancel', { id: s.id }, 'Scan cancelled – its suggestions stay')}><X /></Button>
              : <Button size="icon-pill" variant="ghost" title="Remove from the list" disabled={!!busy} onClick={() => act('kb_scan_remove', { id: s.id }, 'Removed')}><X /></Button>}
          </div>
        })}
      </div>
      {adding && <NewScan onClose={() => setAdding(false)} onAdded={() => { setAdding(false); load() }} />}
    </Card>
  )
}

function NewScan({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const { ax, activeProjects } = useApp()
  const accounts = profile().accounts
  const year = new Date(); year.setFullYear(year.getFullYear() - 1)
  const [f, setF] = useState({ label: '', mailbox: '', account: '', sender: '', query: '', start: isoDate(year), end: '', project: '' })
  const [folders, setFolders] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const set = (p: Partial<typeof f>) => setF(x => ({ ...x, ...p }))
  useEffect(() => {
    const accs = f.account ? [f.account] : accounts.map(a => a.id)
    Promise.all(accs.map(a => get<{ folders: Record<string, string[]> }>('folders?account=' + encodeURIComponent(a)).then(j => j.folders[a] || []).catch(() => [])))
      .then(l => setFolders([...new Set(l.flat())].sort((x, y) => x.localeCompare(y, 'da'))))
  }, [f.account])
  const ok = !!(f.mailbox.trim() || f.sender.trim() || f.query.trim())
  async function add() {
    setBusy(true)
    try {
      await ax.act('kb_scan_add', Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.trim() || null])), [])
      toast('Scan added – Axella works on it tonight, or tap "Run a batch now"'); onAdded()
    } catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(false) }
  }
  const preset = (p: Partial<typeof f>) => set({ label: '', mailbox: '', sender: '', query: '', project: '', ...p })
  return <Dialog open onOpenChange={o => !o && onClose()}>
    <DialogContent>
      <div className="border-b px-5 py-3.5 pr-12">
        <DialogTitle className="flex items-center gap-2 text-base font-semibold"><Search className="size-4" />New mailbox scan</DialogTitle>
        <div className="text-ink-3 text-xs">Axella reads the threads you answered in this part of your mail and suggests facts. Nothing in Mail changes.</div>
      </div>
      <form className="flex-1 space-y-3 overflow-y-auto p-5 text-sm" onSubmit={e => { e.preventDefault(); if (ok) add() }}>
        <div className="flex flex-wrap gap-1.5">
          <span className="text-ink-3 mr-1 self-center text-[13px]">Quick:</span>
          <Button type="button" size="pill" variant="outline" onClick={() => preset({ mailbox: 'Sent', label: 'Sent mail – last 12 months' })}>Sent mail, last year</Button>
          {activeProjects.slice(0, 4).map(p => <Button key={p.id} type="button" size="pill" variant="outline"
            onClick={() => preset({ mailbox: folders.find(x => x.toLowerCase().endsWith(p.name.toLowerCase())) || '', query: folders.some(x => x.toLowerCase().endsWith(p.name.toLowerCase())) ? '' : p.name, project: p.id, label: p.name })}>{p.name}</Button>)}
        </div>
        <label className="block"><span className="mb-1 block font-medium">Folder</span>
          <Input list="ax-scan-folders" value={f.mailbox} onChange={e => set({ mailbox: e.target.value })} placeholder={folders.length ? `Pick or type – ${folders.length} folders` : 'e.g. Easy Timing, Bookings, Sent'} />
          <datalist id="ax-scan-folders">{folders.map(x => <option key={x} value={x} />)}</datalist></label>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block"><span className="mb-1 block font-medium">Sender or domain <span className="text-ink-3 font-normal">(optional)</span></span>
            <Input value={f.sender} onChange={e => set({ sender: e.target.value })} placeholder="e.g. acme.com" /></label>
          <label className="block"><span className="mb-1 block font-medium">Words in the subject <span className="text-ink-3 font-normal">(optional)</span></span>
            <Input value={f.query} onChange={e => set({ query: e.target.value })} placeholder="e.g. booking" /></label>
          <label className="block"><span className="mb-1 block font-medium">Mailbox</span>
            <NativeSelect value={f.account} onChange={e => set({ account: e.target.value })}>
              <option value="">All mailboxes</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}</NativeSelect></label>
          <label className="block"><span className="mb-1 block font-medium">Tie suggestions to a project</span>
            <NativeSelect value={f.project} onChange={e => set({ project: e.target.value })}>
              <option value="">No – Axella decides per fact</option>{activeProjects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</NativeSelect></label>
          <label className="block"><span className="mb-1 block font-medium">From</span><Input type="date" value={f.start} onChange={e => set({ start: e.target.value })} /></label>
          <label className="block"><span className="mb-1 block font-medium">To <span className="text-ink-3 font-normal">(empty = today)</span></span><Input type="date" value={f.end} onChange={e => set({ end: e.target.value })} /></label>
        </div>
        <label className="block"><span className="mb-1 block font-medium">Name <span className="text-ink-3 font-normal">(optional)</span></span>
          <Input value={f.label} onChange={e => set({ label: e.target.value })} placeholder="Shown in the list" /></label>
        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
          <span className="text-ink-3 flex-1 text-[12px]">Runs at night in batches; you can pause or cancel it any time.</span>
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={!ok || busy}>{busy ? <Loader2 className="animate-spin" /> : <Plus />}Start scan</Button>
        </div>
      </form>
    </DialogContent>
  </Dialog>
}
