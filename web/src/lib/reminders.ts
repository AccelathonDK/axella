/* Recurring reminders (setup/reminders.py, state/reminders.json): repeating to-dos that drop a task into To do
   on schedule. One small shared store so the To do card and Settings show the same list. */
import { useEffect, useState } from 'react'
import { get } from './api'

export type Every = 'day' | 'week' | 'month' | 'year'
export interface Reminder {
  id: string; text: string; every: Every; interval: number; start: string; lead: number; push: boolean; paused: boolean
  next: string; last: string | null; created: string; count: number; label: string
}

let list: Reminder[] | null = null
const subs = new Set<(l: Reminder[]) => void>()
let inflight: Promise<void> | null = null

export function loadReminders(force = false) {
  if (inflight && !force) return inflight
  inflight = get<{ reminders: Reminder[] }>('reminders')
    .then(j => { list = j.reminders || []; subs.forEach(f => f(list!)) })
    .catch(() => { list = list || []; subs.forEach(f => f(list!)) })
    .finally(() => { inflight = null })
  return inflight
}

export function useReminders(): Reminder[] | null {
  const [l, setL] = useState<Reminder[] | null>(list)
  useEffect(() => { subs.add(setL); if (list) setL(list); else loadReminders(); return () => { subs.delete(setL) } }, [])
  return l
}

export const EVERY_LABEL: Record<Every, string> = { day: 'Every day', week: 'Every week', month: 'Every month', year: 'Every year' }
export const short = (d: string) => new Date(d + 'T12:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })

/** "Every month on the 7th" – same wording as reminders.py describe(), for previews before saving. */
export function describe(every: Every, interval: number, start: string) {
  const s = new Date(start + 'T12:00')
  const unit = interval === 1 ? every : `${interval} ${every}s`
  const head = every === 'day' && interval === 1 ? 'Every day' : `Every ${unit}`
  if (every === 'week') return `${head} on ${s.toLocaleDateString('en-GB', { weekday: 'long' })}`
  if (every === 'month') {
    const d = s.getDate(), suf = d % 100 >= 11 && d % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[d % 10] || 'th'
    return `${head} on the ${d}${suf}`
  }
  if (every === 'year') return `${head} on ${s.getDate()} ${s.toLocaleDateString('en-GB', { month: 'long' })}`
  return head
}
