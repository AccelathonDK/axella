// axella.dev report intake – a Cloudflare Worker (D1 queue, R2 for renders).
//   POST /api/report                 a community report (allow-list in schema.js) → {ok, code, status_url}
//   GET  /api/report/status/:code    how it is doing → {ok, status, issue_url}
//   GET  /api/triage                 (maintainer) the queue                      Authorization: Bearer TRIAGE_TOKEN
//   GET  /api/triage/:id/render      (maintainer) a report's privacy render
//   POST /api/triage/:id/act         (maintainer) {action: approve|discard|merge|edit, title, text, class, into}
//   GET  /r/:id.png                  the render of an APPROVED report (linked from its public GitHub issue)
// Privacy: no IP address is read or stored (Cloudflare's own logs are off in wrangler.toml); the install token is stored
// only as a hash and used for rate limiting; the optional reply address sits in its own table and is never published.
import { invalid, MAX_RENDER } from './schema.js'

const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } })
const PER_INSTALL_PER_DAY = 10, ALL_PER_DAY = 500

async function sha256(s) {
  const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s))
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, '0')).join('')
}
function code() {               // 8 characters, no look-alikes
  const a = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789', r = crypto.getRandomValues(new Uint8Array(8))
  return [...r].map(x => a[x % a.length]).join('')
}
function sameToken(a, b) {      // constant time
  if (!a || !b || a.length !== b.length) return false
  let d = 0
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i)
  return d === 0
}
const b64bytes = s => Uint8Array.from(atob(s), c => c.charCodeAt(0))

async function putRender(env, id, b64) {
  const bytes = b64bytes(b64)
  if (bytes.length > MAX_RENDER) throw new Error('render too large')
  if (env.RENDERS) await env.RENDERS.put(`renders/${id}.png`, bytes, { httpMetadata: { contentType: 'image/png' } })
  else await env.DB.prepare('UPDATE reports SET render = ? WHERE id = ?').bind(bytes, id).run()
}
async function getRender(env, id) {
  if (env.RENDERS) { const o = await env.RENDERS.get(`renders/${id}.png`); return o ? await o.arrayBuffer() : null }
  const r = await env.DB.prepare('SELECT render FROM reports WHERE id = ?').bind(id).first()
  return r?.render ? new Uint8Array(r.render) : null
}
const png = data => new Response(data, { headers: { 'Content-Type': 'image/png', 'Cache-Control': 'private, max-age=300', 'X-Content-Type-Options': 'nosniff',
  'Content-Security-Policy': "default-src 'none'; sandbox" } })

export async function receive(req, env) {
  const len = Number(req.headers.get('Content-Length') || 0)
  if (len > 3_000_000) return json({ ok: false, error: 'too large' }, 413)
  let p
  try { p = await req.json() } catch { return json({ ok: false, error: 'not JSON' }, 400) }
  const why = invalid(p)
  if (why) return json({ ok: false, error: why }, 400)
  const day = new Date().toISOString().slice(0, 10), who = await sha256('install:' + p.install)
  const mine = await env.DB.prepare('SELECT n FROM rate WHERE who = ? AND day = ?').bind(who, day).first()
  const all = await env.DB.prepare("SELECT SUM(n) n FROM rate WHERE day = ?").bind(day).first()
  if ((mine?.n || 0) >= PER_INSTALL_PER_DAY || (all?.n || 0) >= ALL_PER_DAY) return json({ ok: false, error: 'too many reports today – try tomorrow' }, 429)
  const id = crypto.randomUUID(), c = code()
  await env.DB.batch([
    env.DB.prepare('INSERT INTO rate (who, day, n) VALUES (?, ?, 1) ON CONFLICT(who, day) DO UPDATE SET n = n + 1').bind(who, day),
    env.DB.prepare(`INSERT INTO reports (id, code, created, class, text, route, trail, errors, meta, status, install_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)`)
      .bind(id, c, new Date().toISOString(), p.class, p.text, p.route, JSON.stringify(p.trail), JSON.stringify(p.errors), JSON.stringify(p.meta), who),
    ...(p.reply ? [env.DB.prepare('INSERT INTO replies (report_id, address) VALUES (?, ?)').bind(id, p.reply)] : []),
  ])
  if (p.render) await putRender(env, id, p.render)
  const base = env.PUBLIC_BASE || new URL(req.url).origin
  return json({ ok: true, code: c, status_url: `${base}/api/report/status/${c}` })
}

async function status(env, c) {
  const r = await env.DB.prepare('SELECT status, issue_url FROM reports WHERE code = ?').bind(c).first()
  return r ? json({ ok: true, status: r.status, issue_url: r.issue_url || null }) : json({ ok: false, error: 'unknown code' }, 404)
}

/** The reporter's words are untrusted and the issue is public: no live @mention, HTML, link or image. They go in a
    fenced block (fence longer than any run of backticks or tildes inside), with @ broken by a zero-width space too. */
export function safeText(text) {
  const t = String(text || '').replace(/@/g, '@\u200b').replace(/\r/g, '')
  const longest = Math.max(2, ...[...t.matchAll(/`+|~+/g)].map(m => m[0].length))
  const fence = '`'.repeat(longest + 1)
  return fence + 'text\n' + t + '\n' + fence
}
/** A one-line title: no mention, no HTML. */
export function safeTitle(t) {
  return String(t || '').replace(/[\r\n]+/g, ' ').replace(/@/g, '@\u200b').replace(/</g, '‹').replace(/>/g, '›').slice(0, 120)
}

export function issueBody(r, base) {
  const meta = JSON.parse(r.meta || '{}'), trail = JSON.parse(r.trail || '[]'), errors = JSON.parse(r.errors || '[]')
  const rows = Object.entries(meta).map(([k, v]) => `| ${k} | ${Array.isArray(v) ? v.join(', ') : v ?? '–'} |`).join('\n')
  return [safeText(r.text), '', r.has_render ? `![Privacy render – layout only, every text replaced](${base}/r/${r.id}.png)` : '',
    '', '| | |', '|---|---|', rows, '', `**Route:** \`${r.route}\``, '',
    trail.length ? '<details><summary>Last actions</summary>\n\n' + trail.map(t => '- `' + t + '`').join('\n') + '\n</details>' : '',
    errors.length ? '<details><summary>Errors</summary>\n\n' + errors.map(e => '- ' + e.source + ': `' + e.message + '`' + (e.frames?.length ? '\n  ' + e.frames.map(f => '`' + f + '`').join(' ') : '')).join('\n') + '\n</details>' : '',
    '', '_Reported from Axella with Report a problem – anonymised on the reporter\'s own machine, reviewed before publishing._'].join('\n')
}

async function triage(req, env, path) {
  const auth = (req.headers.get('Authorization') || '').replace(/^Bearer /, '')
  if (!sameToken(auth, env.TRIAGE_TOKEN || '')) return json({ ok: false, error: 'not allowed' }, 401)
  const m = path.match(/^\/api\/triage(?:\/([\w-]{36}))?(?:\/(render|act))?$/)
  if (!m) return json({ ok: false, error: 'not found' }, 404)
  const [, id, what] = m
  if (!id && req.method === 'GET') {
    const { results } = await env.DB.prepare(`SELECT id, created, class, text, route, trail, errors, meta, status, issue_url, duplicate_of,
        (render IS NOT NULL) has_render FROM reports WHERE status = 'new' ORDER BY created LIMIT 100`).all()
    return json({ ok: true, reports: results.map(r => ({ ...r, trail: JSON.parse(r.trail || '[]'), errors: JSON.parse(r.errors || '[]'), meta: JSON.parse(r.meta || '{}') })) })
  }
  const r = id && await env.DB.prepare('SELECT * FROM reports WHERE id = ?').bind(id).first()
  if (!r) return json({ ok: false, error: 'unknown report' }, 404)
  if (what === 'render' && req.method === 'GET') { const d = await getRender(env, id); return d ? png(d) : json({ ok: false, error: 'no render' }, 404) }
  if (what !== 'act' || req.method !== 'POST') return json({ ok: false, error: 'not found' }, 404)
  let b
  try { b = await req.json() } catch { return json({ ok: false, error: 'not JSON' }, 400) }
  const text = typeof b.text === 'string' && b.text.trim() ? b.text.slice(0, 4000) : r.text
  const cls = ['critical', 'annoying', 'cosmetic', 'missing'].includes(b.class) ? b.class : r.class
  if (b.action === 'edit') {
    await env.DB.prepare('UPDATE reports SET text = ?, class = ? WHERE id = ?').bind(text, cls, id).run()
    return json({ ok: true, id })
  }
  if (b.action === 'discard') {
    await env.DB.prepare("UPDATE reports SET status = 'discarded' WHERE id = ?").bind(id).run()
    return json({ ok: true, id, status: 'discarded' })
  }
  if (b.action === 'merge') {
    const into = await env.DB.prepare('SELECT id, issue_url FROM reports WHERE id = ?').bind(String(b.into || '')).first()
    if (!into || into.id === id) return json({ ok: false, error: 'merge into which report?' }, 400)
    await env.DB.prepare("UPDATE reports SET status = 'merged', duplicate_of = ?, issue_url = ? WHERE id = ?").bind(into.id, into.issue_url, id).run()
    return json({ ok: true, id, status: 'merged', issue_url: into.issue_url || null })
  }
  if (b.action === 'approve') {
    if (!env.GITHUB_TOKEN || !env.GITHUB_REPO) return json({ ok: false, error: 'GITHUB_TOKEN / GITHUB_REPO not set up' }, 500)
    const title = safeTitle(typeof b.title === 'string' && b.title.trim() ? b.title : text.split('\n')[0])
    const base = env.PUBLIC_BASE || new URL(req.url).origin
    const has_render = !!(await getRender(env, id))
    const res = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/issues`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'axella-report-intake', 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, body: issueBody({ ...r, text, has_render }, base), labels: [cls, 'from-report'] }),
    })
    const gh = await res.json().catch(() => ({}))
    if (!res.ok || !gh.html_url) return json({ ok: false, error: 'GitHub said ' + res.status + (gh.message ? ': ' + gh.message : '') }, 502)
    await env.DB.prepare("UPDATE reports SET status = 'approved', issue_url = ?, text = ?, class = ? WHERE id = ?").bind(gh.html_url, text, cls, id).run()
    // reports merged into this one follow it
    await env.DB.prepare('UPDATE reports SET issue_url = ? WHERE duplicate_of = ?').bind(gh.html_url, id).run()
    return json({ ok: true, id, status: 'approved', issue_url: gh.html_url })
  }
  return json({ ok: false, error: 'unknown action' }, 400)
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url), path = url.pathname
    try {
      if (path === '/api/report' && req.method === 'POST') return await receive(req, env)
      let m = path.match(/^\/api\/report\/status\/([A-Z0-9]{8})$/)
      if (m && req.method === 'GET') return await status(env, m[1])
      if (path.startsWith('/api/triage')) return await triage(req, env, path)
      m = path.match(/^\/r\/([\w-]{36})\.png$/)
      if (m && req.method === 'GET') {
        const r = await env.DB.prepare('SELECT status FROM reports WHERE id = ?').bind(m[1]).first()
        if (r?.status !== 'approved') return new Response('not found', { status: 404 })
        const d = await getRender(env, m[1])
        return d ? png(d) : new Response('not found', { status: 404 })
      }
      return json({ ok: false, error: 'not found' }, 404)
    } catch (e) {
      return json({ ok: false, error: 'intake error' }, 500)       // never echo request content
    }
  },
}
