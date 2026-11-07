import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { Toaster } from 'sonner'
import { useAxella } from '@/hooks/useAxella'
import { App as AppContext, type AppCtx, type CtxFilter, type View, type SettingsPage } from '@/lib/app'
import { ctxOf } from '@/lib/data'
import { projectsOf } from '@/lib/projects'
import { setTitle } from '@/lib/title'
import { profileVersion } from '@/lib/profile'
import { track } from '@/lib/report'
import { store } from '@/lib/utils'
import { ContactsView } from '@/components/Contacts'
import { CalendarView } from '@/components/Calendar'
import { ActivityView } from '@/components/Activity'
import { Shell } from '@/components/Shell'
import { TodayView } from '@/components/Today'
import { ProjectView, ProjectsOverview } from '@/components/Projects'
import { ArchiveView } from '@/components/Archive'
import { SettingsView } from '@/components/Settings'
import { ReceiptsView } from '@/components/Receipts'
import { NewslettersView } from '@/components/Newsletters'
import { RunsView } from '@/components/Runs'
import { StatusView } from '@/components/Status'
import { InsightsView } from '@/components/Insights'
import { KnowledgeView } from '@/components/Knowledge'
import { NotesView } from '@/components/Notes'
import { CleanupView } from '@/components/Cleanup'
import { NowView } from '@/components/Now'
import { MailboxView, TodoView } from '@/components/Hubs'
import { SearchView } from '@/components/Search'
import { BriefingsView } from '@/components/Briefings'
import { MeetingPrepView, MeetingsView } from '@/components/Meetings'
import { PersonView } from '@/components/People'
import { TripsView } from '@/components/Trips'

const SETTINGS_ANCHOR: Record<string, SettingsPage> = { reminders: 'reminders', callcfg: 'calls', privacy: 'privacy', reports: 'reports',
  recipients: 'bookkeeping', vac: 'schedule', days: 'schedule', sched: 'schedule', sweep: 'schedule', ooo: 'away', cleanupcfg: 'mailbox', look: 'appearance' }

function viewFromUrl(): View {
  const q = new URLSearchParams(location.search)
  if (q.get('p')) return { kind: 'project', id: q.get('p')! }
  if (q.get('v') === 'projects') return { kind: 'projects' }
  if (q.get('v') === 'archive') return { kind: 'archive' }
  if (q.get('v') === 'settings') return { kind: 'settings', page: (q.get('s') || undefined) as SettingsPage | undefined }
  if (q.get('v') === 'receipts' || q.get('v') === 'subscriptions') return { kind: 'receipts' }
  if (q.get('v') === 'briefing') return q.get('f') === 'cal' ? { kind: 'briefing', focus: 'cal' } : { kind: 'briefing' }
  if (q.get('v') === 'todo') return { kind: 'todo', tab: q.get('t') === 'waiting' ? 'waiting' : 'tasks' }
  if (q.get('v') === 'mailbox') return { kind: 'mailbox', tab: (['filing', 'newsletters', 'cleanup'] as const).find(t => t === q.get('t')) || 'filing' }
  if (q.get('v') === 'newsletters') return { kind: 'mailbox', tab: 'newsletters' }    // old links
  if (q.get('v') === 'cleanup') return { kind: 'mailbox', tab: 'cleanup' }
  if (q.get('v') === 'runs') return { kind: 'runs' }
  if (q.get('v') === 'status') return { kind: 'status' }
  if (q.get('v') === 'insights') return { kind: 'insights' }
  if (q.get('v') === 'knowledge') return { kind: 'knowledge' }
  if (q.get('v') === 'notes') return { kind: 'notes' }
  if (q.get('v') === 'search') return { kind: 'search', q: q.get('q') || '' }
  if (q.get('v') === 'contacts') return { kind: 'contacts' }
  if (q.get('v') === 'calendar') return { kind: 'calendar' }
  if (q.get('v') === 'activity') return { kind: 'activity' }
  if (q.get('v') === 'briefings') return { kind: 'briefings', id: q.get('b') || undefined }
  if (q.get('v') === 'meetings') return { kind: 'meetings' }
  if (q.get('v') === 'trips') return { kind: 'trips' }
  if (q.get('v') === 'meeting' && q.get('m')) return { kind: 'meeting', id: q.get('m')! }
  if (q.get('v') === 'person' && q.get('c')) return { kind: 'person', id: q.get('c')! }
  return { kind: 'today' }
}

function useDark() {
  const [d, setD] = useState(() => document.documentElement.classList.contains('dark'))
  useEffect(() => { const o = new MutationObserver(() => setD(document.documentElement.classList.contains('dark'))); o.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] }); return () => o.disconnect() }, [])
  return d
}

export default function App() {
  const dark = useDark()
  const ax = useAxella()
  // launch splash (index.html) goes once the first digest is in – or on an error, so it never hides a problem
  useEffect(() => { if (!ax.loading || ax.error) (window as any).__axSplashDone?.() }, [ax.loading, ax.error])
  const [ctx, setCtxState] = useState<CtxFilter>(() => store.get('axella-ctx', 'all') as CtxFilter)
  const [view, setView] = useState<View>(viewFromUrl)
  // opened with a focus in the URL (e.g. Calendar after a reload): scroll there once the digest has rendered
  useEffect(() => {
    if (view.kind !== 'briefing' || !view.focus) return
    const f = view.focus
    const ts = [700, 1500, 2500].map(ms => setTimeout(() => { const el = document.getElementById('sec-' + f); if (el && Math.abs(el.getBoundingClientRect().top) > 80) el.scrollIntoView({ block: 'start' }) }, ms))
    return () => ts.forEach(clearTimeout)
  }, [])   // eslint-disable-line react-hooks/exhaustive-deps
  const setCtx = (c: CtxFilter) => { store.set('axella-ctx', c); setCtxState(c) }

  const go = useCallback((v0: View, anchor?: string) => {
    track('open_route', v0.kind)                        // for Report a problem: the route name, nothing else
    // the old Newsletters and Cleanup pages now live as tabs of Mailbox
    let v: View = v0.kind === 'newsletters' ? { kind: 'mailbox', tab: 'newsletters' } : v0.kind === 'cleanup' ? { kind: 'mailbox', tab: 'cleanup' } : v0
    // Settings is an overview with one page per area: old links to a card ("reminders", "callcfg" …) open its page
    if (v.kind === 'settings' && !v.page && anchor && SETTINGS_ANCHOR[anchor]) { v = { kind: 'settings', page: SETTINGS_ANCHOR[anchor] }; anchor = undefined }
    setView(v); window.scrollTo({ top: 0 })
    // the target card may only appear once the view has rendered and its data settled: try again a few times
    if (anchor) [120, 450, 1000].forEach(ms => setTimeout(() => {
      const el = document.getElementById('sec-' + anchor)
      if (el && Math.abs(el.getBoundingClientRect().top) > 80) el.scrollIntoView({ behavior: ms === 120 ? 'smooth' : 'auto', block: 'start' })
    }, ms))
    const u = new URL(location.href); u.searchParams.delete('p'); u.searchParams.delete('v'); u.searchParams.delete('t'); u.searchParams.delete('f'); u.searchParams.delete('q'); u.searchParams.delete('b'); u.searchParams.delete('s'); u.searchParams.delete('m'); u.searchParams.delete('c')
    if (v.kind === 'settings' && v.page) u.searchParams.set('s', v.page)
    if (v.kind === 'project') u.searchParams.set('p', v.id)
    if (v.kind === 'briefing') { u.searchParams.set('v', 'briefing'); if (v.focus) u.searchParams.set('f', v.focus) }
    if (v.kind === 'todo') { u.searchParams.set('v', 'todo'); if (v.tab === 'waiting') u.searchParams.set('t', 'waiting') }
    if (v.kind === 'mailbox') { u.searchParams.set('v', 'mailbox'); u.searchParams.set('t', v.tab || 'filing') }
    if (v.kind === 'briefings') { u.searchParams.set('v', 'briefings'); if (v.id) u.searchParams.set('b', v.id) }
    if (v.kind === 'meetings') u.searchParams.set('v', 'meetings')
    if (v.kind === 'trips') u.searchParams.set('v', 'trips')
    if (v.kind === 'meeting') { u.searchParams.set('v', 'meeting'); u.searchParams.set('m', v.id) }
    if (v.kind === 'person') { u.searchParams.set('v', 'person'); u.searchParams.set('c', v.id) }
    if (v.kind === 'search') { u.searchParams.set('v', 'search'); if (v.q) u.searchParams.set('q', v.q) }
    if (v.kind === 'projects' || v.kind === 'archive' || v.kind === 'settings' || v.kind === 'receipts' || v.kind === 'runs' || v.kind === 'status' || v.kind === 'insights' || v.kind === 'knowledge' || v.kind === 'notes' || v.kind === 'contacts' || v.kind === 'calendar' || v.kind === 'activity') u.searchParams.set('v', v.kind)
    history.pushState(null, '', u)
  }, [])
  useEffect(() => { const f = () => setView(viewFromUrl()); addEventListener('popstate', f); return () => removeEventListener('popstate', f) }, [])

  const activeProjects = useMemo(() => ax.projects.filter(p => p.status === 'active')
    .sort((a, b) => (a.order ?? 999) - (b.order ?? 999) || (a.created || '').localeCompare(b.created || '')), [ax.projects])
  const value: AppCtx = {
    ax, ctx, view, go, activeProjects,
    inCtx: x => ctx === 'all' || ctxOf(x, ax.overrides) === ctx,
    projectsFor: it => projectsOf(it, ax.projects, ctxOf(it, ax.overrides)),
  }

  // tab title always counts everything, regardless of the Work/Private filter
  useEffect(() => {
    if (!ax.current || !ax.stateReady) return       // until Done/snoozed is known the numbers would be too high
    const items = ax.current.data.items, open = (s: string) => items.filter(i => i.section === s && !ax.isHandled(i.id)).length
    const calls = ax.calls.filter(c => !ax.isHandled(c.id))
    // the same things Today counts: replies, calls, overdue waiting, and tasks due today or overdue
    const today = new Date().toLocaleDateString('sv-SE')
    const tasks = ax.tasks.filter(t => t.status !== 'done' && t.due && t.due <= today).length
    const waitOver = items.filter(i => i.section === 'wait' && i.overdue && !ax.isHandled(i.id)).length
    setTitle(open('p0') + open('p1') + open('p2') + calls.length + tasks + waitOver,
      open('p0') + calls.filter(c => c.priority === 'p0').length, ax.current.meta.date)
  }, [ax.current, ax.state, ax.calls, ax.tasks, ax.isHandled, ax.stateReady])

  return (
    <AppContext.Provider value={value}>
      <Shell ctx={ctx} setCtx={setCtx}>
        {!ax.profileReady ? null : <Fragment key={profileVersion()}>{view.kind === 'today' ? <NowView /> : view.kind === 'briefing' ? <TodayView /> : view.kind === 'todo' ? <TodoView key={view.only || 'all'} tab={view.tab || 'tasks'} only={view.only} /> : view.kind === 'mailbox' ? <MailboxView tab={view.tab || 'filing'} /> : view.kind === 'projects' ? <ProjectsOverview /> : view.kind === 'archive' ? <ArchiveView /> : view.kind === 'settings' ? <SettingsView /> : view.kind === 'receipts' ? <ReceiptsView /> :  view.kind === 'runs' ? <RunsView /> : view.kind === 'status' ? <StatusView /> : view.kind === 'insights' ? <InsightsView /> : view.kind === 'knowledge' ? <KnowledgeView /> : view.kind === 'notes' ? <NotesView /> : view.kind === 'project' ? <ProjectView id={view.id} /> : view.kind === 'search' ? <SearchView q0={view.q} /> : view.kind === 'contacts' ? <ContactsView /> : view.kind === 'calendar' ? <CalendarView /> : view.kind === 'activity' ? <ActivityView /> : view.kind === 'briefings' ? <BriefingsView open={view.id} /> : view.kind === 'meetings' ? <MeetingsView /> : view.kind === 'trips' ? <TripsView /> : view.kind === 'meeting' ? <MeetingPrepView key={view.id} id={view.id} /> : view.kind === 'person' ? <PersonView key={view.id} id={view.id} /> : null}</Fragment>}
      </Shell>
      <Toaster theme={dark ? 'dark' : 'light'} position="bottom-center" offset={56} mobileOffset={{ bottom: 84 }} toastOptions={{ className: '!rounded-md !text-sm !font-sans !shadow-float !border-line' }} />
    </AppContext.Provider>
  )
}
