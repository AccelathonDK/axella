import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)) }
export const IOS = /iPhone|iPad|iPod/.test(navigator.userAgent)
export const pad = (n: number) => String(n).padStart(2, '0')
export const isoDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
export function ago(d: Date) {
  const min = Math.round((Date.now() - d.getTime()) / 60000)
  if (min < 60) return `${Math.max(min, 0)} min ago`
  const h = Math.round(min / 60); if (h < 24) return `${h} h ago`
  return `${Math.round(h / 24)} d ago`
}
export const store = {
  get(k: string, d: string) { try { return localStorage.getItem(k) || d } catch { return d } },
  set(k: string, v: string) { try { localStorage.setItem(k, v) } catch { /* private mode */ } },
}

/* Radix dialogs/sheets treat a tap outside as "close" and block the page under their overlay – our toasts (sonner,
   outside the dialog) must stay tappable: "Undo" on a send, "Try again" … Pass to every dialog/sheet Content. */
export const keepToasts = (e: { target: EventTarget | null; preventDefault: () => void }) => {
  if ((e.target as Element | null)?.closest?.('[data-sonner-toaster]')) e.preventDefault()
}

/* An invisible <input type="date"> over a chip: a click on it only focuses the field in desktop Chrome and Safari –
   open the calendar explicitly (the phones open it by themselves). */
export const openPicker = (e: { currentTarget: HTMLInputElement }) => {
  try { e.currentTarget.showPicker() } catch { /* older browser: the click still focuses the field */ }
}
