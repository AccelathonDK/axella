import { BillsCard } from '@/components/Bills'
import { CommitmentsCard } from '@/components/Commitments'
import { RenewalsCard } from '@/components/Renewals'
import { SprintLine } from '@/components/Sprint'
import { useState, type ReactNode } from 'react'
import { ItemSection, TasksCard, taskInCtx } from '@/components/Cards'
import { CleanupView } from '@/components/Cleanup'
import { NewslettersView } from '@/components/Newsletters'
import { useBySection } from '@/components/Today'
import { useApp } from '@/lib/app'
import { SEC } from '@/lib/sections'
import { cn } from '@/lib/utils'

/* Two hubs from the new structure:
   - To do: your own tasks, and what you wait for from others (the digest's Waiting section) – two kinds of open loop.
   - Mailbox: everything that keeps the mailbox tidy – filing suggestions, newsletters, cleanup. */
function Tabs<T extends string>({ value, tabs, onChange }: { value: T; tabs: [T, string, number | null][]; onChange: (t: T) => void }) {
  return <div role="tablist" className="bg-bg-2 inline-flex rounded-md p-0.5">
    {tabs.map(([k, l, n]) => <button key={k} role="tab" aria-selected={value === k} onClick={() => onChange(k)}
      className={cn('inline-flex h-9 items-center gap-1.5 rounded-sm px-3 text-sm transition-colors', value === k ? 'bg-surface text-ink ring-line font-medium shadow-sm ring-1' : 'text-ink-2 hover:text-ink')}>
      {l}{n != null && n > 0 && <span className="text-ink-3 font-mono text-[12px]">{n}</span>}</button>)}
  </div>
}
const Head = ({ title, sub, children }: { title: string; sub: string; children: ReactNode }) =>
  <div className="space-y-3"><div><h1 className="text-[28px] leading-tight font-semibold tracking-[-0.02em]">{title}</h1>
    <p className="text-ink-2 text-sm">{sub}</p></div>{children}</div>

export function TodoView({ tab, only: only0 }: { tab: 'tasks' | 'waiting'; only?: 'bills' }) {
  const { ax, go, ctx } = useApp()
  const { by } = useBySection()
  const waiting = by.wait || []
  const openWait = waiting.filter(i => !ax.isHandled(i.id)).length
  const [only, setOnly] = useState<'all' | 'promises' | 'bills'>(only0 || 'all')
  const hasBills = ax.tasks.some(t => t.type === 'bill')
  const hasProm = ax.tasks.some(t => t.source === 'promise' && t.status !== 'done')
  return <div className="space-y-4">
    <Head title="To do" sub="Your own tasks, and what you're waiting for from others.">
      <Tabs value={tab} onChange={t => go({ kind: 'todo', tab: t })}
        tabs={[['tasks', 'My tasks', ax.tasks.filter(t => t.status !== 'done' && taskInCtx(t, ctx)).length], ['waiting', 'Waiting on others', openWait]]} />
    </Head>
    <div className="space-y-3">
      {tab === 'tasks' && <CommitmentsCard />}
      {tab === 'tasks' && <SprintLine />}
      {tab === 'tasks' && <BillsCard />}
      {tab === 'tasks' && <RenewalsCard />}
      {tab === 'tasks' && (hasProm || hasBills) && <div className="flex gap-1.5 text-[13px]" role="group" aria-label="Show">
        {(['all', ...(hasProm ? ['promises'] : []), ...(hasBills ? ['bills'] : [])] as ('all' | 'promises' | 'bills')[]).map(k => <button key={k} onClick={() => setOnly(k)} aria-pressed={only === k}
          className={only === k ? 'bg-fjord-soft text-fjord rounded-md px-2.5 py-1 font-medium' : 'text-ink-2 hover:bg-bg-2 rounded-md px-2.5 py-1'}>{k === 'all' ? 'All tasks' : k === 'promises' ? 'Promises' : 'Bills'}</button>)}
      </div>}
      {tab === 'tasks' ? (only === 'promises' ? <TasksCard filter={t => t.source === 'promise'} title="Promises" sub="What you promised – from your own messages" />
        : only === 'bills' ? <TasksCard filter={t => t.type === 'bill'} title="Bills" sub="Bills to pay – tick one when it's paid. Axella never pays." /> : <TasksCard />)
        : <ItemSection def={SEC.wait} items={waiting} />}
      {tab === 'waiting' && <p className="text-ink-3 mt-3 text-xs">From the latest digest: things you asked for and haven't had an answer to. When one goes stale it also shows up in Today.</p>}
    </div>
  </div>
}

export function MailboxView({ tab }: { tab: 'filing' | 'newsletters' | 'cleanup' }) {
  const { ax, go } = useApp()
  const { by } = useBySection()
  const filing = by.file || []
  const openFiling = filing.filter(i => !ax.isHandled(i.id)).length
  return <div className="space-y-4">
    <Head title="Mailbox" sub="Keep it tidy: file what's done, unsubscribe what you don't read, and clear out old mail.">
      <Tabs value={tab} onChange={t => go({ kind: 'mailbox', tab: t })}
        tabs={[['filing', 'Filing', openFiling], ['newsletters', 'Newsletters', null], ['cleanup', 'Cleanup', null]]} />
    </Head>
    {tab === 'filing' ? <ItemSection def={SEC.file} items={filing} />
      : tab === 'newsletters' ? <div className="[&>div>div:first-child_h1]:hidden"><NewslettersView /></div>
      : <div className="[&>div>div:first-child_h1]:hidden"><CleanupView /></div>}
  </div>
}
