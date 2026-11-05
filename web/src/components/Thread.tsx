import { useState } from 'react'
import { toast } from 'sonner'
import { Check, ChevronRight, ExternalLink, FolderInput, Loader2, MoreHorizontal, Trash2 } from '@/components/ax-icons'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Button } from '@/components/ui/button'
import { FolderPicker, ItemRow } from '@/components/ItemRow'
import { useApp } from '@/lib/app'
import { ctxOf } from '@/lib/data'
import { accLabel } from '@/lib/profile'
import { projColor } from '@/lib/projects'
import { mdInline } from '@/lib/md'
import { ITEM_ICON } from '@/lib/sections'
import type { Item } from '@/lib/types'
import { IOS, cn } from '@/lib/utils'

/* Filing per thread: mails of the same conversation (same account + subject without Re:/Fwd:/AW:/SV: … prefixes) are
   one row – "Move thread to …" files every mail in it; expand to see or file them one by one. */
const PREFIX = /^\s*((re|fw|fwd|aw|sv|vs|wg|tr|antw|ref|r)\s*(\[\d+\])?\s*:\s*|\[(ext|external|extern)\]\s*)/i
export function threadKey(i: Item) {
  let s = (i.subject || '').trim()
  for (let n = 0; n < 10 && PREFIX.test(s); n++) s = s.replace(PREFIX, '')
  s = s.replace(/\s+/g, ' ').toLowerCase()
  return s && i.channel === 'mail' ? `${i.account || ''}|${s}` : 'one:' + i.id
}
export function groupThreads(items: Item[]) {
  const map = new Map<string, Item[]>()
  items.forEach(i => { const k = threadKey(i); map.set(k, [...(map.get(k) || []), i]) })
  return [...map.values()]
}
// the digest writes "(21 Oct 12:54, answered)" at the end of a headline – the thread row drops it
const bare = (h?: string) => (h || '').replace(/\s*\([^()]*\)\s*$/, '')

export function ThreadRow({ items }: { items: Item[] }) {
  const { ax, go, projectsFor, activeProjects } = useApp()
  const [open, setOpen] = useState(false)
  const [pick, setPick] = useState(false)
  const [busy, setBusy] = useState(false)
  const [armed, setArmed] = useState(false)
  const it = items[0]
  const Icon = ITEM_ICON[it.section]
  const world = ctxOf(it, ax.overrides)
  const projects = [...new Map(items.flatMap(i => projectsFor(i)).map(p => [p.id, p])).values()]
  const people = [...new Set(items.map(i => i.from?.name).filter(Boolean))]
  const canFile = ax.apiOk && items.every(i => i.message_id && i.account)
  async function fileAll(folder: string) {
    setBusy(true); let ok = 0
    for (const i of items) {
      try { await ax.act('file', { item_id: i.id, account: i.account, message_id: i.message_id, folder, suggested: i.file_to, from: i.from?.address || null, title: i.headline || '' }, []); ok++ } catch { /* next */ }
    }
    await ax.refresh(['state']); setBusy(false); setPick(false)
    ok === items.length ? toast(`Moved the thread (${ok} mails) to ${folder}`) : toast.error(`Moved ${ok} of ${items.length} to ${folder}`)
  }
  // the same as ⋯ on a single mail, for every mail in the thread
  async function each(action: string, body: (i: Item) => object, done: string) {
    setBusy(true); let ok = 0
    for (const i of items) { try { await ax.act(action, body(i), []); ok++ } catch { /* next */ } }
    await ax.refresh(['state']); setBusy(false)
    ok === items.length ? toast(done) : toast.error(`Only ${ok} of ${items.length} mails – try the rest one by one`)
  }
  const latest = items.reduce((a, b) => ((b.date || '') > (a.date || '') ? b : a), it)
  return (
    <div data-thread="">
      <div className="bg-card flex gap-3 px-4 py-3">
        <div className={cn('flex size-9 shrink-0 items-center justify-center rounded-md', world === 'work' ? 'bg-work-soft text-work' : 'bg-private-soft text-private')}>
          <Icon className="size-[18px]" /></div>
        <div className="min-w-0 flex-1">
          <button className="flex w-full items-start gap-1.5 text-left font-semibold leading-snug" onClick={() => setOpen(!open)} aria-expanded={open}>
            <span className="md-inline min-w-0 flex-1" dangerouslySetInnerHTML={{ __html: mdInline(bare(it.headline) || it.subject || 'Thread') }} />
            <ChevronRight className={cn('text-ink-3 mt-0.5 size-4 shrink-0 transition-transform duration-[220ms]', open && 'rotate-90')} />
          </button>
          <div className="text-muted-foreground mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
            <span className="text-ink-2 font-mono">{items.length} mails</span>
            <span>{[people.slice(0, 2).join(', ') + (people.length > 2 ? ` +${people.length - 2}` : ''), accLabel(it.account)].filter(Boolean).join(' · ')}</span>
            {projects.map(p => <button key={p.id} onClick={() => go({ kind: 'project', id: p.id })}
              className="text-ink-2 hover:border-line-strong inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-px font-mono text-[11px]">
              <span className="ax-diamond" style={{ color: projColor(activeProjects, p.id), width: 6, height: 6 }} />#{p.tag}</button>)}
          </div>
          {canFile && !pick && <div className="mt-2.5 flex flex-wrap items-center gap-2">
            {it.file_to && <Button size="pill" disabled={busy} onClick={() => fileAll(it.file_to!)}>{busy ? <Loader2 className="animate-spin" /> : <FolderInput />}Move thread to {it.file_to}</Button>}
            <Button size="pill" variant="outline" disabled={busy} onClick={() => setPick(true)}><FolderInput />Other folder</Button>
            <DropdownMenu onOpenChange={o => !o && setArmed(false)}>
              <DropdownMenuTrigger asChild><Button size="icon-pill" variant="outline" className="ml-auto" aria-label="More actions" disabled={busy}><MoreHorizontal /></Button></DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => setOpen(!open)}><ChevronRight />{open ? 'Hide the mails' : `Show the ${items.length} mails`}</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => each('done', i => ({ item_id: i.id, title: i.headline || '' }), `Marked ${items.length} mails as done`)}><Check />Mark all as done</DropdownMenuItem>
                {latest.deep_link && !IOS && <DropdownMenuItem asChild><a href={latest.deep_link}><ExternalLink />Open in Mail</a></DropdownMenuItem>}
                <DropdownMenuSeparator />
                <DropdownMenuItem destructive onSelect={e => {
                  if (!armed) { e.preventDefault(); setArmed(true); setTimeout(() => setArmed(false), 3000); return }
                  each('trash', i => ({ item_id: i.id, account: i.account, message_id: i.message_id }), `Moved ${items.length} mails to Trash – recoverable in Mail`)
                }}><Trash2 />{armed ? `Tap again to delete ${items.length} mails` : 'Delete the thread'}</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>}
          {pick && <FolderPicker it={it} busy={busy} onCancel={() => setPick(false)} onMove={fileAll} />}
        </div>
      </div>
      {open && <div className="ax-reveal bg-bg-2/40 divide-y border-t pl-6">{items.map(i => <ItemRow key={i.id} it={i} />)}</div>}
    </div>
  )
}
