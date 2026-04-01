#!/bin/sh
set -e

until python manage.py migrate --noinput; do
  echo "Database unavailable, retrying migrations in 2 seconds..."
  sleep 2
done

exec gunicorn --bind 0.0.0.0:8000 coretrack.wsgi:application
