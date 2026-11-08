/* A project page's working state, targets and people (setup/planner.py, project_plan_view). Owner only; every change
   is a tap, nothing is sent from here – Mail opens the composer, Message the app you last used, Call the phone link,
   Meeting a prep with the project linked. A private contact shows no content, only times. */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { CalendarCheck, Check, ChevronDown, ExternalLink, Loader2, Mail, MessageCircle, Pencil, Phone, Plus, Sparkles, Star, Trash2, UserCircle, X, axi } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Card } from '@/components/ui/card'
import { Input, NativeSelect } from '@/components/ui/input'
import { openCompose } from '@/components/Compose'
import { links } from '@/components/Contacts'
import { openNewPrep } from '@/components/Meetings'
import { TagSuggestion } from '@/components/Plan'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { useNotesOwner } from '@/lib/notes'
import { STATES, STATE_COLOR, TARGET_LABEL, dayLabel, planChanged, targetWhen, usePlan, type Entry, type PState, type ProjPerson, type ProjectPlan, type Target } from '@/lib/plan'
import type { Project } from '@/lib/types'
import { cn } from '@/lib/utils'

const TargetIcon = axi('rhythm')
const CH: Record<string, string> = { mail: 'Mail', imessage: 'iMessage', sms: 'SMS', whatsapp: 'WhatsApp', signal: 'Signal', call: 'Call' }
const ago = (s?: string) => {
  if (!s) return ''
  const d = new Date(s), days = Math.floor((Date.now() - d.getTime()) / 864e5)
  return days <= 0 ? 'today' : days === 1 ? 'yesterday' : days < 14 ? days + ' days ago' : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

/** the project page's own data, reloaded after every change */
export function useProjectPlan(p: Project) {
  const { ax } = useApp()
  const owner = useNotesOwner(ax.apiOk)
  const [v, setV] = useState<ProjectPlan | null>(null)
  const on = !!owner && ax.apiOk && p.status === 'active'
  const load = () => get<ProjectPlan>('project_plan?id=' + encodeURIComponent(p.id)).then(setV).catch(() => setV(null))
  useEffect(() => { if (on) load() }, [on, p.id])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const h = () => { if (on) load() }; window.addEventListener('ax-plan', h); return () => window.removeEventListener('ax-plan', h) })
  const [busy, setBusy] = useState<string | null>(null)
  const act = async (key: string, action: string, body: object, msg?: string) => {
    setBusy(key)
    try { const r = await ax.act<any>(action, { id: p.id, ...body }, []); planChanged(); if (msg) toast(msg); return r ?? true }
    catch (e: any) { toast.error(e.message); return null } finally { setBusy(null) }
  }
  return { v, busy, act, on }
}
type Ctl = ReturnType<typeof useProjectPlan>

/* ---------- the state: one coloured pill next to Archive, a short menu with each state's meaning ---------- */
export function StatePill({ p, c, className }: { p: Project; c: Ctl; className?: string }) {
  const [ask, setAsk] = useState<PState | null>(null)
  const [what, setWhat] = useState('')
  const [until, setUntil] = useState('')
  const v = c.v
  if (!v) return null
  const st = v.state
  const set = (state: PState, extra: object = {}) => c.act('st', 'project_state', { state, ...extra }, `${p.name}: ${STATES.find(x => x.id === state)!.label}`).then(() => setAsk(null))
  const pick = (s: PState) => s === 'waiting' || s === 'paused' ? (setAsk(s), setWhat(''), setUntil('')) : set(s)
  const persons = v.people.filter(x => x.source !== 'suggested')
  const cur = STATES.find(x => x.id === st)!
  return <>
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button" disabled={!!c.busy} data-project-state={st} title={cur.hint + ' – Axella never changes it by itself'}
          className={cn('border-line-strong bg-card text-ink inline-flex h-8 items-center gap-2 rounded-md border px-3 text-[13px] font-semibold', className)}>
          <StateDot s={st} />{cur.label}<ChevronDown className="text-ink-3 size-4" /></button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        {STATES.map(s => <DropdownMenuItem key={s.id} onSelect={() => s.id !== st || s.id === 'waiting' || s.id === 'paused' ? pick(s.id) : undefined} data-state-btn={s.id}
          className="items-start">
          <span className="mt-1.5"><StateDot s={s.id} /></span>
          <span className="min-w-0 flex-1"><span className="flex items-center gap-1.5 font-semibold">{s.label}{s.id === st && <Check className="size-3.5" />}</span>
            <span className="text-ink-3 block text-[12.5px] leading-snug">{s.hint}</span></span>
        </DropdownMenuItem>)}
        <p className="text-ink-3 px-2.5 pt-1 pb-1.5 text-[11.5px]">Axella never changes a state by itself – it only suggests.</p>
      </DropdownMenuContent>
    </DropdownMenu>
    <Dialog open={!!ask} onOpenChange={o => !o && setAsk(null)}>
      <DialogContent className="sm:w-[min(420px,92vw)]">
        <form className="space-y-3 p-5" onSubmit={e => { e.preventDefault()
          if (ask === 'paused') { set('paused', until ? { until } : {}); return }
          const person = persons.find(x => x.key === what)
          set('waiting', what ? { waiting_for: person ? { kind: 'person', ref: person.key, label: person.name } : { kind: 'item', ref: what, label: what } } : {}) }}>
          <DialogTitle className="flex items-center gap-2 text-lg font-semibold"><StateDot s={ask || 'waiting'} />{ask === 'paused' ? `Pause ${p.name}` : `${p.name} is waiting`}</DialogTitle>
          {ask === 'waiting' ? <label className="block space-y-1 text-sm"><span className="text-ink-2">Waiting for (optional) – back to Active is suggested when it moves</span>
            <NativeSelect aria-label="Waiting for" value={what} onChange={e => setWhat(e.target.value)}>
              <option value="">Something</option>{persons.map(x => <option key={x.key} value={x.key}>{x.name}</option>)}</NativeSelect></label>
            : <label className="block space-y-1 text-sm"><span className="text-ink-2">Until (optional) – Axella asks you to pick it up again that day</span>
              <Input type="date" value={until} onChange={e => setUntil(e.target.value)} aria-label="Paused until (optional)" /></label>}
          <div className="flex justify-end gap-2"><Button variant="ghost" type="button" onClick={() => setAsk(null)}>Cancel</Button>
            <Button type="submit" disabled={!!c.busy}>{ask === 'paused' ? 'Pause' : 'Set Waiting'}</Button></div>
        </form>
      </DialogContent>
    </Dialog>
  </>
}

export const StateDot = ({ s }: { s: PState }) => s === 'done'
  ? <Check className="size-3.5 shrink-0" style={{ color: STATE_COLOR.done }} />
  : <span className="ax-diamond shrink-0" style={{ color: STATE_COLOR[s], width: 8, height: 8 }} />

/** under the project name: "· waiting for Kim", "· paused until Mon 1 Dec" – only when set */
export function stateDetail(v: ProjectPlan | null) {
  if (!v) return ''
  if (v.state === 'waiting' && v.waiting_for) return 'waiting for ' + v.waiting_for.label
  if (v.state === 'paused' && v.paused_until) {
    const t = v.targets.find(x => x.status !== 'done' && x.due)
    return 'paused until ' + dayLabel(v.paused_until) + (t ? ` · target ${dayLabel(t.due!)} still counts` : '')
  }
  return ''
}

/* ---------- targets: Date · Period · Idea ---------- */
export function TargetsSection({ p, c }: { p: Project; c: Ctl }) {
  const [adding, setAdding] = useState<Target['kind'] | null>(null)
  const v = c.v
  if (!v) return null
  const add = <DropdownMenu>
    <DropdownMenuTrigger asChild><Button size="pill" variant="outline" data-add-target-btn=""><Plus />Add target<ChevronDown /></Button></DropdownMenuTrigger>
    <DropdownMenuContent align="end">
      {(['date', 'period', 'idea'] as const).map(k => <DropdownMenuItem key={k} onSelect={() => setAdding(k)} data-add-target-kind={k}><TargetIcon />{TARGET_LABEL[k]}</DropdownMenuItem>)}
    </DropdownMenuContent>
  </DropdownMenu>
  return <section className="space-y-3" data-targets="">
    {v.targets.map(t => <TargetCard key={t.id} t={t} c={c} ideas={v.step_ideas} briefings={v.briefings} />)}
    {adding ? <NewTarget kind={adding} c={c} briefings={v.briefings} onDone={() => setAdding(null)} />
      : v.targets.length ? <div className="flex justify-end" data-add-target="">{add}</div>
      : <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed px-4 py-2.5" data-add-target="">
        <TargetIcon className="text-ink-3 size-4 shrink-0" /><span className="text-ink-2 min-w-0 flex-1 text-sm">What does success look like for {p.name}?</span>{add}
      </div>}
  </section>
}

function NewTarget({ kind, c, briefings, onDone }: { kind: Target['kind']; c: Ctl; briefings: { id: string; name: string }[]; onDone: () => void }) {
  const [f, setF] = useState({ title: '', done_means: '', date: '', from: '', to: '', brief: '' })
  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (await c.act('tadd', 'project_target_add', { kind, ...f, brief: f.brief || null }, 'Target added')) onDone()
  }
  return <Card className="space-y-2 p-4" data-new-target={kind}>
    <form className="space-y-2" onSubmit={save}>
      <div className="ax-label">New target · {TARGET_LABEL[kind]}</div>
      <Input required maxLength={120} placeholder={kind === 'idea' ? 'e.g. A calmer app for a service people use every day' : 'e.g. Proposal sent to Acme'} value={f.title} onChange={e => setF({ ...f, title: e.target.value })} aria-label="Target" />
      <Input maxLength={400} placeholder="Done means… (one or two sentences)" value={f.done_means} onChange={e => setF({ ...f, done_means: e.target.value })} aria-label="Done means" />
      {kind === 'date' && <label className="flex items-center gap-2 text-sm">Done by <Input required type="date" className="w-44" value={f.date} onChange={e => setF({ ...f, date: e.target.value })} /></label>}
      {kind === 'period' && <div className="flex flex-wrap items-center gap-2 text-sm">Between <Input required type="date" className="w-44" value={f.from} onChange={e => setF({ ...f, from: e.target.value })} aria-label="From" />
        and <Input required type="date" className="w-44" value={f.to} onChange={e => setF({ ...f, to: e.target.value })} aria-label="To" /></div>}
      {kind === 'idea' && <label className="flex flex-wrap items-center gap-2 text-sm">Signals from a Topic brief
        <NativeSelect value={f.brief} onChange={e => setF({ ...f, brief: e.target.value })} className="w-56"><option value="">None</option>{briefings.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</NativeSelect></label>}
      <div className="flex gap-2"><Button size="pill" type="submit" disabled={!!c.busy}><Check />Add target</Button><Button size="pill" variant="ghost" type="button" onClick={onDone}>Cancel</Button></div>
    </form>
  </Card>
}

function TargetCard({ t, c, ideas, briefings }: { t: Target; c: Ctl; ideas: { text: string; src: string }[]; briefings: { id: string; name: string }[] }) {
  const [edit, setEdit] = useState(false)
  const [f, setF] = useState({ title: t.title, done_means: t.done_means || '', date: t.date || '', from: t.from || '', to: t.to || '', brief: t.brief || '' })
  const done = t.status === 'done'
  return <Card className={cn('space-y-3 p-4 sm:p-5', done && 'opacity-70')} data-target={t.id}>
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <div className="ax-label text-fjord">Target · {TARGET_LABEL[t.kind]}{t.kind !== 'idea' ? ' · ' + targetWhen(t) : ''}</div>
      <span className="text-ink-2 font-mono text-[13px]" data-target-progress="">{done ? 'done' : t.progress}</span>
    </div>
    {edit ? <form className="space-y-2" onSubmit={async e => { e.preventDefault(); if (await c.act('tu', 'project_target_update', { target: t.id, ...f, brief: f.brief || null }, 'Target saved')) setEdit(false) }}>
      <Input required value={f.title} maxLength={120} onChange={e => setF({ ...f, title: e.target.value })} aria-label="Target" />
      <Input value={f.done_means} maxLength={400} placeholder="Done means…" onChange={e => setF({ ...f, done_means: e.target.value })} aria-label="Done means" />
      {t.kind === 'date' && <Input type="date" className="w-44" value={f.date} onChange={e => setF({ ...f, date: e.target.value })} aria-label="Done by" />}
      {t.kind === 'period' && <div className="flex gap-2"><Input type="date" className="w-44" value={f.from} onChange={e => setF({ ...f, from: e.target.value })} aria-label="From" /><Input type="date" className="w-44" value={f.to} onChange={e => setF({ ...f, to: e.target.value })} aria-label="To" /></div>}
      {t.kind === 'idea' && <NativeSelect value={f.brief} onChange={e => setF({ ...f, brief: e.target.value })} className="w-56" aria-label="Topic brief"><option value="">No Topic brief</option>{briefings.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</NativeSelect>}
      <div className="flex flex-wrap gap-2"><Button size="pill" type="submit"><Check />Save</Button><Button size="pill" variant="ghost" type="button" onClick={() => setEdit(false)}>Cancel</Button>
        <Button size="pill" variant="ghost" type="button" className="text-danger ml-auto" onClick={() => c.act('td', 'project_target_delete', { target: t.id }, 'Target removed')}><Trash2 />Remove target</Button></div>
    </form> : <>
      <h3 className="text-lg font-semibold">{t.title}</h3>
      {t.done_means && <p className="text-ink-2 text-[15px]"><span className="font-semibold">Done means:</span> {t.done_means}</p>}
    </>}
    {t.kind === 'idea' ? <>
      <EntryList t={t} c={c} list="questions" title="Open questions" add="Add a question" />
      <EntryList t={t} c={c} list="go" title="We go when…" add="Add a condition" />
      {(t.signals || []).map(s => <div key={s.url} className="bg-bg-2 space-y-1.5 rounded-md px-3 py-2.5" data-signal="">
        <div className="ax-label">Signals · Topic brief{t.brief ? ` "${briefings.find(b => b.id === t.brief)?.name || t.brief}"` : ''}</div>
        <p className="text-[15px]">Possible answer to "{s.for}": {s.title}</p>
        <div className="flex gap-1.5"><Button size="pill" asChild><a href={s.url} target="_blank" rel="noopener noreferrer"><ExternalLink />Open</a></Button>
          <Button size="pill" variant="outline" onClick={() => c.act('sn', 'project_target_signal_not', { target: t.id, url: s.url }, 'Not relevant')}>Not relevant</Button></div>
      </div>)}
      <EntryList t={t} c={c} list="experiments" title="Next experiments" add="Add an experiment" mins />
    </> : <EntryList t={t} c={c} list="steps" title="Steps" add="Add a step" mins ideas={ideas} />}
    {!edit && <div className="flex flex-wrap gap-2 border-t pt-3">
      <Button size="pill" variant="outline" onClick={() => setEdit(true)}><Pencil />Edit target</Button>
      <Button size="pill" variant="ghost" onClick={() => c.act('ts', 'project_target_update', { target: t.id, status: done ? 'open' : 'done' }, done ? 'Target open again' : 'Target done')}>
        {done ? 'Open again' : <><Check />Mark target done</>}</Button>
    </div>}
  </Card>
}

function EntryList({ t, c, list, title, add, mins, ideas }: { t: Target; c: Ctl; list: 'steps' | 'questions' | 'go' | 'experiments'; title: string; add: string; mins?: boolean; ideas?: { text: string; src: string }[] }) {
  const L = (t[list] || []) as Entry[]
  const [v, setV] = useState(''), [m, setM] = useState('')
  const [showIdeas, setShowIdeas] = useState(false)
  const firstOpen = L.find(x => !x.done)
  const move = (i: number, d: number) => {
    const ids = L.map(x => x.id); const j = i + d
    if (j < 0 || j >= ids.length) return
    ;[ids[i], ids[j]] = [ids[j], ids[i]]
    c.act('mv', 'project_entry_reorder', { target: t.id, list, ids })
  }
  return <div className="space-y-1.5" data-entries={list}>
    <div className="text-ink-3 text-[12.5px] font-semibold">{title}</div>
    <ul className="space-y-0.5">{L.map((x, i) => <li key={x.id} className="group flex min-h-10 items-center gap-2.5">
      <button type="button" role="checkbox" aria-checked={!!x.done} aria-label={(x.done ? 'Not done: ' : 'Done: ') + x.text}
        onClick={() => c.act('e' + x.id, 'project_entry_update', { target: t.id, list, entry: x.id, done: !x.done })}
        className={cn('flex size-5 shrink-0 items-center justify-center rounded-sm border', x.done ? 'bg-fjord border-fjord text-on-fjord' : 'border-line-strong')}>{x.done && <Check className="size-3.5" />}</button>
      <span className={cn('min-w-0 flex-1 text-[15px]', x.done && 'text-ink-3 line-through')}>
        {x.text}
        {list === 'steps' && x === firstOpen && <span className="text-fjord ml-2 font-mono text-[11px] font-semibold">NOW</span>}
        {x.mins ? <span className="text-ink-3 ml-2 font-mono text-[12px]">{x.mins} min</span> : null}
        {x.day && <span className="text-ink-3 ml-2 font-mono text-[12px]">{dayLabel(x.day, true)}</span>}
        {x.waits_label && <span className="text-ink-3 ml-2 text-[12px]">· waits for {x.waits_label}</span>}
        {x.src && <span className="text-ink-3 ml-2 text-[12px]">· from {x.src}</span>}
      </span>
      <span className="flex shrink-0 gap-0.5 opacity-60 group-hover:opacity-100">
        {i > 0 && <button type="button" className="text-ink-3 hover:text-ink size-8" aria-label="Move up" onClick={() => move(i, -1)}><ChevronDown className="mx-auto size-4 rotate-180" /></button>}
        {list === 'steps' && <input type="date" aria-label="Day" className="text-ink-3 w-8 cursor-pointer bg-transparent text-[0px] max-sm:hidden" title="Plan it for a day"
          onChange={e => c.act('d' + x.id, 'project_entry_update', { target: t.id, list, entry: x.id, day: e.target.value || null }, e.target.value ? 'Planned for ' + dayLabel(e.target.value) : undefined)} />}
        <button type="button" className="text-ink-3 hover:text-danger size-8" aria-label={'Remove ' + x.text} onClick={() => c.act('x' + x.id, 'project_entry_delete', { target: t.id, list, entry: x.id })}><X className="mx-auto size-4" /></button>
      </span>
    </li>)}</ul>
    <form className="flex flex-wrap gap-2" onSubmit={async e => { e.preventDefault(); if (!v.trim()) return
      if (await c.act('a' + list, 'project_entry_add', { target: t.id, list, text: v.trim(), ...(mins && m ? { mins: +m } : {}) })) { setV(''); setM('') } }}>
      <Input value={v} onChange={e => setV(e.target.value)} placeholder={add} maxLength={200} className="min-w-[12rem] flex-1" aria-label={add} />
      {mins && <Input value={m} onChange={e => setM(e.target.value.replace(/\D/g, ''))} placeholder="min" inputMode="numeric" className="w-20" aria-label="Estimate in minutes" />}
      <Button size="icon-sm" type="submit" aria-label={add}><Plus /></Button>
    </form>
    {ideas && ideas.length > 0 && (showIdeas
      ? <div className="bg-bg-2 space-y-1 rounded-md p-3" data-step-ideas="">
        <div className="text-ink-3 text-[12.5px]">Suggested from the project's tasks, mails and meetings – add the ones that fit:</div>
        {ideas.map(x => <div key={x.text} className="flex items-center gap-2 text-sm"><span className="min-w-0 flex-1">{x.text} <span className="text-ink-3">· {x.src}</span></span>
          <Button size="pill" variant="outline" onClick={() => c.act('i', 'project_entry_add', { target: t.id, list: 'steps', text: x.text, src: x.src })}><Plus />Add</Button></div>)}
      </div>
      : <button type="button" className="text-fjord flex items-center gap-1.5 text-[13px] font-medium hover:underline" onClick={() => setShowIdeas(true)}><Sparkles className="size-3.5" />Suggest steps ({ideas.length})</button>)}
  </div>
}

/* ---------- People ---------- */
export function PeopleSection({ p, c }: { p: Project; c: Ctl }) {
  const plan = usePlan(c.on)
  const [adding, setAdding] = useState(false)
  const v = c.v
  if (!v) return null
  const shown = v.people.filter(x => x.source !== 'suggested')
  const sugg = v.people.filter(x => x.source === 'suggested')
  const mailable = shown.filter(x => !x.private && x.emails?.[0])
  return <Card className="space-y-1 p-0" data-project-people="">
    <div className="flex flex-wrap items-center gap-2 px-4 pt-4 pb-2">
      <UserCircle className="text-ink-3 size-5" /><h2 className="mr-auto text-[17px] font-semibold">People</h2>
      {mailable.length > 1 && <Button size="pill" variant="outline" onClick={() => openCompose({ to: mailable.map(x => x.emails![0]).join(', '), topic: p.name + ': ', notes: 'Project: ' + p.name })}><Mail />Write to everyone</Button>}
      <Button size="pill" variant="outline" onClick={() => setAdding(a => !a)}><Plus />Add person</Button>
    </div>
    {adding && <AddPerson c={c} onDone={() => setAdding(false)} />}
    <ul className="divide-y">
      {shown.map(x => <PersonRow key={x.key} x={x} p={p} c={c} />)}
      {sugg.map(x => <li key={x.key} className="flex flex-wrap items-center gap-3 px-4 py-3" data-person-suggested={x.key}>
        <span className="min-w-0 flex-1"><span className="font-semibold">{x.name}</span> <span className="text-ink-3 ml-1 font-mono text-[11px]">SUGGESTED</span>
          <span className="text-ink-3 block text-[13px]">{x.why}</span></span>
        <Button size="pill" onClick={() => c.act('pa', 'project_person_add', { key: x.key, name: x.name, source: 'suggested', why: x.why }, x.name + ' added')}>Add</Button>
        <Button size="pill" variant="outline" onClick={() => c.act('pn', 'project_person_not', { key: x.key }, 'Not asked again')}>Not for this project</Button>
      </li>)}
    </ul>
    {!shown.length && !sugg.length && !adding && <p className="text-ink-3 px-4 pb-3 text-sm">Nobody yet – add the people you work with on this project, or Axella suggests them from its mails and meetings.</p>}
    {plan && <div className="space-y-2 px-4 pb-3"><TagSuggestion plan={plan} pid={p.id} max={3} /></div>}
    <p className="text-ink-3 border-t px-4 py-2.5 text-[12px]">Roles are your own words: tap a role to edit it. Mail from project people is suggested for tagging, never tagged by itself. Nothing is sent without your tap.</p>
  </Card>
}

function PersonRow({ x, p, c }: { x: ProjPerson; p: Project; c: Ctl }) {
  const { go } = useApp()
  const [role, setRole] = useState<string | null>(null)
  const last = Object.entries(x.last || {}).sort((a, b) => b[1].localeCompare(a[1]))
  const lastCh = last[0]?.[0]
  const phone = x.phones?.[0]
  const msgHref = phone ? (lastCh === 'whatsapp' ? links.whatsapp(phone) : lastCh === 'signal' ? links.signal(phone) : links.sms(phone)) : null
  const open = [x.to_answer ? `${x.to_answer} to answer` : '', x.waiting ? `you're waiting on ${x.waiting}` : '', x.promises ? `${x.promises} promise${x.promises > 1 ? 's' : ''}` : ''].filter(Boolean)
  return <li className="space-y-2 px-4 py-3" data-project-person={x.key}>
    <div className="flex flex-wrap items-baseline gap-x-2">
      <button type="button" className="font-semibold hover:underline" onClick={() => x.pid && go({ kind: 'person', id: x.pid })}>{x.name}</button>
      <button type="button" aria-label={(x.star ? 'Not a key person: ' : 'Key person: ') + x.name} onClick={() => c.act('st' + x.key, 'project_person_update', { key: x.key, name: x.name, star: !x.star })}
        className={cn('size-6', x.star ? 'text-dawn' : 'text-ink-3 opacity-50 hover:opacity-100')}><Star className={cn('mx-auto size-4', x.star && 'fill-current')} /></button>
      {role !== null ? <form className="inline-flex gap-1" onSubmit={async e => { e.preventDefault(); if (await c.act('r', 'project_person_update', { key: x.key, name: x.name, role })) setRole(null) }}>
        <Input autoFocus value={role} maxLength={60} onChange={e => setRole(e.target.value)} className="h-7 w-36 text-[13px]" aria-label="Role" onKeyDown={e => { if (e.key === 'Escape') setRole(null) }} />
        <Button size="icon-sm" type="submit" aria-label="Save role"><Check /></Button></form>
        : <button type="button" className="text-ink-2 text-[14px] hover:underline" onClick={() => setRole(x.role || '')}>· {x.role || 'add a role'}</button>}
      {x.source === 'auto' && <span className="text-ink-3 font-mono text-[11px]" title={x.why}>AUTO</span>}
      <button type="button" className="text-ink-3 hover:text-danger ml-auto text-[12px]" onClick={() => c.act('rm', 'project_person_remove', { key: x.key }, `${x.name} is off ${p.name}`)}>Remove</button>
    </div>
    <p className="text-ink-3 text-[13px]">{[x.source === 'auto' ? x.why : '', last.length ? `${CH[last[0][0]] || last[0][0]} ${ago(last[0][1])}` : 'No contact in Axella yet', ...open,
      x.private ? 'private contact – no content' : ''].filter(Boolean).join(' · ')}</p>
    <div className="flex flex-wrap gap-1.5">
      {x.emails?.[0] && <Button size="pill" variant="outline" onClick={() => x.private ? (location.href = links.mailto(x.emails![0])) : openCompose({ to: x.emails![0], topic: p.name + ': ', notes: 'Project: ' + p.name })}><Mail />Mail</Button>}
      {msgHref && <Button size="pill" variant="outline" asChild><a href={msgHref}><MessageCircle />Message</a></Button>}
      {phone && <Button size="pill" variant="outline" asChild><a href={links.tel(phone)}><Phone />Call</a></Button>}
      {x.emails?.[0] && <Button size="pill" variant="outline" onClick={() => openNewPrep({ title: `${p.name} – meeting with ${x.name.split(/\s+/)[0]}`, project: p.id, attendees: [{ name: x.name, email: x.emails![0] }] })}><CalendarCheck />Meeting</Button>}
    </div>
  </li>
}

function AddPerson({ c, onDone }: { c: Ctl; onDone: () => void }) {
  const [q, setQ] = useState('')
  const [book, setBook] = useState<{ id: string; name: string; emails: string[]; phones: string[] }[] | null>(null)
  useEffect(() => { get<{ people: { id: string; name: string; emails: string[]; phones: string[] }[] }>('contacts').then(b => setBook(b.people)).catch(() => setBook([])) }, [])
  const f = q.trim().toLowerCase()
  const hits = f.length < 2 ? [] : (book || []).filter(x => x.name.toLowerCase().includes(f) || x.emails.some(e => e.includes(f))).slice(0, 6)
  return <div className="space-y-2 px-4 pb-3" data-add-person="">
    <Input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Name or e-mail from Contacts" aria-label="Find a person" />
    {!book && <p className="text-ink-3 flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" />Reading Contacts…</p>}
    {hits.map(x => <button key={x.id} type="button" className="hover:bg-bg-2 flex min-h-11 w-full items-center gap-2 rounded-md px-2 text-left text-sm"
      onClick={async () => { if (await c.act('add', 'project_person_add', { key: x.emails[0] || x.phones[0] || x.id, pid: x.id, name: x.name }, x.name + ' added')) onDone() }}>
      <span className="font-medium">{x.name}</span><span className="text-ink-3 truncate">{x.emails[0] || x.phones[0]}</span></button>)}
    {f.includes('@') && !hits.length && <Button size="pill" variant="outline" onClick={async () => { if (await c.act('add', 'project_person_add', { key: f, name: f }, 'Added')) onDone() }}><Plus />Add {f}</Button>}
  </div>
}
