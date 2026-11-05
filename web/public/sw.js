// Axella service worker – shows Web Push notifications and opens the dashboard on tap, and keeps the app shell
// (index.html, the built JS/CSS, icons, fonts) so the dashboard still opens without a connection and can say so.
// Only the app itself is cached – never digests, mail or API answers – with ONE exception the owner asked for (Trips
// v2, decided 1): the owner's own upcoming trips, the travel-day card and their tickets, so a travel day works offline.
// The page sends that list only after GET trips answered (owner only – any other login gets 403 and clears it); entries
// not in the newest list (a trip now past or removed) are deleted. Network first; the kept copy only without a network.
const SHELL = 'axella-shell-v1';
const TRIPS = 'axella-trips-v1';
const TRIP_PATHS = /^\/axella\/api\/(trips|trip_today|attachment)(\?|$)/;
self.addEventListener('message', event => {
  const m = event.data || {};
  if (m.type === 'axella-trips-clear') event.waitUntil(caches.delete(TRIPS));
  if (m.type === 'axella-trips-cache' && Array.isArray(m.urls)) event.waitUntil((async () => {
    const base = new URL('/axella/', self.location.origin);
    const want = new Set(m.urls.slice(0, 80).map(u => new URL(u, base).href).filter(u => TRIP_PATHS.test(new URL(u).pathname + new URL(u).search.slice(0, 1))));
    const c = await caches.open(TRIPS);
    for (const r of await c.keys()) if (!want.has(r.url)) await c.delete(r);
    for (const u of want) {
      if (/\/attachment\?/.test(u) && await c.match(u)) continue;     // a ticket doesn't change: fetched once
      try { const res = await fetch(u, { credentials: 'include' }); if (res.ok) await c.put(u, res.clone()); } catch (e) {}
    }
  })());
});
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k.startsWith('axella-shell-') && k !== SHELL) await caches.delete(k);
  await self.clients.claim();
})()));

const isShell = url => url.origin === self.location.origin && /\/axella\/(assets|icons)\//.test(url.pathname)
  || url.origin === self.location.origin && /\/axella\/(manifest\.webmanifest)$/.test(url.pathname);   // fonts are in assets/

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  // the page itself: network first (always the newest build), the cached copy only when offline
  if (req.mode === 'navigate' && url.origin === self.location.origin && url.pathname.startsWith('/axella/')
      && !url.pathname.startsWith('/axella/api/') && !url.pathname.startsWith('/axella/digests/')) {
    // …but never a black screen while the Mac mini is slow or asleep: after 4 s the kept copy opens (it says when it
    // can't reach the Mac mini), and the newest build is kept for next time when it arrives
    event.respondWith((async () => {
      const net = fetch(req).then(async res => {
        if (res.ok) (await caches.open(SHELL)).put('/axella/', res.clone());
        return res;
      })
      const kept = await caches.match('/axella/')
      if (!kept) return net.catch(() => Response.error())
      net.catch(() => {})
      const late = new Promise(r => setTimeout(() => r(null), 4000))
      try {
        const res = await Promise.race([net, late])
        return res && res.ok ? res : kept           // slow, or a gateway error page (502): the kept app
      } catch (e) {
        return kept
      }
    })());
    return;
  }
  // the owner's trips, travel-day card and tickets – only what is in the trips cache: network first, the copy offline
  if (url.origin === self.location.origin && TRIP_PATHS.test(url.pathname + url.search.slice(0, 1))) {
    event.respondWith((async () => {
      const c = await caches.open(TRIPS);
      const kept = await c.match(req.url);
      if (!kept) return fetch(req);
      try {
        const res = await fetch(req);
        if (res.ok && !/\/attachment\?/.test(req.url)) await c.put(req.url, res.clone());
        if (res.status === 403) await caches.delete(TRIPS);          // not the owner (any more): nothing kept
        return res;
      } catch (e) { return kept; }
    })());
    return;
  }
  // built files have hashed names, so a cached copy is always right; fetch and keep anything not cached yet
  if (isShell(url)) {
    event.respondWith((async () => {
      const hit = await caches.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok || res.type === 'opaque') (await caches.open(SHELL)).put(req, res.clone());
      return res;
    })());
  }
});

self.addEventListener('push', event => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (e) { d = { body: event.data && event.data.text() }; }
  const title = d.title || 'Axella';
  // the count on the Home Screen icon, sent with digest pushes (same count as the dashboard's title); other pushes leave it
  if (typeof d.badge === 'number' && self.navigator.setAppBadge) {
    event.waitUntil((d.badge > 0 ? self.navigator.setAppBadge(d.badge) : self.navigator.clearAppBadge()).catch(() => {}));
  }
  event.waitUntil(self.registration.showNotification(title, {
    body: d.body || 'New digest',
    icon: 'icons/icon-192.png',
    badge: 'icons/icon-192.png',
    tag: d.tag || 'axella',
    renotify: true,
    data: { url: d.url || '/axella/' }
  }));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || '/axella/', self.location.origin).href;
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of all) {
      if (c.url.includes('/axella/')) { await c.focus(); try { await c.navigate(url); } catch (e) {} return; }
    }
    await self.clients.openWindow(url);
  })());
});
