/* The VIP lists in contacts.md (GET vips) – who is a VIP, so items can offer "Add to VIPs" / "Remove from VIPs". */
import { useEffect, useState } from 'react'
import { get } from './api'

export interface Vip { name: string; list: string }
let list: Vip[] | null = null
const subs = new Set<(v: Vip[]) => void>()
export function loadVips() {
  return get<{ vips: Vip[] }>('vips').then(j => { list = j.vips || []; subs.forEach(f => f(list!)) }).catch(() => {})
}
export function useVips() {
  const [v, setV] = useState(list || [])
  useEffect(() => { subs.add(setV); if (!list) loadVips(); return () => { subs.delete(setV) } }, [])
  return v
}
export const isVip = (vips: Vip[], name?: string) => !!name && vips.some(v => v.name.toLowerCase() === name.trim().toLowerCase())
