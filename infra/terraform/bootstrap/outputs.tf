output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

output "lock_table" {
  value = aws_dynamodb_table.locks.name
}

output "releases_bucket" {
  value = aws_s3_bucket.releases.bucket
}

output "ecr_registry" {
  description = "GitHub repository variable ECR_REGISTRY"
  value       = split("/", aws_ecr_repository.app["api"].repository_url)[0]
}

output "ci_build_role_arn" {
  description = "GitHub repository variable AWS_BUILD_ROLE_ARN"
  value       = aws_iam_role.ci_build.arn
}

output "github_oidc_provider_arn" {
  description = "Input for infra/terraform/app (per-environment deploy roles)"
  value       = aws_iam_openid_connect_provider.github.arn
}
