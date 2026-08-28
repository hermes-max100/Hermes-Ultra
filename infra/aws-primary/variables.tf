variable "aws_region" {
  description = "AWS region for the primary Hermes Max deployment."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix used for AWS resource names."
  type        = string
  default     = "hermes-max"
}

variable "budget_alert_emails" {
  description = "Email recipients for AWS Budget actual and forecast alerts."
  type        = list(string)
  default     = []
}

variable "monthly_budget_limit_usd" {
  description = "Initial monthly AWS budget cap before model/API inference."
  type        = number
  default     = 75
}

variable "enable_storage" {
  description = "Create private encrypted S3 buckets for evidence, artifacts, and backups."
  type        = bool
  default     = false
}

variable "enable_ec2_compute" {
  description = "Create the primary Hermes EC2 host. Requires storage plus a release object key and SHA256."
  type        = bool
  default     = false
}

variable "ec2_instance_type" {
  description = "Initial Hermes EC2 size. Verify current pricing before enabling."
  type        = string
  default     = "m7i-flex.large"
}

variable "ec2_root_volume_gib" {
  description = "Encrypted gp3 root volume size."
  type        = number
  default     = 30

  validation {
    condition     = var.ec2_root_volume_gib >= 20 && var.ec2_root_volume_gib <= 100
    error_message = "ec2_root_volume_gib must be between 20 and 100 GiB for the initial bounded deployment."
  }
}

variable "vpc_id" {
  description = "Optional VPC id. Empty uses the account default VPC."
  type        = string
  default     = ""
}

variable "subnet_id" {
  description = "Optional public subnet id. Empty chooses one subnet from the selected/default VPC."
  type        = string
  default     = ""
}

variable "https_ingress_cidrs" {
  description = "CIDRs allowed to reach HTTPS. Empty by default; open only when an authenticated gateway is actually deployed."
  type        = list(string)
  default     = []
}

variable "enable_http_redirect" {
  description = "Allow TCP/80 only for an HTTP-to-HTTPS redirect layer."
  type        = bool
  default     = false
}

variable "release_object_key" {
  description = "Object key in the private artifacts bucket for the checksummed Hermes cloud release tarball."
  type        = string
  default     = ""
}

variable "release_sha256" {
  description = "Expected SHA256 of release_object_key. Required when compute is enabled."
  type        = string
  default     = ""

  validation {
    condition     = var.release_sha256 == "" || can(regex("^[0-9a-fA-F]{64}$", var.release_sha256))
    error_message = "release_sha256 must be empty or a 64-character hexadecimal SHA256 digest."
  }
}


variable "runtime_ssm_parameter_prefix" {
  description = "SSM Parameter Store prefix for Hermes runtime SecureString values."
  type        = string
  default     = "/hermes-max/runtime/"

  validation {
    condition     = startswith(var.runtime_ssm_parameter_prefix, "/hermes-max/runtime/") && endswith(var.runtime_ssm_parameter_prefix, "/")
    error_message = "runtime_ssm_parameter_prefix must stay under /hermes-max/runtime/ and end with /."
  }
}

variable "common_tags" {
  description = "Tags applied to supported resources."
  type        = map(string)
  default = {
    Project     = "Hermes Max"
    ManagedBy   = "Terraform"
    Environment = "foundation"
  }
}
