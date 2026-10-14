// Phone-mode service worker: caches only the page shell (so the home-screen icon opens instantly).
// Uploads and API calls are never cached. Note: browsers only run service workers in a secure context
// (https or localhost), so over plain-http LAN this file is simply not used.
const C = "gac-phone-v1", SHELL = ["/m/phone.css", "/m/phone.js", "/m/manifest.webmanifest", "/m/icon-192.png"];
self.addEventListener("install", e => e.waitUntil(caches.open(C).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== C).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.pathname.startsWith("/m/api/") || u.pathname === "/m") return;   // network only
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
