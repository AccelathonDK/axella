import * as React from 'react'
import * as D from '@radix-ui/react-dialog'
import { cn, keepToasts } from '@/lib/utils'
export const Sheet = D.Root
export const SheetTitle = D.Title
export function SheetContent({ className, children, ...p }: React.ComponentPropsWithoutRef<typeof D.Content>) {
  return <D.Portal>
    <D.Overlay data-sheet-overlay="" className="fixed inset-0 z-50 bg-[var(--ax-scrim)]" />
    <D.Content data-sheet="" aria-describedby={undefined} onOpenAutoFocus={e => e.preventDefault()} onPointerDownOutside={keepToasts} onInteractOutside={keepToasts} className={cn('fixed inset-y-0 left-0 z-50 w-[300px] max-w-[85vw] border-r bg-sidebar shadow-float outline-none pt-safe pb-safe', className)} {...p}>{children}</D.Content>
  </D.Portal>
}
