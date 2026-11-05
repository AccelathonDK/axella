/* Replies you confirmed (second tap + 6 s) while the Axella service on the Mac mini wasn't answering: kept in this
   browser and sent once by itself as soon as the service answers again (OutboxRunner in Shell). A reply lands here when
   the answer didn't arrive (api.ts Unreachable) – the Mac mini may still have got it. So each reply carries the send_id
   of its tap: before sending it by itself the outbox asks the Mac mini (GET send_status) and drops it if the Mac mini
   already has it, and the Mac mini never sends the same send_id twice. After 30 minutes a waiting reply is not sent by itself any more – you see it again and decide (the
   thread may have moved on); after 24 hours it is removed from this browser. */
export interface Waiting { id: string; action: 'reply_send'; body: Record<string, unknown>; to: string; title: string; at: number }
const KEY = 'ax-outbox'
/** Sent by itself only within this time; after that you see it again and decide (Send now / Cancel). */
export const MAX_AGE = 30 * 60 * 1000
/** The reply text is removed from this browser after a day, sent or not. */
export const PURGE_AGE = 24 * 3600 * 1000
const subs = new Set<(l: Waiting[]) => void>()
export function outbox(): Waiting[] {
  try {
    const l = JSON.parse(localStorage.getItem(KEY) || '[]')
    if (!Array.isArray(l)) return []
    const keep = l.filter((w: Waiting) => w && Date.now() - w.at < PURGE_AGE)
    if (keep.length !== l.length) localStorage.setItem(KEY, JSON.stringify(keep))
    return keep
  } catch { return [] }
}
/** This device isn't allowed any more (HTTP 403): nothing of yours stays in its storage. */
export function purgeOutbox() { try { localStorage.removeItem(KEY) } catch { /* nothing stored */ } subs.forEach(f => f([])) }
function save(l: Waiting[]) {
  try { localStorage.setItem(KEY, JSON.stringify(l)) } catch { /* private mode: it stays in memory for this tab only */ }
  subs.forEach(f => f(l))
}
export function queue(w: Omit<Waiting, 'id' | 'at'>) {
  const l = outbox().filter(x => !(x.body.item_id && x.body.item_id === w.body.item_id))   // one waiting reply per item
  const { force: _force, ...body } = w.body                // "Send again" is never carried over: the send_id decides
  l.push({ ...w, body, id: Math.random().toString(36).slice(2), at: Date.now() }); save(l)
}
export function unqueue(id: string) { save(outbox().filter(x => x.id !== id)) }
export function onOutbox(f: (l: Waiting[]) => void) { subs.add(f); return () => { subs.delete(f) } }
