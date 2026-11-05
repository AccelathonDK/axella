import { useEffect, useMemo, useRef, useState } from 'react'
import * as D from '@radix-ui/react-dialog'
import { toast } from 'sonner'
import { ChevronDown, Loader2, Paperclip, Sparkles, X } from '@/components/ax-icons'
import { Badge } from '@/components/ui/badge'
import { NativeSelect } from '@/components/ui/input'
import { ActionBar, seen, useHold } from '@/components/ItemRow'
import { SafetyNote } from '@/components/Safety'
import { AttachButton, AttachList, useAttachments } from '@/components/Send'
import { BasedOn } from '@/components/Knowledge'
import { openAsk } from '@/components/Ask'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { ctxOf, isNoReply, senderKey } from '@/lib/data'
import { accLabel } from '@/lib/profile'
import { projColor } from '@/lib/projects'
import { mdInline } from '@/lib/md'
import { CH_ICON, ITEM_ICON, SEC } from '@/lib/sections'
import type { Item } from '@/lib/types'
import { cn, isoDate, keepToasts } from '@/lib/utils'
import { RecipientField, validAddress, type Person } from '@/components/Recipients'
import { AssistPanel, type AssistTarget } from '@/components/Assist'

interface ChatMsg { at?: string; from_me: boolean; sender?: string | null; text: string; media?: number }
interface ChatPreview { chat: { name?: string; group: boolean; last_at?: string; messages: ChatMsg[] } | null; window_hours?: number; export_ok: boolean; export_error?: string | null }
interface Preview { subject: string; from: string; date: string; mailbox: string; attachments: string[]; body: string; truncated: boolean; html?: string | null; remote?: boolean; pics?: boolean; pics_always?: boolean }

const Label = ({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) =>
  <div className="mb-2 flex items-center gap-2"><span className="ax-label">{children}</span>{right && <span className="text-ink-3 ml-auto text-xs">{right}</span>}</div>

/** One item, one place: the message, Axella's note, the draft to edit, every action, and what it relates to.
    A right-hand panel on the laptop, full screen on the phone. */
/** Reply sprint (components/Sprint.tsx): the same sheet, one reply after another – progress, Skip, and the swipes */
export interface SprintCtl { pos: number; total: number; seconds?: number; owed?: boolean; hint: boolean; onSkip: () => void; onHandled: () => void; onScheduled: () => void }

export function ItemSheet({ it, handled, since, onClose, onCal, sprint }: { it: Item; handled: boolean; since?: string | null; onClose: () => void; onCal: () => void; sprint?: SprintCtl }) {
  const { ax, go, projectsFor, activeProjects } = useApp()
  useHold()
  const live = ax.apiOk && !it.readonly
  const canPreview = ax.apiOk && it.channel === 'mail' && (!!it.found || (!!it.message_id && !!it.account))
  const src = it.found ? `file=${encodeURIComponent(it.found)}` : `account=${encodeURIComponent(it.account || '')}&id=${encodeURIComponent(it.message_id || '')}`
  // every mail can be answered here – written, edited and sent without opening Mail
  const noReply = isNoReply(it.from?.address)
  const canReply = live && !it.safety && it.channel === 'mail' && !!it.message_id && !!it.account && !noReply   // flagged: no reply
  const waAddr = it.from?.address || it.from?.number || ''
  const canChat = ax.apiOk && (it.channel === 'whatsapp' || it.channel === 'signal') && !!(waAddr || it.from?.name)
  const [chat, setChat] = useState<ChatPreview | null>(null)
  const [m, setM] = useState<Preview | null>(null)
  // pictures from the internet: off by default (as Mail's "Load remote content" off) – per message, or always for a sender
  const [pics, setPics] = useState(false), [picsRev, setPicsRev] = useState(0)
  const [err, setErr] = useState<string | null>(null)
  const KEEP = 'ax-reply-' + it.id
  const [text, setText] = useState(() => { try { return sessionStorage.getItem(KEEP) ?? it.draft?.text ?? '' } catch { return it.draft?.text || '' } })
  // a reply you typed survives closing the sheet (or an accidental Done) until it's sent or this tab is closed
  useEffect(() => { try { if (text.trim() && text.trim() !== (it.draft?.text || '').trim()) sessionStorage.setItem(KEEP, text); else sessionStorage.removeItem(KEEP) } catch { /* private mode */ } }, [text])
  const [zoom, setZoom] = useState<{ src: string; name: string } | null>(null)
  // the first "[a / b]" Axella left in the draft: its options become buttons that put the chosen one in its place
  // options are split on "/" with or without spaces ("a / b", "status/price/first shipment")
  const choice = (() => {
    const m = text.match(/\[([^\]\n]{3,})\]/); if (!m) return null
    const parts = /:\/\//.test(m[1]) ? [m[1]] : m[1].split(/\s*\/\s*/).map(x => x.trim()).filter(Boolean)   // a link isn't a list
    return { raw: m[0], opts: parts.some(x => x.length < 2) ? [m[1]] : parts } })()
  const replyBox = useRef<HTMLTextAreaElement>(null)
  const editChoice = () => {                    // select the "[ … ]" in the text so it can be typed over
    const el = replyBox.current, i = choice ? text.indexOf(choice.raw) : -1
    if (!el || i < 0) return
    el.focus(); el.setSelectionRange(i, i + choice!.raw.length)
  }
  const chatDraft = !canReply && !!it.draft?.text && ['whatsapp', 'signal', 'imessage', 'sms'].includes(it.channel || '')
  const choiceBox = choice && <div id="ax-choice" className={cn('bg-dawn/15 text-ink rounded-md px-3 py-2 text-[13px]', canReply ? 'mx-3 mb-3' : 'mt-2')}>
    <div>Axella left {choice.opts.length > 1 ? 'a choice' : 'something to fill in'} in <b>[ … ]</b> – {canReply ? 'Send' : 'the reply button'} stays off until you {choice.opts.length > 1 ? 'pick one or edit it' : 'edit it'}.</div>
    <div className="mt-2 flex flex-wrap gap-2">
      {choice.opts.length > 1 && choice.opts.map((o, i) =>
        <button key={i} type="button" className="bg-card hover:bg-bg-2 rounded-md border px-2.5 py-1 text-left text-[13px]"
          onClick={() => setText(t => t.replace(choice.raw, o))}>{o}</button>)}
      <button type="button" className="text-fjord self-center px-1 font-semibold hover:underline" onClick={editChoice}>Edit the [ … ] part</button></div>
  </div>
  const [follow, setFollow] = useState(canReply && !it.found && !!it.draft?.text && ['p0', 'p1', 'p2', 'wait'].includes(it.section))
  const [days, setDays] = useState(3)
  const [showMsg, setShowMsg] = useState(false)
  // To / Cc / Bcc: reply all by default – the sender (or Reply-To) on To, everyone else on the mail on Cc, never you
  const fallback: Person[] = it.from?.address && validAddress(it.from.address) ? [{ name: it.from.name, address: it.from.address }] : []
  const [to, setTo] = useState<Person[]>(fallback), [cc, setCc] = useState<Person[]>([]), [bcc, setBcc] = useState<Person[]>([])
  const [showBcc, setShowBcc] = useState(false), [rcptNote, setRcptNote] = useState('')
  // the writing assistant: beside the reply on a wide screen, under it on the phone
  const [assist, setAssist] = useState(() => { try { return localStorage.getItem('ax-assist') === '1' } catch { return false } })
  useEffect(() => { try { localStorage.setItem('ax-assist', assist ? '1' : '0') } catch { /* private mode */ } }, [assist])
  const [wide, setWide] = useState(() => matchMedia('(min-width: 640px)').matches)
  useEffect(() => { const q = matchMedia('(min-width: 640px)'); const f = () => setWide(q.matches); q.addEventListener('change', f); return () => q.removeEventListener('change', f) }, [])
  const textRef = useRef(text); textRef.current = text
  const assistTarget: AssistTarget = useMemo(() => ({
    get text() { return textRef.current },
    getSelection: () => { const el = replyBox.current; return el && el.selectionEnd > el.selectionStart ? { start: el.selectionStart, end: el.selectionEnd } : null },
    setText: (t: string) => setText(t),
    focus: (a: number, b: number) => { const el = replyBox.current; if (el) { el.focus(); el.setSelectionRange(a, b) } },
  }), [])
  const assistPanel = canReply && assist && <AssistPanel target={assistTarget} account={it.account} messageId={it.message_id} title={it.headline || it.subject || ''} onClose={() => setAssist(false)} />
  useEffect(() => {
    if (!canReply || !it.message_id || !it.account) return
    get<{ to: Person[]; cc: Person[]; reply_to_differs?: boolean }>(`reply_info?account=${encodeURIComponent(it.account)}&id=${encodeURIComponent(it.message_id)}`)
      .then(j => { if (j.to?.length) setTo(j.to); setCc(j.cc || []); if (j.reply_to_differs) setRcptNote('Replies go to the Reply-To address the sender set') })
      .catch(() => { /* not on disk yet: the sender only, as before */ })
  }, [canReply, it.message_id, it.account])
  const [plain, setPlain] = useState(!!it.safety)   // a flagged mail opens as plain text: its links are not live
  const att = useAttachments()
  const [drag, setDrag] = useState(false)
  const wasHandled = useRef(handled)
  useEffect(() => { if (handled && !wasHandled.current) { if (sprint) sprint.onHandled(); else onClose() } }, [handled, onClose])
  // the sprint's swipes (touch only, never on the text or a button): right = Send (with its countdown and Undo), left = Skip
  const swipeSend = useRef<(() => void) | null>(null)
  const sw = useRef({ x: 0, y: 0, id: -1, on: false }), [dx, setDx] = useState(0)
  const swipe = sprint ? {
    onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => {
      if (e.pointerType !== 'touch' || (e.target as HTMLElement).closest('button,a,input,textarea,select,[role=menu],[data-composer-head]')) return
      sw.current = { x: e.clientX, y: e.clientY, id: e.pointerId, on: false }
    },
    onPointerMove: (e: React.PointerEvent<HTMLDivElement>) => {
      const s = sw.current; if (s.id !== e.pointerId) return
      const mx = e.clientX - s.x, my = e.clientY - s.y
      if (!s.on) { if (Math.abs(mx) > 14 && Math.abs(mx) > Math.abs(my) * 1.5) s.on = true; else { if (Math.abs(my) > 14) s.id = -1; return } }
      setDx(mx)
    },
    onPointerUp: (e: React.PointerEvent<HTMLDivElement>) => {
      const s = sw.current; if (s.id !== e.pointerId) return
      const d = s.on ? e.clientX - s.x : 0; s.id = -1; s.on = false; setDx(0)
      if (d >= 90) swipeSend.current?.(); else if (d <= -90) sprint.onSkip()
    },
    onPointerCancel: () => { sw.current.id = -1; sw.current.on = false; setDx(0) },
  } : {}
  useEffect(() => {
    if (!canPreview) return
    get<{ message: Preview }>('message?' + src + (pics ? '&pics=1' : ''))
      .then(j => { setM(j.message); seen(it) }).catch(e => setErr(e.message))
  }, [canPreview, src, pics, picsRev])
  const always = async (on: boolean) => {
    try {
      const a = (m?.from || '').match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/)?.[0] || ''
      await ax.act('pics_sender', { address: a, on }, [])
      toast(on ? `Pictures from ${a} load from now on` : `Pictures from ${a} blocked again`)
      if (!on) setPics(false)
      setPicsRev(r => r + 1)
    } catch (e: any) { toast.error('Not saved: ' + e.message) }
  }

  useEffect(() => {
    if (!canChat) return
    get<ChatPreview>(`chat?address=${encodeURIComponent(waAddr)}&name=${encodeURIComponent(it.from?.name || '')}&channel=${it.channel}`)
      .then(setChat).catch(e => setChat({ chat: null, export_ok: false, export_error: e.message }))
  }, [canChat, waAddr, it.from?.name])

  const Icon = it.found ? CH_ICON.mail : ((it.section === 'p1' || it.section === 'p2') && it.channel && it.channel !== 'mail' && CH_ICON[it.channel]) || ITEM_ICON[it.section]   // a reply item shows its channel, not an envelope
  const world = ctxOf(it, ax.overrides)
  const projects = projectsFor(it)
  const name = it.from?.name || it.from?.address || ''
  // a person by first name; a group (WhatsApp …@g.us or "… (group)") by its whole name
  const isGroupChat = /@g\.us$/i.test(it.from?.address || '') || /\(group\)\s*$/i.test(name)
  const first = isGroupChat ? name.replace(/\s*\(group\)\s*$/i, '') : name.split(/\s+/)[0]
  const sk = senderKey(it)
  const others = useMemo(() => !sk ? [] : (ax.current?.data.items || []).filter(o => o.id !== it.id && senderKey(o) === sk && !ax.isHandled(o.id)), [ax, sk, it.id])
  const msgOpen = !canReply || showMsg
  const edited = !!it.draft?.text && text.trim() !== it.draft.text.trim()

  const onDraftSaved = () => {
    try { sessionStorage.removeItem(KEEP) } catch { /* private mode */ }
    if (!follow) return
    const d = new Date(); d.setDate(d.getDate() + days)
    ax.act('task_add', {
      text: 'Follow up: ' + (it.headline || it.subject || name || 'reply'), due: isoDate(d), source: 'followup',
      ref: { digest: ax.current?.name, item_id: it.id, message_id: it.message_id || null, deep_link: it.deep_link || null },
    }, ['tasks']).then(() => toast(`I'll remind you on ${d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })} if ${first || 'they'} hasn't answered`),
      e => toast.error('Could not add the follow-up: ' + e.message))
  }

  return (
    <D.Root open onOpenChange={o => !o && onClose()}>
      <D.Portal>
        <D.Overlay data-sheet-overlay="" className="fixed inset-0 z-50 bg-[var(--ax-scrim)]" />
        <D.Content aria-describedby={undefined} onOpenAutoFocus={e => e.preventDefault()} onPointerDownOutside={keepToasts} onInteractOutside={keepToasts}
          className="ax-sheet bg-card text-card-foreground fixed inset-0 z-50 flex flex-col outline-none sm:left-auto sm:w-[min(900px,100vw)] sm:border-l sm:shadow-float">
          {sprint && <div data-sprint-bar="" className="bg-fjord-soft text-ink flex items-center gap-3 px-4 pt-[max(.5rem,env(safe-area-inset-top))] pb-2 text-[13px] sm:px-7">
            <span className="font-semibold tabular-nums">Reply sprint · {sprint.pos} of {sprint.total}</span>
            {sprint.owed && <span className="text-ink-2 max-sm:hidden">they're waiting on you</span>}
            {sprint.hint && <span className="text-ink-2 sm:hidden">Swipe → Send · ← Skip</span>}
            <button type="button" className="text-fjord ml-auto font-semibold hover:underline" onClick={sprint.onSkip} data-sprint-skip="">Skip</button>
          </div>}
          <header className={cn('flex items-start gap-3.5 border-b px-4 pb-3.5 sm:px-7 sm:pt-5', sprint ? 'pt-3' : 'pt-[max(1rem,env(safe-area-inset-top))]')}>
            <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-md', world === 'work' ? 'bg-work-soft text-work' : 'bg-private-soft text-private')}><Icon className="size-5" /></span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 text-[13px]">
                {it.overdue && <Badge variant="destructive" className="py-px">Overdue</Badge>}
                {handled && <Badge variant="outline" className="py-px">Handled</Badge>}
                <span className="text-ink-3">{(it.found ? ['Found in ' + (it.found_in || 'Mail'), it.date && fmtWhen(it.date)] : [accLabel(it.account), world === 'work' ? 'Work' : 'Private', SEC[it.section]?.short, since && 'since ' + since]).filter(Boolean).join(' · ')}</span>
              </div>
              <D.Title className="md-inline mt-1.5 text-[19px] leading-snug font-semibold tracking-[-0.02em] sm:text-[22px]" dangerouslySetInnerHTML={{ __html: mdInline(it.headline || it.subject || 'Item') }} />
            </div>
            <D.Close className="text-ink hover:bg-bg-2 -mr-1 flex size-10 shrink-0 items-center justify-center rounded-md" aria-label="Close"><X className="size-5" /></D.Close>
          </header>

          <div {...swipe} style={dx ? { transform: `translateX(${Math.max(-120, Math.min(120, dx))}px)`, transition: 'none' } : undefined}
            className="flex min-h-0 flex-1 touch-pan-y flex-col overflow-y-auto transition-transform duration-200 sm:flex-row sm:overflow-hidden">
            <div className="flex min-w-0 flex-none flex-col gap-5 px-4 py-5 sm:flex-1 sm:overflow-y-auto sm:border-r sm:px-7 [&>*]:shrink-0">
              {(it.detail || it.summary) && <div className="text-ink-2 border-fjord/40 border-l-2 pl-3 text-[14px] leading-relaxed">
                <span className="ax-label mr-2">Axella</span><span className="md-inline" dangerouslySetInnerHTML={{ __html: mdInline(String(it.detail || it.summary)) }} />
              </div>}

              {it.safety && <SafetyNote it={it} open />}

              {canReply && <section className={cn('bg-surface ring-line focus-within:ring-ring/50 overflow-hidden rounded-lg shadow-sm ring-1 transition-shadow focus-within:ring-2', drag && 'ring-fjord ring-2')}
                onDragOver={e => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); setDrag(true) } }} onDragLeave={() => setDrag(false)}
                onDrop={e => { if (e.dataTransfer.files.length) { e.preventDefault(); setDrag(false); att.add(e.dataTransfer.files) } }}>
                <div data-composer-head="">
                  <RecipientField label="To" value={to} onChange={setTo}
                    right={<span className="text-ink-3 shrink-0 pt-1.5 text-[12px] max-sm:hidden">in the thread · from {accLabel(it.account)}</span>} />
                  <RecipientField label="Cc" value={cc} onChange={setCc}
                    right={!showBcc ? <button type="button" className="text-fjord shrink-0 pt-1.5 text-[12px] font-semibold hover:underline" onClick={e => { e.stopPropagation(); setShowBcc(true) }}>Bcc</button> : undefined} />
                  {showBcc && <RecipientField label="Bcc" value={bcc} onChange={setBcc} autoFocus />}
                  {rcptNote && <div className="text-ink-3 border-b px-4 py-1.5 text-[12px]">{rcptNote}</div>}
                </div>
                <textarea ref={replyBox} aria-label="Reply" value={text} onChange={e => setText(e.target.value)} placeholder={'Write your reply to ' + (first || 'them') + '…'}
                  rows={Math.min(22, Math.max(9, text.split('\n').length + 2))}
                  className="placeholder:text-ink-3 block min-h-[180px] w-full resize-y border-0 bg-transparent px-4 py-4 text-[16px] leading-[1.6] outline-none sm:min-h-[200px] sm:px-5" />
                <AttachList list={att.list} onRemove={att.remove} />
                {choiceBox}
                <div className="bg-bg-2/60 flex flex-wrap items-center gap-x-4 gap-y-2 border-t px-4 py-2.5 text-[13px]">
                  <AttachButton onFiles={att.add} />
                  <button type="button" onClick={() => setAssist(a => !a)} aria-pressed={assist}
                    className={cn('inline-flex items-center gap-1.5 font-semibold hover:underline', assist ? 'text-fjord' : 'text-ink-2')}><Sparkles className="size-4" />Assistant</button>
                  {it.draft?.text && <span className="text-ink-3">Drafted by Axella</span>}
                  <BasedOn ids={it.draft?.kb} />
                  {edited && <button className="text-fjord font-semibold hover:underline" onClick={() => setText(it.draft!.text!)}>Undo my edits</button>}
                  {!handled && <label className="ml-auto flex items-center gap-2">
                    <input type="checkbox" checked={follow} onChange={e => setFollow(e.target.checked)} className="accent-fjord size-4" />
                    Remind me if no answer in
                    <NativeSelect aria-label="Days" value={days} onChange={e => setDays(+e.target.value)} className="h-7 w-auto text-[13px] sm:h-7">
                      {[1, 2, 3, 5, 7, 14].map(n => <option key={n} value={n}>{n} {n === 1 ? 'day' : 'days'}</option>)}
                    </NativeSelect>
                  </label>}
                </div>
              </section>}
              {!wide && assistPanel}
              {!canReply && it.draft?.text && <section>
                <Label>Drafted reply</Label>
                {chatDraft
                  // WhatsApp, Signal, Messages: edit here, then the reply button carries (or copies) this text
                  ? <><textarea ref={replyBox} aria-label="Reply" value={text} onChange={e => setText(e.target.value)} rows={Math.min(14, Math.max(3, text.split('\n').length + 1))}
                      className="bg-bg-2 focus-visible:ring-ring/50 block w-full resize-y rounded-md px-3.5 py-3 text-[15px] leading-relaxed outline-none focus-visible:ring-2" />
                    {choiceBox}
                    {edited && <button className="text-fjord mt-1.5 text-[13px] font-semibold hover:underline" onClick={() => setText(it.draft!.text!)}>Undo my edits</button>}</>
                  : <div className="bg-bg-2 rounded-md px-3.5 py-3 text-[15px] whitespace-pre-wrap">{it.draft.text}</div>}
                <div className="mt-1.5"><BasedOn ids={it.draft.kb} /></div>
              </section>}

              {canPreview && <section>
                <button className="mb-2 flex w-full items-center gap-2 text-left" onClick={() => setShowMsg(v => !v)} aria-expanded={msgOpen}>
                  <span className="ax-label">{canReply ? 'Replying to' : 'The message'}</span>
                  <span className="text-ink-3 truncate text-xs">{m ? [m.from.replace(/\s*<.*$/, ''), m.date].filter(Boolean).join(' · ') : ''}</span>
                  {canReply && <ChevronDown className={cn('text-ink-3 ml-auto size-4 shrink-0 transition-transform', msgOpen && 'rotate-180')} />}
                </button>
                <div className="bg-bg-2 rounded-md px-4 py-3">
                  {err ? <div className="text-destructive text-sm">Couldn't load the message: {err}</div>
                    : !m ? <div className="text-ink-3 flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" />Loading from Mail…</div>
                    : <>
                      {msgOpen && <div className="text-ink text-sm font-semibold">{m.from}<span className="text-ink-3 font-normal"> · {m.mailbox && accLabel(it.account) + '/' + m.mailbox}</span></div>}
                      {msgOpen && m.attachments.some(a => IMG.test(a)) && <div className="mt-2 flex flex-wrap gap-2">
                        {m.attachments.map((a, i) => IMG.test(a) && <a key={i} title={a} href={`api/attachment?${src}&n=${i + 1}`}
                          onClick={e => { e.preventDefault(); setZoom({ src: `api/attachment?${src}&n=${i + 1}`, name: a }) }}>
                          <img src={`api/attachment?${src}&n=${i + 1}`} alt={a} loading="lazy"
                            onError={e => { (e.currentTarget.parentElement as HTMLElement).style.display = 'none' }} className="bg-card max-h-40 max-w-[240px] rounded-md border object-contain" /></a>).slice(0, 6)}
                      </div>}
                      {!!m.attachments.length && <div className="mt-2 flex flex-wrap gap-1.5">
                        {m.attachments.map((a, i) => <a key={i} target="_blank" rel="noopener" title="Open attachment"
                          href={`api/attachment?${src}&n=${i + 1}`}
                          onClick={IMG.test(a) || PDF.test(a) ? e => { e.preventDefault(); setZoom({ src: `api/attachment?${src}&n=${i + 1}`, name: a }) } : undefined}
                          className="bg-card hover:bg-fjord-soft inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 text-xs underline-offset-2 hover:underline"><Paperclip className="size-3" />{a}</a>)}
                      </div>}
                      {msgOpen && m.html && !plain
                        ? <MailFrame html={m.html} />
                        : <div className={cn('text-ink-2 mt-2 text-[14px] leading-relaxed break-words whitespace-pre-wrap', msgOpen ? 'max-h-[35vh] overflow-y-auto' : 'line-clamp-4')}>{m.body || '(no text)'}
                        {msgOpen && m.truncated && <div className="text-ink-3 mt-3 text-xs">… truncated</div>}</div>}
                      {msgOpen && m.html && <div className="text-ink-3 mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] [&>button]:whitespace-nowrap">
                        <button className={cn('hover:text-ink', !plain && 'text-ink font-semibold')} onClick={() => setPlain(false)}>As in Mail</button>
                        <button className={cn('hover:text-ink', plain && 'text-ink font-semibold')} onClick={() => setPlain(true)}>Plain text</button>
                        {!plain && m.remote && !it.safety && <span className="ml-auto flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
                          {m.pics_always ? 'Pictures load for this sender' : m.pics ? 'Pictures fetched by the Mac mini' : 'Pictures from the internet are blocked'}
                          {!m.pics && <button className="text-fjord font-semibold hover:underline" onClick={() => setPics(true)}>Load pictures</button>}
                          {m.pics_always
                            ? <button className="text-fjord font-semibold hover:underline" onClick={() => always(false)}>Block for this sender</button>
                            : <button className="text-fjord font-semibold hover:underline" onClick={() => always(true)}>Always for this sender</button>}</span>}
                      </div>}
                      {!msgOpen && <button className="text-fjord mt-1.5 text-[13px] font-semibold hover:underline" onClick={() => setShowMsg(true)}>Show the whole message</button>}
                    </>}
                </div>
              </section>}

              {canChat && <ChatSection c={chat} app={it.channel === 'signal' ? 'Signal' : 'WhatsApp'} />}
            </div>

            <aside aria-label="Related" className="bg-bg flex shrink-0 flex-col gap-3 px-4 py-5 sm:w-[300px] sm:overflow-y-auto sm:px-5">
              {wide && assistPanel}
              <span className="ax-label">Related</span>
              {name && <div className="bg-card rounded-md border px-3.5 py-3">
                <div className="font-semibold">{it.from?.name || it.from?.address}</div>
                {it.from?.name && it.from?.address && !/@(g\.us|s\.whatsapp\.net)$/i.test(it.from.address) && <div className="text-ink-3 truncate text-[13px]">{it.from.address}</div>}
                <div className="text-ink-2 mt-1.5 text-[13px]">{others.length ? `${others.length} more open from ${first} in this digest` : 'Nothing else open from ' + first}</div>
                {others.slice(0, 3).map(o => <div key={o.id} className="text-ink-2 mt-1 truncate text-[13px]">· <span className="md-inline" dangerouslySetInnerHTML={{ __html: mdInline(o.headline || o.subject || '') }} /></div>)}
                {ax.apiOk && <button className="text-fjord mt-2 text-[13px] font-semibold hover:underline" onClick={() => { onClose(); openAsk(`What's going on with ${name}? Open threads, what I promised, and what they're waiting for.`) }}>Ask Axella about {name}</button>}
              </div>}
              {projects.map(p => <button key={p.id} onClick={() => { onClose(); go({ kind: 'project', id: p.id }) }} className="bg-card hover:border-line-strong rounded-md border px-3.5 py-3 text-left">
                <div className="flex items-center gap-2"><span className="ax-diamond" style={{ color: projColor(activeProjects, p.id), width: 7, height: 7 }} /><span className="font-semibold">{p.name}</span></div>
                <div className="text-ink-3 mt-0.5 text-[13px]">Project · #{p.tag}</div>
              </button>)}
              {it.event && <div className="bg-card rounded-md border px-3.5 py-3">
                <div className="text-ink-3 text-[13px]">{fmtWhen(it.event.start)}</div>
                <div className="font-semibold">{it.event.title}</div>
                <div className="text-ink-3 mt-0.5 text-[13px]">{it.in_calendar ? 'In your calendar' : 'Not in your calendar yet'}</div>
              </div>}
              {!name && !projects.length && !it.event && <div className="text-ink-3 text-sm">Nothing linked yet.</div>}
            </aside>
          </div>
          <div className="bg-card z-10 shrink-0 border-t px-4 pt-1 pb-[max(.75rem,env(safe-area-inset-bottom))] sm:px-7 sm:pb-3 sm:pr-[calc(300px+1.75rem)]">
            <ActionBar it={it} handled={handled} onCal={onCal} draftText={canReply ? text : undefined} rcpt={canReply ? { to, cc, bcc } : undefined} chatText={chatDraft ? text : undefined} onDraftSaved={onDraftSaved} attachments={att.ids} attBusy={att.busy}
              sprint={sprint ? { swipeSend, onScheduled: sprint.onScheduled } : undefined} />
          </div>
          {zoom && <Lightbox src={zoom.src} name={zoom.name} onClose={() => setZoom(null)} />}
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}

const fmtWhen = (s?: string) => { const d = s ? new Date(s) : null; return d && !isNaN(d.getTime()) ? d.toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : (s || '') }

/* WhatsApp: the last messages of the chat, read from the Mac mini's read-only export (never opens the chat or marks it
   read on the phone). Newest at the bottom, like WhatsApp; the message this item is about is usually the last one. */
function ChatSection({ c, app = 'WhatsApp' }: { c: ChatPreview | null; app?: string }) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { const el = box.current; if (el) el.scrollTop = el.scrollHeight }, [c])
  const msgs = c?.chat?.messages || []
  return <section>
    <Label right={c?.chat?.last_at ? 'last ' + fmtTime(c.chat.last_at) : undefined}>The chat</Label>
    <div ref={box} className="bg-bg-2 max-h-[45vh] overflow-y-auto rounded-md px-3 py-3">
      {!c ? <div className="text-ink-3 flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" />Loading from {app}…</div>
        : !c.export_ok ? <div className="text-ink-3 text-sm">{app} can't be read on the Mac mini right now{c.export_error ? ` (${c.export_error})` : ''}. Open the chat to read it.</div>
        : !msgs.length ? <div className="text-ink-3 text-sm">Nothing from this chat in the last {Math.round((c.window_hours || 48) / 24)} days – open it in {app} to read older messages.</div>
        : <ol className="flex flex-col gap-1.5">
          {msgs.map((x, i) => {
            const prev = msgs[i - 1], group = !!c.chat?.group
            const who = x.from_me ? 'You' : group ? (x.sender || 'Someone') : (c.chat?.name || '')
            const turn = !prev || prev.from_me !== x.from_me || (group && prev.sender !== x.sender)
            const photo = x.media != null && /^\[(photo|GIF|sticker)\]$/.test(x.text)
            return <li key={i} className={cn('flex flex-col', x.from_me ? 'items-end' : 'items-start', turn && i > 0 && 'mt-2')}>
              {turn && <span className="text-ink-3 mb-0.5 px-1 text-[12px]">{who}</span>}
              <div className={cn('max-w-[85%] rounded-lg text-[14px] leading-snug break-words whitespace-pre-wrap', photo ? 'p-1' : 'px-3 py-1.5', x.from_me ? 'bg-fjord-soft text-ink' : 'bg-card text-ink border')}>
                {x.media != null && <ChatPhoto id={x.media} />}
                {!photo && x.text}
                <span className={cn('text-ink-3 font-mono text-[11px] whitespace-nowrap', photo ? 'block px-2 pt-1 text-right' : 'ml-2 align-bottom')}>{x.at ? fmtTime(x.at) : ''}</span>
              </div>
            </li>
          })}
        </ol>}
    </div>
  </section>
}
/* The mail as Mail shows it: its own HTML on white "paper", in a sandboxed frame – no scripts, no forms, its own
   origin, links open in a new tab, and the dashboard's content policy keeps pictures from the internet (and tracking
   pixels) out. Made safe on the Mac mini first (setup/mailsearch.py html_of). */
/* pictures from the internet load by default (fetched by the Mac mini); "Block pictures" turns that off – this browser only */

function MailFrame({ html }: { html: string }) {
  return <iframe title="The message" sandbox="allow-popups allow-popups-to-escape-sandbox" referrerPolicy="no-referrer" srcDoc={html}
    className="mt-2 block h-[55vh] w-full rounded-md border bg-white" />
}

function ChatPhoto({ id }: { id: number }) {
  const [bad, setBad] = useState(false)
  const src = 'api/chat_media?id=' + id
  if (bad) return <span className="text-ink-3 block px-2 py-1 text-[13px]">[photo – open it in WhatsApp]</span>
  const [open, setOpen] = useState(false)
  return <><a href={src} title="Open the photo" onClick={e => { e.preventDefault(); setOpen(true) }}><img src={src} alt="Photo" loading="lazy" onError={() => setBad(true)} className="block max-h-64 max-w-full rounded-md object-contain" /></a>
    {open && <Lightbox src={src} name="Photo" onClose={() => setOpen(false)} />}</>
}

/** A picture on top of the item sheet – instead of a new browser tab. Esc, ✕ or a tap outside the picture closes it. */
/** A picture or a PDF (e-ticket, voucher) shown full screen inside Axella; "Open" gives the browser's own viewer. */
export function Lightbox({ src, name, onClose }: { src: string; name: string; onClose: () => void }) {
  const [bad, setBad] = useState(false)
  const pdf = PDF.test(name)
  return <D.Root open onOpenChange={o => !o && onClose()}>
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-[60] bg-black/90" />
      <D.Content aria-describedby={undefined} onClick={onClose}
        className="fixed inset-0 z-[60] flex flex-col items-center justify-center p-4 outline-none sm:p-10">
        <D.Title className="sr-only">{name}</D.Title>
        <div className="absolute top-0 right-0 left-0 flex items-center gap-3 px-4 py-3 text-[13px] text-white/80" onClick={e => e.stopPropagation()}>
          <span className="min-w-0 flex-1 truncate">{name}</span>
          <a href={src} target="_blank" rel="noopener" className="shrink-0 hover:text-white hover:underline">{pdf ? 'Open' : 'Full size'}</a>
          <D.Close aria-label="Close" className="shrink-0 rounded-md p-1.5 hover:bg-white/10 hover:text-white"><X className="size-5" /></D.Close>
        </div>
        {pdf ? <iframe src={src} title={name} onClick={e => e.stopPropagation()} className="mt-10 h-full w-full max-w-4xl rounded-md bg-white shadow-2xl" />
          : bad ? <div className="text-sm text-white/80">This picture can't be shown here – <a href={src} target="_blank" rel="noopener" className="underline">open it</a>.</div>
          : <img src={src} alt={name} onError={() => setBad(true)} onClick={e => e.stopPropagation()} className="max-h-full max-w-full rounded-md object-contain shadow-2xl" />}
      </D.Content>
    </D.Portal>
  </D.Root>
}
const IMG = /\.(jpe?g|png|gif|webp|heic)$/i
const PDF = /\.pdf$/i
function fmtTime(iso: string) {
  const d = new Date(iso)
  if (isNaN(+d)) return ''
  const hm = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  return d.toDateString() === new Date().toDateString() ? hm : d.toLocaleDateString('en-GB', { weekday: 'short' }) + ' ' + hm
}
