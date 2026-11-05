import { useState } from 'react'
import { toast } from 'sonner'
import { Loader2, Pause, Pencil, Play, Plus, Recurring, X } from '@/components/ax-icons'
import { SectionCard, Empty } from '@/components/Section'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input, NativeSelect } from '@/components/ui/input'
import { useApp } from '@/lib/app'
import { describe, loadReminders, short, useReminders, type Every, type Reminder } from '@/lib/reminders'
import { cn, isoDate } from '@/lib/utils'

/* Settings → Recurring reminders: repeating to-dos. The Mac mini (setup/reminders.py) adds a task to To do for every
   occurrence – on the day, or a few days before – and can push you when it does. Nothing is ever sent. */
type Form = { text: string; every: Every; interval: number; start: string; lead: number; push: boolean }
const blank = (): Form => ({ text: '', every: 'month', interval: 1, start: isoDate(new Date()), lead: 0, push: true })
const UNIT: Record<Every, [string, string]> = { day: ['day', 'days'], week: ['week', 'weeks'], month: ['month', 'months'], year: ['year', 'years'] }

export function RemindersCard() {
  const { ax } = useApp()
  const list = useReminders()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const act = async (a: string, body: object, msg: string) => {
    try { await ax.act(a, body, ['tasks']); await loadReminders(true); toast(msg); return true }
    catch (e: any) { toast.error('Failed: ' + e.message); return false }
  }
  const active = (list || []).filter(r => !r.paused).length
  return (
    <SectionCard id="reminders" icon={Recurring} title="Recurring reminders"
      sub={list?.length ? `${active} active${list.length > active ? ` · ${list.length - active} paused` : ''} · each one adds a task to To do` : 'Repeating to-dos – rent, renewals, birthdays'}
      right={!adding && <Button size="pill" variant="outline" onClick={() => { setAdding(true); setEditing(null) }}><Plus />New</Button>}>
      {adding && <div className="p-4"><ReminderForm init={blank()} submit="Add reminder" onCancel={() => setAdding(false)}
        onSave={async f => { if (await act('reminder_add', f, describe(f.every, f.interval, f.start) + ' – added')) setAdding(false) }} /></div>}
      {!list ? <div className="text-ink-3 flex items-center gap-2 px-4 py-3.5 text-sm"><Loader2 className="size-4 animate-spin" />Loading…</div>
        : !list.length ? (!adding && <Empty>No recurring reminders yet</Empty>)
        : list.map(r => editing === r.id
          ? <div key={r.id} className="p-4"><ReminderForm init={r} submit="Save" onCancel={() => setEditing(null)}
              onSave={async f => { if (await act('reminder_update', { id: r.id, ...f }, 'Reminder saved')) setEditing(null) }} /></div>
          : <ReminderRow key={r.id} r={r} onEdit={() => { setEditing(r.id); setAdding(false) }}
              onPause={() => act('reminder_update', { id: r.id, paused: !r.paused }, r.paused ? 'Reminder resumed' : 'Reminder paused')}
              onDelete={() => act('reminder_delete', { id: r.id }, 'Reminder deleted – tasks it made stay in To do')} />)}
    </SectionCard>
  )
}

function ReminderRow({ r, onEdit, onPause, onDelete }: { r: Reminder; onEdit: () => void; onPause: () => void; onDelete: () => void }) {
  const [armed, setArmed] = useState(false)
  const when = r.lead ? `task ${r.lead} ${r.lead === 1 ? 'day' : 'days'} before` : 'task on the day'
  return (
    <div className={cn('flex min-h-11 items-start gap-3 px-4 py-2.5', r.paused && 'opacity-60')}>
      <Recurring className={cn('mt-[3px] size-4 shrink-0', r.paused ? 'text-ink-3' : 'text-fjord')} />
      <div className="min-w-0 flex-1">
        <div className="text-[15px] leading-snug">{r.text}</div>
        <div className="text-ink-3 mt-0.5 flex flex-wrap gap-x-3 font-mono text-[12px]">
          <span>{r.label}</span>
          <span>{r.paused ? 'paused' : `next ${short(r.next)}`}</span>
          <span>{when}{r.push ? ' + push' : ''}</span>
        </div>
      </div>
      <div className="-my-1.5 -mr-2 flex shrink-0 items-center">
        <button className="text-ink-3 hover:text-ink flex size-8 items-center justify-center rounded-md" title={r.paused ? 'Resume' : 'Pause'} aria-label={r.paused ? 'Resume' : 'Pause'} onClick={onPause}>
          {r.paused ? <Play className="size-4" /> : <Pause className="size-4" />}</button>
        <button className="text-ink-3 hover:text-ink flex size-8 items-center justify-center rounded-md" title="Edit" aria-label="Edit" onClick={onEdit}><Pencil className="size-4" /></button>
        <button className={cn('text-ink-3 hover:text-danger flex h-8 min-w-8 items-center justify-center rounded-md px-1 text-xs', armed && 'text-danger font-medium')} aria-label="Delete"
          onClick={() => { if (armed) onDelete(); else { setArmed(true); setTimeout(() => setArmed(false), 3000) } }}>{armed ? 'Delete?' : <X className="size-4" />}</button>
      </div>
    </div>
  )
}

function ReminderForm({ init, submit, onSave, onCancel }: { init: Form; submit: string; onSave: (f: Form) => Promise<void>; onCancel: () => void }) {
  const [f, setF] = useState<Form>({ text: init.text, every: init.every, interval: init.interval, start: init.start, lead: init.lead, push: init.push })
  const [busy, setBusy] = useState(false)
  const set = (p: Partial<Form>) => setF(x => ({ ...x, ...p }))
  const ok = f.text.trim() && f.start
  return (
    <form className="space-y-3 text-sm" onSubmit={async e => { e.preventDefault(); if (!ok) return; setBusy(true); await onSave({ ...f, text: f.text.trim() }); setBusy(false) }}>
      <label className="block"><span className="mb-1 block font-medium">What</span>
        <Input autoFocus value={f.text} maxLength={500} placeholder="e.g. Pay the rent, renew the domain, water the plants" onChange={e => set({ text: e.target.value })} /></label>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <label className="block"><span className="mb-1 block font-medium">Every</span>
          <NativeSelect value={f.interval} onChange={e => set({ interval: +e.target.value })}>
            {Array.from({ length: 12 }, (_, i) => i + 1).map(n => <option key={n} value={n}>{n}</option>)}</NativeSelect></label>
        <label className="block"><span className="mb-1 block font-medium">&nbsp;</span>
          <NativeSelect value={f.every} onChange={e => set({ every: e.target.value as Every })}>
            {(['day', 'week', 'month', 'year'] as Every[]).map(u => <option key={u} value={u}>{UNIT[u][f.interval === 1 ? 0 : 1]}</option>)}</NativeSelect></label>
        <label className="block"><span className="mb-1 block font-medium">First date</span>
          <Input type="date" value={f.start} onChange={e => set({ start: e.target.value })} required /></label>
        <label className="block"><span className="mb-1 block font-medium">Task appears</span>
          <NativeSelect value={f.lead} onChange={e => set({ lead: +e.target.value })}>
            {[0, 1, 2, 3, 5, 7, 14, 30].map(n => <option key={n} value={n}>{n ? `${n} ${n === 1 ? 'day' : 'days'} before` : 'On the day'}</option>)}</NativeSelect></label>
      </div>
      <label className="flex items-center gap-2"><Checkbox checked={f.push} onCheckedChange={c => set({ push: !!c })} />Push to my phone when the task is added</label>
      {f.start && <div className="text-ink-3 font-mono text-[12px]">{describe(f.every, f.interval, f.start)} · first {short(f.start)}</div>}
      <div className="flex items-center justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={!ok || busy}>{busy ? <Loader2 className="animate-spin" /> : <Recurring />}{submit}</Button>
      </div>
    </form>
  )
}
