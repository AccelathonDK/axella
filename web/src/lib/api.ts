import { purgeOutbox } from '@/lib/outbox'
export const API = 'api/'
/** No answer from the Axella service (no connection, or Tailscale Serve answered 502/503/504). The request may still
    have arrived – a send is only repeated with its send_id, which the Mac mini never sends twice (lib/outbox.ts). */
export class Unreachable extends Error {}
/** One id per confirmed send (the second tap): the Mac mini sends each id at most once (setup/axella-actions.py). */
export const newSendId = (): string => (globalThis.crypto && 'randomUUID' in crypto) ? crypto.randomUUID()
  : Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('')
export async function post<T = any>(action: string, body: unknown): Promise<T> {
  let r: Response
  try { r = await fetch(API + action, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Axella': '1' }, body: JSON.stringify(body) }) }
  catch { throw new Unreachable("The Mac mini isn't answering") }
  if ([502, 503, 504].includes(r.status)) throw new Unreachable("The Mac mini isn't answering")
  if (r.status === 403) purgeOutbox()                     // this device isn't allowed any more
  const j = await r.json().catch(() => ({ ok: false, error: 'bad response' }))
  if (!j.ok) throw new Error(j.error || 'HTTP ' + r.status)
  return j
}
export async function get<T = any>(what: string): Promise<T> {
  let r: Response
  try { r = await fetch(API + what, { cache: 'no-store' }) }
  catch { throw new Unreachable("The Mac mini isn't answering") }
  if ([502, 503, 504].includes(r.status)) throw new Unreachable("The Mac mini isn't answering")   // e.g. while it restarts
  if (r.status === 403) purgeOutbox()
  const j = await r.json().catch(() => { throw new Unreachable("The Mac mini isn't answering") })
  if (!j.ok) throw new Error(j.error || 'failed')
  return j
}
