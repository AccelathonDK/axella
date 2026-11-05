/* Projects → Scan mail (setup/project_scan.py): the mails that make up a project, found on the Mac mini by rules from
   the project's Matches (tag, keywords, senders, added threads – subject and sender only, never Claude), sorted by you
   in To sort, kept on the Mails card and opened in Axella's own reader. Read with Claude reads only mails you pick and
   suggests cards you confirm one by one. Linking a trip shows its card here. */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { CalendarPlus, Check, ExternalLink, FileText, Inbox, Loader2, Plus, RotateCw, Sparkles, StickyNote, Trip as TripIcon, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { SectionCard, Empty } from '@/components/Section'
import { CalendarForm } from '@/components/ItemRow'
import { openMailInAxella } from '@/components/MailReader'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { cals } from '@/lib/profile'
import type { Item, Project } from '@/lib/types'
import { cn } from '@/lib/utils'

interface PMail { account?: string; message_id: string; subject?: string; from?: string; address?: string; date?: string; why?: string[]; thread?: string }
interface Card_ { id: string; kind: 'task' | 'note' | 'date'; text: string; due?: string | null; date?: string; time?: string | null; message_id: string }
interface PView { since?: string | null; since_default: string; last_scan?: string | null; candidates: PMail[]; threads: { thread: string; mails: PMail[] }[]; added: number
  suggest: { match: string; mails: number }[]; trips: string[]; suggestions: Card_[]; reading?: string | null
  status: { running?: boolean; error?: string | null; found?: number | null }; trip_offers: { id: string; title: string }[]
  linked_trips: { id: string; title: string; start?: string; end?: string; bookings: number; next?: { title: string; start: string } | null }[] }

const day = (s?: string | null) => s ? new Date(s).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: new Date(s).getFullYear() === new Date().getFullYear() ? undefined : 'numeric' }) : ''

function useProjectMail(id: string) {
  const [v, setV] = useState<PView | null>(null)
  const [err, setErr] = useState('')
  const load = () => get<PView & { ok?: boolean; error?: string }>('project_mail?id=' + encodeURIComponent(id))
    .then(r => { if ((r as any).ok === false) setErr((r as any).error || 'not available'); else { setV(r); setErr('') } }).catch(e => setErr(e.message))
  useEffect(() => { load() }, [id])                                // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {                                                // a scan or a reading in progress: look again shortly
    if (!v?.status?.running && !v?.reading) return
    const t = setTimeout(load, 4000); return () => clearTimeout(t)
  }, [v])                                                          // eslint-disable-line react-hooks/exhaustive-deps
  return { v, err, load }
}

export function ProjectMail({ p }: { p: Project }) {
  const { ax } = useApp()
  const { v, err, load } = useProjectMail(p.id)
  const [busy, setBusy] = useState<string | null>(null)
  const [since, setSince] = useState('')
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [adding, setAdding] = useState(false)
  const [moving, setMoving] = useState<PMail | null>(null)
  const act = async (key: string, action: string, body: Record<string, unknown>, msg?: string, undo?: { action: string; body: Record<string, unknown> }) => {
    setBusy(key)
    try {
      await ax.act(action, { id: p.id, ...body }, ['projects'])
      if (msg) toast(msg, undo ? { action: { label: 'Undo', onClick: () => ax.act(undo.action, { id: p.id, ...undo.body }, ['projects']).then(load) } } : undefined)
      await load(); return true
    } catch (e: any) { toast.error('Failed: ' + e.message); return false } finally { setBusy(null) }
  }
  if (err) return null                                             // an older Mac mini, or not the owner: nothing to show
  if (!v) return null
  const others = ax.projects.filter(x => x.id !== p.id && x.status === 'active')
  const scanning = !!v.status?.running
  return <>
    <SectionCard id="pmail" color="var(--ax-p2)" icon={Inbox} title="Mails" count={v.added}
      sub={v.last_scan ? `Scanned ${day(v.last_scan)} · active projects are re-scanned every night` : 'All mail you add to this project – kept across digests'}>
      <div className="flex flex-wrap items-center gap-2 px-4 py-2.5" data-project-scan="">
        <span className="text-ink-3 text-[12.5px]">Scan since</span>
        <Input type="date" className="h-8 w-40 text-xs" value={since || v.since || v.since_default} onChange={e => setSince(e.target.value)} aria-label="Scan since" />
        <Button size="pill" variant="outline" disabled={scanning || busy === 'scan'} onClick={() => act('scan', 'project_mail_scan', since ? { since } : {}, 'Scanning your mail for ' + p.name + '…')}>
          {scanning ? <Loader2 className="animate-spin" /> : <RotateCw />}{scanning ? 'Scanning…' : 'Scan mail'}</Button>
        <Button size="pill" variant="ghost" onClick={() => setAdding(true)}><Plus />Add a mail…</Button>
        {v.status?.error && <span className="text-dawn text-[12.5px]">{v.status.error}</span>}
        {v.status?.found != null && !scanning && <span className="text-ink-3 text-[12.5px]">{v.status.found} new to sort</span>}
      </div>
      {v.candidates.length > 0 && <div className="border-t" data-to-sort="">
        <div className="ax-label px-4 pt-2.5 pb-1">To sort ({v.candidates.length})</div>
        <div className="divide-y">{v.candidates.slice(0, 50).map(c => <div key={c.message_id} className="flex flex-wrap items-center gap-x-2 gap-y-1 px-4 py-2 text-sm" data-candidate="">
          <button className="min-w-0 flex-1 basis-[14rem] text-left" onClick={() => openMailInAxella({ account: c.account, message_id: c.message_id, subject: c.subject, from: c.from })}>
            <span className="block truncate">{c.subject || '(no subject)'}</span>
            <span className="text-ink-3 block truncate text-[12.5px]">{[c.from, day(c.date), (c.why || []).join(' · ')].filter(Boolean).join(' · ')}</span></button>
          <Button size="pill" variant="outline" disabled={!!busy} onClick={() => act('a' + c.message_id, 'project_mail_add', { message_id: c.message_id }, 'Added to ' + p.name)}><Check />Add</Button>
          <Button size="pill" variant="ghost" disabled={!!busy} onClick={() => act('n' + c.message_id, 'project_mail_not', { message_id: c.message_id }, 'Not offered again', { action: 'project_mail_undo_not', body: { message_id: c.message_id } })}><X />Not this project</Button>
          {others.length > 0 && <Button size="pill" variant="ghost" disabled={!!busy} onClick={() => setMoving(c)}>Another project…</Button>}
        </div>)}</div>
      </div>}
      {v.suggest.length > 0 && <div className="bg-fjord-soft/40 border-t px-4 py-2.5 text-sm" data-match-suggest="">
        {v.suggest.map(s => <div key={s.match} className="flex flex-wrap items-center gap-2">
          <span className="min-w-0 flex-1">Add <b className="font-medium">{s.match}</b> to this project's matches? <span className="text-ink-3">({s.mails} added mails)</span></span>
          <Button size="pill" variant="outline" disabled={!!busy} onClick={() => act('m', 'project_match_add', { match: s.match }, 'Added to matches')}>Add</Button>
          <Button size="pill" variant="ghost" disabled={!!busy} onClick={() => act('md', 'project_match_dismiss', { match: s.match })}>No</Button>
        </div>)}
      </div>}
      {v.threads.length ? <div className="divide-y border-t" data-project-mails="">
        {v.threads.map(t => <div key={t.thread} className="px-4 py-2">
          {t.mails.map(m => <MailRow key={m.message_id} m={m} picked={picked.has(m.message_id)} busy={!!busy}
            onPick={on => setPicked(s => { const n = new Set(s); if (on) n.add(m.message_id); else n.delete(m.message_id); return n })}
            onRemove={() => act('r' + m.message_id, 'project_mail_remove', { message_id: m.message_id }, 'Removed from ' + p.name, { action: 'project_mail_undo_remove', body: { message_id: m.message_id } })}
            onAttach={n => act('f' + m.message_id, 'project_mail_attach', { message_id: m.message_id, n }, 'Added to Documents')} />)}
        </div>)}
      </div> : <Empty>No mails added yet – Scan mail, or Add a mail…</Empty>}
      {v.threads.length > 0 && <div className="flex flex-wrap items-center gap-2 border-t px-4 py-2.5">
        <Button size="pill" variant="outline" disabled={!picked.size || !!v.reading || !!busy} data-tour="project-read"
          onClick={async () => {
            setBusy('read')
            try {
              const r: any = await ax.act('project_read', { id: p.id, message_ids: [...picked] }, ['projects'])
              const res = r?.result || r || {}
              toast(`Claude is reading ${res.mails ?? picked.size} mail${(res.mails ?? picked.size) === 1 ? '' : 's'}…`)
              if (res.note) toast(res.note)
              setPicked(new Set()); await load()
            } catch (e: any) { toast.error(e.message) } finally { setBusy(null) }
          }}>
          {v.reading ? <Loader2 className="animate-spin" /> : <Sparkles />}{v.reading ? 'Reading…' : `Read with Claude${picked.size ? ` (${picked.size})` : ''}`}</Button>
        <span className="text-ink-3 text-[12px]">Only the mails you tick are read – it suggests tasks, notes and dates; nothing is added without your tap.</span>
      </div>}
    </SectionCard>
    {v.suggestions.length > 0 && <Suggestions p={p} cards={v.suggestions} onDone={load} />}
    {adding && <AddMailDialog onClose={() => setAdding(false)} onAdd={m => act('add', 'project_mail_add', { mail: m, message_id: m.message_id }, 'Added to ' + p.name).then(ok => ok && setAdding(false))} />}
    {moving && <Dialog open onOpenChange={o => !o && setMoving(null)}><DialogContent className="sm:max-w-sm"><div className="space-y-3 p-5 text-sm">
      <DialogTitle className="text-lg font-semibold">Add to another project</DialogTitle>
      <div className="divide-y rounded-md border">{others.map(o => <button key={o.id} className="hover:bg-bg-2 block w-full px-3 py-2 text-left" disabled={!!busy}
        onClick={async () => { if (await act('mv', 'project_mail_move', { message_id: moving.message_id, to: o.id }, 'Added to ' + o.name)) setMoving(null) }}>{o.name}</button>)}</div>
    </div></DialogContent></Dialog>}
  </>
}

function MailRow({ m, picked, busy, onPick, onRemove, onAttach }: { m: PMail; picked: boolean; busy: boolean; onPick: (on: boolean) => void; onRemove: () => void; onAttach: (n: number) => void }) {
  const [att, setAtt] = useState<string[] | null>(null)
  const [open, setOpen] = useState(false)
  async function showAtt() {
    setOpen(!open)
    if (att || !m.account) return
    try { const j = await get<{ message: { attachments: string[] } }>(`message?account=${encodeURIComponent(m.account)}&id=${encodeURIComponent(m.message_id)}`); setAtt(j.message?.attachments || []) }
    catch { setAtt([]) }
  }
  return <div className="py-1 text-sm" data-project-mail="">
    <div className="flex items-center gap-2">
      <input type="checkbox" checked={picked} onChange={e => onPick(e.target.checked)} aria-label={'Pick ' + (m.subject || 'mail')} />
      <button className="min-w-0 flex-1 text-left" onClick={() => openMailInAxella({ account: m.account, message_id: m.message_id, subject: m.subject, from: m.from })}>
        <span className="block truncate">{m.subject || '(no subject)'}</span>
        <span className="text-ink-3 block truncate text-[12.5px]">{[m.from, day(m.date)].filter(Boolean).join(' · ')}</span></button>
      <button className="text-ink-3 hover:text-ink shrink-0 text-[12px]" onClick={showAtt} aria-expanded={open}><FileText className="mr-0.5 inline size-3.5" />Attachments</button>
      <button className="text-ink-3 hover:text-danger shrink-0 p-1" aria-label="Remove from project" disabled={busy} onClick={onRemove}><X className="size-4" /></button>
    </div>
    {open && <div className="text-ink-2 mt-1 space-y-1 pl-6 text-[12.5px]">{att === null ? 'Loading…' : !att.length ? 'No attachments.' : att.map((a, i) =>
      <div key={i} className="flex items-center gap-2"><span className="min-w-0 flex-1 truncate">{a}</span>
        <Button size="pill" variant="outline" disabled={busy} onClick={() => onAttach(i + 1)}>Add to Documents</Button></div>)}</div>}
  </div>
}

function Suggestions({ p, cards, onDone }: { p: Project; cards: Card_[]; onDone: () => void }) {
  const { ax } = useApp()
  const [cal, setCal] = useState<Card_ | null>(null)
  const [busy, setBusy] = useState(false)
  async function done(c: Card_, action?: string, body?: Record<string, unknown>, msg?: string) {
    setBusy(true)
    try {
      if (action) await ax.act(action, body!, ['tasks', 'projects'])
      await ax.act('project_suggestion_done', { id: p.id, sid: c.id }, [])
      if (msg) toast(msg); onDone()
    } catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(false) }
  }
  const icon = { task: Check, note: StickyNote, date: CalendarPlus }
  return <Card className="overflow-hidden" data-project-suggestions="">
    <div className="ax-label flex items-center gap-1.5 border-b px-4 py-2.5"><Sparkles className="size-3.5" />Suggested from the mails you picked</div>
    <div className="divide-y">{cards.map(c => {
      const I = icon[c.kind]
      return <div key={c.id} className="space-y-2 px-4 py-2.5 text-sm">
        <div className="flex gap-2"><I className="text-ink-3 mt-0.5 size-4 shrink-0" /><span className="min-w-0 flex-1">{c.text}
          {c.kind === 'task' && c.due && <span className="text-ink-3"> · due {day(c.due)}</span>}
          {c.kind === 'date' && <span className="text-ink-3"> · {day(c.date)}{c.time ? ' ' + c.time : ''}</span>}</span></div>
        <div className="flex flex-wrap gap-2 pl-6">
          {c.kind === 'task' && <Button size="pill" variant="outline" disabled={busy} onClick={() => done(c, 'task_add', { text: `${c.text} #${p.tag}`, due: c.due || null, source: 'project' }, 'Added to To do')}><Plus />Add task</Button>}
          {c.kind === 'note' && <Button size="pill" variant="outline" disabled={busy} onClick={() => done(c, 'project_note_add', { id: p.id, text: c.text }, 'Added to Notes')}><Plus />Add note</Button>}
          {c.kind === 'date' && <Button size="pill" variant="outline" disabled={busy} onClick={() => setCal(c)}><CalendarPlus />Add to calendar</Button>}
          <Button size="pill" variant="ghost" disabled={busy} onClick={() => done(c)}>Dismiss</Button>
        </div>
        {cal?.id === c.id && <CalendarForm it={{ id: 'pdate-' + c.id, section: 'p3', headline: c.text,
          event: { title: c.text, calendar: cals()[0]?.[0] || '', start: `${c.date}T${c.time || '09:00'}`, end: `${c.date}T${c.time ? String(Math.min(23, +c.time.slice(0, 2) + 1)).padStart(2, '0') + c.time.slice(2) : '10:00'}` } } as Item}
          onClose={() => setCal(null)} onCreate={async body => { await ax.act('event', body); await done(c) }} />}
      </div>
    })}</div>
  </Card>
}

interface Found { account?: string | null; message_id?: string | null; subject?: string; from_name?: string; from_address?: string; date?: string; private?: boolean }

function AddMailDialog({ onClose, onAdd }: { onClose: () => void; onAdd: (m: { account: string; message_id: string; subject?: string; from?: string; date?: string }) => void }) {
  const [q, setQ] = useState('')
  const [res, setRes] = useState<{ items: Found[]; error?: string } | null>(null)
  const [busy, setBusy] = useState(false)
  async function search(e?: React.FormEvent) {
    e?.preventDefault()
    if (q.trim().length < 2) return
    setBusy(true)
    try { setRes(await get<{ items: Found[]; error?: string }>('mail_search?q=' + encodeURIComponent(q.trim()) + '&limit=40')) }
    catch (x: any) { setRes({ items: [], error: x.message }) } finally { setBusy(false) }
  }
  return <Dialog open onOpenChange={o => !o && onClose()}>
    <DialogContent className="max-h-[85dvh] overflow-y-auto sm:w-[min(560px,94vw)]">
      <div className="space-y-3 p-5 text-sm" data-add-project-mail="">
        <DialogTitle className="text-lg font-semibold">Add a mail to this project</DialogTitle>
        <p className="text-ink-3 -mt-1 text-[13px]">Search all mail on the Mac mini. Mail with a private contact can't be added.</p>
        <form onSubmit={search} className="flex gap-2"><Input value={q} onChange={e => setQ(e.target.value)} placeholder="Sender, subject or a word" autoFocus />
          <Button type="submit" disabled={busy || q.trim().length < 2}>{busy ? <Loader2 className="animate-spin" /> : null}Search</Button></form>
        {res?.error && <p className="text-dawn text-[13px]">{res.error}</p>}
        {res && !res.error && !res.items.length && <p className="text-ink-3 text-[13px]">Nothing found.</p>}
        {!!res?.items.length && <div className="divide-y rounded-md border">{res.items.map((f, i) => {
          const can = !f.private && !!f.message_id && !!f.account
          return <div key={(f.message_id || '') + i} className="flex items-center gap-2 px-3 py-2">
            <span className="min-w-0 flex-1"><span className="block truncate">{f.private ? 'A mail with a private contact' : f.subject || '(no subject)'}</span>
              <span className="text-ink-3 text-[12.5px]">{[f.private ? '' : f.from_name || f.from_address, day(f.date)].filter(Boolean).join(' · ')}</span></span>
            {can && <Button size="pill" variant="outline" onClick={() => onAdd({ account: f.account!, message_id: f.message_id!, subject: f.subject, from: f.from_name || f.from_address, date: f.date })}>Add</Button>}
          </div>
        })}</div>}
      </div>
    </DialogContent>
  </Dialog>
}

/** On the project page: Link to trip offers, and the linked trips' cards (dates, bookings, next item). */
export function ProjectTrips({ p }: { p: Project }) {
  const { ax, go } = useApp()
  const { v, load } = useProjectMail(p.id)
  if (!v || (!v.trip_offers.length && !v.linked_trips.length)) return null
  const act = (action: string, trip: string, msg: string) => ax.act(action, { id: p.id, trip }, ['projects']).then(() => { toast(msg); load() }).catch((e: any) => toast.error('Failed: ' + e.message))
  return <Card className="overflow-hidden" data-project-trips="">
    <div className="ax-label flex items-center gap-1.5 border-b px-4 py-2.5"><TripIcon className="size-3.5" />Trips</div>
    <div className="divide-y">
      {v.linked_trips.map(t => <div key={t.id} className="space-y-1 px-4 py-2.5 text-sm">
        <div className="flex items-center gap-2"><button className="min-w-0 flex-1 truncate text-left font-medium hover:underline" onClick={() => go({ kind: 'trips' })}>{t.title}</button>
          <button className="text-ink-3 hover:text-ink text-[12px]" onClick={() => act('project_trip_unlink', t.id, 'Unlinked')}>Unlink</button></div>
        <div className="text-ink-3 text-[12.5px]">{[t.start && t.end ? `${day(t.start)} – ${day(t.end)}` : '', `${t.bookings} booking${t.bookings === 1 ? '' : 's'}`, t.next ? 'next: ' + t.next.title + ' ' + day(t.next.start) : ''].filter(Boolean).join(' · ')}</div>
      </div>)}
      {v.trip_offers.map(t => <div key={t.id} className={cn('flex items-center gap-2 px-4 py-2.5 text-sm', 'bg-fjord-soft/30')}>
        <span className="min-w-0 flex-1">Its booking mails are on this project – link to <b className="font-medium">{t.title}</b>?</span>
        <Button size="pill" variant="outline" onClick={() => act('project_trip_link', t.id, 'Linked to ' + t.title)}><ExternalLink />Link to trip</Button>
      </div>)}
    </div>
  </Card>
}

/** On a trip: the projects it is linked to (the link back). */
export function TripProjects({ tripId }: { tripId: string }) {
  const { go } = useApp()
  const [ps, setPs] = useState<{ id: string; name: string }[]>([])
  useEffect(() => { get<{ projects: { id: string; name: string }[] }>('project_links_for_trip?trip=' + encodeURIComponent(tripId)).then(r => setPs(r.projects || [])).catch(() => {}) }, [tripId])
  if (!ps.length) return null
  return <span className="text-ink-3 flex flex-wrap items-center gap-1.5 text-[12.5px]" data-trip-projects="">Project{ps.length > 1 ? 's' : ''}:
    {ps.map(x => <button key={x.id} className="text-fjord hover:underline" onClick={() => go({ kind: 'project', id: x.id })}>{x.name}</button>)}</span>
}

