import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { AlarmClock, Briefcase, CalendarPlus, Home, Check, CheckCheck, ExternalLink, Folder, StickyNote, Trash2, MessageCircle, Phone, PhoneIncoming, Plus, Recurring, Sparkles, SquarePlus, Undo2, X, Receipt, Mail } from '@/components/ax-icons'
import { BillDetails, BillMeta } from '@/components/Bills'
import { openMailInAxella } from '@/components/MailReader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { EVERY_LABEL, describe, loadReminders, short, useReminders, type Every } from '@/lib/reminders'
import { SectionCard, Empty } from '@/components/Section'
import { ItemRow } from '@/components/ItemRow'
import { ThreadRow, groupThreads } from '@/components/Thread'
import { useApp } from '@/lib/app'
import { mdInline } from '@/lib/md'
import { EXTRA, SEC, type SectionDef } from '@/lib/sections'
import type { Call, Item, Task } from '@/lib/types'
import { IOS, cn, isoDate, openPicker } from '@/lib/utils'
import { taskInCtx } from '@/lib/data'
import { withUndo } from '@/components/Contacts'

export function ItemSection({ def, items }: { def: SectionDef; items: Item[] }) {
  const { ax } = useApp()
  // overdue first, then reminders; otherwise the order Axella wrote them in
  const open = items.filter(i => !ax.isHandled(i.id)).sort((a, b) => (+!!b.overdue - +!!a.overdue) || (+!!b.reminder - +!!a.reminder)), done = items.filter(i => ax.isHandled(i.id))
  return (
    <SectionCard id={def.key} color={def.color} icon={def.icon} title={def.title} sub={def.sub} count={open.length}
      handled={{ n: done.length, render: () => done.map(i => <ItemRow key={i.id} it={i} />) }}>
      {!open.length ? <Empty /> : def.key === 'file' ? <FilingGroups items={open} /> : open.map(i => <ItemRow key={i.id} it={i} />)}
    </SectionCard>
  )
}

const TRASH_MAX = 200                              // the action service refuses bigger batches

function FilingGroups({ items }: { items: Item[] }) {
  const { ax } = useApp()
  const [busy, setBusy] = useState(false)
  // ticked mails (ids); a thread ticks all its mails
  const [sel, setSel] = useState<Set<string>>(new Set())
  // Delete = move to Trash (recoverable in Mail), after a confirmation and 6 s to undo
  const [ask, setAsk] = useState<{ what: string; list: Item[] } | null>(null)
  const groups: Record<string, Item[]> = {}
  items.forEach(i => (groups[i.file_to || 'Other'] ||= []).push(i))
  const can = (i: Item) => ax.apiOk && !!i.message_id && !!i.file_to
  const picked = items.filter(i => sel.has(i.id))
  const toggle = (list: Item[], on: boolean) => setSel(s => { const n = new Set(s); list.forEach(i => on ? n.add(i.id) : n.delete(i.id)); return n })
  const clearOf = (list: Item[]) => toggle(list, false)

  async function fileList(list: Item[]) {
    setBusy(true); let ok = 0
    for (const i of list) { try { await ax.act('file', { item_id: i.id, account: i.account, message_id: i.message_id, folder: i.file_to }, []); ok++ } catch { /* next */ } }
    await ax.refresh(['state']); clearOf(list); setBusy(false)
    const folders = [...new Set(list.map(i => i.file_to))]
    const where = folders.length === 1 ? folders[0] : `${folders.length} folders`
    if (ok === list.length) toast(`Moved ${ok} to ${where}`); else toast.error(`Moved ${ok} of ${list.length} to ${where} – the rest are still here`)
  }
  function confirmTrash(list: Item[]) {
    setAsk(null); setBusy(true)
    let started = false
    withUndo(`Moving ${Math.min(list.length, TRASH_MAX)} to Trash…`, () => { started = true; trashList(list) })
    setTimeout(() => { if (!started) setBusy(false) }, 6100)
  }
  async function trashList(list: Item[]) {
    // one job on the Mac mini, at most TRASH_MAX mails, one line in the activity log (security review 5)
    setBusy(true)
    const batch = list.slice(0, TRASH_MAX)
    let moved = 0
    try {
      const r = await ax.act<{ result?: { moved?: number; pending?: boolean } }>('trash_batch', { items: batch.map(i => ({ item_id: i.id, account: i.account, message_id: i.message_id })) }, [])
      moved = r?.result?.pending ? -1 : r?.result?.moved ?? batch.length
    } catch { moved = 0 }
    await ax.refresh(['state']); clearOf(batch); setBusy(false)
    const rest = list.length - batch.length
    const more = rest > 0 ? ` – ${rest} more still here (${TRASH_MAX} at a time)` : ''
    if (moved === -1) return                     // still running: the background toast says when it's done
    if (moved === batch.length) toast(`Moved ${moved} to Trash – recoverable in Mail${more}`)
    else toast.error(`Moved ${moved} of ${batch.length} to Trash – the rest are still here${more}`)
  }
  const Tick = ({ list, label }: { list: Item[]; label: string }) => {
    const ok = list.filter(can), n = ok.filter(i => sel.has(i.id)).length
    if (!ok.length) return <span className="w-[18px] shrink-0" />
    return <Checkbox checked={n === 0 ? false : n === ok.length ? true : 'indeterminate'} disabled={busy} aria-label={label}
      onCheckedChange={() => toggle(ok, n < ok.length)} data-file-tick="" />
  }
  return <>
    {items.some(can) && <div className={cn('sticky top-0 z-10 flex min-h-11 flex-wrap items-center gap-2 border-b px-4 py-1.5 text-sm', picked.length ? 'bg-fjord-soft' : 'bg-card')} data-file-selbar="">
      <Tick list={items} label="Select all" />
      <span className={cn(picked.length ? 'font-medium' : 'text-ink-2')}>{picked.length ? `${picked.length} selected` : 'Select all'}</span>
      {picked.length > 0 && <>
        <Button size="pill" variant="ghost" className="h-6" disabled={busy} onClick={() => setSel(new Set())}>Clear</Button>
        <span className="ml-auto flex gap-1.5">
          <Button size="pill" variant="outline" className="h-7" disabled={busy} onClick={() => setAsk({ what: 'the selected mails', list: picked })} data-delete-selected=""><Trash2 />Delete</Button>
          <Button size="pill" variant="outline" className="h-7" disabled={busy} onClick={() => fileList(picked)} data-file-selected=""><CheckCheck />File</Button></span></>}
    </div>}
    {Object.entries(groups).map(([folder, list]) => (
    <div key={folder} className="divide-y">
      <div className="flex items-center gap-2 px-4 pt-2.5 pb-1.5 text-sm font-semibold">
        {list.length > 1 && <Tick list={list} label={'Select all for ' + folder} />}
        <Folder className="text-ink-2 size-4" />{folder}<Badge variant="secondary">{list.length}</Badge>
        {(() => { const n = groupThreads(list).length; return n < list.length ? <span className="text-ink-3 font-mono text-[11px] font-normal">{n} thread{n > 1 ? 's' : ''}</span> : null })()}
      </div>
      {groupThreads(list).map(t => <div key={t[0].id} className="flex items-start">
        <span className="flex min-h-11 items-center pt-3.5 pl-4">{list.some(can) && <Tick list={t} label={'Select ' + (t[0].subject || t[0].headline || 'mail')} />}</span>
        <div className="min-w-0 flex-1">{t.length > 1 ? <ThreadRow items={t} /> : <ItemRow it={t[0]} />}</div>
      </div>)}
    </div>))}
    {ask && <Dialog open onOpenChange={o => !o && !busy && setAsk(null)}>
      <DialogContent className="sm:w-[min(480px,92vw)]">
        <div className="flex gap-3 px-5 pt-5 pb-2 pr-12">
          <span className="bg-danger/10 text-danger flex size-10 shrink-0 items-center justify-center rounded-md"><Trash2 className="size-5" /></span>
          <div><DialogTitle className="text-lg leading-snug font-semibold">Delete {Math.min(ask.list.length, TRASH_MAX)} {ask.list.length === 1 ? 'mail' : 'mails'}?</DialogTitle>
            <ul className="text-ink-2 mt-1.5 space-y-1 text-sm">
              <li>{ask.what[0].toUpperCase() + ask.what.slice(1)} move to Trash instead of being filed.</li>
              {ask.list.length > TRASH_MAX && <li>{TRASH_MAX} at a time – the other {ask.list.length - TRASH_MAX} stay here for the next round.</li>}
              <li>You get 6 seconds to undo, and nothing is deleted for good – they can be recovered from Trash in Mail.</li>
            </ul></div>
        </div>
        <div className="flex justify-end gap-2 border-t px-5 py-3">
          <Button variant="ghost" disabled={busy} onClick={() => setAsk(null)}>Cancel</Button>
          <Button variant="destructive" disabled={busy} onClick={() => confirmTrash(ask.list)} data-delete-all-confirm="">
            <Trash2 />Move to Trash</Button>
        </div>
      </DialogContent>
    </Dialog>}</>
}

/* Tasks: the due date is not a floating badge. Open tasks are grouped by when they're due (Overdue · Today · This week ·
   Later · No date), and each row carries one quiet meta line under the title: the date, where it came from, a link. */
const DAY = 864e5
function dueInfo(d?: string | null) {
  if (!d) return { group: 'none' as const, diff: 0, label: '' }
  const t = new Date(d + 'T00:00'), today = new Date(); today.setHours(0, 0, 0, 0)
  const diff = Math.round((t.getTime() - today.getTime()) / DAY)
  const date = t.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
  const label = diff === 0 ? 'Today' : diff === 1 ? 'Tomorrow' : diff === -1 ? 'Yesterday' : diff < 0 ? `${-diff} days ago · ${date}` : date
  const group = diff < 0 ? 'overdue' : diff === 0 ? 'today' : diff <= 6 ? 'week' : 'later'
  return { group, diff, label } as { group: 'overdue' | 'today' | 'week' | 'later' | 'none'; diff: number; label: string }
}
const GROUPS: [ReturnType<typeof dueInfo>['group'], string][] = [['overdue', 'Overdue'], ['today', 'Today'], ['week', 'This week'], ['later', 'Later'], ['none', 'No date']]

/** Work / Private for a task is optional: unset, it shows under both filters. */
export { taskInCtx }
const CTX_NEXT = { '': 'work', work: 'private', private: '' } as const
function CtxChip({ value, onChange, title }: { value: '' | 'work' | 'private'; onChange: (v: '' | 'work' | 'private') => void; title?: string }) {
  const label = value === 'work' ? 'Work' : value === 'private' ? 'Private' : ''
  return <button type="button" onClick={() => onChange(CTX_NEXT[value])} title={title || 'Work or Private (optional) – tap to change'}
    aria-label={label ? label + ' – tap to change' : 'Mark as Work or Private'}
    className={cn('inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md border px-2.5 font-mono text-[12px] transition-colors',
      value ? 'border-fjord text-fjord bg-fjord-soft' : 'border-line-strong text-ink-3 hover:text-ink')}>
    {value === 'private' ? <Home className="size-4" /> : <Briefcase className="size-4" />}{label && <span>{label}</span>}</button>
}

export function TaskRow({ t }: { t: Task }) {
  const { ax } = useApp()
  const [armed, setArmed] = useState(false)
  const [open, setOpen] = useState(false), [notes, setNotes] = useState(t.notes || '')
  const done = t.status === 'done'
  const saveNotes = async () => {
    try { await ax.act('task_update', { id: t.id, notes }, ['tasks']); toast(notes.trim() ? 'Details saved' : 'Details removed'); setOpen(false) } catch (e: any) { toast.error('Failed: ' + e.message) }
  }
  // what "Open in Claude" hands over: the task, and its details when there are any
  const prompt = t.text + (t.notes?.trim() ? '\n\n' + t.notes.trim() : '')
  const due = dueInfo(t.due)
  const reminders = useReminders()
  const run = async (a: string, msg: string) => { try { await ax.act(a, { id: t.id }, ['tasks']); toast(msg) } catch (e: any) { toast.error('Failed: ' + e.message) } }
  const setCtx = async (ctx: '' | 'work' | 'private') => {
    try { await ax.act('task_update', { id: t.id, ctx: ctx || null }, ['tasks']); toast(ctx ? 'Marked as ' + (ctx === 'work' ? 'Work' : 'Private') : 'Work/Private removed') } catch (e: any) { toast.error('Failed: ' + e.message) }
  }
  const meta = [
    t.ctx && <span key="c" className="inline-flex items-center gap-1">{t.ctx === 'work' ? <Briefcase className="size-3.5" /> : <Home className="size-3.5" />}{t.ctx === 'work' ? 'Work' : 'Private'}</span>,
    // inside the Today group the date says nothing new; in Done it's history
    !done && t.due && due.group !== 'today' && <span key="d" className={cn('inline-flex items-center gap-1.5', due.group === 'overdue' && 'text-ink-2')}>
      {due.group === 'overdue' && <span className="ax-diamond text-dawn" style={{ width: 6, height: 6 }} />}{due.label}</span>,
    t.reminder ? <span key="r" className="inline-flex items-center gap-1" title="Made by a recurring reminder – manage under Settings">
      <Recurring className="size-3.5" />{reminders?.find(r => r.id === t.reminder)?.label || 'Recurring'}</span>
      : t.source === 'promise' ? <span key="s">Promised to {String((t.ref?.person as { name?: string } | undefined)?.name || 'someone')}</span>
      : t.type === 'bill' && t.bill ? <span key="s" className="inline-flex items-center gap-1"><Receipt className="size-3.5" />Bill{t.bill.amount != null && <> · <BillMeta b={t.bill} /></>}
        {(t.bill.first_time || t.bill.details_differ || t.bill.sender_differs) && <span className="text-dawn" data-bill-flag="">· {t.bill.sender_differs ? 'from another address than earlier bills' : t.bill.details_differ ? 'payment details differ from earlier bills' : 'first bill from this sender'}</span>}</span>
      : t.source && t.source !== 'dashboard' && <span key="s">via {t.source}</span>,
    // a mail Axella knows (a bill's, a promise's): opened in Axella's own reader; otherwise Mail's link on the Mac
    !done && (t.bill?.message_id && t.bill.account
      ? <button key="l" type="button" className="text-fjord inline-flex items-center gap-1 hover:underline" onClick={() => openMailInAxella({ account: t.bill!.account, message_id: t.bill!.message_id, subject: t.bill!.subject })}><Mail className="size-3" />Open message</button>
      : t.ref?.deep_link && !IOS && <a key="l" className="text-fjord inline-flex items-center gap-1 hover:underline" href={t.ref.deep_link}><ExternalLink className="size-3" />Open message</a>),
  ].filter(Boolean)
  return (
    <div className={cn('flex min-h-11 items-start gap-3 px-4 py-2.5', done && 'opacity-50')}>
      <Checkbox className="mt-[3px]" checked={done} aria-label="Done" onCheckedChange={() => run(done ? 'task_undo' : 'task_done', done ? 'Task reopened' : 'Task done')} />
      <div className="min-w-0 flex-1">
        <button type="button" onClick={() => { setNotes(t.notes || ''); setOpen(!open) }} title={open ? 'Close' : t.notes ? 'Show and edit the details' : 'Add details'}
          className={cn('block w-full text-left text-[15px] leading-snug', done && 'line-through')}>{t.text}
          {t.notes?.trim() && <StickyNote className="text-ink-3 ml-1.5 inline size-3.5 align-[-2px]" aria-label="Has details" />}</button>
        {t.notes?.trim() && !open && <div className="text-ink-3 mt-0.5 line-clamp-2 text-[13px] whitespace-pre-line">{t.notes}</div>}
        {open && <div className="mt-2 space-y-2">
          {t.type === 'bill' && <BillDetails t={t} />}
          <textarea autoFocus value={notes} onChange={e => setNotes(e.target.value)} maxLength={4000} rows={Math.min(14, Math.max(4, notes.split('\n').length + 1))}
            placeholder={'Details – background, links, what "done" looks like. Handed to Claude with ✦ Open in Claude.'}
            className="border-input bg-card focus-visible:ring-ring/50 w-full rounded-md border px-3 py-2 text-[14px] leading-relaxed outline-none focus-visible:ring-2" />
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={saveNotes} disabled={notes === (t.notes || '')}>Save</Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            <span className="bg-bg-2 ml-2 inline-flex rounded-md border p-0.5 text-[12px]" role="group" aria-label="Work or Private">
              {([['', 'Either'], ['work', 'Work'], ['private', 'Private']] as const).map(([v, l]) =>
                <button key={v} type="button" onClick={() => setCtx(v)} aria-pressed={(t.ctx || '') === v}
                  className={cn('rounded px-2 py-1', (t.ctx || '') === v ? 'bg-card text-ink font-semibold shadow-sm' : 'text-ink-3 hover:text-ink')}>{l}</button>)}
            </span>
            <span className="text-ink-3 ml-auto font-mono text-[11px]">{notes.length > 3500 ? `${notes.length}/4000` : ''}</span>
          </div>
        </div>}
        {!!meta.length && <div className="text-ink-3 mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[12px]">{meta}</div>}
      </div>
      <div className="-my-1.5 -mr-2 flex shrink-0 items-center">
        {!done && <DueMenu t={t} />}
        {!done && <a className="text-ink-3 flex size-8 items-center justify-center rounded-md transition-colors hover:text-[#d97757]" title="Open in Claude" aria-label="Open in Claude"
          // desktop: the Claude app's own link (prefilled, you review and send); iPhone: claude.ai, which hands over to the app if installed
          href={(IOS ? 'https://claude.ai/new?q=' : 'claude://claude.ai/new?q=') + encodeURIComponent(prompt)}
          {...(IOS ? { target: '_blank', rel: 'noopener noreferrer' } : {})}><Sparkles className="size-4" /></a>}
        <button className={cn('text-ink-3 hover:text-danger flex h-8 min-w-8 items-center justify-center rounded-md px-1 text-xs', armed && 'text-danger font-medium')} aria-label="Delete"
          onClick={() => { if (armed) run('task_delete', 'Task deleted'); else { setArmed(true); setTimeout(() => setArmed(false), 3000) } }}>
          {armed ? 'Delete?' : <X className="size-4" />}</button>
      </div>
    </div>
  )
}

/* move a task: quick dates, a picked date, or no date */
function DueMenu({ t }: { t: Task }) {
  const { ax } = useApp()
  const date = useRef<HTMLInputElement>(null)
  const day = (n: number) => { const d = new Date(); d.setDate(d.getDate() + n); return d }
  const monday = (() => { const d = day(1); while (d.getDay() !== 1) d.setDate(d.getDate() + 1); return d })()
  const fmt = (d: Date) => d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
  const set = async (due: string | null, label: string) => {
    try { await ax.act('task_update', { id: t.id, due }, ['tasks']); toast(due ? 'Moved to ' + label : 'Date removed') } catch (e: any) { toast.error('Failed: ' + e.message) }
  }
  const opts: [string, Date][] = [['Today', day(0)], ['Tomorrow', day(1)], ['Monday', monday], ['In a week', day(7)]]
  return <span className="relative inline-flex">
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="text-ink-3 hover:text-ink flex size-8 items-center justify-center rounded-md" title="Change date" aria-label="Change date"><CalendarPlus className="size-4" /></button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <div className="text-ink-3 px-2.5 pt-1.5 pb-1 text-[11px]">{t.due ? 'Due ' + fmt(new Date(t.due + 'T12:00')) : 'No date'}</div>
        {opts.filter(([, d], i, a) => a.findIndex(x => isoDate(x[1]) === isoDate(d)) === i && isoDate(d) !== t.due).map(([l, d]) =>
          <DropdownMenuItem key={l} onSelect={() => set(isoDate(d), fmt(d))}><span className="flex-1">{l}</span><span className="text-ink-3 font-mono text-[12px]">{fmt(d)}</span></DropdownMenuItem>)}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => setTimeout(() => { const el = date.current; if (!el) return; try { el.showPicker() } catch { el.focus(); el.click() } }, 50)}>Pick a date…</DropdownMenuItem>
        {t.due && <DropdownMenuItem onSelect={() => set(null, '')}>Remove date</DropdownMenuItem>}
      </DropdownMenuContent>
    </DropdownMenu>
    <input ref={date} type="date" aria-label="Due date" defaultValue={t.due || ''} className="pointer-events-none absolute inset-0 opacity-0"
      onChange={e => { if (e.target.value) set(e.target.value, fmt(new Date(e.target.value + 'T12:00'))) }} />
  </span>
}

export function TasksCard({ filter, title, sub, tag }: { filter?: (t: Task) => boolean; title?: string; sub?: string; tag?: string }) {
  const { ax, go, ctx } = useApp()
  const [text, setText] = useState(''), [due, setDue] = useState(''), [every, setEvery] = useState<Every | null>(null), [notes, setNotes] = useState('')
  // a new task starts in the filter you're looking at (Work or Private), else unset – tap to change
  const [tctx, setTctx] = useState<'' | 'work' | 'private'>(ctx === 'all' ? '' : ctx)
  const reminders = useReminders()
  const all = (filter ? ax.tasks.filter(filter) : ax.tasks).filter(t => taskInCtx(t, ctx))
  const open = all.filter(t => t.status !== 'done').sort((a, b) => (a.due || '9999').localeCompare(b.due || '9999'))
  const done = all.filter(t => t.status === 'done').slice(-10).reverse()
  const groups = GROUPS.map(([g, l]) => [g, l, open.filter(t => dueInfo(t.due).group === g)] as const).filter(x => x[2].length)
  async function add(e: React.FormEvent) {
    e.preventDefault(); if (!text.trim()) return
    const body = text.trim() + (tag && !text.includes('#' + tag) ? ' #' + tag : '')
    try {
      if (every) {   // a repeating to-do: the Mac mini makes a task for every occurrence (setup/reminders.py)
        const start = due || isoDate(new Date())
        await ax.act('reminder_add', { text: body, every, interval: 1, start, lead: 0, push: true }, ['tasks'])
        await loadReminders(true)
        toast(`${describe(every, 1, start)} – first on ${short(start)}`)
      } else {
        await ax.act('task_add', { text: body, due: due || null, source: 'dashboard', notes: notes.trim() || undefined, ctx: tctx || undefined }, ['tasks'])
        toast('Task added' + (tctx ? ' · ' + (tctx === 'work' ? 'Work' : 'Private') : ''))
      }
      setText(''); setDue(''); setEvery(null); setNotes(''); setTctx(ctx === 'all' ? '' : ctx)
    } catch (err: any) { toast.error('Failed: ' + err.message) }
  }
  const dueShort = due ? new Date(due + 'T12:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : ''
  return (
    <SectionCard id="tasks" color={EXTRA.tasks.color} icon={EXTRA.tasks.icon} title={title || EXTRA.tasks.title} sub={sub || EXTRA.tasks.sub} count={open.length}
      handled={{ n: done.length, label: 'Done', render: () => done.map(t => <TaskRow key={t.id} t={t} />) }}>
      {ax.apiOk && (!filter || tag) && <form onSubmit={add} className="p-3">
        <div className="flex gap-2">
        <Input value={text} onChange={e => setText(e.target.value)} placeholder="Add a task…" maxLength={500} className="min-w-0 flex-1" />
        {/* a compact date chip; the real date input sits invisibly on top so the phone's own picker opens */}
        <label className={cn('relative inline-flex h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-md border px-2.5 font-mono text-[12px] transition-colors',
          due ? 'border-fjord text-fjord bg-fjord-soft' : 'border-line-strong text-ink-3 hover:text-ink')} title="Due date">
          <CalendarPlus className="size-4" /><span className={cn(!due && 'max-sm:hidden')}>{dueShort || 'Due'}</span>
          <input type="date" onClick={openPicker} value={due} onChange={e => setDue(e.target.value)} aria-label="Due date" className="absolute inset-0 cursor-pointer opacity-0" />
        </label>
        {due && <button type="button" aria-label="Clear due date" onClick={() => setDue('')} className="text-ink-3 hover:text-ink -ml-1 shrink-0"><X className="size-4" /></button>}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button type="button" title="Repeat" aria-label={every ? EVERY_LABEL[every] : 'Repeat'}
              className={cn('inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md border px-2.5 font-mono text-[12px] transition-colors',
                every ? 'border-fjord text-fjord bg-fjord-soft' : 'border-line-strong text-ink-3 hover:text-ink')}>
              <Recurring className="size-4" />{every && <span>{({ day: 'Daily', week: 'Weekly', month: 'Monthly', year: 'Yearly' } as const)[every]}</span>}</button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-60">
            <div className="text-ink-3 px-2.5 pt-1.5 pb-1 text-xs">Repeat – Axella adds the task each time{due ? '' : ', starting today'}</div>
            <DropdownMenuItem onSelect={() => setEvery(null)} className={cn(!every && 'text-fjord')}>Doesn’t repeat</DropdownMenuItem>
            {(['day', 'week', 'month', 'year'] as Every[]).map(e => <DropdownMenuItem key={e} onSelect={() => setEvery(e)} className={cn(every === e && 'text-fjord')}>
              <span className="flex-1">{EVERY_LABEL[e]}</span><span className="text-ink-3 text-xs">{e === 'day' ? '' : describe(e, 1, due || isoDate(new Date())).replace(/^Every \w+ /, '')}</span></DropdownMenuItem>)}
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => { go({ kind: 'settings', page: 'reminders' }) }}>
              <Recurring />More options…</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        {!every && <CtxChip value={tctx} onChange={setTctx} />}
        <Button size="icon-sm" type="submit" aria-label="Add" className="size-9 shrink-0"><Plus /></Button>
        </div>
        {/* details appear once there is a task to describe; repeating to-dos keep just the line */}
        {text.trim() && !every && <textarea value={notes} onChange={e => setNotes(e.target.value)} maxLength={4000} rows={notes ? 4 : 2}
          placeholder="Details (optional) – background, links, what “done” looks like. Handed to Claude with ✦ Open in Claude."
          className="border-input bg-card focus-visible:ring-ring/50 mt-2 w-full rounded-md border px-3 py-2 text-[14px] leading-relaxed outline-none focus-visible:ring-2" />}
      </form>}
      {!open.length ? <Empty>No open tasks</Empty>
        : groups.length === 1 && groups[0][0] === 'none' ? open.map(t => <TaskRow key={t.id} t={t} />)
        : groups.map(([g, l, list]) => <div key={g} className="divide-y">
            <div className="bg-bg-2/60 flex items-center gap-2 px-4 py-1.5">
              {g === 'overdue' && <span className="ax-diamond text-dawn" style={{ width: 7, height: 7 }} />}
              <span className={cn('ax-label', g === 'overdue' && 'text-ink-2')}>{l}</span>
              <span className="text-ink-3 ml-auto font-mono text-[12px] tabular-nums">{list.length}</span>
            </div>
            {list.map(t => <TaskRow key={t.id} t={t} />)}
          </div>)}
      {!filter && !!reminders?.length && <button onClick={() => { go({ kind: 'settings', page: 'reminders' }) }}
        className="text-ink-3 hover:text-ink flex w-full items-center gap-1.5 border-t px-4 py-2.5 text-left text-[13px]">
        <Recurring className="size-4" />{reminders.length} recurring {reminders.length === 1 ? 'reminder' : 'reminders'}
        {reminders.some(r => r.paused) && <span>· {reminders.filter(r => r.paused).length} paused</span>}<span className="text-fjord ml-auto">Manage</span></button>}
    </SectionCard>
  )
}

const PRIO: Record<string, [string, string]> = { p0: ['Urgent', 'var(--ax-p0)'], p1: ['Before noon', 'var(--ax-p1)'], p2: ['Today', 'var(--ax-p2)'], p3: ['FYI', 'var(--ax-p3)'] }
const dur = (s = 0) => { const m = Math.floor(s / 60), r = s % 60; return m ? `${m} min ${r} s` : `${r} s` }

export function CallRow({ c }: { c: Call }) {
  const { ax } = useApp()
  const [pl, pc] = PRIO[c.priority || 'p3'] || PRIO.p3
  const t = new Date(c.started || ''), time = t.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  const day = t.toDateString() === new Date().toDateString() ? 'Today' : t.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
  const num = (c.from?.number || '').replace(/\s/g, ''), handled = ax.isHandled(c.id)
  // Caller ID can be faked: the contact name is only "matches caller ID" unless the caller gave the same first name.
  // Records from before Nov 2026 (and demo calls) have no caller_id_match: show their name as before.
  const legacy = c.from?.caller_id_match === undefined
  const contact = c.from?.caller_id_match ? c.from?.name : null, said = legacy ? c.from?.name : c.from?.said_name
  const same = legacy || (!!contact && !!said && said.split(' ')[0].toLowerCase() === contact.split(' ')[0].toLowerCase())
  const shown = (legacy ? said : same ? contact : said || (contact ? contact + '?' : '')) || c.from?.number || ''
  const who = (legacy ? said : same ? contact : said || contact) || c.from?.number || ''
  const run = async (a: string, body: any, msg: string, r: any[] = ['state']) => { try { await ax.act(a, body, r); toast(msg) } catch (e: any) { toast.error('Failed: ' + e.message) } }
  return (
    <div className={cn('flex gap-3 px-4 py-3', handled && 'opacity-50')} style={{ ['--c' as any]: pc }}>
      <div className="bg-fjord-soft text-fjord flex size-9 shrink-0 items-center justify-center rounded-md"><PhoneIncoming className="size-[18px]" /></div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-semibold">{shown || 'Unknown caller'}</span>
          {c.from?.tier === 'VIP' && <Badge variant="warning">{same ? 'VIP' : 'VIP?'}</Badge>}
          <Badge variant="outline" style={{ color: pc, borderColor: pc }}>{c.urgent_claimed ? 'Caller says urgent' : pl}</Badge>
          {c.demo && <Badge variant="secondary">Demo</Badge>}
        </div>
        <div className="text-muted-foreground text-xs">{day} {time} · {dur(c.duration_s)}{shown !== c.from?.number && c.from?.number ? ' · ' + c.from.number : ''}{c.context ? ' · ' + c.context : ''}</div>
        {!legacy && contact && !same && <div className="text-ink-2 mt-0.5 text-xs">{said ? `Said they are ${said} – caller ID matches ${contact}` : `Caller ID matches ${contact} – not confirmed in the call`}</div>}
        {c.urgent_capped && <div className="text-ink-2 mt-0.5 text-xs">Also said urgent – this number already had an urgent call today, so no urgent push.</div>}
        <div className="md-inline mt-1 text-[14.5px]" dangerouslySetInnerHTML={{ __html: mdInline(c.summary, { links: false }) }} />
        {(c.callback?.by || c.callback?.number) && <div className="mt-1 flex items-center gap-1.5 text-sm"><AlarmClock className="text-fjord size-3.5" />Wants a call back{c.callback.by ? ' ' + c.callback.by : ''}{c.callback.number ? ' on ' + c.callback.number : ''}</div>}
        {c.callback?.other_number && <div className="mt-1 text-sm"><span className="bg-dawn text-on-dawn mr-1.5 rounded-sm px-1.5 text-xs">Check</span>Asked to be called back on a different number than the one they called from.</div>}
        {c.sms_draft && <div className="bg-muted/70 mt-2 rounded-lg border-l-[3px] border-l-primary px-3 py-2 text-sm">{c.sms_draft}</div>}
        {!!c.transcript?.length && <details className="mt-2 text-sm"><summary className="text-muted-foreground cursor-pointer">Transcript</summary>
          <div className="bg-muted/70 mt-1 rounded-lg px-3 py-2">{c.transcript.map((l, i) => <div key={i} className="mb-1"><b>{l.who}:</b> {l.text}</div>)}</div></details>}
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {num && <Button size="pill" asChild><a href={'tel:' + num}><Phone />Call back</a></Button>}
          {num && c.sms_draft && <Button size="pill" variant="outline" asChild><a href={`sms:${num}${IOS ? '&' : '?'}body=${encodeURIComponent(c.sms_draft)}`}><MessageCircle />Reply by SMS</a></Button>}
          {c.callback_event && <Button size="pill" variant="outline" disabled={!ax.apiOk || c.demo}
            onClick={() => run('event', { item_id: c.id, ...c.callback_event }, 'Callback booked')}><CalendarPlus />Book callback</Button>}
          {ax.apiOk && !c.demo && <>
            <Button size="pill" variant="outline" onClick={() => run('task_add', { text: 'Call back ' + who + (c.callback?.by ? ` (${c.callback.by})` : ''), due: isoDate(new Date()), source: 'call', ref: { call_id: c.id } }, 'Added to To do', ['tasks'])}><SquarePlus />Task</Button>
            {handled ? <Button size="pill" variant="outline" onClick={() => run('undo', { item_id: c.id }, 'Restored')}><Undo2 />Undo</Button>
              : <Button size="pill" variant="success" onClick={() => run('done', { item_id: c.id, title: 'Call: ' + who }, 'Call marked as handled')}><Check />Done</Button>}
          </>}
        </div>
      </div>
    </div>
  )
}

export function CallsCard({ calls }: { calls: Call[] }) {
  const { ax } = useApp()
  const open = calls.filter(c => !ax.isHandled(c.id)), done = calls.filter(c => ax.isHandled(c.id))
  return (
    <SectionCard id="calls" color={EXTRA.calls.color} icon={EXTRA.calls.icon} title="Calls" sub={ax.callCfg?.mode_label ? 'Axella · ' + ax.callCfg.mode_label : EXTRA.calls.sub}
      count={open.length} handled={{ n: done.length, render: () => done.map(c => <CallRow key={c.id} c={c} />) }}>
      {open.length ? open.map(c => <CallRow key={c.id} c={c} />) : <Empty>No calls to follow up</Empty>}
    </SectionCard>
  )
}

function ago(iso?: string) {
  if (!iso) return '–'
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return m + ' min ago'
  if (m < 48 * 60) return Math.round(m / 60) + ' h ago'
  return Math.round(m / 1440) + ' days ago'
}

export function CallSettingsCard() {
  const c = useApp().ax.callCfg
  if (!c) return null
  const stale = !c.last_sync || Date.now() - new Date(c.last_sync).getTime() > 10 * 60000
  const Row = ({ k, children }: { k: string; children: React.ReactNode }) =>
    <div><div className="mb-1 font-semibold">{k}</div>{children}</div>
  return (
    <SectionCard id="callcfg" color={EXTRA.calls.color} icon={Phone} title="Call agent" sub={c.demo ? 'Preview – not connected yet' : 'Answers when you don’t – greeting, callers, transcripts'}>
      <div className="space-y-3 p-4 text-sm">
        <Row k="Status">
          <div className="flex items-center gap-2">
            <span className={'ax-diamond ' + (c.last_error || stale ? 'text-dawn' : 'text-success')} style={{ width: 7, height: 7 }} />
            <span>On · taking messages{c.number ? ' · ' + c.number : ''}</span>
          </div>
          <div className="text-muted-foreground mt-0.5">Last check {ago(c.last_sync)} · last call {ago(c.last_call)}</div>
          {c.last_error && <div className="text-ink mt-1"><span className="bg-dawn text-on-dawn mr-1.5 rounded-sm px-1.5 text-xs">Problem</span>Sync problem {ago(c.last_error_at)}: {c.last_error}</div>}
          {!c.last_error && stale && <div className="text-ink-2 mt-1">The Mac mini hasn't checked for calls for a while – new calls wait on Vercel until it does.</div>}
        </Row>
        <Row k="Greeting callers hear">
          {c.greeting_da || c.greeting_en ? <>
            {c.greeting_da && <div className="bg-muted/70 rounded-lg px-3 py-2"><span className="text-muted-foreground mr-1.5 text-xs font-semibold">DA</span>{c.greeting_da}</div>}
            {c.greeting_en && <div className="bg-muted/70 mt-1.5 rounded-lg px-3 py-2"><span className="text-muted-foreground mr-1.5 text-xs font-semibold">EN</span>{c.greeting_en}</div>}
          </> : <span className="text-muted-foreground">Shown after the next contact sync</span>}
          <div className="text-muted-foreground mt-1">Danish for +45 numbers, English otherwise – switches if the caller speaks the other language.</div>
        </Row>
        <Row k="Callers recognised">
          {c.contacts != null ? `${c.contacts} numbers from Contacts · ${c.vips ?? 0} VIPs` : '–'}
          {c.lookup === 'hashed' && <div className="text-muted-foreground mt-0.5">Sent as fingerprints with first names only – no numbers or full names leave the Mac mini.</div>}
          {c.lookup === 'plain' && <div className="text-ink-2 mt-0.5">Names and numbers are sent in plain form – add a lookup key (setup guide, call agent step 5) to send fingerprints instead.</div>}
          {c.lookup === 'key-missing-on-vercel' && <div className="text-ink mt-0.5"><span className="bg-dawn text-on-dawn mr-1.5 rounded-sm px-1.5 text-xs">Problem</span>The lookup key is set on the Mac mini but not on Vercel – callers aren't recognised until VOICE_LOOKUP_KEY is added there.</div>}
          <div className="text-muted-foreground mt-0.5">Updated every 6 hours · last {ago(c.config_pushed)}</div>
        </Row>
        <Row k="Transcripts">Full transcript and summary for every call · kept {c.retention_days || 30} days on the Mac mini, removed from Vercel once fetched</Row>
      </div>
    </SectionCard>
  )
}

/* Today shows the call agent only when it needs attention; the full card lives in Settings. */
export function CallAgentAlert() {
  const { ax, go } = useApp()
  const c = ax.callCfg
  if (!c || c.demo) return null
  const stale = !c.last_sync || Date.now() - new Date(c.last_sync).getTime() > 10 * 60000
  if (!c.last_error && !stale) return null
  return <button onClick={() => { go({ kind: 'settings', page: 'calls' }) }}
    className="bg-card hover:border-line-strong flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-left text-sm transition-colors">
    <span className="ax-diamond text-dawn mt-1.5 shrink-0" style={{ width: 7, height: 7 }} />
    <span className="min-w-0 flex-1"><span className="font-semibold">Call agent</span>
      <span className="text-ink-2 block">{c.last_error ? `Sync problem ${ago(c.last_error_at)}: ${c.last_error}` : `The Mac mini last checked for calls ${ago(c.last_sync)} – new calls wait on Vercel.`}</span></span>
    <span className="text-fjord shrink-0 text-[13px]">Details</span>
  </button>
}

export { SEC }
