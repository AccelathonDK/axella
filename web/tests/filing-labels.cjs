// Filing rows name the workplace, not the mail account's id (fix round 7, P2-3) – also when the profile doesn't come at
// first (the action service restarting): the first GET profile fails, the dashboard fetches it again and every filing
// row then shows the workplace label. The profile and the digest's accounts are faked; fictional names.
// Run:  AX_URL=http://127.0.0.1:8811/axella/ node web/tests/filing-labels.cjs   (needs Playwright and a running dashboard)
// A dashboard whose API is on another port (a test setup): AX_API=http://127.0.0.1:8798 AX_LOGIN=<login> as well.
const { chromium } = require('playwright')
const URL = process.env.AX_URL || 'http://127.0.0.1:8811/axella/'
;(async () => {
  const b = await chromium.launch()
  const c = await b.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: 'block' })
  await c.addInitScript(() => { try { sessionStorage.setItem('ax-splash', '1') } catch {} })
  const p = await c.newPage()
  let fails = 0, asked = 0
  const ok = (cond, label) => { console.log((cond ? '  ok   ' : '  FAIL ') + label); fails += cond ? 0 : 1 }
  const api = process.env.AX_API
  const fetchApi = r => api ? r.fetch({ url: r.request().url().replace(/^https?:\/\/[^/]+/, api), headers: { ...r.request().headers(), 'tailscale-user-login': process.env.AX_LOGIN || '' } }) : r.fetch()
  if (api) await p.route('**/axella/api/**', async r => r.fulfill({ response: await fetchApi(r) }))
  await p.route('**/digests/*.json*', async r => {
    const resp = await r.fetch(); let j
    try { j = await resp.json() } catch { return r.fulfill({ response: resp }) }
    for (const i of j.items || []) if (i.file_to) i.account = 'Exchange'
    await r.fulfill({ contentType: 'application/json', body: JSON.stringify(j) })
  })
  await p.route('**/api/profile*', async r => {
    if (asked++ === 0) return r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"error":"restarting"}' })
    const resp = await fetchApi(r); const j = await resp.json()
    j.accounts = [...(j.accounts || []).filter(a => a.id !== 'Exchange'), { id: 'Exchange', label: 'Acme', kind: 'work', workplace: 'acme' }]
    j.workplaces = [...(j.workplaces || []), { id: 'acme', name: 'Acme', protected: false }]
    await r.fulfill({ contentType: 'application/json', body: JSON.stringify(j) })
  })
  await p.goto(URL + '?v=mailbox', { waitUntil: 'load' }); await p.waitForTimeout(6000)
  const rows = await p.locator('[data-item-row], [data-thread]').allInnerTexts()
  ok(asked >= 2, 'the profile is fetched again after a failure')
  ok(rows.length > 0, `filing rows on screen (${rows.length})`)
  ok(rows.every(t => !/\bExchange\b/.test(t)), 'no row says "Exchange"')
  ok(rows.some(t => /\bAcme\b/.test(t)), 'the rows say the workplace label (Acme)')
  console.log(fails ? 'FAIL' : 'PASS'); await b.close(); process.exit(fails ? 1 : 0)
})()
