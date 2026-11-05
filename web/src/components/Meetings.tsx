/* Meeting prep (dev request claude/dev-request-meeting-prep.md): a Meetings page with upcoming meetings and their
   prep status, and one prep per meeting – a form (goals, points to discuss, background, notes, materials, people)
   that also reads as a document (print / PDF, download). The assistant works on this meeting only and proposes cards
   you add with a tap; nothing is sent. Owner only. setup/meetings.py. */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import {
  ArrowDownRight, ArrowUpRight, CalendarCheck, CalendarDays, Meeting, Check, ChevronRight, ClipboardCopy, Copy, ExternalLink, FileText, Link2, Loader2,
  Mail, MailPlus, MoreHorizontal, Paperclip, Play, Plus, Search as SearchIcon, Sparkles, Square, Trash2, Upload, UserCircle, X,
} from '@/components/ax-icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input, NativeSelect } from '@/components/ui/input'
import { withUndo } from '@/components/Contacts'
import { useCalendarRefresh } from '@/lib/calendarBus'
import { PendingInvites } from '@/components/Invite'
import { openKnowledge } from '@/lib/knowledge'
import { openCompose } from '@/components/Compose'
import { AnswersPoint, ProjectAdd, Speakers, TranscribeStatus, WaitingRecordings, useChunkRecorder } from '@/components/MeetingsFinish'
import { get, post } from '@/lib/api'
import { useApp } from '@/lib/app'
import {
  agendaText, fileUrl, fmtWhen, joinLink, prepForEvent, prepMarkdown, reloadPreps, startFromEvent, startManual, uploadMaterial, uploadTranscript, usePreps,
  type CalEv, type Card as AssistCard, type MeetingCtx, type Outcome, type Outcomes, type Point, type Prep, type PrepSummary,
} from '@/lib/meetings'
import { rowsOf, todayRows, type Row } from '@/lib/meetingRows'
import type { Item, Project } from '@/lib/types'
import { cn, isoDate } from '@/lib/utils'

export const MeetingIcon = Meeting
const DAY = 864e5
const hm = (s: string) => new Date(s).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
const dayHead = (d: Date) => {
  const t = new Date(); t.setHours(0, 0, 0, 0)
  const k = Math.round((new Date(d).setHours(0, 0, 0, 0) - t.getTime()) / DAY)
  return k === 0 ? 'Today' : k === 1 ? 'Tomorrow' : d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })
}
const TA = 'border-line-strong bg-card focus-visible:border-ring focus-visible:ring-ring/30 w-full rounded-md border px-3 py-2 text-[16px] leading-relaxed outline-none focus-visible:ring-2 sm:text-sm'
const SECTION_LABEL: Record<AssistCard['section'], string> = { goals: 'Goals', points: 'To discuss', background: 'Background', notes: 'Notes' }

/* ---------- start a prep from anywhere: New menu, a mail's ⋯ menu ---------- */
export const openNewPrep = (init?: { title?: string; item?: Item; project?: string; attendees?: { name: string; email: string }[] }) => window.dispatchEvent(new CustomEvent('ax-new-prep', { detail: init || {} }))
export function NewPrepHost() {
  const { go } = useApp()
  const [init, setInit] = useState<{ title?: string; item?: Item; project?: string; attendees?: { name: string; email: string }[] } | null>(null)
  const [f, setF] = useState({ title: '', date: '', time: '' })
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const h = (e: Event) => { const d = (e as CustomEvent).detail || {}; setInit(d); setF({ title: d.title || d.item?.subject || (d.item?.headline || '').replace(/\*\*/g, '').slice(0, 120) || '', date: '', time: '' }) }
    window.addEventListener('ax-new-prep', h); return () => window.removeEventListener('ax-new-prep', h)
  }, [])
  if (!init) return null
  async function create() {
    setBusy(true)
    try {
      const it = init!.item
      const start = f.date ? new Date(f.date + 'T' + (f.time || '09:00')).toISOString() : null
      const extra: Record<string, unknown> = init!.project ? { project: init!.project } : {}
      if (init!.attendees?.length) extra.attendees = init!.attendees      // from a person's page
      if (it?.message_id) {
        extra.mail = { account: it.account, message_id: it.message_id, subject: it.subject || it.headline, date: it.date || '',
          from: it.from ? `${it.from.name || ''} <${it.from.address || ''}>` : '' }
        if (it.from?.address) extra.attendees = [{ name: it.from.name || it.from.address, email: it.from.address }]
      }
      const id = await startManual(f.title.trim(), start, extra)
      setInit(null); go({ kind: 'meeting', id })
    } catch (e: any) { toast.error('Not started: ' + e.message) } finally { setBusy(false) }
  }
  return <Dialog open onOpenChange={o => !o && setInit(null)}>
    <DialogContent className="sm:w-[min(460px,92vw)]">
      <form className="space-y-3 p-5" onSubmit={e => { e.preventDefault(); if (f.title.trim()) create() }}>
        <DialogTitle className="text-lg font-semibold">New meeting prep</DialogTitle>
        {init.item && <p className="text-ink-3 text-[13px]">The mail is added to the materials.</p>}
        <label className="block text-sm"><span className="mb-1 block font-medium">Meeting</span>
          <Input autoFocus value={f.title} maxLength={200} onChange={e => setF({ ...f, title: e.target.value })} placeholder="Call with Acme about the offer" /></label>
        <div className="grid grid-cols-2 gap-2">
          <label className="block text-sm"><span className="mb-1 block font-medium">Date <span className="text-ink-3 font-normal">(optional)</span></span>
            <Input type="date" value={f.date} onChange={e => setF({ ...f, date: e.target.value })} /></label>
          <label className="block text-sm"><span className="mb-1 block font-medium">Time</span>
            <Input type="time" value={f.time} disabled={!f.date} onChange={e => setF({ ...f, time: e.target.value })} /></label>
        </div>
        <p className="text-ink-3 text-[12.5px]">For a meeting in your calendar, use Prepare on the event instead – it brings the people and the join link.</p>
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={() => setInit(null)}>Cancel</Button>
          <Button type="submit" disabled={busy || !f.title.trim()}>{busy ? <Loader2 className="animate-spin" /> : <Plus />}Start prep</Button>
        </div>
      </form>
    </DialogContent>
  </Dialog>
}

/** "Prepare" / "Open prep" for a calendar event (event sheet) */
export function PrepareButton({ e, onGo }: { e: CalEv; onGo?: () => void }) {
  const { go, ax } = useApp()
  const { preps, owner } = usePreps()
  const [busy, setBusy] = useState(false)
  if (!ax.apiOk || !owner || e.all_day) return null
  const p = prepForEvent(preps, e)
  if (p) return <Button size="pill" variant="outline" onClick={() => { onGo?.(); go({ kind: 'meeting', id: p.id }) }} data-open-prep="">
    <MeetingIcon />Open prep{p.status === 'ready' ? ' · ready' : ''}</Button>
  return <Button size="pill" variant="outline" disabled={busy || !preps} data-prepare="" onClick={async () => {
    setBusy(true)
    try { const id = await startFromEvent(e); onGo?.(); go({ kind: 'meeting', id }) } catch (x: any) { toast.error('Not started: ' + x.message) } finally { setBusy(false) }
  }}>{busy ? <Loader2 className="animate-spin" /> : <MeetingIcon />}Prepare</Button>
}

/* ---------- events of the next days, for the Meetings page and the Today card ---------- */
function useUpcoming(days: number) {
  const [ev, setEv] = useState<CalEv[] | null>(null)
  const [err, setErr] = useState('')
  const [n, setN] = useState(0)
  const fresh = useRef(false)
  useCalendarRefresh(f => { fresh.current = f; setN(x => x + 1) })
  useEffect(() => {
    const a = new Date(), b = new Date(Date.now() + days * DAY)
    const f = fresh.current; fresh.current = false
    get<{ events: CalEv[] }>(`calendar?from=${isoDate(a)}&to=${isoDate(b)}${f ? '&fresh=1' : ''}`).then(j => { setEv(j.events || []); setErr('') }).catch(e => { setEv([]); setErr(e.message) })
  }, [days, n])
  return { events: ev, err, reload: () => setN(x => x + 1) }
}

function PrepChip({ p }: { p: PrepSummary | null }) {
  if (!p) return <span className="text-ink-3 font-mono text-[11.5px]">No prep</span>
  return <span className={cn('rounded-sm px-1.5 py-px font-mono text-[11.5px]', p.status === 'ready' ? 'bg-fjord-soft text-fjord' : 'bg-bg-2 text-ink-2')}>
    {p.status === 'ready' ? 'Ready' : 'Draft'}{p.points ? ` · ${p.done}/${p.points}` : ''}</span>
}

/* ---------- the Meetings page ---------- */
export function MeetingsView() {
  const { go, ctx, ax } = useApp()
  const { preps, owner } = usePreps()
  const { events, err } = useUpcoming(14)
  const [all, setAll] = useState(false)
  const [q, setQ] = useState('')
  const inCtx = (x: { ctx: 'work' | 'private' | null }) => ctx === 'all' || !x.ctx || x.ctx === ctx
  const rows = useMemo(() => rowsOf(events, preps, all).filter(inCtx), [events, preps, all, ctx]) // eslint-disable-line react-hooks/exhaustive-deps
  const days = useMemo(() => {
    const g: [string, Row[]][] = []
    for (const r of rows) { const k = dayHead(new Date(r.start!)); const l = g[g.length - 1]; if (l && l[0] === k) l[1].push(r); else g.push([k, [r]]) }
    return g
  }, [rows])
  const now = Date.now()
  const nodate = (preps || []).filter(p => !p.start && inCtx(p))
  const past = (preps || []).filter(p => p.start && new Date(p.end || p.start).getTime() < now && inCtx(p)
    && (!q.trim() || (p.title + ' ' + p.attendees.map(a => a.name + ' ' + a.email).join(' ')).toLowerCase().includes(q.trim().toLowerCase())))
  if (!ax.apiOk) return <p className="text-ink-3 text-sm">Meeting prep needs the Mac mini.</p>
  if (!owner) return <p className="text-ink-3 text-sm">Meeting preps are the owner's own.</p>
  const open = (r: Row) => r.prep ? go({ kind: 'meeting', id: r.prep.id }) : null
  return <div className="space-y-4" data-meetings-view="">
    <div className="flex items-start gap-3">
      <div className="min-w-0 flex-1">
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><MeetingIcon className="size-5" />Meetings</h1>
        <p className="text-muted-foreground text-sm">Prepare what you want out of a meeting – goals, points, background and material in one place.</p>
      </div>
      <Button size="pill" onClick={() => openNewPrep()}><Plus />New prep</Button>
    </div>
    <Card className="overflow-hidden">
      <div className="flex items-center gap-2 border-b px-4 py-2.5">
        <span className="ax-label">Next 14 days</span>
        <label className="text-ink-2 ml-auto flex items-center gap-2 text-[13px]"><Checkbox checked={all} onCheckedChange={v => setAll(!!v)} />Show other events too</label>
      </div>
      {err && <div className="text-dawn px-4 py-2 text-sm">Calendar: {err}</div>}
      {!events || !preps ? <div className="text-ink-3 px-4 py-3 text-sm">Loading…</div>
        : !rows.length ? <div className="text-ink-3 flex items-center gap-1.5 px-4 py-3.5 text-sm"><Check className="text-success size-4" />No meetings in the next 14 days</div>
        : days.map(([day, list]) => <div key={day}>
          <div className="bg-bg-2/60 border-b px-4 py-1.5 text-[13px] font-semibold">{day}</div>
          <div className="divide-y border-b last:border-b-0">{list.map(r => <div key={r.key} className="flex min-h-11 items-center gap-3 px-4 py-2" data-meeting-row="">
            <span className="text-ink-3 w-11 shrink-0 font-mono text-[12px]">{hm(r.start!)}</span>
            <span className="size-2 shrink-0 rounded-full" style={{ background: r.ctx === 'work' ? 'var(--ax-work)' : r.ctx === 'private' ? 'var(--ax-private)' : 'var(--ax-ink-3)' }} />
            <button className="min-w-0 flex-1 text-left" onClick={() => open(r)} disabled={!r.prep}>
              <span className="block truncate text-sm font-medium">{r.title}</span>
              <span className="text-ink-3 block truncate text-[12.5px]">{r.sub}{r.others ? ` · ${r.others} other${r.others === 1 ? '' : 's'}` : ''}{r.ev?.join && !r.others ? ' · online' : ''}{r.repeats ? ` · repeats – ${r.repeats} times in 14 days, the next shown` : ''}</span>
            </button>
            <PrepChip p={r.prep} />
            {r.prep ? <Button size="pill" variant="ghost" onClick={() => open(r)} aria-label="Open prep"><ChevronRight /></Button>
              : r.ev && <PrepareButton e={r.ev} />}
          </div>)}</div>
        </div>)}
    </Card>
    <PendingInvites />
    <WorkplaceDefaults />
    {nodate.length > 0 && <Card className="overflow-hidden">
      <div className="ax-label border-b px-4 py-2.5">No date yet</div>
      <div className="divide-y">{nodate.map(p => <PrepLine key={p.id} p={p} />)}</div>
    </Card>}
    {preps && (preps.some(p => p.start && new Date(p.end || p.start).getTime() < now)) && <Card className="overflow-hidden">
      <div className="flex items-center gap-2 border-b px-4 py-2">
        <span className="ax-label">Past</span>
        <label className="relative ml-auto block w-48 max-w-[55%]">
          <SearchIcon className="text-ink-3 pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
          <Input value={q} onChange={e => setQ(e.target.value)} placeholder="Search" aria-label="Search past meetings" className="h-8 pl-8" /></label>
      </div>
      <div className="divide-y">{past.length ? past.slice(0, 60).map(p => <PrepLine key={p.id} p={p} />) : <div className="text-ink-3 px-4 py-3 text-sm">Nothing found</div>}</div>
    </Card>}
  </div>
}
function PrepLine({ p }: { p: PrepSummary }) {
  const { go } = useApp()
  return <button className="hover:bg-bg-2/50 flex min-h-11 w-full items-center gap-3 px-4 py-2 text-left" onClick={() => go({ kind: 'meeting', id: p.id })} data-prep-line="">
    <span className="text-ink-3 w-28 shrink-0 font-mono text-[12px]">{p.start ? new Date(p.start).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: '2-digit' }) : '—'}</span>
    <span className="min-w-0 flex-1 truncate text-sm font-medium">{p.title}</span>
    <PrepChip p={p} /><ChevronRight className="text-ink-3 size-4" />
  </button>
}

/* ---------- Today: a quiet card for the next meeting(s) ---------- */
export function MeetingsCard() {
  const { go, ax, ctx } = useApp()
  const { preps, owner } = usePreps()
  const { events } = useUpcoming(2)
  if (!ax.apiOk || !owner || !events || !preps) return null
  const now = Date.now()
  const rows = todayRows(events, preps, now).filter(r => ctx === 'all' || !r.ctx || r.ctx === ctx)
  const soon = rows.filter(r => r.prep && new Date(r.start!).getTime() - now < 2 * 36e5)
  const missing = rows.filter(r => !r.prep && r.ev).slice(0, 3)
  if (!soon.length && !missing.length) return null
  return <Card className="overflow-hidden" data-meetings-card="">
    <div className="flex items-center border-b px-4 py-2.5"><span className="ax-label">Meetings</span>
      <button className="text-fjord ml-auto text-[13px] font-medium" onClick={() => go({ kind: 'meetings' })}>All</button></div>
    <div className="divide-y">
      {soon.map(r => <button key={r.key} className="hover:bg-bg-2/50 block w-full px-4 py-2.5 text-left text-sm" onClick={() => go({ kind: 'meeting', id: r.prep!.id })}>
        <span className="font-medium">{r.title}</span> <span className="text-ink-3 font-mono text-[12px]">at {hm(r.start!)}</span>
        <span className="text-ink-3 block text-[12.5px]">Prep {r.prep!.status === 'ready' ? 'ready' : 'in draft'}{r.prep!.points ? ` · ${r.prep!.points} point${r.prep!.points === 1 ? '' : 's'}` : ''}</span></button>)}
      {missing.map(r => <div key={r.key} className="flex items-center gap-2 px-4 py-2 text-sm">
        <span className="min-w-0 flex-1"><span className="block truncate">{r.title}</span>
          <span className="text-ink-3 font-mono text-[12px]">{dayHead(new Date(r.start!))} {hm(r.start!)} · no prep yet</span></span>
        <PrepareButton e={r.ev!} /></div>)}
    </div>
  </Card>
}

/* ---------- one prep ---------- */
type Draft = Pick<Prep, 'title' | 'goals' | 'background' | 'notes' | 'points' | 'status' | 'ctx' | 'project' | 'location' | 'join' | 'start' | 'end' | 'outcomes'>
const FIELDS: (keyof Draft)[] = ['title', 'goals', 'background', 'notes', 'points', 'status', 'ctx', 'project', 'location', 'join', 'start', 'end', 'outcomes']

export function MeetingPrepView({ id }: { id: string }) {
  const { go, activeProjects } = useApp()
  const [prep, setPrep] = useState<Prep | null>(null)
  const [d, setD] = useState<Draft | null>(null)
  const [err, setErr] = useState('')
  const [saved, setSaved] = useState<'saved' | 'saving' | 'error' | null>(null)
  const [mode, setMode] = useState<'form' | 'doc'>('form')
  const [ctxInfo, setCtxInfo] = useState<MeetingCtx | null>(null)
  const [ctxErr, setCtxErr] = useState('')
  const [shielded, setShielded] = useState(false)
  const [ai, setAi] = useState<'none' | 'own' | 'all'>('all')
  const [aiInfo, setAiInfo] = useState<{ source: string; workplaces: string[] }>({ source: 'ordinary', workplaces: [] })
  const dirty = useRef<Set<keyof Draft>>(new Set())
  const dRef = useRef(d); dRef.current = d
  const timer = useRef<number | undefined>(undefined)

  const load = useCallback(() => get<{ prep: Prep; protected?: boolean; ai?: 'none' | 'own' | 'all'; ai_source?: string; workplaces?: string[] }>('meeting?id=' + encodeURIComponent(id)).then(j => {
    setPrep(j.prep); setShielded(!!j.protected); setAi(j.ai || 'all'); setAiInfo({ source: j.ai_source || 'ordinary', workplaces: j.workplaces || [] }); setD(x => x && dirty.current.size ? x : pick(j.prep)); setErr('')
  }).catch(e => setErr(e.message)), [id])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    setCtxInfo(null); setCtxErr('')
    get<MeetingCtx>('meeting_context?id=' + encodeURIComponent(id)).then(setCtxInfo).catch(e => setCtxErr(e.message))
  }, [id, prep?.attendees.length])                     // eslint-disable-line react-hooks/exhaustive-deps

  const flush = useCallback(async () => {
    window.clearTimeout(timer.current)
    const cur = dRef.current
    if (!cur || !dirty.current.size) return
    const body: Record<string, unknown> = { id, title: cur.title }
    dirty.current.forEach(k => { body[k] = cur[k] })
    dirty.current = new Set()
    setSaved('saving')
    try { await post('meeting_update', body); setSaved('saved'); reloadPreps() }
    catch (e: any) { setSaved('error'); toast.error('Not saved: ' + e.message) }
  }, [id])
  useEffect(() => () => { flush() }, [flush])
  useEffect(() => { const h = () => { if (dirty.current.size) flush() }; window.addEventListener('pagehide', h); return () => window.removeEventListener('pagehide', h) }, [flush])
  const set = <K extends keyof Draft>(k: K, v: Draft[K], now = false) => {
    setD(x => x ? { ...x, [k]: v } : x); dirty.current.add(k); setSaved(null)
    window.clearTimeout(timer.current)
    if (now) setTimeout(flush, 0); else timer.current = window.setTimeout(flush, 1200)
  }
  const addTo = (c: AssistCard) => {
    if (!d) return
    if (c.section === 'points') set('points', [...d.points, { text: c.text, done: false }], true)
    else set(c.section, (d[c.section] ? d[c.section].trimEnd() + '\n\n' : '') + c.text, true)
    toast('Added to ' + SECTION_LABEL[c.section])
  }

  if (err) return <div className="space-y-3"><BackLink /><p className="text-dawn text-sm">{err}</p></div>
  if (!prep || !d) return <div className="space-y-3"><BackLink /><p className="text-ink-3 text-sm">Loading…</p></div>
  const full: Prep = { ...prep, ...d }
  const del = () => withUndo(`Deleting the prep for ${prep.title}…`, async () => {
    try {
      await post('meeting_delete', { id, title: prep.title }); reloadPreps()
      toast.success('Prep deleted – Restore from the Activity log for 90 days'); go({ kind: 'meetings' })
    } catch (e: any) { toast.error('Not deleted: ' + e.message) }
  })
  return <div className="space-y-4" data-prep-view="">
    <div className="flex flex-wrap items-center gap-2 print:hidden">
      <BackLink />
      <span className="text-ink-3 ml-auto font-mono text-[12px]" aria-live="polite">{saved === 'saving' ? 'Saving…' : saved === 'saved' ? 'Saved' : saved === 'error' ? 'Not saved' : ''}</span>
      <div className="bg-bg-2 flex rounded-md p-0.5 text-[13px]" role="tablist">
        {(['form', 'doc'] as const).map(m => <button key={m} role="tab" aria-selected={mode === m} onClick={() => { flush(); setMode(m) }}
          className={cn('rounded px-2.5 py-1', mode === m ? 'bg-card shadow-sm font-medium' : 'text-ink-2')}>{m === 'form' ? 'Prepare' : 'Document'}</button>)}
      </div>
      <PrepMenu prep={full} people={ctxInfo?.people} onDelete={del} onPrint={() => { flush(); setMode('doc'); setTimeout(() => window.print(), 150) }} />
    </div>
    {mode === 'doc' ? <PrepDocument prep={full} people={ctxInfo} /> : <>
      <Header prep={prep} d={d} set={set} projects={activeProjects} onLinked={async () => { await flush(); load() }} />
      <div className="grid grid-cols-1 items-start gap-4 min-[1100px]:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-4">
          <Section title="Goals" hint="What a good result looks like">
            <AutoText value={d.goals} onChange={v => set('goals', v)} onBlur={flush} rows={2} placeholder="Agree the price · decide on the scope" maxLength={5000} />
          </Section>
          <Section title="To discuss" hint={d.points.length ? `${d.points.filter(p => p.done).length} of ${d.points.length} done` : 'Tick them off during the meeting'}>
            <Points points={d.points} onChange={pts => set('points', pts, true)} />
          </Section>
          <Section title="Background" hint="Who, history, where things stand">
            <AutoText value={d.background} onChange={v => set('background', v)} onBlur={flush} rows={4} maxLength={20000} />
          </Section>
          <Section title="Notes" hint="Also during the meeting">
            <AutoText value={d.notes} onChange={v => set('notes', v)} onBlur={flush} rows={4} maxLength={30000} />
          </Section>
          <Materials prep={prep} onChanged={load} />
          <AfterMeeting prep={full} shielded={shielded && ai !== 'all'} off={shielded && ai === 'none'} onChanged={load} flush={flush}
            setOutcomes={(o, now) => set('outcomes', o, now)} />
        </div>
        <div className="min-w-0 space-y-4">
          {shielded && <AiChoice prep={prep} ai={ai} info={aiInfo} onChange={async v => {
            const was = ai; if (v) setAi(v)
            try { await post('meeting_update', { id, title: d.title, ai: v }); toast(v ? 'Saved for this meeting' : 'Back to the default'); load() } catch (e: any) { setAi(was); toast.error(e.message) }
          }} />}
          <Assistant prep={full} off={shielded && ai === 'none'} open={!shielded || ai === 'all'} flush={flush} onAdd={addTo} onSummary={async (mid, text) => {
            try { await post('meeting_material_update', { id, material: mid, summary: text, title: prep.title }); load(); toast('Summary kept with the material') } catch (e: any) { toast.error(e.message) }
          }} />
          <People info={ctxInfo} err={ctxErr} onPoint={t => addTo({ section: 'points', text: t })} />
        </div>
      </div>
    </>}
  </div>
}
const pick = (p: Prep): Draft => Object.fromEntries(FIELDS.map(k => [k, p[k]])) as Draft
function BackLink() {
  const { go } = useApp()
  return <button className="text-fjord flex items-center gap-1 text-sm font-medium" onClick={() => go({ kind: 'meetings' })}><ChevronRight className="size-4 rotate-180" />Meetings</button>
}
function Section({ title, hint, right, children }: { title: string; hint?: string; right?: ReactNode; children: ReactNode }) {
  return <Card className="overflow-hidden" data-prep-section={title}>
    <div className="flex items-baseline gap-2 border-b px-4 py-2.5">
      <span className="text-[15px] font-semibold">{title}</span>{hint && <span className="text-ink-3 truncate text-[12.5px]">{hint}</span>}
      {right && <span className="ml-auto">{right}</span>}
    </div>
    <div className="p-3">{children}</div>
  </Card>
}
function AutoText({ value, onChange, onBlur, rows, placeholder, maxLength }: { value: string; onChange: (v: string) => void; onBlur?: () => void; rows: number; placeholder?: string; maxLength: number }) {
  return <textarea value={value} onChange={e => onChange(e.target.value)} onBlur={onBlur} maxLength={maxLength} placeholder={placeholder}
    rows={Math.min(24, Math.max(rows, value.split('\n').length + 1))} className={TA} />
}

function Header({ prep, d, set, projects, onLinked }: { prep: Prep; d: Draft; set: <K extends keyof Draft>(k: K, v: Draft[K], now?: boolean) => void; projects: Project[]; onLinked: () => void }) {
  const linked = !!prep.event
  const [pick, setPick] = useState(false)
  const [armed, setArmed] = useState(false)
  const suggest = !d.project ? suggestProject(projects, d.title, prep.attendees) : null
  async function unlink() {
    if (!armed) { setArmed(true); setTimeout(() => setArmed(false), 3000); return }
    try { await post('meeting_update', { id: prep.id, title: d.title, event: null }); toast('No longer linked to the calendar'); reloadPreps(); onLinked() } catch (e: any) { toast.error(e.message) }
  }
  const local = (s: string | null) => s ? new Date(new Date(s).getTime() - new Date(s).getTimezoneOffset() * 6e4).toISOString().slice(0, 16) : ''
  return <Card className="space-y-3 p-4">
    <input value={d.title} maxLength={200} onChange={e => set('title', e.target.value)} aria-label="Meeting title"
      className="w-full bg-transparent text-xl font-semibold tracking-tight outline-none" />
    <div className="text-ink-2 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
      {linked ? <span className="flex items-center gap-1.5"><CalendarDays className="size-4" />{fmtWhen(d.start, true)}{d.end ? '–' + hm(d.end) : ''}
          <span className="text-ink-3 text-[12.5px]">· from {prep.event?.calendar || 'Calendar'}{prep.event?.recurring ? ', repeats' : ''}</span>
          <button className={cn('text-[12.5px]', armed ? 'text-danger font-medium' : 'text-ink-3 hover:text-ink')} onClick={unlink}>{armed ? 'Unlink?' : 'Unlink'}</button></span>
        : <><label className="flex items-center gap-1.5"><CalendarDays className="size-4" />
          <input type="datetime-local" value={local(d.start)} onChange={e => set('start', e.target.value ? new Date(e.target.value).toISOString() : null, true)}
            className="border-line-strong bg-card rounded-md border px-2 py-1 text-sm" aria-label="When" /></label>
          <Button size="pill" variant="outline" onClick={() => setPick(true)} data-link-event=""><CalendarDays />Link to a calendar event…</Button></>}
      {d.location && <span className="truncate">{d.location}</span>}
      {d.join && <Button size="pill" asChild><a href={d.join} target="_blank" rel="noopener noreferrer"><ExternalLink />Join</a></Button>}
    </div>
    <div className="flex flex-wrap items-center gap-2">
      <div className="bg-bg-2 flex rounded-md p-0.5 text-[13px]" role="radiogroup" aria-label="Status">
        {(['draft', 'ready'] as const).map(s => <button key={s} role="radio" aria-checked={d.status === s} onClick={() => set('status', s, true)}
          className={cn('rounded px-2.5 py-1', d.status === s ? (s === 'ready' ? 'bg-fjord text-on-fjord' : 'bg-card shadow-sm') : 'text-ink-2')}>{s === 'draft' ? 'Draft' : 'Ready'}</button>)}
      </div>
      <NativeSelect aria-label="Work or Private" value={d.ctx || ''} onChange={e => set('ctx', (e.target.value || null) as Draft['ctx'], true)} className="h-8 w-auto text-[13px]">
        <option value="">Work or Private</option><option value="work">Work</option><option value="private">Private</option></NativeSelect>
      <NativeSelect aria-label="Project" value={d.project || ''} onChange={e => set('project', e.target.value || null, true)} className="h-8 w-auto max-w-56 text-[13px]">
        <option value="">No project</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</NativeSelect>
      {suggest && <button className="bg-fjord-soft text-fjord rounded-sm px-2 py-1 text-[12.5px]" onClick={() => set('project', suggest.id, true)} data-suggest-project="">
        <Plus className="mr-0.5 inline size-3.5" />{suggest.name}?</button>}
      {prep.attendees.length > 0 && <span className="text-ink-3 truncate text-[12.5px]">With {prep.attendees.map(a => a.name).slice(0, 4).join(', ')}{prep.attendees.length > 4 ? ` +${prep.attendees.length - 4}` : ''}</span>}
    </div>
    {pick && <LinkEvent prep={prep} title={d.title} start={d.start} onClose={() => setPick(false)} onDone={() => { setPick(false); onLinked() }} />}
  </Card>
}

/** A project that fits the meeting: its name, tag or a keyword in the title, or an attendee among its senders. */
function suggestProject(projects: Project[], title: string, people: { email: string }[]) {
  const t = title.toLowerCase()
  const mails = people.map(p => p.email.toLowerCase()).filter(Boolean)
  return projects.find(p => [p.name, p.tag, ...(p.keywords || [])].some(k => k && k.length > 3 && t.includes(k.toLowerCase()))
    || (p.senders || []).some(s => mails.some(m => m === s.toLowerCase() || (s.startsWith('@') && m.endsWith(s.toLowerCase()))))) || null
}

/** Link a prep started by hand to an event: it takes the event's time, place, join link and people. */
function LinkEvent({ prep, title, start, onClose, onDone }: { prep: Prep; title: string; start: string | null; onClose: () => void; onDone: () => void }) {
  const { preps } = usePreps()
  const [ev, setEv] = useState<CalEv[] | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const a = start ? new Date(start) : new Date(), b = new Date(a.getTime() + (start ? 1 : 14) * DAY)
    if (start) a.setDate(a.getDate() - 1)
    get<{ events: CalEv[] }>(`calendar?from=${isoDate(a)}&to=${isoDate(b)}`).then(j => setEv((j.events || []).filter(e => !e.all_day && !prepForEvent(preps, e)))).catch(() => setEv([]))
  }, [start, preps])
  async function link(e: CalEv) {
    setBusy(true)
    const people = [...prep.attendees]
    for (const x of e.people || []) if (!people.some(y => (y.email && y.email === x.email) || y.name === x.name)) people.push(x)
    try {
      await post('meeting_update', { id: prep.id, title, event: { id: e.id, start: e.start, calendar: e.calendar, recurring: e.recurring },
        start: e.start, end: e.end, location: prep.location || e.location || '', join: prep.join || joinLink(e) || '', attendees: people, ctx: prep.ctx || e.ctx })
      toast('Linked to ' + e.title); reloadPreps(); onDone()
    } catch (x: any) { toast.error(x.message) } finally { setBusy(false) }
  }
  return <Dialog open onOpenChange={o => !o && onClose()}>
    <DialogContent className="sm:w-[min(520px,92vw)]">
      <div className="space-y-3 p-5">
        <DialogTitle className="text-lg font-semibold">Link to a calendar event</DialogTitle>
        <p className="text-ink-3 text-[13px]">{start ? 'Events around ' + fmtWhen(start) : 'Events in the next 14 days'} without a prep. The prep takes the event's time, place, join link and people.</p>
        <div className="max-h-[50vh] divide-y overflow-y-auto rounded-md border">
          {!ev ? <div className="text-ink-3 px-3 py-2 text-sm">Loading…</div> : !ev.length ? <div className="text-ink-3 px-3 py-2 text-sm">No events without a prep</div>
            : ev.map(e => <button key={e.id + e.start} disabled={busy} onClick={() => link(e)} className="hover:bg-bg-2/50 flex w-full items-center gap-3 px-3 py-2 text-left" data-link-pick="">
              <span className="text-ink-3 w-28 shrink-0 font-mono text-[12px]">{fmtWhen(e.start)}</span>
              <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{e.title}</span>
                <span className="text-ink-3 block truncate text-[12px]">{e.calendar_label}{e.attendees ? ` · ${e.attendees} other${e.attendees === 1 ? '' : 's'}` : ''}</span></span>
            </button>)}
        </div>
      </div>
    </DialogContent>
  </Dialog>
}

/** "Claude and this meeting" – for a meeting with a protected workplace (an employer or a client): the owner decides. */
function AiChoice({ prep, ai, info, onChange }: { prep: Prep; ai: 'none' | 'own' | 'all'; info: { source: string; workplaces: string[] }; onChange: (v: 'none' | 'own' | 'all' | null) => void }) {
  const { go } = useApp()
  const wp = info.workplaces.join(' and ') || 'this workplace'
  const opts: ['none' | 'own' | 'all', string, string][] = [
    ['own', 'My own text only', 'Goals, points, notes and background you wrote. The workplace’s mail, documents and transcripts stay on the Mac mini.'],
    ['all', 'Everything for this meeting', 'Also transcripts, documents and the workplace’s mail with the attendees.'],
    ['none', 'Nothing', 'The assistant is off for this meeting. Transcription still runs on the Mac mini.'],
  ]
  return <Section title="Claude and this meeting" hint={'With ' + wp}>
    <div className="space-y-1.5" role="radiogroup" aria-label="What may go to Claude" data-ai-choice="">
      {opts.map(([v, label, sub]) => <label key={v} className={cn('flex cursor-pointer gap-2.5 rounded-md border px-3 py-2', ai === v ? 'border-fjord bg-fjord-soft' : 'hover:bg-bg-2/40')}>
        <input type="radio" name={'ai-' + prep.id} checked={ai === v} onChange={() => onChange(v)} className="mt-1 accent-[var(--ax-fjord)]" />
        <span><span className="block text-sm font-medium">{label}</span><span className="text-ink-3 block text-[12.5px]">{sub}</span></span>
      </label>)}
      <p className="text-ink-3 text-[11.5px]">{info.source === 'meeting' ? <>Chosen for this meeting. <button className="text-fjord" onClick={() => onChange(null)}>Use the default for {wp}</button></>
        : info.source === 'workplace' ? <>The default for {wp} – change it here for this meeting, or <button className="text-fjord" onClick={() => go({ kind: 'meetings' })}>the default on the Meetings page</button>.</>
        : <>No default set for {wp} yet – <button className="text-fjord" onClick={() => go({ kind: 'meetings' })}>set one on the Meetings page</button>.</>}
        {' '}Check what your workplace allows before choosing Everything.</p>
    </div>
  </Section>
}

/* ---------- a project's meetings (project page) ---------- */
export function ProjectMeetings({ project }: { project: { id: string; name: string } }) {
  const { ax } = useApp()
  const { preps, owner } = usePreps()
  if (!ax.apiOk || !owner || !preps) return null
  const list = preps.filter(p => p.project === project.id)
  return <Card className="overflow-hidden" data-project-meetings="">
    <div className="flex items-center gap-3 border-b px-4 py-3">
      <span className="bg-bg-2 flex size-10 items-center justify-center rounded-md"><MeetingIcon className="size-5" /></span>
      <span className="text-[15px] font-semibold">Meetings</span>
      <Button size="pill" variant="ghost" className="ml-auto" onClick={() => openNewPrep({ title: '', project: project.id })}><Plus />New prep</Button>
    </div>
    {list.length ? <div className="divide-y">{list.map(p => <PrepLine key={p.id} p={p} />)}</div>
      : <p className="text-ink-3 px-4 py-3 text-sm">No meeting preps for {project.name} yet – pick the project on a prep, or start one here.</p>}
  </Card>
}


function Points({ points, onChange }: { points: Point[]; onChange: (p: Point[]) => void }) {
  const [v, setV] = useState('')
  const [edit, setEdit] = useState<number | null>(null)
  const [t, setT] = useState('')
  const move = (i: number, k: number) => { const n = [...points]; const [x] = n.splice(i, 1); n.splice(i + k, 0, x); onChange(n) }
  return <div className="space-y-1" data-points="">
    {points.map((p, i) => <div key={p.id || i} className="group flex min-h-10 items-start gap-2.5 rounded-md px-1 py-1 hover:bg-bg-2/40">
      <Checkbox className="mt-[3px]" checked={p.done} aria-label={'Done: ' + p.text} onCheckedChange={c => onChange(points.map((x, j) => j === i ? { ...x, done: !!c } : x))} />
      {edit === i ? <Input autoFocus value={t} onChange={e => setT(e.target.value)} className="h-8 flex-1"
          onBlur={() => { if (t.trim()) onChange(points.map((x, j) => j === i ? { ...x, text: t.trim() } : x)); setEdit(null) }}
          onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); if (e.key === 'Escape') setEdit(null) }} />
        : <button className={cn('min-w-0 flex-1 text-left text-sm leading-6 [overflow-wrap:anywhere]', p.done && 'text-ink-3 line-through')} onClick={() => { setEdit(i); setT(p.text) }}>
          <span className="text-ink-3 mr-1.5 font-mono text-[12px]">{i + 1}.</span>{p.text}
          {p.carried && <span className="text-ink-3 ml-1.5 text-[11.5px]">· from last time</span>}</button>}
      <span className="flex shrink-0 gap-0.5 opacity-60 group-hover:opacity-100">
        <button aria-label="Move up" disabled={!i} onClick={() => move(i, -1)} className="text-ink-3 hover:text-ink rounded p-1 disabled:opacity-30"><ArrowUpRight className="size-4 -rotate-45" /></button>
        <button aria-label="Move down" disabled={i === points.length - 1} onClick={() => move(i, 1)} className="text-ink-3 hover:text-ink rounded p-1 disabled:opacity-30"><ArrowDownRight className="size-4 rotate-45" /></button>
        <button aria-label={'Remove ' + p.text} onClick={() => onChange(points.filter((_, j) => j !== i))} className="text-ink-3 hover:text-danger rounded p-1"><X className="size-4" /></button>
      </span>
    </div>)}
    <form className="flex gap-2 pt-1" onSubmit={e => { e.preventDefault(); if (v.trim()) { onChange([...points, { text: v.trim(), done: false }]); setV('') } }}>
      <Input value={v} onChange={e => setV(e.target.value)} placeholder="Add a point" maxLength={1000} aria-label="Add a point" />
      <Button type="submit" variant="outline" disabled={!v.trim()} aria-label="Add point"><Plus /></Button>
    </form>
  </div>
}

function Materials({ prep, onChanged }: { prep: Prep; onChanged: () => void }) {
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [armed, setArmed] = useState<string | null>(null)
  const file = useRef<HTMLInputElement>(null)
  async function up(files: FileList | null) {
    for (const f of Array.from(files || [])) {
      setBusy('up')
      try { const r = await uploadMaterial(prep.id, f); toast(r.chars ? `Added ${f.name}` : `Added ${f.name} – no text could be read from it`) }
      catch (e: any) { toast.error(f.name + ': ' + e.message) }
    }
    setBusy(null); onChanged(); reloadPreps()
  }
  async function addUrl() {
    setBusy('url')
    try { const r = await post<{ result: { title: string; chars: number } }>('meeting_url_add', { id: prep.id, url: url.trim(), title: prep.title }); setUrl(''); toast('Added ' + (r.result.title || 'the page')); onChanged() }
    catch (e: any) { toast.error('Not added: ' + e.message) } finally { setBusy(null) }
  }
  async function remove(mid: string) {
    if (armed !== mid) { setArmed(mid); setTimeout(() => setArmed(a => a === mid ? null : a), 3000); return }
    try { await post('meeting_material_remove', { id: prep.id, material: mid, title: prep.title }); onChanged() } catch (e: any) { toast.error(e.message) }
  }
  return <Section title="Materials" hint="Files, web pages and mails" right={<>
      <input ref={file} type="file" hidden multiple accept=".pdf,.docx,.txt,.md,.ics,image/*" onChange={e => { up(e.target.files); e.target.value = '' }} />
      <ProjectAdd prep={prep} onChanged={onChanged} />
      <Button size="pill" variant="outline" disabled={!!busy} onClick={() => file.current?.click()}>{busy === 'up' ? <Loader2 className="animate-spin" /> : <Upload />}Upload</Button></>}>
    <div className="space-y-2" data-materials=""
      onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); up(e.dataTransfer.files) }}>
      {prep.materials.filter(m => m.kind !== 'transcript').map(m => <div key={m.id} className="flex items-start gap-2.5 rounded-md border px-3 py-2" data-material="">
        {m.kind === 'mail' ? <Mail className="text-ink-2 mt-0.5 size-4 shrink-0" /> : m.kind === 'url' ? <Link2 className="text-ink-2 mt-0.5 size-4 shrink-0" /> : <Paperclip className="text-ink-2 mt-0.5 size-4 shrink-0" />}
        <div className="min-w-0 flex-1 text-sm">
          {m.kind === 'file' ? <a className="text-fjord block truncate font-medium hover:underline" href={fileUrl(prep, m)} target="_blank" rel="noopener noreferrer">{m.name}</a>
            : m.kind === 'url' ? <a className="text-fjord block truncate font-medium hover:underline" href={m.url} target="_blank" rel="noopener noreferrer">{m.name}</a>
            : <span className="block truncate font-medium">{m.name}</span>}
          <span className="text-ink-3 block truncate text-[12px]">
            {m.kind === 'mail' ? [m.from, m.date].filter(Boolean).join(' · ') : m.kind === 'url' ? m.url : m.kind === 'project' ? 'From the project – it keeps the original' : (m.size ? Math.max(1, Math.round(m.size / 1e3)) + ' kB' : '')}
            {m.protected ? ' · protected workplace – content stays in Mail' : m.kind !== 'mail' && m.kind !== 'project' && !m.chars ? ' · no text read' : ''}</span>
          {m.summary && <p className="text-ink-2 mt-1 text-[13px] whitespace-pre-wrap">{m.summary}</p>}
        </div>
        <button onClick={() => remove(m.id)} className={cn('shrink-0 rounded px-1.5 py-0.5 text-[12px]', armed === m.id ? 'text-danger font-medium' : 'text-ink-3 hover:text-danger')} aria-label={'Remove ' + m.name}>
          {armed === m.id ? 'Remove?' : <X className="size-4" />}</button>
      </div>)}
      {!prep.materials.some(m => m.kind !== 'transcript') && <p className="text-ink-3 text-[13px]">Drop a PDF, Word or text file here – or add a web page below. Mails come in from a mail's ⋯ menu (Prepare meeting).</p>}
      <form className="flex gap-2" onSubmit={e => { e.preventDefault(); if (/^https?:\/\//.test(url.trim())) addUrl() }}>
        <Input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…" aria-label="Add a web page" inputMode="url" />
        <Button type="submit" variant="outline" disabled={!!busy || !/^https?:\/\/\S+\.\S+/.test(url.trim())}>{busy === 'url' ? <Loader2 className="animate-spin" /> : <Link2 />}Add page</Button>
      </form>
      <p className="text-ink-3 text-[11.5px]">A page is fetched once by the Mac mini when you add it, and shows under What leaves my home.</p>
    </div>
  </Section>
}

function People({ info, err, onPoint }: { info: MeetingCtx | null; err: string; onPoint: (t: string) => void }) {
  const { go } = useApp()
  return <Section title="People and context" hint="From Contacts, Mail, To do">
    {err ? <p className="text-dawn text-sm">{err}</p> : !info ? <p className="text-ink-3 flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" />Looking through your mail…</p> : <div className="space-y-3 text-sm" data-people="">
      {!info.people.length && <p className="text-ink-3 text-[13px]">No people on this meeting yet – they come from the calendar invite or the mail you started from.</p>}
      {info.people.map(p => <div key={p.email || p.name}>
        <div className="flex items-center gap-1.5"><UserCircle className="text-ink-3 size-4" /><span className="font-medium">{p.name}</span>
          {p.private && <Badge variant="secondary">Private – not used</Badge>}{p.protected && !p.private && <Badge variant="secondary">Protected</Badge>}</div>
        {p.email && <div className="text-ink-3 pl-5.5 text-[12px]">{p.email}{p.last ? ' · last mail ' + new Date(p.last).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : ''}</div>}
        {p.subjects.slice(0, 3).map((s, i) => <div key={i} className="text-ink-2 truncate pl-5.5 text-[12.5px]">{s.from_me ? '→ ' : '← '}{s.subject}</div>)}
      </div>)}
      {info.tasks.length > 0 && <div><div className="ax-label mb-1">Open tasks</div>{info.tasks.map(t => <div key={t.id} className="text-ink-2 flex gap-1.5 text-[13px]"><Square className="mt-0.5 size-3.5 shrink-0" />{t.text}</div>)}</div>}
      {info.waiting.length > 0 && <div><div className="ax-label mb-1">Waiting on them</div>{info.waiting.map((w, i) => <div key={i} className="text-ink-2 text-[13px]">{w.headline.replace(/\*\*/g, '')}</div>)}</div>}
      {info.earlier.length > 0 && <div><div className="ax-label mb-1">Earlier meetings</div>{info.earlier.map(e => <div key={e.id} className="mb-1.5">
        <button className="text-fjord text-[13px] font-medium hover:underline" onClick={() => go({ kind: 'meeting', id: e.id })}>{e.title} · {new Date(e.start).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}</button>
        {e.open.map((o, i) => <div key={i} className="text-ink-2 flex items-center gap-1.5 text-[13px]"><span className="min-w-0 flex-1">Open: {o}</span>
          <button className="text-fjord shrink-0 text-[12px]" onClick={() => onPoint(o)}>Add</button></div>)}
      </div>)}</div>}
    </div>}
  </Section>
}

/* ---------- the assistant: this meeting only, cards you add with a tap ---------- */
type Result = { kind: string; answer: string; cards: AssistCard[]; material?: string }
function Assistant({ prep, off, open, flush, onAdd, onSummary }: { prep: Prep; off: boolean; open: boolean; flush: () => Promise<void>; onAdd: (c: AssistCard) => void; onSummary: (mid: string, text: string) => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [res, setRes] = useState<Result | null>(null)
  const [q, setQ] = useState('')
  const [used, setUsed] = useState<Set<number>>(new Set())
  const [mat, setMat] = useState('')
  const [speaking, setSpeaking] = useState(false)
  const mats = prep.materials.filter(m => (open || !m.protected) && m.kind !== 'transcript')
  async function run(kind: string, extra: Record<string, unknown> = {}) {
    await flush()
    setBusy(kind); setRes(null); setUsed(new Set())
    try {
      const r = await post<{ result: { answer: string; cards: AssistCard[] } }>('meeting_assist', { id: prep.id, kind, title: prep.title, ...extra })
      setRes({ kind, ...r.result, material: extra.material as string | undefined })
      if (kind === 'brief' && r.result.answer) speak(r.result.answer)
    } catch (e: any) { toast.error(e.message) } finally { setBusy(null) }
  }
  function speak(t: string) {
    if (!('speechSynthesis' in window)) return
    speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(t); u.rate = 0.97
    u.lang = /[æøå]/i.test(t) ? 'da-DK' : 'en-GB'
    u.onend = () => setSpeaking(false); setSpeaking(true); speechSynthesis.speak(u)
  }
  useEffect(() => () => { if ('speechSynthesis' in window) speechSynthesis.cancel() }, [])
  const B = ({ kind, children }: { kind: string; children: ReactNode }) =>
    <Button size="pill" variant="outline" disabled={!!busy || off} onClick={() => run(kind)}>{busy === kind ? <Loader2 className="animate-spin" /> : <Sparkles />}{children}</Button>
  return <Section title="Assistant" hint="Works on this meeting only">
    <div className="space-y-3" data-assistant="">
      <div className="flex flex-wrap gap-1.5">
        <B kind="background">Draft the background</B><B kind="points">Suggest points</B><B kind="questions">What might they ask?</B><B kind="brief">Brief me in 60 s</B>
      </div>
      {mats.length > 0 && <div className="flex gap-2">
        <NativeSelect value={mat} onChange={e => setMat(e.target.value)} aria-label="Material to summarise" className="h-9 min-w-0 flex-1 text-[13px]">
          <option value="">Summarise a material…</option>{mats.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</NativeSelect>
        <Button size="pill" variant="outline" disabled={!!busy || !mat || off} onClick={() => run('summary', { material: mat })}>{busy === 'summary' ? <Loader2 className="animate-spin" /> : <FileText />}Summarise</Button>
      </div>}
      <form className="flex gap-2" onSubmit={e => { e.preventDefault(); if (q.trim()) run('ask', { question: q.trim() }) }}>
        <Input value={q} onChange={e => setQ(e.target.value)} placeholder="Ask about this meeting" maxLength={1000} aria-label="Ask about this meeting" />
        <Button type="submit" variant="outline" disabled={!!busy || !q.trim() || off}>{busy === 'ask' ? <Loader2 className="animate-spin" /> : 'Ask'}</Button>
      </form>
      {busy && <p className="text-ink-3 text-[12.5px]">Reading the meeting and its material… this can take a minute.</p>}
      {res && <div className="bg-bg-2/50 space-y-2 rounded-md border p-3" data-assist-result="">
        {res.answer && <p className="text-[13.5px] leading-relaxed whitespace-pre-wrap">{res.answer}</p>}
        {res.kind === 'brief' && res.answer && <Button size="pill" variant="outline" onClick={() => speaking ? (speechSynthesis.cancel(), setSpeaking(false)) : speak(res.answer)}>
          {speaking ? <Square /> : <Play />}{speaking ? 'Stop' : 'Play again'}</Button>}
        {res.kind === 'summary' && res.material && res.answer && <Button size="pill" variant="outline" onClick={() => onSummary(res.material!, res.answer)}><Check />Keep with the material</Button>}
        {res.cards.map((c, i) => <div key={i} className="bg-card flex items-start gap-2 rounded-md border px-3 py-2" data-assist-card="">
          <p className="min-w-0 flex-1 text-[13px] whitespace-pre-wrap">{c.text}</p>
          <Button size="pill" variant={used.has(i) ? 'ghost' : 'outline'} disabled={used.has(i)} onClick={() => { onAdd(c); setUsed(s => new Set(s).add(i)) }}>
            {used.has(i) ? <><Check />Added</> : <><Plus />{SECTION_LABEL[c.section]}</>}</Button>
        </div>)}
        {!res.answer && !res.cards.length && <p className="text-ink-3 text-[13px]">Nothing to suggest from what's here.</p>}
      </div>}
      <p className="text-ink-3 text-[11.5px]">{off ? 'Claude is off for this meeting – change it above.' : open
        ? 'Sends this prep, its material and the context to Claude – private contacts are left out. Nothing is added without your tap.'
        : 'Sends your own goals, points and notes to Claude – the workplace\'s mail, documents and transcripts stay on the Mac mini. Nothing is added without your tap.'}</p>
    </div>
  </Section>
}

/* ---------- the document view (print / PDF) and the ⋯ menu ---------- */
function PrepDocument({ prep, people }: { prep: Prep; people: MeetingCtx | null }) {
  const H = ({ children }: { children: ReactNode }) => <h2 className="mt-6 mb-2 text-[15px] font-semibold tracking-tight">{children}</h2>
  const P = ({ t }: { t: string }) => <p className="text-[14px] leading-relaxed whitespace-pre-wrap">{t}</p>
  return <article data-print-doc="" className="bg-card mx-auto max-w-[760px] rounded-lg border px-8 py-8 print:border-0 print:px-0 print:py-0">
    <div className="ax-label">Meeting prep{prep.status === 'ready' ? '' : ' · draft'}</div>
    <h1 className="mt-1 text-2xl font-semibold tracking-tight">{prep.title}</h1>
    <p className="text-ink-2 mt-1 font-mono text-[13px]">{[fmtWhen(prep.start, true), prep.location].filter(Boolean).join(' · ')}</p>
    {prep.attendees.length > 0 && <p className="text-ink-2 mt-1 text-[13px]">With {prep.attendees.map(a => a.name).join(', ')}</p>}
    {prep.join && <p className="mt-1 truncate text-[13px]"><a className="text-fjord" href={prep.join}>{prep.join}</a></p>}
    {prep.goals.trim() && <><H>Goals</H><P t={prep.goals.trim()} /></>}
    {prep.points.length > 0 && <><H>To discuss</H><ol className="space-y-1 text-[14px]">{prep.points.map((p, i) => <li key={i} className="flex gap-2">
      <span className="text-ink-3 w-5 shrink-0 text-right font-mono text-[12px] leading-6">{i + 1}.</span><span className={cn('leading-6', p.done && 'line-through opacity-70')}>{p.text}{p.done && <span className="sr-only"> (done)</span>}</span></li>)}</ol></>}
    {prep.background.trim() && <><H>Background</H><P t={prep.background.trim()} /></>}
    {prep.notes.trim() && <><H>Notes</H><P t={prep.notes.trim()} /></>}
    {prep.outcomes && (prep.outcomes.summary.trim() || prep.outcomes.items.some(i => i.state !== 'dismissed')) && <><H>Outcomes</H>
      {prep.outcomes.summary.trim() && <P t={prep.outcomes.summary.trim()} />}
      {OUTCOME_GROUPS.map(([k, h]) => { const l = prep.outcomes!.items.filter(i => i.kind === k && i.state !== 'dismissed'); return l.length ? <div key={k} className="mt-3">
        <div className="text-[13px] font-semibold">{h}</div><ul className="mt-1 list-disc space-y-0.5 pl-5 text-[14px]">{l.map((i, n) => <li key={n}>{i.who ? i.who + ': ' : ''}{i.text}{i.due ? <span className="text-ink-3"> · by {i.due}</span> : null}</li>)}</ul></div> : null })}</>}
    {prep.materials.some(m => m.kind !== 'transcript') && <><H>Materials</H><ul className="space-y-1.5 text-[14px]">{prep.materials.filter(m => m.kind !== 'transcript').map(m => <li key={m.id}>
      <span className="font-medium">{m.name}</span>{m.kind === 'url' && m.url ? <span className="text-ink-3"> – {m.url}</span> : m.kind === 'mail' ? <span className="text-ink-3"> – mail{m.from ? ' from ' + m.from : ''}</span> : null}
      {m.summary && <p className="text-ink-2 mt-0.5 text-[13px] whitespace-pre-wrap">{m.summary}</p>}</li>)}</ul></>}
    {people && people.people.length > 0 && <><H>People</H><ul className="text-[14px]">{people.people.map(p => <li key={p.email || p.name}>{p.name}{p.email ? <span className="text-ink-3"> · {p.email}</span> : null}</li>)}</ul></>}
  </article>
}
function PrepMenu({ prep, people, onDelete, onPrint }: { prep: Prep; people?: MeetingCtx['people']; onDelete: () => void; onPrint: () => void }) {
  const [armed, setArmed] = useState(false)
  const emails = prep.attendees.map(a => a.email).filter(Boolean)
  const copy = (t: string, what: string) => navigator.clipboard.writeText(t).then(() => toast(what + ' copied')).catch(() => toast.error('Could not copy'))
  const mailAgenda = () => mailTo(emails, 'Agenda: ' + prep.title, agendaText(prep))
  function download() {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([prepMarkdown(prep, people)], { type: 'text/markdown' }))
    a.download = prep.title.replace(/[^\w\- ]+/g, '').trim().replace(/\s+/g, '-').toLowerCase().slice(0, 60) + '-prep.md'
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000)
  }
  return <DropdownMenu onOpenChange={o => !o && setArmed(false)}>
    <DropdownMenuTrigger asChild><Button size="pill" variant="outline" aria-label="More"><MoreHorizontal /></Button></DropdownMenuTrigger>
    <DropdownMenuContent align="end">
      <DropdownMenuItem onSelect={() => copy(agendaText(prep), 'Agenda')}><ClipboardCopy />Copy agenda</DropdownMenuItem>
      <DropdownMenuItem disabled={!emails.length} onSelect={mailAgenda}><MailPlus />Mail the agenda{emails.length > 1 ? ' (opens Mail)' : ''}</DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem onSelect={onPrint}><FileText />Print or save as PDF</DropdownMenuItem>
      <DropdownMenuItem onSelect={download}><Copy />Download as text (.md)</DropdownMenuItem>
      <DropdownMenuItem onSelect={() => copy(prepMarkdown(prep, people), 'Prep')}><ClipboardCopy />Copy the whole prep</DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem destructive onSelect={e => { if (!armed) { e.preventDefault(); setArmed(true) } else onDelete() }}><Trash2 />{armed ? 'Tap again to delete' : 'Delete prep…'}</DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
}


/** Axella's own composer – one recipient or several (sent on your tap; Mail checks the recipients before sending). */
function mailTo(emails: string[], subject: string, body: string) {
  openCompose({ to: emails.join(', '), subject, body })
}

/* ---------- V2: after the meeting – recording or transcript, outcomes, follow-up mail ---------- */
const OUTCOME_GROUPS: [Outcome['kind'], string][] = [['decision', 'Decisions'], ['task', 'Your tasks'], ['waiting', 'Waiting on others'], ['fact', 'Worth keeping']]
let capsCache: Promise<{ transcribe: boolean; why?: string | null; model?: string | null }> | null = null
const loadCaps = () => (capsCache ||= get<{ transcribe: boolean; why?: string | null; model?: string | null }>('meeting_caps').catch(() => ({ transcribe: false, why: 'unknown' })))
const words = (n?: number) => n ? Math.max(1, Math.round(n / 6)).toLocaleString('en-GB') + ' words' : ''
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

function AfterMeeting({ prep, shielded, off, onChanged, flush, setOutcomes }: { prep: Prep; shielded: boolean; off: boolean; onChanged: () => void; flush: () => Promise<void>; setOutcomes: (o: Outcomes, now?: boolean) => void }) {
  const { ax } = useApp()
  const [caps, setCaps] = useState<{ transcribe: boolean; why?: string | null } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [paste, setPaste] = useState<string | null>(null)
  const [show, setShow] = useState<Record<string, string>>({})
  const [labels, setLabels] = useState<Record<string, string[]>>({})
  const recorder = useChunkRecorder(prep.id, r => { toast(r.status === 'transcribing' ? 'Transcribing on the Mac mini…' : 'Recording kept – ' + (r.error || 'it can be transcribed later')); onChanged() })
  const rec = recorder.state
  const [, tick] = useState(0)
  const [mail, setMail] = useState<{ subject: string; body: string } | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const ts = prep.materials.filter(m => m.kind === 'transcript')
  const o: Outcomes = prep.outcomes || { summary: '', items: [] }
  const emails = prep.attendees.map(a => a.email).filter(Boolean)
  useEffect(() => { loadCaps().then(setCaps) }, [])
  // while a recording is being transcribed, look again every 5 s
  const transcribing = ts.some(t => t.status === 'transcribing')
  useEffect(() => { if (!transcribing) return; const t = setInterval(onChanged, 5000); return () => clearInterval(t) }, [transcribing, onChanged])
  useEffect(() => { if (!rec) return; const t = setInterval(() => tick(x => x + 1), 1000); return () => clearInterval(t) }, [rec])

  async function send(f: File | Blob, name: string) {
    setBusy('up')
    try {
      const r = await uploadTranscript(prep.id, f, name)
      toast(r.status === 'transcribing' ? 'Transcribing on the Mac mini…' : r.status === 'waiting' ? 'Recording kept – ' + (r.error || 'it can be transcribed later') : `Transcript added (${words(r.chars)})`)
      onChanged()
    } catch (e: any) { toast.error(name + ': ' + e.message) } finally { setBusy(null) }
  }
  const start = recorder.start, stop = recorder.stop
  async function toggle(id: string) {
    if (show[id] !== undefined) { setShow(s => { const n = { ...s }; delete n[id]; return n }); return }
    try { const j = await get<{ text: string; labels?: string[] }>(`meeting_text?id=${encodeURIComponent(prep.id)}&a=${encodeURIComponent(id)}`); setShow(s => ({ ...s, [id]: j.text })); setLabels(s => ({ ...s, [id]: j.labels || [] })) }
    catch (e: any) { toast.error(e.message) }
  }
  async function act(action: string, body: Record<string, unknown>, ok: string) {
    try { await post(action, { id: prep.id, title: prep.title, ...body }); toast(ok); onChanged() } catch (e: any) { toast.error(e.message) }
  }
  async function assist(kind: 'outcomes' | 'followup') {
    await flush(); setBusy(kind)
    try {
      const r = await post<{ result: { answer: string; outcomes: Omit<Outcome, 'state'>[]; mail: { subject: string; body: string } | null } }>('meeting_assist', { id: prep.id, kind, title: prep.title })
      if (kind === 'outcomes') {
        const have = new Set(o.items.map(i => i.kind + ':' + i.text.toLowerCase()))
        const fresh = (r.result.outcomes || []).filter(i => !have.has(i.kind + ':' + i.text.toLowerCase())).map(i => ({ ...i, state: 'open' as const }))
        setOutcomes({ summary: o.summary.trim() ? o.summary : r.result.answer || '', items: [...o.items, ...fresh], at: new Date().toISOString() }, true)
        toast(fresh.length ? `${fresh.length} outcome${fresh.length === 1 ? '' : 's'} found – add the ones you want` : 'Nothing new found')
      } else if (r.result.mail) setMail(r.result.mail)
      else toast('No follow-up drafted – add notes or a transcript first')
    } catch (e: any) { toast.error(e.message) } finally { setBusy(null) }
  }
  const setItem = (i: number, patch: Partial<Outcome>) => setOutcomes({ ...o, items: o.items.map((x, j) => j === i ? { ...x, ...patch } : x) }, true)
  async function addTask(i: number) {
    const x = o.items[i]
    const text = x.kind === 'waiting' ? `Waiting on ${x.who || 'them'}: ${x.text}` : x.text
    try {
      await ax.act('task_add', { text: text.slice(0, 500), due: x.due || null, source: 'meeting', ctx: prep.ctx || undefined, notes: `From the meeting “${prep.title}”${prep.start ? ' on ' + fmtWhen(prep.start, true) : ''}.` }, ['tasks'])
      setItem(i, { state: 'added' }); toast('Added to To do')
    } catch (e: any) { toast.error('Not added: ' + e.message) }
  }
  const capNote = caps && !caps.transcribe ? `Recordings are kept but not transcribed yet: ${caps.why}. Transcripts from Teams, Zoom or Meet (.vtt, .txt, .docx) work right away.` : null
  return <Section title="After the meeting" hint="Recording or transcript, outcomes, follow-up">
    <div className="space-y-4" data-after="">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          {rec ? <Button size="pill" variant="destructive" onClick={stop} data-rec-stop=""><Square />Stop · {mmss((Date.now() - rec.t0) / 1000)}</Button>
            : <Button size="pill" variant="outline" disabled={!!busy || !('MediaRecorder' in window)} onClick={start} data-rec-start=""><span className="bg-danger size-2.5 rounded-full" />Record</Button>}
          <input ref={file} type="file" hidden accept="audio/*,.m4a,.mp3,.wav,.webm,.vtt,.srt,.txt,.md,.docx" onChange={e => { const f = e.target.files?.[0]; if (f) send(f, f.name); e.target.value = '' }} />
          <Button size="pill" variant="outline" disabled={!!busy || !!rec} onClick={() => file.current?.click()}>{busy === 'up' ? <Loader2 className="animate-spin" /> : <Upload />}Recording or transcript</Button>
          <Button size="pill" variant="ghost" disabled={!!rec} onClick={() => setPaste(paste === null ? '' : null)}><ClipboardCopy />Paste a transcript</Button>
        </div>
        <p className="text-ink-3 text-[11.5px]">{rec ? `Recording – keep Axella open (the screen stays on)${rec.pending ? ` · ${rec.pending} part${rec.pending === 1 ? '' : 's'} waiting for the Mac mini – kept, sent when it answers` : ' · saved on the Mac mini as you go'}. ` : 'Keep Axella open while recording. '}Let the others know before you record. Recordings are transcribed on the Mac mini and never leave it.</p>
        <TranscribeStatus caps={caps as any} />
        <WaitingRecordings prep={prep} current={rec?.rec} onChanged={onChanged} />
        {paste !== null && <div className="space-y-2">
          <textarea value={paste} onChange={e => setPaste(e.target.value)} rows={6} className={TA} placeholder="Paste the transcript or your meeting minutes" aria-label="Transcript" />
          <div className="flex justify-end gap-2"><Button size="pill" variant="ghost" onClick={() => setPaste(null)}>Cancel</Button>
            <Button size="pill" disabled={!paste.trim()} onClick={async () => { await act('meeting_transcript_paste', { text: paste, name: 'Transcript ' + new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) }, 'Transcript added'); setPaste(null) }}>Save transcript</Button></div>
        </div>}
        {ts.map(t => <div key={t.id} className="rounded-md border px-3 py-2" data-transcript="">
          <div className="flex items-start gap-2.5">
            <FileText className="text-ink-2 mt-0.5 size-4 shrink-0" />
            <div className="min-w-0 flex-1 text-sm">
              <div className="truncate font-medium">{t.name}</div>
              <div className={cn('text-[12px]', t.status === 'failed' ? 'text-dawn' : 'text-ink-3')}>
                {t.status === 'transcribing' ? <span className="inline-flex items-center gap-1"><Loader2 className="size-3 animate-spin" />Transcribing on the Mac mini…</span>
                  : t.status === 'ready' ? words(t.chars) || 'empty' : t.status === 'waiting' ? 'Not transcribed – ' + (t.error || 'no transcriber') : 'Failed – ' + (t.error || 'unknown')}</div>
            </div>
            <span className="flex shrink-0 gap-1">
              {t.audio && <Button size="pill" variant="ghost" asChild><a href={fileUrl(prep, t)} target="_blank" rel="noopener noreferrer" aria-label={'Listen to ' + t.name}><Play /></a></Button>}
              {t.status === 'ready' && <Button size="pill" variant="ghost" onClick={() => toggle(t.id)}>{show[t.id] !== undefined ? 'Hide' : 'Read'}</Button>}
              {t.audio && (t.status === 'waiting' || t.status === 'failed') && <Button size="pill" variant="outline" disabled={caps?.transcribe === false} onClick={() => act('meeting_transcribe', { material: t.id }, 'Transcribing on the Mac mini…')}>Transcribe</Button>}
              <RemoveX onRemove={() => act('meeting_material_remove', { material: t.id }, 'Removed')} label={'Remove ' + t.name} />
            </span>
          </div>
          {show[t.id] !== undefined && <pre className="bg-bg-2/50 mt-2 max-h-72 overflow-y-auto rounded px-3 py-2 font-sans text-[13px] leading-relaxed whitespace-pre-wrap">{show[t.id] || '(empty)'}</pre>}
          {show[t.id] !== undefined && <Speakers prep={prep} materialId={t.id} labels={labels[t.id] || []} names={t.speakers} onChanged={() => { onChanged(); setShow(s => { const n = { ...s }; delete n[t.id]; return n }) }} />}
        </div>)}
      </div>

      <div className="space-y-2 border-t pt-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[14px] font-semibold">Outcomes</span>
          <Button size="pill" variant="outline" className="ml-auto" disabled={!!busy || transcribing || off} onClick={() => assist('outcomes')} data-find-outcomes="">
            {busy === 'outcomes' ? <Loader2 className="animate-spin" /> : <Sparkles />}Find outcomes</Button>
        </div>
        {off ? <p className="text-ink-3 text-[11.5px]">Claude is off for this meeting – write the outcomes yourself, or change it under “Claude and this meeting”.</p>
          : shielded && ts.length > 0 && <p className="text-ink-3 text-[11.5px]">The transcript stays on the Mac mini (your choice for this workplace meeting) – Axella works from your notes and ticked points only.</p>}
        <AutoText value={o.summary} onChange={v => setOutcomes({ ...o, summary: v })} onBlur={flush} rows={2} placeholder="Summary of the meeting" maxLength={20000} />
        {OUTCOME_GROUPS.map(([k, h]) => {
          const list = o.items.map((x, i) => [x, i] as const).filter(([x]) => x.kind === k && x.state !== 'dismissed')
          if (!list.length) return null
          return <div key={k} data-outcomes={k}>
            <div className="ax-label mb-1">{h}</div>
            <div className="space-y-1.5">{list.map(([x, i]) => <div key={x.id || i} className="bg-card flex flex-wrap items-center gap-2 rounded-md border px-3 py-2" data-outcome="">
              <span className={cn('min-w-0 flex-1 text-[13.5px]', (x.state === 'added' || x.state === 'kept') && 'text-ink-2')}>{x.who && k !== 'task' ? <b className="font-semibold">{x.who}: </b> : null}{x.text}</span>
              {(k === 'task' || k === 'waiting') && x.state === 'open' && <Input type="date" value={x.due || ''} onChange={e => setItem(i, { due: e.target.value || null })} className="h-8 w-36 text-[13px]" aria-label="Due" />}
              {x.state === 'open' ? <>
                {k === 'decision' && <Button size="pill" variant="outline" onClick={() => setItem(i, { state: 'kept' })}><Check />Keep</Button>}
                {(k === 'decision' || k === 'task') && <AnswersPoint prep={prep} outcomeId={x.id} onChanged={onChanged} />}
                {(k === 'task' || k === 'waiting') && <Button size="pill" variant="outline" onClick={() => addTask(i)}><Plus />{k === 'task' ? 'To do' : 'Add as task'}</Button>}
                {k === 'fact' && <Button size="pill" variant="outline" onClick={() => {
                  openKnowledge({ title: x.text.slice(0, 80), body: x.text, ...(prep.project ? { scope: [prep.project] } : {}), source: { kind: 'manual', label: 'Meeting: ' + prep.title } } as any)
                  setItem(i, { state: 'added' })
                }}><Plus />Knowledge…</Button>}
                <button className="text-ink-3 hover:text-ink rounded p-1" aria-label="Dismiss" onClick={() => setItem(i, { state: 'dismissed' })}><X className="size-4" /></button>
              </> : <span className="text-ink-3 flex items-center gap-1 text-[12px]"><Check className="size-3.5" />{x.state === 'kept' ? 'Kept' : 'Added'}</span>}
            </div>)}</div>
          </div>
        })}
        {!o.items.length && <p className="text-ink-3 text-[12.5px]">After the meeting: tick the points you covered, add notes or a transcript, then Find outcomes – decisions, your tasks, what you wait for, and facts worth keeping. Nothing is added without your tap.</p>}
      </div>

      <div className="space-y-2 border-t pt-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[14px] font-semibold">Follow-up mail</span>
          <Button size="pill" variant="outline" className="ml-auto" disabled={!!busy || off} onClick={() => assist('followup')} data-draft-followup="">
            {busy === 'followup' ? <Loader2 className="animate-spin" /> : <Sparkles />}Draft follow-up</Button>
        </div>
        {mail && <div className="space-y-2" data-followup="">
          <Input value={mail.subject} onChange={e => setMail({ ...mail, subject: e.target.value })} aria-label="Subject" />
          <textarea value={mail.body} onChange={e => setMail({ ...mail, body: e.target.value })} rows={Math.min(18, mail.body.split('\n').length + 2)} className={TA} aria-label="Follow-up text" />
          <div className="flex flex-wrap justify-end gap-2">
            <Button size="pill" variant="ghost" onClick={() => navigator.clipboard.writeText(mail.subject + '\n\n' + mail.body).then(() => toast('Copied'))}><ClipboardCopy />Copy</Button>
            <Button size="pill" disabled={!emails.length} onClick={() => mailTo(emails, mail.subject, mail.body)}><MailPlus />{emails.length > 1 ? 'Open in Mail' : 'Open in the composer'}</Button>
          </div>
          <p className="text-ink-3 text-[11.5px]">{emails.length ? `To ${prep.attendees.filter(a => a.email).map(a => a.name).join(', ')}. ` : 'No addresses on this meeting – copy the text instead. '}Nothing is sent until you press Send there.</p>
        </div>}
      </div>
    </div>
  </Section>
}
function RemoveX({ onRemove, label }: { onRemove: () => void; label: string }) {
  const [armed, setArmed] = useState(false)
  return <button onClick={() => { if (armed) onRemove(); else { setArmed(true); setTimeout(() => setArmed(false), 3000) } }} aria-label={label}
    className={cn('shrink-0 rounded px-1.5 py-0.5 text-[12px]', armed ? 'text-danger font-medium' : 'text-ink-3 hover:text-danger')}>{armed ? 'Remove?' : <X className="size-4" />}</button>
}

/** Meetings page: for each protected workplace, what may go to Claude for a new meeting with them. */
const AI_LABEL = { own: 'My own text only', all: 'Everything', none: 'Nothing' } as const
function WorkplaceDefaults() {
  const [wps, setWps] = useState<{ id: string; name: string; ai: 'none' | 'own' | 'all' | null }[] | null>(null)
  useEffect(() => { get<{ workplaces?: { id: string; name: string; ai: 'none' | 'own' | 'all' | null }[] }>('meeting_caps').then(j => setWps(j.workplaces || [])).catch(() => setWps([])) }, [])
  if (!wps?.length) return null
  async function save(id: string, v: string) {
    const ai = (v || null) as 'none' | 'own' | 'all' | null
    setWps(l => l!.map(w => w.id === id ? { ...w, ai } : w))
    try { await post('meeting_ai_default', { workplace: id, ai, title: wps!.find(w => w.id === id)?.name }); toast('Saved – new meetings start with this') } catch (e: any) { toast.error(e.message) }
  }
  return <Card className="overflow-hidden" data-workplace-defaults="">
    <div className="border-b px-4 py-2.5"><span className="ax-label">Workplace meetings and Claude</span></div>
    <div className="divide-y">{wps.map(w => <div key={w.id} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-2.5">
      <span className="min-w-0 flex-1 text-sm"><span className="font-medium">{w.name}</span>
        <span className="text-ink-3 block text-[12.5px]">{w.ai === 'none' ? 'Nothing from these meetings goes to Claude – the assistant is off.' : w.ai === 'all' ? 'Transcripts, documents and their mail may go to Claude.' : 'Only what you write yourself goes to Claude.'}</span></span>
      <NativeSelect aria-label={'Default for ' + w.name} value={w.ai || ''} onChange={e => save(w.id, e.target.value)} className="h-8 w-auto text-[13px]">
        <option value="">{AI_LABEL.own} (standard)</option><option value="own">{AI_LABEL.own}</option><option value="all">{AI_LABEL.all}</option><option value="none">{AI_LABEL.none}</option>
      </NativeSelect>
    </div>)}</div>
    <p className="text-ink-3 border-t px-4 py-2 text-[11.5px]">Where a new meeting with them starts. You can still change it on a single meeting. With two workplaces in one meeting, the stricter one counts.</p>
  </Card>
}
