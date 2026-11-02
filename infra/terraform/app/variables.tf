variable "environment" {
  type = string
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production"
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

# ---------- Domains (app and CDN must share a parent domain for the signed cookies) ----------

variable "app_domain" {
  type        = string
  description = "e.g. app.example.com (staging: staging.example.com)"
}

variable "cdn_domain" {
  type        = string
  description = "e.g. media.example.com (staging: media-staging.example.com)"
}

variable "cookie_domain" {
  type        = string
  description = "Parent domain for CDN cookies, e.g. .example.com"
}

variable "alb_certificate_arn" {
  type        = string
  description = "ACM certificate for app_domain, in var.region"
}

variable "cdn_certificate_arn" {
  type        = string
  description = "ACM certificate for cdn_domain, in us-east-1 (CloudFront requirement)"
}

variable "cloudfront_public_key_pem" {
  type = string
}

# ---------- Sizing ----------

variable "api_instance_type" {
  type    = string
  default = "t3.medium"
}

variable "encoder_instance_type" {
  type    = string
  default = "c7i.large"
}

variable "encoder_count" {
  type    = number
  default = 1
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.small"
}

variable "db_multi_az" {
  type    = bool
  default = false
}

variable "deletion_protection" {
  type    = bool
  default = true
}

# ---------- From infra/terraform/bootstrap ----------

variable "ecr_registry" {
  type = string
}

variable "releases_bucket" {
  type = string
}

variable "github_oidc_provider_arn" {
  type = string
}

variable "github_repository" {
  type = string
}

variable "github_environment" {
  type        = string
  description = "GitHub Actions environment name (staging / production)"
}

variable "alarm_email" {
  type    = string
  default = ""
}
