import { useState } from 'react'
import { toast } from 'sonner'
import { AlertTriangle, ChevronDown, FolderInput, Info, ShieldCheck } from '@/components/ax-icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useApp } from '@/lib/app'
import type { Item } from '@/lib/types'
import { cn } from '@/lib/utils'

/* The scam check (setup/safety.py, local rules on the Mac mini). Calm, never alarming: a quiet label, and on tap
   the concrete reasons. A flagged item gets no draft and no reply button, and Axella never opens or previews its links. */

export const isFlagged = (it: Item) => !!it.safety

/** The label in the row's meta line. */
export function SafetyBadge({ it }: { it: Item }) {
  if (!it.safety) return null
  return <Badge variant="outline" className="text-ink border-line-strong py-px font-medium" title="Flagged by Axella's scam check – open the item to see why">
    <AlertTriangle />{it.safety.label}</Badge>
}

/** "Why flagged": the signals, what Axella does with it, and the actions. */
export function SafetyNote({ it, open: start = false, className }: { it: Item; open?: boolean; className?: string }) {
  const { ax } = useApp()
  const [open, setOpen] = useState(start)
  const [busy, setBusy] = useState<string | null>(null)
  const [safe, setSafe] = useState(false)
  if (!it.safety || safe) return null
  const s = it.safety
  const sender = (it.from?.address || it.from?.number || '').trim()
  const isMail = it.channel === 'mail' && !!it.message_id && !!it.account
  const isText = ['sms', 'imessage', 'messages'].includes(it.channel || '')
  const live = ax.apiOk && !it.readonly
  const act = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key)
    try { await fn(); toast(ok) } catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(null) }
  }
  return (
    <div className={cn('bg-bg-2 rounded-md px-3 py-2 text-[13.5px]', className)} data-safety={s.level}>
      <button type="button" className="text-ink flex w-full items-center gap-2 text-left font-medium" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        <AlertTriangle className="size-4 shrink-0" />
        <span className="flex-1">{s.level === 'scam' ? 'Possible scam – held by Axella' : 'Check before you click'}</span>
        <span className="text-ink-3 text-[12px] font-normal">Why flagged</span>
        <ChevronDown className={cn('text-ink-3 size-4 transition-transform', open && 'rotate-180')} />
      </button>
      {open && <div className="mt-2">
        <ul className="text-ink-2 list-disc space-y-0.5 pl-5">{s.signals.map(x => <li key={x.code}>{x.text}</li>)}</ul>
        <div className="text-ink-3 mt-2 flex items-start gap-1.5 text-[12.5px]"><Info className="mt-0.5 size-3.5 shrink-0" />
          <span>Axella never treats it as urgent, wrote no reply{s.draft_removed ? ' (it removed the draft)' : ''}, and never opens or previews its links. If you weren't expecting it, don't click – go to the sender's own site or app instead.</span></div>
        {live && <div className="mt-2.5 flex flex-wrap gap-1.5">
          {isMail && <Button size="pill" variant="outline" disabled={!!busy} onClick={() => act('junk', () => ax.act('file', { item_id: it.id, account: it.account, message_id: it.message_id, folder: 'Junk',
            from: null, title: it.headline || '' }, ['state']), 'Moved to Junk in Mail')}><FolderInput />Move to Junk</Button>}
          {isText && <Button size="pill" variant="outline" onClick={() => toast('Block the number on your iPhone', {
            description: 'In Messages, open the conversation, tap the number at the top, then Info → Block Caller. “Report Junk” under the message also tells Apple.', duration: 15000 })}>
            <Info />Block number</Button>}
          {sender && <Button size="pill" variant="outline" disabled={!!busy} onClick={() => act('safe', async () => {
            await ax.act('safety_mark_safe', { sender, title: it.from?.name || sender }, []); setSafe(true)
          }, 'Marked safe – this sender is not flagged again')}><ShieldCheck />Mark safe</Button>}
        </div>}
      </div>}
    </div>
  )
}
