/* Urai service worker — app-shell cache only.
 *
 * Rules:
 *   - Never cache API traffic (/v1/*, /health, /vibe, /agent) so answers,
 *     tokens and agent runs are always live.
 *   - Cache-first for the shell (works offline / on flaky hardware).
 *   - Network responses are copied into the cache for next time.
 */
const CACHE = 'urai-shell-v3';
const SHELL = [
  './',
  './app.html',
  './manifest.webmanifest',
  './icon.svg',
  './icon-192.png',
  './icon-512.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(SHELL).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function isApi(url) {
  return url.pathname.startsWith('/v1/') ||
         url.pathname === '/health' ||
         url.pathname === '/vibe' ||
         url.pathname.startsWith('/agent') ||
         url.pathname.startsWith('/superadmin');
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;

  let url;
  try { url = new URL(req.url); } catch { return; }
  if (url.origin !== self.location.origin) return;   // fonts/CDN: browser handles
  if (isApi(url)) return;                            // always network

  e.respondWith(
    caches.match(req).then((hit) => {
      if (hit) return hit;
      return fetch(req).then((resp) => {
        if (resp && resp.ok) {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return resp;
      }).catch(() => caches.match('./app.html'));
    })
  );
});
