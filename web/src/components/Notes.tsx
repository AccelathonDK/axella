/* Notes (setup/notes.py): Axella's own notes – plain text, the first line is the title – linked to people, projects,
   trips, meeting preps and threads. The Notes page (Library), the editor any screen can open (openNote), the "Linked
   notes" card on a person, project, trip and prep, and the quiet "Your note" chip on an item when the person writes
   again. Owner only; nothing here goes to Claude except when Ask Axella reads a note (counted in What leaves my home). */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { BellRing, Check, ListTodo, Loader2, Pencil, PencilLine, Plus, Search as SearchIcon, Trash2, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input, NativeSelect } from '@/components/ui/input'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { LINK_LABEL, NOTE_EVENT, NOTES_CHANGED, notesChanged, openNote, useNotesOwner, type Chip, type LinkKind, type Note, type NoteLink } from '@/lib/notes'
import { cn } from '@/lib/utils'

export const NoteIcon = PencilLine
const when = (s?: string) => s ? new Date(s).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : ''
const URL_RE = /\bhttps?:\/\/[^\s<>"')\]]+/g

/** a note's text with its links clickable (plain text otherwise – never HTML) */
export function NoteText({ text }: { text: string }) {
  const parts: ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(URL_RE)) {
    parts.push(text.slice(last, m.index))
    parts.push(<a key={m.index} href={m[0]} target="_blank" rel="noopener noreferrer" className="text-fjord break-all underline-offset-2 hover:underline">{m[0]}</a>)
    last = (m.index || 0) + m[0].length
  }
  parts.push(text.slice(last))
  return <div className="whitespace-pre-wrap break-words">{parts}</div>
}

/* ---------- the editor (one host in the Shell) ---------- */
export function NoteHost() {
  const [o, setO] = useState<{ id?: string; links?: NoteLink[]; text?: string } | null>(null)
  useEffect(() => { const h = (e: Event) => setO((e as CustomEvent).detail || {}); addEventListener(NOTE_EVENT, h); return () => removeEventListener(NOTE_EVENT, h) }, [])
  return o ? <NoteEditor key={o.id || 'new'} init={o} onClose={() => setO(null)} /> : null
}

function NoteEditor({ init, onClose }: { init: { id?: string; links?: NoteLink[]; text?: string }; onClose: () => void }) {
  const { ax } = useApp()
  const [note, setNote] = useState<Note | null>(init.id ? null : { id: '', title: '', links: init.links || [], pinned: false, ctx: null, remind: false })
  const [text, setText] = useState(init.text || '')
  const [busy, setBusy] = useState<string | null>(null)
  const [armed, setArmed] = useState(false)
  const [preview, setPreview] = useState(!!init.id)
  const area = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    if (!init.id) return
    get<{ note: Note }>('note?id=' + encodeURIComponent(init.id)).then(j => { setNote(j.note); setText(j.note.text || '') })
      .catch(e => { toast.error(e.message); onClose() })
  }, [init.id])   // eslint-disable-line react-hooks/exhaustive-deps
  if (!note) return null
  const isNew = !note.id
  const canRemind = note.links.some(l => ['person', 'mail', 'chat', 'meeting', 'trip'].includes(l.kind))
  const remindLabel = note.links.some(l => ['person', 'mail', 'chat'].includes(l.kind)) ? 'Remind me when they write' : 'Remind me on the day'
  async function save(extra: Partial<Note> = {}, close = false) {
    if (!text.trim()) { toast.error('Write something first'); return null }
    setBusy('save')
    try {
      const r: any = await ax.act('note_save', { id: note!.id || undefined, text, links: note!.links, pinned: note!.pinned, ctx: note!.ctx, remind: note!.remind, ...extra }, [])
      const n: Note = r?.result
      if (n?.id) { setNote(n); notesChanged() }
      if (close) { toast(isNew ? 'Note saved' : 'Saved'); onClose() }
      return n
    } catch (e: any) { toast.error('Not saved: ' + e.message); return null } finally { setBusy(null) }
  }
  async function toTodo() {
    const el = area.current
    const sel = el && el.selectionStart !== el.selectionEnd ? text.slice(el.selectionStart, el.selectionEnd) : ''
    const n = note!.id ? note : await save()
    if (!n?.id) return
    setBusy('todo')
    try { await ax.act('note_todo', { id: n.id, text: sel.trim() || undefined }, ['tasks']); toast.success('Added to To do – linked to this note') }
    catch (e: any) { toast.error(e.message) } finally { setBusy(null) }
  }
  async function remove() {
    if (!armed) { setArmed(true); setTimeout(() => setArmed(false), 3000); return }
    setBusy('delete')
    try {
      const r: any = await ax.act('note_delete', { id: note!.id }, [])
      const backup = r?.result?.backup
      notesChanged(); onClose()
      toast('Note deleted', { duration: 6000, action: backup ? { label: 'Undo', onClick: () => {
        ax.act('note_restore', { backup }, []).then(() => { notesChanged(); toast('The note is back') }, (e: any) => toast.error(e.message)) } } : undefined,
        description: 'Restore from the Activity log for 90 days' })
    } catch (e: any) { toast.error(e.message); setBusy(null) }
  }
  const set = (p: Partial<Note>) => setNote(n => n && ({ ...n, ...p }))
  return <Dialog open onOpenChange={o => !o && onClose()}>
    <DialogContent className="sm:max-w-xl" data-note-editor="">
      <div className="space-y-3 px-5 py-4">
        <div className="flex items-center gap-2 pr-8">
          <NoteIcon className="text-fjord size-[18px]" />
          <DialogTitle className="flex-1 text-base font-semibold">{isNew ? 'New note' : note.title}</DialogTitle>
          {!isNew && <Button size="pill" variant="ghost" onClick={() => setPreview(p => !p)}>{preview ? <><Pencil />Edit</> : 'Done editing'}</Button>}
        </div>
        {preview && !isNew
          ? <div className="bg-bg-2/40 max-h-[50vh] min-h-24 overflow-y-auto rounded-md border px-3 py-2 text-[14.5px] leading-relaxed" onDoubleClick={() => setPreview(false)} data-note-preview=""><NoteText text={text} /></div>
          : <textarea ref={area} autoFocus value={text} onChange={e => setText(e.target.value)} rows={8} maxLength={20000} aria-label="Note"
              onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) save({}, true) }}
              placeholder={'The first line is the title\nThen anything you want to remember'}
              className="bg-card focus-visible:ring-fjord/40 w-full resize-y rounded-md border px-3 py-2 text-[15px] leading-relaxed outline-none focus-visible:ring-2" />}
        {note.links.length > 0 && <div className="flex flex-wrap gap-1.5" data-note-links="">
          {note.links.map(l => <span key={l.kind + l.ref} className="bg-bg-2 inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[12.5px]">
            <span className="text-ink-3">{LINK_LABEL[l.kind]}</span><span className="max-w-48 truncate">{l.label || l.ref}</span>
            <button type="button" aria-label={'Unlink ' + (l.label || l.ref)} className="text-ink-3 hover:text-ink" onClick={() => set({ links: note.links.filter(x => x !== l) })}><X className="size-3" /></button></span>)}
        </div>}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px]">
          <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={!!note.pinned} onChange={e => set({ pinned: e.target.checked })} />Pin</label>
          <label className="flex items-center gap-2">
            <NativeSelect value={note.ctx || ''} onChange={e => set({ ctx: (e.target.value || null) as Note['ctx'] })} aria-label="Work or Private" className="h-9 w-auto">
              <option value="">Work and Private</option><option value="work">Work</option><option value="private">Private</option></NativeSelect></label>
          {canRemind && <label className="flex min-h-9 items-center gap-2" data-note-remind=""><input type="checkbox" checked={!!note.remind} onChange={e => set({ remind: e.target.checked })} /><BellRing className="text-ink-3 size-4" />{remindLabel}</label>}
        </div>
        {canRemind && note.remind && <p className="text-ink-3 text-[12px]">A quiet chip on that item in Today – added on the Mac mini, never put in the digest or sent to Claude.</p>}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button size="pill" onClick={() => save({}, true)} disabled={!!busy || !text.trim()} data-note-save="">{busy === 'save' ? <Loader2 className="animate-spin" /> : <Check />}Save</Button>
          <Button size="pill" variant="outline" onClick={toTodo} disabled={!!busy || !text.trim()} title="The selected line, or the title" data-note-todo="">{busy === 'todo' ? <Loader2 className="animate-spin" /> : <ListTodo />}Make a To do</Button>
          <span className="flex-1" />
          {!isNew && <Button size="pill" variant="ghost" onClick={remove} disabled={busy === 'delete'} className={cn(armed && 'text-danger')} data-note-delete=""><Trash2 />{armed ? 'Tap again to delete' : 'Delete'}</Button>}
        </div>
      </div>
    </DialogContent>
  </Dialog>
}

/* ---------- a list of notes ---------- */
function useNotes(query: string) {
  const [list, setList] = useState<Note[] | null>(null)
  const load = useCallback(() => get<{ notes: Note[] }>('notes' + query).then(j => setList(j.notes || [])).catch(() => setList([])), [query])
  useEffect(() => { load(); addEventListener(NOTES_CHANGED, load); return () => removeEventListener(NOTES_CHANGED, load) }, [load])
  return list
}

function NoteRow({ n }: { n: Note }) {
  return <button type="button" onClick={() => openNote({ id: n.id })} className="hover:bg-bg-2/50 flex min-h-11 w-full items-start gap-3 px-4 py-2.5 text-left" data-note-row={n.id}>
    <NoteIcon className={cn('mt-0.5 size-4 shrink-0', n.pinned ? 'text-fjord' : 'text-ink-3')} />
    <span className="min-w-0 flex-1">
      <span className="block truncate text-[14.5px] font-medium">{n.title}</span>
      {n.snippet && <span className="text-ink-3 line-clamp-1 block text-[13px]">{n.snippet}</span>}
      <span className="text-ink-3 mt-0.5 flex flex-wrap gap-x-2 text-[12px]">
        {n.pinned && <span>Pinned</span>}{n.remind && <span className="inline-flex items-center gap-1"><BellRing className="size-3" />reminder</span>}
        {n.links.slice(0, 3).map(l => <span key={l.kind + l.ref}>{LINK_LABEL[l.kind]}: {l.label || l.ref}</span>)}
        {n.ctx && <span>{n.ctx === 'work' ? 'Work' : 'Private'}</span>}</span>
    </span>
    <span className="text-ink-3 shrink-0 font-mono text-[12px]">{when(n.updated)}</span>
  </button>
}

/* ---------- the Notes page ---------- */
export function NotesView() {
  const { ax } = useApp()
  const [q, setQ] = useState('')
  const [ctx, setCtx] = useState<'' | 'work' | 'private'>('')
  const [kind, setKind] = useState<'' | LinkKind | 'none'>('')
  const [debounced, setDebounced] = useState('')
  useEffect(() => { const t = setTimeout(() => setDebounced(q.trim()), 250); return () => clearTimeout(t) }, [q])
  const list = useNotes('?q=' + encodeURIComponent(debounced))
  const shown = useMemo(() => (list || []).filter(n => (!ctx || !n.ctx || n.ctx === ctx)
    && (!kind || (kind === 'none' ? !n.links.length : n.links.some(l => l.kind === kind)))), [list, ctx, kind])
  const owner = useNotesOwner(ax.apiOk)
  if (!ax.apiOk) return <div className="text-ink-3 text-sm">Notes need the Mac mini – it isn't answering right now.</div>
  if (owner === false) return <div className="text-ink-3 text-sm">Notes are the owner's own.</div>
  if (list === null || owner === null) return <div className="text-ink-3 text-sm">Loading…</div>
  return <div className="space-y-4" data-notes-view="">
    <div className="flex flex-wrap items-center gap-3">
      <h1 className="flex-1 text-[28px] leading-tight font-semibold tracking-[-0.02em]">Notes</h1>
      <Button size="pill" onClick={() => openNote({})} data-note-new=""><Plus />New note</Button>
    </div>
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-48 flex-1">
        <SearchIcon className="text-ink-3 pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
        <Input value={q} onChange={e => setQ(e.target.value)} placeholder="Search your notes" aria-label="Search your notes" className="h-10 pl-9" /></div>
      <NativeSelect value={ctx} onChange={e => setCtx(e.target.value as typeof ctx)} aria-label="Work or Private" className="h-10 w-auto">
        <option value="">Work and Private</option><option value="work">Work</option><option value="private">Private</option></NativeSelect>
      <NativeSelect value={kind} onChange={e => setKind(e.target.value as typeof kind)} aria-label="Linked to" className="h-10 w-auto">
        <option value="">Linked to anything</option>
        {(Object.keys(LINK_LABEL) as LinkKind[]).map(k => <option key={k} value={k}>{LINK_LABEL[k]}</option>)}
        <option value="none">Not linked</option></NativeSelect>
    </div>
    <Card className="divide-y overflow-hidden" data-notes-list="">
      {!shown.length ? <div className="text-ink-2 space-y-1 px-4 py-6 text-center text-sm">
        <p>{debounced || ctx || kind ? 'No notes match.' : 'No notes yet.'}</p>
        {!debounced && !ctx && !kind && <p className="text-ink-3 text-[13px]">Write one here, or with ⋯ → Note… on any message – it is linked to that person, and can remind you when they write again.</p>}
      </div> : shown.map(n => <NoteRow key={n.id} n={n} />)}
    </Card>
    <p className="text-ink-3 text-[12px]">Your notes stay on the Mac mini. Digests and drafts never read them; Ask Axella may when you ask it something – counted in Settings → Privacy → What leaves my home – but never one linked to a private contact.</p>
  </div>
}

/* ---------- "Linked notes" on a person, project, trip and meeting prep ---------- */
export function LinkedNotes({ link }: { link: NoteLink }) {
  const { ax } = useApp()
  const owner = useNotesOwner(ax.apiOk)
  const list = useNotes('?kind=' + link.kind + '&ref=' + encodeURIComponent(link.ref))
  if (!owner) return null
  return <Card className="overflow-hidden" data-linked-notes={link.kind}>
    <div className="flex items-center border-b px-4 py-2.5"><span className="ax-label">Linked notes</span>
      <Button size="pill" variant="ghost" className="text-fjord -mr-2 ml-auto h-7" onClick={() => openNote({ links: [link] })} data-linked-notes-add=""><Plus />Note</Button></div>
    {!list?.length ? <div className="text-ink-3 px-4 py-3 text-[13px]">No notes yet. + Note links one here.</div>
      : <div className="divide-y">{list.map(n => <NoteRow key={n.id} n={n} />)}</div>}
  </Card>
}

/* ---------- the quiet chip: "Your note: …" when the person writes again ---------- */
export function NoteChip({ chip, itemId }: { chip: Chip; itemId?: string }) {
  const { ax } = useApp()
  const [busy, setBusy] = useState(false)
  const act = async (a: 'done' | 'keep') => {
    setBusy(true)
    try {
      await ax.act(a === 'done' ? 'note_save' : 'note_keep', a === 'done' ? { id: chip.id, remind: false } : { id: chip.id, item_id: itemId }, [])
      notesChanged(); toast(a === 'done' ? 'Reminder off' : 'Kept – it shows again next time')
    } catch (e: any) { toast.error(e.message) } finally { setBusy(false) }
  }
  return <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[12.5px]" data-note-chip={chip.id}>
    <button type="button" onClick={() => openNote({ id: chip.id })} className="bg-fjord-soft text-fjord inline-flex max-w-full items-center gap-1 rounded-full px-2.5 py-0.5 font-medium hover:underline">
      <NoteIcon className="size-3.5 shrink-0" /><span className="truncate">Your note: {chip.title}</span>{chip.more > 0 && <span className="opacity-70">· and {chip.more} more</span>}</button>
    <button type="button" disabled={busy} onClick={() => act('done')} className="text-ink-3 hover:text-ink rounded px-1.5 py-0.5" data-note-chip-done="">Done</button>
    {itemId && <button type="button" disabled={busy} onClick={() => act('keep')} className="text-ink-3 hover:text-ink rounded px-1.5 py-0.5" data-note-chip-keep="">Keep</button>}
  </div>
}
