import { PrivacyCard } from '@/components/Privacy'
import { OutboundCard } from '@/components/Outbound'
import { BlocksSettingsCard } from '@/components/Blocks'
import { BackupCard } from '@/components/Backup'
import { useFab } from '@/components/Tour'
import { CalmSetupCard } from '@/components/CalmSetup'
import { RulesCard, useLearn } from '@/components/Learn'
import { ReportIcon, ReportsCard } from '@/components/Report'
import { get } from '@/lib/api'
import { APP_VERSION } from '@/lib/report'
import { useReminders } from '@/lib/reminders'
import { Component, useEffect, useState, type ReactNode } from 'react'
import { useTheme, type Theme } from '@/lib/theme'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Activity, Archive, Bell, CalendarDays, ChevronRight, Lock, Moon, Phone, Receipt, Recurring, Sparkles, Star, Sun, SunMoon } from '@/components/ax-icons'
import { VipsCard } from '@/components/Vips'
import { MeetingServicesCard } from '@/components/CalendarInvites'
import { useVips } from '@/lib/vips'
import { OutOfOfficeCard } from '@/components/Ooo'
import { CallSettingsCard } from '@/components/Cards'
import { RemindersCard } from '@/components/Reminders'
import { CleanupSettingsCard } from '@/components/Cleanup'
import { toast } from 'sonner'
import { CalendarOff, Forward, Palmtree, Plus, Radar, Save, ShieldCheck, Trash2, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { SectionCard } from '@/components/Section'
import { useApp, type SettingsPage } from '@/lib/app'
import type { Recipient, ScheduleSettings } from '@/lib/types'
import { NativeSelect } from '@/components/ui/input'
import { SchedulerCard } from '@/components/Runs'
import { cn, isoDate } from '@/lib/utils'

const nice = (d: string) => new Date(d + 'T00:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })

/** Banner on Today while Axella is paused (vacation / day off) */
export function PauseBanner() {
  const { ax, go } = useApp()
  const st = ax.schedule?.status
  if (!st?.reason) return null
  return (
    <button onClick={() => go({ kind: 'settings', page: 'schedule' })} className="flex w-full items-center gap-2 rounded-lg border border-fjord/40 bg-fjord-soft/10 px-3 py-2 text-left text-sm">
      {st.reason.startsWith('Vacation') ? <Palmtree className="size-4 shrink-0" /> : <CalendarOff className="size-4 shrink-0" />}
      <span className="flex-1">{st.reason.replace(/until (\d{4}-\d{2}-\d{2})/, (_, d) => 'until ' + nice(d))}. No scheduled digests{st.urgent ? ', urgent items still pushed' : ''}.</span>
      <span className="text-muted-foreground text-xs">Settings</span>
    </button>
  )
}

/* ---------- Settings: an overview, one page per area ---------- */
interface Area { page: SettingsPage; icon: any; title: string; line: string; intro: string }
const AREAS: Area[] = [
  { page: 'schedule', icon: CalendarDays, title: 'Schedule', line: 'When Axella reads your mail and writes digests – and when it stays quiet',
    intro: 'The digest times, days off and vacation. On paused days scheduled runs stop straight away – nothing is read and nothing is pushed. "Run sweep now" in the menu makes an extra digest any time.' },
  { page: 'calendar', icon: CalendarDays, title: 'Calendar', line: 'Meeting services and who invitations go from',
    intro: 'Teams, Google Meet and Zoom for online meetings, iCloud invites, and the online meeting each calendar suggests.' },
  { page: 'away', icon: Palmtree, title: 'Away', line: "What people read and hear while you're out",
    intro: "An automatic reply in your mailboxes and a different greeting on the call agent – on and off by itself on the dates you set." },
  { page: 'calls', icon: Phone, title: 'Calls', line: "The call agent that answers when you don't",
    intro: 'Calls you miss are answered by the call agent, which takes a message. Here: how it greets callers, quiet hours and whether it is connected.' },
  { page: 'privacy', icon: Lock, title: 'Privacy', line: 'Who Axella never reads, and what leaves your home',
    intro: "Private and hidden contacts per app – enforced on the Mac mini before any Claude run sees anything – Signal, and the notification for private messages." },
  { page: 'vips', icon: Star, title: 'VIPs', line: 'People who always reach you first',
    intro: 'Your VIP lists from contacts.md. VIPs come first in digests and urgent checks, and the call agent marks their calls.' },
  { page: 'reminders', icon: Recurring, title: 'Reminders', line: 'Tasks that come back by themselves',
    intro: 'Rules like "every month on the 1st". The Mac mini adds the task to To do each time, with a push if you want one.' },
  { page: 'mailbox', icon: Archive, title: 'Mailbox', line: 'Rules for cleaning up old mail',
    intro: 'Which mailboxes and how old. Cleanup suggests old mail with no relationship to you and moves it to a "Cleanup" folder only when you approve – never deleted.' },
  { page: 'bookkeeping', icon: Receipt, title: 'Bookkeeping', line: 'Where receipts and invoices may be forwarded',
    intro: 'Your closed list of recipients. Receipts are only ever forwarded to these addresses – never to an address found in a mail.' },
  { page: 'reports', icon: ReportIcon, title: 'Reports', line: "Problems you've reported, and community triage",
    intro: 'Everything you reported with ⌘B / Ctrl+B, saved on the Mac mini. Download them for Claude as a zip.' },
  { page: 'notifications', icon: Bell, title: 'Notifications', line: 'Calm setup – keep the other apps quiet',
    intro: 'Three steps, about two minutes: quiet Mail, Messages and WhatsApp on your iPhone, let Axella through, and an “Axella” Focus. Axella changes nothing on the iPhone – these are steps you follow.' },
  { page: 'rules', icon: Sparkles, title: 'Rules', line: 'What Axella has learned from you',
    intro: 'Every rule you made on a tap – from “Not important”, “This should have reached me” or a suggestion – in plain words, with when and why. Remove one and it stops at once.' },
  { page: 'appearance', icon: SunMoon, title: 'Appearance', line: 'Light, dark or follow the device', intro: 'Applies to this device.' },
  { page: 'system', icon: Activity, title: 'System', line: "Versions, the Mac mini, and what's running",
    intro: 'What this Axella is running on. Every run with its log is under Runs and logs.' },
]

/* One broken area (an unexpected answer from the Mac mini) shows a short note instead of a blank page. */
class Guard extends Component<{ title?: string; children: ReactNode }, { err: string | null }> {
  state = { err: null as string | null }
  static getDerivedStateFromError(e: unknown) { return { err: e instanceof Error ? e.message : String(e) } }
  componentDidCatch(e: unknown) { console.error(e) }
  render() {
    if (!this.state.err) return this.props.children
    return <div className="bg-card max-w-xl rounded-lg border p-5 text-sm">
      <div className="mb-1 font-semibold">{this.props.title ? this.props.title + ' couldn’t be shown' : 'Settings couldn’t be shown'}</div>
      <p className="text-ink-2">The Mac mini sent something this page didn’t expect. Reload, or report it with ⌘B.</p>
      <button className="text-fjord mt-3 font-semibold hover:underline" onClick={() => this.setState({ err: null })}>Try again</button>
    </div>
  }
}

function useAreaStatus(): Partial<Record<SettingsPage, string>> {
  const { ax } = useApp()
  const reminders = useReminders()
  const vipList = useVips()
  const [t] = useTheme()
  const learn = useLearn()
  const [x, setX] = useState<{ ooo?: any; privacy?: any; reports?: any; system?: any; cleanup?: any }>({})
  useEffect(() => {
    if (!ax.apiOk) return
    get('ooo').then(o => setX(v => ({ ...v, ooo: o }))).catch(() => {})
    get('cleanup').then(o => setX(v => ({ ...v, cleanup: o }))).catch(() => {})
    get('privacy').then(o => setX(v => ({ ...v, privacy: o }))).catch(() => {})
    get('reports').then(o => setX(v => ({ ...v, reports: o }))).catch(() => {})
    get('report_context').then(o => setX(v => ({ ...v, system: o }))).catch(() => {})
  }, [ax.apiOk])
  const st = ax.schedule?.status, sch = ax.schedule?.schedule
  const today = isoDate(new Date())
  const daysOff = (Array.isArray(sch?.off_dates) ? sch!.off_dates : []).filter(d => d >= today).length
  const cc = ax.callCfg
  const p = x.privacy, o = x.ooo, r = x.reports
  const d = (iso?: string | null) => iso ? nice(iso) : ''
  // the answers may come from an older Mac mini or a demo backend: count only what is really there, never crash
  const n = (v: unknown) => Array.isArray(v) ? v.length : null
  const pc = n(p?.contacts), rc = n(r?.reports), rec = n(ax.recipients) ?? 0
  const rem = Array.isArray(reminders) ? reminders : null
  return {
    schedule: st?.reason ? st.reason.replace(/until (\d{4}-\d{2}-\d{2})/, (_, dd) => 'until ' + nice(dd))
      : sch ? ['Digests on', sch.vacation?.on ? 'vacation planned' : 'vacation off', daysOff ? `${daysOff} day${daysOff === 1 ? '' : 's'} off planned` : ''].filter(Boolean).join(' · ') : undefined,
    away: o ? (o.active ? `On${o.until ? ' until ' + d(o.until) : ''}` : o.from ? `From ${d(o.from)}` : 'Off') : undefined,
    calls: !cc ? 'Not set up' : cc.last_error ? 'Problem – see Calls' : cc.demo ? 'Demo' : `Connected${cc.last_call ? ' · last call ' + new Date(cc.last_call).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : ''}`,
    privacy: p && pc != null ? [`${pc} private contact${pc === 1 ? '' : 's'}`, p.signal?.linked ? 'Signal on' : '', p.notify === false ? 'no notifications' : ''].filter(Boolean).join(' · ') : undefined,
    vips: Array.isArray(vipList) ? `${vipList.length} VIP${vipList.length === 1 ? '' : 's'}` : undefined,
    reminders: rem ? `${rem.filter(x => !x.paused).length} active${rem.some(x => x.paused) ? ` · ${rem.filter(x => x.paused).length} paused` : ''}` : undefined,
    mailbox: (() => {               // Settings → Mailbox: which mailboxes are cleaned up, and from what age
      const cs = x.cleanup?.settings
      if (!cs || !Array.isArray(cs.accounts)) return undefined
      if (!cs.accounts.length) return 'Cleanup off'
      return `${cs.accounts.length} mailbox${cs.accounts.length === 1 ? '' : 'es'} · older than ${cs.age_months} months`
    })(),
    bookkeeping: `${rec} recipient${rec === 1 ? '' : 's'}`,
    reports: r && rc != null ? `${rc} report${rc === 1 ? '' : 's'}${r.mode === 'developer' ? ' · developer mode' : ''}` : undefined,
    rules: learn ? (learn.rules.length ? `${learn.rules.length} learned rule${learn.rules.length === 1 ? '' : 's'}` : 'None yet') : undefined,
    appearance: t === 'auto' ? 'Follows this device' : t === 'dark' ? 'Dark' : 'Light',
    system: typeof x.system?.meta?.commit === 'string' ? `${APP_VERSION.split('+')[0]} · ${x.system.meta.commit.slice(0, 12)}` : APP_VERSION.split('+')[0],
  }
}

export function SettingsView() {
  const { view } = useApp()
  const page = view.kind === 'settings' ? view.page : undefined
  const area = AREAS.find(a => a.page === page)
  return <Guard key={page || 'overview'} title={area?.title}>{area ? <SettingsPageView area={area} /> : <SettingsOverview />}</Guard>
}

function SettingsOverview() {
  const { go } = useApp()
  const status = useAreaStatus()
  return <div className="space-y-4">
    <div><h1 className="text-xl font-semibold tracking-tight">Settings</h1>
      <p className="text-muted-foreground text-sm">Pick an area. Everything here is stored on your Mac mini.</p></div>
    <nav data-settings-nav aria-label="Settings areas" className="bg-card divide-y overflow-hidden rounded-lg border">
      {AREAS.map(a => <button key={a.page} onClick={() => go({ kind: 'settings', page: a.page })}
        className="hover:bg-bg-2 flex w-full items-center gap-3 px-4 py-3 text-left transition-colors">
        <span className="bg-bg-2 text-ink-2 flex size-9 shrink-0 items-center justify-center rounded-md"><a.icon className="size-[18px]" /></span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2"><span className="font-semibold">{a.title}</span>
            {status[a.page] && <span className="text-ink-3 ml-auto truncate text-[12.5px] max-sm:hidden">{status[a.page]}</span>}</span>
          <span className="text-ink-2 block text-[13px] leading-snug">{a.line}</span>
          {status[a.page] && <span className="text-ink-3 block truncate text-[12.5px] sm:hidden">{status[a.page]}</span>}
        </span>
        <ChevronRight className="text-ink-3 size-4 shrink-0" />
      </button>)}
    </nav>
    <HouseRules />
  </div>
}

function CallsPage() {
  const { ax } = useApp()
  if (ax.callCfg) return <CallSettingsCard />
  return <div className="bg-card text-ink-2 rounded-lg border p-4 text-sm">
    <div className="text-ink mb-1 font-semibold">Not set up</div>
    The call agent isn’t connected on this Mac mini yet. See “Call agent” in SETUP.md – once it runs, its greeting, callers and transcripts appear here.
  </div>
}

function SettingsPageView({ area }: { area: Area }) {
  const { go } = useApp()
  return <div className="space-y-4">
    <div data-settings-area={area.page}>
      <button onClick={() => go({ kind: 'settings' })} className="text-fjord -ml-1 mb-1 inline-flex items-center gap-1 px-1 text-[13px] font-semibold hover:underline">
        <ChevronRight className="size-4 rotate-180" />Settings</button>
      <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><area.icon className="size-5" />{area.title}</h1>
      <p className="text-muted-foreground text-sm">{area.intro}</p>
    </div>
    {area.page === 'schedule' ? <SchedulePage />
      : area.page === 'calendar' ? <><MeetingServicesCard /><BlocksSettingsCard /></>
      : area.page === 'away' ? <OutOfOfficeCard />
      : area.page === 'calls' ? <CallsPage />
      : area.page === 'privacy' ? <><PrivacyCard /><OutboundCard /></>
      : area.page === 'vips' ? <VipsCard />
      : area.page === 'reminders' ? <RemindersCard />
      : area.page === 'mailbox' ? <CleanupSettingsCard />
      : area.page === 'bookkeeping' ? <RecipientsCard />
      : area.page === 'reports' ? <ReportsCard />
      : area.page === 'notifications' ? <CalmSetupCard />
      : area.page === 'rules' ? <RulesCard />
      : area.page === 'appearance' ? <SectionCard id="look" icon={SunMoon} title="Appearance" sub="Light, dark, or follow this device"><div className="space-y-4 p-4"><ThemePicker /><TourFabSetting /></div></SectionCard>
      : <><SystemPage /><BackupCard /></>}
  </div>
}

/* the house rules – same wording as the Guide ("The house rules") and New mail */
function HouseRules() {
  return <div className="bg-card flex gap-3 rounded-lg border px-4 py-3 text-sm">
    <ShieldCheck className="text-fjord mt-0.5 size-5 shrink-0" />
    <div className="min-w-0">
      <div className="font-semibold">How Axella handles your mail</div>
      <ul className="text-ink-2 mt-1 space-y-0.5">
        <li>Nothing is sent automatically. You write or edit a reply in Axella and tap Send; after a second tap and 6 seconds to undo, your Mac mini's Mail sends it. Or save it as a draft in Mail instead.</li>
        <li>Receipts and invoices go only to your own recipients list (Settings → Bookkeeping).</li>
        <li>Newsletters are unsubscribed only when you tap Unsubscribe. Delete always means Trash, never gone.</li>
      </ul>
      <p className="text-ink-3 mt-1.5 text-xs">Every mail sent from Axella is logged on the Mac mini, with a brake of 20 an hour.</p>
    </div>
  </div>
}

function SystemPage() {
  const { go } = useApp()
  const [c, setC] = useState<{ meta: Record<string, any>; mode: string } | null>(null)
  useEffect(() => { get('report_context').then(setC).catch(() => {}) }, [])
  const rows: [string, string][] = [['Axella', APP_VERSION], ['Commit', c?.meta.commit || '–'], ['Mac mini', c?.meta.mac_model || '–'],
    ['macOS', c?.meta.os_version || '–'], ['Memory', c?.meta.ram_tier || '–'], ['Connected', (c?.meta.connectors || []).join(', ') || '–'],
    ['Reports', c ? (c.mode === 'developer' ? 'developer mode' : 'community') : '–']]
  return <div className="bg-card overflow-hidden rounded-lg border">
    <dl className="divide-y text-sm">{rows.map(([k, v]) => <div key={k} className="flex gap-3 px-4 py-2.5"><dt className="text-ink-3 w-28 shrink-0">{k}</dt><dd className="min-w-0 break-words">{v}</dd></div>)}</dl>
    <div className="flex gap-2 border-t px-4 py-3"><Button size="sm" variant="outline" onClick={() => go({ kind: 'status' })}><ShieldCheck />System status</Button><Button size="sm" variant="outline" onClick={() => go({ kind: 'runs' })}><Activity />Runs and logs</Button></div>
  </div>
}

function SchedulePage() {
  const { ax } = useApp()
  const [s, setS] = useState<ScheduleSettings | null>(ax.schedule?.schedule || null)
  const [busy, setBusy] = useState(false)
  const [newDate, setNewDate] = useState('')
  useEffect(() => { if (ax.schedule && !busy) setS(ax.schedule.schedule) }, [ax.schedule])
  if (!s) return <div className="text-muted-foreground py-10 text-center">{ax.apiOk ? 'Loading…' : 'Action service not reachable.'}</div>

  async function save(patch: Partial<ScheduleSettings>, msg: string) {
    const next = { ...s!, ...patch }
    setS(next); setBusy(true)
    try { await ax.act('schedule_set', patch, ['schedule']); toast(msg) }
    catch (e: any) { toast.error('Failed: ' + e.message); setS(ax.schedule?.schedule || s) }
    finally { setBusy(false) }
  }
  const v = s.vacation
  const setV = (p: Partial<typeof v>, msg: string) => save({ vacation: { ...v, ...p } }, msg)
  const today = isoDate(new Date())

  return (
    <div className="space-y-4">
      <SchedulerCard />
      <SectionCard id="days" color="var(--ax-p2)" icon={CalendarOff} title="Days off" sub="Holidays and single days without digests – weekdays are set per digest under Schedule">
        <div className="space-y-4 p-4 text-sm">
          <label className="flex items-start gap-3">
            <Checkbox className="mt-0.5" checked={s.urgent_on_days_off} onCheckedChange={c => save({ urgent_on_days_off: !!c }, c ? 'Urgent checks run on days off' : 'Days off are fully off')} />
            <span>Keep urgent checks running on days off<span className="text-muted-foreground block text-xs">Off = nothing runs on those days, not even urgent checks.</span></span>
          </label>
          <label className="flex items-start gap-3">
            <Checkbox className="mt-0.5" checked={!!s.off_work_only} onCheckedChange={c => save({ off_work_only: !!c }, c ? 'Days off pause work digests only' : 'Days off pause every digest')} />
            <span>Pause work digests only<span className="text-muted-foreground block text-xs">A day off from work: Work-only digests are skipped, private ones still run and digests for both cover private only. Urgent checks keep running.</span></span>
          </label>
          <div className="space-y-1.5">
            <div className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">Single days off</div>
            <form className="flex gap-2" onSubmit={e => { e.preventDefault(); if (newDate && !s.off_dates.includes(newDate)) save({ off_dates: [...s.off_dates, newDate].sort() }, nice(newDate) + ' is a day off'); setNewDate('') }}>
              <Input type="date" min={today} value={newDate} onChange={e => setNewDate(e.target.value)} className="w-44" />
              <Button size="icon-sm" type="submit" aria-label="Add day off" disabled={!newDate}><Plus /></Button>
            </form>
            <div className="flex flex-wrap gap-1.5">
              {s.off_dates.filter(d => d >= today).map(d => <span key={d} className="bg-bg-2 inline-flex items-center gap-1 rounded-sm py-1 pr-1.5 pl-2.5 text-xs font-medium">{nice(d)}
                <button aria-label={'Remove ' + d} onClick={() => save({ off_dates: s.off_dates.filter(x => x !== d) }, 'Removed')}><X className="text-muted-foreground hover:text-destructive size-3.5" /></button></span>)}
              {!s.off_dates.some(d => d >= today) && <span className="text-muted-foreground text-xs">None planned</span>}
            </div>
          </div>
        </div>
      </SectionCard>

      <SectionCard id="vac" color="var(--ax-wait)" icon={Palmtree} title="Vacation mode" sub={v.on ? (ax.schedule?.status.reason || 'On – scheduled for later') : 'Off'}>
        <div className="space-y-4 p-4 text-sm">
          <label className="flex items-center gap-3 font-medium">
            <Checkbox checked={v.on} onCheckedChange={c => setV({ on: !!c }, c ? 'Vacation mode on' : 'Vacation mode off – digests resume')} />
            Vacation mode on
          </label>
          <div className={cn('space-y-3', !v.on && 'opacity-60')}>
            <div className="space-y-1.5">
              <div className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">While on vacation</div>
              {([['urgent', 'Urgent only', 'No digests, but the urgent checks keep running and push anything truly urgent (VIPs).'],
                 ['off', 'Completely off', 'Nothing runs at all. The first digest after you’re back catches up on everything.']] as const).map(([val, label, hint]) =>
                <label key={val} className="flex cursor-pointer gap-3 rounded-lg border p-2.5 has-[:checked]:border-primary has-[:checked]:bg-primary/5">
                  <input type="radio" name="vmode" className="mt-0.5 accent-[var(--primary)]" checked={v.mode === val} onChange={() => setV({ mode: val }, label)} />
                  <span><span className="font-medium">{label}</span><span className="text-muted-foreground block text-xs">{hint}</span></span>
                </label>)}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <label className="space-y-1"><span className="text-muted-foreground text-xs">From (optional)</span>
                <Input type="date" value={v.from || ''} onChange={e => setV({ from: e.target.value || null }, 'Saved')} /></label>
              <label className="space-y-1"><span className="text-muted-foreground text-xs">Until (optional)</span>
                <Input type="date" value={v.until || ''} min={v.from || today} onChange={e => setV({ until: e.target.value || null }, 'Saved')} /></label>
            </div>
            <p className="text-muted-foreground text-xs">With dates, vacation mode switches itself on and off. Leave them empty to switch it by hand.</p>
          </div>
        </div>
      </SectionCard>

      <SectionCard id="sweep" color="var(--ax-cal)" icon={Radar} title="On-demand sweep" sub="“Run sweep now” in the menu">
        <div className="text-muted-foreground space-y-2 p-4 text-sm">
          <p>Starts a full digest outside the schedule, e.g. in the evening. It also runs on paused days – you asked for it.</p>
          <p>{ax.schedule?.wait || 'You get a push when it’s ready.'} Follow it under <b className="text-foreground">Runs</b>.</p>
          <SweepStatus />
        </div>
      </SectionCard>
    </div>
  )
}

function SweepStatus() {
  const { ax } = useApp()
  const sw = ax.schedule?.sweep
  const since = sw ? new Date(sw.fired_at || sw.at).getTime() : 0
  const done = sw && ((ax.current?.meta.date && ax.current.meta.date.getTime() > since) || Date.now() - since > 60 * 60e3)
  if (!sw || done) return null
  const t = (iso: string) => new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  return <div className="text-foreground flex items-center gap-2 rounded-lg border px-3 py-2">
    <Radar className="size-4" />
    <span className="flex-1">{sw.fired_at ? `Sweep started ${t(sw.fired_at)} – digest on its way` : `Requested ${t(sw.at)} – waiting for the next check`}</span>
    {!sw.fired_at && <Button size="pill" variant="outline" onClick={() => ax.act('sweep_cancel', {}, ['schedule']).then(() => toast('Sweep cancelled'))}>Cancel</Button>}
  </div>
}

/** Menu entry: request a sweep and tell the user how long it takes */
export function useSweep() {
  const { ax } = useApp()
  const sw = ax.schedule?.sweep
  // waiting = requested and no newer digest yet – but give up after 60 min so a stuck run never blocks a new request
  const since = sw ? new Date(sw.fired_at || sw.at).getTime() : 0
  const pending = !!sw && Date.now() - since < 60 * 60e3 && !(ax.current?.meta.date && ax.current.meta.date.getTime() > since)
  async function request() {
    try {
      const r = await ax.act<{ result: { message: string } }>('sweep_request', {}, ['schedule'])
      toast(r.result.message, { duration: 9000 })
    } catch (e: any) { toast.error('Failed: ' + e.message) }
  }
  return { pending, sw, request }
}

/** Bookkeepers / platforms that receipts may be forwarded to – the closed circle */
function RecipientsCard() {
  const { ax } = useApp()
  const [rows, setRows] = useState<Recipient[]>(ax.recipients)
  const [dirty, setDirty] = useState(false)
  useEffect(() => { if (!dirty) setRows(ax.recipients) }, [ax.recipients])
  const projects = ax.projects.filter(p => p.status === 'active')
  const upd = (i: number, patch: Partial<Recipient>) => { setRows(rows.map((r, j) => j === i ? { ...r, ...patch } : r)); setDirty(true) }
  async function save() {
    try { await ax.act('recipients_set', { recipients: rows.filter(r => r.name || r.email) }, ['documents']); setDirty(false); toast('Recipients saved') }
    catch (e: any) { toast.error('Failed: ' + e.message) }
  }
  return (
    <SectionCard id="recipients" color="var(--ax-tasks)" icon={Forward} title="Bookkeeping recipients" sub="Where receipts and invoices may be forwarded – nowhere else">
      <div className="space-y-3 p-4 text-sm">
        <p className="text-muted-foreground text-xs">Your bookkeeper, or a company's receipt inbox. Receipts are forwarded as the original mail with its attachments, and only ever be forwarded to addresses on this list – never to an address found in a mail. Optionally tie one to a project to have it suggested for that project’s receipts.</p>
        {rows.map((r, i) => <div key={r.id || i} className="grid grid-cols-[1fr_auto] gap-2 rounded-lg border p-2.5 2xl:grid-cols-[1fr_1.4fr_10rem_auto]">
          <Input value={r.name} onChange={e => upd(i, { name: e.target.value })} placeholder="Name, e.g. Bookkeeper – My Company" />
          <button className="text-muted-foreground hover:text-destructive self-center 2xl:order-last" aria-label="Remove" onClick={() => { setRows(rows.filter((_, j) => j !== i)); setDirty(true) }}><Trash2 className="size-4" /></button>
          <Input value={r.email} onChange={e => upd(i, { email: e.target.value })} placeholder="email@…" type="email" className="col-span-2 2xl:col-span-1" />
          <NativeSelect value={r.project || ''} onChange={e => upd(i, { project: e.target.value || null })} className="col-span-2 2xl:col-span-1">
            <option value="">Any project</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </NativeSelect>
        </div>)}
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => { setRows([...rows, { id: '', name: '', email: '', project: null }]); setDirty(true) }}><Plus />Add recipient</Button>
          {dirty && <Button size="sm" onClick={save}><Save />Save</Button>}
        </div>
      </div>
    </SectionCard>
  )
}

/* the floating ? for page tours (components/Tour.tsx) – on by default, per device */
function TourFabSetting() {
  const [on, set] = useFab()
  return <label className="flex items-start gap-2.5 text-sm" data-tour-fab-setting="">
    <input type="checkbox" className="mt-0.5" checked={on} onChange={e => set(e.target.checked)} />
    <span><span className="font-medium">Show the ? for page tours</span>
      <span className="text-ink-3 block text-[12.5px]">A small ? in the bottom-right corner of pages with a tour (Today, Trips, Meetings, Calendar, a project, Settings → System). Getting started always has Show me.</span></span>
  </label>
}

function ThemePicker() {
  const [t, set] = useTheme()
  return <ToggleGroup type="single" value={t} onValueChange={(v: string) => v && set(v as Theme)} aria-label="Theme">
    <ToggleGroupItem value="light"><Sun />Light</ToggleGroupItem>
    <ToggleGroupItem value="dark"><Moon />Dark</ToggleGroupItem>
    <ToggleGroupItem value="auto"><SunMoon />System</ToggleGroupItem>
  </ToggleGroup>
}
