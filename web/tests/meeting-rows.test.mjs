// Which events are meetings on the Meetings page and the Today card (fix round 7, P2-2): the Mac mini's verdict counts,
// a repeating event is one row, and Today suggests only real meetings within 48 hours. Fictional events.
// Run: node web/tests/meeting-rows.test.mjs   (bundles web/src/lib/meetingRows.ts with esbuild – no browser)
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
const here = path.dirname(fileURLToPath(import.meta.url))
const require = createRequire(path.join(here, '..', 'package.json'))
const esbuild = require('esbuild')
const out = await esbuild.build({ entryPoints: [path.join(here, '..', 'src', 'lib', 'meetingRows.ts')], bundle: true, format: 'esm', write: false, platform: 'node' })
const M = await import('data:text/javascript;base64,' + Buffer.from(out.outputFiles[0].text).toString('base64'))

let fails = 0
const ok = (c, label) => { console.log((c ? '  ok   ' : '  FAIL ') + label); fails += c ? 0 : 1 }
const now = new Date('2026-11-04T20:00:00+01:00').getTime()
const ev = (id, start, kw = {}) => ({ id, title: id, start, end: start, all_day: false, calendar: 'Work', calendar_label: 'Work', ctx: 'work', recurring: false, attendees: 0, ...kw })
const daily = Array.from({ length: 14 }, (_, i) => ev('reading', new Date(now + (i + 1) * 864e5 - 2 * 36e5).toISOString(),
  { title: "Kid's daily reading", calendar: 'Home', calendar_label: 'Home', ctx: 'private', recurring: true, attendees: 2, meeting: null }))
const standup = Array.from({ length: 5 }, (_, i) => ev('standup', new Date(now + (i + 1) * 864e5 - 11 * 36e5).toISOString(),
  { title: 'Acme stand-up', recurring: true, attendees: 4, meeting: 'people' }))
const events = [...daily, ...standup,
  ev('alex-x-sam', '2026-11-05T09:00:00+01:00', { meeting: 'join', join: 'https://meet.google.com/abc-defg-hij' }),
  ev('lunch', '2026-11-05T12:00:00+01:00', { meeting: null }),
  ev('kickoff', '2026-11-17T10:00:00+01:00', { attendees: 6, meeting: 'people' }),
  ev('old-service', '2026-11-05T15:00:00+01:00', { attendees: 1 }),
  ev('old-service-home', '2026-11-05T17:00:00+01:00', { attendees: 2, ctx: 'private', calendar: 'Home' })]           // no verdict from an older service

const rows = M.rowsOf(events, [], false, now)
const titles = rows.map(r => r.title)
ok(titles.includes('alex-x-sam'), 'a meeting with a join link and no attendee list is listed')
ok(!titles.includes("Kid's daily reading"), 'a private family event is not a meeting (the Mac mini says so)')
ok(!titles.includes('lunch'), 'an event with nobody else, no link and no invitation is left out')
ok(titles.includes('kickoff') && titles.includes('old-service'), 'other attendees count; an older service without a verdict: attendees')
ok(!titles.includes('old-service-home'), '… but not in a private calendar')
ok(titles.filter(t => t === 'Acme stand-up').length === 1 && rows.find(r => r.title === 'Acme stand-up').repeats === 5,
   'a repeating meeting is one row – its next occurrence, with how often it comes')
const every = M.rowsOf(events, [], true, now)
ok(every.filter(r => r.title === "Kid's daily reading").length === 1 && every.find(r => r.title === "Kid's daily reading").repeats === 14,
   '"Show other events too": the daily family event is there once, not 14 times')
const prep = { id: 'p1', title: 'Stand-up prep', start: standup[2].start, end: null, event: { id: 'standup', start: standup[2].start }, attendees: [], ctx: 'work' }
const withPrep = M.rowsOf(events, [prep], false, now).filter(r => r.ev?.id === 'standup')
ok(withPrep.length === 2 && withPrep.some(r => r.prep?.id === 'p1'), 'an occurrence with its own prep keeps its own row')
const today = M.todayRows(events, [], now).map(r => r.title)
ok(today.includes('alex-x-sam') && !today.includes('kickoff'), 'Today: real meetings within 48 hours only (not 17 Nov)')
ok(!today.includes("Kid's daily reading"), 'Today: never the daily family event')
console.log(fails ? `FAIL (${fails})` : 'PASS')
process.exit(fails ? 1 : 0)
