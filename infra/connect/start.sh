#!/bin/sh
# Start the Connect worker, then create or update the lake connector. Safe on every restart: PUT is idempotent.
set -eu

/etc/confluent/docker/run &
worker=$!
trap 'kill "$worker"' TERM INT

until curl -fsS localhost:8083/connectors >/dev/null 2>&1; do
  kill -0 "$worker" || exit 1
  sleep 3
done

sed -e "s|\${S3_BUCKET}|$S3_BUCKET|" -e "s|\${AWS_REGION}|$AWS_REGION|" -e "s|\${S3_ENDPOINT_URL}|$S3_ENDPOINT_URL|" \
  /etc/lake/lake-sink.json >/tmp/lake-sink.json
curl -fsS -X PUT -H 'Content-Type: application/json' --data @/tmp/lake-sink.json \
  localhost:8083/connectors/lake-sink/config >/dev/null
echo "lake-sink connector configured"

wait "$worker"
