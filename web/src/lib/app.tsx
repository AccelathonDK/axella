import { createContext, useContext } from 'react'
import type { Ax } from '@/hooks/useAxella'
import type { Ctx, Item, Project } from './types'

export type CtxFilter = 'all' | Ctx
export type SettingsPage = 'schedule' | 'calendar' | 'away' | 'calls' | 'privacy' | 'vips' | 'reminders' | 'mailbox' | 'bookkeeping' | 'reports' | 'notifications' | 'rules' | 'appearance' | 'system' | 'handles'
export type View = { kind: 'today' } | { kind: 'briefing'; focus?: 'cal' } | { kind: 'todo'; tab?: 'tasks' | 'waiting'; only?: 'bills' } | { kind: 'mailbox'; tab?: 'filing' | 'newsletters' | 'cleanup' } | { kind: 'project'; id: string } | { kind: 'projects' } | { kind: 'archive' } | { kind: 'settings'; page?: SettingsPage } | { kind: 'receipts' } | { kind: 'newsletters' } | { kind: 'runs' } | { kind: 'status' } | { kind: 'insights' } | { kind: 'knowledge' } | { kind: 'cleanup' } | { kind: 'search'; q?: string } | { kind: 'contacts' } | { kind: 'calendar' } | { kind: 'activity' } | { kind: 'briefings'; id?: string } | { kind: 'meetings' } | { kind: 'trips' } | { kind: 'meeting'; id: string } | { kind: 'person'; id: string } | { kind: 'notes' } | { kind: 'week' } | { kind: 'setup'; card?: import('./features').CardId }
export interface AppCtx {
  ax: Ax
  ctx: CtxFilter
  inCtx: (x: any) => boolean
  view: View
  go: (v: View, anchor?: string) => void   // anchor: a section id to scroll to after switching
  activeProjects: Project[]
  projectsFor: (it: Item) => Project[]
}
export const App = createContext<AppCtx>(null as any)
export const useApp = () => useContext(App)
