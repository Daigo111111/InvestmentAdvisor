// 离线缓存：页面外壳缓存优先，数据文件网络优先（保证看到最新报告，断网时显示上次结果）
const VERSION = 'advisor-__BUILD__';
const SHELL = ['./', 'index.html', 'style.css', 'manifest.webmanifest', 'js/app.js', 'js/store.js', 'js/crypto.js',
  'js/ui.js', 'js/views.js', 'js/views2.js', 'js/holdings.js', 'js/ocr.js', 'js/live.js', 'icons/icon-192.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k.startsWith('advisor-') && k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.includes('/data/')) {
    e.respondWith(fetch(e.request).then((r) => {
      if (r.ok) {
        const copy = r.clone();
        caches.open(VERSION).then((c) => c.put(url.pathname, copy));
      }
      return r;
    }).catch(() => caches.match(url.pathname)));
    return;
  }
  // 页面导航网络优先（保证拿到新版本），静态资源缓存优先
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).catch(() => caches.match('index.html')));
    return;
  }
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then((hit) => hit || fetch(e.request)));
});
