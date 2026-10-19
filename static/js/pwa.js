/*
 * Zentry PWA bootstrap
 * ────────────────────
 * • Registers the service worker (and keeps it fresh).
 * • Shows a custom "Install app" banner for Chrome/Edge/Android.
 * • Shows Add-to-Home-Screen instructions on iOS Safari.
 * • Surfaces offline/online state via the shared toast helper.
 */

(function () {
  'use strict';

  const DISMISS_KEY = 'zentry-install-dismissed-at';
  const DISMISS_FOR_MS = 14 * 24 * 60 * 60 * 1000; // 14 days
  const isBrowser = typeof window !== 'undefined';

  let deferredInstallPrompt = null;
  let registration = null;
  let updateNotified = false;

  function isStandalone() {
    const media = window.matchMedia && window.matchMedia('(display-mode: standalone)').matches;
    return Boolean(media || window.navigator.standalone === true);
  }

  function isIos() {
    const ua = window.navigator.userAgent || '';
    const iOSDevice = /iPad|iPhone|iPod/.test(ua);
    const iPadOS = /Macintosh/.test(ua) && (window.navigator.maxTouchPoints || 0) > 1;
    return iOSDevice || iPadOS;
  }

  function isIosSafari() {
    if (!isIos()) return false;
    const ua = window.navigator.userAgent || '';
    // Chrome/Firefox/Edge on iOS cannot install PWAs.
    return !/CriOS|FxiOS|EdgiOS|OPiOS/.test(ua);
  }

  function recentlyDismissed() {
    const raw = window.localStorage.getItem(DISMISS_KEY);
    if (!raw) return false;
    const dismissedAt = Number(raw);
    if (!Number.isFinite(dismissedAt)) return false;
    return Date.now() - dismissedAt < DISMISS_FOR_MS;
  }

  function bannerElement() {
    return document.getElementById('pwa-install-banner');
  }

  function setBannerText(title, subtitle, buttonLabel) {
    const titleEl = document.getElementById('pwa-install-title');
    const subtitleEl = document.getElementById('pwa-install-subtitle');
    const buttonEl = document.getElementById('pwa-install-action');
    if (titleEl) titleEl.textContent = title;
    if (subtitleEl) subtitleEl.textContent = subtitle;
    if (buttonEl) buttonEl.textContent = buttonLabel;
  }

  function hideBanner() {
    const banner = bannerElement();
    if (banner) banner.classList.add('hidden');
  }

  function showBanner(mode) {
    const banner = bannerElement();
    if (!banner || isStandalone() || recentlyDismissed()) return;

    if (mode === 'ios') {
      setBannerText(
        'Install Zentry',
        'Tap the Share button, then “Add to Home Screen”.',
        'Got it'
      );
    } else {
      setBannerText(
        'Install Zentry',
        'Add it to your home screen for a faster, full-screen experience.',
        'Install'
      );
    }

    banner.dataset.mode = mode;
    banner.classList.remove('hidden');
  }

  async function promptInstall() {
    if (deferredInstallPrompt) {
      deferredInstallPrompt.prompt();
      const choice = await deferredInstallPrompt.userChoice;
      deferredInstallPrompt = null;
      if (choice && choice.outcome === 'accepted') {
        hideBanner();
        return 'accepted';
      }
      return 'dismissed';
    }

    if (isIosSafari()) {
      showBanner('ios');
      return 'ios-instructions';
    }

    return 'unavailable';
  }

  function wireBanner() {
    const action = document.getElementById('pwa-install-action');
    const dismiss = document.getElementById('pwa-install-dismiss');
    const banner = bannerElement();

    if (action) {
      action.addEventListener('click', async () => {
        const mode = banner && banner.dataset.mode;
        if (mode === 'ios') {
          hideBanner();
          return;
        }
        const result = await promptInstall();
        if (result !== 'accepted') {
          hideBanner();
        }
      });
    }

    if (dismiss) {
      dismiss.addEventListener('click', () => {
        window.localStorage.setItem(DISMISS_KEY, String(Date.now()));
        hideBanner();
      });
    }
  }

  function wireInstallEvents() {
    window.addEventListener('beforeinstallprompt', (event) => {
      event.preventDefault();
      deferredInstallPrompt = event;
      window.dispatchEvent(new CustomEvent('zentry:install-available'));
      showBanner('prompt');
    });

    window.addEventListener('appinstalled', () => {
      deferredInstallPrompt = null;
      window.localStorage.removeItem(DISMISS_KEY);
      hideBanner();
      if (typeof window.showToast === 'function') {
        window.showToast('Zentry installed. Open it from your home screen.', 'success');
      }
    });

    if (isIosSafari() && !isStandalone()) {
      window.setTimeout(() => showBanner('ios'), 2500);
    }
  }

  async function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return null;

    try {
      registration = await navigator.serviceWorker.register('/service-worker.js', {
        scope: '/',
        updateViaCache: 'none',
      });

      registration.update().catch(() => {});

      // Check for a new deployment while the app stays open.
      window.setInterval(() => {
        registration.update().catch(() => {});
      }, 60 * 60 * 1000);

      registration.addEventListener('updatefound', () => {
        const installing = registration.installing;
        if (!installing) return;

        installing.addEventListener('statechange', () => {
          if (installing.state !== 'installed') return;
          if (!navigator.serviceWorker.controller) return; // first install
          if (!updateNotified) {
            updateNotified = true;
            if (typeof window.showToast === 'function') {
              window.showToast('Zentry updated. Refresh for the latest version.', 'info');
            }
          }
        });
      });

      // A browser may rotate the push subscription; re-register it.
      navigator.serviceWorker.addEventListener('message', (event) => {
        if (event.data && event.data.type === 'PUSH_SUBSCRIPTION_CHANGED') {
          if (window.zentryNotify && typeof window.zentryNotify.resubscribe === 'function') {
            window.zentryNotify.resubscribe().catch(() => {});
          }
        }
      });

      return registration;
    } catch (error) {
      // A failed service worker registration must never break the app.
      return null;
    }
  }

  function wireConnectivity() {
    window.addEventListener('offline', () => {
      if (typeof window.showToast === 'function') {
        window.showToast("You're offline. Some pages may be unavailable.", 'warning');
      }
    });

    window.addEventListener('online', () => {
      if (typeof window.showToast === 'function') {
        window.showToast('Back online.', 'success');
      }
    });
  }

  if (isBrowser) {
    wireBanner();
    wireInstallEvents();
    wireConnectivity();

    if (document.readyState === 'complete') {
      registerServiceWorker();
    } else {
      window.addEventListener('load', registerServiceWorker);
    }
  }

  window.zentryPWA = {
    isStandalone,
    isIos,
    canInstall: () => Boolean(deferredInstallPrompt),
    promptInstall,
    showBanner,
    hideBanner,
    getRegistration: () => registration || navigator.serviceWorker.ready,
  };
})();
