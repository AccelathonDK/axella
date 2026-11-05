import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { AlertTriangle, Check, ExternalLink, Loader2, Mail, Pencil, Plus, Search, Trash2, axi } from '@/components/ax-icons'
import { SectionCard, Empty } from '@/components/Section'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input, NativeSelect } from '@/components/ui/input'
import { useApp } from '@/lib/app'
import { CATEGORIES, CAT_LABEL, LEARNED, VIS, inProject, needsCheck, scopeIds, loadKnowledge, openKnowledge, shortDate, useKnowledge, type KDraft, type KEntry, type Visibility } from '@/lib/knowledge'
import { LearningCard } from '@/components/KnowledgeLearn'
import { projColor } from '@/lib/projects'
import { cn } from '@/lib/utils'

export const KnowledgeIcon = axi('one-place')
const area = 'border-line-strong bg-card focus-visible:border-ring focus-visible:ring-ring/30 w-full rounded-md border px-2.5 py-1.5 text-[16px] outline-none focus-visible:ring-2 sm:text-sm'

/* ---------- the editor: one dialog for the whole app ---------- */
export function KnowledgeHost() {
  const [d, setD] = useState<KDraft | null>(null)
  useEffect(() => { const h = (e: Event) => setD((e as CustomEvent).detail); window.addEventListener('ax-kb', h); return () => window.removeEventListener('ax-kb', h) }, [])
  return d ? <Editor key={d.id || 'new' + (d.title || '')} init={d} onClose={() => setD(null)} /> : null
}

function Editor({ init, onClose }: { init: KDraft; onClose: () => void }) {
  const { ax, activeProjects } = useApp()
  const all = useKnowledge()
  const existing = init.id ? all?.find(e => e.id === init.id) : undefined
  const [f, setF] = useState({
    title: init.title || '', body: init.body || '', scope: (Array.isArray(init.scope) && init.scope.length ? init.scope : 'overall') as 'overall' | string[],
    category: init.category || 'other', visibility: (init.visibility || 'internal') as Visibility, check_after: init.check_after || '',
  })
  const [busy, setBusy] = useState(false)
  const [armed, setArmed] = useState(false)
  const set = (p: Partial<typeof f>) => setF(x => ({ ...x, ...p }))
  const projects = f.scope === 'overall' ? [] : f.scope
  const toggle = (pid: string) => { const next = projects.includes(pid) ? projects.filter(x => x !== pid) : [...projects, pid]; set({ scope: next.length ? next : 'overall' }) }
  async function save(extra: object = {}) {
    setBusy(true)
    try {
      const body = { ...f, check_after: f.check_after || null, ...extra }
      if (init.id) await ax.act('kb_update', { id: init.id, ...body }, [])
      else await ax.act('kb_add', { ...body, ...(init.source ? { source: init.source } : {}) }, [])
      await loadKnowledge(true)
      toast(init.id ? 'Knowledge saved' : 'Added to knowledge – drafts can use it from the next run')
      onClose()
    } catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(false) }
  }
  async function del() {
    if (!armed) { setArmed(true); setTimeout(() => setArmed(false), 3000); return }
    try { await ax.act('kb_delete', { id: init.id }, []); await loadKnowledge(true); toast('Entry deleted (kept in knowledge/.deleted on the Mac mini)'); onClose() }
    catch (e: any) { toast.error('Failed: ' + e.message) }
  }
  const ok = f.title.trim() && f.body.trim()
  return <Dialog open onOpenChange={o => !o && onClose()}>
    <DialogContent>
      <div className="border-b px-5 py-3.5 pr-12">
        <DialogTitle className="flex items-center gap-2 text-base font-semibold"><KnowledgeIcon className="size-4" />{init.id ? 'Knowledge entry' : 'Add to knowledge'}</DialogTitle>
        <div className="text-ink-3 text-xs">A short fact or answer Axella may build drafts on · one language is fine, Axella translates</div>
      </div>
      <form className="flex-1 space-y-3 overflow-y-auto p-5 text-sm" onSubmit={e => { e.preventDefault(); if (ok) save() }}>
        {existing?.status === 'suggested' && <div className="bg-fjord-soft flex items-start gap-2 rounded-md px-3 py-2"><KnowledgeIcon className="text-fjord mt-0.5 size-4 shrink-0" />Suggested by Axella – approve it to let drafts use it.</div>}
        {existing?.status === 'suggested' && existing.learned && LEARNED[existing.learned] && <div className="text-ink-2 -mt-1 text-[13px]">
          Learned {LEARNED[existing.learned]}{existing.from_others ? <> – <b className="font-medium">stated by {existing.from_others}</b>, not by you: check it</> : ''}.</div>}
        {existing?.outdated && <div className="bg-bg-2 flex items-start gap-2 rounded-md px-3 py-2"><AlertTriangle className="text-dawn mt-0.5 size-4 shrink-0" />
          <span>May be outdated: {existing.outdated.reason}{existing.outdated.source?.label ? <span className="text-ink-3"> ({existing.outdated.source.label})</span> : ''}. Saving your edit clears this.</span></div>}
        {existing?.stale && <div className="bg-bg-2 flex items-start gap-2 rounded-md px-3 py-2"><AlertTriangle className="text-dawn mt-0.5 size-4 shrink-0" />Check date passed – is this still true? Save to keep it, or change the date.</div>}
        <label className="block"><span className="mb-1 block font-medium">Title</span>
          <Input autoFocus={!init.title} value={f.title} maxLength={200} placeholder="e.g. Invoicing terms, Check-in time, Parking at the office" onChange={e => set({ title: e.target.value })} /></label>
        <label className="block"><span className="mb-1 block font-medium">The fact or answer</span>
          <textarea rows={6} className={area + ' leading-relaxed'} value={f.body} maxLength={20000} placeholder="Keep it short and exact – dates, prices, links, the answer you'd give."
            onChange={e => set({ body: e.target.value })} /></label>
        <div>
          <span className="mb-1 block font-medium">Where it applies</span>
          <div className="flex flex-wrap gap-1.5">
            <Chip on={f.scope === 'overall'} onClick={() => set({ scope: 'overall' })}>Overall</Chip>
            {activeProjects.map(p => <Chip key={p.id} on={projects.includes(p.id)} onClick={() => toggle(p.id)}>
              <span className="ax-diamond" style={{ color: projColor(activeProjects, p.id), width: 6, height: 6 }} />{p.name}</Chip>)}
          </div>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block"><span className="mb-1 block font-medium">Category</span>
            <NativeSelect value={f.category} onChange={e => set({ category: e.target.value })}>
              {CATEGORIES.map(c => <option key={c} value={c}>{CAT_LABEL[c]}</option>)}</NativeSelect></label>
          <label className="block"><span className="mb-1 block font-medium">Check again after <span className="text-ink-3 font-normal">(optional)</span></span>
            <Input type="date" value={f.check_after} onChange={e => set({ check_after: e.target.value })} /></label>
        </div>
        <div>
          <span className="mb-1 block font-medium">Who may see it in a reply</span>
          <div className="grid gap-1.5 sm:grid-cols-3">
            {(Object.keys(VIS) as Visibility[]).map(v => <button type="button" key={v} onClick={() => set({ visibility: v })} aria-pressed={f.visibility === v}
              className={cn('rounded-md border px-3 py-2 text-left transition-colors', f.visibility === v ? 'border-fjord bg-fjord-soft' : 'border-line hover:border-line-strong')}>
              <div className={cn('font-medium', f.visibility === v && 'text-fjord')}>{VIS[v][0]}</div><div className="text-ink-3 text-xs">{VIS[v][1]}</div></button>)}
          </div>
        </div>
        {(existing?.sources?.length || init.source) && <div>
          <span className="mb-1 block font-medium">Sources</span>
          <ul className="text-ink-2 space-y-1 text-[13px]">
            {(existing?.sources || [init.source!]).map((s, i) => <li key={i} className="flex items-center gap-1.5">
              {s.kind === 'mail' ? <Mail className="size-3.5" /> : s.kind === 'url' ? <ExternalLink className="size-3.5" /> : <Pencil className="size-3.5" />}
              <span className="min-w-0 truncate">{s.label || s.ref || s.kind}</span><span className="text-ink-3 ml-auto font-mono text-[12px]">{shortDate(s.date)}</span></li>)}
          </ul>
        </div>}
        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
          {init.id && <button type="button" onClick={del} className={cn('text-ink-3 hover:text-danger inline-flex items-center gap-1.5 text-[13px]', armed && 'text-danger font-medium')}>
            <Trash2 className="size-4" />{armed ? 'Tap again to delete' : 'Delete'}</button>}
          <span className="flex-1" />
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          {existing?.status === 'suggested'
            ? <Button type="button" disabled={!ok || busy} onClick={() => save({ status: 'active' })}><Check />Approve</Button>
            : <Button type="submit" disabled={!ok || busy}>{busy ? <Loader2 className="animate-spin" /> : <Check />}{init.id ? 'Save' : 'Add'}</Button>}
        </div>
      </form>
    </DialogContent>
  </Dialog>
}

const Chip = ({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) =>
  <button type="button" onClick={onClick} aria-pressed={on}
    className={cn('inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-[13px] transition-colors', on ? 'border-fjord bg-fjord-soft text-fjord' : 'border-line text-ink-2 hover:border-line-strong')}>
    {on && <Check className="size-3.5" />}{children}</button>

/* ---------- one row ---------- */
function Row({ e, showScope = true }: { e: KEntry; showScope?: boolean }) {
  const { activeProjects, ax } = useApp()
  const [busy, setBusy] = useState(false)
  const names = scopeIds(e).map(id => ax.projects.find(p => p.id === id)).filter(Boolean)
  async function quick(p: object, msg: string) {
    setBusy(true)
    try { await ax.act('kb_update', { id: e.id, ...p }, []); await loadKnowledge(true); toast(msg) }
    catch (err: any) { toast.error('Failed: ' + err.message) } finally { setBusy(false) }
  }
  const src = e.sources?.[e.sources.length - 1]
  return <div className={cn('flex min-h-11 items-start gap-3 px-4 py-2.5', e.status === 'dismissed' && 'opacity-50')}>
    <KnowledgeIcon className={cn('mt-[3px] size-4 shrink-0', e.status === 'suggested' ? 'text-fjord' : 'text-ink-3')} />
    <div className="min-w-0 flex-1">
      <button onClick={() => openKnowledge(e)} className="block w-full text-left">
        <span className="block text-[15px] leading-snug hover:underline">{e.title}</span>
        <span className="text-ink-2 line-clamp-2 block text-[13px]">{e.body}</span>
      </button>
      {e.status === 'suggested' && <div className="text-ink-3 mt-0.5 text-[12px]">
        {e.learned && LEARNED[e.learned] ? 'Learned ' + LEARNED[e.learned] : 'Suggested'}{src?.label ? ' · ' + src.label : ''}{e.sources?.length > 1 ? ` · +${e.sources.length - 1} more` : ''}
        {e.from_others && <span className="text-ink-2"> · stated by {e.from_others}</span>}</div>}
      {e.status === 'active' && e.outdated && <div className="text-ink-2 mt-0.5 flex items-start gap-1.5 text-[13px]">
        <span className="ax-diamond text-dawn mt-[5px] shrink-0" style={{ width: 6, height: 6 }} />May be outdated: {e.outdated.reason}</div>}
      <span className="text-ink-3 mt-0.5 flex flex-wrap items-center gap-x-3 font-mono text-[12px]">
        {e.stale && <span className="text-ink-2 inline-flex items-center gap-1.5"><span className="ax-diamond text-dawn" style={{ width: 6, height: 6 }} />check date passed</span>}
        {showScope && (names.length ? names.map(p => <span key={p!.id} className="inline-flex items-center gap-1"><span className="ax-diamond" style={{ color: projColor(activeProjects, p!.id), width: 6, height: 6 }} />{p!.name}</span>) : <span>overall</span>)}
        <span>{e.visibility === 'private' ? 'only for you' : e.visibility === 'shareable' ? 'shareable in replies' : 'internal'}</span>
        <span>{CAT_LABEL[e.category]?.toLowerCase() || e.category}</span>
      </span>
      {ax.apiOk && e.status === 'suggested' && <div className="mt-2 flex flex-wrap gap-2">
        <Button size="pill" disabled={busy} onClick={() => quick({ status: 'active' }, 'Approved – drafts can use it from the next run')}><Check />Approve</Button>
        <Button size="pill" variant="outline" disabled={busy} onClick={() => openKnowledge(e)}><Pencil />Edit</Button>
        <Button size="pill" variant="ghost" disabled={busy} onClick={() => quick({ status: 'dismissed' }, 'Dismissed – Axella won\'t suggest it again')}>Dismiss</Button>
      </div>}
      {ax.apiOk && e.status === 'active' && e.outdated && <div className="mt-2 flex flex-wrap gap-2">
        <Button size="pill" variant="outline" disabled={busy} onClick={() => quick({ outdated: null }, 'Kept as it is')}><Check />Still correct</Button>
        <Button size="pill" variant="outline" disabled={busy} onClick={() => openKnowledge(e)}><Pencil />Update</Button>
      </div>}
    </div>
  </div>
}

/* ---------- the Knowledge page (overall) ---------- */
export function KnowledgeView() {
  const { ax, activeProjects } = useApp()
  const list = useKnowledge()
  const [q, setQ] = useState('')
  const [scope, setScope] = useState<string>('all')
  const [show, setShow] = useState<'active' | 'suggested' | 'check' | 'dismissed'>('active')
  const rows = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean)
    return (list || []).filter(e =>
      (show === 'check' ? needsCheck(e) : e.status === show)
      && (scope === 'all' || (scope === 'overall' ? !scopeIds(e).length : inProject(e, scope)))
      && words.every(w => (e.title + ' ' + e.body).toLowerCase().includes(w)))
  }, [list, q, scope, show])
  const n = (s: typeof show) => (list || []).filter(e => s === 'check' ? needsCheck(e) : e.status === s).length
  // open on the suggestions when there are some and nothing is in use yet
  const [picked, setPicked] = useState(false)
  useEffect(() => { if (!picked && list && !n('active') && n('suggested')) { setShow('suggested'); setPicked(true) } }, [list])
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1"><h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><KnowledgeIcon className="size-5" />Knowledge</h1>
          <p className="text-muted-foreground text-sm">Facts and answers Axella may build drafts on – overall or per project. Drafts show which entries they used.</p></div>
        {ax.apiOk && <Button onClick={() => openKnowledge({ scope: scope !== 'all' && scope !== 'overall' ? [scope] : 'overall' })}><Plus />Add</Button>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[12rem] flex-1 sm:max-w-sm">
          <Search className="text-ink-3 pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
          <Input value={q} onChange={e => setQ(e.target.value)} placeholder="Search knowledge…" className="pl-8" />
        </div>
        <NativeSelect value={scope} onChange={e => setScope(e.target.value)} className="w-auto" aria-label="Where">
          <option value="all">Everywhere</option><option value="overall">Overall only</option>
          {activeProjects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </NativeSelect>
        <div className="flex flex-wrap gap-1.5">
          {([['active', 'In use'], ['suggested', 'Suggested'], ['check', 'Check again'], ['dismissed', 'Dismissed']] as const).map(([k, l]) =>
            (k === 'active' || n(k) > 0) && <Chip key={k} on={show === k} onClick={() => { setShow(k); setPicked(true) }}>{l}{k !== 'active' && <span className="font-mono text-[12px]">{n(k)}</span>}</Chip>)}
        </div>
      </div>
      <div className="bg-card divide-y rounded-lg border">
        {!list ? <div className="text-ink-3 flex items-center gap-2 px-4 py-3.5 text-sm"><Loader2 className="size-4 animate-spin" />Loading…</div>
          : rows.length ? rows.map(e => <Row key={e.id} e={e} />)
          : <Empty>{q ? 'Nothing matches' : show === 'active' ? 'No entries yet – add the answers you give again and again' : 'Nothing here'}</Empty>}
      </div>
      {ax.apiOk && <LearningCard onReview={() => { setShow('suggested'); setPicked(true) }} />}
      <p className="text-ink-3 text-xs">Stored as files on the Mac mini (knowledge/entries). Suggestions are never used until you approve them. Coming next: imported documents, then web pages.</p>
    </div>
  )
}

/* ---------- the card on a project page ---------- */
export function KnowledgeCard({ project }: { project: { id: string; name: string } }) {
  const { ax, go } = useApp()
  const list = useKnowledge()
  const mine = (list || []).filter(e => e.status !== 'dismissed' && inProject(e, project.id))
  const overall = (list || []).filter(e => e.status === 'active' && !scopeIds(e).length).length
  return (
    <SectionCard id="pkb" icon={KnowledgeIcon} title="Knowledge" sub={`Facts drafts for ${project.name} may use${overall ? ` · plus ${overall} overall` : ''}`} count={mine.length || null}
      right={ax.apiOk && <Button size="pill" variant="outline" onClick={() => openKnowledge({ scope: [project.id] })}><Plus />Add</Button>}>
      {mine.length ? mine.map(e => <Row key={e.id} e={e} showScope={false} />) : <Empty>No entries for this project yet</Empty>}
      {overall > 0 && <button onClick={() => go({ kind: 'knowledge' })} className="text-ink-3 hover:text-ink flex w-full items-center gap-1.5 px-4 py-2.5 text-left text-[13px]">
        <KnowledgeIcon className="size-4" />All knowledge<span className="text-fjord ml-auto">Open</span></button>}
    </SectionCard>
  )
}

/* ---------- "based on" chips under a draft ---------- */
export function BasedOn({ ids }: { ids?: string[] }) {
  const list = useKnowledge()
  if (!ids?.length) return null
  const es = ids.map(id => list?.find(e => e.id === id))
  return <div className="text-ink-3 mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
    <KnowledgeIcon className="size-3.5" />Based on
    {es.map((e, i) => e
      ? <button key={e.id} onClick={() => openKnowledge(e)} className="text-ink-2 hover:border-line-strong rounded-sm border px-1.5 py-px">{e.title}</button>
      : <span key={ids[i]} className="rounded-sm border border-dashed px-1.5 py-px" title="This entry was deleted after the draft was written">deleted entry</span>)}
  </div>
}


