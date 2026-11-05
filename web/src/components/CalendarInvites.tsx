/* Calendar → invitees and online meetings (setup/calendar_online.py, meeting_providers.py, calendar_invites.py).
   The calendar's own server sends the invitations (iCloud for an iCloud calendar, Exchange for the work calendar), so
   people get a real invitation with Accept / Decline. Nothing is sent before the tap on Send invites / Send update /
   Send cancellation. Online meetings come from the services you connected in Settings → Calendar; any of them, or a
   pasted link, can go on any calendar's invitation (Teams only on a work calendar). */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { ExternalLink, Mail, Plus, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Input, NativeSelect } from '@/components/ui/input'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { cn } from '@/lib/utils'

export interface Svc { key: string; label: string; offer: string; state: string; offered: boolean; why?: string | null
  capabilities: { lobby: boolean; passcode: boolean; has_time: boolean; dial_in: boolean; can_send_invites: boolean } }
export interface OnlineCal { title: string; kind: 'work' | 'private'; path: 'icloud' | 'graph' | null; from: string | null; why: string | null
  services: Svc[]; default: string | null; protected: boolean }
export interface ServiceRow { key: string; label: string; state: 'connected' | 'not_connected' | 'not_set_up' | 'needs_approval'; why?: string
  account?: string | null; revoke_page: string; capabilities: Svc['capabilities'] }
export interface OnlineInfo { calendars: OnlineCal[]; services: ServiceRow[]; icloud: boolean; defaults: Record<string, string> }
export interface Person { email: string; name?: string | null }
export type Online = { kind: 'none' } | { kind: 'provider'; provider: string } | { kind: 'link'; url: string }
export interface InviteRec { uid: string; calendar: string; from: string; people: Person[]; join?: { join_url: string; passcode?: string; code?: string; dial_in?: string; provider?: string } | null
  meeting?: string | null; path: 'icloud' | 'graph'; cancelled: boolean; silent_save: boolean; answers?: { email: string; answer: string }[]; line?: string; answers_error?: string }

let cache: Promise<OnlineInfo | null> | null = null
export const loadOnline = (fresh = false) => {
  if (fresh || !cache) cache = get<OnlineInfo>('meeting_services').then(r => (r as any).calendars ? r : null).catch(() => null)
  return cache
}
export function useOnline() {
  const [o, setO] = useState<OnlineInfo | null>(null)
  useEffect(() => { loadOnline().then(setO) }, [])
  return o
}
export const newSendId = () => (crypto as any).randomUUID ? (crypto as any).randomUUID() as string
  : Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('')
export const myZone = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || '' } catch { return '' } }

const EMAIL = /^[^\s@<>",;]+@[^\s@<>",;]+\.[A-Za-z]{2,}$/
interface Contact { address: string; name: string }
let contactsCache: Promise<Contact[]> | null = null

/** Invitees: chips, picked from your contacts or typed. */
export function InviteesField({ value, onChange }: { value: Person[]; onChange: (p: Person[]) => void }) {
  const [text, setText] = useState('')
  const [contacts, setContacts] = useState<Contact[]>([])
  useEffect(() => { (contactsCache ||= get<{ contacts: Contact[] }>('compose_contacts').then(r => r.contacts || []).catch(() => [])).then(setContacts) }, [])
  function add(raw: string) {
    const parts = raw.split(/[,;\s]+/).map(s => s.trim()).filter(Boolean)
    const out = [...value]
    for (const p of parts) {
      if (!EMAIL.test(p)) { toast.error(`Not an address: ${p}`); continue }
      if (out.some(x => x.email.toLowerCase() === p.toLowerCase())) continue
      out.push({ email: p, name: contacts.find(c => c.address === p.toLowerCase())?.name || null })
    }
    onChange(out); setText('')
  }
  return <div data-invitees="">
    <span className="mb-1 block font-medium">Invitees</span>
    {value.length > 0 && <div className="mb-1.5 flex flex-wrap gap-1.5">{value.map(p => <span key={p.email}
      className="bg-bg-2 inline-flex max-w-full items-center gap-1 rounded-full border py-0.5 pr-1 pl-2.5 text-[13px]">
      <span className="truncate">{p.name || p.email}</span>
      <button type="button" aria-label={'Remove ' + (p.name || p.email)} className="text-ink-3 hover:text-ink rounded-full p-0.5" onClick={() => onChange(value.filter(x => x !== p))}><X className="size-3.5" /></button>
    </span>)}</div>}
    <div className="flex gap-1.5">
      <Input list="ax-invite-contacts" type="email" value={text} placeholder="name@example.com" onChange={x => setText(x.target.value)}
        onKeyDown={x => { if ((x.key === 'Enter' || x.key === ',') && text.trim()) { x.preventDefault(); add(text) } }} onBlur={() => text.trim() && add(text)} />
      <Button type="button" variant="outline" size="icon-pill" aria-label="Add invitee" disabled={!text.trim()} onClick={() => add(text)}><Plus /></Button>
    </div>
    <datalist id="ax-invite-contacts">{contacts.map(c => <option key={c.address} value={c.address}>{c.name}</option>)}</datalist>
  </div>
}

/** Online meeting: None, each service offered for this calendar, or Paste a link. */
export function OnlinePicker({ cal, value, onChange }: { cal?: OnlineCal; value: Online; onChange: (o: Online) => void }) {
  const offered = (cal?.services || []).filter(s => s.offered)
  const off = (cal?.services || []).filter(s => !s.offered && s.why && s.state !== 'not_set_up')
  const sel = value.kind === 'provider' ? 'p:' + value.provider : value.kind
  return <div data-online-picker="">
    <span className="mb-1 block font-medium">Online meeting</span>
    <NativeSelect value={sel} onChange={x => {
      const v = x.target.value
      onChange(v === 'none' ? { kind: 'none' } : v === 'link' ? { kind: 'link', url: value.kind === 'link' ? value.url : '' } : { kind: 'provider', provider: v.slice(2) })
    }} aria-label="Online meeting">
      <option value="none">None</option>
      {offered.map(s => <option key={s.key} value={'p:' + s.key}>{s.offer}</option>)}
      <option value="link">Paste a link</option>
    </NativeSelect>
    {value.kind === 'link' && <Input className="mt-1.5" type="url" value={value.url} placeholder="https://… (Teams, Meet, Zoom, FaceTime, Webex)" onChange={x => onChange({ kind: 'link', url: x.target.value })} />}
    {value.kind === 'provider' && <p className="text-ink-3 mt-1 text-[12px]">{(() => {
      const c = offered.find(s => s.key === value.provider)?.capabilities
      const safe = c ? [c.lobby && 'a lobby', c.passcode && 'a passcode'].filter(Boolean).join(' and ') : ''
      return `A new meeting is made on your tap${safe ? ', with ' + safe : ''}. Only the title and the time go to the service.`
    })()}</p>}
    {off.length > 0 && value.kind === 'none' && <p className="text-ink-3 mt-1 text-[12px]">{off.map(s => `${s.label}: ${s.why}`).join(' · ')}</p>}
  </div>
}

/** The confirm step before anything is sent: who gets it, from which account, when. */
export function InviteConfirm({ people, from, title, when, zone, online, busy, onSend, onBack, verb = 'Send invites', alt }: { people: Person[]; from: string; title: string; when: string
  zone: string; online?: string | null; busy: boolean; onSend: () => void; onBack: () => void; verb?: string; alt?: { label: string; onClick: () => void } }) {
  return <div className="space-y-3" data-invite-confirm="">
    <div className="text-lg font-semibold">{verb === 'Send invites' ? 'Send the invitation?' : verb + '?'}</div>
    <div className="bg-bg-2/60 space-y-1.5 rounded-md border px-3 py-2.5 text-[13.5px]">
      <div><b className="font-medium">{title}</b> · {when}</div>
      <div className="text-ink-2">From <span className="font-medium">{from}</span></div>
      <div className="text-ink-2">To {people.map(p => p.name ? `${p.name} (${p.email})` : p.email).join(', ')}</div>
      {online && <div className="text-ink-2">{online}</div>}
      <div className="text-ink-3 text-[12px]">Sent with your time zone{zone ? ` (${zone})` : ''} – each person's calendar shows it in their own time.</div>
    </div>
    <div className="flex flex-wrap justify-end gap-2">
      <Button type="button" variant="ghost" onClick={onBack} disabled={busy}>Back</Button>
      {alt && <Button type="button" variant="outline" onClick={alt.onClick} disabled={busy} data-save-silent="">{alt.label}</Button>}
      <Button type="button" onClick={onSend} disabled={busy} data-send-invites=""><Mail />{verb}</Button>
    </div>
  </div>
}

const WORD: Record<string, string> = { accepted: 'text-fjord', declined: 'text-dawn', maybe: 'text-ink-2', none: 'text-ink-3' }

/** On the event sheet: who was invited by Axella, their answers, the join link – and Send cancellation. */
export function InviteStatus({ e, onEdit, onCancelled, onFound }: { e: { calendar: string; title: string; start: string; url?: string | null }
  onEdit: (r: InviteRec) => void; onCancelled: () => void; onFound?: (found: boolean) => void }) {
  const { ax } = useApp()
  const [r, setR] = useState<InviteRec | null | undefined>(undefined)
  const [asking, setAsking] = useState(false), [alsoMeeting, setAlsoMeeting] = useState(true), [busy, setBusy] = useState(false)
  const [sid] = useState(newSendId)
  useEffect(() => {
    const q = new URLSearchParams({ calendar: e.calendar, title: e.title, start: e.start, url: e.url || '' })
    get<{ invite: InviteRec | null }>('cal_invite_for?' + q).then(x => { setR(x.invite || null); onFound?.(!!x.invite) }).catch(() => setR(null))
  }, [e.calendar, e.title, e.start, e.url])
  if (!r) return null
  async function cancel() {
    setBusy(true)
    try {
      await ax.act('cal_invite_cancel', { uid: r!.uid, confirm: 'send', send_id: sid, delete_meeting: !!r!.meeting && alsoMeeting, title: e.title }, [])
      toast.success('Cancellation sent – ' + e.title); onCancelled()
    } catch (x: any) { toast.error('Not cancelled: ' + x.message) } finally { setBusy(false) }
  }
  return <div className="space-y-2 rounded-md border px-3 py-2.5 text-[13.5px]" data-invite-status="">
    <div className="text-ink-3 text-[12px]">Invited by Axella from {r.from}{r.cancelled ? ' · cancelled' : ''}</div>
    {r.answers?.length ? <ul className="space-y-0.5">{r.answers.map(a => {
      const p = r.people.find(x => x.email.toLowerCase() === a.email.toLowerCase())
      return <li key={a.email} className="flex gap-2"><span className="min-w-0 flex-1 truncate">{p?.name || a.email}</span>
        <span className={cn('shrink-0', WORD[a.answer])}>{a.answer === 'none' ? "hasn't answered" : a.answer === 'maybe' ? 'maybe' : a.answer}</span></li>
    })}</ul> : r.answers_error ? <div className="text-ink-3">{r.answers_error}</div> : null}
    {!r.cancelled && <div className="flex flex-wrap items-center gap-2 pt-1">
      <Button size="pill" variant="outline" onClick={() => onEdit(r)}>Change…</Button>
      {!asking ? <Button size="pill" variant="ghost" className="ml-auto" onClick={() => setAsking(true)}>Cancel the meeting</Button>
        : <span className="ml-auto flex flex-wrap items-center gap-2">
            {r.meeting && <label className="flex items-center gap-1.5 text-[12.5px]"><input type="checkbox" checked={alsoMeeting} onChange={x => setAlsoMeeting(x.target.checked)} />Also delete the online meeting</label>}
            <Button size="pill" variant="ghost" onClick={() => setAsking(false)} disabled={busy}>Keep it</Button>
            <Button size="pill" variant="destructive" onClick={cancel} disabled={busy} data-send-cancel=""><Mail />Send cancellation</Button></span>}
    </div>}
  </div>
}

/* ---------- Settings → Calendar ---------- */
const STATE: Record<string, string> = { connected: 'Connected', not_connected: 'Not connected', not_set_up: 'Not set up', needs_approval: 'Waiting for your IT' }

export function MeetingServicesCard() {
  const { ax } = useApp()
  const [o, setO] = useState<OnlineInfo | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const reload = () => loadOnline(true).then(setO)
  useEffect(() => {
    reload()
    const q = new URLSearchParams(location.search)
    if (q.get('connected')) toast.success('Connected')
    if (q.get('connect_error')) toast.error(q.get('connect_error')!)
    if (q.get('connected') || q.get('connect_error')) {
      const u = new URL(location.href); u.searchParams.delete('connected'); u.searchParams.delete('connect_error'); history.replaceState(null, '', u)
    }
  }, [])
  async function connect(k: string) {
    setBusy(k)
    try { const r: any = await ax.act('meeting_service_connect', { provider: k }, []); const url = r?.result?.url || r?.url; if (url) location.href = url }
    catch (x: any) { toast.error(x.message); setBusy(null) }
  }
  async function disconnect(s: ServiceRow) {
    setBusy(s.key)
    try { await ax.act('meeting_service_disconnect', { provider: s.key }, []); toast(`${s.label} disconnected – also remove Axella's access on its own page`); window.open(s.revoke_page, '_blank', 'noopener'); reload() }
    catch (x: any) { toast.error(x.message) } finally { setBusy(null) }
  }
  async function setDefault(cal: string, provider: string) {
    try { await ax.act('meeting_service_default', { calendar: cal, provider: provider || null }, []); reload() } catch (x: any) { toast.error(x.message) }
  }
  if (!o) return <div className="text-ink-3 text-sm">Loading…</div>
  return <div className="space-y-4">
    <div className="bg-card divide-y overflow-hidden rounded-lg border" data-meeting-services="">
      <div className="px-4 py-2.5"><div className="font-semibold">Meeting services</div>
        <div className="text-ink-3 text-[12.5px]">Each one is your own app registration (SETUP "Meeting services"); the sign-in stays in the Mac mini's Keychain. Only a meeting's title and time are sent.</div></div>
      {o.services.map(s => <div key={s.key} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-3" data-service={s.key}>
        <div className="min-w-0 flex-1 basis-[14rem]">
          <div className="font-medium">{s.label} <span className={cn('ml-1 text-[12.5px] font-normal', s.state === 'connected' ? 'text-fjord' : 'text-ink-3')}>{STATE[s.state] || s.state}{s.account ? ' · ' + s.account : ''}</span></div>
          <div className="text-ink-3 text-[12.5px]">{[s.capabilities.lobby && 'lobby', s.capabilities.passcode && 'passcode', s.capabilities.dial_in && 'dial-in',
            !s.capabilities.has_time && 'no time – the link can\'t be moved or deleted', s.key === 'teams' && 'work accounts only'].filter(Boolean).join(' · ')}</div>
          {s.why && s.state !== 'connected' && <div className="text-ink-3 text-[12.5px]">{s.why}</div>}
        </div>
        {s.state === 'connected' || s.state === 'needs_approval'
          ? <Button size="pill" variant="ghost" disabled={busy === s.key} onClick={() => disconnect(s)}>Disconnect</Button>
          : <Button size="pill" variant="outline" disabled={busy === s.key || s.state === 'not_set_up'} onClick={() => connect(s.key)}><ExternalLink />Connect</Button>}
      </div>)}
      <div className="flex items-center gap-3 px-4 py-3" data-service="icloud">
        <div className="min-w-0 flex-1"><div className="font-medium">iCloud invites <span className={cn('ml-1 text-[12.5px] font-normal', o.icloud ? 'text-fjord' : 'text-ink-3')}>{o.icloud ? 'Set up' : 'Not set up'}</span></div>
          <div className="text-ink-3 text-[12.5px]">iCloud sends the invitations from your iCloud calendars. Set up once in Terminal: tools/meeting-services.py icloud</div></div>
      </div>
    </div>
    <div className="bg-card divide-y overflow-hidden rounded-lg border" data-calendar-defaults="">
      <div className="px-4 py-2.5"><div className="font-semibold">Per calendar</div><div className="text-ink-3 text-[12.5px]">Who invitations go from, and the online meeting New event suggests.</div></div>
      {o.calendars.map(c => <div key={c.title} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-3">
        <div className="min-w-0 flex-1 basis-[12rem]"><div className="font-medium">{c.title} <span className="text-ink-3 text-[12.5px] font-normal">{c.kind === 'work' ? 'Work' : 'Private'}{c.protected ? ' · protected workplace' : ''}</span></div>
          <div className="text-ink-3 text-[12.5px]">{c.path ? 'Invites go from ' + c.from : c.why}</div></div>
        <NativeSelect className="h-8 w-48 text-xs" aria-label={'Default online meeting for ' + c.title} value={c.default || ''} onChange={x => setDefault(c.title, x.target.value)}>
          <option value="">No online meeting</option>
          {c.services.filter(s => s.offered).map(s => <option key={s.key} value={s.key}>{s.offer}</option>)}
        </NativeSelect>
      </div>)}
    </div>
  </div>
}
