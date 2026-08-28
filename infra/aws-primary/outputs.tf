output "aws_budget_name" {
  description = "AWS budget guard name."
  value       = aws_budgets_budget.monthly_actual_and_forecast.name
}

output "storage_bucket_names" {
  description = "Private S3 bucket names, when storage is enabled."
  value       = { for key, bucket in aws_s3_bucket.private_storage : key => bucket.bucket }
}

output "gateway_public_ip" {
  description = "Ephemeral public IP for the Hermes host, when compute is enabled."
  value       = var.enable_ec2_compute ? aws_instance.hermes_gateway[0].public_ip : null
}

output "gateway_instance_id" {
  description = "EC2 instance id for SSM access, when compute is enabled."
  value       = var.enable_ec2_compute ? aws_instance.hermes_gateway[0].id : null
}

output "artifact_bucket" {
  description = "Private artifact bucket used to stage checksummed Hermes releases."
  value       = var.enable_storage ? aws_s3_bucket.private_storage["artifacts"].bucket : null
}
