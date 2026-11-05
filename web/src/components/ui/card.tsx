import * as React from 'react'
import { cn } from '@/lib/utils'
export const Card = ({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) =>
  <div className={cn('rounded-lg border bg-card text-card-foreground overflow-hidden', className)} {...p} />
export const CardContent = ({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) => <div className={cn('p-4', className)} {...p} />
