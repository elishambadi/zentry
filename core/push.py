"""Web Push helpers.

The push backend is optional: if VAPID keys are not configured the app keeps
working, and the JSON endpoints report that push is unavailable. This lets
local/dev installs (and tests) run without external credentials.
"""

import json
import logging

from django.conf import settings
from django.templatetags.static import static
from django.utils import timezone

from .models import PushSubscription

logger = logging.getLogger('core.push')

# Subscriptions that repeatedly fail are deactivated after this many attempts.
MAX_FAILURES = 5


def push_is_configured():
    """Return True when both halves of the VAPID key pair are present."""
    return bool(
        getattr(settings, 'VAPID_PUBLIC_KEY', '')
        and getattr(settings, 'VAPID_PRIVATE_KEY', '')
    )


def _vapid_subject():
    subject = getattr(settings, 'VAPID_ADMIN_EMAIL', '') or 'admin@example.com'
    if subject.startswith('mailto:') or subject.startswith('https://'):
        return subject
    return f'mailto:{subject}'


def send_push_to_subscription(
    subscription,
    title,
    body,
    url='/dashboard/',
    tag=None,
    require_interaction=False,
):
    """Send one push message to one stored subscription.

    Returns one of: ``sent``, ``gone``, ``failed``, ``unconfigured``, ``error``.
    """
    if not push_is_configured():
        return 'unconfigured'

    # Imported lazily so the rest of the app runs even if pywebpush is not
    # installed yet (for example during a partial deployment).
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.error('[push] pywebpush is not installed; cannot send notifications')
        return 'unconfigured'

    payload = json.dumps({
        'title': title,
        'body': body,
        'url': url or '/dashboard/',
        'tag': tag or 'zentry',
        'icon': static('icons/icon-192.png'),
        'badge': static('icons/badge-72.png'),
        'requireInteraction': bool(require_interaction),
    })

    try:
        webpush(
            subscription_info=subscription.subscription_info,
            data=payload,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={'sub': _vapid_subject()},
            timeout=10,
        )
    except WebPushException as exc:
        status_code = getattr(exc.response, 'status_code', None)
        if status_code in (404, 410):
            subscription.is_active = False
            subscription.save(update_fields=['is_active', 'updated_at'])
            logger.info(
                '[push] subscription expired (HTTP %s) for user=%s',
                status_code,
                subscription.user_id,
            )
            return 'gone'

        subscription.failure_count += 1
        if subscription.failure_count >= MAX_FAILURES:
            subscription.is_active = False
        subscription.save(update_fields=['failure_count', 'is_active', 'updated_at'])
        logger.warning(
            '[push] delivery failed (HTTP %s) for user=%s: %s',
            status_code,
            subscription.user_id,
            exc,
        )
        return 'failed'
    except Exception:  # pragma: no cover - defensive: network/TLS errors
        logger.exception('[push] unexpected delivery error for user=%s', subscription.user_id)
        return 'error'

    subscription.last_used_at = timezone.now()
    subscription.failure_count = 0
    subscription.is_active = True
    subscription.save(update_fields=['last_used_at', 'failure_count', 'is_active', 'updated_at'])
    return 'sent'


def send_push_to_user(
    user,
    title,
    body,
    url='/dashboard/',
    tag=None,
    require_interaction=False,
):
    """Send a push to every active device the user has subscribed.

    Returns a dict with the number of sent/failed/gone/unconfigured devices.
    """
    stats = {'sent': 0, 'failed': 0, 'gone': 0, 'unconfigured': 0, 'error': 0}

    if not push_is_configured():
        stats['unconfigured'] = user.push_subscriptions.filter(is_active=True).count()
        return stats

    subscriptions = list(user.push_subscriptions.filter(is_active=True))
    for subscription in subscriptions:
        result = send_push_to_subscription(
            subscription,
            title=title,
            body=body,
            url=url,
            tag=tag,
            require_interaction=require_interaction,
        )
        stats[result] = stats.get(result, 0) + 1

    return stats


def deactivate_subscription(user, endpoint):
    """Mark a subscription inactive (used when the browser unsubscribes)."""
    updated = PushSubscription.objects.filter(
        user=user,
        endpoint=endpoint,
    ).update(is_active=False)
    return bool(updated)
