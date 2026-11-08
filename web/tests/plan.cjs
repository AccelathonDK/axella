// Targets and Now · Next · Later, end to end on a TEST dashboard (never the real one): an invented project with a
// target, the focus question → Plan my day → Done / Not now, the rest of the week, and Waiting for a person on the
// project page. Laptop and iPhone (swipe right = Done).
//   AX_URL=http://127.0.0.1:8811/axella/ AX_API=http://127.0.0.1:8798 AX_LOGIN=<owner login> AX_BASE=<test Axella folder> node web/tests/plan.cjs
// AX_BASE's state/planner.json is wiped first – never point it at your real Axella folder.
const { chromium, devices } = require('playwright')
const fs = require('fs'), path = require('path')
const URL = process.env.AX_URL || 'http://127.0.0.1:8811/axella/'
const API = process.env.AX_API || 'http://127.0.0.1:8798'
const BASE = process.env.AX_BASE
if (!BASE || !/test|tmp|axtest/.test(BASE)) { console.log('SKIP – set AX_BASE to a test Axella folder'); process.exit(0) }
const H = { 'X-Axella': '1', 'Content-Type': 'application/json', 'tailscale-user-login': process.env.AX_LOGIN || '' }
const post = (a, b) => fetch(API + '/' + a, { method: 'POST', headers: H, body: JSON.stringify(b) }).then(r => r.json())
const get = a => fetch(API + '/' + a, { headers: H }).then(r => r.json())
;(async () => {
  let fails = 0
  const ok = (c, label) => { console.log((c ? '  ok   ' : '  FAIL ') + label); fails += c ? 0 : 1 }
  const b = await chromium.launch()
  for (const [tag, opts] of [['laptop', { viewport: { width: 1280, height: 1000 } }], ['phone', { ...devices['iPhone 13'] }]]) {
    fs.rmSync(path.join(BASE, 'state', 'planner.json'), { force: true })
    const ps = (await get('projects')).projects || []
    let pid = (ps.find(p => p.name === 'Acme test proposal' && p.status === 'active') || {}).id
    if (!pid) pid = (await post('project_add', { name: 'Acme test proposal' })).result
    await post('project_update', { id: pid, ctx: 'private' })                // so the weekend works too
    const due = new Date(Date.now() + 3 * 864e5).toISOString().slice(0, 10)
    const tid = (await post('project_target_add', { id: pid, kind: 'date', title: 'Proposal sent', date: due })).result.id
    for (const [t, m] of [['Draft pricing', 20], ['Delivery plan', 20], ['Read-through', 20]]) await post('project_entry_add', { id: pid, target: tid, list: 'steps', text: t, mins: m })
    await post('project_person_add', { id: pid, key: 'lee@example.com', name: 'Lee Chen', role: 'Client' })
    const c = await b.newContext({ ...opts, serviceWorkers: 'block' })
    await c.addInitScript(() => { try { sessionStorage.setItem('ax-splash', '1'); localStorage.setItem('ax-tour', 'seen'); localStorage.setItem('ax-tour-fab', 'off') } catch {} })
    const p = await c.newPage()
    p.on('pageerror', e => ok(false, `${tag}: no page error (${e.message})`))
    await p.route('**/axella/api/**', async r => {
      try { const resp = await r.fetch({ url: r.request().url().replace(/^https?:\/\/[^/]+\/axella\/api/, API), headers: { ...r.request().headers(), 'tailscale-user-login': process.env.AX_LOGIN || '' } }); await r.fulfill({ response: resp }) } catch {}
    })
    await p.goto(URL + '?v=today', { waitUntil: 'load' }); await p.waitForTimeout(4000)
    ok(await p.locator(`[data-focus-question] [data-focus-pick="${pid}"][aria-pressed="true"]`).count() === 1, `${tag}: the focus question suggests the project`)
    await p.locator('[data-plan-my-day]').click(); await p.waitForTimeout(2500)
    const now = p.locator('[data-plan-now]')
    ok(/Draft pricing/.test(await now.innerText()), `${tag}: Plan my day → Now is the current step`)
    if (tag === 'phone') {
      const bx = await now.boundingBox()
      const cdp = await c.newCDPSession(p)
      const y = bx.y + 30, x0 = bx.x + 90          // away from the screen edge (that opens the menu)
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: x0, y }] })
      for (let i = 1; i <= 10; i++) await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x0 + i * 22, y }] })
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
    } else await p.locator('[data-plan-done-btn]').click()
    await p.waitForTimeout(2500)
    const steps = (await get('project_plan?id=' + pid)).targets[0].steps
    ok(steps[0].done, `${tag}: Done (${tag === 'phone' ? 'swipe right' : 'button'}) ticks the step on its target`)
    ok(/Delivery plan/.test(await p.locator('[data-plan-now]').innerText()), `${tag}: … and the plan moves on`)
    await p.locator('[data-plan-notnow]').click(); await p.waitForTimeout(2500)
    ok(/Delivery plan/.test(await p.locator('[data-plan-later]').innerText()), `${tag}: Not now → Later`)
    await p.locator('[data-plan-week]').click(); await p.waitForTimeout(3000)
    ok(await p.locator('[data-week-day]').count() >= 1 && await p.locator(`[data-week-day="${due}"]`).count() === 1, `${tag}: the rest of the week, with the target day`)
    await p.screenshot({ path: `plan-${tag}.png`, fullPage: true })
    await p.evaluate(id => { history.pushState({}, '', '?p=' + id); window.dispatchEvent(new PopStateEvent('popstate')) }, pid); await p.waitForTimeout(3000)
    await p.locator('[data-project-state]:visible').click(); await p.waitForTimeout(300)
    await p.locator('[data-state-btn="waiting"]').click(); await p.waitForTimeout(300)
    await p.getByLabel('Waiting for').selectOption('lee@example.com')
    await p.getByRole('button', { name: 'Set Waiting' }).click(); await p.waitForTimeout(2000)
    const pl = await get('plan')
    ok(pl.projects[pid].state === 'waiting' && pl.projects[pid].waiting_for.ref === 'lee@example.com', `${tag}: Waiting for Lee, set from the state pill`)
    ok(/waiting for Lee Chen/.test(await p.locator('[data-state-detail]').innerText()) && /Waiting/.test(await p.locator('[data-project-state]:visible').innerText()),
      `${tag}: the pill says Waiting, and "waiting for Lee Chen" shows under the name`)
    await p.screenshot({ path: `plan-project-${tag}.png` })
    await post('project_state', { id: pid, state: 'active' })
    await c.close()
  }
  await b.close()
  console.log(fails ? `${fails} failed` : 'all ok')
  process.exit(fails ? 1 : 0)
})()
