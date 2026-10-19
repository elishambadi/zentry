/*
 * Zentry notifications
 * ────────────────────
 * Shared helper used by the preferences page and the Pomodoro timer.
 *
 * - Requests Notification permission only from an explicit user gesture.
 * - Registers a Web Push subscription and persists it via /push/subscribe/.
 * - Falls back to "local only" notifications when VAPID keys are absent.
 * - Exposes window.zentryNotify for other views.
 */

(function () {
  'use strict';

  const configElement = document.getElementById('zentry-notify-config');
  let config = {};
  if (configElement) {
    try {
      config = JSON.parse(configElement.textContent || '{}');
    } catch (error) {
      config = {};
    }
  }

  const state = {
    permission: typeof Notification !== 'undefined' ? Notification.permission : 'unsupported',
    configured: Boolean(config.pushConfigured),
    deviceCount: 0,
    pushEnabled: false,
    dailyReminderEnabled: false,
    dailyReminderTime: '08:00',
  };

  function supported() {
    return typeof Notification !== 'undefined';
  }

  function pushSupported() {
    return Boolean(
      supported() &&
      'serviceWorker' in navigator &&
      'PushManager' in window
    );
  }

  function getCsrfToken() {
    if (config.csrfToken) return config.csrfToken;
    const match = document.cookie
      .split('; ')
      .find((row) => row.startsWith('csrftoken='));
    return match ? decodeURIComponent(match.split('=')[1]) : '';
  }

  async function postJson(url, body) {
    if (!url) throw new Error('Notification endpoint is not configured.');

    const response = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: JSON.stringify(body || {}),
    });

    let data = {};
    try {
      data = await response.json();
    } catch (error) {
      data = {};
    }

    if (!response.ok || data.success === false) {
      throw new Error(data.error || 'Notification request failed.');
    }
    return data;
  }

  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding)
      .replace(/-/g, '+')
      .replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  async function getRegistration() {
    if (!('serviceWorker' in navigator)) return null;
    try {
      return await navigator.serviceWorker.ready;
    } catch (error) {
      return null;
    }
  }

  async function requestPermission() {
    if (!supported()) {
      throw new Error('This browser does not support notifications.');
    }
    if (Notification.permission === 'granted') {
      state.permission = 'granted';
      return 'granted';
    }
    if (Notification.permission === 'denied') {
      throw new Error(
        'Notifications are blocked for Zentry. Allow them in your browser settings, then try again.'
      );
    }
    const permission = await Notification.requestPermission();
    state.permission = permission;
    if (permission !== 'granted') {
      throw new Error('Notification permission was not granted.');
    }
    return permission;
  }

  async function createPushSubscription() {
    if (!config.vapidPublicKey) {
      throw new Error('Server push keys are not configured.');
    }

    const registration = await getRegistration();
    if (!registration) {
      throw new Error('The service worker is not ready yet. Reload and try again.');
    }

    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(config.vapidPublicKey),
      });
    }

    await postJson(config.urls.subscribe, {
      subscription: subscription.toJSON(),
    });

    return subscription;
  }

  async function enableNotifications() {
    const permission = await requestPermission();

    if (!state.configured || !pushSupported()) {
      // Local notifications still work even without server push keys.
      return {
        permission,
        localOnly: true,
        deviceCount: state.deviceCount,
        message:
          'Browser alerts enabled. Server push is not configured, so daily reminders are unavailable.',
      };
    }

    await createPushSubscription();
    await refreshStatus();

    return {
      permission,
      localOnly: false,
      deviceCount: state.deviceCount,
      message: 'Push notifications enabled for this device.',
    };
  }

  async function disableNotifications() {
    let endpoint = '';

    if (pushSupported()) {
      const registration = await getRegistration();
      if (registration) {
        const subscription = await registration.pushManager.getSubscription();
        if (subscription) {
          endpoint = subscription.endpoint;
          try {
            await subscription.unsubscribe();
          } catch (error) {
            // Still tell the server to drop it.
          }
        }
      }
    }

    if (config.urls.unsubscribe) {
      await postJson(config.urls.unsubscribe, { endpoint });
    }

    await refreshStatus();
    return {
      deviceCount: state.deviceCount,
      message: 'Push notifications disabled.',
    };
  }

  async function sendTestNotification() {
    return postJson(config.urls.test, {});
  }

  async function refreshStatus() {
    if (!config.urls || !config.urls.status) return state;

    try {
      const response = await fetch(config.urls.status, {
        credentials: 'same-origin',
        headers: { 'Accept': 'application/json' },
      });
      if (!response.ok) return state;

      const data = await response.json();
      state.permission = supported() ? Notification.permission : 'unsupported';
      state.configured = Boolean(data.configured);
      state.deviceCount = data.device_count || 0;
      state.pushEnabled = Boolean(data.push_enabled);
      state.dailyReminderEnabled = Boolean(data.daily_reminder_enabled);
      state.dailyReminderTime = data.daily_reminder_time || '08:00';

      window.dispatchEvent(new CustomEvent('zentry:notifications-status', {
        detail: { ...state },
      }));
      return state;
    } catch (error) {
      return state;
    }
  }

  async function resubscribe() {
    if (!state.configured || !config.vapidPublicKey) return null;
    if (!supported() || Notification.permission !== 'granted') return null;
    try {
      return await createPushSubscription();
    } catch (error) {
      return null;
    }
  }

  function pomodoroNotificationsEnabled() {
    if (typeof window.ZENTRY_POMODORO_NOTIFICATIONS === 'boolean') {
      return window.ZENTRY_POMODORO_NOTIFICATIONS;
    }
    return window.localStorage.getItem('zentry-pomodoro-notifications') !== 'false';
  }

  async function showNotification(title, options) {
    if (!supported() || Notification.permission !== 'granted') return false;

    const settings = options || {};
    if (settings.requirePomodoroPreference && !pomodoroNotificationsEnabled()) {
      return false;
    }

    const iconFallback = (config.icons && config.icons.icon) || '/static/icons/icon-192.png';
    const badgeFallback = (config.icons && config.icons.badge) || '/static/icons/badge-72.png';

    const notificationOptions = {
      body: settings.body || '',
      icon: settings.icon || iconFallback,
      badge: settings.badge || badgeFallback,
      tag: settings.tag || 'zentry',
      renotify: true,
      requireInteraction: Boolean(settings.requireInteraction),
      vibrate: settings.vibrate || [80, 40, 80],
      data: { url: settings.url || '/dashboard/' },
    };

    try {
      const registration = await getRegistration();
      if (registration && typeof registration.showNotification === 'function') {
        await registration.showNotification(title, notificationOptions);
        return true;
      }
    } catch (error) {
      // Fall through to the constructor below where supported.
    }

    try {
      new Notification(title, notificationOptions);
      return true;
    } catch (error) {
      return false;
    }
  }

  window.zentryNotify = {
    supported,
    pushSupported,
    getPermission: () => (supported() ? Notification.permission : 'unsupported'),
    getState: () => ({ ...state }),
    refreshStatus,
    requestPermission,
    enableNotifications,
    disableNotifications,
    sendTestNotification,
    resubscribe,
    showNotification,
    pomodoroNotificationsEnabled,
  };
})();
