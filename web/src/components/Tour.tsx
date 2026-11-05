/* Guided tours: a spotlight on the real screens, one thing at a time, with Back / Next / Skip. They only point – a tour
   never taps a button, opens a sheet or calls the Mac mini, and the dimmed layer takes every click.
   - The welcome tour (Today, the header, the menu) is offered once per device on a first visit, and from Getting
     started → Take the tour.
   - Feature tours ("Show me" in Getting started, or the floating ? on a page – Settings → Appearance turns it off): Reply sprint, Trips, Meetings and a meeting prep,
     Calendar invitations, a project's mails, Backup.
   A step may open a page first (view) and then waits for its element; with nothing to point at it shows its empty
   text on the empty state instead (empty), or is passed over. Anchors are data-… attributes on the screens.
   Keep TOURS in step with the screens – web/tests/tours.cjs walks every tour. */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ChevronRight, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Rune } from '@/components/icons'
import { useApp, type View } from '@/lib/app'
import { cn } from '@/lib/utils'

interface Step {
  at: string[]; title: string; text: string
  view?: View                                   // open this page first
  empty?: { at: string[]; text: string }        // nothing to point at: point here instead, with this text
}
export interface Tour { id: string; title: string; steps: Step[]; start?: 'today' | 'project' | View }
const T = (sel: string) => `[data-tour="${sel}"]`

export const TOURS: Record<string, Tour> = {
  welcome: { id: 'welcome', title: 'Welcome tour', start: 'today', steps: [
    { at: [T('today')], title: 'Today',
      text: 'Everything that needs you, most urgent first – replies, calls and tasks due. When it\'s empty, you\'re done.' },
    { at: [`${T('today')} [data-item-row]`], title: 'One item',
      text: 'Tap its title to open it: Axella\'s note, the mail and your reply. Done clears it; Later brings it back when you choose. On the iPhone: swipe right for Done, left for tomorrow.' },
    { at: [`${T('today')} ${T('reply')}`], title: 'Reply',
      text: 'Axella has drafted a reply in your tone. Change what you like – nothing is sent until you tap Send, tap again, and the 6 seconds to undo run out.' },
    { at: ['[data-sprint-card]'], title: 'Reply sprint',
      text: 'Several short replies ready? Start takes you through them one after another – each Send is still your own tap.' },
    { at: [T('ctx')], title: 'Work and private',
      text: 'Show everything, or only work or only private. Digests, receipts and insights follow the switch.' },
    { at: [T('new')], title: 'New',
      text: 'Start a mail, a message, a task, a meeting prep, a recurring reminder or a knowledge entry.' },
    { at: [T('ask')], title: 'Ask Axella',
      text: 'Ask about your mail, tasks and projects – "What did Sam say about access?". It can suggest actions, and nothing happens until you tap one.' },
    { at: [T('search')], title: 'Search',
      text: 'Search everything Axella has seen as you type – or all mail on the Mac mini, also from before Axella.' },
    { at: [T('listen'), T('briefing')], title: 'Briefing and Listen',
      text: 'The Briefing is the calm read of the latest digest. The headphones read it aloud – also in the car with the Siri shortcut "Axella digest".' },
    { at: [T('todo')], title: 'To do',
      text: 'Your tasks, bills and promises – and what you\'re waiting for from others.' },
    { at: [T('menu')], title: 'The rest',
      text: 'The menu has Calendar, Meetings and Trips, Mailbox and Receipts, Contacts, Knowledge and your projects.' },
    { at: [T('account')], title: 'Help and settings',
      text: 'Getting started explains everything in more depth, with a Show me tour for the bigger features – or tap the ? in the corner of a page. Here too: System status, Settings, Runs and the Activity log. A dot here means something needs you.' },
  ] },
  sprint: { id: 'sprint', title: 'Reply sprint', start: 'today', steps: [
    { at: ['[data-sprint-card]'], title: 'Reply sprint',
      text: 'When 3 or more quick replies are ready – Axella\'s short drafts – this card says how many and about how long they take.',
      empty: { at: [T('today')], text: 'When 3 or more quick replies are ready – Axella\'s short drafts – a Reply sprint card appears here, with how long they take.' } },
    { at: ['[data-sprint-card] button'], title: 'Start',
      text: 'Start opens them one at a time, people waiting on you first. A bar on top shows how far you are, with Skip.' },
    { at: ['[data-sprint-card]', T('today')], title: 'Each reply',
      text: 'Each one is the ordinary reply: edit it, Send (two taps and 6 seconds to undo), Later, Skip, or Done without reply. On the iPhone, swipe right to send and left to skip. There is no send-all.' },
  ] },
  trips: { id: 'trips', title: 'Trips', start: { kind: 'trips' }, steps: [
    { at: ['[data-trip-since]'], title: 'Scan since',
      text: 'Axella finds trips in the booking confirmations already in your mail – from the date you pick, up to 18 months back.' },
    { at: ['[data-trip-scan]'], title: 'Scan mail',
      text: 'The scan runs on the Mac mini, by rules – never Claude. Private contacts and protected workplaces are left out.' },
    { at: ['[data-trip-suggestion]'], title: 'A suggested trip',
      text: 'Bookings close in time become one suggestion. Untick what doesn\'t belong, give it a name and Confirm – or Not a trip. Nothing becomes a trip by itself.' },
    { at: ['[data-trip]'], title: 'A trip',
      text: 'Its bookings day by day, in each place\'s own time, with the booking reference and a link to the mail. On a travel day Today shows it – also offline.' },
    { at: ['[data-trip] [aria-label^="More for "]'], title: 'A booking',
      text: 'Each booking\'s ⋯: Add to calendar, Edit, Move to another trip, or Void a duplicate.' },
    { at: ['[data-trip-pdf]', '[data-trip-email]'], title: 'PDF and Email',
      text: 'A travel plan to print or save, or a new mail with the plan – you choose who gets it.',
      empty: { at: ['[data-trip-scan]'], text: 'Once you have a trip: a PDF travel plan, or a mail with the plan to whoever you choose.' } },
  ] },
  meetings: { id: 'meetings', title: 'Meetings', start: { kind: 'meetings' }, steps: [
    { at: ['[data-meeting-row]'], title: 'Your meetings',
      text: 'Meetings with other people, a join link or an invitation in the next 14 days – a repeating meeting is one row – and how far each prep is.',
      empty: { at: ['[data-meetings-view] h1'], text: 'Meetings with other people in the next 14 days show up here, with how far each prep is.' } },
    { at: ['[data-prepare]', '[data-open-prep]'], title: 'Prepare',
      text: 'One prep per meeting: goals, points to discuss, materials and the people. Open one and tap the ? in the corner for its own tour.' },
  ] },
  prep: { id: 'prep', title: 'A meeting prep', steps: [
    { at: ['[data-points]'], title: 'Points to discuss',
      text: 'Goals, the points to discuss, background and notes – saved as you type. It reads as a document you can print or mail as an agenda.' },
    { at: ['[data-materials]'], title: 'Materials',
      text: 'Files, web pages and mails that belong to the meeting.' },
    { at: ['[data-people]'], title: 'The people',
      text: 'Who is coming, with your recent mail, open tasks and earlier meetings with them.' },
    { at: ['[data-ai-choice]'], title: 'What Claude may read',
      text: 'For a protected workplace you choose what Claude may read for this meeting – your own text only, everything, or nothing.' },
    { at: ['[data-rec-start]'], title: 'Record',
      text: 'Record on the phone or the Mac, or upload a recording or a transcript. It\'s transcribed on the Mac mini and never leaves your home.' },
    { at: ['[data-find-outcomes]'], title: 'Find outcomes',
      text: 'Decisions, your tasks, what you wait for and facts worth keeping – nothing is added without your tap.' },
    { at: ['[data-draft-followup]'], title: 'Follow-up mail',
      text: 'A follow-up mail to the people who were there, for you to check and send.' },
  ] },
  invites: { id: 'invites', title: 'Calendar invitations', start: { kind: 'calendar' }, steps: [
    { at: [T('cal-new')], title: 'New event',
      text: 'New event has an Invitees field and an Online meeting picker – Teams, Meet, Zoom or a pasted link. You see who, from where and when before Send invites.',
      empty: { at: ['[data-calendar-view] h1'], text: 'Once your calendars are set up, New event here sends real invitations from the calendar\'s own server.' } },
    { at: ['[data-event]'], title: 'An event',
      text: 'An event you invited people to shows each person\'s answer. Change… sends an update, and Cancel the meeting sends a cancellation – with the same confirm as any send.' },
    { at: ['[data-meeting-services]'], view: { kind: 'settings', page: 'calendar' }, title: 'Meeting services',
      text: 'Teams, Google Meet and Zoom are connected here, and each calendar gets its default online meeting.',
      empty: { at: ['[data-settings-area="calendar"] h1'], text: 'Settings → Calendar connects Teams, Google Meet and Zoom, and sets each calendar\'s default online meeting.' } },
  ] },
  'project-mails': { id: 'project-mails', title: 'Project mails', start: 'project', steps: [
    { at: ['[data-project-scan]'], title: 'Scan mail',
      text: 'Finds this project\'s mails by its tag, keywords in the subject and its senders – from the date you pick. Rules on the Mac mini, never Claude.',
      empty: { at: [`${T('project')} h1`, T('projects')], text: 'A project\'s Mails card scans your mail for it – by its tag, keywords in the subject and its senders. Open a project and tap the ? in the corner for the tour.' } },
    { at: ['[data-to-sort]'], title: 'To sort',
      text: 'What the scan found, with why each one matched. Add it, or Not this project – it isn\'t offered again.' },
    { at: ['[data-match-suggest]'], title: 'Add to matches',
      text: 'When you add several mails from one sender, Axella offers to match that sender from now on.' },
    { at: ['[data-project-mails]'], title: 'The project\'s mails',
      text: 'Grouped by thread, opened in Axella\'s reader. Attachments can go to the project\'s Documents.' },
    { at: [T('project-read')], title: 'Read with Claude',
      text: 'Tick mails and Read with Claude suggests tasks, notes and dates – nothing is added without your tap. A protected workplace\'s mail stays on the Mac mini unless its AI setting allows it.' },
    { at: ['[data-project-trips]'], title: 'Trips',
      text: 'A project can link to a trip, and the trip shows its projects.' },
  ] },
  backup: { id: 'backup', title: 'Backup', start: { kind: 'settings', page: 'system' }, steps: [
    { at: ['[data-backup-export]'], title: 'Export backup',
      text: 'One encrypted file with everything Axella has learned. You choose the passphrase – it\'s never stored, so keep it safe.',
      empty: { at: ['[data-settings-area] h1'], text: 'The Backup card appears here once the Mac mini answers.' } },
    { at: ['[data-pass-hint]'], title: 'The passphrase',
      text: 'Type it in both fields. This line says what\'s still missing – the button turns on when they match.' },
    { at: [T('backup-history')], title: 'Include history',
      text: 'Adds digests, calls, the activity log and recordings – larger, and personal.' },
    { at: ['[data-backup-auto]'], title: 'Weekly, by itself',
      text: 'Pick a folder on the Mac mini – a disk, a NAS or iCloud Drive – and Axella keeps the last 4 weekly backups there.' },
    { at: [T('backup-restore')], title: 'Restore',
      text: 'On a new Mac mini: tools/restore.sh shows what\'s in the backup and what it would replace, then restores – your current data is moved aside, never deleted. Keys and tokens are reconnected afterwards.' },
  ] },
}
const SEEN = 'ax-tour'
export const openTour = (id = 'welcome') => window.dispatchEvent(new CustomEvent('ax-tour', { detail: id }))

function visible(sel: string): HTMLElement | null {
  for (const el of Array.from(document.querySelectorAll<HTMLElement>(sel))) {
    const r = el.getBoundingClientRect()
    if (r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden') return el
  }
  return null
}
const first = (sels: string[]) => sels.map(visible).find(Boolean) || null
/** what a step points at now: its element, or its empty fallback (with that text), or nothing */
function resolve(s: Step): { el: HTMLElement; text: string } | null {
  const el = first(s.at)
  if (el) return { el, text: s.text }
  const e = s.empty && first(s.empty.at)
  return e ? { el: e, text: s.empty!.text } : null
}
const same = (a: View, b: View) => JSON.stringify(a) === JSON.stringify(b)

export function TourHost() {
  const { ax, view, go, activeProjects } = useApp()
  const [on, setOn] = useState<{ tour: Tour } | 'welcome' | null>(null)
  const loaded = !!ax.current || ax.stateReady     // a boolean (ax.current is a new object on every refresh); no digest needed
  const viewRef = useRef(view); viewRef.current = view
  useEffect(() => {
    const h = (e: Event) => {
      const t = TOURS[String((e as CustomEvent).detail || 'welcome')] || TOURS.welcome
      const st = t.start
      if (st === 'today') go({ kind: 'today' })
      else if (st === 'project') { if (viewRef.current.kind !== 'project') { const p = activeProjects[0]; go(p ? { kind: 'project', id: p.id } : { kind: 'projects' }) } }
      else if (st && !same(st, viewRef.current)) go(st)
      setTimeout(() => setOn({ tour: t }), 400)
    }
    window.addEventListener('ax-tour', h); return () => window.removeEventListener('ax-tour', h)
  }, [go, activeProjects])
  // once per device: a first visit to Today, once the Mac mini has answered, gets the welcome card
  useEffect(() => {
    if (on || view.kind !== 'today' || !loaded) return
    let seen = '1'
    try { seen = localStorage.getItem(SEEN) || '' } catch { /* private mode: never nag */ }
    if (seen) return
    const t = setTimeout(() => { if (!document.querySelector('[role="dialog"]')) setOn('welcome') }, 2500)
    return () => clearTimeout(t)
  }, [view.kind, loaded, on])
  const seen = () => { try { localStorage.setItem(SEEN, new Date().toISOString().slice(0, 10)) } catch { /* private mode */ } }
  if (on === 'welcome') return <Welcome onStart={() => setOn({ tour: TOURS.welcome })} onSkip={() => { seen(); setOn(null) }} />
  if (on) return <Spotlight tour={on.tour} onEnd={() => { if (on.tour.id === 'welcome') seen(); setOn(null) }} />
  return <TourFab />
}

/** the page's own tour, if it has one – the floating ? starts it */
export function pageTour(v: View): string | null {
  switch (v.kind) {
    case 'today': return 'welcome'
    case 'trips': return 'trips'
    case 'meetings': return 'meetings'
    case 'meeting': return 'prep'
    case 'calendar': return 'invites'
    case 'project': return 'project-mails'
    case 'settings': return v.page === 'system' ? 'backup' : v.page === 'calendar' ? 'invites' : null
    default: return null
  }
}

/* the floating ?: bottom right, quiet, only on a page with a tour. Settings → Appearance turns it off (per device). */
const FAB = 'ax-tour-fab'
export const fabOn = () => { try { return localStorage.getItem(FAB) !== 'off' } catch { return true } }
export const setFab = (on: boolean) => { try { localStorage.setItem(FAB, on ? 'on' : 'off') } catch { /* private mode */ } window.dispatchEvent(new Event(FAB)) }
export function useFab(): [boolean, (on: boolean) => void] {
  const [on, set] = useState(fabOn)
  useEffect(() => { const h = () => set(fabOn()); window.addEventListener(FAB, h); return () => window.removeEventListener(FAB, h) }, [])
  return [on, setFab]
}
function TourFab() {
  const { view } = useApp()
  const [on] = useFab()
  const id = pageTour(view)
  if (!on || !id || !TOURS[id]) return null
  return <button type="button" onClick={() => openTour(id)} aria-label={'Show me around: ' + TOURS[id].title} title={'Show me around: ' + TOURS[id].title} data-tour-help={id}
    className="bg-card/90 text-ink-3 hover:text-ink hover:border-line-strong fixed right-3 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-30 flex size-9 items-center justify-center rounded-full border text-[15px] font-semibold opacity-70 shadow-sm backdrop-blur transition-opacity hover:opacity-100 focus-visible:opacity-100 print:hidden lg:right-5 lg:bottom-12">?</button>
}

function Welcome({ onStart, onSkip }: { onStart: () => void; onSkip: () => void }) {
  return <div className="fixed inset-0 z-[60] flex items-end justify-center bg-[var(--ax-scrim)] p-4 sm:items-center" data-tour-welcome="" role="dialog" aria-modal="true" aria-labelledby="tour-w">
    <div className="bg-card w-full max-w-sm rounded-lg border p-5 shadow-float">
      <div className="flex items-center gap-2.5"><Rune size={20} /><div id="tour-w" className="text-[17px] font-semibold">Welcome to Axella</div></div>
      <p className="text-ink-2 mt-2 text-[14.5px]">A one-minute tour of the main screens. It only points things out – nothing is changed or sent.</p>
      <div className="mt-4 flex justify-end gap-2"><Button variant="ghost" onClick={onSkip}>Not now</Button><Button onClick={onStart} autoFocus>Start the tour<ChevronRight /></Button></div>
      <p className="text-ink-3 mt-3 text-[12px]">You can take it later from Getting started in the account menu.</p>
    </div>
  </div>
}

function Spotlight({ tour, onEnd }: { tour: Tour; onEnd: () => void }) {
  const { go, view } = useApp()
  const steps = tour.steps
  const [i, setI] = useState(0)
  const dir = useRef(1)                                    // which way to pass over a step with nothing to point at
  const shown = useRef(new Set<number>())                  // the steps actually shown – the counter counts only these
  const [hit, setHit] = useState<{ el: HTMLElement; text: string } | null>(null)
  const [rect, setRect] = useState<DOMRect | null>(null)
  const card = useRef<HTMLDivElement>(null)
  const [cardH, setCardH] = useState(180)
  const s = steps[i]
  const viewRef = useRef(view); viewRef.current = view
  // find the step's element: open its page first, then wait a little for the page to draw it
  useEffect(() => {
    if (!s) return
    let gone = false
    setHit(null)
    if (s.view && !same(s.view, viewRef.current)) go(s.view)
    const until = Date.now() + (s.view ? 3000 : 600)
    const look = () => {
      if (gone) return
      const r = resolve(s)
      if (r) {                                             // a tall thing (a long trip): its top, not its middle
        const tall = r.el.getBoundingClientRect().height > innerHeight * 0.55
        r.el.scrollIntoView({ block: tall ? 'start' : 'center', behavior: 'instant' as ScrollBehavior })
        if (tall) window.scrollBy(0, -72)                // clear of the sticky header
        shown.current.add(i); setHit(r); setRect(r.el.getBoundingClientRect()); return
      }
      if (Date.now() < until) { setTimeout(look, 100); return }
      const n = i + dir.current                            // nothing here: pass it over
      if (n < 0 || n >= steps.length) onEnd(); else setI(n)
    }
    look()
    return () => { gone = true }
  }, [i])                                                  // eslint-disable-line react-hooks/exhaustive-deps
  const measure = useCallback(() => { if (hit?.el.isConnected) setRect(hit.el.getBoundingClientRect()) }, [hit])
  useEffect(() => {
    addEventListener('resize', measure); addEventListener('scroll', measure, true)
    return () => { removeEventListener('resize', measure); removeEventListener('scroll', measure, true) }
  }, [measure])
  useLayoutEffect(() => { if (card.current) setCardH(card.current.offsetHeight) })
  const next = () => { dir.current = 1; if (i + 1 < steps.length) setI(i + 1); else onEnd() }   // a passed-over last step ends the tour
  const back = () => { dir.current = -1; setI(x => Math.max(0, x - 1)) }
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onEnd(); else if (e.key === 'ArrowRight' || e.key === 'Enter') forward(); else if (e.key === 'ArrowLeft') back() }
    addEventListener('keydown', k); return () => removeEventListener('keydown', k)
  })
  useEffect(() => { card.current?.focus() }, [hit])
  // n / total over the steps you see: the ones shown so far, plus those still ahead that have something to point at on
  // this page (a step on another page counts – it can't be checked from here)
  let pos = 0, total = 0, away = false
  steps.forEach((st, k) => {
    if (k <= i) { if (shown.current.has(k) || k === i) { total++; pos++ } return }
    if (st.view) away = true
    if (away || resolve(st)) total++
  })
  const lastStep = total === pos                           // nothing left ahead to show: this one says Done
  const forward = () => (lastStep ? onEnd() : next())
  const pad = 6, vw = innerWidth, vh = innerHeight
  const r = hit && rect ? { x: Math.max(4, rect.left - pad), y: Math.max(4, rect.top - pad), w: Math.min(vw - 8, rect.width + pad * 2), h: Math.min(vh - 8, rect.height + pad * 2) } : null
  // taller than the room above the card: show its top part, so the card fits underneath
  if (r && r.y + r.h + 12 + cardH > vh - 8 && r.y - 12 - cardH <= 8 && !(r.x + r.w + 12 + Math.min(340, vw - 32) < vw - 8)) r.h = Math.max(80, vh - 8 - cardH - 12 - r.y)
  const w = Math.min(340, vw - 32)
  // the card goes below the spotlight when there is room, else above it, else beside it, else at the bottom
  let top = vh - cardH - 16, left = (vw - w) / 2
  if (r) {
    left = Math.min(Math.max(16, r.x + r.w / 2 - w / 2), vw - w - 16)
    if (r.y + r.h + 12 + cardH < vh - 8) top = r.y + r.h + 12
    else if (r.y - 12 - cardH > 8) top = r.y - 12 - cardH
    else if (r.x + r.w + 12 + w < vw - 8) { left = r.x + r.w + 12; top = Math.min(Math.max(16, r.y + 80), vh - cardH - 16) }   // a tall thing (the sidebar): beside it
  }
  return <div className="fixed inset-0 z-[60]" data-tour-on={tour.id} onClick={e => e.stopPropagation()}>
    {/* the spotlight: a clear box, the rest dimmed by its shadow; the layer takes the clicks, so nothing underneath is touched */}
    <div aria-hidden className="absolute rounded-lg transition-all duration-200 ease-out"
      style={r ? { left: r.x, top: r.y, width: r.w, height: r.h, boxShadow: '0 0 0 9999px var(--ax-scrim), 0 0 0 2px var(--ax-accent)' } : { inset: 0, background: 'var(--ax-scrim)' }} />
    <div className="absolute inset-0" />
    {hit && s && <div ref={card} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="tour-t" aria-describedby="tour-d" data-tour-card="" data-tour-step={i}
      className="bg-card absolute rounded-lg border p-4 shadow-float outline-none" style={{ left, top, width: w }}>
      <div className="flex items-start gap-2">
        <div id="tour-t" className="flex-1 text-[15.5px] font-semibold">{s.title}</div>
        <span className="text-ink-3 pt-0.5 font-mono text-[11px] tabular-nums">{pos} / {total}</span>
        <button className="text-ink-3 hover:bg-bg-2 -mt-1 -mr-1 flex size-7 items-center justify-center rounded-md" aria-label="End the tour" onClick={onEnd}><X className="size-4" /></button>
      </div>
      <p id="tour-d" className="text-ink-2 mt-1 text-[14px] leading-relaxed">{hit.text}</p>
      <div className="mt-3 flex items-center gap-2">
        <button className="text-ink-3 hover:text-ink text-[13px]" onClick={onEnd}>Skip</button>
        <span className="flex-1" />
        {i > 0 && <Button size="pill" variant="outline" onClick={back}>Back</Button>}
        <Button size="pill" onClick={forward} data-tour-next="">{!lastStep ? <>Next<ChevronRight /></> : 'Done'}</Button>
      </div>
      {lastStep && <p className="text-ink-3 mt-2 text-[12px]">{tour.id === 'welcome' ? 'Take it again any time from Getting started.' : 'Getting started has a Show me for the other features.'}</p>}
    </div>}
  </div>
}
