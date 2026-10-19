"""Template context shared by every page (PWA / Web Push settings)."""

from django.conf import settings


def pwa(request):
    return {
        'vapid_public_key': getattr(settings, 'VAPID_PUBLIC_KEY', ''),
        'push_configured': bool(
            getattr(settings, 'VAPID_PUBLIC_KEY', '')
            and getattr(settings, 'VAPID_PRIVATE_KEY', '')
        ),
    }
