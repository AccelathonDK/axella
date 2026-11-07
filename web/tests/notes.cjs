// Notes, end to end on a TEST dashboard (never the real one), laptop and iPhone: write a note from a mail (⋯ → Note…),
// switch on "Remind me when they write", the next mail from the same invented person shows the quiet chip on the
// Briefing – the digest file itself holds nothing of the note – Done stops it; the Notes page and Search list it.
//   AX_URL=http://127.0.0.1:8811/axella/ AX_API=http://127.0.0.1:8798 AX_LOGIN=<owner login> AX_BASE=<test Axella folder> node web/tests/notes.cjs
// AX_BASE's notes/ and the two test digests (2099-01-0x) are wiped first – never point it at your real Axella folder.
const { chromium, devices } = require('playwright')
const fs = require('fs'), path = require('path')
const URL = process.env.AX_URL || 'http://127.0.0.1:8811/axella/'
const BASE = process.env.AX_BASE
if (!BASE || !/test|tmp|axtest/.test(BASE)) { console.log('SKIP – set AX_BASE to a test Axella folder'); process.exit(0) }
const DIG = path.join(BASE, 'digests')
const lee = { name: 'Lee Chen', address: 'lee@example.com' }
const digest = (name, items) => { fs.writeFileSync(path.join(DIG, name + '.json'), JSON.stringify({ title: 'Digest', kind: 'digest', generated: new Date().toISOString(), items }))
  fs.writeFileSync(path.join(DIG, name + '.md'), '# Digest\n') }
const clean = () => { fs.rmSync(path.join(BASE, 'notes'), { recursive: true, force: true })
  for (const n of ['2099-01-01-0700', '2099-01-02-0700']) for (const e of ['.json', '.md']) fs.rmSync(path.join(DIG, n + e), { force: true }) }
;(async () => {
  const b = await chromium.launch()
  let fails = 0
  const ok = (cond, label) => { console.log((cond ? '  ok   ' : '  FAIL ') + label); fails += cond ? 0 : 1 }
  for (const [tag, opts] of [['laptop', { viewport: { width: 1280, height: 1000 } }], ['phone', { ...devices['iPhone 13'] }]]) {
    clean()
    digest('2099-01-01-0700', [{ id: 'n-q1', section: 'p1', channel: 'mail', account: 'iCloud', message_id: '<q1@example.com>', headline: 'Lee: the quote',
      subject: 'Quote v2', from: lee, first_seen: new Date(Date.now() - 3600e3).toISOString() }])
    const c = await b.newContext({ ...opts, serviceWorkers: 'block' })
    await c.addInitScript(() => { try { sessionStorage.setItem('ax-splash', '1'); localStorage.setItem('ax-tour', 'seen'); localStorage.setItem('ax-tour-fab', 'off') } catch {} })
    const p = await c.newPage()
    p.on('pageerror', e => ok(false, `${tag}: no page error (${e.message})`))
    await p.route('**/axella/api/**', async r => {
      const u = r.request().url()
      try {
        const resp = await r.fetch({ url: u.replace(/^https?:\/\/[^/]+/, process.env.AX_API || ''), headers: { ...r.request().headers(), 'tailscale-user-login': process.env.AX_LOGIN || '' } })
        await r.fulfill({ response: resp })
      } catch {}
    })
    const nav = async q => { await p.evaluate(s => { history.pushState({}, '', s); window.dispatchEvent(new PopStateEvent('popstate')) }, q); await p.waitForTimeout(1200) }
    await p.goto(URL + '?v=briefing', { waitUntil: 'load' }); await p.waitForTimeout(3500)
    // 1. a note from the mail's ⋯ menu
    await p.locator('[data-item-row="n-q1"]').first().getByRole('button', { name: 'More actions' }).click(); await p.waitForTimeout(300)
    await p.locator('[data-note-from-item]').click(); await p.waitForTimeout(500)
    const ed = p.locator('[data-note-editor]')
    ok(/Person\s*Lee Chen/.test(await ed.locator('[data-note-links]').innerText()) && /Mail\s*Quote v2/.test(await ed.locator('[data-note-links]').innerText()),
      `${tag}: a note from a mail is linked to the person and the thread`)
    await ed.getByLabel('Note').fill('Ask Lee about the delivery date\nand the price for 200 units – https://example.com/quote')
    await ed.locator('[data-note-remind] input').check()
    await ed.locator('[data-note-save]').click(); await p.waitForTimeout(1200)
    const idx = JSON.parse(fs.readFileSync(path.join(BASE, 'notes', 'index.json'), 'utf8'))
    const [nid, meta] = Object.entries(idx.notes)[0] || []
    ok(meta && meta.remind && meta.title === 'Ask Lee about the delivery date', `${tag}: saved, with Remind me when they write`)
    // 2. the next mail from Lee → the chip
    digest('2099-01-02-0700', [{ id: 'n-q2', section: 'p1', channel: 'mail', account: 'iCloud', message_id: '<q2@example.com>', headline: 'Lee: about the quote',
      subject: 'Re: Quote v2', from: lee, first_seen: new Date(Date.now() + 60e3).toISOString() },
      { id: 'n-k1', section: 'p2', channel: 'mail', account: 'iCloud', message_id: '<k1@example.net>', headline: 'Kim: lunch?', subject: 'Lunch', from: { name: 'Kim', address: 'kim@example.net' },
        first_seen: new Date(Date.now() + 60e3).toISOString() }])
    await p.reload({ waitUntil: 'load' }); await p.waitForTimeout(4000)
    const chip = p.locator('[data-item-row="n-q2"] [data-note-chip]').first()
    ok(await chip.count() === 1 && /Your note: Ask Lee about the delivery date/.test(await chip.innerText()), `${tag}: Lee's next mail shows the chip`)
    ok(await p.locator('[data-item-row="n-k1"] [data-note-chip]').count() === 0, `${tag}: someone else's mail shows none`)
    const raw = fs.readFileSync(path.join(DIG, '2099-01-02-0700.json'), 'utf8')
    ok(!/delivery date|Your note/i.test(raw), `${tag}: the digest file holds nothing of the note`)
    await chip.locator('[data-note-chip-done]').click(); await p.waitForTimeout(1500)
    ok(await p.locator('[data-item-row="n-q2"] [data-note-chip]').count() === 0, `${tag}: Done – the chip is gone`)
    ok(!JSON.parse(fs.readFileSync(path.join(BASE, 'notes', 'index.json'), 'utf8')).notes[nid].remind, `${tag}: … and the reminder is off`)
    // 3. the Notes page, Search
    await nav('?v=notes')
    ok(await p.locator(`[data-note-row="${nid}"]`).count() === 1, `${tag}: the Notes page lists it`)
    await p.locator(`[data-note-row="${nid}"]`).click(); await p.waitForTimeout(800)
    ok(await p.locator('[data-note-preview] a[href="https://example.com/quote"]').count() === 1, `${tag}: links in a note are clickable`)
    await p.keyboard.press('Escape'); await p.waitForTimeout(300)
    await nav('?v=search&q=' + encodeURIComponent('delivery date'))
    await p.waitForTimeout(1200)
    ok(await p.locator('[data-search-notes]').count() === 1, `${tag}: Search finds it under Your notes`)
    await p.screenshot({ path: `notes-${tag}.png`, fullPage: true })
    await p.unrouteAll({ behavior: 'ignoreErrors' }); await c.close()
  }
  clean()
  await b.close()
  console.log(fails ? `${fails} failed` : 'all ok')
  process.exit(fails ? 1 : 0)
})()
