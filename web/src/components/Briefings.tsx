import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Briefing as BriefingIcon, Check, Headphones, ChevronDown, Loader2, MoreHorizontal, Pencil, Play, Plus, Trash2 } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input, NativeSelect } from '@/components/ui/input'
import { get } from '@/lib/api'
import { start } from '@/components/Listen'
import { useApp } from '@/lib/app'
import type { Brief, Briefing } from '@/lib/types'
import { cn } from '@/lib/utils'

/* Briefings: research and news briefs on the owner's schedule (setup/briefings.py).
   The research run may only search and read the web – no mail, messages or calendar – and only the search queries leave
   the home. Personal context (calendar/projects) is added afterwards by a separate offline run. */
export { BriefingIcon }
const DAY = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const days = (d: number[]) => d.length === 7 ? 'Every day' : d.join() === '0,1,2,3,4' ? 'Weekdays' : d.join() === '5,6' ? 'Weekends' : d.map(i => DAY[i]).join(' ')
export const when = (iso?: string | null, withDay = true) => {
  if (!iso) return ''
  const d = new Date(iso), t = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  if (!withDay) return t
  const today = new Date(); const y = new Date(); y.setDate(today.getDate() - 1)
  const day = d.toDateString() === today.toDateString() ? 'Today' : d.toDateString() === y.toDateString() ? 'Yesterday'
    : d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
  return day + ' ' + t
}

export function useBriefings() {
  const { ax } = useApp()
  const [list, setList] = useState<Briefing[] | null>(null)
  const [max, setMax] = useState(8)
  const load = useCallback(() => get<{ briefings: Briefing[]; max: number }>('briefings')
    .then(j => { setList(j.briefings); setMax(j.max) }).catch(() => setList(l => l || [])), [])
  useEffect(() => { if (ax.apiOk) load() }, [ax.apiOk, load])
  useEffect(() => { const t = setInterval(() => !document.hidden && load(), 60000); return () => clearInterval(t) }, [load])
  return { list, max, load }
}

export function BriefingsView({ open: openId }: { open?: string }) {
  const { ax } = useApp()
  const { list, max, load } = useBriefings()
  const [edit, setEdit] = useState<Partial<Briefing> | null>(null)
  if (!ax.apiOk) return <div className="text-ink-3 text-sm">Briefings need the Mac mini – it isn't answering right now.</div>
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><BriefingIcon className="size-5" />Topic briefs</h1>
          <p className="text-muted-foreground text-sm">Research and news on your schedule – short, with sources, and quiet when nothing is new. Only the search queries leave your home; your mail, messages and calendar never do.</p>
        </div>
        {list && list.length < max && <Button onClick={() => setEdit({ kind: 'research', days: [0], time: '07:30', length: 5, language: 'en', voice: true, personal: false, enabled: true, sources: [] })}><Plus />New briefing</Button>}
      </div>
      {!list ? <div className="text-ink-3 flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" />Loading…</div>
        : !list.length ? <Card className="px-6 py-10 text-center text-sm"><div className="font-semibold">No briefings yet</div>
          <div className="text-ink-3 mt-1">Add one for a topic you'd otherwise go looking for – a weekly research brief or weekday headlines.</div></Card>
        : list.map(b => <BriefingCard key={b.id} b={b} startOpen={b.id === openId} onEdit={() => setEdit(b)} reload={load} />)}
      {list && list.length >= max && <p className="text-ink-3 text-[13px]">That's the maximum of {max} briefings – Axella keeps you informed, it isn't a news app.</p>}
      {edit && <BriefingEditor b={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load() }} />}
    </div>
  )
}

function BriefingCard({ b, startOpen, onEdit, reload }: { b: Briefing; startOpen?: boolean; onEdit: () => void; reload: () => void }) {
  const { ax } = useApp()
  const [busy, setBusy] = useState<string | null>(null)
  const [older, setOlder] = useState<Brief[] | null>(null)
  const [showOlder, setShowOlder] = useState(false)
  const [armed, setArmed] = useState(false)
  useEffect(() => { if (startOpen) document.getElementById('briefing-' + b.id)?.scrollIntoView({ block: 'start', behavior: 'smooth' }) }, [startOpen, b.id])
  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key)
    try { await fn(); toast(ok); reload() } catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(null) }
  }
  const toggleOlder = async () => {
    const o = !showOlder; setShowOlder(o)
    if (o && !older) get<{ briefs: Brief[] }>('briefs?id=' + encodeURIComponent(b.id)).then(j => setOlder(j.briefs.slice(1))).catch(() => setOlder([]))
  }
  return <Card id={'briefing-' + b.id} className={cn('overflow-hidden scroll-mt-20', !b.enabled && 'opacity-75')}>
    <div className="flex items-start gap-3 border-b px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2"><span className="font-semibold">{b.name}</span>
          <span className="text-ink-3 text-[13px]">{b.kind === 'news' ? 'News' : 'Research'}{b.personal ? ' · with your calendar' : ''}{!b.enabled ? ' · paused' : ''}</span></div>
        <div className="text-ink-3 font-mono text-[12px]">{days(b.days)} {b.time}{b.next_run ? ' · next ' + when(b.next_run) : ''}</div>
      </div>
      <Button size="pill" variant="outline" disabled={!!busy} onClick={() => run('run', () => ax.act('briefing_run', { id: b.id }, []),
        'Started – the brief appears here in a few minutes')}>{busy === 'run' ? <Loader2 className="animate-spin" /> : <Play />}Run now</Button>
      <DropdownMenu onOpenChange={o => !o && setArmed(false)}>
        <DropdownMenuTrigger asChild><Button size="icon-pill" variant="outline" aria-label="More"><MoreHorizontal /></Button></DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={onEdit}><Pencil />Edit</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => run('pause', () => ax.act('briefing_save', { ...b, enabled: !b.enabled }, []), b.enabled ? 'Paused' : 'Resumed')}>
            {b.enabled ? 'Pause' : 'Resume'}</DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem destructive onSelect={e => {
            if (!armed) { e.preventDefault(); setArmed(true); setTimeout(() => setArmed(false), 3000); return }
            run('del', () => ax.act('briefing_delete', { id: b.id }, []), b.name + ' removed – earlier briefs are kept on the Mac mini')
          }}><Trash2 />{armed ? 'Tap again to remove' : 'Remove'}</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
    {b.latest ? <BriefBody br={b.latest} /> : <div className="text-ink-3 px-4 py-4 text-sm">No brief yet{b.next_run ? ' – the first one comes ' + when(b.next_run) : ''}.</div>}
    {b.latest && <div className="border-t">
      <button onClick={toggleOlder} className="text-ink-2 hover:bg-bg-2 flex w-full items-center gap-2 px-4 py-2 text-left text-[13px]">
        Older briefs<ChevronDown className={cn('ml-auto size-4 transition-transform', showOlder && 'rotate-180')} /></button>
      {showOlder && <div className="ax-reveal divide-y border-t">
        {!older ? <div className="text-ink-3 px-4 py-3 text-sm">Loading…</div>
          : !older.length ? <div className="text-ink-3 px-4 py-3 text-sm">No older briefs yet.</div>
          : older.map(o => <details key={o.id} className="group">
            <summary className="hover:bg-bg-2 flex cursor-pointer list-none items-baseline gap-3 px-4 py-2.5 text-sm">
              <span className="text-ink-3 w-28 shrink-0 font-mono text-[12px]">{when(o.at)}</span><span className="min-w-0 flex-1 truncate">{o.headline}</span>
              <ChevronDown className="text-ink-3 size-4 shrink-0 self-center transition-transform group-open:rotate-180" /></summary>
            <BriefBody br={o} compact />
          </details>)}
      </div>}
    </div>}
  </Card>
}

export function BriefBody({ br, compact }: { br: Brief; compact?: boolean }) {
  return <div className={cn('px-4', compact ? 'pb-3' : 'py-3')}>
    {!compact && <div className="text-ink-3 mb-1 flex items-center font-mono text-[12px]">{when(br.at)}
      {Date.now() - new Date(br.at).getTime() < 36 * 3600e3 && <button onClick={() => start('b-' + br.briefing + '-' + br.id)} className="text-fjord ml-auto flex items-center gap-1 font-sans text-[13px] font-medium hover:underline"><Headphones className="size-4" />Listen</button>}</div>}
    {br.nothing_new
      ? <div className="text-ink-2 flex items-center gap-2 text-sm"><Check className="text-fjord size-4" />{br.headline}</div>
      : <>
        {!compact && <div className="mb-2 font-medium">{br.headline}</div>}
        <ol className="space-y-3">
          {br.items.map((it, i) => <li key={i} className="flex gap-3">
            <span className="ax-diamond text-fjord mt-[7px] shrink-0" style={{ width: 6, height: 6 }} />
            <div className="min-w-0 text-sm">
              <a href={it.url} target="_blank" rel="noopener noreferrer" className="font-semibold underline-offset-2 hover:underline">{it.title}</a>
              <div className="text-ink-2 mt-0.5 leading-relaxed">{it.summary}</div>
              <div className="text-ink-3 mt-0.5 text-[12px]">{it.source}{it.published ? <span className="font-mono"> · {it.published}</span> : null}</div>
            </div>
          </li>)}
        </ol>
        {br.personal_note && <div className="text-ink-2 border-fjord/40 mt-3 border-l-2 pl-3 text-sm"><span className="ax-label mr-2">For you</span>{br.personal_note}</div>}
      </>}
    {br.outbound && <details className="text-ink-3 mt-3 text-[12px]">
      <summary className="hover:text-ink cursor-pointer">Left your home: {br.outbound.queries.length} search{br.outbound.queries.length === 1 ? '' : 'es'}, {br.outbound.fetched} page{br.outbound.fetched === 1 ? '' : 's'} read · {br.outbound.provider}</summary>
      {/* recorded from the run's own tool calls on the Mac mini, not from what the model said it did */}
      <ul className="mt-1.5 space-y-0.5 break-all font-mono text-[11.5px]">
        {br.outbound.queries.map((q, i) => <li key={'q' + i}>search: {q}</li>)}
        {(br.outbound.urls || []).map((u, i) => <li key={'u' + i}>page: {u}</li>)}
      </ul></details>}
  </div>
}

function BriefingEditor({ b, onClose, onSaved }: { b: Partial<Briefing>; onClose: () => void; onSaved: () => void }) {
  const { ax } = useApp()
  const [f, setF] = useState<Partial<Briefing>>({ ...b })
  const [src, setSrc] = useState((b.sources || []).join('\n'))
  const [busy, setBusy] = useState(false)
  const set = (x: Partial<Briefing>) => setF(o => ({ ...o, ...x }))
  const day = (i: number) => set({ days: (f.days || []).includes(i) ? (f.days || []).filter(x => x !== i) : [...(f.days || []), i].sort() })
  const save = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true)
    try {
      await ax.act('briefing_save', { ...f, sources: src.split(/[\n,]+/).map(s => s.trim()).filter(Boolean) }, [])
      toast(b.id ? 'Briefing saved' : 'Briefing added'); onSaved()
    } catch (err: any) { toast.error('Not saved: ' + err.message) } finally { setBusy(false) }
  }
  const lbl = 'text-ink-2 grid gap-1.5 text-[13px] font-medium'
  return <Dialog open onOpenChange={o => !o && onClose()}>
    <DialogContent>
      <form onSubmit={save} className="flex min-h-0 flex-1 flex-col">
        <div className="border-b px-5 py-4 pr-12"><DialogTitle className="text-lg font-semibold">{b.id ? 'Edit briefing' : 'New briefing'}</DialogTitle></div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
          <label className={lbl}>Name<Input autoFocus value={f.name || ''} maxLength={60} required placeholder="e.g. News in my field" onChange={e => set({ name: e.target.value })} /></label>
          <label className={lbl}>What should Axella look for?
            <textarea value={f.prompt || ''} maxLength={1500} required rows={4} onChange={e => set({ prompt: e.target.value })}
              placeholder="Describe the topic and what matters to you – e.g. what happened this week in my field: launches, deals and events. Prefer news from the source over opinion pieces."
              className="border-input bg-card placeholder:text-ink-3 focus-visible:ring-ring/50 rounded-md border px-3 py-2 text-[15px] font-normal outline-none focus-visible:ring-2" /></label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className={lbl}>Kind<NativeSelect value={f.kind} onChange={e => set({ kind: e.target.value as Briefing['kind'] })}>
              <option value="research">Research – find out what happened</option><option value="news">News – headlines from sources</option></NativeSelect></label>
            <label className={lbl}>Language<NativeSelect value={f.language} onChange={e => set({ language: e.target.value as Briefing['language'] })}>
              <option value="en">English</option><option value="da">Danish</option></NativeSelect></label>
          </div>
          <div className={lbl}>Days
            <div className="flex flex-wrap gap-1.5">{DAY.map((d, i) => <button type="button" key={d} onClick={() => day(i)} aria-pressed={(f.days || []).includes(i)}
              className={cn('h-8 w-11 rounded-md border text-[13px]', (f.days || []).includes(i) ? 'bg-fjord-soft border-fjord text-fjord font-semibold' : 'bg-card text-ink-2')}>{d}</button>)}</div></div>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className={lbl}>Time<Input type="time" value={f.time || '07:30'} required onChange={e => set({ time: e.target.value })} /></label>
            <label className={lbl}>Items<NativeSelect value={f.length} onChange={e => set({ length: +e.target.value })}>
              {[3, 4, 5, 6, 7, 8].map(n => <option key={n} value={n}>Up to {n}</option>)}</NativeSelect></label>
          </div>
          <label className={lbl}>Preferred sources <span className="text-ink-3 font-normal">optional – sites or feeds, one per line</span>
            <textarea value={src} rows={2} onChange={e => setSrc(e.target.value)} placeholder="e.g. a news site, a trade magazine or an RSS feed – one per line"
              className="border-input bg-card placeholder:text-ink-3 focus-visible:ring-ring/50 rounded-md border px-3 py-2 text-[15px] font-normal outline-none focus-visible:ring-2" /></label>
          <label className="flex items-start gap-2.5 text-sm"><input type="checkbox" className="accent-fjord mt-0.5 size-4" checked={!!f.personal} onChange={e => set({ personal: e.target.checked })} />
            <span><span className="font-medium">Use my calendar</span><span className="text-ink-3 block text-[13px]">Adds a short note like "You're free Saturday afternoon". Done afterwards on the Mac mini, without web access – nothing personal goes into a search.</span></span></label>
          <label className="flex items-start gap-2.5 text-sm"><input type="checkbox" className="accent-fjord mt-0.5 size-4" checked={f.voice !== false} onChange={e => set({ voice: e.target.checked })} />
            <span><span className="font-medium">Include when I listen</span><span className="text-ink-3 block text-[13px]">The brief is read after the digest in Listen.</span></span></label>
        </div>
        <div className="flex justify-end gap-2 border-t px-5 py-3">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy}>{busy && <Loader2 className="animate-spin" />}{b.id ? 'Save' : 'Add briefing'}</Button>
        </div>
      </form>
    </DialogContent>
  </Dialog>
}

/* Today: a quiet card when briefs arrived since the latest digest – collapsed to one line per brief */
export function BriefsCard({ since }: { since?: string | null }) {
  const { ax, go } = useApp()
  const [briefs, setBriefs] = useState<Brief[]>([])
  useEffect(() => {
    if (!ax.apiOk) return
    const s = since || new Date(Date.now() - 864e5).toISOString()
    const f = () => get<{ briefs: Brief[] }>('briefs?since=' + encodeURIComponent(s)).then(j => setBriefs(j.briefs || [])).catch(() => {})
    f()
    const t = setInterval(() => !document.hidden && f(), 60000)        // a brief that arrives while Today is open shows up
    addEventListener('focus', f)
    return () => { clearInterval(t); removeEventListener('focus', f) }
  }, [ax.apiOk, since])
  if (!briefs.length) return null
  return <Card className="overflow-hidden">
    <div className="flex items-center border-b px-4 py-2.5"><span className="ax-label">Topic briefs</span>
      <button className="text-fjord ml-auto text-[13px] font-medium" onClick={() => go({ kind: 'briefings' })}>All briefings</button></div>
    <div className="divide-y">{briefs.slice(0, 4).map(br => <button key={br.briefing + br.id} onClick={() => go({ kind: 'briefings', id: br.briefing })}
      className="hover:bg-bg-2 block w-full px-4 py-2.5 text-left text-sm">
      <div className="flex items-baseline gap-2"><span className="min-w-0 flex-1 truncate font-medium">{br.headline}</span>
        <span className="text-ink-3 shrink-0 font-mono text-[12px]">{when(br.at, false)}</span></div>
      <div className="text-ink-3 truncate text-[13px]">{br.nothing_new ? 'Nothing new' : br.items.map(i => i.title).join(' · ')}</div>
    </button>)}</div>
  </Card>
}
