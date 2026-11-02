#!/bin/sh
# Deploy one release on this host. Run as root by SSM Run Command (see ci-deploy.sh), from /opt/streaming:
#
#   sh deploy.sh <image-tag>
#
# 1. render .env from SSM + Secrets Manager   2. pull the images for this host's role
# 3. API host only: migrate + ensure Kafka topics / Mongo indexes, before the new code starts
# 4. start the new containers   5. wait until healthy, else exit non-zero (CI then stops the rollout)
set -eu

TAG="${1:?usage: deploy.sh <image-tag>}"
cd /opt/streaming
# shellcheck disable=SC1091  # written at first boot by Terraform user_data
. ./host.env
export AWS_REGION AWS_DEFAULT_REGION="$AWS_REGION"

log() { printf '%s deploy[%s] %s\n' "$(date -u +%FT%TZ)" "$ROLE" "$*"; }

log "rendering configuration"
umask 077
mkdir -p secrets
aws ssm get-parameter --name "$CONFIG_PARAMETER" --query Parameter.Value --output text > config.json
aws secretsmanager get-secret-value --secret-id "$APP_SECRET_ID" --query SecretString --output text > app.json
aws secretsmanager get-secret-value --secret-id "$DB_SECRET_ID" --query SecretString --output text > db.json
rm -f secrets/cloudfront.pem
if ! python3 render_env.py config.json app.json db.json host.env --pem-out secrets/cloudfront.pem > .env.new; then
  rm -f app.json db.json .env.new
  exit 1
fi
rm -f app.json db.json
mv .env.new .env
chown 1000:1000 secrets/cloudfront.pem # the app user inside the containers

log "pulling images $TAG"
aws ecr get-login-password | docker login --username AWS --password-stdin "$ECR_REGISTRY" >/dev/null
export IMAGE_TAG="$TAG"
compose() { docker compose -f compose.prod.yml --profile "$ROLE" "$@"; }
compose pull --quiet

if [ "$ROLE" = "api" ]; then
  # Migrations must be backward compatible: the old version keeps serving until `up` below (runbook).
  log "migrating database"
  compose run --rm --no-deps django python manage.py migrate --noinput
  log "ensuring Kafka topics and MongoDB indexes"
  compose run --rm --no-deps django python manage.py ensure_infra --skip-s3
fi

log "starting containers"
compose up -d --remove-orphans

log "waiting for health"
if [ "$ROLE" = "api" ]; then services="django nginx status-consumer analytics-consumer notify-consumer feed-consumer"; else services="encoder"; fi
deadline=$(( $(date +%s) + 300 ))
for service in $services; do
  while :; do
    id=$(compose ps -q "$service")
    state=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id" 2>/dev/null || echo missing)
    case "$state" in
      healthy|running) log "$service: $state"; break ;;
      unhealthy|exited|dead|missing) log "$service: $state"; compose logs --tail 50 "$service"; exit 1 ;;
    esac
    if [ "$(date +%s)" -gt "$deadline" ]; then log "$service: still $state after 5 minutes"; exit 1; fi
    sleep 5
  done
done

[ -f current_tag ] && cp current_tag previous_tag
echo "$TAG" > current_tag
docker image prune -af --filter "until=168h" >/dev/null || true
log "deployed $TAG"
