"""Terraform outputs for deployed infrastructure."""

output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer"
  value       = aws_lb.burnlens.dns_name
}

output "alb_arn" {
  description = "ARN of the Application Load Balancer"
  value       = aws_lb.burnlens.arn
}

output "rds_endpoint" {
  description = "RDS cluster endpoint for connections"
  value       = aws_rds_cluster.burnlens.endpoint
}

output "rds_reader_endpoint" {
  description = "RDS read-only replica endpoint"
  value       = aws_rds_cluster.burnlens.reader_endpoint
}

output "s3_bucket_name" {
  description = "S3 bucket for cost export archives"
  value       = aws_s3_bucket.exports.id
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.burnlens.name
}

output "ecs_service_name" {
  description = "ECS service name"
  value       = aws_ecs_service.burnlens.name
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group for ECS logs"
  value       = aws_cloudwatch_log_group.ecs.name
}

output "next_steps" {
  description = "Post-deployment configuration steps"
  value       = <<-EOT
    1. Create HTTPS listener on ALB (requires ACM certificate for ${var.domain})
    2. Update Route53 record to point ${var.domain} → ${aws_lb.burnlens.dns_name}
    3. Connect first OSS proxy: burnlens start --cloud-endpoint https://${var.domain}
    4. Monitor: CloudWatch Logs → /ecs/burnlens-${var.customer_name}
  EOT
}
