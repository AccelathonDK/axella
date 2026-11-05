/* The writing assistant next to the reply: improve, shorten, change the tone, fix spelling, translate, draft – or ask
   for anything. It works on the selected text if there is a selection, else on the whole reply. The answer is only a
   suggestion: Replace / Insert / Try again – your text changes only when you choose. It never touches recipients,
   subject or attachments, and never sends (setup/compose_assist.py, a Claude call with no tools). */
import { useEffect, useRef, useState } from 'react'
import { Loader2, Sparkles, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Input, NativeSelect } from '@/components/ui/input'
import { post } from '@/lib/api'
import { cn } from '@/lib/utils'

type Mode = 'draft' | 'improve' | 'shorter' | 'friendlier' | 'formal' | 'spelling' | 'translate' | 'sender_language' | 'free'
const ACTIONS: [Mode, string][] = [['improve', 'Improve'], ['shorter', 'Shorter'], ['friendlier', 'Friendlier'], ['formal', 'More formal'],
  ['spelling', 'Fix spelling'], ['sender_language', "In the sender's language"]]
const LANGS = ['Danish', 'English', 'German', 'Dutch', 'Swedish', 'Norwegian', 'French', 'Spanish', 'Italian', 'Portuguese', 'Finnish', 'Polish']
let lastLang = 'English'

export interface AssistTarget {
  text: string
  /** the selection in the reply box when the panel was used, if any */
  getSelection: () => { start: number; end: number } | null
  setText: (t: string) => void
  focus: (start: number, end: number) => void
}

export function AssistPanel({ target, account, messageId, title, to, onClose }: { target: AssistTarget; account?: string; messageId?: string; title?: string; to?: string; onClose: () => void }) {
  const [busy, setBusy] = useState<Mode | null>(null)
  const [secs, setSecs] = useState(0)
  const [res, setRes] = useState<{ text: string; range: { start: number; end: number } | null; mode: Mode; req?: string } | null>(null)
  const [err, setErr] = useState('')
  const [req, setReq] = useState('')
  const [lang, setLang] = useState(lastLang)
  const [sel, setSel] = useState<{ start: number; end: number } | null>(null)
  const seq = useRef(0)
  useEffect(() => { if (!busy) return; setSecs(0); const t = setInterval(() => setSecs(s => s + 1), 1000); return () => clearInterval(t) }, [busy])
  // show what will be worked on: the selection follows the reply box while the panel is open
  useEffect(() => { const t = setInterval(() => setSel(target.getSelection()), 400); return () => clearInterval(t) }, [target])

  async function run(mode: Mode, request?: string) {
    const range = target.getSelection()
    const selection = range ? target.text.slice(range.start, range.end) : ''
    const n = ++seq.current
    setBusy(mode); setErr(''); setRes(null)
    try {
      const j = await post<{ result: { text: string } }>('compose_assist', { mode, account, message_id: messageId, to: to || undefined, title: title || '',
        text: target.text, selection, request: request || '', language: mode === 'translate' ? lang : undefined })
      if (n === seq.current) setRes({ text: j.result.text, range, mode, req: request })
    } catch (e: any) { if (n === seq.current) setErr(e.message) } finally { if (n === seq.current) setBusy(null) }
  }
  function apply(how: 'replace' | 'insert') {
    if (!res) return
    const t = target.text
    let start: number, end: number
    if (how === 'replace') { start = res.range ? res.range.start : 0; end = res.range ? res.range.end : t.length }
    else { const at = res.range ? res.range.end : t.length; start = end = at }
    // an inserted piece gets its own paragraph; the cursor goes after the new text (nothing stays selected)
    const before = t.slice(0, start)
    const piece = how === 'insert' && before.trim() ? (before.endsWith('\n\n') ? '' : before.endsWith('\n') ? '\n' : '\n\n') + res.text : res.text
    target.setText(before + piece + t.slice(end))
    setTimeout(() => target.focus(start + piece.length, start + piece.length))
    setRes(null)
  }
  const empty = !target.text.trim()
  const selLen = sel ? sel.end - sel.start : 0
  return <section aria-label="Writing assistant" data-assist="" className="bg-card rounded-lg border shadow-sm">
    <div className="flex items-center gap-2 border-b px-4 py-2.5">
      <Sparkles className="text-fjord size-4" /><span className="font-semibold">Writing assistant</span>
      <button type="button" aria-label="Close the assistant" onClick={onClose} className="text-ink-3 hover:text-ink ml-auto p-1"><X className="size-4" /></button>
    </div>
    <div className="space-y-3 p-4 text-[13px]">
      <div className="text-ink-3">{selLen > 0 ? `Works on the selected text (${selLen} characters).` : empty ? 'Nothing written yet – let Axella draft it, or ask below.' : `Works on your whole ${messageId ? 'reply' : 'mail'} – select a part to change only that.`}</div>
      <div className="flex flex-wrap gap-1.5">
        <Chip on={busy === 'draft'} disabled={!!busy} onClick={() => run('draft')}>{empty ? (messageId ? 'Draft a reply' : 'Draft it') : 'Redraft'}</Chip>
        {ACTIONS.filter(([m]) => messageId || m !== 'sender_language').map(([m, l]) => <Chip key={m} on={busy === m} disabled={!!busy || (empty && selLen === 0)} onClick={() => run(m)}>{l}</Chip>)}
      </div>
      <div className="flex items-center gap-1.5">
        <NativeSelect aria-label="Language" value={lang} onChange={e => { setLang(e.target.value); lastLang = e.target.value }} className="h-8 min-w-0 flex-1 text-[13px]">
          {LANGS.map(l => <option key={l}>{l}</option>)}</NativeSelect>
        <Button size="pill" variant="outline" disabled={!!busy || (empty && selLen === 0)} onClick={() => run('translate')}>{busy === 'translate' ? <Loader2 className="animate-spin" /> : null}Translate</Button>
      </div>
      <form className="flex items-center gap-1.5" onSubmit={e => { e.preventDefault(); if (req.trim()) run('free', req.trim()) }}>
        <Input value={req} onChange={e => setReq(e.target.value)} maxLength={600} placeholder="Ask Axella… e.g. say no politely, suggest next week" aria-label="Ask the assistant" className="h-8 text-[13px]" />
        <Button type="submit" size="pill" disabled={!!busy || !req.trim()}>{busy === 'free' ? <Loader2 className="animate-spin" /> : null}Go</Button>
      </form>
      {busy && <div className="text-ink-2 flex items-center gap-2" aria-live="polite"><Loader2 className="text-fjord size-4 animate-spin" />Writing…{secs >= 3 && <span className="text-ink-3 font-mono text-[12px]">{secs} s</span>}
        <button type="button" className="text-ink-3 ml-auto hover:underline" onClick={() => { seq.current++; setBusy(null) }}>Stop</button></div>}
      {err && <div className="text-dawn" aria-live="polite">{err}</div>}
      {res && <div className="space-y-2" data-assist-result="">
        <div className="text-ink-3 text-[12px]">Suggestion{res.range ? ' for the selected text' : ''} – your reply is unchanged until you choose</div>
        <div className="bg-bg-2/60 max-h-72 overflow-y-auto rounded-md border px-3 py-2 text-[14px] leading-relaxed whitespace-pre-wrap">{res.text}</div>
        <div className="flex flex-wrap gap-1.5">
          <Button size="pill" onClick={() => apply('replace')}>Replace</Button>
          <Button size="pill" variant="outline" onClick={() => apply('insert')}>Insert</Button>
          <Button size="pill" variant="ghost" onClick={() => run(res.mode, res.req)}>Try again</Button>
          <Button size="pill" variant="ghost" className="ml-auto" onClick={() => setRes(null)}>Discard</Button>
        </div>
      </div>}
      <p className="text-ink-3 text-[11.5px] leading-snug">Axella reads {messageId ? 'this mail and ' : ''}your text to help – it can't change who it goes to, and nothing is sent until you tap Send.</p>
    </div>
  </section>
}

function Chip({ on, disabled, onClick, children }: { on?: boolean; disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button type="button" disabled={disabled} onClick={onClick}
    className={cn('hover:border-line-strong inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[13px] transition-colors disabled:opacity-50',
      on && 'border-fjord text-fjord')}>{on && <Loader2 className="size-3.5 animate-spin" />}{children}</button>
}
