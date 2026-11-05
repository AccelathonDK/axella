/* Add as task – the form opens at once with the item's headline; for a mail, Claude reads it on the Mac mini (no tools,
   nothing saved) and proposes a title, details and – only when the mail gives one – a due date. Fields you have already
   changed are left alone. Nothing is added until you tap Add. */
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { CalendarPlus, Loader2, SquarePlus, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { post } from '@/lib/api'
import { useApp } from '@/lib/app'
import { ctxOf } from '@/lib/data'
import type { Item } from '@/lib/types'
import { cn, isoDate, openPicker } from '@/lib/utils'

export type TaskFrom = { item: Item; digest?: string; dueToday?: boolean }
type Proposal = { title: string; details: string; due: string | null; due_reason: string | null }

export const openTaskFrom = (d: TaskFrom) => window.dispatchEvent(new CustomEvent('ax-task-from', { detail: d }))
export function TaskFromHost() {
  const [open, setOpen] = useState<TaskFrom | null>(null)
  useEffect(() => { const h = (e: Event) => setOpen((e as CustomEvent).detail); window.addEventListener('ax-task-from', h); return () => window.removeEventListener('ax-task-from', h) }, [])
  return open ? <TaskFromDialog key={open.item.id} from={open} onClose={() => setOpen(null)} /> : null
}

const isMail = (it: Item) => !!it.message_id && !!it.account && (!it.channel || it.channel === 'mail')
const short = (d: string) => new Date(d + 'T12:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })

function TaskFromDialog({ from, onClose }: { from: TaskFrom; onClose: () => void }) {
  const { ax } = useApp()
  const it = from.item
  const [title, setTitle] = useState((it.headline || it.subject || it.detail || 'Task').replace(/^→\s*[^:]+:\s*/, ''))   // a filing headline "→ Folder: …" without its folder
  const [notes, setNotes] = useState('')
  const [due, setDue] = useState(from.dueToday ? isoDate(new Date()) : '')
  // Work / Private: the mail's own (as the dashboard sorts it); optional, change or clear it here
  const [tctx, setTctx] = useState<'' | 'work' | 'private'>(() => { try { return ctxOf(it, ax.overrides) } catch { return '' } })
  const [why, setWhy] = useState<string | null>(null)
  const [state, setState] = useState<'reading' | 'done' | 'failed' | 'off'>(isMail(it) ? 'reading' : 'off')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const touched = useRef({ title: false, notes: false, due: false })
  const [secs, setSecs] = useState(0), [flash, setFlash] = useState(false)
  useEffect(() => {                       // a running count while Claude reads – it usually takes 10–30 s
    if (state !== 'reading') return
    setSecs(0); const t = setInterval(() => setSecs(s => s + 1), 1000); return () => clearInterval(t)
  }, [state])

  function read() {
    setState('reading'); setErr('')
    post<{ result: Proposal }>('task_suggest', { account: it.account, message_id: it.message_id, item_id: it.id, title: it.headline || '' })
      .then(({ result: p }) => {
        if (!touched.current.title) setTitle(p.title)
        if (!touched.current.notes) setNotes(p.details || '')
        if (!touched.current.due && p.due) { setDue(p.due); setWhy(p.due_reason) }
        setState('done'); setFlash(true); setTimeout(() => setFlash(false), 1400)
      }, e => { setErr(e.message); setState('failed') })
  }
  useEffect(() => { if (isMail(it)) read() }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  async function add() {
    if (!title.trim()) return
    setBusy(true)
    try {
      await ax.act('task_add', {
        text: title.trim().slice(0, 500), due: due || null, notes: notes.trim() || undefined, source: 'digest', ctx: tctx || undefined,
        ref: { digest: from.digest, item_id: it.id, message_id: it.message_id || null, deep_link: it.deep_link || null },
      }, ['tasks'])
      toast('Added to To do' + (due ? ' – due ' + short(due) : ''))
      onClose()
    } catch (e: any) { toast.error('Could not add the task: ' + e.message); setBusy(false) }
  }

  return (
    <Dialog open onOpenChange={o => !o && onClose()}>
      <DialogContent className="sm:w-[min(560px,92vw)]" data-task-from="">
        {state === 'reading' && <div className="bg-fjord-soft absolute inset-x-0 top-0 h-[3px] overflow-hidden" aria-hidden><div className="ax-indeterminate bg-fjord h-full w-1/3" /></div>}
        <div className="space-y-3 overflow-y-auto px-5 pt-4 pb-5">
          <DialogTitle className="flex items-center gap-2 pr-8 text-lg font-semibold"><SquarePlus className="size-5" />Add as task</DialogTitle>
          <div className={cn('text-[13px]', state === 'failed' ? 'text-dawn' : 'text-ink-3')} aria-live="polite">
            {state === 'reading' && <span className="text-ink-2 inline-flex items-center gap-2"><Loader2 className="text-fjord size-4 animate-spin" />Axella is reading the mail and proposing the task…{secs >= 3 && <span className="text-ink-3 font-mono text-[12px]">{secs} s</span>}</span>}
            {state === 'done' && 'Proposed from the mail – change anything before you add it.'}
            {state === 'failed' && <>Couldn't propose a task: {err} <button className="text-fjord font-semibold hover:underline" onClick={read}>Try again</button></>}
            {state === 'off' && 'From this item – edit it and add.'}
          </div>
          <label className="block"><span className="mb-1 block text-[13px] font-semibold">Task</span>
            <Input value={title} maxLength={500} className={cn('transition-shadow duration-700', flash && !touched.current.title && 'ring-fjord/60 ring-2')} autoFocus={state === 'off'}
              onChange={e => { touched.current.title = true; setTitle(e.target.value) }} onKeyDown={e => { if (e.key === 'Enter') add() }} /></label>
          <div><span className="mb-1 block text-[13px] font-semibold">Due</span>
            <div className="flex flex-wrap items-center gap-2">
              <label className={cn('relative inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-md border px-2.5 font-mono text-[12px] transition-colors',
                due ? 'border-fjord text-fjord bg-fjord-soft' : 'border-line-strong text-ink-3 hover:text-ink')}>
                <CalendarPlus className="size-4" />{due ? short(due) : 'No date'}
                <input type="date" onClick={openPicker} value={due} aria-label="Due date" className="absolute inset-0 cursor-pointer opacity-0"
                  onChange={e => { touched.current.due = true; setDue(e.target.value); setWhy(null) }} />
              </label>
              {due && <button type="button" aria-label="Clear due date" className="text-ink-3 hover:text-ink" onClick={() => { touched.current.due = true; setDue(''); setWhy(null) }}><X className="size-4" /></button>}
              {why && <span className="text-ink-3 text-[12.5px]">from the mail: {why}</span>}
            </div></div>
          <div><span className="mb-1 block text-[13px] font-semibold">Work or Private <span className="text-ink-3 font-normal">(optional)</span></span>
            <span className="bg-bg-2 inline-flex rounded-md border p-0.5 text-[13px]" role="group" aria-label="Work or Private">
              {([['', 'Either'], ['work', 'Work'], ['private', 'Private']] as const).map(([v, l]) =>
                <button key={v} type="button" onClick={() => setTctx(v)} aria-pressed={tctx === v}
                  className={cn('rounded px-2.5 py-1', tctx === v ? 'bg-card text-ink font-semibold shadow-sm' : 'text-ink-3 hover:text-ink')}>{l}</button>)}
            </span></div>
          <label className="relative block"><span className="mb-1 block text-[13px] font-semibold">Details</span>
            {state === 'reading' && !notes && <span className="pointer-events-none absolute inset-x-3 top-9 space-y-2.5" aria-hidden>
              {['w-11/12', 'w-4/5', 'w-2/3'].map(w => <span key={w} className={cn('ax-shimmer block h-3 rounded', w)} />)}</span>}
            <textarea value={notes} maxLength={4000} rows={Math.min(10, Math.max(4, notes.split('\n').length + 1))}
              onChange={e => { touched.current.notes = true; setNotes(e.target.value) }}
              placeholder={state === 'reading' ? '' : 'Background, links, what "done" looks like (optional)'}
              className={cn('border-input bg-card focus-visible:ring-ring/50 w-full rounded-md border px-3 py-2 text-[14px] leading-relaxed outline-none focus-visible:ring-2 transition-shadow duration-700',
                flash && !touched.current.notes && notes && 'ring-fjord/60 ring-2')} /></label>
          <div className="flex items-center gap-2 pt-1">
            <Button onClick={add} disabled={busy || !title.trim()}>Add task</Button>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            {state === 'reading' && <span className="text-ink-3 ml-auto text-[12px]">You can add it now – the proposal is optional.</span>}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
