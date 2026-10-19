{% load static %}
/*
 * Zentry service worker
 * ─────────────────────
 * Strategy:
 *   • App shell (offline page + icons) is precached at install.
 *   • Static assets use cache-first with a background refresh.
 *   • Navigations use network-first and fall back to /offline/.
 *   • Authenticated HTML/API responses are deliberately NOT cached, so one
 *     user's data can never leak to the next person using the browser.
 *   • Handles Web Push delivery and notification clicks.
 */

const CACHE_VERSION = 'zentry-v3';
const SHELL_CACHE = `${CACHE_VERSION}-shell`;
const ASSET_CACHE = `${CACHE_VERSION}-assets`;
const OFFLINE_URL = '/offline/';

const PRECACHE_URLS = [
  OFFLINE_URL,
  '{% static "icons/icon-192.png" %}',
  '{% static "icons/icon-512.png" %}',
  '{% static "icons/icon-maskable-192.png" %}',
  '{% static "icons/icon-maskable-512.png" %}',
  '{% static "icons/apple-touch-icon.png" %}',
  '{% static "icons/badge-72.png" %}',
];

// ── Install ───────────────────────────────────────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    // Use allSettled: one missing asset must never block the whole install.
    await Promise.allSettled(
      PRECACHE_URLS.map((url) =>
        cache.add(new Request(url, { cache: 'reload' }))
      )
    );
    await self.skipWaiting();
  })());
});

// ── Activate ──────────────────────────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys
        .filter((key) => key.startsWith('zentry-') && !key.startsWith(CACHE_VERSION))
        .map((key) => caches.delete(key))
    );
    await self.clients.claim();
  })());
});

// ── Fetch ─────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Never intercept cross-origin requests or auth/admin/push endpoints.
  if (url.origin !== self.location.origin) return;
  if (
    url.pathname.startsWith('/admin/') ||
    url.pathname.startsWith('/accounts/') ||
    url.pathname.startsWith('/push/')
  ) {
    return;
  }

  const acceptsHtml =
    request.mode === 'navigate' ||
    (request.headers.get('accept') || '').includes('text/html');

  if (acceptsHtml) {
    // Network-first. We intentionally do not cache personalized HTML.
    event.respondWith((async () => {
      try {
        return await fetch(request);
      } catch (error) {
        const cached = await caches.match(OFFLINE_URL);
        if (cached) return cached;

        return new Response(
          '<!doctype html><meta charset="utf-8"><title>Offline</title>' +
          '<body style="font-family:system-ui;padding:2rem">' +
          '<h1>You are offline</h1><p>Reconnect to keep using Zentry.</p>' +
          '<button onclick="location.reload()">Retry</button></body>',
          { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
        );
      }
    })());
    return;
  }

  // Static assets: cache-first with background refresh.
  if (url.pathname.startsWith('/static/')) {
    event.respondWith((async () => {
      const cache = await caches.open(ASSET_CACHE);
      const cached = await cache.match(request);

      const network = fetch(request)
        .then((response) => {
          if (response && response.ok) {
            cache.put(request, response.clone());
          }
          return response;
        })
        .catch(() => null);

      return cached || (await network) || Response.error();
    })());
  }
});

// ── Service worker messages ───────────────────────────────────────────────────
self.addEventListener('message', (event) => {
  if (!event.data) return;

  if (event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

// ── Web Push ──────────────────────────────────────────────────────────────────
self.addEventListener('push', (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (error) {
    payload = { body: event.data ? event.data.text() : '' };
  }

  const title = payload.title || 'Zentry';
  const options = {
    body: payload.body || '',
    icon: payload.icon || '{% static "icons/icon-192.png" %}',
    badge: payload.badge || '{% static "icons/badge-72.png" %}',
    tag: payload.tag || 'zentry',
    renotify: true,
    requireInteraction: Boolean(payload.requireInteraction),
    vibrate: [80, 40, 80],
    data: {
      url: payload.url || '/dashboard/',
      sentAt: Date.now(),
    },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const targetUrl = new URL(
    (event.notification.data && event.notification.data.url) || '/dashboard/',
    self.location.origin
  ).href;

  event.waitUntil((async () => {
    const windowClients = await self.clients.matchAll({
      type: 'window',
      includeUncontrolled: true,
    });

    for (const client of windowClients) {
      const clientUrl = new URL(client.url);
      if (clientUrl.origin !== self.location.origin) continue;

      if (clientUrl.href === targetUrl) {
        return client.focus();
      }
    }

    // Prefer reusing an existing Zentry window, navigating it to the target.
    const existing = windowClients.find((client) => {
      try {
        return new URL(client.url).origin === self.location.origin;
      } catch (error) {
        return false;
      }
    });

    if (existing) {
      await existing.focus();
      if ('navigate' in existing) {
        try {
          await existing.navigate(targetUrl);
        } catch (error) {
          // Some browsers refuse navigate() on uncontrolled clients; fall back.
        }
      }
      return;
    }

    if (self.clients.openWindow) {
      await self.clients.openWindow(targetUrl);
    }
  })());
});

// Browsers occasionally rotate push subscriptions. Ask open pages to create a
// fresh subscription (pages have the CSRF token needed to persist it).
self.addEventListener('pushsubscriptionchange', (event) => {
  event.waitUntil((async () => {
    const windowClients = await self.clients.matchAll({
      type: 'window',
      includeUncontrolled: true,
    });
    windowClients.forEach((client) => {
      client.postMessage({ type: 'PUSH_SUBSCRIPTION_CHANGED' });
    });
  })());
});
