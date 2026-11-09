import { useStatusShort } from '@/components/Status'
import { MailReaderHost } from '@/components/MailReader'
import { CatchUpDialog } from '@/components/Welcome'
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { Activity, MessageCircle, Archive as ArchiveIcon, BarChart3, Receipt, Newspaper, Radar, Settings as SettingsIcon, ChevronDown, ChevronRight, Check, MoreHorizontal, Bell, BellRing, Briefcase, CalendarDays, FolderInput, FolderKanban, Home, Hourglass, Headphones, Inbox, ListTodo, Mail, MailPlus, Menu, Square, Moon, Phone, Plus, RotateCw, ShieldCheck, Sparkles, Sun, SunMoon, ThemeDark, ThemeLight, UserCircle, Recurring, Search as SearchIcon, Briefing as BriefingNavIcon, Palmtree } from '@/components/ax-icons'
import { DndContext, KeyboardSensor, MouseSensor, TouchSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core'
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Brand, Rune } from '@/components/icons'
import { ArrivalNote, RevealOnArrival } from '@/components/Arrival'
import { ConnectionBar } from '@/components/Offline'
import { CleanupIcon } from '@/components/Cleanup'
import { GuideHost, GuideIcon, openGuide } from '@/components/Guide'
import { TourHost } from '@/components/Tour'
import { ReportHost, ReportIcon, longPress, openReport, useReportShortcut } from '@/components/Report'
import { BriefingIcon, NowIcon, useNow } from '@/components/Now'
import { NewMessageHost, openNewMessage } from '@/components/Contacts'
import { MeetingIcon, NewPrepHost, openNewPrep } from '@/components/Meetings'
import { TripsIcon } from '@/components/Trips'
import { InviteHost } from '@/components/Invite'
import { ComposeHost, openCompose } from '@/components/Compose'
import { TaskFromHost } from '@/components/TaskFromMail'
import { OutboxBar } from '@/components/Outbox'
import { ArchiveHost, openArchive } from '@/components/Projects'
import { KnowledgeHost, KnowledgeIcon } from '@/components/Knowledge'
import { NOTE_KEY, NoteHost, NoteIcon, useNoteShortcut } from '@/components/Notes'
import { openNote, useNotesOwner } from '@/lib/notes'
import { STATE_COLOR, stateOf, usePlan } from '@/lib/plan'
import { needsCheck, openKnowledge, useKnowledge } from '@/lib/knowledge'
import { AskHost, AskIcon, openAsk } from '@/components/Ask'
import { ListenBar, toggleListen, useListening } from '@/components/Listen'
import { jump } from '@/components/Today'
import { useSweep } from '@/components/Settings'
import { get } from '@/lib/api'
import { useApp, type CtxFilter } from '@/lib/app'
import { dayKey, dayLabel, isRegular, parseName, taskInCtx } from '@/lib/data'
import { bell, pushOn, registerSW } from '@/lib/push'
import { projColor } from '@/lib/projects'
import { useTheme } from '@/lib/theme'
import { cn, isoDate, store } from '@/lib/utils'
import type { Project } from '@/lib/types'

/* ---------- theme (lib/theme.ts) ---------- */
function useThemeCycle() {
  const [t, set] = useTheme()
  const next = () => { const n = ({ auto: 'light', light: 'dark', dark: 'auto' } as const)[t]; set(n); toast('Theme: ' + ({ auto: 'System', light: 'Light', dark: 'Dark' })[n]) }
  return [t, next, set] as const
}

/* ---------- controls shared by the top bar (tablet/desktop) and the menu (phone) ---------- */
function useControls() {
  const { ax } = useApp()
  const [theme, nextTheme, setTheme] = useThemeCycle()
  const [hasSW, setHasSW] = useState(false), [on, setOn] = useState(false)
  useEffect(() => { registerSW().then(ok => { setHasSW(ok); pushOn().then(setOn) }) }, [])
  const ThemeI = theme === 'auto' ? SunMoon : theme === 'light' ? Sun : Moon
  const who = ax.who ? (ax.who.startsWith('node:') ? ax.who.slice(5) + ' (this Mac)' : ax.who) : null
  const ring = async () => { try { toast(await bell(on)); setOn(await pushOn()) } catch (e: any) { toast.error('Failed: ' + e.message) } }
  return { ax, theme, nextTheme, setTheme, ThemeI, hasSW, on, ring, who }
}
type Controls = ReturnType<typeof useControls>

/* ---------- sidebar ---------- */
const LargeCtx = createContext(false)
function NavItem({ icon: I, label, count, active, onClick, color, tour }: { icon: any; label: ReactNode; count?: number; active?: boolean; onClick: () => void; color?: string; tour?: string }) {
  const lg = useContext(LargeCtx)   // the slide-in menu on phones: ~10% bigger text and taller rows
  if (!useApp().ax.stateReady) count = undefined    // no numbers until Done/snoozed is known (else they jump after a reload)
  return <button onClick={onClick} aria-current={active ? 'page' : undefined} data-tour={tour}
    className={cn('relative flex w-full items-center gap-2.5 rounded-md px-2.5 text-left transition-colors duration-[120ms] outline-none',
      lg ? 'py-2.5 text-[15.5px] gap-3' : 'py-[7px] text-sm',
      active ? 'bg-surface text-ink ring-line font-semibold ring-1 before:bg-fjord before:absolute before:inset-y-1.5 before:left-0 before:w-0.5'
        : 'text-ink-2 hover:bg-surface/60 hover:text-ink')}>
    {color ? <span className={cn('flex items-center justify-center', lg ? 'size-[18px]' : 'size-[18px]')}><span className="ax-diamond" style={{ color, width: 7, height: 7 }} /></span>
      : <I className={cn('shrink-0', lg ? 'size-5' : 'size-[18px]', active && 'text-fjord')} />}
    <span className="min-w-0 flex-1 truncate">{label}</span>
    {!!count && <span className={cn('font-mono tabular-nums', lg ? 'text-sm' : 'text-xs', active ? 'text-fjord' : 'text-ink-3')}>{count}</span>}
  </button>
}

/* Projects in the menu: drag to reorder (mouse: drag; touch: long-press then drag). Order is saved on the Mac mini. */
function SortableProjects({ projects, render }: { projects: Project[]; render: (p: Project) => ReactNode }) {
  const { ax } = useApp()
  const [ids, setIds] = useState(projects.map(p => p.id))
  useEffect(() => { setIds(projects.map(p => p.id)) }, [projects.map(p => p.id).join()])
  const sensors = useSensors(useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 300, tolerance: 8 } }), useSensor(KeyboardSensor))
  const byId = Object.fromEntries(projects.map(p => [p.id, p]))
  async function end(e: DragEndEvent) {
    if (!e.over || e.active.id === e.over.id) return
    const next = arrayMove(ids, ids.indexOf(String(e.active.id)), ids.indexOf(String(e.over.id)))
    setIds(next)
    try { await ax.act('project_reorder', { ids: next }, ['projects']) } catch (err: any) { toast.error('Failed: ' + err.message); setIds(projects.map(p => p.id)) }
  }
  return <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={end}>
    <SortableContext items={ids} strategy={verticalListSortingStrategy}>
      {ids.filter(id => byId[id]).map(id => <SortableRow key={id} id={id}>{render(byId[id])}</SortableRow>)}
    </SortableContext>
  </DndContext>
}
function SortableRow({ id, children }: { id: string; children: ReactNode }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id })
  return <div ref={setNodeRef} data-noswipe="" {...attributes} {...listeners}
    style={{ transform: CSS.Transform.toString(transform), transition, zIndex: isDragging ? 10 : undefined, position: 'relative', WebkitTouchCallout: 'none' }}
    className={cn('select-none', isDragging && 'bg-sidebar rounded-md opacity-90 shadow-float ring-1 ring-border')}>{children}</div>
}

function SidebarBody({ onNav }: { onNav: () => void }) {
  const { ax, view, go, activeProjects, projectsFor, inCtx, ctx } = useApp()
  const kb = useKnowledge()
  const notesOwner = useNotesOwner(ax.apiOk)
  const plan = usePlan(!!notesOwner && ax.apiOk)
  const kbTodo = (kb || []).filter(e => e.status === 'suggested' || needsCheck(e)).length   // waiting for your OK
  const items = ax.current?.data.items || []
  const open = (f: (i: any) => boolean) => items.filter(i => !ax.isHandled(i.id) && inCtx(i) && f(i)).length
  const nowCount = useNow().count
  const lg = useContext(LargeCtx)     // the slide-in menu on phones also carries the actions the laptop has in its top bar
  const sugg = ax.projects.filter(p => p.status === 'suggested').length
  const archived = ax.projects.filter(p => p.status === 'archived').length
  const listening = useListening()
  const nav = (v: Parameters<typeof go>[0], anchor?: string) => { go(v, anchor); onNav() }
  return (
    <nav className="flex h-full flex-col gap-4 overflow-y-auto p-3">
      <div className="flex items-center gap-2.5 px-1.5 pt-1"><Brand size={28} /><span className="text-[15px] font-semibold tracking-[.22em] uppercase">Axella</span></div>
      <div className="space-y-0.5">
        <div className="ax-label px-2.5 pb-1">Your day</div>
        <NavItem icon={NowIcon} label="Today" count={nowCount} active={view.kind === 'today'} onClick={() => nav({ kind: 'today' })} />
        <NavItem icon={BriefingIcon} label="Briefing" tour="briefing" active={view.kind === 'briefing' && !view.focus} onClick={() => nav({ kind: 'briefing' })} />
        <NavItem icon={ListTodo} label="To do" tour="todo" count={ax.tasks.filter(t => t.status !== 'done' && taskInCtx(t, ctx)).length} active={view.kind === 'todo'} onClick={() => nav({ kind: 'todo' })} />
        <NavItem icon={CalendarDays} label="Calendar" count={open(i => i.section === 'cal')} active={view.kind === 'calendar' || (view.kind === 'briefing' && view.focus === 'cal')} onClick={() => nav({ kind: 'calendar' })} />
        {ax.apiOk && <NavItem icon={MeetingIcon} label="Meetings" active={view.kind === 'meetings' || view.kind === 'meeting'} onClick={() => nav({ kind: 'meetings' })} />}
        {ax.apiOk && <NavItem icon={TripsIcon} label="Trips" active={view.kind === 'trips'} onClick={() => nav({ kind: 'trips' })} />}
      </div>
      {lg && ax.apiOk && <div className="space-y-0.5">
        <div className="ax-label px-2.5 pb-1">Do</div>
        <NavItem icon={AskIcon} label="Ask Axella" onClick={() => { onNav(); openAsk() }} />
        <NavItem icon={MailPlus} label="New mail" onClick={() => { onNav(); openCompose() }} />
        <NavItem icon={listening ? Square : Headphones} label={listening ? 'Stop reading' : 'Listen to the briefing'} onClick={() => toggleListen()} />
      </div>}
      <div className="space-y-0.5">
        <div className="ax-label px-2.5 pb-1">Tidy</div>
        <NavItem icon={FolderInput} label="Mailbox" count={open(i => i.section === 'file')} active={view.kind === 'mailbox'} onClick={() => nav({ kind: 'mailbox' })} />
        <NavItem icon={Receipt} label="Receipts" active={view.kind === 'receipts'} onClick={() => nav({ kind: 'receipts' })} />
      </div>
      <div className="space-y-0.5">
        <div className="ax-label px-2.5 pb-1">Library</div>
        {ax.apiOk && <NavItem icon={SearchIcon} label="Search" active={view.kind === 'search'} onClick={() => nav({ kind: 'search' })} />}
        {ax.apiOk && <NavItem icon={UserCircle} label="Contacts" active={view.kind === 'contacts'} onClick={() => nav({ kind: 'contacts' })} />}
        {ax.apiOk && <NavItem icon={BriefingNavIcon} label="Topic briefs" active={view.kind === 'briefings'} onClick={() => nav({ kind: 'briefings' })} />}
        {ax.apiOk && <NavItem icon={KnowledgeIcon} label="Knowledge" count={kbTodo || undefined} active={view.kind === 'knowledge'} onClick={() => nav({ kind: 'knowledge' })} />}
        {ax.apiOk && notesOwner && <NavItem icon={NoteIcon} label="Notes" active={view.kind === 'notes'} onClick={() => nav({ kind: 'notes' })} tour="nav-notes" />}
        {ax.apiOk && <NavItem icon={BarChart3} label="Insights" active={view.kind === 'insights'} onClick={() => nav({ kind: 'insights' })} />}
        <NavItem icon={ArchiveIcon} label="Older digests" active={view.kind === 'archive'} onClick={() => nav({ kind: 'archive' })} />
      </div>
      <div className="space-y-0.5">
        <div className="flex items-center justify-between px-2.5 pb-1">
          <button className="ax-label hover:text-ink" onClick={() => nav({ kind: 'projects' })}>Projects</button>
          <button aria-label="New project" className="text-ink-3 hover:text-ink" onClick={() => nav({ kind: 'projects' })}><Plus className="size-4" /></button>
        </div>
        <SortableProjects projects={activeProjects} render={p => <div className="group/proj relative">
          <NavItem icon={FolderKanban} color={projColor(activeProjects, p.id)} label={stateOf(plan, p.id) === 'active' ? p.name
            : <span className="text-ink-3 flex items-center gap-2" data-nav-state={stateOf(plan, p.id)}><span className="min-w-0 flex-1 truncate">{p.name}</span>
              <span className="font-mono text-[10.5px] tracking-[0.06em] uppercase" style={{ color: STATE_COLOR[stateOf(plan, p.id)] }}>{stateOf(plan, p.id)}</span></span>}
            count={items.filter(i => !ax.isHandled(i.id) && projectsFor(i).some(x => x.id === p.id)).length}
            active={view.kind === 'project' && view.id === p.id} onClick={() => nav({ kind: 'project', id: p.id })} />
          {/* desktop: a quiet ⋯ on hover (phones use the project page's Archive button) */}
          {ax.apiOk && <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button aria-label={'More for ' + p.name} onPointerDown={e => e.stopPropagation()}
                className="bg-sidebar text-ink-3 hover:text-ink absolute inset-y-1 right-1 hidden w-7 items-center justify-center rounded-md opacity-0 group-hover/proj:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100 [@media(hover:hover)]:flex">
                <MoreHorizontal className="size-4" /></button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side="right">
              <DropdownMenuItem onSelect={() => nav({ kind: 'project', id: p.id })}><FolderKanban />Open</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => openArchive(p.id)}><ArchiveIcon />Archive…</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>}
        </div>} />
        <NavItem icon={FolderKanban} label="All projects" active={view.kind === 'projects'} onClick={() => nav({ kind: 'projects' })} />
        {archived > 0 && <NavItem icon={ArchiveIcon} label="Archived" count={archived} active={view.kind === 'project' && ax.projects.find(x => x.id === view.id)?.status === 'archived'}
          onClick={() => { go({ kind: 'projects' }); onNav(); setTimeout(() => document.getElementById('archived')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80) }} />}
        {sugg > 0 && <NavItem icon={Sparkles} label={<span>Suggested</span>} count={sugg} onClick={() => nav({ kind: 'projects' })} />}
      </div>
    </nav>
  )
}

/* ---------- digest picker: last 7 days grouped by day, older ones via the Archive view ---------- */
/* What kind of run a digest was, from its time (the default slots); anything else was an extra run (sweep / re-scan). */
/* The digest slots from Settings → Schedule (GET runs → config.digests): a digest is named after the slot it ran in
   ("Evening wrap" at 20:00), not after fixed times. Without them (offline, older API) the default times are used. */
type Slot = { label: string; time: string; days: number[]; enabled?: boolean; task?: string; worlds?: string[] }
let slotCache: Slot[] | null = null
function useDigestSlots(on: boolean) {
  const [slots, setSlots] = useState<Slot[] | null>(slotCache)
  useEffect(() => {
    if (!on || slotCache) return
    get<{ config?: { digests?: Slot[] } }>('runs').then(j => {
      const d = Array.isArray(j.config?.digests) ? j.config!.digests!.filter(x => x && typeof x.time === 'string' && /^\d{1,2}:\d{2}$/.test(x.time)) : null
      if (d) { slotCache = d; setSlots(d) }
    }).catch(() => { /* fall back to the default times */ })
  }, [on])
  return slots
}
const slotName = (l: string) => l.replace(/\s+digest$/i, '').replace(/^Sunday week-ahead$/i, 'Week ahead').trim() || l
/* The schedule slot a digest came from: the latest slot at or before the time in its name – a run takes up to
   30 min, and its file is named when it is written (07:30 slot → 07:52). */
function slotOf(n: string, slots?: Slot[] | null) {
  const d = parseName(n).date
  if (!d || !slots?.length) return null
  const m = d.getHours() * 60 + d.getMinutes(), wd = (d.getDay() + 6) % 7      // the scheduler counts Monday = 0
  const cand = slots.map(s => { const [h, mm] = s.time.split(':').map(Number); return { s, late: m - (h * 60 + mm) } })
    .filter(x => x.late >= -10 && x.late <= 50)
  const pick = (l: typeof cand) => l.sort((a, b) => Math.abs(a.late) - Math.abs(b.late))[0]?.s
  return pick(cand.filter(x => !Array.isArray(x.s.days) || x.s.days.includes(wd))) || pick(cand) || null
}
function runKind(n: string, slots?: Slot[] | null) {
  const d = parseName(n).date
  if (!d) return ''
  const m = d.getHours() * 60 + d.getMinutes(), near = (h: number, mm: number) => Math.abs(m - (h * 60 + mm)) <= 15
  if (/-week\b/.test(n)) return 'Week ahead'
  const s = slotOf(n, slots)
  if (s) return slotName(s.label)
  if (d.getDay() === 0 && near(20, 30)) return 'Week ahead'
  if (near(7, 30)) return 'Morning'
  if (near(11, 30)) return 'Midday'
  if (near(15, 30)) return 'Afternoon'
  return 'Extra run'
}
const hhmm = (n: string) => { const d = parseName(n).date; return d ? d.toTimeString().slice(0, 5) : '' }

/* Digest picker: last 7 days grouped by day, older ones via the Archive view (design system: quiet list, mono times) */
function DigestPicker() {
  const { ax, go } = useApp()
  const from = new Date(); from.setDate(from.getDate() - 6)
  const fromKey = isoDate(from)
  const recent = ax.names.filter(n => isRegular(n) && dayKey(n) >= fromKey)
  const groups: [string, string[]][] = []
  recent.forEach(n => { const k = dayKey(n), g = groups.find(x => x[0] === k); g ? g[1].push(n) : groups.push([k, [n]]) })
  const cur = ax.current?.name
  const curDay = cur ? dayLabel(dayKey(cur)) : ''
  const slots = useDigestSlots(ax.apiOk)
  const [catchUp, setCatchUp] = useState(false)
  return <><DropdownMenu>
    <DropdownMenuTrigger asChild>
      <button aria-label="Choose digest" className="bg-card hover:border-line-strong data-[state=open]:border-line-strong inline-flex h-10 min-w-0 flex-1 items-center gap-2 rounded-md border px-3 text-left transition-colors sm:h-9 sm:max-w-[320px] sm:flex-none">
        {cur && <span className="text-ink-3 shrink-0 text-[13px] max-sm:hidden lg:max-xl:hidden">Digest</span>}
        <span className="min-w-0 shrink-0 text-[15px] font-medium whitespace-nowrap sm:text-sm">{cur ? <><span className="max-sm:hidden">{curDay} </span>{hhmm(cur)}</> : 'Digest'}</span>
        {cur && <span className="text-ink-3 truncate font-mono text-[12px] max-sm:hidden lg:max-xl:hidden">{runKind(cur, slots)}</span>}
        <ChevronDown className="text-ink-3 ml-auto size-4 shrink-0" />
      </button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="start" className="max-h-[min(70vh,560px)] w-[min(320px,calc(100vw-32px))] overflow-y-auto p-1">
      {cur && !recent.includes(cur) && <>
        <div className="ax-label px-2.5 pt-2 pb-1">Selected</div>
        <PickRow n={cur} on day={dayLabel(dayKey(cur))} slots={slots} />
      </>}
      {groups.map(([k, list]) => <div key={k}>
        <div className="ax-label flex items-center gap-2 px-2.5 pt-2.5 pb-1">{dayLabel(k)}<span className="bg-line h-px flex-1" /></div>
        {list.map(n => <PickRow key={n} n={n} on={n === cur} slots={slots} onPick={() => ax.select(n)} />)}
      </div>)}
      <DropdownMenuSeparator />
      <DropdownMenuItem onSelect={() => go({ kind: 'archive' })}><ArchiveIcon />Older digests<ChevronRight className="text-ink-3 ml-auto" /></DropdownMenuItem>
      {ax.apiOk && <DropdownMenuItem onSelect={() => setTimeout(() => setCatchUp(true), 100)}><Palmtree />Catch me up since…</DropdownMenuItem>}
    </DropdownMenuContent>
  </DropdownMenu>
  <CatchUpDialog open={catchUp} onClose={() => setCatchUp(false)} /></>
}
function PickRow({ n, on, day, onPick, slots }: { n: string; on: boolean; day?: string; onPick?: () => void; slots?: Slot[] | null }) {
  const kind = runKind(n, slots)
  const w = slotOf(n, slots)?.worlds
  const scope = w && w.length === 1 ? (w[0] === 'work' ? 'Work' : 'Private') : ''
  return <DropdownMenuItem onSelect={onPick} className={cn('relative min-h-10 gap-3 py-2 sm:min-h-8 sm:py-1.5', on && 'bg-fjord-soft text-fjord focus:bg-fjord-soft before:bg-fjord before:absolute before:inset-y-1.5 before:left-0 before:w-0.5')}>
    <span className="w-11 shrink-0 font-mono text-[13px] tabular-nums">{hhmm(n)}</span>
    <span className={cn('min-w-0 flex-1 truncate', !on && 'text-ink-2', kind === 'Extra run' && !on && 'text-ink-3')}>{day ? day + ' · ' : ''}{kind}</span>
    {scope && <span className="text-ink-3 shrink-0 font-mono text-[11px]" data-pick-scope="">{scope}</span>}
    {on && <Check className="!size-4" />}
  </DropdownMenuItem>
}

/* ---------- account menu: the system pages live here, the sidebar is for content ---------- */
function SweepConfirm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const sweep = useSweep()
  const { ax } = useApp()
  const [busy, setBusy] = useState(false)
  return <Dialog open={open} onOpenChange={o => !o && onClose()}>
    <DialogContent className="sm:w-[min(460px,92vw)]">
      <div className="flex gap-3 px-5 pt-5 pb-2 pr-12">
        <span className="bg-fjord-soft text-fjord flex size-10 shrink-0 items-center justify-center rounded-md"><Radar className="size-5" /></span>
        <div><DialogTitle className="text-lg leading-snug font-semibold">Run a sweep now?</DialogTitle>
          <p className="text-ink-2 mt-1 text-sm">Axella reads every mailbox and chat now and writes a full digest, outside the schedule – also on paused days. Nothing is sent.</p>
          <p className="text-ink-3 mt-2 text-[13px]">{ax.schedule?.wait || 'You get a push when it’s ready.'}</p></div>
      </div>
      <div className="flex justify-end gap-2 border-t px-5 py-3">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button disabled={busy} onClick={async () => { setBusy(true); await sweep.request(); setBusy(false); onClose() }}><Radar />Run sweep now</Button>
      </div>
    </DialogContent>
  </Dialog>
}

/* Inbox re-scan: one digest run that looks at EVERYTHING still in the mail inboxes (setup/local-tasks/inbox-rescan.md) */
function RescanConfirm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { ax } = useApp()
  const [busy, setBusy] = useState(false)
  async function go() {
    setBusy(true)
    try {
      const r: any = await ax.act('run_now', { task: 'inbox-rescan' }, [])
      toast(r?.result === 'already queued' ? 'An inbox re-scan is already on its way' : 'Inbox re-scan queued – you get a push when the digest is ready')
      onClose()
    } catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(false) }
  }
  return <Dialog open={open} onOpenChange={o => !o && onClose()}>
    <DialogContent className="sm:w-[min(480px,92vw)]">
      <div className="flex gap-3 px-5 pt-5 pb-2 pr-12">
        <span className="bg-fjord-soft text-fjord flex size-10 shrink-0 items-center justify-center rounded-md"><Mail className="size-5" /></span>
        <div><DialogTitle className="text-lg leading-snug font-semibold">Re-scan your inboxes?</DialogTitle>
          <p className="text-ink-2 mt-1 text-sm">Axella looks at every mail still in your inboxes – however old – and writes a full digest: replies drafted for what still needs an answer, a folder for what's done, newsletters flagged.</p>
          <p className="text-ink-3 mt-2 text-[13px]">Up to 150 mails per mailbox · 10–30 minutes · nothing is moved or sent – you file from the digest (“File all” per folder).</p></div>
      </div>
      <div className="flex justify-end gap-2 border-t px-5 py-3">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button disabled={busy} onClick={go}>{busy ? <RotateCw className="animate-spin" /> : <Mail />}Re-scan inboxes</Button>
      </div>
    </DialogContent>
  </Dialog>
}

function AccountMenu({ c, compact }: { c: Controls; compact?: boolean }) {
  const { ax, view, go } = useApp()
  const sweep = useSweep()
  const [confirm, setConfirm] = useState(false)
  const [rescan, setRescan] = useState(false)
  const paused = ax.schedule?.status.reason
  const health = useStatusShort(ax.apiOk)
  const sick = !!health && health.level !== 'ok'
  return <>
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button aria-label="Account and system" data-tour="account" className={cn('bg-card text-ink-2 hover:text-ink hover:border-line-strong inline-flex h-9 items-center gap-1.5 rounded-md border px-2.5 text-[13px] transition-colors',
          compact && 'w-9 justify-center px-0')}>
          <span className="relative inline-flex"><UserCircle className="size-[18px]" />
            {sick && <span className={cn('absolute -top-0.5 -right-0.5 size-2 rounded-full ring-2 ring-[var(--ax-card,white)]', health!.level === 'down' ? 'bg-danger' : 'bg-dawn')} aria-label="Something needs you" data-status-dot="" />}</span>
          {!compact && c.who && <span className="hidden max-w-[220px] truncate md:inline">{c.who}</span>}
          {!compact && <ChevronDown className="size-4" />}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        {c.who && <div className="text-ink-3 px-2.5 pt-1.5 pb-2 text-xs">Signed in via Tailscale as<div className="text-ink truncate text-[13px] font-medium">{c.who}</div></div>}
        {c.who && <DropdownMenuSeparator />}
        <DropdownMenuItem onSelect={() => openGuide()}><GuideIcon />Getting started</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setTimeout(openReport, 150)}><ReportIcon />Report a problem<span className="text-ink-3 ml-auto text-xs max-sm:hidden">{/Mac/.test(navigator.platform) ? '⌘B' : 'Ctrl+B'}</span></DropdownMenuItem>
        <DropdownMenuItem onSelect={() => go({ kind: 'settings' })} className={cn(view.kind === 'settings' && 'text-fjord')}>
          <SettingsIcon />Settings{paused && <span className="text-ink-3 ml-auto text-xs">paused</span>}</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => go({ kind: 'status' })} className={cn(view.kind === 'status' && 'text-fjord')}><ShieldCheck /><span className="whitespace-nowrap">System status</span>
          {health && <span className={cn('ml-auto flex min-w-0 items-center gap-1 truncate text-xs', sick ? (health.level === 'down' ? 'text-danger' : 'text-dawn') : 'text-ink-3')} data-status-short="">
            {sick && <span className={cn('size-1.5 shrink-0 rounded-full', health.level === 'down' ? 'bg-danger' : 'bg-dawn')} />}<span className="truncate">{health.short}</span></span>}</DropdownMenuItem>
        {ax.apiOk && <DropdownMenuItem onSelect={() => go({ kind: 'activity' })} className={cn(view.kind === 'activity' && 'text-fjord')}><ListTodo />Activity log</DropdownMenuItem>}
        {ax.apiOk && <DropdownMenuItem onSelect={() => go({ kind: 'runs' })} className={cn(view.kind === 'runs' && 'text-fjord')}><Activity />Runs and logs</DropdownMenuItem>}
        {ax.apiOk && <DropdownMenuItem onSelect={() => sweep.pending ? go({ kind: 'runs' }) : setConfirm(true)}>
          <Radar />{sweep.pending ? 'Sweep requested…' : 'Run sweep now'}</DropdownMenuItem>}
        {ax.apiOk && <DropdownMenuItem onSelect={() => setRescan(true)}><Mail />Re-scan inboxes…</DropdownMenuItem>}
        {compact && <>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={e => { e.preventDefault(); ax.reload() }}><RotateCw className={cn(ax.loading && 'animate-spin')} />Refresh</DropdownMenuItem>
          {c.hasSW && <DropdownMenuItem onSelect={c.ring} className={cn(c.on && 'text-fjord')}>{c.on ? <BellRing /> : <Bell />}{c.on ? 'Notifications on · send test' : 'Turn on notifications'}</DropdownMenuItem>}
          <div className="px-2.5 pt-2 pb-1.5">
            <div className="ax-label mb-1.5">Theme</div>
            <div role="radiogroup" aria-label="Theme" className="bg-bg-2 grid grid-cols-3 gap-0.5 rounded-md p-0.5">
              {([['light', 'Light', ThemeLight], ['dark', 'Dark', ThemeDark], ['auto', 'System', SunMoon]] as const).map(([v, l, I]) =>
                <button key={v} role="radio" aria-checked={c.theme === v} onClick={() => c.setTheme(v)}
                  className={cn('flex h-9 items-center justify-center gap-1.5 rounded-sm text-[13px] transition-colors [&_svg]:size-4',
                    c.theme === v ? 'bg-surface text-ink ring-line font-medium shadow-sm ring-1' : 'text-ink-3 hover:text-ink')}><I />{l}</button>)}
            </div>
          </div>
        </>}
      </DropdownMenuContent>
    </DropdownMenu>
    <SweepConfirm open={confirm} onClose={() => setConfirm(false)} />
    <RescanConfirm open={rescan} onClose={() => setRescan(false)} />
  </>
}

/* Hover label for the top-bar buttons (design system: inverse chip, mono-free, appears after a short pause; never on touch) */
function Tip({ text, children, align = 'center' }: { text: string; children: ReactNode; align?: 'center' | 'right' }) {
  return <span className="group/tip relative inline-flex">
    {children}
    <span role="tooltip" className={cn('bg-surface-inverse text-on-inverse pointer-events-none absolute top-full z-50 mt-1.5 whitespace-nowrap rounded-sm px-2 py-1 text-xs opacity-0 shadow-float transition-opacity duration-[120ms]',
      '[@media(hover:hover)]:group-hover/tip:opacity-100 [@media(hover:hover)]:group-hover/tip:delay-500 group-has-[:focus-visible]/tip:opacity-100 group-has-[[data-state=open]]/tip:!opacity-0',
      align === 'right' ? 'right-0' : 'left-1/2 -translate-x-1/2')}>{text}</span>
  </span>
}
const THEME_NAME = { auto: 'System', light: 'Light', dark: 'Dark' } as const

const iconBtn = 'text-ink-2 hover:text-ink hover:border-line-strong inline-flex size-9 items-center justify-center rounded-md border bg-card transition-colors [&_svg]:size-[18px]'

/* ---------- top bar ---------- */
/* "+ New": the one place to start something – mail, task, reminder, knowledge (also on the phone) */
function NewMenu({ compact = false }: { compact?: boolean }) {
  const { go, ax } = useApp()
  const notesOwner = useNotesOwner(ax.apiOk)
  return <DropdownMenu>
    <DropdownMenuTrigger asChild>{compact
      ? <Button className="size-10 p-0" aria-label="New" data-tour="new"><Plus className="size-5" /></Button>
      : <Button className="h-9 gap-1.5 px-3" data-tour="new"><Plus />New</Button>}</DropdownMenuTrigger>
    <DropdownMenuContent align="end" className="w-52">
      <DropdownMenuItem onSelect={() => openCompose()}><MailPlus />New mail</DropdownMenuItem>
      <DropdownMenuItem onSelect={() => setTimeout(openNewMessage, 120)}><MessageCircle />Message…<span className="text-ink-3 ml-auto text-xs">Messages, WhatsApp, Signal</span></DropdownMenuItem>
      <DropdownMenuItem onSelect={() => go({ kind: 'todo' })}><ListTodo />Task</DropdownMenuItem>
      {ax.apiOk && <DropdownMenuItem onSelect={() => setTimeout(() => openNewPrep(), 120)}><MeetingIcon />Meeting prep</DropdownMenuItem>}
      <DropdownMenuItem onSelect={() => go({ kind: 'settings' }, 'reminders')}><Recurring />Recurring reminder</DropdownMenuItem>
      <DropdownMenuItem onSelect={() => openKnowledge({})}><KnowledgeIcon />Knowledge entry</DropdownMenuItem>
      {notesOwner && <DropdownMenuItem onSelect={() => openNote({})} data-new-note=""><NoteIcon />Note<span className="text-ink-3 ml-auto text-xs max-sm:hidden">{NOTE_KEY}</span></DropdownMenuItem>}
    </DropdownMenuContent>
  </DropdownMenu>
}

function TopBar({ onMenu, ctx, setCtx, c }: { onMenu: () => void; ctx: CtxFilter; setCtx: (c: CtxFilter) => void; c: Controls }) {
  const { ax, view, go } = useApp()
  return (
    <div className="flex h-14 items-center gap-2 sm:h-12">
      <span className="lg:hidden select-none" {...longPress(openReport)} title="Long-press: report a problem"><Brand /></span>
      {(view.kind === 'today' || view.kind === 'briefing') && ax.names.length > 0 &&
        <span className={cn('flex min-w-0', view.kind === 'today' && 'max-lg:hidden')}><DigestPicker /></span>}
      <div className="ml-auto flex shrink-0 items-center gap-2">
        <ToggleGroup type="single" value={ctx} onValueChange={(v: string) => v && setCtx(v as CtxFilter)} aria-label="Filter" data-tour="ctx" className="max-lg:h-10 max-lg:[&>button]:h-8">
          <ToggleGroupItem value="all">All</ToggleGroupItem>
          <ToggleGroupItem value="work" aria-label="Work"><Briefcase className="xl:hidden" /><span className="max-xl:hidden">Work</span></ToggleGroupItem>
          <ToggleGroupItem value="private" aria-label="Private"><Home className="xl:hidden" /><span className="max-xl:hidden">Private</span></ToggleGroupItem>
        </ToggleGroup>
        <div className="hidden items-center gap-2 lg:flex">
          {ax.apiOk && <Tip text="Search mail and digests ( / )"><button className={cn(iconBtn, view.kind === 'search' && 'text-fjord')} onClick={() => go({ kind: 'search' })} aria-label="Search" data-tour="search"><SearchIcon /></button></Tip>}
          {ax.apiOk && <Tip text="Ask Axella"><button className={iconBtn} onClick={() => openAsk()} aria-label="Ask Axella" data-tour="ask"><AskIcon /></button></Tip>}
          {ax.apiOk && <Tip text="Listen to the briefing"><button className={iconBtn} onClick={() => toggleListen()} aria-label="Listen to the briefing" data-tour="listen"><Headphones /></button></Tip>}
          <Tip text="Refresh – check for a new digest"><button className={iconBtn} onClick={() => ax.reload()} aria-label="Refresh"><RotateCw className={cn(ax.loading && 'animate-spin')} /></button></Tip>
          <Tip text={`Theme: ${THEME_NAME[c.theme]} – click to switch`}><button className={iconBtn} onClick={c.nextTheme} aria-label={`Theme: ${THEME_NAME[c.theme]}`}><c.ThemeI /></button></Tip>
          {c.hasSW && <Tip text={c.on ? 'Notifications on – click to send a test' : 'Turn on notifications for urgent mail'}><button className={cn(iconBtn, c.on && 'text-fjord')} aria-label={c.on ? 'Notifications on' : 'Turn on notifications'} onClick={c.ring}>{c.on ? <BellRing /> : <Bell />}</button></Tip>}
          {ax.apiOk && <NewMenu />}
          <Tip text="Settings, runs, sweep and re-scan" align="right"><AccountMenu c={c} /></Tip>
        </div>
        {ax.apiOk && view.kind !== 'briefing' && <button className={cn(iconBtn, 'size-10 lg:hidden', view.kind === 'search' && 'text-fjord')} onClick={() => go({ kind: 'search' })} aria-label="Search" data-tour="search"><SearchIcon className="size-5" /></button>}
        {ax.apiOk && <span className="lg:hidden"><NewMenu compact /></span>}
        <span className="lg:hidden"><AccountMenu c={c} compact /></span>
      </div>
    </div>
  )
}

/* ---------- phone/tablet: bottom tab bar (Now · Briefing · Ask · To do · More) ---------- */
function TabBar({ onMore }: { onMore: () => void }) {
  const { ax, view, go } = useApp()
  const n = useNow().count
  const tab = (on: boolean) => cn('relative flex flex-1 flex-col items-center gap-1 pt-2 pb-1 text-[11px] transition-colors', on ? 'text-fjord font-semibold' : 'text-ink-3')
  return <nav aria-label="Tabs" className="bg-background/95 fixed inset-x-0 bottom-0 z-20 flex border-t px-1 pb-[env(safe-area-inset-bottom)] backdrop-blur-md lg:hidden">
    <button className={tab(view.kind === 'today')} onClick={() => go({ kind: 'today' })} aria-current={view.kind === 'today' ? 'page' : undefined}>
      <span className="relative"><NowIcon className="size-[22px]" />{n > 0 && <span className="bg-fjord text-on-fjord absolute -top-1 -right-3 rounded-[2px] px-1 font-mono text-[10px] leading-4">{n}</span>}</span>Today</button>
    <button className={tab(view.kind === 'briefing')} data-tour="briefing" onClick={() => go({ kind: 'briefing' })} aria-current={view.kind === 'briefing' ? 'page' : undefined}><BriefingIcon className="size-[22px]" />Briefing</button>
    {ax.apiOk && <button className={tab(false)} data-tour="ask" onClick={() => openAsk()}><AskIcon className="size-[22px]" />Ask</button>}
    <button className={tab(view.kind === 'todo')} data-tour="todo" onClick={() => go({ kind: 'todo' })} aria-current={view.kind === 'todo' ? 'page' : undefined}><ListTodo className="size-[22px]" />To do</button>
    <button className={tab(false)} data-tour="menu" onClick={onMore}><MoreHorizontal className="size-[22px]" />More</button>
  </nav>
}

/* swipe right anywhere opens the menu, swipe left closes it (phones/tablets) */
function useSwipe(open: boolean, setOpen: (o: boolean) => void) {
  useEffect(() => {
    let x = 0, y = 0, t = 0, ok = false
    const start = (e: TouchEvent) => {
      const el = e.target as HTMLElement
      ok = e.touches.length === 1 && !el.closest('input,textarea,select,[role=menu],[data-noswipe]') && innerWidth < 1024
      x = e.touches[0].clientX; y = e.touches[0].clientY; t = Date.now()
    }
    const end = (e: TouchEvent) => {
      if (!ok) return
      const dx = e.changedTouches[0].clientX - x, dy = e.changedTouches[0].clientY - y
      if (Date.now() - t > 600 || Math.abs(dx) < 60 || Math.abs(dy) > Math.abs(dx) * 0.6) return
      if (dx > 0 && !open && !document.querySelector('[role=menu]')) setOpen(true)
      if (dx < 0 && open) setOpen(false)
    }
    document.addEventListener('touchstart', start, { passive: true })
    document.addEventListener('touchend', end, { passive: true })
    return () => { document.removeEventListener('touchstart', start); document.removeEventListener('touchend', end) }
  }, [open, setOpen])
}

export function Shell({ children, ctx, setCtx }: { children: ReactNode; ctx: CtxFilter; setCtx: (c: CtxFilter) => void }) {
  const { view, go } = useApp()
  const [open, setOpen] = useState(false)
  const c = useControls()
  useSwipe(open, setOpen)
  useReportShortcut()                                   // Cmd/Ctrl+B anywhere: Report a problem
  useNoteShortcut()                                     // Cmd/Ctrl+J anywhere: a new note (owner only)
  useEffect(() => {                                     // "/" anywhere (not while typing) opens Search
    const k = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey || el.closest('input,textarea,select,[contenteditable=true],[role=dialog]')) return
      e.preventDefault(); go({ kind: 'search' })
    }
    addEventListener('keydown', k); return () => removeEventListener('keydown', k)
  }, [go])
  const head = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = head.current; if (!el) return
    const ro = new ResizeObserver(() => document.documentElement.style.setProperty('--top-h', el.offsetHeight + 'px'))
    ro.observe(el); return () => ro.disconnect()
  }, [])
  return (
    <div className="min-h-dvh">
      <aside data-tour="menu" className="bg-sidebar pt-safe pb-safe fixed inset-y-0 left-0 z-30 hidden w-[248px] border-r lg:block"><SidebarBody onNav={() => {}} /></aside>
      <ComposeHost />
      <NewMessageHost />
      <MailReaderHost />
      <NewPrepHost />
      <InviteHost />
      <OutboxBar />
      <TaskFromHost />
      <ArchiveHost />
      <KnowledgeHost />
      <NoteHost />
      <GuideHost />
      <TourHost />
      <ReportHost />
      <AskHost />
      <Sheet open={open} onOpenChange={setOpen}><SheetContent><SheetTitle className="sr-only">Menu</SheetTitle><LargeCtx.Provider value={true}><SidebarBody onNav={() => setOpen(false)} /></LargeCtx.Provider></SheetContent></Sheet>
      <div className="lg:pl-[248px]">
        <div ref={head} className="bg-background/90 pt-safe sticky top-0 z-20 border-b backdrop-blur-md">
          <div className="px-4 lg:px-6"><TopBar onMenu={() => setOpen(true)} ctx={ctx} setCtx={setCtx} c={c} />
          </div>
        </div>
        <main className="px-4 pt-4 pb-[calc(5.5rem+env(safe-area-inset-bottom))] lg:px-6 lg:pb-20"><RevealOnArrival>{children}</RevealOnArrival></main>
        <ArrivalNote />
        <TabBar onMore={() => setOpen(true)} />
        <ConnectionBar />
        <ListenBar />
        <footer className="bg-background/90 text-ink-3 pb-safe fixed max-lg:hidden inset-x-0 bottom-0 z-20 border-t text-xs backdrop-blur-md lg:left-[248px]">
          <div className="flex items-center justify-end gap-2 px-4 py-2 lg:px-6"><Rune size={12} className="text-ink-3" /><span className="tracking-wide">Your attention, on your terms.</span></div>
        </footer>
      </div>
    </div>
  )
}
