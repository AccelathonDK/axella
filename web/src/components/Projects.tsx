import { ProjectMeetings } from '@/components/Meetings'
import { ProjectMail, ProjectTrips } from '@/components/ProjectMail'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Archive, ArchiveRestore, Check, MoreHorizontal, ExternalLink, FileText, FolderKanban, Image as ImageIcon, Inbox, Link2, Loader2, Pencil, Plus, Sparkles, StickyNote, Tag, Upload, X } from '@/components/ax-icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input, NativeSelect } from '@/components/ui/input'
import { SectionCard, Empty } from '@/components/Section'
import { ItemRow, useHold } from '@/components/ItemRow'
import { TasksCard } from '@/components/Cards'
import { ThreadRow, groupThreads } from '@/components/Thread'
import { KnowledgeCard } from '@/components/Knowledge'
import { useApp } from '@/lib/app'
import { archivePath } from '@/lib/data'
import { PROJECT_COLORS, fileUrl, fmtSize, projColor, projectWorld, upload } from '@/lib/projects'
import type { Project } from '@/lib/types'
import { cn } from '@/lib/utils'

const when = (iso?: string) => iso ? new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: new Date(iso).getFullYear() === new Date().getFullYear() ? undefined : 'numeric' }) : ''

function useRun() {
  const { ax } = useApp()
  const [busy, setBusy] = useState<string | null>(null)
  const run = async (key: string, action: string, body: any, msg?: string) => {
    setBusy(key)
    try { await ax.act(action, body, ['projects']); if (msg) toast(msg); return true }
    catch (e: any) { toast.error('Failed: ' + e.message); return false } finally { setBusy(null) }
  }
  return { busy, run }
}

/* ---------- archive: one confirm dialog for the whole app (project page, Projects overview, sidebar) ---------- */
export const openArchive = (id: string) => window.dispatchEvent(new CustomEvent('ax-archive', { detail: id }))
export function ArchiveHost() {
  const { ax, view, go } = useApp()
  const [id, setId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { const h = (e: Event) => setId((e as CustomEvent).detail); window.addEventListener('ax-archive', h); return () => window.removeEventListener('ax-archive', h) }, [])
  const p = ax.projects.find(x => x.id === id)
  if (!p) return null
  const tasks = ax.tasks.filter(t => t.status !== 'done' && new RegExp('#' + p.tag + '\\b', 'i').test(t.text)).length
  const restore = () => ax.act('project_update', { id: p.id, status: 'active' }, ['projects']).then(() => toast(p.name + ' restored')).catch((e: any) => toast.error('Failed: ' + e.message))
  async function archive() {
    setBusy(true)
    try {
      await ax.act('project_update', { id: p!.id, status: 'archived' }, ['projects'])
      toast(p!.name + ' archived', { action: { label: 'Undo', onClick: restore } })
      if (view.kind === 'project' && view.id === p!.id) go({ kind: 'projects' })
      setId(null)
    } catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(false) }
  }
  return <Dialog open onOpenChange={o => !o && setId(null)}>
    <DialogContent className="sm:w-[min(480px,92vw)]">
      <div className="flex gap-3 px-5 pt-5 pb-2 pr-12">
        <span className="bg-bg-2 text-ink flex size-10 shrink-0 items-center justify-center rounded-md"><Archive className="size-5" /></span>
        <div><DialogTitle className="text-lg leading-snug font-semibold">Archive {p.name}?</DialogTitle>
          <ul className="text-ink-2 mt-1.5 space-y-1 text-sm">
            <li>It leaves the menu, and Axella stops tagging new messages to #{p.tag}.</li>
            <li>Notes, links, documents{tasks ? ` and its ${tasks} open ${tasks === 1 ? 'task' : 'tasks'}` : ''} stay as they are.</li>
            <li>Restore it any time from Projects → Archived.</li>
          </ul></div>
      </div>
      <div className="flex justify-end gap-2 border-t px-5 py-3">
        <Button variant="ghost" onClick={() => setId(null)}>Cancel</Button>
        <Button disabled={busy} onClick={archive}>{busy ? <Loader2 className="animate-spin" /> : <Archive />}Archive</Button>
      </div>
    </DialogContent>
  </Dialog>
}

function DeleteX({ onDelete, label = 'Delete' }: { onDelete: () => void; label?: string }) {
  const [armed, setArmed] = useState(false)
  return <button aria-label={label} className={cn('text-muted-foreground hover:text-destructive shrink-0 text-xs', armed && 'text-destructive font-medium')}
    onClick={() => { if (armed) onDelete(); else { setArmed(true); setTimeout(() => setArmed(false), 3000) } }}>{armed ? 'Delete?' : <X className="size-4" />}</button>
}

/* ---------- one project ---------- */
export function ProjectView({ id }: { id: string }) {
  const { ax, go, projectsFor, activeProjects } = useApp()
  const p = ax.projects.find(x => x.id === id)
  const { busy, run } = useRun()
  if (!p) return <div className="py-10 text-center text-muted-foreground">Project not found.</div>
  const items = (ax.current?.data.items || []).filter(it => projectsFor(it).some(x => x.id === p.id))
  const inDigest = new Set(items.map(i => i.id))
  const earlier = (p.items || []).filter(r => !inDigest.has(r.item_id)).slice().reverse()
  const tagRe = new RegExp('#' + p.tag + '\\b', 'i')
  const kws = (p.keywords || []).filter(k => k.length > 2).map(k => k.toLowerCase())
  const taskFilter = (t: { text: string }) => tagRe.test(t.text) || kws.some(k => t.text.toLowerCase().includes(k))
  const color = projColor(activeProjects, p.id)
  return (
    <div className="space-y-4" style={{ ['--c' as any]: color }} data-tour="project">
      <div className="flex flex-wrap items-start gap-3">
        <div className="bg-bg-2 flex size-11 shrink-0 items-center justify-center rounded-md"><span className="ax-diamond" style={{ color, width: 12, height: 12 }} /></div>
        <div className="min-w-0 flex-1">
          <ProjectTitle p={p} />
          <div className="text-muted-foreground flex flex-wrap items-center gap-x-2 text-sm">
            <span className="text-ink-3 font-mono text-[13px]">#{p.tag}</span>
            <span>· {p.status === 'suggested' ? 'Suggested by ' + (p.source || 'Claude') : p.status === 'archived' ? 'Archived' + (p.archived ? ' ' + when(p.archived) : '') : 'Since ' + when(p.accepted || p.created)}</span>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {p.status === 'suggested' ? <>
            <Button size="sm" onClick={() => run('acc', 'project_update', { id: p.id, status: 'active' }, 'Project created')} disabled={!!busy}><Check />Accept</Button>
            <Button size="sm" variant="outline" onClick={async () => { if (await run('dis', 'project_dismiss', { id: p.id }, 'Suggestion dismissed')) go({ kind: 'projects' }) }} disabled={!!busy}><X />Dismiss</Button>
          </> : p.status === 'archived'
            ? null   /* the banner below has Restore */
            : <Button size="sm" variant="outline" onClick={() => openArchive(p.id)}><Archive />Archive</Button>}
        </div>
      </div>
      {p.status === 'archived' && <div className="bg-bg-2 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg px-4 py-3 text-sm">
        <Archive className="text-ink-3 size-4 shrink-0" />
        <span className="text-ink-2 min-w-[14rem] flex-1">Not in the menu, and Axella doesn’t tag new messages to it. Everything here is kept.</span>
        {ax.apiOk && <Button size="pill" className="max-sm:w-full" onClick={() => run('arc2', 'project_update', { id: p.id, status: 'active' }, p.name + ' restored – back in the menu')} disabled={!!busy}><ArchiveRestore />Restore project</Button>}
      </div>}
      {p.status === 'suggested' && p.why && <div className="bg-fjord-soft flex gap-2 rounded-lg px-3 py-2 text-sm"><Sparkles className="text-fjord mt-0.5 size-4 shrink-0" />{p.why}</div>}
      <Keywords p={p} />
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <div className="space-y-4">
          <SectionCard id="pmsg" color={color} icon={Inbox} title="Messages" sub={ax.current ? 'In ' + ax.current.meta.label + ' · matched by tag, keyword or your pins' : ''} count={items.filter(i => !ax.isHandled(i.id)).length}>
            {items.length ? [...items.filter(i => i.section !== 'file').map(i => <ItemRow key={i.id} it={i} />),
              ...groupThreads(items.filter(i => i.section === 'file')).map(g => g.length > 1 ? <ThreadRow key={g[0].id} items={g} /> : <ItemRow key={g[0].id} it={g[0]} />)]
              : <Empty>Nothing for this project in this digest</Empty>}
            {earlier.length > 0 && <div className="px-4 py-3">
              <div className="text-muted-foreground mb-1.5 text-xs font-semibold tracking-wide uppercase">Pinned from earlier digests</div>
              {earlier.map(r => <div key={r.item_id} className="flex items-center gap-2 py-1 text-sm">
                <button className="hover:text-primary min-w-0 flex-1 truncate text-left" onClick={async () => { if (!r.digest) return; try { await ax.select(r.digest).catch(() => ax.select(archivePath(r.digest!))); go({ kind: 'briefing' }) } catch { toast('That digest is no longer available') } }}>{r.headline || r.item_id}</button>
                <span className="text-muted-foreground shrink-0 text-xs">{when(r.added)}</span>
                <DeleteX label="Unpin" onDelete={() => run('unpin', 'project_item_remove', { id: p.id, item_id: r.item_id }, 'Unpinned')} />
              </div>)}
            </div>}
          </SectionCard>
          {p.status === 'active' && ax.apiOk && <ProjectMail p={p} />}
          <TasksCard filter={taskFilter} tag={p.tag} title="Tasks" sub={`Tasks mentioning #${p.tag} or a keyword`} />
          {p.status !== 'suggested' && <ProjectMeetings project={p} />}
          {p.status !== 'suggested' && <KnowledgeCard project={p} />}
        </div>
        <div className="space-y-4">
          {p.status === 'active' && ax.apiOk && <ProjectTrips p={p} />}
          <Documents p={p} />
          <Notes p={p} />
          <Links p={p} />
        </div>
      </div>
    </div>
  )
}

function ProjectTitle({ p }: { p: Project }) {
  const { run, busy } = useRun()
  const [edit, setEdit] = useState(false)
  const [name, setName] = useState(p.name)
  const [color, setColor] = useState(p.color || PROJECT_COLORS[0])
  useHold(edit)
  if (!edit) return (
    <button className="group flex items-center gap-2 text-left" onClick={() => { setName(p.name); setColor(p.color || PROJECT_COLORS[0]); setEdit(true) }} title="Rename">
      <h1 className="text-xl font-semibold tracking-tight">{p.name}</h1>
      <Pencil className="text-muted-foreground size-4 opacity-60 group-hover:opacity-100" />
    </button>)
  async function save(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    if (name.trim() === p.name && color === p.color) { setEdit(false); return }
    if (await run('ren', 'project_update', { id: p.id, name: name.trim(), color }, 'Project updated')) setEdit(false)
  }
  return (
    <form onSubmit={save} className="w-full space-y-2">
      <div className="flex flex-wrap gap-2">
        <Input value={name} onChange={e => setName(e.target.value)} maxLength={80} autoFocus className="h-9 basis-full text-base font-semibold sm:basis-0 sm:flex-1"
          onKeyDown={e => { if (e.key === 'Escape') setEdit(false) }} aria-label="Project name" />
        <Button size="sm" type="submit" className="h-9" disabled={!!busy}><Check />Save</Button>
        <Button size="sm" type="button" variant="outline" className="h-9" onClick={() => setEdit(false)}>Cancel</Button>
      </div>
      <p className="text-muted-foreground text-xs">Project colours follow the order in the menu – drag to reorder. The tag #{p.tag} stays the same, so existing links and tagged messages keep working.</p>
    </form>)
}

function Keywords({ p }: { p: Project }) {
  const { run } = useRun()
  const [v, setV] = useState('')
  const kws = p.keywords || []
  const save = (list: string[], msg: string) => run('kw', 'project_update', { id: p.id, keywords: list }, msg)
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-sm">
      <Tag className="text-muted-foreground size-4" />
      <span className="text-muted-foreground mr-1">Matches</span>
      {kws.map(k => <Badge key={k} variant="outline" className="text-foreground gap-1 py-0.5 text-xs font-medium">{k}
        <button aria-label={'Remove ' + k} onClick={() => save(kws.filter(x => x !== k), 'Keyword removed')}><X className="text-muted-foreground hover:text-destructive" /></button></Badge>)}
      <form className="inline-flex" onSubmit={e => { e.preventDefault(); if (v.trim() && !kws.includes(v.trim())) save([...kws, v.trim()], 'Keyword added'); setV('') }}>
        <Input value={v} onChange={e => setV(e.target.value)} placeholder="+ keyword or sender" className="h-7 w-40 text-[13px]" maxLength={60} />
      </form>
      <span className="text-muted-foreground ml-3 mr-1">Belongs to</span>
      <NativeSelect aria-label="Work or private" className="h-7 w-auto text-[13px] sm:h-7" value={p.ctx || ''}
        title="Private items never get a work project, and the other way round"
        onChange={e => run('ctx', 'project_update', { id: p.id, ctx: e.target.value || null }, e.target.value ? `${p.name} is ${e.target.value} now` : `${p.name}: decided automatically`)}>
        <option value="">{projectWorld({ ...p, ctx: undefined }) === 'work' ? 'Work (auto)' : 'Both (auto)'}</option>
        <option value="work">Work</option>
        <option value="private">Private</option>
      </NativeSelect>
    </div>
  )
}

function Documents({ p }: { p: Project }) {
  const { ax, go } = useApp()
  const tagged = ax.documents.filter(d => d.project === p.id && !d.hidden).length
  const { run } = useRun()
  const ref = useRef<HTMLInputElement>(null)
  const [up, setUp] = useState<string | null>(null)
  const [drag, setDrag] = useState(false)
  async function send(files: FileList | File[]) {
    for (const f of Array.from(files)) {
      setUp(f.name)
      try { await upload(p, f); toast('Uploaded ' + f.name) } catch (e: any) { toast.error(f.name + ': ' + e.message) }
    }
    setUp(null); await ax.refresh(['projects'])
  }
  const files = (p.files || []).slice().reverse()
  return (
    <div onDragOver={e => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
      onDrop={e => { e.preventDefault(); setDrag(false); if (e.dataTransfer.files.length) send(e.dataTransfer.files) }}
      className={cn('rounded-lg', drag && 'ring-fjord ring-2')}>
      <SectionCard id="pdocs" color="var(--ax-wait)" icon={FileText} title="Documents" sub="Tickets, bookings, PDFs" count={files.length + tagged}
        right={ax.apiOk && <Button size="pill" variant="outline" onClick={() => ref.current?.click()} disabled={!!up}>{up ? <Loader2 className="animate-spin" /> : <Upload />}Upload</Button>}>
        <input ref={ref} type="file" multiple hidden accept="application/pdf,image/*,.txt,.ics,.pkpass" onChange={e => { if (e.target.files?.length) send(e.target.files); e.target.value = '' }} />
        {up && <div className="text-muted-foreground flex items-center gap-2 px-4 py-2.5 text-sm"><Loader2 className="size-4 animate-spin" />Uploading {up}…</div>}
        {files.length ? files.map(f => {
          const I = f.type.startsWith('image/') ? ImageIcon : FileText
          return <div key={f.id} className="flex items-center gap-3 px-4 py-2.5">
            <div className="bg-bg-2 text-ink flex size-8 shrink-0 items-center justify-center rounded-md"><I className="size-4" /></div>
            <a href={fileUrl(p, f)} target="_blank" rel="noopener" className="min-w-0 flex-1">
              <div className="truncate text-[14.5px] font-medium hover:underline">{f.name}</div>
              <div className="text-muted-foreground text-xs">{fmtSize(f.size)} · {when(f.uploaded)}</div>
            </a>
            <DeleteX onDelete={() => run('fdel', 'project_file_delete', { id: p.id, entry: f.id }, 'Document removed')} />
          </div>
        }) : !up && <button onClick={() => ref.current?.click()} className="text-muted-foreground hover:text-foreground w-full px-4 py-5 text-center text-sm">
          <Upload className="mx-auto mb-1 size-5" />Drop a PDF here or tap to upload</button>}
        {tagged > 0 && <button onClick={() => go({ kind: 'receipts' })} className="text-fjord w-full border-t px-4 py-2.5 text-left text-[13px] font-medium hover:underline">
          + {tagged} receipt{tagged === 1 ? '' : 's'} and invoices tagged to this project – see Receipts</button>}
      </SectionCard>
    </div>
  )
}

function Notes({ p }: { p: Project }) {
  const { busy, run } = useRun()
  const [v, setV] = useState('')
  useHold(!!v.trim())
  const notes = (p.notes || []).slice().reverse()
  return (
    <SectionCard id="pnotes" color="var(--ax-p1)" icon={StickyNote} title="Notes" count={notes.length}>
      <form className="flex flex-col gap-2 p-3" onSubmit={async e => { e.preventDefault(); if (v.trim() && await run('note', 'project_note_add', { id: p.id, text: v.trim() }, 'Note added')) setV('') }}>
        <textarea value={v} onChange={e => setV(e.target.value)} rows={2} maxLength={5000} placeholder="Booking ref, gate code, who to call…"
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) (e.currentTarget.form as HTMLFormElement).requestSubmit() }}
          className="border-line-strong bg-card focus-visible:border-ring focus-visible:ring-ring/30 w-full rounded-md border px-2.5 py-1.5 text-[16px] outline-none focus-visible:ring-2 sm:text-sm" />
        {v.trim() && <Button size="sm" type="submit" className="self-end" disabled={!!busy}><Plus />Add note</Button>}
      </form>
      {notes.map(n => <div key={n.id} className="flex gap-2 px-4 py-2.5">
        <div className="min-w-0 flex-1"><div className="text-[14.5px] whitespace-pre-wrap">{n.text}</div><div className="text-muted-foreground text-xs">{when(n.created)}</div></div>
        <DeleteX onDelete={() => run('ndel', 'project_note_delete', { id: p.id, entry: n.id }, 'Note deleted')} />
      </div>)}
    </SectionCard>
  )
}

function Links({ p }: { p: Project }) {
  const { busy, run } = useRun()
  const [url, setUrl] = useState(''), [title, setTitle] = useState('')
  useHold(!!url.trim())
  const links = (p.links || []).slice().reverse()
  async function add(e: React.FormEvent) {
    e.preventDefault()
    let u = url.trim(); if (!u) return
    if (!/^https?:\/\//i.test(u)) u = 'https://' + u
    if (await run('link', 'project_link_add', { id: p.id, url: u, title: title.trim() }, 'Link added')) { setUrl(''); setTitle('') }
  }
  return (
    <SectionCard id="plinks" color="var(--ax-cal)" icon={Link2} title="Links" count={links.length}>
      <form className="flex flex-wrap gap-2 p-3" onSubmit={add}>
        <Input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…" inputMode="url" className="min-w-[160px] flex-[2]" />
        <Input value={title} onChange={e => setTitle(e.target.value)} placeholder="Title (optional)" className="min-w-[120px] flex-1" />
        <Button size="icon-sm" type="submit" aria-label="Add link" disabled={!!busy}><Plus /></Button>
      </form>
      {links.map(l => <div key={l.id} className="flex items-center gap-2 px-4 py-2.5">
        <ExternalLink className="text-muted-foreground size-4 shrink-0" />
        <a href={l.url} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1">
          <div className="truncate text-[14.5px] font-medium hover:underline">{l.title || l.url.replace(/^https?:\/\/(www\.)?/, '')}</div>
          {l.title && <div className="text-muted-foreground truncate text-xs">{l.url.replace(/^https?:\/\/(www\.)?/, '')}</div>}
        </a>
        <DeleteX onDelete={() => run('ldel', 'project_link_delete', { id: p.id, entry: l.id }, 'Link removed')} />
      </div>)}
    </SectionCard>
  )
}

/* ---------- overview ---------- */
export function NewProjectForm({ onDone }: { onDone?: (id: string) => void }) {
  const { ax } = useApp()
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  useHold(!!name.trim())
  return (
    <form className="flex gap-2" onSubmit={async e => {
      e.preventDefault(); if (!name.trim()) return; setBusy(true)
      try { const r = await ax.act<{ result: string }>('project_add', { name: name.trim() }, ['projects']); setName(''); toast('Project created'); onDone?.(r.result) }
      catch (err: any) { toast.error('Failed: ' + err.message) } finally { setBusy(false) }
    }}>
      <Input value={name} onChange={e => setName(e.target.value)} placeholder="New project, e.g. Summer 2027" maxLength={80} />
      <Button size="icon-sm" type="submit" aria-label="Create project" className="shrink-0" disabled={busy}><Plus /></Button>
    </form>
  )
}

export function ProjectsOverview() {
  const { ax, go, projectsFor } = useApp()
  const { run } = useRun()
  const items = ax.current?.data.items || []
  const active = ax.projects.filter(p => p.status === 'active'), sugg = ax.projects.filter(p => p.status === 'suggested'), arch = ax.projects.filter(p => p.status === 'archived')
  const count = (p: Project) => items.filter(i => !ax.isHandled(i.id) && projectsFor(i).some(x => x.id === p.id)).length
  return (
    <div className="space-y-5" data-tour="projects">
      <div><h1 className="text-xl font-semibold tracking-tight">Projects</h1>
        <p className="text-muted-foreground text-sm">Messages, tasks, notes, links and documents per project. Tag messages from the ⋯ menu; Axella also matches keywords and suggests new projects.</p></div>
      {ax.apiOk && <div className="max-w-md"><NewProjectForm onDone={id => go({ kind: 'project', id })} /></div>}
      {sugg.length > 0 && <section className="space-y-2">
        <h2 className="text-muted-foreground flex items-center gap-1.5 text-xs font-semibold tracking-wide uppercase"><Sparkles className="size-3.5" />Suggested by Axella</h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {sugg.map(p => <Card key={p.id} className="space-y-2 p-4">
            <div className="flex items-center gap-2"><span className="ax-diamond text-ink-3" /><span className="font-semibold">{p.name}</span><span className="text-ink-3 font-mono text-[13px]">#{p.tag}</span></div>
            {p.why && <p className="text-muted-foreground text-sm">{p.why}</p>}
            <div className="flex gap-1.5">
              <Button size="pill" onClick={() => run('a' + p.id, 'project_update', { id: p.id, status: 'active' }, p.name + ' created')}><Check />Accept</Button>
              <Button size="pill" variant="outline" onClick={() => run('d' + p.id, 'project_dismiss', { id: p.id }, 'Dismissed')}><X />Dismiss</Button>
              <Button size="pill" variant="ghost" onClick={() => go({ kind: 'project', id: p.id })}>Preview</Button>
            </div>
          </Card>)}
        </div>
      </section>}
      <section className="space-y-2">
        <h2 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">Active</h2>
        {active.length ? <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {active.map(p => <div key={p.id} className="bg-card hover:border-line-strong relative rounded-lg border transition-colors">
            <button onClick={() => go({ kind: 'project', id: p.id })} className="block w-full p-4 pr-12 text-left">
              <div className="flex items-center gap-2"><span className="ax-diamond" style={{ color: projColor(active, p.id) }} /><span className="font-semibold">{p.name}</span>
                {count(p) > 0 && <span className="bg-fjord-soft text-fjord ml-auto rounded-sm px-1.5 font-mono text-xs leading-5 tabular-nums">{count(p)}</span>}</div>
              <div className="text-muted-foreground mt-1 text-sm">#{p.tag} · {plural((p.files || []).length + ax.documents.filter(d => d.project === p.id && !d.hidden).length, 'document')} · {plural((p.notes || []).length, 'note')} · {plural((p.links || []).length, 'link')}</div>
            </button>
            {ax.apiOk && <DropdownMenu>
              <DropdownMenuTrigger asChild><button aria-label={'More for ' + p.name} className="text-ink-3 hover:text-ink absolute top-3 right-2 flex size-8 items-center justify-center rounded-md"><MoreHorizontal className="size-4" /></button></DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => go({ kind: 'project', id: p.id })}><FolderKanban />Open</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => openArchive(p.id)}><Archive />Archive…</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>}
          </div>)}
        </div> : ax.projectsError ? <p className="text-destructive text-sm">Couldn't load your projects from the Mac mini. <button className="text-fjord font-semibold hover:underline" onClick={() => ax.refresh(['projects'])}>Try again</button></p>
          : !ax.projectsLoaded ? <p className="text-muted-foreground text-sm">Loading projects…</p>
          : <p className="text-muted-foreground text-sm">No projects yet – create one above or accept a suggestion.</p>}
      </section>
      {arch.length > 0 && <section id="archived" className="scroll-mt-sec space-y-2">
        <h2 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">Archived · {arch.length}</h2>
        <Card className="divide-y">
          {arch.slice().sort((a, b) => (b.archived || '').localeCompare(a.archived || '')).map(p => <div key={p.id} className="flex min-h-11 items-center gap-3 px-4 py-2">
            <span className="ax-diamond text-ink-3 shrink-0" style={{ width: 7, height: 7 }} />
            <button className="text-ink-2 hover:text-ink min-w-0 flex-1 truncate text-left text-sm" onClick={() => go({ kind: 'project', id: p.id })}>{p.name}
              <span className="text-ink-3 ml-2 font-mono text-[12px]">#{p.tag}{p.archived ? ' · archived ' + when(p.archived) : ''}</span></button>
            {ax.apiOk && <Button size="pill" variant="outline" onClick={async () => { if (await run('r' + p.id, 'project_update', { id: p.id, status: 'active' }))
              toast(p.name + ' restored – back in the menu', { action: { label: 'Open', onClick: () => go({ kind: 'project', id: p.id }) } }) }}><ArchiveRestore />Restore</Button>}
          </div>)}
        </Card>
      </section>}
    </div>
  )
}

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`
