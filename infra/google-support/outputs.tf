output "google_budget_name" {
  description = "Google Cloud budget guard display name."
  value       = google_billing_budget.monthly_support_guard.display_name
}

output "support_storage_bucket" {
  description = "Support storage bucket name, when enabled."
  value       = var.enable_support_storage ? google_storage_bucket.support_storage[0].name : null
}

output "cloud_run_probe_uri" {
  description = "Bounded Cloud Run probe URI, when enabled."
  value       = var.enable_cloud_run_probe ? google_cloud_run_v2_service.support_probe[0].uri : null
}
