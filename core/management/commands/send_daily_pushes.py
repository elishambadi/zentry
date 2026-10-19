"""Send the once-a-day task digest as a Web Push notification.

Run from cron every few minutes; the command only sends inside each user's
configured reminder window and records the last sent date to prevent
duplicates.

    python manage.py send_daily_pushes
    python manage.py send_daily_pushes --dry-run
    python manage.py send_daily_pushes --force --user alice
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Task, UserPreference
from core.push import push_is_configured, send_push_to_user


class Command(BaseCommand):
    help = "Send daily task digest push notifications to opted-in users."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be sent without sending or recording anything.',
        )
        parser.add_argument(
            '--user',
            help='Only process this username.',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Ignore the reminder time window and the once-per-day guard.',
        )
        parser.add_argument(
            '--window',
            type=int,
            default=10,
            help='Minutes after the configured time during which a send is allowed (default: 10).',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        window = max(1, options['window'])

        if not push_is_configured():
            self.stdout.write(self.style.WARNING(
                'VAPID keys are not configured; no push notifications can be sent.'
            ))
            if not dry_run:
                return

        now_utc = timezone.now()

        preferences = UserPreference.objects.filter(
            push_enabled=True,
            daily_reminder_enabled=True,
            user__push_subscriptions__is_active=True,
        ).select_related('user').distinct()

        username = options.get('user')
        if username:
            preferences = preferences.filter(user__username=username)

        sent_total = 0
        processed = 0

        for preference in preferences.iterator():
            user = preference.user

            try:
                user_timezone = (
                    ZoneInfo(preference.timezone)
                    if preference.timezone
                    else timezone.get_current_timezone()
                )
            except (ZoneInfoNotFoundError, ValueError):
                user_timezone = timezone.get_current_timezone()

            local_now = now_utc.astimezone(user_timezone)
            today = local_now.date()
            current_minutes = local_now.hour * 60 + local_now.minute

            if not force and preference.last_daily_reminder_sent == today:
                continue

            target = preference.daily_reminder_time
            if target is None:
                continue

            target_minutes = target.hour * 60 + target.minute
            delta = current_minutes - target_minutes
            if not force and not (0 <= delta < window):
                continue

            tasks = Task.objects.filter(
                user=user,
                date=today,
                is_recurring_template=False,
                is_dead=False,
            )
            total = tasks.count()
            completed = tasks.filter(completed=True).count()
            pending = total - completed

            if pending > 0:
                title = f"{pending} task{'s' if pending != 1 else ''} left today"
                next_task = tasks.filter(completed=False).order_by('created_at').first()
                if next_task:
                    body = f"Next: {next_task.title}"
                else:
                    body = f"You've completed {completed} of {total} tasks."
            elif total > 0:
                title = 'All tasks complete'
                body = 'Everything is checked off. Enjoy the rest of your day.'
            else:
                title = 'A fresh day'
                body = 'No tasks yet — add one small win to get started.'

            processed += 1

            if dry_run:
                self.stdout.write(
                    f'[dry-run] {user.username}: {title} — {body}'
                )
                continue

            stats = send_push_to_user(
                user,
                title=title,
                body=body,
                url='/dashboard/',
                tag='zentry-daily',
            )

            if stats.get('sent', 0) > 0:
                preference.last_daily_reminder_sent = today
                preference.save(update_fields=['last_daily_reminder_sent', 'updated_at'])

            sent_total += stats.get('sent', 0)
            self.stdout.write(
                self.style.SUCCESS(
                    f'{user.username}: sent={stats.get("sent", 0)} '
                    f'failed={stats.get("failed", 0)} gone={stats.get("gone", 0)}'
                )
            )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'[dry-run] {processed} user(s) matched.')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Processed {processed} user(s); delivered {sent_total} notification(s).'
                )
            )
