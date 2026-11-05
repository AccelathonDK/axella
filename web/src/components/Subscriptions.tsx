import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Briefcase, Check, ChevronDown, ChevronRight, ExternalLink, Home, Loader2, Recurring, RotateCw, X } from '@/components/ax-icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input, NativeSelect } from '@/components/ui/input'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { get, post } from '@/lib/api'
import { useApp } from '@/lib/app'
import { cn } from '@/lib/utils'

/* Subscriptions (setup/recurring.py): regular charges found in Receipts, plus renewal, trial and price mails.
   Totals per currency – never converted. Axella never cancels or changes anything with a vendor.
   App stores (setup/app_stores.py): one row per item under the store, "<store> – other" for charges without item
   lines; the store's own page is a fixed link kept here (MANAGE), never one from a mail. */

/** the stores' own subscription pages – fixed in code (the same as app_stores.py STORES), never taken from a mail */
const MANAGE: Record<string, { name: string; url: string }> = {
  apple: { name: 'Apple', url: 'https://apps.apple.com/account/subscriptions' },
  google_play: { name: 'Google Play', url: 'https://play.google.com/store/account/subscriptions' },
  paypal: { name: 'PayPal', url: 'https://www.paypal.com/myaccount/autopay/' },
}

/** set before navigating to Receipts to land on the Subscriptions page (a digest item's "Open") */
export const subsNext = { open: false }

export interface Sub {
  id: string; vendor: string; currency?: string | null; amount?: number | null; interval?: 'monthly' | 'quarterly' | 'yearly' | null
  monthly?: number; first_seen?: string; last_seen?: string; next?: string | null; count: number; source: 'receipts' | 'mail' | 'store'
  account_link?: string | null; status: 'active' | 'cancelled' | 'not'; ctx?: 'work' | 'private' | null; auto_ctx?: 'work' | null
  project?: string | null; company?: string | null; quiet?: boolean; gone?: boolean
  store?: string | null; store_name?: string; plan?: string | null; store_other?: boolean; superseded?: boolean; trial_ends?: string | null
}
interface StoreGroup { name: string; count: number; month: Record<string, number>; tags: { ctx?: 'work' | 'private' | null; project?: string | null; company?: string | null } }
interface Change { id: string; sub: string; kind: string; text: string; at: string }
interface View { subs: Sub[]; totals: Record<string, { month: number; year: number; count: number }>; changes: Change[]; stores?: Record<string, StoreGroup>; last_scan?: string }

const money = (n: number, cur?: string | null) => n.toLocaleString('da-DK', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + (cur ? ' ' + cur : '')
const day = (d?: string | null) => d ? new Date(d.slice(0, 10) + 'T00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '–'
const PER: Record<string, string> = { monthly: 'month', quarterly: 'quarter', yearly: 'year' }
const ctxOfSub = (s: Sub) => s.ctx || s.auto_ctx || 'private'

export function SubscriptionsView() {
  const { ax, ctx } = useApp()
  const [v, setV] = useState<View | null>(null)
  const [tab, setTab] = useState<'active' | 'cancelled' | 'not'>('active')
  const [busy, setBusy] = useState<string | null>(null)
  const load = () => get<View>('recurring').then(setV).catch(() => setV({ subs: [], totals: {}, changes: [] }))
  useEffect(() => { load() }, [])
  const projects = ax.projects.filter(p => p.status === 'active')

  async function set(s: Sub, body: Record<string, unknown>, msg: string) {
    setBusy(s.id)
    try { await post('recurring_set', { id: s.id, title: s.vendor, ...body }); toast(msg); await load() }
    catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(null) }
  }
  async function seen() {
    try { await post('recurring_seen', { title: 'subscription changes' }); await load() } catch (e: any) { toast.error('Failed: ' + e.message) }
  }
  async function scan() {
    setBusy('scan')
    try { await post('recurring_scan', { title: 'subscriptions' }); toast('Checking Receipts and your mail – this takes a minute or two'); setTimeout(load, 60000) }
    catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(null) }
  }

  if (!v) return <div className="text-muted-foreground flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" />Loading…</div>
  const inCtx = (s: Sub) => ctx === 'all' || ctxOfSub(s) === ctx
  const list = v.subs.filter(s => s.status === tab && inCtx(s))
  // the totals follow the Work/Private filter too
  const totals: Record<string, { month: number; year: number; count: number }> = {}
  const perYear = (s: Sub) => s.amount! * ({ monthly: 12, quarterly: 4, yearly: 1 } as const)[s.interval!]   // a yearly charge is exact, not 12 × its rounded month
  v.subs.filter(s => s.status === 'active' && !s.gone && !s.superseded && s.monthly && s.currency && s.amount && s.interval && inCtx(s)).forEach(s => {
    const t = totals[s.currency!] = totals[s.currency!] || { month: 0, year: 0, count: 0 }; t.month += s.monthly!; t.year += perYear(s); t.count++ })
  const curs = Object.entries(totals).sort((a, b) => b[1].month - a[1].month)
  // a store with item lines is one group (its items and "<store> – other"); everything else is a row of its own
  const itemised = new Set(v.subs.filter(s => s.source === 'store' && s.store && !s.gone).map(s => s.store!))
  const rows: ({ s: Sub } | { group: string; subs: Sub[] })[] = []
  for (const s of list) {
    if (s.store && itemised.has(s.store) && (s.source === 'store' || s.store_other)) {
      const g = rows.find(r => 'group' in r && r.group === s.store) as { group: string; subs: Sub[] } | undefined
      if (g) g.subs.push(s); else rows.push({ group: s.store, subs: [s] })
    } else rows.push({ s })
  }
  return (
    <div className="space-y-4">
      {v.changes.length > 0 && <Card className="p-4" data-sub-changes="">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1"><div className="text-sm font-medium">Changes</div>
            <ul className="text-ink-2 mt-1 space-y-0.5 text-sm">{v.changes.map(c => <li key={c.id}>{c.text}</li>)}</ul></div>
          <Button size="pill" variant="ghost" onClick={seen}><Check />Seen</Button>
        </div>
      </Card>}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {curs.length ? curs.map(([cur, t]) => <div key={cur} className="contents">
          <Stat label={`Per month · ${cur}`} value={money(t.month, cur)} />
          <Stat label={`Per year · ${cur}`} value={money(t.year, cur)} />
        </div>) : <Stat label="Per month" value="–" />}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <ToggleGroup type="single" value={tab} onValueChange={(x: string) => x && setTab(x as typeof tab)}>
          <ToggleGroupItem value="active">Active</ToggleGroupItem>
          <ToggleGroupItem value="cancelled">Cancelled</ToggleGroupItem>
          <ToggleGroupItem value="not">Not a subscription</ToggleGroupItem>
        </ToggleGroup>
        <Button size="pill" variant="outline" className="ml-auto" disabled={busy === 'scan'} onClick={scan}>{busy === 'scan' ? <Loader2 className="animate-spin" /> : <RotateCw />}Check again</Button>
      </div>
      <Card className="divide-y">
        {!list.length && <div className="text-muted-foreground p-4 text-sm">{tab === 'active'
          ? 'No subscriptions found yet. Axella lists a vendor after three regular charges in Receipts, or one renewal, trial or price mail.'
          : 'Nothing here.'}</div>}
        {rows.map(r => 'group' in r
          ? <StoreRows key={'store:' + r.group} store={r.group} g={v.stores?.[r.group]} subs={r.subs} busy={busy} projects={projects}
              onSet={set} onGroup={(b, m) => set({ id: 'store:' + r.group, vendor: (MANAGE[r.group]?.name || r.group) + ' defaults' } as Sub, b, m)} />
          : <SubRow key={r.s.id} s={r.s} busy={busy === r.s.id} projects={projects} onSet={(b, m) => set(r.s, b, m)} />)}
      </Card>
      <p className="text-muted-foreground text-xs">Found by Axella on the Mac mini from your receipts and from renewal, trial and price mails – nothing is sent anywhere. Axella never cancels, pays or changes a subscription; “Open account page” and “Manage in …” open the vendor’s or store’s own page on your device. Last check {v.last_scan ? new Date(v.last_scan).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '–'}.</p>
    </div>
  )
}

function StoreRows({ store, g, subs, busy, projects, onSet, onGroup }: { store: string; g?: StoreGroup; subs: Sub[]; busy: string | null
  projects: { id: string; name: string }[]; onSet: (s: Sub, b: Record<string, unknown>, msg: string) => void; onGroup: (b: Record<string, unknown>, msg: string) => void }) {
  const [open, setOpen] = useState(false)
  const m = MANAGE[store]
  const name = m?.name || g?.name || store
  const items = subs.filter(s => s.source === 'store').length
  const month: Record<string, number> = {}
  subs.filter(s => s.status === 'active' && !s.gone && !s.superseded && s.monthly && s.currency).forEach(s => { month[s.currency!] = (month[s.currency!] || 0) + s.monthly! })
  const [company, setCompany] = useState(g?.tags.company || '')
  const cx = g?.tags.ctx || 'private'
  return <div data-store-group={store}>
    <button type="button" className="hover:bg-muted/50 flex w-full items-center gap-3 px-4 py-3 text-left" aria-expanded={open} onClick={() => setOpen(!open)}>
      <div className="bg-muted flex size-9 shrink-0 items-center justify-center rounded-lg">{open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}</div>
      <div className="min-w-0 flex-1"><div className="font-medium">{name} · {items} subscription{items === 1 ? '' : 's'}</div>
        <div className="text-muted-foreground text-xs">One charge from {name} is several things – here one row per item on the receipt.</div></div>
      <div className="text-right font-mono text-[14px] tabular-nums">{Object.entries(month).map(([c, n]) => <div key={c}>{money(n, c)}<span className="text-ink-3"> /month</span></div>)}</div>
    </button>
    {open && <div className="bg-muted/20 divide-y border-t">
      {[...subs].sort((a, b) => Number(!!a.store_other) - Number(!!b.store_other)).map(s => <SubRow key={s.id} s={s} busy={busy === s.id} projects={projects} onSet={(b, msg) => onSet(s, b, msg)} inGroup />)}
      <div className="flex flex-wrap items-center gap-1.5 px-4 py-2.5 pl-12" data-store-defaults="">
        {m && <Button size="pill" variant="outline" asChild><a href={m.url} target="_blank" rel="noopener noreferrer"><ExternalLink />Manage in {m.name}</a></Button>}
        <span className="text-ink-3 ml-auto text-xs">New items get:</span>
        <Button size="icon-pill" variant="ghost" title={cx === 'work' ? 'Work – tap for Private' : 'Private – tap for Work'} aria-label="Work or private for new items"
          onClick={() => onGroup({ ctx: cx === 'work' ? 'private' : 'work' }, `New ${name} items → ${cx === 'work' ? 'Private' : 'Work'}`)}>{cx === 'work' ? <Briefcase /> : <Home />}</Button>
        <NativeSelect value={g?.tags.project || ''} onChange={e => onGroup({ project: e.target.value || null }, 'Saved for new items')} className="h-8 w-40 text-xs" aria-label="Project for new items">
          <option value="">No project</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </NativeSelect>
        <Input value={company} onChange={e => setCompany(e.target.value)} onBlur={() => company !== (g?.tags.company || '') && onGroup({ company }, 'Saved for new items')}
          placeholder="Company tag" aria-label="Company tag for new items" maxLength={40} className="h-8 w-36 text-xs" />
      </div>
    </div>}
  </div>
}

function SubRow({ s, busy, projects, onSet, inGroup }: { s: Sub; busy: boolean; projects: { id: string; name: string }[]; onSet: (b: Record<string, unknown>, msg: string) => void; inGroup?: boolean }) {
  const [company, setCompany] = useState(s.company || '')
  const cx = ctxOfSub(s)
  const m = s.store ? MANAGE[s.store] : undefined
  return <div className="space-y-2 px-4 py-3" data-sub={s.id}>
    <div className="flex flex-wrap items-start gap-x-3 gap-y-1.5">
      <div className="bg-muted flex size-9 shrink-0 items-center justify-center rounded-lg"><Recurring className="size-4" /></div>
      <div className="min-w-0 flex-1 basis-[14rem]">
        <div className="flex flex-wrap items-center gap-1.5"><span className="truncate font-medium">{s.vendor}</span>
          {s.quiet && s.status === 'active' && <Badge variant="outline" className="py-px">not seen for a while – possibly cancelled</Badge>}
          {s.source === 'mail' && <Badge variant="outline" className="py-px">from a mail</Badge>}
          {s.superseded && <Badge variant="outline" className="py-px">before itemised receipts – not counted</Badge>}</div>
        {s.store_other && <div className="text-ink-3 text-xs">Charges from {s.store_name || 'the store'} whose receipt shows no item lines. Goes away once three months are itemised.</div>}
        <div className="text-muted-foreground text-xs">
          {s.plan ? s.plan + ' · ' : ''}{s.trial_ends ? `free trial until ${day(s.trial_ends)} · ` : ''}{s.interval ? 'Every ' + PER[s.interval] : 'Interval not known yet'} · next {day(s.next)} · first seen {day(s.first_seen)}{s.count ? ` · ${s.count} charge${s.count === 1 ? '' : 's'}` : ''}</div>
      </div>
      <div className="text-right">
        <div className="font-mono text-[14px] tabular-nums">{s.amount != null ? money(s.amount, s.currency) : '–'}{s.interval ? <span className="text-ink-3"> /{PER[s.interval]}</span> : null}</div>
        {s.interval && s.interval !== 'monthly' && s.monthly != null && <div className="text-ink-3 font-mono text-[12px] tabular-nums">≈ {money(s.monthly, s.currency)} /month</div>}
      </div>
    </div>
    <div className="flex flex-wrap items-center gap-1.5 pl-12">
      {s.status !== 'active' && <Button size="pill" variant="outline" disabled={busy} onClick={() => onSet({ status: 'active' }, `Keeping ${s.vendor}`)}><Check />Keep</Button>}
      {s.status === 'active' && <Button size="pill" variant="outline" disabled={busy} onClick={() => onSet({ status: 'cancelled' }, `${s.vendor} marked cancelled`)}><X />Mark cancelled</Button>}
      {s.status !== 'not' && <Button size="pill" variant="ghost" disabled={busy} onClick={() => onSet({ status: 'not' }, `${s.vendor} is not a subscription`)}>Not a subscription</Button>}
      {m && !inGroup ? <Button size="pill" variant="outline" asChild><a href={m.url} target="_blank" rel="noopener noreferrer"><ExternalLink />Manage in {m.name}</a></Button>
        : !m && s.account_link && <Button size="pill" variant="outline" asChild><a href={s.account_link} target="_blank" rel="noopener noreferrer"><ExternalLink />Open account page</a></Button>}
      <span className="ml-auto" />
      <Button size="icon-pill" variant="ghost" title={cx === 'work' ? 'Work – tap for Private' : 'Private – tap for Work'} aria-label="Work or private" disabled={busy}
        onClick={() => onSet({ ctx: cx === 'work' ? 'private' : 'work' }, `${s.vendor} → ${cx === 'work' ? 'Private' : 'Work'}`)}>{cx === 'work' ? <Briefcase /> : <Home />}</Button>
      <NativeSelect value={s.project || ''} onChange={e => onSet({ project: e.target.value || null }, 'Project saved')} className="h-8 w-40 text-xs" aria-label="Project">
        <option value="">No project</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
      </NativeSelect>
      <Input value={company} onChange={e => setCompany(e.target.value)} onBlur={() => company !== (s.company || '') && onSet({ company }, company ? 'Company tag saved' : 'Company tag removed')}
        placeholder="Company tag" aria-label="Company tag" maxLength={40} className={cn('h-8 w-36 text-xs')} />
    </div>
  </div>
}

function Stat({ label, value }: { label: string; value: string }) {
  return <Card className="p-3"><div className="text-muted-foreground text-xs font-medium tracking-wide uppercase">{label}</div>
    <div className="mt-1 truncate font-mono text-lg font-medium tabular-nums">{value}</div></Card>
}
