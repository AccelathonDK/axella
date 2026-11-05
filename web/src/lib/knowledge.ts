/* Knowledge base (setup/knowledge.py, knowledge/entries/*.md): short, checked facts drafts may build on.
   Shared store so the Knowledge page, project pages and "based on" chips show the same entries. */
import { useEffect, useState } from 'react'
import { get } from './api'

export type Visibility = 'private' | 'internal' | 'shareable'
export type KStatus = 'suggested' | 'active' | 'dismissed'
export interface KSource { kind: 'manual' | 'mail' | 'file' | 'url'; ref?: string; label?: string; date?: string }
export interface KEntry {
  id: string; title: string; body: string; scope: 'overall' | string[]; category: string; visibility: Visibility; status: KStatus
  sources: KSource[]; created?: string; updated?: string; check_after?: string | null; language?: string | null; stale?: boolean
  learned?: 'manual' | 'sent' | 'draft-edit' | 'thread' | null; from_others?: string | null
  outdated?: { reason: string; source?: KSource; at?: string } | null
}
/** needs a look: suggestions, plus active entries past their check date or contradicted by newer mail */
export const needsCheck = (e: KEntry) => e.status === 'active' && (!!e.stale || !!e.outdated)
export const LEARNED: Record<string, string> = { sent: 'from your sent mail', 'draft-edit': 'your correction to a draft', thread: 'from a mail thread' }
export type KDraft = Partial<Omit<KEntry, 'sources'>> & { source?: KSource }

export const CATEGORIES = ['employer', 'own company', 'holiday rental', 'private', 'other'] as const
export const CAT_LABEL: Record<string, string> = { employer: 'Employer', 'own company': 'Own company', 'holiday rental': 'Holiday rental', private: 'Private', other: 'Other' }
export const VIS: Record<Visibility, [string, string]> = {
  private: ['Private', 'Never used in replies – just for you'],
  internal: ['Internal', 'Replies to you, colleagues and your own companies'],
  shareable: ['Shareable', 'May be used in replies to anyone'],
}

let list: KEntry[] | null = null
const subs = new Set<(l: KEntry[]) => void>()
let inflight: Promise<void> | null = null
export function loadKnowledge(force = false) {
  if (inflight && !force) return inflight
  inflight = get<{ entries: KEntry[] }>('knowledge')
    .then(j => { list = j.entries || []; subs.forEach(f => f(list!)) })
    .catch(() => { list = list || []; subs.forEach(f => f(list!)) })
    .finally(() => { inflight = null })
  return inflight
}
export function useKnowledge(): KEntry[] | null {
  const [l, setL] = useState<KEntry[] | null>(list)
  useEffect(() => { subs.add(setL); if (list) setL(list); else loadKnowledge(); return () => { subs.delete(setL) } }, [])
  return l
}
export const scopeIds = (e: KEntry): string[] => Array.isArray(e.scope) ? e.scope : []
export const inProject = (e: KEntry, pid: string) => scopeIds(e).includes(pid)
export const shortDate = (d?: string | null) => d ? new Date(d.length === 10 ? d + 'T12:00' : d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: '2-digit' }) : ''

/** One dialog for the whole app – "Save as knowledge" from a draft, New mail, the Knowledge page, project pages. */
export const openKnowledge = (d: KDraft) => window.dispatchEvent(new CustomEvent('ax-kb', { detail: d }))
