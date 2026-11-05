import { useEffect, useRef } from 'react'
import { toast } from 'sonner'
import { Rune } from '@/components/icons'
import { useApp } from '@/lib/app'

/* Offline notice in the Axella style: a calm bar above the footer while this laptop/phone has no connection
   (buttons pause, the page keeps what it showed). When the connection is back the bar goes and a short
   "Back online" toast confirms it. A Mac mini that doesn't answer while online is shown on Today instead. */
export function ConnectionBar() {
  const { ax } = useApp()
  const wasOff = useRef(false)
  useEffect(() => {
    if (!ax.online) wasOff.current = true
    else if (wasOff.current) { wasOff.current = false; toast('Back online – Axella is up to date again') }
  }, [ax.online])
  if (ax.online) return null      // Mac mini unreachable while online: the notice on Today covers it
  return (
    <div role="status" aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] lg:bottom-[calc(2.5rem+env(safe-area-inset-bottom))] z-30 flex justify-center px-4 lg:left-[248px]">
      <div className="ax-reveal bg-surface-inverse text-on-inverse pointer-events-auto flex max-w-xl items-start gap-3 rounded-lg px-4 py-3 shadow-lg">
        <span className="relative mt-0.5 shrink-0"><Rune size={20} />
          <span className="bg-ink-3 absolute -right-1 -bottom-0.5 size-2 rounded-full ring-2 ring-[var(--ax-surface-inverse)]" /></span>
        <div className="min-w-0 text-sm leading-snug">
          <div className="font-semibold">You're offline</div>
          <div className="opacity-75">Axella shows what it loaded last. Buttons are paused, and it picks up again by itself when you're back online.</div>
        </div>
      </div>
    </div>
  )
}

/* The whole page when there is nothing to show yet (opened without a connection). */
export function OfflineScreen({ mini = false }: { mini?: boolean }) {
  return (
    <div className="flex flex-col items-center px-6 py-16 text-center">
      <span className="text-ink-2"><Rune size={44} /></span>
      <h1 className="mt-5 text-xl font-semibold tracking-tight">{mini ? "Can't reach your Mac mini" : "You're offline"}</h1>
      <p className="text-ink-2 mt-1.5 max-w-sm text-sm">
        {mini ? 'You are online, but Axella on the Mac mini does not answer. Check that it is on and that Tailscale is connected on this device.'
          : 'Axella needs a connection to your Mac mini. Nothing is lost – it picks up where it left off as soon as you are back online.'}
      </p>
      <p className="text-ink-3 mt-6 font-mono text-[11px] tracking-[.08em] uppercase">Your attention, on your terms.</p>
    </div>
  )
}
