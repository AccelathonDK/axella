/* Meeting prep – the dashboard side of setup/meetings.py (owner only). */
import { useEffect, useState } from 'react'
import { get, post } from '@/lib/api'
import { prepForEvent } from './meetingRows'

export interface Point { id?: string; text: string; done: boolean; carried?: boolean; outcome?: { id: string; kind: string; text: string } }
export interface Material {
  id: string; kind: 'file' | 'url' | 'mail' | 'transcript' | 'project'; name: string; ref?: string; ref_kind?: string; project?: string; speakers?: Record<string, string>; ext?: string; audio?: boolean; status?: 'ready' | 'transcribing' | 'waiting' | 'failed'; error?: string | null; type?: string; size?: number; url?: string; account?: string
  message_id?: string; from?: string; date?: string; chars?: number; summary?: string; protected?: boolean; added?: string
}
export interface Attendee { name: string; email: string }
export interface PrepEvent { id: string; start: string | null; calendar?: string; recurring?: boolean }
export interface Prep {
  id: string; title: string; start: string | null; end: string | null; location: string; join: string
  ctx: 'work' | 'private' | null; project: string | null; status: 'draft' | 'ready'; event: PrepEvent | null; series: string | null
  attendees: Attendee[]; goals: string; background: string; notes: string; points: Point[]; materials: Material[]
  outcomes?: Outcomes | null
  recordings?: Record<string, { id: string; bytes: number; started: string; updated?: string; type: string; next: number }>
  created: string; updated: string
}
export interface Outcome { id?: string; kind: 'decision' | 'task' | 'waiting' | 'fact'; text: string; due?: string | null; who?: string | null; state: 'open' | 'added' | 'kept' | 'dismissed' }
export interface Outcomes { summary: string; items: Outcome[]; at?: string | null }
export async function uploadTranscript(id: string, file: File | Blob, name: string) {
  const r = await fetch(`api/meeting_transcript_upload?id=${encodeURIComponent(id)}&name=${encodeURIComponent(name)}`, {
    method: 'POST', headers: { 'X-Axella': '1', 'Content-Type': (file as File).type || 'application/octet-stream' }, body: file,
  })
  const j = await r.json().catch(() => ({ ok: false, error: 'HTTP ' + r.status }))
  if (!j.ok) throw new Error(j.error)
  return j.result as { id: string; status: string; error?: string | null; chars: number }
}
export type PrepSummary = Pick<Prep, 'id' | 'title' | 'start' | 'end' | 'location' | 'ctx' | 'project' | 'status' | 'event' | 'series' | 'attendees' | 'created' | 'updated'>
  & { points: number; done: number; materials: number; has_goals: boolean }
export interface Person { name: string; email: string; private: boolean; protected: boolean; last: string | null; subjects: { subject: string; date: string; from_me: boolean }[] }
export interface MeetingCtx {
  people: Person[]; mails: { subject: string; from: string; date: string; protected: boolean; who: string }[]
  tasks: { id: string; text: string; due?: string }[]; waiting: { headline: string; who?: string }[]
  earlier: { id: string; title: string; start: string; open: string[]; notes: string }[]
}
export interface Card { section: 'goals' | 'points' | 'background' | 'notes'; text: string }
/** An event from GET calendar, with the attendees meeting prep needs */
export interface CalEv {
  id: string; title: string; start: string; end: string; all_day: boolean; location?: string | null; notes?: string | null
  url?: string | null; calendar: string; calendar_label: string; ctx: 'work' | 'private' | null; recurring: boolean
  attendees: number; people?: Attendee[]
  /** why the Mac mini counts it as a meeting: a join link, an invitation, other people – null: not a meeting */
  meeting?: 'join' | 'invite' | 'people' | null; join?: string | null
}

/* ---------- the list of preps, shared by the Meetings page, the calendar sheet and the Today card ---------- */
let cache: PrepSummary[] | null = null
let denied = false
let loading: Promise<PrepSummary[]> | null = null
const subs = new Set<() => void>()
let retry: ReturnType<typeof setTimeout> | null = null
let at = 0                                               // when the list was last read
export function reloadPreps() {
  if (retry) { clearTimeout(retry); retry = null }
  loading = get<{ preps: PrepSummary[] }>('meetings').then(j => { cache = j.preps || []; denied = false; at = Date.now(); return cache })
    .catch(e => {
      if (/owner/i.test(e.message)) { denied = true; cache = cache || []; return cache }
      // the Mac mini didn't answer (a restart): never show "No prep" for preps that exist – keep what we had and try again
      retry = setTimeout(() => { if (subs.size) reloadPreps() }, 5000)
      return cache || []
    })
    .finally(() => { loading = null; subs.forEach(f => f()) })
  return loading
}
if (typeof document !== 'undefined')                     // back to the app (another device may have added a prep)
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && subs.size && !loading) reloadPreps() })
/** null while loading; owner=false when the Mac mini says preps are the owner's own */
export function usePreps() {
  const [, tick] = useState(0)
  useEffect(() => {
    const f = () => tick(x => x + 1)
    subs.add(f)
    if ((!cache || Date.now() - at > 30e3) && !loading) reloadPreps()   // a page opened later reads it fresh
    return () => { subs.delete(f) }
  }, [])
  return { preps: cache, owner: !denied }
}

export { sameMinute, prepForEvent } from './meetingRows'

export const JOIN_RE = /https:\/\/(?:teams\.microsoft\.com\/(?:l\/meetup-join|meet)\/|[\w-]+\.zoom\.us\/j\/|meet\.google\.com\/|[\w-]+\.webex\.com\/(?:meet|join)\/)[^\s<>"]+/
export function joinLink(e: { url?: string | null; location?: string | null; notes?: string | null }) {
  const m = [e.url, e.location, e.notes].filter(Boolean).join(' ').match(JOIN_RE)
  return m ? m[0] : null
}

export async function startFromEvent(e: CalEv): Promise<string> {
  const have = prepForEvent(cache, e)
  if (have) return have.id
  const r = await post<{ result: { id: string; carried: number } }>('meeting_add', {
    title: e.title.slice(0, 200), start: e.start, end: e.end, location: e.location || '', join: joinLink(e) || '',
    ctx: e.ctx, event: { id: e.id, start: e.start, calendar: e.calendar, recurring: e.recurring },
    attendees: e.people || [], background: '', notes: '',
  }).catch(async x => {
    if (!/already has a prep/i.test(x.message)) throw x
    const found = prepForEvent(await reloadPreps(), e)  // made earlier (or on another device): open that one
    if (!found) throw x
    return { result: { id: found.id, carried: 0 } }
  })
  await reloadPreps()
  return r.result.id
}
export async function startManual(title: string, start?: string | null, extra: Record<string, unknown> = {}): Promise<string> {
  const r = await post<{ result: { id: string } }>('meeting_add', { title, start: start || null, ...extra })
  await reloadPreps()
  return r.result.id
}
export async function uploadMaterial(id: string, file: File) {
  const r = await fetch(`api/meeting_upload?id=${encodeURIComponent(id)}&name=${encodeURIComponent(file.name)}`, {
    method: 'POST', headers: { 'X-Axella': '1', 'Content-Type': file.type || 'application/octet-stream' }, body: file,
  })
  const j = await r.json().catch(() => ({ ok: false, error: 'HTTP ' + r.status }))
  if (!j.ok) throw new Error(j.error)
  return j.result as { id: string; chars: number }
}
export const fileUrl = (prep: { id: string }, m: { id: string }) => `api/meeting_file?id=${encodeURIComponent(prep.id)}&a=${encodeURIComponent(m.id)}`

export const fmtWhen = (s?: string | null, withYear = false) => !s ? 'No date' : new Date(s).toLocaleString('en-GB', {
  weekday: 'short', day: 'numeric', month: 'short', ...(withYear ? { year: 'numeric' } : {}), hour: '2-digit', minute: '2-digit' })

/** The prep as a plain document (Download, Copy) – the same order as the Document view. */
export function prepMarkdown(p: Prep, people?: Person[]) {
  const out = [`# ${p.title}`, '', [fmtWhen(p.start, true), p.location].filter(Boolean).join(' · ')]
  if (p.join) out.push('Join: ' + p.join)
  if (p.attendees.length) out.push('With: ' + p.attendees.map(a => a.name).join(', '))
  const sec = (h: string, body: string) => { if (body.trim()) out.push('', '## ' + h, '', body.trim()) }
  sec('Goals', p.goals)
  if (p.points.length) out.push('', '## To discuss', '', ...p.points.map(x => `- [${x.done ? 'x' : ' '}] ${x.text}`))
  sec('Background', p.background)
  sec('Notes', p.notes)
  const o = p.outcomes
  if (o && (o.summary.trim() || o.items.some(i => i.state !== 'dismissed'))) {
    out.push('', '## Outcomes')
    if (o.summary.trim()) out.push('', o.summary.trim())
    for (const [k, h] of [['decision', 'Decisions'], ['task', 'Tasks'], ['waiting', 'Waiting on others'], ['fact', 'Worth keeping']] as const) {
      const l = o.items.filter(i => i.kind === k && i.state !== 'dismissed')
      if (l.length) out.push('', '### ' + h, '', ...l.map(i => `- ${i.who ? i.who + ': ' : ''}${i.text}${i.due ? ' (by ' + i.due + ')' : ''}`))
    }
  }
  const mats = p.materials.filter(m => m.kind !== 'transcript')
  if (mats.length) out.push('', '## Materials', '', ...mats.map(m =>
    `- ${m.name}${m.kind === 'url' && m.url ? ' – ' + m.url : ''}${m.kind === 'mail' ? ` (mail${m.from ? ' from ' + m.from : ''}${m.date ? ', ' + m.date : ''})` : ''}${m.summary ? '\n  ' + m.summary.replace(/\n/g, '\n  ') : ''}`))
  if (people?.length) out.push('', '## People', '', ...people.map(x => `- ${x.name}${x.email ? ' <' + x.email + '>' : ''}`))
  return out.join('\n') + '\n'
}
export function agendaText(p: Prep) {
  const out = [p.title, p.start ? fmtWhen(p.start, true) : ''].filter(Boolean)
  if (p.goals.trim()) out.push('', 'Goals', p.goals.trim())
  if (p.points.length) out.push('', 'To discuss', ...p.points.map((x, i) => `${i + 1}. ${x.text}`))
  return out.join('\n')
}
