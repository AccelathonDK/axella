// What you pushed to Later – the line at the bottom of Today (web/src/components/Later.tsx), on a laptop and an iPhone.
// The line counts what's waiting and says when the next one is back; it opens the list grouped by when they come back;
// Bring back now, Change time and Done use the ordinary undo / snooze / done. Invented data only.
// Run by hand against a TEST dashboard whose state has snoozed items (never the real one):
//   AX_URL=http://127.0.0.1:8811/axella/ AX_API=http://127.0.0.1:8798 AX_LOGIN=<owner login> node web/tests/later.cjs
const { chromium, devices } = require('playwright')
const URL = process.env.AX_URL || 'http://127.0.0.1:8811/axella/'
;(async () => {
  const b = await chromium.launch()
  let fails = 0
  const ok = (cond, label) => { console.log((cond ? '  ok   ' : '  FAIL ') + label); fails += cond ? 0 : 1 }
  for (const [tag, opts] of [['laptop', { viewport: { width: 1280, height: 1000 } }], ['phone', { ...devices['iPhone 13'] }]]) {
    const c = await b.newContext({ ...opts, serviceWorkers: 'block' })
    await c.addInitScript(() => { try { sessionStorage.setItem('ax-splash', '1'); localStorage.setItem('ax-tour', 'seen') } catch {} })
    const p = await c.newPage()
    p.on('pageerror', e => ok(false, `${tag}: no page error (${e.message})`))
    const posts = []
    await p.route('**/axella/api/**', async r => {
      const u = r.request().url(), m = r.request().method()
      if (m === 'POST') {           // the actions are only recorded here – the test state stays as it is
        posts.push({ a: u.split('/api/')[1].split('?')[0], body: JSON.parse(r.request().postData() || '{}') })
        return r.fulfill({ contentType: 'application/json', body: '{"ok":true,"result":"ok"}' })
      }
      try {
        const resp = process.env.AX_API ? await r.fetch({ url: u.replace(/^https?:\/\/[^/]+/, process.env.AX_API), headers: { ...r.request().headers(), 'tailscale-user-login': process.env.AX_LOGIN || '' } }) : await r.fetch()
        await r.fulfill({ response: resp })
      } catch {}
    })
    await p.goto(URL, { waitUntil: 'load' }); await p.waitForTimeout(3500)
    const line = p.locator('[data-later-line]')
    ok(await line.count() === 1, `${tag}: the Later line is on Today`)
    const text = await line.innerText()
    ok(/^\d+ for later · next /.test(text), `${tag}: "${text}"`)
    await line.click(); await p.waitForTimeout(400)
    const rows = p.locator('[data-later-item]')
    const n = Number(text.match(/^\d+/)[0])
    ok(await rows.count() === n, `${tag}: the list has the ${n} items`)
    const labels = await p.locator('[data-later-list] .ax-label').allInnerTexts()
    ok(labels.length >= 2 && labels.every((l, i) => labels.indexOf(l) === i), `${tag}: grouped by when they come back (${labels.join(', ')})`)
    const kim = p.locator('[data-later-item="t-l1"]')
    ok(/back \d\d:\d\d|back tomorrow/.test(await kim.innerText()), `${tag}: each row says when it's back`)
    await kim.locator('[data-later-act="back"]').click(); await p.waitForTimeout(500)
    const u1 = posts.find(x => x.a === 'undo')
    ok(u1 && u1.body.item_id === 't-l1' && u1.body.account === 'iCloud' && u1.body.message_id === '<l1@example.net>', `${tag}: Bring back now = undo, with the mail`)
    await p.locator('[data-later-item="t-l2"]').getByRole('button', { name: /Change time/ }).click(); await p.waitForTimeout(300)
    await p.getByRole('menuitem', { name: /Tomorrow/ }).click(); await p.waitForTimeout(500)
    const s1 = posts.find(x => x.a === 'snooze')
    ok(s1 && s1.body.item_id === 't-l2' && new Date(s1.body.until).getHours() === 7, `${tag}: Change time → tomorrow 07:00 = snooze`)
    await p.locator('[data-later-item="t-l3"] [data-later-act="done"]').click(); await p.waitForTimeout(500)
    const d1 = posts.find(x => x.a === 'done')
    ok(d1 && d1.body.item_id === 't-l3' && d1.body.channel === 'mail', `${tag}: Done = done, with the mail (read in Mail)`)
    const gone = p.locator('[data-later-item="t-gone"]')
    ok(await gone.count() === 0 || /Sam: an old digest item/.test(await gone.innerText()), `${tag}: an item whose digest is gone keeps its title`)
    await p.screenshot({ path: `later-${tag}.png`, fullPage: true })
    await p.unrouteAll({ behavior: 'ignoreErrors' }); await c.close()
  }
  await b.close()
  console.log(fails ? `${fails} failed` : 'all ok')
  process.exit(fails ? 1 : 0)
})()
