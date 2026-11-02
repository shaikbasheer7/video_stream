output "alb_dns_name" {
  description = "Create DNS: app_domain -> this (alias/CNAME)"
  value       = module.platform.alb_dns_name
}

output "cdn_base_url" {
  value = module.media.cdn_base_url
}

output "cdn_dns_target" {
  description = "Create DNS: cdn_domain -> this (alias/CNAME)"
  value       = module.media.distribution_domain_name
}

output "cdn_distribution_id" {
  value = module.media.distribution_id
}

output "deploy_role_arn" {
  description = "GitHub environment variable AWS_DEPLOY_ROLE_ARN"
  value       = module.platform.deploy_role_arn
}

output "app_secret_arn" {
  value = module.platform.app_secret_arn
}

output "app_host_public_ips" {
  description = "Allow in the MongoDB Atlas IP access list"
  value       = module.platform.app_host_public_ips
}

output "log_group" {
  value = module.platform.log_group
}
