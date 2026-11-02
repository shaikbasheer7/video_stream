resource "aws_security_group" "alb" {
  name        = "${var.name_prefix}-alb"
  description = "Public HTTPS (HTTP only redirects)"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTPS from anywhere"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP, redirected to HTTPS"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_egress_rule" "alb_to_api" {
  security_group_id            = aws_security_group.alb.id
  description                  = "To nginx on the API host"
  referenced_security_group_id = aws_security_group.api.id
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
}

# API host: nginx + Django + consumers. Only the load balancer may connect.
resource "aws_security_group" "api" {
  name        = "${var.name_prefix}-api"
  description = "API host: inbound only from the load balancer"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "api_from_alb" {
  security_group_id            = aws_security_group.api.id
  description                  = "nginx from the load balancer"
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
}

# Encoder hosts: no inbound at all (they pull work from Kafka; shell access is via SSM).
resource "aws_security_group" "encoder" {
  name        = "${var.name_prefix}-encoder"
  description = "Encoder hosts: no inbound"
  vpc_id      = aws_vpc.main.id
}

# Outbound for app hosts: ECR, S3, Secrets Manager, CloudWatch, SSM, MongoDB Atlas, RDS, MSK.
#trivy:ignore:AVD-AWS-0104 AWS API addresses change, and there are no VPC endpoints to reach them privately
resource "aws_vpc_security_group_egress_rule" "app_https" {
  for_each          = { api = aws_security_group.api.id, encoder = aws_security_group.encoder.id }
  security_group_id = each.value
  description       = "HTTPS to AWS APIs and MongoDB Atlas"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

#trivy:ignore:AVD-AWS-0104 the Atlas cluster doesn't exist yet: narrow this to its addresses once it does
resource "aws_vpc_security_group_egress_rule" "app_mongo" {
  for_each          = { api = aws_security_group.api.id, encoder = aws_security_group.encoder.id }
  security_group_id = each.value
  description       = "MongoDB Atlas"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 27015
  to_port           = 27017
}

resource "aws_vpc_security_group_egress_rule" "app_to_db" {
  for_each                     = { api = aws_security_group.api.id, encoder = aws_security_group.encoder.id }
  security_group_id            = each.value
  description                  = "PostgreSQL"
  referenced_security_group_id = aws_security_group.db.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_egress_rule" "app_to_kafka" {
  for_each                     = { api = aws_security_group.api.id, encoder = aws_security_group.encoder.id }
  security_group_id            = each.value
  description                  = "Kafka over TLS"
  referenced_security_group_id = aws_security_group.kafka.id
  ip_protocol                  = "tcp"
  from_port                    = 9094
  to_port                      = 9094
}

resource "aws_security_group" "db" {
  name        = "${var.name_prefix}-db"
  description = "PostgreSQL: app hosts only"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "db_from_app" {
  for_each                     = { api = aws_security_group.api.id, encoder = aws_security_group.encoder.id }
  security_group_id            = aws_security_group.db.id
  description                  = "PostgreSQL from ${each.key}"
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_security_group" "kafka" {
  name        = "${var.name_prefix}-kafka"
  description = "MSK brokers: app hosts only, TLS"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "kafka_from_app" {
  for_each                     = { api = aws_security_group.api.id, encoder = aws_security_group.encoder.id }
  security_group_id            = aws_security_group.kafka.id
  description                  = "Kafka TLS from ${each.key}"
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 9094
  to_port                      = 9094
}
