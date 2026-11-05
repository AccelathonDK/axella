/* The replies waiting for the Mac mini (lib/outbox.ts): a small bar above the footer while any wait, each with Cancel,
   and the runner that sends them – one at a time, once – as soon as the Axella service answers again. */
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Hourglass, X } from '@/components/ax-icons'
import { API, Unreachable } from '@/lib/api'
import { useApp } from '@/lib/app'
import { MAX_AGE, onOutbox, outbox, unqueue, type Waiting } from '@/lib/outbox'

/** Does the Mac mini already have this send? Any failure to tell counts as "not answering" – the reply keeps waiting. */
async function sendStatus(id: string): Promise<{ known: boolean; state?: string; error?: string }> {
  try {
    const r = await fetch(API + 'send_status?send_id=' + encodeURIComponent(id), { cache: 'no-store' })
    const j = await r.json()
    if (r.ok && j?.ok) return j
  } catch { /* below */ }
  throw new Unreachable("The Mac mini isn't answering")
}

export function OutboxBar() {
  const { ax } = useApp()
  const [list, setList] = useState<Waiting[]>(outbox)
  const busy = useRef(false)
  useEffect(() => onOutbox(setList), [])
  useEffect(() => {                                       // the service answers again: send what waits, oldest first
    if (!ax.apiOk || busy.current || !list.length) return
    busy.current = true
    ;(async () => {
      for (const w of outbox()) {
        if (Date.now() - w.at > MAX_AGE) continue         // too old to send by itself – stays in the bar for you to decide
        try {
          if (w.body.send_id) {                           // the answer may have been lost while the Mac mini did get it
            const st = await sendStatus(String(w.body.send_id))
            if (st.known) {
              unqueue(w.id)
              if (st.state === 'error') toast.error(`Not sent to ${w.to}: ${st.error || 'it failed'}`, { duration: 15000 })
              else toast.success(`Already sent to ${w.to}`, { description: 'The Mac mini got it before the connection dropped – not sent again.' })
              continue
            }
          }
          await ax.act(w.action, w.body, ['state'])
          unqueue(w.id)
          toast.success(`Sent to ${w.to}`, { description: 'It waited while the Mac mini was not answering.' })
        } catch (e: any) {
          if (e instanceof Unreachable) break             // still down: try again later
          unqueue(w.id)
          toast.error(`Not sent to ${w.to}: ${e.message}`, { duration: 15000 })
        }
      }
      busy.current = false
    })()
  }, [ax.apiOk, list.length])                             // eslint-disable-line react-hooks/exhaustive-deps
  if (!list.length) return null
  return <div role="status" aria-live="polite" data-outbox=""
    className="pointer-events-none fixed inset-x-0 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-30 flex justify-center px-4 lg:bottom-[calc(2.5rem+env(safe-area-inset-bottom))] lg:left-[248px]">
    <div className="bg-card pointer-events-auto max-w-xl space-y-1.5 rounded-lg border px-4 py-3 text-sm shadow-lg">
      {list.map(w => {
        const old = Date.now() - w.at > MAX_AGE
        return <div key={w.id} className="flex items-center gap-2.5">
          <Hourglass className="text-dawn size-4 shrink-0" />
          <span className="min-w-0 flex-1 truncate">{old ? 'Not sent yet – it waited over 30 minutes; still send it?' : 'Waiting to send'} · to <b className="font-semibold">{w.to}</b>{w.title && <span className="text-ink-3"> · {w.title}</span>}</span>
          {old && ax.apiOk && <button className="text-fjord shrink-0 font-semibold hover:underline" onClick={async () => {
            try {
              if (w.body.send_id && (await sendStatus(String(w.body.send_id))).known) { unqueue(w.id); toast.success('Already sent to ' + w.to + ' – not sent again'); return }
              await ax.act(w.action, w.body, ['state']); unqueue(w.id); toast.success('Sent to ' + w.to)
            } catch (e: any) { toast.error('Not sent: ' + e.message) }
          }}>Send now</button>}
          <button className="text-ink-3 hover:text-ink inline-flex shrink-0 items-center gap-1" aria-label={'Cancel the reply to ' + w.to}
            onClick={() => { unqueue(w.id); toast('Cancelled – the reply to ' + w.to + ' was not sent') }}><X className="size-4" />Cancel</button>
        </div>
      })}
    </div>
  </div>
}
