# ---------- PostgreSQL (RDS) ----------
# The master password is generated and rotated by RDS in Secrets Manager; it never enters Terraform state.

resource "aws_db_subnet_group" "main" {
  name       = var.name_prefix
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "main" {
  identifier                      = var.name_prefix
  engine                          = "postgres"
  engine_version                  = "16"
  instance_class                  = var.db_instance_class
  allocated_storage               = var.db_allocated_storage
  max_allocated_storage           = var.db_allocated_storage * 5
  storage_type                    = "gp3"
  storage_encrypted               = true
  db_name                         = "streaming"
  username                        = "streaming"
  manage_master_user_password     = true
  db_subnet_group_name            = aws_db_subnet_group.main.name
  vpc_security_group_ids          = [aws_security_group.db.id]
  publicly_accessible             = false
  multi_az                        = var.db_multi_az
  backup_retention_period         = 7 # point-in-time restore window (runbook: "Restore the database")
  copy_tags_to_snapshot           = true
  auto_minor_version_upgrade      = true
  deletion_protection             = var.deletion_protection
  skip_final_snapshot             = !var.deletion_protection
  final_snapshot_identifier       = var.deletion_protection ? "${var.name_prefix}-final" : null
  performance_insights_enabled    = true
  enabled_cloudwatch_logs_exports = ["postgresql"]
  # Allows IAM-token logins for operators; the app still uses the managed password.
  iam_database_authentication_enabled = true
}

# ---------- Kafka (MSK) ----------
# Two brokers across two AZs, TLS between clients and brokers. Access is limited by security group to the app
# hosts; switching to IAM/SASL client authentication is a later hardening step (runbook).

resource "aws_msk_configuration" "main" {
  name              = var.name_prefix
  kafka_versions    = [var.kafka_version]
  server_properties = <<-PROPERTIES
    auto.create.topics.enable=false
    default.replication.factor=2
    min.insync.replicas=1
    num.partitions=6
  PROPERTIES
}

resource "aws_cloudwatch_log_group" "kafka" {
  name              = "/${var.name_prefix}/msk"
  retention_in_days = var.log_retention_days
}

# MSK always encrypts data at rest (AWS-owned key); the rule only asks for a customer-managed key.
#trivy:ignore:AVD-AWS-0179
resource "aws_msk_cluster" "main" {
  cluster_name           = var.name_prefix
  kafka_version          = var.kafka_version
  number_of_broker_nodes = var.az_count

  broker_node_group_info {
    instance_type   = var.kafka_instance_type
    client_subnets  = aws_subnet.private[*].id
    security_groups = [aws_security_group.kafka.id]
    storage_info {
      ebs_storage_info {
        volume_size = var.kafka_volume_size
      }
    }
  }

  configuration_info {
    arn      = aws_msk_configuration.main.arn
    revision = aws_msk_configuration.main.latest_revision
  }

  encryption_info {
    encryption_in_transit {
      client_broker = "TLS"
      in_cluster    = true
    }
  }

  client_authentication {
    unauthenticated = true
  }

  logging_info {
    broker_logs {
      cloudwatch_logs {
        enabled   = true
        log_group = aws_cloudwatch_log_group.kafka.name
      }
    }
  }
}
