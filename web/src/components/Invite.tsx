/* Answer a calendar invitation from the mail it came in: Accept / Maybe / Decline – Send's second tap and 6 s undo,
   like every send. When the invitation is in Calendar on the Mac mini (Exchange, iCloud), Axella presses the answer
   there, so it leaves Calendar's "New" and the account's server replies (setup/calendar_answer.py). Otherwise Axella
   sends the organizer the standard calendar reply through Mail and, on Accept or Maybe, puts the meeting in the
   calendar you pick. setup/invites.py, axella-actions.py invite_respond. */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { CalendarCheck, CalendarDays, ExternalLink, Loader2 } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { NativeSelect } from '@/components/ui/input'
import { SendButton } from '@/components/Send'
import { get, newSendId } from '@/lib/api'
import { useApp } from '@/lib/app'
import { JOIN_RE, startManual } from '@/lib/meetings'
import type { Item } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useCalendarRefresh } from '@/lib/calendarBus'

interface Invite {
  uid: string; summary: string; start: string; end: string; all_day: boolean; location: string; url: string; description: string
  organizer: { email: string; name: string } | null; recurring: boolean; cancelled: boolean
  attendees: { name: string; email: string; partstat: string }[]; me: { email: string; partstat: string } | null
  from_address?: string; calendars: { name: string; label: string; kind: string }[]; calendar: string | null; in_calendar: boolean
  check?: { organizer_domain: string; mail_domain: string; mismatch: boolean; no_reply: boolean }
}
type Resp = 'accepted' | 'tentative' | 'declined'
const LABEL: Record<Resp, string> = { accepted: 'Accept', tentative: 'Maybe', declined: 'Decline' }
const STATUS: Record<string, string> = { ACCEPTED: 'You accepted', TENTATIVE: 'You said maybe', DECLINED: 'You declined', 'NEEDS-ACTION': 'Not answered yet' }

/** Does this mail look like an invitation? The sheet checks for the real calendar part. */
export const looksLikeInvite = (it: Item) => it.channel === 'mail' && !!it.message_id && !!it.account &&
  (!!it.event || /\b(invit|invitation|inviteret|invitasjon|einladung|uitnodiging|meeting request|mødeindkaldelse)/i.test(`${it.headline || ''} ${it.subject || ''} ${it.detail || ''}`))
export const openInvite = (it: Item) => window.dispatchEvent(new CustomEvent('ax-invite', { detail: it }))

export function InviteHost() {
  const [it, setIt] = useState<Item | null>(null)
  useEffect(() => { const h = (e: Event) => setIt((e as CustomEvent).detail); window.addEventListener('ax-invite', h); return () => window.removeEventListener('ax-invite', h) }, [])
  return it ? <InviteSheet key={it.id} it={it} onClose={() => setIt(null)} /> : null
}

function InviteSheet({ it, onClose }: { it: Item; onClose: () => void }) {
  const { ax, go } = useApp()
  const [inv, setInv] = useState<Invite | null>(null)
  const [err, setErr] = useState('')
  const [resp, setResp] = useState<Resp>('accepted')
  const [cal, setCal] = useState('')
  const [done, setDone] = useState<{ response: Resp; calendar?: string | null; via?: string } | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    get<{ invite: Invite }>(`invite?account=${encodeURIComponent(it.account!)}&message_id=${encodeURIComponent(it.message_id!)}`)
      .then(j => { setInv(j.invite); setCal(it.event?.calendar && j.invite.calendars.some(c => c.name === it.event!.calendar) ? it.event.calendar : j.invite.calendar || '') })
      .catch(e => setErr(e.message))
  }, [it])
  const org = inv?.organizer
  const who = (org?.name || org?.email || 'the organizer').split(/\s+/)[0]
  const join = inv ? ([inv.url, inv.location, inv.description].join(' ').match(JOIN_RE) || [null])[0] : null
  const when = inv ? (inv.all_day ? new Date(inv.start).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' }) + ' · all day'
    : `${new Date(inv.start).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })} · ${hm(inv.start)}–${hm(inv.end)}`) : ''
  async function send() {
    const r: any = await ax.act('invite_respond', { account: it.account, message_id: it.message_id, response: resp, item_id: it.id,
      title: (resp === 'declined' ? 'Declined: ' : resp === 'tentative' ? 'Maybe: ' : 'Accepted: ') + inv!.summary,
      calendar: resp === 'declined' ? null : cal || null, in_calendar: inv!.in_calendar, confirm: 'send', send_id: newSendId() }, ['state'])
    const res = r?.result || {}
    if (res.pending) { onClose(); return }               // Mail is still busy – the background toast reports how it ends
    setDone({ response: resp, calendar: res.calendar, via: res.via })
    if (res.via === 'calendar') { toast.success(`${LABEL[resp]} in Calendar – ${who} gets the answer from your calendar`); return }
    toast.success(`${LABEL[resp]} sent to ${who}${res.calendar && !/^(not added|all-day|already)/.test(res.calendar) ? ' – in ' + (inv!.calendars.find(c => c.name === res.calendar)?.label || res.calendar) : ''}`)
  }
  async function prepare() {
    if (!inv) return
    setBusy(true)
    try {
      const id = await startManual(inv.summary, inv.start, {
        end: inv.end, location: inv.location || '', join: join || '',
        attendees: inv.attendees.filter(a => a.email !== inv.me?.email).map(a => ({ name: a.name, email: a.email })),
        mail: { account: it.account, message_id: it.message_id, subject: it.subject || inv.summary, date: it.date || '', from: org ? `${org.name} <${org.email}>` : '' },
      })
      onClose(); go({ kind: 'meeting', id })
    } catch (e: any) { toast.error('Not started: ' + e.message) } finally { setBusy(false) }
  }
  return <Dialog open onOpenChange={o => !o && onClose()}>
    <DialogContent className="sm:w-[min(500px,92vw)]" data-invite-sheet="">
      <div className="space-y-3 overflow-y-auto p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))]">
        <div className="flex items-start gap-2.5 pr-7">
          <CalendarDays className="text-ink-2 mt-1 size-5 shrink-0" />
          <DialogTitle className="text-lg leading-snug font-semibold">{inv?.summary || 'Invitation'}</DialogTitle>
        </div>
        {err ? <p className="text-dawn text-sm">{err}</p> : !inv ? <p className="text-ink-3 flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" />Reading the invitation…</p> : <>
          <div className="text-ink-2 space-y-1 text-sm">
            <div>{when}{inv.recurring && <span className="text-ink-3"> · repeats</span>}</div>
            {inv.location && !JOIN_RE.test(inv.location) && <div>{inv.location}</div>}
            <div className="text-ink-3">From {org?.name || org?.email || 'unknown'}{inv.attendees.length > 1 ? ` · ${inv.attendees.length} invited` : ''}</div>
            <div className={cn('text-[13px]', inv.me?.partstat === 'NEEDS-ACTION' ? 'text-ink-2' : 'text-fjord')}>{inv.me ? STATUS[inv.me.partstat] || inv.me.partstat : `Sent to ${inv.from_address || 'you'}`}</div>
          </div>
          {join && <Button size="pill" variant="outline" asChild><a href={join} target="_blank" rel="noopener noreferrer"><ExternalLink />Join link</a></Button>}
          {inv.cancelled ? <p className="text-dawn text-sm">This meeting was cancelled – there is nothing to answer.</p>
          : done ? <div className="space-y-2 border-t pt-3">
              {done.via === 'calendar' ? <p className="text-sm" data-invite-done="calendar">{LABEL[done.response]} in Calendar on the Mac mini – it has left Calendar's New list, and {org?.name || who} gets the answer from your calendar.</p>
              : <p className="text-sm">{LABEL[done.response]} sent to {org?.name || who}.{done.calendar && done.response !== 'declined' ? ' ' + (done.calendar.startsWith('not added') ? 'The calendar: ' + done.calendar + '.' : done.calendar === 'already in the calendar' ? 'It was already in your calendar.' : done.calendar.startsWith('all-day') ? 'All-day events: add it in Calendar.' : 'It\'s in ' + (inv.calendars.find(c => c.name === done.calendar)?.label || done.calendar) + '.') : ''}</p>}
              <div className="flex flex-wrap gap-2">
                {done.response !== 'declined' && !inv.all_day && <Button size="pill" variant="outline" disabled={busy} onClick={prepare}><CalendarCheck />Prepare the meeting</Button>}
                <Button size="pill" variant="ghost" className="ml-auto" onClick={onClose}>Close</Button>
              </div>
            </div>
          : <div className="space-y-3 border-t pt-3">
              <div className="bg-bg-2 flex rounded-md p-0.5 text-[13.5px]" role="radiogroup" aria-label="Your answer">
                {(['accepted', 'tentative', 'declined'] as Resp[]).map(r => <button key={r} role="radio" aria-checked={resp === r} onClick={() => setResp(r)}
                  className={cn('flex-1 rounded px-3 py-1.5', resp === r ? (r === 'declined' ? 'bg-card text-danger shadow-sm font-medium' : 'bg-fjord text-on-fjord font-medium') : 'text-ink-2')}>{LABEL[r]}</button>)}
              </div>
              {resp !== 'declined' && (inv.in_calendar ? <p className="text-ink-2 text-[13px]">Already in your calendar. If Calendar still lists it under New, Axella answers it there; if you answered it before, the organizer gets a second answer. Nothing is added to the calendar.</p>
                : inv.all_day ? <p className="text-ink-3 text-[13px]">An all-day event – add it in Calendar after answering.</p>
                : <label className="flex items-center gap-2 text-sm"><span className="text-ink-2">Put it in</span>
                    <NativeSelect value={cal} onChange={e => setCal(e.target.value)} aria-label="Calendar" className="h-8 w-auto text-[13px]">
                      <option value="">Don't add it</option>{inv.calendars.map(c => <option key={c.name} value={c.name}>{c.label}</option>)}</NativeSelect></label>)}
              {inv.check?.no_reply && <p className="text-danger text-[13px]" role="alert">The organizer is a no-reply address ({org?.email}) – an answer would go nowhere. Answer in Calendar or on the organizer's own page.</p>}
              {!inv.check?.no_reply && inv.check?.mismatch && <p className="text-dawn text-[13px]" role="alert">Check who this goes to: the mail came from {inv.check.mail_domain}, but your answer goes to {inv.check.organizer_domain}. Send only if you know {org?.email}.</p>}
              <div className="flex items-center gap-2">
                <SendButton to={who} onSend={send} disabled={!ax.apiOk || !!inv.check?.no_reply} />
                <span className="text-ink-3 text-[12px]">{LABEL[resp]} goes to {org?.email} from {inv.me?.email || inv.from_address} – answered in Calendar when it is there.</span>
              </div>
            </div>}
        </>}
      </div>
    </DialogContent>
  </Dialog>
}
const hm = (s: string) => new Date(s).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })

/* ---------- invitations still waiting for an answer (Calendar page, Meetings page, Today) ---------- */
export interface Pending {
  uid: string; summary: string; start: string; end: string; all_day: boolean; location: string; organizer: { email: string; name: string } | null
  account: string; message_id: string; subject: string; date?: string | null; from_name?: string; from_address?: string
}
let pcache: Pending[] | null = null
let ploading: Promise<void> | null = null
const psubs = new Set<() => void>()
function loadPending(fresh = false) {
  if (ploading && !fresh) return ploading
  ploading = get<{ invites: Pending[] }>('invites_pending' + (fresh ? '?fresh=1' : '')).then(j => { pcache = j.invites || [] })
    .catch(() => { pcache = pcache || [] }).finally(() => { ploading = null; psubs.forEach(f => f()) })
  return ploading
}
export function usePendingInvites() {
  const { ax } = useApp()
  const [, tick] = useState(0)
  useEffect(() => { const f = () => tick(x => x + 1); psubs.add(f); if (!pcache && ax.apiOk) loadPending(); return () => { psubs.delete(f) } }, [ax.apiOk])
  useCalendarRefresh(f => { if (ax.apiOk) loadPending(f) })
  return pcache
}
const asItem = (x: Pending): Item => ({ id: 'inv:' + x.uid, section: 'cal', channel: 'mail', account: x.account, message_id: x.message_id,
  subject: x.subject || x.summary, headline: x.summary, date: x.date || undefined, from: { name: x.organizer?.name || x.from_name, address: x.organizer?.email || x.from_address } })
const pWhen = (x: Pending) => x.all_day ? new Date(x.start).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }) + ' · all day'
  : new Date(x.start).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

/** Rows of waiting invitations: Answer opens the Accept sheet, Hide drops one you answered elsewhere. */
export function PendingInvites({ limit, card = true }: { limit?: number; card?: boolean }) {
  const { ax } = useApp()
  const list = usePendingInvites()
  const [armed, setArmed] = useState<string | null>(null)
  if (!list?.length) return null
  const rows = list.slice(0, limit || list.length)
  async function hide(x: Pending) {
    if (armed !== x.uid) { setArmed(x.uid); setTimeout(() => setArmed(a => a === x.uid ? null : a), 3000); return }
    try { await ax.act('invite_dismiss', { uid: x.uid, title: x.summary }, []); loadPending(true); toast('Hidden – it won\'t show as waiting any more') } catch (e: any) { toast.error(e.message) }
  }
  const body = <div className="divide-y">{rows.map(x => <div key={x.uid} className="flex min-h-11 items-center gap-3 px-4 py-2" data-pending-invite="">
    <CalendarDays className="text-fjord size-4 shrink-0" />
    <span className="min-w-0 flex-1">
      <span className="block truncate text-sm font-medium">{x.summary}</span>
      <span className="text-ink-3 block truncate text-[12.5px]"><span className="font-mono text-[12px]">{pWhen(x)}</span> · from {x.organizer?.name || x.from_name || x.organizer?.email}</span>
    </span>
    <button onClick={() => hide(x)} className={cn('shrink-0 text-[12.5px]', armed === x.uid ? 'text-danger font-medium' : 'text-ink-3 hover:text-ink')}>{armed === x.uid ? 'Hide?' : 'Hide'}</button>
    <Button size="pill" onClick={() => openInvite(asItem(x))}><CalendarCheck />Answer</Button>
  </div>)}{list.length > rows.length && <div className="text-ink-3 px-4 py-2 text-[12.5px]">+{list.length - rows.length} more on the Calendar page</div>}</div>
  if (!card) return body
  return <div className="bg-card overflow-hidden rounded-lg border" data-pending-invites="">
    <div className="flex items-center gap-2 border-b px-4 py-2.5"><span className="ax-label">Invitations waiting for your answer</span>
      <span className="text-ink-3 ml-auto font-mono text-[12px]">{list.length}</span></div>
    {body}
  </div>
}
