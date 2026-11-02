# Runbook: AWS deployment and operations

How the platform runs on AWS, how to set it up the first time, and what to do day to day.

## What runs where

| Piece | AWS service | Defined in |
|---|---|---|
| Web app + API + Kafka consumers + monitor | 1 EC2 host (Docker Compose, profile `api`) behind an Application Load Balancer (TLS) | `infra/terraform/modules/platform`, `deploy/compose.prod.yml` |
| FFmpeg encoders | N compute-optimised EC2 hosts (profile `encoder`) | same |
| PostgreSQL | RDS (private subnets, encrypted, 7-day point-in-time restore) | `platform/data_stores.tf` |
| Kafka | MSK, 2 brokers, TLS (private subnets) | `platform/data_stores.tf` |
| MongoDB | MongoDB Atlas (set up by hand, see step 5) | — |
| Uploads, HLS, thumbnails | Private S3 bucket | `infra/terraform/modules/media` |
| Playback | CloudFront with Origin Access Control and signed cookies | `modules/media` |
| Images | ECR (`streaming/api`, `streaming/encoder`, `streaming/web`), tag = git SHA | `infra/terraform/bootstrap` |
| Config / secrets | SSM parameter (non-secret, Terraform), Secrets Manager (app secret, RDS password) | `platform/config.tf` |
| Logs, metrics, alarms | CloudWatch Logs (`/streaming-<env>/app`), metrics `Streaming/<env>`, SNS e-mail | `platform/observability.tf` |
| CI/CD | GitHub Actions with OIDC (no stored AWS keys) | `.github/workflows/deploy.yml` |

The hosts have no SSH. Shell access and deploys use SSM. Inbound traffic reaches the API host only from the
load balancer; encoders accept no inbound traffic at all.

**Rough monthly cost, production, on-demand us-east-1, before traffic.** Check current AWS pricing; these are
estimates:

| Item | Approx. cost |
|---|---|
| Load balancer | ~$20 |
| t3.medium API host | ~$30 |
| c7i.large encoder | ~$65 |
| RDS db.t4g.small Multi-AZ | ~$50 |
| MSK, 2 × kafka.t3.small + storage | ~$75 |
| CloudWatch | ~$10 |
| MongoDB Atlas M10 | ~$60 |
| **Total** | **~$310** |

Staging is about half of that (smaller sizes, single-AZ database, Atlas M0). CloudFront and S3 cost scales
with viewing.

## First-time setup

Do these steps once, in order. You need: an AWS account, a domain you control, Terraform ≥ 1.9, the AWS CLI,
and a MongoDB Atlas account.

### 1. Bootstrap (once per AWS account)

```sh
cd infra/terraform/bootstrap
terraform init
terraform apply -var github_repository=<owner>/<repo>
terraform output   # note every value; you need them below
```

This step uses local state. Keep `terraform.tfstate` safe, or move it into the new bucket with
`terraform init -migrate-state` after adding a `backend "s3"` block.

### 2. GitHub settings

- **Repository variables:** `AWS_REGION`, `AWS_BUILD_ROLE_ARN` (`ci_build_role_arn`), `ECR_REGISTRY`,
  `RELEASES_BUCKET`.
- **Environments:** create `staging` and `production`. On `production`, add **required reviewers**: that's
  the manual approval before every production deploy.
- **Per environment:**
  - variables: `AWS_DEPLOY_ROLE_ARN` (from step 6) and `APP_URL` (e.g. `https://staging.example.com`)
  - secrets: `SMOKE_EMAIL` and `SMOKE_PASSWORD` (step 8)

### 3. Certificates and domains

The app and the CDN must share a parent domain, or the browser won't send the playback cookies to the CDN.
For example: `app.example.com` + `media.example.com` with cookie domain `.example.com` (staging:
`staging.example.com` + `media-staging.example.com`).

In ACM, request DNS-validated certificates:
- the app domain, in your region
- the CDN domain, in **us-east-1** (a CloudFront requirement)

### 4. Playback signing key (per environment)

```sh
openssl genrsa -out cf_private.pem 2048
openssl rsa -pubout -in cf_private.pem -out cf_public.pem
```

`cf_public.pem` goes into the tfvars. `cf_private.pem` goes into Secrets Manager in step 7 and is then deleted
locally. It never touches Terraform state or git (`*.pem` is git-ignored).

### 5. MongoDB Atlas (per environment)

Create a cluster (M0 is enough for staging) and a database user with `readWrite` on `streaming`. Copy the
`mongodb+srv://` connection string. The IP access list is filled in after step 6.

### 6. Create the environment

```sh
cd infra/terraform/app
cp staging.tfvars.example staging.tfvars                  # fill in
cp staging.backend.hcl.example staging.backend.hcl        # bucket/table from step 1
terraform init -backend-config=staging.backend.hcl
terraform plan  -var-file=staging.tfvars
terraform apply -var-file=staging.tfvars
```

For production, use the same commands with `production.*` (switch backends with `terraform init -reconfigure`).

Then:
- **DNS:** create records for the app domain → `alb_dns_name` and the CDN domain → `cdn_dns_target`.
- **Atlas:** add every `app_host_public_ips` entry as `/32` to the IP access list.
- **GitHub:** set `AWS_DEPLOY_ROLE_ARN` from `deploy_role_arn`.
- **Alarms:** confirm the alarm e-mail subscription.

### 7. App secrets

```sh
python3 - <<'PY' > app-secret.json
import json, secrets
print(json.dumps({
    "DJANGO_SECRET_KEY": secrets.token_urlsafe(50),
    "MONGO_URL": "mongodb+srv://USER:PASSWORD@CLUSTER/?retryWrites=true&w=majority",
    "CLOUDFRONT_PRIVATE_KEY": open("cf_private.pem").read(),
    # "SENTRY_DSN": "https://...",   optional
}))
PY
aws secretsmanager put-secret-value --secret-id <app_secret_arn> --secret-string file://app-secret.json
rm app-secret.json cf_private.pem
```

The database password needs no action: RDS manages it in its own secret, and deploys read it from there.

### 8. First deploy

1. Merge to `main`. CI runs; when it's green, the **Deploy** workflow builds and pushes the images and deploys
   to staging.
2. On staging, register the smoke-test account in the UI (e.g. `smoke@example.com`) and store its credentials
   as the `SMOKE_*` secrets of both environments. Create the same account in production after its first
   deploy.
3. Re-run the workflow. Staging runs the **full smoke test**: upload, encode, play through CloudFront with
   signed cookies, delete. This is the end-to-end check from checklist step 41.
4. Approve the production job.

## Everyday operations

### Deploying

Every green commit on `main` goes through these steps:
1. Images tagged with the SHA are pushed to ECR, and `deploy/` is uploaded to the releases bucket.
2. `deploy/ci-deploy.sh staging <sha>` runs on each host via SSM, **API host first**. `deploy.sh` then:
   1. renders `.env` from SSM and Secrets Manager
   2. pulls the images
   3. runs `migrate` and `ensure_infra` (topics, Mongo indexes)
   4. runs `docker compose up -d`
   5. waits for the health checks
3. The full smoke test runs on staging.
4. Production waits for approval, then gets the same deploy and a read-only smoke test.

A failing step stops the rollout, and the step's output contains the host's log.

**Migrations must be backward compatible** (expand, then contract), because the old version keeps serving
while `migrate` runs and a rollback doesn't undo migrations. To rename a column, for example:
1. Add the new column and write to both.
2. Backfill.
3. Switch reads to the new column.
4. Drop the old column in a later release.

### Rolling back

Go to **Actions → Deploy → Run workflow** and pick the environment and an earlier commit SHA. The previous SHA
is in the GitHub deployment history, or on the host:

```sh
aws ssm start-session --target <api-instance-id>
cat /opt/streaming/previous_tag
```

Images are kept for the last 100 builds, and release files for 180 days. A rollback doesn't revert database
migrations (see above).

### Logs

All containers log JSON to CloudWatch Logs group `/streaming-<env>/app`, stream `<env>/<container>`. To follow
one upload end to end, take the `X-Request-ID` from the browser's network tab, or from the nginx log line of
its `/complete` request, and run in CloudWatch Logs Insights:

```
fields @timestamp, service, level, message
| filter correlation_id = "<request id>" or request_id = "<request id>"
| sort @timestamp asc
```

### Shell access

```sh
aws ssm start-session --target <instance-id>
cd /opt/streaming
sudo docker compose -f compose.prod.yml --profile api ps   # or: logs -f django
```

### Scaling encoding

Raise `encoder_count` in the tfvars and apply, then redeploy so the new hosts get the current release. Kafka
spreads `video.uploaded` partitions across hosts, up to 6 encoders with the default topic settings.

### Alarms: what they mean and what to do first

| Alarm | Meaning | First steps |
|---|---|---|
| `lag-encoder` | Uploads are waiting for encoding | Check the encoder logs and CPU. Scale `encoder_count`. |
| `lag-<consumer>` | Status, notification, feed or analytics updates are behind | Check that consumer's logs. Usually MongoDB or Postgres reachability. |
| `dlq-growth` | An upload failed after 3 attempts | Read the DLQ message (below). Invalid files are expected; repeated FFmpeg errors are not. |
| `api-5xx` | API errors | Check Sentry and the `django` logs. Roll back if it started with a deploy. |
| `api-unhealthy` | Load balancer has no healthy API host | `docker compose ps` on the API host; `/api/health/` checks only Postgres. |
| `*-system-check` | Hardware problem | EC2 recovers the instance automatically; confirm afterwards. |

To read the dead-letter queue, on the API host (TLS to MSK):

```sh
cd /opt/streaming
sudo docker compose -f compose.prod.yml --profile api run --rm --no-deps django python - <<'PY'
from confluent_kafka import Consumer
from common.kafka import client_config
c = Consumer(client_config(**{"group.id": "dlq-reader", "auto.offset.reset": "earliest", "enable.auto.commit": False}))
c.subscribe(["video.uploaded.dlq"])
for _ in range(50):
    m = c.poll(5)
    if m is None: break
    print(m.value().decode())
c.close()
PY
```

### Restoring the database

RDS keeps 7 days of point-in-time recovery. Restore to a **new** instance (console or
`aws rds restore-db-instance-to-point-in-time`), check it, then point the platform at it:
1. Change `POSTGRES_HOST` in the SSM config parameter (or import the instance into Terraform).
2. Redeploy.

Production also takes a final snapshot if the instance is ever deleted.

### Rotating secrets

- **`DJANGO_SECRET_KEY`:** put a new value in the app secret and redeploy. Everyone has to log in again.
- **CloudFront key pair:**
  1. Generate a new pair.
  2. Add the new public key to the key group alongside the old one (Terraform).
  3. Put the new private key and its `CLOUDFRONT_KEY_PAIR_ID` in place and redeploy.
  4. Remove the old key after 12 hours, the maximum cookie lifetime.
- **Database password:** RDS rotates it in its secret. Redeploy afterwards so the containers pick it up.

## Known limitations and follow-ups

- **Presigned upload URLs are signed with the API host's temporary role credentials.** A URL stops working
  when those credentials expire. boto3 refreshes them well before expiry, so 15-minute single-upload URLs are
  fine. A multipart upload lasting close to 2 hours could see late parts fail. Fixes: presign parts in
  batches as the upload progresses, or sign with a dedicated role session.
- **One API host:** a host failure means downtime until EC2 auto-recovery (minutes). The next step is ECS
  Fargate or an Auto Scaling group behind the same load balancer (blueprint: "later").
- **No NAT gateway:** app hosts are in public subnets without inbound access. Moving them to private subnets
  needs NAT gateways (cost) or VPC endpoints.
- **MSK access** is limited by security group, with TLS but without client authentication. A later step is
  IAM (SASL/OAUTHBEARER) auth.
- **Not yet in place:** AWS WAF in front of the load balancer and CloudFront, CloudFront access logs, and
  customer-managed KMS keys. They're marked with `trivy:ignore` and a reason in the Terraform.
- **MongoDB Atlas** is set up by hand. The `mongodbatlas` Terraform provider could manage it, with VPC
  peering instead of an IP access list.
- **HSTS preload** is deliberately not enabled. Opt in once the domain is final.
