import * as React from 'react'
import * as M from '@radix-ui/react-dropdown-menu'
import { cn } from '@/lib/utils'
export const DropdownMenu = M.Root
export const DropdownMenuTrigger = M.Trigger
export function DropdownMenuContent({ className, sideOffset = 4, ...p }: React.ComponentPropsWithoutRef<typeof M.Content>) {
  // Radix flips automatically when there's no room below (collision-aware)
  return <M.Portal><M.Content sideOffset={sideOffset} collisionPadding={{ top: 110, bottom: 56, left: 8, right: 8 }}
    className={cn('z-50 min-w-[220px] max-h-[var(--radix-dropdown-menu-content-available-height)] overflow-y-auto overscroll-contain rounded-lg border bg-popover p-1 text-popover-foreground shadow-float data-[state=open]:animate-in', className)} {...p} /></M.Portal>
}
/* Radix selects an item on pointerup, so "press, drag, release" works. But a menu that had to move up over its trigger
   (short window, row low on the screen) then gets the release of the very press that opened it, and selects whatever
   lies under the pointer. Only a press that started inside a menu may select on release; taps, clicks and keys work as before. */
let pressInMenu = false
if (typeof document !== 'undefined') document.addEventListener('pointerdown', e => {
  pressInMenu = !!(e.target as Element | null)?.closest?.('[role=menu]')
}, true)
export function DropdownMenuItem({ className, destructive, onPointerUp, ...p }: React.ComponentPropsWithoutRef<typeof M.Item> & { destructive?: boolean }) {
  return <M.Item onPointerUp={e => { onPointerUp?.(e); if (!pressInMenu) e.preventDefault() }} className={cn('relative flex select-none items-center gap-2.5 rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-bg-2 data-[disabled]:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground',
    destructive && 'text-destructive data-[highlighted]:bg-destructive/10 [&_svg]:text-destructive', className)} {...p} />
}
export const DropdownMenuSeparator = ({ className, ...p }: React.ComponentPropsWithoutRef<typeof M.Separator>) =>
  <M.Separator className={cn('-mx-1 my-1 h-px bg-border', className)} {...p} />
