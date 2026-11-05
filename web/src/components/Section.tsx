import { useState, type ReactNode } from 'react'
import { ChevronRight, Check, type LucideIcon } from '@/components/ax-icons'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

/* BucketCard (design system "Axella"): icon tile, title, subtitle, a count in a small mono square, the items – or
   "Nothing here" – and a collapsed "Handled (n)". Buckets have no colours of their own: neutral when empty, accent
   when something waits, dawn only for Urgent – now with items. */
export function SectionCard({ id, icon: Icon, title, sub, count, children, handled, right, urgent }: {
  id: string; color?: string; icon: LucideIcon; title: string; sub?: string; count?: number | null
  children: ReactNode; handled?: { n: number; render: () => ReactNode; label?: string }; right?: ReactNode; urgent?: boolean
}) {
  const [showDone, setShowDone] = useState(false)
  const live = !!count
  const hot = live && (urgent || id === 'p0')
  return (
    <Card id={'sec-' + id} data-sec={id} className="scroll-mt-sec">
      <div className="flex items-center gap-3 px-4 py-3">
        <div className={cn('flex size-10 shrink-0 items-center justify-center rounded-md',
          hot ? 'bg-dawn text-on-dawn' : live ? 'bg-fjord-soft text-fjord' : 'bg-bg-2 text-ink')}><Icon className="size-5" /></div>
        <div className="min-w-0">
          <div className="text-[15px] leading-tight font-semibold">{title}</div>
          {sub && <div className="text-ink-3 truncate text-[13px]">{sub}</div>}
        </div>
        <div className="ml-auto flex items-center gap-2">
          {right}
          {count != null && <span aria-label={count + ' items'} className={cn('flex h-7 min-w-7 items-center justify-center rounded-sm px-1.5 font-mono text-[13px] font-medium tabular-nums',
            hot ? 'bg-dawn text-on-dawn' : live ? 'bg-fjord text-on-fjord' : 'text-ink-3 border border-line')}>{count}</span>}
        </div>
      </div>
      <div className="divide-y border-t">{children}</div>
      {handled && handled.n > 0 && <>
        <button onClick={() => setShowDone(!showDone)} aria-expanded={showDone}
          className="text-ink-3 hover:text-ink flex w-full items-center gap-1.5 border-t px-4 py-2.5 text-left text-[13px]">
          <ChevronRight className={cn('size-4 transition-transform duration-[480ms]', showDone && 'rotate-90')} />{handled.label || 'Handled'} ({handled.n})
        </button>
        {showDone && <div className="ax-reveal divide-y border-t">{handled.render()}</div>}
      </>}
    </Card>
  )
}

export const Empty = ({ children = 'Nothing here' }: { children?: ReactNode }) =>
  <div className="text-ink-3 flex items-center gap-1.5 px-4 py-3.5 text-sm"><Check className="text-success size-4" />{children}</div>
