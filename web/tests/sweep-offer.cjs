// The sweep offered outside digest hours – the quiet row at the top of Today (web/src/components/SweepOffer.tsx), on a
// laptop and an iPhone. The Mac mini's answer (GET sweep_offer) is stood in here, because its count of new items reads
// the Mac mini's own Mail index; the rules behind it are tested in setup/tests/test_sweep_offer.py. POSTs are only
// recorded. Checks: the row and its text; Now; In an hour with its "Sweep at …" and Undo; Dismiss (× on the laptop,
// swipe left on the iPhone); the "Stop offering …?" question; no row for a background tab, or when the Mac mini says no.
// Invented data only. Run by hand against a TEST dashboard (never the real one):
//   AX_URL=http://127.0.0.1:8811/axella/ AX_API=http://127.0.0.1:8798 AX_LOGIN=<owner login> node web/tests/sweep-offer.cjs
const { chromium, devices } = require('playwright')
const URL = process.env.AX_URL || 'http://127.0.0.1:8811/axella/'
const OFFER = { ok: true, show: true, gap: '20270313-153000-digest-afternoon', kind: 'day-5', count: 3,
  text: 'No digest today. 3 new since yesterday 15:30 – sweep now?', worlds: ['private', 'work'], ask_stop: false, stop_text: null }
;(async () => {
  const b = await chromium.launch()
  let fails = 0
  const ok = (cond, label) => { console.log((cond ? '  ok   ' : '  FAIL ') + label); fails += cond ? 0 : 1 }
  for (const [tag, opts] of [['laptop', { viewport: { width: 1280, height: 1000 } }], ['phone', { ...devices['iPhone 13'] }]]) {
    const c = await b.newContext({ ...opts, serviceWorkers: 'block' })
    await c.addInitScript(() => { try { sessionStorage.setItem('ax-splash', '1'); localStorage.setItem('ax-tour', 'seen'); localStorage.setItem('ax-tour-fab', 'off') } catch {} })
    const p = await c.newPage()
    p.on('pageerror', e => ok(false, `${tag}: no page error (${e.message})`))
    const posts = []
    let offer = OFFER
    await p.route('**/axella/api/**', async r => {
      const u = r.request().url(), m = r.request().method(), a = u.split('/api/')[1].split('?')[0]
      if (m === 'POST') {
        const body = JSON.parse(r.request().postData() || '{}')
        posts.push({ a, body })
        const result = body.act === 'later' ? { at: '2027-03-13T15:00:00+01:00' } : body.act === 'stop' ? { stopped: 'day-5', text: 'No sweep offers on Saturdays – change it in Settings → Schedule.' } : 'ok'
        return r.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result }) })
      }
      if (a === 'sweep_offer') return r.fulfill({ contentType: 'application/json', body: JSON.stringify(offer) })
      try {
        const resp = process.env.AX_API ? await r.fetch({ url: u.replace(/^https?:\/\/[^/]+/, process.env.AX_API), headers: { ...r.request().headers(), 'tailscale-user-login': process.env.AX_LOGIN || '' } }) : await r.fetch()
        await r.fulfill({ response: resp })
      } catch {}
    })
    const open = async () => { await p.goto(URL + '?v=today', { waitUntil: 'load' }); await p.waitForTimeout(3500) }
    const row = p.locator('[data-sweep-offer="day-5"]')
    const last = () => posts.filter(x => x.a === 'sweep_offer').pop()

    await open()
    ok(await row.count() === 1 && /No digest today\. 3 new since yesterday 15:30/.test(await row.innerText()), `${tag}: the row is at the top of Today`)
    const box = await row.boundingBox(), h1 = await p.locator('h1').first().boundingBox()
    ok(box && h1 && box.y > h1.y && box.height >= 44, `${tag}: under the heading, at least 44 px high`)
    await p.screenshot({ path: `sweep-offer-${tag}.png`, fullPage: false })

    await row.getByRole('button', { name: 'Now' }).click(); await p.waitForTimeout(600)
    ok(last()?.body.act === 'now' && last()?.body.gap === OFFER.gap, `${tag}: Now = the sweep, for this gap`)
    ok(/Sweeping/.test(await p.locator('[data-sweep-offer="note"]').innerText()), `${tag}: … and the row says it is sweeping`)

    await open()
    await row.getByRole('button', { name: 'In an hour' }).click(); await p.waitForTimeout(600)
    ok(last()?.body.act === 'later', `${tag}: In an hour`)
    const note = p.locator('[data-sweep-offer="note"]')
    ok(/Sweep at \d\d:\d\d\./.test(await note.innerText()), `${tag}: … "Sweep at HH:MM." with Undo`)
    await note.getByRole('button', { name: 'Undo' }).click(); await p.waitForTimeout(600)
    ok(last()?.body.act === 'undo', `${tag}: Undo cancels it`)

    await open()
    if (tag === 'phone') {
      const bx = await row.locator('[data-sweep-offer-text]').boundingBox()
      const cdp = await c.newCDPSession(p)
      const y = bx.y + 12, x0 = bx.x + bx.width - 30                  // on the text, away from the buttons
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: x0, y }] })
      for (let i = 1; i <= 10; i++) await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x0 - i * 14, y }] })
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
    } else await row.getByRole('button', { name: 'Dismiss' }).click()
    await p.waitForTimeout(800)
    ok(last()?.body.act === 'dismiss' && await row.count() === 0, `${tag}: Dismiss (${tag === 'phone' ? 'swipe left' : '×'}) – the row goes`)

    offer = { ...OFFER, ask_stop: true, stop_text: 'Stop offering a sweep on Saturdays?' }
    await open()
    ok(/Stop offering a sweep on Saturdays\?/.test(await row.innerText()), `${tag}: after three dismissals the question, once`)
    await row.getByRole('button', { name: 'Stop' }).click(); await p.waitForTimeout(600)
    ok(last()?.body.act === 'stop' && await row.count() === 0, `${tag}: Stop`)

    offer = { ok: true, show: false, why: 'nothing new' }
    await open()
    ok(await p.locator('[data-sweep-offer]').count() === 0, `${tag}: no row when the Mac mini says no`)

    offer = OFFER
    const bg = await c.newPage()                                  // this tab goes to the background before it asks
    await bg.route('**/axella/api/sweep_offer', r => r.fulfill({ contentType: 'application/json', body: JSON.stringify(OFFER) }))
    await bg.addInitScript(() => { Object.defineProperty(document, 'visibilityState', { get: () => 'hidden' }); document.hasFocus = () => false })
    await bg.goto(URL + '?v=today', { waitUntil: 'load' }); await bg.waitForTimeout(3500)
    ok(await bg.locator('[data-sweep-offer]').count() === 0, `${tag}: a background tab never shows the offer`)
    await bg.close()
    await p.unrouteAll({ behavior: 'ignoreErrors' }); await c.close()
  }
  await b.close()
  console.log(fails ? `${fails} failed` : 'all ok')
  process.exit(fails ? 1 : 0)
})()
