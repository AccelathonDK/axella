import { useEffect, useRef, useState, type PointerEvent as RPointerEvent } from 'react'
import { toast } from 'sonner'
import { FocusButtons } from '@/components/Blocks'
import { PlanButton } from '@/components/Plan'
import { renewalsNext } from '@/components/Receipts'
import { AlarmClock, ArrowDownRight, Briefcase, CalendarCheck, CalendarPlus, Check, ClipboardCopy, ExternalLink, FolderInput, Hash, Home,
  BellOff, ChevronDown, Eye, Linkedin, Recurring, Star, Loader2, Paperclip, Mail, MessageCircle, MoreHorizontal, PencilLine, Reply, SquarePlus, Trash2, Undo2, UserCircle, axi } from '@/components/ax-icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input, NativeSelect } from '@/components/ui/input'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Unreachable, get, newSendId, post } from '@/lib/api'
import { queue } from '@/lib/outbox'
import { useApp } from '@/lib/app'
import { cals, calLabel, ctxOf, guessEvent, isAutomatedSender, isNoReply, replyLink, senderKey } from '@/lib/data'
import { accLabel } from '@/lib/profile'
import { projColor } from '@/lib/projects'
import { mdInline } from '@/lib/md'
import { CH_ICON, ITEM_ICON } from '@/lib/sections'
import type { Item } from '@/lib/types'
import { IOS, cn, isoDate } from '@/lib/utils'
import type { RowApi } from '@/lib/rows'
import { BasedOn, KnowledgeIcon } from '@/components/Knowledge'
import { openKnowledge } from '@/lib/knowledge'
import { draftLink, loadDrafts, useDrafts } from '@/lib/drafts'
import { isVip, loadVips, useVips } from '@/lib/vips'
import { ItemSheet } from '@/components/ItemSheet'
import { SendButton, type SendPhase } from '@/components/Send'
import { openTaskFrom } from '@/components/TaskFromMail'
import { openNewPrep } from '@/components/Meetings'
import { TeachSheet } from '@/components/Learn'
import { NoteChip, NoteIcon } from '@/components/Notes'
import { itemLinks, openNote, useNoteChips, useNotesOwner } from '@/lib/notes'
import { SendLaterButton, scheduleSend } from '@/components/SendLater'
import { looksLikeInvite, openInvite } from '@/components/Invite'
import { recipientLabel, type Person } from '@/components/Recipients'
import { SafetyBadge, SafetyNote } from '@/components/Safety'
import { subsNext } from '@/components/Subscriptions'

const REPLY_ICON = { linkedin: Linkedin, whatsapp: axi('chat'), signal: axi('chat'), sms: MessageCircle, mail: Mail } as const

export function ItemRow({ it }: { it: Item }) {
  const { ax, go, projectsFor, activeProjects } = useApp()
  const [calOpen, setCalOpen] = useState(false)
  const [preview, setPreview] = useState(false)
  const canPreview = ax.apiOk && it.channel === 'mail' && !!it.message_id && !!it.account
  const canOpen = !it.readonly || canPreview
  const handled = ax.isHandled(it.id)
  const notesOwner = useNotesOwner(ax.apiOk)
  const chips = useNoteChips(ax.current?.name, !!notesOwner && !it.readonly)
  const chip = chips?.items[it.id]
  const Icon = ((it.section === 'p1' || it.section === 'p2') && it.channel && it.channel !== 'mail' && CH_ICON[it.channel]) || ITEM_ICON[it.section]   // a reply item shows its channel, not an envelope
  const Ch = it.channel ? CH_ICON[it.channel] : null
  const who = [it.from?.name, accLabel(it.account)].filter(Boolean).join(' · ')
  const projects = projectsFor(it)
  const since = sinceLabel(it, ax.current?.meta.date)
  const world = ctxOf(it, ax.overrides)
  // leaving animation (design system Motion): show what happened, then the row settles into "Handled"
  const [leave, setLeave] = useState<Leave | null>(null)
  const [gone, setGone] = useState(false)
  // iPhone swipes call the same actions as the buttons – ActionBar fills this in
  const api = useRef<RowApi>({})
  const sw = useRowSwipe(api)
  const onLeave = (l: Leave) => {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) { ax.refresh(['state']); return }
    setLeave(l); setTimeout(() => setGone(true), l.kind === 'done' ? 900 : 650); setTimeout(() => ax.refresh(['state']), l.kind === 'done' ? 1400 : 1150)
  }
  return (
    <div data-item-row={it.id} data-leaving={leave ? '' : undefined}
      className={cn('grid transition-[grid-template-rows,opacity] duration-[480ms] ease-[cubic-bezier(.2,.8,.2,1)]', gone ? 'grid-rows-[0fr] opacity-0' : 'grid-rows-[1fr]')}>
    <div className="relative min-h-0 overflow-hidden">
    {sw.hint && <SwipeHint h={sw.hint} dx={sw.dx} />}
    <div {...sw.handlers} data-noswipe="" style={sw.style}
      className={cn('bg-card relative flex touch-pan-y gap-3 px-4 py-3 transition-[transform,opacity,background-color] duration-[480ms] ease-[cubic-bezier(.2,.8,.2,1)]', handled && 'opacity-50',
      leave?.kind === 'file' && 'translate-x-6', leave?.kind === 'snooze' && 'translate-x-10', leave?.kind === 'trash' && 'bg-danger/10 -translate-x-10')}>
      {leave && leave.kind !== 'done' && <LeaveTag l={leave} />}
      <div className={cn('flex size-9 shrink-0 items-center justify-center rounded-md',
        leave?.kind === 'done' ? 'bg-fjord-soft text-fjord' : world === 'work' ? 'bg-work-soft text-work' : 'bg-private-soft text-private')}
        title={world === 'work' ? 'Work' : 'Private'}>{leave?.kind === 'done' ? <ApproveDraw /> : <Icon className="size-[18px]" />}</div>
      <div className={cn('min-w-0 flex-1 transition-opacity duration-[480ms]', leave && leave.kind !== 'done' && 'opacity-40')}>
        {it.headline && <div className="font-semibold leading-snug">
          {Ch && <Ch className="text-muted-foreground mr-1.5 -mt-0.5 inline size-3.5" />}
          {canOpen
            ? <button className="text-left hover:underline decoration-muted-foreground/50 underline-offset-2" onClick={() => setPreview(true)} title="Open">
                <span className="md-inline" dangerouslySetInnerHTML={{ __html: mdInline(it.headline) }} /></button>
            : <span className="md-inline" dangerouslySetInnerHTML={{ __html: mdInline(it.headline) }} />}
        </div>}
        {(who && !it.readonly || projects.length > 0 || it.in_calendar || it.overdue || it.reminder || since || it.safety || it.world) && <div className="text-muted-foreground mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          {who && !it.readonly && <span>{who}</span>}
          <SafetyBadge it={it} />
          {it.world && <Badge variant="outline" className="py-px" title={`Urgent – shown in this ${it.world === 'work' ? 'private' : 'work'} digest anyway`}>{it.world === 'work' ? 'Work' : 'Private'} · urgent</Badge>}
          {it.in_calendar && <Badge variant="outline" className="py-px font-medium"><CalendarCheck />In calendar</Badge>}
          {it.overdue && <Badge variant="destructive" className="py-px">Overdue</Badge>}
          {it.reminder && <Badge variant="warning" className="py-px">Reminder</Badge>}
          {since && <Badge variant="outline" className="py-px font-medium" title={'First reported ' + new Date(it.first_seen!).toLocaleString('en-GB')}>since {since}</Badge>}
          {projects.map(p => <button key={p.id} onClick={() => go({ kind: 'project', id: p.id })}
            className="text-ink-2 hover:border-line-strong inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-px font-mono text-[11px]">
            <span className="ax-diamond" style={{ color: projColor(activeProjects, p.id), width: 6, height: 6 }} />#{p.tag}</button>)}
        </div>}
        {it.detail && <div className={cn('md-inline mt-0.5 text-[14.5px]', it.headline && 'text-muted-foreground')}
          dangerouslySetInnerHTML={{ __html: mdInline(String(it.detail).replace(/\n/g, ' ')) }} />}
        {it.safety && <SafetyNote it={it} className="mt-2" />}
        {chip && !handled && <NoteChip chip={chip} itemId={it.id} />}
        {it.draft?.text && <div className="bg-bg-2 relative mt-2 rounded-md py-2 pr-11 pl-3 text-sm whitespace-pre-wrap">
          <PencilLine className="text-muted-foreground mr-1.5 -mt-0.5 inline size-3.5" />{it.draft.text}
          <button type="button" title="Copy draft" aria-label="Copy draft" className="text-muted-foreground hover:text-foreground hover:bg-background/60 absolute top-1.5 right-1.5 inline-flex size-8 items-center justify-center rounded-md"
            onClick={() => navigator.clipboard.writeText(it.draft!.text!).then(() => toast('Draft copied'), () => toast.error('Could not copy'))}><ClipboardCopy className="size-4" /></button></div>}
        {it.draft?.text && <BasedOn ids={it.draft.kb} />}
        <ActionBar it={it} handled={handled} onCal={() => setCalOpen(o => !o)} onPreview={canOpen ? () => setPreview(true) : undefined} onLeave={onLeave} api={api} />
        {preview && <ItemSheet it={it} handled={handled} since={since} onClose={() => setPreview(false)} onCal={() => { setPreview(false); setCalOpen(true) }} />}
        {calOpen && <CalendarForm it={it} onClose={() => setCalOpen(false)} />}
      </div>
    </div>
    </div>
    </div>
  )
}

type Leave = { kind: 'done' | 'file' | 'snooze' | 'trash'; label: string }

/* iPhone swipe (design system Motion: settle, no bounce). Right = Done (Filing: move to the suggested folder).
   Left = Tomorrow; a long left swipe = move to the suggested folder. Delete is never a swipe – it stays two taps. */
export type Hint = { side: 'right' | 'left'; label: string; icon: any; tone: 'done' | 'snooze' | 'file'; armed: boolean }
export function useRowSwipe(api: { current: RowApi }) {
  const [dx, setDx] = useState(0)
  const [drag, setDrag] = useState(false)
  const st = useRef({ x: 0, y: 0, id: -1, on: false, w: 1, dx: 0 })
  const plan = (d: number, w: number) => {
    const a = api.current
    const right = a.done ? { fn: a.done, label: 'Done', icon: Check, tone: 'done' as const } : a.file ? { fn: a.file, label: 'Move to ' + a.fileLabel, icon: FolderInput, tone: 'file' as const } : null
    const fileLeft = a.file && right?.tone !== 'file' ? { fn: a.file, label: 'Move to ' + a.fileLabel, icon: FolderInput, tone: 'file' as const } : null
    const snooze = a.snooze ? { fn: a.snooze, label: a.snoozeLabel || 'Tomorrow 07:00', icon: AlarmClock, tone: 'snooze' as const } : null
    const left = -d > w * 0.55 && snooze && fileLeft ? fileLeft : snooze || fileLeft
    return d > 0 ? right && { ...right, side: 'right' as const } : left && { ...left, side: 'left' as const }
  }
  const end = (e: RPointerEvent<HTMLDivElement>) => {
    if (st.current.id !== e.pointerId) return
    const was = st.current.on, d = st.current.dx; st.current.id = -1; st.current.on = false; st.current.dx = 0; setDrag(false)
    if (!was) return
    const p = plan(d, st.current.w)
    setDx(0)                                   // settle back; the row's own leave animation shows what happened
    if (p && Math.abs(d) >= 80 && e.type === 'pointerup') p.fn()
  }
  const handlers = {
    onPointerDown: (e: RPointerEvent<HTMLDivElement>) => {
      if (e.pointerType !== 'touch' || (e.target as HTMLElement).closest('button,a,input,textarea,select,[role=menu]')) return
      st.current = { x: e.clientX, y: e.clientY, id: e.pointerId, on: false, w: e.currentTarget.offsetWidth, dx: 0 }
    },
    onPointerMove: (e: RPointerEvent<HTMLDivElement>) => {
      const s = st.current
      if (s.id !== e.pointerId) return
      const mx = e.clientX - s.x, my = e.clientY - s.y
      if (!s.on) {
        if (Math.abs(mx) > 12 && Math.abs(mx) > Math.abs(my) * 1.5) { s.on = true; setDrag(true); try { e.currentTarget.setPointerCapture(e.pointerId) } catch { /* synthetic or ended pointer */ } }
        else { if (Math.abs(my) > 12) s.id = -1; return }
      }
      s.dx = plan(mx, s.w) ? mx : mx / 6       // nothing that way: a little resistance only
      setDx(s.dx)
    },
    onPointerUp: end, onPointerCancel: end,
  }
  const p = dx ? plan(dx, st.current.w) : null
  const hint: Hint | null = p && Math.abs(dx) > 4 ? { side: p.side, label: p.label, icon: p.icon, tone: p.tone, armed: Math.abs(dx) >= 80 } : null
  return { dx, hint, handlers, style: dx || drag ? { transform: `translateX(${dx}px)`, transition: drag ? 'none' : 'transform 220ms cubic-bezier(.2,.8,.2,1)' } : undefined }
}
export function SwipeHint({ h, dx }: { h: Hint; dx: number }) {
  const I = h.icon
  return <div aria-hidden className={cn('absolute inset-0 flex items-center px-5 text-sm font-medium',
    h.side === 'right' ? 'justify-start' : 'justify-end',
    h.tone === 'done' ? 'bg-fjord text-on-fjord' : h.tone === 'file' ? 'bg-fjord-soft text-fjord' : 'bg-surface-inverse text-on-inverse')}>
    <span className={cn('inline-flex items-center gap-2 transition-opacity duration-[120ms]', h.armed ? 'opacity-100' : 'opacity-50')}
      style={{ maxWidth: Math.max(0, Math.abs(dx) - 16), overflow: 'hidden', whiteSpace: 'nowrap' }}><I className="size-[18px] shrink-0" />{h.label}</span>
  </div>
}
/* the approve mark: the diamond frame draws, then the tick (duration-draw) */
function ApproveDraw() {
  return <svg viewBox="0 0 24 24" className="size-[18px]" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinejoin="miter" aria-hidden>
    <path d="M12 2.5L21.5 12 12 21.5 2.5 12z" pathLength={1} className="ax-draw" />
    <path d="M8.5 12l2.5 2.5 4.5-4.5" pathLength={1} className="ax-draw ax-draw-late" /></svg>
}
function LeaveTag({ l }: { l: Leave }) {
  const I = l.kind === 'file' ? FolderInput : l.kind === 'snooze' ? AlarmClock : Trash2
  return <span className={cn('ax-reveal absolute top-1/2 right-4 z-10 inline-flex -translate-y-1/2 items-center gap-1.5 rounded-sm px-2 py-1 text-xs font-medium shadow-float',
    l.kind === 'trash' ? 'bg-card text-danger border-danger/40 border' : 'bg-card text-ink border')}><I className="size-4" />{l.label}</span>
}

/* Same order for every item type:
   visible: [primary: Reply / Move to … / Add to calendar] [Draft in Mail] [Done] [Tomorrow] …… [⋯]
   ⋯ menu:  Copy draft · Add to calendar · Move to … · Add as task · #projects · Work/Private · Open in Mail · ─ · Delete */
/* "Later": when the item should come back. Swipes keep the quick "tomorrow 07:00". */
export function laterChoices(now = new Date()) {
  const at = (days: number, h: number) => { const d = new Date(now); d.setDate(d.getDate() + days); d.setHours(h, 0, 0, 0); return d }
  const monday = (() => { const d = at(1, 7); while (d.getDay() !== 1) d.setDate(d.getDate() + 1); return d })()
  const out: [string, string, Date][] = []
  if (now.getHours() < 16) out.push(['Later today', '17:00', at(0, 17)])
  if (now.getHours() < 19) out.push(['This evening', '20:00', at(0, 20)])
  out.push(['Tomorrow', '07:00', at(1, 7)])
  if (monday.getTime() - at(1, 7).getTime() > 864e5) out.push(['Monday', '07:00', monday])
  return out
}
export function LaterMenu({ onPick, busy, disabled, label = 'Later', full }: { onPick: (d: Date, label: string) => void; busy?: boolean; disabled?: boolean; label?: string; full?: boolean }) {
  const date = useRef<HTMLInputElement>(null)
  return <span className="relative inline-flex">
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="pill" variant="outline" disabled={disabled} title="Bring it back later">{busy ? <Loader2 className="animate-spin" /> : <AlarmClock />}<span className={full ? '' : 'max-[420px]:hidden'}>{label}</span><ChevronDown className="!size-3.5 opacity-60" /></Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        {laterChoices().map(([l, t, d]) => <DropdownMenuItem key={l} onSelect={() => onPick(d, l.toLowerCase() + ' ' + t)}>
          <span className="flex-1">{l}</span><span className="text-ink-3 font-mono text-[12px]">{t}</span></DropdownMenuItem>)}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => setTimeout(() => { const el = date.current; if (!el) return; try { el.showPicker() } catch { el.focus(); el.click() } }, 50)}>Pick a date…</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
    <input ref={date} type="date" aria-label="Bring it back on" min={isoDate(new Date())} className="pointer-events-none absolute inset-0 opacity-0"
      onChange={e => { if (!e.target.value) return; const d = new Date(e.target.value + 'T07:00'); onPick(d, d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }) + ' 07:00') }} />
  </span>
}

export function ActionBar({ it, handled, onCal, onPreview, onLeave, api, draftText, chatText, onDraftSaved, attachments, attBusy, rcpt, sprint }: { it: Item; handled: boolean; onCal: () => void; onPreview?: () => void; onLeave?: (l: Leave) => void; api?: { current: RowApi }
  draftText?: string; chatText?: string; onDraftSaved?: () => void; attachments?: string[]; attBusy?: boolean; rcpt?: { to: Person[]; cc: Person[]; bcc: Person[] }
  /** Reply sprint: the swipe-right Send, and a reply put in Send later moves on to the next */
  sprint?: { swipeSend: { current: (() => void) | null }; onScheduled: () => void } }) {
  // the composer's To / Cc / Bcc (item sheet) – sent as plain address lists; the Mac mini sets exactly these in Mail
  const lists = rcpt ? { to: rcpt.to.map(p => p.address), cc: rcpt.cc.map(p => p.address), bcc: rcpt.bcc.map(p => p.address) } : null
  const inSheet = draftText !== undefined
  const { ax, go, activeProjects, projectsFor } = useApp()
  const [busy, setBusy] = useState<string | null>(null)
  const [armed, setArmed] = useState(false)
  const [pick, setPick] = useState(false)
  const [sendPhase, setSendPhase] = useState<SendPhase>('idle')
  const [doneArmed, setDoneArmed] = useState(false)
  const [teach, setTeach] = useState<'not_important' | 'reached' | null>(null)   // Teach Axella: the reason sheet
  const notesOwner = useNotesOwner(ax.apiOk)
  const lock = useRef(false)
  const drafts = useDrafts()
  const vips = useVips()
  if (api) api.current = { preview: onPreview }
  if (it.readonly && !it.draft) return null
  const live = ax.apiOk && !it.readonly, sec = it.section
  const tracked = live && !it.found      // a mail found by Search isn't a digest item: no Done/Later/Undo/projects/Work-Private
  // a chat reply edited in the item sheet: the WhatsApp/Signal/Messages button carries that text
  // flagged by the scam check: no reply of any kind, no draft – Done, Later, Move, Delete and Mark safe stay
  const flagged = !!it.safety
  const rl = flagged ? null : replyLink(chatText !== undefined && it.draft ? { ...it, draft: { ...it.draft, text: chatText } } : it)
  const chatChoice = /\[[^\]\n]{3,}\]/.test(rl?.copy || (chatText ?? it.draft?.text) || '')
  const canDraft = live && !flagged && !!it.draft?.text && it.channel === 'mail' && !!it.message_id && it.draft?.mode === 'reply'
  // any mail can be answered from the item sheet; Mail itself stays in the background
  const canReply = live && !flagged && it.channel === 'mail' && !!it.message_id && !!it.account && !isNoReply(it.from?.address)
  const toName = (it.from?.name || it.from?.address || 'them').split(/\s+/)[0]
  const fromVip = isVip(vips, it.from?.name)
  // a WhatsApp group (id …@g.us, or a name ending in "(group)") is not a person – never a VIP
  const isGroup = /@g\.us$/i.test(it.from?.address || '') || /\(group\)\s*$/i.test(it.from?.name || '')
  const vipCandidate = !flagged && /\bVIP\b.*\b(candidate|suggest)/i.test(it.headline || '') && !!it.from?.name && !isGroup
  const canFile = live && !!it.file_to && !!it.message_id
  // a mail you answered (or marked done) still sits in the inbox: it can be filed afterwards. Only filed or deleted
  // mail is really gone from there.
  const st = ax.state[it.id] as { how?: string; status?: string } | undefined
  const how = String(st?.how || '')
  const stillInInbox = !handled || !/^(filed:|trash$)/.test(how)
  const isMail = live && it.channel === 'mail' && !!it.message_id && !!it.account
  const cx = ctxOf(it, ax.overrides)
  const mine = new Set(projectsFor(it).map(p => p.id))
  const mailRef = it.channel === 'mail' && it.account && it.message_id
    ? { account: it.account, message_id: it.message_id, channel: 'mail', sender: (it.from?.address || '').toLowerCase() } : { channel: it.channel || '' }

  async function run(key: string, fn: () => Promise<unknown>, ok: string, leave?: Leave) {
    if (lock.current) return          // a second swipe/key/tap while the first is still on its way
    lock.current = true; setBusy(key)
    let gone = false
    try {
      const r: any = await fn()
      if (!r?.result?.pending) toast(ok)
      gone = !!leave
      if (leave && onLeave) onLeave(leave); else if (leave) ax.refresh(['state'])
    } catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(null); if (!gone) lock.current = false }
  }
  const spin = (k: string, I: any) => busy === k ? <Loader2 className="animate-spin" /> : <I />
  const lbl = (t: string, small = false) => <span className={small ? 'max-[420px]:hidden' : ''}>{t}</span>

  const actions = {
    draft: async () => {
      if (lock.current) return
      lock.current = true; setBusy('draft')
      try {
        const r: any = await ax.act('draft', { item_id: it.id, account: it.account, message_id: it.message_id, text: draftText ?? it.draft!.text, title: it.headline || '', ...(lists && lists.to.length ? lists : {}) })
        onDraftSaved?.()
        loadDrafts()
        const link = draftLink(r?.result?.draft_id)
        if (r?.result?.pending) { /* the background toast reports it */ }
        else if (link) toast('Reply saved in Drafts, in the thread', { description: IOS ? 'Tap it in Drafts to edit and send' : 'Mail shows it as a message – double-click it to edit and send', action: { label: 'Show in Mail', onClick: () => { location.href = link } }, duration: 12000 })
        else toast('Reply saved in Drafts, in the thread – open Mail on your phone or Mac to send')
      } catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(null); lock.current = false }
    },
    send: async (extra: { force?: boolean; expect_to?: string } = {}): Promise<void> => {
      const body = { item_id: it.id, account: it.account, message_id: it.message_id, text: draftText ?? '',
        title: it.headline || it.subject || '', confirm: 'send', attachments: attachments || [],
        channel: it.channel, sender: (it.from?.address || '').toLowerCase(), first_seen: it.first_seen,   // Keep Mail tidy, Teach Axella
        ...(lists ? lists : { expect_to: (it.from?.address || '').toLowerCase() }), ...extra,
        send_id: newSendId() }   // this tap: a repeat of the same POST (lost answer, outbox) never sends twice
      try {
        const r: any = await ax.act('reply_send', body, ['state'])
        onDraftSaved?.()
        if (!r?.result?.pending) toast.success('Sent to ' + (rcpt ? recipientLabel(rcpt.to, rcpt.cc, rcpt.bcc) : (r?.result?.to || toName).trim()),
          it.file_to ? { description: 'The mail is still in your inbox.', duration: 10000, action: { label: 'File in ' + it.file_to, onClick: () => { actions.file() } } }
            : { description: 'It’s still in your inbox – Today lists it under “Answered – still in the inbox”, where you can file it', duration: 8000 })
      } catch (e: any) {
        if (e instanceof Unreachable) {           // the Mac mini never got it: it waits here and goes out when it answers
          const to = rcpt ? recipientLabel(rcpt.to, rcpt.cc, rcpt.bcc) : toName
          queue({ action: 'reply_send', body, to, title: it.headline || it.subject || '' })
          toast.warning(`Waiting to send to ${to} – the Mac mini isn't answering`, { description: 'It goes out by itself if Axella is back within 30 minutes – after that it asks you first. Cancel it in the bar at the bottom.', duration: 12000 })
          return
        }
        const msg = String(e.message || e)
        const other = msg.match(/replies to this mail go to (\S+@\S+?),? not/)
        // the server stops before anything is sent; these two need a deliberate second decision
        if (other) toast.warning('Not sent – ' + msg, { duration: 20000, action: { label: 'Send to ' + other[1], onClick: () => { actions.send({ ...extra, expect_to: other[1].toLowerCase() }) } } })
        else if (/already sent/.test(msg)) toast.warning('Not sent – ' + msg, { duration: 20000, action: { label: 'Send again', onClick: () => { actions.send({ ...extra, force: true }) } } })
        else throw e
      }
    },
    vip: (add: boolean) => {
      const name = (it.from?.name || '').trim()
      const address = (it.from?.number || it.from?.address || '').trim()   // checked on the Mac: plain e-mail or phone number only
      return run('vip', async () => { const r = await ax.act(add ? 'vip_add' : 'vip_remove', { name, title: name, ctx: cx, address }, []); loadVips()
        if (add && vipCandidate) await ax.act('done', { item_id: it.id, title: it.headline || '' }, [])
        return r },
        add ? `${name} is a VIP now – the call agent and digests treat him/her as one` : `${name} removed from VIPs`,
        add && vipCandidate ? { kind: 'done', label: 'VIP' } : undefined)
    },
    file: (folder: string = it.file_to!) => run('file', () => ax.act('file', { item_id: it.id, account: it.account, message_id: it.message_id, folder, channel: it.channel,
      suggested: it.file_to, from: it.from?.address || null, title: it.headline || '' }, []), 'Moved to ' + folder, { kind: 'file', label: folder }),
    // Keep Mail tidy: the mail's account and id go along, so Done marks it read in Mail (and Undo unread again)
    done: () => run('done', () => ax.act('done', { item_id: it.id, title: it.headline || '', ...mailRef }, []), 'Marked as done', { kind: 'done', label: 'Done' }),
    undo: () => run('undo', () => ax.act('undo', { item_id: it.id, ...mailRef }), 'Restored'),
    snooze: (at?: Date, label = 'tomorrow 07:00') => {
      const u = at || (() => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(7, 0, 0, 0); return d })()
      return run('snooze', () => ax.act('snooze', { item_id: it.id, until: u.toISOString(), title: it.headline || '' }, []), 'Back ' + label, { kind: 'snooze', label: 'Back ' + label })
    },
    // a form with Claude's proposal (title, details, due date from the mail) – nothing is added until you tap Add
    task: () => openTaskFrom({ item: it, digest: ax.current?.name, dueToday: sec === 'p0' || sec === 'p1' }),
    ctx: () => {
      const value = cx === 'work' ? 'private' : 'work', sk = senderKey(it)
      return run('ctx', () => ax.act('ctx_set', { kind: sk ? 'sender' : 'item', key: sk || String(it.id).toLowerCase(), value, was: cx, label: it.headline || '' }, ['overrides']),
        sk ? `${it.from?.name || sk} → ${value === 'work' ? 'Work' : 'Private'} from now on` : `Moved to ${value === 'work' ? 'Work' : 'Private'}`)
    },
    trash: () => run('trash', () => ax.act('trash', { item_id: it.id, account: it.account, message_id: it.message_id, channel: it.channel }, []), 'Moved to Trash – recoverable in Mail', { kind: 'trash', label: 'Moved to Trash' }),
    project: (pid: string, name: string, on: boolean) => run('project', () => ax.act(on ? 'project_item_remove' : 'project_item_add',
      { id: pid, item_id: it.id, digest: ax.current?.name, headline: it.headline || it.detail || '' }, ['projects']), on ? `Removed from ${name}` : `Added to ${name}`),
  }

  if (api) {
    const mailOk = live && it.channel === 'mail' && !!it.message_id && !!it.account && !handled
    api.current = {
      preview: onPreview,
      done: live && !handled && sec !== 'file' ? actions.done : undefined,
      undo: live && handled ? actions.undo : undefined,
      snooze: live && !handled && ['p0', 'p1', 'p2', 'open', 'wait'].includes(sec) ? () => actions.snooze() : undefined,
      task: live && sec !== 'file' ? actions.task : undefined,
      file: canFile && stillInInbox ? () => actions.file() : undefined, fileLabel: it.file_to,
      pick: isMail && stillInInbox ? () => setPick(true) : undefined,
      trash: mailOk ? actions.trash : undefined,
      reply: canDraft && !handled ? (onPreview || actions.draft) : rl ? () => { location.href = rl.href } : undefined,
    }
  }
  const vis: React.ReactNode[] = []
  if (inSheet && canReply && !handled)
    vis.push(<SendButton key="send" to={rcpt ? recipientLabel(rcpt.to, rcpt.cc, rcpt.bcc) : toName} disabled={!!busy || !draftText?.trim() || attBusy || (!!rcpt && !rcpt.to.length)} onSend={() => actions.send()} onPhase={setSendPhase} swipeRef={sprint?.swipeSend}
      blocked={/\[[^\]\n]{3,}\]/.test(draftText || '') ? 'Not sent – Axella left a choice in [ … ]. Pick one above (or edit the text), then send.' : undefined} />)
  else if (canDraft && !handled)
    vis.push(<Button key="draft" size="pill" data-tour="reply" title="Read, edit and send the reply" onClick={onPreview || actions.draft} disabled={!!busy}>{spin('draft', Reply)}Reply</Button>)
  else if (rl) {
    const I = REPLY_ICON[rl.kind as keyof typeof REPLY_ICON] || Mail
    vis.push(chatChoice && rl.kind !== 'linkedin' && rl.kind !== 'mail'
      // "[ … ]" still in the draft: no link at all – a tap explains and opens the item to fix it
      ? <Button key="reply" size="pill" variant="outline" aria-disabled="true" className="text-ink-3 cursor-not-allowed opacity-50 active:translate-y-0" title="Pick or edit the [ … ] part first" onClick={() => {
          toast.warning('Axella left a choice in [ … ] – ' + (onPreview ? 'open the item and pick or edit it first.' : 'pick or edit it above first.'), { duration: 8000 })
          if (onPreview) onPreview(); else document.getElementById('ax-choice')?.scrollIntoView({ block: 'center', behavior: 'smooth' })
        }}><I />{rl.label}</Button>
      : <Button key="reply" size="pill" asChild><a href={rl.href} onClick={() => {
          if (rl.copy) navigator.clipboard.writeText(rl.copy).then(() => toast(rl.kind === 'signal' ? 'Reply copied – paste it in Signal' : 'Reply copied – pick the group in WhatsApp, or paste it there'), () => {})
        }}><I />{rl.label}</a></Button>)
  } else if (sec === 'file' && canFile && !handled)
    vis.push(<Button key="file" size="pill" onClick={() => actions.file()} disabled={!!busy}>{spin('file', FolderInput)}Move to {it.file_to}</Button>,
      <Button key="filepick" size="pill" variant="outline" onClick={() => setPick(true)} disabled={!!busy}><FolderInput />{lbl('Other folder', true)}</Button>)
  if (it.link === 'bills') vis.push(<Button key="bills" size="pill" variant="outline" onClick={() => go({ kind: 'todo', tab: 'tasks', only: 'bills' })}><Recurring />Open Bills</Button>)
  if (it.link === 'person' && it.person) vis.push(<Button key="person" size="pill" variant="outline" onClick={() => go({ kind: 'person', id: it.person! })}><UserCircle />Open their page</Button>)
  if (it.link === 'focus' && !handled) vis.push(<FocusButtons key="focus" it={it} />)
  if (it.link === 'plan' && !handled) vis.push(<PlanButton key="plan" />)
  if (it.link === 'renewals') vis.push(<Button key="renewals" size="pill" variant="outline" onClick={() => { renewalsNext.open = true; go({ kind: 'receipts' }) }}><Recurring />Open Renewals</Button>)
  if (it.link === 'subscriptions') vis.push(<Button key="subs" size="pill" variant="outline" onClick={() => { subsNext.open = true; go({ kind: 'receipts' }) }}><Recurring />Open Subscriptions</Button>)
  // only a real suggestion (Axella checked it isn't in the calendar yet) gets the visible button
  // send later: only while Send is idle, and only when the text has no unresolved "[ … ]" choice
  if (inSheet && canReply && !handled && sendPhase === 'idle' && !/\[[^\]\n]{3,}\]/.test(draftText || ''))
    vis.push(<SendLaterButton key="later" to={rcpt ? recipientLabel(rcpt.to, rcpt.cc, rcpt.bcc) : toName} disabled={!!busy || !draftText?.trim() || attBusy || (!!rcpt && !rcpt.to.length)}
      onSchedule={async at => { await scheduleSend('reply_send', { item_id: it.id, account: it.account, message_id: it.message_id, text: draftText ?? '',
        title: it.headline || it.subject || '', attachments: attachments || [], ...(lists ? lists : { expect_to: (it.from?.address || '').toLowerCase() }) },
        at, rcpt ? recipientLabel(rcpt.to, rcpt.cc, rcpt.bcc) : toName); onDraftSaved?.(); sprint?.onScheduled() }} />)
  // an invitation: answer it (the organizer is told) – Add to calendar only puts it in your own calendar
  const invite = live && !handled && !flagged && looksLikeInvite(it)
  if (invite) vis.push(<Button key="rsvp" size="pill" onClick={() => openInvite(it)} data-rsvp=""><CalendarCheck />Accept…</Button>)
  if (live && sec === 'cal' && !handled && it.event && !it.in_calendar)
    vis.push(<Button key="cal" size="pill" variant={invite ? 'outline' : undefined} onClick={onCal}><CalendarPlus />Add to calendar</Button>)
  // while Send waits for its second tap (or counts down) nothing else sits next to it to be hit by accident
  const sending = sendPhase !== 'idle'
  // Done in the sheet after you wrote or changed the reply asks once – Axella's untouched draft doesn't
  const unsent = inSheet && canReply && !handled && !!draftText?.trim() && draftText.trim() !== (it.draft?.text || '').trim()
  const doneTap = () => {
    if (!unsent || doneArmed) { setDoneArmed(false); actions.done(); return }
    setDoneArmed(true); setTimeout(() => setDoneArmed(false), 4000)
  }
  if (tracked && !sending) {
    if (handled) {
      if (isMail && stillInInbox && st?.status === 'done')   // answered or done, but not filed yet: file it now
        vis.push(canFile
          ? <Button key="file" size="pill" variant="outline" onClick={() => actions.file()} disabled={!!busy}>{spin('file', FolderInput)}Move to {it.file_to}</Button>
          : <Button key="filepick" size="pill" variant="outline" onClick={() => setPick(true)} disabled={!!busy}><FolderInput />File…</Button>)
      vis.push(<Button key="undo" size="pill" variant="outline" onClick={actions.undo} disabled={!!busy}>{spin('undo', Undo2)}Undo</Button>)
    }
    else if (sec !== 'file') {
      if (vipCandidate && !fromVip) vis.push(<Button key="vip" size="pill" variant="outline" onClick={() => actions.vip(true)} disabled={!!busy}>{spin('vip', Star)}Add to VIPs</Button>)
      vis.push(<Button key="done" size="pill" variant={doneArmed ? 'outline' : 'success'} title={doneArmed ? 'Tap again to mark it done – the reply is not sent' : 'Done'} onClick={doneTap} disabled={!!busy}>
        {spin('done', Check)}{doneArmed ? 'Done without sending?' : sprint ? 'Done without reply' : lbl('Done', true)}</Button>)
      if (['p0', 'p1', 'p2', 'open', 'wait'].includes(sec))
        vis.push(<LaterMenu key="snz" busy={busy === 'snooze'} disabled={!!busy} onPick={(d, l) => actions.snooze(d, l)} />)
    }
  }

  const menu: React.ReactNode[] = []
  if (onPreview) menu.push(<DropdownMenuItem key="prev" onSelect={onPreview}><Eye />Open item</DropdownMenuItem>)
  if (inSheet && canReply && !handled && draftText?.trim()) menu.push(<DropdownMenuItem key="savedraft" onSelect={actions.draft}><PencilLine />Save as draft in Mail instead</DropdownMenuItem>)
  if (!inSheet && canReply && !canDraft && !handled && onPreview) menu.push(<DropdownMenuItem key="replyhere" onSelect={onPreview}><Reply />Reply…</DropdownMenuItem>)
  if (canDraft && !handled && rl) menu.push(<DropdownMenuItem key="newmail" asChild><a href={rl.href}><Mail />Reply as new mail</a></DropdownMenuItem>)
  const saved = drafts[it.id], savedLink = draftLink(saved?.draft_id)
  if (savedLink) menu.push(<DropdownMenuItem key="opendraft" asChild><a href={savedLink}><Mail />Show saved draft in Mail</a></DropdownMenuItem>)
  if (it.draft?.text) menu.push(<DropdownMenuItem key="copy" onSelect={() => navigator.clipboard.writeText(it.draft!.text!).then(() => toast('Draft copied'))}><ClipboardCopy />Copy draft</DropdownMenuItem>)
  if (live && !flagged && (it.draft?.text || it.detail)) menu.push(<DropdownMenuItem key="kb" onSelect={() => {
    const ps = projectsFor(it).map(p => p.id)
    openKnowledge({
      title: (it.subject || it.headline || '').replace(/^(re|sv|aw|fw|fwd):\s*/i, '').slice(0, 200), body: it.draft?.text || it.detail || '',
      scope: ps.length ? ps : 'overall', category: cx === 'work' ? 'employer' : 'private', visibility: cx === 'work' ? 'internal' : 'private',
      source: { kind: it.channel === 'mail' ? 'mail' : 'manual', ref: it.message_id || it.id, date: isoDate(new Date()),
        label: (it.draft?.text ? 'Draft reply to ' : 'Message from ') + (it.from?.name || it.from?.address || 'someone') + (it.subject ? ' – ' + it.subject : '') },
    })
  }}><KnowledgeIcon />Save as knowledge…</DropdownMenuItem>)
  if (live && !(sec === 'cal' && it.event && !it.in_calendar)) menu.push(<DropdownMenuItem key="cal" onSelect={onCal}><CalendarPlus />{it.event ? `Add to calendar (${calLabel(it.event.calendar)})` : 'Add to calendar…'}</DropdownMenuItem>)
  if (canFile && sec !== 'file' && !handled) menu.push(<DropdownMenuItem key="file" onSelect={() => actions.file()}><FolderInput />Move to {it.file_to}</DropdownMenuItem>)
  if (isMail && stillInInbox) menu.push(<DropdownMenuItem key="filepick" onSelect={() => setPick(true)}><FolderInput />{handled ? 'File in a folder…' : 'Move to another folder…'}</DropdownMenuItem>)
  if (live && !flagged) menu.push(<DropdownMenuItem key="task" onSelect={actions.task}><SquarePlus />Add as task…</DropdownMenuItem>)
  if (live && !flagged && looksLikeInvite(it)) menu.push(<DropdownMenuItem key="rsvp" onSelect={() => setTimeout(() => openInvite(it), 120)}><CalendarCheck />Accept, maybe or decline…</DropdownMenuItem>)
  if (isMail && !flagged) menu.push(<DropdownMenuItem key="prep" onSelect={() => setTimeout(() => openNewPrep({ item: it }), 120)}><CalendarCheck />Prepare meeting…</DropdownMenuItem>)
  if (tracked && activeProjects.length) {
    menu.push(<div key="ph" className="text-muted-foreground px-2.5 pt-2 pb-1 text-[11px] font-semibold uppercase tracking-wide">Projects</div>)
    activeProjects.forEach(p => {
      const on = mine.has(p.id)
      menu.push(<DropdownMenuItem key={'p' + p.id} onSelect={() => actions.project(p.id, p.name, on)}>
        <Hash style={{ color: p.color }} className="!text-current" /><span className="flex-1">{p.name}</span>{on && <Check className="!text-primary" />}
      </DropdownMenuItem>)
    })
    menu.push(<DropdownMenuSeparator key="ps" />)
  }
  // removing is always possible; adding only for people – not for no-reply, automated or invoicing senders
  if (live && !flagged && it.from?.name && !isGroup && !(vipCandidate && !fromVip) && (fromVip || !isAutomatedSender(it.from?.address))) menu.push(<DropdownMenuItem key="vip" onSelect={() => actions.vip(!fromVip)}><Star />{fromVip ? `Remove ${it.from.name} from VIPs` : `Add ${it.from.name} to VIPs`}</DropdownMenuItem>)
  if (rl?.web) menu.push(<DropdownMenuItem key="waweb" asChild><a href={rl.web} target="_blank" rel="noopener noreferrer"><ExternalLink />Open in WhatsApp Web</a></DropdownMenuItem>)
  // People: the sender's page (their identities joined via Contacts; the Mac mini finds them by address or number)
  // Notes: a note linked to this person and thread (owner only)
  if (live && notesOwner && !flagged) menu.push(<DropdownMenuItem key="note" onSelect={() => openNote({ links: itemLinks(it) })} data-note-from-item=""><NoteIcon />Note…</DropdownMenuItem>)
  if (live && it.from?.address && !isGroup && !isAutomatedSender(it.from.address)) menu.push(<DropdownMenuItem key="person" onSelect={() => go({ kind: 'person', id: it.from!.address! })}><UserCircle />Open {it.from.name ? it.from.name.split(' ')[0] + '’s' : 'their'} page</DropdownMenuItem>)
  // Your calm: an item that should have broken through as urgent (counted under "Nothing missed" in Insights)
  // Teach Axella: a reason sheet (this sender / this topic / just this once) – a rule only from your tap
  if (tracked && !flagged && ['p0', 'p1', 'p2'].includes(sec)) menu.push(<DropdownMenuItem key="notimp" onSelect={() => setTeach('not_important')} data-teach-open="not_important"><ArrowDownRight />Not important…</DropdownMenuItem>)
  if (tracked && sec !== 'p0' && sec !== 'file' && sec !== 'cal') menu.push(<DropdownMenuItem key="missed" onSelect={() => setTeach('reached')} data-teach-open="reached"><AlarmClock />This should have reached me…</DropdownMenuItem>)
  // noise cleanup: this sender's mail stays out of the digests from now on (Newsletters lists it, and undoes it)
  const holdAddr = (it.from?.address || '').trim().toLowerCase()
  if (live && it.channel === 'mail' && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(holdAddr)) menu.push(<DropdownMenuItem key="hold" onSelect={() => run('hold',
    () => ax.act('sender_hold', { address: holdAddr, name: it.from?.name || '', title: it.from?.name || holdAddr }, []),
    `${it.from?.name || holdAddr} is held – not in your digests from the next one. Undo it under Newsletters.`)}><BellOff />Always hold mail from {(it.from?.name || holdAddr).split(/\s+/)[0]}</DropdownMenuItem>)
  if (tracked) menu.push(<DropdownMenuItem key="ctx" onSelect={actions.ctx}>{cx === 'work' ? <Home /> : <Briefcase />}Move to {cx === 'work' ? 'Private' : 'Work'}</DropdownMenuItem>)
  if (it.deep_link && !IOS) menu.push(<DropdownMenuItem key="open" asChild><a href={it.deep_link}><ExternalLink />Open in Mail</a></DropdownMenuItem>)
  if (live && it.channel === 'mail' && it.message_id && it.account && !handled) {
    menu.push(<DropdownMenuSeparator key="sep" />)
    menu.push(<DropdownMenuItem key="trash" destructive onSelect={e => {
      if (!armed) { e.preventDefault(); setArmed(true); setTimeout(() => setArmed(false), 3000); return }
      actions.trash()
    }}><Trash2 />{armed ? 'Tap again to delete' : 'Delete'}</DropdownMenuItem>)
  }
  if (!vis.length && !menu.length) return null
  if (pick) return <FolderPicker it={it} busy={busy === 'file'} onCancel={() => setPick(false)} onMove={async f => { await actions.file(f); setPick(false) }} />
  return (
    <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
      {teach && <TeachSheet it={it} what={teach} onClose={() => setTeach(null)} />}
      {vis}
      {sending && sendPhase === 'armed' && <span className="text-ink-3 text-[13px]">Tap the blue button again to send</span>}
      {menu.length > 0 && !sending && <DropdownMenu onOpenChange={o => !o && setArmed(false)}>
        <DropdownMenuTrigger asChild><Button size="icon-pill" variant="outline" className="ml-auto" aria-label="More actions"><MoreHorizontal /></Button></DropdownMenuTrigger>
        <DropdownMenuContent align="end">{menu}</DropdownMenuContent>
      </DropdownMenu>}
    </div>
  )
}

const FOLDERS: Record<string, Promise<string[]>> = {}
export function FolderPicker({ it, busy, onCancel, onMove }: { it: Item; busy: boolean; onCancel: () => void; onMove: (f: string) => Promise<void> }) {
  const [list, setList] = useState<string[] | null>(null)
  const [q, setQ] = useState('')
  const [hi, setHi] = useState(0)
  const box = useRef<HTMLDivElement>(null)
  useHold()
  const load = (fresh = false) => {
    const a = it.account || ''
    if (fresh) { delete FOLDERS[a]; setList(null) }
    FOLDERS[a] = FOLDERS[a] || get<{ folders: Record<string, string[]> }>('folders?account=' + encodeURIComponent(a) + (fresh ? '&fresh=1' : ''))
      .then(j => j.folders[a] || []).catch(e => { delete FOLDERS[a]; throw e })
    FOLDERS[a].then(l => setList([...new Set(l)].sort((x, y) => x.localeCompare(y, 'da')))).catch(() => setList([]))
  }
  useEffect(() => { load() }, [it.account])
  const words = q.toLowerCase().split(/\s+/).filter(Boolean)
  const shown = (list || []).filter(f => words.every(w => f.toLowerCase().includes(w)))
  // suggested folder first when not searching
  const rows = !q && it.file_to && shown.includes(it.file_to) ? [it.file_to, ...shown.filter(f => f !== it.file_to)] : shown
  useEffect(() => { setHi(0) }, [q])
  useEffect(() => { box.current?.querySelector('[data-hi="1"]')?.scrollIntoView({ block: 'nearest' }) }, [hi])
  const pick = (f?: string) => { if (f && !busy) onMove(f) }
  return (
    <div className="mt-2.5 w-full max-w-md rounded-lg border">
      <div className="flex items-center gap-2 border-b p-1.5">
        <Input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder={list ? `Search ${list.length} folders…` : 'Loading folders from Mail…'}
          className="h-9 border-0 shadow-none focus-visible:ring-0"
          onKeyDown={e => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setHi(h => Math.min(h + 1, rows.length - 1)) }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setHi(h => Math.max(h - 1, 0)) }
            else if (e.key === 'Enter') { e.preventDefault(); pick(rows[hi]) }
            else if (e.key === 'Escape') onCancel()
          }} />
        {busy ? <Loader2 className="text-muted-foreground mr-2 size-4 animate-spin" /> : <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>}
      </div>
      <div ref={box} className="max-h-64 overflow-y-auto overscroll-contain p-1">
        {!list && <div className="text-muted-foreground flex items-center gap-2 px-2.5 py-2 text-sm"><Loader2 className="size-4 animate-spin" />Loading…</div>}
        {list && !rows.length && <div className="text-muted-foreground px-2.5 py-2 text-sm">No folder matches “{q}”</div>}
        {rows.map((f, i) => {
          const parts = f.split('/'), leaf = parts.pop()!
          return <button key={f} type="button" data-hi={i === hi ? '1' : undefined} onMouseEnter={() => setHi(i)} onClick={() => pick(f)} disabled={busy}
            className={cn('flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm', i === hi && 'bg-accent')}>
            <FolderInput className="text-muted-foreground size-4 shrink-0" style={{ marginLeft: q ? 0 : parts.length * 14 }} />
            <span className="min-w-0 flex-1 truncate">{q && parts.length ? <span className="text-muted-foreground">{parts.join(' / ')} / </span> : null}{leaf}</span>
            {f === it.file_to && <Badge variant="outline" className="py-px">suggested</Badge>}
          </button>
        })}
      </div>
      {it.file_to && rows[hi] && rows[hi] !== it.file_to && <div className="text-muted-foreground border-t px-3 py-1.5 text-xs">Axella will suggest this folder for this sender from now on</div>}
      {list && <div className="text-muted-foreground flex items-center justify-between gap-2 border-t px-3 py-1.5 text-xs">
        <span>Missing a new folder? Mail on the Mac mini must have it first.</span>
        <button type="button" className="text-primary shrink-0 font-medium" onClick={() => load(true)}>Reload from Mail</button></div>}
    </div>
  )
}

export function CalendarForm({ it, onClose, onCreate }: { it: Item; onClose: () => void; onCreate?: (body: any) => Promise<void> }) {
  const { ax } = useApp()
  const g = guessEvent(it, ax.overrides)
  const [f, setF] = useState({ title: g.title, date: g.start.slice(0, 10), start: g.start.slice(11, 16), end: g.end.slice(11, 16), calendar: g.calendar, location: g.location || '' })
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value })
  // hold polling from switching digests while the form is open
  useHold()
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true)
    const body = { item_id: it.id, calendar: f.calendar, title: f.title, location: f.location, start: `${f.date}T${f.start}`, end: `${f.date}T${f.end}`, notes: 'Created from Axella' }
    try { await (onCreate ? onCreate(body) : ax.act('event', body)); toast('Added to ' + calLabel(f.calendar)); onClose() }
    catch (err: any) { toast.error('Failed: ' + err.message); setBusy(false) }
  }
  return (
    <form onSubmit={submit} className="bg-muted/40 mt-2.5 grid grid-cols-2 gap-2 rounded-lg border p-2.5 md:grid-cols-4">
      <Input className="col-span-2 md:col-span-4" value={f.title} onChange={set('title')} placeholder="Title" required autoFocus />
      <Input className="col-span-2" type="date" value={f.date} onChange={set('date')} required />
      <Input type="time" value={f.start} onChange={set('start')} required aria-label="Start" />
      <Input type="time" value={f.end} onChange={set('end')} required aria-label="End" />
      <NativeSelect className="col-span-2 md:col-span-4" value={f.calendar} onChange={set('calendar')}>
        {cals().map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </NativeSelect>
      <Input className="col-span-2 md:col-span-4" value={f.location} onChange={set('location')} placeholder="Location (optional)" />
      <div className="col-span-2 flex flex-wrap items-center gap-2 md:col-span-4">
        <Button size="sm" type="submit" disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : <CalendarCheck />}Create event</Button>
        <Button size="sm" variant="outline" type="button" onClick={onClose}>Cancel</Button>
        {g.guessed && <span className="text-muted-foreground text-xs">Time guessed – check before creating</span>}
      </div>
    </form>
  )
}

export function useHold(active = true) {
  const { ax } = useApp()
  useEffect(() => { if (!active) return; ax.hold.current++; return () => { ax.hold.current-- } }, [active, ax.hold])
}

/** "07:30" (earlier today), "Mon" (this week) or "2 Nov" – only for items first reported in an earlier digest */
function sinceLabel(it: Item, digestAt?: Date) {
  if (!it.first_seen) return null
  const f = new Date(it.first_seen)
  if (isNaN(f.getTime()) || (digestAt && digestAt.getTime() - f.getTime() < 20 * 60e3)) return null
  const now = new Date(), days = Math.round((new Date(now.toDateString()).getTime() - new Date(f.toDateString()).getTime()) / 864e5)
  if (days === 0) return f.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  if (days === 1) return 'yesterday'
  if (days < 7) return f.toLocaleDateString('en-GB', { weekday: 'short' })
  return f.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

interface Preview { subject: string; from: string; date: string; mailbox: string; attachments: string[]; body: string; truncated: boolean }

/** Keep Mail tidy: a mail opened in Axella's reader is marked read in Mail (quietly, in the background; only Mail) */
const seenOnce = new Set<string>()
export function seen(it: Item) {
  if (it.channel !== 'mail' || (!it.found && !(it.account && it.message_id))) return
  const k = it.found || it.account + '|' + it.message_id
  if (seenOnce.has(k)) return
  seenOnce.add(k)
  post('mail_seen', it.found ? { file: it.found } : { account: it.account, message_id: it.message_id }).catch(() => seenOnce.delete(k))
}

export function MessagePreview({ it, handled, onClose, onCal }: { it: Item; handled: boolean; onClose: () => void; onCal: () => void }) {
  const [m, setM] = useState<Preview | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useHold()
  const wasHandled = useRef(handled)
  useEffect(() => { if (handled && !wasHandled.current) onClose() }, [handled, onClose])   // filed/done from the preview → close it
  useEffect(() => {
    get<{ message: Preview }>(`message?account=${encodeURIComponent(it.account!)}&id=${encodeURIComponent(it.message_id!)}`)
      .then(j => { setM(j.message); seen(it) }).catch(e => setErr(e.message))
  }, [it.account, it.message_id])
  return (
    <Dialog open onOpenChange={o => !o && onClose()}>
      <DialogContent>
        <div className="border-b px-5 pt-4 pb-3 pr-12">
          <DialogTitle className="text-base leading-snug font-semibold">{m?.subject || it.subject || it.headline}</DialogTitle>
          <div className="text-muted-foreground mt-0.5 text-xs">
            {m ? <>{m.from}{m.date && <> · {m.date}</>}{m.mailbox && <> · {accLabel(it.account)}/{m.mailbox}</>}</> : (it.from?.name || it.from?.address || '')}
          </div>
          {!!m?.attachments.length && <div className="mt-2 flex flex-wrap gap-1.5">
            {m.attachments.map((a, i) => <a key={i} target="_blank" rel="noopener" title="Open attachment"
              href={`api/attachment?account=${encodeURIComponent(it.account!)}&id=${encodeURIComponent(it.message_id!)}&n=${i + 1}`}
              className="bg-bg-2 hover:bg-fjord-soft inline-flex items-center gap-1 rounded-sm px-2 py-0.5 text-xs underline-offset-2 hover:underline"><Paperclip className="size-3" />{a}</a>)}
          </div>}
        </div>
        <div className="min-h-[120px] flex-1 overflow-y-auto px-5 py-4 text-[14.5px] leading-relaxed">
          {err ? <div className="text-destructive text-sm">Couldn't load the message: {err}</div>
            : !m ? <div className="text-muted-foreground flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" />Loading from Mail…</div>
            : <div className="break-words whitespace-pre-wrap">{m.body || '(no text)'}{m.truncated && <div className="text-muted-foreground mt-3 text-xs">… truncated – open in Mail for the rest</div>}</div>}
        </div>
        <div className="bg-muted/30 border-t px-5 pt-1 pb-3"><ActionBar it={it} handled={handled} onCal={onCal} /></div>
      </DialogContent>
    </Dialog>
  )
}
