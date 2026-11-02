# Runtime configuration for the containers, merged into /opt/streaming/.env by deploy/render_env.py:
#   - non-secret settings: this SSM parameter (written by Terraform, safe in state)
#   - app secrets: the Secrets Manager secret below (values set by an operator, never in state)
#   - database credentials: the RDS-managed secret

locals {
  metrics_namespace = "Streaming/${var.environment}"
  upload_origins    = "https://${var.media_bucket_name}.s3.amazonaws.com https://${var.media_bucket_name}.s3.${var.region}.amazonaws.com"
}

resource "aws_ssm_parameter" "config" {
  name = "/${var.name_prefix}/config"
  type = "String"
  value = jsonencode({
    DJANGO_SETTINGS_MODULE      = "config.settings.prod"
    DJANGO_ALLOWED_HOSTS        = var.app_domain
    DJANGO_CSRF_TRUSTED_ORIGINS = "https://${var.app_domain}"
    POSTGRES_HOST               = aws_db_instance.main.address
    POSTGRES_PORT               = tostring(aws_db_instance.main.port)
    POSTGRES_DB                 = aws_db_instance.main.db_name
    KAFKA_BOOTSTRAP_SERVERS     = aws_msk_cluster.main.bootstrap_brokers_tls
    KAFKA_SECURITY_PROTOCOL     = "SSL"
    KAFKA_REPLICATION_FACTOR    = tostring(min(var.az_count, 3))
    KAFKA_TOPIC_PARTITIONS      = "6"
    AWS_REGION                  = var.region
    S3_BUCKET                   = var.media_bucket_name
    CDN_BASE_URL                = var.cdn_base_url
    CDN_COOKIE_DOMAIN           = var.cdn_cookie_domain
    CLOUDFRONT_KEY_PAIR_ID      = var.cloudfront_key_pair_id
    CLOUDFRONT_PRIVATE_KEY_PATH = "/run/secrets/cloudfront.pem"
    MONGO_DB                    = "streaming"
    CLOUDWATCH_NAMESPACE        = local.metrics_namespace
    SENTRY_ENVIRONMENT          = var.environment
    LOG_FORMAT                  = "json"
    # nginx (web image)
    CSP_MEDIA_ORIGINS  = var.cdn_base_url
    CSP_UPLOAD_ORIGINS = local.upload_origins
    TRUSTED_PROXY_CIDR = var.vpc_cidr
  })
}

resource "aws_secretsmanager_secret" "app" {
  name        = "${var.name_prefix}/app"
  description = "JSON: DJANGO_SECRET_KEY, MONGO_URL, CLOUDFRONT_PRIVATE_KEY (PEM), optional SENTRY_DSN. Set with the CLI (docs/runbook.md)."
}
