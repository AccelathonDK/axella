import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Check, ChevronRight, Loader2, Plus, X, axi } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { openCompose } from '@/components/Compose'
import { get, post } from '@/lib/api'
import { useApp } from '@/lib/app'
import { loadKnowledge, openKnowledge, useKnowledge } from '@/lib/knowledge'
import { loadReminders } from '@/lib/reminders'
import { mdInline } from '@/lib/md'
import { cn } from '@/lib/utils'

/* Ask Axella (roadmap: chat with Axella, v1). A question goes to the Mac mini, a short read-only Claude run answers from the
   digests, tasks, knowledge and – if needed – mail (setup/local-tasks/ask.md). Anything that would change something comes
   back as a card; nothing happens until the owner taps "Do it". */
export const AskIcon = axi('message')

interface Source { kind: string; label: string; digest?: string; id?: string }
interface Step { action: string; label?: string; payload: Record<string, any> }
interface Card { title: string; steps: Step[] }
interface Result { answer: string; sources?: Source[]; actions?: Card[]; followups?: string[] }
type Status = { state: 'queued'; position: number; waiting_for?: string | null } | { state: 'running' } | { state: 'failed'; error: string } | { state: 'done'; result: Result } | { state: 'unknown' }
interface Turn { q: string; id?: string; result?: Result; error?: string; done?: Record<number, 'done' | 'skipped' | 'failed'> }

/* The only actions a card may run, and what to refresh afterwards. Everything else is refused here (and by the server). */
const ALLOWED: Record<string, { refresh: any[]; ok: string; after?: () => void }> = {
  done: { refresh: ['state'], ok: 'Marked as done' },
  snooze: { refresh: ['state'], ok: 'Snoozed' },
  file: { refresh: ['state'], ok: 'Moved' },
  task_add: { refresh: ['tasks'], ok: 'Task added' },
  reminder_add: { refresh: ['tasks'], ok: 'Reminder set', after: () => { loadReminders(true) } },
  kb_add: { refresh: [], ok: 'Saved to knowledge – under Suggested, for you to approve', after: () => { loadKnowledge(true) } },
  project_item_add: { refresh: ['projects'], ok: 'Added to project' },
}
const cardOk = (c: Card) => Array.isArray(c.steps) && c.steps.length > 0 && c.steps.length <= 10 &&
  (c.steps.every(s => s && ALLOWED[s.action] && typeof s.payload === 'object') || (c.steps.length === 1 && c.steps[0]?.action === 'compose'))

let thread: Turn[] = []                    // survives closing the panel; "New chat" clears it
export const openAsk = (q?: string) => window.dispatchEvent(new CustomEvent('ax-ask', { detail: q || '' }))

export function AskHost() {
  const [open, setOpen] = useState(false)
  const [seed, setSeed] = useState('')
  useEffect(() => { const h = (e: Event) => { setSeed((e as CustomEvent).detail || ''); setOpen(true) }; window.addEventListener('ax-ask', h); return () => window.removeEventListener('ax-ask', h) }, [])
  useEffect(() => { if (!open) return; const k = (e: KeyboardEvent) => e.key === 'Escape' && !document.querySelector('[role=dialog]') && setOpen(false); addEventListener('keydown', k); return () => removeEventListener('keydown', k) }, [open])
  return open ? <Panel seed={seed} onClose={() => setOpen(false)} /> : null
}

const EXAMPLES = ['What is still open from this week?', 'Did anyone reply to the mails I sent yesterday?', 'What do I need to do for my projects this week?', 'Snooze all LinkedIn notifications until Monday']

function Panel({ seed, onClose }: { seed: string; onClose: () => void }) {
  const { ax, view, ctx } = useApp()
  const [turns, setTurns] = useState<Turn[]>(thread)
  const [text, setText] = useState(seed)
  const [st, setSt] = useState<Status | null>(null)
  const [since, setSince] = useState(0)
  const [, tick] = useState(0)
  const box = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const alive = useRef(true)
  useEffect(() => () => { alive.current = false }, [])
  useEffect(() => { thread = turns; box.current?.scrollTo({ top: box.current.scrollHeight, behavior: 'smooth' }) }, [turns, st])
  useEffect(() => { input.current?.focus() }, [])
  const busy = turns.some(t => t.id && !t.result && !t.error)

  async function ask(q: string) {
    q = q.trim()
    if (!q || busy) return
    const history = turns.filter(t => t.result).slice(-6).map(t => ({ q: t.q, a: t.result!.answer }))
    const context = { view: view.kind, project: view.kind === 'project' ? view.id : '', digest: ax.current?.name || '', filter: ctx }
    setTurns(t => [...t, { q }]); setText('')
    try {
      const r = await post<{ result: { id: string } }>('ask', { question: q, history, context })
      const id = r.result.id
      setTurns(t => t.map((x, i) => i === t.length - 1 ? { ...x, id } : x))
      setSince(Date.now()); setSt({ state: 'queued', position: 0 })
      const timer = setInterval(() => tick(n => n + 1), 1000)
      try {
        for (let i = 0; i < 200 && alive.current; i++) {
          await new Promise(res => setTimeout(res, i ? 2000 : 1200))
          const s = await get<Status>('ask?id=' + id).catch(() => null)
          if (!s) continue
          setSt(s)
          if (s.state === 'done' || s.state === 'failed') {
            setTurns(t => t.map(x => x.id === id ? (s.state === 'done' ? { ...x, result: s.result, done: {} } : { ...x, error: s.error }) : x))
            return
          }
        }
        setTurns(t => t.map(x => x.id === id && !x.result ? { ...x, error: 'No answer – see Runs for what happened' } : x))
      } finally { clearInterval(timer) }
    } catch (e: any) {
      setTurns(t => t.map((x, i) => i === t.length - 1 && !x.id ? { ...x, error: e.message } : x))
    }
  }

  async function run(ti: number, ci: number, card: Card) {
    const mark = (v: 'done' | 'skipped' | 'failed') => setTurns(t => t.map((x, i) => i === ti ? { ...x, done: { ...x.done, [ci]: v } } : x))
    if (card.steps.length === 1 && card.steps[0].action === 'compose') {
      const p = card.steps[0].payload || {}
      openCompose({ to: String(p.to || ''), topic: String(p.topic || ''), target: String(p.target || ''), notes: String(p.notes || ''), account: p.account ? String(p.account) : undefined })
      mark('done'); return
    }
    let ok = 0, fail = ''
    for (const s of card.steps) {
      const a = ALLOWED[s.action]
      if (!a) { fail = 'not allowed: ' + s.action; break }
      // knowledge from an answer is a suggestion, approved like the harvest's – never active straight away
      const payload = s.action === 'kb_add' ? { ...s.payload, status: 'suggested' } : s.payload
      try { await ax.act(s.action, payload, a.refresh); ok++ } catch (e: any) { fail = e.message; break }
    }
    card.steps.forEach(s => ALLOWED[s.action]?.after?.())
    if (fail) { toast.error(`Done ${ok} of ${card.steps.length} – ${fail}`); mark(ok ? 'done' : 'failed') }
    else { toast(card.steps.length > 1 ? `${card.title} – done` : ALLOWED[card.steps[0].action].ok); mark('done') }
  }

  const secs = since ? Math.round((Date.now() - since) / 1000) : 0
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button aria-label="Close" className="absolute inset-0 hidden bg-[var(--ax-scrim)] max-lg:block" onClick={onClose} />
      <section role="complementary" aria-label="Ask Axella"
        className="bg-bg relative flex h-full w-full flex-col border-l shadow-float sm:max-w-[440px] ax-reveal">
        <header className="pt-safe flex items-center gap-3 border-b px-4 py-3">
          <span className="bg-surface-inverse text-on-inverse flex size-9 shrink-0 items-center justify-center rounded-md"><AskIcon className="size-[18px]" /></span>
          <div className="min-w-0 flex-1"><div className="font-semibold leading-tight">Ask Axella</div>
            <div className="text-ink-3 text-xs leading-snug">From your digests, tasks, knowledge and mail · nothing changes without your tap</div></div>
          {turns.length > 0 && <Button size="pill" variant="ghost" disabled={busy} onClick={() => { setTurns([]); thread = []; setSt(null); input.current?.focus() }} title="Start a new chat"><Plus />New</Button>}
          <button aria-label="Close" onClick={onClose} className="text-ink-3 hover:text-ink flex size-9 items-center justify-center rounded-md"><X className="size-5" /></button>
        </header>

        <div ref={box} className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
          {!turns.length && <div className="space-y-3 pt-2">
            <p className="text-ink-2 text-sm">Ask about anything in your mail, messages, tasks and projects – or tell Axella what to do. Answers take 10–40 seconds; Axella works on the Mac mini.</p>
            <div className="space-y-1.5">{EXAMPLES.map(e => <button key={e} onClick={() => ask(e)}
              className="bg-card hover:border-line-strong flex w-full items-center gap-2 rounded-md border px-3 py-2.5 text-left text-sm transition-colors">
              <span className="min-w-0 flex-1">{e}</span><ChevronRight className="text-ink-3 size-4" /></button>)}</div>
          </div>}
          {turns.map((t, ti) => <div key={ti} className="space-y-2">
            <div className="flex justify-end"><div className="bg-surface-inverse text-on-inverse max-w-[85%] rounded-lg rounded-br-sm px-3 py-2 text-[15px] whitespace-pre-wrap">{t.q}</div></div>
            {t.error ? <div className="text-danger text-sm">Couldn't answer: {t.error}</div>
              : !t.result ? <Waiting st={st} secs={secs} />
              : <Answer r={t.result} done={t.done || {}} onRun={(ci, c) => run(ti, ci, c)} onSkip={ci => setTurns(x => x.map((y, i) => i === ti ? { ...y, done: { ...y.done, [ci]: 'skipped' } } : y))}
                  onFollow={q => ask(q)} canFollow={!busy && ti === turns.length - 1} />}
          </div>)}
        </div>

        <form className="pb-safe border-t p-3" onSubmit={e => { e.preventDefault(); ask(text) }}>
          <div className="bg-card focus-within:border-ring flex items-end gap-2 rounded-lg border px-3 py-2">
            <textarea ref={input} rows={1} value={text} maxLength={1500} placeholder={busy ? 'Axella is answering…' : 'Ask or tell Axella…'}
              onChange={e => { setText(e.target.value); e.target.style.height = 'auto'; e.target.style.height = Math.min(e.target.scrollHeight, 140) + 'px' }}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && matchMedia('(hover: hover)').matches) { e.preventDefault(); ask(text) } }}
              className="max-h-[140px] min-h-6 flex-1 resize-none bg-transparent text-[16px] outline-none sm:text-sm" />
            <Button type="submit" size="icon-sm" disabled={busy || !text.trim()} aria-label="Send"><ChevronRight /></Button>
          </div>
        </form>
      </section>
    </div>
  )
}

function Waiting({ st, secs }: { st: Status | null; secs: number }) {
  const msg = st?.state === 'queued' && st.waiting_for ? `Waiting for “${st.waiting_for}” to finish…` : secs < 4 ? 'Asking the Mac mini…' : `Axella is looking… ${secs}s`
  return <div className="text-ink-3 flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" />{msg}</div>
}

function Answer({ r, done, onRun, onSkip, onFollow, canFollow }: { r: Result; done: Record<number, string>; onRun: (i: number, c: Card) => void; onSkip: (i: number) => void; onFollow: (q: string) => void; canFollow: boolean }) {
  const { ax, go } = useApp()
  const kb = useKnowledge()
  const [busy, setBusy] = useState<number | null>(null)
  /* what a step really does, in plain words from its payload – never the run's own label, which could say anything */
  const subj = (id?: string) => { const i = (ax.current?.data.items || []).find(x => x.id === id); return i ? (i.headline || i.subject || id) : (id || 'an item') }
  const q = (x: unknown) => '“' + String(x ?? '').slice(0, 80) + '”'
  const describe = (s: Step) => {
    const p = s.payload || {}
    switch (s.action) {
      case 'done': return 'Mark as done: ' + q(subj(p.item_id))
      case 'snooze': return 'Bring back ' + (p.until ? new Date(p.until).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : 'later') + ': ' + q(subj(p.item_id))
      case 'file': return 'Move ' + q(subj(p.item_id) || p.title) + ' to ' + q(p.folder)
      case 'task_add': return 'Add task ' + q(p.text) + (p.due ? ' due ' + p.due : '')
      case 'reminder_add': return 'Recurring reminder ' + q(p.text || p.title)
      case 'kb_add': return 'Suggest knowledge ' + q(p.title) + ' (you approve it in Knowledge)'
      case 'project_item_add': return 'Add ' + q(p.headline || subj(p.item_id)) + ' to project ' + q(ax.projects.find(x => x.id === p.id)?.name || p.id)
      case 'compose': return 'Draft a new mail to ' + q(p.to)
      default: return s.action
    }
  }
  const open = (s: Source) => {
    if (s.kind === 'knowledge' && s.id) { const e = kb?.find(x => x.id === s.id); if (e) openKnowledge(e); return }
    if (s.kind === 'task' || s.kind === 'reminder') { go({ kind: 'todo' }); return }
    if (s.kind === 'project' && s.id) { go({ kind: 'project', id: s.id }); return }
    if (s.kind === 'receipt') { go({ kind: 'receipts' }); return }
    if (s.digest) { const n = s.digest.replace(/^.*\//, '').replace(/\.json$/, '.md'); ax.select(n).catch(() => ax.select(`archive/${n.slice(0, 7)}/${n}`)).then(() => go({ kind: 'briefing' })).catch(() => toast('That digest is no longer available')) }
  }
  return <div className="space-y-2.5">
    <div className="space-y-1.5 text-[15px] leading-relaxed">{blocks(r.answer)}</div>
    {!!r.sources?.length && <div className="flex flex-wrap gap-1.5">{r.sources.slice(0, 8).map((s, i) =>
      <button key={i} onClick={() => open(s)} className="text-ink-2 hover:border-line-strong max-w-full truncate rounded-sm border px-1.5 py-0.5 text-xs" title={s.kind}>{s.label}</button>)}</div>}
    {(r.actions || []).slice(0, 3).map((c, ci) => {
      const ok = cardOk(c), state = done[ci]
      return <div key={ci} className={cn('rounded-lg border p-3', state === 'done' ? 'border-success/40' : 'bg-card')}>
        <div className="flex items-start gap-2 text-sm font-medium">{state === 'done' && <Check className="text-success mt-0.5 size-4 shrink-0" />}{c.title}</div>
        <ul className="text-ink-2 mt-1 space-y-0.5 text-[13px]">{c.steps.slice(0, 10).map((s, i) => <li key={i} className="truncate" title={s.label || ''}>· {describe(s)}</li>)}</ul>
        {!state && (ok
          ? <div className="mt-2.5 flex gap-2"><Button size="pill" disabled={busy !== null} onClick={async () => { setBusy(ci); await onRun(ci, c); setBusy(null) }}>{busy === ci ? <Loader2 className="animate-spin" /> : <Check />}{c.steps[0]?.action === 'compose' ? 'Open New mail' : 'Do it'}</Button>
              <Button size="pill" variant="ghost" onClick={() => onSkip(ci)}>No thanks</Button></div>
          : <div className="text-ink-3 mt-2 text-xs">Axella can't do this from here.</div>)}
        {state === 'skipped' && <div className="text-ink-3 mt-1.5 text-xs">Skipped</div>}
        {state === 'failed' && <div className="text-danger mt-1.5 text-xs">Didn't work – see the message above</div>}
      </div>
    })}
    {canFollow && !!r.followups?.length && <div className="flex flex-wrap gap-1.5">{r.followups.slice(0, 3).map(f =>
      <button key={f} onClick={() => onFollow(f)} className="text-fjord hover:bg-fjord-soft rounded-md border border-fjord/30 px-2 py-1 text-left text-xs">{f}</button>)}</div>}
  </div>
}

/* markdown light: paragraphs and "- " bullets, inline formatting via mdInline (escaped) */
function blocks(md: string) {
  const out: React.ReactNode[] = []
  let list: string[] = []
  const flush = () => { if (list.length) { out.push(<ul key={out.length} className="list-disc space-y-0.5 pl-5">{list.map((l, i) => <li key={i} className="md-inline" dangerouslySetInnerHTML={{ __html: mdInline(l) }} />)}</ul>); list = [] } }
  for (const line of String(md || '').split('\n')) {
    const m = line.match(/^\s*[-*•]\s+(.*)$/)
    if (m) { list.push(m[1]); continue }
    flush()
    if (line.trim()) out.push(<p key={out.length} className="md-inline" dangerouslySetInnerHTML={{ __html: mdInline(line) }} />)
  }
  flush()
  return out
}
