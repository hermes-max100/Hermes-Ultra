variable "project_id" {
  description = "Google Cloud project used for Hermes Max support workloads."
  type        = string
}

variable "billing_account" {
  description = "Google Cloud billing account id for budget creation."
  type        = string
}

variable "region" {
  description = "Google Cloud region for support workloads."
  type        = string
  default     = "us-central1"
}

variable "name_prefix" {
  description = "Prefix used for Google Cloud support resources."
  type        = string
  default     = "hermes-max-support"
}

variable "budget_alert_emails" {
  description = "Email recipients documented for Google Cloud budget alerts."
  type        = list(string)
  default     = []
}

variable "monthly_budget_limit_usd" {
  description = "Initial monthly Google Cloud support budget cap."
  type        = number
  default     = 15
}

variable "enable_support_storage" {
  description = "Create a private encrypted Google Cloud Storage bucket for support backups/artifacts."
  type        = bool
  default     = false
}

variable "enable_cloud_run_probe" {
  description = "Create a bounded Cloud Run support probe. Do not enable until console pricing/API impact is approved."
  type        = bool
  default     = false
}

variable "labels" {
  description = "Labels applied to supported Google Cloud resources."
  type        = map(string)
  default = {
    project     = "hermes-max"
    managed-by  = "terraform"
    environment = "foundation"
  }
}
