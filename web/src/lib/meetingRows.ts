/* Which calendar events are meetings, as rows for the Meetings page and the Today card (fix round 7, P2-2). Pure –
   tested by web/tests/meeting-rows.test.mjs. */
import type { CalEv, PrepSummary } from './meetings'

export const sameMinute = (a?: string | null, b?: string | null) => !!a && !!b && Math.abs(new Date(a).getTime() - new Date(b).getTime()) < 60e3
/** the prep linked to a calendar event (a repeating event: the prep of this occurrence) */
export function prepForEvent(preps: PrepSummary[] | null, e: { id: string; start: string; recurring: boolean }) {
  return (preps || []).find(p => p.event?.id === e.id && (!e.recurring || sameMinute(p.event.start, e.start))) || null
}

export type Row = { key: string; start: string | null; title: string; sub: string; ctx: 'work' | 'private' | null; others: number; prep: PrepSummary | null; ev: CalEv | null; repeats?: number }
/** a meeting: the Mac mini's verdict (join link, invitation, other people – private family calendars need more); an
    older service without it: other attendees, not in a private calendar */
export const isMeeting = (e: CalEv) => e.meeting !== undefined ? !!e.meeting : e.attendees > 0 && e.ctx !== 'private'

/** the coming events worth a row: meetings (all: every event) and every prep with a time; a repeating event is one row
    – its next occurrence, with how often it comes – unless an occurrence has its own prep */
export function rowsOf(events: CalEv[] | null, preps: PrepSummary[] | null, all: boolean, now = Date.now()) {
  const rows: Row[] = []
  const used = new Set<string>()
  const series = new Map<string, Row>()
  const sorted = [...(events || [])].sort((a, b) => String(a.start).localeCompare(String(b.start)))
  for (const e of sorted) {
    if (e.all_day || new Date(e.end || e.start).getTime() < now) continue
    const p = prepForEvent(preps, e)
    if (!p && !all && !isMeeting(e)) continue
    if (p) used.add(p.id)
    const k = e.recurring && !p ? 'r:' + e.calendar + '|' + e.id + '|' + e.title : ''
    const seen = k ? series.get(k) : undefined
    if (seen) { seen.repeats = (seen.repeats || 1) + 1; continue }
    const row: Row = { key: e.id + e.start, start: e.start, title: e.title, sub: e.calendar_label, ctx: e.ctx, others: e.attendees, prep: p, ev: e }
    if (k) series.set(k, row)
    rows.push(row)
  }
  for (const p of preps || []) {
    if (used.has(p.id) || !p.start || new Date(p.end || p.start).getTime() < now) continue
    rows.push({ key: p.id, start: p.start, title: p.title, sub: p.event ? 'Not in the calendar at this time' : 'Not in the calendar', ctx: p.ctx, others: p.attendees.length, prep: p, ev: null })
  }
  return rows.sort((a, b) => String(a.start).localeCompare(String(b.start)))
}

/** Today: only real meetings within 48 hours (and preps you made for that time) */
export const todayRows = (events: CalEv[] | null, preps: PrepSummary[] | null, now = Date.now()) =>
  rowsOf(events, preps, false, now).filter(r => r.start && new Date(r.start).getTime() - now < 48 * 36e5)
