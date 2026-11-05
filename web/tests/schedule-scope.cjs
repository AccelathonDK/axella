// Work/private per schedule: three slots (work morning, private evening, weekend private) – their scope toggles in
// Settings → Schedule, the digest picker's slot names and scope labels (never "Extra run" for a scheduled slot, also
// when the run wrote its file late), the "Work digest" header, an urgent private item in a work digest, and the empty
// state of a work-only digest under the Private filter. The schedule and the digests are faked; fictional names.
// Run:  AX_URL=http://127.0.0.1:8811/axella/ node web/tests/schedule-scope.cjs   (needs Playwright and a running dashboard)
// A dashboard whose API is on another port (a test setup): AX_API=http://127.0.0.1:8798 AX_LOGIN=<login> as well.
const { chromium } = require('playwright')
const URL = process.env.AX_URL || 'http://127.0.0.1:8811/axella/'
const day = (() => { const d = new Date(); return d.toISOString().slice(0, 10) })()
const W = day + '-0912', P = day + '-2008'           // written 12 and 8 minutes after their slots
const cfg = { enabled: true, digests: [
  { id: 'wm', label: 'Work morning', task: 'digest-morning', time: '09:00', days: [0, 1, 2, 3, 4, 5, 6], enabled: true, worlds: ['work'], mention_other: true },
  { id: 'pe', label: 'Evening wrap', task: 'digest-afternoon', time: '20:00', days: [0, 1, 2, 3, 4, 5, 6], enabled: true, worlds: ['private'], mention_other: true },
  { id: 'we', label: 'Weekend', task: 'digest-morning', time: '09:30', days: [5, 6], enabled: true, worlds: ['private'], mention_other: false }],
  p0: { enabled: true, from: '07:00', to: '22:45', every: 15, days: [0, 1, 2, 3, 4] }, models: { digest: 'opus', p0: 'sonnet', compose: 'sonnet' } }
const runs = { config: cfg, tasks: { 'digest-morning': 'Morning digest', 'digest-afternoon': 'Afternoon digest', 'week-ahead': 'Sunday week-ahead' }, current: null, queue: [], today: [], runs: [], kept_days: 30, total_runs: 0, doctor: null }
const digests = {
  [W]: { title: 'Work morning', kind: 'digest', intro: 'Your work digest. 1 to answer. 2 private messages are waiting for this evening.', scope: ['work'], items: [
    { id: 'w1', section: 'p1', channel: 'mail', context: 'work', headline: 'Lee asks about the review', from: { name: 'Lee Chen', address: 'lee@acme.example' } },
    { id: 'u1', section: 'p0', channel: 'sms', context: 'private', world: 'private', headline: 'Kim: call me back now', from: { name: 'Kim', address: '+45 00 00 00 03' } }] },
  [P]: { title: 'Evening wrap', kind: 'digest', intro: 'Your private digest.', scope: ['private'], items: [
    { id: 'p1', section: 'p2', channel: 'mail', context: 'private', headline: 'Robin: dinner Friday?', from: { name: 'Robin', address: 'robin@example.org' } }] },
}
;(async () => {
  const b = await chromium.launch()
  const c = await b.newContext({ viewport: { width: 1280, height: 1000 }, serviceWorkers: 'block' })
  await c.addInitScript(() => { try { sessionStorage.setItem('ax-splash', '1') } catch {} })
  const p = await c.newPage()
  let fails = 0
  const ok = (cond, label) => { console.log((cond ? '  ok   ' : '  FAIL ') + label); fails += cond ? 0 : 1 }
  const api = process.env.AX_API
  const fetchApi = r => api ? r.fetch({ url: r.request().url().replace(/^https?:\/\/[^/]+/, api), headers: { ...r.request().headers(), 'tailscale-user-login': process.env.AX_LOGIN || '' } }) : r.fetch()
  const posted = []
  await p.route('**/axella/api/**', async r => {
    const u = r.request().url()
    if (/\/api\/runs(\?|$)/.test(u)) return r.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, ...runs }) })
    if (r.request().method() === 'POST' && /\/api\/(scheduler_set|schedule_set)/.test(u)) { posted.push(JSON.parse(r.request().postData())); return r.fulfill({ contentType: 'application/json', body: '{"ok":true,"result":"saved"}' }) }
    return r.fulfill({ response: await fetchApi(r) })
  })
  await p.route('**/digests/', r => r.fulfill({ contentType: 'text/html', body: Object.keys(digests).map(n => `<a href="${n}.md">${n}.md</a><a href="${n}.json">${n}.json</a>`).join('') }))
  await p.route('**/digests/*.json*', r => { const n = r.request().url().split('/').pop().split('.json')[0]; return digests[n] ? r.fulfill({ contentType: 'application/json', body: JSON.stringify(digests[n]) }) : r.fulfill({ status: 404, body: '' }) })
  await p.route('**/digests/*.md*', r => r.fulfill({ contentType: 'text/markdown', body: '# Digest\n' }))

  await p.goto(URL + '?v=briefing', { waitUntil: 'load' }); await p.waitForTimeout(2500)
  await p.getByRole('button', { name: 'Choose digest' }).click(); await p.waitForTimeout(300)
  const menu = (await p.locator('[role=menu]').innerText()).replace(/\n/g, ' | ')
  ok(/Work morning \| Work/.test(menu) && /Evening wrap \| Private/.test(menu), 'picker: slot names with their scope (' + menu.slice(0, 120) + ')')
  ok(!/Extra run/.test(menu), 'picker: no "Extra run" for a scheduled slot written late')
  await p.locator('[role=menu]').getByText('Work morning').first().click(); await p.waitForTimeout(800)
  ok((await p.locator('[data-scope-label]').first().innerText()) === 'Work digest', 'header: "Work digest"')
  ok(/Private · urgent/.test(await p.locator('[data-item-row="u1"]').innerText()), 'an urgent private item shows its world')
  await p.getByRole('radio', { name: 'Private' }).first().click(); await p.waitForTimeout(400)
  ok(/covers work only/.test(await p.locator('[data-scope-empty]').innerText().catch(() => '')), 'under Private: "This digest covers work only."')

  await p.goto(URL + '?v=settings', { waitUntil: 'load' }); await p.waitForTimeout(1500)
  await p.getByRole('button', { name: /^Schedule/ }).first().click(); await p.waitForTimeout(1500)
  const on = async id => (await p.locator(`[data-slot-scope="${id}"] [role=radio][aria-checked=true], [data-slot-scope="${id}"] [data-state=on]`).first().innerText()).trim()
  ok(await on('wm') === 'Work' && await on('pe') === 'Private' && await on('we') === 'Private', 'Settings: each slot shows its scope')
  ok(!(await p.locator('[data-slot-scope="we"] [role=checkbox]').first().isChecked()), 'Settings: "no mention" is kept per slot')
  await p.locator('[data-slot-scope="wm"]').getByRole('radio', { name: 'Both' }).click()
  await p.getByRole('button', { name: 'Duplicate slot' }).first().click(); await p.waitForTimeout(200)
  await p.getByRole('button', { name: /^Save/ }).first().click(); await p.waitForTimeout(500)
  const sent = posted.find(x => x.digests)
  ok(sent && sent.digests.length === 4 && sent.digests[0].worlds.join() === 'private,work' && sent.digests[1].label.endsWith('(copy)'), 'Both and Duplicate slot are saved')
  await b.close()
  console.log(fails ? fails + ' failed' : 'all passed'); process.exit(fails ? 1 : 0)
})()
