import json
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import PushSubscription, UserPreference


@override_settings(
    VAPID_PUBLIC_KEY='test-public-key',
    VAPID_PRIVATE_KEY='test-private-key',
)
class PwaTests(TestCase):
    def test_manifest_is_installable(self):
        response = self.client.get(reverse('pwa_manifest'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/manifest+json', response['Content-Type'])

        manifest = json.loads(response.content)
        sizes = {(icon['sizes'], icon['type']) for icon in manifest['icons']}
        self.assertIn(('192x192', 'image/png'), sizes)
        self.assertIn(('512x512', 'image/png'), sizes)
        self.assertTrue(any(icon['purpose'] == 'maskable' for icon in manifest['icons']))
        self.assertEqual(manifest['scope'], '/')

    def test_service_worker_has_push_and_offline_support(self):
        response = self.client.get(reverse('service_worker'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Service-Worker-Allowed'], '/')

        content = response.content.decode()
        self.assertIn("addEventListener('push'", content)
        self.assertIn("addEventListener('notificationclick'", content)
        self.assertIn('/offline/', content)
        # Personalized HTML must not be cached.
        self.assertNotIn('caches.open(CACHE_NAME)', content)

    def test_offline_page_is_public_and_self_contained(self):
        response = self.client.get(reverse('offline'))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('cdn.tailwindcss.com', response.content.decode())


@override_settings(
    VAPID_PUBLIC_KEY='test-public-key',
    VAPID_PRIVATE_KEY='test-private-key',
)
class PushNotificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='pusher',
            email='pusher@example.com',
            password='test-pass-123',
        )
        self.preferences = UserPreference.objects.create(user=self.user)
        self.client.force_login(self.user)
        self.subscription = {
            'endpoint': 'https://push.example.com/subscription/1',
            'keys': {
                'p256dh': 'B' * 88,
                'auth': 'A' * 24,
            },
        }

    def test_status_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('push_status'))
        self.assertIn(response.status_code, (302, 403))

    def test_subscribe_and_unsubscribe(self):
        response = self.client.post(
            reverse('push_subscribe'),
            data=json.dumps({'subscription': self.subscription}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['device_count'], 1)
        self.assertEqual(PushSubscription.objects.filter(user=self.user, is_active=True).count(), 1)

        self.preferences.refresh_from_db()
        self.assertTrue(self.preferences.push_enabled)

        response = self.client.post(
            reverse('push_unsubscribe'),
            data=json.dumps({'endpoint': self.subscription['endpoint']}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['device_count'], 0)

        self.preferences.refresh_from_db()
        self.assertFalse(self.preferences.push_enabled)

    def test_subscribe_rejects_insecure_endpoint(self):
        response = self.client.post(
            reverse('push_subscribe'),
            data=json.dumps({
                'subscription': {
                    **self.subscription,
                    'endpoint': 'http://insecure.example.com/subscription',
                }
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_subscribe_rejects_missing_keys(self):
        response = self.client.post(
            reverse('push_subscribe'),
            data=json.dumps({'subscription': {'endpoint': self.subscription['endpoint']}}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    @mock.patch('core.views.send_push_to_user', return_value={'sent': 1})
    def test_test_notification_requires_a_device(self, mocked_send):
        response = self.client.post(
            reverse('push_test'),
            data='{}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        mocked_send.assert_not_called()

        self.client.post(
            reverse('push_subscribe'),
            data=json.dumps({'subscription': self.subscription}),
            content_type='application/json',
        )
        response = self.client.post(
            reverse('push_test'),
            data='{}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        mocked_send.assert_called_once()


class UserPreferenceNotificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='prefuser',
            email='pref@example.com',
            password='test-pass-123',
        )
        self.client.force_login(self.user)

    def test_preferences_save_notification_settings(self):
        response = self.client.post(
            reverse('preferences'),
            data={
                'default_page': 'pomodoro',
                'monthly_books': '',
                'favorite_authors': '',
                'pomodoro_notifications': 'on',
                'daily_reminder_enabled': 'on',
                'daily_reminder_time': '07:30',
                'timezone': 'Europe/Lisbon',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)

        preferences = UserPreference.objects.get(user=self.user)
        self.assertTrue(preferences.pomodoro_notifications)
        self.assertTrue(preferences.daily_reminder_enabled)
        self.assertEqual(preferences.daily_reminder_time.strftime('%H:%M'), '07:30')
        self.assertEqual(preferences.timezone, 'Europe/Lisbon')

    def test_daily_push_command_dry_run(self):
        UserPreference.objects.update_or_create(
            user=self.user,
            defaults={
                'push_enabled': True,
                'daily_reminder_enabled': True,
                'timezone': 'UTC',
            },
        )
        PushSubscription.objects.create(
            user=self.user,
            endpoint='https://push.example.com/subscription/daily-test',
            p256dh='B' * 88,
            auth='A' * 24,
        )

        output = StringIO()
        call_command('send_daily_pushes', '--dry-run', '--force', stdout=output)
        self.assertIn('dry-run', output.getvalue())
        self.assertIn(self.user.username, output.getvalue())
