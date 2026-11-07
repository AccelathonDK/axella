// Waking the phone with the connection not back yet must never show old, handled items (done / later) or calls for a
// moment: a failed GET state keeps what was known, and on a cold start the lists wait for Done / Later to be known.
// Run by hand against a TEST dashboard whose state has a snoozed item in the current digest (AX_SNOOZED=<its id>):
//   AX_URL=http://127.0.0.1:8811/axella/ AX_API=http://127.0.0.1:8798 AX_LOGIN=<login> AX_SNOOZED=<item id> node web/tests/no-flash.cjs
const { chromium, devices } = require('playwright')
const URL = process.env.AX_URL || 'http://127.0.0.1:8811/axella/'
const ID = process.env.AX_SNOOZED
if (!ID) { console.log('SKIP – set AX_SNOOZED'); process.exit(0) }
;(async () => {
  const b = await chromium.launch()
  let fails = 0
  const ok = (cond, label) => { console.log((cond ? '  ok   ' : '  FAIL ') + label); fails += cond ? 0 : 1 }
  for (const view of ['', '?v=briefing']) {
    const c = await b.newContext({ ...devices['iPhone 13'], serviceWorkers: 'block' })
    await c.addInitScript(() => { try { sessionStorage.setItem('ax-splash', '1'); localStorage.setItem('ax-tour', 'seen') } catch {} })
    const p = await c.newPage()
    let failState = 2                    // the first two GET state calls fail, like a phone whose VPN is still connecting
    await p.route('**/axella/api/**', async r => {
      const u = r.request().url()
      if (/\/api\/state\b/.test(u) && failState > 0) { failState--; return r.fulfill({ status: 502, body: 'Bad Gateway' }) }
      try {
        const resp = await r.fetch({ url: u.replace(/^https?:\/\/[^/]+/, process.env.AX_API || ''), headers: { ...r.request().headers(), 'tailscale-user-login': process.env.AX_LOGIN || '' } })
        await r.fulfill({ response: resp })
      } catch {}
    })
    const row = `[data-item-row="${ID}"]`
    let seen = false
    p.on('framenavigated', () => {})
    await p.goto(URL + view, { waitUntil: 'load' })
    for (let i = 0; i < 30; i++) { if (await p.locator(row).count()) seen = true; await p.waitForTimeout(250) }
    const v = view || 'Today'
    ok(!seen, `${v}: cold start with the connection not back – the snoozed item never shows`)
    await p.waitForTimeout(4000)
    ok(await p.locator('[data-state-wait]').count() === 0, `${v}: once the Mac mini answers, the lists are there`)
    ok(await p.locator(row).count() === 0, `${v}: … still without the snoozed item`)
    failState = 3                        // back from the background, the connection drops again
    await p.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
    seen = false
    for (let i = 0; i < 16; i++) { if (await p.locator(row).count()) seen = true; await p.waitForTimeout(250) }
    ok(!seen, `${v}: waking with the connection gone – what was known is kept, no old items flash up`)
    await p.unrouteAll({ behavior: 'ignoreErrors' }); await c.close()
  }
  await b.close()
  console.log(fails ? `${fails} failed` : 'all ok')
  process.exit(fails ? 1 : 0)
})()
