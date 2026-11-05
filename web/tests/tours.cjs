// Walks every guided tour (web/src/components/Tour.tsx) on a laptop and an iPhone viewport: each tour starts, every
// step it shows has its card next to something visible on the screen, it ends with Done, and nothing is sent while
// it runs (no POST except the quiet digest_seen). Prints which steps were shown and which were passed over (no data
// for them on this install). Reply sprint and Backup get invented data so their steps can show; the rest use whatever
// the dashboard has. Run by hand, like the other browser tests:
//   AX_URL=http://127.0.0.1:8811/axella/ node web/tests/tours.cjs      (needs Playwright and a running dashboard)
//   A dashboard whose API is on another port (a test setup): AX_API=http://127.0.0.1:8798 AX_LOGIN=<login> as well.
const { chromium, devices } = require('playwright')
const URL = process.env.AX_URL || 'http://127.0.0.1:8811/axella/'
const TOURS = ['welcome', 'sprint', 'trips', 'meetings', 'invites', 'project-mails', 'backup']
const SPRINT = { items: [], count: 3, seconds: 120, minutes: 2, show: true, min: 3, digest: null }
const BACKUP = { age: true, auto: { on: false, folder: null, history: true, last_ok: null, last_try: null, last_error: null, last_name: null, icloud: false, keep: 4 },
  reconnect: ['Mail accounts – add them in Mail on this Mac'], left_out: ['state/voice-token'], min_pass: 10, keep: 4 }
;(async () => {
  const b = await chromium.launch()
  let fails = 0
  const ok = (cond, label) => { console.log((cond ? '  ok   ' : '  FAIL ') + label); fails += cond ? 0 : 1 }
  for (const [tag, opts] of [['laptop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
    const c = await b.newContext({ ...opts, serviceWorkers: 'block' })
    await c.addInitScript(() => { try { sessionStorage.setItem('ax-splash', '1'); localStorage.setItem('ax-tour', 'seen') } catch {} })
    const p = await c.newPage()
    p.on('pageerror', e => { ok(false, `${tag}: no page error (${e.message})`) })
    const posts = []
    const api = process.env.AX_API
    await p.route('**/axella/api/**', async r => {
      const u = r.request().url(), m = r.request().method()
      if (m === 'POST') { posts.push(u.split('/api/')[1].split('?')[0]); return r.fulfill({ contentType: 'application/json', body: '{"ok":true,"result":"ok"}' }) }
      if (/\/api\/sprint\b/.test(u)) return r.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, ...SPRINT }) })
      if (/\/api\/backup\b(?!_)/.test(u)) return r.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, ...BACKUP }) })
      const resp = api ? await r.fetch({ url: u.replace(/^https?:\/\/[^/]+/, api), headers: { ...r.request().headers(), 'tailscale-user-login': process.env.AX_LOGIN || '' } }) : await r.fetch()
      await r.fulfill({ response: resp })
    })
    await p.goto(URL, { waitUntil: 'load' }); await p.waitForTimeout(3000)
    for (const id of TOURS) {
      posts.length = 0
      await p.evaluate(t => window.dispatchEvent(new CustomEvent('ax-tour', { detail: t })), id)
      const shown = []
      let started = false
      for (let k = 0; k < 20; k++) {
        const card = p.locator('[data-tour-card]')
        try { await card.waitFor({ state: 'visible', timeout: 5000 }) } catch { break }
        started = true
        const title = await p.locator('#tour-t').innerText()
        const box = await card.boundingBox()
        const spot = await p.evaluate(() => { const d = document.querySelector('[data-tour-on] > div'); const r = d && d.getBoundingClientRect(); return r ? { w: r.width, h: r.height, vw: innerWidth } : null })
        if (!(box && box.width > 0 && spot && spot.w > 0 && spot.w < spot.vw + 1)) ok(false, `${tag} ${id}: "${title}" points at something visible`)
        shown.push(title)
        const last = (await p.locator('[data-tour-next]').innerText()).trim() === 'Done'
        await p.locator('[data-tour-next]').click(); await p.waitForTimeout(250)
        if (last) break
      }
      await p.waitForTimeout(300)
      ok(started && shown.length > 0, `${tag} ${id}: starts and shows ${shown.length} step(s) – ${shown.join(' · ')}`)
      ok(!(await p.locator('[data-tour-on]').count()), `${tag} ${id}: ends with Done`)
      const sent = posts.filter(x => x !== 'digest_seen')
      ok(!sent.length, `${tag} ${id}: nothing sent while it ran${sent.length ? ' (' + sent.join(', ') + ')' : ''}`)
    }
    // the ? on a page starts that page's tour
    await p.evaluate(() => window.dispatchEvent(new CustomEvent('ax-tour', { detail: 'trips' })))
    await p.locator('[data-tour-card]').waitFor({ timeout: 5000 }).catch(() => {})
    await p.keyboard.press('Escape'); await p.waitForTimeout(300)
    const help = p.locator('[data-tour-help="trips"]')
    if (await help.count()) {
      await help.first().click()
      ok(await p.locator('[data-tour-card]').waitFor({ timeout: 5000 }).then(() => true, () => false), `${tag}: the ? on Trips starts its tour`)
      await p.keyboard.press('Escape')
    } else ok(false, `${tag}: the ? on Trips is there`)
    // Settings → Appearance turns the floating ? off on this device, and on again
    await p.evaluate(() => { history.pushState({}, '', '?v=settings&s=appearance'); window.dispatchEvent(new PopStateEvent('popstate')) }); await p.waitForTimeout(800)
    const box = p.locator('[data-tour-fab-setting] input')
    if (await box.count()) {
      await box.uncheck(); await p.waitForTimeout(200)
      await p.evaluate(() => { history.pushState({}, '', '?v=trips'); window.dispatchEvent(new PopStateEvent('popstate')) }); await p.waitForTimeout(800)
      ok(!(await p.locator('[data-tour-help]').count()), `${tag}: the ? is gone when it's turned off`)
      await p.evaluate(() => { localStorage.removeItem('ax-tour-fab') })
    } else ok(false, `${tag}: Settings → Appearance has the ? switch`)
    await c.close()
  }
  await b.close()
  console.log(fails ? `${fails} failed` : 'all ok')
  process.exit(fails ? 1 : 0)
})()
