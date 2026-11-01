# Media storage and delivery: private S3 bucket + CloudFront with Origin Access Control and signed cookies.
# Mirrors the local stack (SeaweedFS + infra/local-cdn). Validate with `terraform validate`; apply in Phase 6.
#
# Before applying:
#   openssl genrsa -out cf_private.pem 2048
#   openssl rsa -pubout -in cf_private.pem -out cf_public.pem
#   Store cf_private.pem in Secrets Manager (it never goes through Terraform state); pass cf_public.pem below.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }
}

provider "aws" {
  region = var.region
}

locals {
  bucket_name = "${var.name_prefix}-media"
}

# ---------- S3 (private) ----------

resource "aws_s3_bucket" "media" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_public_access_block" "media" {
  bucket                  = aws_s3_bucket.media.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "media" {
  bucket = aws_s3_bucket.media.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Browsers upload straight to S3 with presigned URLs; multipart needs the ETag header exposed.
resource "aws_s3_bucket_cors_configuration" "media" {
  bucket = aws_s3_bucket.media.id
  cors_rule {
    allowed_origins = var.app_origins
    allowed_methods = ["PUT", "GET", "HEAD"]
    allowed_headers = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "media" {
  bucket = aws_s3_bucket.media.id
  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
  rule {
    id     = "raw-to-glacier"
    status = "Enabled"
    filter {
      prefix = "raw/"
    }
    transition {
      days          = 30
      storage_class = "GLACIER_IR"
    }
  }
}

# CloudFront may read only the HLS output and thumbnails, never raw uploads.
data "aws_iam_policy_document" "media" {
  statement {
    sid       = "CloudFrontReadsPlayableMedia"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.media.arn}/hls/*", "${aws_s3_bucket.media.arn}/thumbnails/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.media.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "media" {
  bucket     = aws_s3_bucket.media.id
  policy     = data.aws_iam_policy_document.media.json
  depends_on = [aws_s3_bucket_public_access_block.media]
}

# ---------- CloudFront ----------

resource "aws_cloudfront_origin_access_control" "media" {
  name                              = "${var.name_prefix}-media-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_public_key" "playback" {
  name        = "${var.name_prefix}-playback"
  encoded_key = var.cloudfront_public_key_pem
}

resource "aws_cloudfront_key_group" "playback" {
  name  = "${var.name_prefix}-playback"
  items = [aws_cloudfront_public_key.playback.id]
}

# Segments never change: cache for a year. Cookies/query strings stay out of the cache key, so one
# cached copy serves every viewer (signature checks happen before the cache).
resource "aws_cloudfront_cache_policy" "segments" {
  name        = "${var.name_prefix}-hls-segments"
  min_ttl     = 86400
  default_ttl = 31536000
  max_ttl     = 31536000
  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = false
    enable_accept_encoding_brotli = false
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

# Playlists: short TTL so a re-encode is picked up quickly.
resource "aws_cloudfront_cache_policy" "playlists" {
  name        = "${var.name_prefix}-hls-playlists"
  min_ttl     = 0
  default_ttl = 60
  max_ttl     = 300
  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

# hls.js fetches with credentials (the signed cookies) from the app's origin.
resource "aws_cloudfront_response_headers_policy" "cors" {
  name = "${var.name_prefix}-media-cors"
  cors_config {
    access_control_allow_credentials = true
    access_control_allow_headers {
      items = ["*"]
    }
    access_control_allow_methods {
      items = ["GET", "HEAD"]
    }
    access_control_allow_origins {
      items = var.app_origins
    }
    access_control_max_age_sec = 3000
    origin_override            = true
  }
}

data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

resource "aws_cloudfront_distribution" "media" {
  enabled     = true
  comment     = "${var.name_prefix} media (HLS + thumbnails)"
  price_class = var.price_class
  aliases     = var.cdn_domain_name == "" ? [] : [var.cdn_domain_name]

  origin {
    origin_id                = "media-s3"
    domain_name              = aws_s3_bucket.media.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.media.id
  }

  # Anything not matched below also requires a signature (and the bucket policy denies it anyway).
  default_cache_behavior {
    target_origin_id           = "media-s3"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = aws_cloudfront_cache_policy.playlists.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.cors.id
    trusted_key_groups         = [aws_cloudfront_key_group.playback.id]
  }

  ordered_cache_behavior {
    path_pattern               = "/hls/*.ts"
    target_origin_id           = "media-s3"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = aws_cloudfront_cache_policy.segments.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.cors.id
    trusted_key_groups         = [aws_cloudfront_key_group.playback.id]
  }

  ordered_cache_behavior {
    path_pattern               = "/hls/*"
    target_origin_id           = "media-s3"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = aws_cloudfront_cache_policy.playlists.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.cors.id
    trusted_key_groups         = [aws_cloudfront_key_group.playback.id]
  }

  ordered_cache_behavior {
    path_pattern           = "/thumbnails/*"
    target_origin_id       = "media-s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.caching_optimized.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # Signed cookies set by the API only reach the CDN if both share a parent domain
  # (api: example.com, cdn: media.example.com, CDN_COOKIE_DOMAIN=.example.com), so production needs
  # the custom domain and its ACM certificate (us-east-1).
  dynamic "viewer_certificate" {
    for_each = var.acm_certificate_arn == "" ? [1] : []
    content {
      cloudfront_default_certificate = true
    }
  }
  dynamic "viewer_certificate" {
    for_each = var.acm_certificate_arn == "" ? [] : [1]
    content {
      acm_certificate_arn      = var.acm_certificate_arn
      ssl_support_method       = "sni-only"
      minimum_protocol_version = "TLSv1.2_2021"
    }
  }
}
