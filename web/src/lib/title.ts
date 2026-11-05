/* Tab title + favicon badge + "new digest" flashing (works outside React so the timer survives re-renders) */
let attention = 0, urgent = 0, when: Date | undefined, unseen = document.hidden || !document.hasFocus()
let timer: number | null = null, flashOn = false

function favicon(n: number, urg: boolean) {
  const c = document.createElement('canvas'); c.width = c.height = 64; const x = c.getContext('2d')!
  const g = x.createLinearGradient(0, 0, 64, 64); g.addColorStop(0, '#3a3a3f'); g.addColorStop(1, '#121214')
  x.fillStyle = g; x.beginPath(); x.roundRect(1, 1, 62, 62, 14); x.fill()
  // the Axella mark (same geometry as public/icons/mark.svg, 100-unit box scaled to 64 px)
  x.save(); x.scale(0.64, 0.64); x.translate(50, 50); x.scale(1.22, 1.22); x.translate(-50, -50)
  x.beginPath(); x.rect(0, 0, 100, 75.5); x.clip()
  x.strokeStyle = '#fff'; x.lineWidth = 6.5; x.lineJoin = 'miter'; x.miterLimit = 12
  x.beginPath(); x.moveTo(71, 79.5); x.lineTo(33, 41.5); x.lineTo(50, 24.5); x.lineTo(67, 41.5); x.lineTo(29, 79.5); x.stroke()
  x.fillStyle = '#fff'; x.beginPath(); x.arc(50, 41.5, 3.1, 0, Math.PI * 2); x.fill()
  x.restore()
  if (n) {
    x.fillStyle = urg ? '#dc3545' : '#fd7e14'; x.beginPath(); x.arc(46, 18, 17, 0, Math.PI * 2); x.fill()
    x.fillStyle = '#fff'; x.font = 'bold 22px -apple-system,system-ui,sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillText(n > 9 ? '9+' : String(n), 46, 19)
  }
  let l = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
  if (!l) { l = document.createElement('link'); l.rel = 'icon'; document.head.appendChild(l) }
  l.href = c.toDataURL('image/png')
}
export function digestTime(d = when) {
  if (!d) return ''
  const hm = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  return d.toDateString() === new Date().toDateString() ? hm : d.toLocaleDateString('en-GB', { weekday: 'short' }) + ' ' + hm
}
const base = () => (urgent ? '⚠ ' : '') + (attention ? `(${attention}) ` : '') + 'Axella' + (when ? ' · ' + digestTime() : '')

function paint() {
  if (unseen && timer === null) {
    timer = window.setInterval(() => {
      flashOn = !flashOn
      document.title = flashOn ? `🔔 New digest ${digestTime()}` : '● ' + base()
      favicon(flashOn ? 0 : attention, !!urgent)
    }, 1000)
  }
  if (!unseen && timer !== null) { clearInterval(timer); timer = null; flashOn = false }
  if (!flashOn) { document.title = (unseen ? '● ' : '') + base(); favicon(attention, !!urgent) }
}
/* The number on the Home Screen icon (iPhone app, installed desktop app) – the same count as the title. The Mac mini
   sets it with each digest push too (sw.js), so it is right before the app is opened. */
let lastBadge = -1
function appBadge(n: number) {
  if (n === lastBadge) return
  const nav = navigator as Navigator & { setAppBadge?: (n?: number) => Promise<void>; clearAppBadge?: () => Promise<void> }
  if (!nav.setAppBadge) return
  lastBadge = n
  ;(n > 0 ? nav.setAppBadge(n) : nav.clearAppBadge!()).catch(() => { /* no permission yet – fine */ })
}
export function setTitle(n: number, u: number, d?: Date) { attention = n; urgent = u; when = d; paint(); appBadge(n) }
export function markUnseen() { if (document.hidden || !document.hasFocus()) { unseen = true; paint(); return true } return false }
function markSeen() { if (unseen && !document.hidden && document.hasFocus()) { unseen = false; paint() } }
document.addEventListener('visibilitychange', markSeen)
addEventListener('focus', markSeen)
addEventListener('pointerdown', markSeen)
