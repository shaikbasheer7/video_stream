variable "name_prefix" {
  type        = string
  description = "e.g. streaming-staging"
}

variable "environment" {
  type        = string
  description = "staging or production (also the instance tag the deploy pipeline targets)"
}

variable "region" {
  type = string
}

# ---------- Network ----------

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "az_count" {
  type    = number
  default = 2
  validation {
    condition     = var.az_count >= 2
    error_message = "RDS subnet groups, MSK and the load balancer need at least two availability zones."
  }
}

# ---------- Web ----------

variable "app_domain" {
  type        = string
  description = "Public hostname of the app, e.g. app.example.com (point its DNS at the load balancer)"
}

variable "alb_certificate_arn" {
  type        = string
  description = "ACM certificate for app_domain in this region"
}

# ---------- Compute ----------

variable "api_instance_type" {
  type    = string
  default = "t3.medium"
}

variable "encoder_instance_type" {
  type    = string
  default = "c7i.large" # compute-optimised: FFmpeg is CPU-bound
}

variable "encoder_count" {
  type    = number
  default = 1
}

variable "docker_compose_version" {
  type    = string
  default = "v2.30.3"
}

# ---------- Data ----------

variable "db_instance_class" {
  type    = string
  default = "db.t4g.small"
}

variable "db_allocated_storage" {
  type    = number
  default = 20
}

variable "db_multi_az" {
  type    = bool
  default = false
}

variable "deletion_protection" {
  type        = bool
  default     = true
  description = "Protects RDS (and keeps a final snapshot). Turn off only to tear down a throwaway environment."
}

variable "kafka_version" {
  type    = string
  default = "3.9.x"
}

variable "kafka_instance_type" {
  type    = string
  default = "kafka.t3.small"
}

variable "kafka_volume_size" {
  type    = number
  default = 50
}

# ---------- Media / CDN (from the media module) ----------

variable "media_bucket_name" {
  type = string
}

variable "media_bucket_arn" {
  type = string
}

variable "cdn_base_url" {
  type = string
}

variable "cdn_cookie_domain" {
  type        = string
  description = "Parent domain shared by app and CDN, e.g. .example.com"
}

variable "cloudfront_key_pair_id" {
  type = string
}

# ---------- Delivery ----------

variable "ecr_registry" {
  type        = string
  description = "<account>.dkr.ecr.<region>.amazonaws.com (bootstrap output)"
}

variable "ecr_repository_prefix" {
  type    = string
  default = "streaming"
}

variable "releases_bucket" {
  type        = string
  description = "Bucket holding compose file + deploy scripts per release (bootstrap output)"
}

variable "github_oidc_provider_arn" {
  type = string
}

variable "github_repository" {
  type        = string
  description = "owner/name"
}

variable "github_environment" {
  type        = string
  description = "GitHub Actions environment allowed to deploy here (e.g. staging, production)"
}

# ---------- Operations ----------

variable "alarm_email" {
  type        = string
  default     = ""
  description = "Receives CloudWatch alarms (confirm the subscription e-mail)"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "consumer_lag_alarm_threshold" {
  type    = number
  default = 100
}
