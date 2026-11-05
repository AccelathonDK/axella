// The allow-list for a community report – the same shape setup/reports.py payload() builds on the Mac mini.
// Anything else is rejected, not cleaned: an extra key, a value that doesn't fit, a render that isn't a PNG.
export const CLASSES = ['critical', 'annoying', 'cosmetic', 'missing']
export const CONNECTORS = ['mail', 'imessage', 'whatsapp', 'signal', 'calendar', 'calls', 'linkedin']
export const META_KEYS = ['app_version', 'commit', 'os', 'os_version', 'mac_model', 'ram_tier', 'connectors', 'theme', 'locale']
const TOP = ['v', 'class', 'text', 'route', 'trail', 'errors', 'meta', 'render', 'install', 'reply']
const TRAIL = /^[a-z][a-z0-9_]{0,30}:[a-z0-9_.-]{1,40}$/
const ROUTE = /^[a-z][a-z0-9_:-]{0,39}$/
const FRAME = /^[\w$.<>\[\] -]{0,80}\(?(assets\/)?index-[\w-]+\.js:\d+:\d+\)?$|^[\w$.<> -]{1,80}$/
const META_VALUE = /^[\w .,+()/:-]{0,60}$/
const EMAIL = /^[^@\s<>"]{1,64}@[\w-]+(\.[\w-]+)+$/
export const MAX_RENDER = 400_000          // renders are layout only – 400 kB is plenty

/** Returns null when the payload fits, else the reason. */
export function invalid(p) {
  if (!p || typeof p !== 'object' || Array.isArray(p)) return 'not an object'
  const extra = Object.keys(p).filter(k => !TOP.includes(k))
  if (extra.length) return 'unknown field: ' + extra[0]
  if (p.v !== 1) return 'unknown version'
  if (!CLASSES.includes(p.class)) return 'bad class'
  if (typeof p.text !== 'string' || !p.text.trim() || p.text.length > 4000) return 'bad text'
  if (typeof p.route !== 'string' || !ROUTE.test(p.route)) return 'bad route'
  if (!Array.isArray(p.trail) || p.trail.length > 30 || p.trail.some(t => typeof t !== 'string' || !TRAIL.test(t))) return 'bad trail'
  if (!Array.isArray(p.errors) || p.errors.length > 20) return 'bad errors'
  for (const e of p.errors) {
    if (!e || typeof e !== 'object' || Object.keys(e).some(k => !['message', 'frames', 'source'].includes(k))) return 'bad error entry'
    if (typeof e.message !== 'string' || e.message.length > 300) return 'bad error message'
    if (/[\w.+-]+@[\w-]+\.[\w.-]+|\/Users\/|https?:\/\//.test(e.message)) return 'error message carries a value'
    if (/`|\/\//.test(e.message)) return 'error message carries markup'      // a backtick ends the code span; //host is a link
    if (!Array.isArray(e.frames) || e.frames.length > 8 || e.frames.some(f => typeof f !== 'string' || !FRAME.test(f))) return 'bad frames'
    if (!['app', 'server'].includes(e.source)) return 'bad error source'
  }
  const m = p.meta
  if (!m || typeof m !== 'object' || Array.isArray(m)) return 'bad meta'
  if (Object.keys(m).some(k => !META_KEYS.includes(k)) || META_KEYS.some(k => !(k in m))) return 'meta keys differ from the allow-list'
  for (const k of META_KEYS) {
    const v = m[k]
    if (k === 'connectors') { if (!Array.isArray(v) || v.some(c => !CONNECTORS.includes(c))) return 'bad connectors'; continue }
    if (v !== null && (typeof v !== 'string' || !META_VALUE.test(v) || /\/Users|@|\\/.test(v))) return 'bad meta value: ' + k
  }
  if (p.render !== null) {
    if (typeof p.render !== 'string' || p.render.length > MAX_RENDER * 4 / 3 + 100 || !/^[A-Za-z0-9+/=]+$/.test(p.render)) return 'bad render'
    if (!p.render.startsWith('iVBORw0KGgo')) return 'render is not a PNG'
  }
  if (typeof p.install !== 'string' || !/^[0-9a-f]{32}$/.test(p.install)) return 'bad install token'
  if ('reply' in p && (typeof p.reply !== 'string' || p.reply.length > 120 || !EMAIL.test(p.reply))) return 'bad reply address'
  return null
}
