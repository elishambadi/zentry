# core/management/commands/cleanup_dead_tasks.py
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from core.models import Note, Task


class Command(BaseCommand):
    help = (
        "Retire incomplete tasks that haven't been touched in more than 30 days. "
        "A recurring series is killed as a whole only when its template is untouched. "
        "Each cleaned task gets an 'auto_cleaned' note so it can be identified when "
        "reviewing dead tasks."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Age in days without a touch before a task is retired (default: 30).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be cleaned without changing anything.',
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']
        cutoff = timezone.now() - timedelta(days=days)
        now = timezone.now()

        untouched = Q(updated_at__lt=cutoff) | Q(updated_at__isnull=True)
        killed = 0

        # ── 1) Whole recurring series, retired via their template ──────────
        stale_templates = Task.objects.filter(
            is_recurring_template=True,
            recurrence_type__in=['daily', 'weekly', 'custom'],
            is_dead=False,
        ).filter(untouched).order_by('id')

        for template in stale_templates.iterator():
            instances = Task.objects.filter(
                user=template.user,
                recurrence_source=template,
            ).exclude(is_dead=True)
            instance_ids = list(instances.values_list('id', flat=True))
            if dry_run:
                self.stdout.write(self.style.WARNING(
                    f'[dry-run] would kill recurring series: "{template.title}" '
                    f'({len(instance_ids) + 1} task(s))'
                ))
            else:
                instances.update(is_dead=True, dead_at=now)
                template.is_dead = True
                template.dead_at = now
                template.save(update_fields=['is_dead', 'dead_at'])
                Note.objects.create(task=template, content='auto_cleaned')
            killed += len(instance_ids) + 1

        # ── 2) Single, non-recurring tasks (and one-off templates) ─────────
        # Instances are skipped — they live and die with their series.
        stale_singles = Task.objects.filter(
            recurrence_source__isnull=True,
            is_dead=False,
            completed=False,
        ).exclude(
            Q(is_recurring_template=True) & Q(recurrence_type__in=['daily', 'weekly', 'custom'])
        ).filter(untouched).order_by('id')

        for task in stale_singles.iterator():
            if dry_run:
                self.stdout.write(self.style.WARNING(
                    f'[dry-run] would kill task: "{task.title}"'
                ))
            else:
                task.is_dead = True
                task.dead_at = now
                task.save(update_fields=['is_dead', 'dead_at'])
                Note.objects.create(task=task, content='auto_cleaned')
            killed += 1

        if dry_run:
            self.stdout.write(self.style.NOTICE(
                f'[dry-run] would retire {killed} task(s) untouched for >{days} days.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Retired {killed} task(s) untouched for >{days} days.'
            ))