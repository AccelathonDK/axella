import * as React from 'react'
import * as D from '@radix-ui/react-dialog'
import { X } from '@/components/ax-icons'
import { cn, keepToasts } from '@/lib/utils'
export const Dialog = D.Root
export const DialogTitle = D.Title
/* centred card on desktop, bottom sheet on phones */
export function DialogContent({ className, children, ...p }: React.ComponentPropsWithoutRef<typeof D.Content>) {
  return <D.Portal>
    <D.Overlay data-sheet-overlay="" className="fixed inset-0 z-50 bg-[var(--ax-scrim)]" />
    <D.Content aria-describedby={undefined} onOpenAutoFocus={e => e.preventDefault()} onPointerDownOutside={keepToasts} onInteractOutside={keepToasts} className={cn(
      'bg-card text-card-foreground fixed z-50 flex flex-col overflow-hidden border shadow-float outline-none',
      'inset-x-0 bottom-0 max-h-[88dvh] rounded-t-lg pb-safe',
      'sm:inset-x-auto sm:bottom-auto sm:top-1/2 sm:left-1/2 sm:max-h-[85vh] sm:w-[min(720px,92vw)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-lg sm:pb-0',
      className)} {...p}>
      {children}
      <D.Close className="text-muted-foreground hover:text-foreground absolute top-3 right-3 rounded-md p-1.5 hover:bg-bg-2" aria-label="Close"><X className="size-5" /></D.Close>
    </D.Content>
  </D.Portal>
}
