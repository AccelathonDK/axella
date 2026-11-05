/* A mail opened in Axella's own reader (also on the phone) – never Mail's message:// link. Anything that knows a mail's
   account and message id calls openMailInAxella(); one host (in the Shell) shows it read-only in the item sheet. */
import { useEffect, useState } from 'react'
import { ItemSheet } from '@/components/ItemSheet'
import type { Item } from '@/lib/types'

export type MailRef = { account?: string; message_id?: string | null; subject?: string; from?: string }
export const openMailInAxella = (m?: MailRef) => { if (m?.message_id && m.account) window.dispatchEvent(new CustomEvent('ax-open-mail', { detail: m })) }

export function MailReaderHost() {
  const [m, setM] = useState<MailRef | null>(null)
  useEffect(() => { const h = (e: Event) => setM((e as CustomEvent).detail); addEventListener('ax-open-mail', h); return () => removeEventListener('ax-open-mail', h) }, [])
  if (!m) return null
  const it: Item = { id: 'mail-' + m.message_id, section: 'p3', channel: 'mail', account: m.account, message_id: m.message_id || undefined,
    headline: m.subject || 'Mail', subject: m.subject, from: { name: m.from }, readonly: true } as Item
  return <ItemSheet it={it} handled={false} onClose={() => setM(null)} onCal={() => setM(null)} />
}
