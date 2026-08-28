data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  count   = var.vpc_id == "" ? 1 : 0
  default = true
}

locals {
  selected_vpc_id = var.vpc_id != "" ? var.vpc_id : data.aws_vpc.default[0].id
  account_suffix  = data.aws_caller_identity.current.account_id
  storage_bucket_names = {
    evidence  = "${var.name_prefix}-${local.account_suffix}-evidence"
    artifacts = "${var.name_prefix}-${local.account_suffix}-artifacts"
    backups   = "${var.name_prefix}-${local.account_suffix}-backups"
  }
}

data "aws_subnets" "selected" {
  count = var.subnet_id == "" ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [local.selected_vpc_id]
  }
}

data "aws_ami" "ubuntu_2404" {
  count       = var.enable_ec2_compute ? 1 : 0
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd*/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_budgets_budget" "monthly_actual_and_forecast" {
  name         = "${var.name_prefix}-monthly-cost-guard"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = length(var.budget_alert_emails) == 0 ? [] : [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = var.budget_alert_emails
    }
  }

  dynamic "notification" {
    for_each = length(var.budget_alert_emails) == 0 ? [] : [80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "FORECASTED"
      subscriber_email_addresses = var.budget_alert_emails
    }
  }
}

resource "aws_s3_bucket" "private_storage" {
  for_each = var.enable_storage ? local.storage_bucket_names : {}

  bucket = each.value
  tags   = var.common_tags
}

resource "aws_s3_bucket_public_access_block" "private_storage" {
  for_each = aws_s3_bucket.private_storage

  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "private_storage" {
  for_each = aws_s3_bucket.private_storage

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "private_storage" {
  for_each = aws_s3_bucket.private_storage

  bucket = each.value.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "private_storage" {
  for_each = aws_s3_bucket.private_storage

  bucket = each.value.id

  rule {
    id     = "bounded-noncurrent-retention"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "expire-transient-logs"
    status = "Enabled"

    filter {
      prefix = "logs/"
    }

    expiration {
      days = 30
    }
  }
}

resource "aws_iam_role" "hermes_host" {
  count = var.enable_ec2_compute ? 1 : 0
  name  = "${var.name_prefix}-host-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = var.common_tags
}

resource "aws_iam_role_policy_attachment" "ssm" {
  count      = var.enable_ec2_compute ? 1 : 0
  role       = aws_iam_role.hermes_host[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "hermes_storage" {
  count = var.enable_ec2_compute ? 1 : 0
  name  = "${var.name_prefix}-bounded-storage"
  role  = aws_iam_role.hermes_host[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ListHermesBuckets"
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = [
          aws_s3_bucket.private_storage["artifacts"].arn,
          aws_s3_bucket.private_storage["evidence"].arn,
          aws_s3_bucket.private_storage["backups"].arn
        ]
      },
      {
        Sid      = "ReadArtifacts"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${aws_s3_bucket.private_storage["artifacts"].arn}/*"]
      },
      {
        Sid    = "WriteEvidenceBackups"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"]
        Resource = [
          "${aws_s3_bucket.private_storage["evidence"].arn}/*",
          "${aws_s3_bucket.private_storage["backups"].arn}/*"
        ]
      }
    ]
  })
}


resource "aws_iam_role_policy" "hermes_runtime_secrets" {
  count = var.enable_ec2_compute ? 1 : 0
  name  = "${var.name_prefix}-runtime-secrets"
  role  = aws_iam_role.hermes_host[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "ReadHermesRuntimeSecrets"
      Effect = "Allow"
      Action = [
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath"
      ]
      Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.runtime_ssm_parameter_prefix}*"
    }]
  })
}

resource "aws_iam_instance_profile" "hermes_host" {
  count = var.enable_ec2_compute ? 1 : 0
  name  = "${var.name_prefix}-host-profile"
  role  = aws_iam_role.hermes_host[0].name
}

resource "aws_security_group" "hermes_gateway" {
  count       = var.enable_ec2_compute ? 1 : 0
  name        = "${var.name_prefix}-gateway"
  description = "Hermes gateway ingress; SSH intentionally absent"
  vpc_id      = local.selected_vpc_id
  tags        = var.common_tags

  dynamic "ingress" {
    for_each = var.https_ingress_cidrs
    content {
      description = "HTTPS"
      protocol    = "tcp"
      from_port   = 443
      to_port     = 443
      cidr_blocks = [ingress.value]
    }
  }

  dynamic "ingress" {
    for_each = var.enable_http_redirect ? var.https_ingress_cidrs : []
    content {
      description = "HTTP redirect only"
      protocol    = "tcp"
      from_port   = 80
      to_port     = 80
      cidr_blocks = [ingress.value]
    }
  }

  egress {
    description = "Outbound package/provider access"
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "hermes_gateway" {
  count                       = var.enable_ec2_compute ? 1 : 0
  ami                         = data.aws_ami.ubuntu_2404[0].id
  instance_type               = var.ec2_instance_type
  subnet_id                   = var.subnet_id != "" ? var.subnet_id : sort(data.aws_subnets.selected[0].ids)[0]
  vpc_security_group_ids      = [aws_security_group.hermes_gateway[0].id]
  iam_instance_profile        = aws_iam_instance_profile.hermes_host[0].name
  associate_public_ip_address = true
  user_data_replace_on_change = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = var.ec2_root_volume_gib
    iops        = 3000
    throughput  = 125
  }

  user_data = templatefile("${path.module}/templates/bootstrap-hermes.sh.tftpl", {
    aws_region                   = var.aws_region
    artifact_bucket              = aws_s3_bucket.private_storage["artifacts"].bucket
    release_object_key           = var.release_object_key
    release_sha256               = lower(var.release_sha256)
    runtime_ssm_parameter_prefix = var.runtime_ssm_parameter_prefix
  })

  lifecycle {
    precondition {
      condition     = var.enable_storage
      error_message = "enable_storage must be true before enable_ec2_compute can be true."
    }
    precondition {
      condition     = var.release_object_key != "" && can(regex("^[0-9a-fA-F]{64}$", var.release_sha256))
      error_message = "EC2 compute requires release_object_key and a valid release_sha256."
    }
    precondition {
      condition     = var.vpc_id == "" || var.subnet_id != ""
      error_message = "subnet_id is required when vpc_id is set so Hermes does not guess a private/unroutable subnet."
    }
  }

  tags = merge(var.common_tags, { Name = "${var.name_prefix}-gateway" })
}
