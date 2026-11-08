/* Targets and Now · Next · Later (setup/planner.py): project states, targets, people on a project and the day plan.
   Owner only (GET plan answers 403 for anyone else). One shared request per screen; any change reloads it. */
import { useEffect, useState } from 'react'
import { get } from './api'

export type PState = 'active' | 'waiting' | 'paused' | 'running' | 'done'
export const STATES: { id: PState; label: string; hint: string }[] = [
  { id: 'active', label: 'Active', hint: 'Being worked on – can be suggested as today\'s focus' },
  { id: 'waiting', label: 'Waiting', hint: 'Can\'t move until something happens – never suggested' },
  { id: 'paused', label: 'Paused', hint: 'Set aside on purpose, maybe until a date – never suggested' },
  { id: 'running', label: 'Running', hint: 'No project work, but things still arrive – mail still tagged' },
  { id: 'done', label: 'Done', hint: 'Finished – targets closed; archive it when you\'re ready' },
]
/** state colours from the design system – never dawn (urgent only) */
export const STATE_COLOR: Record<PState, string> = {
  active: 'var(--ax-accent)', waiting: 'var(--ax-project-4)', paused: 'var(--ax-ink-3)', running: 'var(--ax-project-2)', done: 'var(--ax-success)',
}
export interface Waiting { kind: 'person' | 'item' | 'task'; ref: string; label: string }
export interface Entry { id: string; text: string; done?: boolean; mins?: number | null; day?: string | null; src?: string; waits?: string | null; waits_label?: string | null }
export interface Target {
  id: string; kind: 'date' | 'period' | 'idea'; title: string; done_means?: string; date?: string; from?: string; to?: string; status: 'open' | 'done'
  brief?: string | null; steps?: Entry[]; questions?: Entry[]; go?: Entry[]; experiments?: Entry[]; progress: string; due?: string | null
  signals?: { url: string; title: string; for: string; at?: string }[]
}
export interface ProjPerson {
  key: string; pid?: string | null; name: string; role?: string; star?: boolean; source: 'manual' | 'suggested' | 'auto'; why?: string
  emails?: string[]; phones?: string[]; private?: boolean; last?: Record<string, string>; to_answer?: number; waiting?: number; promises?: number
  mails?: number; of?: number
}
export interface ProjectPlan {
  id: string; state: PState; since?: string; waiting_for?: Waiting | null; paused_until?: string | null
  people: ProjPerson[]; targets: Target[]; step_ideas: { text: string; src: string }[]; briefings: { id: string; name: string }[]
}
export interface PlanItem { key: string; pid?: string; project?: string; title: string; mins?: number; target?: string; where?: string; due?: string
  world?: string; start?: string; end?: string; why?: string; when?: string; link?: string }
export interface DayPlan { date: string; focus: string[]; none: boolean; now: PlanItem | null; next: PlanItem[]; later: PlanItem[]; done: PlanItem[]; free: number; buffer: number }
export interface Suggestion { key: string; pid: string; kind: 'back' | 'resume' | 'idle' | 'done'; text: string; yes: string; no: string }
export interface Light { state: PState; since?: string; waiting_for?: Waiting | null; paused_until?: string | null; people?: string[]
  targets: { id: string; kind: string; title: string; status: string; due?: string | null; progress: string }[] }
export interface Plan {
  enabled: boolean; settings: { enabled: boolean; buffer: number; idle_weeks: number }; projects: Record<string, Light>
  suggestions?: Suggestion[]; question?: { projects: string[]; reason: string }; chosen?: boolean; plan?: DayPlan
  calendar_error?: string | null; checks?: { key: string; pid: string; text: string }[]
}
export interface WeekDay { date: string; past?: boolean; focus: string[]; none?: boolean; items: PlanItem[]; targets: { pid: string; project: string; title: string }[]
  private: boolean; meeting_mins?: number; free?: number }
export interface Week { enabled: boolean; days: WeekDay[]; heads_up: { key: string; pid: string; text: string; move?: { key: string; label: string } } | null; calendar_error?: string | null }

export const PLAN_CHANGED = 'ax-plan'
export const planChanged = () => { cache = null; window.dispatchEvent(new Event(PLAN_CHANGED)) }

let cache: { at: number; p: Promise<Plan | null> } | null = null
/** the shared plan (null for anyone but the owner, or while the Mac mini doesn't answer) */
export function usePlan(on = true) {
  const [p, setP] = useState<Plan | null>(null)
  useEffect(() => {
    if (!on) return
    let live = true
    const load = () => {
      if (!cache || Date.now() - cache.at > 60e3) cache = { at: Date.now(), p: get<Plan>('plan').catch(() => null) }
      cache.p.then(x => { if (live) setP(x) })
    }
    load()
    window.addEventListener(PLAN_CHANGED, load)
    const t = setInterval(() => { if (document.visibilityState === 'visible') { cache = null; load() } }, 5 * 60e3)
    return () => { live = false; window.removeEventListener(PLAN_CHANGED, load); clearInterval(t) }
  }, [on])
  return p
}

export const stateOf = (plan: Plan | null, pid: string): PState => plan?.projects[pid]?.state || 'active'
export const fmtMins = (m: number) => { const h = Math.floor(m / 60), r = m % 60; return h ? (r ? `${h} h ${r} min` : `${h} h`) : `${r} min` }
export const dayLabel = (iso: string, short = false) => new Date(iso + 'T12:00').toLocaleDateString('en-GB', short ? { weekday: 'short', day: 'numeric' } : { weekday: 'short', day: 'numeric', month: 'short' })
export const TARGET_LABEL = { date: 'Date', period: 'Period', idea: 'Idea · research' } as const
export function targetWhen(t: { kind: string; date?: string; from?: string; to?: string }) {
  if (t.kind === 'date' && t.date) {
    const days = Math.round((new Date(t.date + 'T12:00').getTime() - new Date(new Date().toDateString() + ' 12:00').getTime()) / 864e5)
    return `${dayLabel(t.date)} · ${days === 0 ? 'today' : days === 1 ? 'tomorrow' : days > 1 ? days + ' days' : Math.abs(days) + ' days ago'}`
  }
  if (t.kind === 'period' && t.from && t.to) return `${dayLabel(t.from)} – ${dayLabel(t.to)}`
  return 'No date'
}
