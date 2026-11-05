import * as React from 'react'
import * as C from '@radix-ui/react-checkbox'
import { Check } from '@/components/ax-icons'
import { cn } from '@/lib/utils'
export const Checkbox = React.forwardRef<React.ElementRef<typeof C.Root>, React.ComponentPropsWithoutRef<typeof C.Root>>(({ className, ...p }, ref) => (
  <C.Root ref={ref} className={cn('peer group size-[18px] shrink-0 rounded-sm border border-line-strong bg-card outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fjord data-[state=checked]:bg-fjord data-[state=checked]:border-fjord data-[state=checked]:text-on-fjord data-[state=indeterminate]:bg-fjord data-[state=indeterminate]:border-fjord data-[state=indeterminate]:text-on-fjord', className)} {...p}>
    <C.Indicator className="flex items-center justify-center"><Check className="size-3.5 group-data-[state=indeterminate]:hidden" strokeWidth={2.5} /><span className="hidden h-0.5 w-2.5 rounded-full bg-current group-data-[state=indeterminate]:block" /></C.Indicator>
  </C.Root>))
Checkbox.displayName = 'Checkbox'
