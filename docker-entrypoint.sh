#!/bin/sh
set -e

echo "Waiting for database..."
until python -c "
import os, sys, psycopg
try:
    psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=3).close()
except Exception as e:
    sys.exit(1)
"; do
  sleep 1
done
echo "Database is up."

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
