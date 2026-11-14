/* What Axella handles (setup/features.py): the 7 cards, the switches behind each card's More, per person. The owner's
   switches are the installation's; anyone else only narrows them for themselves. Unknown or unreachable = on, so
   nothing disappears while the Mac mini doesn't answer. */
import { useEffect, useState } from 'react'
import { get, post } from './api'

export type CardId = 'messages' | 'calendar' | 'projects' | 'trips' | 'money' | 'briefs' | 'voice'
export interface Feature { id: string; card: CardId; label: string; desc: string; needs: string[]; on: boolean; owner_off: boolean; owner_only: boolean }
export interface CardInfo {
  id: CardId; title: string; color: string; default: boolean; minutes: number; line: string; needs: string; claude: string
  features: string[]; n_on: number; n: number; on: boolean; owner_off: boolean; not_set_up: boolean; includes: string
}
export interface About { name: string; language: 'en' | 'da'; work_hours: { days: number[]; from: string; to: string }; mode: 'separate' | 'mixed' | 'private' | null; digest_time?: string }
export interface FeaturesView {
  features: Record<string, Feature>; cards: CardInfo[]; core: string; owner: boolean; broken: boolean; about: About | null
  setup: { needed: boolean; progress: { step?: string; chosen?: CardId[]; skipped?: CardId[]; done?: boolean } | null; first_visit: boolean; review: boolean }
}

export const FEATURES_CHANGED = 'ax-features'
let cache: { at: number; p: Promise<FeaturesView | null> } | null = null
export const featuresChanged = () => { cache = null; window.dispatchEvent(new Event(FEATURES_CHANGED)) }

export function useFeatures(on = true) {
  const [v, setV] = useState<FeaturesView | null | undefined>(cache ? undefined : undefined)
  useEffect(() => {
    if (!on) return
    let live = true
    const load = () => {
      if (!cache || Date.now() - cache.at > 5 * 60e3) cache = { at: Date.now(), p: get<FeaturesView>('features').catch(() => null) }
      cache.p.then(x => { if (live) setV(x) })
    }
    load()
    window.addEventListener(FEATURES_CHANGED, load)
    return () => { live = false; window.removeEventListener(FEATURES_CHANGED, load) }
  }, [on])
  return v
}

/** is this feature on for me? (no answer yet / unknown feature = on) */
export const isOn = (v: FeaturesView | null | undefined, id: string) => !v || !v.features[id] || v.features[id].on
export const anyOn = (v: FeaturesView | null | undefined, ...ids: string[]) => ids.some(id => isOn(v, id))

export async function featAct<T = any>(action: string, body: object): Promise<T> {
  const r = await post<{ result: T }>(action, body)
  featuresChanged()
  return r.result
}

/** the page that shows which feature (for the quiet "This feature is off" page) */
export const VIEW_FEATURE: Record<string, string[]> = {
  trips: ['trips'], meetings: ['meeting_prep'], meeting: ['meeting_prep'], briefings: ['topic_briefs'], knowledge: ['knowledge'],
  receipts: ['receipts', 'bills', 'subscriptions', 'renewals'], projects: ['projects'], project: ['projects'],
  person: ['people'], mailbox: ['filing', 'mail_tidy'],
}
