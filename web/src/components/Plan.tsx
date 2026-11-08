/* Targets and Now · Next · Later on Today (setup/planner.py): a state suggestion, the focus question ("What are we
   working on today?"), one Now · Next · Later card, a tagging suggestion – and the rest of the week as its own page.
   Suggestions only: nothing is sent, booked, moved or changed without a tap; Hold is the one calendar change. Owner only. */
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { CalendarCheck, Check, ChevronRight, Loader2, X, axi } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { SwipeHint, useRowSwipe } from '@/components/ItemRow'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { useNotesOwner } from '@/lib/notes'
import { dayLabel, fmtMins, planChanged, usePlan, type Plan, type PlanItem, type Suggestion, type Week } from '@/lib/plan'
import { projColor } from '@/lib/projects'
import type { RowApi } from '@/lib/rows'
import { cn, isoDate } from '@/lib/utils'

export const PlanIcon = axi('focus')

function usePlanAct() {
  const { ax } = useApp()
  const [busy, setBusy] = useState<string | null>(null)
  const run = async (key: string, action: string, body: object, msg?: string, undo?: () => void) => {
    setBusy(key)
    try {
      const r = await ax.act<any>(action, body, action.startsWith('project_') ? ['projects'] : [])
      planChanged()
      if (msg) toast(msg, undo ? { action: { label: 'Undo', onClick: undo } } : undefined)
      return r
    } catch (e: any) { toast.error(e.message); return null } finally { setBusy(null) }
  }
  return { busy, run }
}

const Diamond = ({ pid, size = 7 }: { pid?: string; size?: number }) => {
  const { activeProjects } = useApp()
  return <span className="ax-diamond shrink-0" style={{ color: pid ? projColor(activeProjects, pid) : 'var(--ax-ink-3)', width: size, height: size }} />
}

/** Today: everything the plan has to say, in one place. */
export function PlanToday() {
  const { ax } = useApp()
  const owner = useNotesOwner(ax.apiOk)
  const plan = usePlan(!!owner && ax.apiOk)
  if (!plan || !plan.enabled) return null
  return <div className="space-y-3" data-plan-today="">
    {(plan.suggestions || []).slice(0, 2).map(s => <StateCard key={s.key} s={s} />)}
    <TagSuggestion plan={plan} max={1} />
    {!plan.chosen && (plan.question?.projects.length || 0) > 0 ? <FocusQuestion plan={plan} />
      : plan.plan && (plan.plan.focus.length > 0 || plan.plan.now || plan.plan.next.length > 0) ? <NowNextLater plan={plan} />
      : plan.plan?.none ? <NoneToday plan={plan} /> : null}
  </div>
}

/* ---------- a project state suggestion: "Website refresh can move again – Kim sent the copy this morning." ---------- */
function StateCard({ s }: { s: Suggestion }) {
  const { busy, run } = usePlanAct()
  const yes = () => run('y', 'project_state', { id: s.pid, state: s.kind === 'idle' ? 'paused' : s.kind === 'done' ? 'done' : 'active' },
    s.kind === 'idle' ? 'Paused' : s.kind === 'done' ? 'Marked done – archive it whenever you are ready' : 'Back to Active')
  return <section className="bg-card flex flex-wrap items-center gap-3 rounded-lg border p-4" data-plan-suggestion={s.kind}>
    <span className="bg-bg-2 text-ink flex size-9 shrink-0 items-center justify-center rounded-md"><Diamond pid={s.pid} size={9} /></span>
    <div className="min-w-0 flex-1"><div className="ax-label">Project state · suggestion</div><div className="text-[15px]">{s.text}</div></div>
    <div className="flex gap-1.5">
      <Button size="pill" disabled={!!busy} onClick={yes}>{s.yes}</Button>
      <Button size="pill" variant="outline" disabled={!!busy} onClick={() => run('n', 'plan_suggestion', { key: s.key })}>{s.no}</Button>
    </div>
  </section>
}

/* ---------- "What are we working on today?" ---------- */
function FocusQuestion({ plan }: { plan: Plan }) {
  const { ax } = useApp()
  const { busy, run } = usePlanAct()
  const q = plan.question!
  const [pick, setPick] = useState<string[]>(q.projects)
  const [more, setMore] = useState(false)
  const act = ax.projects.filter(p => p.status === 'active' && (plan.projects[p.id]?.state || 'active') === 'active')
  const withTargets = act.filter(p => (plan.projects[p.id]?.targets || []).some(t => t.status !== 'done'))
  const shown = more ? act : withTargets.filter(p => q.projects.includes(p.id) || withTargets.length <= 4)
  const note = (pid: string) => {
    const t = (plan.projects[pid]?.targets || []).find(x => x.status !== 'done')
    return t ? (t.due ? `${t.title} · ${dayLabel(t.due)}` : t.progress) : ''
  }
  const toggle = (pid: string) => setPick(x => x.includes(pid) ? x.filter(y => y !== pid) : x.length >= 3 ? x : [...x, pid])
  return <section className="bg-card space-y-3 rounded-lg border p-4 sm:p-5" aria-labelledby="focus-q" data-focus-question="">
    <div className="ax-label text-fjord">Focus · today</div>
    <h2 id="focus-q" className="text-lg font-semibold">What are we working on today?</h2>
    <p className="text-ink-2 text-[15px]">{q.reason}</p>
    <div className="flex flex-wrap gap-2">
      {shown.map(p => <button key={p.id} type="button" aria-pressed={pick.includes(p.id)} onClick={() => toggle(p.id)} data-focus-pick={p.id}
        className={cn('flex min-h-11 items-center gap-2.5 rounded-md border px-3 py-2 text-left text-[15px] max-sm:w-full',
          pick.includes(p.id) ? 'border-fjord bg-fjord-soft' : 'border-line-strong bg-card text-ink-2')}>
        <Diamond pid={p.id} /><span className={cn(pick.includes(p.id) && 'font-semibold')}>{p.name}</span>
        <span className="text-ink-3 text-[13px] max-sm:ml-auto">{note(p.id)}</span></button>)}
      {!more && act.length > shown.length && <button type="button" className="text-fjord min-h-11 px-2 text-sm font-medium hover:underline" onClick={() => setMore(true)}>Other projects</button>}
    </div>
    <div className="flex flex-wrap items-center gap-2">
      <Button disabled={!!busy || !pick.length} onClick={() => run('plan', 'plan_focus', { projects: pick }, 'Planned – Axella re-plans quietly as you go')} data-plan-my-day="">
        {busy === 'plan' ? <Loader2 className="animate-spin" /> : <PlanIcon />}Plan my day</Button>
      <Button variant="outline" disabled={!!busy} onClick={() => run('none', 'plan_none', {}, 'Nothing planned today')} data-none-today="">None today</Button>
      <span className="text-ink-3 text-[13px]">Your choice is the plan. A free calendar isn't taken to mean free.</span>
    </div>
  </section>
}

function NoneToday({ plan }: { plan: Plan }) {
  const { busy, run } = usePlanAct()
  return <div className="text-ink-3 flex flex-wrap items-center gap-2 px-1 text-[13px]" data-none-line="">
    <PlanIcon className="size-3.5" />Nothing planned today.
    <button type="button" className="text-fjord font-medium hover:underline" disabled={!!busy} onClick={() => run('u', 'plan_none', { none: false, date: plan.plan?.date })}>Plan my day after all</button>
  </div>
}

/* ---------- one Today card: Now · Next · Later in today's real free stretches ---------- */
function NowNextLater({ plan }: { plan: Plan }) {
  const { go } = useApp()
  const p = plan.plan!
  const [all, setAll] = useState(false)
  return <section className="bg-card space-y-3 rounded-lg border p-4 sm:p-5" aria-labelledby="nnl-h" data-now-next-later="">
    <div className="flex flex-wrap items-baseline justify-between gap-3">
      <h2 id="nnl-h" className="text-lg font-semibold">Now · Next · Later</h2>
      <button type="button" className="text-fjord text-[15px] font-semibold hover:underline" onClick={() => go({ kind: 'week' })} data-plan-week="">Rest of the week</button>
    </div>
    {plan.calendar_error && <p className="text-ink-3 text-[13px]">Couldn't read the calendar ({plan.calendar_error}) – the plan uses what it has.</p>}
    {p.now ? <NowBox it={p.now} date={p.date} /> : <p className="text-ink-3 text-sm">No free stretch left today for the focus projects.</p>}
    {p.next.length > 0 && <>
      <div className="ax-label pt-1">Next · today</div>
      <ul className="divide-y border-t" data-plan-next="">{p.next.slice(0, all ? 20 : 4).map(it => <PlanRow key={it.key} it={it} date={p.date} hold />)}</ul>
    </>}
    {p.later.length > 0 && <>
      <div className="ax-label pt-1">Later</div>
      <ul className="divide-y border-t" data-plan-later="">{p.later.slice(0, all ? 20 : 3).map(it => <PlanRow key={it.key} it={it} date={p.date} />)}</ul>
    </>}
    {(p.next.length > 4 || p.later.length > 3) && !all && <button type="button" className="text-fjord text-sm font-medium hover:underline" onClick={() => setAll(true)}>Show all</button>}
    {p.done.length > 0 && <p className="text-ink-3 text-[13px]" data-plan-done="">Done today: {p.done.map(x => x.title).join(' · ')}</p>}
    <p className="text-ink-3 text-[13px]">{fmtMins(p.free)} free today · {p.buffer} min buffer around each meeting · Not now teaches Axella the order</p>
  </section>
}

function useItemActs(it: PlanItem, date: string) {
  const { busy, run } = usePlanAct()
  const undo = () => run('u', 'plan_item', { key: it.key, status: null, date })
  return {
    busy,
    done: () => run('d', 'plan_item', { key: it.key, status: 'done', date }, `Done: ${it.title}`, undo),
    notnow: () => run('n', 'plan_item', { key: it.key, status: 'notnow', date }, 'Not now – moved to Later', undo),
    swap: () => run('s', 'plan_swap', { key: it.key, date }, 'Swapped'),
    hold: async () => {
      const r = await run('h', 'plan_hold', { date, start: it.start, end: it.end, label: it.title }, undefined)
      const id = r?.result?.id
      if (r) toast(`Held ${it.start}–${it.end} in your calendar`, id ? { action: { label: 'Undo', onClick: () => run('x', 'cal_delete', { id, start: new Date(`${date}T${it.start}`).toISOString() }, 'Hold removed') } } : undefined)
    },
  }
}

function NowBox({ it, date }: { it: PlanItem; date: string }) {
  const a = useItemActs(it, date)
  const api = useRef<RowApi>({}); api.current = { done: a.done, snooze: a.notnow, snoozeLabel: 'Not now' }
  const sw = useRowSwipe(api)
  return <div className="relative overflow-hidden rounded-md">
    {sw.hint && <SwipeHint h={sw.hint} dx={sw.dx} />}
    <div {...sw.handlers} data-noswipe="" style={sw.style} className="bg-fjord-soft relative touch-pan-y space-y-2 rounded-md px-4 py-3" data-plan-now="">
      <div className="ax-label text-fjord">Now · {it.start}–{it.end} · {fmtMins(it.mins || 0)}</div>
      <div className="flex items-center gap-2.5"><Diamond pid={it.pid} /><span className="text-lg font-semibold">{it.title}</span></div>
      <p className="text-ink-2 text-[13px] font-medium">{[it.project, it.where, it.why].filter(Boolean).join(' · ')}</p>
      <div className="flex flex-wrap gap-2">
        <Button disabled={!!a.busy} onClick={a.done} data-plan-done-btn=""><Check />Done</Button>
        <Button variant="outline" disabled={!!a.busy} onClick={a.swap}>Swap</Button>
        <Button variant="outline" disabled={!!a.busy} onClick={a.notnow} data-plan-notnow="">Not now</Button>
        <Button variant="ghost" disabled={!!a.busy} onClick={a.hold} title="Puts a busy block in your calendar"><CalendarCheck />Hold</Button>
      </div>
    </div>
  </div>
}

function PlanRow({ it, date, hold }: { it: PlanItem; date: string; hold?: boolean }) {
  const a = useItemActs(it, date)
  const api = useRef<RowApi>({}); api.current = hold ? { done: a.done, snooze: a.notnow, snoozeLabel: 'Not now' } : {}
  const sw = useRowSwipe(api)
  const when = it.start ? `${it.start}–${it.end}` : it.when || 'Later'
  return <li className="relative overflow-hidden">
    {sw.hint && <SwipeHint h={sw.hint} dx={sw.dx} />}
    <div {...sw.handlers} data-noswipe="" style={sw.style} className="bg-card relative flex min-h-11 touch-pan-y items-center gap-3 py-2.5" data-plan-row={it.key}>
      <span className="text-ink-2 w-[6.5rem] shrink-0 font-mono text-[13px] sm:w-[7.5rem] sm:text-[14px]">{when}</span>
      <span className="flex min-w-0 flex-1 items-center gap-2 text-[15px]">{it.pid && <Diamond pid={it.pid} />}
        <span className="min-w-0">{it.title} <span className="text-ink-3 text-[13px]">· {[it.project, it.why].filter(Boolean).join(' · ')}</span></span></span>
      {hold && it.start && <Button size="pill" variant="outline" disabled={!!a.busy} onClick={a.hold} aria-label={`Hold ${when} in calendar`}>Hold</Button>}
    </div>
  </li>
}

/* ---------- "New mail from Lee: 'Delivery dates'. Tag it to Acme?" – suggested, never tagged by itself ---------- */
export function TagSuggestion({ plan, pid, max = 3 }: { plan: Plan; pid?: string; max?: number }) {
  const { ax, projectsFor } = useApp()
  const { busy, run } = usePlanAct()
  const [gone, setGone] = useState<string[]>([])
  const people: Record<string, string[]> = {}
  for (const [id, l] of Object.entries(plan.projects)) for (const k of l.people || []) (people[k] ||= []).push(id)
  const act = ax.projects.filter(p => p.status === 'active')
  const out: { it: typeof items[number]; cands: string[] }[] = []
  const items = (ax.current?.data.items || []).filter(i => !ax.isHandled(i.id) && !gone.includes(i.id) && i.section !== 'cal')
  for (const it of items) {
    const k = (it.from?.address || '').toLowerCase()
    const cands = (people[k] || []).filter(id => act.some(p => p.id === id) && (!pid || id === pid))
    if (!cands.length) continue
    const tagged = projectsFor(it).map(p => p.id)
    const open = cands.filter(id => !tagged.includes(id) && !act.find(p => p.id === id)?.hidden_items?.includes(it.id))
    if (open.length && !tagged.some(t => cands.includes(t))) out.push({ it, cands: open })
    if (out.length >= max) break
  }
  if (!out.length) return null
  const name = (id: string) => act.find(p => p.id === id)?.name || id
  return <>{out.map(({ it, cands }) => {
    const first = it.from?.name?.split(/\s+/)[0] || it.from?.address
    const tag = (id: string) => run('t' + it.id, 'project_item_add', { id, item_id: it.id, digest: ax.current?.name, headline: it.headline || it.subject }, 'Tagged to ' + name(id))
    return <section key={it.id} className="bg-bg-2 flex flex-wrap items-center gap-3 rounded-lg px-4 py-3" data-tag-suggestion={it.id}>
      <div className="min-w-0 flex-1"><div className="ax-label">Tagging · suggestion</div>
        <div className="text-[15px]">New {it.channel === 'mail' ? 'mail' : 'message'} from {first}{it.subject ? `: "${it.subject}"` : ''}. Tag it to {cands.length === 1 ? name(cands[0]) : cands.map(name).join(' or ')}?</div></div>
      <div className="flex flex-wrap gap-1.5">
        {cands.slice(0, 3).map(id => <Button key={id} size="pill" disabled={!!busy} onClick={() => tag(id)}>Tag to {name(id)}</Button>)}
        <OtherProject onPick={tag} exclude={cands} />
        <Button size="pill" variant="ghost" disabled={!!busy} onClick={async () => {
          setGone(g => [...g, it.id])
          for (const id of cands) await run('n' + id, 'project_item_remove', { id, item_id: it.id })
          toast('Not project mail')
        }}><X />Not project mail</Button>
      </div>
    </section>
  })}</>
}

function OtherProject({ onPick, exclude }: { onPick: (id: string) => void; exclude: string[] }) {
  const { ax } = useApp()
  const [open, setOpen] = useState(false)
  const list = ax.projects.filter(p => p.status === 'active' && !exclude.includes(p.id))
  if (!list.length) return null
  return open ? <select className="border-line-strong bg-card h-8 rounded-md border px-2 text-[13px]" autoFocus defaultValue="" onChange={e => { if (e.target.value) onPick(e.target.value); setOpen(false) }}
    onBlur={() => setOpen(false)} aria-label="Other project">
    <option value="">Pick a project…</option>{list.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
    : <Button size="pill" variant="outline" onClick={() => setOpen(true)}>Other project</Button>
}

/* ---------- the rest of the week ---------- */
export function WeekView() {
  const { ax, go } = useApp()
  const owner = useNotesOwner(ax.apiOk)
  const [whole, setWhole] = useState(false)
  const [w, setW] = useState<Week | null>(null)
  const [err, setErr] = useState('')
  const { busy, run } = usePlanAct()
  const load = () => get<Week>('plan_week' + (whole ? '?whole=1' : '')).then(setW).catch(e => setErr(e.message))
  useEffect(() => { if (owner) load() }, [owner, whole])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const h = () => { if (owner) load() }; window.addEventListener('ax-plan', h); return () => window.removeEventListener('ax-plan', h) })
  const name = (id: string) => ax.projects.find(p => p.id === id)?.name || id
  const today = isoDate(new Date())
  if (owner === false) return <p className="text-ink-3 text-sm">Only the owner sees the plan.</p>
  return <div className="space-y-4" data-week-view="">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div><button type="button" className="text-fjord text-[15px] font-semibold hover:underline" onClick={() => go({ kind: 'today' })}>Back to today</button>
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.02em]">The rest of the week</h1>
        <p className="text-ink-3 text-[13px] font-medium">Suggested from your targets · change any day</p></div>
      <div role="group" aria-label="Show" className="bg-bg-2 flex rounded-md p-[3px]">
        {([false, true] as const).map(v => <button key={String(v)} type="button" aria-pressed={whole === v} onClick={() => setWhole(v)}
          className={cn('min-h-10 rounded-md px-3.5 text-[15px]', whole === v ? 'bg-card text-ink font-semibold' : 'text-ink-2')}>{v ? 'Whole week' : 'Rest of week'}</button>)}
      </div>
    </div>
    {err && <p className="text-dawn text-sm">{err}</p>}
    {!w && !err && <p className="text-ink-3 flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" />Reading your calendar…</p>}
    {w && !w.enabled && <p className="text-ink-3 text-sm">Targets and Now · Next · Later is switched off in Settings → Calendar.</p>}
    {w?.heads_up && <section aria-label="Heads-up" className="bg-fjord-soft flex flex-wrap items-center gap-4 rounded-lg px-5 py-4" data-heads-up="">
      <p className="min-w-[16rem] flex-1 text-[15px]"><span className="font-semibold">{w.heads_up.text}</span>{w.heads_up.move ? ` ${w.heads_up.move.label}, or keep the plan?` : ' Keep the plan?'}</p>
      <div className="flex flex-wrap gap-2">
        {w.heads_up.move && <Button disabled={!!busy} onClick={() => run('m', 'plan_heads_up', { key: w.heads_up!.key, how: 'moved', item: w.heads_up!.move!.key }, 'Moved to next week')}>{w.heads_up.move.label.replace(/ to next week$/, '')}</Button>}
        <Button variant="outline" disabled={!!busy} onClick={() => run('k', 'plan_heads_up', { key: w.heads_up!.key, how: 'keep' }, 'Plan kept')}>Keep the plan</Button>
      </div>
    </section>}
    {w?.calendar_error && <p className="text-ink-3 text-[13px]">Couldn't read the calendar ({w.calendar_error}).</p>}
    <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(210px,1fr))]">
      {(w?.days || []).map(d => <article key={d.date} data-week-day={d.date}
        className={cn('flex flex-col gap-3 rounded-lg border p-4', d.date === today ? 'border-fjord bg-card border-2' : d.private ? 'bg-bg-2' : 'bg-card', d.past && 'opacity-60')}>
        <h2 className="text-lg font-semibold">{d.date === today ? 'Today' : new Date(d.date + 'T12:00').toLocaleDateString('en-GB', { weekday: 'long' })}
          <span className="text-ink-3 ml-1.5 font-mono text-[13px] font-normal">{dayLabel(d.date, true).replace(/^\w+ /, '')}</span></h2>
        {d.private && <span className="bg-private-soft text-private self-start rounded-sm px-1.5 py-0.5 text-[12px] font-semibold">Private</span>}
        {d.focus.length > 0 && <div className="flex flex-wrap gap-1.5">{d.focus.map(id => <span key={id} className="bg-bg-2 flex items-center gap-1.5 rounded-sm px-2 py-1 text-[13px] font-medium"><Diamond pid={id} size={6} />{name(id)}</span>)}</div>}
        {d.targets.map(t => <div key={t.title} className="bg-bg-2 flex items-center gap-2 rounded-md px-2.5 py-2 text-[13px] font-semibold"><Diamond pid={t.pid} size={8} />Target · {t.title}</div>)}
        {(d.meeting_mins || 0) >= 300 && <p className="text-ink-2 text-[13px]">{fmtMins(d.meeting_mins!)} of meetings. Only small things fit.</p>}
        {d.items.length > 0 ? <ul className="space-y-2.5 text-[15px]">{d.items.map(it => <li key={it.key}>
          <span className="text-ink-2 block font-mono text-[13px]">{it.start}–{it.end}</span>{it.title}</li>)}</ul>
          : !d.past && <p className="text-ink-2 text-[14px]">{d.none ? 'Nothing planned – your choice.' : d.private ? 'Nothing planned.' : 'Nothing slotted.'}</p>}
        {!d.past && d.date > today && <DayFocus date={d.date} focus={d.focus} />}
      </article>)}
    </div>
    <p className="text-ink-3 text-[13px] font-medium">Suggestions only. Hold puts a busy block in your calendar on your tap; nothing else changes.</p>
  </div>
}

function DayFocus({ date, focus }: { date: string; focus: string[] }) {
  const { ax } = useApp()
  const { busy, run } = usePlanAct()
  const [open, setOpen] = useState(false)
  const [pick, setPick] = useState<string[]>(focus)
  if (!open) return <button type="button" className="text-fjord mt-auto self-start text-[13px] font-medium hover:underline" onClick={() => setOpen(true)}>Change</button>
  const act = ax.projects.filter(p => p.status === 'active')
  return <div className="mt-auto space-y-2">
    <div className="flex flex-wrap gap-1.5">{act.map(p => <button key={p.id} type="button" aria-pressed={pick.includes(p.id)}
      onClick={() => setPick(x => x.includes(p.id) ? x.filter(y => y !== p.id) : x.length >= 3 ? x : [...x, p.id])}
      className={cn('flex min-h-9 items-center gap-1.5 rounded-sm border px-2 text-[13px]', pick.includes(p.id) ? 'border-fjord bg-fjord-soft' : 'border-line-strong')}><Diamond pid={p.id} size={6} />{p.name}</button>)}</div>
    <div className="flex gap-1.5">
      <Button size="pill" disabled={!!busy || !pick.length} onClick={async () => { if (await run('f', 'plan_focus', { projects: pick, date }, 'Focus set for ' + dayLabel(date))) setOpen(false) }}>Save</Button>
      <Button size="pill" variant="outline" disabled={!!busy} onClick={async () => { if (await run('n', 'plan_none', { date }, 'Nothing planned that day')) setOpen(false) }}>None</Button>
      <Button size="pill" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
    </div>
  </div>
}

/* the morning digest's focus question (link "plan") opens Today */
export function PlanButton() {
  const { go } = useApp()
  return <Button size="pill" onClick={() => { go({ kind: 'today' }); setTimeout(() => document.querySelector('[data-plan-today]')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 300) }}>
    <PlanIcon />Plan my day<ChevronRight /></Button>
}

/* Settings → Calendar: switch the planner on/off, and the buffer around meetings */
export function PlanSettingsCard() {
  const { ax } = useApp()
  const owner = useNotesOwner(ax.apiOk)
  const plan = usePlan(!!owner && ax.apiOk)
  const { busy, run } = usePlanAct()
  if (!plan) return null
  const s = plan.settings
  return <div className="bg-card divide-y overflow-hidden rounded-lg border" data-plan-settings="">
    <div className="px-4 py-2.5"><div className="font-semibold">Targets and Now · Next · Later</div>
      <div className="text-ink-3 text-[12.5px]">The focus question in the morning digest and on Today, and a day plan in your real free time. Suggestions only. Off: no question, no card, no plan – states, people and targets are kept.</div></div>
    <div className="flex flex-wrap items-center gap-4 px-4 py-3 text-sm">
      <label className="flex min-h-11 items-center gap-2"><input type="checkbox" className="size-4" checked={s.enabled} disabled={!!busy}
        onChange={e => run('on', 'plan_settings', { enabled: e.target.checked }, e.target.checked ? 'Planner on' : 'Planner off')} />On</label>
      <label className="flex items-center gap-2">Buffer around meetings
        <select className="border-line-strong bg-card h-8 rounded-md border px-2 text-xs" value={String(s.buffer)} disabled={!!busy}
          onChange={e => run('buf', 'plan_settings', { buffer: Number(e.target.value) }, 'Saved')}>
          {[0, 5, 10, 15, 20, 30].map(m => <option key={m} value={m}>{m} min</option>)}</select></label>
    </div>
  </div>
}
