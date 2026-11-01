variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name_prefix" {
  type        = string
  description = "Prefix for resource names, e.g. streaming-prod"
}

variable "app_origins" {
  type        = list(string)
  description = "Origins of the web app (S3 upload CORS and CDN CORS), e.g. [\"https://example.com\"]"
}

variable "cloudfront_public_key_pem" {
  type        = string
  description = "Public half of the playback signing key (PEM). The private half goes to Secrets Manager."
}

variable "cdn_domain_name" {
  type        = string
  default     = ""
  description = "Custom CDN domain under the app's domain, e.g. media.example.com"
}

variable "acm_certificate_arn" {
  type        = string
  default     = ""
  description = "ACM certificate (us-east-1) for cdn_domain_name"
}

variable "price_class" {
  type    = string
  default = "PriceClass_100"
}
