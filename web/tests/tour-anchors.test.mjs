// Every element a guided tour points at (web/src/components/Tour.tsx TOURS) still exists on some screen: each
// data-tour="…" name and each [data-…] attribute in a tour's selectors must be written somewhere in web/src. Catches a
// renamed or removed marker before a tour quietly points at nothing. No browser needed; run by tools/run-tests.sh.
// Run:  node web/tests/tour-anchors.test.mjs
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const src = join(dirname(fileURLToPath(import.meta.url)), '..', 'src')
const files = []
const walk = d => { for (const n of readdirSync(d)) { const p = join(d, n); statSync(p).isDirectory() ? walk(p) : /\.(tsx?|css)$/.test(n) && files.push(p) } }
walk(src)
const tourFile = join(src, 'components', 'Tour.tsx')
const tour = readFileSync(tourFile, 'utf8')
const others = files.filter(f => f !== tourFile).map(f => readFileSync(f, 'utf8')).join('\n')
const body = tour.slice(tour.indexOf('export const TOURS'), tour.indexOf('const SEEN'))
const own = tour.slice(tour.indexOf('const SEEN'))          // Tour.tsx's own components (the ? button) count as a screen too
let fails = 0
const ok = (c, label) => { console.log((c ? '  ok   ' : '  FAIL ') + label); fails += c ? 0 : 1 }

const names = new Set([...body.matchAll(/T\('([\w-]+)'\)/g)].map(m => m[1]))
for (const n of names) ok(new RegExp(`data-tour=(?:"${n}"|\\{?['"]${n}['"])`).test(others) || new RegExp(`tour="${n}"`).test(others), `data-tour="${n}" is on a screen`)
const attrs = new Set([...body.matchAll(/\[data-([a-z][\w-]*)/g)].map(m => m[1]).filter(a => a !== 'tour'))
for (const a of attrs) ok(new RegExp(`data-${a}[=\\s>{]`).test(others + own), `data-${a} is on a screen`)
const ids = [...body.matchAll(/^ {2}'?([\w-]+)'?: \{ id: '([\w-]+)'/gm)]
ok(ids.length >= 7 && ids.every(m => m[1] === m[2]), `every tour's key matches its id (${ids.map(m => m[2]).join(', ')})`)
for (const m of [...others.matchAll(/TourHelp id="([\w-]+)"/g), ...others.matchAll(/openTour\('([\w-]+)'\)/g)]) ok(ids.some(x => x[2] === m[1]), `a ? or Show me starts a tour that exists: ${m[1]}`)
const page = (own.match(/export function pageTour[\s\S]*?\n\}/) || [''])[0]
const pageIds = [...new Set([...page.matchAll(/return '([\w-]+)'|\? '([\w-]+)' :/g)].map(m => m[1] || m[2]))]
ok(pageIds.length >= 6, `the floating ? knows its pages (${pageIds.join(', ')})`)
for (const id of pageIds) ok(ids.some(x => x[2] === id), `the floating ? starts a tour that exists: ${id}`)
const show = others.match(/SHOW_ME[^=]*=\s*\{([^}]*)\}/)
for (const m of show ? show[1].matchAll(/'([\w-]+)'(?=\s*(?:,|$))/g) : []) ok(ids.some(x => x[2] === m[1]), `Show me in Getting started starts a tour that exists: ${m[1]}`)
console.log(fails ? `${fails} failed` : 'all ok')
process.exit(fails ? 1 : 0)
