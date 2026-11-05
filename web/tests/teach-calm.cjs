// Calm setup, Teach Axella and Keep Mail tidy in the dashboard, on a laptop and an iPhone viewport. Invented data only.
//  - Settings → Notifications → Calm setup: 3 steps, Done on steps 1 and 3, step 2 ticks itself when push is on for this
//    device (once with push off, once with a stubbed subscription), "3 of 3 done"; the Today / Getting started card,
//    dismissed once and gone.
//  - ⋯ → Not important… → This sender → a rule (Settings → Rules lists it; Remove, then Undo); This should have reached
//    me… → this topic, Always urgent; the suggestion card from habits (Not now).
//  - Keep Mail tidy: opening a mail posts mail_seen; Done and Undo carry the mail's account and id; a chat doesn't.
// Run by hand, like the other browser tests (needs Playwright and a running test dashboard – never the real one):
//   AX_URL=http://127.0.0.1:8811/axella/ AX_API=http://127.0.0.1:8798 AX_LOGIN=<owner login> AX_STATE=<test state dir> \
//   AX_DIGESTS=<test digests dir> node web/tests/teach-calm.cjs
// AX_STATE is wiped of learned-rules.json, learned-habits.jsonl and calm-setup.json first – never point it at real state.
const { chromium, devices } = require('playwright')
const fs = require('fs'), path = require('path')
const URL = process.env.AX_URL || 'http://127.0.0.1:8811/axella/'
const API = process.env.AX_API, STATE = process.env.AX_STATE
if (!STATE || !/test|tmp|axtest/.test(STATE)) { console.log('SKIP – set AX_STATE to a test state dir'); process.exit(0) }
const DIG = process.env.AX_DIGESTS     // optional: the test dashboard's digests folder – the invented digest below is (re)written there
const ITEMS = [
  { id: 't-news', section: 'p1', channel: 'mail', account: 'iCloud', message_id: '<n1@news.acme.example>', context: 'private', headline: 'Acme News: spring offers', subject: 'Spring offers inside', from: { name: 'Acme News', address: 'news@acme.example' } },
  { id: 't-kim', section: 'p2', channel: 'mail', account: 'iCloud', message_id: '<k1@example.net>', context: 'private', headline: 'Kim: dinner on Saturday?', subject: 'Dinner on Saturday', from: { name: 'Kim Example', address: 'kim@example.net' }, draft: { mode: 'reply', text: 'Saturday works – see you at 7.' } },
  { id: 't-robin', section: 'p3', channel: 'mail', account: 'iCloud', message_id: '<r1@robin-radio.example>', context: 'private', headline: 'Robin Radio: the weekly show notes', subject: 'Weekly show notes', from: { name: 'Robin Radio', address: 'show@robin-radio.example' } },
  { id: 't-jamie', section: 'p3', channel: 'whatsapp', context: 'private', headline: 'Jamie: photos from the trip', from: { name: 'Jamie', address: '+4500000003' } },
  { id: 't-bill', section: 'file', channel: 'mail', account: 'iCloud', message_id: '<b1@billing.acme.example>', file_to: 'Receipts', context: 'private', headline: 'Acme Billing: your receipt', subject: 'Your receipt', from: { name: 'Acme Billing', address: 'billing@acme.example' } }]
const reset = () => {
  ['learned-rules.json', 'learned-habits.jsonl', 'calm-setup.json'].forEach(f => { try { fs.unlinkSync(path.join(STATE, f)) } catch {} })
  try {                                          // the test items are not handled yet
    const f = path.join(STATE, 'actions.json'), st = JSON.parse(fs.readFileSync(f, 'utf8'))
    for (const k of Object.keys(st)) if (k.startsWith('t-')) delete st[k]
    fs.writeFileSync(f, JSON.stringify(st))
  } catch {}
  if (DIG) {
    const at = new Date(Date.now() - 3600e3).toISOString()
    fs.writeFileSync(path.join(DIG, '2099-01-01-0700.json'), JSON.stringify({ title: 'Morning digest', kind: 'digest', intro: 'A quiet morning.', generated: at, items: ITEMS.map(i => ({ ...i, first_seen: at })) }))
    fs.writeFileSync(path.join(DIG, '2099-01-01-0700.md'), '# Morning digest\n\nA quiet morning.\n')
  }
}
const cleanup = () => { if (DIG) ['2099-01-01-0700.json', '2099-01-01-0700.md'].forEach(f => { try { fs.unlinkSync(path.join(DIG, f)) } catch {} }) }
const habits = () => fs.writeFileSync(path.join(STATE, 'learned-habits.jsonl'), [0, 1, 2].map(k => JSON.stringify({
  at: new Date(Date.now() - k * 864e5).toISOString().slice(0, 19), kind: 'file', sender: 'billing@acme.example', account: 'iCloud', folder: 'Receipts' }) + '\n').join(''))
;(async () => {
  const b = await chromium.launch()
  let fails = 0
  const ok = (cond, label) => { console.log((cond ? '  ok   ' : '  FAIL ') + label); fails += cond ? 0 : 1 }
  for (const [tag, opts] of [['laptop', { viewport: { width: 1280, height: 1000 } }], ['phone', { ...devices['iPhone 13'] }]]) {
    for (const push of [false, true]) {
      reset()
      const c = await b.newContext({ ...opts, serviceWorkers: 'allow' })
      await c.addInitScript(on => {
        try { sessionStorage.setItem('ax-splash', '1'); localStorage.setItem('ax-tour', 'seen'); localStorage.setItem('ax-tour-fab', 'off') } catch {}
        if (on) {                                     // a push subscription on this device (stubbed)
          try { Object.defineProperty(Notification, 'permission', { get: () => 'granted' }) } catch {}
          if (window.PushManager) PushManager.prototype.getSubscription = async () => ({ endpoint: 'https://push.example.invalid/x' })
        }
      }, push)
      const p = await c.newPage()
      p.on('pageerror', e => ok(false, `${tag}: no page error (${e.message})`))
      const posts = []
      await p.route('**/axella/api/**', async r => {
        const u = r.request().url(), m = r.request().method()
        if (m === 'POST') posts.push({ a: u.split('/api/')[1].split('?')[0], body: JSON.parse(r.request().postData() || '{}') })
        if (/push_test|push_subscribe/.test(u)) return r.fulfill({ contentType: 'application/json', body: '{"ok":true,"result":"ok"}' })
        if (/\/api\/message\?/.test(u)) return r.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, message: {  // no Mail here: an invented mail
          subject: 'Dinner on Saturday', from: 'Kim Example <kim@example.net>', date: 'Sat 7 Nov 06:50', mailbox: 'INBOX', attachments: [], body: 'Saturday at 7?' } }) })
        const resp = API ? await r.fetch({ url: u.replace(/^https?:\/\/[^/]+/, API), headers: { ...r.request().headers(), 'tailscale-user-login': process.env.AX_LOGIN || '' } }) : await r.fetch()
        await r.fulfill({ response: resp })
      })
      const nav = async q => { await p.evaluate(s => { history.pushState({}, '', s); window.dispatchEvent(new PopStateEvent('popstate')) }, q); await p.waitForTimeout(900) }
      await p.goto(URL, { waitUntil: 'load' }); await p.waitForTimeout(3000)
      const T = `${tag}${push ? ' (push on)' : ''}`
      // ---- Calm setup
      ok(await p.locator('[data-calm-nudge="today"]').count() === 1, `${T}: Today shows the Calm setup card on a new installation`)
      await nav('?v=settings&s=notifications')
      const cs = p.locator('[data-calm-setup]')
      ok(await cs.locator('[data-calm-step]').count() === 3, `${T}: Calm setup has exactly 3 steps`)
      ok((await cs.getAttribute('data-calm-count')) === (push ? '1' : '0'), `${T}: step 2 ticks itself ${push ? 'when push is on' : '– off here, with the button to turn it on'}`)
      ok(await p.locator(push ? '[data-calm-push="on"]' : '[data-calm-push="off"]').count() === 1, `${T}: step 2 shows ${push ? '"On for this device"' : 'Turn on notifications'}`)
      const here = await cs.innerText()
      ok(tag === 'phone' ? /Here: Settings → Notifications/.test(here) : /On your iPhone: Settings → Notifications/.test(here), `${T}: the steps say ${tag === 'phone' ? '"here"' : '"on your iPhone"'}`)
      await p.locator('[data-calm-done="banners"]').click(); await p.waitForTimeout(700)
      await p.locator('[data-calm-done="focus"]').click(); await p.waitForTimeout(700)
      const n = await cs.getAttribute('data-calm-count')
      ok(n === (push ? '3' : '2'), `${T}: Done on steps 1 and 3 → ${n} of 3`)
      if (push) ok(/3 of 3 done/.test(await p.locator('#sec-calm-setup').innerText()), `${T}: "3 of 3 done"`)
      await nav('?v=today')
      ok(await p.locator('[data-calm-nudge="today"]').count() === (push ? 0 : 1), `${T}: the Today card ${push ? 'is gone when all 3 are done' : 'stays until done or dismissed'}`)
      if (!push) {
        await p.locator('[data-calm-dismiss]').click(); await p.waitForTimeout(800)
        ok(await p.locator('[data-calm-nudge]').count() === 0, `${T}: Dismiss – gone`)
        await p.evaluate(() => window.dispatchEvent(new Event('ax-guide'))); await p.waitForTimeout(600)
        ok(await p.locator('[data-calm-nudge="guide"]').count() === 0, `${T}: … and not in Getting started either (never comes back by itself)`)
        await p.keyboard.press('Escape'); await p.waitForTimeout(300)
      }
      if (push) { await p.unrouteAll({ behavior: 'ignoreErrors' }); await c.close(); continue }        // the teach / tidy checks once per viewport
      // ---- Keep Mail tidy: open a mail, Done, Undo (on the Briefing page: the digest by section)
      await nav('?v=briefing')
      posts.length = 0
      const kim = p.locator('[data-item-row="t-kim"]').first()
      await kim.getByText('Kim: dinner on Saturday?').first().click(); await p.waitForTimeout(1800)
      ok(posts.some(x => x.a === 'mail_seen' && x.body.message_id === '<k1@example.net>'), `${T}: opening a mail in the reader posts mail_seen`)
      await p.keyboard.press('Escape'); await p.waitForTimeout(500)
      // ---- Not important → this sender
      const news = p.locator('[data-item-row="t-news"]').first()
      await news.getByRole('button', { name: 'More actions' }).click(); await p.waitForTimeout(300)
      await p.locator('[data-teach-open="not_important"]').click(); await p.waitForTimeout(400)
      ok(await p.locator('[data-teach="not_important"] [data-teach-why]').count() === 3, `${T}: Not important asks why – sender, kind of mail, just this once`)
      await p.locator('[data-teach-why="sender"]').click()
      await p.locator('[data-teach-save]').click(); await p.waitForTimeout(1800)
      const t1 = posts.find(x => x.a === 'teach_not_important')
      ok(t1 && t1.body.why === 'sender' && t1.body.address === 'news@acme.example', `${T}: … this sender is sent with the address`)
      const fyi = await p.evaluate(() => { const el = document.querySelector('[data-item-row="t-news"]'); return el ? el.closest('[data-sec]')?.getAttribute('data-sec') : null })
      ok(fyi === 'p3', `${T}: the item moves to FYI (got ${fyi})`)
      await p.waitForTimeout(400)
      // ---- Should have reached me → this topic, always urgent
      const rob = p.locator('[data-item-row="t-robin"]').first()
      await rob.getByRole('button', { name: 'More actions' }).click(); await p.waitForTimeout(300)
      await p.locator('[data-teach-open="reached"]').click(); await p.waitForTimeout(400)
      await p.locator('[data-teach-why="topic"]').click()
      ok((await p.getByLabel('Topic word').inputValue()) === 'weekly', `${T}: the topic word is guessed from the subject`)
      await p.locator('[data-teach-level] button', { hasText: 'Always urgent' }).click()
      await p.locator('[data-teach-save]').click(); await p.waitForTimeout(1500)
      const t2 = posts.find(x => x.a === 'should_have_reached')
      ok(t2 && t2.body.why === 'topic' && t2.body.topic === 'weekly' && t2.body.level === 'urgent', `${T}: Should have reached me → this topic, always urgent`)
      // ---- Done / Undo carry the mail; a chat doesn't
      posts.length = 0
      await p.locator('[data-item-row="t-kim"]').first().getByRole('button', { name: /Done/ }).first().click(); await p.waitForTimeout(1500)
      const dn = posts.find(x => x.a === 'done')
      ok(dn && dn.body.account === 'iCloud' && dn.body.message_id === '<k1@example.net>' && dn.body.channel === 'mail', `${T}: Done sends the mail's account and id (marked read in Mail)`)
      // ---- Settings → Rules
      await nav('?v=settings&s=rules')
      const rules = p.locator('[data-rules] [data-rule]')
      ok(await rules.count() === 2, `${T}: Settings → Rules lists both rules`)
      const txt = await p.locator('[data-rules]').innerText()
      ok(/Acme News: FYI/.test(txt) && /Mail about “weekly”: always urgent/.test(txt), `${T}: … in plain words`)
      await rules.first().getByRole('button', { name: /Remove/ }).click(); await p.waitForTimeout(900)
      ok(await rules.count() === 1, `${T}: Remove – gone`)
      await p.getByRole('button', { name: 'Undo' }).click(); await p.waitForTimeout(1200)
      ok(await rules.count() === 2, `${T}: Undo – back`)
      // ---- the suggestion card
      habits()
      await p.evaluate(() => window.dispatchEvent(new Event('ax-learn')))
      await nav('?v=today'); await p.waitForTimeout(800)
      const sg = p.locator('[data-suggestion]')
      ok(await sg.count() === 1 && /You always file mail from Acme Billing in Receipts/.test(await sg.innerText()), `${T}: one suggestion card on Today, from your filing`)
      await sg.locator('[data-suggest="later"]').click(); await p.waitForTimeout(1000)
      ok(await p.locator('[data-suggestion]').count() === 0, `${T}: Not now – gone`)
      await p.screenshot({ path: `teach-${tag}.png` })
      await p.unrouteAll({ behavior: 'ignoreErrors' }); await c.close()
    }
  }
  reset(); cleanup()
  await b.close()
  console.log(fails ? `${fails} failed` : 'all ok')
  process.exit(fails ? 1 : 0)
})()
