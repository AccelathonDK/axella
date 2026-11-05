/* Replies saved to Drafts from the dashboard (GET drafts, state/drafts.json): item id → the draft's Message-ID, so
   "Open in Mail" can open that exact draft with a message:// link (Mail on Mac and iPhone understand them). */
import { useEffect, useState } from 'react'
import { get } from './api'

export interface SavedDraft { draft_id: string; account: string; reply_to: string; title?: string; saved: string }
let map: Record<string, SavedDraft> | null = null
const subs = new Set<(m: Record<string, SavedDraft>) => void>()
export function loadDrafts() {
  return get<{ drafts: Record<string, SavedDraft> }>('drafts').then(j => { map = j.drafts || {}; subs.forEach(f => f(map!)) }).catch(() => {})
}
export function useDrafts() {
  const [m, setM] = useState(map || {})
  useEffect(() => { subs.add(setM); if (!map) loadDrafts(); return () => { subs.delete(setM) } }, [])
  return m
}
export const draftLink = (id?: string | null) => id ? 'message://' + encodeURIComponent('<' + id.replace(/^<|>$/g, '') + '>') : null
