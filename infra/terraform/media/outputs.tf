output "bucket_name" {
  value = aws_s3_bucket.media.bucket
}

output "cloudfront_key_pair_id" {
  description = "CLOUDFRONT_KEY_PAIR_ID for Django"
  value       = aws_cloudfront_public_key.playback.id
}

output "cdn_base_url" {
  description = "CDN_BASE_URL for Django"
  value       = "https://${var.cdn_domain_name != "" ? var.cdn_domain_name : aws_cloudfront_distribution.media.domain_name}"
}

output "distribution_id" {
  value = aws_cloudfront_distribution.media.id
}
