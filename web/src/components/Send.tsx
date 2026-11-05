import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Forward, Loader2, Paperclip, Undo2, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const UNDO_S = 6
const ARM_S = 6

/** Send, the careful way: first tap arms ("Tap again to send to Sam"), the second starts a short countdown – the
    button itself becomes Undo meanwhile – and only then the Mac mini's Mail sends it. Closing the page during the
    countdown sends nothing. */
export type SendPhase = 'idle' | 'armed' | 'counting' | 'busy'
export function SendButton({ to, disabled, onSend, className, size = 'pill', blocked, onPhase, swipeRef }: {
  to: string; disabled?: boolean; onSend: () => Promise<unknown>; className?: string; size?: 'pill' | 'default'
  /** Reply sprint: a deliberate swipe right counts as both taps – it starts the same countdown, with Undo */
  swipeRef?: { current: (() => void) | null }
  onPhase?: (p: SendPhase) => void   // the bar hides its other buttons while a send is armed or counting down
  blocked?: string            // a reason not to send yet (e.g. an unresolved "[ … ]" choice) – the tap explains instead of arming
}) {
  // idle → armed (tap again within ARM_S) → counting (UNDO_S, a tap undoes) → busy (Mail is sending) → idle
  const [phase, setPhase] = useState<SendPhase>('idle')
  useEffect(() => { onPhase?.(phase) }, [phase])
  const [left, setLeft] = useState(UNDO_S)
  const timers = useRef<number[]>([])
  const cancel = useRef<() => void>(() => {})
  const counting = useRef(false), toastId = useRef<string | number | undefined>(undefined)
  const clear = () => { timers.current.forEach(t => { clearTimeout(t); clearInterval(t) }); timers.current = [] }
  // the sheet closing (or the list redrawing) during the countdown stops the send – and says so, never silently
  useEffect(() => () => { const was = timers.current.length > 0 && counting.current; clear(); if (was) { toast.dismiss(toastId.current); toast.warning(`Not sent – the reply to ${to} closed before it went`, { duration: 10000 }) } }, [])

  const fire = () => {
    let cancelled = false
    setPhase('counting'); setLeft(UNDO_S)
    const id = toast(`Sending to ${to}…`, {
      description: `In ${UNDO_S} seconds – from your Mac mini's Mail`,
      duration: UNDO_S * 1000,
      action: { label: 'Undo', onClick: () => cancel.current() },
    })
    toastId.current = id; counting.current = true
    cancel.current = () => { if (cancelled) return; cancelled = true; counting.current = false; clear(); toast.dismiss(id); setPhase('idle'); toast('Not sent – your text is still here') }
    const started = Date.now()
    timers.current.push(window.setInterval(() => setLeft(Math.max(1, Math.ceil(UNDO_S - (Date.now() - started) / 1000))), 250))
    timers.current.push(window.setTimeout(async () => {
      if (cancelled) return
      counting.current = false; clear(); toast.dismiss(id); setPhase('busy')
      try { await onSend() } catch (e: any) { toast.error('Not sent: ' + e.message, { duration: 10000 }) } finally { setPhase('idle') }
    }, UNDO_S * 1000 + 150))
  }
  if (swipeRef) swipeRef.current = () => {
    if (phase === 'busy' || phase === 'counting' || (disabled && phase === 'idle')) return
    if (blocked) { toast.warning(blocked, { duration: 8000 }); return }
    clear(); fire()
  }
  const tap = () => {
    if (phase === 'busy') return
    if (phase === 'counting') { cancel.current(); return }
    if (blocked) { toast.warning(blocked, { duration: 8000 }); document.getElementById('ax-choice')?.scrollIntoView({ block: 'center', behavior: 'smooth' }); return }
    if (phase === 'idle') { clear(); setPhase('armed'); timers.current.push(window.setTimeout(() => setPhase(p => p === 'armed' ? 'idle' : p), ARM_S * 1000)); return }
    clear(); fire()
  }
  const label = phase === 'busy' ? 'Sending…' : phase === 'counting' ? `Undo · sends in ${left} s` : phase === 'armed' ? `Tap again to send to ${to}` : blocked ? 'Pick in [ … ] first' : 'Send'
  return <Button size={size} onClick={tap} disabled={(disabled && phase === 'idle') || phase === 'busy'} aria-live="polite" data-send=""
    variant={phase === 'counting' || (blocked && phase === 'idle') ? 'outline' : undefined}
    className={cn(phase === 'armed' && 'bg-fjord text-on-fjord hover:bg-fjord/90 ring-fjord/40 ring-4', className)}
    title={phase === 'armed' ? 'Tap again to send' : phase === 'counting' ? 'Tap to stop – nothing has been sent yet' : 'Send – you get a few seconds to undo'}>
    {phase === 'busy' ? <Loader2 className="animate-spin" /> : phase === 'counting' ? <Undo2 /> : <Forward />}{label}
  </Button>
}

/* ---------- attachments for a mail you send from Axella (uploaded to the Mac mini's outbox, attached by Mail) ---------- */
export interface Att { key: string; id?: string; name: string; size: number; busy?: boolean; error?: string }
export const fmtBytes = (n: number) => n < 1024 * 1024 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n / 1024 / 1024).toFixed(1) + ' MB'

export function useAttachments() {
  const [list, setList] = useState<Att[]>([])
  const add = (files: FileList | File[] | null) => {
    Array.from(files || []).forEach(f => {
      if (f.size > 20 * 1024 * 1024) { toast.error(f.name + ' is larger than 20 MB'); return }
      const key = f.name + ':' + f.size + ':' + Math.random()
      setList(l => [...l, { key, name: f.name, size: f.size, busy: true }])
      fetch(`api/outbox_upload?name=${encodeURIComponent(f.name)}`, { method: 'POST', headers: { 'X-Axella': '1', 'Content-Type': f.type || 'application/octet-stream' }, body: f })
        .then(r => r.json().catch(() => ({ ok: false, error: 'HTTP ' + r.status })))
        .then(j => setList(l => l.map(a => a.key === key ? { ...a, busy: false, id: j.ok ? j.result : undefined, error: j.ok ? undefined : j.error } : a)))
        .catch(e => setList(l => l.map(a => a.key === key ? { ...a, busy: false, error: e.message } : a)))
    })
  }
  const remove = (a: Att) => setList(l => l.filter(x => x !== a))
  const ids = list.filter(a => a.id).map(a => a.id!)
  const busy = list.some(a => a.busy)
  return { list, add, remove, ids, busy, clear: () => setList([]) }
}

export function AttachButton({ onFiles, className }: { onFiles: (f: FileList | null) => void; className?: string }) {
  const inp = useRef<HTMLInputElement>(null)
  return <>
    <button type="button" className={cn('text-ink-2 hover:text-ink inline-flex items-center gap-1.5 font-medium', className)} onClick={() => inp.current?.click()}>
      <Paperclip className="size-4" />Attach</button>
    <input ref={inp} type="file" multiple className="hidden" onChange={e => { onFiles(e.target.files); e.target.value = '' }} />
  </>
}

export function AttachList({ list, onRemove }: { list: Att[]; onRemove: (a: Att) => void }) {
  if (!list.length) return null
  return <div className="flex flex-wrap gap-1.5 px-4 pb-3">
    {list.map(a => <span key={a.key} className={cn('bg-bg-2 inline-flex max-w-full items-center gap-1.5 rounded-sm border py-0.5 pr-1 pl-2 text-[13px]', a.error && 'border-danger/50 text-danger')}
      title={a.error || undefined}>
      {a.busy ? <Loader2 className="size-3.5 animate-spin" /> : <Paperclip className="size-3.5" />}
      <span className="truncate">{a.name}</span><span className="text-ink-3 shrink-0 font-mono text-[11px]">{a.error ? 'failed' : fmtBytes(a.size)}</span>
      <button type="button" aria-label={'Remove ' + a.name} className="text-ink-3 hover:text-ink rounded-sm p-0.5" onClick={() => onRemove(a)}><X className="size-3.5" /></button>
    </span>)}
  </div>
}
