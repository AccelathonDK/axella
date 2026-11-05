import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { useApp } from '@/lib/app'

/* "New digest" note (design system › Motion): the rune draws on once, the note rises 8px into place and rests –
   nothing pulses or loops. When the view followed the new digest by itself the note goes after 10 s; when you were
   reading an older digest it stays with a Show button until you pick one. Reduced motion: shown in its final state. */
const STROKES = 'M71 79.5 33 41.5 50 24.5 67 41.5 29 79.5'

export function ArrivalNote() {
  const { ax, go, view } = useApp()
  const a = ax.arrival
  useEffect(() => {
    if (!a?.followed) return
    let t: number | undefined
    const start = () => { if (!document.hidden && t === undefined) t = window.setTimeout(ax.dismissArrival, 10000) }   // count only while you can see it
    start(); document.addEventListener('visibilitychange', start)
    return () => { clearTimeout(t); document.removeEventListener('visibilitychange', start) }
  }, [a, ax.dismissArrival])
  useEffect(() => { if (a && !a.followed && ax.current?.name === a.name) ax.dismissArrival() }, [a, ax.current?.name, ax.dismissArrival])
  if (!a) return null
  const what = a.followed
    ? (a.fresh ? `${a.fresh} new ${a.fresh === 1 ? 'thing needs' : 'things need'} you${a.urgent ? ' – one is urgent' : ''}` : 'Nothing new needs you')
    : 'You are reading an older digest'
  const open = () => { ax.select(a.name); if (view.kind !== 'today' && view.kind !== 'briefing') go({ kind: 'today' }); ax.dismissArrival() }
  return (
    <div role="status" aria-live="polite" className="pointer-events-none fixed inset-x-0 top-[calc(var(--top-h,56px)+0.5rem)] z-30 flex justify-center px-4 lg:left-[248px]">
      <div key={a.seq} className="ax-reveal bg-surface-inverse text-on-inverse pointer-events-auto flex max-w-md items-center gap-3 rounded-lg py-2.5 pr-2 pl-3 shadow-lg">
        <svg viewBox="0 0 100 100" width={22} height={22} aria-hidden className="shrink-0 overflow-visible">
          <defs><clipPath id={'ar' + a.seq}><rect width="100" height="75.5" /></clipPath></defs>
          <g clipPath={`url(#ar${a.seq})`}><path d={STROKES} pathLength={1} fill="none" stroke="currentColor" strokeWidth={10} strokeLinejoin="miter" strokeMiterlimit={12} className="ax-draw ax-draw-slow" /></g>
        </svg>
        <div className="min-w-0 text-sm leading-snug">
          <div className="font-semibold">{a.followed ? 'New digest' : 'Newer digest'} <span className="font-mono text-[12px] font-normal opacity-75">{a.label}</span></div>
          <div className="opacity-75">{what}</div>
        </div>
        {!a.followed && <button onClick={open} className="text-on-inverse ml-1 shrink-0 rounded-md border border-current/30 px-2.5 py-1 text-sm font-medium hover:border-current">Show</button>}
        <button onClick={ax.dismissArrival} aria-label="Dismiss" className="ml-auto shrink-0 rounded-md p-1.5 opacity-60 hover:opacity-100"><X className="size-4" /></button>
      </div>
    </div>
  )
}

/* Remounts its children with the digest reveal once, when the view followed a newly arrived digest */
export function RevealOnArrival({ children }: { children: React.ReactNode }) {
  const { ax, view } = useApp()
  const [k, setK] = useState(0)
  useEffect(() => { if (ax.arrival?.followed && (view.kind === 'today' || view.kind === 'briefing')) setK(ax.arrival.seq) }, [ax.arrival])  // eslint-disable-line react-hooks/exhaustive-deps
  return <div key={k} className={k ? 'ax-reveal' : undefined}>{children}</div>
}
