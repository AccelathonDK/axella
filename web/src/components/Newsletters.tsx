import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { AlertTriangle, BellOff, Check, ChevronRight, Eye, EyeOff, Loader2, Mail, MousePointerClick, Newspaper, Pause, Play, Search, ShieldCheck, X } from '@/components/ax-icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { get, post } from '@/lib/api'
import { useApp } from '@/lib/app'
import type { QuietSuggestion, Sender } from '@/lib/types'
import { cn } from '@/lib/utils'
import { accLabel } from '@/lib/profile'

const day = (d?: string) => d ? new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : '–'

export function NewslettersView() {
  const { ax } = useApp()
  const [senders, setSenders] = useState<Sender[] | null>(null)
  const [meta, setMeta] = useState<{ last_scan?: string; days?: number; status?: { at: string; state: string; message: string } | null }>({})
  const [tab, setTab] = useState<'active' | 'unsubscribed' | 'kept' | 'held'>('active')
  const [quiet, setQuiet] = useState<QuietSuggestion | null>(null)
  const [safe, setSafe] = useState<string[]>([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const load = () => get<{ senders: Sender[]; last_scan?: string; days?: number; status?: { at: string; state: string; message: string } | null; quiet?: QuietSuggestion; safe?: string[] }>('senders')
    .then(j => { setSenders(j.senders); setMeta({ last_scan: j.last_scan, days: j.days, status: j.status }); setQuiet(j.quiet || null); setSafe(j.safe || []) }).catch(() => setSenders([]))
  useEffect(() => { load() }, [])

  const list = useMemo(() => (senders || []).filter(s => (tab === 'held' ? !!s.hold : s.status === tab && !s.manual) && (!q || (s.name + s.address).toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => b.count - a.count), [senders, tab, q])
  // one company, many addresses (LinkedIn: invitations@, updates-noreply@, messages-noreply@ …) → one group
  const groups = useMemo(() => {
    const m = new Map<string, Sender[]>()
    list.forEach(s => { const k = orgOf(s); m.set(k, [...(m.get(k) || []), s]) })
    return [...m.entries()].map(([k, ss]) => ({ key: k, name: orgName(k, ss), senders: ss, count: ss.reduce((n, s) => n + s.count, 0),
      unread: ss.reduce((n, s) => n + s.unread, 0), last: ss.map(s => s.last_at || '').sort().pop() }))
      .sort((a, b) => b.count - a.count)
  }, [list])
  const [openGroup, setOpenGroup] = useState<string | null>(null)
  const active = (senders || []).filter(s => s.status === 'active' && !s.manual)
  const activeOrgs = new Set(active.map(orgOf)).size          // the Senders stat counts rows (companies), like the list
  // the Active tab without a search shows exactly these rows – the stats and the list can't disagree
  const shownActive = tab === 'active' && !q ? groups : null
  // counted per row (company), like the Senders stat and the list
  const never = [...active.reduce((m, s) => { const k = orgOf(s), g = m.get(k) || { count: 0, unread: 0 }; g.count += s.count; g.unread += s.unread; return m.set(k, g) }, new Map<string, { count: number; unread: number }>()).values()]
    .filter(g => g.count >= NEVER_MIN && g.unread === g.count).length
  const total = active.reduce((n, s) => n + s.count, 0)

  async function unsubscribe(s: Sender) {
    setBusy(s.address)
    try {
      const j = await post<{ result: { method: string; message: string; url?: string } }>('sender_unsubscribe', { address: s.address })
      if (j.result.url) window.open(j.result.url, '_blank', 'noopener')
      toast(j.result.message, { duration: 7000 }); await load()
    } catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(null) }
  }
  async function unsubscribeAll(ss: Sender[]) {
    const oc = ss.filter(s => s.unsub?.one_click)
    setBusy('group:' + orgOf(ss[0])); let ok = 0
    for (const s of oc) { try { await post('sender_unsubscribe', { address: s.address }); ok++ } catch { /* next */ } }
    const left = ss.length - oc.length
    toast(`Unsubscribed from ${ok} of ${oc.length}` + (left ? ` – ${left} need${left === 1 ? 's' : ''} its own tap (email or web page)` : ''), { duration: 7000 })
    await load(); setBusy(null)
  }
  async function hold(s: { address: string; name: string }, h: boolean) {
    try { await post('sender_hold', { address: s.address, name: s.name, hold: h, title: s.name }); toast(h ? `${s.name} is held – not in your digests from the next one` : `${s.name} is back in your digests`); await load() }
    catch (e: any) { toast.error('Failed: ' + e.message) }
  }
  async function unflag(addr: string) {
    try { await post('safety_unmark_safe', { sender: addr, title: addr }); toast('The scam check looks at this sender again'); await load() }
    catch (e: any) { toast.error('Failed: ' + e.message) }
  }
  async function keep(s: Sender, k: boolean) {
    try { await post('sender_keep', { address: s.address, keep: k }); toast(k ? `Keeping ${s.name}` : 'Moved back'); await load() }
    catch (e: any) { toast.error('Failed: ' + e.message) }
  }

  return (
    <div className="space-y-4">
      <div><h1 className="text-xl font-semibold tracking-tight">Newsletters</h1>
        <p className="text-muted-foreground text-sm">Everyone sending you newsletters and marketing (all your mailboxes), from the last {meta.days || 90} days. Unsubscribe in one tap – Axella only uses the sender’s official unsubscribe, never links from the mail itself.</p></div>
      {senders === null ? <div className="text-muted-foreground flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" />Loading…</div>
        : !senders.length ? <Card className="text-muted-foreground p-4 text-sm">{meta.last_scan ? 'No newsletters found.' : meta.status?.state === 'error'
          ? `Scan failed at ${new Date(meta.status.at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })} – retrying every 30 min. (${meta.status.message})`
          : 'Scanning your mailboxes in 2-day steps, newest first – the first senders show up after the first step (a few minutes).'}</Card>
        : <>
          {quiet && !quiet.dismissed && quiet.senders.length > 0 && <QuietCard q={quiet} senders={senders} busy={busy} onUnsub={unsubscribe} onHold={hold} onKeep={keep}
            onDismiss={async () => { try { await post('senders_quiet_dismiss', { title: 'never opened' }); await load() } catch (e: any) { toast.error('Failed: ' + e.message) } }} />}
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Senders" value={shownActive ? shownActive.length : activeOrgs} />
            <Stat label={`Mails (${meta.days || 90} d)`} value={shownActive ? shownActive.reduce((n, g) => n + g.count, 0) : total} />
            <Stat label={`Never opened (${NEVER_MIN}+ mails)`} value={never} accent />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <ToggleGroup type="single" value={tab} onValueChange={(v: string) => v && setTab(v as typeof tab)}>
              <ToggleGroupItem value="active">Active</ToggleGroupItem>
              <ToggleGroupItem value="unsubscribed">Unsubscribed</ToggleGroupItem>
              <ToggleGroupItem value="kept">Kept</ToggleGroupItem>
              <ToggleGroupItem value="held">Held</ToggleGroupItem>
            </ToggleGroup>
            <div className="relative min-w-40 flex-1"><Search className="text-muted-foreground absolute top-2 left-2.5 size-4" />
              <Input value={q} onChange={e => setQ(e.target.value)} placeholder="Sender" className="pl-8" /></div>
          </div>
          <Card className="divide-y">
            {!list.length && <div className="text-muted-foreground p-4 text-sm">{tab === 'held' ? 'Nobody is held. “Always hold” (here, or in an item’s ⋯ menu) keeps a sender’s mail out of your digests without unsubscribing.' : 'Nothing here.'}</div>}
            {groups.map(g => g.senders.length === 1 ? <SenderRow key={g.key} s={g.senders[0]} busy={busy} onUnsub={unsubscribe} onKeep={keep} onHold={hold} />
              : <div key={g.key}>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
                  <button onClick={() => setOpenGroup(openGroup === g.key ? null : g.key)} aria-expanded={openGroup === g.key} className="flex min-w-0 flex-1 basis-[15rem] items-center gap-3 text-left">
                    <div className="bg-fjord-soft text-fjord flex size-9 shrink-0 items-center justify-center rounded-lg text-sm font-semibold">{g.name.slice(0, 1).toUpperCase()}</div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5"><span className="truncate font-medium">{g.name}</span>
                        <span className="text-ink-3 font-mono text-[12px]">{g.senders.length} addresses</span>
                        {g.count >= NEVER_MIN && g.unread === g.count && <Badge variant="warning" className="py-px" title={`All ${g.count} mails unread (shown from ${NEVER_MIN} mails)`}>never opened</Badge>}</div>
                      <div className="text-muted-foreground truncate text-xs">{g.key} · {g.count} mails · {g.count - g.unread} opened · last {day(g.last)}</div>
                    </div>
                    <ChevronRight className={cn('text-ink-3 size-4 shrink-0 transition-transform duration-[220ms]', openGroup === g.key && 'rotate-90')} />
                  </button>
                  {tab === 'active' && g.senders.some(s => s.unsub?.one_click) && <Button size="pill" variant="outline" disabled={busy === 'group:' + g.key} onClick={() => unsubscribeAll(g.senders)}
                    title="One-click unsubscribe for every address that offers it">{busy === 'group:' + g.key ? <Loader2 className="animate-spin" /> : <BellOff />}Unsubscribe all</Button>}
                </div>
                {openGroup === g.key && <div className="ax-reveal bg-bg-2/40 divide-y border-t pl-6">
                  {g.senders.map(s => <SenderRow key={s.address} s={s} busy={busy} onUnsub={unsubscribe} onKeep={keep} onHold={hold} />)}</div>}
              </div>)}
          </Card>
          {tab === 'held' && safe.length > 0 && <Card className="p-4">
            <div className="text-sm font-medium">Marked safe in the scam check</div>
            <div className="text-muted-foreground mb-2 text-xs">Mail and texts from these senders are never flagged.</div>
            <div className="flex flex-wrap gap-1.5">{safe.map(a => <Badge key={a} variant="outline" className="gap-1 py-0.5">{a}
              <button type="button" aria-label={'Flag ' + a + ' again'} title="Check this sender again" onClick={() => unflag(a)} className="text-ink-3 hover:text-ink"><X className="size-3" /></button></Badge>)}</div>
          </Card>}
          <p className="text-muted-foreground flex items-start gap-1.5 text-xs"><ShieldCheck className="mt-px size-3.5 shrink-0" />
            One-click: the Mac mini tells the sender directly (standard RFC 8058). By email: a draft is saved in Mail for you to send. Web page: the sender’s page opens on your device. A sender still mailing you a week after unsubscribing gets a red mark. Scanned {meta.days || 0} of 90 days · last scan {meta.last_scan ? new Date(meta.last_scan).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '–'}.</p>
        </>}
    </div>
  )
}

function SenderRow({ s, busy, onUnsub, onKeep, onHold }: { s: Sender; busy: string | null; onUnsub: (s: Sender) => void; onKeep: (s: Sender, k: boolean) => void; onHold: (s: Sender, h: boolean) => void }) {
              const u = s.unsub || { https: null, mailto: null, one_click: false }
              const how = u.one_click ? 'One-click' : u.mailto ? 'By email (draft)' : u.https ? 'Web page' : null
              const neverOpened = s.count >= NEVER_MIN && s.unread === s.count
              return <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
                <div className="bg-muted flex size-9 shrink-0 items-center justify-center rounded-lg text-sm font-semibold">{(s.name || s.domain).slice(0, 1).toUpperCase()}</div>
                <div className="min-w-0 flex-1 basis-[13rem]">
                  <div className="flex flex-wrap items-center gap-1.5"><span className="truncate font-medium">{s.name}</span>
                    {neverOpened && <Badge variant="warning" className="py-px">never opened</Badge>}
                    {s.hold && <Badge variant="outline" className="py-px"><Pause />held</Badge>}
                    {!!s.after_unsub && <Badge variant="destructive" className="py-px"><AlertTriangle />still sending</Badge>}</div>
                  <div className="text-muted-foreground truncate text-xs">{s.manual ? s.address + ' · held from a digest' : <>{(s.accounts || [s.account || '']).map(a => accLabel(a)).join(' + ')} · {s.address} · {s.count} mail{s.count > 1 ? 's' : ''} · {s.count - s.unread} opened · last {day(s.last_at)}</>}</div>
                  {s.subjects[0] && <div className="text-muted-foreground truncate text-xs italic">“{s.subjects[0]}”</div>}
                </div>
                <div className="flex items-center gap-1.5">
                  {s.hold
                    ? <Button size="pill" variant="ghost" title="Back in your digests" onClick={() => onHold(s, false)}><Play />Stop holding</Button>
                    : s.status === 'active' && <Button size="icon-pill" variant="ghost" title="Always hold – keep it out of my digests (no unsubscribe)" aria-label="Always hold" onClick={() => onHold(s, true)}><Pause /></Button>}
                  {s.status === 'active' && !s.manual && <>
                    {how ? <Button size="pill" variant="outline" disabled={busy === s.address} onClick={() => onUnsub(s)} title={how}>
                      {busy === s.address ? <Loader2 className="animate-spin" /> : u.one_click ? <BellOff /> : u.mailto ? <Mail /> : <MousePointerClick />}Unsubscribe</Button>
                      : <span className="text-muted-foreground text-xs">no unsubscribe option</span>}
                    <Button size="icon-pill" variant="ghost" title="Keep – I want these" onClick={() => onKeep(s, true)}><Eye /></Button>
                  </>}
                  {s.status === 'unsubscribed' && <span className="text-muted-foreground inline-flex items-center gap-1 text-xs"><Check className="text-success size-3.5" />{s.method === 'mailto-draft' ? 'Draft in Mail – send it' : s.method === 'link' ? 'Page opened' : 'Unsubscribed'} · {day(s.changed_at)}</span>}
                  {s.status === 'kept' && <Button size="pill" variant="ghost" onClick={() => onKeep(s, false)}><EyeOff />Un-keep</Button>}
                </div>
              </div>
}

/* The monthly suggestion: senders you never opened in 3 months (never banks, authorities or insurers – the Mac mini
   leaves those out). Unsubscribe asks once first: it sends the unsubscribe request to the sender. */
function QuietCard({ q, senders, busy, onUnsub, onHold, onKeep, onDismiss }: { q: QuietSuggestion; senders: Sender[]; busy: string | null
  onUnsub: (s: Sender) => void; onHold: (s: { address: string; name: string }, h: boolean) => void; onKeep: (s: Sender, k: boolean) => void; onDismiss: () => void }) {
  const [armed, setArmed] = useState<string | null>(null)
  const top = q.senders.slice(0, 5)
  const one = top[0]
  return <Card className="p-4">
    <div className="flex items-start gap-2">
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">{q.senders.length === 1 ? `You haven’t opened ${one.count} mails from ${one.name} in 3 months` : `${q.senders.length} senders you never open`}</div>
        <div className="text-muted-foreground text-xs">This month’s suggestion – nothing changes until you tap.</div>
      </div>
      <Button size="pill" variant="ghost" onClick={onDismiss}>Not now</Button>
    </div>
    <div className="mt-2 divide-y">
      {top.map(x => {
        const s = senders.find(y => y.address === x.address)
        const canUnsub = !!(s?.unsub && (s.unsub.one_click || s.unsub.mailto || s.unsub.https))
        return <div key={x.address} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2">
          <div className="min-w-0 flex-1 basis-[12rem]"><div className="truncate text-sm font-medium">{x.name}</div>
            <div className="text-muted-foreground truncate text-xs">{x.count} mails, none opened · {x.address}</div></div>
          <div className="flex flex-wrap gap-1.5">
            {s && canUnsub && <Button size="pill" variant="outline" disabled={busy === x.address}
              title="Sends the sender’s official unsubscribe request"
              onClick={() => { if (armed !== x.address) { setArmed(x.address); setTimeout(() => setArmed(a => a === x.address ? null : a), 4000); return } setArmed(null); onUnsub(s) }}>
              {busy === x.address ? <Loader2 className="animate-spin" /> : <BellOff />}{armed === x.address ? 'Tap again – this tells the sender' : 'Unsubscribe'}</Button>}
            <Button size="pill" variant="outline" onClick={() => onHold(x, true)}><Pause />Always hold</Button>
            {s && <Button size="pill" variant="ghost" onClick={() => onKeep(s, true)}><Eye />Keep</Button>}
          </div>
        </div>
      })}
    </div>
  </Card>
}

/* "never opened" needs a little history: one unread mail says nothing yet */
const NEVER_MIN = 2

/* the company behind an address: the last two labels of the domain (three for co.uk-style domains) */
function orgOf(s: Sender) {
  const d = (s.domain || s.address.split('@')[1] || '').toLowerCase().split('.')
  return (d.length > 2 && ['co', 'com', 'org', 'net', 'ac', 'gov'].includes(d[d.length - 2]) && d[d.length - 1].length === 2 ? d.slice(-3) : d.slice(-2)).join('.')
}
function orgName(org: string, ss: Sender[]) {
  const word = org.split('.')[0]
  // a sender name that is the company ("LinkedIn", "LinkedIn Job Alerts") beats person names ("Harindu K.")
  const named = ss.map(s => s.name || '').filter(n => n.toLowerCase().replace(/\s/g, '').includes(word.replace(/-/g, '')))
  if (named.length) return named.sort((a, b) => a.length - b.length)[0]
  return word.charAt(0).toUpperCase() + word.slice(1)
}

function Stat({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return <Card className="p-3"><div className="text-muted-foreground text-xs font-medium tracking-wide uppercase">{label}</div>
    <div className={cn('mt-1 font-mono text-lg font-medium tabular-nums', accent && value > 0 && 'text-fjord')}>{value}</div></Card>
}

export { Newspaper }
