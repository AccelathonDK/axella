// What Axella handles and the guided setup, end to end on TEST installs (never the real one), invented data only.
//  A – an install in use (AX_API / AX_BASE): the "Review what Axella handles" card → cards → a new card's mini-setup →
//      Summary; Trips leaves the menu and its page is a quiet "off" page; Settings → What Axella handles switches a
//      card on again; a second login (AX_LOGIN2) only narrows the owner's set.
//  B – a new install (AX_API_NEW / AX_BASE_NEW): Today opens the setup → About you → cards → Messages → skip Calendar →
//      Projects → Summary; the skipped card says "Not set up yet".
//   AX_URL=http://127.0.0.1:8811/axella/ AX_API=http://127.0.0.1:8798 AX_BASE=<test Axella> AX_API_NEW=http://127.0.0.1:8799 AX_BASE_NEW=<empty test Axella>
//   AX_LOGIN=<owner login> AX_LOGIN2=<second login on the test access list> node web/tests/setup.cjs
// Both bases' state/features.json (and the new one's about.json) are wiped first – never point them at your real Axella folder.
const { chromium } = require('playwright')
const fs = require('fs'), path = require('path')
const URL = process.env.AX_URL || 'http://127.0.0.1:8811/axella/'
const API = process.env.AX_API || 'http://127.0.0.1:8798', API_NEW = process.env.AX_API_NEW || 'http://127.0.0.1:8799'
const BASE = process.env.AX_BASE, BASE_NEW = process.env.AX_BASE_NEW
const L1 = process.env.AX_LOGIN || '', L2 = process.env.AX_LOGIN2 || ''
if (!BASE || !BASE_NEW || ![BASE, BASE_NEW].every(b => /test|tmp|axtest|axnew/.test(b))) { console.log('SKIP – set AX_BASE and AX_BASE_NEW to test Axella folders'); process.exit(0) }
const H = l => ({ 'X-Axella': '1', 'Content-Type': 'application/json', 'tailscale-user-login': l })
const getF = (api, l, a) => fetch(api + '/' + a, { headers: H(l) }).then(r => r.json())
;(async () => {
  let fails = 0
  const ok = (c, label) => { console.log((c ? '  ok   ' : '  FAIL ') + label); fails += c ? 0 : 1 }
  const b = await chromium.launch()
  async function page(api, login) {
    const c = await b.newContext({ viewport: { width: 1280, height: 1000 }, serviceWorkers: 'block' })
    await c.addInitScript(() => { try { sessionStorage.setItem('ax-splash', '1'); localStorage.setItem('ax-tour', 'seen'); localStorage.setItem('ax-tour-fab', 'off') } catch {} })
    const p = await c.newPage()
    p.on('pageerror', e => ok(false, `no page error (${e.message})`))
    p.on('dialog', d => d.accept())
    await p.route('**/axella/api/**', async rt => {
      try { const resp = await rt.fetch({ url: rt.request().url().replace(/^https?:\/\/[^/]+\/axella\/api/, api), headers: { ...rt.request().headers(), 'tailscale-user-login': login } }); await rt.fulfill({ response: resp }) } catch {}
    })
    return { c, p }
  }
  const nav = async (p, v) => { await p.goto(URL + v, { waitUntil: 'load' }); await p.waitForTimeout(3000) }

  // ---------- A: an install in use ----------
  fs.rmSync(path.join(BASE, 'state', 'features.json'), { force: true })
  await fetch(API + '/card_set', { method: 'POST', headers: H(L1), body: JSON.stringify({ card: 'briefs', on: false, confirm: true }) })   // a known start: Topic briefs off
  let { c, p } = await page(API, L1)
  await nav(p, '?v=today')
  ok(await p.locator('[data-handles-review]').count() === 1, 'A: Today offers "Review what Axella handles"')
  await p.locator('[data-handles-review] button', { hasText: 'Review' }).click(); await p.waitForTimeout(2500)
  ok(await p.locator('[data-setup="cards"]').count() === 1 && await p.locator('[data-setup-switch="trips"][aria-checked="true"]').count() === 1, 'A: the cards, with what is on now ticked')
  await p.locator('[data-setup-switch="trips"]').click()
  await p.locator('[data-setup-switch="briefs"]').click()
  await p.screenshot({ path: 'setup-cards.png', fullPage: true })
  await p.locator('[data-setup-next]').click(); await p.waitForTimeout(3500)
  ok(await p.locator('[data-setup="briefs"]').count() === 1, 'A: only the newly chosen card (Topic briefs) is set up')
  await p.screenshot({ path: 'setup-briefs.png', fullPage: true })
  await p.locator('[data-setup-next]').click(); await p.waitForTimeout(3500)
  ok(await p.locator('[data-setup-summary]').count() === 1 && /Trips/.test(await p.locator('[data-setup-summary]').innerText()), 'A: Summary – Trips under "Not now"')
  await p.screenshot({ path: 'setup-summary.png', fullPage: true })
  let f = await getF(API, L1, 'features')
  ok(!f.features.trips.on && f.features.topic_briefs.on && !f.setup.review, 'A: Trips off, Topic briefs on, the review card gone')
  await p.locator('[data-setup-today]').click(); await p.waitForTimeout(3000)
  ok(await p.getByRole('button', { name: 'Trips', exact: true }).count() === 0, 'A: Trips has left the menu')
  ok((await fetch(API + '/trips', { headers: H(L1) })).status === 403, 'A: … and its API answers 403')
  await nav(p, '?v=trips')
  ok(await p.locator('[data-feature-off]').count() === 1, 'A: its page is the quiet "Trips is off" page')
  await nav(p, '?v=settings&s=handles')
  ok(await p.locator('[data-handles-setup="trips"]').count() === 1, 'A: Settings → What Axella handles: "Set up – 2 min" on Trips')
  await p.locator('[data-handles-card="messages"] button', { hasText: 'More' }).click(); await p.waitForTimeout(400)
  ok(await p.locator('[data-feature-switch]').count() >= 10, 'A: More shows the feature switches')
  await p.screenshot({ path: 'handles-settings.png', fullPage: true })
  await p.locator('[data-feature-switch="birthdays"]').click(); await p.waitForTimeout(1500)
  ok(!(await getF(API, L1, 'features')).features.birthdays.on, 'A: a single feature off from More')
  await p.locator('[data-handles-setup="trips"]').click(); await p.waitForTimeout(3500)
  ok(await p.locator('[data-setup="trips"]').count() === 1, "A: Set up opens that card's mini-setup")
  await p.locator('[data-setup-next]').click(); await p.waitForTimeout(3500)
  f = await getF(API, L1, 'features')
  ok(f.features.trips.on && !f.cards.find(x => x.id === 'trips').not_set_up, 'A: Trips on again and set up')
  await c.close()
  if (L2) {
    ;({ c, p } = await page(API, L2))
    await fetch(API + '/feature_set', { method: 'POST', headers: H(L1), body: JSON.stringify({ id: 'bills', on: false }) })
    await nav(p, '?v=settings&s=handles')
    await p.locator('[data-handles-card="money"] button', { hasText: 'More' }).click(); await p.waitForTimeout(400)
    ok(/Switched off by the owner/.test(await p.locator('[data-feature="bills"]').innerText()) && await p.locator('[data-feature-switch="bills"][disabled]').count() === 1,
      'A: a second login sees "Switched off by the owner" and cannot switch it on')
    await p.locator('[data-feature-switch="receipts"]').click(); await p.waitForTimeout(1500)
    ok(!(await getF(API, L2, 'features')).features.receipts.on && (await getF(API, L1, 'features')).features.receipts.on, "A: the second login's switch is theirs only")
    await c.close()
  }

  // ---------- B: a new install ----------
  for (const x of ['features.json', 'about.json']) fs.rmSync(path.join(BASE_NEW, 'state', x), { force: true })
  ;({ c, p } = await page(API_NEW, L1))
  await nav(p, '?v=today'); await p.waitForTimeout(1500)
  ok(await p.locator('[data-setup="about"]').count() === 1, 'B: a new install opens the guided setup')
  await p.getByLabel('What should Axella call you?').fill('Alex Example')
  await p.screenshot({ path: 'setup-about.png', fullPage: true })
  await p.locator('[data-setup-next]').click(); await p.waitForTimeout(2500)
  ok(await p.locator('[data-setup-switch][aria-checked="true"]').count() === 3, 'B: Messages, Calendar and Projects chosen by default')
  await p.locator('[data-setup-next]').click(); await p.waitForTimeout(3500)
  ok(await p.locator('[data-setup="messages"]').count() === 1 && await p.locator('[data-setup-accounts] li').count() >= 1, 'B: Messages – the mail accounts')
  await p.screenshot({ path: 'setup-messages.png', fullPage: true })
  await p.locator('[data-setup-next]').click(); await p.waitForTimeout(3500)
  ok(await p.locator('[data-setup="calendar"]').count() === 1, 'B: then Calendar')
  await p.locator('[data-setup-skip]').click(); await p.waitForTimeout(3000)
  ok(await p.locator('[data-setup="projects"]').count() === 1, 'B: skipped – on to Projects')
  await p.locator('[data-setup-next]').click(); await p.waitForTimeout(3500)
  ok(await p.locator('[data-setup-summary]').count() === 1, 'B: Summary')
  f = await getF(API_NEW, L1, 'features')
  ok(!f.setup.needed && f.cards.find(x => x.id === 'calendar').not_set_up && !f.cards.find(x => x.id === 'messages').not_set_up, 'B: done; Calendar "Not set up yet"')
  ok(!f.features.trips.on && !f.features.topic_briefs.on, 'B: the cards not chosen stay off')
  await c.close()
  await b.close()
  console.log(fails ? `${fails} failed` : 'all ok')
  process.exit(fails ? 1 : 0)
})()
