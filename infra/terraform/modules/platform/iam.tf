# Least privilege per host role (security checklist): the API may only touch what the API code does, the
# encoder only what the encoder does. No AWS keys anywhere: hosts use instance profiles, CI uses OIDC.

data "aws_iam_policy_document" "ec2_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "host" {
  for_each           = toset(["api", "encoder"])
  name               = "${var.name_prefix}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.ec2_trust.json
}

resource "aws_iam_instance_profile" "host" {
  for_each = aws_iam_role.host
  name     = each.value.name
  role     = each.value.name
}

resource "aws_iam_role_policy_attachment" "ssm" {
  for_each   = aws_iam_role.host
  role       = each.value.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore" # Session Manager + Run Command
}

# Shared by both hosts: pull images, fetch the release, read config and secrets, write logs.
data "aws_iam_policy_document" "host_common" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid       = "EcrPull"
    actions   = ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = ["arn:aws:ecr:${var.region}:*:repository/${var.ecr_repository_prefix}/*"]
  }
  statement {
    sid       = "FetchRelease"
    actions   = ["s3:GetObject"]
    resources = ["arn:aws:s3:::${var.releases_bucket}/releases/*"]
  }
  statement {
    sid       = "ListRelease"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.releases_bucket}"]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["releases/*"]
    }
  }
  statement {
    sid       = "ReadConfig"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.config.arn]
  }
  statement {
    sid       = "ReadSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn, aws_db_instance.main.master_user_secret[0].secret_arn]
  }
  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["${aws_cloudwatch_log_group.app.arn}:*"]
  }
}

resource "aws_iam_role_policy" "host_common" {
  for_each = aws_iam_role.host
  name     = "common"
  role     = each.value.id
  policy   = data.aws_iam_policy_document.host_common.json
}

# API: presign uploads to raw/ (incl. multipart), verify them, delete a video's files, push monitor metrics.
data "aws_iam_policy_document" "api" {
  statement {
    sid = "Uploads"
    actions = [
      "s3:PutObject", "s3:GetObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts",
    ]
    resources = ["${var.media_bucket_arn}/raw/*"]
  }
  statement {
    sid       = "DeleteVideoFiles"
    actions   = ["s3:DeleteObject"]
    resources = ["${var.media_bucket_arn}/raw/*", "${var.media_bucket_arn}/hls/*", "${var.media_bucket_arn}/thumbnails/*"]
  }
  statement {
    sid       = "ListForDeleteAndHealth"
    actions   = ["s3:ListBucket"]
    resources = [var.media_bucket_arn]
  }
  statement {
    sid       = "Metrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = [local.metrics_namespace]
    }
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "app"
  role   = aws_iam_role.host["api"].id
  policy = data.aws_iam_policy_document.api.json
}

# Encoder: read the upload, write HLS + thumbnail, and clean up if the video was deleted mid-encode.
data "aws_iam_policy_document" "encoder" {
  statement {
    sid       = "ReadSource"
    actions   = ["s3:GetObject"]
    resources = ["${var.media_bucket_arn}/raw/*"]
  }
  statement {
    sid       = "WriteOutputs"
    actions   = ["s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = ["${var.media_bucket_arn}/hls/*", "${var.media_bucket_arn}/thumbnails/*"]
  }
  statement {
    sid       = "ListOutputs"
    actions   = ["s3:ListBucket"]
    resources = [var.media_bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["hls/*", "thumbnails/*"]
    }
  }
}

resource "aws_iam_role_policy" "encoder" {
  name   = "app"
  role   = aws_iam_role.host["encoder"].id
  policy = data.aws_iam_policy_document.encoder.json
}

# ---------- Deploy role for GitHub Actions (this environment only) ----------

data "aws_iam_policy_document" "deploy_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.github_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only jobs running in this GitHub environment (which can require manual approval) can deploy here.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:environment:${var.github_environment}"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "${var.name_prefix}-deploy"
  assume_role_policy = data.aws_iam_policy_document.deploy_trust.json
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "FindHosts"
    actions   = ["ec2:DescribeInstances"]
    resources = ["*"]
  }
  statement {
    sid       = "RunDeployOnThisEnvironmentOnly"
    actions   = ["ssm:SendCommand"]
    resources = ["arn:aws:ec2:${var.region}:*:instance/*"]
    condition {
      test     = "StringEquals"
      variable = "ssm:resourceTag/Environment"
      values   = [var.environment]
    }
  }
  statement {
    sid       = "RunShellScriptDocument"
    actions   = ["ssm:SendCommand"]
    resources = ["arn:aws:ssm:${var.region}::document/AWS-RunShellScript"]
  }
  statement {
    sid       = "FollowCommand"
    actions   = ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "deploy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}
