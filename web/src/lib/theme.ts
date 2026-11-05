/* Light · Dark · System (design system "Axella" Themes): System is the default and follows the OS. */
import { useEffect, useState } from 'react'
import { store } from '@/lib/utils'
export type Theme = 'auto' | 'light' | 'dark'
const mq = matchMedia('(prefers-color-scheme: dark)')
const subs = new Set<(t: Theme) => void>()
let cur = (store.get('axella-theme', 'auto') as Theme)
function apply() { document.documentElement.classList.toggle('dark', cur === 'dark' || (cur === 'auto' && mq.matches)) }
apply(); mq.addEventListener('change', apply)
export function setTheme(t: Theme) { cur = t; store.set('axella-theme', t); apply(); subs.forEach(f => f(t)) }
export function useTheme(): [Theme, (t: Theme) => void] {
  const [t, setT] = useState(cur)
  useEffect(() => { subs.add(setT); return () => { subs.delete(setT) } }, [])
  return [t, setTheme]
}
