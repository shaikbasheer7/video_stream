#!/bin/sh
set -e

# Only the API container migrates; consumers set RUN_MIGRATIONS=0.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi

# Local stack only: create the bucket and Kafka topics. In AWS these come from IaC.
if [ "${ENSURE_INFRA:-0}" = "1" ]; then
  python manage.py ensure_infra
fi

exec "$@"
