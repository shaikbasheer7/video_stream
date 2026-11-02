# One API host (nginx + Django + Kafka consumers + monitor) and N encoder hosts, all running Docker Compose
# (blueprint section 10, "MVP deployment on AWS"). No SSH: shell access and deploys go through SSM.

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

locals {
  host_settings = {
    environment            = var.environment
    region                 = var.region
    ecr_registry           = var.ecr_registry
    ecr_repository_prefix  = var.ecr_repository_prefix
    releases_bucket        = var.releases_bucket
    config_parameter       = aws_ssm_parameter.config.name
    app_secret_id          = aws_secretsmanager_secret.app.arn
    db_secret_id           = aws_db_instance.main.master_user_secret[0].secret_arn
    log_group              = aws_cloudwatch_log_group.app.name
    docker_compose_version = var.docker_compose_version
  }
}

resource "aws_instance" "api" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.api_instance_type
  subnet_id              = aws_subnet.public[0].id
  vpc_security_group_ids = [aws_security_group.api.id]
  iam_instance_profile   = aws_iam_instance_profile.host["api"].name
  user_data              = templatefile("${path.module}/templates/user_data.sh.tftpl", merge(local.host_settings, { role = "api" }))
  monitoring             = true

  metadata_options {
    http_tokens = "required" # IMDSv2 only
    # Containers sit one network hop behind the host; they need hop limit 2 to reach their AWS credentials.
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 40
    encrypted   = true
  }

  lifecycle {
    ignore_changes = [ami] # new AMIs roll out by replacing hosts deliberately, not on every plan
  }

  tags = { Name = "${var.name_prefix}-api", Role = "api", Environment = var.environment }
}

resource "aws_instance" "encoder" {
  count                  = var.encoder_count
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.encoder_instance_type
  subnet_id              = aws_subnet.public[count.index % var.az_count].id
  vpc_security_group_ids = [aws_security_group.encoder.id]
  iam_instance_profile   = aws_iam_instance_profile.host["encoder"].name
  user_data              = templatefile("${path.module}/templates/user_data.sh.tftpl", merge(local.host_settings, { role = "encoder" }))
  monitoring             = true

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 100 # source download + three renditions of a long video in flight
    encrypted   = true
  }

  lifecycle {
    ignore_changes = [ami]
  }

  tags = { Name = "${var.name_prefix}-encoder-${count.index}", Role = "encoder", Environment = var.environment }
}
