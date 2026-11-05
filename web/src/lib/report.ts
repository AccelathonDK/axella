/* Report a problem – what the dashboard records so a report can say how it got there, without any content:
   - a trail of the last action NAMES ("open_route:today", "act:reply_send") – never ids, names or text
   - recent errors as TEMPLATES (values out) with only Axella's own stack frames
   - the privacy render: the current screen re-drawn from a copy of the page where every content string is replaced by
     same-length placeholders (x / 0) and pictures by grey blocks – never a blurred real screenshot
   The Mac mini adds its part and checks everything against the same allow-list again (setup/reports.py). */
import { toPng } from 'html-to-image'

declare const __AX_BUILD__: string
export const APP_VERSION = '1.0.0+' + (typeof __AX_BUILD__ === 'string' ? __AX_BUILD__ : 'dev')

const trail: string[] = []
const errors: { message: string; frames: string[] }[] = []
const clean = (s: string) => s.toLowerCase().replace(/[^a-z0-9_.-]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40) || 'x'
export function track(kind: string, name: string) {
  trail.push(clean(kind).slice(0, 30) + ':' + clean(name))
  if (trail.length > 40) trail.shift()
}

/* values out: the same rules as setup/reports.py template() */
export function template(msg: string) {
  return String(msg || '').slice(0, 500)
    .replace(/https?:\/\/\S+/g, '{url}')
    .replace(/[\w.+-]+@[\w-]+(\.[\w-]+)+/g, '{email}')
    .replace(/(\/Users|\/home|\/private|\/var|~)\/\S*/g, '{path}')
    .replace(/"[^"]*"|“[^”]*”|'[^']*'|‘[^’]*’/g, '{text}')
    .replace(/\+?\d[\d\s().-]{5,}\d/g, '{number}')
    .replace(/\b\d+\b/g, '{n}')
    .replace(/\b[0-9a-f]{12,}\b/gi, '{id}')
    .replace(/\b[A-ZÆØÅÄÖÜ][a-zæøåäöüé]+ [A-ZÆØÅÄÖÜ][a-zæøåäöüé]+\b/g, '{name}')
    .slice(0, 300)
}
function ownFrames(stack?: string) {
  return String(stack || '').split('\n').map(l => l.trim())
    .map(l => { const m = l.match(/(?:at\s+([\w$.<>]+)\s+\()?\S*?(assets\/index-[\w-]+\.js:\d+:\d+)\)?/); return m ? `at ${m[1] || 'anonymous'} (${m[2]})` : null })
    .filter(Boolean).slice(0, 8) as string[]
}
function addError(message: string, stack?: string) {
  errors.push({ message: template(message), frames: ownFrames(stack) })
  if (errors.length > 20) errors.shift()
}

let installed = false
export function installReportCapture() {
  if (installed) return
  installed = true
  addEventListener('error', e => addError(e.message || 'error', (e.error as Error | undefined)?.stack))
  addEventListener('unhandledrejection', e => { const r = e.reason as Error | undefined; addError(r?.message || String(r), r?.stack) })
  const ce = console.error.bind(console)
  console.error = (...a: unknown[]) => { try { const err = a.find(x => x instanceof Error) as Error | undefined; addError(err?.message || a.map(String).join(' '), err?.stack) } catch { /* never break logging */ } ce(...a) }
}

export function snapshot() {
  return {
    trail: [...trail], errors: errors.map(e => ({ ...e })),
    meta: {
      app_version: APP_VERSION, os: /Mac/.test(navigator.platform) ? 'macOS' : /iPhone|iPad/.test(navigator.userAgent) ? 'iOS' : /Android/.test(navigator.userAgent) ? 'Android' : /Win/.test(navigator.platform) ? 'Windows' : 'other',
      theme: document.documentElement.classList.contains('dark') ? 'dark' : 'light', locale: navigator.language.slice(0, 10),
    },
  }
}

/* ---------- the privacy render ---------- */
// Words of the app itself that may stay readable in a short label ("Still open", "By end of day"). A text with any other word is
// content and is replaced – safe by default.
const KEEP_WORDS = new Set(['Today', 'Briefing', 'To', 'do', 'Calendar', 'Mailbox', 'Receipts', 'Search', 'Topic', 'briefs', 'Knowledge', 'Insights',
  'Older', 'digests', 'Projects', 'All', 'projects', 'Archived', 'Settings', 'Done', 'Later', 'Send', 'Reply', 'Task', 'Undo', 'Open', 'Close', 'Cancel',
  'Save', 'Edit', 'Delete', 'Attach', 'More', 'Filing', 'Newsletters', 'Cleanup', 'Urgent', 'now', 'Before', 'noon', 'By', 'end', 'of', 'day', 'Still',
  'open', 'FYI', 'Waiting', 'for', 'replies', 'suggestions', 'Calls', 'Private', 'Work', 'Listen', 'Ask', 'Axella', 'Related', 'Replying', 'The', 'message',
  'Drafted', 'reply', 'by', 'As', 'in', 'Mail', 'Plain', 'text', 'YOUR', 'DAY', 'TIDY', 'LIBRARY', 'PROJECTS', 'AXELLA', 'RELATED', 'REPLYING', 'TO',
  'Load', 'pictures', 'Show', 'the', 'whole', 'Remind', 'me', 'if', 'no', 'answer', 'days', 'day', 'Active', 'Unsubscribed', 'Kept', 'Senders',
  'Unsubscribe', 'My', 'tasks', 'on', 'others', 'Move', 'Other', 'folder', 'contacts', 'Notify', 'Discreet', 'Report', 'a', 'problem', 'Run', 'sweep',
  'Re-scan', 'inboxes…', 'New', 'Getting', 'started', 'Runs', 'and', 'logs', 'Sent', 'Handled', 'Noon', 'Open', 'Calendar', 'Waiting', 'Notes', 'Spoken',
  'MESSAGE', 'THE', 'DRAFTED', 'PRIVATE', 'BRIEFING', 'TODAY', 'Work', 'Private', 'Mails', 'Never', 'opened', 'mails'])
const isUi = (s: string) => {
  const t = s.trim()
  if (!t) return true
  // a short label made only of app words ("Still open", "By end of day") stays; anything with other words goes
  return t.length <= 40 && t.split(/[\s·–—:]+/).filter(Boolean).every(w => KEEP_WORDS.has(w))   // numbers (counts, times) are content too
}
const mask = (s: string) => s.replace(/\p{L}/gu, c => c === c.toUpperCase() && c !== c.toLowerCase() ? 'X' : 'x').replace(/\p{N}/gu, '0')

/** A copy of `root` with every content string replaced – exported for the tests. */
export function privacyClone(root: HTMLElement): HTMLElement {
  const copy = root.cloneNode(true) as HTMLElement
  const walker = document.createTreeWalker(copy, NodeFilter.SHOW_TEXT)
  const texts: Text[] = []
  for (let n = walker.nextNode(); n; n = walker.nextNode()) texts.push(n as Text)
  for (const t of texts) if (!isUi(t.data)) t.data = mask(t.data)
  copy.querySelectorAll('*').forEach(el => {
    for (const a of ['title', 'aria-label', 'placeholder', 'alt', 'href', 'value', 'data-tip', 'srcdoc', 'download']) {
      if (el.hasAttribute(a) && !(a === 'aria-label' && isUi(el.getAttribute(a) || ''))) el.removeAttribute(a)
    }
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) { el.value = ''; el.textContent = el instanceof HTMLTextAreaElement ? mask(el.textContent || '') : '' }
  })
  copy.querySelectorAll('[data-sonner-toaster], section[aria-label^="Notifications"]').forEach(el => el.remove())   // our own toasts
  // pictures, frames and canvases: grey blocks of the same size
  copy.querySelectorAll('img, iframe, canvas, video, picture, image').forEach(el => {
    const r = (el as HTMLElement).getBoundingClientRect?.() || { width: 0, height: 0 }
    const b = document.createElement('div')
    b.style.cssText = `display:inline-block;width:${Math.round(r.width) || 40}px;height:${Math.round(r.height) || 40}px;background:#8888;border-radius:4px`
    el.replaceWith(b)
  })
  // what a real textarea shows lives in its value, not its text: copy the masked value back as text
  root.querySelectorAll('textarea').forEach((ta, i) => { const c = copy.querySelectorAll('textarea')[i] as HTMLTextAreaElement | undefined; if (c) { c.value = mask((ta as HTMLTextAreaElement).value); c.textContent = c.value } })
  return copy
}

async function draw(node: HTMLElement, width: number, height: number, place = false) {
  // skipFonts: the app's own fonts are bundled; embedding them needs a <base> the page's CSP (rightly) forbids – the render
  // falls back to the system font, which is fine for a layout picture
  const opts = { cacheBust: false, pixelRatio: 1, width, height, backgroundColor: getComputedStyle(document.body).backgroundColor, skipFonts: true,
    ...(place ? { style: { position: 'relative', left: '0px', top: '0px' } } : {}) }
  let url = await toPng(node, opts)
  if (url.length > 1_900_000) url = await toPng(node, { ...opts, pixelRatio: 0.5 })
  return url
}

/** The privacy render of the whole window (the report dialog itself left out). */
export async function privacyRender(): Promise<string> {
  const root = document.getElementById('root')!
  const copy = privacyClone(root)
  const host = document.createElement('div')
  host.setAttribute('aria-hidden', 'true')
  // transform: fixed-position sheets inside the copy are placed relative to this box, not the window
  host.style.cssText = `position:fixed;left:-${innerWidth + 50}px;top:0;width:${innerWidth}px;height:${innerHeight}px;overflow:hidden;pointer-events:none;transform:translateZ(0)`
  copy.style.width = innerWidth + 'px'
  host.setAttribute('data-ax-privacy', '')
  host.appendChild(copy)
  // copies of open sheets would replay their opening animation from opacity 0 – drawn as they are now instead
  const still = document.createElement('style')
  still.textContent = '[data-ax-privacy] *, [data-ax-privacy] *::before, [data-ax-privacy] *::after { animation: none !important; transition: none !important }'
  document.head.appendChild(still)
  document.body.appendChild(host)
  // sheets and dialogs open on top of the page (outside #root): masked too, unless it's the report dialog
  Array.from(document.body.children).forEach(el => {
    if (el === root || el === host || !(el instanceof HTMLElement) || el.tagName === 'SCRIPT' || el.hasAttribute('data-sonner-toaster') || el.querySelector('[data-report-dialog], section[aria-label^="Notifications"]')) return
    if (getComputedStyle(el).display === 'none') return
    copy.appendChild(privacyClone(el))              // a sheet or dialog open on top: drawn on top in the copy too
  })
  try { return await draw(copy, innerWidth, innerHeight) } finally { host.remove(); still.remove() }
}

/** Developer mode only: the real screen, for the owner's own reports/ folder. */
export async function realRender(): Promise<string> {
  const hide = document.querySelectorAll<HTMLElement>('[data-sonner-toaster], section[aria-label^="Notifications"]')
  hide.forEach(h => (h.style.visibility = 'hidden'))
  try { return await draw(document.body, innerWidth, innerHeight) } finally { hide.forEach(h => (h.style.visibility = '')) }
}

// for the automated privacy test (setup/tests / web tests): the same function the render uses
;(window as unknown as { __axReport?: unknown }).__axReport = { privacyClone, privacyRender: () => privacyRender(), realRender: () => realRender() }
