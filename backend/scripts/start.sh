#!/bin/sh
set -eu

if [ "${RUN_MIGRATIONS_ON_STARTUP:-0}" = "1" ]; then
  python manage.py migrate --noinput
fi

if [ "${RUN_SEED_ON_STARTUP:-0}" = "1" ]; then
  python manage.py seed_default_departments_and_metrics_if_empty
fi

exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8080}" \
  --workers "${GUNICORN_WORKERS:-2}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-120}"
