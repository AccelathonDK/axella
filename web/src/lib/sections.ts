import { axi, type LucideIcon } from '@/components/ax-icons'
import type { SectionKey } from './types'

export interface SectionDef { key: SectionKey; title: string; short: string; sub: string; icon: LucideIcon; col: 'main' | 'side'; color: string; always?: boolean }
export const SECTIONS: SectionDef[] = [
  { key: 'p0', title: 'Urgent – now', short: 'Urgent', sub: 'Act within the hour', icon: axi('urgent'), col: 'main', color: 'var(--ax-p0)', always: true },
  { key: 'p1', title: 'Before noon', short: 'Noon', sub: 'Answer this morning', icon: axi('morning'), col: 'main', color: 'var(--ax-p1)', always: true },
  { key: 'p2', title: 'By end of day', short: 'Today', sub: 'Answer or follow up', icon: axi('evening'), col: 'main', color: 'var(--ax-p2)', always: true },
  { key: 'open', title: 'Still open', short: 'Open', sub: 'Carried over', icon: axi('still-open'), col: 'main', color: 'var(--ax-open)' },
  { key: 'p3', title: 'FYI', short: 'FYI', sub: 'No answer needed', icon: axi('info'), col: 'main', color: 'var(--ax-p3)' },
  { key: 'cal', title: 'Calendar', short: 'Calendar', sub: 'Conflicts and notes', icon: axi('calendar'), col: 'side', color: 'var(--ax-cal)' },
  { key: 'wait', title: 'Waiting for replies', short: 'Waiting', sub: 'You asked, no answer', icon: axi('waiting'), col: 'side', color: 'var(--ax-wait)' },
  { key: 'file', title: 'Filing suggestions', short: 'Filing', sub: 'Approve to move', icon: axi('filing'), col: 'side', color: 'var(--ax-p3)' },
]
export const SEC = Object.fromEntries(SECTIONS.map(s => [s.key, s])) as Record<SectionKey, SectionDef>
export const EXTRA = {
  tasks: { title: 'To do', short: 'To do', sub: 'Your tasks, logged in Axella', icon: axi('todo'), color: 'var(--ax-tasks)' },
  calls: { title: 'Calls', short: 'Calls', sub: 'Axella · taking messages', icon: axi('phone'), color: 'var(--ax-calls)' },
}
export const ITEM_ICON: Record<SectionKey, LucideIcon> = { p0: axi('urgent'), p1: axi('mail'), p2: axi('mail'), p3: axi('info'), cal: axi('calendar'), wait: axi('waiting'), file: axi('filing'), open: axi('still-open') }
/* streams: generic icons only – other companies' logos are never redrawn */
export const CH_ICON: Record<string, LucideIcon> = { linkedin: axi('person'), mail: axi('mail'), whatsapp: axi('chat'), signal: axi('chat'), imessage: axi('message'), sms: axi('message'), slack: axi('chat'), calendar: axi('calendar'), call: axi('phone') }
