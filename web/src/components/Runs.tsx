import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Activity, AlertTriangle, CalendarClock, Check, ChevronDown, Clock, Copy, Loader2, Play, Plus, Save, Square, Trash2, X } from '@/components/ax-icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input, NativeSelect } from '@/components/ui/input'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { SectionCard } from '@/components/Section'
import { get, post } from '@/lib/api'
import { cn } from '@/lib/utils'

/* ---------- types (GET runs) ---------- */
export interface DigestSlot { id: string; label: string; task: string; time: string; days: number[]; enabled: boolean
  /** work/private per schedule: missing = both; mention_other = the one count line about the other world */
  worlds?: ('work' | 'private')[]; mention_other?: boolean
  /** week-ahead: include the private week wrap (default on) */
  wrap?: boolean }
export interface SchedulerConfig {
  enabled: boolean; digests: DigestSlot[]
  p0: { enabled: boolean; from: string; to: string; every: number; days: number[] }
  models: { digest: string; p0: string; compose?: string }
}
export interface Run {
  id: string; task: string; label: string; slot?: string | null; trigger: string; attempt: number
  status: 'running' | 'ok' | 'failed' | 'cancelled'; started: string; ended?: string | null; reason?: string | null
  summary?: string | null; model?: string | null; usage?: { input: number; output: number; turns?: number; cost_usd?: number } | null
}
interface TodaySlot { slot: string; time: string; task: string; label: string; status: string; note?: string | null; run?: string | null }
interface Overview {
  config: SchedulerConfig; tasks: Record<string, string>; current: Run | null
  queue: { task: string; label: string; trigger: string; not_before?: string | null }[]
  today: TodaySlot[]; runs: Run[]; kept_days?: number; total_runs?: number; history_from?: string | null; capped?: boolean
  doctor: { at?: string; claude?: string | null; claude_version?: string; api_key_set?: boolean; mcp_file?: boolean } | null
  peer_check_off?: boolean
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const hm = (iso?: string | null) => iso ? new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : '–'
const dayhm = (iso: string) => new Date(iso).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const dur = (a: string, b?: string | null) => { const s = Math.max(0, Math.round(((b ? new Date(b) : new Date()).getTime() - new Date(a).getTime()) / 1000)); return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s` }
const tok = (n?: number) => n == null ? '–' : n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? Math.round(n / 1e3) + 'k' : String(n)

function useRuns(every = 5000) {
  const [o, setO] = useState<Overview | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const load = useCallback(() => get<Overview>('runs').then(j => { setO(j); setErr(null) }).catch(e => setErr(e.message)), [])
  useEffect(() => { load(); const t = setInterval(() => { if (!document.hidden) load() }, every); return () => clearInterval(t) }, [load, every])
  return { o, err, load }
}

export function StatusBadge({ s }: { s: string }) {
  if (s === 'running') return <Badge variant="default"><Loader2 className="animate-spin" />running</Badge>
  if (s === 'ok') return <Badge variant="success"><Check />done</Badge>
  if (s === 'failed' || s === 'missed') return <Badge variant="destructive"><AlertTriangle />{s}</Badge>
  if (s === 'queued') return <Badge variant="secondary"><Clock />queued</Badge>
  if (s === 'due') return <Badge variant="warning">due</Badge>
  return <Badge variant="outline">{s}</Badge>
}

/* ---------- live log ---------- */
function LogView({ id, live }: { id: string; live: boolean }) {
  const [text, setText] = useState('')
  const off = useRef(0), box = useRef<HTMLPreElement>(null)
  useEffect(() => { setText(''); off.current = 0 }, [id])
  useEffect(() => {
    let stop = false
    const pull = async () => {
      try {
        const j = await get<{ text: string; offset: number }>(`run_log?id=${encodeURIComponent(id)}&offset=${off.current}`)
        if (stop || !j.text) return
        off.current = j.offset
        setText(t => t + j.text)
        requestAnimationFrame(() => { const b = box.current; if (b && b.scrollHeight - b.scrollTop - b.clientHeight < 80) b.scrollTop = b.scrollHeight })
      } catch { /* next round */ }
    }
    pull()
    const t = live ? setInterval(pull, 2000) : undefined
    return () => { stop = true; if (t) clearInterval(t) }
  }, [id, live])
  return <pre ref={box} className="bg-muted/60 max-h-[60vh] overflow-auto rounded-lg p-3 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap break-words">
    {text || <span className="text-muted-foreground">No log yet…</span>}</pre>
}

/* ---------- Runs view ---------- */
export function RunsView() {
  const { o, err, load } = useRuns(4000)
  const [open, setOpen] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  async function act(a: string, body: object, msg: string) {
    setBusy(a + JSON.stringify(body))
    try { const j = await post<{ result: string }>(a, body); toast(j.result === 'queued' ? msg : j.result); await load() }
    catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(null) }
  }
  if (!o) return <div className="text-muted-foreground py-10 text-center">{err ? 'Action service not reachable – ' + err : 'Loading…'}</div>
  const cur = o.current, d = o.doctor
  const ready = d?.claude && d?.mcp_file && !d?.api_key_set
  const failedToday = o.today.filter(s => s.status === 'failed' || s.status === 'missed').length
  const nextSlot = o.today.find(s => s.status === 'planned' || s.status === 'due')?.slot

  return (
    <div className="space-y-4">
      {o.peer_check_off && <div className="border-danger/50 bg-danger/10 text-danger rounded-lg border px-4 py-3 text-sm font-medium">
        The "only Tailscale may connect" check is OFF (state/peer-check.off) – any program on the Mac can reach Axella.
        Delete the file and restart the service; it is ignored after 24 hours anyway.</div>}
      <div><h1 className="text-xl font-semibold tracking-tight">Runs</h1>
        <p className="text-muted-foreground text-sm">What the Mac mini runs, when, and how it went. Times and days are set in Settings → Schedule.</p></div>

      {!o.config.enabled && <Card className="p-3 text-sm">
        <b>Local scheduler is off.</b> The cloud scheduled tasks still run the schedule. Turn it on in Settings → Schedule once the
        cloud tasks are switched off – never both at once. You can still start a run by hand below to test it.</Card>}
      {d && !ready && <Card className="border-destructive/50 bg-destructive/10 space-y-1 p-3 text-sm">
        <b>Setup not complete on the Mac mini</b>
        {!d.claude && <div>· Claude Code (the <code>claude</code> command) was not found.</div>}
        {!d.mcp_file && <div>· The Macuse connection for local runs (state/mcp.json) is missing.</div>}
        {d.api_key_set && <div>· ANTHROPIC_API_KEY is set for the service – runs must use your subscription, remove it.</div>}
      </Card>}

      {/* now running */}
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 px-4 py-3">
          <div className={cn('flex size-9 items-center justify-center rounded-md', cur ? 'bg-fjord-soft text-fjord' : 'bg-bg-2 text-ink')}>
            {cur ? <Loader2 className="size-[18px] animate-spin" /> : <Activity className="size-[18px]" />}</div>
          <div className="min-w-0 flex-1">
            <div className="font-semibold">{cur ? cur.label : 'Nothing running'}</div>
            <div className="text-muted-foreground text-xs">{cur ? `started ${hm(cur.started)} · ${dur(cur.started)} · ${cur.trigger}${cur.model ? ' · ' + cur.model : ''}`
              : o.queue.length ? `${o.queue.length} waiting` : `Next: ${o.today.find(s => s.status === 'planned')?.time || 'tomorrow'}`}</div>
          </div>
          {cur && <Button size="pill" variant="outline" disabled={!!busy} onClick={() => act('run_cancel', { task: cur.task }, 'Stopping')}><Square />Stop</Button>}
        </div>
        {cur && <div className="border-t p-3"><LogView id={cur.id} live /></div>}
        {o.queue.length > 0 && <div className="text-muted-foreground border-t px-4 py-2 text-xs">Waiting: {o.queue.map(q => q.label + (q.not_before ? ` (retry ${hm(q.not_before)})` : '')).join(' · ')}</div>}
      </Card>

      {/* today */}
      <SectionCard id="today-runs" color="var(--ax-cal)" icon={CalendarClock} title="Today" sub={failedToday ? `${failedToday} failed or missed` : 'Planned and finished runs'}>
        <div className="flex flex-wrap gap-1.5 p-4">
          {o.today.length ? o.today.map(s => <button key={s.slot} title={`${s.label} ${s.time} – ${s.status}${s.note ? ': ' + s.note : ''}`}
            onClick={() => s.run && setOpen(s.run)}
            className={cn('rounded-md border px-2 py-1 font-mono text-xs tabular-nums', s.slot === nextSlot && 'border-fjord text-fjord', s.task !== 'p0-check' && 'font-semibold',
              s.status === 'ok' && 'border-line-strong', (s.status === 'failed' || s.status === 'missed') && 'border-destructive/60 bg-destructive/15',
              s.status === 'running' && 'border-fjord text-fjord', s.status === 'skipped' && 'text-muted-foreground line-through', s.status === 'planned' && 'text-muted-foreground')}>
            {s.status === 'ok' && <span className="ax-diamond text-success mr-1.5 -mt-px align-middle" style={{ width: 6, height: 6 }} />}
            {s.time}{s.task !== 'p0-check' ? ' ' + s.label.replace(' digest', '') : ''}</button>)
            : <span className="text-muted-foreground text-sm">Nothing scheduled today.</span>}
        </div>
        {o.today.some(s => s.status === 'skipped') && <p className="text-muted-foreground -mt-2 px-4 pb-3 text-xs">
          <span className="line-through">Struck through</span> = skipped on purpose: no new mail, messages or WhatsApp since the last check, so Claude wasn’t started. The check on the hour always runs. Hover or tap a time for details.</p>}
      </SectionCard>

      {/* start by hand */}
      <Card className="flex flex-wrap items-center gap-2 p-3">
        <span className="text-muted-foreground mr-1 text-sm">Run now:</span>
        {Object.entries(o.tasks).map(([t, label]) => <Button key={t} size="pill" variant="outline" disabled={!!busy || !d?.claude}
          onClick={() => act('run_now', { task: t }, label + ' queued')}><Play />{label}</Button>)}
      </Card>

      {/* history */}
      <Card className="divide-y">
        <div className="flex items-baseline gap-2 px-4 py-3"><span className="font-semibold">Recent runs</span>
          <span className="text-muted-foreground text-xs">last {o.runs.length}{o.total_runs ? ` of ${o.total_runs}${o.capped ? '+' : ''}` : ''} · kept {o.kept_days || 30} days{o.history_from && Date.now() - new Date(o.history_from).getTime() < (o.kept_days || 30) * 86400e3 ? ` (history starts ${new Date(o.history_from).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })})` : ''} · skipped checks only under Today</span></div>
        {!o.runs.length && <div className="text-muted-foreground px-4 py-3 text-sm">No runs yet.</div>}
        {o.runs.map(r => <div key={r.id}>
          <button className="hover:bg-accent/40 flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-left" onClick={() => setOpen(open === r.id ? null : r.id)}>
            <StatusBadge s={r.status} />
            <span className="font-medium">{r.label}</span>
            <span className="text-muted-foreground text-xs">{dayhm(r.started)} · {r.ended ? dur(r.started, r.ended) : dur(r.started)} · {r.trigger}{r.attempt > 1 ? ' (2nd try)' : ''}</span>
            <span className="text-muted-foreground ml-auto text-xs tabular-nums">{r.usage ? `${tok(r.usage.input)} in · ${tok(r.usage.output)} out` : ''}</span>
            <ChevronDown className={cn('text-muted-foreground size-4 transition-transform', open === r.id && 'rotate-180')} />
            {/* a finished run shows its own summary; a note from the checks (e.g. a count mismatch) goes on a line of its own */}
            {r.status === 'ok' && r.summary && (!r.reason || /^count check/.test(r.reason)) && <div className="text-muted-foreground w-full truncate text-xs">{oneLine(r.summary, r.task)}</div>}
            {r.reason && <div className={cn('w-full truncate text-xs', r.status === 'failed' ? 'text-destructive' : r.status === 'ok' ? 'text-ink-2' : 'text-muted-foreground')}>{r.status === 'ok' && /^count check/.test(r.reason) ? '⚠ ' : ''}{r.reason}</div>}
            {r.status !== 'ok' && !r.reason && r.summary && <div className="text-muted-foreground w-full truncate text-xs">{oneLine(r.summary, r.task)}</div>}
          </button>
          {open === r.id && <div className="px-4 pb-3"><LogView id={r.id} live={r.status === 'running'} /></div>}
        </div>)}
      </Card>
      {d && <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">Claude Code: {d.claude_version || d.claude || 'not found'} · checked {d.at ? dayhm(d.at) : '–'}
        <Button size="sm" variant="ghost" disabled={!!busy} onClick={async () => {
          setBusy('doctor'); const t = toast.loading('Checking setup – starts Macuse once, up to 90 s…')
          try { await post('doctor_run', {}); toast.success('Setup checked', { id: t }); await load() }
          catch (e: any) { toast.error('Failed: ' + e.message, { id: t }) } finally { setBusy(null) }
        }}>{busy === 'doctor' ? <Loader2 className="animate-spin" /> : <Activity />}Re-check setup</Button></div>}
    </div>
  )
}

/* ---------- Settings → Schedule ---------- */
const scopeKey = (w?: string[]) => !w || w.length !== 1 ? 'both' : w[0]

export function SchedulerCard() {
  const { o, load } = useRuns(30000)
  const [c, setC] = useState<SchedulerConfig | null>(null)
  const [dirty, setDirty] = useState(false)
  useEffect(() => { if (o && !dirty) setC(o.config) }, [o])
  if (!c || !o) return null
  const upd = (p: Partial<SchedulerConfig>) => { setC({ ...c, ...p }); setDirty(true) }
  const updSlot = (i: number, p: Partial<DigestSlot>) => upd({ digests: c.digests.map((s, j) => j === i ? { ...s, ...p } : s) })
  const digestTasks = Object.entries(o.tasks).filter(([t]) => t.startsWith('digest-') || t === 'week-ahead' || t === 'week-wrap')
  async function save(next = c!, msg = 'Schedule saved') {
    try { await post('scheduler_set', next); setDirty(false); toast(msg); await load() }
    catch (e: any) { toast.error('Failed: ' + e.message) }
  }
  const Days = ({ v, on }: { v: number[]; on: (d: number[]) => void }) => <div className="flex flex-wrap gap-1">
    {DAYS.map((d, i) => { const sel = v.includes(i); return <button key={d} type="button" onClick={() => on(sel ? v.filter(x => x !== i) : [...v, i].sort())}
      className={cn('h-8 w-10 rounded-md border text-xs font-medium', sel ? 'bg-primary text-primary-foreground border-primary' : 'text-muted-foreground hover:bg-accent')}>{d}</button> })}
  </div>

  return (
    <SectionCard id="sched" color="var(--ax-p1)" icon={CalendarClock} title="Schedule" sub={c.enabled ? 'Run by the Mac mini' : 'Local scheduler off – cloud tasks run the schedule'}>
      <div className="space-y-5 p-4 text-sm">
        <label className="flex items-start gap-3">
          <Checkbox className="mt-0.5" checked={c.enabled} onCheckedChange={v => { const n = { ...c, enabled: !!v }; setC(n); save(n, v ? 'Local scheduler on' : 'Local scheduler off') }} />
          <span className="font-medium">Mac mini runs the schedule<span className="text-muted-foreground block text-xs font-normal">Off = nothing runs on its own – only “Run now” in Runs. Vacation mode and days off still apply.</span></span>
        </label>

        <div className="space-y-2">
          <div className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">Digests</div>
          {c.digests.map((s, i) => <div key={s.id + i} className="space-y-2 rounded-lg border p-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <Checkbox checked={s.enabled} onCheckedChange={v => updSlot(i, { enabled: !!v })} aria-label="Enabled" />
              <Input value={s.label} onChange={e => updSlot(i, { label: e.target.value })} className="h-9 w-44 flex-1" />
              <Input type="time" value={s.time} step={300} onChange={e => updSlot(i, { time: e.target.value })} className="h-9 w-28" />
              <NativeSelect value={s.task} onChange={e => updSlot(i, { task: e.target.value })} className="h-9 w-52">
                {digestTasks.map(([t, l]) => <option key={t} value={t}>{l}</option>)}
              </NativeSelect>
              <button className="text-muted-foreground hover:text-foreground" aria-label="Duplicate slot" title="Duplicate – e.g. the same time with another scope on other days"
                onClick={() => upd({ digests: [...c.digests.slice(0, i + 1), { ...s, id: '', label: s.label + ' (copy)' }, ...c.digests.slice(i + 1)] })}><Copy className="size-4" /></button>
              <button className="text-muted-foreground hover:text-destructive" aria-label="Remove" onClick={() => upd({ digests: c.digests.filter((_, j) => j !== i) })}><Trash2 className="size-4" /></button>
            </div>
            <Days v={s.days} on={d => updSlot(i, { days: d })} />
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5" data-slot-scope={s.id}>
              <ToggleGroup type="single" aria-label="Covers" value={scopeKey(s.worlds)} onValueChange={(v: string) => v && updSlot(i, { worlds: v === 'both' ? ['private', 'work'] : [v as 'work' | 'private'] })}>
                <ToggleGroupItem value="work">Work</ToggleGroupItem><ToggleGroupItem value="private">Private</ToggleGroupItem><ToggleGroupItem value="both">Both</ToggleGroupItem>
              </ToggleGroup>
              {scopeKey(s.worlds) !== 'both' && <label className="text-muted-foreground flex items-center gap-2 text-xs">
                <Checkbox checked={s.mention_other !== false} onCheckedChange={v => updSlot(i, { mention_other: !!v })} />
                Mention {scopeKey(s.worlds) === 'work' ? 'private' : 'work'} messages waiting (a count only)</label>}
              {s.task === 'week-ahead' && <label className="text-muted-foreground flex items-center gap-2 text-xs">
                <Checkbox checked={s.wrap !== false} onCheckedChange={v => updSlot(i, { wrap: !!v })} />Include the week wrap</label>}
            </div>
          </div>)}
          <Button size="sm" variant="outline" onClick={() => upd({ digests: [...c.digests, { id: '', label: 'Extra digest', task: 'digest-afternoon', time: '18:00', days: [0, 1, 2, 3, 4], enabled: true, worlds: ['private', 'work'], mention_other: true }] })}><Plus />Add digest time</Button>
        </div>

        <div className="space-y-2">
          <div className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">Urgent checks</div>
          <label className="flex items-center gap-3"><Checkbox checked={c.p0.enabled} onCheckedChange={v => upd({ p0: { ...c.p0, enabled: !!v } })} />Check for urgent items</label>
          <div className={cn('flex flex-wrap items-center gap-2', !c.p0.enabled && 'opacity-60')}>
            <span className="text-muted-foreground">every</span>
            <NativeSelect value={String(c.p0.every)} onChange={e => upd({ p0: { ...c.p0, every: +e.target.value } })} className="h-9 w-24">
              {[15, 30, 60].map(m => <option key={m} value={m}>{m} min</option>)}</NativeSelect>
            <span className="text-muted-foreground">from</span>
            <Input type="time" value={c.p0.from} onChange={e => upd({ p0: { ...c.p0, from: e.target.value } })} className="h-9 w-28" />
            <span className="text-muted-foreground">to</span>
            <Input type="time" value={c.p0.to} onChange={e => upd({ p0: { ...c.p0, to: e.target.value } })} className="h-9 w-28" />
          </div>
          <Days v={c.p0.days} on={d => upd({ p0: { ...c.p0, days: d } })} />
          <p className="text-muted-foreground text-xs">A check due at the same time as a digest, or while a digest runs, is skipped – the digest covers it. “Run sweep now” starts straight away on any day.</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-muted-foreground">Model – digests</span>
          <NativeSelect value={c.models.digest} onChange={e => upd({ models: { ...c.models, digest: e.target.value } })} className="h-9 w-28">
            {['opus', 'sonnet'].map(m => <option key={m}>{m}</option>)}</NativeSelect>
          <span className="text-muted-foreground">urgent checks</span>
          <NativeSelect value={c.models.p0} onChange={e => upd({ models: { ...c.models, p0: e.target.value } })} className="h-9 w-28">
            {['sonnet', 'haiku', 'opus'].map(m => <option key={m}>{m}</option>)}</NativeSelect>
          <span className="text-muted-foreground">new mail</span>
          <NativeSelect value={c.models.compose || 'sonnet'} onChange={e => upd({ models: { ...c.models, compose: e.target.value } })} className="h-9 w-28">
            {['sonnet', 'opus'].map(m => <option key={m}>{m}</option>)}</NativeSelect>
        </div>

        {dirty && <div className="flex gap-2">
          <Button size="sm" onClick={() => save()}><Save />Save schedule</Button>
          <Button size="sm" variant="ghost" onClick={() => { setC(o.config); setDirty(false) }}><X />Undo changes</Button>
        </div>}
      </div>
    </SectionCard>
  )
}

/* One readable line per run: the digest's own "Axella HH:MM: …" sentence, "No P0." for checks, otherwise the first
   sentence that isn't the agent talking about files it wrote. Markdown is stripped; the full output is in the log. */
export function oneLine(text: string, task?: string) {
  const plain = text
    .replace(/^\s*\|.*\|\s*$/gm, ' ')                       // Markdown table rows
    .replace(/[*_`#>]+/g, '').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/\s+/g, ' ').trim()
  const sentences = plain.split(/(?<=[.!?])\s+(?=[A-ZÆØÅ"“])/)
  const pick = (re: RegExp) => sentences.find(x => re.test(x))
  const narration = /^(I('ve| have| wrote| updated| didn't| did not| read| checked| saved| couldn't)|Done\b|All done|Here('s| is))/i
  const fileTalk = /(state\/|digests\/|\.json\b|\.md\b|\.txt\b|sidecar|the file)/i
  const best = pick(/\bAxella \d{1,2}[:.]\d{2}\b/)
    || (task === 'p0-check' && pick(/\bno p0\b/i) ? 'No P0.' : null)
    || pick(/\bno p0\b/i) && 'No P0.'
    || sentences.find(x => !narration.test(x) && !fileTalk.test(x))
    || sentences[0] || ''
  return best.length > 160 ? best.slice(0, 157).replace(/\s+\S*$/, '') + '…' : best
}
