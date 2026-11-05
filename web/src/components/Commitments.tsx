/* Commitments and follow-through (feature pack Nov 2026 §1a/§1b): what you promised in your own messages, as cards
   you confirm into To do – and who you owe a reply. Found on the Mac mini by rules; nothing from private contacts.
   setup/commitments.py, axella-actions.py scan_commitments. */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Check, Loader2, Pencil, Plus, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { get, post } from '@/lib/api'
import { useApp } from '@/lib/app'

interface Promise_ {
  id: string; text: string; sentence: string; due?: string | null; world?: string; person: { name: string; address: string }
  source: { kind: string; account?: string; message_id?: string; subject?: string; chat?: string; at: string }; looks_done?: { at: string } | null; task_id?: string
}
interface Debt { who: string; name: string; channel: string; world: string; days: number; subject?: string; last_in: string }
// a name to show, never a full address (the service already sends one; an old cache may not)
const first = (d: Debt) => (d.name.includes('@') ? d.name.split('@')[0].replace(/[._-]+/g, ' ') : d.name).split(' ')[0]
interface View { promises: Promise_[]; looks_done: Promise_[]; reply_debt: Debt[]; scanned?: string; error?: string | null }

let cache: View | null = null
const subs = new Set<(v: View) => void>()
function load(fresh = false) {
  return get<View>('commitments' + (fresh ? '?fresh=1' : '')).then(v => { cache = v; subs.forEach(f => f(v)); return v })
}
function useCommitments() {
  const { ax } = useApp()
  const [v, setV] = useState<View | null>(cache)
  useEffect(() => { subs.add(setV); if (ax.apiOk) load().catch(() => {}); const t = setInterval(() => ax.apiOk && load().catch(() => {}), 10 * 60e3); return () => { subs.delete(setV); clearInterval(t) } }, [ax.apiOk])
  return v
}
const WHERE: Record<string, string> = { mail: 'mail', imessage: 'Messages', whatsapp: 'WhatsApp', signal: 'Signal' }
const dueLabel = (d?: string | null) => !d ? '' : new Date(d + 'T12:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })

/** Today / To do: promises to confirm, "looks done", and the reply-debt line. Hidden when there is nothing. */
export function CommitmentsCard({ ctxFilter = true }: { ctxFilter?: boolean }) {
  const { ax, ctx, go } = useApp()
  const v = useCommitments()
  const [edit, setEdit] = useState<{ id: string; text: string; due: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [allDebt, setAllDebt] = useState(false)
  if (!v || !ax.apiOk) return null
  const inCtx = (w?: string) => !ctxFilter || ctx === 'all' || !w || w === ctx
  const promises = v.promises.filter(p => inCtx(p.world))
  const done = v.looks_done.filter(p => inCtx(p.world))
  const debt = v.reply_debt.filter(d => inCtx(d.world))
  if (!promises.length && !done.length && !debt.length) return null
  async function act(action: string, body: Record<string, unknown>, msg: string) {
    setBusy(String(body.id || body.who))
    try { await post(action, body); await load(); if (action === 'promise_add' || action === 'promise_done') ax.refresh(['tasks']); toast(msg); setEdit(null) }
    catch (e: any) { toast.error(e.message) } finally { setBusy(null) }
  }
  // Done: answered elsewhere or nothing to answer – back only when they write again. Never: not for this person.
  async function debtAct(d: Debt, action: 'replydebt_done' | 'replydebt_never') {
    setBusy(d.who)
    try {
      await post(action, { who: d.who, last_in: d.last_in, title: d.name }); await load()
      toast(action === 'replydebt_done' ? `${first(d)}: done – back only if they write again` : `${d.name} won't show here again`, {
        action: { label: 'Undo', onClick: () => { post(action, { who: d.who, on: false, title: d.name }).then(() => load(true)).catch(e => toast.error(e.message)) } } })
    } catch (e: any) { toast.error(e.message) } finally { setBusy(null) }
  }
  return <Card className="overflow-hidden" data-commitments="">
    <div className="flex items-center border-b px-4 py-2.5"><span className="ax-label">Your promises and replies</span></div>
    <div className="divide-y">
      {debt.length > 0 && <div className="px-4 py-2.5 text-sm" data-reply-debt="">
        <span className="font-medium">You owe {debt.length} {debt.length === 1 ? 'reply' : 'replies'}: </span>
        {(allDebt ? debt : debt.slice(0, 6)).map((d, i, shown) => <span key={d.who} className="group" data-debt={d.who}>
          <button className="text-fjord hover:underline" title={d.subject ? 'Last: ' + d.subject : WHERE[d.channel]} onClick={() => go({ kind: 'search', q: d.channel === 'mail' ? d.who : d.name })}>{first(d)}</button>
          <span className="text-ink-3"> ({d.days} days{d.channel !== 'mail' ? ', ' + WHERE[d.channel] : ''}
            <DropdownMenu>
              <DropdownMenuTrigger disabled={busy === d.who} className="text-ink-3 hover:text-ink -my-1 ml-0.5 rounded-sm px-1 py-1 text-[11.5px]" aria-label={'Done or never for ' + d.name} title="Done, or never for this person">×</DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuItem onSelect={() => debtAct(d, 'replydebt_done')} data-debt-done=""><Check />Done – nothing to answer</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => debtAct(d, 'replydebt_never')}><X />Never for {first(d)}</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>)</span>{i < shown.length - 1 ? ', ' : ''}</span>)}
        {debt.length > 6 && !allDebt && <button className="text-ink-3 hover:text-ink" onClick={() => setAllDebt(true)}> and {debt.length - 6} more</button>}
      </div>}
      {done.map(p => <div key={p.id} className="flex flex-wrap items-center gap-2 px-4 py-2.5" data-looks-done="">
        <Check className="text-success size-4 shrink-0" />
        <span className="min-w-0 flex-1 text-sm">Looks done – tick it off? <span className="text-ink-2">{p.sentence}</span>
          <span className="text-ink-3 block text-[12.5px]">To {p.person.name} · you wrote again {dueLabel(p.looks_done!.at.slice(0, 10))}</span></span>
        <Button size="pill" disabled={!!busy} onClick={() => act('promise_done', { id: p.id, title: p.sentence }, 'Ticked off')}><Check />Tick off</Button>
        <Button size="pill" variant="ghost" disabled={!!busy} onClick={() => act('promise_not_done', { id: p.id }, 'Kept open')}>Not yet</Button>
      </div>)}
      {promises.map(p => <div key={p.id} className="space-y-1.5 px-4 py-2.5" data-promise="">
        <div className="text-sm">{p.text}{!p.sentence && p.source.message_id && <> · <a className="text-fjord hover:underline" href={'message://' + encodeURIComponent('<' + p.source.message_id + '>')}>Open in Mail</a></>}</div>
        <div className="text-ink-3 text-[12.5px]">{WHERE[p.source.kind] || p.source.kind}{p.source.subject ? ' · ' + p.source.subject : ''} · {dueLabel(p.source.at.slice(0, 10))}{p.due ? <> · <span className="text-ink-2 font-mono text-[12px]">due {dueLabel(p.due)}</span></> : ''}</div>
        {edit?.id === p.id ? <form className="flex flex-wrap gap-2" onSubmit={e => { e.preventDefault(); act('promise_add', { id: p.id, text: edit.text, due: edit.due || null }, 'Added to To do') }}>
            <Input autoFocus value={edit.text} maxLength={500} onChange={e => setEdit({ ...edit, text: e.target.value })} className="min-w-0 flex-1" aria-label="Task" />
            <Input type="date" value={edit.due} onChange={e => setEdit({ ...edit, due: e.target.value })} className="w-40" aria-label="Due" />
            <Button size="pill" type="submit" disabled={!!busy || !edit.text.trim()}><Plus />Add</Button>
            <Button size="pill" type="button" variant="ghost" onClick={() => setEdit(null)}>Cancel</Button>
          </form>
          : <div className="flex flex-wrap gap-1.5">
            <Button size="pill" disabled={!!busy} onClick={() => act('promise_add', { id: p.id }, 'Added to To do')}>{busy === p.id ? <Loader2 className="animate-spin" /> : <Plus />}Add to To do</Button>
            <Button size="pill" variant="outline" disabled={!!busy} onClick={() => setEdit({ id: p.id, text: taskText(p), due: p.due || '' })}><Pencil />Edit</Button>
            <Button size="pill" variant="ghost" disabled={!!busy} onClick={() => act('promise_dismiss', { id: p.id, title: p.sentence }, 'Okay – not a promise')}><X />Not a promise</Button>
          </div>}
      </div>)}
    </div>
  </Card>
}
/** The To do text Edit starts from: "Lee: send the revised quote" */
function taskText(p: Promise_) {
  if (!p.sentence) return `${p.person.name.split(' ')[0]}: follow up on your promise`
  const s = p.sentence.replace(/^(hi|hej|hello|thanks|tak)[^,.!]*[,.!]\s*/i, '')
    .replace(/^.*?\b(i'll|i will|i shall|i'm going to|let me|jeg|vi)\s+(skal |vil |kan |lige |also |just )?/i, '').replace(/[.!]+$/, '')
  return `${p.person.name.split(' ')[0]}: ${s.charAt(0).toLowerCase() + s.slice(1)}`.slice(0, 500)
}
