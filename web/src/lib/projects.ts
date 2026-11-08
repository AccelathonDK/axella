import type { Item, Project } from './types'
import { senderKey } from './data'
import { profile } from './profile'

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Which active projects does this item belong to? Claude's tag > your pin > sender > keyword. */
/** A project counts as work when it says so, or when its id, tag or name is one of the workplaces (Settings → profile). */
export function projectWorld(p: Project): 'work' | 'private' | null {
  if (p.ctx === 'work' || p.ctx === 'private') return p.ctx
  const names = [p.id.replace(/^p-/, ''), p.tag, p.name].map(x => (x || '').toLowerCase())
  return profile().workplaces.some(w => [w.id, w.name].some(x => x && names.includes(x.toLowerCase()))) ? 'work' : null
}

/** Axella's own lines in a digest (bills, subscriptions, renewals, keep in touch, hold a block, the plan): its own
    wording, not something anyone wrote to you – a project only when you pin it. */
export const ownLine = (it: Item) => /-p3-(bills|subscriptions|renewals|keepintouch|focus|plan|check\d+|done\d+)$/.test(it.id)

/** Projects an item belongs to. Pinned by hand always wins; otherwise a private item never gets a work project, and a
    calendar note (free slots, conflicts – no single event) gets no project at all. */
export function projectsOf(it: Item, projects: Project[], ctx?: 'work' | 'private'): Project[] {
  const tagged = ([] as string[]).concat(it.project || []).map(s => s.toLowerCase().replace(/^#/, ''))
  // keywords match what someone wrote to you (headline, subject, sender), not the longer detail text where words turn up by accident
  const short = [it.headline, it.subject, it.from?.name].filter(Boolean).join(' ')
  const hay = [short, it.detail, it.file_to].filter(Boolean).join(' ')
  const sk = senderKey(it)
  const calNote = it.section === 'cal' && !it.event
  return projects.filter(p => {
    if (p.status !== 'active') return false
    if (p.hidden_items?.includes(it.id)) return false
    if (p.items?.some(r => r.item_id === it.id)) return true
    if (calNote || ownLine(it)) return false
    const pw = projectWorld(p)
    if (ctx && pw && ctx !== pw) return false                  // private item ↛ work project, and the other way round
    if (tagged.includes(p.id.toLowerCase()) || tagged.includes(p.tag)) return true
    if (sk && p.senders?.map(s => s.toLowerCase()).includes(sk)) return true
    if (new RegExp('#' + esc(p.tag) + '\\b', 'i').test(hay)) return true
    return (p.keywords || []).some(k => k.length > 2 && new RegExp('(^|[^\\p{L}\\d])' + esc(k) + '($|[^\\p{L}\\d])', 'iu').test(short))
  })
}
export const fileUrl = (p: Project, f: { id: string }) => `api/project_file?p=${encodeURIComponent(p.id)}&f=${encodeURIComponent(f.id)}`
export const fmtSize = (n: number) => n > 1e6 ? (n / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1e3)) + ' kB'
export const PROJECT_COLORS = ['#0d6efd', '#6f42c1', '#d63384', '#fd7e14', '#198754', '#20c997', '#0aa2c0', '#6c757d']

export async function upload(p: Project, file: File) {
  const r = await fetch(`api/project_upload?p=${encodeURIComponent(p.id)}&name=${encodeURIComponent(file.name)}`, {
    method: 'POST', headers: { 'X-Axella': '1', 'Content-Type': file.type || 'application/octet-stream' }, body: file,
  })
  const j = await r.json().catch(() => ({ ok: false, error: 'HTTP ' + r.status }))
  if (!j.ok) throw new Error(j.error)
  return j.result as string
}

/** Project colours follow project-1 … project-8 in the order projects are listed (design system "Axella"). */
export function projColor(list: { id: string }[], id: string) {
  const i = Math.max(0, list.findIndex(p => p.id === id))
  return `var(--ax-project-${(i % 8) + 1})`
}
