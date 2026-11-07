/* Notes (setup/notes.py): Axella's own notes, owner only. One cached "may I see notes" probe, the chip map for the digest
   Today shows, and openNote() – any screen can open the editor (new, or an existing note) with links filled in. */
import { useEffect, useState } from 'react'
import { Unreachable, get } from './api'
import type { Item } from './types'

export type LinkKind = 'person' | 'project' | 'trip' | 'meeting' | 'mail' | 'chat'
export interface NoteLink { kind: LinkKind; ref: string; label?: string; keys?: string[]; account?: string; thread?: string; date?: string }
export interface Note { id: string; title: string; text?: string; snippet?: string; created?: string; updated?: string; pinned?: boolean
  ctx?: 'work' | 'private' | null; links: NoteLink[]; remind?: boolean }
export interface Chip { id: string; title: string; more: number }
export interface Chips { items: Record<string, Chip>; meetings: Record<string, Chip>; trips: Record<string, Chip> }

export const NOTE_EVENT = 'ax-note'
export const NOTES_CHANGED = 'ax-notes'
/** open the note editor: an existing note (id), or a new one with these links */
export const openNote = (o: { id?: string; links?: NoteLink[]; text?: string }) => window.dispatchEvent(new CustomEvent(NOTE_EVENT, { detail: o }))
export const notesChanged = () => { chipCache = null; window.dispatchEvent(new Event(NOTES_CHANGED)) }

/* owner only: the first GET notes tells (403 for anyone else) */
let owner: boolean | null = null, probing: Promise<boolean | null> | null = null
export function useNotesOwner(apiOk: boolean) {
  const [v, setV] = useState<boolean | null>(owner)
  useEffect(() => {
    if (!apiOk || owner !== null) return
    probing = probing || get('notes').then(() => (owner = true), e => e instanceof Unreachable ? null : (owner = false)).finally(() => { probing = null })
    probing.then(setV)
  }, [apiOk])
  return v                     // null while asking
}

/* the chips for the digest on screen: matched on the Mac mini, never written into the digest */
let chipCache: { name: string; chips: Chips } | null = null
let chipFlight: { name: string; p: Promise<Chips> } | null = null   // one request for every row on the page
export function useNoteChips(digest: string | undefined, on: boolean): Chips | null {
  const [c, setC] = useState<Chips | null>(chipCache && chipCache.name === digest ? chipCache.chips : null)
  useEffect(() => {
    if (!on || !digest) return
    let live = true
    const name = digest.replace(/^.*\//, '').replace(/\.md$/, '.json')
    const load = () => {
      if (!chipFlight || chipFlight.name !== digest) chipFlight = { name: digest, p: get<Chips>('note_chips?digest=' + encodeURIComponent(name))
        .then(j => (chipCache = { name: digest, chips: { items: j.items || {}, meetings: j.meetings || {}, trips: j.trips || {} } }).chips)
        .finally(() => { setTimeout(() => { chipFlight = null }, 0) }) }
      chipFlight.p.then(x => { if (live) setC(x) }, () => {})
    }
    if (!chipCache || chipCache.name !== digest) load()
    else setC(chipCache.chips)
    window.addEventListener(NOTES_CHANGED, load)
    return () => { live = false; window.removeEventListener(NOTES_CHANGED, load) }
  }, [digest, on])
  return c
}

/** a note from an item: linked to its person (every identity it shows) and its mail or chat thread */
export function itemLinks(it: Item): NoteLink[] {
  const out: NoteLink[] = []
  const addr = (it.from?.address || '').trim()
  if (addr) out.push({ kind: 'person', ref: addr.toLowerCase(), label: it.from?.name || addr, keys: [addr] })
  if (it.channel === 'mail' && it.message_id) out.push({ kind: 'mail', ref: it.message_id, label: it.subject || it.headline || 'Mail', account: it.account, thread: it.subject || '', keys: addr ? [addr] : [] })
  else if (it.channel && it.channel !== 'mail' && addr) out.push({ kind: 'chat', ref: it.channel + ':' + addr.toLowerCase(), label: (it.from?.name || addr) + ' · ' + it.channel, account: it.channel, thread: '', keys: [addr] })
  return out
}
export const LINK_LABEL: Record<LinkKind, string> = { person: 'Person', project: 'Project', trip: 'Trip', meeting: 'Meeting', mail: 'Mail', chat: 'Chat' }
