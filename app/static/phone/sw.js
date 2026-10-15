// Phone-mode service worker: keeps a copy of the page shell (so the home-screen icon still opens when the network blips).
// Uploads and API calls are never cached. Note: browsers only run service workers in a secure context
// (https or localhost), so over plain-http LAN this file is simply not used.
// audit 2026-10: it was cache-first under a fixed cache name, so an updated phone.js was never seen. Now the network comes
// first (the cached copy is only a fallback when offline), and caches of older versions are deleted on activate.
const C = "gac-phone-v2", SHELL = ["/m/phone.css", "/m/phone.js", "/m/manifest.webmanifest", "/m/icon-192.png"];
self.addEventListener("install", e => e.waitUntil(caches.open(C).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== C).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/m/api/") || u.pathname === "/m") return;   // network only
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok && SHELL.includes(u.pathname)) { const copy = r.clone(); caches.open(C).then(c => c.put(e.request, copy)).catch(() => {}); }
    return r;
  }).catch(() => caches.match(e.request).then(r => r || Response.error())));
});
