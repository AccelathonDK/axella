import { calendarChanged } from '@/lib/calendarBus'
import { track } from '@/lib/report'
import { useCallback, useEffect, useRef, useState } from 'react'
import { profile, setProfile, type Profile } from '@/lib/profile'
import { toast } from 'sonner'
import { get, post } from '@/lib/api'
import { archivePath, baseName, digestNames, isRegular, listDir, loadDigest, parseName } from '@/lib/data'
import { isoDate } from '@/lib/utils'
import type { Call, CallConfig, Digest, Doc, ItemState, Overrides, Project, Recipient, ScheduleInfo, Task, VendorRule } from '@/lib/types'
import { markUnseen } from '@/lib/title'

/* a digest is complete when its .json sidecar exists – until then only its .md (no buttons) */
const jsonReady = (name: string) => fetch('digests/' + name.replace(/\.md$/, '.json'), { method: 'GET', cache: 'no-store' }).then(r => r.ok).catch(() => false)

export type Refresh = 'state' | 'tasks' | 'overrides' | 'projects' | 'schedule' | 'documents' | 'calendar'
const CAL_ACTIONS = new Set(['event', 'cal_add', 'cal_update', 'cal_delete', 'cal_restore', 'invite_respond', 'invite_dismiss'])
const JOB_LABEL: Record<string, string> = {
  draft: 'Reply saved in Drafts', reply_send: 'Sent', mail_send: 'Sent', invite_respond: 'Answer sent', file: 'Moved', trash: 'Moved to Trash', trash_batch: 'Moved to Trash', event: 'Added to calendar', document_forward: 'Forwarded',
}
const EMPTY_OV: Overrides = { sender: {}, domain: {}, item: {} }
const NEEDS = new Set(['p0', 'p1', 'p2', 'open'])   // sections that count as "needs you" in the arrival note
const RANK: Record<string, number> = { p0: 0, p1: 1, p2: 2, p3: 3 }

/* A digest that arrived while the dashboard was open or in the background. followed: the view moved to it by itself
   (you were on the latest); otherwise you were reading an older one and get a "Show" button instead. */
export interface Arrival { name: string; label: string; fresh: number; urgent: boolean; followed: boolean; seq: number }

export interface Ax {
  profileReady: boolean
  names: string[]; current: Digest | null; loading: boolean; error: string | null
  state: ItemState; stateReady: boolean; tasks: Task[]; projects: Project[]; projectsError: boolean; projectsLoaded: boolean; schedule: ScheduleInfo | null; documents: Doc[]; recipients: Recipient[]; vendorRules: Record<string, VendorRule>; overrides: Overrides; calls: Call[]; callCfg: CallConfig | null
  live: { active?: boolean; from?: { name?: string; number?: string } } | null
  apiOk: boolean; online: boolean; who: string | null; profile: Profile
  select: (name: string) => Promise<void>; reload: () => Promise<void>
  act: <T = any>(action: string, body: unknown, refresh?: Refresh[]) => Promise<T>
  isHandled: (id: string) => boolean
  refresh: (kinds: Refresh[]) => Promise<void>
  hold: React.MutableRefObject<number>
  arrival: Arrival | null; dismissArrival: () => void
}

async function fetchCalls() {
  try {
    const names = (await listDir('calls/')).filter(n => /\.json$/.test(n))
    const g = (n: string) => fetch('calls/' + encodeURIComponent(n), { cache: 'no-store' }).then(r => r.ok ? r.json() : null).catch(() => null)
    const cfg: CallConfig | null = names.includes('config.json') ? await g('config.json') : null
    const live = names.includes('live.json') ? await g('live.json') : null
    const list: Call[] = (await Promise.all(names.filter(n => !['config.json', 'live.json'].includes(n)).map(g))).filter(Boolean)
    list.sort((a, b) => ((RANK[a.priority!] ?? 4) - (RANK[b.priority!] ?? 4)) || (b.started || '').localeCompare(a.started || ''))
    return { calls: list, cfg, live }
  } catch { return { calls: [], cfg: null, live: null } }
}

export function useAxella(): Ax {
  const [names, setNames] = useState<string[]>([])
  const [current, setCurrent] = useState<Digest | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [state, setState] = useState<ItemState>({})
  const [stateReady, setStateReady] = useState(false)   // counts and the tab title wait for Done/snoozed to be known
  const [tasks, setTasks] = useState<Task[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [schedule, setSchedule] = useState<ScheduleInfo | null>(null)
  const [documents, setDocuments] = useState<Doc[]>([])
  const [recipients, setRecipients] = useState<Recipient[]>([])
  const [vendorRules, setVendorRules] = useState<Record<string, VendorRule>>({})
  const [overrides, setOverrides] = useState<Overrides>(EMPTY_OV)
  const [calls, setCalls] = useState<Call[]>([])
  const [callCfg, setCallCfg] = useState<CallConfig | null>(null)
  const [live, setLive] = useState<Ax['live']>(null)
  const [apiOk, setApiOk] = useState(false)
  const [online, setOnline] = useState(navigator.onLine)   // this laptop/phone has a connection
  const [who, setWho] = useState<string | null>(null)
  const [prof, setProf] = useState<Profile>(profile())
  const [profileReady, setProfileReady] = useState(false)   // views render after the profile (labels, accounts) is in
  const files = useRef<string[]>([])
  const cur = useRef<Digest | null>(null)
  const retry = useRef<Record<string, number>>({})   // digest name → tries to get its .json
  const [arrival, setArrival] = useState<Arrival | null>(null)
  const arrSeq = useRef(0)
  const announce = useCallback((name: string, prev: Digest | null, followed: boolean, urgentOnly = false) => {
    const d = cur.current
    const before = new Set((prev?.data.items || []).map(i => i.id))
    const items = followed && d?.name === name ? d.data.items : []
    const fresh = items.filter(i => !before.has(i.id) && NEEDS.has(i.section))
    setArrival({ name, label: parseName(name).label, fresh: fresh.length, urgent: urgentOnly || fresh.some(i => i.section === 'p0'), followed, seq: ++arrSeq.current })
  }, [])
  const dismissArrival = useCallback(() => setArrival(null), [])
  const hold = useRef(0)   // >0 while a form is being filled in: don't switch digest under the user's feet

  // A failed load keeps what was known: an empty state would make every handled (done / later) item and call look
  // open again for a moment – old messages flashing up when the phone wakes and the connection isn't back yet.
  const loadState = useCallback(async () => {
    try { const j = await get('state'); setState(j.state || {}); setApiOk(true); setStateReady(true); return true }
    catch { setApiOk(false); return false }
  }, [])
  // the very first load failed (Tailscale still connecting): wait for the retry (every 5 s) before showing the digest
  // without Done / Later known – after 8 s it shows anyway, as before, with the "can't reach the Mac mini" banner
  useEffect(() => { const t = setTimeout(() => setStateReady(true), 8000); return () => clearTimeout(t) }, [])
  const loadTasks = useCallback(async () => { try { setTasks((await get('tasks')).tasks || []) } catch { setTasks([]) } }, [])
  // a failed load keeps the list it had (never "no projects" by accident) and tries again: 2 s, 5 s, 15 s
  const [projectsError, setProjectsError] = useState(false), [projectsLoaded, setProjectsLoaded] = useState(false)
  const loadProjects = useCallback(async (attempt = 0): Promise<void> => {
    try { setProjects((await get('projects')).projects || []); setProjectsError(false); setProjectsLoaded(true) }
    catch {                                   // retried in the background – the rest of the page doesn't wait for it
      if (attempt < 3) setTimeout(() => { loadProjects(attempt + 1) }, [2000, 5000, 15000][attempt]); else setProjectsError(true)
    }
  }, [])
  const loadSchedule = useCallback(async () => { try { const j = await get('schedule'); setSchedule({ schedule: j.schedule, status: j.status, sweep: j.sweep, wait: j.wait, next: j.next }) } catch { setSchedule(null) } }, [])
  const loadDocuments = useCallback(async () => { try { const j = await get('documents'); setDocuments(j.documents || []); setRecipients(j.recipients || []); setVendorRules(j.vendor_rules || {}) } catch { /* keep */ } }, [])
  const loadOverrides = useCallback(async () => { try { setOverrides({ ...EMPTY_OV, ...(await get('overrides')).overrides }) } catch { /* keep */ } }, [])
  // the profile names the accounts (workplace labels instead of "Exchange"): if it doesn't come – the service was
  // restarting, a slow Mac mini – the views render with the defaults and it is fetched again until it arrives; then
  // profileVersion() changes and every view remounts with the real labels (fix round 7, P2-3)
  const profileTry = useRef<{ ok: boolean; timer: ReturnType<typeof setTimeout> | null; n: number }>({ ok: false, timer: null, n: 0 })
  const loadProfile = useCallback(async (): Promise<void> => {
    const t = profileTry.current
    if (t.timer) { clearTimeout(t.timer); t.timer = null }
    try { const j = await get<Profile>('profile'); setProfile(j); setProf(profile()); t.ok = true; t.n = 0 }
    catch { t.n++; t.timer = setTimeout(() => { loadProfile() }, Math.min(30000, 2000 * t.n)) }
    finally { setProfileReady(true) }
  }, [])
  const loadCalls = useCallback(async () => { const c = await fetchCalls(); setCalls(c.calls); setCallCfg(c.cfg); setLive(c.live) }, [])

  const show = useCallback(async (name: string) => {
    speechSynthesis.cancel()
    const data = await loadDigest(name)
    // older digests carried a "Your tasks: …" card – the live To do list on Today already shows the tasks
    data.items = data.items.filter(i => !(i.channel === 'calendar' && /^Your tasks\b/.test(i.headline || '')))
    // urgent alerts written after this digest (hourly P0 check) belong on it too, until the next digest repeats them
    if (isRegular(name) && !name.includes('/')) {
      const later = digestNames(files.current).filter(n => !isRegular(n) && n > name)
      const regLater = digestNames(files.current).some(n => isRegular(n) && n > name)
      if (!regLater) for (const n of later) {
        try {
          const extra = await loadDigest(n)
          const have = new Set(data.items.map(i => i.id)), mids = new Set(data.items.map(i => i.message_id).filter(Boolean))
          // same item (or same mail under another id) already in the digest → don't show it twice
          data.items.unshift(...extra.items.filter(i => i.section === 'p0' && !have.has(i.id) && !(i.message_id && mids.has(i.message_id))))
        } catch { /* skip */ }
      }
    }
    const d = { name, meta: parseName(name), data }
    cur.current = d; setCurrent(d)
    // a digest that is still being written shows its .md first (read-only, no buttons): try the .json again shortly
    // a digest still being written shows its .md first (read-only, no buttons): look for the .json every 10 s until it's
    // there (up to 30 min; paused while the app is in the background – coming back re-checks at once, see reload)
    if (data.fromMd && (retry.current[name] || 0) < 180 && baseName(name).slice(0, 10) >= isoDate(new Date(Date.now() - 864e5))) {
      retry.current[name] = (retry.current[name] || 0) + 1
      setTimeout(() => {
        if (cur.current?.name !== name) return
        if (document.hidden) { retry.current[name]--; return }      // reload() on return picks it up
        show(name).catch(() => {})
      }, 10000)
    }
  }, [])

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const ok = await loadState()
      if (ok) await Promise.all([loadTasks(), loadOverrides(), loadProjects(), loadSchedule(), loadDocuments(), loadProfile()])
      else setProfileReady(true)                       // no action service: render with the defaults
      await loadCalls()
      get('health').then(j => setWho(j.login || null)).catch(() => {})
      const prevFiles = files.current
      const prevLatest = digestNames(prevFiles).find(isRegular)
      files.current = await listDir('digests/')
      const n = digestNames(files.current); setNames(n)
      if (!n.length) { setError('No digests yet'); return }
      const latest = n.find(isRegular) || n[0]
      const want = new URLSearchParams(location.search).get('d')
      const c = cur.current
      let arrived = !!(c && prevLatest && latest !== prevLatest && isRegular(latest))
      if (arrived && !(await jsonReady(latest))) { arrived = false; files.current = prevFiles }   // still being written: switch when complete
      if (arrived && c!.name === prevLatest && hold.current <= 0) {      // back from the background and a new digest came in
        await show(latest).catch(() => show(c!.name)); markUnseen(); announce(latest, c, true)
      }
      else if (arrived) { await show(c!.name).catch(() => show(latest)); announce(latest, c, false) }
      else if (c) await show(c.name).catch(() => show(latest))            // keep what you were looking at (also archived/P0)
      else if (want) await show(want).catch(() => show(archivePath(want))).catch(() => show(latest))   // push links to moved digests still open
      else await show(latest)
      setError(null)
    } catch { setError('Could not load digests') }
    finally { setLoading(false) }
  }, [loadState, loadTasks, loadOverrides, loadProjects, loadSchedule, loadDocuments, loadCalls, loadProfile, show, announce])

  // action service unreachable (e.g. restarting) → keep trying every 5 s; when it answers, bring the buttons back
  useEffect(() => {
    if (apiOk) return
    const t = setInterval(async () => {
      if (document.hidden || !navigator.onLine) return
      if (await loadState()) {
        await Promise.all([loadTasks(), loadOverrides(), loadProjects(), loadSchedule(), loadDocuments(), loadProfile()])
        get('health').then(j => setWho(j.login || null)).catch(() => {})
      }
    }, 5000)
    return () => clearInterval(t)
  }, [apiOk, loadState, loadTasks, loadOverrides, loadProjects, loadSchedule, loadDocuments, loadProfile])

  // the device itself goes offline/online: pause the buttons, and pick up again by itself when the connection is back
  useEffect(() => {
    const off = () => { setOnline(false); setApiOk(false) }
    const on = () => { setOnline(true); reload() }
    window.addEventListener('offline', off); window.addEventListener('online', on)
    return () => { window.removeEventListener('offline', off); window.removeEventListener('online', on) }
  }, [reload])

  // first load + reload when the app comes back to the foreground
  useEffect(() => {
    reload()
    const v = () => { if (!document.hidden) reload() }
    document.addEventListener('visibilitychange', v)
    return () => document.removeEventListener('visibilitychange', v)
  }, [reload])

  // every 60 s: new digest? (follow it if you were on the latest) + refresh handled/tasks/sorting/calls
  useEffect(() => {
    const t = setInterval(async () => {
      try {
        const f = await listDir('digests/'), n = digestNames(f), c = cur.current
        if (!n.length || !c) return
        const before = digestNames(files.current)
        const latest = n.find(isRegular), wasLatest = before.find(isRegular) === c.name
        const newP0 = n.some(x => !isRegular(x) && !before.includes(x))
        files.current = f; setNames(n)
        if (await loadState()) await Promise.all([loadTasks(), loadOverrides(), loadProjects(), loadSchedule(), loadDocuments()])
        await loadCalls()
        const prevLatest = before.find(isRegular)
        if (latest && latest !== prevLatest && !(await jsonReady(latest))) { files.current = before; return }   // still being written
        if (latest && latest !== c.name && wasLatest && hold.current <= 0) {
          await show(latest); markUnseen(); announce(latest, c, true)
        }
        else if (latest && latest !== prevLatest && !wasLatest) announce(latest, c, false)   // reading an older one: offer it
        else if (newP0 && wasLatest && hold.current <= 0) {
          await show(c.name)                       // pull the new urgent item into the current digest
          if (!markUnseen()) toast.warning('New urgent item')
        }
      } catch { /* offline – try again next minute */ }
    }, 60000)
    return () => clearInterval(t)
  }, [loadState, loadTasks, loadOverrides, loadProjects, loadSchedule, loadDocuments, loadCalls, show, announce])

  const refresh = useCallback(async (kinds: Refresh[]) => {
    await Promise.all(kinds.map(x => x === 'calendar' ? Promise.resolve(calendarChanged()) : x === 'state' ? loadState() : x === 'tasks' ? loadTasks() : x === 'projects' ? loadProjects() : x === 'schedule' ? loadSchedule() : x === 'documents' ? loadDocuments() : loadOverrides()))
  }, [loadState, loadTasks, loadOverrides, loadProjects, loadSchedule, loadDocuments])
  const act = useCallback(async (action: string, body: unknown, kinds: Refresh[] = ['state']) => {
    // a change to the calendar: every calendar view on the page reads Calendar again
    if (CAL_ACTIONS.has(action)) kinds = [...kinds, 'calendar']
    track('act', action)                                // the action's name only (Report a problem)
    const r = await post(action, body)
    if (!r?.result?.queued) { await refresh(kinds); return r }
    // Mail/Calendar work runs in the background on the Mac mini – wait a little, then keep watching quietly
    const id = r.result.job as string
    const check = async () => (await get<{ job: { state: string; result?: unknown; error?: string } }>('job?id=' + id)).job
    for (let i = 0; i < 12; i++) {
      await new Promise(res => setTimeout(res, i < 4 ? 500 : 1000))
      const j = await check().catch(() => null)
      if (j?.state === 'ok') { await refresh(kinds); return { ok: true, result: j.result } }
      if (j?.state === 'error') { await refresh(kinds); throw new Error(j.error || 'failed') }
    }
    const label = JOB_LABEL[action] || 'Done'
    const t = toast.loading('Mail is busy – finishing in the background…')
    ;(async () => {
      for (let i = 0; i < 120; i++) {
        await new Promise(res => setTimeout(res, 3000))
        const j = await check().catch(() => null)
        if (j?.state === 'ok') { toast.success(label, { id: t }); refresh(kinds); return }
        if (j?.state === 'error') { toast.error('Failed: ' + j.error, { id: t, duration: 10000 }); refresh(kinds); return }
      }
      toast.error('No answer from Mail on the Mac mini – check it there', { id: t })
    })()
    return { ok: true, result: { pending: true } }
  }, [refresh])

  const isHandled = useCallback((id: string) => {
    const s = state[id]; if (!s) return false
    if (s.status === 'done') return true
    if (s.status === 'snoozed') return new Date(s.until!) > new Date()
    return false
  }, [state])

  const select = useCallback(async (name: string) => {
    await show(name)
    const u = new URL(location.href); u.searchParams.set('d', name); history.replaceState(null, '', u)
  }, [show])

  return { names, current, loading, error, state, stateReady, tasks, projects, projectsError, projectsLoaded, schedule, documents, recipients, vendorRules, overrides, calls, callCfg, live, apiOk, online, who, profile: prof, profileReady, select, reload, act, isHandled, hold, refresh, arrival, dismissArrival }
}
