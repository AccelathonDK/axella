import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'
const badgeVariants = cva('inline-flex h-6 items-center gap-1 rounded-sm border px-2 text-xs font-medium whitespace-nowrap [&_svg]:size-3.5', {
  variants: {
    variant: {
      default: 'border-transparent bg-fjord-soft text-fjord',
      secondary: 'border-transparent bg-secondary text-secondary-foreground',
      outline: 'border-line text-ink-3',
      destructive: 'border-transparent bg-dawn text-on-dawn',
      warning: 'border-transparent bg-dawn text-on-dawn',
      work: 'border-transparent bg-work-soft text-work',
      private: 'border-transparent bg-private-soft text-private',
      success: 'border-transparent bg-fjord-soft text-success',
    },
  },
  defaultVariants: { variant: 'default' },
})
export function Badge({ className, variant, ...p }: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...p} />
}
