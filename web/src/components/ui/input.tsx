import * as React from 'react'
import { cn } from '@/lib/utils'
const base = 'h-9 w-full min-w-0 rounded-md border border-line-strong bg-card px-2.5 text-[16px] sm:text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:opacity-50'
export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, ref) =>
  <input ref={ref} className={cn(base, className)} {...p} />)
Input.displayName = 'Input'
/* same look as the digest picker and the dropdown triggers: card surface, quiet border, ink-3 chevron */
export const NativeSelect = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(({ className, ...p }, ref) =>
  <select ref={ref} className={cn('ax-select h-10 w-full min-w-0 appearance-none rounded-md border border-line bg-card pr-9 pl-3 text-[16px] font-medium outline-none transition-colors hover:border-line-strong focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:opacity-50 sm:h-9 sm:text-sm', className)} {...p} />)
NativeSelect.displayName = 'NativeSelect'
