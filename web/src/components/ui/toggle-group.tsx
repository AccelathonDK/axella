import * as React from 'react'
import * as T from '@radix-ui/react-toggle-group'
import { cn } from '@/lib/utils'
export const ToggleGroup = ({ className, ...p }: React.ComponentPropsWithoutRef<typeof T.Root>) =>
  <T.Root className={cn('inline-flex items-center rounded-md bg-bg-2 p-0.5', className)} {...(p as any)} />
export const ToggleGroupItem = ({ className, ...p }: React.ComponentPropsWithoutRef<typeof T.Item>) =>
  <T.Item className={cn('inline-flex h-7 items-center justify-center gap-1 rounded-md px-2.5 text-[13px] font-medium text-ink-2 transition-colors duration-[220ms] hover:text-ink data-[state=on]:bg-surface data-[state=on]:text-ink data-[state=on]:ring-1 data-[state=on]:ring-line-strong [&_svg]:size-4', className)} {...p} />
