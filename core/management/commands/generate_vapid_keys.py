"""Generate a VAPID key pair for Web Push.

Usage:
    python manage.py generate_vapid_keys
    python manage.py generate_vapid_keys --write-env
    python manage.py generate_vapid_keys --json
"""

import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from django.conf import settings
from django.core.management.base import BaseCommand
from py_vapid import Vapid, b64urlencode


class Command(BaseCommand):
    help = 'Generate a VAPID public/private key pair for Web Push.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--write-env',
            action='store_true',
            help='Write/update VAPID_* values in the project .env file.',
        )
        parser.add_argument(
            '--json',
            action='store_true',
            help='Emit the key pair as JSON instead of .env lines.',
        )

    def handle(self, *args, **options):
        vapid = Vapid()
        vapid.generate_keys()

        raw_public_key = vapid.public_key.public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        public_key = b64urlencode(raw_public_key)
        private_key = vapid.private_pem().decode('utf-8')

        if options['json']:
            self.stdout.write(json.dumps({
                'VAPID_PUBLIC_KEY': public_key,
                'VAPID_PRIVATE_KEY': private_key,
            }, indent=2))
        else:
            self.stdout.write('Add these to your .env (or container environment):\n')
            self.stdout.write(f'VAPID_PUBLIC_KEY={public_key}')
            self.stdout.write(
                'VAPID_PRIVATE_KEY=' + private_key.replace('\n', '\\n').strip()
            )
            self.stdout.write(
                f'VAPID_ADMIN_EMAIL={settings.VAPID_ADMIN_EMAIL}'
            )

        if options['write_env']:
            env_path = Path(settings.BASE_DIR) / '.env'
            self._write_env(env_path, public_key, private_key)
            self.stdout.write(self.style.SUCCESS(f'\nUpdated {env_path}'))

    def _write_env(self, env_path, public_key, private_key):
        escaped_private_key = private_key.replace('\n', '\\n').strip()
        updates = {
            'VAPID_PUBLIC_KEY': public_key,
            'VAPID_PRIVATE_KEY': escaped_private_key,
            'VAPID_ADMIN_EMAIL': settings.VAPID_ADMIN_EMAIL,
        }

        lines = []
        if env_path.exists():
            lines = env_path.read_text().splitlines()

        seen = set()
        output = []
        for line in lines:
            key = line.split('=', 1)[0].strip()
            if key in updates:
                output.append(f'{key}={updates[key]}')
                seen.add(key)
            else:
                output.append(line)

        for key, value in updates.items():
            if key not in seen:
                output.append(f'{key}={value}')

        env_path.write_text('\n'.join(output).rstrip() + '\n')
