import { Card } from '@/components/ui/card'
import { SuggestionCard } from '@/components/Learn'
import { useApp } from '@/lib/app'
import type { WrapLine } from '@/lib/types'

/* The week wrap (AXELLA.md "Week wrap"): the Friday work wrap, and the private wrap in the Sunday week-ahead.
   Headline, still open, next week, one line of calm – every line points to its source. */
export function WrapCard() {
  const { ax, go } = useApp()
  const w = ax.current?.data.wrap
  if (!w || !w.headline) return null
  const open = (l: WrapLine) => {
    if (l.item_id) {
      const el = document.querySelector(`[data-item-row="${CSS.escape(String(l.item_id))}"]`)
      if (el) { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); el.classList.add('ax-flash'); setTimeout(() => el.classList.remove('ax-flash'), 1600); return }
    }
    if (l.task_id) return go({ kind: 'todo', tab: 'tasks' })
    if (l.event) return go({ kind: 'calendar' })
  }
  const List = ({ title, lines }: { title: string; lines?: WrapLine[] }) => !lines?.length ? null : <div>
    <div className="ax-label mb-1">{title}</div>
    <ul className="space-y-1 text-[14.5px]">{lines.map((l, i) => {
      const linked = !!(l.item_id || l.task_id || l.event)
      return <li key={i}>{linked
        ? <button type="button" onClick={() => open(l)} className="text-left hover:underline decoration-muted-foreground/50 underline-offset-2">{l.text}</button>
        : l.text}</li>
    })}</ul>
  </div>
  return <Card className="space-y-3 p-4" data-wrap="">
    <div><div className="ax-label">Week wrap</div><div className="mt-1 text-[17px] leading-snug font-semibold">{w.headline}</div></div>
    <List title="Still open" lines={w.still_open} />
    <List title="Next week" lines={w.next_week} />
    {w.calm && <div className="text-ink-3 text-[13px]">{w.calm}</div>}
    <SuggestionCard inWrap />
  </Card>
}
