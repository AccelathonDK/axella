// Which project an item belongs to (lib/projects.ts projectsOf): keywords match what someone wrote to you – headline,
// subject, sender – not the detail text; Axella's own digest lines (bills, renewals, the plan …) only by your pin; and
// "Not this project" keeps an item out. Invented projects and items.
// Run: node web/tests/project-match.test.mjs   (bundles web/src/lib/projects.ts with esbuild – no browser)
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
const here = path.dirname(fileURLToPath(import.meta.url))
const require = createRequire(path.join(here, '..', 'package.json'))
const esbuild = require('esbuild')
const out = await esbuild.build({ entryPoints: [path.join(here, '..', 'src', 'lib', 'projects.ts')], bundle: true, format: 'esm', write: false, platform: 'node',
  alias: { '@': path.join(here, '..', 'src') } })
const M = await import('data:text/javascript;base64,' + Buffer.from(out.outputFiles[0].text).toString('base64'))

let fails = 0
const ok = (c, label) => { console.log((c ? '  ok   ' : '  FAIL ') + label); fails += c ? 0 : 1 }
const lighthouse = { id: 'p-lighthouse', name: 'Lighthouse', tag: 'lighthouse', status: 'active', keywords: ['Lighthouse'], senders: ['kim@example.net'], items: [], hidden_items: [] }
const ids = (it, ps = [lighthouse]) => M.projectsOf(it, ps).map(p => p.id)
ok(ids({ id: 'a1', section: 'p1', headline: 'Kim: the Lighthouse prototype' }).includes('p-lighthouse'), 'a keyword in the headline matches')
ok(ids({ id: 'a2', section: 'p1', headline: 'Lunch?', subject: 'Re: Lighthouse notes' }).includes('p-lighthouse'), '… or in the subject')
ok(!ids({ id: 'a3', section: 'p1', headline: 'Robin: dinner on Friday', detail: 'Meet at the old lighthouse café' }).length, 'a keyword only in the detail text: no match')
ok(ids({ id: 'a4', section: 'p1', headline: 'A question', from: { name: 'Kim', address: 'kim@example.net' } }).includes('p-lighthouse'), 'a sender in the matches still matches')
ok(ids({ id: 'a5', section: 'p1', headline: 'Status', detail: 'More in #lighthouse' }).includes('p-lighthouse'), 'the #tag still counts anywhere')
const bills = { id: '203011040730-p3-bills', section: 'p3', channel: 'bills', headline: '2 bills due this week: Lighthouse Ltd 100 DKK (Tue).', detail: 'In To do → Bills. Axella never pays.' }
ok(M.ownLine(bills) && !ids(bills).length, "Axella's own bills line: no project by keyword")
ok(!ids({ id: '203011040730-p3-plan', section: 'p3', headline: 'What are we working on today? Axella suggests Lighthouse.' }).length, '… nor the focus question')
ok(ids(bills, [{ ...lighthouse, items: [{ item_id: bills.id }] }]).includes('p-lighthouse'), '… unless you pin it')
ok(!ids({ id: 'a1', section: 'p1', headline: 'Kim: the Lighthouse prototype' }, [{ ...lighthouse, hidden_items: ['a1'] }]).length, '"Not this project" keeps it out')
console.log(fails ? `${fails} failed` : 'all ok')
process.exit(fails ? 1 : 0)
