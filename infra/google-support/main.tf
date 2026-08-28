resource "google_monitoring_notification_channel" "budget_email" {
  for_each = toset(var.budget_alert_emails)

  display_name = "Hermes Max budget alert ${each.value}"
  type         = "email"
  labels = {
    email_address = each.value
  }
}

resource "google_billing_budget" "monthly_support_guard" {
  billing_account = var.billing_account
  display_name    = "${var.name_prefix}-monthly-cost-guard"

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_limit_usd)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
    spend_basis       = "CURRENT_SPEND"
  }

  threshold_rules {
    threshold_percent = 0.8
    spend_basis       = "CURRENT_SPEND"
  }

  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "CURRENT_SPEND"
  }

  threshold_rules {
    threshold_percent = 0.8
    spend_basis       = "FORECASTED_SPEND"
  }

  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  all_updates_rule {
    monitoring_notification_channels = [
      for channel in google_monitoring_notification_channel.budget_email : channel.id
    ]
    disable_default_iam_recipients = false
  }
}

resource "google_storage_bucket" "support_storage" {
  count = var.enable_support_storage ? 1 : 0

  name                        = "${var.name_prefix}-${var.project_id}"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = var.labels

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_service_account" "cloud_run_probe" {
  count = var.enable_cloud_run_probe ? 1 : 0

  account_id   = "${var.name_prefix}-probe"
  display_name = "Hermes Max bounded support probe"
}

resource "google_cloud_run_v2_service" "support_probe" {
  count = var.enable_cloud_run_probe ? 1 : 0

  name     = "${var.name_prefix}-probe"
  location = var.region
  labels   = var.labels

  template {
    service_account = google_service_account.cloud_run_probe[0].email
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }
}
