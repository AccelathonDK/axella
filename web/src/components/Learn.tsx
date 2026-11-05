/* Teach Axella (setup/learned.py): feedback on an item ("Not important", "This should have reached me") with a reason,
   the one suggestion card found from your habits (Today and the week wrap – at most one at a time, 3 a week), and
   Settings → Rules → Learned from you. Rules are made only on a tap, listed in plain words, and can be undone.
   Rules only, on the Mac mini – no Claude. */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { BellOff, Check, FolderInput, Inbox, Loader2, Sparkles, Star, Trash2, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { SectionCard } from '@/components/Section'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import type { Item } from '@/lib/types'
import { cn } from '@/lib/utils'

export interface Rule { id: string; kind: 'section' | 'hold' | 'vip' | 'file'; text: string; why?: string; at?: string; source?: string }
export interface Suggestion { key: string; text: string }
interface LearnData { rules: Rule[]; suggestion: Suggestion | null }

/* one fetch for every card on the page; a change anywhere tells the others (event "ax-learn") */
let cache: LearnData | null = null, inflight: Promise<LearnData | null> | null = null
function loadLearn(): Promise<LearnData | null> {         // every mount asks again (shows the last answer meanwhile)
  if (inflight) return inflight
  inflight = get<LearnData>('learn').then(j => (cache = { rules: Array.isArray(j.rules) ? j.rules : [], suggestion: j.suggestion || null }))
    .catch(() => (cache = null)).finally(() => { inflight = null })
  return inflight
}
const changed = () => { cache = null; window.dispatchEvent(new Event('ax-learn')) }
export function useLearn(): LearnData | null {
  const { ax } = useApp()
  const [d, setD] = useState<LearnData | null>(cache)
  useEffect(() => {
    if (!ax.apiOk) return
    let live = true
    const h = () => { inflight = null; loadLearn().then(x => live && setD(x)) }
    loadLearn().then(x => live && setD(x))
    window.addEventListener('ax-learn', h)
    return () => { live = false; window.removeEventListener('ax-learn', h) }
  }, [ax.apiOk])
  return d
}

const STOP = new Set(['the', 'and', 'for', 'you', 'your', 'with', 'from', 'this', 'that', 'are', 'was', 'have', 'has', 'not', 'new',
  'fwd', 'our', 'about', 'will', 'can', 'just', 'now', 'today', 'week', 'please', 'reminder', 'update'])
/** the longest word of the subject that isn't a filler – a start for "this kind of mail" (same as learned.topic_guess) */
export function topicGuess(s?: string) {
  const w = (s || '').replace(/^\s*(re|fwd?|sv|aw|vs)\s*:\s*/gi, '').match(/\p{L}[\p{L}\p{N}'&-]{2,30}/gu) || []
  const ok = w.filter(x => !STOP.has(x.toLowerCase()) && !/\d/.test(x[0]))
  return ok.length ? ok.reduce((a, b) => (b.length > a.length ? b : a)).toLowerCase() : ''
}

/* ---------- 1. feedback on an item ---------- */
type What = 'not_important' | 'reached'
export function TeachSheet({ it, what, onClose }: { it: Item; what: What; onClose: () => void }) {
  const { ax } = useApp()
  const addr = (it.from?.address || '').trim().toLowerCase()
  const hasAddr = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(addr)
  const name = it.from?.name || addr
  const [why, setWhy] = useState<'sender' | 'topic' | 'once'>(hasAddr ? 'sender' : 'once')
  const [topic, setTopic] = useState(() => topicGuess(it.subject || it.headline))
  const [level, setLevel] = useState<'answer' | 'urgent'>('answer')
  const [busy, setBusy] = useState(false)
  const topicOk = /^[\p{L}\p{N}][\p{L}\p{N}_ .'&-]{1,38}[\p{L}\p{N}]$/u.test(topic.trim())
  async function save() {
    setBusy(true)
    try {
      const body = { item_id: it.id, why, title: it.headline || it.subject || '', address: hasAddr ? addr : '', name: it.from?.name || '',
        topic: topic.trim(), level }
      const r: any = await ax.act(what === 'not_important' ? 'teach_not_important' : 'should_have_reached', body, [])
      const rule: Rule | null = r?.result?.rule || null
      if (rule) { toast.success('Rule made: ' + rule.text, { description: 'Settings → Rules lists it – undo it there any time.' }); changed() }
      else toast(what === 'not_important' ? 'Moved to FYI – just this once' : 'Noted – it counts under “Nothing missed” in Insights')
      if (what === 'not_important' || rule) ax.reload()
      onClose()
    } catch (e: any) { toast.error('Not saved: ' + e.message) } finally { setBusy(false) }
  }
  const Opt = ({ v, title, sub, disabled }: { v: typeof why; title: string; sub?: string; disabled?: boolean }) =>
    <button type="button" disabled={disabled} onClick={() => setWhy(v)} aria-pressed={why === v} data-teach-why={v}
      className={cn('flex min-h-11 w-full items-start gap-3 rounded-md border px-3 py-2.5 text-left disabled:opacity-40',
        why === v ? 'border-fjord bg-fjord-soft/40' : 'hover:border-line-strong')}>
      <span className={cn('mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border', why === v && 'border-fjord bg-fjord text-on-fjord')}>{why === v && <Check className="size-3" />}</span>
      <span className="min-w-0"><span className="block text-[14.5px] font-medium">{title}</span>{sub && <span className="text-ink-3 block text-[12.5px]">{sub}</span>}</span>
    </button>
  return <Dialog open onOpenChange={o => !o && onClose()}>
    <DialogContent className="sm:max-w-md" data-teach={what}>
      <div className="space-y-3 px-5 py-4">
        <DialogTitle className="text-base font-semibold">{what === 'not_important' ? 'Not important – why?' : 'Should have reached you – why?'}</DialogTitle>
        <p className="text-ink-2 text-[13px]">{what === 'not_important' ? 'Axella puts it under FYI. Tell it what to learn:' : 'Axella raises it next time. Tell it what to learn:'}</p>
        <div className="space-y-2">
          <Opt v="sender" title={`This sender – ${name}`} sub={hasAddr ? addr : 'No sender address on this item'} disabled={!hasAddr} />
          <Opt v="topic" title="This kind of mail" sub="Mail with this word in the subject" />
          {why === 'topic' && <Input value={topic} onChange={e => setTopic(e.target.value)} aria-label="Topic word" placeholder="e.g. newsletter" className="ml-7 w-[calc(100%-1.75rem)]" />}
          <Opt v="once" title="Just this once" sub={what === 'not_important' ? 'Only this item moves to FYI – no rule' : 'Only counted – no rule'} />
        </div>
        {what === 'reached' && why !== 'once' && <div className="flex flex-wrap gap-2 pt-1" data-teach-level="">
          {(['answer', 'urgent'] as const).map(l => <Button key={l} size="pill" variant={level === l ? 'default' : 'outline'} onClick={() => setLevel(l)}>
            {l === 'answer' ? 'To answer' : 'Always urgent'}</Button>)}
        </div>}
        <div className="flex justify-end gap-2 pt-2">
          <Button size="pill" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button size="pill" onClick={save} disabled={busy || (why === 'topic' && !topicOk)} data-teach-save="">{busy ? <Loader2 className="animate-spin" /> : <Check />}Save</Button>
        </div>
      </div>
    </DialogContent>
  </Dialog>
}

/* ---------- 2. the one suggestion (Today, the week wrap) ---------- */
export function SuggestionCard({ inWrap }: { inWrap?: boolean }) {
  const { ax } = useApp()
  const d = useLearn()
  const [busy, setBusy] = useState<string | null>(null)
  const s = d?.suggestion
  if (!s || !ax.apiOk) return null
  async function answer(a: 'accept' | 'later' | 'never') {
    setBusy(a)
    try {
      const r: any = await ax.act('suggest_' + a, { key: s!.key, title: s!.text }, [])
      toast(a === 'accept' ? (r?.result?.message || 'Rule made') + ' – undo it in Settings → Rules' : r?.result?.message || 'OK')
      changed(); if (a === 'accept') ax.reload()
    } catch (e: any) { toast.error(e.message); changed() } finally { setBusy(null) }
  }
  const body = <div className="flex items-start gap-3">
    <span className="bg-fjord-soft text-fjord flex size-9 shrink-0 items-center justify-center rounded-md"><Sparkles className="size-[18px]" /></span>
    <div className="min-w-0 flex-1">
      <div className="ax-label">Axella noticed</div>
      <div className="mt-0.5 text-[15px] leading-snug">{s.text}</div>
      <div className="mt-2.5 flex flex-wrap gap-2">
        <Button size="pill" onClick={() => answer('accept')} disabled={!!busy} data-suggest="accept">{busy === 'accept' ? <Loader2 className="animate-spin" /> : <Check />}Make it a rule</Button>
        <Button size="pill" variant="outline" onClick={() => answer('later')} disabled={!!busy} data-suggest="later">Not now</Button>
        <Button size="pill" variant="ghost" onClick={() => answer('never')} disabled={!!busy} data-suggest="never"><X />Never suggest this</Button>
      </div>
    </div>
  </div>
  return inWrap ? <div className="border-t pt-3" data-suggestion="">{body}</div> : <Card className="p-4" data-suggestion="">{body}</Card>
}

/* ---------- 3. Settings → Rules ---------- */
const KIND_ICON = { section: Inbox, hold: BellOff, vip: Star, file: FolderInput }
export function RulesCard() {
  const { ax } = useApp()
  const d = useLearn()
  const [busy, setBusy] = useState<string | null>(null)
  async function remove(r: Rule) {
    setBusy(r.id)
    try {
      await ax.act('rule_remove', { id: r.id, title: r.text }, [])
      changed()
      toast('Removed: ' + r.text, { duration: 10000, action: { label: 'Undo', onClick: () => {
        ax.act('rule_restore', { id: r.id, title: r.text }, []).then(() => { changed(); toast('Back: ' + r.text) }, (e: any) => toast.error(e.message)) } } })
    } catch (e: any) { toast.error(e.message) } finally { setBusy(null) }
  }
  if (!d) return null
  const when = (s?: string) => s ? new Date(s).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : ''
  return <SectionCard id="learned" icon={Sparkles} title="Learned from you" sub="Made on your tap – never by itself" count={d.rules.length}>
    <div className="divide-y" data-rules="">
      {!d.rules.length && <div className="text-ink-2 space-y-1 px-4 py-3 text-sm">
        <p>No rules yet.</p>
        <p className="text-ink-3 text-[13px]">Tap ⋯ on an item → <b>Not important</b> or <b>This should have reached me</b>, and say why. Axella also suggests a rule now and then from what you always do – one card at a time, on Today.</p></div>}
      {d.rules.map(r => {
        const I = KIND_ICON[r.kind] || Check
        return <div key={r.id} className="flex min-h-11 items-center gap-3 px-4 py-2.5" data-rule={r.kind}>
          <I className="text-ink-3 size-4 shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="text-[14.5px]">{r.text}</div>
            <div className="text-ink-3 text-[12.5px]">{[r.why, when(r.at)].filter(Boolean).join(' · ')}</div>
          </div>
          <Button size="pill" variant="ghost" onClick={() => remove(r)} disabled={busy === r.id} aria-label={'Remove ' + r.text}>
            {busy === r.id ? <Loader2 className="animate-spin" /> : <Trash2 />}<span className="max-[420px]:hidden">Remove</span></Button>
        </div>
      })}
    </div>
    <div className="text-ink-3 border-t px-4 py-2.5 text-[12.5px]">Your own settings always win: VIPs, private contacts, protected workplaces and the scam check. A rule never makes something private readable.</div>
  </SectionCard>
}
