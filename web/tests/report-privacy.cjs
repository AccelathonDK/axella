// Report a problem – automated privacy check of the render's source (acceptance: no original content strings).
// Opens a running dashboard, reads every visible text, builds the privacy copy the render is drawn from, and checks that
// none of the screen's words longer than 3 letters survive – except the app's own labels. Also with an item sheet open.
// Run:  AX_URL=http://127.0.0.1:8811/axella/ node web/tests/report-privacy.cjs   (needs Playwright)
const { chromium } = require('playwright')
const URL = process.env.AX_URL || 'http://127.0.0.1:8811/axella/'
;(async () => {
  const b = await chromium.launch(); const p = await (await b.newContext({ viewport: { width: 1280, height: 860 }, serviceWorkers: 'block' })).newPage()
  let fails = 0
  for (const [label, prep] of [['Briefing', async () => {}], ['item sheet', async () => { await p.locator('button[title=Open]').first().click(); await p.waitForTimeout(600) }]]) {
    await p.goto(URL + '?v=briefing', { waitUntil: 'load' }); await p.waitForTimeout(1800); await prep()
    const r = await p.evaluate(() => {
      const parts = [document.getElementById('root'), ...Array.from(document.body.children).filter(e => e.id !== 'root' && e.tagName === 'DIV')]
      const words = new Set(parts.flatMap(e => (e.innerText || '').split(/[^\p{L}\p{N}@.]+/u)).filter(w => w.length > 3))
      const copy = new Set(parts.map(e => window.__axReport.privacyClone(e).textContent).join(' ').split(/[^\p{L}\p{N}@.]+/u))
      const kept = [...words].filter(w => copy.has(w))
      return { words: words.size, kept }
    })
    // what may survive: the app's own labels only
    const allowed = /^(Today|Briefing|Calendar|Mailbox|Receipts|Search|Topic|briefs|Knowledge|Insights|Older|digests|Projects|projects|Archived|Settings|Done|Later|Send|Reply|Task|Undo|Open|Close|Cancel|Save|Edit|Delete|Attach|More|Filing|Newsletters|Cleanup|Urgent|Before|noon|Still|open|Waiting|replies|suggestions|Calls|Private|Work|Listen|Axella|AXELLA|Related|RELATED|Replying|REPLYING|message|MESSAGE|Drafted|reply|Plain|text|YOUR|TIDY|LIBRARY|PROJECTS|Load|pictures|Show|whole|Remind|answer|days|Active|Senders|Unsubscribe|tasks|others|Move|Other|folder|contacts|Notify|Discreet|Report|problem|sweep|Getting|started|Runs|logs|Sent|Handled|Noon|Notes|Spoken|Mails|Never|opened|mails|BRIEFING|TODAY|DRAFTED|PRIVATE|THE|Mail)$/
    const leaked = r.kept.filter(w => !allowed.test(w))
    console.log((leaked.length ? '  FAIL ' : '  ok   ') + `${label}: ${r.words} words on screen, none of the content kept` + (leaked.length ? ' – kept: ' + leaked.slice(0, 10).join(', ') : ''))
    fails += leaked.length ? 1 : 0
  }
  console.log(fails ? 'FAIL' : 'PASS'); await b.close(); process.exit(fails ? 1 : 0)
})()
