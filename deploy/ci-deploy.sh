#!/bin/sh
# Run from CI (or an operator's shell with the environment's deploy role) to roll a release out:
#
#   RELEASES_BUCKET=... sh deploy/ci-deploy.sh <environment> <image-tag>
#
# API host first (it runs the migrations), then the encoder hosts. Each host fetches the release's deploy
# files from S3 and runs deploy.sh via SSM Run Command; any failure stops the rollout with the host's output.
set -eu

ENVIRONMENT="${1:?usage: ci-deploy.sh <environment> <image-tag>}"
TAG="${2:?usage: ci-deploy.sh <environment> <image-tag>}"
: "${RELEASES_BUCKET:?RELEASES_BUCKET is required}"

instances() {
  aws ec2 describe-instances \
    --filters "Name=tag:Environment,Values=$ENVIRONMENT" "Name=tag:Role,Values=$1" "Name=instance-state-name,Values=running" \
    --query 'Reservations[].Instances[].InstanceId' --output text
}

run_on() {
  role=$1
  ids=$(instances "$role")
  if [ -z "$ids" ]; then echo "no running $role instances in $ENVIRONMENT" >&2; exit 1; fi
  echo "== $role: $ids"
  params=$(mktemp)
  # JSON built with jq so the bucket/tag can't break the quoting.
  jq -n --arg bucket "$RELEASES_BUCKET" --arg tag "$TAG" '{commands: [
      "set -eu",
      "aws s3 cp --recursive --quiet s3://\($bucket)/releases/\($tag)/ /opt/streaming/ --exclude \"tests/*\"",
      "sh /opt/streaming/deploy.sh \($tag)"
    ]}' > "$params"
  # shellcheck disable=SC2086  # $ids is a whitespace-separated list of instance ids
  command_id=$(aws ssm send-command --document-name AWS-RunShellScript --instance-ids $ids \
    --parameters "file://$params" --timeout-seconds 1800 --comment "deploy $TAG to $ENVIRONMENT ($role)" \
    --query Command.CommandId --output text)
  rm -f "$params"

  for id in $ids; do
    while :; do
      status=$(aws ssm get-command-invocation --command-id "$command_id" --instance-id "$id" \
        --query Status --output text 2>/dev/null || echo Pending)
      case "$status" in
        Pending|InProgress|Delayed) sleep 10 ;;
        *) break ;;
      esac
    done
    aws ssm get-command-invocation --command-id "$command_id" --instance-id "$id" \
      --query '[StandardOutputContent, StandardErrorContent]' --output text
    if [ "$status" != "Success" ]; then echo "deploy on $id ended with status $status" >&2; exit 1; fi
  done
}

run_on api
run_on encoder
echo "== $TAG deployed to $ENVIRONMENT"
