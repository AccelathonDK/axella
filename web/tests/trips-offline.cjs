// Trips v2 §4: the Today card on a travel day and the Trips page work with the phone offline – the owner's upcoming
// trip, its travel-day card and its ticket are kept by the service worker (only these; nothing else from the API).
// The API is faked with an invented trip; fictional names.
// Run:  AX_URL=http://127.0.0.1:8811/axella/ node web/tests/trips-offline.cjs   (needs Playwright and a running dashboard)
// A dashboard whose API is on another port (a test setup): AX_API=http://127.0.0.1:8798 AX_LOGIN=<login> as well.
const { chromium } = require('playwright')
const URL = process.env.AX_URL || URL
let fails = 0
const ok = (c, l) => { console.log((c ? '  ok   ' : '  FAIL ') + l); if (!c) fails++ }
const now = new Date(); const pad = n => String(n).padStart(2, '0')
const today = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
const later = new Date(Date.now() + 3 * 3600e3), lh = `${pad(later.getHours())}:${pad(later.getMinutes())}`
const off = (() => { const o = -now.getTimezoneOffset(); return (o >= 0 ? '+' : '-') + pad(Math.floor(Math.abs(o) / 60)) + ':' + pad(Math.abs(o) % 60) })()
const start = `${today}T${lh}:00${off}`
const B = { key: 'a1', kind: 'flight', title: 'AX 101 · Homeport → Lakeby', start, end: start, place: 'Lakeby', address: 'Homeport T3', ref: 'QX7KLM', number: 'AX101', provider: 'Acme Air',
  travellers: ['Alex Example'], confidence: 'read', status: 'booked', ticket: 0, source: { account: 'iCloud', message_id: 'm-a1' },
  checkin_view: { at: new Date(Date.now() - 3600e3).toISOString(), estimated: true }, updated: { by: 'Acme Air', at: now.toISOString(), was: { start: `${today}T09:00:00${off}` } },
  pending: null, cal: { id: 'e1', calendar: 'Home' }, cal_stale: 'changed' }
const T = { id: 'trA', title: 'Lakeby trip', start, end: `${today}T23:00:00${off}`, places: [], bookings: [B], checklist: [] }
const TRIPS = { ok: true, suggested: [], trips: [T], past: [], unsorted: [], quotes: [], removed: [], scan: { running: false, error: null, found: null } }
const CARD = { ok: true, card: { trip: { id: 'trA', title: 'Lakeby trip' }, mode: 'travel', next: { ...B, checkin: B.checkin_view, ticket: { account: 'iCloud', message_id: 'm-a1', n: 0 } }, day: [] } }
;(async () => {
  const b = await chromium.launch()
  const c = await b.newContext({ viewport: { width: 420, height: 900 }, serviceWorkers: 'allow' })
  await c.addInitScript(() => { try { sessionStorage.setItem('ax-splash', '1') } catch {} })
    await c.route('**/axella/api/**', async r => {
    const u = r.request().url()
    const J = o => r.fulfill({ contentType: 'application/json', body: JSON.stringify(o) })
    if (/api\/trips(\?|$)/.test(u)) { return J(TRIPS) }
    if (/api\/trip_today/.test(u)) { return J(CARD) }
    if (/api\/attachment/.test(u)) { return r.fulfill({ contentType: 'application/pdf', body: '%PDF-1.4 invented ticket' }) }
    if (/digest_seen/.test(u)) return J({ ok: true })
    // everything else from the dashboard's own API (AX_API/AX_LOGIN for a test setup on another port)
    const api = process.env.AX_API, login = process.env.AX_LOGIN
    const resp = await r.fetch(api ? { url: u.replace(/^https?:\/\/[^/]+/, api), headers: { ...r.request().headers(), ...(login ? { 'tailscale-user-login': login } : {}) } } : undefined)
    await r.fulfill({ response: resp })
  })
  const p = await c.newPage(); p.on('pageerror', e => ok(false, 'page error: ' + e.message))
  await p.goto(URL + '?v=trips', { waitUntil: 'load' })
  await p.waitForFunction(() => navigator.serviceWorker && navigator.serviceWorker.controller, null, { timeout: 15000 }).catch(() => {})
  if (!(await p.evaluate(() => !!navigator.serviceWorker?.controller))) { await p.reload({ waitUntil: 'load' }); await p.waitForTimeout(1500) }
  await p.waitForTimeout(2500)
  const live = await p.locator('[data-booking-live]').first().innerText().catch(() => '')
  ok(/Updated from Acme Air/.test(live) && /Check-in opens/.test(live) && /Update in calendar/.test(live), 'a booking shows the update, check-in and the calendar to fix')
  const kept = await p.evaluate(async () => (await (await caches.open('axella-trips-v1')).keys()).map(r => new URL(r.url).pathname + new URL(r.url).search))
  ok(kept.length === 3 && kept.some(k => /attachment/.test(k)), 'the trip, the card and the ticket are kept on the device – nothing else')
  const shell = await p.evaluate(async () => (await (await caches.open('axella-shell-v1')).keys()).length)
  await c.unroute('**/axella/api/**')            // from here on nothing answers but the device's own copy
  await c.setOffline(true)
  await p.goto(URL + '?v=trips', { waitUntil: 'load' }).catch(e => console.log('nav', e.message))
  await p.waitForTimeout(2500)
  ok(/Lakeby trip/.test(await p.locator('[data-trip]').first().innerText().catch(() => '')), 'offline: the Trips page shows the trip')
  await p.goto(URL, { waitUntil: 'load' }).catch(e => console.log('nav', e.message))
  await p.waitForTimeout(3000)
  const card = await p.locator('[data-travel-card]').innerText().catch(() => '')
  ok(/Travel day/i.test(card) && /AX101/.test(card) && /QX7KLM/.test(card) && /Ticket/.test(card), 'offline: the Today card with the next flight, its reference and the ticket')
  const tk = await p.evaluate(async () => { try { const r = await fetch('api/attachment?account=iCloud&id=m-a1&n=1'); return r.status + ' ' + (await r.text()).slice(0, 20) } catch (e) { return 'fail ' + e.message } })
  ok(/^200 %PDF/.test(tk), 'offline: the ticket opens')
  await c.setOffline(false)
  await b.close()
  console.log(fails ? fails + ' failed' : 'all ok'); process.exit(fails ? 1 : 0)
})()
