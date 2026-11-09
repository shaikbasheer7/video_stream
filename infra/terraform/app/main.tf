# One environment (staging or production). Same code for both; the differences live in <env>.tfvars and
# <env>.backend.hcl, so staging really is a rehearsal of production.
#
#   terraform init -backend-config=staging.backend.hcl
#   terraform plan -var-file=staging.tfvars
#
# Prerequisite: infra/terraform/bootstrap applied once per account (see docs/runbook.md).

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.72"
    }
  }
  backend "s3" {} # bucket/key/table come from <env>.backend.hcl
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "streaming", Environment = var.environment, ManagedBy = "terraform" }
  }
}

locals {
  name_prefix = "streaming-${var.environment}"
}

module "media" {
  source                    = "../modules/media"
  name_prefix               = local.name_prefix
  app_origins               = ["https://${var.app_domain}"]
  cloudfront_public_key_pem = var.cloudfront_public_key_pem
  cdn_domain_name           = var.cdn_domain
  acm_certificate_arn       = var.cdn_certificate_arn
}

module "platform" {
  source      = "../modules/platform"
  name_prefix = local.name_prefix
  environment = var.environment
  region      = var.region

  app_domain          = var.app_domain
  alb_certificate_arn = var.alb_certificate_arn

  api_instance_type     = var.api_instance_type
  encoder_instance_type = var.encoder_instance_type
  encoder_count         = var.encoder_count
  db_instance_class     = var.db_instance_class
  db_multi_az           = var.db_multi_az
  deletion_protection   = var.deletion_protection

  media_bucket_name      = module.media.bucket_name
  media_bucket_arn       = module.media.bucket_arn
  cdn_base_url           = module.media.cdn_base_url
  cdn_cookie_domain      = var.cookie_domain
  cloudfront_key_pair_id = module.media.cloudfront_key_pair_id

  ecr_registry             = var.ecr_registry
  releases_bucket          = var.releases_bucket
  github_oidc_provider_arn = var.github_oidc_provider_arn
  github_repository        = var.github_repository
  github_environment       = var.github_environment

  alarm_email = var.alarm_email
}
