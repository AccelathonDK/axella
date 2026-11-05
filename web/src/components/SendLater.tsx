/* Send later (feature pack Nov 2026 §1c): pick a time and the mail waits on the Mac mini; it goes through the same send
   path as Send at that time. Picking the time is the approval – a short Undo follows. The Scheduled card lists what
   waits: change the time or text, send now, cancel. setup/scheduled.py. */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { AlarmClock, Forward as SendIcon, Loader2, Pencil, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { get, post } from '@/lib/api'
import { useApp } from '@/lib/app'
import { cn } from '@/lib/utils'

const at8 = (d: Date) => { const x = new Date(d); x.setHours(8, 0, 0, 0); return x }
export function laterChoices(now = new Date()): [string, Date][] {
  const tomorrow = at8(new Date(now.getTime() + 864e5))
  const mon = at8(new Date(now)); mon.setDate(mon.getDate() + ((8 - mon.getDay()) % 7 || 7))
  const out: [string, Date][] = [['Tomorrow 08:00', tomorrow]]
  if (mon.getTime() !== tomorrow.getTime()) out.push(['Monday 08:00', mon])
  return out
}
export const fmtAt = (s: string | Date) => new Date(s).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const localInput = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 16)

/** Next to Send: "Send at…" – Tomorrow 08:00, Monday 08:00 or a time you pick. */
export function SendLaterButton({ onSchedule, disabled, to }: { onSchedule: (at: string) => Promise<unknown>; disabled?: boolean; to: string }) {
  const [pick, setPick] = useState(false)
  const [v, setV] = useState(() => localInput(at8(new Date(Date.now() + 864e5))))
  const [busy, setBusy] = useState(false)
  async function go(d: Date) {
    setBusy(true)
    try { await onSchedule(d.toISOString()); setPick(false) } catch (e: any) { toast.error('Not scheduled: ' + e.message) } finally { setBusy(false) }
  }
  return <>
    <DropdownMenu>
      <DropdownMenuTrigger asChild><Button size="pill" variant="outline" disabled={disabled || busy} aria-label="Send later" title="Send later" data-send-later="">
        {busy ? <Loader2 className="animate-spin" /> : <AlarmClock />}<span className="max-sm:hidden">Later</span></Button></DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <div className="text-ink-3 px-2.5 pt-1.5 pb-1 text-[11.5px]">Send to {to} at…</div>
        {laterChoices().map(([l, d]) => <DropdownMenuItem key={l} onSelect={() => go(d)}>{l}<span className="text-ink-3 ml-auto pl-4 font-mono text-[11px]">{d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })}</span></DropdownMenuItem>)}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => setTimeout(() => setPick(true), 100)}>Pick a time…</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
    {pick && <Dialog open onOpenChange={o => !o && setPick(false)}>
      <DialogContent className="sm:w-[min(400px,92vw)]">
        <form className="space-y-3 p-5" onSubmit={e => { e.preventDefault(); if (v) go(new Date(v)) }}>
          <DialogTitle className="text-lg font-semibold">Send later</DialogTitle>
          <Input type="datetime-local" value={v} onChange={e => setV(e.target.value)} aria-label="When" />
          <p className="text-ink-3 text-[12.5px]">It waits on the Mac mini and goes to {to} at that time. If the Mac mini is off then, it goes as soon as it's back.</p>
          <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setPick(false)}>Cancel</Button>
            <Button type="submit" disabled={busy || !v || new Date(v).getTime() < Date.now() + 60e3}><AlarmClock />Schedule</Button></div>
        </form>
      </DialogContent>
    </Dialog>}
  </>
}

/** Schedule one mail or reply; the toast offers Undo (cancels it). */
export async function scheduleSend(action: 'mail_send' | 'reply_send', payload: Record<string, unknown>, at: string, to: string) {
  const { send_id, confirm, ...p } = payload as any   // eslint-disable-line @typescript-eslint/no-unused-vars
  const r = await post<{ result: { id: string; at: string } }>('schedule_send', { action, payload: p, at, title: p.title || p.subject })
  scheduledChanged()
  toast.success(`Goes to ${to} ${fmtAt(r.result.at)}`, {
    description: 'Waiting on the Mac mini – change or cancel it on Today until then.', duration: 10000,
    action: { label: 'Undo', onClick: () => { post('schedule_cancel', { id: r.result.id }).then(() => { scheduledChanged(); toast('Cancelled – nothing will be sent') }).catch(e => toast.error(e.message)) } },
  })
  return r.result
}

interface Sch { id: string; action: string; at: string; status: string; sent_at?: string; late_min?: number; error?: string; title?: string; to?: string; subject?: string; attachments: number; item_id?: string }
const EVT = 'ax-scheduled-changed'
export const scheduledChanged = () => window.dispatchEvent(new CustomEvent(EVT))

/** Today: what waits to be sent later (and what failed or went late lately). Hidden when there is nothing. */
export function ScheduledCard() {
  const { ax } = useApp()
  const [list, setList] = useState<Sch[] | null>(null)
  const [n, setN] = useState(0)
  const [edit, setEdit] = useState<Sch | null>(null)
  const [armed, setArmed] = useState<string | null>(null)
  useEffect(() => {
    if (!ax.apiOk) return
    get<{ scheduled: Sch[] }>('scheduled').then(j => setList(j.scheduled || [])).catch(() => setList([]))
  }, [n, ax.apiOk])
  useEffect(() => {
    const f = () => setN(x => x + 1)
    window.addEventListener(EVT, f)
    const t = setInterval(f, 60e3)                     // a waiting one goes while you look
    return () => { window.removeEventListener(EVT, f); clearInterval(t) }
  }, [])
  const day = 864e5
  const show = (list || []).filter(x => x.status === 'scheduled' || x.status === 'sending'
    || (['failed', 'unknown', 'missed'].includes(x.status) && Date.now() - new Date(x.sent_at || x.at).getTime() < 3 * day)
    || (x.status === 'sent' && (x.late_min || 0) >= 2 && Date.now() - new Date(x.sent_at || x.at).getTime() < day))
  if (!show.length) return null
  async function act(action: string, x: Sch, done: string, extra: Record<string, unknown> = {}) {
    if (armed !== action + x.id) { setArmed(action + x.id); setTimeout(() => setArmed(a => a === action + x.id ? null : a), 5000); return }
    setArmed(null)
    try { await post(action, { id: x.id, title: x.title, ...extra }); toast(done); setN(k => k + 1) } catch (e: any) { toast.error(e.message) }
  }
  return <Card className="overflow-hidden" data-scheduled-card="">
    <div className="flex items-center border-b px-4 py-2.5"><span className="ax-label">Send later</span>
      <span className="text-ink-3 ml-auto font-mono text-[12px]">{show.filter(x => x.status === 'scheduled').length} waiting</span></div>
    <div className="divide-y">{show.map(x => <div key={x.id} className="flex flex-wrap items-center gap-x-2 gap-y-1 px-4 py-2" data-scheduled="">
      <AlarmClock className={cn('size-4 shrink-0', ['failed', 'unknown', 'missed'].includes(x.status) ? 'text-dawn' : 'text-ink-3')} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{x.subject || x.title || '(no subject)'}</span>
        <span className="text-ink-3 block truncate text-[12.5px]">To {x.to || 'them'} · <span className="font-mono text-[12px]">{fmtAt(x.at)}</span>
          {x.status === 'sending' ? ' · sending…' : x.status === 'sent' ? ` · sent ${x.late_min} min late` : x.status === 'failed' ? ' · not sent: ' + (x.error || '') : x.status === 'unknown' ? ' · may have gone – check Sent in Mail' : x.status === 'missed' ? ' · missed its time – not sent' : ''}
          {x.attachments ? ` · ${x.attachments} attachment${x.attachments === 1 ? '' : 's'}` : ''}</span>
      </span>
      {x.status === 'failed' && <Button size="pill" variant={armed === 'schedule_now' + x.id ? 'default' : 'outline'} onClick={() => act('schedule_now', x, 'Trying again…')}>
        {armed === 'schedule_now' + x.id ? 'Send now?' : 'Try again'}</Button>}
      {x.status === 'unknown' && <Button size="pill" variant={armed === 'schedule_now' + x.id ? 'default' : 'outline'} onClick={() => act('schedule_now', x, 'Trying again…', { checked_sent: true })}
        title="Mail may have sent it already – look in Sent first">{armed === 'schedule_now' + x.id ? 'Not in Sent – send it' : 'Checked Sent?'}</Button>}
      {x.status === 'missed' && <span className="flex shrink-0 gap-1">
        <Button size="pill" variant={armed === 'schedule_now' + x.id ? 'default' : 'outline'} onClick={() => act('schedule_now', x, 'Sending now…')}><SendIcon />{armed === 'schedule_now' + x.id ? 'Send now?' : 'Send now'}</Button>
        <Button size="pill" variant="outline" onClick={() => setEdit(x)}><Pencil />New time</Button>
        <button onClick={() => act('schedule_cancel', x, 'Cancelled – nothing will be sent')} className={cn('rounded px-1.5 text-[12.5px]', armed === 'schedule_cancel' + x.id ? 'text-danger font-medium' : 'text-ink-3 hover:text-ink')} aria-label="Cancel">
          {armed === 'schedule_cancel' + x.id ? 'Cancel?' : <X className="size-4" />}</button></span>}
      {x.status === 'scheduled' && <span className="flex shrink-0 gap-1">
        <Button size="pill" variant="ghost" onClick={() => setEdit(x)} aria-label="Change"><Pencil /></Button>
        <Button size="pill" variant={armed === 'schedule_now' + x.id ? 'default' : 'outline'} onClick={() => act('schedule_now', x, 'Sending now…')}><SendIcon />{armed === 'schedule_now' + x.id ? 'Send now?' : 'Now'}</Button>
        <button onClick={() => act('schedule_cancel', x, 'Cancelled – nothing will be sent')} className={cn('rounded px-1.5 text-[12.5px]', armed === 'schedule_cancel' + x.id ? 'text-danger font-medium' : 'text-ink-3 hover:text-ink')} aria-label="Cancel">
          {armed === 'schedule_cancel' + x.id ? 'Cancel?' : <X className="size-4" />}</button>
      </span>}
    </div>)}</div>
    {edit && <EditScheduled x={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); setN(k => k + 1) }} />}
  </Card>
}

function EditScheduled({ x, onClose, onDone }: { x: Sch; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState<{ text: string; subject: string; at: string } | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { get<{ text: string; subject: string }>('scheduled_text?id=' + encodeURIComponent(x.id)).then(j => setF({ text: j.text, subject: j.subject, at: localInput(new Date(x.at).getTime() > Date.now() + 120e3 ? new Date(x.at) : at8(new Date(Date.now() + 864e5))) })).catch(e => { toast.error(e.message); onClose() }) }, [x])
  async function save() {
    setBusy(true)
    try {
      await post('schedule_update', { id: x.id, title: x.title, at: new Date(f!.at).toISOString(), text: f!.text, ...(x.action === 'mail_send' ? { subject: f!.subject } : {}) })
      toast('Changed – goes ' + fmtAt(new Date(f!.at))); onDone()
    } catch (e: any) { toast.error(e.message) } finally { setBusy(false) }
  }
  return <Dialog open onOpenChange={o => !o && onClose()}>
    <DialogContent className="sm:w-[min(620px,92vw)]">
      <div className="space-y-3 p-5">
        <DialogTitle className="text-lg font-semibold">Send later · to {x.to}</DialogTitle>
        {!f ? <p className="text-ink-3 flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" />Loading…</p> : <>
          <label className="block text-sm"><span className="mb-1 block font-medium">When</span><Input type="datetime-local" value={f.at} onChange={e => setF({ ...f, at: e.target.value })} /></label>
          {x.action === 'mail_send' && <label className="block text-sm"><span className="mb-1 block font-medium">Subject</span><Input value={f.subject} maxLength={300} onChange={e => setF({ ...f, subject: e.target.value })} /></label>}
          <textarea value={f.text} onChange={e => setF({ ...f, text: e.target.value })} rows={Math.min(16, f.text.split('\n').length + 2)} aria-label="Text"
            className="border-line-strong bg-card focus-visible:ring-ring/30 w-full rounded-md border px-3 py-2 text-[16px] leading-relaxed outline-none focus-visible:ring-2 sm:text-sm" />
          <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Close</Button>
            <Button disabled={busy || !f.text.trim() || !f.at} onClick={save}>{busy ? <Loader2 className="animate-spin" /> : <AlarmClock />}Save</Button></div>
        </>}
      </div>
    </DialogContent>
  </Dialog>
}
