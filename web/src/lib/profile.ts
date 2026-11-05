/* Who Axella works for – GET api/profile, from setup/actions-config.json on the Mac mini (owner, mail accounts,
   workplaces, calendars). Nothing personal is built into the dashboard; private-only setups have no workplaces. */
export interface Account { id: string; label: string; kind: 'private' | 'work'; workplace?: string | null }
export interface Workplace { id: string; name: string; calendar?: string | null; protected: boolean }
export interface Calendar { name: string; label: string; kind: 'private' | 'work'; workplace?: string | null }
export interface Profile { owner: { name: string; first_name: string; sign_off: string }; accounts: Account[]; workplaces: Workplace[]; calendars: Calendar[] }

let P: Profile = {
  owner: { name: '', first_name: '', sign_off: '' },
  accounts: [{ id: 'iCloud', label: 'iCloud', kind: 'private' }],
  workplaces: [],
  calendars: [{ name: 'Home', label: 'Home', kind: 'private' }],
}
export const profile = () => P
let V = 0
/** bumps each time the real profile arrives – the views are keyed on it, so labels and account lists computed once at
    mount (or in memo/state) are rebuilt after a hard reload instead of keeping the defaults */
export const profileVersion = () => V
export function setProfile(p: Profile) {
  const n = { ...P, ...p, owner: { ...P.owner, ...p.owner } }
  if (JSON.stringify(n) !== JSON.stringify(P)) { P = n; V++ }   // unchanged on a reconnect: no remount
}

export const account = (id?: string | null) => P.accounts.find(a => a.id === id)
export const accLabel = (id?: string | null) => account(id)?.label || id || ''
export const isWorkAccount = (id?: string | null) => account(id)?.kind === 'work'
export const workplaceOf = (accountId?: string | null) => P.workplaces.find(w => w.id === account(accountId)?.workplace)
export const firstName = () => P.owner.first_name || 'you'
export const hasProtected = () => P.workplaces.some(w => w.protected)

/** [value, label] pairs for the calendar picker */
export const cals = (): [string, string][] => P.calendars.map(c => [c.name, c.label])
export const calLabel = (v: string) => P.calendars.find(c => c.name === v)?.label || v

/** Best calendar for a suggested event: the workplace's own calendar, else a general work calendar, else private. */
export function calendarFor(work: boolean, accountId?: string | null, text = ''): string {
  const cs = P.calendars
  if (work) {
    const wp = workplaceOf(accountId) || P.workplaces.find(w => w.name && new RegExp('\\b' + w.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b', 'i').test(text))
    const own = wp && (cs.find(c => c.name === wp.calendar) || cs.find(c => c.workplace === wp.id))
    if (own) return own.name
    const gen = cs.find(c => c.kind === 'work' && !c.workplace) || cs.find(c => c.kind === 'work')
    if (gen) return gen.name
  }
  return (cs.find(c => c.kind === 'private') || cs[0])?.name || 'Home'
}
