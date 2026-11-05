/* People (feature pack §2a–b, setup/people.py): one page per person – their identities joined via Contacts, the last
   contact per channel, what's open between you, meetings, a timeline and your own note – plus keep in touch.
   Everything is read on the Mac mini and stays there; a private contact shows times and channels only. No scores,
   streaks or counters: keep in touch is one quiet digest line, at most one a day. Owner only. */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { CalendarCheck, Clock, Mail, Pencil, Phone, Sparkles, UserCircle } from '@/components/ax-icons'
import { ContactForm, type Person as BookPerson } from '@/components/Contacts'
import { openCompose } from '@/components/Compose'
import { openNewPrep } from '@/components/Meetings'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { NativeSelect } from '@/components/ui/input'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { cn } from '@/lib/utils'

interface Line { id: string; channel: string; at: string; title?: string }
interface Entry { id: string; digest?: string; channel: string; at: string; dir: 'in' | 'out' | 'call'; title?: string; snippet?: string; minutes?: number }
interface Meeting { id: string; title: string; start?: string | null; status?: string }
export interface PersonPage {
  id: string; name: string; first?: string; company?: string; emails: string[]; phones: string[]; private: boolean; vip: boolean
  in_contacts: boolean; birthday?: string; world: 'work' | 'private' | null; last_contact: Record<string, string>
  open: { to_answer: Line[]; waiting: Line[]; reply_owed: { days: number; channel: string }[]
    promises: { id: string | null; text: string | null; due?: string | null; status: string; task_id?: string | null }[] }
  meetings: { upcoming: Meeting[]; past: Meeting[] }
  timeline: Entry[]; note: { text: string; updated: string } | null; keep: { every: number; since: string } | null
}

const CH: Record<string, string> = { mail: 'Mail', imessage: 'iMessage', sms: 'SMS', whatsapp: 'WhatsApp', signal: 'Signal', call: 'Call', linkedin: 'LinkedIn', slack: 'Slack' }
const RHYTHMS: [number, string][] = [[14, 'Every 2 weeks'], [30, 'Every month'], [91, 'Every quarter']]
const when = (s?: string | null) => {
  if (!s) return ''
  const d = new Date(s.length <= 10 ? s + 'T12:00' : s)
  if (isNaN(+d)) return s.slice(0, 10)
  const days = Math.floor((Date.now() - d.getTime()) / 864e5)
  const same = new Date().getFullYear() === d.getFullYear()
  const date = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', ...(same ? {} : { year: 'numeric' }) })
  return days <= 0 && days > -1 ? 'today' : days === 1 ? 'yesterday' : date
}
const area = 'border-line-strong bg-card focus-visible:border-ring focus-visible:ring-ring/30 w-full rounded-md border px-2.5 py-1.5 text-[16px] outline-none focus-visible:ring-2 sm:text-sm'

/** "Draft a note": the composer, asked for a short personal opener – nothing is written until you tap, nothing sent
    without Send. A private contact gets no AI (the composer opens on "Write it myself"). */
export function draftNote(p: { first?: string; name: string; emails: string[]; private?: boolean }) {
  const to = p.emails[0]
  if (!to) { toast('No e-mail address for ' + p.name + ' – message them from Contacts'); return }
  openCompose(p.private ? { to, mode: 'self' } : { to, mode: 'ai', tone: 'warm and personal', topic: `A short, personal note to ${p.first || p.name.split(' ')[0]} – just checking in, nothing to ask` })
}

export function PersonView({ id }: { id: string }) {
  const { ax, go } = useApp()
  const [p, setP] = useState<PersonPage | null>(null)
  const [err, setErr] = useState('')
  const [edit, setEdit] = useState<BookPerson | null>(null)
  const load = () => get<PersonPage>('person?id=' + encodeURIComponent(id)).then(setP).catch(e => setErr(e.message))
  useEffect(() => { load() }, [id])  // eslint-disable-line react-hooks/exhaustive-deps
  if (err) return <div className="space-y-2"><h1 className="text-xl font-semibold">Person</h1><p className="text-ink-3 text-sm">{err}</p>
    <Button size="pill" variant="outline" onClick={() => go({ kind: 'contacts' })}>Contacts</Button></div>
  if (!p) return <div className="text-ink-3 text-sm">Loading…</div>
  const last = Object.entries(p.last_contact).sort((a, b) => b[1].localeCompare(a[1]))
  const o = p.open
  const nOpen = o.to_answer.length + o.waiting.length + o.reply_owed.length + o.promises.length
  return <div className="space-y-4" data-person-view="">
    <div className="flex items-start gap-3">
      <span className="bg-fjord-soft text-fjord inline-flex size-12 shrink-0 items-center justify-center rounded-full text-lg font-semibold" aria-hidden>
        {p.name.split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase() || <UserCircle className="size-5" />}</span>
      <div className="min-w-0 flex-1">
        <h1 className="text-xl font-semibold tracking-tight">{p.name}</h1>
        <p className="text-muted-foreground text-sm">{[p.company, p.world === 'work' ? 'Work' : p.world === 'private' ? 'Private' : null, p.private ? 'private contact – times and channels only' : null].filter(Boolean).join(' · ')}</p>
        <p className="text-ink-3 mt-1 text-[13px]" data-last-contact="">{last.length ? 'Last in touch: ' + last.map(([c, t]) => `${CH[c] || c} ${when(t)}`).join(' · ') : 'Nothing in Axella yet.'}</p>
      </div>
    </div>

    <div className="flex flex-wrap gap-2">
      {p.emails[0] && <Button size="pill" onClick={() => p.private ? (location.href = 'mailto:' + p.emails[0]) : openCompose({ to: p.emails[0] })}><Mail />New mail</Button>}
      {p.emails[0] && <Button size="pill" variant="outline" onClick={() => draftNote(p)} data-draft-note=""><Sparkles />Draft a note</Button>}
      {p.emails[0] && <Button size="pill" variant="outline" onClick={() => openNewPrep({ title: 'Meeting with ' + p.name, attendees: [{ name: p.name, email: p.emails[0] }] })}><CalendarCheck />Prepare meeting</Button>}
      {p.phones[0] && <Button size="pill" variant="outline" asChild><a href={'tel:' + p.phones[0]}><Phone />Call</a></Button>}
      {p.in_contacts && <Button size="pill" variant="ghost" onClick={() => get<{ people: BookPerson[] }>('contacts').then(b => {
        const c = b.people.find(x => x.id === p.id); if (c) setEdit(c); else toast('Not found in Contacts')
      }).catch(e => toast.error(e.message))}><Pencil />Edit contact</Button>}
    </div>

    <KeepInTouch p={p} onChange={k => setP({ ...p, keep: k })} />

    <Card className="space-y-3 p-4" data-person-open="">
      <div className="ax-label">Open between you</div>
      {!nOpen && <p className="text-ink-3 text-sm">Nothing open.</p>}
      <Lines title="To answer" lines={o.to_answer} priv={p.private} onOpen={() => go({ kind: 'briefing' })} />
      {o.reply_owed.map((r, i) => <p key={i} className="text-sm">You owe a reply ({CH[r.channel] || r.channel}, {r.days} days)</p>)}
      <Lines title="Waiting on them" lines={o.waiting} priv={p.private} onOpen={() => go({ kind: 'todo', tab: 'waiting' })} />
      {o.promises.length > 0 && <div><div className="text-ink-3 mb-1 text-[12.5px]">Your promises</div>
        <ul className="space-y-1 text-sm">{o.promises.map((x, i) => <li key={i}>
          <button type="button" className="text-left hover:underline" onClick={() => go({ kind: 'todo', tab: 'tasks' })}>
            {x.text || 'A promise (protected workplace – the words stay in Mail)'}{x.due && <span className="text-ink-3"> · due {when(x.due)}</span>}{x.status === 'suggested' && <span className="text-ink-3"> · suggested</span>}</button></li>)}</ul></div>}
    </Card>

    {(p.meetings.upcoming.length > 0 || p.meetings.past.length > 0) && <Card className="space-y-2 p-4" data-person-meetings="">
      <div className="ax-label">Meetings</div>
      {[...p.meetings.upcoming.map(m => ({ ...m, up: true })), ...p.meetings.past.map(m => ({ ...m, up: false }))].map(m =>
        <button key={m.id} type="button" onClick={() => go({ kind: 'meeting', id: m.id })} className="hover:bg-bg-2 -mx-2 flex w-full items-baseline gap-2 rounded px-2 py-1 text-left text-sm">
          <span className={cn('font-mono text-[12px] tabular-nums', m.up ? 'text-fjord' : 'text-ink-3')}>{when(m.start) || 'no date'}</span><span className="min-w-0 flex-1 truncate">{m.title}</span></button>)}
    </Card>}

    <Notes p={p} />

    <Card className="space-y-2 p-4" data-person-timeline="">
      <div className="ax-label">Timeline</div>
      {!p.timeline.length && <p className="text-ink-3 text-sm">Nothing yet.</p>}
      <ul className="divide-y">{p.timeline.map((e, i) => <li key={i} className="flex gap-3 py-2 text-sm">
        <span className="text-ink-3 w-20 shrink-0 font-mono text-[12px] tabular-nums">{when(e.at)}</span>
        <span className="min-w-0 flex-1">
          <span className="text-ink-3 text-[12px]">{CH[e.channel] || e.channel}{e.dir === 'out' ? ' · you replied' : e.dir === 'call' ? ` · call${e.minutes ? ', ' + e.minutes + ' min' : ''}` : ''}</span>
          {e.dir === 'in' && (p.private ? <span className="text-ink-3 block">A message</span> : <>
            {e.title && <span className="block truncate">{e.title}</span>}
            {e.snippet && <span className="text-ink-3 line-clamp-2 block text-[13px]">{e.snippet}</span>}</>)}
        </span>
      </li>)}</ul>
      <p className="text-ink-3 text-[11.5px]">From the digests, your replies from Axella and the call agent – kept on the Mac mini. {p.private ? 'A private contact: no titles or snippets.' : ''}</p>
    </Card>
    {edit && <ContactForm init={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); load() }} />}
    {!ax.apiOk && <p className="text-ink-3 text-[12px]">Offline – changes wait until the Mac mini is reachable.</p>}
  </div>
}

function Lines({ title, lines, priv, onOpen }: { title: string; lines: Line[]; priv: boolean; onOpen: () => void }) {
  if (!lines.length) return null
  return <div><div className="text-ink-3 mb-1 text-[12.5px]">{title}</div>
    <ul className="space-y-1 text-sm">{lines.map(l => <li key={l.id}>
      <button type="button" className="text-left hover:underline" onClick={onOpen}>{priv || !l.title ? `A message (${CH[l.channel] || l.channel})` : l.title}</button>
      <span className="text-ink-3"> · {when(l.at)}</span></li>)}</ul></div>
}

function KeepInTouch({ p, onChange }: { p: PersonPage; onChange: (k: PersonPage['keep']) => void }) {
  const { ax } = useApp()
  const [busy, setBusy] = useState(false)
  async function set(v: string) {
    setBusy(true)
    const every = v ? +v : null
    try {
      await ax.act('keep_set', { id: p.id, every }, [])
      onChange(every ? { every, since: p.keep?.since || new Date().toISOString().slice(0, 10) } : null)
      toast(every ? `Keep in touch with ${p.first || p.name}: ${RHYTHMS.find(r => r[0] === every)![1].toLowerCase()}` : 'Not on keep in touch any more')
    } catch (e: any) { toast.error(e.message) } finally { setBusy(false) }
  }
  return <Card className="flex flex-wrap items-center gap-3 p-4" data-keep-in-touch="">
    <Clock className="text-ink-3 size-4" />
    <div className="min-w-0 flex-1">
      <div className="text-sm font-medium">Keep in touch</div>
      <div className="text-ink-3 text-[12.5px]">{p.private
        ? 'A private contact: Axella keeps the rhythm here, but never names them in a digest.'
        : 'When the time passes with no contact in any channel, one quiet line in a private digest – at most one a day.'}</div>
    </div>
    <NativeSelect aria-label="Keep in touch" value={p.keep ? String(p.keep.every) : ''} disabled={busy || !ax.apiOk} onChange={e => set(e.target.value)} className="w-40">
      <option value="">Off</option>{RHYTHMS.map(([d, l]) => <option key={d} value={d}>{l}</option>)}</NativeSelect>
  </Card>
}

function Notes({ p }: { p: PersonPage }) {
  const { ax } = useApp()
  const [text, setText] = useState(p.note?.text || '')
  const [saved, setSaved] = useState(p.note?.text || '')
  const [busy, setBusy] = useState(false)
  async function save() {
    setBusy(true)
    try { await ax.act('person_note', { id: p.id, text }, []); setSaved(text); toast('Note saved') }
    catch (e: any) { toast.error('Not saved: ' + e.message) } finally { setBusy(false) }
  }
  return <Card className="space-y-2 p-4" data-person-notes="">
    <div className="ax-label">Your notes</div>
    <textarea className={area} rows={3} maxLength={2000} value={text} onChange={e => setText(e.target.value)} placeholder="Only for you – kept on the Mac mini, never sent anywhere." aria-label="Your notes" />
    {text !== saved && <div className="flex justify-end"><Button size="pill" disabled={busy || !ax.apiOk} onClick={save}>Save note</Button></div>}
  </Card>
}

/** Contacts page: who is on keep in touch, the ones due first – a quiet list, no counters. */
export function KeepInTouchList() {
  const { go } = useApp()
  const [d, setD] = useState<{ people: { id: string; name: string; every: number; due: boolean; days: number | null }[] } | null>(null)
  useEffect(() => { get<typeof d>('keep_in_touch').then(setD).catch(() => {}) }, [])
  if (!d?.people.length) return null
  return <section className="bg-card overflow-hidden rounded-lg border" aria-label="Keep in touch" data-keep-list="">
    <div className="ax-label border-b px-4 py-2">Keep in touch</div>
    <div className="divide-y">{d.people.map(x => <button key={x.id} type="button" onClick={() => go({ kind: 'person', id: x.id })}
      className="hover:bg-bg-2 flex min-h-11 w-full items-center gap-3 px-4 py-2 text-left">
      <span className="min-w-0 flex-1 truncate font-medium">{x.name}</span>
      <span className="text-ink-3 text-[12.5px]">{x.due && x.days != null ? `${x.days} days since you spoke` : (RHYTHMS.find(r => r[0] === x.every)?.[1] || '')}</span>
    </button>)}</div>
  </section>
}
