import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

export const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md text-sm font-semibold transition-colors duration-[120ms] outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fjord active:translate-y-px disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        default: 'bg-ink text-bg hover:bg-ink/90',
        approve: 'bg-fjord text-on-fjord hover:bg-fjord/90',
        destructive: 'border border-danger bg-card text-danger hover:bg-danger/10',
        outline: 'border border-line-strong bg-card text-ink hover:bg-bg-2',
        success: 'bg-fjord text-on-fjord hover:bg-fjord/90',
        secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        ghost: 'text-ink-2 hover:bg-bg-2 hover:text-ink',
        link: 'text-fjord underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-9 px-4 py-2',
        sm: 'h-8 rounded-md px-3 text-[13px]',
        pill: 'h-8 rounded-md px-3 text-[13px] [&_svg]:size-4',
        icon: 'size-9',
        'icon-sm': 'size-8',
        'icon-pill': 'size-8 rounded-md [&_svg]:size-4',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> { asChild?: boolean }
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : 'button'
  return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
})
Button.displayName = 'Button'
