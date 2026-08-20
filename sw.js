// Cache everything up front so the app works with no signal in the venue.
const CACHE = 'beervana-v26';
const FILES = ['./', 'index.html', 'data.json', 'manifest.json', 'icon.svg'];

// cache: 'reload' forces each precache fetch to the network. Without it addAll
// is served by the browser's HTTP cache, which happily hands back the previous
// deploy - so a fresh worker installs with stale files inside it.
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE)
    .then(c => c.addAll(FILES.map(u => new Request(u, { cache: 'reload' }))))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// Network first, falling back to cache. Still works with no signal, but never
// serves a stale build while there is a connection.
//
// Our own files are revalidated with the server rather than taken from the
// browser's HTTP cache, which GitHub Pages lets sit for ten minutes - long
// enough for "network first" to still hand back the previous deploy.
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const sameOrigin = new URL(e.request.url).origin === self.location.origin;
  const req = sameOrigin ? new Request(e.request, { cache: 'no-cache' }) : e.request;
  e.respondWith(
    fetch(req)
      .then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request).then(hit => hit || caches.match('index.html')))
  );
});
