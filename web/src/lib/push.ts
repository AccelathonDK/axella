import { get, post } from './api'
import { IOS } from './utils'

export const standalone = matchMedia('(display-mode: standalone)').matches || (navigator as any).standalone === true
const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
let reg: ServiceWorkerRegistration | null = null

export async function registerSW() {
  if (!('serviceWorker' in navigator)) return false
  try { reg = await navigator.serviceWorker.register('sw.js', { scope: './' }) } catch { /* not over https */ }
  return true
}
export async function pushOn() {
  try { return !!(reg && await reg.pushManager.getSubscription()) && Notification.permission === 'granted' } catch { return false }
}
const b64 = (s: string) => { const p = '='.repeat((4 - s.length % 4) % 4); const r = atob((s + p).replace(/-/g, '+').replace(/_/g, '/')); return Uint8Array.from(r, c => c.charCodeAt(0)) }

/** Turn on notifications (or send a test when already on). Returns a message for a toast. */
export async function bell(on: boolean): Promise<string> {
  if (on) return 'Test: ' + (await post('push_test', {})).result
  if (IOS && !standalone) return 'Open Axella from your Home Screen first, then tap the bell'
  if (!supported) return 'This browser does not support notifications'
  if (await Notification.requestPermission() !== 'granted') return 'Notifications not allowed – check Settings → Notifications'
  const k = await get<{ public_key: string }>('vapid')
  reg = reg || await navigator.serviceWorker.ready
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(k.public_key) })
  const ua = navigator.userAgent, device = /iPad/.test(ua) ? 'iPad' : /iPhone/.test(ua) ? 'iPhone' : /Mac/.test(ua) ? 'Mac' : 'Browser'
  await post('push_subscribe', { subscription: sub.toJSON(), device })
  return 'Notifications on – ' + (await post('push_test', {})).result
}
