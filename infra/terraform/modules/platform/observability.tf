# Container logs (Docker awslogs driver), alarms on the blueprint's key metrics, and e-mail notifications.

resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.name_prefix}/app"
  retention_in_days = var.log_retention_days
}

# Unencrypted on purpose: CloudWatch alarms cannot publish to a topic encrypted with the AWS-managed SNS key,
# and alarm texts contain no sensitive data.
#trivy:ignore:AVD-AWS-0095
resource "aws_sns_topic" "alarms" {
  name = "${var.name_prefix}-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

locals {
  alarm_actions = [aws_sns_topic.alarms.arn]
  # Consumer groups published by `manage.py monitor` (backend/common/lag.py).
  consumer_groups = ["encoder", "api-status", "analytics", "notify", "feed"]
}

resource "aws_cloudwatch_metric_alarm" "consumer_lag" {
  for_each            = toset(local.consumer_groups)
  alarm_name          = "${var.name_prefix}-lag-${each.key}"
  alarm_description   = "Kafka consumer group ${each.key} is falling behind"
  namespace           = local.metrics_namespace
  metric_name         = "ConsumerLag"
  dimensions          = { ConsumerGroup = each.key }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 5 # sustained, not a burst of uploads
  threshold           = var.consumer_lag_alarm_threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "breaching" # no data = the monitor itself is down
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "dlq_growth" {
  alarm_name          = "${var.name_prefix}-dlq-growth"
  alarm_description   = "New messages in video.uploaded.dlq: an upload failed encoding after all retries"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions

  metric_query {
    id          = "growth"
    expression  = "DIFF(dlq)"
    label       = "New DLQ messages"
    return_data = true
  }
  metric_query {
    id = "dlq"
    metric {
      namespace   = local.metrics_namespace
      metric_name = "DeadLetterMessages"
      period      = 300
      stat        = "Maximum"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${var.name_prefix}-api-5xx"
  alarm_description   = "API returning server errors"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { LoadBalancer = aws_lb.main.arn_suffix }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 10
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "api_unhealthy" {
  alarm_name          = "${var.name_prefix}-api-unhealthy"
  alarm_description   = "The load balancer sees no healthy API host"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HealthyHostCount"
  dimensions          = { LoadBalancer = aws_lb.main.arn_suffix, TargetGroup = aws_lb_target_group.api.arn_suffix }
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# EC2 auto-recovery: move the instance to healthy hardware if the underlying host fails.
resource "aws_cloudwatch_metric_alarm" "instance_recover" {
  for_each            = merge({ api = aws_instance.api.id }, { for i, inst in aws_instance.encoder : "encoder-${i}" => inst.id })
  alarm_name          = "${var.name_prefix}-${each.key}-system-check"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_System"
  dimensions          = { InstanceId = each.value }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = concat(local.alarm_actions, ["arn:aws:automate:${var.region}:ec2:recover"])
}

resource "aws_cloudwatch_metric_alarm" "db_storage" {
  alarm_name          = "${var.name_prefix}-db-storage-low"
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 2 * 1024 * 1024 * 1024
  comparison_operator = "LessThanThreshold"
  alarm_actions       = local.alarm_actions
}
