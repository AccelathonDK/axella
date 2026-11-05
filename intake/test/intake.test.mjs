// Runs the Worker against a real SQLite (node:sqlite, standing in for D1) and a fake GitHub – no network.
// node --experimental-sqlite intake/test/intake.test.mjs   (Node 22+)
import { DatabaseSync } from 'node:sqlite'
import { readFileSync } from 'node:fs'
import worker from '../src/index.js'

let fails = 0
const ok = (c, l) => { console.log((c ? '  ok   ' : '  FAIL ') + l); if (!c) fails++ }
const sql = new DatabaseSync(':memory:')
sql.exec(readFileSync(new URL('../schema.sql', import.meta.url), 'utf8'))
const stmt = (q, args = []) => ({
  bind: (...a) => stmt(q, a),
  first: async () => sql.prepare(q).get(...args.map(v => v instanceof Uint8Array ? Buffer.from(v) : v)) ?? null,
  run: async () => sql.prepare(q).run(...args.map(v => v instanceof Uint8Array ? Buffer.from(v) : v)),
  all: async () => ({ results: sql.prepare(q).all(...args) }),
})
const DB = { prepare: q => stmt(q), batch: async list => { for (const s of list) await s.run() } }
const issues = []
globalThis.fetch = async (url, init) => { issues.push({ url, body: JSON.parse(init.body), auth: init.headers.Authorization })
  return new Response(JSON.stringify({ html_url: 'https://github.com/owner/axella/issues/' + issues.length }), { status: 201 }) }
const env = { DB, TRIAGE_TOKEN: 't'.repeat(40), GITHUB_TOKEN: 'gh-test', GITHUB_REPO: 'owner/axella', PUBLIC_BASE: 'https://axella.dev' }
const call = (method, path, body, auth) => worker.fetch(new Request('https://axella.dev' + path, { method,
  headers: { 'Content-Type': 'application/json', ...(auth ? { Authorization: 'Bearer ' + auth } : {}) }, body: body ? JSON.stringify(body) : undefined }), env)

const PNG = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.alloc(40)]).toString('base64')
const good = { v: 1, class: 'annoying', text: 'Filing takes two taps', route: 'mailbox', trail: ['open_route:mailbox', 'act:file'],
  errors: [{ message: 'TypeError: x of {text} undefined', frames: ['at f (assets/index-AbC12.js:1:200)'], source: 'app' }],
  meta: { app_version: '1.0.0+202611021300', commit: 'abc1234', os: 'macOS', os_version: '15.1', mac_model: 'Macmini9,1', ram_tier: '16 GB',
    connectors: ['mail', 'whatsapp'], theme: 'dark', locale: 'en-GB' }, render: PNG, install: 'a'.repeat(32) }

let r = await call('POST', '/api/report', good); let j = await r.json()
ok(r.status === 200 && /^[A-Z2-9]{8}$/.test(j.code) && j.status_url.endsWith(j.code), 'a valid report is queued with a code')
for (const [bad, label] of [[{ ...good, ip: '1.2.3.4' }, 'extra top-level field'], [{ ...good, meta: { ...good.meta, hostname: 'x' } }, 'extra meta key'],
  [{ ...good, meta: { ...good.meta, mac_model: '/Users/alex' } }, 'path in meta'], [{ ...good, errors: [{ ...good.errors[0], message: 'from lee@clientb.example' }] }, 'value in error message'],
  [{ ...good, trail: ['Lee Chen opened'] }, 'content in trail'], [{ ...good, render: 'aGVsbG8=' }, 'render that is not a PNG'], [{ ...good, class: 'urgent' }, 'unknown class'],
  [{ ...good, install: 'me' }, 'bad install token']]) {
  r = await call('POST', '/api/report', bad); ok(r.status === 400, 'rejected: ' + label + ' (' + (await r.json()).error + ')')
}
const row = sql.prepare('SELECT * FROM reports').get()
ok(!JSON.stringify(row).includes('aaaaaaaa') && row.install_hash.length === 64, 'install token stored only as a hash')
ok(!Object.keys(row).some(k => /ip|addr|host|agent/i.test(k) && k !== 'address'), 'no IP or user-agent column')
r = await call('GET', '/api/report/status/' + j.code); ok((await r.json()).status === 'new', 'status by code')
ok((await call('GET', '/api/triage')).status === 401 && (await call('GET', '/api/triage', null, 'wrong')).status === 401, 'triage needs the token')
let list = await (await call('GET', '/api/triage', null, env.TRIAGE_TOKEN)).json()
ok(list.reports.length === 1 && list.reports[0].meta.os === 'macOS', 'triage lists the queue')
const id = list.reports[0].id
ok((await call('GET', `/r/${id}.png`)).status === 404, 'render not public before approval')
r = await call('POST', `/api/triage/${id}/act`, { action: 'approve', title: 'Filing needs two taps', class: 'cosmetic' }, env.TRIAGE_TOKEN); j = await r.json()
ok(j.ok && j.issue_url.endsWith('/1') && issues[0].body.labels.includes('cosmetic') && issues[0].body.body.includes(`/r/${id}.png`) && issues[0].auth === 'Bearer gh-test',
  'approve creates a labelled issue with the render link')
ok((await call('GET', `/r/${id}.png`)).status === 200, 'render public after approval')
r = await call('POST', '/api/report', { ...good, text: 'Same thing', reply: 'kim@private.example' }); const c2 = (await r.json()).code
const id2 = sql.prepare('SELECT id FROM reports WHERE code = ?').get(c2).id
ok(sql.prepare('SELECT address FROM replies WHERE report_id = ?').get(id2).address === 'kim@private.example' && !issues.some(i => JSON.stringify(i).includes('kim@')), 'reply address kept apart, never in an issue')
r = await call('POST', `/api/triage/${id2}/act`, { action: 'merge', into: id }, env.TRIAGE_TOKEN)
ok((await (await call('GET', '/api/report/status/' + c2)).json()).issue_url.endsWith('/1'), 'merged report follows the issue')
// the reporter's text can't ping, tag or embed anything in the public issue (security review 4, P2-5)
const nasty = '@octocat <img src=x> ![t](//x/y.png) ```\n@org/team'
r = await call('POST', '/api/report', { ...good, text: nasty, install: 'b'.repeat(32) }); const c3 = (await r.json()).code
const id3 = sql.prepare('SELECT id FROM reports WHERE code = ?').get(c3).id
await call('POST', `/api/triage/${id3}/act`, { action: 'approve' }, env.TRIAGE_TOKEN)
const ib = issues[issues.length - 1].body, txt = ib.body
const fenced = txt.match(/^(`{3,})text\n([\s\S]*?)\n\1$/m)
ok(fenced && fenced[1].length > 3, 'reporter text sits in a fence longer than any backtick run inside it')
ok(!/@(?!\u200b)\w/.test(txt) && !/@(?!\u200b)\w/.test(ib.title), 'no live @mention in the body or the title')
ok(fenced && fenced[2].includes('<img src=x>') && fenced[2].includes('![t](//x/y.png)'), '<img> and ![image] only as inert text inside the fence')
ok(!txt.replace(fenced ? fenced[0] : '', '').match(/<img|!\[t\]|\/\/x\//), 'nothing of it outside the fence')
ok(!/[<>]/.test(ib.title), 'no HTML in the title')
for (const [m, label] of [['bad `code` here', 'backtick'], ['see //x/y.png', 'protocol-relative link']]) {
  r = await call('POST', '/api/report', { ...good, errors: [{ ...good.errors[0], message: m }] }); ok(r.status === 400, 'error message refused: ' + label)
}
r = await call('POST', '/api/report', { ...good, render: Buffer.concat([Buffer.from(PNG, 'base64'), Buffer.alloc(450_000)]).toString('base64') })
ok(r.status === 400 || r.status === 413, 'a render over 400 kB is refused')
for (let i = 0; i < 12; i++) r = await call('POST', '/api/report', good)
ok(r.status === 429, 'rate limit per install')
console.log(fails ? `FAIL (${fails})` : 'PASS'); process.exit(fails ? 1 : 0)
