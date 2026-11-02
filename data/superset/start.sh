#!/bin/sh
# Prepare Superset's metadata, (re)import the dashboards from code, then start the web server.
set -eu

superset db upgrade
superset fab create-admin --username admin --firstname Local --lastname Admin --email admin@example.com \
  --password "$SUPERSET_ADMIN_PASSWORD" || true # already exists on later starts
superset init

python /app/streaming/build_assets.py /tmp/streaming-dashboards.zip
superset import-dashboards -p /tmp/streaming-dashboards.zip -u admin
rm -f /tmp/streaming-dashboards.zip # holds the read-only database password

exec /app/docker/entrypoints/run-server.sh
