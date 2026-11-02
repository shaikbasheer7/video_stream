output "alb_dns_name" {
  description = "Point app_domain (CNAME/alias) here"
  value       = aws_lb.main.dns_name
}

output "deploy_role_arn" {
  description = "GitHub environment variable AWS_DEPLOY_ROLE_ARN"
  value       = aws_iam_role.deploy.arn
}

output "app_secret_arn" {
  description = "Fill with: aws secretsmanager put-secret-value (docs/runbook.md)"
  value       = aws_secretsmanager_secret.app.arn
}

output "config_parameter" {
  value = aws_ssm_parameter.config.name
}

output "api_instance_id" {
  value = aws_instance.api.id
}

output "encoder_instance_ids" {
  value = aws_instance.encoder[*].id
}

output "db_endpoint" {
  value = aws_db_instance.main.address
}

output "kafka_bootstrap_brokers_tls" {
  value = aws_msk_cluster.main.bootstrap_brokers_tls
}

output "app_host_public_ips" {
  description = "Public IPs of the app hosts: allow these (/32) in the MongoDB Atlas IP access list"
  value       = concat([aws_instance.api.public_ip], aws_instance.encoder[*].public_ip)
}

output "log_group" {
  value = aws_cloudwatch_log_group.app.name
}

output "alarm_topic_arn" {
  value = aws_sns_topic.alarms.arn
}
